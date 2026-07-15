<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import {
  hrApi,
  type ApplicationDto,
  type InterviewResult,
  type InterviewStage,
  type InterviewStageDto,
} from '../services/hrApi'
import { authSession } from '../services/auth'

const applications = ref<ApplicationDto[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const departmentId = ref<number | null>(null)
const requisitionId = ref<number | null>(null)
const editingApplicationId = ref<number | null>(null)
const editingStage = ref<InterviewStage | null>(null)
const form = reactive({
  interview_at: '',
  interview_result: 'pending' as InterviewResult,
  interview_notes: '',
})

const resultLabels: Record<InterviewResult, string> = {
  pending: '待面試／待結果',
  advance: '進入下一階段',
  hold: '保留',
  rejected: '未通過',
  offered: '已發 Offer',
  hired: '錄取',
  no_show: '未到場',
  cancelled: '取消',
}
const interviewStages: Array<{ key: InterviewStage; title: string; owner: string; notesLabel: string; placeholder: string }> = [
  { key: 'hr', title: '第一關｜HR 初談', owner: 'HR', notesLabel: 'HR 建議／意見', placeholder: '請記錄溝通能力、動機、薪資期待、到職日與是否建議進入第二關…' },
  { key: 'manager', title: '第二關｜部門主管複試', owner: '部門主管', notesLabel: '主管面試意見', placeholder: '請記錄專業能力、團隊適配、風險、錄用建議與後續安排…' },
]
const applicationStatusLabels: Record<string, string> = {
  submitted: '已投遞',
  screening: '履歷審查',
  interview: '面試中',
  interviewing: '面試中',
  offered: '已發 Offer',
  hired: '已錄取',
  rejected: '未錄取',
  withdrawn: '已撤回',
}

function stageData(application: ApplicationDto, stage: InterviewStage): InterviewStageDto {
  return stage === 'hr' ? application.hr_interview : application.manager_interview
}

function canEditStage(stage: InterviewStage) {
  const role = authSession.state.user?.role
  return role === 'admin' || (stage === 'hr' ? role === 'hr' : role === 'manager')
}

function firstScheduledAt(application: ApplicationDto) {
  const values = [application.hr_interview.interview_at, application.manager_interview.interview_at]
    .filter((value): value is string => Boolean(value))
    .map(value => new Date(value).getTime())
  return values.length ? Math.min(...values) : null
}

const departments = computed(() => {
  const values = new Map<number, string>()
  applications.value.forEach(application => {
    const requisition = application.requisition
    if (requisition.department_id !== null) {
      values.set(requisition.department_id, requisition.department_name || `部門 #${requisition.department_id}`)
    }
  })
  return Array.from(values, ([id, name]) => ({ id, name })).sort((left, right) => left.name.localeCompare(right.name, 'zh-TW'))
})

const requisitions = computed(() => {
  const values = new Map<number, ApplicationDto['requisition']>()
  applications.value.forEach(application => {
    const requisition = application.requisition
    if (departmentId.value === null || requisition.department_id === departmentId.value) values.set(requisition.id, requisition)
  })
  return Array.from(values.values()).sort((left, right) => left.req_no.localeCompare(right.req_no, 'zh-TW'))
})

const filteredApplications = computed(() => applications.value
  .filter(application => departmentId.value === null || application.requisition.department_id === departmentId.value)
  .filter(application => requisitionId.value === null || application.requisition_id === requisitionId.value)
  .sort((left, right) => {
    const leftAt = firstScheduledAt(left)
    const rightAt = firstScheduledAt(right)
    if (leftAt !== null && rightAt !== null) return leftAt - rightAt
    if (leftAt !== null) return -1
    if (rightAt !== null) return 1
    return new Date(right.applied_at).getTime() - new Date(left.applied_at).getTime()
  }))

const scheduledCount = computed(() => applications.value.filter(application => (
  application.hr_interview.interview_at || application.manager_interview.interview_at
)).length)
const upcomingCount = computed(() => applications.value.filter(application =>
  [application.hr_interview, application.manager_interview].some(stage => (
    stage.interview_at
    && new Date(stage.interview_at).getTime() >= Date.now()
    && !['cancelled', 'no_show'].includes(stage.interview_result || '')
  )),
).length)
const completedCount = computed(() => applications.value.filter(application =>
  [application.hr_interview, application.manager_interview].some(stage => (
    stage.interview_result && stage.interview_result !== 'pending'
  )),
).length)

async function load() {
  loading.value = true
  error.value = ''
  try {
    applications.value = (await hrApi.applications()).data
    if (departmentId.value !== null && !departments.value.some(department => department.id === departmentId.value)) {
      departmentId.value = null
    }
    if (requisitionId.value !== null && !requisitions.value.some(requisition => requisition.id === requisitionId.value)) {
      requisitionId.value = null
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法載入面試安排'
  } finally {
    loading.value = false
  }
}

function toLocalDateTime(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function openEditor(application: ApplicationDto, stage: InterviewStage) {
  if (!canEditStage(stage)) return
  const interview = stageData(application, stage)
  editingApplicationId.value = application.id
  editingStage.value = stage
  form.interview_at = toLocalDateTime(interview.interview_at)
  form.interview_result = interview.interview_result || 'pending'
  form.interview_notes = interview.interview_notes || ''
  error.value = ''
  notice.value = ''
}

function closeEditor() {
  if (saving.value) return
  editingApplicationId.value = null
  editingStage.value = null
}

async function saveInterview(application: ApplicationDto) {
  if (editingStage.value === null || !canEditStage(editingStage.value)) {
    error.value = '目前帳號沒有編輯這一關面試的權限'
    return
  }
  if (!form.interview_at) {
    error.value = '請選擇面試日期與時間'
    return
  }
  const interviewDate = new Date(form.interview_at)
  if (Number.isNaN(interviewDate.getTime())) {
    error.value = '面試日期或時間格式不正確'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const stage = editingStage.value
    const updated = (await hrApi.updateApplicationInterviewStage(application.id, stage, {
      interview_at: interviewDate.toISOString(),
      interview_result: form.interview_result,
      interview_notes: form.interview_notes.trim() || null,
    })).data
    const index = applications.value.findIndex(item => item.id === updated.id)
    if (index >= 0) applications.value[index] = updated
    editingApplicationId.value = null
    editingStage.value = null
    const stageTitle = interviewStages.find(item => item.key === stage)?.title || '面試'
    notice.value = `已更新 ${updated.candidate.name} 的${stageTitle}紀錄`
    window.setTimeout(() => {
      if (notice.value === `已更新 ${updated.candidate.name} 的${stageTitle}紀錄`) notice.value = ''
    }, 3500)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法儲存面試安排'
  } finally {
    saving.value = false
  }
}

function formatDate(value: string | null) {
  if (!value) return '尚未安排'
  return new Intl.DateTimeFormat('zh-TW', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

watch(departmentId, () => {
  if (requisitionId.value !== null && !requisitions.value.some(requisition => requisition.id === requisitionId.value)) {
    requisitionId.value = null
  }
})

onMounted(load)
</script>

<template>
  <section class="interview-page" data-testid="interview-management">
    <header class="interview-hero">
      <div><p>INTERVIEW SCHEDULE</p><h1>面試安排</h1><span>集中查看應徵者、安排面試時間並記錄結果；主管只會看到自己部門的資料。</span></div>
      <button class="button secondary" data-testid="interviews-refresh" :disabled="loading" @click="load">{{ loading ? '同步中…' : '重新同步' }}</button>
    </header>

    <div v-if="error" class="interview-alert error" role="alert" data-testid="interview-error"><strong>!</strong><span>{{ error }}</span><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>
    <div v-if="notice" class="interview-alert success" role="status" data-testid="interview-success"><strong>✓</strong><span>{{ notice }}</span><button aria-label="關閉成功訊息" @click="notice = ''">×</button></div>

    <div class="interview-metrics">
      <article><small>應徵紀錄</small><strong>{{ applications.length }}</strong><span>目前權限範圍</span></article>
      <article><small>已安排面試</small><strong>{{ scheduledCount }}</strong><span>已有日期與時間</span></article>
      <article><small>即將面試</small><strong>{{ upcomingCount }}</strong><span>時間尚未到且未取消</span></article>
      <article><small>已有結果</small><strong>{{ completedCount }}</strong><span>不含待面試／待結果</span></article>
    </div>

    <div class="interview-filters">
      <div><strong>篩選面試名單</strong><span>可依部門與職缺縮小範圍</span></div>
      <label>部門<select v-model="departmentId" data-testid="interview-department-filter"><option :value="null">全部部門</option><option v-for="department in departments" :key="department.id" :value="department.id">{{ department.name }}</option></select></label>
      <label>職缺<select v-model="requisitionId" data-testid="interview-job-filter"><option :value="null">全部職缺</option><option v-for="requisition in requisitions" :key="requisition.id" :value="requisition.id">{{ requisition.req_no }} · {{ requisition.title }}</option></select></label>
      <em>{{ filteredApplications.length }} 筆</em>
    </div>

    <div v-if="loading && !applications.length" class="interview-empty panel"><span class="spinner"></span><strong>正在載入應徵與面試資料…</strong></div>
    <div v-else-if="filteredApplications.length" class="interview-list">
      <article v-for="application in filteredApplications" :key="application.id" class="interview-card panel" :data-testid="`interview-application-${application.id}`">
        <header>
          <div class="candidate-identity"><span>{{ application.candidate.name.slice(0, 1) }}</span><div><h2>{{ application.candidate.name }}</h2><p>{{ application.candidate.code }} · {{ application.candidate.current_title || '尚未填寫職稱' }}</p></div></div>
          <span class="application-status" :data-status="application.status">{{ applicationStatusLabels[application.status] || application.status }}</span>
        </header>

        <div class="application-job"><small>{{ application.requisition.department_name || `部門 #${application.requisition.department_id || '—'}` }}</small><strong>{{ application.requisition.req_no }} · {{ application.requisition.title }}</strong><span>{{ application.requisition.work_city }} · 應徵於 {{ formatDate(application.applied_at) }}</span></div>

        <div class="application-details">
          <div><small>Email</small><strong>{{ application.candidate.email || '未提供' }}</strong></div>
          <div><small>電話</small><strong>{{ application.candidate.phone || '未提供' }}</strong></div>
          <div><small>應徵來源</small><strong>{{ application.source || '未提供' }}</strong></div>
          <div><small>兩關進度</small><strong>HR：{{ resultLabels[application.hr_interview.interview_result || 'pending'] }}／主管：{{ resultLabels[application.manager_interview.interview_result || 'pending'] }}</strong></div>
        </div>

        <div class="stage-grid">
          <section v-for="stage in interviewStages" :key="stage.key" class="interview-stage" :class="{ unscheduled: !stageData(application, stage.key).interview_at }" :data-testid="`interview-stage-${application.id}-${stage.key}`">
            <header><div><small>{{ stage.owner }} OWNED</small><h3>{{ stage.title }}</h3></div><span>{{ resultLabels[stageData(application, stage.key).interview_result || 'pending'] }}</span></header>
            <div class="stage-content">
              <small>面試日期與時間</small>
              <strong>{{ formatDate(stageData(application, stage.key).interview_at) }}</strong>
              <small>{{ stage.notesLabel }}</small>
              <p>{{ stageData(application, stage.key).interview_notes || '尚未填寫意見。' }}</p>
              <small v-if="stageData(application, stage.key).updated_at">最後更新：{{ formatDate(stageData(application, stage.key).updated_at) }}</small>
            </div>
            <footer>
              <span v-if="!canEditStage(stage.key)">僅供檢視，由{{ stage.owner }}維護</span>
              <button v-else class="button secondary" type="button" :data-testid="`interview-edit-${application.id}-${stage.key}`" @click="openEditor(application, stage.key)">{{ stageData(application, stage.key).interview_at ? '編輯紀錄' : '安排並註記' }}</button>
            </footer>

            <form v-if="editingApplicationId === application.id && editingStage === stage.key" class="interview-editor" :data-testid="`interview-form-${application.id}-${stage.key}`" @submit.prevent="saveInterview(application)">
              <header><div><small>INTERVIEW DETAILS</small><h3>{{ application.candidate.name }}｜{{ stage.title }}</h3></div><button type="button" :disabled="saving" aria-label="關閉面試編輯" @click="closeEditor">×</button></header>
              <div class="editor-grid">
                <label>面試日期與時間 *<input v-model="form.interview_at" data-testid="interview-at-input" type="datetime-local" required></label>
                <label>面試結果<select v-model="form.interview_result" data-testid="interview-result-select"><option v-for="(label, value) in resultLabels" :key="value" :value="value">{{ label }}</option></select></label>
                <label class="wide">{{ stage.notesLabel }}<textarea v-model="form.interview_notes" data-testid="interview-notes" rows="6" maxlength="3000" :placeholder="stage.placeholder"></textarea></label>
              </div>
              <footer><span>這一關的意見會獨立保存，不會覆蓋另一關紀錄。</span><div><button class="button secondary" type="button" :disabled="saving" @click="closeEditor">取消</button><button class="button primary" data-testid="interview-save" type="submit" :disabled="saving">{{ saving ? '儲存中…' : '儲存這一關紀錄' }}</button></div></footer>
            </form>
          </section>
        </div>
      </article>
    </div>
    <div v-else class="interview-empty panel"><strong>目前沒有符合條件的應徵者</strong><p>請調整部門／職缺篩選；HR 建立人才與應徵關聯後，也會顯示在這裡。</p></div>
  </section>
</template>

<style scoped>
.interview-page{display:grid;gap:14px}.interview-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:25px 28px;border-radius:18px;background:linear-gradient(120deg,#153f3b,#17695f 62%,#74ad91);color:#fff;box-shadow:0 16px 38px rgba(20,74,68,.14)}.interview-hero p{margin:0;color:#f2c96d;font-size:8px;font-weight:800;letter-spacing:1.3px}.interview-hero h1{margin:6px 0;font-size:25px}.interview-hero span{font-size:10px;color:rgba(255,255,255,.76)}.interview-hero .button{background:rgba(255,255,255,.95)}.interview-alert{display:flex;align-items:center;gap:10px;padding:11px 14px;border:1px solid;border-radius:10px;font-size:9px}.interview-alert>strong{width:22px;height:22px;border-radius:50%;display:grid;place-items:center}.interview-alert>span{flex:1}.interview-alert>button{border:0;background:transparent;color:inherit;font-size:18px}.interview-alert.error{border-color:#efd0cd;background:#fff0ef;color:#893d39}.interview-alert.error>strong{background:#e5b0ac}.interview-alert.success{border-color:#baddc3;background:#ecf8ef;color:#286547}.interview-alert.success>strong{background:#cbe8d2}.interview-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.interview-metrics article{padding:16px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-metrics small,.interview-metrics span{display:block;color:var(--muted);font-size:8px}.interview-metrics strong{display:block;margin:4px 0;color:#185e56;font-size:23px}.interview-filters{display:flex;align-items:end;gap:12px;padding:13px 15px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-filters>div{margin-right:auto}.interview-filters>div strong,.interview-filters>div span{display:block}.interview-filters>div strong{font-size:11px}.interview-filters>div span{margin-top:3px;color:var(--muted);font-size:8px}.interview-filters label{display:grid;gap:5px;color:#61756f;font-size:8px}.interview-filters select{width:210px;height:37px;padding:0 10px;border:1px solid #d8e3df;border-radius:8px;background:#fff;color:#31534d;font-size:9px}.interview-filters em{padding-bottom:10px;color:var(--muted);font-size:8px;font-style:normal}.interview-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.interview-card{min-width:0;padding:16px}.interview-card>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.candidate-identity{display:flex;align-items:center;gap:10px;min-width:0}.candidate-identity>span{width:40px;height:40px;flex:0 0 auto;border-radius:50%;display:grid;place-items:center;background:#dceee8;color:#1f6b61;font-weight:800}.candidate-identity h2{margin:0;font-size:13px}.candidate-identity p{margin:3px 0 0;color:var(--muted);font-size:8px}.application-status{padding:4px 8px;border-radius:99px;background:#edf2f0;color:#60736e;font-size:8px;white-space:nowrap}.application-status[data-status="interview"],.application-status[data-status="interviewing"]{background:#e3eff9;color:#326f9d}.application-status[data-status="offered"],.application-status[data-status="hired"]{background:#e1f2e9;color:#27725b}.application-status[data-status="rejected"],.application-status[data-status="withdrawn"]{background:#f8e7e5;color:#a64b46}.application-job{display:grid;gap:3px;margin:14px 0;padding:11px;border-radius:9px;background:#f3f8f6}.application-job small{color:#2c786c;font-size:8px;font-weight:700}.application-job strong{font-size:10px}.application-job span{color:var(--muted);font-size:8px}.application-details{display:grid;grid-template-columns:1fr 1fr;gap:7px}.application-details>div{min-width:0;padding:8px;border:1px solid #e8eeec;border-radius:7px}.application-details small,.application-details strong{display:block;font-size:7px}.application-details small{color:var(--muted)}.application-details strong{margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:8px}.schedule-summary{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:11px;padding:11px 12px;border:1px solid #cde5dc;border-radius:9px;background:#f0f9f5}.schedule-summary.unscheduled{border-style:dashed;background:#fafcfb}.schedule-summary>div{min-width:0}.schedule-summary small,.schedule-summary strong{display:block}.schedule-summary small{color:var(--muted);font-size:7px}.schedule-summary strong{margin-top:3px;color:#245f56;font-size:10px}.schedule-summary p{margin:4px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#71847f;font-size:8px}.schedule-summary .button{flex:0 0 auto}.interview-editor{margin-top:12px;border:1px solid #bcdcd2;border-radius:11px;background:#fbfdfc;overflow:hidden}.interview-editor>header{display:flex;align-items:flex-start;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #dce9e5}.interview-editor>header small{color:#b37c20;font-size:7px;font-weight:800;letter-spacing:1px}.interview-editor>header h3{margin:3px 0 0;font-size:11px}.interview-editor>header button{border:0;background:transparent;color:#61736f;font-size:19px}.editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}.editor-grid label{display:grid;gap:5px;color:#536e68;font-size:8px}.editor-grid .wide{grid-column:1/-1}.editor-grid input,.editor-grid select,.editor-grid textarea{width:100%;padding:9px 10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit}.editor-grid textarea{resize:vertical;line-height:1.6}.interview-editor>footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 14px;border-top:1px solid #dce9e5;background:#f5f9f7}.interview-editor>footer>span{color:var(--muted);font-size:7px}.interview-editor>footer>div{display:flex;gap:7px}.interview-empty{text-align:center;padding:60px 20px;color:var(--muted)}.interview-empty strong,.interview-empty p{display:block}.interview-empty strong{font-size:11px}.interview-empty p{font-size:8px}.interview-empty .spinner{margin-bottom:12px}
.stage-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:11px}.interview-stage{min-width:0;border:1px solid #cde5dc;border-radius:10px;background:#f0f9f5;overflow:hidden}.interview-stage.unscheduled{border-style:dashed;background:#fafcfb}.interview-stage>header{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;padding:10px 11px;border-bottom:1px solid #dce9e5}.interview-stage>header small{display:block;color:#b37c20;font-size:6px;font-weight:800;letter-spacing:.8px}.interview-stage>header h3{margin:3px 0 0;font-size:9px}.interview-stage>header>span{padding:3px 6px;border-radius:99px;background:#fff;color:#28675d;font-size:7px;white-space:nowrap}.stage-content{display:grid;gap:3px;padding:10px 11px}.stage-content small{margin-top:4px;color:var(--muted);font-size:7px}.stage-content strong{color:#245f56;font-size:9px}.stage-content p{min-height:32px;margin:1px 0 0;color:#5f746f;font-size:8px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}.interview-stage>footer{display:flex;align-items:center;justify-content:flex-end;min-height:43px;padding:8px 10px;border-top:1px solid #dce9e5;background:rgba(255,255,255,.5)}.interview-stage>footer>span{margin-right:auto;color:var(--muted);font-size:7px}.interview-stage .interview-editor{margin:0;border-width:1px 0 0;border-radius:0}.interview-stage .interview-editor>footer{min-height:0;background:#f5f9f7}
@media(max-width:1120px){.interview-list{grid-template-columns:1fr}.interview-filters{align-items:stretch;flex-wrap:wrap}.interview-filters>div{flex-basis:100%}.interview-filters label{flex:1}.interview-filters select{width:100%}}
@media(max-width:680px){.interview-hero{align-items:flex-start;flex-direction:column}.interview-metrics,.stage-grid{grid-template-columns:1fr}.interview-filters label{flex-basis:100%}.application-details,.editor-grid{grid-template-columns:1fr}.editor-grid .wide{grid-column:auto}.schedule-summary,.interview-editor>footer{align-items:flex-start;flex-direction:column}.interview-editor>footer>div{width:100%}.interview-editor>footer .button{flex:1}}
</style>
