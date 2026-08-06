<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'

import {
  hrApi,
  type ApplicationDto,
  type InterviewQuestion,
  type InterviewQuestionPlan,
  type InterviewQuestionSuggestions,
  type InterviewRecordDto,
  type InterviewRecordMode,
  type InterviewRecordQuestion,
  type InterviewRecordStatus,
  type InterviewRecordWrite,
  type InterviewRecommendation,
  type InterviewResult,
  type InterviewStage,
  type InterviewStageDto,
  type RequisitionDto,
} from '../services/hrApi'
import { matchingReportsApi } from '../services/matchingReportsApi'
import { authSession } from '../services/auth'
import { formatApiDateTime, parseApiDateTime } from '../utils/dateTime'

const props = withDefaults(defineProps<{
  embedded?: boolean
  focusRequisitionId?: number | null
  focusApplicationId?: number | null
  focusRequestKey?: number
  refreshKey?: number
  availableJobs?: RequisitionDto[]
}>(), {
  embedded: false,
  focusRequisitionId: null,
  focusApplicationId: null,
  focusRequestKey: 0,
  refreshKey: 0,
  availableJobs: () => [],
})

const emit = defineEmits<{
  (event: 'back-to-assessment'): void
  (event: 'requisition-selected', requisitionId: number | null): void
}>()

const applications = ref<ApplicationDto[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const focusError = ref('')
const notice = ref('')
const departmentId = ref<number | null>(null)
const requisitionId = ref<number | null>(null)
const editingApplicationId = ref<number | null>(null)
const editingStage = ref<InterviewStage | null>(null)
const expandedApplicationId = ref<number | null>(null)
// One card = one candidate = one workspace. The expanded row *is* the scoring
// surface, so the workspace target is derived instead of tracked separately.
const workspaceApplication = computed(() => (
  expandedApplicationId.value === null
    ? null
    : applications.value.find(application => application.id === expandedApplicationId.value) || null
))
const interviewRecords = ref<InterviewRecordDto[]>([])
const recordsLoading = ref(false)
const recordSaving = ref(false)
const recordSaveIntent = ref<'draft' | 'submit' | null>(null)
const recordReopening = ref(false)
const workspaceError = ref('')
const recordNotice = ref('')
const editingRecord = ref<InterviewRecordDto | null>(null)
const recordEditorOpen = ref(false)
const reopenReasonInput = ref<HTMLInputElement | null>(null)
const reopenPromptOpen = ref(false)
const reopenReason = ref('')
const questionSuggestions = ref<InterviewQuestionSuggestions | null>(null)
const questionLoading = ref(false)
const questionPlanGenerating = ref<Record<string, boolean>>({})
const questionRegenerating = ref<Record<string, boolean>>({})
const cardInterviewErrors = ref<Record<number, string>>({})
const cardQuestionErrors = ref<Record<string, string>>({})
const recordsByApplication = ref<Record<number, InterviewRecordDto[]>>({})
const plansByApplicationStage = ref<Record<string, InterviewQuestionPlan>>({})
const cardDataLoaded = ref<Record<number, boolean>>({})
const cardDataLoading = ref<Record<number, boolean>>({})
const inlineStageByApplication = reactive<Record<number, InterviewStage>>({})
const selectedTraits = ref<string[]>([])
const customTrait = ref('')
const questionTextEditing = ref<Record<number, boolean>>({})
// Pending destructive navigation inside an expanded card (collapse / stage switch)
// while the scoring form still holds unsaved content.
type PendingDiscard =
  | { type: 'collapse' }
  | { type: 'stage'; stage: InterviewStage }
  | { type: 'open'; applicationId: number }
const pendingDiscard = ref<PendingDiscard | null>(null)
const recordFormBaseline = ref('')
// Resume match score for the expanded card. The composite breakdown carries it
// too, but only once both stages are submitted, and it is worth seeing before
// that. Keyed by requisition because that is what the matching API returns.
const matchScoreByApplication = ref<Record<number, number | null>>({})
const matchScoreLoading = ref(false)
const recordForm = reactive<InterviewRecordWrite>({
  stage: 'hr',
  question_plan_id: null,
  interviewed_at: '',
  duration_minutes: 60,
  mode: 'video',
  status: 'in_progress',
  questions: [],
  summary: '',
  private_notes: '',
  recommendation: null,
  overall_rating: null,
  overall_score: null,
})
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
const commonTraits = ['主動積極', '溝通表達', '團隊合作', '適應變化', '問題解決', '同理心', '抗壓韌性', '領導影響']
const recordModeLabels: Record<InterviewRecordMode, string> = { onsite: '現場面試', video: '視訊面試', phone: '電話訪談', other: '其他' }
const recordStatusLabels: Record<InterviewRecordStatus, string> = { planned: '已規劃', in_progress: '填寫中', completed: '已提交評分', cancelled: '已取消', no_show: '未到場' }
const recommendationLabels: Record<InterviewRecommendation, string> = { advance: '進入下一階段', hold: '保留觀察', reject: '不建議錄用', offer: '建議發 Offer' }
const ratingScale = [
  { value: 1, label: '明顯不足' },
  { value: 2, label: '未達期待' },
  { value: 3, label: '符合期待' },
  { value: 4, label: '優於期待' },
  { value: 5, label: '卓越表現' },
] as const
const recordValidationErrors = reactive({
  questions: {} as Record<number, string>,
  overall: '',
  recommendation: '',
  summary: '',
})

// --- Interview-question compliance (就服法§5 / 性平法§7·§11) ---------------
// The backend attaches a `compliance` result to AI-generated / suggested
// questions. For manually typed questions (which the record read schema does
// not carry compliance for) we mirror the backend rule library here so the
// interviewer still gets an immediate 合法 / 疑似違法 verdict. Keep this list in
// sync with backend/app/services/interview_question_compliance.py; both need a
// legal review before production use.
type QuestionCompliance = {
  status: 'ok' | 'warning'
  categories: string[]
  matched: string[]
  suggestion: string
  rules_version?: string
}
const complianceCategoryLabels: Record<string, string> = {
  marital: '婚姻狀況',
  pregnancy: '懷孕或生育計畫',
  childcare: '家庭照顧責任',
  age: '年齡',
  gender: '性別或性傾向',
  race: '種族或籍貫',
  religion: '宗教或黨派',
  disability_health: '身心障礙或健康病史',
  appearance: '容貌或身材',
  astrology_blood: '星座、血型或命理',
}
const localComplianceRules: Array<{ category: string; keywords: string[]; patterns: RegExp[]; suggestion: string }> = [
  { category: 'marital', keywords: ['婚姻', '已婚', '未婚', '離婚', '結婚', '打算結婚', '何時結婚', '配偶', '老公', '老婆', '感情狀況', '有沒有男朋友', '有沒有女朋友', '有沒有交往'], patterns: [/\b(?:marital|married|spouse|husband|wife|boyfriend|girlfriend)\b/i], suggestion: '建議改問工作能力面向：避免詢問婚姻或感情狀況，可改問是否能配合職務所需的出差、輪班或加班安排。' },
  { category: 'pregnancy', keywords: ['懷孕', '有孕', '生育', '生小孩', '生子', '生寶寶', '打算生', '備孕', '產假', '育嬰假', '育嬰留職', '生育計畫', '月經', '經期'], patterns: [/\b(?:pregnan\w*|maternity|childbearing)\b/i, /plan to have (?:a )?(?:child|children|baby|kids)/i], suggestion: '建議改問工作能力面向：避免詢問懷孕或生育計畫，可改問是否能配合職務的工作時間與出勤要求。' },
  { category: 'childcare', keywords: ['照顧小孩', '照顧家人', '照顧長輩', '照顧父母', '家庭照顧', '家庭責任', '帶小孩', '誰帶小孩', '誰顧小孩', '托兒', '育兒', '家裡有沒有小孩'], patterns: [/child\s?care/i, /care for (?:your )?(?:children|family|parents|kids)/i, /\b(?:caregiving|dependents)\b/i], suggestion: '建議改問工作能力面向：避免詢問家庭照顧責任，可改問是否能配合職務所需的工時、值班或臨時加班。' },
  { category: 'age', keywords: ['年齡', '幾歲', '今年多大', '出生年', '出生日期', '民國幾年', '哪一年出生', '生肖', '屬什麼'], patterns: [/\b(?:age|how old|year of birth|birth year|date of birth|birthday)\b/i], suggestion: '建議改問工作能力面向：避免詢問年齡或出生年次，可改問與職務相關的經驗年資或具體技能。' },
  { category: 'gender', keywords: ['性別', '性傾向', '性向', '你是男是女', '男生還是女生', '同性戀', '異性戀', '跨性別'], patterns: [/\b(?:gender|sexual orientation|homosexual|heterosexual|transgender|lgbt)\b/i], suggestion: '建議改問工作能力面向：避免詢問性別或性傾向，請聚焦職務所需的專業能力與工作表現。' },
  { category: 'race', keywords: ['種族', '籍貫', '省籍', '外省', '本省', '族群', '原住民', '血統', '國籍', '你是哪裡人', '老家在哪', '老家哪裡'], patterns: [/\b(?:race|ethnicity|ethnic|nationality|native place|where are you from)\b/i], suggestion: '建議改問工作能力面向：避免詢問種族、籍貫或國籍，可改問是否具備合法工作資格與職務所需語言能力。' },
  { category: 'religion', keywords: ['宗教', '信仰', '拜拜', '佛教', '基督教', '天主教', '伊斯蘭', '回教', '政黨', '黨派', '政治立場', '支持哪一黨', '支持哪個政黨'], patterns: [/\b(?:religion|religious|faith|church|political party|which party)\b/i], suggestion: '建議改問工作能力面向：避免詢問宗教信仰或政黨黨派，可改問是否能配合公司既定的工作時間與排班。' },
  { category: 'disability_health', keywords: ['身心障礙', '殘障', '殘疾', '病史', '疾病', '健康狀況', '健康情形', '慢性病', '精神疾病', '家族病史', '遺傳疾病', '開過刀', '服用藥物', '身心狀況', '是否生病'], patterns: [/\b(?:disabilit\w*|handicap\w*|health condition|medical history|mental illness)\b/i, /chronic (?:illness|disease)/i], suggestion: '建議改問工作能力面向：避免詢問健康病史或身心障礙，可改問是否能執行職務說明書所列的必要工作任務（必要時提供合理調整）。' },
  { category: 'appearance', keywords: ['身高', '體重', '外貌', '長相', '五官', '容貌', '胖瘦', '幾公斤', '幾公分', '整形', '身材'], patterns: [/\b(?:body weight|physical appearance|how tall|your looks)\b/i], suggestion: '建議改問工作能力面向：避免針對身高、體重或容貌提問，請改問與職務績效直接相關的能力；如職務確有外型需求，須有明確職業資格依據並經法遵確認。' },
  { category: 'astrology_blood', keywords: ['星座', '血型', '命盤', '紫微', '塔羅', '算命', '生辰八字', '八字', '占卜'], patterns: [/\b(?:astrolog\w*|blood type|horoscope|zodiac)\b/i], suggestion: '建議改問工作能力面向：避免以星座、血型或命理作為評估依據，請改問可觀察的工作行為與具體成果。' },
]

function localCompliance(text: string | null | undefined): QuestionCompliance {
  const result: QuestionCompliance = { status: 'ok', categories: [], matched: [], suggestion: '' }
  const haystack = (text || '').trim()
  if (!haystack) return result
  const suggestions: string[] = []
  for (const rule of localComplianceRules) {
    const hits = [
      ...rule.keywords.filter(keyword => haystack.includes(keyword)),
      ...rule.patterns.filter(pattern => pattern.test(haystack)).map(pattern => pattern.source),
    ]
    if (!hits.length) continue
    result.categories.push(rule.category)
    suggestions.push(rule.suggestion)
    for (const hit of hits) if (!result.matched.includes(hit)) result.matched.push(hit)
  }
  if (result.categories.length) {
    result.status = 'warning'
    result.suggestion = suggestions.join(' ')
  }
  return result
}

function questionCompliance(question: { question?: string | null; compliance?: QuestionCompliance | null }): QuestionCompliance {
  const attached = question.compliance
  if (attached && (attached.status === 'ok' || attached.status === 'warning')) return attached
  return localCompliance(question.question)
}

function complianceCategoryText(compliance: QuestionCompliance): string {
  return compliance.categories.map(category => complianceCategoryLabels[category] || category).join('、')
}

function stageData(application: ApplicationDto, stage: InterviewStage): InterviewStageDto {
  return stage === 'hr' ? application.hr_interview : application.manager_interview
}

// The card shows one stage at a time; the other stage's shared schedule and
// notes stay reachable as a collapsed reference (問答共享、評分分開).
function peerStage(stage: InterviewStage) {
  return stage === 'hr' ? interviewStages[1] : interviewStages[0]
}

async function toggleApplicationDetails(applicationId: number) {
  if (expandedApplicationId.value === applicationId) {
    requestCollapseApplicationCard()
    return
  }
  if (recordSaving.value || recordReopening.value) return
  if (expandedApplicationId.value !== null && recordFormIsDirty.value) {
    pendingDiscard.value = { type: 'open', applicationId }
    return
  }
  const application = applications.value.find(item => item.id === applicationId)
  if (application) await openApplicationCard(application)
}

function nearestInterviewAt(application: ApplicationDto) {
  const values = interviewStages
    .map(stage => stageData(application, stage.key).interview_at)
    .filter((value): value is string => Boolean(value))
    .sort((left, right) => parseApiDateTime(left).getTime() - parseApiDateTime(right).getTime())
  if (!values.length) return null
  const now = Date.now()
  return values.find(value => parseApiDateTime(value).getTime() >= now) || values[values.length - 1]
}

function canEditStage(stage: InterviewStage) {
  const role = authSession.state.user?.role
  return stage === 'hr' ? role === 'hr' : role === 'manager'
}

function canGenerateQuestionStage(stage: InterviewStage) {
  const role = authSession.state.user?.role
  return stage === 'hr' ? role === 'hr' : role === 'manager'
}

function firstScheduledAt(application: ApplicationDto) {
  const values = [application.hr_interview.interview_at, application.manager_interview.interview_at]
    .filter((value): value is string => Boolean(value))
    .map(value => parseApiDateTime(value).getTime())
  return values.length ? Math.min(...values) : null
}

const departments = computed(() => {
  const values = new Map<number, string>()
  const jobs = [...props.availableJobs, ...applications.value.map(application => application.requisition)]
  jobs.forEach(requisition => {
    if (requisition.department_id !== null) {
      values.set(requisition.department_id, requisition.department_name || `部門 #${requisition.department_id}`)
    }
  })
  return Array.from(values, ([id, name]) => ({ id, name })).sort((left, right) => left.name.localeCompare(right.name, 'zh-TW'))
})

const requisitions = computed(() => {
  const values = new Map<number, RequisitionDto>()
  const jobs = [...props.availableJobs, ...applications.value.map(application => application.requisition)]
  jobs.forEach(requisition => {
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
    return parseApiDateTime(right.applied_at).getTime() - parseApiDateTime(left.applied_at).getTime()
  }))

const scheduledCount = computed(() => applications.value.filter(application => (
  application.hr_interview.interview_at || application.manager_interview.interview_at
)).length)
const upcomingCount = computed(() => applications.value.filter(application =>
  [application.hr_interview, application.manager_interview].some(stage => (
    stage.interview_at
    && parseApiDateTime(stage.interview_at).getTime() >= Date.now()
    && !['cancelled', 'no_show'].includes(stage.interview_result || '')
  )),
).length)
const completedCount = computed(() => applications.value.filter(application =>
  [application.hr_interview, application.manager_interview].some(stage => (
    stage.interview_result && stage.interview_result !== 'pending'
  )),
).length)

const hasFocusContext = computed(() => props.focusApplicationId !== null)
const focusedApplication = computed(() => (
  props.focusApplicationId === null
    ? null
    : applications.value.find(application => application.id === props.focusApplicationId) || null
))
const focusedRequisition = computed(() => (
  props.focusRequisitionId === null
    ? null
    : props.availableJobs.find(job => job.id === props.focusRequisitionId)
      || applications.value.find(application => application.requisition_id === props.focusRequisitionId)?.requisition
      || null
))
const focusContextDescription = computed(() => {
  const application = focusedApplication.value
  if (application) {
    return `${application.candidate.name} · ${application.requisition.req_no} · ${application.requisition.title}`
  }
  if (props.focusApplicationId !== null) return `應徵紀錄 #${props.focusApplicationId}`
  if (focusedRequisition.value) return `${focusedRequisition.value.req_no} · ${focusedRequisition.value.title}`
  if (props.focusRequisitionId !== null) return `職缺 #${props.focusRequisitionId}`
  return '從人才評估選擇人才後，可直接帶入對應面試流程。'
})

async function revealFocusedApplication(applicationId: number) {
  await nextTick()
  const toggle = document.querySelector<HTMLButtonElement>(
    `[data-testid="interview-row-toggle-${applicationId}"]`,
  )
  toggle?.scrollIntoView({ block: 'nearest' })
  toggle?.focus({ preventScroll: true })
}

async function applyFocusContext() {
  focusError.value = ''
  if (!hasFocusContext.value) return

  if (props.focusApplicationId !== null) {
    const application = applications.value.find(item => item.id === props.focusApplicationId)
    if (!application) {
      expandedApplicationId.value = null
      resetRecordEditor()
      interviewRecords.value = []
      focusError.value = `找不到從人才評估帶入的應徵紀錄 #${props.focusApplicationId}。請返回人才評估，確認人才已加入目前職缺後再試一次。`
      return
    }
    departmentId.value = application.requisition.department_id
    requisitionId.value = application.requisition_id
    if (expandedApplicationId.value !== application.id || !recordEditorOpen.value) {
      await openApplicationCard(application)
    }
    await revealFocusedApplication(application.id)
    return
  }

  const requisition = focusedRequisition.value
  if (!requisition) {
    requisitionId.value = null
    focusError.value = `目前權限範圍內找不到職缺 #${props.focusRequisitionId}。`
    return
  }
  departmentId.value = requisition.department_id
  requisitionId.value = requisition.id
}

async function load() {
  loading.value = true
  error.value = ''
  recordsByApplication.value = {}
  plansByApplicationStage.value = {}
  cardInterviewErrors.value = {}
  cardQuestionErrors.value = {}
  cardDataLoaded.value = {}
  cardDataLoading.value = {}
  try {
    applications.value = (await hrApi.applications()).data
    applications.value.forEach(application => {
      if (!inlineStageByApplication[application.id]) {
        inlineStageByApplication[application.id] = defaultRecordStage()
      }
    })
    // Apply the incoming job/application context before the slower question-plan
    // preload. This prevents a late background refresh from collapsing a row that
    // the recruiter has already opened.
    await applyFocusContext()
    if (props.focusApplicationId === null && expandedApplicationId.value !== null) {
      const expanded = applications.value.find(application => application.id === expandedApplicationId.value)
      if (!expanded) expandedApplicationId.value = null
      else if (recordFormIsDirty.value) await loadCardInterviewData([expanded])
      else await openApplicationCard(expanded)
    }
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
  const date = parseApiDateTime(value)
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

function defaultRecordStage(): InterviewStage {
  return authSession.state.user?.role === 'manager' ? 'manager' : 'hr'
}

function planKey(applicationId: number, stage: InterviewStage) {
  return `${applicationId}:${stage}`
}

function questionRegenerationKey(applicationId: number, stage: InterviewStage, questionIndex: number) {
  return `${planKey(applicationId, stage)}:${questionIndex}`
}

function sortInterviewRecords(records: InterviewRecordDto[]) {
  return [...records].sort((left, right) => (
    parseApiDateTime(right.interviewed_at).getTime() - parseApiDateTime(left.interviewed_at).getTime()
  ))
}

async function loadCardInterviewData(items: ApplicationDto[]) {
  const pendingItems = items.filter(application => (
    !cardDataLoaded.value[application.id] && !cardDataLoading.value[application.id]
  ))
  if (!pendingItems.length) return
  cardDataLoading.value = {
    ...cardDataLoading.value,
    ...Object.fromEntries(pendingItems.map(application => [application.id, true])),
  }
  const nextRecords: Record<number, InterviewRecordDto[]> = {}
  const nextPlans: Record<string, InterviewQuestionPlan> = {}
  const nextErrors: Record<number, string> = {}
  const nextQuestionErrors: Record<string, string> = {}

  const batchSize = 4
  for (let index = 0; index < pendingItems.length; index += batchSize) {
    await Promise.all(pendingItems.slice(index, index + batchSize).map(async application => {
      const [recordResult, hrPlanResult, managerPlanResult] = await Promise.allSettled([
        hrApi.interviewRecords(application.id),
        hrApi.interviewQuestionPlan(application.id, 'hr'),
        hrApi.interviewQuestionPlan(application.id, 'manager'),
      ])
      if (recordResult.status === 'fulfilled') {
        nextRecords[application.id] = sortInterviewRecords(recordResult.value.data)
      } else {
        nextRecords[application.id] = []
        nextErrors[application.id] = recordResult.reason instanceof Error
          ? recordResult.reason.message
          : '無法載入面試進度'
      }
      for (const [stage, result] of [
        ['hr', hrPlanResult],
        ['manager', managerPlanResult],
      ] as const) {
        if (result.status === 'fulfilled') {
          nextPlans[planKey(application.id, stage)] = result.value.data
        } else {
          nextQuestionErrors[planKey(application.id, stage)] = result.reason instanceof Error
            ? result.reason.message
            : `無法載入${stage === 'hr' ? 'HR' : '主管'}題目`
        }
      }
    }))
  }

  recordsByApplication.value = { ...recordsByApplication.value, ...nextRecords }
  plansByApplicationStage.value = { ...plansByApplicationStage.value, ...nextPlans }
  cardInterviewErrors.value = { ...cardInterviewErrors.value, ...nextErrors }
  cardQuestionErrors.value = { ...cardQuestionErrors.value, ...nextQuestionErrors }
  cardDataLoaded.value = {
    ...cardDataLoaded.value,
    ...Object.fromEntries(pendingItems.map(application => [application.id, true])),
  }
  cardDataLoading.value = {
    ...cardDataLoading.value,
    ...Object.fromEntries(pendingItems.map(application => [application.id, false])),
  }
}

async function ensureQuestionPlan(application: ApplicationDto, stage: InterviewStage) {
  const key = planKey(application.id, stage)
  const existing = plansByApplicationStage.value[key]
  if (existing) return existing
  const plan = (await hrApi.interviewQuestionPlan(application.id, stage)).data
  plansByApplicationStage.value = { ...plansByApplicationStage.value, [key]: plan }
  return plan
}

async function generateQuestionPlan(
  application: ApplicationDto,
  stage: InterviewStage,
  force = false,
) {
  const key = planKey(application.id, stage)
  if (!canGenerateQuestionStage(stage)) {
    cardQuestionErrors.value = {
      ...cardQuestionErrors.value,
      [key]: stage === 'hr' ? '只有 HR 能產生 HR 題目' : '只有部門主管能產生主管題目',
    }
    return
  }
  questionPlanGenerating.value = { ...questionPlanGenerating.value, [key]: true }
  cardQuestionErrors.value = { ...cardQuestionErrors.value, [key]: '' }
  if (workspaceApplication.value?.id === application.id && inlineStage(application.id) === stage) {
    workspaceError.value = ''
  }
  try {
    const plan = (await hrApi.generateInterviewQuestionPlan(application.id, stage, force)).data
    plansByApplicationStage.value = {
      ...plansByApplicationStage.value,
      [key]: plan,
    }
    const stageLabel = stage === 'hr' ? 'HR' : '主管'
    notice.value = plan.generation_mode === 'gemini'
      ? `${stageLabel} 五題已由 Gemini 產生並保存。`
      : `${stageLabel} 五題已使用規則式備援產生並保存。`
  } catch (caught) {
    const message = caught instanceof Error ? caught.message : '無法產生面試題目'
    cardQuestionErrors.value = {
      ...cardQuestionErrors.value,
      [key]: message,
    }
    if (workspaceApplication.value?.id === application.id && inlineStage(application.id) === stage) {
      workspaceError.value = message
    }
  } finally {
    questionPlanGenerating.value = { ...questionPlanGenerating.value, [key]: false }
  }
}

async function regenerateQuestionPlanItem(
  application: ApplicationDto,
  stage: InterviewStage,
  questionIndex: number,
) {
  const key = planKey(application.id, stage)
  const itemKey = questionRegenerationKey(application.id, stage, questionIndex)
  const currentPlan = plansByApplicationStage.value[key]
  const originalQuestion = currentPlan?.questions[questionIndex]
  if (!originalQuestion || questionPlanGenerating.value[key]) return
  if (!canGenerateQuestionStage(stage)) {
    cardQuestionErrors.value = {
      ...cardQuestionErrors.value,
      [key]: stage === 'hr' ? '只有 HR 能重新產生 HR 題目' : '只有部門主管能重新產生主管題目',
    }
    return
  }

  questionPlanGenerating.value = { ...questionPlanGenerating.value, [key]: true }
  questionRegenerating.value = { ...questionRegenerating.value, [itemKey]: true }
  cardQuestionErrors.value = { ...cardQuestionErrors.value, [key]: '' }
  if (workspaceApplication.value?.id === application.id && inlineStage(application.id) === stage) {
    workspaceError.value = ''
  }
  try {
    const plan = (await hrApi.regenerateInterviewQuestion(
      application.id,
      stage,
      questionIndex,
    )).data
    plansByApplicationStage.value = {
      ...plansByApplicationStage.value,
      [key]: plan,
    }

    const replacement = plan.questions[questionIndex]
    const inCurrentWorkspace = workspaceApplication.value?.id === application.id
      && recordEditorOpen.value
      && recordForm.stage === stage
    if (inCurrentWorkspace && replacement) {
      if (editingRecord.value) {
        recordNotice.value = `第 ${questionIndex + 1} 題已建立新版；既有面試紀錄與回答維持原題。`
      } else {
        const draftQuestion = recordForm.questions[questionIndex]
        const targetHasProgress = Boolean(
          draftQuestion?.response?.trim()
          || draftQuestion?.notes?.trim()
          || (draftQuestion?.not_asked_reason !== null && draftQuestion?.not_asked_reason !== undefined)
          || (draftQuestion?.rating !== null && draftQuestion?.rating !== undefined),
        )
        const targetWasEdited = !draftQuestion || draftQuestion.question !== originalQuestion.question
        if (draftQuestion && !targetHasProgress && !targetWasEdited) {
          recordForm.question_plan_id = plan.id ?? null
          recordForm.questions[questionIndex] = {
            ...draftQuestion,
            question: replacement.question,
            trait: replacement.category,
            purpose: replacement.purpose,
            follow_up: replacement.follow_up,
            source: replacement.source,
          }
          recordNotice.value = `第 ${questionIndex + 1} 題已替換，其餘題目與目前填寫內容都已保留。`
        } else {
          recordNotice.value = `第 ${questionIndex + 1} 題已建立新版；這題已有回答、評分或手動修改，因此目前草稿未被覆蓋。`
        }
      }
    }

    const stageLabel = stage === 'hr' ? 'HR' : '主管'
    notice.value = plan.generation_mode === 'gemini'
      ? `${stageLabel} 第 ${questionIndex + 1} 題已由 Gemini 重新產生，其餘四題維持不變。`
      : `${stageLabel} 第 ${questionIndex + 1} 題已使用規則式備援重新產生，其餘四題維持不變。`
  } catch (caught) {
    const message = caught instanceof Error ? caught.message : '無法重新產生這一題'
    cardQuestionErrors.value = {
      ...cardQuestionErrors.value,
      [key]: message,
    }
    if (workspaceApplication.value?.id === application.id && inlineStage(application.id) === stage) {
      workspaceError.value = message
    }
  } finally {
    questionPlanGenerating.value = { ...questionPlanGenerating.value, [key]: false }
    questionRegenerating.value = { ...questionRegenerating.value, [itemKey]: false }
  }
}

function latestStageRecord(applicationId: number, stage: InterviewStage) {
  return (recordsByApplication.value[applicationId] || []).find(record => record.stage === stage) || null
}

function currentPlanRecord(applicationId: number, stage: InterviewStage) {
  const records = (recordsByApplication.value[applicationId] || []).filter(record => record.stage === stage)
  const plan = plansByApplicationStage.value[planKey(applicationId, stage)]
  if (plan?.id !== null && plan?.id !== undefined) {
    return records.find(record => record.question_plan_id === plan.id) || null
  }
  return records[0] || null
}

function recordHasContent(record: InterviewRecordDto) {
  return Boolean(
    record.summary?.trim()
    || record.recommendation
    || record.overall_rating !== null && record.overall_rating !== undefined
    || record.overall_score !== null && record.overall_score !== undefined
    || record.questions.some(question => (
      Boolean(question.response?.trim())
      || Boolean(question.notes?.trim())
      || Boolean(question.not_asked_reason?.trim())
      || (question.rating !== null && question.rating !== undefined)
    )),
  )
}

// Opening a card must never hide work that was already saved. A record created
// against an older question version no longer matches currentPlanRecord(), so
// fall back to it whenever it actually holds answers or scores.
function editableStageRecord(applicationId: number, stage: InterviewStage) {
  const current = currentPlanRecord(applicationId, stage)
  if (current) return current
  const latest = latestStageRecord(applicationId, stage)
  return latest && recordHasContent(latest) ? latest : null
}

function hasOlderPlanRecord(applicationId: number, stage: InterviewStage) {
  return Boolean(
    plansByApplicationStage.value[planKey(applicationId, stage)]?.id
    && latestStageRecord(applicationId, stage)
    && !currentPlanRecord(applicationId, stage),
  )
}

function planQuestions(applicationId: number, stage: InterviewStage): InterviewRecordQuestion[] {
  return (plansByApplicationStage.value[planKey(applicationId, stage)]?.questions || []).map(item => ({
    question: item.question,
    trait: item.category,
    response: '',
    rating: null,
    not_asked_reason: null,
    notes: '',
    purpose: item.purpose,
    follow_up: item.follow_up,
    source: item.source,
  }))
}

async function generateCardQuestionPlan(application: ApplicationDto, stage: InterviewStage) {
  const key = planKey(application.id, stage)
  const currentPlan = plansByApplicationStage.value[key]
  await generateQuestionPlan(
    application,
    stage,
    Boolean(currentPlan?.questions.length && currentPlan.context_matches),
  )
  if (cardQuestionErrors.value[key]) return
  const generatedPlan = plansByApplicationStage.value[key]
  if (!generatedPlan?.questions.length) return

  await realignEditorWithPlan(application, stage)
  if (!recordEditorOpen.value || recordForm.stage !== stage || !canEditStage(stage) || recordIsCompleted.value) return
  if (!editingRecord.value && !recordFormIsDirty.value) {
    recordForm.question_plan_id = generatedPlan.id ?? null
    recordForm.questions = planQuestions(application.id, stage).slice(0, 5)
    recordFormBaseline.value = recordFormSnapshot()
    return
  }
  recordNotice.value = editingRecord.value
    ? '新版題目已建立；這筆既有面試紀錄仍保留原題。新建紀錄時才會帶入新版。'
    : '新版題目已建立；目前尚未儲存的內容已保留，未自動替換題目。'
}

async function regenerateCardQuestion(application: ApplicationDto, stage: InterviewStage, questionIndex: number) {
  await regenerateQuestionPlanItem(application, stage, questionIndex)
  await realignEditorWithPlan(application, stage)
}

function tokenSummary(plan: InterviewQuestionPlan | null | undefined) {
  if (!plan?.total_tokens) return ''
  const format = new Intl.NumberFormat('zh-TW').format
  return `本次 ${format(plan.total_tokens)} tokens（輸入 ${format(plan.input_tokens)}、輸出 ${format(plan.output_tokens)}、思考 ${format(plan.thinking_tokens)}）`
}

function generationModeLabel(plan: InterviewQuestionPlan | null | undefined) {
  if (plan?.generation_mode === 'gemini') return '產生方式：Gemini 動態生成'
  if (plan?.generation_mode === 'rules') return '產生方式：規則式備援'
  return '尚未產生'
}

function mergeQuestionsToFive(
  existing: InterviewRecordQuestion[],
  planned: InterviewRecordQuestion[],
) {
  const merged = existing.slice(0, 5).map(question => ({ ...question }))
  for (const question of planned) {
    if (merged.length >= 5) break
    if (!merged.some(item => item.question === question.question)) merged.push({ ...question })
  }
  return merged
}

function fiveQuestionSet(applicationId: number, stage: InterviewStage) {
  const recordQuestions = currentPlanRecord(applicationId, stage)?.questions || []
  const plannedQuestions = planQuestions(applicationId, stage).slice(0, 5)
  if (!plannedQuestions.length) return recordQuestions.slice(0, 5).map(question => ({ ...question }))
  if (!recordQuestions.length) return plannedQuestions
  return mergeQuestionsToFive(recordQuestions, plannedQuestions)
}

function inlineStage(applicationId: number): InterviewStage {
  return inlineStageByApplication[applicationId] || defaultRecordStage()
}

function questionIsAnswered(question: InterviewRecordQuestion) {
  return Boolean(question.response?.trim())
}

function stageAnsweredCount(applicationId: number, stage: InterviewStage) {
  return fiveQuestionSet(applicationId, stage).filter(questionIsAnswered).length
}

function questionAnswer(question: InterviewRecordQuestion) {
  if (question.response?.trim()) return question.response.trim()
  return '尚未紀錄答案'
}

function stageSubmissionLabel(applicationId: number, stage: InterviewStage) {
  const record = currentPlanRecord(applicationId, stage)
  if (!record && hasOlderPlanRecord(applicationId, stage)) return '新版尚未填答'
  if (!record) return '尚未開始'
  return record.status === 'completed' ? '評分已提交' : '問答填寫中'
}

function structuredRecordSummary(record: InterviewRecordDto) {
  if (!record.evaluation_revealed) {
    return '已建立結構化紀錄；問答已共享，評分與錄用建議會在 HR 與主管都提交後自動公開。'
  }
  const details: string[] = []
  if (record.summary?.trim()) details.push(`總結：${record.summary.trim()}`)
  if (validScore(record.overall_score)) details.push(`面試總分：${record.overall_score} / 100`)
  else if (validRating(record.overall_rating)) details.push(`整體評分：${record.overall_rating} / 5`)
  if (record.recommendation) details.push(`建議：${recommendationLabels[record.recommendation]}`)
  return details.join('；') || '已建立紀錄，尚未填寫評估內容。'
}

function structuredRecordStatus(applicationId: number, stage: InterviewStage) {
  const record = latestStageRecord(applicationId, stage)
  return record ? recordStatusLabels[record.status] : ''
}

function structuredRecordLocked(applicationId: number, stage: InterviewStage) {
  return !latestStageRecord(applicationId, stage)?.evaluation_revealed
}

function structuredRecordSummaryForStage(applicationId: number, stage: InterviewStage) {
  const record = latestStageRecord(applicationId, stage)
  return record ? structuredRecordSummary(record) : ''
}

function peerEvaluationsReleased(applicationId: number) {
  const hrRecord = currentPlanRecord(applicationId, 'hr')
  const managerRecord = currentPlanRecord(applicationId, 'manager')
  return hrRecord?.status === 'completed' && managerRecord?.status === 'completed'
}

// Per-question score on the same 0-100 scale as the interviewer's own total.
// Questions marked 未詢問 are excluded from the denominator as well as the
// numerator: a question that was never put to the candidate must not be scored
// against them.
function stageQuestionScore(applicationId: number, stage: InterviewStage): number | null {
  const record = currentPlanRecord(applicationId, stage)
  if (!record) return null
  const rated = record.questions.filter(question => validRating(question.rating))
  if (!rated.length) return null
  const total = rated.reduce((sum, question) => sum + Number(question.rating), 0)
  return Math.round((total / (rated.length * 5)) * 1000) / 10
}

function stageRatedCount(applicationId: number, stage: InterviewStage) {
  return (currentPlanRecord(applicationId, stage)?.questions || []).filter(question => validRating(question.rating)).length
}

// Two interviewers scoring 95 and 60 average to the same 77.5 as two scoring 78
// and 77, but they are opposite situations. The combined figure is only ever
// shown next to a verdict on whether the two sides actually agree.
const CONSENSUS_SCORE_GAP = 20
const recommendationTone: Record<InterviewRecommendation, 'positive' | 'neutral' | 'negative'> = {
  advance: 'positive', offer: 'positive', hold: 'neutral', reject: 'negative',
}

type InterviewConsensus = {
  state: 'pending' | 'aligned' | 'divergent'
  label: string
  detail: string
  combined: string | null
}

function interviewConsensus(applicationId: number): InterviewConsensus {
  const hrRecord = currentPlanRecord(applicationId, 'hr')
  const managerRecord = currentPlanRecord(applicationId, 'manager')
  const hrDone = hrRecord?.status === 'completed'
  const managerDone = managerRecord?.status === 'completed'
  if (!hrDone || !managerDone) {
    const waiting = hrDone ? '主管' : managerDone ? 'HR' : '雙方'
    return {
      state: 'pending',
      label: `等待${waiting}提交`,
      detail: '兩關都提交後才會計算面試綜合分，避免只用一半的評分做判斷。',
      combined: null,
    }
  }
  const hrScore = validScore(hrRecord?.overall_score) ? Number(hrRecord?.overall_score) : null
  const managerScore = validScore(managerRecord?.overall_score) ? Number(managerRecord?.overall_score) : null
  const combined = hrScore !== null && managerScore !== null
    ? ((hrScore + managerScore) / 2).toFixed(1)
    : null
  const gap = hrScore !== null && managerScore !== null ? Math.abs(hrScore - managerScore) : 0
  const hrTone = hrRecord?.recommendation ? recommendationTone[hrRecord.recommendation] : null
  const managerTone = managerRecord?.recommendation ? recommendationTone[managerRecord.recommendation] : null
  const recommendationDiffers = Boolean(hrTone && managerTone && hrTone !== managerTone)
  if (recommendationDiffers || gap >= CONSENSUS_SCORE_GAP) {
    const reason = recommendationDiffers
      ? `HR 建議${recommendationLabels[hrRecord!.recommendation!]}，主管建議${recommendationLabels[managerRecord!.recommendation!]}`
      : `兩關分數相差 ${gap} 分`
    return { state: 'divergent', label: '意見分歧 · 建議討論', detail: `${reason}。請先釐清雙方看到的證據差異，再做錄用決定。`, combined }
  }
  return { state: 'aligned', label: '雙方共識一致', detail: '兩關的評分與錄用建議方向相同。', combined }
}

const compositeComponentLabels: Record<string, string> = {
  resume: '履歷匹配', hr_questions: 'HR 題目', hr_overall: 'HR 總結',
  manager_questions: '主管題目', manager_overall: '主管總結',
}
const compositeExclusionLabels: Record<string, string> = {
  no_match_result: '無媒合紀錄', no_rated_questions: '無已評分題目', no_overall_score: '未填總結分數',
}

// Why a stage has no score, stated rather than left blank: not started, still
// being filled in, or withheld until both sides submit.
function stageScoreReason(applicationId: number, stage: InterviewStage) {
  const record = currentPlanRecord(applicationId, stage)
  if (!record) return '尚未開始評分'
  if (record.evaluation_revealed === false) return '評分保護中 · 雙方提交後公開'
  if (record.status !== 'completed') return '評分填寫中，尚未提交'
  return '此關未留下可計算的分數'
}

function compositeBreakdown(application: ApplicationDto) {
  const breakdown = application.composite_score_breakdown
  return breakdown && breakdown.status === 'computed' ? breakdown : null
}

function compositeNote(application: ApplicationDto) {
  const breakdown = application.composite_score_breakdown
  if (!breakdown) return '尚無綜合分紀錄；兩關都提交後才會計算'
  if (breakdown.status === 'pending_stages') {
    const waiting = breakdown.pending_stages.map(stage => stage === 'hr' ? 'HR' : '主管').join('、')
    return `等待${waiting}提交；未齊前不顯示任何部分計算結果`
  }
  return '僅供排序與討論參考，不代表錄用結論，也不會改變應徵狀態'
}

// Requisition-level opt-out of blind review, decided before scoring starts. The
// backend field is being added separately; a missing value must read as "blind
// review on" so the protection never loosens by accident.
function blindReviewEnabled(application: ApplicationDto) {
  return (application.requisition as { blind_review_enabled?: boolean }).blind_review_enabled !== false
}

// A bare lock icon reads as "you are not allowed to see this". Say who has
// submitted, who is still pending, and that release is automatic.
function evaluationReleaseHint(application: ApplicationDto) {
  if (!blindReviewEnabled(application)) return '本職缺採即時共享評分'
  const hrDone = currentPlanRecord(application.id, 'hr')?.status === 'completed'
  const managerDone = currentPlanRecord(application.id, 'manager')?.status === 'completed'
  if (hrDone && managerDone) return '雙方已提交 · 評分已公開'
  if (hrDone) return 'HR 已提交 · 待主管提交後自動公開'
  if (managerDone) return '主管已提交 · 待 HR 提交後自動公開'
  return '雙方提交後自動公開評分'
}

function evaluationWaitingFor(applicationId: number) {
  const hrDone = currentPlanRecord(applicationId, 'hr')?.status === 'completed'
  const managerDone = currentPlanRecord(applicationId, 'manager')?.status === 'completed'
  if (hrDone && !managerDone) return '主管'
  if (managerDone && !hrDone) return 'HR'
  return ''
}

const editorEvaluationVisible = computed(() => (
  !editingRecord.value || editingRecord.value.evaluation_revealed
))
const recordIsCompleted = computed(() => editingRecord.value?.status === 'completed')
const recordCanEdit = computed(() => (
  recordEditorOpen.value && canEditStage(recordForm.stage) && !recordIsCompleted.value
))
const recordQuestionTotal = computed(() => recordForm.questions.length)

function recordFormSnapshot() {
  return JSON.stringify([
    recordForm.stage,
    recordForm.questions.map(item => [item.question, item.trait ?? '', item.response ?? '', item.rating ?? null, item.not_asked_reason ?? null, item.notes ?? '']),
    recordForm.summary ?? '', recordForm.private_notes ?? '', recordForm.recommendation ?? null,
    recordForm.overall_rating ?? null, recordForm.overall_score ?? null,
  ])
}

// Extracted from the former `hasDraftProgress` check so that stage switching,
// filter changes and collapsing all share one definition of "unsaved work".
const recordFormIsDirty = computed(() => (
  recordEditorOpen.value
  && recordCanEdit.value
  && Boolean(recordFormBaseline.value)
  && recordFormSnapshot() !== recordFormBaseline.value
))

function validRating(value: number | null | undefined) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 5
}

// The backend stores overall_score as an integer 0-100; a fractional value would
// be rejected with 422 instead of being rounded silently.
function validScore(value: number | null | undefined) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100
}

function questionIsSkipped(question: InterviewRecordQuestion) {
  return question.not_asked_reason !== null && question.not_asked_reason !== undefined
}

function questionSkipIsComplete(question: InterviewRecordQuestion) {
  return Boolean(question.not_asked_reason?.trim())
}

const recordRatedCount = computed(() => recordForm.questions.filter(question => (
  !questionIsSkipped(question) && validRating(question.rating)
)).length)
const recordSkippedCount = computed(() => recordForm.questions.filter(questionSkipIsComplete).length)
const recordEvaluatedCount = computed(() => recordRatedCount.value + recordSkippedCount.value)
const recordAverageRating = computed(() => {
  const ratings = recordForm.questions
    .filter(question => !questionIsSkipped(question) && validRating(question.rating))
    .map(question => Number(question.rating))
  if (!ratings.length) return '—'
  return (ratings.reduce((total, rating) => total + rating, 0) / ratings.length).toFixed(1)
})
const recordHasExceptionalStatus = computed(() => (
  recordForm.status === 'cancelled' || recordForm.status === 'no_show'
))

function recordControlPrefix() {
  return `interview-record-${editingRecord.value?.id ?? 'new'}`
}

function questionRatingName(index: number) {
  return `${recordControlPrefix()}-question-${index}-rating`
}

function questionRatingId(index: number, value: number | 'not-asked') {
  return `${questionRatingName(index)}-${value}`
}

function questionNotAskedReasonId(index: number) {
  return `${recordControlPrefix()}-question-${index}-not-asked-reason`
}

function overallScoreId() {
  return `${recordControlPrefix()}-overall-score`
}

function questionTextId(index: number) {
  return `${recordControlPrefix()}-question-${index}-text`
}

// The question itself is normally read-only text; typing over it stays possible
// but is an explicit choice, so the five questions read as one list.
function questionTextIsEditable(question: InterviewRecordQuestion, index: number) {
  return Boolean(questionTextEditing.value[index]) || !question.question.trim()
}

async function editQuestionText(index: number) {
  questionTextEditing.value = { ...questionTextEditing.value, [index]: true }
  await nextTick()
  document.getElementById(questionTextId(index))?.focus()
}

function clearRecordValidation() {
  recordValidationErrors.questions = {}
  recordValidationErrors.overall = ''
  recordValidationErrors.recommendation = ''
  recordValidationErrors.summary = ''
}

function clearQuestionValidation(index: number) {
  if (!recordValidationErrors.questions[index]) return
  const next = { ...recordValidationErrors.questions }
  delete next[index]
  recordValidationErrors.questions = next
}

function setQuestionRating(question: InterviewRecordQuestion, index: number, rating: number) {
  question.rating = rating
  question.not_asked_reason = null
  clearQuestionValidation(index)
}

async function setQuestionNotAsked(question: InterviewRecordQuestion, index: number) {
  question.rating = null
  if (question.not_asked_reason === null || question.not_asked_reason === undefined) {
    question.not_asked_reason = ''
  }
  clearQuestionValidation(index)
  await nextTick()
  document.getElementById(questionNotAskedReasonId(index))?.focus()
}

function focusRecordControl(id: string) {
  void nextTick(() => document.getElementById(id)?.focus())
}

function setOverallScore(raw: string) {
  const value = raw.trim()
  const parsed = Number(value)
  recordForm.overall_score = value === '' || Number.isNaN(parsed) ? null : Math.round(parsed)
  recordValidationErrors.overall = ''
}

function openHistoryRecord(application: ApplicationDto, record: InterviewRecordDto) {
  if (recordSaving.value || recordReopening.value) return
  if (recordFormIsDirty.value) {
    workspaceError.value = '目前的評分內容尚未儲存；請先儲存草稿，或放棄後再切換其他紀錄。'
    return
  }
  inlineStageByApplication[application.id] = record.stage
  editRecord(record)
}

async function startNewRecord(application: ApplicationDto) {
  if (recordSaving.value || recordReopening.value) return
  if (recordFormIsDirty.value) {
    workspaceError.value = '目前的評分內容尚未儲存；請先儲存草稿，或放棄後再建立新紀錄。'
    return
  }
  await newRecord(inlineStage(application.id))
}

// The five questions render once per card. The editable list is the live form;
// everyone else (no rights for the stage, or a submitted record) reads the same
// five through the stored record + plan merge.
function cardQuestionsAreEditable(applicationId: number, stage: InterviewStage) {
  return workspaceApplication.value?.id === applicationId
    && recordEditorOpen.value
    && recordForm.stage === stage
    && recordCanEdit.value
}

function cardQuestions(applicationId: number, stage: InterviewStage): InterviewRecordQuestion[] {
  return cardQuestionsAreEditable(applicationId, stage)
    ? recordForm.questions
    : fiveQuestionSet(applicationId, stage)
}

// Only one card is expanded and only one stage selected at a time, so the
// question section can read these directly instead of threading ids around.
const cardStage = computed<InterviewStage>(() => (
  workspaceApplication.value ? inlineStage(workspaceApplication.value.id) : defaultRecordStage()
))
const cardStageKey = computed(() => (
  workspaceApplication.value ? planKey(workspaceApplication.value.id, cardStage.value) : ''
))
const cardStagePlan = computed(() => plansByApplicationStage.value[cardStageKey.value] || null)
const cardStageGenerating = computed(() => Boolean(questionPlanGenerating.value[cardStageKey.value]))
const cardStageQuestionError = computed(() => cardQuestionErrors.value[cardStageKey.value] || '')
// One compliance verdict for the whole list instead of a chip on every question;
// a question that fails still carries its own full warning.
const cardStageComplianceWarnings = computed(() => cardStageQuestions.value.filter(question => (
  question.question.trim() && questionCompliance(question).status === 'warning'
)).length)
// Four separate banners could stack on top of the questions. Show only the one
// that matters most right now.
const cardStageAlert = computed<{ tone: 'error' | 'warn'; title: string; text: string } | null>(() => {
  if (cardStageQuestionError.value) {
    return { tone: 'error', title: '無法更新題目', text: `${cardStageQuestionError.value}；目前題目仍保留。` }
  }
  const plan = cardStagePlan.value
  if (plan?.generation_warning) return { tone: 'warn', title: 'Gemini 生成提醒', text: plan.generation_warning }
  if (plan?.questions.length && plan.context_matches === false) {
    return { tone: 'warn', title: '履歷或職缺已更新', text: '現有題目仍可查看；請針對需要更新的題目逐題重新產生。' }
  }
  const application = workspaceApplication.value
  if (application && !editingRecord.value && hasOlderPlanRecord(application.id, cardStage.value)) {
    return { tone: 'warn', title: '尚未建立新版填答', text: '目前顯示新版題目；舊版問答仍保留在下方「面試紀錄歷程」中。' }
  }
  return null
})
const cardStageEditable = computed(() => (
  workspaceApplication.value ? cardQuestionsAreEditable(workspaceApplication.value.id, cardStage.value) : false
))
const cardStageQuestions = computed<InterviewRecordQuestion[]>(() => (
  workspaceApplication.value ? cardQuestions(workspaceApplication.value.id, cardStage.value) : []
))

function readOnlyEvaluationVisible(applicationId: number, stage: InterviewStage) {
  const record = currentPlanRecord(applicationId, stage) || latestStageRecord(applicationId, stage)
  return !record || record.evaluation_revealed
}

function readOnlyStageReason(stage: InterviewStage) {
  if (recordIsCompleted.value && recordForm.stage === stage) {
    return '這一關的評分已提交，目前為唯讀；需要修改請按「重新開啟評分」並填寫原因。'
  }
  const owner = stage === 'hr' ? 'HR' : '部門主管'
  return `這一關由${owner}維護，你只能查看；評分與觀察依盲評規則於雙方提交後才會顯示。`
}

function canEditRecord(record: InterviewRecordDto) {
  return canEditStage(record.stage) && record.status !== 'completed'
}

function canReopenRecord(record: InterviewRecordDto | null) {
  return Boolean(record && record.status === 'completed' && canEditStage(record.stage))
}

function recordHistoryActionLabel(record: InterviewRecordDto) {
  if (canEditRecord(record)) return '可編輯'
  if (canReopenRecord(record)) return '唯讀 · 可重新開啟'
  return '唯讀'
}

async function loadInterviewRecords(applicationId: number) {
  recordsLoading.value = true
  workspaceError.value = ''
  try {
    interviewRecords.value = sortInterviewRecords((await hrApi.interviewRecords(applicationId)).data)
    recordsByApplication.value = {
      ...recordsByApplication.value,
      [applicationId]: interviewRecords.value,
    }
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法載入面試過程紀錄'
  } finally {
    recordsLoading.value = false
  }
}

function resetRecordEditor() {
  editingRecord.value = null
  recordEditorOpen.value = false
  questionSuggestions.value = null
  selectedTraits.value = []
  customTrait.value = ''
  questionTextEditing.value = {}
  reopenPromptOpen.value = false
  reopenReason.value = ''
  workspaceError.value = ''
  recordNotice.value = ''
  recordFormBaseline.value = ''
  clearRecordValidation()
}

// Expanding a card is itself the "start scoring" action: the editor is prepared
// locally and nothing is written until 儲存草稿 / 提交評分 is pressed.
async function openApplicationCard(application: ApplicationDto) {
  pendingDiscard.value = null
  expandedApplicationId.value = application.id
  resetRecordEditor()
  interviewRecords.value = []
  void loadMatchScore(application)
  await loadCardInterviewData([application])
  await loadInterviewRecords(application.id)
  await bindStageEditor(application, inlineStage(application.id))
}

// Failure here must never block scoring, so it resolves to null rather than
// surfacing an error: a missing resume score is a real state (candidates added
// by hand never went through matching) and is labelled as such.
async function loadMatchScore(application: ApplicationDto) {
  if (application.id in matchScoreByApplication.value) return
  matchScoreLoading.value = true
  try {
    const matches = (await matchingReportsApi.matches(application.requisition_id, true)).items
    const hit = matches.find(item => item.candidate_id === application.candidate_id)
    matchScoreByApplication.value = {
      ...matchScoreByApplication.value,
      [application.id]: hit ? Number(hit.total_score) : null,
    }
  } catch {
    matchScoreByApplication.value = { ...matchScoreByApplication.value, [application.id]: null }
  } finally {
    matchScoreLoading.value = false
  }
}

function collapseApplicationCard() {
  if (recordSaving.value || recordReopening.value) return
  const applicationId = expandedApplicationId.value
  pendingDiscard.value = null
  expandedApplicationId.value = null
  resetRecordEditor()
  interviewRecords.value = []
  if (applicationId !== null) {
    void nextTick(() => document.querySelector<HTMLButtonElement>(
      `[data-testid="interview-row-toggle-${applicationId}"]`,
    )?.focus({ preventScroll: true }))
  }
}

function requestCollapseApplicationCard() {
  if (recordSaving.value || recordReopening.value) return
  if (recordFormIsDirty.value) {
    pendingDiscard.value = { type: 'collapse' }
    return
  }
  collapseApplicationCard()
}

async function bindStageEditor(application: ApplicationDto, stage: InterviewStage) {
  inlineStageByApplication[application.id] = stage
  questionTextEditing.value = {}
  pendingDiscard.value = null
  const record = editableStageRecord(application.id, stage)
  if (record) {
    const isOlderPlanRecord = !currentPlanRecord(application.id, stage)
    editRecord(record)
    if (canEditStage(stage) && record.status !== 'completed' && recordForm.questions.length < 5) {
      try {
        await ensureQuestionPlan(application, stage)
        recordForm.questions = mergeQuestionsToFive(recordForm.questions, planQuestions(application.id, stage))
        recordFormBaseline.value = recordFormSnapshot()
        recordNotice.value = '已補上系統建議題；儲存後才會寫入這筆紀錄'
      } catch (cause) {
        workspaceError.value = cause instanceof Error ? cause.message : '無法載入系統面試題'
      }
    }
    if (isOlderPlanRecord) {
      recordNotice.value = '已載入你先前填寫的內容（題目版本較舊）。可直接接續修改；需要換成新版題目時，按該題的「重新產生此題」。'
    }
    return
  }
  if (canEditStage(stage)) {
    await newRecord(stage)
    return
  }
  // Read-only stage with no record yet: keep the form aligned with the tab so
  // labels and permission checks describe the stage the user is looking at.
  editingRecord.value = null
  recordEditorOpen.value = false
  recordForm.stage = stage
  recordFormBaseline.value = ''
}

async function switchCardStage(application: ApplicationDto, stage: InterviewStage) {
  if (recordSaving.value || recordReopening.value) return
  if (inlineStage(application.id) === stage) return
  if (recordFormIsDirty.value) {
    pendingDiscard.value = { type: 'stage', stage }
    return
  }
  await bindStageEditor(application, stage)
}

async function confirmPendingDiscard() {
  const pending = pendingDiscard.value
  const application = workspaceApplication.value
  pendingDiscard.value = null
  if (!pending) return
  if (pending.type === 'collapse') {
    collapseApplicationCard()
    return
  }
  if (pending.type === 'open') {
    const target = applications.value.find(item => item.id === pending.applicationId)
    if (target) await openApplicationCard(target)
    return
  }
  if (application) await bindStageEditor(application, pending.stage)
}

function cancelPendingDiscard() {
  pendingDiscard.value = null
}

// Realign the editor after the plan changed: a record that belongs to an older
// plan version stays in the history, the card moves on to the new five.
async function realignEditorWithPlan(application: ApplicationDto, stage: InterviewStage) {
  if (recordFormIsDirty.value || inlineStage(application.id) !== stage) return
  // Only move on to a fresh record when the bound one holds no saved work.
  const record = editableStageRecord(application.id, stage)
  if ((record?.id ?? null) === (editingRecord.value?.id ?? null)) return
  if (record) {
    editRecord(record)
    return
  }
  if (!canEditStage(stage)) return
  await newRecord(stage)
  recordNotice.value = '已切換到最新版題目；先前的紀錄仍保留在下方「面試紀錄歷程」。'
}

async function newRecord(stage: InterviewStage = defaultRecordStage()) {
  if (!workspaceApplication.value) return
  const scheduledAt = stageData(workspaceApplication.value, stage).interview_at
  editingRecord.value = null
  recordEditorOpen.value = true
  reopenPromptOpen.value = false
  reopenReason.value = ''
  clearRecordValidation()
  Object.assign(recordForm, {
    stage,
    question_plan_id: null,
    interviewed_at: toLocalDateTime(scheduledAt) || toLocalDateTime(new Date().toISOString()),
    duration_minutes: 60,
    mode: 'video' as InterviewRecordMode,
    status: 'in_progress' as InterviewRecordStatus,
    questions: [] as InterviewRecordQuestion[],
    summary: '',
    private_notes: '',
    recommendation: null,
    overall_rating: null,
    overall_score: null,
  })
  recordNotice.value = ''
  workspaceError.value = ''
  recordFormBaseline.value = recordFormSnapshot()
  try {
    const plan = await ensureQuestionPlan(workspaceApplication.value, stage)
    if (!editingRecord.value && recordForm.stage === stage) {
      recordForm.question_plan_id = plan.id ?? null
      recordForm.questions = planQuestions(workspaceApplication.value.id, stage)
      recordFormBaseline.value = recordFormSnapshot()
    }
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法載入系統面試題'
  }
}

function editRecord(record: InterviewRecordDto) {
  editingRecord.value = record
  recordEditorOpen.value = true
  reopenPromptOpen.value = false
  reopenReason.value = ''
  questionTextEditing.value = {}
  clearRecordValidation()
  Object.assign(recordForm, {
    stage: record.stage,
    question_plan_id: record.question_plan_id,
    interviewed_at: toLocalDateTime(record.interviewed_at),
    duration_minutes: record.duration_minutes ?? 60,
    mode: record.mode,
    status: record.status,
    questions: record.questions.map(question => ({ ...question })),
    summary: record.summary || '',
    private_notes: record.private_notes || '',
    recommendation: record.recommendation || null,
    overall_rating: record.overall_rating ?? null,
    overall_score: record.overall_score ?? null,
  })
  recordNotice.value = ''
  workspaceError.value = ''
  recordFormBaseline.value = recordFormSnapshot()
}

function addBlankQuestion() {
  workspaceError.value = ''
  clearRecordValidation()
  recordForm.questions.push({ question: '', trait: null, response: '', rating: null, not_asked_reason: null, notes: '' })
}

function removeRecordQuestion(index: number) {
  workspaceError.value = ''
  clearRecordValidation()
  recordForm.questions.splice(index, 1)
}

async function addSuggestedQuestion(question: InterviewQuestion, trait: string) {
  if (!workspaceApplication.value) return
  if (recordEditorOpen.value && !recordCanEdit.value) {
    workspaceError.value = recordIsCompleted.value
      ? '已提交的評分為唯讀；重新開啟後才能調整題目'
      : '目前帳號不能修改這筆面試紀錄'
    return
  }
  if (!recordEditorOpen.value || !canEditStage(recordForm.stage)) {
    await newRecord(inlineStage(workspaceApplication.value.id))
  }
  if (recordForm.questions.some(item => item.question === question.question)) return
  workspaceError.value = ''
  recordForm.questions.push({
    question: question.question,
    trait,
    response: '',
    rating: null,
    not_asked_reason: null,
    notes: '',
    purpose: question.purpose,
    follow_up: question.follow_up,
    source: question.source,
  })
  recordNotice.value = `已將「${trait}」題目加入面試紀錄`
}

function toggleTrait(trait: string) {
  if (selectedTraits.value.includes(trait)) {
    selectedTraits.value = selectedTraits.value.filter(item => item !== trait)
  } else if (selectedTraits.value.length < 10) {
    selectedTraits.value.push(trait)
  }
  questionSuggestions.value = null
}

function addCustomTrait() {
  const value = customTrait.value.trim()
  if (!value || selectedTraits.value.includes(value) || selectedTraits.value.length >= 10) return
  selectedTraits.value.push(value)
  customTrait.value = ''
  questionSuggestions.value = null
}

async function generateQuestions() {
  if (!workspaceApplication.value || !selectedTraits.value.length) {
    workspaceError.value = '請先選擇至少一項人格特質'
    return
  }
  questionLoading.value = true
  workspaceError.value = ''
  try {
    questionSuggestions.value = (await hrApi.applicationInterviewQuestionSuggestions(
      workspaceApplication.value.id,
      selectedTraits.value,
    )).data
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法產生面試題建議'
  } finally {
    questionLoading.value = false
  }
}

function optionalText(value: string | null | undefined) {
  return value?.trim() || null
}

function validateRecordForSubmission() {
  clearRecordValidation()
  let firstInvalidId = ''
  const questionErrors: Record<number, string> = {}
  if (!recordForm.questions.length) {
    workspaceError.value = '提交評分前至少需要一題面試題'
    focusRecordControl('interview-record-add-question')
    return false
  }
  recordForm.questions.forEach((question, index) => {
    if (!question.question.trim()) {
      questionErrors[index] = '請先填寫問題內容'
      firstInvalidId ||= questionTextId(index)
      return
    }
    if (questionIsSkipped(question)) {
      if (!question.not_asked_reason?.trim()) {
        questionErrors[index] = '選擇「未詢問」時，必須填寫原因'
        firstInvalidId ||= questionNotAskedReasonId(index)
      }
      return
    }
    if (!validRating(question.rating)) {
      questionErrors[index] = '請選擇 1–5 分，或標記為「未詢問」並說明原因'
      firstInvalidId ||= questionRatingId(index, 1)
    }
  })
  recordValidationErrors.questions = questionErrors
  if (!validScore(recordForm.overall_score)) {
    recordValidationErrors.overall = '請填寫 0–100 的面試總分'
    firstInvalidId ||= overallScoreId()
  }
  if (!recordForm.recommendation) {
    recordValidationErrors.recommendation = '請選擇錄用建議'
    firstInvalidId ||= `${recordControlPrefix()}-recommendation`
  }
  if (!recordForm.summary?.trim()) {
    recordValidationErrors.summary = '請填寫面試總評'
    firstInvalidId ||= `${recordControlPrefix()}-summary`
  }
  if (!firstInvalidId) return true
  workspaceError.value = '尚有必填評分未完成，請依下方提示補齊後再提交'
  focusRecordControl(firstInvalidId)
  return false
}

async function saveRecord(intent: 'draft' | 'submit') {
  const application = workspaceApplication.value
  if (!application) return
  if (!recordCanEdit.value) {
    workspaceError.value = recordIsCompleted.value
      ? '已提交的評分為唯讀；請先使用「重新開啟評分」'
      : '目前帳號不能維護這個面試階段的紀錄'
    return
  }
  const interviewedAt = new Date(recordForm.interviewed_at)
  if (Number.isNaN(interviewedAt.getTime())) {
    workspaceError.value = '請填寫正確的面試日期與時間'
    return
  }
  if (recordForm.duration_minutes !== null && recordForm.duration_minutes !== undefined
      && (recordForm.duration_minutes < 1 || recordForm.duration_minutes > 1440)) {
    workspaceError.value = '面試時長必須介於 1 到 1440 分鐘'
    return
  }
  if (recordForm.overall_score !== null && recordForm.overall_score !== undefined
      && !validScore(recordForm.overall_score)) {
    workspaceError.value = '面試總分必須介於 0 到 100 分'
    focusRecordControl(overallScoreId())
    return
  }
  if (intent === 'submit' && !recordHasExceptionalStatus.value && !validateRecordForSubmission()) {
    return
  }
  if (intent === 'draft') clearRecordValidation()
  const questions = recordForm.questions
    .filter(item => item.question.trim())
    .map(item => {
      const notAskedReason = optionalText(item.not_asked_reason)
      return {
        question: item.question.trim(),
        trait: optionalText(item.trait),
        response: optionalText(item.response),
        rating: !notAskedReason && validRating(item.rating) ? Number(item.rating) : null,
        not_asked_reason: notAskedReason,
        notes: optionalText(item.notes),
        purpose: optionalText(item.purpose),
        follow_up: optionalText(item.follow_up),
        source: optionalText(item.source),
      }
    })
  const targetStatus: InterviewRecordStatus = recordHasExceptionalStatus.value
    ? recordForm.status
    : intent === 'submit' ? 'completed' : 'in_progress'
  recordSaving.value = true
  recordSaveIntent.value = intent
  workspaceError.value = ''
  try {
    const payload: InterviewRecordWrite = {
      stage: recordForm.stage,
      question_plan_id: recordForm.question_plan_id ?? null,
      interviewed_at: interviewedAt.toISOString(),
      duration_minutes: recordForm.duration_minutes ? Number(recordForm.duration_minutes) : null,
      mode: recordForm.mode,
      status: targetStatus,
      questions,
      summary: optionalText(recordForm.summary),
      private_notes: recordForm.stage === 'hr' ? optionalText(recordForm.private_notes) : undefined,
      recommendation: recordForm.recommendation || null,
      overall_rating: recordForm.overall_rating ? Number(recordForm.overall_rating) : null,
      overall_score: validScore(recordForm.overall_score) ? Number(recordForm.overall_score) : null,
    }
    const saved = editingRecord.value
      ? (await hrApi.updateInterviewRecord(application.id, editingRecord.value.id, {
          interviewed_at: payload.interviewed_at,
          duration_minutes: payload.duration_minutes,
          mode: payload.mode,
          status: payload.status,
          questions: payload.questions,
          summary: payload.summary,
          ...(payload.stage === 'hr' ? { private_notes: payload.private_notes } : {}),
          recommendation: payload.recommendation,
          overall_rating: payload.overall_rating,
          overall_score: payload.overall_score,
        })).data
      : (await hrApi.createInterviewRecord(application.id, payload)).data
    const successMessage = targetStatus === 'completed'
      ? '評分已提交；這筆紀錄現在為唯讀'
      : targetStatus === 'cancelled'
        ? '面試取消狀態已儲存'
        : targetStatus === 'no_show'
          ? '未到場狀態已儲存'
          : editingRecord.value ? '面試草稿已更新' : '面試草稿已建立'
    await loadInterviewRecords(application.id)
    editRecord(saved)
    workspaceError.value = ''
    recordNotice.value = successMessage
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法儲存面試過程紀錄'
  } finally {
    recordSaving.value = false
    recordSaveIntent.value = null
  }
}

async function showReopenPrompt() {
  if (!canReopenRecord(editingRecord.value)) return
  reopenPromptOpen.value = true
  reopenReason.value = ''
  workspaceError.value = ''
  await nextTick()
  reopenReasonInput.value?.focus()
}

function cancelReopenPrompt() {
  if (recordReopening.value) return
  reopenPromptOpen.value = false
  reopenReason.value = ''
}

async function reopenRecord() {
  const application = workspaceApplication.value
  const record = editingRecord.value
  if (!application || !record || !canReopenRecord(record)) return
  const reason = reopenReason.value.trim()
  if (!reason) {
    workspaceError.value = '重新開啟評分前，請填寫原因'
    reopenReasonInput.value?.focus()
    return
  }
  recordReopening.value = true
  workspaceError.value = ''
  try {
    const reopened = (await hrApi.reopenInterviewRecord(application.id, record.id, reason)).data
    await loadInterviewRecords(application.id)
    editRecord(reopened)
    recordNotice.value = reopened.revision_number > 0
      ? `評分已重新開啟；目前正式修訂為 #${reopened.revision_number}，再次提交後修訂編號會遞增`
      : '評分已重新開啟'
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法重新開啟這筆評分'
  } finally {
    recordReopening.value = false
  }
}

function answeredQuestionCount(record: InterviewRecordDto) {
  return record.questions.filter(question => question.response?.trim()).length
}

function formatDate(value: string | null) {
  if (!value) return '尚未安排'
  return formatApiDateTime(value)
}

function collapseForFilterChange() {
  if (expandedApplicationId.value === null) return
  const wasDirty = recordFormIsDirty.value
  pendingDiscard.value = null
  expandedApplicationId.value = null
  resetRecordEditor()
  interviewRecords.value = []
  if (wasDirty) notice.value = '已切換篩選條件並收合評分表；尚未儲存的評分內容未保留。'
}

function onRequisitionFilterChange() {
  collapseForFilterChange()
  focusError.value = ''
  emit('requisition-selected', requisitionId.value)
}

function onDepartmentFilterChange() {
  if (requisitionId.value !== null && !requisitions.value.some(requisition => requisition.id === requisitionId.value)) {
    requisitionId.value = null
  }
  collapseForFilterChange()
  focusError.value = ''
  emit('requisition-selected', requisitionId.value)
}

watch(departmentId, () => {
  if (requisitionId.value !== null && !requisitions.value.some(requisition => requisition.id === requisitionId.value)) {
    requisitionId.value = null
  }
})

watch(() => props.focusRequestKey, () => {
  void load()
})

watch(() => props.refreshKey, () => {
  void load()
})

watch(
  [() => props.focusApplicationId, () => props.focusRequisitionId],
  () => {
    if (!loading.value) void applyFocusContext()
  },
)

onMounted(load)
</script>

<template>
  <section class="interview-page" data-testid="interview-management">
    <header v-if="!props.embedded" class="interview-hero">
      <div><p>INTERVIEW SCHEDULE</p><h1>面試安排</h1><span>集中查看應徵者、安排面試時間並記錄結果；主管只會看到自己部門的資料。</span></div>
      <button class="button secondary" data-testid="interviews-refresh" :disabled="loading" @click="load">{{ loading ? '同步中…' : '重新同步' }}</button>
    </header>
    <header v-else class="interview-embedded-heading panel" data-testid="interview-embedded-heading">
      <div>
        <small>{{ hasFocusContext ? '已從人才評估帶入' : 'INTERVIEW WORKFLOW' }}</small>
        <h2>面試流程</h2>
        <p>{{ focusContextDescription }}</p>
      </div>
      <div class="interview-embedded-actions">
        <button class="button secondary" type="button" data-testid="interviews-back-to-assessment" @click="emit('back-to-assessment')">← 返回人才評估</button>
        <button class="button secondary" data-testid="interviews-refresh" :disabled="loading" @click="load">{{ loading ? '同步中…' : '重新同步' }}</button>
      </div>
    </header>

    <div v-if="error" class="interview-alert error" role="alert" data-testid="interview-error"><strong>!</strong><span>{{ error }}</span><button aria-label="關閉錯誤訊息" @click="error = ''">×</button></div>
    <div v-if="focusError" class="interview-alert error" role="alert" data-testid="interview-focus-error"><strong>!</strong><span>{{ focusError }}</span><button aria-label="關閉帶入錯誤訊息" @click="focusError = ''">×</button></div>
    <div v-if="notice" class="interview-alert success" role="status" data-testid="interview-success"><strong>✓</strong><span>{{ notice }}</span><button aria-label="關閉成功訊息" @click="notice = ''">×</button></div>

    <div class="interview-metrics">
      <article><small>應徵紀錄</small><strong>{{ applications.length }}</strong><span>目前權限範圍</span></article>
      <article><small>已安排面試</small><strong>{{ scheduledCount }}</strong><span>已有日期與時間</span></article>
      <article><small>即將面試</small><strong>{{ upcomingCount }}</strong><span>時間尚未到且未取消</span></article>
      <article><small>已有結果</small><strong>{{ completedCount }}</strong><span>不含待面試／待結果</span></article>
    </div>

    <div class="interview-filters">
      <div><strong>篩選面試名單</strong><span>可依部門與職缺縮小範圍；點整列即可展開該人的面試與評分</span></div>
      <label>部門<select v-model="departmentId" data-testid="interview-department-filter" @change="onDepartmentFilterChange"><option :value="null">全部部門</option><option v-for="department in departments" :key="department.id" :value="department.id">{{ department.name }}</option></select></label>
      <label>職缺<select v-model="requisitionId" data-testid="interview-job-filter" @change="onRequisitionFilterChange"><option :value="null">全部職缺</option><option v-for="requisition in requisitions" :key="requisition.id" :value="requisition.id">{{ requisition.req_no }} · {{ requisition.title }}</option></select></label>
      <em>{{ filteredApplications.length }} 筆</em>
    </div>

    <details class="interview-sharing-policy" data-testid="interview-sharing-policy">
      <summary><strong>問答共享、評分分開</strong><span>查看資料規則</span></summary>
      <div class="sharing-policy-details">
        <p><b>問答</b><span>HR 與主管都能查看問題、回答與目前進度。</span></p>
        <p><b>評分</b><span>雙方都提交後，才互相公開評分、觀察與錄用建議。</span></p>
        <p v-if="authSession.state.user?.role === 'hr'"><b>HR 備註</b><span>敏感資訊只提供 HR 查看。</span></p>
      </div>
    </details>

    <div v-if="loading && !applications.length" class="interview-empty panel"><span class="spinner"></span><strong>正在載入應徵與面試資料…</strong></div>
    <div v-else-if="filteredApplications.length" class="interview-list">
      <article v-for="application in filteredApplications" :key="application.id" class="interview-card panel" :class="{ expanded: expandedApplicationId === application.id }" :data-testid="`interview-application-${application.id}`">
        <header class="interview-row-summary">
          <button
            type="button"
            class="interview-row-toggle"
            :aria-expanded="expandedApplicationId === application.id"
            :aria-controls="`interview-detail-${application.id}`"
            :data-testid="`interview-row-toggle-${application.id}`"
            @click="toggleApplicationDetails(application.id)"
          >
            <div class="candidate-identity"><span>{{ application.candidate.name.slice(0, 1) }}</span><div><h2>{{ application.candidate.name }}</h2><p>{{ application.candidate.code }} · {{ application.candidate.current_title || '尚未填寫職稱' }}</p></div></div>
            <div class="interview-row-progress">
              <span class="application-status" :data-status="application.status">{{ applicationStatusLabels[application.status] || application.status }}</span>
              <strong>HR：{{ resultLabels[application.hr_interview.interview_result || 'pending'] }} · 主管：{{ resultLabels[application.manager_interview.interview_result || 'pending'] }}</strong>
              <small>最近面試：{{ formatDate(nearestInterviewAt(application)) }} · {{ inlineStage(application.id) === 'hr' ? 'HR' : '主管' }}題目 {{ stageAnsweredCount(application.id, inlineStage(application.id)) }}/5</small>
            </div>
            <span class="row-chevron" aria-hidden="true">{{ expandedApplicationId === application.id ? '−' : '＋' }}</span>
          </button>
        </header>

        <div v-if="expandedApplicationId === application.id" :id="`interview-detail-${application.id}`" class="interview-card-detail" @keydown.esc="requestCollapseApplicationCard">
          <details class="application-meta">
            <summary>
              <strong>{{ application.requisition.req_no }} · {{ application.requisition.title }}</strong>
              <span>{{ application.requisition.department_name || `部門 #${application.requisition.department_id || '—'}` }} · {{ application.requisition.work_city }} · 應徵於 {{ formatDate(application.applied_at) }}</span>
              <em>聯絡資訊</em>
            </summary>
            <div class="application-details">
              <div><small>Email</small><strong>{{ application.candidate.email || '未提供' }}</strong></div>
              <div><small>電話</small><strong>{{ application.candidate.phone || '未提供' }}</strong></div>
              <div><small>應徵來源</small><strong>{{ application.source || '未提供' }}</strong></div>
            </div>
          </details>

          <div v-if="cardInterviewErrors[application.id]" class="workspace-message error" role="alert"><strong>!</strong><span>{{ cardInterviewErrors[application.id] }}</span></div>
          <div v-if="workspaceError" class="workspace-message error" role="alert"><strong>!</strong><span>{{ workspaceError }}</span><button type="button" aria-label="關閉錯誤訊息" @click="workspaceError = ''">×</button></div>
          <div v-if="recordNotice" class="workspace-message success" role="status"><strong>✓</strong><span>{{ recordNotice }}</span><button type="button" aria-label="關閉成功訊息" @click="recordNotice = ''">×</button></div>

          <div class="question-stage-tabs" role="tablist" aria-label="切換 HR 初談或主管複試">
            <button
              v-for="stage in interviewStages"
              :key="stage.key"
              type="button"
              role="tab"
              :class="{ active: inlineStage(application.id) === stage.key }"
              :aria-selected="inlineStage(application.id) === stage.key"
              :data-testid="`question-stage-${application.id}-${stage.key}`"
              @click="switchCardStage(application, stage.key)"
            >
              <small>{{ stage.owner }}</small><strong>{{ stageAnsweredCount(application.id, stage.key) }}/5</strong><span>{{ stageSubmissionLabel(application.id, stage.key) }}</span>
            </button>
          </div>

          <div class="consensus-strip" :class="interviewConsensus(application.id).state">
            <div class="consensus-verdict">
              <strong>{{ interviewConsensus(application.id).label }}</strong>
              <span>{{ interviewConsensus(application.id).detail }}</span>
            </div>
            <div v-if="interviewConsensus(application.id).combined" class="consensus-score">
              <strong>{{ interviewConsensus(application.id).combined }}</strong>
              <small>面試綜合分 · 參考值</small>
            </div>
            <details class="score-overview">
              <summary>六項分數總覽</summary>
              <div>
                <p class="score-overview-note">六項都是 0–100 分制。缺少的項目一律標示原因，不以 0 分計 —— 0 分是「表現不佳」的真實評價，與「沒有資料」不同。</p>
                <ol>
                  <li><b>① 履歷匹配</b><strong>{{ matchScoreByApplication[application.id] ?? '—' }}</strong><small>{{ matchScoreByApplication[application.id] === null ? '此人才未經媒合計算（例如由 HR 手動建立）' : matchScoreByApplication[application.id] === undefined ? '載入中…' : '履歷與職缺條件的符合度' }}</small></li>
                  <li v-for="stage in interviewStages" :key="`q-${stage.key}`"><b>{{ stage.key === 'hr' ? '②' : '④' }} {{ stage.owner }} 題目</b><strong>{{ stageQuestionScore(application.id, stage.key) ?? '—' }}</strong><small>{{ stageQuestionScore(application.id, stage.key) === null ? stageScoreReason(application.id, stage.key) : `${stageRatedCount(application.id, stage.key)} 題已評分，未詢問不計入` }}</small></li>
                  <li v-for="stage in interviewStages" :key="`o-${stage.key}`"><b>{{ stage.key === 'hr' ? '③' : '⑤' }} {{ stage.owner }} 總結</b><strong>{{ validScore(currentPlanRecord(application.id, stage.key)?.overall_score) ? currentPlanRecord(application.id, stage.key)?.overall_score : '—' }}</strong><small>{{ validScore(currentPlanRecord(application.id, stage.key)?.overall_score) ? '面試官依整體表現填寫' : stageScoreReason(application.id, stage.key) }}</small></li>
                  <li class="composite"><b>⑥ 綜合參考分</b><strong>{{ application.composite_score ?? '—' }}</strong><small>{{ compositeNote(application) }}</small></li>
                </ol>
                <div v-if="compositeBreakdown(application)" class="score-weights">
                  <b>權重明細</b>
                  <span v-for="(detail, key) in compositeBreakdown(application)!.components" :key="key">{{ compositeComponentLabels[key] }}：設定 {{ Math.round(detail.weight * 100) }}%<template v-if="detail.applied_weight !== detail.weight"> · 實際計入 {{ Math.round(detail.applied_weight * 100) }}%</template><template v-if="detail.excluded_reason"> · 已排除（{{ compositeExclusionLabels[detail.excluded_reason] || detail.excluded_reason }}）</template></span>
                </div>
              </div>
            </details>
            <div class="consensus-sides">
              <span v-for="stage in interviewStages" :key="stage.key">
                <b>{{ stage.owner }}</b>
                <template v-if="currentPlanRecord(application.id, stage.key)?.status === 'completed'">題目 {{ stageQuestionScore(application.id, stage.key) ?? '—' }}<em v-if="stageRatedCount(application.id, stage.key)">（{{ stageRatedCount(application.id, stage.key) }} 題）</em> · 總結 {{ validScore(currentPlanRecord(application.id, stage.key)?.overall_score) ? currentPlanRecord(application.id, stage.key)?.overall_score : '—' }}<template v-if="currentPlanRecord(application.id, stage.key)?.recommendation"> · {{ recommendationLabels[currentPlanRecord(application.id, stage.key)!.recommendation!] }}</template></template>
                <template v-else>{{ stageSubmissionLabel(application.id, stage.key) }}</template>
              </span>
            </div>
          </div>

          <div v-if="pendingDiscard" class="record-discard-confirm" role="alert">
            <div><strong>這一關的評分內容尚未儲存</strong><span>{{ pendingDiscard.type === 'stage' ? '切換到另一關' : '離開這張卡片' }}會放棄目前填寫的內容。</span></div>
            <div><button class="button secondary" type="button" @click="cancelPendingDiscard">留在這裡</button><button class="button primary" type="button" @click="confirmPendingDiscard">放棄並繼續</button></div>
          </div>

          <template v-for="stage in interviewStages" :key="stage.key">
          <div v-if="inlineStage(application.id) === stage.key" class="card-stage-body">
            <div class="stage-grid">
              <section class="interview-stage" :class="{ unscheduled: !stageData(application, stage.key).interview_at }" :data-testid="`interview-stage-${application.id}-${stage.key}`">
                <div class="stage-line">
                  <strong>{{ formatDate(stageData(application, stage.key).interview_at) }}</strong>
                  <span class="stage-result">{{ resultLabels[stageData(application, stage.key).interview_result || 'pending'] }}</span>
                  <details class="stage-note">
                    <summary>備註與紀錄</summary>
                    <div>
                      <small>{{ stage.notesLabel }}</small>
                      <p>{{ stageData(application, stage.key).interview_notes || '尚未填寫共享備註。' }}</p>
                      <template v-if="latestStageRecord(application.id, stage.key)">
                        <small>結構化面試紀錄 · {{ structuredRecordStatus(application.id, stage.key) }}</small>
                        <p :class="{ 'structured-record-locked': structuredRecordLocked(application.id, stage.key) }">{{ structuredRecordSummaryForStage(application.id, stage.key) }}</p>
                      </template>
                      <small v-if="stageData(application, stage.key).updated_at">最後更新：{{ formatDate(stageData(application, stage.key).updated_at) }}</small>
                    </div>
                  </details>
                  <span v-if="!canEditStage(stage.key)" class="stage-readonly">僅供檢視</span>
                  <button v-else class="button secondary" type="button" :data-testid="`interview-edit-${application.id}-${stage.key}`" @click="openEditor(application, stage.key)">{{ stageData(application, stage.key).interview_at ? '編輯排程' : '安排並註記' }}</button>
                </div>

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
              <details class="peer-stage-note">
                <summary>另一關（{{ peerStage(stage.key).owner }}）：{{ resultLabels[stageData(application, peerStage(stage.key).key).interview_result || 'pending'] }} · {{ formatDate(stageData(application, peerStage(stage.key).key).interview_at) }}</summary>
                <div><small>{{ peerStage(stage.key).notesLabel }}</small><p>{{ stageData(application, peerStage(stage.key).key).interview_notes || '尚未填寫共享備註。' }}</p></div>
              </details>
            </div>

            <form class="record-editor" data-testid="interview-record-form" @submit.prevent>
              <header>
                <h3>面試題目與評分</h3>
                <div class="record-answer-progress"><strong>{{ recordEvaluatedCount }}/{{ recordQuestionTotal }}</strong><span>已評分</span></div>
              </header>

              <div v-if="recordEditorOpen && !recordCanEdit" class="record-readonly-notice" role="note">
                <span aria-hidden="true">🔒</span>
                <div><strong>{{ recordIsCompleted ? '這筆評分已提交，內容為唯讀' : `這一關由${stage.owner}維護，你目前為唯讀` }}</strong><p>{{ readOnlyStageReason(stage.key) }}</p></div>
                <button v-if="canReopenRecord(editingRecord) && !reopenPromptOpen" class="button primary" type="button" data-testid="interview-record-reopen-top" :disabled="recordReopening" @click="showReopenPrompt">重新開啟評分</button>
              </div>
              <div v-else-if="!recordEditorOpen" class="record-readonly-notice" role="note">
                <span aria-hidden="true">🔒</span>
                <div><strong>這一關由{{ stage.owner }}維護，你目前為唯讀</strong><p>{{ readOnlyStageReason(stage.key) }}</p></div>
              </div>
              <section v-if="reopenPromptOpen && canReopenRecord(editingRecord)" class="record-reopen-panel" aria-labelledby="record-reopen-title">
                <div><strong id="record-reopen-title">重新開啟評分</strong><p>請留下原因供稽核；重新開啟後會回到草稿狀態，再次提交時才會遞增修訂編號。</p></div>
                <label>重新開啟原因 *<input ref="reopenReasonInput" v-model="reopenReason" maxlength="1000" :disabled="recordReopening" placeholder="例如：補充面試證據後需要調整第 3 題評分" @keydown.enter.prevent="reopenRecord"></label>
                <div><button class="button secondary" type="button" :disabled="recordReopening" @click="cancelReopenPrompt">取消</button><button class="button primary" type="button" :disabled="recordReopening || !reopenReason.trim()" @click="reopenRecord">{{ recordReopening ? '重新開啟中…' : '確認重新開啟' }}</button></div>
              </section>

              <div v-if="editingRecord && !editorEvaluationVisible" class="evaluation-lock-notice"><span>🔒</span><div><strong>{{ evaluationWaitingFor(application.id) ? `目前等待${evaluationWaitingFor(application.id)}提交，之後評分會自動互相公開` : '雙方各自評分中，提交後會自動互相公開' }}</strong><p>問答內容現在就已共享；單題評分、面試官觀察、總結與錄用建議會在 HR 與主管都按下「提交評分」後自動顯示，不需要任何人核准。先各自評分再一起討論，是為了避免先看到對方分數造成判斷偏移。</p></div></div>

              <fieldset :disabled="recordSaving || recordReopening">
                <details v-if="recordEditorOpen" class="record-basic-details">
                  <summary><div><strong>面試基本資料</strong><span>{{ stage.title }} · {{ recordModeLabels[recordForm.mode] }} · {{ recordStatusLabels[recordForm.status] }}</span></div><em>查看／修改</em></summary>
                  <div class="record-meta-grid">
                    <label>面試日期與時間 *<input v-model="recordForm.interviewed_at" type="datetime-local" :disabled="!recordCanEdit" required></label>
                    <label>面試方式<select v-model="recordForm.mode" :disabled="!recordCanEdit"><option v-for="(label, value) in recordModeLabels" :key="value" :value="value">{{ label }}</option></select></label>
                    <label>紀錄狀態<select v-model="recordForm.status" :disabled="!recordCanEdit" aria-describedby="record-status-help"><option value="in_progress">填寫中</option><option value="cancelled">已取消</option><option value="no_show">未到場</option><option v-if="recordForm.status === 'planned'" value="planned" disabled>已規劃</option><option v-if="recordForm.status === 'completed'" value="completed" disabled>已提交評分</option></select><small id="record-status-help">正常流程請用下方「儲存草稿」或「提交評分」；此處僅保留取消／未到場。</small></label>
                    <label>面試時長（分鐘）<input v-model.number="recordForm.duration_minutes" type="number" min="1" max="1440" :disabled="!recordCanEdit"></label>
                  </div>
                </details>

                <section class="question-progress" :data-testid="`interview-question-progress-${application.id}`">
                  <div class="question-plan-meta">
                    <b v-if="cardStageQuestions.length && !cardStageComplianceWarnings" class="compliance-chip">合規檢查通過</b>
                    <b v-else-if="cardStageComplianceWarnings" class="compliance-chip warn">{{ cardStageComplianceWarnings }} 題疑似違法</b>
                    <button v-if="canGenerateQuestionStage(stage.key) && !cardStagePlan?.questions.length" type="button" class="button generation-button" :disabled="cardStageGenerating" :data-testid="`question-plan-generate-${application.id}-${stage.key}`" @click="generateCardQuestionPlan(application, stage.key)">{{ cardStageGenerating ? '產生中…' : '使用 Gemini 產生 5 題' }}</button>
                    <b class="evaluation-release-chip" :class="{ unlocked: peerEvaluationsReleased(application.id) || !blindReviewEnabled(application), shared: !blindReviewEnabled(application) }">{{ evaluationReleaseHint(application) }}</b>
                    <small v-if="cardStageEditable && editorEvaluationVisible" class="meta-progress">已評 {{ recordRatedCount }} · 略過 {{ recordSkippedCount }} · 共 {{ recordQuestionTotal }} 題</small>
                    <details class="record-meta-summary">
                      <summary>紀錄資訊</summary>
                      <div>
                        <span v-if="cardStagePlan?.version"><b>題目版本</b> v{{ cardStagePlan.version }} · {{ formatDate(cardStagePlan.generated_at || null) }}</span>
                        <span v-else-if="currentPlanRecord(application.id, stage.key)"><b>紀錄更新</b>{{ formatDate(currentPlanRecord(application.id, stage.key)?.updated_at || null) }}</span>
                        <span v-else><b>題目版本</b>尚未開始填答</span>
                        <span v-if="cardStagePlan"><b>產生方式</b>{{ generationModeLabel(cardStagePlan) }}<template v-if="tokenSummary(cardStagePlan)"> · {{ tokenSummary(cardStagePlan) }}</template></span>
                        <span v-if="editingRecord"><b>紀錄修訂</b>{{ editingRecord.revision_number > 0 ? `#${editingRecord.revision_number}` : '尚未提交（#0）' }}</span>
                        <span v-if="editingRecord?.submitted_at"><b>最近提交</b>{{ editingRecord.submitted_by_name || '原面試官' }} · {{ formatDate(editingRecord.submitted_at) }}</span>
                        <span v-if="editingRecord?.last_reopen_reason"><b>重新開啟原因</b>{{ editingRecord.last_reopen_reason }}</span>
                      </div>
                    </details>
                    <details v-if="cardStageEditable && editorEvaluationVisible" class="rating-scale-guide"><summary>1–5 分量表</summary><ol><li v-for="scale in ratingScale" :key="scale.value"><b>{{ scale.value }}</b><span>{{ scale.label }}</span></li></ol></details>
                  </div>
                  <div v-if="cardStageAlert" class="question-alert" :class="cardStageAlert.tone" :role="cardStageAlert.tone === 'error' ? 'alert' : 'status'"><strong>{{ cardStageAlert.title }}</strong><span>{{ cardStageAlert.text }}</span></div>

                  <div v-if="cardDataLoading[application.id] && !cardStageQuestions.length" class="question-progress-loading"><span class="spinner"></span>正在準備 5 題…</div>
                  <template v-else>
                    <div v-if="recordHasExceptionalStatus && recordCanEdit" class="exceptional-status-note" role="note"><strong>{{ recordForm.status === 'cancelled' ? '本次面試已取消' : '候選人未到場' }}</strong><span>可直接儲存此狀態，不強制填寫逐題與整體評分。</span></div>

                    <ol v-if="cardStageQuestions.length" class="record-question-list question-preview-list">
                      <li v-for="(question, index) in cardStageQuestions" :key="index" class="record-question-card" :class="{ invalid: cardStageEditable && recordValidationErrors.questions[index], readonly: !cardStageEditable, answered: questionIsAnswered(question) }" :data-question-index="index">
                        <header>
                          <span>{{ questionIsAnswered(question) ? '✓' : index + 1 }}</span>
                          <div class="record-question-heading">
                            <label v-if="cardStageEditable && questionTextIsEditable(question, index)" class="record-question-text-label">問題內容<textarea :id="questionTextId(index)" v-model="question.question" class="record-question-text-input" rows="2" maxlength="500" placeholder="輸入面試問題" required @input="clearQuestionValidation(index)"></textarea></label>
                            <strong v-else>{{ question.question }}</strong>
                            <div class="record-question-tools">
                              <button v-if="canGenerateQuestionStage(stage.key) && cardStagePlan?.questions[index]" type="button" class="question-regenerate-button" :disabled="cardStageGenerating" :aria-label="`重新產生第 ${index + 1} 題`" :data-testid="`question-regenerate-${application.id}-${stage.key}-${index}`" @click="regenerateCardQuestion(application, stage.key, index)">{{ questionRegenerating[questionRegenerationKey(application.id, stage.key, index)] ? '重新產生中…' : '重新產生此題' }}</button>
                              <details v-if="cardStageEditable" class="question-more">
                                <summary :aria-label="`第 ${index + 1} 題的其他操作`">⋯</summary>
                                <div>
                                  <button v-if="!questionTextIsEditable(question, index)" type="button" @click="editQuestionText(index)">修改題目文字</button>
                                  <button type="button" class="danger" @click="removeRecordQuestion(index)">移除這一題</button>
                                </div>
                              </details>
                            </div>
                          </div>
                        </header>
                        <p v-if="question.question.trim() && questionCompliance(question).status === 'warning'" class="question-compliance warning" role="alert"><b>⚠ 疑似違法提問</b><span>涉及：{{ complianceCategoryText(questionCompliance(question)) }}</span><em>{{ questionCompliance(question).suggestion }}</em></p>
                        <details v-if="question.source || question.purpose || question.follow_up" class="record-question-context">
                          <summary>需要時查看面試提示</summary>
                          <div><small v-if="question.purpose"><b>評估重點</b>{{ question.purpose }}</small><small v-if="question.follow_up"><b>建議追問</b>{{ question.follow_up }}</small><small v-if="question.source"><b>題目依據</b>{{ question.source }}</small></div>
                        </details>
                        <div v-if="cardStageEditable" class="record-quick-answer"><label><span class="answer-label">面試過程回答紀錄</span><textarea :id="`${recordControlPrefix()}-question-${index}-response`" v-model="question.response" rows="4" maxlength="5000" placeholder="記錄候選人實際說了什麼：情境、採取的行動與結果。只寫候選人陳述與客觀證據，結論請留到下方評分欄。"></textarea></label></div>
                        <div v-else class="record-quick-answer readonly"><span class="answer-label">面試過程回答紀錄</span><p :class="{ empty: !questionIsAnswered(question) }">{{ questionAnswer(question) }}</p></div>

                        <template v-if="cardStageEditable">
                          <div v-if="editorEvaluationVisible" class="question-evaluation-direct">
                            <fieldset class="rating-radio-group" :aria-describedby="recordValidationErrors.questions[index] ? `${questionRatingName(index)}-error` : undefined" :aria-invalid="Boolean(recordValidationErrors.questions[index])">
                              <legend>第 {{ index + 1 }} 題評分</legend>
                              <div class="rating-segments">
                                <label v-for="scale in ratingScale" :key="scale.value" :class="{ selected: !questionIsSkipped(question) && question.rating === scale.value }"><input :id="questionRatingId(index, scale.value)" type="radio" :name="questionRatingName(index)" :value="scale.value" :checked="!questionIsSkipped(question) && question.rating === scale.value" :aria-label="`${scale.value} 分：${scale.label}`" @change="setQuestionRating(question, index, scale.value)"><b>{{ scale.value }}</b><span>{{ scale.label }}</span></label>
                                <label class="not-asked-option" :class="{ selected: questionIsSkipped(question) }"><input :id="questionRatingId(index, 'not-asked')" type="radio" :name="questionRatingName(index)" value="not-asked" :checked="questionIsSkipped(question)" aria-label="未詢問此題" @change="setQuestionNotAsked(question, index)"><b>—</b><span>未詢問</span></label>
                              </div>
                            </fieldset>
                            <label v-if="questionIsSkipped(question)" class="not-asked-reason">未詢問原因 *<input :id="questionNotAskedReasonId(index)" v-model="question.not_asked_reason" maxlength="1000" required :aria-invalid="Boolean(recordValidationErrors.questions[index])" :aria-describedby="recordValidationErrors.questions[index] ? `${questionRatingName(index)}-error` : undefined" placeholder="例如：時間不足、題目不適用或已由前題充分涵蓋" @input="clearQuestionValidation(index)"></label>
                            <p v-if="recordValidationErrors.questions[index]" :id="`${questionRatingName(index)}-error`" class="field-error" role="alert">{{ recordValidationErrors.questions[index] }}</p>
                            <details class="question-observation-details">
                              <summary><span>對應特質與面試官觀察</span><em>{{ question.notes?.trim() ? '已有觀察' : '選填' }}</em></summary>
                              <div class="record-answer-grid"><label>對應特質<input v-model="question.trait" maxlength="100" placeholder="例如：團隊合作"></label><label class="wide">面試官觀察（評分區）<textarea v-model="question.notes" rows="2" maxlength="2000" placeholder="記錄非語言反應、待查證處或追問結果…"></textarea></label></div>
                            </details>
                          </div>
                          <div v-else class="evaluation-lock-inline"><span>🔒</span><p><b>{{ evaluationWaitingFor(application.id) ? `待${evaluationWaitingFor(application.id)}提交後自動公開評分` : '待雙方提交後自動公開評分' }}</b><small>候選人回答仍可直接查看，不需另外申請。</small></p></div>
                        </template>
                        <div v-else class="question-evaluation-readonly">
                          <template v-if="readOnlyEvaluationVisible(application.id, stage.key)"><b v-if="question.rating" class="rating-chip">{{ question.rating }} / 5 分</b><b v-else-if="question.not_asked_reason" class="rating-chip skipped">未詢問：{{ question.not_asked_reason }}</b><b v-else class="rating-chip empty">尚未評分</b><span v-if="question.notes?.trim()">面試官觀察：{{ question.notes }}</span></template>
                          <em v-else class="evaluation-locked">評分與觀察{{ evaluationWaitingFor(application.id) ? `待${evaluationWaitingFor(application.id)}提交後自動顯示` : '待雙方提交後自動顯示' }}</em>
                        </div>
                      </li>
                    </ol>
                    <div v-else class="question-preview-error">{{ cardStageQuestionError || cardInterviewErrors[application.id] || '尚未產生五題，請由這一階段的面試官按上方按鈕。' }}</div>

                    <div v-if="cardStageEditable" class="question-list-actions">
                      <button id="interview-record-add-question" class="button secondary" type="button" @click="addBlankQuestion">＋ 自訂問題</button>
                    </div>

                    <details v-if="cardStageEditable" class="question-builder">
                      <summary><div><small>OPTIONAL QUESTION TOOL</small><h3>需要加問時的特質出題工具</h3><p>五題已依所屬階段帶入；只有需要額外的人格特質或履歷追問時才使用這裡。</p></div><span>展開工具 · 已選 {{ selectedTraits.length }}/10</span></summary>
                      <div class="question-builder-body">
                        <div class="trait-picker">
                          <button v-for="trait in commonTraits" :key="trait" type="button" :class="{ selected: selectedTraits.includes(trait) }" :aria-pressed="selectedTraits.includes(trait)" @click="toggleTrait(trait)">{{ trait }}</button>
                        </div>
                        <div class="custom-trait"><input v-model="customTrait" maxlength="30" placeholder="輸入其他人格特質" @keydown.enter.prevent="addCustomTrait"><button class="button secondary" type="button" :disabled="!customTrait.trim() || selectedTraits.length >= 10" @click="addCustomTrait">加入</button></div>
                        <div v-if="selectedTraits.some(trait => !commonTraits.includes(trait))" class="selected-custom-traits"><button v-for="trait in selectedTraits.filter(trait => !commonTraits.includes(trait))" :key="trait" type="button" @click="toggleTrait(trait)">{{ trait }} ×</button></div>
                        <button class="button primary generate-questions" data-testid="interview-question-generate" type="button" :disabled="questionLoading || !selectedTraits.length" @click="generateQuestions">{{ questionLoading ? '正在產生建議…' : `產生 ${application.requisition.title} 面試題` }}</button>

                        <template v-if="questionSuggestions">
                          <p class="question-guidance">{{ questionSuggestions.guidance }}</p>
                          <div v-if="questionSuggestions.personalization_basis.length" class="question-personalization-basis">
                            <strong>本次出題依據</strong><span v-for="item in questionSuggestions.personalization_basis" :key="item">{{ item }}</span>
                          </div>
                          <div class="suggestion-groups">
                            <article v-for="suggestion in questionSuggestions.suggestions" :key="suggestion.trait">
                              <header><strong>{{ suggestion.trait }}</strong><span>{{ questionSuggestions.job_title }}</span></header>
                              <div v-for="suggested in suggestion.questions" :key="suggested.question" class="suggested-question">
                                <div><small v-if="suggested.source" class="question-source">履歷依據｜{{ suggested.source }}</small><strong>{{ suggested.question }}</strong><p v-if="questionCompliance(suggested).status === 'warning'" class="question-compliance warning" role="alert"><b>⚠ 疑似違法提問</b><span>涉及：{{ complianceCategoryText(questionCompliance(suggested)) }}</span><em>{{ questionCompliance(suggested).suggestion }}</em></p><p v-else class="question-compliance ok"><b>✓ 合法</b></p><p><b>提問目的</b>{{ suggested.purpose }}</p><p><b>追問方向</b>{{ suggested.follow_up }}</p></div>
                                <button class="button secondary" type="button" :disabled="recordForm.questions.some(item => item.question === suggested.question) || !recordCanEdit" @click="addSuggestedQuestion(suggested, suggestion.trait)">{{ recordForm.questions.some(item => item.question === suggested.question) ? '已加入' : '加入紀錄' }}</button>
                              </div>
                            </article>
                          </div>
                        </template>
                      </div>
                    </details>
                  </template>
                </section>
              </fieldset>

              <fieldset :disabled="recordSaving || recordReopening || !recordCanEdit">
                <section v-if="editorEvaluationVisible && recordEditorOpen" class="record-conclusion-section" aria-labelledby="record-conclusion-title">
                  <header><div><strong id="record-conclusion-title">整體總評</strong><span>提交評分前，請完成面試總分、錄用建議與面試總評。</span></div><em>{{ recordForm.recommendation ? recommendationLabels[recordForm.recommendation] : '尚未填寫' }}</em></header>
                  <div class="record-conclusion">
                    <label class="overall-score-field">面試總分（0–100）*
                      <span class="overall-score-input"><input :id="overallScoreId()" :value="recordForm.overall_score ?? ''" type="number" min="0" max="100" step="1" inputmode="numeric" placeholder="例如 82" :aria-invalid="Boolean(recordValidationErrors.overall)" :aria-describedby="`${recordControlPrefix()}-overall-help`" @input="setOverallScore(($event.target as HTMLInputElement).value)"><b>／ 100</b></span>
                      <small :id="`${recordControlPrefix()}-overall-help`">由面試官依整體表現填寫，系統不會自動換算。</small>
                      <small v-if="recordValidationErrors.overall" :id="`${recordControlPrefix()}-overall-error`" class="field-error" role="alert">{{ recordValidationErrors.overall }}</small>
                      <small class="score-reference">題目平均 {{ recordAverageRating }} / 5（{{ recordEvaluatedCount }}/{{ recordQuestionTotal }} 題已評分或略過）· 僅供參考，不計入面試總分</small>
                    </label>
                    <label>錄用建議 *<select :id="`${recordControlPrefix()}-recommendation`" v-model="recordForm.recommendation" :aria-invalid="Boolean(recordValidationErrors.recommendation)" :aria-describedby="recordValidationErrors.recommendation ? `${recordControlPrefix()}-recommendation-error` : undefined" @change="recordValidationErrors.recommendation = ''"><option :value="null">尚未決定</option><option v-for="(label, value) in recommendationLabels" :key="value" :value="value">{{ label }}</option></select><small v-if="recordValidationErrors.recommendation" :id="`${recordControlPrefix()}-recommendation-error`" class="field-error" role="alert">{{ recordValidationErrors.recommendation }}</small></label>
                    <label class="wide">面試總評 *<textarea :id="`${recordControlPrefix()}-summary`" v-model="recordForm.summary" rows="4" maxlength="5000" :aria-invalid="Boolean(recordValidationErrors.summary)" :aria-describedby="recordValidationErrors.summary ? `${recordControlPrefix()}-summary-error` : undefined" placeholder="摘要主要優勢、風險、待確認事項與共識…" @input="recordValidationErrors.summary = ''"></textarea><small v-if="recordValidationErrors.summary" :id="`${recordControlPrefix()}-summary-error`" class="field-error" role="alert">{{ recordValidationErrors.summary }}</small></label>
                  </div>
                </section>
                <div v-else-if="recordEditorOpen" class="record-conclusion-locked"><span>🔒</span><div><strong>{{ evaluationWaitingFor(application.id) ? `面試總分與錄用建議待${evaluationWaitingFor(application.id)}提交後自動公開` : '面試總分與錄用建議待雙方提交後自動公開' }}</strong><p>你自己填寫的內容不受影響，隨時可以查看與修改；這裡隱藏的是對方的評估結果。</p></div></div>

                <details v-if="recordEditorOpen && recordForm.stage === 'hr' && (canEditStage('hr') || editingRecord?.private_notes_visible)" class="hr-private-notes">
                  <summary><span>HR ONLY</span><div><strong>HR 限定敏感備註（選填）</strong><small>此區內容不會出現在主管的畫面或 API 回應中。</small></div><em>{{ recordForm.private_notes?.trim() ? '已有內容' : '尚未填寫' }}</em></summary>
                  <label>私密備註<textarea v-model="recordForm.private_notes" rows="4" maxlength="10000" placeholder="例如：薪資個資、合理調整需求或其他僅限 HR 處理的敏感事項…"></textarea></label>
                </details>
              </fieldset>

              <footer>
                <span><template v-if="editingRecord">建立者：{{ editingRecord.interviewer_name }} · 更新：{{ formatDate(editingRecord.updated_at) }}<template v-if="editingRecord.submitted_at"> · 提交：{{ editingRecord.submitted_by_name || '原面試官' }}／{{ formatDate(editingRecord.submitted_at) }}</template></template><template v-else-if="recordCanEdit">草稿可隨時補填；「提交評分」後即轉為唯讀。</template><template v-else>這一關尚未建立結構化紀錄。</template></span>
                <div>
                  <button class="button secondary" type="button" :disabled="recordSaving || recordReopening" @click="requestCollapseApplicationCard">收合</button>
                  <button v-if="canReopenRecord(editingRecord) && !reopenPromptOpen" class="button secondary reopen-button" type="button" data-testid="interview-record-reopen" :disabled="recordReopening" @click="showReopenPrompt">重新開啟評分</button>
                  <template v-if="recordCanEdit">
                    <button v-if="recordHasExceptionalStatus" class="button primary" type="button" data-testid="interview-record-save-status" :disabled="recordSaving || recordReopening" @click="saveRecord('draft')">{{ recordSaving && recordSaveIntent === 'draft' ? '儲存狀態中…' : '儲存狀態' }}</button>
                    <template v-else>
                      <button class="button secondary" type="button" data-testid="interview-record-save-draft" :disabled="recordSaving || recordReopening" @click="saveRecord('draft')">{{ recordSaving && recordSaveIntent === 'draft' ? '儲存草稿中…' : '儲存草稿' }}</button>
                      <button class="button primary" type="button" data-testid="interview-record-submit" :disabled="recordSaving || recordReopening" @click="saveRecord('submit')">{{ recordSaving && recordSaveIntent === 'submit' ? '提交評分中…' : '提交評分' }}</button>
                    </template>
                  </template>
                </div>
              </footer>
            </form>
          </div>
          </template>

          <details class="record-history">
            <summary><div><strong>面試紀錄歷程</strong><span>{{ interviewRecords.length }} 筆</span></div><em>展開查看舊版問答與提交紀錄</em></summary>
            <div class="record-history-body">
              <div class="record-history-actions">
                <span>每次提交或重新開啟都會保留一筆；舊版題目的問答也在這裡。</span>
                <button v-if="canEditStage(inlineStage(application.id))" class="button secondary" type="button" data-testid="interview-record-new" :disabled="recordSaving || recordReopening" @click="startNewRecord(application)">＋ 建立新紀錄</button>
              </div>
              <div v-if="recordsLoading" class="workspace-loading"><span class="spinner"></span>載入紀錄中…</div>
              <button v-for="record in interviewRecords" v-else :key="record.id" class="record-history-item" :class="{ active: editingRecord?.id === record.id }" type="button" @click="openHistoryRecord(application, record)">
                <span class="record-status" :data-status="record.status">{{ recordStatusLabels[record.status] }}</span>
                <strong>{{ record.stage === 'hr' ? 'HR 初談' : '主管複試' }} · {{ formatDate(record.interviewed_at) }}</strong>
                <small>{{ recordModeLabels[record.mode] }}<template v-if="record.duration_minutes"> · {{ record.duration_minutes }} 分鐘</template></small>
                <small>{{ record.interviewer_name }} · 已記錄 {{ answeredQuestionCount(record) }}/{{ record.questions.length }} 題<template v-if="record.question_plan_version"> · 題目 v{{ record.question_plan_version }}</template></small>
                <small><template v-if="record.revision_number > 0">紀錄修訂 #{{ record.revision_number }}</template><template v-else>尚未正式提交</template><template v-if="record.submitted_at"> · {{ record.submitted_by_name || '原面試官' }} 於 {{ formatDate(record.submitted_at) }} 提交</template></small>
                <small class="history-visibility" :class="{ unlocked: record.evaluation_revealed }">{{ record.evaluation_revealed ? '評分可見' : '僅共享問答 · 評分保護中' }}</small>
                <em>{{ recordHistoryActionLabel(record) }} →</em>
              </button>
              <div v-if="!recordsLoading && !interviewRecords.length" class="record-history-empty"><strong>尚無過程紀錄</strong><p>目前的填寫內容按下「儲存草稿」後就會成為第一筆紀錄。</p></div>
            </div>
          </details>
        </div>
      </article>
    </div>
    <div v-else class="interview-empty panel"><strong>目前沒有符合條件的應徵者</strong><p>請調整部門／職缺篩選；HR 建立人才與應徵關聯後，也會顯示在這裡。</p></div>
  </section>
</template>

<style scoped>
/* 一張卡片＝一位應徵者＝一條由上而下的流程：職缺資訊 → 關卡 → 排程 → 題目與評分 → 總評 → 動作。 */
/* 字級只有四階：--fs-xs 輔助說明、--fs-sm 內文、--fs-md 重點、--fs-lg 區塊標題。 */
.interview-page{--fs-xs:11px;--fs-sm:13px;--fs-md:15px;--fs-lg:18px;display:grid;gap:14px}

.interview-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:25px 28px;border-radius:18px;background:linear-gradient(120deg,#153f3b,#17695f 62%,#74ad91);color:#fff;box-shadow:0 16px 38px rgba(20,74,68,.14)}.interview-hero p{margin:0;color:#f2c96d;font-size:var(--fs-xs);font-weight:800;letter-spacing:1.3px}.interview-hero h1{margin:6px 0;font-size:25px}.interview-hero span{font-size:var(--fs-sm);color:rgba(255,255,255,.78)}.interview-hero .button{background:rgba(255,255,255,.95)}
.interview-embedded-heading{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:15px 17px;border-color:#b9dbd2;background:linear-gradient(110deg,#eef8f5,#fff)}.interview-embedded-heading>div:first-child{min-width:0}.interview-embedded-heading small,.interview-embedded-heading h2,.interview-embedded-heading p{display:block}.interview-embedded-heading small{color:#a56d17;font-size:var(--fs-xs);font-weight:900;letter-spacing:1px}.interview-embedded-heading h2{margin:3px 0;font-size:var(--fs-lg)}.interview-embedded-heading p{margin:0;color:#677d77;font-size:var(--fs-sm);line-height:1.55}.interview-embedded-actions{display:flex;flex:0 0 auto;align-items:center;gap:8px}
.interview-alert{display:flex;align-items:center;gap:10px;padding:11px 14px;border:1px solid;border-radius:10px;font-size:var(--fs-sm)}.interview-alert>strong{width:22px;height:22px;border-radius:50%;display:grid;place-items:center}.interview-alert>span{flex:1}.interview-alert>button{border:0;background:transparent;color:inherit;font-size:18px}.interview-alert.error{border-color:#efd0cd;background:#fff0ef;color:#893d39}.interview-alert.error>strong{background:#e5b0ac}.interview-alert.success{border-color:#baddc3;background:#ecf8ef;color:#286547}.interview-alert.success>strong{background:#cbe8d2}

.interview-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.interview-metrics article{padding:16px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-metrics small,.interview-metrics span{display:block;color:var(--muted);font-size:var(--fs-xs)}.interview-metrics strong{display:block;margin:4px 0;color:#185e56;font-size:23px}
.interview-filters{display:flex;align-items:end;gap:12px;padding:13px 15px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-filters>div{margin-right:auto}.interview-filters>div strong,.interview-filters>div span{display:block}.interview-filters>div strong{font-size:var(--fs-md)}.interview-filters>div span{margin-top:3px;color:var(--muted);font-size:var(--fs-xs)}.interview-filters label{display:grid;gap:5px;color:#61756f;font-size:var(--fs-xs)}.interview-filters select{width:230px;height:38px;padding:0 10px;border:1px solid #d8e3df;border-radius:8px;background:#fff;color:#31534d;font-size:var(--fs-sm)}.interview-filters em{padding-bottom:10px;color:var(--muted);font-size:var(--fs-xs);font-style:normal}

/* 共享規則只在頁面說明一次，不重複出現在每張卡片。 */
.interview-sharing-policy{border:1px solid var(--line);border-radius:12px;background:#fff}.interview-sharing-policy>summary{display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer;padding:11px 15px;color:#315a53;font-size:var(--fs-sm);font-weight:700}.interview-sharing-policy>summary span{color:#39776d;font-size:var(--fs-xs);font-weight:400}.sharing-policy-details{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:0 15px 12px}.sharing-policy-details p{display:grid;gap:3px;margin:0;padding:9px 11px;border:1px solid #dbe7e3;border-radius:8px;background:#f8fbfa}.sharing-policy-details b{color:#2e6d62;font-size:var(--fs-sm)}.sharing-policy-details span{color:#71817d;font-size:var(--fs-xs);line-height:1.5}

.interview-empty{text-align:center;padding:60px 20px;color:var(--muted)}.interview-empty strong,.interview-empty p{display:block}.interview-empty strong{font-size:var(--fs-md)}.interview-empty p{font-size:var(--fs-sm)}.interview-empty .spinner{margin-bottom:12px}

/* 一人一列：排程、題目與紀錄只在點開該列後顯示；展開本身就是「開始評分」。 */
.interview-list{display:grid;grid-template-columns:1fr;gap:10px}
.interview-card{min-width:0;padding:0;overflow:hidden;transition:border-color .18s ease,box-shadow .18s ease}
.interview-card.expanded{border-color:#8fc4b7;box-shadow:0 8px 24px rgba(31,91,81,.08)}
.interview-row-summary{display:grid;grid-template-columns:minmax(0,1fr);width:100%}
.interview-row-toggle{display:grid;grid-template-columns:minmax(260px,1fr) minmax(320px,auto) 36px;align-items:center;gap:18px;width:100%;padding:14px 16px;border:0;background:#fff;color:inherit;text-align:left;cursor:pointer}
.interview-row-toggle:hover{background:#f5faf8}.interview-row-toggle:focus-visible{outline:3px solid rgba(35,130,116,.2);outline-offset:-3px}
.candidate-identity{display:flex;align-items:center;gap:10px;min-width:0}.candidate-identity>span{width:40px;height:40px;flex:0 0 auto;border-radius:50%;display:grid;place-items:center;background:#dceee8;color:#1f6b61;font-weight:800}.candidate-identity>div{min-width:0}.candidate-identity h2{margin:0;font-size:var(--fs-md)}.candidate-identity p{margin:3px 0 0;color:var(--muted);font-size:var(--fs-xs)}.interview-row-toggle .candidate-identity h2,.interview-row-toggle .candidate-identity p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.application-status{padding:4px 8px;border-radius:99px;background:#edf2f0;color:#60736e;font-size:var(--fs-xs);white-space:nowrap}.application-status[data-status="interview"],.application-status[data-status="interviewing"]{background:#e3eff9;color:#326f9d}.application-status[data-status="offered"],.application-status[data-status="hired"]{background:#e1f2e9;color:#27725b}.application-status[data-status="rejected"],.application-status[data-status="withdrawn"]{background:#f8e7e5;color:#a64b46}
.interview-row-progress{display:grid;grid-template-columns:auto minmax(210px,auto);align-items:center;justify-items:end;gap:4px 12px}.interview-row-progress .application-status{grid-row:1/3}.interview-row-progress strong{font-size:var(--fs-sm);color:#315f57}.interview-row-progress small{font-size:var(--fs-xs);color:#71847f}
.row-chevron{width:30px;height:30px;display:grid;place-items:center;border:1px solid #cfe0db;border-radius:50%;background:#f3f8f6;color:#236f64;font-size:18px;font-weight:500}
.interview-card-detail{display:grid;gap:12px;padding:14px 16px 16px;border-top:1px solid #e0ebe7;background:#fff}

/* 職缺與聯絡資訊在評分當下不是主角：一行帶過，需要時再展開。 */
.application-meta{border-radius:9px;background:#f3f8f6}
.application-meta>summary{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 10px;list-style:none;cursor:pointer;padding:10px 12px}.application-meta>summary::-webkit-details-marker{display:none}
.application-meta>summary strong{font-size:var(--fs-md);color:#245f56}.application-meta>summary span{min-width:0;flex:1;color:var(--muted);font-size:var(--fs-sm)}
.application-meta>summary em{flex:0 0 auto;color:#2f7166;font-size:var(--fs-xs);font-style:normal;font-weight:700}.application-meta>summary em:before{content:'＋';margin-right:4px}.application-meta[open]>summary em:before{content:'－'}
.application-details{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:0 12px 11px}.application-details>div{min-width:0;padding:9px 10px;border:1px solid #e8eeec;border-radius:8px}.application-details small,.application-details strong{display:block}.application-details small{color:var(--muted);font-size:var(--fs-xs)}.application-details strong{margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs-sm)}

.workspace-message{display:flex;align-items:center;gap:8px;padding:10px 13px;border:1px solid;border-radius:9px;font-size:var(--fs-sm)}.workspace-message>span{flex:1}.workspace-message>button{border:0;background:transparent;color:inherit;font-size:18px}.workspace-message.error{border-color:#eac6c2;background:#fff0ef;color:#8e403b}.workspace-message.success{border-color:#c7dfcf;background:#edf8f1;color:#2d674a}

/* 關卡頁籤是卡片的主軸：切換後排程、題目、評分與總評都跟著換。 */
.question-stage-tabs{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.question-stage-tabs button{display:grid;grid-template-columns:1fr auto;align-items:center;gap:3px 8px;min-height:62px;padding:10px 13px;border:1px solid #d4e2de;border-radius:10px;background:#fff;color:#5b706b;text-align:left;cursor:pointer}
.question-stage-tabs button small{grid-row:1;color:inherit;font-size:var(--fs-sm);font-weight:700}
.question-stage-tabs button strong{grid-area:1/2/3/3;color:#1e665b;font-size:21px}
.question-stage-tabs button span{grid-row:2;color:#82918d;font-size:var(--fs-xs)}
.question-stage-tabs button.active{border-color:#278477;background:#e7f5f1;color:#1e665b;box-shadow:0 0 0 2px rgba(39,132,119,.08)}
.question-stage-tabs button:focus-visible{outline:3px solid rgba(35,130,116,.24);outline-offset:2px}
.record-discard-confirm{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 13px;border:1px solid #e0cf9c;border-radius:9px;background:#fff9e8;color:#6e5525}.record-discard-confirm strong,.record-discard-confirm span{display:block}.record-discard-confirm strong{font-size:var(--fs-sm)}.record-discard-confirm span{margin-top:3px;color:#806b42;font-size:var(--fs-xs);line-height:1.5}.record-discard-confirm>div:last-child{display:flex;flex:0 0 auto;gap:7px}
/* 綜合分永遠與共識判定並列：95/60 與 78/77 平均相同，處理方式卻完全不同。 */
.consensus-strip{display:flex;align-items:center;flex-wrap:wrap;gap:10px 16px;padding:11px 13px;border:1px solid #dbe7e3;border-left-width:4px;border-radius:9px;background:#f8fbfa}
.consensus-strip.pending{border-left-color:#c9d6d2}
.consensus-strip.aligned{border-left-color:#2a8879;background:#f4faf7}
.consensus-strip.divergent{border-left-color:#c98a2d;background:#fff8e8}
.consensus-verdict{min-width:0;flex:1}.consensus-verdict strong,.consensus-verdict span{display:block}
.consensus-verdict strong{color:#2c4f49;font-size:var(--fs-md)}
.consensus-strip.divergent .consensus-verdict strong{color:#8a5a16}
.consensus-verdict span{margin-top:3px;color:#6b7e79;font-size:var(--fs-xs);line-height:1.55}
.consensus-score{flex:0 0 auto;display:grid;justify-items:center;padding:6px 13px;border-radius:9px;background:#fff}
.consensus-score strong{color:#1f6b60;font-size:var(--fs-lg)}.consensus-score small{color:#93a09c;font-size:var(--fs-xs)}
.score-overview{flex-basis:100%;order:9}
.score-overview>summary{list-style:none;cursor:pointer;color:#2f7166;font-size:var(--fs-xs);font-weight:700}.score-overview>summary::-webkit-details-marker{display:none}.score-overview>summary:before{content:'＋';margin-right:5px}.score-overview[open]>summary:before{content:'－'}
.score-overview>div{margin-top:9px;padding:11px 12px;border:1px solid #dbe7e3;border-radius:9px;background:#fff}
.score-overview-note{margin:0 0 9px;color:#93a09c;font-size:var(--fs-xs);line-height:1.55}
.score-overview ol{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0;padding:0;list-style:none}
.score-overview li{display:grid;gap:2px;padding:9px 10px;border:1px solid #e8eeec;border-radius:8px}
.score-overview li.composite{grid-column:1/-1;border-color:#bcded4;background:#f7fcfa}
.score-overview b{color:#2f7065;font-size:var(--fs-xs)}.score-overview strong{color:#1f6b60;font-size:var(--fs-lg)}.score-overview small{color:#8b9995;font-size:var(--fs-xs);line-height:1.5}
.score-weights{display:grid;gap:3px;margin-top:9px;padding-top:9px;border-top:1px solid #e8eeec}.score-weights b{color:#2f7065;font-size:var(--fs-xs)}.score-weights span{color:#8b9995;font-size:var(--fs-xs)}
@media(max-width:900px){.score-overview ol{grid-template-columns:1fr 1fr}}
@media(max-width:680px){.score-overview ol{grid-template-columns:1fr}}
.consensus-sides{flex:0 0 auto;display:grid;gap:3px}.consensus-sides span{color:#5f746f;font-size:var(--fs-xs)}.consensus-sides b{margin-right:6px;color:#2f7065}.consensus-sides em{color:#93a09c;font-style:normal}
@media(max-width:680px){.consensus-strip{align-items:stretch;flex-direction:column}.consensus-score{justify-items:start}}
.card-stage-body{display:grid;gap:12px}

.stage-grid{display:grid;grid-template-columns:1fr;gap:9px}
.interview-stage{min-width:0;border:1px solid #cde5dc;border-radius:10px;background:#f0f9f5;overflow:hidden}.interview-stage.unscheduled{border-style:dashed;background:#fafcfb}
/* 排程在面試當下只需要一行：時間、結果、備註入口、編輯。 */
.stage-line{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;padding:10px 13px}
.stage-line>strong{color:#245f56;font-size:var(--fs-md)}
.stage-result{padding:4px 9px;border-radius:99px;background:#fff;color:#28675d;font-size:var(--fs-xs);white-space:nowrap}
.stage-readonly{color:var(--muted);font-size:var(--fs-xs)}
.stage-line>.button{margin-left:auto}
.stage-note{position:relative;flex:0 0 auto}
.stage-note>summary{list-style:none;cursor:pointer;color:#3a7067;font-size:var(--fs-xs);font-weight:700}.stage-note>summary::-webkit-details-marker{display:none}.stage-note>summary:before{content:'＋';margin-right:4px}.stage-note[open]>summary:before{content:'－'}
.stage-note>div{position:absolute;z-index:5;top:100%;left:0;min-width:320px;max-width:min(560px,80vw);display:grid;gap:3px;margin-top:6px;padding:11px 13px;border:1px solid #dbe7e3;border-radius:9px;background:#fff;box-shadow:0 8px 22px rgba(24,74,65,.13)}
.stage-note small{margin-top:4px;color:var(--muted);font-size:var(--fs-xs)}.stage-note p{margin:2px 0 0;color:#5f746f;font-size:var(--fs-sm);line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}.stage-note p.structured-record-locked{padding:7px 9px;border:1px dashed #dfc994;border-radius:6px;background:#fffaf0;color:#876323}
.peer-stage-note{border:1px dashed #cfe0db;border-radius:9px;background:#fafcfb}.peer-stage-note>summary{list-style:none;cursor:pointer;padding:10px 13px;color:#4f6b65;font-size:var(--fs-sm)}.peer-stage-note>summary::-webkit-details-marker{display:none}.peer-stage-note>summary:before{content:'＋';margin-right:7px;color:#27766b;font-weight:800}.peer-stage-note[open]>summary:before{content:'－'}.peer-stage-note>div{padding:0 13px 11px}.peer-stage-note small{display:block;color:var(--muted);font-size:var(--fs-xs)}.peer-stage-note p{margin:4px 0 0;color:#5f746f;font-size:var(--fs-sm);line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
.interview-editor{margin:0;border:1px solid #bcdcd2;border-width:1px 0 0;background:#fbfdfc;overflow:hidden}
.interview-editor>header{display:flex;align-items:flex-start;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #dce9e5}.interview-editor>header small{color:#b37c20;font-size:var(--fs-xs);font-weight:800;letter-spacing:1px}.interview-editor>header h3{margin:3px 0 0;font-size:var(--fs-md)}.interview-editor>header button{border:0;background:transparent;color:#61736f;font-size:19px}
.editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}.editor-grid label{display:grid;gap:5px;color:#536e68;font-size:var(--fs-sm)}.editor-grid .wide{grid-column:1/-1}.editor-grid input,.editor-grid select,.editor-grid textarea{width:100%;padding:10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit;font-size:var(--fs-md)}.editor-grid textarea{resize:vertical;line-height:1.6}
.interview-editor>footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 14px;border-top:1px solid #dce9e5;background:#f5f9f7}.interview-editor>footer>span{color:var(--muted);font-size:var(--fs-xs)}.interview-editor>footer>div{display:flex;gap:7px}

/* 題目與評分：五題只渲染一次，可編輯時就是表單本身，唯讀時為純文字。 */
.record-editor{border:1px solid #d8e5e1;border-radius:12px;background:#fff;box-shadow:0 5px 18px rgba(24,74,65,.05)}
.record-editor>header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 16px;border-bottom:1px solid #e0e9e6}.record-editor>header h3{margin:0;min-width:0;flex:1;font-size:var(--fs-md)}
.record-answer-progress{flex:0 0 auto;display:flex;align-items:baseline;gap:5px;padding:5px 11px;border-radius:99px;background:#eaf6f2;color:#236b60}.record-answer-progress strong{font-size:var(--fs-md)}.record-answer-progress span{font-size:var(--fs-xs)}
.record-editor fieldset{margin:0;padding:0;border:0}
/* 唯讀說明放在表單最上方，重新開啟的入口就在旁邊。 */
.record-readonly-notice{display:flex;align-items:center;gap:11px;margin:13px 16px 0;padding:12px 13px;border:1px solid #d8c7a2;border-radius:10px;background:#fff8ea;color:#6f5726}.record-readonly-notice>span{font-size:18px}.record-readonly-notice>div{flex:1;min-width:0}.record-readonly-notice strong{display:block;font-size:var(--fs-md)}.record-readonly-notice p{margin:4px 0 0;font-size:var(--fs-sm);line-height:1.6}.record-readonly-notice .button{flex:0 0 auto}
.evaluation-lock-notice{display:flex;align-items:flex-start;gap:10px;margin:12px 16px 0;padding:11px 12px;border:1px solid #ead7ad;border-radius:9px;background:#fff9eb;color:#765722}.evaluation-lock-notice>span{font-size:16px}.evaluation-lock-notice strong{display:block;font-size:var(--fs-md)}.evaluation-lock-notice p{margin:4px 0 0;font-size:var(--fs-sm);line-height:1.6}
.record-basic-details{margin:13px 16px 0;border:1px solid #dce7e3;border-radius:9px;background:#fbfdfc}.record-basic-details>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;list-style:none;cursor:pointer;padding:12px 14px}.record-basic-details>summary::-webkit-details-marker{display:none}.record-basic-details>summary:before{content:'＋';margin-right:7px;color:#27766b;font-weight:800}.record-basic-details[open]>summary:before{content:'－'}.record-basic-details>summary strong,.record-basic-details>summary span{display:block}.record-basic-details>summary strong{color:#315d55;font-size:var(--fs-md)}.record-basic-details>summary span{margin-top:3px;color:#748681;font-size:var(--fs-sm)}.record-basic-details>summary em{color:#287469;font-size:var(--fs-sm);font-style:normal;font-weight:700}.record-basic-details[open]>summary{border-bottom:1px solid #e1e9e6}
.record-meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:13px 14px}.record-meta-grid label{display:grid;gap:5px;color:#536e68;font-size:var(--fs-sm)}.record-meta-grid label>small{color:#778984;font-size:var(--fs-xs);line-height:1.45}.record-meta-grid input,.record-meta-grid select{width:100%;padding:10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit;font-size:var(--fs-md)}

.question-progress{padding:13px 16px 0}
.question-plan-meta{display:flex;align-items:center;flex-wrap:wrap;gap:9px;padding:0 0 10px;border-bottom:1px solid #e6eeeb}.question-plan-meta>span{padding:5px 9px;border-radius:99px;background:#e7f3ef;color:#216d61;font-size:var(--fs-sm);font-weight:700}.question-plan-meta>span[data-stage="manager"]{background:#fff3d8;color:#8a621a}.question-plan-meta>small{margin-left:auto;color:#798984;font-size:var(--fs-sm)}
.generation-button{min-height:38px;padding:8px 13px;font-size:var(--fs-sm);white-space:nowrap}
.evaluation-release-chip{padding:5px 9px;border-radius:99px;background:#fff0df;color:#93601c;font-size:var(--fs-xs);font-weight:700}.evaluation-release-chip.unlocked{background:#e1f3e9;color:#257052}.evaluation-release-chip.shared{background:#e3eff9;color:#326f9d}
.meta-progress{margin-left:0!important;color:#5f746f}
.record-meta-summary,.question-more{position:relative}
.record-meta-summary>summary,.question-more>summary{list-style:none;cursor:pointer;color:#3a7067;font-size:var(--fs-xs);font-weight:700}.record-meta-summary>summary::-webkit-details-marker,.question-more>summary::-webkit-details-marker{display:none}
.record-meta-summary>summary:before{content:'＋';margin-right:4px}.record-meta-summary[open]>summary:before{content:'－'}
.record-meta-summary>div{position:absolute;z-index:5;top:100%;left:0;min-width:280px;display:grid;gap:5px;margin-top:6px;padding:10px 12px;border:1px solid #dbe7e3;border-radius:9px;background:#fff;box-shadow:0 8px 22px rgba(24,74,65,.13)}
.record-meta-summary span{color:#5f746f;font-size:var(--fs-xs);line-height:1.55}.record-meta-summary b{margin-right:6px;color:#2f7065}
/* 四種提醒合併為一條，一次只顯示最重要的。 */
.question-alert{display:flex;align-items:flex-start;gap:8px;margin:10px 0 0;padding:10px 11px;border:1px solid;border-radius:8px;font-size:var(--fs-sm);line-height:1.6}.question-alert strong{white-space:nowrap}
.question-alert.warn{border-color:#e7c98c;background:#fff8e8;color:#785a20}.question-alert.error{border-color:#e5b9b5;background:#fff1f0;color:#8c403b}
.question-more>summary{padding:4px 9px;border:1px solid #cfe0db;border-radius:8px;color:#4d6b64;font-size:var(--fs-md);line-height:1}
.question-more>div{position:absolute;z-index:5;top:100%;right:0;display:grid;gap:4px;min-width:150px;margin-top:6px;padding:6px;border:1px solid #dbe7e3;border-radius:9px;background:#fff;box-shadow:0 8px 22px rgba(24,74,65,.13)}
.question-more button{padding:8px 10px;border:0;border-radius:6px;background:transparent;color:#3f5f59;font-size:var(--fs-sm);text-align:left;cursor:pointer}.question-more button:hover{background:#eef6f3}.question-more button.danger{color:#a05b54}.question-more button.danger:hover{background:#fdeceb}
.question-progress-loading,.question-preview-error{display:flex;align-items:center;justify-content:center;gap:8px;min-height:90px;padding:20px;color:#748681;font-size:var(--fs-sm)}.question-preview-error{color:#96524c}

.rating-scale-guide{margin-left:auto}.rating-scale-guide>summary{list-style:none;cursor:pointer;color:#2f7166;font-size:var(--fs-xs);font-weight:700}.rating-scale-guide>summary::-webkit-details-marker{display:none}.rating-scale-guide>summary:before{content:'＋';margin-right:5px}.rating-scale-guide[open]>summary:before{content:'－'}
.rating-scale-guide ol{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:9px 0 0;padding:0;list-style:none}.rating-scale-guide li{display:flex;align-items:center;gap:8px;padding:8px 9px;border:1px solid #dce9e5;border-radius:7px;background:#fff;color:#506c65;font-size:var(--fs-sm)}.rating-scale-guide li b{width:27px;height:27px;display:grid;place-items:center;flex:0 0 auto;border-radius:50%;background:#dff1eb;color:#1e6b60;font-size:var(--fs-sm)}
.rating-scale-guide[open]{flex-basis:100%}
.compliance-chip{flex:0 0 auto;padding:4px 9px;border-radius:99px;background:#e3f4eb;color:#237052;font-size:var(--fs-xs);font-weight:700}.compliance-chip.warn{background:#fbe0de;color:#a2352e}
.question-list-actions{justify-content:flex-end}
.exceptional-status-note{display:flex;align-items:center;gap:9px;margin:12px 0 0;padding:10px 12px;border:1px solid #e6d2ad;border-radius:8px;background:#fff8e9;color:#755b2a}.exceptional-status-note strong{font-size:var(--fs-md)}.exceptional-status-note span{font-size:var(--fs-sm)}

/* `.question-preview-list` 已無樣式，僅保留給 e2e 既有選擇器使用。 */
.record-question-list{display:grid;gap:12px;margin:12px 0 0;padding:0;list-style:none}
.record-question-card{display:grid;grid-template-columns:minmax(280px,.78fr) minmax(420px,1.22fr);column-gap:12px;align-items:start;overflow:hidden;border:1px solid #dbe6e2;border-radius:10px;background:#fbfdfc}
.record-question-card.invalid{border-color:#d88982;box-shadow:0 0 0 2px rgba(190,74,65,.08)}
.record-question-card>header,.record-question-card>.question-compliance,.record-question-card>.record-question-context{grid-column:1/-1}
.record-question-card>header{display:grid;grid-template-columns:36px minmax(0,1fr);align-items:start;gap:10px;padding:13px;border-bottom:1px solid #e2ebe8}
.record-question-card>header>span{width:34px;height:34px;display:grid;place-items:center;border-radius:50%;background:#dff0eb;color:#226e63;font-size:var(--fs-md);font-weight:800}
.record-question-card.answered>header>span{background:#2a8879;color:#fff}
.record-question-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;min-width:0}
.record-question-heading>strong{min-width:0;flex:1;color:#2b4f49;font-size:var(--fs-md);line-height:1.7}
.record-question-text-label{min-width:0;flex:1;display:grid;gap:5px;color:#536e68;font-size:var(--fs-sm)}
.record-question-text-input{width:100%;min-height:58px;max-height:110px;box-sizing:border-box;padding:10px 11px;border:1px solid #c9ddd7;border-radius:8px;background:#fff;color:#284a44;font:inherit;font-size:var(--fs-md);font-weight:650;line-height:1.55;resize:vertical}
.record-question-tools{display:flex;flex:0 0 auto;align-items:center;gap:7px}
.question-regenerate-button:disabled{cursor:not-allowed;opacity:.55}
.record-question-context{display:block;padding:0;border-bottom:1px solid #e2ebe8;background:#f5f9f7}.record-question-context>summary{list-style:none;cursor:pointer;padding:9px 13px;color:#3b7168;font-size:var(--fs-sm);font-weight:700}.record-question-context>summary::-webkit-details-marker{display:none}.record-question-context>summary:before{content:'＋';margin-right:7px}.record-question-context[open]>summary:before{content:'－'}.record-question-context>div{display:grid;gap:6px;padding:0 13px 11px}.record-question-context small{color:#617771;font-size:var(--fs-sm);line-height:1.55}.record-question-context b{margin-right:7px;color:#2f7065}
/* 回答紀錄是面試當下的主要產出，給它最大的視覺權重。 */
.record-quick-answer{grid-column:1;padding:13px 0 14px 13px}.record-quick-answer label{display:grid;gap:7px}
.answer-label{display:flex;align-items:center;gap:6px;color:#1f6b60;font-size:var(--fs-sm);font-weight:800}.answer-label:before{content:'';width:3px;height:14px;border-radius:2px;background:#2a8879}
.record-quick-answer textarea{width:100%;box-sizing:border-box;min-height:120px;padding:12px 13px;border:1px solid #bfd9d1;border-radius:8px;background:#fff;color:#284a44;font:inherit;font-size:var(--fs-md);line-height:1.7;resize:vertical}.record-quick-answer textarea:focus{border-color:#258174;outline:3px solid rgba(37,129,116,.1)}
.record-quick-answer.readonly{display:grid;gap:7px}.record-quick-answer.readonly p{margin:0;padding:11px 13px;border-left:3px solid #2a8879;border-radius:0 7px 7px 0;background:#f3f9f7;color:#2f544e;font-size:var(--fs-md);line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere}.record-quick-answer.readonly p.empty{border-left-color:#d7dfdd;background:#f8faf9;color:#8a9693;font-style:italic}
.question-evaluation-direct{grid-column:2;display:grid;gap:11px;margin:13px 13px 14px 0;padding:13px;border:1px solid #cfe2dc;border-radius:9px;background:#fff}
.rating-radio-group{min-width:0}.rating-radio-group>legend{margin-bottom:9px;color:#365f58;font-size:var(--fs-md);font-weight:800}
.rating-segments{display:grid;grid-template-columns:repeat(6,minmax(74px,1fr));gap:7px}
.rating-segments label{position:relative;min-height:62px;display:grid;place-content:center;justify-items:center;gap:3px;padding:8px;border:1px solid #cfdfda;border-radius:9px;background:#fff;color:#5c716c;text-align:center;cursor:pointer;transition:border-color .15s ease,background .15s ease,box-shadow .15s ease}
.rating-segments label:hover{border-color:#62a99b;background:#f2faf7}
.rating-segments label.selected{border-color:#247f72;background:#e3f4ef;color:#175f55;box-shadow:0 0 0 2px rgba(36,127,114,.1)}
.rating-segments label.not-asked-option.selected{border-color:#a9792d;background:#fff4dc;color:#79581e}
.rating-segments input{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap}
.rating-segments label:focus-within{outline:3px solid rgba(25,111,99,.25);outline-offset:2px}
.rating-segments b{font-size:21px}.rating-segments span{font-size:var(--fs-xs);line-height:1.3}
.record-editor fieldset:disabled .rating-segments label{cursor:default}.record-editor fieldset:disabled .rating-segments label:hover{border-color:#cfdfda;background:#fff}.record-editor fieldset:disabled .rating-segments label.selected{border-color:#247f72;background:#e3f4ef}
.not-asked-reason{display:grid;gap:5px;color:#6e5727;font-size:var(--fs-sm);font-weight:700}.not-asked-reason input{width:100%;box-sizing:border-box;padding:10px 11px;border:1px solid #d9c28d;border-radius:7px;background:#fffdf7;color:#4b412d;font:inherit;font-size:var(--fs-md)}
.field-error{margin:0!important;color:#a23f37!important;font-size:var(--fs-sm)!important;line-height:1.45!important}
.question-observation-details{border-top:1px solid #e4ebe9}.question-observation-details>summary{display:flex;align-items:center;gap:8px;padding:9px 2px 0;list-style:none;cursor:pointer;color:#56716a;font-size:var(--fs-sm)}.question-observation-details>summary::-webkit-details-marker{display:none}.question-observation-details>summary:before{content:'＋';color:#27766b;font-weight:800}.question-observation-details[open]>summary:before{content:'－'}.question-observation-details>summary span{flex:1}.question-observation-details>summary em{font-style:normal}
.record-answer-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:10px 0 0}.record-answer-grid .wide{grid-column:1/-1}.record-answer-grid label{display:grid;gap:5px;color:#536e68;font-size:var(--fs-sm)}.record-answer-grid input,.record-answer-grid textarea{width:100%;box-sizing:border-box;padding:10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit;font-size:var(--fs-sm);line-height:1.6;resize:vertical}
.question-evaluation-readonly{grid-column:2;display:grid;gap:7px;align-content:start;margin:13px 13px 14px 0;padding:12px;border:1px dashed #cfe2dc;border-radius:9px;background:#fbfdfc}.question-evaluation-readonly>span{color:#5f746f;font-size:var(--fs-sm);line-height:1.6}
.rating-chip{justify-self:start;padding:5px 10px;border-radius:99px;background:#e3f4ef;color:#1f7165;font-size:var(--fs-md);font-weight:800}.rating-chip.skipped{background:#fff4dc;color:#79581e;font-weight:700}.rating-chip.empty{background:#eef2f1;color:#71827d;font-weight:700}
.evaluation-locked{color:#8a641f;font-size:var(--fs-sm);font-style:normal;font-weight:600}
.evaluation-lock-inline{grid-column:2;display:flex;align-items:center;gap:9px;margin:13px 13px 14px 0;padding:11px;border:1px dashed #dfc994;border-radius:8px;background:#fffaf0;color:#785b22}.evaluation-lock-inline p{margin:0}.evaluation-lock-inline b,.evaluation-lock-inline small{display:block}.evaluation-lock-inline b{font-size:var(--fs-sm)}.evaluation-lock-inline small{margin-top:2px;font-size:var(--fs-xs)}
.question-list-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px}.question-list-actions>span{color:#748580;font-size:var(--fs-sm)}

/* 特質出題工具排在題目清單之後，且維持收合。 */
.question-builder{margin:12px 0 16px;border:1px solid #d8e5e1;border-radius:12px;background:#fff}
.question-builder>summary{display:flex;align-items:center;justify-content:space-between;gap:16px;list-style:none;cursor:pointer;padding:14px 16px}.question-builder>summary::-webkit-details-marker{display:none}.question-builder>summary:before{content:'＋';margin-right:7px;color:#27766b;font-weight:800}.question-builder[open]>summary:before{content:'－'}
.question-builder>summary>div{min-width:0}.question-builder>summary small{color:#ae761d;font-size:var(--fs-xs);font-weight:800;letter-spacing:1px}.question-builder>summary h3{margin:4px 0;font-size:var(--fs-md)}.question-builder>summary p{margin:0;color:#6b7e79;font-size:var(--fs-sm);line-height:1.55}.question-builder>summary>span{flex:0 0 auto;padding:7px 10px;border-radius:99px;background:#eef5f3;color:#386b63;font-size:var(--fs-sm);font-weight:700}.question-builder[open]>summary{border-bottom:1px solid #e1ebe7}
.question-builder-body{padding:0 16px 16px}
.trait-picker,.selected-custom-traits{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.trait-picker button,.selected-custom-traits button{padding:7px 10px;border:1px solid #d6e3df;border-radius:99px;background:#fff;color:#516d67;font-size:var(--fs-sm)}.trait-picker button.selected{border-color:#2c897b;background:#e4f4ef;color:#1d6e62;font-weight:700}.selected-custom-traits button{border-color:#d6c590;background:#fff9e9;color:#79602b}
.custom-trait{display:flex;gap:7px;margin-top:10px}.custom-trait input{min-width:0;flex:1;height:38px;padding:0 10px;border:1px solid #d5e2de;border-radius:8px;font-size:var(--fs-sm)}
.generate-questions{margin-top:11px}
.question-guidance{margin:13px 0 0;padding:11px 13px;border-left:3px solid #d5a74c;border-radius:7px;background:#fff9eb;color:#735c33;font-size:var(--fs-sm);line-height:1.65}
.question-personalization-basis{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-top:10px;padding:9px 10px;border:1px solid #d7e7e2;border-radius:8px;background:#f3f9f7}.question-personalization-basis strong{margin-right:3px;color:#315f57;font-size:var(--fs-sm)}.question-personalization-basis span{padding:4px 8px;border-radius:99px;background:#fff;color:#527069;font-size:var(--fs-xs)}
.suggestion-groups{display:grid;gap:9px;margin-top:11px}.suggestion-groups>article{overflow:hidden;border:1px solid #dce7e3;border-radius:9px}.suggestion-groups>article>header{display:flex;justify-content:space-between;gap:10px;padding:9px 12px;background:#f2f7f5}.suggestion-groups>article>header strong{font-size:var(--fs-sm);color:#2d6d62}.suggestion-groups>article>header span{color:#758681;font-size:var(--fs-xs)}
.suggested-question{display:flex;align-items:flex-start;gap:12px;padding:12px;border-top:1px solid #e5ece9}.suggested-question:first-of-type{border-top:0}.suggested-question>div{min-width:0;flex:1}.suggested-question>div>strong{display:block;font-size:var(--fs-sm);line-height:1.6}.suggested-question p{margin:5px 0 0;color:#667b75;font-size:var(--fs-sm);line-height:1.6}.suggested-question p b{margin-right:5px;color:#397268}.suggested-question>.button{flex:0 0 auto}.suggested-question .question-source{display:block;margin-bottom:5px;color:#a16e18;font-size:var(--fs-xs);font-weight:700}

/* 面試題目合規檢核（就服法§5 / 性平法§7·§11）：綠=合法、紅=疑似違法。 */
.question-compliance{display:grid!important;gap:2px;margin:10px 13px 0!important;padding:9px 11px!important;border-left:3px solid!important;border-radius:0 6px 6px 0!important;font-size:var(--fs-sm)!important;line-height:1.6!important}
.question-compliance b{font-weight:800}.question-compliance span,.question-compliance em{font-size:var(--fs-sm);font-style:normal;line-height:1.55}
.question-compliance.ok{border-left-color:#2a8879!important;background:#edf8f3!important;color:#1f6b60!important}
.question-compliance.warning{border-left-color:#c94b43!important;background:#fdeceb!important;color:#8f342e!important}
.suggested-question .question-compliance{margin:6px 0 0!important}

/* 整體總評：面試總分為 0–100 的人工判斷，題目平均只是參考值。 */
.record-conclusion-section{margin:0 16px 14px;border:1px solid #bcded4;border-radius:10px;background:#f8fcfa}
.record-conclusion-section>header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 15px;border-bottom:1px solid #d7e8e2}.record-conclusion-section>header strong,.record-conclusion-section>header span{display:block}.record-conclusion-section>header strong{color:#255f56;font-size:var(--fs-lg)}.record-conclusion-section>header span{margin-top:3px;color:#6e817b;font-size:var(--fs-sm)}.record-conclusion-section>header em{color:#2a756a;font-size:var(--fs-sm);font-style:normal;font-weight:700}
.record-conclusion{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,1fr);align-items:start;gap:14px;padding:15px}
.record-conclusion label{display:grid;gap:6px;color:#536e68;font-size:var(--fs-sm)}.record-conclusion .wide{grid-column:1/-1}
.record-conclusion select,.record-conclusion textarea{width:100%;box-sizing:border-box;padding:10px 11px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit;font-size:var(--fs-md);line-height:1.6;resize:vertical}
.overall-score-field>small{color:#778984;font-size:var(--fs-xs);line-height:1.5}
.overall-score-input{display:flex;align-items:center;gap:9px}.overall-score-input input{width:130px;padding:11px 12px;border:2px solid #9ccabf;border-radius:8px;background:#fff;color:#1c5a52;font:inherit;font-size:22px;font-weight:800;text-align:center}.overall-score-input input:focus{border-color:#218174;outline:3px solid rgba(35,128,114,.18)}.overall-score-input b{color:#4d6b64;font-size:var(--fs-md)}
.score-reference{color:#93a09c!important;font-size:var(--fs-xs)!important;font-style:italic}
.record-conclusion-section [aria-invalid="true"]{border-color:#c8675f}
.record-conclusion-locked{display:flex;align-items:center;gap:10px;margin:0 16px 16px;padding:13px;border:1px dashed #dfc994;border-radius:9px;background:#fffaf0;color:#795c25}.record-conclusion-locked strong{display:block;font-size:var(--fs-md)}.record-conclusion-locked p{margin:3px 0 0;font-size:var(--fs-sm)}

.hr-private-notes{margin:0 16px 16px;border:1px solid #d3c6eb;border-radius:10px;background:#faf7ff}.hr-private-notes>summary{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px;list-style:none;cursor:pointer;padding:12px 13px}.hr-private-notes>summary::-webkit-details-marker{display:none}.hr-private-notes>summary>span{padding:5px 8px;border-radius:6px;background:#6f5799;color:#fff;font-size:var(--fs-xs);font-weight:800;letter-spacing:.7px}.hr-private-notes>summary strong,.hr-private-notes>summary small{display:block}.hr-private-notes>summary strong{color:#54416f;font-size:var(--fs-md)}.hr-private-notes>summary small{margin-top:2px;color:#81728f;font-size:var(--fs-xs)}.hr-private-notes>summary em{color:#705c86;font-size:var(--fs-sm);font-style:normal}.hr-private-notes>label{display:grid;gap:5px;margin:0 13px 13px;color:#665577;font-size:var(--fs-sm)}.hr-private-notes textarea{width:100%;box-sizing:border-box;padding:11px;border:1px solid #d8cee7;border-radius:8px;background:#fff;color:#453952;font:inherit;font-size:var(--fs-md);line-height:1.6;resize:vertical}

.record-reopen-panel{display:grid;grid-template-columns:minmax(180px,1fr) minmax(280px,2fr) auto;align-items:end;gap:12px;padding:13px 16px;border-top:1px solid #e0cf9c;background:#fff9e8}.record-reopen-panel strong{color:#6e5525;font-size:var(--fs-md)}.record-reopen-panel p{margin:3px 0 0;color:#806b42;font-size:var(--fs-sm);line-height:1.5}.record-reopen-panel label{display:grid;gap:5px;color:#6e5727;font-size:var(--fs-sm)}.record-reopen-panel input{width:100%;box-sizing:border-box;padding:10px 11px;border:1px solid #d5bd7f;border-radius:7px;background:#fff;color:#4e452f;font:inherit;font-size:var(--fs-md)}.record-reopen-panel>div:last-child{display:flex;gap:7px}.reopen-button{border-color:#c99d47;color:#76551b}
.record-editor>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 16px;border-top:1px solid #dde7e3;background:#f5f9f7}.record-editor>footer>span{color:#71837e;font-size:var(--fs-sm);line-height:1.55}.record-editor>footer>div{display:flex;gap:7px}.record-editor>footer .button{min-height:44px;padding:10px 16px;font-size:var(--fs-md)}.record-editor>footer .button:disabled{cursor:not-allowed;opacity:.58}
.record-editor :is(input,select,textarea,button):focus-visible{outline:3px solid rgba(35,128,114,.22);outline-offset:2px}.record-editor [aria-invalid="true"]{border-color:#c8675f}

/* 面試紀錄歷程：卡片最下方的收合區，舊版問答仍可回查。 */
.record-history{border:1px solid #dce7e3;border-radius:11px;background:#fff}
.record-history>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;list-style:none;cursor:pointer;padding:12px 15px}.record-history>summary::-webkit-details-marker{display:none}.record-history>summary:before{content:'＋';margin-right:7px;color:#27766b;font-weight:800}.record-history[open]>summary:before{content:'－'}.record-history[open]>summary{border-bottom:1px solid #e5edea}
.record-history>summary strong{font-size:var(--fs-md)}.record-history>summary span{margin-left:8px;color:#748580;font-size:var(--fs-sm)}.record-history>summary em{color:#31786d;font-size:var(--fs-sm);font-style:normal}
.record-history-body{padding:12px 15px 15px}
.record-history-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.record-history-actions>span{color:#748580;font-size:var(--fs-sm)}
.workspace-loading{display:flex;align-items:center;gap:8px;padding:22px 12px;color:#6d807a;font-size:var(--fs-sm)}
.record-history-item{position:relative;width:100%;display:grid;gap:5px;padding:13px 14px;border:1px solid #e9efed;border-radius:9px;background:#fff;color:#34554f;text-align:left;cursor:pointer}.record-history-item+.record-history-item{margin-top:8px}
.record-history-item:hover,.record-history-item.active{border-color:#a8d2c7;background:#eef8f5}
.record-history-item.active:before{content:"";position:absolute;inset:9px auto 9px 0;width:4px;border-radius:0 4px 4px 0;background:#218174}
.record-history-item strong{font-size:var(--fs-md);line-height:1.45}.record-history-item small{color:#71827d;font-size:var(--fs-sm)}.record-history-item em{justify-self:end;color:#31786d;font-size:var(--fs-sm);font-style:normal}
.record-status{justify-self:start;padding:4px 8px;border-radius:99px;background:#e8f3ef;color:#2b7365;font-size:var(--fs-xs)}.record-status[data-status="planned"]{background:#e8f0f8;color:#326c99}.record-status[data-status="cancelled"],.record-status[data-status="no_show"]{background:#f7e9e7;color:#a04f49}
.history-visibility{justify-self:start;padding:4px 8px;border-radius:99px;background:#fff1dc!important;color:#8a601b!important}.history-visibility.unlocked{background:#e3f3ea!important;color:#267052!important}
.record-history-empty{padding:30px 20px;text-align:center;color:#758681}.record-history-empty strong{font-size:var(--fs-md)}.record-history-empty p{font-size:var(--fs-sm);line-height:1.6}

@media(max-width:1260px){.record-question-card{display:block}.record-quick-answer{padding:13px}.question-evaluation-direct,.question-evaluation-readonly,.evaluation-lock-inline{margin:0 13px 13px}}
@media(max-width:1120px){.interview-filters{align-items:stretch;flex-wrap:wrap}.interview-filters>div{flex-basis:100%}.interview-filters label{flex:1}.interview-filters select{width:100%}.rating-segments{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:980px){.rating-scale-guide ol{grid-template-columns:repeat(3,1fr)}.record-reopen-panel{grid-template-columns:1fr}.record-reopen-panel>div:last-child{justify-content:flex-end}}
@media(max-width:900px){.sharing-policy-details{grid-template-columns:1fr}.application-details{grid-template-columns:1fr 1fr}.record-meta-grid{grid-template-columns:1fr 1fr}.record-conclusion{grid-template-columns:1fr}}
@media(max-width:820px){.interview-row-toggle{grid-template-columns:minmax(0,1fr) 32px;gap:10px;padding:13px}.interview-row-progress{grid-column:1;grid-row:2;justify-items:start;grid-template-columns:auto 1fr}.interview-row-progress .application-status{grid-row:auto}.interview-row-toggle .row-chevron{grid-column:2;grid-row:1/3}.interview-card-detail{padding-inline:12px}}
@media(max-width:680px){
.interview-hero{align-items:flex-start;flex-direction:column}
.interview-embedded-heading,.interview-embedded-actions{align-items:stretch;flex-direction:column}.interview-embedded-actions .button{width:100%}
.interview-metrics,.application-details,.editor-grid,.record-meta-grid,.record-answer-grid{grid-template-columns:1fr}.editor-grid .wide,.record-answer-grid .wide{grid-column:auto}
.interview-filters label{flex-basis:100%}
.question-stage-tabs{grid-template-columns:1fr}
.record-discard-confirm,.question-list-actions,.record-history-actions,.interview-editor>footer,.record-editor>footer,.record-editor>header,.question-builder>summary{align-items:flex-start;flex-direction:column}
.record-discard-confirm>div:last-child,.interview-editor>footer>div,.record-editor>footer>div{display:grid;grid-template-columns:1fr;width:100%}
.record-discard-confirm .button,.interview-editor>footer .button,.record-editor>footer .button,.question-list-actions .button,.record-history-actions .button{width:100%}
.record-readonly-notice{align-items:stretch;flex-direction:column;margin-inline:10px}.record-readonly-notice .button{width:100%}
.question-progress{padding-inline:10px}
.rating-segments{grid-template-columns:repeat(2,minmax(0,1fr))}.rating-segments label{min-height:60px}
.record-question-card>header{grid-template-columns:30px minmax(0,1fr);padding:11px}.record-question-heading{align-items:stretch;flex-direction:column;gap:9px}.record-question-tools{flex-wrap:wrap}.question-regenerate-button{flex:1}
.suggested-question{flex-direction:column}.suggested-question>.button{width:100%}
}
</style>
