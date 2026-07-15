<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  hrApi,
  type DepartmentJobDto,
  type DepartmentRequisitionWrite,
  type DepartmentWorkspaceDto,
  type RequisitionDto,
} from '../services/hrApi'

const workspace = ref<DepartmentWorkspaceDto | null>(null)
const selectedJobId = ref<number | null>(null)
const editingJobId = ref<number | null>(null)
const loading = ref(false)
const saving = ref(false)
const dialogOpen = ref(false)
const error = ref('')
const notice = ref('')
const form = reactive({
  title: '',
  employment_type: 'full_time',
  work_city: '台北市',
  headcount: 1,
  salary_min: null as number | null,
  salary_max: null as number | null,
  salary_type: 'monthly',
  skillsText: '',
  summary: '',
  jd: '',
})

const selectedJob = computed<DepartmentJobDto | null>(() =>
  workspace.value?.jobs.find(item => item.requisition.id === selectedJobId.value) || null,
)
const editing = computed(() => editingJobId.value !== null)

const jobStatusLabels: Record<string, string> = {
  draft: '草稿',
  submitted: '待核准',
  approved: '已核准',
  sourcing: '招募中',
  interviewing: '面試中',
  filled: '已補足',
  closed: '已關閉',
}
const applicationStatusLabels: Record<string, string> = {
  submitted: '已投遞',
  screening: '履歷審查',
  interview: '面試中',
  offered: '已發 Offer',
  hired: '已錄取',
  rejected: '未錄取',
  withdrawn: '已撤回',
}
const candidateStatusLabels: Record<string, string> = {
  new: '新進人才',
  contacted: '已聯繫',
  priority: '優先聯繫',
  interviewing: '面試中',
  archived: '已封存',
}
const employmentTypeLabels: Record<string, string> = {
  full_time: '正職',
  contract: '約聘',
  part_time: '兼職',
  intern: '實習',
}
const salaryTypeLabels: Record<string, string> = {
  monthly: '月薪',
  annual: '年薪',
  hourly: '時薪',
  negotiable: '面議',
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

function resetForm(job?: RequisitionDto) {
  Object.assign(form, job ? {
    title: job.title,
    employment_type: job.employment_type,
    work_city: job.work_city,
    headcount: job.headcount,
    salary_min: job.salary_min,
    salary_max: job.salary_max,
    salary_type: job.salary_type || 'monthly',
    skillsText: (job.skills || []).join('、'),
    summary: job.summary || '',
    jd: job.jd,
  } : {
    title: '',
    employment_type: 'full_time',
    work_city: '台北市',
    headcount: 1,
    salary_min: null,
    salary_max: null,
    salary_type: 'monthly',
    skillsText: '',
    summary: '',
    jd: '',
  })
}

function openCreate() {
  editingJobId.value = null
  resetForm()
  error.value = ''
  notice.value = ''
  dialogOpen.value = true
}

function openEdit() {
  if (!selectedJob.value) return
  editingJobId.value = selectedJob.value.requisition.id
  resetForm(selectedJob.value.requisition)
  error.value = ''
  notice.value = ''
  dialogOpen.value = true
}

function closeDialog() {
  if (saving.value) return
  dialogOpen.value = false
  editingJobId.value = null
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function buildPayload(): DepartmentRequisitionWrite | null {
  if (!form.title.trim() || !form.work_city.trim() || !form.jd.trim()) {
    error.value = '職缺名稱、工作地點與職務說明為必填'
    return null
  }
  if (!Number.isInteger(form.headcount) || form.headcount < 1) {
    error.value = '需求人數至少為 1 人'
    return null
  }
  const salaryMin = nullableNumber(form.salary_min)
  const salaryMax = nullableNumber(form.salary_max)
  if (salaryMin !== null && salaryMax !== null && salaryMax < salaryMin) {
    error.value = '薪資上限不可低於薪資下限'
    return null
  }
  return {
    title: form.title.trim(),
    employment_type: form.employment_type,
    work_city: form.work_city.trim(),
    jd: form.jd.trim(),
    summary: form.summary.trim() || null,
    skills: form.skillsText.split(/[,，、\n]/).map(item => item.trim()).filter(Boolean),
    salary_min: salaryMin,
    salary_max: salaryMax,
    salary_type: form.salary_type,
    headcount: form.headcount,
  }
}

async function saveJob() {
  const payload = buildPayload()
  if (!payload) return
  const jobId = editingJobId.value
  saving.value = true
  error.value = ''
  try {
    const saved = jobId === null
      ? (await hrApi.createDepartmentRequisition(payload)).data
      : (await hrApi.updateDepartmentRequisition(jobId, payload)).data
    dialogOpen.value = false
    editingJobId.value = null
    await load()
    selectedJobId.value = saved.id
    notice.value = jobId === null
      ? `${saved.req_no} 已建立並送交 HR 核准`
      : `${saved.req_no} 的職缺細項已更新`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : editing.value ? '無法更新職缺' : '無法建立職缺'
  } finally {
    saving.value = false
  }
}

async function deleteJob() {
  if (!selectedJob.value) return
  const job = selectedJob.value
  const applicantWarning = job.applicants.length
    ? `\n\n此職缺已有 ${job.applicants.length} 位應徵者；系統會保護既有應徵紀錄並拒絕刪除。`
    : '\n\n刪除後無法復原。'
  if (!window.confirm(`確定刪除「${job.requisition.title}」？${applicantWarning}`)) return
  saving.value = true
  error.value = ''
  try {
    await hrApi.deleteDepartmentRequisition(job.requisition.id)
    selectedJobId.value = null
    await load()
    notice.value = `已刪除職缺 ${job.requisition.req_no}`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '無法刪除職缺'
  } finally {
    saving.value = false
  }
}

function salary(job: RequisitionDto) {
  const type = salaryTypeLabels[job.salary_type || ''] || job.salary_type || '薪資'
  if (job.salary_type === 'negotiable' || (job.salary_min === null && job.salary_max === null)) return `${type}／依公司規定`
  const format = (value: number) => new Intl.NumberFormat('zh-TW').format(value)
  if (job.salary_min !== null && job.salary_max !== null) return `${type} ${format(job.salary_min)}～${format(job.salary_max)}`
  if (job.salary_min !== null) return `${type} ${format(job.salary_min)} 起`
  return `${type} 最高 ${format(job.salary_max as number)}`
}

function date(value: string) {
  return new Intl.DateTimeFormat('zh-TW', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

onMounted(load)
</script>

<template>
  <section class="department-page">
    <header class="department-hero">
      <div>
        <p>DEPARTMENT WORKSPACE</p>
        <h1>{{ workspace?.department_name || '部門後台' }}</h1>
        <span>維護本部門職缺細項，並查看實際應徵這些職缺的人才資料。</span>
      </div>
      <div class="department-hero-actions">
        <button class="button secondary" :disabled="loading" @click="load">{{ loading ? '同步中…' : '重新同步' }}</button>
        <button class="button create-button" @click="openCreate">＋ 建立本部門職缺</button>
      </div>
    </header>

    <div v-if="error" class="alert error-alert" role="alert">
      <span>!</span><p>{{ error }}</p><button aria-label="關閉錯誤訊息" @click="error = ''">×</button>
    </div>
    <div v-if="notice" class="department-success" role="status">
      <strong>✓ 操作完成</strong><span>{{ notice }}</span><button aria-label="關閉成功訊息" @click="notice = ''">×</button>
    </div>
    <div class="scope-notice">
      <strong>部門資料隔離已啟用</strong>
      <span>主管只能新增、編輯與刪除自己的部門職缺；部門與建立者由後端依登入帳號鎖定。已有應徵者的職缺會保留，不允許刪除。</span>
    </div>

    <div class="department-metrics">
      <article><small>所屬部門</small><strong>{{ workspace?.department_name || '—' }}</strong><span>部門 ID #{{ workspace?.department_id || '—' }}</span></article>
      <article><small>部門職缺</small><strong>{{ workspace?.total_jobs ?? 0 }}</strong><span>包含各流程狀態</span></article>
      <article><small>應徵紀錄</small><strong>{{ workspace?.total_applications ?? 0 }}</strong><span>僅計算實際應徵關聯</span></article>
      <article><small>應徵人才</small><strong>{{ workspace?.total_candidates ?? 0 }}</strong><span>跨職缺人才不重複計算</span></article>
    </div>

    <div v-if="loading && !workspace" class="department-empty panel">
      <span class="spinner"></span><strong>正在確認部門權限與資料範圍…</strong>
    </div>
    <div v-else-if="workspace" class="department-workspace panel">
      <aside class="department-jobs">
        <header><strong>本部門職缺</strong><small>選擇職缺查看細項與應徵者</small></header>
        <button v-for="item in workspace.jobs" :key="item.requisition.id" :class="{ active: selectedJobId === item.requisition.id }" @click="selectedJobId = item.requisition.id">
          <span><b>{{ item.requisition.title }}</b><small>{{ item.requisition.req_no }}</small></span><em>{{ item.applicants.length }} 人</em>
        </button>
        <p v-if="!workspace.jobs.length">目前沒有本部門職缺，請點選上方按鈕建立。</p>
      </aside>

      <main class="department-main">
        <template v-if="selectedJob">
          <header class="selected-job">
            <div>
              <span class="status" :data-status="selectedJob.requisition.status">{{ jobStatusLabels[selectedJob.requisition.status] || selectedJob.requisition.status }}</span>
              <h2>{{ selectedJob.requisition.title }}</h2>
              <p>{{ selectedJob.requisition.req_no }} · 建立於 {{ date(selectedJob.requisition.created_at) }}</p>
            </div>
            <div class="selected-job-actions">
              <div><button class="button secondary" :disabled="saving" @click="openEdit">編輯細項</button><button class="button danger" :disabled="saving" @click="deleteJob">刪除職缺</button></div>
              <strong>{{ selectedJob.applicants.length }}<small>位應徵者</small></strong>
            </div>
          </header>

          <section class="job-details" aria-label="職缺完整說明">
            <div class="job-meta-grid">
              <article><small>聘僱型態</small><strong>{{ employmentTypeLabels[selectedJob.requisition.employment_type] || selectedJob.requisition.employment_type }}</strong></article>
              <article><small>工作地點</small><strong>{{ selectedJob.requisition.work_city }}</strong></article>
              <article><small>需求人數</small><strong>{{ selectedJob.requisition.headcount }} 人</strong></article>
              <article><small>薪資條件</small><strong>{{ salary(selectedJob.requisition) }}</strong></article>
            </div>
            <article class="job-copy">
              <small>職缺摘要</small>
              <p>{{ selectedJob.requisition.summary || '尚未填寫職缺摘要。' }}</p>
            </article>
            <article class="job-copy">
              <small>職務說明（JD）</small>
              <p class="job-description">{{ selectedJob.requisition.jd }}</p>
            </article>
            <article class="job-copy">
              <small>技能條件</small>
              <div v-if="selectedJob.requisition.skills?.length" class="job-skills"><span v-for="skill in selectedJob.requisition.skills" :key="skill">{{ skill }}</span></div>
              <p v-else>尚未設定技能條件。</p>
            </article>
            <div class="job-publish-note">
              <span>{{ selectedJob.requisition.published_at ? `發布時間：${date(selectedJob.requisition.published_at)}` : '尚未公開發布' }}</span>
              <span>資料庫職缺 ID #{{ selectedJob.requisition.id }}</span>
            </div>
          </section>

          <section class="applicants-section">
            <header><div><h3>應徵人員</h3><p>僅顯示已建立 job_applications 關聯的人才。</p></div><strong>{{ selectedJob.applicants.length }} 筆</strong></header>
            <div v-if="selectedJob.applicants.length" class="applicant-list">
              <article v-for="item in selectedJob.applicants" :key="item.application_id">
                <header>
                  <div class="applicant-identity"><span>{{ item.candidate.name.slice(0, 1) }}</span><div><h3>{{ item.candidate.name }}</h3><p>{{ item.candidate.code }} · {{ item.candidate.current_title || '尚未填寫職稱' }}</p></div></div>
                  <div class="match-score" :class="{ pending: item.match_score === null }"><strong>{{ item.match_score === null ? '—' : item.match_score.toFixed(1) }}<b v-if="item.match_score !== null">%</b></strong><small>{{ item.match_score === null ? '尚未媒合' : '媒合程度' }}</small></div>
                </header>
                <div class="applicant-details">
                  <span><small>Email</small><strong>{{ item.candidate.email || '未提供' }}</strong></span>
                  <span><small>電話</small><strong>{{ item.candidate.phone || '未提供' }}</strong></span>
                  <span><small>地區／年資</small><strong>{{ item.candidate.city || '未填' }} · {{ item.candidate.total_years ?? 0 }} 年</strong></span>
                  <span><small>應徵狀態</small><strong>{{ applicationStatusLabels[item.application_status] || item.application_status }}</strong></span>
                  <span><small>人才狀態</small><strong>{{ candidateStatusLabels[item.candidate.status] || item.candidate.status }}</strong></span>
                  <span><small>人才來源</small><strong>{{ item.candidate.source || '未提供' }}</strong></span>
                </div>
                <footer><span>應徵來源：{{ item.application_source }}</span><span>投遞時間：{{ date(item.applied_at) }}</span><span>Application #{{ item.application_id }}</span></footer>
              </article>
            </div>
            <div v-else class="department-empty"><strong>這項職缺目前沒有應徵者</strong><p>主管可至「履歷辨識中心」選擇此職缺並上傳履歷；確認入庫後，人才會自動顯示在這裡。</p></div>
          </section>
        </template>
        <div v-else class="department-empty"><strong>目前沒有可檢視的部門職缺</strong><p>點選「建立本部門職缺」，送出後會立即顯示在這裡。</p><button class="button primary" @click="openCreate">＋ 建立第一筆職缺</button></div>
      </main>
    </div>

    <div v-if="dialogOpen" class="department-dialog-backdrop" @click.self="closeDialog">
      <form class="department-dialog" role="dialog" aria-modal="true" aria-labelledby="department-job-title" @submit.prevent="saveJob">
        <header>
          <div><small>{{ editing ? 'EDIT REQUISITION' : 'NEW REQUISITION' }}</small><h2 id="department-job-title">{{ editing ? '編輯職缺細項' : '建立本部門職缺' }}</h2><p>{{ editing ? '儲存後會立即更新這筆部門職缺。' : '送出後會寫入資料庫並送交 HR 核准；部門由系統自動鎖定。' }}</p></div>
          <button type="button" :disabled="saving" aria-label="關閉職缺視窗" @click="closeDialog">×</button>
        </header>
        <div class="department-form-grid">
          <label>職缺名稱 *<input v-model="form.title" maxlength="100" required placeholder="例如：資深產品設計師"></label>
          <label>工作地點 *<input v-model="form.work_city" maxlength="50" required placeholder="例如：台北市"></label>
          <label>聘僱類型<select v-model="form.employment_type"><option value="full_time">正職</option><option value="contract">約聘</option><option value="part_time">兼職</option><option value="intern">實習</option></select></label>
          <label>需求人數<input v-model.number="form.headcount" type="number" min="1" step="1" required></label>
          <label>薪資型態<select v-model="form.salary_type"><option value="monthly">月薪</option><option value="annual">年薪</option><option value="hourly">時薪</option><option value="negotiable">面議</option></select></label>
          <span class="form-spacer" aria-hidden="true"></span>
          <label>薪資下限<input v-model.number="form.salary_min" type="number" min="0" placeholder="可留白"></label>
          <label>薪資上限<input v-model.number="form.salary_max" type="number" min="0" placeholder="可留白"></label>
          <label class="wide">技能條件<input v-model="form.skillsText" placeholder="以逗號分隔，例如：Figma、使用者研究"></label>
          <label class="wide">職缺摘要<textarea v-model="form.summary" maxlength="500" rows="3" placeholder="簡短說明職缺目標"></textarea></label>
          <label class="wide">職務說明（JD）*<textarea v-model="form.jd" rows="8" required placeholder="工作內容、必要條件及加分條件"></textarea></label>
        </div>
        <footer><span>部門：{{ workspace?.department_name }}（由系統鎖定）</span><div><button type="button" class="button secondary" :disabled="saving" @click="closeDialog">取消</button><button type="submit" class="button primary" :disabled="saving">{{ saving ? '儲存中…' : editing ? '儲存職缺變更' : '建立並送交 HR' }}</button></div></footer>
      </form>
    </div>
  </section>
</template>

<style scoped>
.department-page{display:grid;gap:14px}.department-hero{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:25px 28px;border-radius:18px;background:linear-gradient(120deg,#123e3a,#176a60 62%,#6cae8f);color:#fff;box-shadow:0 16px 38px rgba(20,74,68,.15)}.department-hero p{margin:0;color:#f1cb77;font-size:8px;font-weight:800;letter-spacing:1.3px}.department-hero h1{margin:6px 0;font-size:25px}.department-hero span{font-size:10px;color:rgba(255,255,255,.75)}.department-hero-actions{display:flex;gap:8px}.department-hero .button{background:rgba(255,255,255,.94)}.department-hero .create-button{background:#f2bb52;color:#173f3a}.department-success,.scope-notice{display:flex;align-items:center;gap:12px;padding:12px 15px;border:1px solid #cfe4dc;border-radius:10px;background:#eff8f4;color:#32635b}.department-success{background:#ecf8ef;border-color:#baddc3}.department-success strong,.scope-notice strong{font-size:10px;white-space:nowrap}.department-success span,.scope-notice span{font-size:9px;line-height:1.6}.department-success button{margin-left:auto;border:0;background:transparent;color:inherit;font-size:16px}.department-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.department-metrics article{padding:16px;border:1px solid var(--line);border-radius:12px;background:#fff}.department-metrics small,.department-metrics span{display:block;color:var(--muted);font-size:8px}.department-metrics strong{display:block;margin:5px 0;font-size:20px;color:#174f49}.department-metrics article:first-child strong{font-size:13px}.department-workspace{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:520px;overflow:hidden}.department-jobs{padding:12px;border-right:1px solid var(--line);background:#f8faf9}.department-jobs>header{padding:9px 8px 13px}.department-jobs>header strong,.department-jobs>header small{display:block}.department-jobs>header strong{font-size:12px}.department-jobs>header small{margin-top:3px;color:var(--muted);font-size:8px}.department-jobs>button{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;margin-bottom:5px;padding:12px;border:0;border-radius:9px;background:transparent;text-align:left;color:inherit}.department-jobs>button:hover,.department-jobs>button.active{background:#e2f0ec;color:#155b52}.department-jobs b,.department-jobs small{display:block}.department-jobs b{font-size:10px}.department-jobs small{margin-top:4px;color:var(--muted);font-size:8px}.department-jobs em{min-width:38px;padding:4px 7px;border-radius:99px;background:#fff;font-size:8px;font-style:normal;text-align:center}.department-jobs>p{padding:12px;color:var(--muted);font-size:9px}.department-main{min-width:0;padding:18px}.selected-job{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:4px 2px 18px;border-bottom:1px solid var(--line)}.selected-job h2{margin:8px 0 3px;font-size:19px}.selected-job p{margin:0;color:var(--muted);font-size:9px}.selected-job-actions{display:flex;align-items:center;gap:20px}.selected-job-actions>div{display:flex;gap:7px}.selected-job-actions>strong{font-size:27px;color:#1d6c62;text-align:right}.selected-job-actions>strong small{display:block;font-size:8px;color:var(--muted)}.job-details{display:grid;gap:11px;padding:16px 0 20px;border-bottom:1px solid var(--line)}.job-meta-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.job-meta-grid article,.job-copy{padding:12px;border:1px solid #e2eae7;border-radius:9px;background:#fbfdfc}.job-meta-grid small,.job-meta-grid strong,.job-copy>small{display:block}.job-meta-grid small,.job-copy>small{color:var(--muted);font-size:8px}.job-meta-grid strong{margin-top:4px;color:#245c55;font-size:10px}.job-copy p{margin:6px 0 0;color:#506964;font-size:9px;line-height:1.75}.job-copy .job-description{white-space:pre-wrap}.job-skills{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.job-skills span{padding:5px 8px;border-radius:6px;background:#e8f3ef;color:#27665d;font-size:8px}.job-publish-note{display:flex;justify-content:space-between;gap:10px;padding:0 3px;color:var(--muted);font-size:8px}.applicants-section{padding-top:18px}.applicants-section>header{display:flex;align-items:center;justify-content:space-between}.applicants-section>header h3{margin:0;font-size:13px}.applicants-section>header p{margin:3px 0 0;color:var(--muted);font-size:8px}.applicants-section>header>strong{color:#1d6c62;font-size:10px}.applicant-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px;padding-top:13px}.applicant-list>article{padding:15px;border:1px solid #e0e9e6;border-radius:12px;background:#fff}.applicant-list>article>header{display:flex;justify-content:space-between;align-items:center}.applicant-identity{display:flex;align-items:center;gap:9px;min-width:0}.applicant-identity>span{width:38px;height:38px;flex:0 0 auto;border-radius:50%;display:grid;place-items:center;background:#dceee8;color:#226960;font-weight:800}.applicant-identity h3{margin:0;font-size:12px}.applicant-identity p{margin:3px 0 0;color:var(--muted);font-size:8px}.match-score{text-align:right;color:#1d7468}.match-score.pending{color:#8a9995}.match-score strong,.match-score small{display:block}.match-score strong{font-size:21px}.match-score b{font-size:9px}.match-score small{font-size:7px}.applicant-details{display:grid;grid-template-columns:1fr 1fr;gap:7px;margin:13px 0}.applicant-details span{padding:8px;border-radius:7px;background:#f5f8f7;min-width:0}.applicant-details small,.applicant-details strong{display:block;font-size:7px}.applicant-details small{color:var(--muted)}.applicant-details strong{margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:8px}.applicant-list footer{display:flex;flex-wrap:wrap;gap:8px;padding-top:9px;border-top:1px solid #edf1f0;color:var(--muted);font-size:7px}.department-empty{text-align:center;padding:70px 20px;color:var(--muted)}.department-empty strong,.department-empty p{display:block}.department-empty strong{font-size:12px}.department-empty p{font-size:9px;line-height:1.7}.department-empty .button{display:inline-flex;margin-top:10px}.department-dialog-backdrop{position:fixed;inset:0;z-index:1000;display:grid;place-items:center;padding:24px;background:rgba(8,35,32,.55);backdrop-filter:blur(4px)}.department-dialog{width:min(780px,100%);max-height:calc(100vh - 48px);overflow:auto;border-radius:17px;background:#fff;box-shadow:0 28px 70px rgba(8,35,32,.3)}.department-dialog>header{display:flex;justify-content:space-between;gap:18px;padding:21px 24px;border-bottom:1px solid var(--line)}.department-dialog>header small{color:#b7801d;font-weight:800;letter-spacing:1px}.department-dialog>header h2{margin:4px 0;font-size:19px}.department-dialog>header p{margin:0;color:var(--muted);font-size:9px}.department-dialog>header button{align-self:flex-start;border:0;background:transparent;color:#61716e;font-size:23px}.department-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:21px 24px}.department-form-grid label{display:grid;gap:6px;color:#3c5c57;font-size:9px}.department-form-grid .wide{grid-column:1/-1}.department-form-grid input,.department-form-grid select,.department-form-grid textarea{width:100%;padding:11px 12px;border:1px solid #d6e2df;border-radius:8px;background:#fbfdfc;color:#153f3a;font:inherit;resize:vertical}.department-dialog>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 24px;border-top:1px solid var(--line);background:#f8faf9}.department-dialog>footer>span{color:var(--muted);font-size:8px}.department-dialog>footer>div{display:flex;gap:8px}
@media(max-width:1150px){.department-workspace{grid-template-columns:1fr}.department-jobs{border-right:0;border-bottom:1px solid var(--line)}.applicant-list{grid-template-columns:1fr}.job-meta-grid{grid-template-columns:1fr 1fr}}
@media(max-width:720px){.department-hero,.scope-notice{align-items:flex-start;flex-direction:column}.department-hero-actions{width:100%;flex-wrap:wrap}.department-metrics{grid-template-columns:1fr 1fr}.department-main{padding:13px}.selected-job{align-items:flex-start;flex-direction:column}.selected-job-actions{width:100%;justify-content:space-between}.job-meta-grid,.applicant-details,.department-form-grid{grid-template-columns:1fr}.department-form-grid .wide{grid-column:auto}.form-spacer{display:none}.department-dialog>footer{align-items:flex-start;flex-direction:column}}
</style>
