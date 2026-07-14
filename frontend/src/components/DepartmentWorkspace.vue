<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  hrApi,
  type DepartmentJobDto,
  type DepartmentRequisitionWrite,
  type DepartmentWorkspaceDto,
} from '../services/hrApi'

const workspace = ref<DepartmentWorkspaceDto | null>(null)
const selectedJobId = ref<number | null>(null)
const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const error = ref('')
const notice = ref('')
const form = reactive({
  title: '', employment_type: 'full_time', work_city: '台北市', headcount: 1,
  salary_min: null as number | null, salary_max: null as number | null,
  skillsText: '', summary: '', jd: '',
})

const selectedJob = computed<DepartmentJobDto | null>(() =>
  workspace.value?.jobs.find(item => item.requisition.id === selectedJobId.value) || null,
)

const jobStatusLabels: Record<string, string> = {
  draft: '草稿', submitted: '待核准', approved: '已核准', sourcing: '招募中',
  interviewing: '面試中', filled: '已補足', closed: '已關閉',
}
const applicationStatusLabels: Record<string, string> = {
  submitted: '已投遞', screening: '履歷審查', interview: '面試中', offered: '已發 Offer',
  hired: '已錄取', rejected: '未錄取', withdrawn: '已撤回',
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    workspace.value = (await hrApi.departmentWorkspace()).data
    const jobs = workspace.value.jobs
    if (!jobs.some(item => item.requisition.id === selectedJobId.value)) {
      selectedJobId.value = jobs[0]?.requisition.id || null
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法載入部門工作台'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    title: '', employment_type: 'full_time', work_city: '台北市', headcount: 1,
    salary_min: null, salary_max: null, skillsText: '', summary: '', jd: '',
  })
  error.value = ''
  notice.value = ''
  creating.value = true
}

async function createJob() {
  if (!form.title.trim() || !form.work_city.trim() || !form.jd.trim()) {
    error.value = '職缺名稱、工作地點與職務說明為必填'
    return
  }
  if (form.salary_min !== null && form.salary_max !== null && form.salary_max < form.salary_min) {
    error.value = '月薪上限不可低於月薪下限'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const payload: DepartmentRequisitionWrite = {
      title: form.title.trim(),
      employment_type: form.employment_type,
      work_city: form.work_city.trim(),
      jd: form.jd.trim(),
      summary: form.summary.trim() || null,
      skills: form.skillsText.split(/[,，\n]/).map(item => item.trim()).filter(Boolean),
      salary_min: form.salary_min,
      salary_max: form.salary_max,
      salary_type: 'monthly',
      headcount: form.headcount,
    }
    const created = (await hrApi.createDepartmentRequisition(payload)).data
    await load()
    selectedJobId.value = created.id
    creating.value = false
    notice.value = `${created.req_no} 已寫入資料庫並送交 HR 核准`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法建立職缺'
  } finally {
    saving.value = false
  }
}

function date(value: string) {
  return new Intl.DateTimeFormat('zh-TW', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

onMounted(load)
</script>

<template>
  <section class="department-page">
    <header class="department-hero">
      <div><p>DEPARTMENT WORKSPACE</p><h1>{{ workspace?.department_name || '部門後台' }}</h1><span>建立本部門職缺，並查看實際投遞這些職缺的人才資料。</span></div>
      <div class="department-hero-actions"><button class="button secondary" :disabled="loading" @click="load">{{ loading ? '同步中…' : '重新同步' }}</button><button class="button create-button" @click="openCreate">＋ 建立本部門職缺</button></div>
    </header>

    <div v-if="error" class="alert error-alert" role="alert"><span>!</span><p>{{ error }}</p><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>
    <div v-if="notice" class="department-success" role="status"><strong>✓ 建立完成</strong><span>{{ notice }}</span><button aria-label="關閉成功訊息" @click="notice = ''">×</button></div>
    <div class="scope-notice"><strong>部門資料隔離已啟用</strong><span>新職缺由後端自動綁定登入帳號的 department_id，寫入 job_requisitions 後送交 HR 核准；前端無法指定其他部門。</span></div>

    <div class="department-metrics">
      <article><small>所屬部門</small><strong>{{ workspace?.department_name || '—' }}</strong><span>部門 ID #{{ workspace?.department_id || '—' }}</span></article>
      <article><small>部門職缺</small><strong>{{ workspace?.total_jobs ?? 0 }}</strong><span>包含各流程狀態</span></article>
      <article><small>應徵紀錄</small><strong>{{ workspace?.total_applications ?? 0 }}</strong><span>僅計算實際投遞</span></article>
      <article><small>應徵人才</small><strong>{{ workspace?.total_candidates ?? 0 }}</strong><span>跨職缺人才不重複計算</span></article>
    </div>

    <div v-if="loading && !workspace" class="department-empty panel"><span class="spinner"></span><strong>正在確認部門權限與資料範圍…</strong></div>
    <div v-else-if="workspace" class="department-workspace panel">
      <aside class="department-jobs">
        <header><strong>本部門職缺</strong><small>選擇職缺查看應徵者</small></header>
        <button v-for="item in workspace.jobs" :key="item.requisition.id" :class="{ active: selectedJobId === item.requisition.id }" @click="selectedJobId = item.requisition.id">
          <span><b>{{ item.requisition.title }}</b><small>{{ item.requisition.req_no }}</small></span><em>{{ item.applicants.length }} 人</em>
        </button>
        <p v-if="!workspace.jobs.length">目前沒有本部門職缺，請點選上方按鈕建立。</p>
      </aside>

      <main class="department-applicants">
        <template v-if="selectedJob">
          <header class="selected-job">
            <div><span class="status" :data-status="selectedJob.requisition.status">{{ jobStatusLabels[selectedJob.requisition.status] || selectedJob.requisition.status }}</span><h2>{{ selectedJob.requisition.title }}</h2><p>{{ selectedJob.requisition.req_no }} · {{ selectedJob.requisition.work_city }} · 需求 {{ selectedJob.requisition.headcount }} 人</p></div>
            <strong>{{ selectedJob.applicants.length }}<small>位應徵者</small></strong>
          </header>
          <div v-if="selectedJob.applicants.length" class="applicant-list">
            <article v-for="item in selectedJob.applicants" :key="item.application_id">
              <header><div class="applicant-identity"><span>{{ item.candidate.name.slice(0, 1) }}</span><div><h3>{{ item.candidate.name }}</h3><p>{{ item.candidate.code }} · {{ item.candidate.current_title || '尚未填寫職稱' }}</p></div></div><div class="match-score" :class="{ pending: item.match_score === null }"><strong>{{ item.match_score === null ? '—' : item.match_score.toFixed(1) }}<b v-if="item.match_score !== null">%</b></strong><small>{{ item.match_score === null ? '尚未媒合' : '媒合程度' }}</small></div></header>
              <div class="applicant-details"><span><small>Email</small><strong>{{ item.candidate.email || '未提供' }}</strong></span><span><small>電話</small><strong>{{ item.candidate.phone || '未提供' }}</strong></span><span><small>地區／年資</small><strong>{{ item.candidate.city || '未填' }} · {{ item.candidate.total_years ?? 0 }} 年</strong></span><span><small>應徵狀態</small><strong>{{ applicationStatusLabels[item.application_status] || item.application_status }}</strong></span></div>
              <footer><span>應徵來源：{{ item.application_source }}</span><span>投遞時間：{{ date(item.applied_at) }}</span><span>Application #{{ item.application_id }}</span></footer>
            </article>
          </div>
          <div v-else class="department-empty"><strong>這項職缺目前沒有應徵者</strong><p>只有完成投遞並寫入 job_applications 的人才才會出現在這裡。</p></div>
        </template>
        <div v-else class="department-empty"><strong>目前沒有可檢視的部門職缺</strong><p>點選「建立本部門職缺」，送出後會立即顯示在這裡。</p><button class="button primary" @click="openCreate">＋ 建立第一筆職缺</button></div>
      </main>
    </div>

    <div v-if="creating" class="department-dialog-backdrop" @click.self="creating = false">
      <form class="department-dialog" role="dialog" aria-modal="true" aria-labelledby="department-job-title" @submit.prevent="createJob">
        <header><div><small>NEW REQUISITION</small><h2 id="department-job-title">建立本部門職缺</h2><p>送出後會寫入資料庫，狀態為「待核准」，HR 可在全公司職缺管理中檢視與核准。</p></div><button type="button" aria-label="關閉新增職缺視窗" @click="creating = false">×</button></header>
        <div class="department-form-grid">
          <label>職缺名稱 *<input v-model="form.title" maxlength="100" required placeholder="例如：資深產品設計師"></label>
          <label>工作地點 *<input v-model="form.work_city" maxlength="50" required placeholder="例如：台北市"></label>
          <label>聘僱類型<select v-model="form.employment_type"><option value="full_time">正職</option><option value="contract">約聘</option><option value="part_time">兼職</option></select></label>
          <label>需求人數<input v-model.number="form.headcount" type="number" min="1" required></label>
          <label>月薪下限<input v-model.number="form.salary_min" type="number" min="0" placeholder="可留白"></label>
          <label>月薪上限<input v-model.number="form.salary_max" type="number" min="0" placeholder="可留白"></label>
          <label class="wide">技能條件<input v-model="form.skillsText" placeholder="以逗號分隔，例如：Figma、使用者研究"></label>
          <label class="wide">職缺摘要<textarea v-model="form.summary" maxlength="500" rows="2" placeholder="簡短說明職缺目標"></textarea></label>
          <label class="wide">職務說明 *<textarea v-model="form.jd" rows="6" required placeholder="工作內容、必要條件及加分條件"></textarea></label>
        </div>
        <footer><span>部門：{{ workspace?.department_name }}（由系統鎖定）</span><div><button type="button" class="button secondary" :disabled="saving" @click="creating = false">取消</button><button type="submit" class="button primary" :disabled="saving">{{ saving ? '寫入中…' : '建立並送交 HR' }}</button></div></footer>
      </form>
    </div>
  </section>
</template>

<style scoped>
.department-page{display:grid;gap:14px}.department-hero{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:25px 28px;border-radius:18px;background:linear-gradient(120deg,#123e3a,#176a60 62%,#6cae8f);color:#fff;box-shadow:0 16px 38px rgba(20,74,68,.15)}.department-hero p{margin:0;color:#f1cb77;font-size:8px;font-weight:800;letter-spacing:1.3px}.department-hero h1{margin:6px 0;font-size:25px}.department-hero span{font-size:10px;color:rgba(255,255,255,.75)}.department-hero-actions{display:flex;gap:8px}.department-hero .button{background:rgba(255,255,255,.94)}.department-hero .create-button{background:#f2bb52;color:#173f3a}.department-success,.scope-notice{display:flex;align-items:center;gap:12px;padding:12px 15px;border:1px solid #cfe4dc;border-radius:10px;background:#eff8f4;color:#32635b}.department-success{background:#ecf8ef;border-color:#baddc3}.department-success strong,.scope-notice strong{font-size:10px;white-space:nowrap}.department-success span,.scope-notice span{font-size:9px;line-height:1.6}.department-success button{margin-left:auto;border:0;background:transparent;color:inherit;font-size:16px}.department-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.department-metrics article{padding:16px;border:1px solid var(--line);border-radius:12px;background:#fff}.department-metrics small,.department-metrics span{display:block;color:var(--muted);font-size:8px}.department-metrics strong{display:block;margin:5px 0;font-size:20px;color:#174f49}.department-metrics article:first-child strong{font-size:13px}.department-workspace{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:520px;overflow:hidden}.department-jobs{padding:12px;border-right:1px solid var(--line);background:#f8faf9}.department-jobs>header{padding:9px 8px 13px}.department-jobs>header strong,.department-jobs>header small{display:block}.department-jobs>header strong{font-size:12px}.department-jobs>header small{margin-top:3px;color:var(--muted);font-size:8px}.department-jobs>button{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;margin-bottom:5px;padding:12px;border:0;border-radius:9px;background:transparent;text-align:left;color:inherit}.department-jobs>button:hover,.department-jobs>button.active{background:#e2f0ec;color:#155b52}.department-jobs b,.department-jobs small{display:block}.department-jobs b{font-size:10px}.department-jobs small{margin-top:4px;color:var(--muted);font-size:8px}.department-jobs em{min-width:38px;padding:4px 7px;border-radius:99px;background:#fff;font-size:8px;font-style:normal;text-align:center}.department-jobs>p{padding:12px;color:var(--muted);font-size:9px}.department-applicants{min-width:0;padding:18px}.selected-job{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:4px 2px 18px;border-bottom:1px solid var(--line)}.selected-job h2{margin:8px 0 3px;font-size:19px}.selected-job p{margin:0;color:var(--muted);font-size:9px}.selected-job>strong{font-size:27px;color:#1d6c62;text-align:right}.selected-job>strong small{display:block;font-size:8px;color:var(--muted)}.applicant-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px;padding-top:15px}.applicant-list>article{padding:15px;border:1px solid #e0e9e6;border-radius:12px;background:#fff}.applicant-list>article>header{display:flex;justify-content:space-between;align-items:center}.applicant-identity{display:flex;align-items:center;gap:9px}.applicant-identity>span{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:#dceee8;color:#226960;font-weight:800}.applicant-identity h3{margin:0;font-size:12px}.applicant-identity p{margin:3px 0 0;color:var(--muted);font-size:8px}.match-score{text-align:right;color:#1d7468}.match-score.pending{color:#8a9995}.match-score strong,.match-score small{display:block}.match-score strong{font-size:21px}.match-score b{font-size:9px}.match-score small{font-size:7px}.applicant-details{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:13px 0}.applicant-details span{padding:8px;border-radius:7px;background:#f5f8f7;min-width:0}.applicant-details small,.applicant-details strong{display:block;font-size:7px}.applicant-details small{color:var(--muted)}.applicant-details strong{margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:8px}.applicant-list footer{display:flex;flex-wrap:wrap;gap:8px;padding-top:9px;border-top:1px solid #edf1f0;color:var(--muted);font-size:7px}.department-empty{text-align:center;padding:70px 20px;color:var(--muted)}.department-empty strong,.department-empty p{display:block}.department-empty strong{font-size:12px}.department-empty p{font-size:9px}.department-empty .button{display:inline-flex;margin-top:10px}.department-dialog-backdrop{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:24px;background:rgba(8,35,32,.55);backdrop-filter:blur(4px)}.department-dialog{width:min(780px,100%);max-height:calc(100vh - 48px);overflow:auto;border-radius:17px;background:#fff;box-shadow:0 28px 70px rgba(8,35,32,.3)}.department-dialog>header{display:flex;justify-content:space-between;gap:18px;padding:21px 24px;border-bottom:1px solid var(--line)}.department-dialog>header small{color:#b7801d;font-weight:800;letter-spacing:1px}.department-dialog>header h2{margin:4px 0;font-size:19px}.department-dialog>header p{margin:0;color:var(--muted);font-size:9px}.department-dialog>header button{align-self:flex-start;border:0;background:transparent;color:#61716e;font-size:23px}.department-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:21px 24px}.department-form-grid label{display:grid;gap:6px;color:#3c5c57;font-size:9px}.department-form-grid .wide{grid-column:1/-1}.department-form-grid input,.department-form-grid select,.department-form-grid textarea{width:100%;padding:11px 12px;border:1px solid #d6e2df;border-radius:8px;background:#fbfdfc;color:#153f3a;font:inherit;resize:vertical}.department-dialog>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 24px;border-top:1px solid var(--line);background:#f8faf9}.department-dialog>footer>span{color:var(--muted);font-size:8px}.department-dialog>footer>div{display:flex;gap:8px}@media(max-width:1050px){.department-workspace{grid-template-columns:1fr}.department-jobs{border-right:0;border-bottom:1px solid var(--line)}.applicant-list{grid-template-columns:1fr}}@media(max-width:720px){.department-hero,.scope-notice{align-items:flex-start;flex-direction:column}.department-hero-actions{width:100%;flex-wrap:wrap}.department-metrics{grid-template-columns:1fr 1fr}.department-applicants{padding:13px}.selected-job{align-items:flex-start}.applicant-details,.department-form-grid{grid-template-columns:1fr}.department-form-grid .wide{grid-column:auto}.department-dialog>footer{align-items:flex-start;flex-direction:column}}
</style>
