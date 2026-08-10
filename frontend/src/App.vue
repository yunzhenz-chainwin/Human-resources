<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import AdminView from './components/AdminView.vue'
import AuthView from './components/AuthView.vue'
import CandidateAnalysisPanel from './components/CandidateAnalysisPanel.vue'
import DepartmentWorkspace from './components/DepartmentWorkspace.vue'
import RecruitmentWorkspace from './components/RecruitmentWorkspace.vue'
import ReportsView from './components/ReportsView.vue'
import TalentRetentionPanel from './components/TalentRetentionPanel.vue'
import { adminApi, type Department } from './services/adminApi'
import { authSession } from './services/auth'
import {
  API_BASE,
  hrApi,
  isInterviewEntryStatus,
  type ActivityDto,
  type ApplicationDto,
  type CandidateApplicationDetailDto,
  type CandidateDetailDto,
  type CandidateDto,
  type CandidateResumeSummaryDto,
  type CandidateWrite,
  type CompositeScoreComponent,
  type CompositeScoreWeights,
  type ParsedResume,
  type RequisitionDto,
  type RequisitionWrite,
  type ResumeDto,
  type ResumeSource,
  type ResumeUploadResult,
} from './services/hrApi'
import { privacyApi } from './services/privacyApi'
import {
  jobComplianceCategoryLabels,
  lintJobText,
  type JobComplianceFinding,
} from './services/jobComplianceApi'
import { formatApiDateTime } from './utils/dateTime'

type Page = 'dashboard' | 'department' | 'candidates' | 'resumes' | 'jobs' | 'matching' | 'reports' | 'admin'
type Dialog = 'candidate' | 'activity' | 'job' | null
type CandidateDetailTab = 'profile' | 'documents' | 'activity'
type IntakeStageId = 1 | 2 | 3 | 4
type IntakeStage = {
  id: IntakeStageId
  title: string
  shortTitle: string
  description: string
  outcome: string
  destination: Page
  action: string
  intakeTab?: 'upload' | 'manual'
}
type UploadItemStatus = 'queued' | 'uploading' | 'pending' | 'processing' | 'needs_review' | 'ready' | 'failed' | 'duplicate'
type UploadItem = {
  key: string
  file: File
  status: UploadItemStatus
  resumeId?: number
  message?: string
}
// Hand-off payload for 人才庫 →「進入面試」; shape matches RecruitmentWorkspace's initial-focus prop.
type InterviewFocus = {
  candidateId: number
  candidateName: string
  requisitionId: number
  applicationId: number | null
}

const ASSIGNABLE_JOB_STATUSES = new Set(['draft', 'submitted', 'returned', 'approved', 'sourcing', 'interviewing'])
// 確定面試 only moves a live application forward; already-closed outcomes stay untouched.
const CLOSED_APPLICATION_STATUSES = new Set(['offered', 'hired', 'rejected', 'withdrawn'])
const RESUME_ALLOWED_EXTENSIONS = new Set(['pdf', 'doc', 'docx'])
const RESUME_MAX_FILE_SIZE = 10 * 1024 * 1024

const page = ref<Page>('dashboard')
const authState = authSession.state
const sidebarOpen = ref(false)
const loading = ref(false)
const saving = ref(false)
const logoutPending = ref(false)
const apiOnline = ref(false)
const error = ref('')
const notice = ref('')
const lastSync = ref('尚未同步')
const recruitmentRefreshKey = ref(0)
const candidates = ref<CandidateDto[]>([])
const retentionPolicyYears = ref(2)
const retentionSavingCandidateId = ref<number | null>(null)
const retentionYearOptions = Array.from({ length: 20 }, (_, index) => index + 1)
const applications = ref<ApplicationDto[]>([])
const applicationsLoaded = ref(false)
const interviewFocus = ref<InterviewFocus | null>(null)
const interviewReadyPendingId = ref<number | null>(null)
const departments = ref<Department[]>([])
const resumes = ref<ResumeDto[]>([])
const jobs = ref<RequisitionDto[]>([])
const search = ref('')
const skillSearch = ref('')
const skillSearching = ref(false)
const candidateStatus = ref('all')
const resumeStatus = ref('all')
const uploadFiles = ref<File[]>([])
const uploadItems = ref<UploadItem[]>([])
const uploadValidationError = ref('')
const resumeDropActive = ref(false)
const syncingResumes = ref(false)
const recentlyConfirmedCount = ref(0)
const uploadRequisitionId = ref<number | null>(null)
const uploadInput = ref<HTMLInputElement | null>(null)
const intakeTab = ref<'upload' | 'manual'>('upload')
const intakeGuideStage = ref<IntakeStageId>(1)
const selectedCandidate = ref<CandidateDetailDto | null>(null)
const candidateDetailTab = ref<CandidateDetailTab>('profile')
const candidateDetailBody = ref<HTMLElement | null>(null)
const candidateActivities = ref<ActivityDto[]>([])
const selectedCandidateResume = ref<ResumeDto | null>(null)
const candidateResumeLoading = ref(false)
const resumeFilePreview = ref<ResumeDto | null>(null)
const resumeFilePreviewUrl = ref('')
const resumeFilePreviewLoadingId = ref<number | null>(null)
const resumeFilePreviewError = ref('')
const candidatePhotoInput = ref<HTMLInputElement | null>(null)
const candidatePhotoFile = ref<File | null>(null)
const candidatePhotoPreviews = reactive<Record<number, string>>({})
const selectedResume = ref<ResumeDto | null>(null)
const parsedForm = reactive<ParsedResume>({})
const dialog = ref<Dialog>(null)
const editingCandidate = ref<CandidateDto | null>(null)
const editingCandidateApplication = ref<ApplicationDto | null>(null)
const candidateDepartmentId = ref<number | null>(null)
const candidateJobId = ref<number | null>(null)
const editingJob = ref<RequisitionDto | null>(null)
const candidateForm = reactive<CandidateWrite>({ name: '', email: '', phone: '', city: '', current_title: '', total_years: 0, source: 'manual', status: 'new' })
const intakeStages: IntakeStage[] = [
  {
    id: 1,
    title: '建立人才基本資料',
    shortTitle: '基本資料',
    description: '填寫姓名與聯絡方式，先建立一筆可搜尋、可持續補充的人才主檔。',
    outcome: '完成後：人才會有基本識別資料',
    destination: 'resumes',
    action: '到新增人才手動填寫',
    intakeTab: 'manual',
  },
  {
    id: 2,
    title: '帶入履歷與經歷',
    shortTitle: '履歷辨識',
    description: '上傳一份或多份履歷，系統會排入 OCR 與來源辨識；手邊沒有履歷也能略過。',
    outcome: '完成後：履歷會進入人工校對佇列',
    destination: 'resumes',
    action: '到新增人才上傳履歷',
    intakeTab: 'upload',
  },
  {
    id: 3,
    title: '指定應徵部門與職缺',
    shortTitle: '招募方向',
    description: '選好應徵部門、目標職缺並補充備註，讓人才正確對應負責主管。',
    outcome: '完成後：系統知道要送往哪個部門',
    destination: 'candidates',
    action: '到人才庫指派',
  },
  {
    id: 4,
    title: '確認建檔並送交主管',
    shortTitle: '送交主管',
    description: '檢查必填資料後一次送出，同時建立人才主檔與正式應徵紀錄。',
    outcome: '完成後：部門主管可在本部門看到人才',
    destination: 'candidates',
    action: '查看人才進度',
  },
]
const activityForm = reactive({ type: '電話聯繫', content: '', next_status: 'contacted' })
// blind_review_enabled keeps the server's polarity (true = evaluations stay hidden until both
// stages submit); the checkbox that edits it is inverted, because what HR opts into is disclosure.
const jobForm = reactive({
  req_no: '', title: '', department_id: null as number | null, employment_type: 'full_time', work_city: '台北市',
  jd: '', summary: '', skillsText: '', salary_min: null as number | null, salary_max: null as number | null,
  salary_type: 'monthly', headcount: 1, status: 'draft', blind_review_enabled: true,
})
// Frozen server-side once any interview here has been submitted, and HR-only in every case.
// RequisitionCreate carries no such field, so a new requisition always starts blind and the
// rule only becomes editable on a later edit — the control stays visible but disabled meanwhile.
const blindReviewLocked = computed(() => !!editingJob.value?.blind_review_locked)
const blindReviewEditable = computed(() => !!editingJob.value && authState.user?.role === 'hr' && !blindReviewLocked.value)

// Weights behind the interview card's ⑥ 綜合參考分, in the order that card numbers them.
// Held apart from jobForm because openJob replaces jobForm wholesale with Object.assign,
// which would flatten a nested reactive object into a plain one.
const compositeWeightKeys = ['resume', 'hr_questions', 'hr_overall', 'manager_questions', 'manager_overall'] as const
const compositeWeightLabels: Record<CompositeScoreComponent, string> = {
  resume: '① 履歷匹配', hr_questions: '② HR 題目', hr_overall: '③ HR 總結',
  manager_questions: '④ 主管題目', manager_overall: '⑤ 主管總結',
}
// Mirrors DEFAULT_COMPOSITE_WEIGHTS in services/interview_scoring.py. Only ever shown for a
// requisition that has not configured its own; the server stays the authority on what is stored.
const defaultCompositeWeights: Record<CompositeScoreComponent, number> = {
  resume: 20, hr_questions: 15, hr_overall: 25, manager_questions: 15, manager_overall: 25,
}
const compositeWeightForm = reactive<Record<CompositeScoreComponent, number>>({ ...defaultCompositeWeights })
// Same shape as blind review above: HR-only on the server, and RequisitionCreate carries no
// weights, so a new requisition starts on the built-in split and only a later edit can change it.
const compositeWeightsEditable = computed(() => !!editingJob.value && authState.user?.role === 'hr')
const compositeWeightTotal = computed(() =>
  compositeWeightKeys.reduce((total, key) => total + (Number(compositeWeightForm[key]) || 0), 0))
const compositeWeightInvalid = computed(() => compositeWeightTotal.value <= 0)

// Reads the resolved weights (already rescaled to sum 1 by the server) back into whole
// percentage points, so the form shows the same split the interview card prints.
function setCompositeWeightForm(resolved?: Required<CompositeScoreWeights> | null) {
  for (const key of compositeWeightKeys) {
    const value = resolved?.[key]
    compositeWeightForm[key] = typeof value === 'number' ? Math.round(value * 100) : defaultCompositeWeights[key]
  }
}

// Anti-discrimination JD lint (就服法 §5 / 中高齡就業促進法 / 性別平等工作法).
// Advisory only: warnings are surfaced in the form but never block saving.
const jobComplianceFindings = ref<JobComplianceFinding[]>([])
const jobComplianceLabel = (category: JobComplianceFinding['category']) =>
  jobComplianceCategoryLabels[category] || category
let jobComplianceTimer: ReturnType<typeof setTimeout> | null = null
let jobComplianceToken = 0

function clearJobComplianceLint() {
  if (jobComplianceTimer) { clearTimeout(jobComplianceTimer); jobComplianceTimer = null }
  jobComplianceToken += 1
  jobComplianceFindings.value = []
}

function scheduleJobComplianceLint() {
  if (dialog.value !== 'job') return
  if (jobComplianceTimer) clearTimeout(jobComplianceTimer)
  const title = jobForm.title, summary = jobForm.summary, jd = jobForm.jd
  if (!title.trim() && !summary.trim() && !jd.trim()) { clearJobComplianceLint(); return }
  const token = ++jobComplianceToken
  jobComplianceTimer = setTimeout(async () => {
    try {
      const result = await lintJobText({ title, summary, jd })
      if (token === jobComplianceToken) jobComplianceFindings.value = result.findings
    } catch {
      // Lint is advisory; a failed preview must not disrupt editing.
      if (token === jobComplianceToken) jobComplianceFindings.value = []
    }
  }, 500)
}

watch(
  () => dialog.value === 'job' && [jobForm.title, jobForm.summary, jobForm.jd].join(''),
  (value) => { if (value !== false) scheduleJobComplianceLint() },
)

type NavItem = { id: Page; label: string; icon: string; roles: string[] }
type NavGroup = { id: string; label: string | null; items: NavItem[] }

const navGroups: NavGroup[] = [
  {
    id: 'overview',
    label: null,
    items: [
      { id: 'dashboard', label: '工作總覽', icon: '⌂', roles: ['it', 'admin', 'hr', 'manager'] },
    ],
  },
  {
    id: 'recruitment',
    label: '招募執行',
    items: [
      { id: 'department', label: '部門後台', icon: '▦', roles: ['manager'] },
      { id: 'candidates', label: '人才庫', icon: '人', roles: ['admin', 'hr'] },
      { id: 'resumes', label: '新增人才', icon: '＋', roles: ['admin', 'hr', 'manager'] },
      { id: 'jobs', label: '職缺管理', icon: '◇', roles: ['admin', 'hr', 'manager'] },
    ],
  },
  {
    id: 'matching',
    label: '媒合與面試',
    items: [
      { id: 'matching', label: '人才評估與面試', icon: '◎', roles: ['admin', 'hr', 'manager'] },
    ],
  },
  {
    id: 'analytics',
    label: '分析報表',
    items: [
      { id: 'reports', label: '招募分析', icon: '⌁', roles: ['admin', 'hr', 'manager'] },
    ],
  },
  {
    id: 'system',
    label: '系統管理',
    items: [
      { id: 'admin', label: '帳號與權限', icon: '⚙', roles: ['it', 'admin', 'hr'] },
    ],
  },
]

const allNav: NavItem[] = navGroups.flatMap(group => group.items)

// Render groups by role, dropping any group that has no visible item for this role.
const visibleNavGroups = computed(() => {
  const role = authState.user?.role || ''
  return navGroups
    .map(group => ({ ...group, items: group.items.filter(item => item.roles.includes(role)) }))
    .filter(group => group.items.length > 0)
})
const managerDefaultPage: Page = 'department'

function canAccessPage(target: Page) {
  const role = authState.user?.role || ''
  return allNav.some(item => item.id === target && item.roles.includes(role))
}

function defaultPageForCurrentRole(): Page {
  return authState.user?.role === 'manager' ? managerDefaultPage : 'dashboard'
}
const roleProfile = computed(() => ({
  it: { label: 'IT 管理員', scope: '系統管理', note: '帳號權限、組織與系統設定，不接觸招募個資' },
  admin: { label: '相容管理員', scope: '系統全域', note: '保留既有管理與招募權限' },
  hr: { label: 'HR 招募夥伴', scope: '全公司資料', note: '所有職缺、人才庫與招募分析' },
  manager: { label: '部門主管', scope: '所屬部門', note: '僅查看本部門職缺與實際應徵人才' },
}[authState.user?.role || 'manager']))

const pageTitle = computed(() => allNav.find(item => item.id === page.value)?.label || 'TalentHub')
const filteredCandidates = computed(() => candidates.value.filter(candidate => {
  const q = search.value.trim().toLocaleLowerCase()
  const inSearch = !q || [candidate.name, candidate.email, candidate.phone, candidate.current_title, candidate.city, candidate.source]
    .some(value => String(value || '').toLocaleLowerCase().includes(q))
  return inSearch && (candidateStatus.value === 'all' || candidate.status === candidateStatus.value)
}))
const queueResumes = computed(() => resumes.value.filter(resume => resume.parse_status !== 'confirmed'))
const filteredResumes = computed(() => queueResumes.value.filter(resume =>
  resumeStatus.value === 'all' || resume.parse_status === resumeStatus.value,
))
const pendingReviewCount = computed(() => resumes.value.filter(r => ['needs_review', 'failed'].includes(r.parse_status)).length)
const uploadSummary = computed(() => uploadItems.value.reduce<Record<UploadItemStatus, number>>((summary, item) => {
  summary[item.status] += 1
  return summary
}, { queued: 0, uploading: 0, pending: 0, processing: 0, needs_review: 0, ready: 0, failed: 0, duplicate: 0 }))
const activeJobCount = computed(() => jobs.value.filter(j => ['approved', 'sourcing', 'interviewing'].includes(j.status)).length)
const activeCandidateCount = computed(() => candidates.value.filter(candidate => candidate.status !== 'archived').length)
const priorityCandidateCount = computed(() => candidates.value.filter(candidate => ['priority', 'interviewing'].includes(candidate.status)).length)
const selectedUploadJob = computed(() => jobs.value.find(job => job.id === uploadRequisitionId.value) || null)
const resumeUploadDisabled = computed(() => saving.value || (authState.user?.role === 'manager' && !selectedUploadJob.value))
const selectableDepartments = computed(() => departments.value
  .filter(department => department.is_active)
  .sort((left, right) => left.name.localeCompare(right.name, 'zh-TW')))
const selectedIntakeStage = computed(() => intakeStages.find(stage => stage.id === intakeGuideStage.value)!)
const candidateDepartmentJobs = computed(() => jobs.value.filter(job =>
  job.department_id === candidateDepartmentId.value
  && (isAssignableJob(job) || job.id === editingCandidateApplication.value?.requisition_id),
))
const editingCandidateAssignments = computed(() => editingCandidate.value
  ? applications.value.filter(application => application.candidate_id === editingCandidate.value?.id)
  : [])
const candidateAssignmentDataUnavailable = computed(() => editingCandidate.value !== null && !applicationsLoaded.value)
const candidateAssignmentInvalid = computed(() => candidateDepartmentId.value !== null
  && !candidateDepartmentJobs.value.some(job => job.id === candidateJobId.value))
const averageCandidateYears = computed(() => {
  const values = candidates.value.map(candidate => Number(candidate.total_years)).filter(value => Number.isFinite(value) && value >= 0)
  return values.length ? (values.reduce((total, value) => total + value, 0) / values.length).toFixed(1) : '0.0'
})

function isAssignableJob(job: RequisitionDto) {
  return job.department_id !== null && ASSIGNABLE_JOB_STATUSES.has(job.status)
}

function intakeStageStatus(stage: IntakeStageId) {
  if (stage === 2) return '可略過'
  if (stage === 4) return '主管接手'
  return intakeGuideStage.value === stage ? '目前查看' : `步驟 ${stage}/4`
}

function goToIntakeStage(stage: IntakeStageId) {
  intakeGuideStage.value = stage
}

async function openIntakeStage(stage: IntakeStage) {
  intakeGuideStage.value = stage.id
  await navigate(stage.destination, stage.intakeTab ? { intakeTab: stage.intakeTab } : undefined)
}

function canReassignApplication(application: ApplicationDto) {
  return application.status === 'submitted'
    && application.interview_at === null
    && application.interview_result === null
    && application.interview_notes === null
    && application.hr_interview.interview_at === null
    && application.hr_interview.interview_result === null
    && application.hr_interview.interview_notes === null
    && application.manager_interview.interview_at === null
    && application.manager_interview.interview_result === null
    && application.manager_interview.interview_notes === null
}

function departmentsFromJobs(items: RequisitionDto[]): Department[] {
  const fallback = new Map<number, Department>()
  items.forEach(job => {
    if (job.department_id !== null && !fallback.has(job.department_id)) {
      fallback.set(job.department_id, {
        id: job.department_id,
        name: job.department_name || `部門 #${job.department_id}`,
        parent_id: null,
        is_active: true,
      })
    }
  })
  return Array.from(fallback.values())
}

const candidateStatusLabels: Record<string, string> = {
  new: '新進人才', contacted: '已聯繫', priority: '優先聯繫', interviewing: '面試中', archived: '已封存',
}
const applicationStatusLabels: Record<string, string> = {
  submitted: '已投遞', screening: '履歷審查', interview_ready: '確定面試', interview: '面試中', interviewing: '面試中',
  offered: '已發 Offer', hired: '已錄取', rejected: '未錄取', withdrawn: '已撤回',
}
const canMarkInterviewReady = computed(() => authState.user?.role === 'hr')
// A talent row can only show one application, so keep whichever is closest to an interview.
const listedApplications = computed(() => {
  const index = new Map<number, ApplicationDto>()
  applications.value.forEach(application => {
    const current = index.get(application.candidate_id)
    if (!current || (!isInterviewEntryStatus(current.status) && isInterviewEntryStatus(application.status))) {
      index.set(application.candidate_id, application)
    }
  })
  return index
})
function listedApplication(candidateId: number) {
  return listedApplications.value.get(candidateId) || null
}
function talentApplicationLabel(candidateId: number) {
  if (!applicationsLoaded.value) return '應徵資料未載入'
  const application = listedApplication(candidateId)
  if (!application) return '尚未指派職缺'
  return applicationStatusLabels[application.status] || application.status
}
const interviewEntryApplication = computed(() => (
  selectedCandidate.value?.applications.find(application => isInterviewEntryStatus(application.status)) || null
))
function canConfirmInterview(application: CandidateApplicationDetailDto) {
  return canMarkInterviewReady.value
    && !isInterviewEntryStatus(application.status)
    && !CLOSED_APPLICATION_STATUSES.has(application.status)
}

async function markInterviewReady(application: CandidateApplicationDetailDto) {
  if (interviewReadyPendingId.value !== null) return
  interviewReadyPendingId.value = application.id
  error.value = ''
  try {
    const updated = (await hrApi.markApplicationInterviewReady(application.id)).data
    application.status = updated.status
    const listed = applications.value.find(item => item.id === updated.id)
    if (listed) listed.status = updated.status
    else applications.value.unshift(updated)
    setNotice(`已確定面試：${updated.candidate.name}／${updated.requisition.title}`)
  } catch (cause) { showError(cause) } finally { interviewReadyPendingId.value = null }
}

// Carry the candidate + requisition into 人才評估與面試 so the interview card opens already expanded.
async function enterInterview(candidate: CandidateDetailDto, application: CandidateApplicationDetailDto) {
  interviewFocus.value = {
    candidateId: candidate.id,
    candidateName: candidate.name,
    requisitionId: application.requisition_id,
    applicationId: application.id,
  }
  selectedCandidate.value = null
  await navigate('matching')
}
const activityRoleLabels: Record<string, string> = {
  admin: '系統管理員', hr: 'HR', manager: '部門主管', it: 'IT',
}

function clearCandidatePhotoPreview(candidateId: number) {
  if (candidatePhotoPreviews[candidateId]) URL.revokeObjectURL(candidatePhotoPreviews[candidateId])
  delete candidatePhotoPreviews[candidateId]
}

async function loadCandidatePhoto(candidate: CandidateDto) {
  clearCandidatePhotoPreview(candidate.id)
  if (!candidate.has_photo) return
  try {
    candidatePhotoPreviews[candidate.id] = URL.createObjectURL(await hrApi.candidatePhoto(candidate.id))
  } catch {
    // The fallback initials remain visible if a private image cannot be loaded.
  }
}

async function loadCandidatePhotos(items: CandidateDto[]) {
  const activePhotoIds = new Set(items.filter(item => item.has_photo).map(item => item.id))
  Object.keys(candidatePhotoPreviews).forEach(id => {
    const candidateId = Number(id)
    if (!activePhotoIds.has(candidateId)) clearCandidatePhotoPreview(candidateId)
  })
  await Promise.all(items.filter(item => item.has_photo).map(loadCandidatePhoto))
}
const resumeStatusLabels: Record<string, string> = {
  pending: '等待解析', processing: '解析中', parsed: '待確認', needs_review: '待人工校對', confirmed: '已入庫', failed: '解析失敗',
}
const resumeQueueStatusLabels: Record<string, string> = {
  pending: '等待解析', processing: '解析中', parsed: '可入庫', needs_review: '需人工確認', failed: '解析失敗',
}
const uploadStatusLabels: Record<UploadItemStatus, string> = {
  queued: '等待上傳', uploading: '上傳中', pending: '等待解析', processing: '解析中',
  needs_review: '需人工確認', ready: '可入庫', failed: '失敗', duplicate: '重複檔案',
}
const jobStatusLabels: Record<string, string> = {
  draft: '草稿', submitted: '待審核', approved: '已核准', sourcing: '招募中', interviewing: '面試中', filled: '已補齊', closed: '已關閉',
}
const sourceLabels: Record<string, string> = { p104: '疑似 104 匯出格式', p1111: '疑似 1111 匯出格式', generic: '來源無法驗證', direct: '一般／自製履歷', manual: '手動建立' }

function setNotice(message: string) {
  notice.value = message
  window.setTimeout(() => { if (notice.value === message) notice.value = '' }, 3000)
}

function showError(cause: unknown) {
  error.value = cause instanceof Error ? cause.message : '發生未預期錯誤'
}

// `error` stays the only error state; this merely picks which open surface renders it. The page
// banner lives in .content, below every fixed overlay declared here (.modal-overlay z-index 100,
// .drawer-overlay z-index 80), so a failure raised while one of them is open has to move up with it
// instead of being painted out of sight behind the scrim — and it is never rendered in two places.
const errorSurface = computed<'modal' | 'drawer' | 'page'>(() => dialog.value ? 'modal' : selectedCandidate.value ? 'drawer' : 'page')

async function refreshAll(silent = false) {
  if (!authSession.authenticated.value) return
  loading.value = true
  error.value = ''
  try {
    await hrApi.health()
    apiOnline.value = true
    if (authState.user?.role === 'it') {
      candidates.value = []
      applications.value = []
      applicationsLoaded.value = false
      departments.value = []
      resumes.value = []
      jobs.value = []
      lastSync.value = new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
      if (!silent) setNotice('系統狀態已同步')
      return
    }
    const canEditCandidates = ['admin', 'hr'].includes(authState.user?.role || '')
    const canReadResumeFiles = canEditCandidates
    if (!canEditCandidates) {
      candidates.value = []
      Object.keys(candidatePhotoPreviews).forEach(id => clearCandidatePhotoPreview(Number(id)))
    }
    const [candidateResult, resumeResult, jobResult, applicationResult, departmentResult] = await Promise.allSettled([
      canEditCandidates ? hrApi.candidates(skillSearch.value.trim() ? { skill: skillSearch.value.trim() } : {}) : Promise.resolve({ data: [] as CandidateDto[] }),
      canReadResumeFiles ? hrApi.resumes() : Promise.resolve({ data: [] as ResumeDto[] }),
      hrApi.requisitions(),
      canEditCandidates ? hrApi.applications() : Promise.resolve({ data: [] as ApplicationDto[] }),
      canEditCandidates ? adminApi.departments() : Promise.resolve({ data: [] as Department[] }),
    ])
    // Apply whichever core datasets loaded; a single endpoint failure must not discard the others or fake a full outage.
    const failures: unknown[] = []
    if (candidateResult.status === 'fulfilled') {
      candidates.value = candidateResult.value.data
      await loadCandidatePhotos(candidates.value)
    } else failures.push(candidateResult.reason)
    if (resumeResult.status === 'fulfilled') {
      resumes.value = resumeResult.value.data
      if (selectedResume.value && !resumes.value.some(resume => resume.id === selectedResume.value?.id)) {
        selectedResume.value = null
      }
    } else failures.push(resumeResult.reason)
    if (jobResult.status === 'fulfilled') {
      jobs.value = jobResult.value.data
      if (uploadRequisitionId.value !== null && !jobs.value.some(job => job.id === uploadRequisitionId.value)) {
        uploadRequisitionId.value = null
      }
    } else failures.push(jobResult.reason)
    applications.value = applicationResult.status === 'fulfilled' ? applicationResult.value.data : []
    applicationsLoaded.value = applicationResult.status === 'fulfilled'
    if (departmentResult.status === 'fulfilled' && departmentResult.value.data.length) {
      departments.value = departmentResult.value.data
    } else if (jobResult.status === 'fulfilled') {
      departments.value = departmentsFromJobs(jobResult.value.data)
    }
    recruitmentRefreshKey.value += 1
    lastSync.value = new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
    if (failures.length) {
      // Surface every failed dataset; health() already ran and set apiOnline, so a data/permission error is not a connection outage.
      const messages = failures.map(failure => failure instanceof Error ? failure.message : '發生未預期錯誤')
      error.value = Array.from(new Set(messages)).join('；')
    } else if (!silent) {
      setNotice('資料已同步')
    }
  } catch (cause) {
    apiOnline.value = false
    showError(cause)
  } finally {
    loading.value = false
  }
}

// Skill filtering needs the backend; other filters (keyword/status) stay client-side over the loaded list.
let skillSearchTimer: ReturnType<typeof setTimeout> | null = null
function scheduleSkillSearch() {
  if (skillSearchTimer) clearTimeout(skillSearchTimer)
  skillSearchTimer = setTimeout(() => { void applySkillSearch() }, 400)
}
async function applySkillSearch() {
  if (skillSearchTimer) {
    clearTimeout(skillSearchTimer)
    skillSearchTimer = null
  }
  if (!['admin', 'hr'].includes(authState.user?.role || '')) return
  const skill = skillSearch.value.trim()
  skillSearching.value = true
  error.value = ''
  try {
    // A cleared skill box returns to the original "load everything + client-side filter" behaviour.
    const result = skill ? await hrApi.candidates({ skill }) : await hrApi.candidates()
    candidates.value = result.data
    await loadCandidatePhotos(candidates.value)
  } catch (cause) {
    showError(cause)
  } finally {
    skillSearching.value = false
  }
}

async function navigate(target: Page, options?: { intakeTab?: 'upload' | 'manual' }) {
  if (!canAccessPage(target)) {
    page.value = defaultPageForCurrentRole()
    sidebarOpen.value = false
    error.value = target === 'candidates'
      ? '人才庫僅開放 HR 管理；部門主管請至「部門後台」查看本部門職缺的實際應徵者。'
      : '目前帳號沒有此頁面的存取權限。'
    return
  }
  page.value = target
  sidebarOpen.value = false
  error.value = ''
  // A talent-pool hand-off is single-use: leaving 人才評估與面試 must not re-focus it on the next visit.
  if (target !== 'matching') interviewFocus.value = null
  // The unified intake page defaults to the upload tab; explicit callers can land on manual filling.
  if (target === 'resumes') setIntakeTab(options?.intakeTab ?? 'upload')
  if (['candidates', 'resumes', 'jobs', 'matching', 'reports'].includes(target)) {
    await refreshAll(true)
  }
}

const canManualIntake = computed(() => ['admin', 'hr'].includes(authState.user?.role || ''))

function setIntakeTab(tab: 'upload' | 'manual') {
  // Managers never get the manual-entry tab; force them back to uploading.
  const next = tab === 'manual' && canManualIntake.value ? 'manual' : 'upload'
  intakeTab.value = next
  if (next === 'manual') resetCandidateForm()
}

// Reset the shared candidate form to a brand-new record (used by the inline manual-intake tab).
function resetCandidateForm() {
  editingCandidate.value = null
  editingCandidateApplication.value = null
  candidateDepartmentId.value = null
  candidateJobId.value = null
  Object.assign(candidateForm, { name: '', email: '', phone: '', city: '', current_title: '', total_years: 0, source: 'manual', status: 'new' })
  candidatePhotoFile.value = null
  if (candidatePhotoInput.value) candidatePhotoInput.value.value = ''
}

async function openCandidate(candidate?: CandidateDto) {
  // Dialogs now render `error` themselves, so a message from an earlier attempt must not reopen with them.
  error.value = ''
  if (candidate && !applicationsLoaded.value && ['admin', 'hr'].includes(authState.user?.role || '')) {
    try {
      applications.value = (await hrApi.applications()).data
      applicationsLoaded.value = true
    } catch {
      error.value = '應徵指派資料暫時無法讀取；仍可編輯基本資料，但本次不能變更部門指派。'
    }
  }
  editingCandidate.value = candidate || null
  editingCandidateApplication.value = candidate
    ? applications.value.find(application => application.candidate_id === candidate.id) || null
    : null
  candidateDepartmentId.value = editingCandidateApplication.value?.requisition.department_id ?? null
  candidateJobId.value = editingCandidateApplication.value?.requisition_id ?? null
  Object.assign(candidateForm, candidate ? {
    name: candidate.name, email: candidate.email || '', phone: candidate.phone || '', city: candidate.city || '',
    current_title: candidate.current_title || '', total_years: candidate.total_years || 0, source: candidate.source || 'manual', status: candidate.status,
  } : { name: '', email: '', phone: '', city: '', current_title: '', total_years: 0, source: 'manual', status: 'new' })
  candidatePhotoFile.value = null
  if (candidatePhotoInput.value) candidatePhotoInput.value.value = ''
  dialog.value = 'candidate'
}

function selectCandidateDepartment() {
  const availableJobs = candidateDepartmentJobs.value.filter(isAssignableJob)
  candidateJobId.value = availableJobs.length === 1 ? availableJobs[0].id : null
}

function selectCandidatePhoto(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  if (file && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    input.value = ''
    candidatePhotoFile.value = null
    return showError('大頭照僅支援 JPG、PNG 或 WebP')
  }
  if (file && file.size > 5 * 1024 * 1024) {
    input.value = ''
    candidatePhotoFile.value = null
    return showError('大頭照不可超過 5 MB')
  }
  candidatePhotoFile.value = file
}

async function saveCandidate(fromInlineIntake = false) {
  if (!candidateForm.name?.trim()) return showError('姓名為必填欄位')
  const target = candidateDepartmentJobs.value.find(job => job.id === candidateJobId.value) || null
  if (candidateDepartmentId.value !== null && !target) {
    return showError('所選部門目前沒有可指派職缺，請先建立／開放職缺，或改選其他部門')
  }
  saving.value = true
  error.value = ''
  let candidateSaved = false
  let assignmentSaved = target === null
  try {
    const payload = { ...candidateForm, email: candidateForm.email || null, phone: candidateForm.phone || null }
    const result = await hrApi.saveCandidate(payload, editingCandidate.value?.id)
    candidateSaved = true
    let assignmentMessage = ''
    if (target) {
      const existingTarget = editingCandidateAssignments.value.find(application => application.requisition_id === target.id)
      let assignment = existingTarget || null
      if (!assignment && editingCandidateApplication.value && canReassignApplication(editingCandidateApplication.value)) {
        assignment = (await hrApi.reassignApplication(editingCandidateApplication.value.id, {
          requisition_id: target.id,
        })).data
        assignmentMessage = `；已改派至「${target.department_name || `部門 #${target.department_id}`}／${target.title}」`
      } else if (!assignment) {
        assignment = (await hrApi.createApplication({
          candidate_id: result.data.id,
          requisition_id: target.id,
        })).data
        assignmentMessage = `；已新增應徵並同步至「${target.department_name || `部門 #${target.department_id}`}」主管後台`
      } else {
        assignmentMessage = `；已維持「${target.department_name || `部門 #${target.department_id}`}／${target.title}」指派`
      }
      const applicationIndex = applications.value.findIndex(item => item.id === assignment.id)
      if (applicationIndex >= 0) applications.value[applicationIndex] = assignment
      else applications.value.unshift(assignment)
      editingCandidateApplication.value = assignment
      assignmentSaved = true
    }
    if (candidatePhotoFile.value) {
      result.data = (await hrApi.uploadCandidatePhoto(result.data.id, candidatePhotoFile.value)).data
      await loadCandidatePhoto(result.data)
    }
    const index = candidates.value.findIndex(item => item.id === result.data.id)
    if (index >= 0) candidates.value[index] = result.data
    else candidates.value.unshift(result.data)
    dialog.value = null
    setNotice(`${editingCandidate.value ? '人才資料已更新' : '人才已建立'}（DB candidates #${result.data.id}／${result.data.code}）${assignmentMessage}`)
    // Inline manual tab stays open for continuous entry; wipe the form so the next record starts clean.
    if (fromInlineIntake) resetCandidateForm()
  } catch (cause) {
    if (candidateSaved && !assignmentSaved) {
      showError(new Error(`人才基本資料已儲存，但部門主管指派未完成：${cause instanceof Error ? cause.message : '請稍後再試'}`))
    } else showError(cause)
  } finally { saving.value = false }
}

async function removeCandidatePhoto(candidate: CandidateDto) {
  if (!window.confirm(`確定移除「${candidate.name}」的大頭照？`)) return
  saving.value = true
  try {
    await hrApi.deleteCandidatePhoto(candidate.id)
    candidate.has_photo = false
    candidate.photo_updated_at = null
    clearCandidatePhotoPreview(candidate.id)
    setNotice('大頭照已移除')
  } catch (cause) { showError(cause) } finally { saving.value = false }
}

function selectCandidateDetailTab(tab: CandidateDetailTab) {
  candidateDetailTab.value = tab
  window.requestAnimationFrame(() => candidateDetailBody.value?.scrollTo({ top: 0 }))
}

async function viewCandidate(candidate: CandidateDto) {
  closeResumeFilePreview()
  resumeFilePreviewError.value = ''
  selectedCandidateResume.value = null
  candidateActivities.value = []
  candidateDetailTab.value = 'profile'
  try {
    const [detail, activities] = await Promise.all([
      hrApi.candidate(candidate.id),
      hrApi.activities(candidate.id),
    ])
    selectedCandidate.value = detail.data
    candidateActivities.value = activities.data
  } catch (cause) { showError(cause) }
}

async function openCandidateResume(resumeId: number) {
  candidateResumeLoading.value = true
  try {
    selectedCandidateResume.value = (await hrApi.resume(resumeId)).data
  } catch (cause) { showError(cause) } finally { candidateResumeLoading.value = false }
}

async function downloadCandidateResume(resumeId: number, filename: string | null) {
  try {
    const blob = await hrApi.downloadResume(resumeId)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename || `resume-${resumeId}`
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) { showError(cause) }
}

function isPdfResume(resume: ResumeDto | null): boolean {
  if (!resume) return false
  return resume.mime?.toLowerCase() === 'application/pdf'
    || resume.original_filename?.toLowerCase().endsWith('.pdf') === true
}

function closeResumeFilePreview() {
  if (resumeFilePreviewUrl.value) URL.revokeObjectURL(resumeFilePreviewUrl.value)
  resumeFilePreviewUrl.value = ''
  resumeFilePreview.value = null
}

async function previewCandidateResume(resume: CandidateResumeSummaryDto) {
  closeResumeFilePreview()
  resumeFilePreviewError.value = ''
  resumeFilePreviewLoadingId.value = resume.id
  try {
    const detail = (await hrApi.resume(resume.id)).data
    let objectUrl = ''
    if (isPdfResume(detail)) {
      const blob = await hrApi.previewResume(resume.id)
      objectUrl = URL.createObjectURL(blob)
    }
    resumeFilePreviewUrl.value = objectUrl
    resumeFilePreview.value = detail
  } catch (cause) {
    closeResumeFilePreview()
    const detail = cause instanceof Error ? cause.message : '未知錯誤'
    resumeFilePreviewError.value = detail.startsWith('404：')
      ? `${resume.original_filename || '這份履歷'}的原始檔已不在儲存空間，請使用系統補建 PDF。`
      : `無法開啟 ${resume.original_filename || '履歷'}：${detail}`
    showError(cause)
  } finally {
    resumeFilePreviewLoadingId.value = null
  }
}

function safeExternalUrl(value: string | null | undefined) {
  if (!value) return ''
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : ''
  } catch { return '' }
}

function resumeValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(item => resumeValue(item)).filter(Boolean).join('、')
  if (value && typeof value === 'object') return Object.values(value).map(item => resumeValue(item)).filter(Boolean).join('；')
  return String(value || '').trim()
}

function resumeHighlights(resume: ResumeDto | null) {
  const payload = resume?.parsed_payload || {}
  const labels: Record<string, string> = {
    current_company: '目前公司', expected_title: '期望職稱', education: '履歷學歷', experience: '履歷經歷',
    skills: '履歷技能', self_intro: '自我介紹', summary: '履歷摘要',
  }
  return Object.entries(labels).map(([key, label]) => ({ label, value: resumeValue(payload[key]) })).filter(item => item.value)
}

const candidateResumeHighlights = computed(() => resumeHighlights(selectedCandidateResume.value))
const resumeFilePreviewHighlights = computed(() => resumeHighlights(resumeFilePreview.value))
const resumeFilePreviewIsPdf = computed(() => isPdfResume(resumeFilePreview.value))
const resumeFilePreviewIsGenerated = computed(() => resumeFilePreview.value?.document_origin === 'system_generated')

function openActivity(candidate: CandidateDetailDto) {
  error.value = ''
  selectedCandidate.value = candidate
  selectCandidateDetailTab('activity')
  const managerMessage = authState.user?.role === 'manager'
  Object.assign(activityForm, {
    type: managerMessage ? '主管留言' : 'HR 留言',
    content: '',
    next_status: managerMessage ? '' : candidate.status || 'contacted',
  })
  dialog.value = 'activity'
}

async function saveActivity() {
  if (!selectedCandidate.value || !activityForm.content.trim()) return showError('請填寫活動紀錄')
  saving.value = true
  error.value = ''
  try {
    const managerMessage = authState.user?.role === 'manager'
    const payload = managerMessage
      ? { type: activityForm.type, content: activityForm.content }
      : { ...activityForm }
    await hrApi.addActivity(selectedCandidate.value.id, payload)
    const updated = await hrApi.candidate(selectedCandidate.value.id)
    const index = candidates.value.findIndex(c => c.id === updated.data.id)
    if (index >= 0) candidates.value[index] = updated.data
    selectedCandidate.value = updated.data
    candidateActivities.value = (await hrApi.activities(updated.data.id)).data
    dialog.value = null
    setNotice(managerMessage ? '主管留言已送出，HR 可在相同時間軸查看' : 'HR 留言與人才狀態已更新，所屬部門主管可查看')
  } catch (cause) { showError(cause) } finally { saving.value = false }
}

async function archiveCandidate(candidate: CandidateDto) {
  if (!window.confirm(`確定封存「${candidate.name}」？`)) return
  try {
    await hrApi.saveCandidate({ status: 'archived' }, candidate.id)
    await refreshAll(true)
    if (selectedCandidate.value?.id === candidate.id) selectedCandidate.value = null
    setNotice('人才已封存')
  } catch (cause) { showError(cause) }
}

async function removeCandidate(candidate: CandidateDto) {
  const confirmed = window.confirm(
    `確定刪除「${candidate.name}」？\n\n刪除後將不再出現在人才庫與媒合名單中。`,
  )
  if (!confirmed) return
  saving.value = true
  error.value = ''
  try {
    await hrApi.deleteCandidate(candidate.id)
    clearCandidatePhotoPreview(candidate.id)
    candidates.value = candidates.value.filter(item => item.id !== candidate.id)
    if (selectedCandidate.value?.id === candidate.id) selectedCandidate.value = null
    setNotice(`已刪除人才「${candidate.name}」`)
  } catch (cause) {
    showError(cause)
  } finally {
    saving.value = false
  }
}

function resumeFileKey(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

function resumeFileValidationError(file: File): string | null {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  if (!RESUME_ALLOWED_EXTENSIONS.has(extension)) return '僅支援 PDF、DOC、DOCX'
  if (file.size > RESUME_MAX_FILE_SIZE) return '檔案超過 10 MB'
  return null
}

function queueResumeFiles(files: File[]) {
  resumeDropActive.value = false
  if (!files.length) return

  const canAppend = uploadFiles.value.length > 0 && uploadItems.value.every(item => item.status === 'queued')
  const currentFiles = canAppend ? [...uploadFiles.value] : []
  const currentItems = canAppend ? [...uploadItems.value] : []
  const queuedKeys = new Set(currentItems.map(item => resumeFileKey(item.file)))
  const acceptedFiles: File[] = []
  const acceptedItems: UploadItem[] = []
  const rejected: string[] = []

  files.forEach(file => {
    const validationError = resumeFileValidationError(file)
    const key = resumeFileKey(file)
    if (validationError) {
      rejected.push(`${file.name}：${validationError}`)
      return
    }
    if (queuedKeys.has(key)) {
      rejected.push(`${file.name}：已在待上傳清單中`)
      return
    }
    queuedKeys.add(key)
    acceptedFiles.push(file)
    acceptedItems.push({ key, file, status: 'queued' })
  })

  if (acceptedFiles.length) {
    uploadFiles.value = [...currentFiles, ...acceptedFiles]
    uploadItems.value = [...currentItems, ...acceptedItems]
  }
  uploadValidationError.value = rejected.length
    ? `有 ${rejected.length} 份檔案未加入：${rejected.join('；')}`
    : ''
}

function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement
  queueResumeFiles(Array.from(input.files || []))
  input.value = ''
}

function setResumeDropActive(active: boolean) {
  resumeDropActive.value = active && !resumeUploadDisabled.value
}

function dropResumeFiles(event: DragEvent) {
  resumeDropActive.value = false
  if (resumeUploadDisabled.value) {
    if (authState.user?.role === 'manager' && !selectedUploadJob.value) {
      uploadValidationError.value = '請先選擇本部門的目標職缺，再拖放履歷。'
    }
    return
  }
  queueResumeFiles(Array.from(event.dataTransfer?.files || []))
}

function removeQueuedResume(key: string) {
  if (saving.value) return
  const item = uploadItems.value.find(candidate => candidate.key === key)
  if (!item || item.status !== 'queued') return
  uploadItems.value = uploadItems.value.filter(candidate => candidate.key !== key)
  uploadFiles.value = uploadFiles.value.filter(file => file !== item.file)
  if (!uploadItems.value.length) uploadValidationError.value = ''
}

async function upload() {
  if (!uploadFiles.value.length) return showError('請先選擇履歷檔案')
  const managerUpload = authState.user?.role === 'manager'
  if (managerUpload && !selectedUploadJob.value) return showError('主管上傳履歷前，請先選擇本部門的目標職缺')
  const targetJob = selectedUploadJob.value
  saving.value = true
  error.value = ''
  uploadValidationError.value = ''
  resumeDropActive.value = false
  const items = [...uploadItems.value]
  for (const item of items) {
    item.status = 'uploading'
    item.message = '正在安全上傳並解析這份履歷'
    try {
      const result = (await hrApi.uploadResumes(
        [item.file],
        'generic',
        undefined,
        managerUpload ? targetJob?.id : undefined,
      )).data[0]
      applyUploadResult(item, result)
      if (managerUpload && !result.duplicate && result.parse_status !== 'failed') {
        item.status = 'ready'
        item.message = '已安全送交 HR 校對；主管不會取得原始履歷讀取權限'
      }
    } catch (cause) {
      item.status = 'failed'
      item.message = cause instanceof Error ? cause.message : '上傳或解析失敗'
    }
  }
  uploadFiles.value = []
  if (uploadInput.value) uploadInput.value.value = ''
  try {
    if (!managerUpload) await syncResumeQueue(false)
    else {
      resumes.value = []
      selectedResume.value = null
    }
  } catch (cause) {
    showError(cause)
  } finally {
    saving.value = false
  }
  const failed = uploadSummary.value.failed
  const duplicate = uploadSummary.value.duplicate
  const accepted = items.length - failed
  if (!accepted) {
    showError(`本批 ${items.length} 份履歷皆未完成，請查看各檔錯誤後重試`)
  } else if (managerUpload && targetJob) {
    setNotice(`${accepted} 份履歷已送往「${targetJob.title}」${failed ? `，${failed} 份失敗` : ''}${duplicate ? `，${duplicate} 份重複` : ''}`)
  } else {
    setNotice(`本批 ${accepted} 份已完成上傳${failed ? `，${failed} 份失敗` : ''}${duplicate ? `，${duplicate} 份重複` : ''}`)
  }
}

function applyUploadResult(item: UploadItem, result: ResumeUploadResult) {
  item.resumeId = result.id
  if (result.duplicate) {
    item.status = 'duplicate'
    item.message = result.parse_status === 'confirmed'
      ? '相同檔案已存在人才庫，不會重複建立'
      : '相同檔案已在辨識佇列，已保留原處理進度'
    return
  }
  if (result.parse_status === 'failed') {
    item.status = 'failed'
    item.message = '檔案已上傳，但解析失敗；可在下方佇列重新解析'
  } else if (result.parse_status === 'pending') {
    item.status = 'pending'
    item.message = '檔案已上傳，正在等待解析'
  } else if (result.parse_status === 'processing') {
    item.status = 'processing'
    item.message = '履歷內容解析中'
  } else if (result.source_review_required || result.parse_status === 'needs_review') {
    item.status = 'needs_review'
    item.message = result.source_review_required ? '請先確認履歷來源，再校對入庫' : '部分欄位需要人工校對'
  } else {
    item.status = 'ready'
    item.message = '解析完成，可從下方佇列開啟校對並入庫'
  }
}

async function syncResumeQueue(notify = true) {
  if (authState.user?.role === 'manager') {
    resumes.value = []
    selectedResume.value = null
    return
  }
  syncingResumes.value = true
  try {
    resumes.value = (await hrApi.resumes()).data
    if (selectedResume.value && !resumes.value.some(item => item.id === selectedResume.value?.id)) {
      selectedResume.value = null
    }
    if (notify) setNotice('履歷辨識進度已更新')
  } catch (cause) {
    showError(cause)
  } finally {
    syncingResumes.value = false
  }
}

async function openResume(resume: ResumeDto) {
  error.value = ''
  try {
    selectedResume.value = (await hrApi.resume(resume.id)).data
    const parsed = selectedResume.value.parsed_payload || {}
    Object.keys(parsedForm).forEach(key => delete parsedForm[key])
    Object.assign(parsedForm, parsed)
  } catch (cause) { showError(cause) }
}

async function saveParsed(confirm = false) {
  if (!selectedResume.value) return
  if (!String(parsedForm.name || '').trim()) return showError('校對資料至少需要姓名')
  const targetRequisitionId = selectedResume.value.target_requisition_id
  const targetJob = jobs.value.find(job => job.id === targetRequisitionId)
  saving.value = true
  error.value = ''
  try {
    await hrApi.updateResumeParsed(selectedResume.value.id, { ...parsedForm, skills: normalizeSkills(parsedForm.skills) })
    if (confirm) {
      const confirmation = (await hrApi.confirmResume(selectedResume.value.id)).data
      await refreshAll(true)
      selectedResume.value = null
      Object.keys(parsedForm).forEach(key => delete parsedForm[key])
      recentlyConfirmedCount.value += 1
      const candidateMessage = confirmation.created ? `已建立人才 ${confirmation.candidate_code}` : `已更新人才 ${confirmation.candidate_code}`
      setNotice(targetRequisitionId
        ? `${candidateMessage}，並自動加入「${targetJob?.title || `職缺 #${targetRequisitionId}`}」應徵名單`
        : candidateMessage)
    } else {
      selectedResume.value = (await hrApi.resume(selectedResume.value.id)).data
      resumes.value = (await hrApi.resumes()).data
      setNotice('校對內容已儲存')
    }
  } catch (cause) { showError(cause) } finally { saving.value = false }
}

function normalizeSkills(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).map(v => v.trim()).filter(Boolean)
  return String(value || '').split(/[,，\n]/).map(v => v.trim()).filter(Boolean)
}

function targetJobName(requisitionId: number | null) {
  if (!requisitionId) return ''
  const job = jobs.value.find(item => item.id === requisitionId)
  return job ? `${job.req_no} · ${job.title}` : `職缺 #${requisitionId}`
}

function sourceEvidence(resume: ResumeDto): string {
  if ((resume.source_evidence || []).some(item => item.type === 'unverified_platform_claim')) {
    return '只偵測到品牌文字或相似欄位，不足以證明是官方匯出檔'
  }
  return (resume.source_evidence || []).map(item => String(item.marker || item.type || '')).filter(Boolean).join('、') || '沒有足夠的平台特徵'
}

function fieldNeedsReview(field: string): boolean {
  if (!selectedResume.value) return false
  const fromOcr = (selectedResume.value.source_evidence || []).some(item => item.type === 'ocr_extracted')
  const score = Number(selectedResume.value.field_confidence?.[field] || 0)
  return fromOcr && score < 0.8
}

async function reparse(resume: ResumeDto) {
  saving.value = true
  try {
    await hrApi.reparseResume(resume.id)
    resumes.value = (await hrApi.resumes()).data
    if (selectedResume.value?.id === resume.id) selectedResume.value = (await hrApi.resume(resume.id)).data
    setNotice('履歷解析結果已更新')
  } catch (cause) { showError(cause) } finally { saving.value = false }
}

async function reviewResumeSource(value: ResumeSource) {
  if (!selectedResume.value) return
  saving.value = true
  try {
    selectedResume.value = (await hrApi.reviewResumeSource(selectedResume.value.id, value)).data
    resumes.value = (await hrApi.resumes()).data
    setNotice(`來源已確認為${sourceLabels[value] || value}`)
  } catch (cause) { showError(cause) } finally { saving.value = false }
}

function openJob(job?: RequisitionDto) {
  error.value = ''
  clearJobComplianceLint()
  editingJob.value = job || null
  Object.assign(jobForm, job ? {
    req_no: job.req_no, title: job.title, department_id: job.department_id, employment_type: job.employment_type,
    work_city: job.work_city, jd: job.jd, summary: job.summary || '', skillsText: (job.skills || []).join(', '),
    salary_min: job.salary_min, salary_max: job.salary_max, salary_type: job.salary_type || 'monthly', headcount: job.headcount, status: job.status,
    // An absent field must never read as "disclosure is open": only an explicit false relaxes blind review.
    blind_review_enabled: job.blind_review_enabled !== false,
  } : { req_no: `R${new Date().getFullYear()}-${String(jobs.value.length + 1).padStart(4, '0')}`, title: '', department_id: null,
    employment_type: 'full_time', work_city: '台北市', jd: '', summary: '', skillsText: '', salary_min: null,
    salary_max: null, salary_type: 'monthly', headcount: 1, status: 'draft', blind_review_enabled: true })
  setCompositeWeightForm(job?.composite_score_weights_resolved)
  dialog.value = 'job'
}

async function saveJob() {
  if (!jobForm.title.trim() || !jobForm.jd.trim()) return showError('職缺名稱與職務說明為必填')
  // An all-zero split carries no decision, and the server would silently fall back to the
  // built-in weights — refuse it here instead, where the number the user typed is still on screen.
  if (compositeWeightsEditable.value && compositeWeightTotal.value <= 0) {
    return showError('綜合參考分權重至少一項必須大於 0')
  }
  saving.value = true
  error.value = ''
  try {
    const payload: RequisitionWrite = {
      req_no: jobForm.req_no, title: jobForm.title, department_id: jobForm.department_id, employment_type: jobForm.employment_type,
      work_city: jobForm.work_city, jd: jobForm.jd, summary: jobForm.summary || null, skills: normalizeSkills(jobForm.skillsText),
      salary_min: jobForm.salary_min, salary_max: jobForm.salary_max, salary_type: jobForm.salary_type,
      headcount: jobForm.headcount, status: jobForm.status,
    }
    // Sent only when the control was actually editable, so a manager's routine edit can never
    // trip the HR-only 403 on a stale copy. A 409 (locked meanwhile) surfaces via showError below.
    if (blindReviewEditable.value) payload.blind_review_enabled = jobForm.blind_review_enabled
    // Same guard as blind review: sent only when the control was editable, so a manager's
    // routine edit never trips the HR-only 403. Restating the current split decides nothing
    // server-side, so re-saving an untouched form is a no-op rather than a needless recompute.
    if (compositeWeightsEditable.value) payload.composite_score_weights = { ...compositeWeightForm }
    await hrApi.saveRequisition(payload, editingJob.value?.id)
    jobs.value = (await hrApi.requisitions()).data
    dialog.value = null
    setNotice(editingJob.value ? '職缺已更新' : '職缺已建立')
  } catch (cause) { showError(cause) } finally { saving.value = false }
}

async function approveJob(job: RequisitionDto) {
  saving.value = true
  try {
    await hrApi.approveRequisition(job.id)
    jobs.value = (await hrApi.requisitions()).data
    setNotice('職缺已核准並可供前台讀取')
  } catch (cause) { showError(cause) } finally { saving.value = false }
}

function date(value: string) {
  return formatApiDateTime(value)
}

async function updateCandidateRetention(candidate: CandidateDto, event: Event) {
  const select = event.target as HTMLSelectElement
  const previous = candidate.retention_years_override
  const retentionYears = select.value === '' ? null : Number(select.value)
  if (retentionYears !== null && (!Number.isInteger(retentionYears) || retentionYears < 1 || retentionYears > 20)) {
    select.value = previous === null ? '' : String(previous)
    showError('個別保存年限必須是 1 到 20 年')
    return
  }
  if (retentionYears === previous) return
  retentionSavingCandidateId.value = candidate.id
  error.value = ''
  try {
    const setting = (await privacyApi.updateCandidateRetention(candidate.id, retentionYears)).data
    candidate.retention_years_override = setting.retention_years_override
    candidate.retention_until = setting.retention_until
    const listedCandidate = candidates.value.find(item => item.id === candidate.id)
    if (listedCandidate && listedCandidate !== candidate) {
      listedCandidate.retention_years_override = setting.retention_years_override
      listedCandidate.retention_until = setting.retention_until
    }
    if (selectedCandidate.value?.id === candidate.id && selectedCandidate.value !== candidate) {
      selectedCandidate.value.retention_years_override = setting.retention_years_override
      selectedCandidate.value.retention_until = setting.retention_until
    }
    setNotice(
      setting.uses_company_default
        ? `${candidate.name} 已恢復公司預設 ${setting.effective_retention_years} 年，保存至 ${dateOnly(setting.retention_until)}`
        : `${candidate.name} 已個別設定 ${setting.effective_retention_years} 年，保存至 ${dateOnly(setting.retention_until)}`,
    )
  } catch (cause) {
    select.value = previous === null ? '' : String(previous)
    showError(cause)
  } finally {
    retentionSavingCandidateId.value = null
  }
}

function dateOnly(value: string) {
  return formatApiDateTime(value, { dateStyle: 'medium' })
}

let authenticationSync: Promise<void> | null = null

async function authenticated() {
  if (authenticationSync) return authenticationSync
  authenticationSync = (async () => {
    page.value = defaultPageForCurrentRole()
    uploadRequisitionId.value = null
    await refreshAll(true)
  })()
  try {
    await authenticationSync
  } finally {
    authenticationSync = null
  }
}

async function logout() {
  if (logoutPending.value) return
  logoutPending.value = true
  closeResumeFilePreview()
  try {
    await authSession.logout()
  } finally {
    candidates.value = []
    Object.keys(candidatePhotoPreviews).forEach(id => clearCandidatePhotoPreview(Number(id)))
    applications.value = []
    applicationsLoaded.value = false
    departments.value = []
    resumes.value = []
    jobs.value = []
    uploadFiles.value = []
    uploadItems.value = []
    uploadValidationError.value = ''
    intakeTab.value = 'upload'
    resumeDropActive.value = false
    recentlyConfirmedCount.value = 0
    uploadRequisitionId.value = null
    editingCandidate.value = null
    editingCandidateApplication.value = null
    candidateDepartmentId.value = null
    candidateJobId.value = null
    selectedCandidate.value = null
    selectedResume.value = null
    interviewFocus.value = null
    page.value = 'dashboard'
    logoutPending.value = false
  }
}

watch(() => authState.user?.id, async (userId, previousId) => {
  if (userId && userId !== previousId) await authenticated()
})

watch([() => authState.user?.role, page], ([role, currentPage]) => {
  if (role && !canAccessPage(currentPage)) {
    page.value = defaultPageForCurrentRole()
  }
})

onMounted(async () => {
  await authSession.initialize()
  if (authState.user && lastSync.value === '尚未同步') await authenticated()
})

onBeforeUnmount(closeResumeFilePreview)
</script>

<template>
  <div v-if="!authState.initialized" class="auth-loading"><span class="spinner"></span><p>正在確認登入狀態…</p></div>
  <AuthView v-else-if="!authState.user" @authenticated="authenticated" />
  <div v-else class="app-shell">
    <button v-if="sidebarOpen" class="mobile-overlay" aria-label="關閉選單" @click="sidebarOpen = false"></button>
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="brand"><div class="brand-mark"><span></span><span></span><span></span></div><div><strong>TalentHub</strong><small>人才與職涯平台</small></div></div>
      <nav>
        <div class="role-scope"><small>目前工作範圍</small><strong>{{ roleProfile.scope }}</strong><span>{{ roleProfile.note }}</span></div>
        <template v-for="group in visibleNavGroups" :key="group.id">
          <p v-if="group.label" class="nav-label">{{ group.label }}</p>
          <button v-for="item in group.items" :key="item.id" class="nav-item" :class="{ active: page === item.id }" :data-testid="`nav-${item.id}`" @click="navigate(item.id)">
            <span class="nav-icon">{{ item.icon }}</span><span>{{ item.label }}</span><em v-if="item.id === 'resumes' && pendingReviewCount">{{ pendingReviewCount }}</em>
          </button>
        </template>
      </nav>
      <div class="sidebar-footer"><div class="connection"><i :class="{ online: apiOnline }"></i><div><strong>{{ apiOnline ? 'API 已連線' : 'API 未連線' }}</strong><small>{{ API_BASE }}</small></div></div></div>
    </aside>

    <main class="main">
      <header class="topbar">
        <button class="menu-button" aria-label="開啟導覽選單" @click="sidebarOpen = true">☰</button>
        <div class="top-title"><strong>{{ pageTitle }}</strong><small>{{ roleProfile.scope }} · 最後同步 {{ lastSync }}</small></div>
        <button class="button secondary" :disabled="loading" @click="refreshAll()">{{ loading ? '同步中…' : '重新同步' }}</button>
        <div class="user-session"><span class="avatar">{{ authState.user.display_name.slice(0, 1) }}</span><div><strong>{{ authState.user.display_name }}</strong><small>{{ roleProfile.label }}</small></div><button class="text-button" :disabled="logoutPending" @click="logout">{{ logoutPending ? '登出中…' : '登出' }}</button></div>
      </header>

      <div class="content">
        <div v-if="error && errorSurface === 'page'" class="alert error-alert" role="alert"><span>!</span><p><strong>操作未完成</strong>{{ error }}</p><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>

        <DepartmentWorkspace v-if="page === 'department'" />

        <section v-else-if="page === 'dashboard'" class="page">
          <div v-if="authState.user.role === 'hr' || authState.user.role === 'admin'" class="intake-page">
            <header class="intake-welcome route-only">
              <nav class="intake-route-guide" data-testid="intake-route-guide" aria-label="HR 人才建檔四關路線">
                <div class="route-guide-heading"><strong>HR 招募四關路線</strong><small>點擊路標直接前往該關；滑過或聚焦可先預覽</small></div>
                <div class="intake-route-map">
                  <svg viewBox="0 0 520 240" preserveAspectRatio="none" aria-hidden="true">
                    <path class="route-road-halo" d="M50 176 C17 125 68 101 105 120 C156 147 116 83 160 54 C207 23 238 84 300 66 C354 50 352 19 399 39 C458 64 466 113 428 142 C396 167 450 177 430 184" />
                    <path class="route-road" d="M50 176 C17 125 68 101 105 120 C156 147 116 83 160 54 C207 23 238 84 300 66 C354 50 352 19 399 39 C458 64 466 113 428 142 C396 167 450 177 430 184" />
                    <path class="route-centerline" d="M50 176 C17 125 68 101 105 120 C156 147 116 83 160 54 C207 23 238 84 300 66 C354 50 352 19 399 39 C458 64 466 113 428 142 C396 167 450 177 430 184" />
                  </svg>
                  <button
                    v-for="stage in intakeStages"
                    :key="stage.id"
                    class="route-stage-button"
                    :class="[`stage-${stage.id}`, { selected: intakeGuideStage === stage.id }]"
                    :data-testid="`intake-route-stop-${stage.id}`"
                    type="button"
                    :aria-current="intakeGuideStage === stage.id ? 'step' : undefined"
                    :aria-label="`第 ${stage.id} 關：${stage.title}，${intakeStageStatus(stage.id)}，前往${stage.action}`"
                    @mouseenter="goToIntakeStage(stage.id)"
                    @focus="goToIntakeStage(stage.id)"
                    @click="openIntakeStage(stage)"
                  >
                    <span class="route-pin"><b>{{ stage.id }}</b></span>
                    <strong>{{ stage.shortTitle }}</strong>
                  </button>
                </div>
                <div class="route-guide-detail" aria-live="polite">
                  <span class="route-detail-number">第 {{ selectedIntakeStage.id }} 關<small>{{ intakeStageStatus(selectedIntakeStage.id) }}</small></span>
                  <div><strong>{{ selectedIntakeStage.title }}</strong><p>{{ selectedIntakeStage.description }}</p><small>{{ selectedIntakeStage.outcome }}</small></div>
                  <button class="route-guide-action" type="button" @click="openIntakeStage(selectedIntakeStage)">{{ selectedIntakeStage.action }} <span>→</span></button>
                </div>
              </nav>
            </header>

          </div>
          <template v-else>
          <div class="welcome-banner">
            <div><p class="eyebrow">{{ roleProfile.label }}</p><h1>{{ authState.user.display_name }}，歡迎回來</h1><p>{{ roleProfile.note }}。{{ authState.user.role === 'it' ? '以下是系統管理入口。' : '以下是你今天需要關注的招募進度。' }}</p></div>
            <div class="scope-orbit"><span>{{ roleProfile.scope }}</span><small>資料存取範圍</small></div>
          </div>
          <div v-if="authState.user.role !== 'it'" class="metric-grid">
            <article v-if="authState.user.role !== 'manager'"><span>人才總數</span><strong>{{ candidates.length }}</strong><small>全公司人才庫資料</small></article>
            <article v-if="authState.user.role !== 'manager'"><span>待校對履歷</span><strong>{{ pendingReviewCount }}</strong><small>待人工確認或解析失敗</small></article>
            <article v-if="authState.user.role !== 'manager'"><span>解析佇列</span><strong>{{ resumes.filter(r => ['pending','processing'].includes(r.parse_status)).length }}</strong><small>等待或正在處理</small></article>
            <article><span>招募中職缺</span><strong>{{ activeJobCount }}</strong><small>目前權限範圍內的職缺</small></article>
          </div>
          <div class="dashboard-actions">
            <article v-if="authState.user.role === 'it'" class="panel"><div><span class="action-icon">⚙</span><div><h3>管理系統與權限</h3><p>維護帳號角色、部門、系統設定與稽核紀錄。</p></div></div><button class="button primary" @click="navigate('admin')">開啟管理中心</button></article>
            <article v-else-if="authState.user.role !== 'manager'" class="panel"><div><span class="action-icon">⇧</span><div><h3>匯入外部履歷</h3><p>批次上傳 104、1111 或其他格式，送入 OCR 解析與欄位校對。</p></div></div><button class="button primary" @click="navigate('resumes')">開始匯入</button></article>
            <article v-else class="panel"><div><span class="action-icon">◎</span><div><h3>檢視推薦人才</h3><p>依技能、經驗與職缺條件查看配對說明，快速做出面試決策。</p></div></div><button class="button primary" @click="navigate('matching')">開始審閱</button></article>
          </div>
          </template>
        </section>

        <section v-else-if="page === 'candidates' && (authState.user.role === 'hr' || authState.user.role === 'admin')" class="page">
          <header class="talent-list-toolbar panel">
            <div><strong>人才清單</strong><span>一人一列顯示摘要；點開人才後再查看聯絡方式、履歷、應徵紀錄與完整操作。</span></div>
            <div class="talent-hero-actions"><button class="button secondary" @click="navigate('matching')">◎ 查看媒合程度</button><button class="button primary" @click="navigate('resumes', { intakeTab: 'manual' })">＋ 手動新增人才</button></div>
          </header>
          <div class="talent-metrics">
            <article><span>人才總數</span><strong>{{ candidates.length }}</strong><small>目前權限範圍</small></article>
            <article><span>活躍人才</span><strong>{{ activeCandidateCount }}</strong><small>未封存資料</small></article>
            <article><span>優先／面試中</span><strong>{{ priorityCandidateCount }}</strong><small>建議優先跟進</small></article>
            <article><span>平均年資</span><strong>{{ averageCandidateYears }}</strong><small>年</small></article>
          </div>
          <TalentRetentionPanel v-if="authState.user.role === 'hr' || authState.user.role === 'admin'" @policy-loaded="retentionPolicyYears = $event" @policy-updated="refreshAll(true)" @purged="refreshAll(true)" />
          <div id="candidate-retention-list" class="filter-bar panel"><label class="search-field"><span>⌕</span><input v-model="search" placeholder="搜尋姓名、Email、電話、職稱或來源"></label><label class="search-field"><span>◆</span><input v-model="skillSearch" data-testid="candidate-skill-search" placeholder="依技能搜尋（後端比對）" @input="scheduleSkillSearch" @keyup.enter="applySkillSearch"></label><select v-model="candidateStatus"><option value="all">全部狀態</option><option v-for="(label, key) in candidateStatusLabels" :key="key" :value="key">{{ label }}</option></select><span>{{ skillSearching ? '技能搜尋中…' : `${filteredCandidates.length} 筆結果` }}</span></div>
          <div v-if="filteredCandidates.length" class="talent-list panel" role="list" data-testid="talent-list">
            <div class="talent-list-head" aria-hidden="true"><span>人才</span><span>目前職務</span><span>來源／更新</span><span>保存期限</span><span>應徵狀態</span><span>狀態</span><span></span></div>
            <article v-for="candidate in filteredCandidates" :key="candidate.id" role="listitem">
              <button type="button" class="talent-list-row" :data-testid="`talent-row-${candidate.id}`" @click="viewCandidate(candidate)">
                <span class="talent-list-identity"><img v-if="candidatePhotoPreviews[candidate.id]" class="person-avatar candidate-photo" :src="candidatePhotoPreviews[candidate.id]" :alt="`${candidate.name}的大頭照`"><span v-else class="person-avatar">{{ candidate.name.slice(0,1) }}</span><span><strong>{{ candidate.name }}</strong><small>{{ candidate.code }}</small></span></span>
                <span class="talent-list-role"><strong>{{ candidate.current_title || '職稱待補' }}</strong><small>{{ candidate.city || '地區待補' }} · {{ candidate.total_years ?? 0 }} 年經驗</small></span>
                <span class="talent-list-source"><strong>{{ sourceLabels[candidate.source || ''] || candidate.source || '未知來源' }}</strong><small>更新於 {{ date(candidate.updated_at) }}</small></span>
                <span class="talent-list-retention" :class="{ custom: candidate.retention_years_override !== null }"><strong>{{ candidate.retention_years_override === null ? `公司預設 ${retentionPolicyYears} 年` : `個別 ${candidate.retention_years_override} 年` }}</strong><small>{{ candidate.retention_until ? `保存至 ${dateOnly(candidate.retention_until)}` : '到期日待計算' }}</small></span>
                <span class="talent-list-application" :data-testid="`talent-application-status-${candidate.id}`"><b class="status" :data-status="listedApplication(candidate.id)?.status">{{ talentApplicationLabel(candidate.id) }}</b><small>{{ listedApplication(candidate.id)?.requisition.title || '—' }}</small></span>
                <span class="status" :data-status="candidate.status">{{ candidateStatusLabels[candidate.status] || candidate.status }}</span>
                <span class="talent-list-open">查看 <b aria-hidden="true">›</b></span>
              </button>
            </article>
          </div>
          <div v-else-if="loading || skillSearching" class="empty panel"><span class="spinner"></span><p>{{ skillSearching ? '正在依技能搜尋人才…' : '正在載入人才資料…' }}</p></div>
          <div v-else class="empty panel"><strong>找不到符合條件的人才</strong><p>請調整搜尋或篩選條件。</p></div>
        </section>

        <section v-else-if="page === 'resumes'" class="page resume-center-page" data-testid="resume-center">
          <div class="page-heading resume-center-heading"><div><p class="eyebrow">{{ authState.user.role === 'manager' ? 'SECURE RESUME HANDOFF' : 'ADD TALENT' }}</p><h1>{{ authState.user.role === 'manager' ? '送交履歷並指派職缺' : '新增人才' }}</h1><p>{{ authState.user.role === 'manager' ? '選擇本部門職缺並安全送交履歷；後續原始檔、解析結果與人工校對由 HR 處理。' : '兩條路都會把人才建進人才庫：用「上傳履歷」讓系統辨識既有履歷，或用「手動填寫」直接建立人才基本資料。' }}</p></div></div>
          <div v-if="canManualIntake" class="intake-tab-bar" role="tablist" aria-label="新增人才方式">
            <button type="button" role="tab" class="intake-tab" :class="{ active: intakeTab === 'upload' }" :aria-selected="intakeTab === 'upload'" data-testid="intake-tab-upload" @click="intakeTab = 'upload'">上傳履歷</button>
            <button type="button" role="tab" class="intake-tab" :class="{ active: intakeTab === 'manual' }" :aria-selected="intakeTab === 'manual'" data-testid="intake-tab-manual" @click="setIntakeTab('manual')">手動填寫</button>
          </div>
          <div v-show="!canManualIntake || intakeTab === 'upload'" class="intake-upload-panel">
          <ol class="resume-center-flow" aria-label="履歷辨識三步驟" data-testid="resume-center-flow">
            <li class="resume-center-flow-step" :class="{ 'is-active': uploadFiles.length, 'is-complete': uploadItems.length && !uploadFiles.length }" data-testid="resume-center-step-1">
              <span class="resume-center-flow-number" aria-hidden="true">1</span>
              <span class="resume-center-flow-copy"><strong>上傳履歷</strong><small>{{ uploadFiles.length ? `${uploadFiles.length} 份等待上傳` : '選擇或拖放檔案' }}</small></span>
              <span class="resume-center-flow-arrow" aria-hidden="true">→</span>
            </li>
            <li v-if="authState.user.role !== 'manager'" class="resume-center-flow-step" :class="{ 'is-active': queueResumes.length && !selectedResume }" data-testid="resume-center-step-2">
              <span class="resume-center-flow-number" aria-hidden="true">2</span>
              <span class="resume-center-flow-copy"><strong>解析佇列</strong><small>{{ queueResumes.length ? `${queueResumes.length} 份待處理` : '等待系統辨識' }}</small></span>
              <span class="resume-center-flow-arrow" aria-hidden="true">→</span>
            </li>
            <li v-if="authState.user.role !== 'manager'" class="resume-center-flow-step" :class="{ 'is-active': selectedResume }" data-testid="resume-center-step-3">
              <span class="resume-center-flow-number" aria-hidden="true">3</span>
              <span class="resume-center-flow-copy"><strong>人工校對</strong><small>{{ selectedResume ? `正在校對 ${selectedResume.original_filename || `履歷 #${selectedResume.id}`}` : '確認後寫入人才庫' }}</small></span>
            </li>
          </ol>
          <div class="resume-layout resume-center-layout">
            <div>
              <article id="resume-upload-stage" class="panel uploader resume-center-upload-panel" aria-labelledby="resume-upload-heading" data-testid="resume-center-upload">
                <div class="section-head resume-center-section-head"><div><h2 id="resume-upload-heading">1. 上傳履歷</h2><p>{{ authState.user.role === 'manager' ? '先選擇本部門職缺，再加入履歷檔案。' : '可混合選擇多份履歷，系統會逐檔辨識來源。' }} PDF、DOC、DOCX，單檔最大 10 MB。</p></div></div>
                <label v-if="authState.user.role === 'manager'" class="manager-job-target"><span>本部門目標職缺 *</span><select v-model="uploadRequisitionId" required><option :value="null" disabled>請選擇履歷要應徵的職缺</option><option v-for="job in jobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}</option></select><small v-if="jobs.length">只能選擇目前登入主管所屬部門的職缺。</small><small v-else class="target-warning">本部門目前沒有可選職缺，請先到「部門後台」建立職缺。</small></label>
                <p v-if="authState.user.role === 'manager'" class="source-auto-note"><span>✓</span><strong>安全送交 HR 校對</strong><small>請先選定職缺。主管無法讀取原始檔或解析內容；HR 確認入庫後，人才才會出現在該職缺的應徵名單。</small></p>
                <p v-else class="source-auto-note"><span>✦</span><strong>不需要先選來源</strong><small>同一批可混合不同格式；判定結果、信心分數與依據會顯示在右側校對區。</small></p>
                <button
                  class="dropzone resume-center-dropzone"
                  :class="{ 'resume-center-dropzone-active': resumeDropActive }"
                  type="button"
                  :disabled="resumeUploadDisabled"
                  :aria-busy="saving"
                  :aria-describedby="uploadValidationError ? 'resume-upload-help resume-upload-error' : 'resume-upload-help'"
                  data-testid="resume-file-picker"
                  @click="uploadInput?.click()"
                  @dragenter.prevent="setResumeDropActive(true)"
                  @dragover.prevent="setResumeDropActive(true)"
                  @dragleave.prevent="setResumeDropActive(false)"
                  @drop.prevent.stop="dropResumeFiles"
                >
                  <span class="resume-center-dropzone-icon" aria-hidden="true">⇧</span>
                  <strong>{{ authState.user.role === 'manager' && !selectedUploadJob ? '請先選擇目標職缺' : resumeDropActive ? '放開以加入履歷' : '拖放履歷到這裡，或點此選擇' }}</strong>
                  <span id="resume-upload-help">支援 PDF、DOC、DOCX；單檔最大 10 MB。可一次加入多份。</span>
                </button>
                <input ref="uploadInput" class="visually-hidden" data-testid="resume-upload-input" type="file" multiple :disabled="resumeUploadDisabled" accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document" aria-label="選擇要上傳的履歷檔案" @change="selectFiles">
                <p v-if="uploadValidationError" id="resume-upload-error" class="inline-error resume-center-upload-error" role="alert" aria-live="assertive" data-testid="resume-upload-validation-error">{{ uploadValidationError }}</p>
                <ul v-if="uploadItems.length" id="resume-upload-list" class="selected-files upload-progress-list resume-center-upload-list" aria-label="履歷上傳清單" aria-live="polite" data-testid="resume-upload-progress">
                  <li v-for="(item, index) in uploadItems" :key="item.key" class="resume-center-upload-item" :data-status="item.status" :data-testid="`resume-upload-item-${index}`" :aria-label="`${item.file.name}，${(item.file.size / 1024 / 1024).toFixed(2)} MB，${uploadStatusLabels[item.status]}`">
                    <span class="resume-center-file-meta"><span class="file-badge" aria-hidden="true">{{ item.file.name.split('.').pop()?.toUpperCase() || 'FILE' }}</span><span><strong :data-testid="`resume-upload-filename-${index}`">{{ item.file.name }}</strong><small>{{ item.message || `${(item.file.size / 1024 / 1024).toFixed(2)} MB` }}</small></span></span>
                    <span class="resume-center-file-actions">
                      <em class="status resume-center-file-status" role="status" :aria-label="`處理狀態：${uploadStatusLabels[item.status]}`" :data-status="item.status" :data-testid="`resume-upload-status-${index}`">{{ uploadStatusLabels[item.status] }}</em>
                      <button v-if="item.status === 'queued' && uploadFiles.length" class="text-button resume-center-file-remove" type="button" :disabled="saving" :aria-label="`移除 ${item.file.name}`" :data-testid="`resume-upload-remove-${index}`" @click="removeQueuedResume(item.key)">移除</button>
                    </span>
                  </li>
                </ul>
                <div v-if="uploadItems.length && !uploadFiles.length" class="upload-batch-summary resume-center-upload-summary" role="status" aria-live="polite" data-testid="resume-upload-summary">
                  <strong>本批處理結果</strong>
                  <span v-if="authState.user.role === 'manager'">已送交 HR {{ uploadSummary.ready }} · 重複 {{ uploadSummary.duplicate }} · 失敗 {{ uploadSummary.failed }}</span><span v-else>可入庫 {{ uploadSummary.ready }} · 需確認 {{ uploadSummary.needs_review }} · 等待中 {{ uploadSummary.pending + uploadSummary.processing }} · 重複 {{ uploadSummary.duplicate }} · 失敗 {{ uploadSummary.failed }}</span>
                </div>
                <button class="button primary upload-button resume-center-upload-action" type="button" aria-controls="resume-upload-list" :aria-label="uploadFiles.length ? `開始上傳 ${uploadFiles.length} 份履歷` : '請先加入履歷檔案'" data-testid="resume-upload-start" :disabled="saving || !uploadFiles.length || (authState.user.role === 'manager' && !selectedUploadJob)" @click="upload">{{ saving ? '逐檔處理中…' : authState.user.role === 'manager' ? `上傳至${selectedUploadJob ? `「${selectedUploadJob.title}」` : '目標職缺'}` : `上傳 ${uploadFiles.length || ''} 份履歷` }}</button>
              </article>
              <article v-if="authState.user.role !== 'manager'" id="resume-queue-stage" class="panel queue resume-center-queue-panel" aria-labelledby="resume-queue-heading" data-testid="resume-center-queue"><div class="section-head resume-center-section-head"><div><h2 id="resume-queue-heading">2. 解析佇列</h2><p>查看等待解析、需校對或尚未入庫的檔案；選取一份即可進到人工校對。</p></div><div class="queue-controls"><label class="visually-hidden" for="resume-queue-filter">篩選解析狀態</label><select id="resume-queue-filter" v-model="resumeStatus" aria-label="篩選解析狀態" data-testid="resume-queue-filter"><option value="all">全部狀態</option><option v-for="(label, key) in resumeQueueStatusLabels" :key="key" :value="key">{{ label }}</option></select><button class="button secondary" type="button" aria-controls="resume-queue-list" data-testid="resume-queue-sync" :disabled="syncingResumes" @click="syncResumeQueue()">{{ syncingResumes ? '同步中…' : '更新進度' }}</button></div></div>
                <div v-if="recentlyConfirmedCount" class="queue-completed-summary" data-testid="resume-confirmed-summary"><strong>✓ 本次已入庫 {{ recentlyConfirmedCount }} 份</strong><span>已從辨識佇列移除，請到「人才庫」查看。</span></div>
                <div id="resume-queue-list" class="resume-center-queue-list" role="region" :aria-label="`解析佇列，共 ${filteredResumes.length} 份履歷`" aria-live="polite">
                  <button v-for="resume in filteredResumes" :key="resume.id" class="resume-row resume-center-queue-item" :class="{ active: selectedResume?.id === resume.id }" type="button" :aria-pressed="selectedResume?.id === resume.id" :aria-label="`${resume.original_filename || `履歷 #${resume.id}`}，${resume.source_review_required ? '來源待確認' : resumeQueueStatusLabels[resume.parse_status] || resume.parse_status}`" :data-testid="`resume-queue-row-${resume.id}`" @click="openResume(resume)"><span class="file-badge">{{ resume.original_filename?.split('.').pop()?.toUpperCase() || 'FILE' }}</span><span><strong>{{ resume.original_filename || `履歷 #${resume.id}` }}</strong><small>{{ sourceLabels[resume.source_platform] || resume.source_platform }} · 信心 {{ Math.round((resume.source_confidence || 0) * 100) }}% · {{ date(resume.uploaded_at) }}<template v-if="resume.target_requisition_id"> · {{ targetJobName(resume.target_requisition_id) }}</template></small></span><span class="status" role="status" :data-status="resume.source_review_required ? 'needs_review' : resume.parse_status">{{ resume.source_review_required ? '來源待確認' : resumeQueueStatusLabels[resume.parse_status] || resume.parse_status }}</span></button>
                </div>
                <div v-if="loading && !filteredResumes.length" class="empty"><span class="spinner"></span><p>正在載入解析佇列…</p></div>
                <div v-else-if="!filteredResumes.length" class="empty"><strong>{{ resumeStatus === 'all' ? '沒有待處理履歷' : '這個狀態目前沒有履歷' }}</strong><p>{{ resumeStatus === 'all' ? '已入庫履歷不會留在這裡，請至人才庫查看。' : '可調整篩選條件或按「更新進度」。' }}</p></div>
              </article>
            </div>
            <article v-if="authState.user.role !== 'manager'" id="resume-review-stage" class="panel review-panel resume-center-review-panel" aria-labelledby="resume-review-heading" data-testid="resume-center-review">
              <template v-if="selectedResume"><div class="section-head resume-center-section-head"><div><h2 id="resume-review-heading">3. 人工校對</h2><p>{{ selectedResume.original_filename }}</p></div><span class="status" role="status" :aria-label="`校對狀態：${resumeStatusLabels[selectedResume.parse_status] || selectedResume.parse_status}`" :data-status="selectedResume.parse_status">{{ resumeStatusLabels[selectedResume.parse_status] || selectedResume.parse_status }}</span></div>
                <div v-if="selectedResume.target_requisition_id" class="resume-target-summary"><small>指定應徵職缺</small><strong>{{ targetJobName(selectedResume.target_requisition_id) }}</strong><p>確認寫入人才庫後，系統會自動建立這項職缺的應徵紀錄。</p></div>
                <div class="source-verdict" :class="{ uncertain: selectedResume.source_review_required }"><div><small>逐檔來源判別</small><strong>{{ sourceLabels[selectedResume.source_platform] || selectedResume.source_platform }} · {{ Math.round((selectedResume.source_confidence || 0) * 100) }}%</strong><p>依據：{{ sourceEvidence(selectedResume) }}</p></div><div v-if="selectedResume.source_review_required" class="source-review-buttons"><button v-for="value in (['p104','p1111','direct','generic'] as ResumeSource[])" :key="value" type="button" class="button secondary" :disabled="saving" @click="reviewResumeSource(value)">{{ sourceLabels[value] }}</button></div></div>
                <div v-if="selectedResume.parse_status === 'pending' || selectedResume.parse_status === 'processing'" class="review-message"><span class="spinner"></span><strong>履歷正在等待解析</strong><p>解析完成後即可在此校對欄位。</p></div>
                <div v-else-if="selectedResume.parse_status !== 'confirmed'" class="review-form">
                  <label :class="{ 'low-confidence': fieldNeedsReview('name') }">姓名 *<input v-model="parsedForm.name"></label><label :class="{ 'low-confidence': fieldNeedsReview('email') }">Email<input v-model="parsedForm.email" type="email"></label><label :class="{ 'low-confidence': fieldNeedsReview('phone') }">電話<input v-model="parsedForm.phone"></label><label :class="{ 'low-confidence': fieldNeedsReview('city') }">居住地<input v-model="parsedForm.city"></label><label :class="{ 'low-confidence': fieldNeedsReview('current_title') }">目前職稱<input v-model="parsedForm.current_title"></label><label :class="{ 'low-confidence': fieldNeedsReview('total_years') }">總年資<input v-model.number="parsedForm.total_years" type="number" min="0" step="0.5"></label><label class="wide" :class="{ 'low-confidence': fieldNeedsReview('skills') }">技能（逗號分隔）<textarea :value="normalizeSkills(parsedForm.skills).join(', ')" rows="2" @input="parsedForm.skills = ($event.target as HTMLTextAreaElement).value.split(/[,，]/)"></textarea></label><label v-if="selectedResume.resume_text" class="wide">解析原文（僅供校對）<textarea :value="selectedResume.resume_text" rows="7" readonly></textarea></label>
                  <div v-if="selectedResume.error_message" class="inline-error wide"><strong>解析錯誤</strong>{{ selectedResume.error_message }}</div>
                </div>
                <div v-else class="review-message"><strong>這份履歷已確認入庫</strong><p>人才編號已建立，確認後的履歷不可再次編輯。</p></div>
                <footer v-if="selectedResume.parse_status !== 'confirmed'" class="review-actions"><button v-if="['pending','failed'].includes(selectedResume.parse_status)" class="button secondary" data-testid="resume-reparse" :disabled="saving" @click="reparse(selectedResume)">{{ selectedResume.parse_status === 'pending' ? '立即解析' : '重新解析' }}</button><span></span><button class="button secondary" :disabled="saving || ['pending','processing'].includes(selectedResume.parse_status)" @click="saveParsed(false)">儲存校對</button><button class="button primary" data-testid="resume-confirm" :disabled="saving || selectedResume.source_review_required || ['pending','processing'].includes(selectedResume.parse_status)" @click="saveParsed(true)">{{ selectedResume.source_review_required ? '請先確認來源' : '確認並寫入人才庫' }}</button></footer>
              </template>
              <div v-else class="empty review-empty"><h2 id="resume-review-heading">3. 人工校對</h2><strong>從解析佇列選擇一份履歷</strong><p>系統解析結果會顯示在這裡，HR 可修正後再寫入人才庫。</p></div>
            </article>
          </div>
          </div>

          <div v-if="canManualIntake && intakeTab === 'manual'" class="intake-manual-panel">
            <form class="panel intake-manual-card" @submit.prevent="saveCandidate(true)">
              <div class="section-head resume-center-section-head"><div><h2>手動建立人才基本資料</h2><p>直接填寫人才主檔資料並儲存；送出後表單會清空，方便連續建立多筆。可一併指派應徵部門與職缺。</p></div></div>
              <div class="form-grid">
                <label class="wide photo-upload-field"><span>大頭照</span><input ref="candidatePhotoInput" type="file" accept="image/jpeg,image/png,image/webp" @change="selectCandidatePhoto"><small>JPG、PNG 或 WebP，最大 5 MB；儲存後才會上傳。</small></label>
                <label>應徵部門<select v-model="candidateDepartmentId" data-testid="candidate-department-select" :disabled="candidateAssignmentDataUnavailable" @change="selectCandidateDepartment"><option :value="null">尚未指派部門</option><option v-for="department in selectableDepartments" :key="department.id" :value="department.id">{{ department.name }}</option></select><small>選擇後會透過正式應徵紀錄同步給該部門主管。</small></label>
                <label>目標職缺<select v-model="candidateJobId" data-testid="candidate-job-select" :disabled="candidateAssignmentDataUnavailable || candidateDepartmentId === null || !candidateDepartmentJobs.length"><option :value="null" disabled>{{ candidateDepartmentId === null ? '請先選擇應徵部門' : candidateDepartmentJobs.length ? '請選擇該部門職缺' : '此部門目前沒有可用職缺' }}</option><option v-for="job in candidateDepartmentJobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}（{{ jobStatusLabels[job.status] || job.status }}）</option></select><small v-if="candidateDepartmentId !== null && !candidateDepartmentJobs.length" class="assignment-warning" data-testid="candidate-assignment-warning">此部門目前沒有可用職缺；請先建立／開放職缺後再指派。</small><small v-else>指派職缺後，儲存時會同步建立該職缺的應徵紀錄。</small></label>
                <label>姓名 *<input v-model="candidateForm.name" required></label><label>Email<input v-model="candidateForm.email" type="email"></label><label>電話<input v-model="candidateForm.phone"></label><label>地區<input v-model="candidateForm.city"></label><label>目前職稱<input v-model="candidateForm.current_title"></label><label>總年資<input v-model.number="candidateForm.total_years" type="number" min="0" step="0.5"></label><label>來源<select v-model="candidateForm.source"><option value="manual">手動建立</option><option value="p104">104</option><option value="p1111">1111</option><option value="generic">一般履歷</option><option value="direct">自製履歷</option></select></label><label>狀態<select v-model="candidateForm.status"><option v-for="(label,key) in candidateStatusLabels" :key="key" :value="key">{{ label }}</option></select></label>
              </div>
              <footer class="intake-manual-actions"><button type="submit" class="button primary" data-testid="intake-manual-submit" :disabled="saving || candidateAssignmentInvalid">{{ saving ? '儲存中…' : '儲存至資料庫' }}</button></footer>
            </form>
          </div>
        </section>


        <section v-else-if="page === 'jobs'" class="page">
          <div class="page-heading"><div><p class="eyebrow">{{ roleProfile.scope }}</p><h1>{{ authState.user.role === 'manager' ? '我的職缺' : '職缺管理' }}</h1><p>{{ authState.user.role === 'manager' ? '追蹤所屬部門職缺、推薦人才與招募進度。' : '建立、編輯及核准全公司職缺；核准後公開前台才能讀取。' }}</p></div><button v-if="authState.user.role !== 'manager'" class="button primary" @click="openJob()">＋ 建立職缺</button></div>
          <div v-if="jobs.length" class="job-list panel" role="list" data-testid="job-list">
            <div class="job-list-head" aria-hidden="true"><span>職缺</span><span>部門／技能</span><span>地點／需求</span><span>狀態</span><span></span></div>
            <article v-for="job in jobs" :key="job.id" role="listitem">
              <div class="job-list-row" :data-testid="`job-row-${job.id}`">
                <span class="job-list-title"><strong>{{ job.title }}</strong><small>{{ job.req_no }}<template v-if="job.requested_by"> · 部門送交</template> · {{ job.published_at ? `發布 ${date(job.published_at)}` : '尚未發布' }}</small></span>
                <span class="job-list-dept"><strong>{{ job.department_name || (job.department_id ? `部門 #${job.department_id}` : '未設定部門') }}</strong><small>{{ (job.skills || []).slice(0, 3).join('、') || '未列技能' }}</small></span>
                <span class="job-list-meta"><strong>{{ job.work_city || '地點待定' }}</strong><small>需求 {{ job.headcount }} 人</small></span>
                <span class="status" :data-status="job.status">{{ jobStatusLabels[job.status] || job.status }}</span>
                <span class="job-list-actions">
                  <button v-if="authState.user.role !== 'manager'" class="text-button" @click="openJob(job)">編輯</button>
                  <button v-else class="text-button" @click="navigate('matching')">查看人才 →</button>
                  <button v-if="authState.user.role !== 'manager' && ['draft','submitted'].includes(job.status)" class="button primary" :disabled="saving" @click="approveJob(job)">核准</button>
                </span>
              </div>
            </article>
          </div>
          <div v-else-if="loading" class="empty panel"><span class="spinner"></span><p>正在載入職缺…</p></div>
          <div v-else class="empty panel"><strong>目前沒有職缺</strong><p>目前權限範圍內沒有可檢視的職缺。</p></div>
        </section>

        <RecruitmentWorkspace
          v-else-if="page === 'matching'"
          :key="page"
          :jobs="jobs"
          :role="authState.user.role"
          :refresh-key="recruitmentRefreshKey"
          :initial-mode="interviewFocus ? 'interviews' : 'matching'"
          :initial-focus="interviewFocus"
          :can-configure="authState.user.role === 'hr' || authState.user.role === 'admin'"
          :can-configure-weights="['hr', 'admin', 'manager'].includes(authState.user.role)"
          :can-manage="['hr', 'admin', 'manager'].includes(authState.user.role)"
        />
        <ReportsView v-else-if="page === 'reports'" :jobs="jobs" />
        <AdminView v-else-if="page === 'admin'" :current-user="authState.user" />
        <section v-else class="page unavailable-page"><div class="unavailable-icon">⌛</div><p class="eyebrow">NOT CONNECTED</p><h1>{{ pageTitle }}尚未接上後端</h1><p>這個模組目前沒有可持久化的 API，因此先停用所有操作，避免產生「看似成功但未寫入資料庫」的誤解。</p><button class="button secondary" @click="navigate('dashboard')">返回工作總覽</button></section>
      </div>
    </main>

    <div v-if="selectedCandidate" class="drawer-overlay" @click.self="selectedCandidate = null" @keydown.esc="selectedCandidate = null">
      <aside class="detail-drawer candidate-detail-drawer" role="dialog" aria-modal="true" aria-labelledby="candidate-drawer-title" data-testid="candidate-detail-drawer">
        <header class="candidate-detail-header">
          <div class="candidate-detail-identity"><img v-if="candidatePhotoPreviews[selectedCandidate.id]" class="person-avatar large candidate-photo" :src="candidatePhotoPreviews[selectedCandidate.id]" :alt="`${selectedCandidate.name}的大頭照`"><span v-else class="person-avatar large">{{ selectedCandidate.name.slice(0,1) }}</span><div><small>{{ selectedCandidate.code }}</small><h2 id="candidate-drawer-title">{{ selectedCandidate.name }}</h2><p>{{ selectedCandidate.current_title || '未填職稱' }} · {{ selectedCandidate.city || '地區待補' }} · {{ selectedCandidate.total_years ?? 0 }} 年經驗</p></div></div>
          <div class="candidate-detail-header-state"><span class="status" :data-status="selectedCandidate.status">{{ candidateStatusLabels[selectedCandidate.status] || selectedCandidate.status }}</span><button aria-label="關閉人才詳情" @click="selectedCandidate = null">×</button></div>
        </header>

        <nav class="candidate-detail-tabs" role="tablist" aria-label="人才詳情分頁">
          <button id="candidate-tab-profile" type="button" role="tab" :class="{ active: candidateDetailTab === 'profile' }" :aria-selected="candidateDetailTab === 'profile'" aria-controls="candidate-panel-profile" data-testid="candidate-detail-tab-profile" @click="selectCandidateDetailTab('profile')"><span>1</span><span><strong>基本資料</strong><small>聯絡、技能與經歷</small></span></button>
          <button id="candidate-tab-documents" type="button" role="tab" :class="{ active: candidateDetailTab === 'documents' }" :aria-selected="candidateDetailTab === 'documents'" aria-controls="candidate-panel-documents" data-testid="candidate-detail-tab-documents" @click="selectCandidateDetailTab('documents')"><span>2</span><span><strong>履歷與去識別化</strong><small>{{ authState.user.role === 'manager' ? '僅顯示已核准去識別化文件' : `${selectedCandidate.resumes.length} 份原始履歷` }}</small></span></button>
          <button id="candidate-tab-activity" type="button" role="tab" :class="{ active: candidateDetailTab === 'activity' }" :aria-selected="candidateDetailTab === 'activity'" aria-controls="candidate-panel-activity" data-testid="candidate-detail-tab-activity" @click="selectCandidateDetailTab('activity')"><span>3</span><span><strong>應徵與紀錄</strong><small>{{ selectedCandidate.applications.length }} 筆應徵 · {{ candidateActivities.length }} 筆活動</small></span></button>
        </nav>

        <div class="candidate-detail-actionbar">
          <div><button v-if="interviewEntryApplication" class="button primary" data-testid="candidate-enter-interview" @click="enterInterview(selectedCandidate, interviewEntryApplication)">進入面試</button><button class="button primary" data-testid="add-shared-activity" @click="openActivity(selectedCandidate)">＋ {{ authState.user.role === 'manager' ? '新增主管留言' : '新增 HR 留言／聯繫' }}</button><template v-if="authState.user.role !== 'manager'"><button class="button secondary" @click="openCandidate(selectedCandidate)">編輯人才</button><button v-if="selectedCandidate.has_photo" class="button secondary" :disabled="saving" @click="removeCandidatePhoto(selectedCandidate)">移除照片</button></template></div>
          <div v-if="authState.user.role !== 'manager'" class="candidate-detail-danger-actions"><button class="button danger" @click="archiveCandidate(selectedCandidate)">封存</button><button class="button danger" :disabled="saving" @click="removeCandidate(selectedCandidate)">刪除人才</button></div>
        </div>

        <div v-if="error && errorSurface === 'drawer'" class="alert error-alert dialog-alert" role="alert" data-testid="drawer-error"><span>!</span><p><strong>操作未完成</strong>{{ error }}</p><button type="button" aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>

        <div ref="candidateDetailBody" class="detail-body candidate-detail-body">
          <section id="candidate-panel-profile" v-show="candidateDetailTab === 'profile'" role="tabpanel" aria-labelledby="candidate-tab-profile" data-testid="candidate-detail-panel-profile">
            <div class="candidate-section-heading"><div><small>PROFILE</small><h3>基本資料</h3><p>聯絡方式、保存期限與人才經歷集中在這一頁。</p></div></div>
            <div class="detail-grid candidate-contact-grid"><div><small>Email</small><strong>{{ selectedCandidate.email || '未提供' }}</strong></div><div><small>電話</small><strong>{{ selectedCandidate.phone || '未提供' }}</strong></div><div><small>居住地</small><strong>{{ authState.user.role === 'manager' ? '依權限隱藏' : selectedCandidate.city || '未提供' }}</strong></div><div><small>來源</small><strong>{{ sourceLabels[selectedCandidate.source || ''] || selectedCandidate.source || '未知' }}</strong></div></div>
            <p v-if="authState.user.role === 'manager'" class="shared-activity-hint">主管畫面僅顯示遮罩後的聯絡方式；居住地址、生日與原始履歷由 HR 保管。</p>
            <div v-if="authState.user.role === 'hr' || authState.user.role === 'admin'" class="candidate-retention-control drawer-retention-control" :class="{ custom: selectedCandidate.retention_years_override !== null }">
              <div><span>{{ selectedCandidate.retention_years_override === null ? `公司預設 ${retentionPolicyYears} 年` : `個別設定 ${selectedCandidate.retention_years_override} 年` }}</span><small>{{ selectedCandidate.retention_until ? `保存至 ${dateOnly(selectedCandidate.retention_until)}` : '尚未計算到期日' }}</small></div>
              <label>保存年限<select :value="selectedCandidate.retention_years_override ?? ''" :disabled="retentionSavingCandidateId === selectedCandidate.id" :aria-label="`${selectedCandidate.name}的保存年限`" @change="updateCandidateRetention(selectedCandidate, $event)"><option value="">沿用公司預設（{{ retentionPolicyYears }} 年）</option><option v-for="years in retentionYearOptions" :key="years" :value="years">個別設定 {{ years }} 年</option></select></label>
            </div>
            <section class="candidate-profile-block candidate-section-card">
              <div class="candidate-block-heading"><div><h3>技能與人才摘要</h3><p>履歷確認後整理出的工作相關資訊。</p></div><span>{{ selectedCandidate.skills.length }} 項技能</span></div>
              <p v-if="selectedCandidate.summary" class="candidate-summary">{{ selectedCandidate.summary }}</p>
              <div v-if="selectedCandidate.skills.length" class="candidate-skill-list"><span v-for="skill in selectedCandidate.skills" :key="skill">{{ skill }}</span></div>
              <div v-else class="empty compact"><p>尚未整理技能或人才摘要。</p></div>
            </section>
            <section class="candidate-profile-block candidate-history-grid">
              <div class="candidate-section-card"><h3>工作經歷</h3><article v-for="experience in selectedCandidate.experiences" :key="experience.id" class="candidate-history-card"><strong>{{ experience.title }}</strong><span>{{ experience.company }}<template v-if="experience.industry"> · {{ experience.industry }}</template></span><small>{{ experience.start_ym || '未填起始' }}－{{ experience.end_ym || '至今' }}<template v-if="experience.years !== null"> · {{ experience.years }} 年</template></small><p v-if="experience.description">{{ experience.description }}</p></article><div v-if="!selectedCandidate.experiences.length" class="empty compact"><p>尚無結構化工作經歷。</p></div></div>
              <div class="candidate-section-card"><h3>學歷</h3><article v-for="education in selectedCandidate.educations" :key="education.id" class="candidate-history-card"><strong>{{ education.school }}</strong><span>{{ [education.degree, education.major].filter(Boolean).join(' · ') || '未填學位／科系' }}</span><small>{{ education.start_ym || '未填起始' }}－{{ education.end_ym || '未填結束' }}</small></article><div v-if="!selectedCandidate.educations.length" class="empty compact"><p>尚無結構化學歷。</p></div></div>
            </section>
          </section>

          <section id="candidate-panel-documents" v-show="candidateDetailTab === 'documents'" role="tabpanel" aria-labelledby="candidate-tab-documents" data-testid="candidate-resumes">
            <div class="candidate-section-heading"><div><small>FILES &amp; PRIVACY</small><h3>履歷與去識別化檔案</h3><p>{{ authState.user.role === 'manager' ? '主管僅可查看 HR 已核准的去識別化版本。' : '先管理檔案，再決定是否使用已核准版本進行職位分析。' }}</p></div><span v-if="authState.user.role !== 'manager'">{{ selectedCandidate.resumes.length }} 份原始履歷</span></div>
            <div class="candidate-storage-guide" data-testid="candidate-deidentification-storage-guide"><span aria-hidden="true">檔</span><div><strong>原始履歷與去識別化檔案會分開保存</strong><p>展開下方原始履歷後按「上傳此履歷的去識別化檔案」，選擇一份已去識別化的 PDF 檔；系統會新增版本化檔案並自動掃描是否殘留個資，不會覆蓋原始檔。預覽確認並核准後，才能提供職位分析使用。</p></div></div>
            <CandidateAnalysisPanel
              :key="selectedCandidate.id"
              :candidate="selectedCandidate"
              :resumes="selectedCandidate.resumes"
              :jobs="jobs"
              :role="authState.user.role"
              auto-expand-first-document
              @open-parsed-resume="openCandidateResume"
            />
            <div v-if="selectedCandidateResume" class="candidate-resume-preview"><header><div><small>履歷解析內容</small><strong>{{ selectedCandidateResume.original_filename || `履歷 #${selectedCandidateResume.id}` }}</strong></div><button type="button" aria-label="關閉履歷內容" @click="selectedCandidateResume = null">×</button></header><div v-if="candidateResumeHighlights.length" class="resume-highlight-list"><div v-for="item in candidateResumeHighlights" :key="item.label"><small>{{ item.label }}</small><p>{{ item.value }}</p></div></div><pre v-if="selectedCandidateResume.resume_text">{{ selectedCandidateResume.resume_text }}</pre><div v-if="!candidateResumeHighlights.length && !selectedCandidateResume.resume_text" class="empty compact"><p>此履歷尚無可顯示的解析內容。</p></div></div>
          </section>

          <section id="candidate-panel-activity" v-show="candidateDetailTab === 'activity'" role="tabpanel" aria-labelledby="candidate-tab-activity" data-testid="candidate-detail-panel-activity">
            <div class="candidate-section-heading"><div><small>APPLICATIONS &amp; TIMELINE</small><h3>應徵與紀錄</h3><p>職缺申請、HR 聯繫與主管留言集中在同一條工作脈絡。</p></div></div>
            <section class="candidate-profile-block candidate-section-card" data-testid="candidate-application-details">
              <div class="candidate-block-heading"><div><h3>應徵職缺與申請資料</h3><p>目前權限範圍內可查看的正式應徵紀錄。</p></div><span>{{ selectedCandidate.applications.length }} 筆</span></div>
              <div v-if="selectedCandidate.applications.length" class="candidate-application-list">
                <article v-for="application in selectedCandidate.applications" :key="application.id">
                  <header><div><small>{{ application.requisition.department_name || `部門 #${application.requisition.department_id}` }}</small><strong>{{ application.requisition.title }}</strong><span>{{ application.requisition.req_no }} · {{ date(application.applied_at) }}</span></div><b class="status" :data-status="application.status">{{ applicationStatusLabels[application.status] || application.status }}</b></header>
                  <div v-if="canConfirmInterview(application) || isInterviewEntryStatus(application.status)" class="candidate-application-actions">
                    <button v-if="canConfirmInterview(application)" type="button" class="button secondary" :data-testid="`candidate-mark-interview-ready-${application.id}`" :disabled="interviewReadyPendingId !== null" @click="markInterviewReady(application)">{{ interviewReadyPendingId === application.id ? '確認中…' : '確定面試' }}</button>
                    <button v-if="isInterviewEntryStatus(application.status)" type="button" class="button primary" :data-testid="`candidate-enter-interview-${application.id}`" @click="enterInterview(selectedCandidate, application)">進入此職缺面試</button>
                    <small>{{ isInterviewEntryStatus(application.status) ? '會直接帶到這位人才在本職缺的面試卡片，不需要重新搜尋。' : '確定面試後，這筆應徵才會出現在面試流程中。' }}</small>
                  </div>
                  <div v-if="safeExternalUrl(application.portfolio_url) || safeExternalUrl(application.linkedin_url)" class="candidate-links"><a v-if="safeExternalUrl(application.portfolio_url)" :href="safeExternalUrl(application.portfolio_url)" target="_blank" rel="noopener noreferrer">作品集／個人網站 ↗</a><a v-if="safeExternalUrl(application.linkedin_url)" :href="safeExternalUrl(application.linkedin_url)" target="_blank" rel="noopener noreferrer">LinkedIn ↗</a></div>
                  <div v-if="application.cover_letter" class="candidate-cover-letter"><small>求職信</small><p>{{ application.cover_letter }}</p></div>
                  <p v-if="!application.cover_letter && !safeExternalUrl(application.portfolio_url) && !safeExternalUrl(application.linkedin_url)" class="candidate-empty-line">這筆應徵未提供作品連結、LinkedIn 或求職信。</p>
                </article>
              </div>
              <div v-else class="empty compact"><p>目前權限範圍內沒有應徵職缺資料。</p></div>
            </section>
            <section class="candidate-profile-block candidate-section-card candidate-activity-block">
              <div class="candidate-block-heading"><div><h3>HR／主管共享留言與活動</h3><p>主管只能留言，不會直接改動人才狀態。</p></div><span>{{ candidateActivities.length }} 筆</span></div>
              <div v-if="candidateActivities.length" class="timeline shared-timeline" data-testid="shared-activity-timeline">
                <article v-for="activity in candidateActivities" :key="activity.id" :data-author-role="activity.author_role || 'legacy'" :data-testid="`shared-activity-${activity.id}`">
                  <i></i><div class="timeline-author"><strong>{{ activity.author_name || '歷史紀錄' }}</strong><span>{{ activityRoleLabels[activity.author_role || ''] || activity.author_role || '未標示角色' }}<template v-if="activity.author_department_name"> · {{ activity.author_department_name }}</template></span></div><small>{{ date(activity.happened_at) }} · {{ activity.type }}</small><p>{{ activity.content }}</p>
                </article>
              </div>
              <div v-else class="empty compact"><p>尚無共享留言或活動紀錄。</p></div>
            </section>
          </section>
        </div>
      </aside>
    </div>

    <div v-if="resumeFilePreview" class="resume-file-preview-overlay" role="presentation" @click.self="closeResumeFilePreview" @keydown.esc="closeResumeFilePreview">
      <section class="resume-file-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="resume-file-preview-title">
        <header>
          <div><small>{{ resumeFilePreviewIsGenerated ? 'SYSTEM-GENERATED PROFILE' : resumeFilePreviewIsPdf ? 'ORIGINAL PDF' : 'WORD TEXT PREVIEW' }}</small><h2 id="resume-file-preview-title">{{ resumeFilePreview.original_filename || `履歷 #${resumeFilePreview.id}` }}</h2><p>{{ resumeFilePreviewIsGenerated ? '依人才庫資料補建的 PDF，並非應徵者原始上傳檔' : resumeFilePreviewIsPdf ? '應徵者提供的原始 PDF 檔案' : '瀏覽器無法原樣呈現 Word，以下顯示安全的解析文字' }}</p></div>
          <div class="resume-file-preview-actions"><button v-if="authState.user.role !== 'manager'" class="button secondary" type="button" @click="downloadCandidateResume(resumeFilePreview.id, resumeFilePreview.original_filename)">下載原檔</button><button class="resume-file-preview-close" type="button" aria-label="關閉履歷預覽" @click="closeResumeFilePreview">×</button></div>
        </header>
        <div v-if="resumeFilePreviewIsPdf && resumeFilePreviewUrl" class="resume-file-preview-canvas">
          <iframe :src="resumeFilePreviewUrl" :title="`${resumeFilePreview.original_filename || '履歷'}預覽`"></iframe>
        </div>
        <div v-else class="resume-word-preview">
          <div class="resume-preview-notice"><strong>Word 預覽為解析文字</strong><span>DOC／DOCX 的字型、圖片與排版可能和原始檔不同；需要核對版面時請使用「下載原檔」。</span></div>
          <div v-if="resumeFilePreviewHighlights.length" class="resume-highlight-list"><div v-for="item in resumeFilePreviewHighlights" :key="item.label"><small>{{ item.label }}</small><p>{{ item.value }}</p></div></div>
          <pre v-if="resumeFilePreview.resume_text">{{ resumeFilePreview.resume_text }}</pre>
          <div v-if="!resumeFilePreviewHighlights.length && !resumeFilePreview.resume_text" class="empty compact"><strong>沒有可顯示的解析文字</strong><p>請下載原始 Word 檔案查看完整內容。</p></div>
        </div>
        <footer><span>預覽與下載都會依照登入權限判斷，且不公開檔案網址。</span><button class="button primary" type="button" @click="closeResumeFilePreview">關閉預覽</button></footer>
      </section>
    </div>

    <div v-if="dialog" class="modal-overlay" @click.self="dialog = null" @keydown.esc="dialog = null"><form class="modal-card" role="dialog" aria-modal="true" aria-labelledby="app-dialog-title" @submit.prevent="dialog === 'candidate' ? saveCandidate() : dialog === 'activity' ? saveActivity() : saveJob()"><header><div><small>{{ dialog === 'candidate' ? '儲存至 candidates 資料表' : '資料會直接寫入 API' }}</small><h2 id="app-dialog-title">{{ dialog === 'candidate' ? (editingCandidate ? `編輯人才（DB #${editingCandidate.id}）` : '新增人才') : dialog === 'activity' ? (authState.user.role === 'manager' ? '新增主管留言' : '新增 HR 留言／聯繫紀錄') : (editingJob ? '編輯職缺' : '建立職缺') }}</h2></div><button type="button" aria-label="關閉編輯視窗" @click="dialog = null">×</button></header>
      <div v-if="dialog === 'candidate'" class="form-grid">
        <label class="wide photo-upload-field"><span>大頭照</span><input ref="candidatePhotoInput" type="file" accept="image/jpeg,image/png,image/webp" @change="selectCandidatePhoto"><small>JPG、PNG 或 WebP，最大 5 MB；儲存後才會上傳。</small></label>
        <div v-if="editingCandidateAssignments.length" class="wide candidate-assignment-list"><small>目前應徵紀錄</small><span v-for="application in editingCandidateAssignments" :key="application.id">{{ application.requisition.department_name || `部門 #${application.requisition.department_id}` }} · {{ application.requisition.title }}</span></div>
        <label>應徵部門<select v-model="candidateDepartmentId" data-testid="candidate-department-select" :disabled="candidateAssignmentDataUnavailable" @change="selectCandidateDepartment"><option :value="null">{{ editingCandidateApplication ? '保留既有指派，不另行變更' : '尚未指派部門' }}</option><option v-for="department in selectableDepartments" :key="department.id" :value="department.id">{{ department.name }}</option></select><small v-if="candidateAssignmentDataUnavailable" class="assignment-warning">應徵資料讀取失敗，本次不開放變更部門指派。</small><small v-else>選擇後會透過正式應徵紀錄同步給該部門主管。</small></label>
        <label>目標職缺<select v-model="candidateJobId" data-testid="candidate-job-select" :disabled="candidateAssignmentDataUnavailable || candidateDepartmentId === null || !candidateDepartmentJobs.length"><option :value="null" disabled>{{ candidateDepartmentId === null ? '請先選擇應徵部門' : candidateDepartmentJobs.length ? '請選擇該部門職缺' : '此部門目前沒有可用職缺' }}</option><option v-for="job in candidateDepartmentJobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}（{{ jobStatusLabels[job.status] || job.status }}）</option></select><small v-if="candidateDepartmentId !== null && !candidateDepartmentJobs.length" class="assignment-warning" data-testid="candidate-assignment-warning">此部門目前沒有可用職缺；請先建立／開放職缺後再指派。</small><small v-else>尚未進入面試的最近一筆會改派；已有面試／錄取歷史時則保留舊紀錄並新增應徵。</small></label>
        <label>姓名 *<input v-model="candidateForm.name" required></label><label>Email<input v-model="candidateForm.email" type="email"></label><label>電話<input v-model="candidateForm.phone"></label><label>地區<input v-model="candidateForm.city"></label><label>目前職稱<input v-model="candidateForm.current_title"></label><label>總年資<input v-model.number="candidateForm.total_years" type="number" min="0" step="0.5"></label><label>來源<select v-model="candidateForm.source"><option value="manual">手動建立</option><option value="p104">104</option><option value="p1111">1111</option><option value="generic">一般履歷</option><option value="direct">自製履歷</option></select></label><label>狀態<select v-model="candidateForm.status"><option v-for="(label,key) in candidateStatusLabels" :key="key" :value="key">{{ label }}</option></select></label>
      </div>
      <div v-else-if="dialog === 'activity'" class="form-grid"><label>紀錄類型<select v-model="activityForm.type" data-testid="activity-type"><option v-if="authState.user.role === 'manager'">主管留言</option><template v-else><option>HR 留言</option><option>電話聯繫</option><option>Email</option><option>面談</option><option>其他</option></template></select></label><label v-if="authState.user.role !== 'manager'">後續狀態<select v-model="activityForm.next_status"><option v-for="(label,key) in candidateStatusLabels" :key="key" :value="key">{{ label }}</option></select></label><label class="wide">{{ authState.user.role === 'manager' ? '給 HR 的主管留言' : '給部門主管的 HR 留言／活動紀錄' }} *<textarea v-model="activityForm.content" data-testid="activity-content" rows="6" required :placeholder="authState.user.role === 'manager' ? '記錄主管觀察、建議或需要 HR 協助的事項…' : '記錄聯繫結果、建議與希望部門主管留意的事項…'"></textarea></label></div>
      <div v-else class="form-grid"><label>職缺編號 *<input v-model="jobForm.req_no" required :disabled="!!editingJob"></label><label>職缺名稱 *<input v-model="jobForm.title" required></label><label>部門 ID<input v-model.number="jobForm.department_id" type="number" min="1"></label><label>工作地點<input v-model="jobForm.work_city"></label><label>聘僱類型<select v-model="jobForm.employment_type"><option value="full_time">正職</option><option value="contract">約聘</option><option value="part_time">兼職</option></select></label><label>需求人數<input v-model.number="jobForm.headcount" type="number" min="1"></label><label>月薪下限<input v-model.number="jobForm.salary_min" type="number" min="0"></label><label>月薪上限<input v-model.number="jobForm.salary_max" type="number" min="0"></label><label class="wide">技能（逗號分隔）<input v-model="jobForm.skillsText"></label><label class="wide">職缺摘要<textarea v-model="jobForm.summary" rows="2"></textarea></label><label class="wide">職務說明 *<textarea v-model="jobForm.jd" rows="7" required></textarea></label><label>流程狀態<select v-model="jobForm.status"><option v-for="(label,key) in jobStatusLabels" :key="key" :value="key">{{ label }}</option></select></label><label class="wide"><input v-model="jobForm.blind_review_enabled" class="inline-check" type="checkbox" data-testid="job-blind-review-disclosure" :true-value="false" :false-value="true" :disabled="!blindReviewEditable">面試評分揭露規則：開放 HR 與主管即時互看彼此評分<small>不勾選（預設）為盲評：雙方先各自評分，等 HR 與主管都提交後才互相公開評分、觀察紀錄、面談總結與錄取建議，避免先看到對方分數影響判斷。勾選後 HR 與主管即時互看彼此評分。</small><small v-if="blindReviewLocked" class="assignment-warning" data-testid="job-blind-review-note">已有面試提交紀錄，設定不可再變更。</small><small v-else-if="!editingJob" data-testid="job-blind-review-note">新職缺一律先採盲評，建立後可由人資調整。</small><small v-else-if="!blindReviewEditable" class="assignment-warning" data-testid="job-blind-review-note">僅人資可變更此設定，目前為唯讀。</small></label><div class="wide composite-weight-field" data-testid="job-composite-weights"><b>綜合參考分權重</b><small>面試卡片「六項分數總覽」第 ⑥ 項的加權來源。數值代表相對重要程度，總和不必剛好 100，儲存時會依比例正規化。</small><div class="composite-weight-grid"><label v-for="key in compositeWeightKeys" :key="key"><span>{{ compositeWeightLabels[key] }}</span><input v-model.number="compositeWeightForm[key]" :data-testid="`job-composite-weight-${key}`" type="number" min="0" max="100" step="1" :disabled="!compositeWeightsEditable"></label></div><small :class="{ 'assignment-warning': compositeWeightInvalid }" data-testid="job-composite-weight-total">目前合計 {{ compositeWeightTotal }}<template v-if="compositeWeightInvalid">（至少一項必須大於 0）</template></small><small v-if="!editingJob" data-testid="job-composite-weight-note">新職缺一律先採預設權重 20／15／25／15／25，建立後可由人資調整。</small><small v-else-if="!compositeWeightsEditable" class="assignment-warning" data-testid="job-composite-weight-note">僅人資可變更此設定，目前為唯讀。</small><small v-else data-testid="job-composite-weight-note">儲存後，此職缺已算出的綜合參考分會立即以新權重重算。</small></div></div>
      <div v-if="dialog === 'job' && jobComplianceFindings.length" class="jd-compliance-alert" role="alert" data-testid="jd-compliance-alert">
        <div class="jd-compliance-head"><span aria-hidden="true">⚠</span><div><strong>可能涉及就業歧視用語（{{ jobComplianceFindings.length }} 項）</strong><small>依就業服務法第 5 條、中高齡就業促進法、性別平等工作法，職缺不得限制受保護特徵。以下為系統偵測提示，仍需人工／法務判斷，警示不會阻擋儲存。</small></div></div>
        <ul class="jd-compliance-list"><li v-for="(finding, index) in jobComplianceFindings" :key="index"><span class="jd-compliance-tag">{{ jobComplianceLabel(finding.category) }}</span><span class="jd-compliance-matched">「{{ finding.matched }}」</span><small class="jd-compliance-where">（{{ finding.field === 'title' ? '職缺名稱' : finding.field === 'summary' ? '職缺摘要' : '職務說明' }}）</small><p>{{ finding.suggestion }}</p></li></ul>
      </div>
      <!-- Sits directly above the submit button, where the eye already is; type="button" keeps the dismiss out of the form's submit path. -->
      <div v-if="error && errorSurface === 'modal'" class="alert error-alert dialog-alert" role="alert" data-testid="dialog-error"><span>!</span><p><strong>操作未完成</strong>{{ error }}</p><button type="button" aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>
      <footer><button type="button" class="button secondary" @click="dialog = null">取消</button><button type="submit" class="button primary" data-testid="activity-submit" :disabled="saving || (dialog === 'candidate' && candidateAssignmentInvalid)">{{ saving ? '儲存中…' : dialog === 'activity' ? '送出共享留言' : '儲存至資料庫' }}</button></footer></form></div>

    <Transition name="toast"><div v-if="notice" class="toast" role="status" aria-live="polite"><span>✓</span>{{ notice }}</div></Transition>
  </div>
</template>

<style scoped>
/* 應徵狀態 column added to the talent list; the shared grid in style.css only declares six tracks. */
.talent-list-head,.talent-list-row{grid-template-columns:minmax(185px,1.35fr) minmax(115px,.95fr) minmax(105px,.8fr) minmax(120px,.95fr) minmax(100px,.75fr) minmax(72px,.55fr) 58px}
.talent-list-application{min-width:0}.talent-list-application>.status{max-width:100%;overflow:hidden;text-overflow:ellipsis}
.status[data-status="interview_ready"]{background:#e2f2eb;color:#28745f}.status[data-status="interview"]{background:#e4eff9;color:#3472a6}
@media(max-width:1100px){.talent-list-head,.talent-list-row{grid-template-columns:minmax(0,1fr) auto}.talent-list-application{grid-column:1;grid-row:5}.talent-list-open{grid-row:2/6}}
@media(max-width:560px){.talent-list-application{grid-column:1/-1}}
.candidate-application-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:11px;padding-top:11px;border-top:1px dashed #dbe8e4}.candidate-application-actions .button{height:34px;font-size:11px}.candidate-application-actions>small{flex:1;min-width:150px;color:#7a8d87;font-size:11px;line-height:1.5}
.intake-tab-bar{display:inline-flex;gap:6px;margin:0 0 16px;padding:5px;border:1px solid #dbe7e3;border-radius:12px;background:#eef4f2}.intake-tab{min-width:132px;padding:9px 18px;border:1px solid transparent;border-radius:9px;background:transparent;color:#5c716b;font-size:12px;font-weight:800;cursor:pointer}.intake-tab:hover{color:#165f55}.intake-tab.active{border-color:#71b8aa;background:#fff;color:#165f55;box-shadow:0 4px 12px rgba(24,95,84,.08)}
.intake-manual-panel{display:block}.intake-manual-card{padding:18px 20px 16px}.intake-manual-card .section-head{margin-bottom:14px}.intake-manual-actions{display:flex;justify-content:flex-end;margin-top:16px}
.manager-job-target{display:grid;gap:6px;margin:14px 16px 12px;padding:13px;border:1px solid #cfe2dc;border-radius:10px;background:#f8fbfa;color:#496c66;font-size:9px;font-weight:700}.manager-job-target select{width:100%;height:40px;border:1px solid #c9dcd7;border-radius:8px;background:#fff;padding:0 11px;color:#274f49;font-size:10px}.manager-job-target small{color:#7f918d;font-weight:400}.manager-job-target .target-warning{color:#a25e38}.dropzone:disabled{cursor:not-allowed;opacity:.62}.resume-target-summary{margin:14px 17px 0;padding:12px 14px;border:1px solid #c9e4da;border-radius:9px;background:#eef8f4;color:#285f56}.resume-target-summary small,.resume-target-summary strong{display:block}.resume-target-summary small{font-size:8px;color:#6e877f}.resume-target-summary strong{margin-top:3px;font-size:11px}.resume-target-summary p{margin:5px 0 0;font-size:8px;color:#668078}
.shared-activity-hint{margin:-5px 0 14px;color:#70827e;font-size:9px;line-height:1.6}.shared-timeline article{padding:12px 12px 12px 23px;border:1px solid #e0ebe7;border-radius:9px;background:#fbfdfc}.shared-timeline article[data-author-role="hr"]{border-left:3px solid #19917e}.shared-timeline article[data-author-role="manager"]{border-left:3px solid #d59b32}.timeline-author{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:4px}.timeline-author strong{color:#174f48;font-size:10px}.timeline-author span{padding:3px 6px;border-radius:99px;background:#edf5f2;color:#56706a;font-size:7px}.shared-timeline article>small{display:block;color:#80908c}.shared-timeline article>p{white-space:pre-wrap;overflow-wrap:anywhere}
.candidate-assignment-list{display:flex;flex-wrap:wrap;gap:6px;padding:10px 12px;border:1px solid #d8e7e2;border-radius:9px;background:#f8fbfa}.candidate-assignment-list>small{flex-basis:100%;color:#6e827d}.candidate-assignment-list>span{padding:5px 8px;border-radius:99px;background:#e6f2ee;color:#27675e;font-size:8px}.form-grid label>small{display:block;margin-top:5px;color:#788b86;font-size:8px;line-height:1.45}.form-grid label>.assignment-warning{color:#a45445;font-weight:700}.form-grid label>.inline-check{display:inline-block;width:auto;height:auto;margin:0 6px 0 0;padding:0;vertical-align:-1px}.form-grid label>.inline-check:disabled{cursor:not-allowed;opacity:.55}
/* Composite-score weights: a bordered sub-panel inside the job form, same treatment as
   .candidate-assignment-list, with the five inputs on one row that wraps on narrow cards. */
.composite-weight-field{padding:10px 12px;border:1px solid #d8e7e2;border-radius:9px;background:#f8fbfa}.composite-weight-field>b{display:block;color:#27675e;font-size:10px;font-weight:800}.composite-weight-field>small{display:block;margin-top:5px;color:#788b86;font-size:8px;line-height:1.45}.composite-weight-field>.assignment-warning{color:#a45445;font-weight:700}
.composite-weight-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(96px,1fr));gap:8px;margin-top:8px}.composite-weight-grid label{display:flex;flex-direction:column;gap:4px}.composite-weight-grid span{color:#4a5f5a;font-size:8px;font-weight:700}.composite-weight-grid input:disabled{cursor:not-allowed;opacity:.55}
/* Same .error-alert treatment as the page banner, re-flowed for the modal card and the drawer column. */
.dialog-alert{flex:0 0 auto;margin:14px 16px 4px}.dialog-alert>p{overflow-wrap:anywhere}
.jd-compliance-alert{margin:14px 16px 4px;padding:13px 15px;border:1px solid #e4c579;border-radius:11px;background:#fff8e8;color:#6e561f}.jd-compliance-head{display:flex;align-items:flex-start;gap:11px}.jd-compliance-head>span{flex:0 0 auto;width:26px;height:26px;display:grid;place-items:center;border-radius:7px;background:#e6a532;color:#fff;font-size:14px;font-weight:900}.jd-compliance-head strong{display:block;color:#6a4d13;font-size:12px}.jd-compliance-head small{display:block;margin-top:4px;color:#8a7233;font-size:9px;line-height:1.6}.jd-compliance-list{list-style:none;margin:12px 0 0;padding:0;display:grid;gap:9px}.jd-compliance-list>li{padding:9px 11px;border:1px solid #ecd6a0;border-radius:9px;background:#fffdf6}.jd-compliance-tag{display:inline-block;padding:3px 7px;border-radius:99px;background:#e6a532;color:#fff;font-size:8px;font-weight:800;vertical-align:middle}.jd-compliance-matched{margin-left:6px;color:#a2381f;font-size:10px;font-weight:800}.jd-compliance-where{margin-left:4px;color:#94805a;font-size:8px}.jd-compliance-list p{margin:6px 0 0;color:#5f6f4e;font-size:9px;line-height:1.6}
.candidate-profile-block{margin:18px 0;padding-top:4px}.candidate-profile-block>h3,.candidate-history-grid h3{margin:0 0 10px}.candidate-application-list,.candidate-resume-list{display:grid;gap:9px}.candidate-application-list>article,.candidate-resume-list>article,.candidate-history-card{padding:12px;border:1px solid #dce9e5;border-radius:10px;background:#fbfdfc}.candidate-application-list article>header{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.candidate-application-list header div>*{display:block}.candidate-application-list header small,.candidate-application-list header span,.candidate-history-card small,.candidate-history-card span,.candidate-resume-list span{color:#778a85;font-size:8px}.candidate-application-list header strong,.candidate-history-card strong,.candidate-resume-list strong{margin:3px 0;color:#214f49;font-size:10px}.candidate-links{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.candidate-links a,.candidate-resume-list a{color:#087b6c;font-size:8px;font-weight:700;text-decoration:none}.candidate-cover-letter{margin-top:10px;padding:9px;border-radius:8px;background:#f1f7f5}.candidate-cover-letter small{color:#6f827d;font-size:8px}.candidate-cover-letter p,.candidate-summary,.candidate-history-card p{margin:5px 0 0;white-space:pre-wrap;color:#405f59;font-size:9px;line-height:1.65}.candidate-empty-line{margin:8px 0 0;color:#879691;font-size:8px}.candidate-skill-list{display:flex;flex-wrap:wrap;gap:6px}.candidate-skill-list span{padding:5px 8px;border-radius:99px;background:#e6f2ee;color:#27675e;font-size:8px;font-weight:700}.candidate-history-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.candidate-history-card{margin-bottom:8px}.candidate-history-card>*{display:block}.candidate-resume-list>article{display:flex;align-items:center;justify-content:space-between;gap:10px}.candidate-resume-list article>div:first-child>*{display:block}.candidate-resume-list article>div:last-child{display:flex;align-items:center;gap:8px}.candidate-resume-preview{margin-top:10px;padding:12px;border:1px solid #cfe3dc;border-radius:10px;background:#f4faf8}.candidate-resume-preview>header{display:flex;align-items:center;justify-content:space-between}.candidate-resume-preview>header div>*{display:block}.candidate-resume-preview>header button{border:0;background:none;color:#607772;font-size:18px}.resume-highlight-list{display:grid;gap:7px;margin-top:10px}.resume-highlight-list>div{padding:8px;border-radius:7px;background:#fff}.resume-highlight-list small{color:#71847f;font-size:7px}.resume-highlight-list p{margin:3px 0 0;white-space:pre-wrap;color:#345b54;font-size:8px;line-height:1.55}.candidate-resume-preview pre{max-height:240px;overflow:auto;margin:10px 0 0;padding:10px;border-radius:7px;background:#173b36;color:#e8f5f1;white-space:pre-wrap;font:8px/1.6 monospace}@media(max-width:700px){.candidate-history-grid{grid-template-columns:1fr}.candidate-resume-list>article{align-items:flex-start;flex-direction:column}}
.resume-origin-badge{display:inline-flex!important;width:max-content;margin-top:5px;padding:3px 6px;border-radius:99px;font-size:7px!important;font-style:normal;font-weight:800}.resume-origin-badge.generated{background:#e1f2eb;color:#1b7463}.resume-origin-badge.missing{background:#fff0df;color:#9b612c}.candidate-resume-file-error{margin:9px 0 0}.resume-preview-trigger{font-weight:800}.resume-file-preview-overlay{position:fixed;inset:0;z-index:1200;display:grid;place-items:center;padding:18px;background:rgba(10,34,31,.7);backdrop-filter:blur(4px)}.resume-file-preview-dialog{display:flex;flex-direction:column;width:min(1120px,100%);height:min(92vh,920px);overflow:hidden;border-radius:16px;background:#fff;box-shadow:0 28px 90px rgba(5,27,24,.4)}.resume-file-preview-dialog>header{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:17px 20px;border-bottom:1px solid #dfe9e6}.resume-file-preview-dialog>header small{color:#218174;font-size:8px;font-weight:800;letter-spacing:1px}.resume-file-preview-dialog>header h2{margin:4px 0;font-size:17px;color:#173f3a}.resume-file-preview-dialog>header p{margin:0;color:#71837f;font-size:9px}.resume-file-preview-actions{display:flex;align-items:center;gap:8px}.resume-file-preview-close{width:38px;height:38px;border:0;background:transparent;color:#647672;font-size:26px}.resume-file-preview-canvas{flex:1;min-height:0;padding:12px;background:#dce3e1}.resume-file-preview-canvas iframe{width:100%;height:100%;border:0;border-radius:7px;background:#fff}.resume-word-preview{flex:1;min-height:0;overflow:auto;padding:18px 22px;background:#f5f8f7}.resume-preview-notice{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid #ead9b8;border-radius:9px;background:#fff8e9;color:#765c2c}.resume-preview-notice strong{font-size:10px;white-space:nowrap}.resume-preview-notice span{font-size:9px;line-height:1.55}.resume-word-preview .resume-highlight-list{grid-template-columns:repeat(2,minmax(0,1fr))}.resume-word-preview pre{margin:12px 0 0;padding:16px;border:1px solid #dce7e3;border-radius:9px;background:#fff;color:#294f49;white-space:pre-wrap;overflow-wrap:anywhere;font:10px/1.75 monospace}.resume-file-preview-dialog>footer{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 18px;border-top:1px solid #dfe9e6}.resume-file-preview-dialog>footer span{color:#71837f;font-size:8px}@media(max-width:700px){.resume-file-preview-overlay{padding:0}.resume-file-preview-dialog{width:100%;height:100vh;border-radius:0}.resume-file-preview-dialog>header{align-items:stretch;flex-direction:column}.resume-file-preview-actions{justify-content:space-between}.resume-word-preview .resume-highlight-list{grid-template-columns:1fr}.resume-file-preview-dialog>footer span{display:none}}

/* Candidate detail workspace: three focused views instead of one long, narrow drawer. */
.candidate-detail-drawer{width:min(880px,calc(100vw - 28px));display:flex;flex-direction:column;overflow:hidden;background:#f5f8f7}.candidate-detail-header{flex:0 0 auto;align-items:center;padding:18px 22px!important;background:#fff}.candidate-detail-identity{min-width:0;align-items:center}.candidate-detail-identity>div{min-width:0}.candidate-detail-header h2{font-size:21px!important;color:#143f39}.candidate-detail-header p{margin-top:4px!important;font-size:12px!important}.candidate-detail-header-state{display:flex;align-items:center;gap:13px}.candidate-detail-header-state>button{width:38px;height:38px;border:0;background:transparent;color:#687b77;font-size:27px}.candidate-detail-header-state>.status{font-size:11px;padding:6px 10px}
.candidate-detail-tabs{flex:0 0 auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:11px 16px;border-bottom:1px solid #dde8e5;background:#eef4f2}.candidate-detail-tabs button{min-width:0;min-height:58px;display:flex;align-items:center;gap:10px;padding:9px 12px;border:1px solid transparent;border-radius:10px;background:transparent;color:#5c716b;text-align:left}.candidate-detail-tabs button:hover{background:#fff}.candidate-detail-tabs button.active{border-color:#71b8aa;background:#fff;color:#165f55;box-shadow:0 4px 12px rgba(24,95,84,.08)}.candidate-detail-tabs button>span:first-child{width:29px;height:29px;flex:0 0 auto;display:grid;place-items:center;border-radius:50%;background:#dce9e5;color:#456c64;font-size:12px;font-weight:800}.candidate-detail-tabs button.active>span:first-child{background:#168476;color:#fff}.candidate-detail-tabs strong,.candidate-detail-tabs small{display:block}.candidate-detail-tabs strong{font-size:13px}.candidate-detail-tabs small{margin-top:2px;color:#7a8d87;font-size:11px}
.candidate-detail-actionbar{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 18px;border-bottom:1px solid #e0e9e7;background:#fff}.candidate-detail-actionbar>div{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.candidate-detail-actionbar .button{height:36px;font-size:12px}.candidate-detail-danger-actions{margin-left:auto}.candidate-detail-body{flex:1;min-height:0;overflow:auto;padding:22px 24px 38px;scrollbar-gutter:stable}.candidate-section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:15px}.candidate-section-heading small{color:#218074;font-size:11px!important;font-weight:900;letter-spacing:1px}.candidate-section-heading h3{margin:3px 0;color:#174b44;font-size:20px}.candidate-section-heading p{margin:0;color:#6b7f79;font-size:13px;line-height:1.55}.candidate-section-heading>span{padding:6px 9px;border-radius:99px;background:#e3f1ed;color:#236b60;font-size:12px;font-weight:800;white-space:nowrap}.candidate-contact-grid{grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.candidate-contact-grid>div{min-height:68px;padding:12px 13px;border:1px solid #e1e9e7;background:#fff}.candidate-contact-grid small{font-size:11px!important}.candidate-contact-grid strong{margin-top:5px;font-size:13px;overflow-wrap:anywhere}.candidate-section-card{padding:16px;border:1px solid #dce8e4;border-radius:12px;background:#fff}.candidate-block-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:12px}.candidate-block-heading h3{margin:0;color:#1b5049;font-size:15px}.candidate-block-heading p{margin:4px 0 0;color:#71847e;font-size:12px}.candidate-block-heading>span{padding:5px 8px;border-radius:99px;background:#edf4f2;color:#55726b;font-size:11px;font-weight:800;white-space:nowrap}.candidate-detail-body .candidate-profile-block{margin:14px 0}.candidate-detail-body .candidate-summary{margin:0 0 12px;font-size:13px;line-height:1.7}.candidate-detail-body .candidate-skill-list span{padding:6px 9px;font-size:12px}.candidate-detail-body .candidate-history-grid{gap:14px}.candidate-detail-body .candidate-history-card{padding:12px 13px;background:#f8fbfa}.candidate-detail-body .candidate-history-card strong{font-size:14px}.candidate-detail-body .candidate-history-card span,.candidate-detail-body .candidate-history-card small{margin-top:3px;font-size:12px}.candidate-detail-body .candidate-history-card p{font-size:12px}.candidate-storage-guide{display:flex;align-items:flex-start;gap:13px;padding:14px 15px;border:1px solid #e4ca91;border-radius:11px;background:#fff9ec;color:#6f572e}.candidate-storage-guide>span{width:36px;height:36px;flex:0 0 auto;display:grid;place-items:center;border-radius:9px;background:#e9b956;color:#fff;font-size:13px;font-weight:900}.candidate-storage-guide strong{display:block;color:#684e22;font-size:14px}.candidate-storage-guide p{margin:4px 0 0;font-size:12px;line-height:1.65}.candidate-detail-body :deep(.candidate-analysis-panel){margin:14px 0 0}.candidate-detail-body .candidate-resume-preview{margin-top:14px;padding:15px}.candidate-detail-body .candidate-resume-preview header small{font-size:11px}.candidate-detail-body .candidate-resume-preview header strong{font-size:14px}.candidate-detail-body .resume-highlight-list{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.candidate-detail-body .resume-highlight-list small{font-size:11px}.candidate-detail-body .resume-highlight-list p{font-size:12px}.candidate-detail-body .candidate-application-list{gap:10px}.candidate-detail-body .candidate-application-list>article{padding:14px}.candidate-detail-body .candidate-application-list header small,.candidate-detail-body .candidate-application-list header span{font-size:11px}.candidate-detail-body .candidate-application-list header strong{font-size:14px}.candidate-detail-body .candidate-links a,.candidate-detail-body .candidate-cover-letter small,.candidate-detail-body .candidate-empty-line{font-size:11px}.candidate-detail-body .candidate-cover-letter p{font-size:12px}.candidate-activity-block{margin-bottom:0!important}.candidate-detail-body .shared-timeline{display:grid;gap:9px}.candidate-detail-body .shared-timeline article{padding:13px 14px 13px 24px}.candidate-detail-body .timeline-author strong{font-size:13px}.candidate-detail-body .timeline-author span{font-size:10px}.candidate-detail-body .shared-timeline article>small{font-size:11px!important}.candidate-detail-body .shared-timeline article>p{font-size:12px!important}
@media(max-width:900px){.candidate-detail-drawer{width:100%}.candidate-detail-actionbar{align-items:flex-start;flex-direction:column}.candidate-detail-danger-actions{margin-left:0}.candidate-contact-grid{grid-template-columns:1fr 1fr}}
@media(max-width:620px){.candidate-detail-header{padding:14px 16px!important}.candidate-detail-header-state>.status{display:none}.candidate-detail-tabs{gap:5px;padding:8px}.candidate-detail-tabs button{justify-content:center;min-height:48px;padding:8px}.candidate-detail-tabs button>span:first-child,.candidate-detail-tabs small{display:none}.candidate-detail-tabs strong{font-size:12px;text-align:center}.candidate-detail-actionbar{padding:9px 12px}.candidate-detail-actionbar>div{width:100%}.candidate-detail-actionbar .button{flex:1}.candidate-detail-body{padding:17px 14px 28px}.candidate-contact-grid,.candidate-detail-body .candidate-history-grid,.candidate-detail-body .resume-highlight-list{grid-template-columns:1fr}.candidate-section-heading{align-items:flex-start;flex-direction:column}.candidate-storage-guide{padding:12px}.candidate-detail-body :deep(.candidate-analysis-panel){margin-top:12px}}
</style>
