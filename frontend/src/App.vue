<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AdminView from './components/AdminView.vue'
import AuthView from './components/AuthView.vue'
import MatchingView from './components/MatchingView.vue'
import ReportsView from './components/ReportsView.vue'
import { authSession } from './services/auth'
import {
  API_BASE,
  hrApi,
  type ActivityDto,
  type CandidateDto,
  type CandidateWrite,
  type ParsedResume,
  type RequisitionDto,
  type RequisitionWrite,
  type ResumeDto,
  type ResumeSource,
} from './services/hrApi'

type Page = 'dashboard' | 'candidates' | 'resumes' | 'jobs' | 'matching' | 'reports' | 'admin'
type Dialog = 'candidate' | 'activity' | 'job' | null

const page = ref<Page>('dashboard')
const authState = authSession.state
const sidebarOpen = ref(false)
const loading = ref(false)
const saving = ref(false)
const apiOnline = ref(false)
const error = ref('')
const notice = ref('')
const lastSync = ref('尚未同步')
const candidates = ref<CandidateDto[]>([])
const resumes = ref<ResumeDto[]>([])
const jobs = ref<RequisitionDto[]>([])
const search = ref('')
const candidateStatus = ref('all')
const resumeStatus = ref('all')
const uploadFiles = ref<File[]>([])
const uploadInput = ref<HTMLInputElement | null>(null)
const intakeInput = ref<HTMLInputElement | null>(null)
const intakeFiles = ref<File[]>([])
const intakeJobId = ref<number | null>(null)
const intakeNotes = ref('')
const intakeDone = ref(false)
const selectedCandidate = ref<CandidateDto | null>(null)
const candidateActivities = ref<ActivityDto[]>([])
const candidatePhotoInput = ref<HTMLInputElement | null>(null)
const candidatePhotoFile = ref<File | null>(null)
const candidatePhotoPreviews = reactive<Record<number, string>>({})
const selectedResume = ref<ResumeDto | null>(null)
const parsedForm = reactive<ParsedResume>({})
const dialog = ref<Dialog>(null)
const editingCandidate = ref<CandidateDto | null>(null)
const editingJob = ref<RequisitionDto | null>(null)
const candidateForm = reactive<CandidateWrite>({ name: '', email: '', phone: '', city: '', current_title: '', total_years: 0, source: 'manual', status: 'new' })
const intakeForm = reactive<CandidateWrite>({ name: '', email: '', phone: '', city: '', current_title: '', total_years: 0, source: 'manual', status: 'new' })
const activityForm = reactive({ type: '電話聯繫', content: '', next_status: 'contacted' })
const jobForm = reactive({
  req_no: '', title: '', department_id: null as number | null, employment_type: 'full_time', work_city: '台北市',
  jd: '', summary: '', skillsText: '', salary_min: null as number | null, salary_max: null as number | null,
  salary_type: 'monthly', headcount: 1, status: 'draft',
})

const allNav: { id: Page; label: string; icon: string; roles: string[] }[] = [
  { id: 'dashboard', label: '工作總覽', icon: '⌂', roles: ['it', 'admin', 'hr', 'manager'] },
  { id: 'candidates', label: '人才庫', icon: '人', roles: ['admin', 'hr', 'manager'] },
  { id: 'resumes', label: '履歷辨識中心', icon: '▤', roles: ['admin', 'hr'] },
  { id: 'jobs', label: '職缺管理', icon: '◇', roles: ['admin', 'hr', 'manager'] },
  { id: 'matching', label: '媒合程度', icon: '◎', roles: ['admin', 'hr', 'manager'] },
  { id: 'reports', label: '招募分析', icon: '⌁', roles: ['admin', 'hr'] },
  { id: 'admin', label: '帳號與權限', icon: '⚙', roles: ['it', 'admin', 'hr'] },
]

const nav = computed(() => allNav.filter(item => item.roles.includes(authState.user?.role || '')))
const roleProfile = computed(() => ({
  it: { label: 'IT 管理員', scope: '系統管理', note: '帳號權限、組織與系統設定，不接觸招募個資' },
  admin: { label: '相容管理員', scope: '系統全域', note: '保留既有管理與招募權限' },
  hr: { label: 'HR 招募夥伴', scope: '全公司資料', note: '所有職缺、人才庫與招募分析' },
  manager: { label: '用人主管', scope: '所屬部門', note: '負責職缺、推薦人才與面試決策' },
}[authState.user?.role || 'manager']))

const pageTitle = computed(() => nav.value.find(item => item.id === page.value)?.label || 'TalentHub')
const filteredCandidates = computed(() => candidates.value.filter(candidate => {
  const q = search.value.trim().toLocaleLowerCase()
  const inSearch = !q || [candidate.name, candidate.email, candidate.phone, candidate.current_title, candidate.city, candidate.source]
    .some(value => String(value || '').toLocaleLowerCase().includes(q))
  return inSearch && (candidateStatus.value === 'all' || candidate.status === candidateStatus.value)
}))
const filteredResumes = computed(() => resumes.value.filter(resume =>
  resumeStatus.value === 'all' || resume.parse_status === resumeStatus.value,
))
const pendingReviewCount = computed(() => resumes.value.filter(r => ['needs_review', 'failed'].includes(r.parse_status)).length)
const activeJobCount = computed(() => jobs.value.filter(j => ['approved', 'sourcing', 'interviewing'].includes(j.status)).length)
const activeCandidateCount = computed(() => candidates.value.filter(candidate => candidate.status !== 'archived').length)
const priorityCandidateCount = computed(() => candidates.value.filter(candidate => ['priority', 'interviewing'].includes(candidate.status)).length)
const averageCandidateYears = computed(() => {
  const values = candidates.value.map(candidate => Number(candidate.total_years)).filter(value => Number.isFinite(value) && value >= 0)
  return values.length ? (values.reduce((total, value) => total + value, 0) / values.length).toFixed(1) : '0.0'
})

const candidateStatusLabels: Record<string, string> = {
  new: '新進人才', contacted: '已聯繫', priority: '優先聯繫', interviewing: '面試中', archived: '已封存',
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

async function refreshAll(silent = false) {
  if (!authSession.authenticated.value) return
  loading.value = true
  error.value = ''
  try {
    await hrApi.health()
    apiOnline.value = true
    if (authState.user?.role === 'it') {
      candidates.value = []
      resumes.value = []
      jobs.value = []
      lastSync.value = new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
      if (!silent) setNotice('系統狀態已同步')
      return
    }
    const [candidateResult, resumeResult, jobResult] = await Promise.all([
      hrApi.candidates(), hrApi.resumes(), hrApi.requisitions(),
    ])
    candidates.value = candidateResult.data
    await loadCandidatePhotos(candidates.value)
    resumes.value = resumeResult.data
    jobs.value = jobResult.data
    lastSync.value = new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
    if (!silent) setNotice('資料已同步')
  } catch (cause) {
    apiOnline.value = false
    showError(cause)
  } finally {
    loading.value = false
  }
}

async function navigate(target: Page) {
  page.value = target
  sidebarOpen.value = false
  error.value = ''
  if (['candidates', 'resumes', 'jobs', 'matching', 'reports'].includes(target)) {
    await refreshAll(true)
  }
}

function openCandidate(candidate?: CandidateDto) {
  editingCandidate.value = candidate || null
  Object.assign(candidateForm, candidate ? {
    name: candidate.name, email: candidate.email || '', phone: candidate.phone || '', city: candidate.city || '',
    current_title: candidate.current_title || '', total_years: candidate.total_years || 0, source: candidate.source || 'manual', status: candidate.status,
  } : { name: '', email: '', phone: '', city: '', current_title: '', total_years: 0, source: 'manual', status: 'new' })
  candidatePhotoFile.value = null
  if (candidatePhotoInput.value) candidatePhotoInput.value.value = ''
  dialog.value = 'candidate'
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

async function saveCandidate() {
  if (!candidateForm.name?.trim()) return showError('姓名為必填欄位')
  saving.value = true
  error.value = ''
  try {
    const payload = { ...candidateForm, email: candidateForm.email || null, phone: candidateForm.phone || null }
    const result = await hrApi.saveCandidate(payload, editingCandidate.value?.id)
    if (candidatePhotoFile.value) {
      result.data = (await hrApi.uploadCandidatePhoto(result.data.id, candidatePhotoFile.value)).data
      await loadCandidatePhoto(result.data)
    }
    const index = candidates.value.findIndex(item => item.id === result.data.id)
    if (index >= 0) candidates.value[index] = result.data
    else candidates.value.unshift(result.data)
    dialog.value = null
    setNotice(editingCandidate.value ? '人才資料已更新' : '人才已建立')
  } catch (cause) { showError(cause) } finally { saving.value = false }
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

async function viewCandidate(candidate: CandidateDto) {
  selectedCandidate.value = candidate
  candidateActivities.value = []
  try { candidateActivities.value = (await hrApi.activities(candidate.id)).data } catch (cause) { showError(cause) }
}

function openActivity(candidate: CandidateDto) {
  selectedCandidate.value = candidate
  Object.assign(activityForm, { type: '電話聯繫', content: '', next_status: 'contacted' })
  dialog.value = 'activity'
}

async function saveActivity() {
  if (!selectedCandidate.value || !activityForm.content.trim()) return showError('請填寫活動紀錄')
  saving.value = true
  try {
    await hrApi.addActivity(selectedCandidate.value.id, activityForm)
    const updated = await hrApi.candidate(selectedCandidate.value.id)
    const index = candidates.value.findIndex(c => c.id === updated.data.id)
    if (index >= 0) candidates.value[index] = updated.data
    selectedCandidate.value = updated.data
    candidateActivities.value = (await hrApi.activities(updated.data.id)).data
    dialog.value = null
    setNotice('聯繫紀錄與人才狀態已更新')
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

function selectFiles(event: Event) {
  uploadFiles.value = Array.from((event.target as HTMLInputElement).files || [])
}

function selectIntakeFiles(event: Event) {
  intakeFiles.value = Array.from((event.target as HTMLInputElement).files || [])
  intakeDone.value = false
}

function removeIntakeFile(index: number) {
  intakeFiles.value.splice(index, 1)
  if (!intakeFiles.value.length && intakeInput.value) intakeInput.value.value = ''
}

async function submitIntake() {
  if (!intakeForm.name?.trim()) return showError('請先填寫人才姓名')
  saving.value = true
  error.value = ''
  intakeDone.value = false
  let created: CandidateDto | null = null
  try {
    created = (await hrApi.saveCandidate({
      ...intakeForm,
      name: intakeForm.name.trim(),
      email: intakeForm.email || null,
      phone: intakeForm.phone || null,
      source: 'manual',
    })).data
    const target = jobs.value.find(job => job.id === intakeJobId.value)
    const note = [target ? `目標職缺：${target.req_no} ${target.title}` : '', intakeNotes.value.trim()].filter(Boolean).join('\n')
    if (note) await hrApi.addActivity(created.id, { type: '招募建檔', content: note, next_status: 'new' })
    let detectionSummary = ''
    if (intakeFiles.value.length) {
      const uploaded = (await hrApi.uploadResumes(intakeFiles.value, 'generic')).data
      const counts = uploaded.reduce<Record<string, number>>((result, item) => {
        result[item.source_platform] = (result[item.source_platform] || 0) + 1
        return result
      }, {})
      const reviewCount = uploaded.filter(item => item.source_review_required).length
      detectionSummary = `；來源判別 ${Object.entries(counts).map(([key, count]) => `${sourceLabels[key] || key} ${count}`).join('、')}${reviewCount ? `，${reviewCount} 份待確認` : ''}`
    }
    await refreshAll(true)
    Object.assign(intakeForm, { name: '', email: '', phone: '', city: '', current_title: '', total_years: 0, source: 'manual', status: 'new' })
    intakeJobId.value = null
    intakeNotes.value = ''
    intakeFiles.value = []
    if (intakeInput.value) intakeInput.value.value = ''
    intakeDone.value = true
    setNotice(`已建立 ${created.name}，資料已寫入人才庫${detectionSummary}`)
  } catch (cause) {
    if (created) showError(`人才 ${created.name} 已建立，但履歷或備註未完整送出：${cause instanceof Error ? cause.message : '請稍後重試'}`)
    else showError(cause)
  } finally { saving.value = false }
}

async function upload() {
  if (!uploadFiles.value.length) return showError('請先選擇履歷檔案')
  saving.value = true
  error.value = ''
  try {
    const uploaded = (await hrApi.uploadResumes(uploadFiles.value, 'generic')).data
    uploadFiles.value = []
    if (uploadInput.value) uploadInput.value.value = ''
    resumes.value = (await hrApi.resumes()).data
    const reviewCount = uploaded.filter(item => item.source_review_required).length
    setNotice(`已逐檔自動判別來源並加入解析佇列${reviewCount ? `，${reviewCount} 份需要人工確認` : ''}`)
  } catch (cause) { showError(cause) } finally { saving.value = false }
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
  saving.value = true
  error.value = ''
  try {
    await hrApi.updateResumeParsed(selectedResume.value.id, { ...parsedForm, skills: normalizeSkills(parsedForm.skills) })
    if (confirm) {
      const confirmation = (await hrApi.confirmResume(selectedResume.value.id)).data
      await refreshAll(true)
      selectedResume.value = (await hrApi.resume(confirmation.resume_id)).data
      setNotice(confirmation.created ? `已建立人才 ${confirmation.candidate_code}` : `已更新人才 ${confirmation.candidate_code}`)
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
    setNotice('履歷已重新加入解析佇列')
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
  editingJob.value = job || null
  Object.assign(jobForm, job ? {
    req_no: job.req_no, title: job.title, department_id: job.department_id, employment_type: job.employment_type,
    work_city: job.work_city, jd: job.jd, summary: job.summary || '', skillsText: (job.skills || []).join(', '),
    salary_min: job.salary_min, salary_max: job.salary_max, salary_type: job.salary_type || 'monthly', headcount: job.headcount, status: job.status,
  } : { req_no: `R${new Date().getFullYear()}-${String(jobs.value.length + 1).padStart(4, '0')}`, title: '', department_id: null,
    employment_type: 'full_time', work_city: '台北市', jd: '', summary: '', skillsText: '', salary_min: null,
    salary_max: null, salary_type: 'monthly', headcount: 1, status: 'draft' })
  dialog.value = 'job'
}

async function saveJob() {
  if (!jobForm.title.trim() || !jobForm.jd.trim()) return showError('職缺名稱與職務說明為必填')
  saving.value = true
  try {
    const payload: RequisitionWrite = {
      req_no: jobForm.req_no, title: jobForm.title, department_id: jobForm.department_id, employment_type: jobForm.employment_type,
      work_city: jobForm.work_city, jd: jobForm.jd, summary: jobForm.summary || null, skills: normalizeSkills(jobForm.skillsText),
      salary_min: jobForm.salary_min, salary_max: jobForm.salary_max, salary_type: jobForm.salary_type,
      headcount: jobForm.headcount, status: jobForm.status,
    }
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
  return new Intl.DateTimeFormat('zh-TW', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

async function authenticated() {
  page.value = 'dashboard'
  await refreshAll(true)
}

function logout() {
  authSession.logout()
  candidates.value = []
  resumes.value = []
  jobs.value = []
  selectedCandidate.value = null
  selectedResume.value = null
  page.value = 'dashboard'
}

watch(() => authState.user?.id, async (userId, previousId) => {
  if (userId && userId !== previousId) await authenticated()
})

onMounted(() => authSession.initialize())
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
        <p class="nav-label">招募工作台</p>
        <button v-for="item in nav" :key="item.id" class="nav-item" :class="{ active: page === item.id }" @click="navigate(item.id)">
          <span class="nav-icon">{{ item.icon }}</span><span>{{ item.label }}</span><em v-if="item.id === 'resumes' && pendingReviewCount">{{ pendingReviewCount }}</em>
        </button>
      </nav>
      <div class="sidebar-footer"><div class="connection"><i :class="{ online: apiOnline }"></i><div><strong>{{ apiOnline ? 'API 已連線' : 'API 未連線' }}</strong><small>{{ API_BASE }}</small></div></div></div>
    </aside>

    <main class="main">
      <header class="topbar">
        <button class="menu-button" @click="sidebarOpen = true">☰</button>
        <div class="top-title"><strong>{{ pageTitle }}</strong><small>{{ roleProfile.scope }} · 最後同步 {{ lastSync }}</small></div>
        <button class="button secondary" :disabled="loading" @click="refreshAll()">{{ loading ? '同步中…' : '重新同步' }}</button>
        <div class="user-session"><span class="avatar">{{ authState.user.display_name.slice(0, 1) }}</span><div><strong>{{ authState.user.display_name }}</strong><small>{{ roleProfile.label }}</small></div><button class="text-button" @click="logout">登出</button></div>
      </header>

      <div class="content">
        <div v-if="error" class="alert error-alert"><span>!</span><p><strong>操作未完成</strong>{{ error }}</p><button @click="error = ''">×</button></div>

        <section v-if="page === 'dashboard'" class="page">
          <div v-if="authState.user.role === 'hr' || authState.user.role === 'admin'" class="intake-page">
            <header class="intake-welcome">
              <div><p class="eyebrow">NEW TALENT INTAKE</p><h1>嗨，{{ authState.user.display_name }}，今天想認識哪位人才？</h1><p>基本資料、履歷與招募方向都在這一頁。填完一次送出，接下來交給系統整理。</p></div>
              <div class="intake-progress" aria-label="建檔流程"><span class="active">1</span><i></i><span :class="{ active: intakeFiles.length }">2</span><i></i><span :class="{ active: intakeJobId || intakeNotes }">3</span></div>
            </header>

            <form class="intake-workspace" @submit.prevent="submitIntake">
              <section class="intake-card identity-card">
                <div class="intake-step"><span>01</span><div><h2>先從基本資料開始</h2><p>只要姓名是必填，其餘可以稍後再補。</p></div></div>
                <div class="intake-fields">
                  <label class="wide">姓名 <b>*</b><input v-model="intakeForm.name" required autofocus placeholder="例如：林小安"></label>
                  <label>Email<input v-model="intakeForm.email" type="email" placeholder="name@example.com"></label>
                  <label>聯絡電話<input v-model="intakeForm.phone" placeholder="09xx-xxx-xxx"></label>
                  <label>目前職稱<input v-model="intakeForm.current_title" placeholder="例如：前端工程師"></label>
                  <label>居住地<input v-model="intakeForm.city" placeholder="例如：台北市"></label>
                  <label>總年資<input v-model.number="intakeForm.total_years" type="number" min="0" step="0.5" placeholder="0"></label>
                </div>
              </section>

              <section class="intake-card resume-intake-card">
                <div class="intake-step"><span>02</span><div><h2>把履歷一起帶進來</h2><p>可一次選多檔；沒有履歷也能先建立人才。</p></div></div>
                <p class="source-auto-note"><span>✦</span><strong>來源由系統逐檔自動判別</strong><small>只有偵測到指定匯出網域與版型特徵才標示疑似平台格式；單有品牌字樣或通用欄位一律待人工覆核。</small></p>
                <button class="intake-dropzone" type="button" @click="intakeInput?.click()"><span class="upload-heart">＋</span><strong>{{ intakeFiles.length ? `已選擇 ${intakeFiles.length} 份履歷` : '選擇一份或多份履歷' }}</strong><small>PDF、DOC、DOCX · 檔案將送入 OCR 校對佇列</small></button>
                <input ref="intakeInput" class="visually-hidden" type="file" multiple accept=".pdf,.doc,.docx,application/pdf" @change="selectIntakeFiles">
                <ul v-if="intakeFiles.length" class="intake-file-list"><li v-for="(file, index) in intakeFiles" :key="`${file.name}-${file.size}`"><span><strong>{{ file.name }}</strong><small>{{ (file.size / 1024 / 1024).toFixed(2) }} MB</small></span><button type="button" aria-label="移除檔案" @click="removeIntakeFile(index)">×</button></li></ul>
              </section>

              <section class="intake-card direction-card">
                <div class="intake-step"><span>03</span><div><h2>給招募夥伴一點方向</h2><p>選擇目標職缺並留下第一手觀察。</p></div></div>
                <div class="intake-fields">
                  <label class="wide">目標職缺<select v-model="intakeJobId"><option :value="null">先不指定職缺</option><option v-for="job in jobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}</option></select></label>
                  <label class="wide">招募備註<textarea v-model="intakeNotes" rows="5" placeholder="例如：朋友推薦、具備 SaaS 經驗，下週方便聯繫…"></textarea></label>
                </div>
              </section>

              <footer class="intake-submit-bar">
                <div><strong>{{ intakeForm.name || '新人才' }}</strong><span>人才資料寫入資料庫；履歷另送 OCR 解析與人工校對。</span></div>
                <button class="button primary intake-submit" type="submit" :disabled="saving || !intakeForm.name?.trim()">{{ saving ? '正在安心保存…' : '完成建檔' }} <span>→</span></button>
              </footer>
              <div v-if="intakeDone" class="intake-success"><span>✓</span><div><strong>人才資料已好好收進人才庫</strong><p>你可以直接開始建立下一位；履歷解析結果請至「履歷匯入」校對。</p></div></div>
            </form>
          </div>
          <template v-else>
          <div class="welcome-banner">
            <div><p class="eyebrow">{{ roleProfile.label }}</p><h1>{{ authState.user.display_name }}，歡迎回來</h1><p>{{ roleProfile.note }}。{{ authState.user.role === 'it' ? '以下是系統管理入口。' : '以下是你今天需要關注的招募進度。' }}</p></div>
            <div class="scope-orbit"><span>{{ roleProfile.scope }}</span><small>資料存取範圍</small></div>
          </div>
          <div v-if="authState.user.role !== 'it'" class="metric-grid">
            <article><span>人才總數</span><strong>{{ candidates.length }}</strong><small>目前權限範圍內的人才</small></article>
            <article v-if="authState.user.role !== 'manager'"><span>待校對履歷</span><strong>{{ pendingReviewCount }}</strong><small>待人工確認或解析失敗</small></article>
            <article v-if="authState.user.role !== 'manager'"><span>解析佇列</span><strong>{{ resumes.filter(r => ['pending','processing'].includes(r.parse_status)).length }}</strong><small>等待或正在處理</small></article>
            <article v-else><span>推薦人才</span><strong>{{ candidates.filter(c => ['priority','interviewing'].includes(c.status)).length }}</strong><small>等待主管檢視與決策</small></article>
            <article v-if="authState.user.role === 'manager'"><span>面試進行中</span><strong>{{ candidates.filter(c => c.status === 'interviewing').length }}</strong><small>所屬職缺的面試人才</small></article>
            <article><span>招募中職缺</span><strong>{{ activeJobCount }}</strong><small>目前權限範圍內的職缺</small></article>
          </div>
          <div class="dashboard-actions">
            <article v-if="authState.user.role === 'it'" class="panel"><div><span class="action-icon">⚙</span><div><h3>管理系統與權限</h3><p>維護帳號角色、部門、系統設定與稽核紀錄。</p></div></div><button class="button primary" @click="navigate('admin')">開啟管理中心</button></article>
            <article v-else-if="authState.user.role !== 'manager'" class="panel"><div><span class="action-icon">⇧</span><div><h3>匯入外部履歷</h3><p>批次上傳 104、1111 或其他格式，送入 OCR 解析與欄位校對。</p></div></div><button class="button primary" @click="navigate('resumes')">開始匯入</button></article>
            <article v-else class="panel"><div><span class="action-icon">◎</span><div><h3>檢視推薦人才</h3><p>依技能、經驗與職缺條件查看配對說明，快速做出面試決策。</p></div></div><button class="button primary" @click="navigate('matching')">開始審閱</button></article>
            <article v-if="authState.user.role !== 'it'" class="panel"><div><span class="action-icon">人</span><div><h3>篩選人才</h3><p>依姓名、聯絡方式、來源、職稱與狀態搜尋。</p></div></div><button class="button secondary" @click="navigate('candidates')">開啟人才庫</button></article>
          </div>
          </template>
        </section>

        <section v-else-if="page === 'candidates'" class="page">
          <header class="talent-hero">
            <div><p class="eyebrow">{{ roleProfile.scope }} TALENT POOL</p><h1>{{ authState.user.role === 'manager' ? '職缺關聯人才' : '人才資料庫' }}</h1><p>{{ authState.user.role === 'manager' ? '僅顯示與你所屬部門職缺相關的人才。' : '從人才資料、聯繫狀態到職缺媒合，在同一個工作區快速管理。' }}</p></div>
            <div class="talent-hero-actions"><button class="button secondary" @click="navigate('matching')">◎ 查看媒合程度</button><button v-if="authState.user.role !== 'manager'" class="button primary" @click="openCandidate()">＋ 手動新增人才</button></div>
          </header>
          <div class="talent-metrics">
            <article><span>人才總數</span><strong>{{ candidates.length }}</strong><small>目前權限範圍</small></article>
            <article><span>活躍人才</span><strong>{{ activeCandidateCount }}</strong><small>未封存資料</small></article>
            <article><span>優先／面試中</span><strong>{{ priorityCandidateCount }}</strong><small>建議優先跟進</small></article>
            <article><span>平均年資</span><strong>{{ averageCandidateYears }}</strong><small>年</small></article>
          </div>
          <div class="filter-bar panel"><label class="search-field"><span>⌕</span><input v-model="search" placeholder="搜尋姓名、Email、電話、職稱或來源"></label><select v-model="candidateStatus"><option value="all">全部狀態</option><option v-for="(label, key) in candidateStatusLabels" :key="key" :value="key">{{ label }}</option></select><span>{{ filteredCandidates.length }} 筆結果</span></div>
          <div v-if="filteredCandidates.length" class="talent-card-grid">
            <article v-for="candidate in filteredCandidates" :key="candidate.id" class="panel talent-card">
              <header><button class="talent-identity" @click="viewCandidate(candidate)"><img v-if="candidatePhotoPreviews[candidate.id]" class="person-avatar large candidate-photo" :src="candidatePhotoPreviews[candidate.id]" :alt="`${candidate.name}的大頭照`"><span v-else class="person-avatar large">{{ candidate.name.slice(0,1) }}</span><span><strong>{{ candidate.name }}</strong><small>{{ candidate.code }}</small></span></button><span class="status" :data-status="candidate.status">{{ candidateStatusLabels[candidate.status] || candidate.status }}</span></header>
              <div class="talent-role"><strong>{{ candidate.current_title || '尚未填寫目前職稱' }}</strong><span>{{ candidate.city || '地區待補' }} · {{ candidate.total_years ?? 0 }} 年經驗</span></div>
              <div class="talent-contact"><p><small>EMAIL</small><strong>{{ candidate.email || '未提供' }}</strong></p><p><small>PHONE</small><strong>{{ candidate.phone || '未提供' }}</strong></p></div>
              <div class="talent-source"><span>{{ sourceLabels[candidate.source || ''] || candidate.source || '未知來源' }}</span><small>建立於 {{ date(candidate.created_at) }}</small></div>
              <footer><button class="button secondary" @click="viewCandidate(candidate)">查看詳情</button><template v-if="authState.user.role !== 'manager'"><button class="text-button" @click="openCandidate(candidate)">編輯</button><button class="text-button danger-text" :disabled="saving" @click="removeCandidate(candidate)">刪除</button></template><span v-else>唯讀</span></footer>
            </article>
          </div>
          <div v-else class="empty panel"><strong>找不到符合條件的人才</strong><p>請調整搜尋或篩選條件。</p></div>
        </section>

        <section v-else-if="page === 'resumes'" class="page">
          <div class="page-heading"><div><h1>履歷匯入與校對</h1><p>直接混合上傳 104、1111 或自製履歷，系統會逐檔自動判別。</p></div></div>
          <div class="resume-layout">
            <div>
              <article class="panel uploader"><div class="section-head"><div><h2>1. 選擇來源與檔案</h2><p>支援 PDF、DOC、DOCX；單檔上限依後端設定。</p></div></div>
                <p class="source-auto-note"><span>✦</span><strong>不需要先選來源</strong><small>同一批可混合不同格式；判定結果、信心分數與依據會顯示在右側校對區。</small></p>
                <button class="dropzone" @click="uploadInput?.click()"><strong>點此選擇多份履歷</strong><span>可一次選擇多個檔案</span></button>
                <input ref="uploadInput" class="visually-hidden" type="file" multiple accept=".pdf,.doc,.docx,application/pdf" @change="selectFiles">
                <ul v-if="uploadFiles.length" class="selected-files"><li v-for="file in uploadFiles" :key="`${file.name}-${file.size}`"><span>{{ file.name }}</span><small>{{ (file.size / 1024 / 1024).toFixed(2) }} MB</small></li></ul>
                <button class="button primary upload-button" :disabled="saving || !uploadFiles.length" @click="upload">{{ saving ? '處理中…' : `上傳 ${uploadFiles.length || ''} 份履歷` }}</button>
              </article>
              <article class="panel queue"><div class="section-head"><div><h2>2. 解析佇列</h2><p>點選待校對或失敗項目查看內容。</p></div><select v-model="resumeStatus"><option value="all">全部狀態</option><option v-for="(label, key) in resumeStatusLabels" :key="key" :value="key">{{ label }}</option></select></div>
                <button v-for="resume in filteredResumes" :key="resume.id" class="resume-row" :class="{ active: selectedResume?.id === resume.id }" @click="openResume(resume)"><span class="file-badge">{{ resume.original_filename?.split('.').pop()?.toUpperCase() || 'FILE' }}</span><span><strong>{{ resume.original_filename || `履歷 #${resume.id}` }}</strong><small>{{ sourceLabels[resume.source_platform] || resume.source_platform }} · 信心 {{ Math.round((resume.source_confidence || 0) * 100) }}% · {{ date(resume.uploaded_at) }}</small></span><span class="status" :data-status="resume.source_review_required ? 'needs_review' : resume.parse_status">{{ resume.source_review_required ? '來源待確認' : resumeStatusLabels[resume.parse_status] || resume.parse_status }}</span></button>
                <div v-if="!filteredResumes.length" class="empty"><strong>目前沒有履歷</strong><p>上傳後會顯示在解析佇列。</p></div>
              </article>
            </div>
            <article class="panel review-panel">
              <template v-if="selectedResume"><div class="section-head"><div><h2>3. 人工校對</h2><p>{{ selectedResume.original_filename }}</p></div><span class="status" :data-status="selectedResume.parse_status">{{ resumeStatusLabels[selectedResume.parse_status] || selectedResume.parse_status }}</span></div>
                <div class="source-verdict" :class="{ uncertain: selectedResume.source_review_required }"><div><small>逐檔來源判別</small><strong>{{ sourceLabels[selectedResume.source_platform] || selectedResume.source_platform }} · {{ Math.round((selectedResume.source_confidence || 0) * 100) }}%</strong><p>依據：{{ sourceEvidence(selectedResume) }}</p></div><div v-if="selectedResume.source_review_required" class="source-review-buttons"><button v-for="value in (['p104','p1111','direct','generic'] as ResumeSource[])" :key="value" type="button" class="button secondary" :disabled="saving" @click="reviewResumeSource(value)">{{ sourceLabels[value] }}</button></div></div>
                <div v-if="selectedResume.parse_status === 'pending' || selectedResume.parse_status === 'processing'" class="review-message"><span class="spinner"></span><strong>履歷正在等待解析</strong><p>解析完成後即可在此校對欄位。</p></div>
                <div v-else-if="selectedResume.parse_status !== 'confirmed'" class="review-form">
                  <label :class="{ 'low-confidence': fieldNeedsReview('name') }">姓名 *<input v-model="parsedForm.name"></label><label :class="{ 'low-confidence': fieldNeedsReview('email') }">Email<input v-model="parsedForm.email" type="email"></label><label :class="{ 'low-confidence': fieldNeedsReview('phone') }">電話<input v-model="parsedForm.phone"></label><label :class="{ 'low-confidence': fieldNeedsReview('city') }">居住地<input v-model="parsedForm.city"></label><label :class="{ 'low-confidence': fieldNeedsReview('current_title') }">目前職稱<input v-model="parsedForm.current_title"></label><label :class="{ 'low-confidence': fieldNeedsReview('total_years') }">總年資<input v-model.number="parsedForm.total_years" type="number" min="0" step="0.5"></label><label class="wide" :class="{ 'low-confidence': fieldNeedsReview('skills') }">技能（逗號分隔）<textarea :value="normalizeSkills(parsedForm.skills).join(', ')" rows="2" @input="parsedForm.skills = ($event.target as HTMLTextAreaElement).value.split(/[,，]/)"></textarea></label><label v-if="selectedResume.resume_text" class="wide">解析原文（僅供校對）<textarea :value="selectedResume.resume_text" rows="7" readonly></textarea></label>
                  <div v-if="selectedResume.error_message" class="inline-error wide"><strong>解析錯誤</strong>{{ selectedResume.error_message }}</div>
                </div>
                <div v-else class="review-message"><strong>這份履歷已確認入庫</strong><p>人才編號已建立，確認後的履歷不可再次編輯。</p></div>
                <footer v-if="selectedResume.parse_status !== 'confirmed'" class="review-actions"><button v-if="selectedResume.parse_status === 'failed'" class="button secondary" :disabled="saving" @click="reparse(selectedResume)">重新解析</button><span></span><button class="button secondary" :disabled="saving || ['pending','processing'].includes(selectedResume.parse_status)" @click="saveParsed(false)">儲存校對</button><button class="button primary" :disabled="saving || selectedResume.source_review_required || ['pending','processing'].includes(selectedResume.parse_status)" @click="saveParsed(true)">{{ selectedResume.source_review_required ? '請先確認來源' : '確認並寫入人才庫' }}</button></footer>
              </template>
              <div v-else class="empty review-empty"><strong>選擇一份履歷開始校對</strong><p>系統解析結果會顯示在這裡，HR 可修正後再寫入人才庫。</p></div>
            </article>
          </div>
        </section>

        <section v-else-if="page === 'jobs'" class="page">
          <div class="page-heading"><div><p class="eyebrow">{{ roleProfile.scope }}</p><h1>{{ authState.user.role === 'manager' ? '我的職缺' : '職缺管理' }}</h1><p>{{ authState.user.role === 'manager' ? '追蹤所屬部門職缺、推薦人才與招募進度。' : '建立、編輯及核准全公司職缺；核准後公開前台才能讀取。' }}</p></div><button v-if="authState.user.role !== 'manager'" class="button primary" @click="openJob()">＋ 建立職缺</button></div>
          <div class="job-grid"><article v-for="job in jobs" :key="job.id" class="panel job-card"><header><span class="status" :data-status="job.status">{{ jobStatusLabels[job.status] || job.status }}</span><button v-if="authState.user.role !== 'manager'" class="text-button" @click="openJob(job)">編輯</button><button v-else class="text-button" @click="navigate('matching')">查看人才 →</button></header><h2>{{ job.title }}</h2><p>{{ job.req_no }} · {{ job.work_city }} · 需求 {{ job.headcount }} 人</p><div class="job-summary">{{ job.summary || job.jd }}</div><div class="skill-list"><span v-for="skill in job.skills || []" :key="skill">{{ skill }}</span></div><footer><small>{{ job.published_at ? `發布：${date(job.published_at)}` : '尚未發布' }}</small><button v-if="authState.user.role !== 'manager' && ['draft','submitted'].includes(job.status)" class="button primary" :disabled="saving" @click="approveJob(job)">核准職缺</button></footer></article><div v-if="!jobs.length" class="empty panel"><strong>目前沒有職缺</strong><p>目前權限範圍內沒有可檢視的職缺。</p></div></div>
        </section>

        <MatchingView v-else-if="page === 'matching'" :jobs="jobs" :can-configure="authState.user.role === 'hr' || authState.user.role === 'admin'" />
        <ReportsView v-else-if="page === 'reports'" :jobs="jobs" />
        <AdminView v-else-if="page === 'admin'" :current-user="authState.user" />
        <section v-else class="page unavailable-page"><div class="unavailable-icon">⌛</div><p class="eyebrow">NOT CONNECTED</p><h1>{{ pageTitle }}尚未接上後端</h1><p>這個模組目前沒有可持久化的 API，因此先停用所有操作，避免產生「看似成功但未寫入資料庫」的誤解。</p><button class="button secondary" @click="navigate('dashboard')">返回工作總覽</button></section>
      </div>
    </main>

    <div v-if="selectedCandidate" class="drawer-overlay" @click.self="selectedCandidate = null"><aside class="detail-drawer"><header><div><img v-if="candidatePhotoPreviews[selectedCandidate.id]" class="person-avatar large candidate-photo" :src="candidatePhotoPreviews[selectedCandidate.id]" :alt="`${selectedCandidate.name}的大頭照`"><span v-else class="person-avatar large">{{ selectedCandidate.name.slice(0,1) }}</span><div><small>{{ selectedCandidate.code }}</small><h2>{{ selectedCandidate.name }}</h2><p>{{ selectedCandidate.current_title || '未填職稱' }}</p></div></div><button @click="selectedCandidate = null">×</button></header><div class="detail-body"><div class="detail-grid"><div><small>Email</small><strong>{{ selectedCandidate.email || '未提供' }}</strong></div><div><small>電話</small><strong>{{ selectedCandidate.phone || '未提供' }}</strong></div><div><small>地區</small><strong>{{ selectedCandidate.city || '未提供' }}</strong></div><div><small>來源</small><strong>{{ sourceLabels[selectedCandidate.source || ''] || selectedCandidate.source || '未知' }}</strong></div></div><div v-if="authState.user.role !== 'manager'" class="drawer-actions"><button class="button primary" @click="openActivity(selectedCandidate)">＋ 新增聯繫紀錄</button><button class="button secondary" @click="openCandidate(selectedCandidate)">編輯資料</button><button v-if="selectedCandidate.has_photo" class="button secondary" :disabled="saving" @click="removeCandidatePhoto(selectedCandidate)">移除照片</button><button class="button danger" @click="archiveCandidate(selectedCandidate)">封存</button><button class="button danger" :disabled="saving" @click="removeCandidate(selectedCandidate)">刪除人才</button></div><h3>活動紀錄</h3><div v-if="candidateActivities.length" class="timeline"><article v-for="activity in candidateActivities" :key="activity.id"><i></i><small>{{ date(activity.happened_at) }} · {{ activity.type }}</small><p>{{ activity.content }}</p></article></div><div v-else class="empty compact"><p>尚無活動紀錄</p></div></div></aside></div>

    <div v-if="dialog" class="modal-overlay" @click.self="dialog = null"><form class="modal-card" @submit.prevent="dialog === 'candidate' ? saveCandidate() : dialog === 'activity' ? saveActivity() : saveJob()"><header><div><small>資料會直接寫入 API</small><h2>{{ dialog === 'candidate' ? (editingCandidate ? '編輯人才' : '新增人才') : dialog === 'activity' ? '新增聯繫紀錄' : (editingJob ? '編輯職缺' : '建立職缺') }}</h2></div><button type="button" @click="dialog = null">×</button></header>
      <div v-if="dialog === 'candidate'" class="form-grid"><label class="wide photo-upload-field"><span>大頭照</span><input ref="candidatePhotoInput" type="file" accept="image/jpeg,image/png,image/webp" @change="selectCandidatePhoto"><small>JPG、PNG 或 WebP，最大 5 MB；儲存後才會上傳。</small></label><label>姓名 *<input v-model="candidateForm.name" required></label><label>Email<input v-model="candidateForm.email" type="email"></label><label>電話<input v-model="candidateForm.phone"></label><label>地區<input v-model="candidateForm.city"></label><label>目前職稱<input v-model="candidateForm.current_title"></label><label>總年資<input v-model.number="candidateForm.total_years" type="number" min="0" step="0.5"></label><label>來源<select v-model="candidateForm.source"><option value="manual">手動建立</option><option value="p104">104</option><option value="p1111">1111</option><option value="generic">一般履歷</option><option value="direct">自製履歷</option></select></label><label>狀態<select v-model="candidateForm.status"><option v-for="(label,key) in candidateStatusLabels" :key="key" :value="key">{{ label }}</option></select></label></div>
      <div v-else-if="dialog === 'activity'" class="form-grid"><label>聯繫方式<select v-model="activityForm.type"><option>電話聯繫</option><option>Email</option><option>面談</option><option>其他</option></select></label><label>後續狀態<select v-model="activityForm.next_status"><option v-for="(label,key) in candidateStatusLabels" :key="key" :value="key">{{ label }}</option></select></label><label class="wide">活動紀錄 *<textarea v-model="activityForm.content" rows="6" required placeholder="記錄聯繫結果與下一步"></textarea></label></div>
      <div v-else class="form-grid"><label>職缺編號 *<input v-model="jobForm.req_no" required :disabled="!!editingJob"></label><label>職缺名稱 *<input v-model="jobForm.title" required></label><label>部門 ID<input v-model.number="jobForm.department_id" type="number" min="1"></label><label>工作地點<input v-model="jobForm.work_city"></label><label>聘僱類型<select v-model="jobForm.employment_type"><option value="full_time">正職</option><option value="contract">約聘</option><option value="part_time">兼職</option></select></label><label>需求人數<input v-model.number="jobForm.headcount" type="number" min="1"></label><label>月薪下限<input v-model.number="jobForm.salary_min" type="number" min="0"></label><label>月薪上限<input v-model.number="jobForm.salary_max" type="number" min="0"></label><label class="wide">技能（逗號分隔）<input v-model="jobForm.skillsText"></label><label class="wide">職缺摘要<textarea v-model="jobForm.summary" rows="2"></textarea></label><label class="wide">職務說明 *<textarea v-model="jobForm.jd" rows="7" required></textarea></label><label>流程狀態<select v-model="jobForm.status"><option v-for="(label,key) in jobStatusLabels" :key="key" :value="key">{{ label }}</option></select></label></div>
      <footer><button type="button" class="button secondary" @click="dialog = null">取消</button><button type="submit" class="button primary" :disabled="saving">{{ saving ? '儲存中…' : '儲存至資料庫' }}</button></footer></form></div>

    <Transition name="toast"><div v-if="notice" class="toast"><span>✓</span>{{ notice }}</div></Transition>
  </div>
</template>
