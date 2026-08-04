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
const workspaceApplication = ref<ApplicationDto | null>(null)
const interviewRecords = ref<InterviewRecordDto[]>([])
const recordsLoading = ref(false)
const recordSaving = ref(false)
const workspaceError = ref('')
const recordNotice = ref('')
const editingRecord = ref<InterviewRecordDto | null>(null)
const recordEditorOpen = ref(false)
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

async function toggleApplicationDetails(applicationId: number) {
  if (expandedApplicationId.value === applicationId) {
    expandedApplicationId.value = null
    return
  }
  expandedApplicationId.value = applicationId
  const application = applications.value.find(item => item.id === applicationId)
  if (application) await loadCardInterviewData([application])
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
      focusError.value = `找不到從人才評估帶入的應徵紀錄 #${props.focusApplicationId}。請返回人才評估，確認人才已加入目前職缺後再試一次。`
      return
    }
    departmentId.value = application.requisition.department_id
    requisitionId.value = application.requisition_id
    expandedApplicationId.value = application.id
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
    const targetApplicationId = props.focusApplicationId ?? expandedApplicationId.value
    const targetApplication = applications.value.find(application => application.id === targetApplicationId)
    if (targetApplication) await loadCardInterviewData([targetApplication])
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
  if (workspaceApplication.value?.id === application.id && workspaceQuestionStage.value === stage) {
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
    if (workspaceApplication.value?.id === application.id && workspaceQuestionStage.value === stage) {
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
  if (workspaceApplication.value?.id === application.id && workspaceQuestionStage.value === stage) {
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
    if (workspaceApplication.value?.id === application.id && workspaceQuestionStage.value === stage) {
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
    notes: '',
    purpose: item.purpose,
    follow_up: item.follow_up,
    source: item.source,
  }))
}

const workspaceQuestionStage = computed<InterviewStage>(() => (
  recordEditorOpen.value ? recordForm.stage : defaultRecordStage()
))

const workspaceQuestionPlan = computed(() => {
  const application = workspaceApplication.value
  return application
    ? plansByApplicationStage.value[planKey(application.id, workspaceQuestionStage.value)] || null
    : null
})

async function generateWorkspaceQuestionPlan() {
  const application = workspaceApplication.value
  if (!application) return
  const stage = workspaceQuestionStage.value
  const currentPlan = workspaceQuestionPlan.value
  const originalPlanQuestions = currentPlan?.questions.map(question => question.question) || []
  await generateQuestionPlan(
    application,
    stage,
    Boolean(currentPlan?.questions.length && currentPlan.context_matches),
  )

  const key = planKey(application.id, stage)
  if (cardQuestionErrors.value[key]) return

  const generatedPlan = plansByApplicationStage.value[key]
  if (!generatedPlan?.questions.length) return

  const hasQuestionProgress = recordForm.questions.some(question => (
    Boolean(question.response?.trim())
    || Boolean(question.notes?.trim())
    || (question.rating !== null && question.rating !== undefined)
  ))
  const hasQuestionEdits = recordForm.questions.length !== originalPlanQuestions.length
    || recordForm.questions.some((question, index) => question.question !== originalPlanQuestions[index])
  const hasDraftProgress = hasQuestionProgress
    || hasQuestionEdits
    || Boolean(recordForm.summary?.trim())
    || Boolean(recordForm.private_notes?.trim())
    || Boolean(recordForm.recommendation)
    || (recordForm.overall_rating !== null && recordForm.overall_rating !== undefined)
  if (recordEditorOpen.value && recordForm.stage === stage && canEditStage(stage)) {
    if (!editingRecord.value && !hasDraftProgress) {
      recordForm.question_plan_id = generatedPlan.id ?? null
      recordForm.questions = planQuestions(application.id, stage).slice(0, 5)
    } else {
      recordNotice.value = editingRecord.value
        ? '新版題目已建立；這筆既有面試紀錄仍保留原題。新建紀錄時才會帶入新版。'
        : '新版題目已建立；目前尚未儲存的內容已保留，未自動替換題目。'
    }
  }
}

async function regenerateWorkspaceQuestion(questionIndex: number) {
  const application = workspaceApplication.value
  if (!application) return
  await regenerateQuestionPlanItem(application, workspaceQuestionStage.value, questionIndex)
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
    return '已建立結構化紀錄；評分、總結與錄用建議待雙方提交後顯示。'
  }
  const details: string[] = []
  if (record.summary?.trim()) details.push(`總結：${record.summary.trim()}`)
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

const editorEvaluationVisible = computed(() => (
  !editingRecord.value || editingRecord.value.evaluation_revealed
))
const recordAnsweredCount = computed(() => (
  recordForm.questions.filter(questionIsAnswered).length
))

function inlineActionLabel(applicationId: number, stage: InterviewStage) {
  const record = currentPlanRecord(applicationId, stage)
  if (record) return canEditStage(stage) ? '繼續填答' : '查看完整紀錄'
  if (hasOlderPlanRecord(applicationId, stage)) {
    const version = plansByApplicationStage.value[planKey(applicationId, stage)]?.version
    return canEditStage(stage) ? `使用 v${version} 建立新紀錄` : '查看舊版紀錄'
  }
  return canEditStage(stage) ? '開始 5 題紀錄' : '尚未開始'
}

function canEditRecord(record: InterviewRecordDto) {
  return canEditStage(record.stage)
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

async function openRecordWorkspace(application: ApplicationDto) {
  workspaceApplication.value = application
  editingRecord.value = null
  recordEditorOpen.value = false
  questionSuggestions.value = null
  selectedTraits.value = []
  customTrait.value = ''
  recordNotice.value = ''
  await loadInterviewRecords(application.id)
}

function closeRecordWorkspace() {
  if (recordSaving.value) return
  workspaceApplication.value = null
  editingRecord.value = null
  recordEditorOpen.value = false
  interviewRecords.value = []
  questionSuggestions.value = null
  workspaceError.value = ''
}

async function newRecord(stage: InterviewStage = defaultRecordStage()) {
  if (!workspaceApplication.value) return
  const scheduledAt = stageData(workspaceApplication.value, stage).interview_at
  editingRecord.value = null
  recordEditorOpen.value = true
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
  })
  recordNotice.value = ''
  workspaceError.value = ''
  try {
    const plan = await ensureQuestionPlan(workspaceApplication.value, stage)
    if (!editingRecord.value && recordForm.stage === stage) {
      recordForm.question_plan_id = plan.id ?? null
      recordForm.questions = planQuestions(workspaceApplication.value.id, stage)
    }
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法載入系統面試題'
  }
}

async function openInlineRecord(application: ApplicationDto) {
  const stage = inlineStage(application.id)
  await openRecordWorkspace(application)
  const record = currentPlanRecord(application.id, stage)
  if (record) {
    editRecord(record)
    if (canEditStage(stage) && recordForm.questions.length < 5) {
      try {
        await ensureQuestionPlan(application, stage)
        recordForm.questions = mergeQuestionsToFive(
          recordForm.questions,
          planQuestions(application.id, stage),
        )
        recordNotice.value = '已補上系統建議題；儲存後才會寫入這筆紀錄'
      } catch (cause) {
        workspaceError.value = cause instanceof Error ? cause.message : '無法載入系統面試題'
      }
    }
  } else if (canEditStage(stage)) {
    await newRecord(stage)
  }
}

function editRecord(record: InterviewRecordDto) {
  editingRecord.value = record
  recordEditorOpen.value = true
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
  })
  recordNotice.value = ''
  workspaceError.value = ''
}

function cancelRecordEdit() {
  if (recordSaving.value) return
  editingRecord.value = null
  recordEditorOpen.value = false
  recordForm.questions = []
}

function addBlankQuestion() {
  workspaceError.value = ''
  recordForm.questions.push({ question: '', trait: null, response: '', rating: null, notes: '' })
}

function removeRecordQuestion(index: number) {
  workspaceError.value = ''
  recordForm.questions.splice(index, 1)
}

async function addSuggestedQuestion(question: InterviewQuestion, trait: string) {
  if (!workspaceApplication.value) return
  if (!recordEditorOpen.value || !canEditStage(recordForm.stage)) await newRecord()
  if (recordForm.questions.some(item => item.question === question.question)) return
  workspaceError.value = ''
  recordForm.questions.push({
    question: question.question,
    trait,
    response: '',
    rating: null,
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

async function saveRecord() {
  const application = workspaceApplication.value
  if (!application) return
  if (!canEditStage(recordForm.stage)) {
    workspaceError.value = '目前帳號不能維護這個面試階段的紀錄'
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
  const questions = recordForm.questions
    .filter(item => item.question.trim())
    .map(item => ({
      question: item.question.trim(),
      trait: optionalText(item.trait),
      response: optionalText(item.response),
      rating: item.rating ? Number(item.rating) : null,
      notes: optionalText(item.notes),
      purpose: optionalText(item.purpose),
      follow_up: optionalText(item.follow_up),
      source: optionalText(item.source),
    }))
  recordSaving.value = true
  workspaceError.value = ''
  try {
    const payload: InterviewRecordWrite = {
      stage: recordForm.stage,
      question_plan_id: recordForm.question_plan_id ?? null,
      interviewed_at: interviewedAt.toISOString(),
      duration_minutes: recordForm.duration_minutes ? Number(recordForm.duration_minutes) : null,
      mode: recordForm.mode,
      status: recordForm.status,
      questions,
      summary: optionalText(recordForm.summary),
      private_notes: recordForm.stage === 'hr' ? optionalText(recordForm.private_notes) : undefined,
      recommendation: recordForm.recommendation || null,
      overall_rating: recordForm.overall_rating ? Number(recordForm.overall_rating) : null,
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
        })).data
      : (await hrApi.createInterviewRecord(application.id, payload)).data
    const successMessage = editingRecord.value ? '面試過程紀錄已更新' : '面試過程紀錄已建立'
    await loadInterviewRecords(application.id)
    editRecord(saved)
    workspaceError.value = ''
    recordNotice.value = successMessage
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法儲存面試過程紀錄'
  } finally {
    recordSaving.value = false
  }
}

function answeredQuestionCount(record: InterviewRecordDto) {
  return record.questions.filter(question => question.response?.trim()).length
}

function formatDate(value: string | null) {
  if (!value) return '尚未安排'
  return formatApiDateTime(value)
}

function onRequisitionFilterChange() {
  expandedApplicationId.value = null
  focusError.value = ''
  emit('requisition-selected', requisitionId.value)
}

function onDepartmentFilterChange() {
  if (requisitionId.value !== null && !requisitions.value.some(requisition => requisition.id === requisitionId.value)) {
    requisitionId.value = null
  }
  expandedApplicationId.value = null
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
      <div><strong>篩選面試名單</strong><span>可依部門與職缺縮小範圍；點整列或右側「＋」展開詳情</span></div>
      <label>部門<select v-model="departmentId" data-testid="interview-department-filter" @change="onDepartmentFilterChange"><option :value="null">全部部門</option><option v-for="department in departments" :key="department.id" :value="department.id">{{ department.name }}</option></select></label>
      <label>職缺<select v-model="requisitionId" data-testid="interview-job-filter" @change="onRequisitionFilterChange"><option :value="null">全部職缺</option><option v-for="requisition in requisitions" :key="requisition.id" :value="requisition.id">{{ requisition.req_no }} · {{ requisition.title }}</option></select></label>
      <em>{{ filteredApplications.length }} 筆</em>
    </div>

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
              <small>最近面試：{{ formatDate(nearestInterviewAt(application)) }}</small>
            </div>
            <span class="row-chevron" aria-hidden="true">{{ expandedApplicationId === application.id ? '−' : '＋' }}</span>
          </button>
        </header>

        <div v-if="expandedApplicationId === application.id" :id="`interview-detail-${application.id}`" class="interview-card-detail">

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
              <p>{{ stageData(application, stage.key).interview_notes || '尚未填寫共享備註。' }}</p>
              <template v-if="latestStageRecord(application.id, stage.key)">
                <small>結構化面試紀錄 · {{ structuredRecordStatus(application.id, stage.key) }}</small>
                <p :class="{ 'structured-record-locked': structuredRecordLocked(application.id, stage.key) }">{{ structuredRecordSummaryForStage(application.id, stage.key) }}</p>
              </template>
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
        <section class="question-progress" :data-testid="`interview-question-progress-${application.id}`">
          <header>
            <div class="question-progress-title"><small>INTERVIEW QUESTIONS</small><strong>面試問題</strong><span>切換 HR 或主管，即可查看目前五題、回答與完成進度。</span></div>
            <div class="question-stage-tabs" role="tablist" aria-label="切換 HR 或主管題目">
              <button
                v-for="stage in interviewStages"
                :key="stage.key"
                type="button"
                role="tab"
                :class="{ active: inlineStage(application.id) === stage.key }"
                :aria-selected="inlineStage(application.id) === stage.key"
                :data-testid="`question-stage-${application.id}-${stage.key}`"
                @click="inlineStageByApplication[application.id] = stage.key"
              >
                <small>{{ stage.owner }}</small><strong>{{ stageAnsweredCount(application.id, stage.key) }}/5</strong><span>{{ stageSubmissionLabel(application.id, stage.key) }}</span>
              </button>
            </div>
          </header>

          <div v-if="cardDataLoading[application.id] && !fiveQuestionSet(application.id, inlineStage(application.id)).length" class="question-progress-loading"><span class="spinner"></span>正在準備 5 題…</div>
          <template v-else>
            <div class="question-plan-meta">
              <span :data-stage="inlineStage(application.id)">{{ inlineStage(application.id) === 'hr' ? 'HR 五題' : '主管五題' }}</span>
              <button
                v-if="canGenerateQuestionStage(inlineStage(application.id)) && !plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.questions.length"
                type="button"
                class="button generation-button"
                :disabled="questionPlanGenerating[planKey(application.id, inlineStage(application.id))]"
                :data-testid="`question-plan-generate-${application.id}-${inlineStage(application.id)}`"
                @click="generateQuestionPlan(application, inlineStage(application.id))"
              >{{ questionPlanGenerating[planKey(application.id, inlineStage(application.id))] ? '產生中…' : '使用 Gemini 產生 5 題' }}</button>
              <b class="evaluation-release-chip" :class="{ unlocked: peerEvaluationsReleased(application.id) }">{{ peerEvaluationsReleased(application.id) ? '雙方已提交 · 評分已公開' : '評分鎖定至雙方提交' }}</b>
              <small v-if="plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.version">題目版本 v{{ plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.version }} · {{ formatDate(plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.generated_at || null) }}</small>
              <small v-else-if="currentPlanRecord(application.id, inlineStage(application.id))">紀錄更新：{{ formatDate(currentPlanRecord(application.id, inlineStage(application.id))?.updated_at || null) }}</small>
              <small v-else>尚未開始填答</small>
            </div>
            <details v-if="plansByApplicationStage[planKey(application.id, inlineStage(application.id))]" class="question-plan-details">
              <summary>查看產生資訊</summary>
              <span>
                {{ generationModeLabel(plansByApplicationStage[planKey(application.id, inlineStage(application.id))]) }}<template v-if="tokenSummary(plansByApplicationStage[planKey(application.id, inlineStage(application.id))])"> · {{ tokenSummary(plansByApplicationStage[planKey(application.id, inlineStage(application.id))]) }}</template>
              </span>
            </details>
            <div
              v-if="plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.generation_warning"
              class="question-generation-warning"
              role="alert"
            >
              <strong>⚠ Gemini 生成提醒</strong>
              <span>{{ plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.generation_warning }}</span>
            </div>
            <div
              v-if="cardQuestionErrors[planKey(application.id, inlineStage(application.id))]"
              class="question-generation-error"
              role="alert"
            >
              <strong>無法更新題目</strong>
              <span>{{ cardQuestionErrors[planKey(application.id, inlineStage(application.id))] }}；目前題目仍保留。</span>
            </div>
            <div
              v-if="plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.questions.length && plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.context_matches === false"
              class="question-context-warning"
              role="status"
            >履歷或職缺內容已更新，現有題目仍可查看；請針對需要更新的題目逐題重新產生。</div>
            <div
              v-if="hasOlderPlanRecord(application.id, inlineStage(application.id))"
              class="question-context-warning"
              role="status"
            >目前顯示新版題目，尚未建立填答紀錄；舊版問答仍保留在面試紀錄歷程中。</div>

            <ol v-if="fiveQuestionSet(application.id, inlineStage(application.id)).length" class="question-preview-list">
              <li
                v-for="(question, index) in fiveQuestionSet(application.id, inlineStage(application.id))"
                :key="`${index}-${question.question}`"
                :class="{ answered: questionIsAnswered(question) }"
              >
                <span>{{ questionIsAnswered(question) ? '✓' : index + 1 }}</span>
                <div>
                  <div class="question-preview-heading">
                    <strong>{{ question.question }}</strong>
                    <button
                      v-if="canGenerateQuestionStage(inlineStage(application.id)) && plansByApplicationStage[planKey(application.id, inlineStage(application.id))]?.questions[index]"
                      type="button"
                      class="question-regenerate-button"
                      :disabled="questionPlanGenerating[planKey(application.id, inlineStage(application.id))]"
                      :aria-label="`重新產生第 ${index + 1} 題`"
                      :data-testid="`question-regenerate-${application.id}-${inlineStage(application.id)}-${index}`"
                      @click="regenerateQuestionPlanItem(application, inlineStage(application.id), index)"
                    >{{ questionRegenerating[questionRegenerationKey(application.id, inlineStage(application.id), index)] ? '重新產生中…' : '重新產生此題' }}</button>
                  </div>
                  <p v-if="questionCompliance(question).status === 'warning'" class="question-compliance warning" role="alert">
                    <b>⚠ 疑似違法提問</b>
                    <span>涉及：{{ complianceCategoryText(questionCompliance(question)) }}</span>
                    <em>{{ questionCompliance(question).suggestion }}</em>
                  </p>
                  <p v-else class="question-compliance ok"><b>✓ 合法</b><span>未偵測到違法／歧視性內容</span></p>
                  <details v-if="question.purpose || question.follow_up || question.source" class="question-prompt-details">
                    <summary>需要時查看面試提示</summary>
                    <div>
                      <p v-if="question.purpose"><b>評估重點</b><span>{{ question.purpose }}</span></p>
                      <p v-if="question.follow_up"><b>建議追問</b><span>{{ question.follow_up }}</span></p>
                      <p v-if="question.source"><b>題目依據</b><span>{{ question.source }}</span></p>
                    </div>
                  </details>
                  <p :class="{ empty: !questionIsAnswered(question) }">{{ questionAnswer(question) }}</p>
                  <em v-if="question.rating">{{ question.rating }} / 5 分</em>
                  <em v-else-if="currentPlanRecord(application.id, inlineStage(application.id)) && !currentPlanRecord(application.id, inlineStage(application.id))?.evaluation_revealed" class="evaluation-locked">🔒 評分與觀察於雙方提交後顯示</em>
                </div>
              </li>
            </ol>
            <div v-else class="question-preview-error">{{ cardQuestionErrors[planKey(application.id, inlineStage(application.id))] || cardInterviewErrors[application.id] || '尚未產生五題，請由這一階段的面試官按上方按鈕。' }}</div>

            <footer>
              <span v-if="currentPlanRecord(application.id, inlineStage(application.id))">
                {{ inlineStage(application.id) === 'hr' ? 'HR' : '主管' }} 紀錄者：{{ currentPlanRecord(application.id, inlineStage(application.id))?.interviewer_name }}。雙方可查看問答，由同階段授權人員維護。
              </span>
              <span v-else>{{ inlineStage(application.id) === 'hr' ? '由 HR 維護五題與答案' : '由部門主管維護五題與答案' }}</span>
              <button
                class="button primary"
                type="button"
                :disabled="!fiveQuestionSet(application.id, inlineStage(application.id)).length || (!canEditStage(inlineStage(application.id)) && !currentPlanRecord(application.id, inlineStage(application.id)) && !latestStageRecord(application.id, inlineStage(application.id)))"
                :data-testid="`interview-workspace-${application.id}`"
                @click="openInlineRecord(application)"
              >{{ inlineActionLabel(application.id, inlineStage(application.id)) }}</button>
            </footer>
          </template>
        </section>
        </div>
      </article>
    </div>
    <div v-else class="interview-empty panel"><strong>目前沒有符合條件的應徵者</strong><p>請調整部門／職缺篩選；HR 建立人才與應徵關聯後，也會顯示在這裡。</p></div>
  </section>

  <div v-if="workspaceApplication" class="record-workspace-overlay" data-testid="interview-record-workspace" @keydown.esc="closeRecordWorkspace">
    <section class="record-workspace" role="dialog" aria-modal="true" aria-labelledby="record-workspace-title">
      <header class="record-workspace-header">
        <div class="workspace-person"><span>{{ workspaceApplication.candidate.name.slice(0, 1) }}</span><div><small>INTERVIEW WORKSPACE</small><h2 id="record-workspace-title">{{ workspaceApplication.candidate.name }}｜面試過程紀錄</h2><p>{{ workspaceApplication.requisition.req_no }} · {{ workspaceApplication.requisition.title }} · {{ workspaceApplication.requisition.department_name || '未標示部門' }}</p></div></div>
        <button type="button" :disabled="recordSaving" aria-label="關閉面試過程工作區" @click="closeRecordWorkspace">×</button>
      </header>

      <div v-if="workspaceError" class="workspace-message error" role="alert"><strong>!</strong><span>{{ workspaceError }}</span><button aria-label="關閉錯誤訊息" @click="workspaceError = ''">×</button></div>
      <div v-if="recordNotice" class="workspace-message success" role="status"><strong>✓</strong><span>{{ recordNotice }}</span><button aria-label="關閉成功訊息" @click="recordNotice = ''">×</button></div>

      <details class="interview-sharing-policy">
        <summary><strong>問答共享、評分分開</strong><span>查看資料規則</span></summary>
        <div class="sharing-policy-details">
          <p><b>問答</b><span>HR 與主管都能查看問題、回答與目前進度。</span></p>
          <p><b>評分</b><span>雙方都提交後，才互相公開評分、觀察與錄用建議。</span></p>
          <p v-if="authSession.state.user?.role === 'hr'"><b>HR 備註</b><span>敏感資訊只提供 HR 查看。</span></p>
        </div>
      </details>

      <div class="record-workspace-body">
        <aside class="record-history">
          <header><div><strong>面試紀錄</strong><span>{{ interviewRecords.length }} 筆歷程</span></div><button v-if="canEditStage(defaultRecordStage())" class="button primary" type="button" data-testid="interview-record-new" @click="newRecord()">＋ 新增</button></header>
          <div v-if="recordsLoading" class="workspace-loading"><span class="spinner"></span>載入紀錄中…</div>
          <button v-for="record in interviewRecords" v-else :key="record.id" class="record-history-item" :class="{ active: editingRecord?.id === record.id }" type="button" @click="editRecord(record)">
            <span class="record-status" :data-status="record.status">{{ recordStatusLabels[record.status] }}</span>
            <strong>{{ record.stage === 'hr' ? 'HR 初談' : '主管複試' }} · {{ formatDate(record.interviewed_at) }}</strong>
            <small>{{ recordModeLabels[record.mode] }}<template v-if="record.duration_minutes"> · {{ record.duration_minutes }} 分鐘</template></small>
            <small>{{ record.interviewer_name }} · 已記錄 {{ answeredQuestionCount(record) }}/{{ record.questions.length }} 題<template v-if="record.question_plan_version"> · 題目 v{{ record.question_plan_version }}</template></small>
            <small class="history-visibility" :class="{ unlocked: record.evaluation_revealed }">{{ record.evaluation_revealed ? '評分可見' : '僅共享問答 · 評分保護中' }}</small>
            <em>{{ canEditRecord(record) ? '可編輯' : '唯讀' }} →</em>
          </button>
          <div v-if="!recordsLoading && !interviewRecords.length" class="record-history-empty"><strong>尚無過程紀錄</strong><p>建立第一筆紀錄，面試中即可逐題輸入回答與評分。</p></div>
        </aside>

        <main class="record-workspace-main">
          <section class="workspace-gemini-panel" data-testid="workspace-gemini-generator">
            <div class="workspace-gemini-copy">
              <small>{{ workspaceQuestionStage === 'hr' ? 'HR 五題' : '主管五題' }}</small>
              <strong>目前面試題目</strong>
              <span>初次建立會產生五題；之後請在需要調整的題目旁按「重新產生此題」，其餘四題與既有紀錄都會保留。</span>
            </div>
            <div class="workspace-gemini-actions">
              <button
                v-if="canGenerateQuestionStage(workspaceQuestionStage) && !workspaceQuestionPlan?.questions.length"
                class="button primary"
                type="button"
                :disabled="questionPlanGenerating[planKey(workspaceApplication.id, workspaceQuestionStage)]"
                :data-testid="`workspace-question-plan-generate-${workspaceQuestionStage}`"
                @click="generateWorkspaceQuestionPlan"
              >{{ questionPlanGenerating[planKey(workspaceApplication.id, workspaceQuestionStage)] ? 'Gemini 產生中…' : '使用 Gemini 產生 5 題' }}</button>
            </div>
            <p v-if="workspaceQuestionPlan?.generation_warning" class="workspace-gemini-warning">⚠ {{ workspaceQuestionPlan.generation_warning }}</p>
            <details v-if="workspaceQuestionPlan" class="workspace-generation-details">
              <summary>查看產生資訊</summary>
              <p>{{ generationModeLabel(workspaceQuestionPlan) }}<template v-if="tokenSummary(workspaceQuestionPlan)"> · {{ tokenSummary(workspaceQuestionPlan) }}</template></p>
            </details>
            <details v-if="workspaceQuestionPlan?.questions.length" class="workspace-gemini-preview" open>
              <summary>目前 {{ workspaceQuestionPlan.questions.length }} 題，可逐題選擇重新產生</summary>
              <ol>
                <li v-for="(question, index) in workspaceQuestionPlan.questions" :key="question.question">
                  <div>
                    <strong>{{ question.question }}</strong>
                    <span v-if="questionCompliance(question).status === 'warning'" class="question-compliance-inline warning" role="alert" :title="questionCompliance(question).suggestion">⚠ 疑似違法（{{ complianceCategoryText(questionCompliance(question)) }}）</span>
                    <span v-else class="question-compliance-inline ok">✓ 合法</span>
                  </div>
                  <button
                    v-if="canGenerateQuestionStage(workspaceQuestionStage)"
                    type="button"
                    class="question-regenerate-button"
                    :disabled="questionPlanGenerating[planKey(workspaceApplication.id, workspaceQuestionStage)]"
                    :data-testid="`workspace-question-regenerate-${workspaceQuestionStage}-${index}`"
                    @click="regenerateWorkspaceQuestion(index)"
                  >{{ questionRegenerating[questionRegenerationKey(workspaceApplication.id, workspaceQuestionStage, index)] ? '重新產生中…' : '重新產生此題' }}</button>
                </li>
              </ol>
            </details>
          </section>

          <details class="question-builder">
            <summary><div><small>OPTIONAL QUESTION TOOL</small><h3>需要加問時，再展開題目工具</h3><p>面試紀錄已帶入所屬階段題目；只有需要額外的人格特質或履歷追問時才使用這裡。</p></div><span>展開工具 · 已選 {{ selectedTraits.length }}/10</span></summary>
            <div class="question-builder-body">
            <div class="trait-picker">
              <button v-for="trait in commonTraits" :key="trait" type="button" :class="{ selected: selectedTraits.includes(trait) }" :aria-pressed="selectedTraits.includes(trait)" @click="toggleTrait(trait)">{{ trait }}</button>
            </div>
            <form class="custom-trait" @submit.prevent="addCustomTrait"><input v-model="customTrait" maxlength="30" placeholder="輸入其他人格特質"><button class="button secondary" :disabled="!customTrait.trim() || selectedTraits.length >= 10">加入</button></form>
            <div v-if="selectedTraits.some(trait => !commonTraits.includes(trait))" class="selected-custom-traits"><button v-for="trait in selectedTraits.filter(trait => !commonTraits.includes(trait))" :key="trait" type="button" @click="toggleTrait(trait)">{{ trait }} ×</button></div>
            <button class="button primary generate-questions" data-testid="interview-question-generate" type="button" :disabled="questionLoading || !selectedTraits.length" @click="generateQuestions">{{ questionLoading ? '正在產生建議…' : `產生 ${workspaceApplication.requisition.title} 面試題` }}</button>

            <template v-if="questionSuggestions">
              <p class="question-guidance">{{ questionSuggestions.guidance }}</p>
              <div v-if="questionSuggestions.personalization_basis.length" class="question-personalization-basis">
                <strong>本次出題依據</strong><span v-for="item in questionSuggestions.personalization_basis" :key="item">{{ item }}</span>
              </div>
              <div class="suggestion-groups">
                <article v-for="suggestion in questionSuggestions.suggestions" :key="suggestion.trait">
                  <header><strong>{{ suggestion.trait }}</strong><span>{{ questionSuggestions.job_title }}</span></header>
                  <div v-for="question in suggestion.questions" :key="question.question" class="suggested-question">
                    <div><small v-if="question.source" class="question-source">履歷依據｜{{ question.source }}</small><strong>{{ question.question }}</strong><p v-if="questionCompliance(question).status === 'warning'" class="question-compliance warning" role="alert"><b>⚠ 疑似違法提問</b><span>涉及：{{ complianceCategoryText(questionCompliance(question)) }}</span><em>{{ questionCompliance(question).suggestion }}</em></p><p v-else class="question-compliance ok"><b>✓ 合法</b></p><p><b>提問目的</b>{{ question.purpose }}</p><p><b>追問方向</b>{{ question.follow_up }}</p></div>
                    <button class="button secondary" type="button" :disabled="recordForm.questions.some(item => item.question === question.question) || (recordEditorOpen && !canEditStage(recordForm.stage))" @click="addSuggestedQuestion(question, suggestion.trait)">{{ recordForm.questions.some(item => item.question === question.question) ? '已加入' : '加入紀錄' }}</button>
                  </div>
                </article>
              </div>
            </template>
            </div>
          </details>

          <form v-if="recordEditorOpen" class="record-editor" data-testid="interview-record-form" @submit.prevent="saveRecord">
            <header><div><small>{{ editingRecord ? `RECORD #${editingRecord.id}` : 'NEW INTERVIEW RECORD' }}</small><h3>{{ editingRecord ? '快速更新面試紀錄' : '開始面試紀錄' }}</h3><p>先記候選人的回答即可；評分、觀察與結論可在面試後再補。</p></div><div class="record-answer-progress"><strong>{{ recordAnsweredCount }}/{{ recordForm.questions.length }}</strong><span>已回答</span></div><span v-if="!canEditStage(recordForm.stage)" class="read-only-badge">唯讀</span></header>
            <div v-if="editingRecord && !editorEvaluationVisible" class="evaluation-lock-notice"><span>🔒</span><div><strong>對方的問答已與你共享，評分仍保持獨立</strong><p>待 HR 與主管都將最新紀錄標記為「已提交評分」，系統才會顯示單題評分、面試官觀察、總結與錄用建議。</p></div></div>
            <fieldset :disabled="recordSaving || !canEditStage(recordForm.stage)">
              <details class="record-basic-details">
                <summary><div><strong>面試基本資料</strong><span>{{ recordForm.stage === 'hr' ? 'HR 初談' : '主管複試' }} · {{ recordModeLabels[recordForm.mode] }} · {{ recordStatusLabels[recordForm.status] }}</span></div><em>查看／修改</em></summary>
              <div class="record-meta-grid">
                <label>面試階段<select v-model="recordForm.stage" disabled><option value="hr">HR 初談</option><option value="manager">主管複試</option></select></label>
                <label>面試日期與時間 *<input v-model="recordForm.interviewed_at" type="datetime-local" required></label>
                <label>面試方式<select v-model="recordForm.mode"><option v-for="(label, value) in recordModeLabels" :key="value" :value="value">{{ label }}</option></select></label>
                <label>目前狀態<select v-model="recordForm.status"><option v-for="(label, value) in recordStatusLabels" :key="value" :value="value">{{ label }}</option></select></label>
                <label>面試時長（分鐘）<input v-model.number="recordForm.duration_minutes" type="number" min="1" max="1440"></label>
              </div>
              </details>

              <section class="record-question-section">
                <header><div><strong>快速問答紀錄</strong><span>目前 {{ recordAnsweredCount }}/{{ recordForm.questions.length }} 題已填寫；面試中只要先記回答。</span></div><button class="button secondary" type="button" @click="addBlankQuestion">＋ 自訂問題</button></header>
                <article v-for="(question, index) in recordForm.questions" :key="index" class="record-question-card">
                  <header><span>{{ index + 1 }}</span><label>問題<input v-model="question.question" maxlength="500" placeholder="輸入面試問題" required></label><button type="button" aria-label="移除這個問題" @click="removeRecordQuestion(index)">×</button></header>
                  <p v-if="question.question.trim() && questionCompliance(question).status === 'warning'" class="question-compliance warning" role="alert">
                    <b>⚠ 疑似違法提問</b>
                    <span>涉及：{{ complianceCategoryText(questionCompliance(question)) }}</span>
                    <em>{{ questionCompliance(question).suggestion }}</em>
                  </p>
                  <p v-else-if="question.question.trim()" class="question-compliance ok"><b>✓ 合法</b><span>未偵測到違法／歧視性內容</span></p>
                  <details v-if="question.source || question.purpose || question.follow_up" class="record-question-context">
                    <summary>查看這題的設計依據與追問提示</summary>
                    <div><small v-if="question.source"><b>設計依據</b>{{ question.source }}</small>
                    <small v-if="question.purpose"><b>提問目的</b>{{ question.purpose }}</small>
                    <small v-if="question.follow_up"><b>追問方向</b>{{ question.follow_up }}</small></div>
                  </details>
                  <div class="record-quick-answer">
                    <label>應徵者回答<textarea v-model="question.response" rows="3" maxlength="5000" placeholder="先記重點：情境、採取的行動、最後結果…"></textarea></label>
                  </div>
                  <details v-if="editorEvaluationVisible" class="question-evaluation-details">
                    <summary><span>評分與觀察（選填，可面試後補）</span><em>{{ question.rating ? `${question.rating} 分` : '尚未評分' }}</em></summary>
                    <div class="record-answer-grid">
                      <label>對應特質<input v-model="question.trait" maxlength="100" placeholder="例如：團隊合作"></label>
                      <label>單題評分<select v-model="question.rating"><option :value="null">未評分</option><option v-for="rating in 5" :key="rating" :value="rating">{{ rating }} 分</option></select></label>
                      <label class="wide">面試官觀察（評分區）<textarea v-model="question.notes" rows="2" maxlength="2000" placeholder="記錄非語言反應、待查證處或追問結果…"></textarea></label>
                    </div>
                  </details>
                  <div v-else class="evaluation-lock-inline compact"><span>🔒</span><p><strong>評分與觀察尚未公開</strong><small>候選人回答仍可直接查看。</small></p></div>
                </article>
                <div v-if="!recordForm.questions.length" class="record-question-empty"><strong>還沒有問題</strong><p>從上方建議題庫加入，或按「自訂問題」開始紀錄。</p></div>
              </section>

              <details v-if="editorEvaluationVisible" class="record-conclusion-details">
                <summary><div><strong>面試後結論與建議</strong><span>評分、總結與錄用建議可在面試結束後補填</span></div><em>{{ recordForm.recommendation ? recommendationLabels[recordForm.recommendation] : '尚未填寫' }}</em></summary>
                <div class="record-conclusion">
                  <label>整體評分<select v-model="recordForm.overall_rating"><option :value="null">尚未評分</option><option v-for="rating in 5" :key="rating" :value="rating">{{ rating }} 分</option></select></label>
                  <label>錄用建議<select v-model="recordForm.recommendation"><option :value="null">尚未決定</option><option v-for="(label, value) in recommendationLabels" :key="value" :value="value">{{ label }}</option></select></label>
                  <label class="wide">面試總結<textarea v-model="recordForm.summary" rows="4" maxlength="5000" placeholder="摘要主要優勢、風險、待確認事項與共識…"></textarea></label>
                </div>
              </details>
              <div v-else class="record-conclusion-locked"><span>🔒</span><div><strong>面試總結與錄用建議尚未公開</strong><p>雙方完成各自評估前，不會互相影響判斷。</p></div></div>

              <details v-if="recordForm.stage === 'hr' && (canEditStage('hr') || editingRecord?.private_notes_visible)" class="hr-private-notes">
                <summary><span>HR ONLY</span><div><strong>HR 限定敏感備註（選填）</strong><small>此區內容不會出現在主管的畫面或 API 回應中。</small></div><em>{{ recordForm.private_notes?.trim() ? '已有內容' : '尚未填寫' }}</em></summary>
                <label>私密備註<textarea v-model="recordForm.private_notes" rows="4" maxlength="10000" placeholder="例如：薪資個資、合理調整需求或其他僅限 HR 處理的敏感事項…"></textarea></label>
              </details>
            </fieldset>
            <footer><span>{{ editingRecord ? `建立者：${editingRecord.interviewer_name} · 更新：${formatDate(editingRecord.updated_at)}` : '可先儲存目前回答，其他評估稍後再補。' }}</span><div><button class="button secondary" type="button" :disabled="recordSaving" @click="cancelRecordEdit">關閉</button><button v-if="canEditStage(recordForm.stage)" class="button primary" data-testid="interview-record-save" :disabled="recordSaving">{{ recordSaving ? '儲存中…' : '儲存目前進度' }}</button></div></footer>
          </form>
          <section v-else class="record-editor-empty"><span>記</span><strong>選擇既有紀錄或建立新紀錄</strong><p>建立後會先帶入所屬階段的 5 題，再依面試進度逐題填答。</p><button v-if="canEditStage(defaultRecordStage())" class="button primary" type="button" @click="newRecord()">建立面試紀錄</button></section>
        </main>
      </div>
    </section>
  </div>
</template>

<style scoped>
.interview-embedded-heading{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:15px 17px;border-color:#b9dbd2;background:linear-gradient(110deg,#eef8f5,#fff)}
.interview-embedded-heading>div:first-child{min-width:0}.interview-embedded-heading small,.interview-embedded-heading h2,.interview-embedded-heading p{display:block}.interview-embedded-heading small{color:#a56d17;font-size:10px;font-weight:900;letter-spacing:1px}.interview-embedded-heading h2{margin:3px 0;color:#194f48;font-size:18px}.interview-embedded-heading p{margin:0;color:#677d77;font-size:12px;line-height:1.55}.interview-embedded-actions{display:flex;flex:0 0 auto;align-items:center;gap:8px}
.interview-page{display:grid;gap:14px}.interview-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:25px 28px;border-radius:18px;background:linear-gradient(120deg,#153f3b,#17695f 62%,#74ad91);color:#fff;box-shadow:0 16px 38px rgba(20,74,68,.14)}.interview-hero p{margin:0;color:#f2c96d;font-size:8px;font-weight:800;letter-spacing:1.3px}.interview-hero h1{margin:6px 0;font-size:25px}.interview-hero span{font-size:10px;color:rgba(255,255,255,.76)}.interview-hero .button{background:rgba(255,255,255,.95)}.interview-alert{display:flex;align-items:center;gap:10px;padding:11px 14px;border:1px solid;border-radius:10px;font-size:9px}.interview-alert>strong{width:22px;height:22px;border-radius:50%;display:grid;place-items:center}.interview-alert>span{flex:1}.interview-alert>button{border:0;background:transparent;color:inherit;font-size:18px}.interview-alert.error{border-color:#efd0cd;background:#fff0ef;color:#893d39}.interview-alert.error>strong{background:#e5b0ac}.interview-alert.success{border-color:#baddc3;background:#ecf8ef;color:#286547}.interview-alert.success>strong{background:#cbe8d2}.interview-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.interview-metrics article{padding:16px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-metrics small,.interview-metrics span{display:block;color:var(--muted);font-size:8px}.interview-metrics strong{display:block;margin:4px 0;color:#185e56;font-size:23px}.interview-filters{display:flex;align-items:end;gap:12px;padding:13px 15px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-filters>div{margin-right:auto}.interview-filters>div strong,.interview-filters>div span{display:block}.interview-filters>div strong{font-size:11px}.interview-filters>div span{margin-top:3px;color:var(--muted);font-size:8px}.interview-filters label{display:grid;gap:5px;color:#61756f;font-size:8px}.interview-filters select{width:210px;height:37px;padding:0 10px;border:1px solid #d8e3df;border-radius:8px;background:#fff;color:#31534d;font-size:9px}.interview-filters em{padding-bottom:10px;color:var(--muted);font-size:8px;font-style:normal}.interview-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.interview-card{min-width:0;padding:16px}.interview-card>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.candidate-identity{display:flex;align-items:center;gap:10px;min-width:0}.candidate-identity>span{width:40px;height:40px;flex:0 0 auto;border-radius:50%;display:grid;place-items:center;background:#dceee8;color:#1f6b61;font-weight:800}.candidate-identity h2{margin:0;font-size:13px}.candidate-identity p{margin:3px 0 0;color:var(--muted);font-size:8px}.application-status{padding:4px 8px;border-radius:99px;background:#edf2f0;color:#60736e;font-size:8px;white-space:nowrap}.application-status[data-status="interview"],.application-status[data-status="interviewing"]{background:#e3eff9;color:#326f9d}.application-status[data-status="offered"],.application-status[data-status="hired"]{background:#e1f2e9;color:#27725b}.application-status[data-status="rejected"],.application-status[data-status="withdrawn"]{background:#f8e7e5;color:#a64b46}.application-job{display:grid;gap:3px;margin:14px 0;padding:11px;border-radius:9px;background:#f3f8f6}.application-job small{color:#2c786c;font-size:8px;font-weight:700}.application-job strong{font-size:10px}.application-job span{color:var(--muted);font-size:8px}.application-details{display:grid;grid-template-columns:1fr 1fr;gap:7px}.application-details>div{min-width:0;padding:8px;border:1px solid #e8eeec;border-radius:7px}.application-details small,.application-details strong{display:block;font-size:7px}.application-details small{color:var(--muted)}.application-details strong{margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:8px}.schedule-summary{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:11px;padding:11px 12px;border:1px solid #cde5dc;border-radius:9px;background:#f0f9f5}.schedule-summary.unscheduled{border-style:dashed;background:#fafcfb}.schedule-summary>div{min-width:0}.schedule-summary small,.schedule-summary strong{display:block}.schedule-summary small{color:var(--muted);font-size:7px}.schedule-summary strong{margin-top:3px;color:#245f56;font-size:10px}.schedule-summary p{margin:4px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#71847f;font-size:8px}.schedule-summary .button{flex:0 0 auto}.interview-editor{margin-top:12px;border:1px solid #bcdcd2;border-radius:11px;background:#fbfdfc;overflow:hidden}.interview-editor>header{display:flex;align-items:flex-start;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #dce9e5}.interview-editor>header small{color:#b37c20;font-size:7px;font-weight:800;letter-spacing:1px}.interview-editor>header h3{margin:3px 0 0;font-size:11px}.interview-editor>header button{border:0;background:transparent;color:#61736f;font-size:19px}.editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}.editor-grid label{display:grid;gap:5px;color:#536e68;font-size:8px}.editor-grid .wide{grid-column:1/-1}.editor-grid input,.editor-grid select,.editor-grid textarea{width:100%;padding:9px 10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit}.editor-grid textarea{resize:vertical;line-height:1.6}.interview-editor>footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 14px;border-top:1px solid #dce9e5;background:#f5f9f7}.interview-editor>footer>span{color:var(--muted);font-size:7px}.interview-editor>footer>div{display:flex;gap:7px}.interview-empty{text-align:center;padding:60px 20px;color:var(--muted)}.interview-empty strong,.interview-empty p{display:block}.interview-empty strong{font-size:11px}.interview-empty p{font-size:8px}.interview-empty .spinner{margin-bottom:12px}
.stage-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:11px}.interview-stage{min-width:0;border:1px solid #cde5dc;border-radius:10px;background:#f0f9f5;overflow:hidden}.interview-stage.unscheduled{border-style:dashed;background:#fafcfb}.interview-stage>header{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;padding:10px 11px;border-bottom:1px solid #dce9e5}.interview-stage>header small{display:block;color:#b37c20;font-size:6px;font-weight:800;letter-spacing:.8px}.interview-stage>header h3{margin:3px 0 0;font-size:9px}.interview-stage>header>span{padding:3px 6px;border-radius:99px;background:#fff;color:#28675d;font-size:7px;white-space:nowrap}.stage-content{display:grid;gap:3px;padding:10px 11px}.stage-content small{margin-top:4px;color:var(--muted);font-size:7px}.stage-content strong{color:#245f56;font-size:9px}.stage-content p{min-height:32px;margin:1px 0 0;color:#5f746f;font-size:8px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}.stage-content p.structured-record-locked{padding:7px 8px;border:1px dashed #dfc994;border-radius:6px;background:#fffaf0;color:#876323}.interview-stage>footer{display:flex;align-items:center;justify-content:flex-end;min-height:43px;padding:8px 10px;border-top:1px solid #dce9e5;background:rgba(255,255,255,.5)}.interview-stage>footer>span{margin-right:auto;color:var(--muted);font-size:7px}.interview-stage .interview-editor{margin:0;border-width:1px 0 0;border-radius:0}.interview-stage .interview-editor>footer{min-height:0;background:#f5f9f7}
.record-workspace-entry{display:flex;align-items:center;gap:13px;margin-top:11px;padding:11px 12px;border:1px solid #d7e4e0;border-radius:9px;background:linear-gradient(110deg,#f5faf8,#fffaf1)}.record-workspace-entry>div{flex:1}.record-workspace-entry strong,.record-workspace-entry span{display:block}.record-workspace-entry strong{font-size:10px;color:#315f57}.record-workspace-entry span{margin-top:3px;color:#6a7d78;font-size:8px;line-height:1.5}.record-workspace-overlay{position:fixed;z-index:180;inset:0;display:grid;place-items:center;padding:18px;background:rgba(12,35,32,.58);backdrop-filter:blur(5px)}.record-workspace{width:min(1480px,100%);height:calc(100dvh - 36px);display:flex;flex-direction:column;overflow:hidden;border:1px solid rgba(255,255,255,.45);border-radius:18px;background:#f3f7f5;box-shadow:0 28px 80px rgba(5,31,27,.3)}.record-workspace-header{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 21px;background:linear-gradient(110deg,#133f3a,#176f64);color:#fff}.workspace-person{display:flex;align-items:center;gap:12px}.workspace-person>span{width:43px;height:43px;display:grid;place-items:center;border-radius:50%;background:rgba(255,255,255,.16);font-size:17px;font-weight:800}.workspace-person small{color:#f1cb75;font-size:9px;font-weight:800;letter-spacing:1px}.workspace-person h2{margin:3px 0;font-size:18px}.workspace-person p{margin:0;color:rgba(255,255,255,.75);font-size:11px}.record-workspace-header>button{width:38px;height:38px;border:1px solid rgba(255,255,255,.22);border-radius:50%;background:rgba(255,255,255,.08);color:#fff;font-size:24px}.workspace-message{flex:0 0 auto;display:flex;align-items:center;gap:8px;padding:9px 14px;border-bottom:1px solid;font-size:11px}.workspace-message>span{flex:1}.workspace-message>button{border:0;background:transparent;color:inherit;font-size:18px}.workspace-message.error{border-color:#eac6c2;background:#fff0ef;color:#8e403b}.workspace-message.success{border-color:#c7dfcf;background:#edf8f1;color:#2d674a}.record-workspace-body{min-height:0;flex:1;display:grid;grid-template-columns:280px minmax(0,1fr)}.record-history{min-height:0;overflow:auto;border-right:1px solid #dbe6e2;background:#fff}.record-history>header{position:sticky;z-index:1;top:0;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:13px;border-bottom:1px solid #e0e9e6;background:rgba(255,255,255,.96)}.record-history>header strong,.record-history>header span{display:block}.record-history>header strong{font-size:12px}.record-history>header span{margin-top:2px;color:#748580;font-size:9px}.workspace-loading{display:flex;align-items:center;gap:8px;padding:24px 14px;color:#6d807a;font-size:10px}.record-history-item{position:relative;width:100%;display:grid;gap:4px;padding:13px 14px;border:0;border-bottom:1px solid #e9efed;background:#fff;color:#34554f;text-align:left}.record-history-item:hover,.record-history-item.active{background:#eef8f5}.record-history-item.active:before{content:"";position:absolute;inset:8px auto 8px 0;width:4px;border-radius:0 4px 4px 0;background:#218174}.record-history-item strong{font-size:10px}.record-history-item small{color:#71827d;font-size:8px}.record-history-item em{justify-self:end;color:#31786d;font-size:8px;font-style:normal}.record-status{justify-self:start;padding:3px 6px;border-radius:99px;background:#e8f3ef;color:#2b7365;font-size:8px}.record-status[data-status="planned"]{background:#e8f0f8;color:#326c99}.record-status[data-status="cancelled"],.record-status[data-status="no_show"]{background:#f7e9e7;color:#a04f49}.record-history-empty{padding:35px 20px;text-align:center;color:#758681}.record-history-empty strong{font-size:11px}.record-history-empty p{font-size:9px;line-height:1.6}.record-workspace-main{min-height:0;overflow:auto;padding:15px}.question-builder,.record-editor,.record-editor-empty{border:1px solid #d8e5e1;border-radius:12px;background:#fff;box-shadow:0 5px 18px rgba(24,74,65,.05)}.question-builder{padding:16px;margin-bottom:14px}.question-builder>header{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.question-builder>header small{color:#ae761d;font-size:8px;font-weight:800;letter-spacing:1px}.question-builder>header h3{margin:3px 0;font-size:13px}.question-builder>header p{margin:0;color:#6b7e79;font-size:9px;line-height:1.55}.question-builder>header>span{padding:5px 8px;border-radius:99px;background:#eef5f3;color:#50716a;font-size:9px;white-space:nowrap}.trait-picker,.selected-custom-traits{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.trait-picker button,.selected-custom-traits button{padding:6px 9px;border:1px solid #d6e3df;border-radius:99px;background:#fff;color:#516d67;font-size:9px}.trait-picker button.selected{border-color:#2c897b;background:#e4f4ef;color:#1d6e62;font-weight:700}.selected-custom-traits button{border-color:#d6c590;background:#fff9e9;color:#79602b}.custom-trait{display:flex;gap:7px;margin-top:10px}.custom-trait input{min-width:0;flex:1;height:36px;padding:0 10px;border:1px solid #d5e2de;border-radius:8px}.generate-questions{margin-top:11px}.question-guidance{margin:13px 0 0;padding:10px 12px;border-left:3px solid #d5a74c;border-radius:7px;background:#fff9eb;color:#735c33;font-size:9px;line-height:1.6}.suggestion-groups{display:grid;gap:9px;margin-top:11px}.suggestion-groups>article{overflow:hidden;border:1px solid #dce7e3;border-radius:9px}.suggestion-groups>article>header{display:flex;justify-content:space-between;gap:10px;padding:8px 11px;background:#f2f7f5}.suggestion-groups>article>header strong{font-size:10px;color:#2d6d62}.suggestion-groups>article>header span{color:#758681;font-size:8px}.suggested-question{display:flex;align-items:flex-start;gap:12px;padding:11px;border-top:1px solid #e5ece9}.suggested-question:first-of-type{border-top:0}.suggested-question>div{min-width:0;flex:1}.suggested-question>div>strong{display:block;font-size:10px;line-height:1.5}.suggested-question p{margin:5px 0 0;color:#667b75;font-size:8px;line-height:1.55}.suggested-question p b{margin-right:5px;color:#397268}.suggested-question>.button{flex:0 0 auto}.record-editor>header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid #e0e9e6}.record-editor>header small{color:#ad761f;font-size:8px;font-weight:800;letter-spacing:1px}.record-editor>header h3{margin:3px 0;font-size:13px}.record-editor>header p{margin:0;color:#70817d;font-size:9px}.read-only-badge{padding:5px 8px;border-radius:99px;background:#eef2f1;color:#667873;font-size:9px}.record-editor fieldset{margin:0;padding:0;border:0}.record-meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:15px 16px}.record-meta-grid label,.record-conclusion label,.record-answer-grid label,.record-question-card>header label{display:grid;gap:5px;color:#536e68;font-size:9px}.record-meta-grid input,.record-meta-grid select,.record-conclusion select,.record-conclusion textarea,.record-answer-grid input,.record-answer-grid select,.record-answer-grid textarea,.record-question-card>header input{width:100%;padding:9px 10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit}.record-question-section{padding:0 16px 15px}.record-question-section>header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid #e1e9e6}.record-question-section>header strong,.record-question-section>header span{display:block}.record-question-section>header strong{font-size:11px}.record-question-section>header span{margin-top:3px;color:#748580;font-size:8px}.record-question-card{overflow:hidden;margin-bottom:9px;border:1px solid #dbe6e2;border-radius:9px;background:#fbfdfc}.record-question-card>header{display:grid;grid-template-columns:29px minmax(0,1fr) 28px;align-items:end;gap:8px;padding:10px;border-bottom:1px solid #e2ebe8}.record-question-card>header>span{width:28px;height:28px;display:grid;place-items:center;border-radius:50%;background:#dff0eb;color:#226e63;font-size:10px;font-weight:800}.record-question-card>header>button{height:29px;border:0;background:transparent;color:#a05b54;font-size:18px}.record-answer-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:10px}.record-answer-grid .wide{grid-column:1/-1}.record-answer-grid textarea,.record-conclusion textarea{resize:vertical;line-height:1.55}.record-question-empty{padding:28px;border:1px dashed #cfded9;border-radius:9px;text-align:center;color:#768782}.record-question-empty strong{font-size:10px}.record-question-empty p{margin:4px 0 0;font-size:8px}.record-conclusion{display:grid;grid-template-columns:minmax(0,2fr) minmax(180px,1fr);align-items:start;gap:10px;padding:0 16px 16px}.record-editor>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-top:1px solid #dde7e3;background:#f5f9f7}.record-editor>footer>span{color:#71837e;font-size:8px}.record-editor>footer>div{display:flex;gap:7px}.record-editor-empty{min-height:280px;display:grid;place-content:center;justify-items:center;padding:35px;text-align:center;color:#748681}.record-editor-empty>span{width:47px;height:47px;display:grid;place-items:center;border-radius:50%;background:#e3f1ed;color:#267267;font-size:16px;font-weight:800}.record-editor-empty strong{margin-top:12px;color:#395d56;font-size:12px}.record-editor-empty p{margin:5px 0 13px;font-size:9px}
.question-progress{overflow:hidden;margin-top:12px;border:1px solid #cfdfda;border-radius:12px;background:#fff}.question-progress>header{display:flex;align-items:center;gap:14px;padding:13px 14px;border-bottom:1px solid #dce8e4;background:linear-gradient(110deg,#eef8f5,#fffaf0)}.question-progress>header>div:first-child{min-width:0;flex:1}.question-progress>header small,.question-progress>header strong,.question-progress>header span{display:block}.question-progress>header>div:first-child>small{color:#ad761f;font-size:7px;font-weight:800;letter-spacing:1px}.question-progress>header>div:first-child>strong{margin-top:3px;color:#244f48;font-size:12px}.question-progress>header>div:first-child>span{margin-top:4px;color:#667a75;font-size:8px;line-height:1.5}.question-stage-tabs{display:grid;grid-template-columns:1fr 1fr;gap:6px;flex:0 0 190px}.question-stage-tabs button{display:grid;grid-template-columns:1fr auto;align-items:center;gap:1px 6px;padding:7px 9px;border:1px solid #d4e2de;border-radius:8px;background:#fff;color:#5b706b;text-align:left}.question-stage-tabs button small{grid-row:1;color:inherit;font-size:7px;font-weight:700}.question-stage-tabs button strong{grid-area:1/2/3/3;color:#1e665b;font-size:13px}.question-stage-tabs button span{grid-row:2;color:#82918d;font-size:6px}.question-stage-tabs button.active{border-color:#278477;background:#e7f5f1;color:#1e665b;box-shadow:0 0 0 2px rgba(39,132,119,.08)}.question-plan-meta{display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid #e6eeeb}.question-plan-meta>span{padding:4px 7px;border-radius:99px;background:#e7f3ef;color:#216d61;font-size:7px;font-weight:700}.question-plan-meta>span[data-stage="manager"]{background:#fff3d8;color:#8a621a}.question-plan-meta>small{margin-left:auto;color:#798984;font-size:7px}.question-preview-list{display:grid;gap:0;margin:0;padding:0;list-style:none}.question-preview-list li{display:grid;grid-template-columns:25px minmax(0,1fr);gap:9px;padding:10px 12px;border-bottom:1px solid #edf1f0}.question-preview-list li>span{width:23px;height:23px;display:grid;place-items:center;border-radius:50%;background:#edf2f0;color:#6d7d79;font-size:8px;font-weight:800}.question-preview-list li.answered>span{background:#2a8879;color:#fff}.question-preview-list li>div{min-width:0}.question-preview-list li small{color:#987022;font-size:6px}.question-preview-list li strong{display:block;margin-top:2px;color:#2b4f49;font-size:9px;line-height:1.5}.question-preview-list li p{margin:5px 0 0;padding:6px 8px;border-left:2px solid #72ad9f;border-radius:0 5px 5px 0;background:#f3f9f7;color:#42645e;font-size:8px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}.question-preview-list li p.empty{border-left-color:#d7dfdd;background:#f8faf9;color:#8a9693;font-style:italic}.question-preview-list li em{display:inline-block;margin-top:4px;color:#267367;font-size:7px;font-style:normal;font-weight:700}.question-progress>footer{display:flex;align-items:center;gap:10px;padding:10px 12px;background:#f8faf9}.question-progress>footer>span{min-width:0;flex:1;color:#6f817c;font-size:7px;line-height:1.45}.question-progress-loading,.question-preview-error{display:flex;align-items:center;justify-content:center;gap:8px;min-height:90px;padding:20px;color:#748681;font-size:9px}.question-preview-error{color:#96524c}.record-question-context{display:grid;gap:4px;padding:9px 11px;border-bottom:1px solid #e2ebe8;background:#f5f9f7}.record-question-context small{color:#617771;font-size:8px;line-height:1.5}.record-question-context b{margin-right:7px;color:#2f7065}
.question-personalization-basis{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-top:10px;padding:9px 10px;border:1px solid #d7e7e2;border-radius:8px;background:#f3f9f7}.question-personalization-basis strong{margin-right:3px;color:#315f57;font-size:8px}.question-personalization-basis span{padding:4px 7px;border-radius:99px;background:#fff;color:#527069;font-size:7px}.suggested-question .question-source{display:block;margin-bottom:5px;color:#a16e18;font-size:7px;font-weight:700}
.interview-sharing-policy{flex:0 0 auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;padding:10px 14px;border-bottom:1px solid #d8e5e1;background:#f8fbfa}.interview-sharing-policy>div{display:flex;align-items:center;gap:9px;padding:9px 11px;border:1px solid #dbe7e3;border-radius:9px;background:#fff}.interview-sharing-policy>div>span{width:30px;height:30px;flex:0 0 auto;display:grid;place-items:center;border-radius:50%;background:#e2f2ed;color:#216f63;font-size:9px;font-weight:800}.interview-sharing-policy p,.evaluation-lock-notice p,.evaluation-lock-inline p,.record-conclusion-locked p{margin:0}.interview-sharing-policy strong,.interview-sharing-policy small{display:block}.interview-sharing-policy strong{color:#315a53;font-size:9px}.interview-sharing-policy small{margin-top:2px;color:#71817d;font-size:7px;line-height:1.45}.evaluation-release-chip{padding:4px 7px;border-radius:99px;background:#fff0df;color:#93601c;font-size:7px;font-weight:700}.evaluation-release-chip.unlocked{background:#e1f3e9;color:#257052}.question-preview-list li em.evaluation-locked{color:#8a641f;font-weight:600}.history-visibility{justify-self:start;padding:3px 6px;border-radius:99px;background:#fff1dc!important;color:#8a601b!important}.history-visibility.unlocked{background:#e3f3ea!important;color:#267052!important}.evaluation-lock-notice{display:flex;align-items:flex-start;gap:10px;margin:13px 16px 0;padding:11px 12px;border:1px solid #ead7ad;border-radius:9px;background:#fff9eb;color:#765722}.evaluation-lock-notice>span{font-size:14px}.evaluation-lock-notice strong{display:block;font-size:10px}.evaluation-lock-notice p{margin-top:4px;font-size:8px;line-height:1.55}.locked-field{display:grid;gap:5px;color:#536e68;font-size:9px}.locked-field strong{min-height:36px;display:flex;align-items:center;padding:9px 10px;border:1px solid #e5d8ba;border-radius:7px;background:#fff9ec;color:#876323;font-size:8px}.evaluation-lock-inline{grid-column:1/-1;display:flex;align-items:center;gap:9px;padding:10px;border:1px dashed #dfc994;border-radius:8px;background:#fffaf0;color:#785b22}.evaluation-lock-inline strong,.evaluation-lock-inline small{display:block}.evaluation-lock-inline strong{font-size:9px}.evaluation-lock-inline small{margin-top:2px;font-size:7px}.record-conclusion-locked{display:flex;align-items:center;gap:10px;margin:0 16px 16px;padding:13px;border:1px dashed #dfc994;border-radius:9px;background:#fffaf0;color:#795c25}.record-conclusion-locked strong{display:block;font-size:10px}.record-conclusion-locked p{margin-top:3px;font-size:8px}.hr-private-notes{margin:0 16px 16px;padding:13px;border:1px solid #d3c6eb;border-radius:10px;background:#faf7ff}.hr-private-notes>header{display:flex;align-items:center;gap:10px;margin-bottom:10px}.hr-private-notes>header>span{padding:5px 7px;border-radius:6px;background:#6f5799;color:#fff;font-size:7px;font-weight:800;letter-spacing:.7px}.hr-private-notes>header strong,.hr-private-notes>header small{display:block}.hr-private-notes>header strong{color:#54416f;font-size:10px}.hr-private-notes>header small{margin-top:2px;color:#81728f;font-size:7px}.hr-private-notes label{display:grid;gap:5px;color:#665577;font-size:9px}.hr-private-notes textarea{width:100%;padding:10px;border:1px solid #d8cee7;border-radius:8px;background:#fff;color:#453952;font:inherit;line-height:1.55;resize:vertical}
@media(max-width:1120px){.interview-list{grid-template-columns:1fr}.interview-filters{align-items:stretch;flex-wrap:wrap}.interview-filters>div{flex-basis:100%}.interview-filters label{flex:1}.interview-filters select{width:100%}}
@media(max-width:900px){.interview-sharing-policy{grid-template-columns:1fr}.record-workspace-body{grid-template-columns:1fr}.record-history{max-height:210px;border-right:0;border-bottom:1px solid #dbe6e2}.record-history>header{position:static}.record-meta-grid{grid-template-columns:1fr 1fr}}
@media(max-width:680px){.interview-hero{align-items:flex-start;flex-direction:column}.interview-metrics,.stage-grid{grid-template-columns:1fr}.interview-filters label{flex-basis:100%}.application-details,.editor-grid{grid-template-columns:1fr}.editor-grid .wide{grid-column:auto}.schedule-summary,.interview-editor>footer,.record-workspace-entry,.record-editor>footer,.question-progress>header,.question-progress>footer{align-items:flex-start;flex-direction:column}.interview-editor>footer>div,.record-workspace-entry .button,.record-editor>footer>div,.question-stage-tabs,.question-progress>footer .button{width:100%}.question-stage-tabs{flex-basis:auto}.interview-editor>footer .button,.record-editor>footer .button{flex:1}.record-workspace-overlay{padding:0}.record-workspace{height:100dvh;border-radius:0}.record-workspace-header{padding:13px}.workspace-person>span{display:none}.workspace-person h2{font-size:15px}.record-workspace-main{padding:10px}.record-meta-grid,.record-answer-grid,.record-conclusion{grid-template-columns:1fr}.record-answer-grid .wide{grid-column:auto}.suggested-question{flex-direction:column}.suggested-question>.button{width:100%}.record-conclusion{padding-top:0}}
/* 面試問答資訊層次：固定題、客製題與評估脈絡 */
.question-progress-title{padding-right:8px}
.question-stage-tabs{flex-basis:210px}
.question-stage-tabs button span{font-size:7px;line-height:1.3}
.question-stage-tabs button em{grid-column:1/-1;color:#71827d;font-size:6px;font-style:normal}
.question-plan-meta>small.question-plan-note{margin-left:0;flex:1;line-height:1.4}
.question-generation-warning{display:flex;align-items:flex-start;gap:8px;margin:0 12px 10px;padding:9px 10px;border:1px solid #e7c98c;border-radius:8px;background:#fff8e8;color:#785a20;font-size:8px;line-height:1.5}.question-generation-warning strong{white-space:nowrap}.question-generation-warning span{color:#866b38}
.question-progress>header>div:first-child>small{font-size:10px}.question-progress>header>div:first-child>strong{font-size:16px}.question-progress>header>div:first-child>span{font-size:10px}.question-plan-meta>span{font-size:9px}.question-plan-meta>small{font-size:9px}.question-preview-list li{grid-template-columns:32px minmax(0,1fr);gap:11px;padding:14px 15px}.question-preview-list li>span{width:29px;height:29px;font-size:10px}.question-preview-list li small{font-size:9px}.question-preview-list li strong{font-size:12px;line-height:1.65}.question-preview-list li p{margin-top:7px;padding:8px 10px;font-size:10px;line-height:1.65}.question-preview-list li em{font-size:9px}.question-generation-warning{font-size:10px}
.question-insights{display:grid;gap:4px;margin-top:6px;padding:6px 8px;border:1px solid #e2ebe7;border-radius:6px;background:#fbfdfc}
.question-insights p{display:grid;grid-template-columns:52px minmax(0,1fr);gap:5px;margin:0;color:#617772;font-size:7px;line-height:1.45}
.question-insights b{color:#397268;font-size:7px}
.question-insights span{min-width:0}
.generation-mode-badge{padding:4px 7px;border-radius:99px;background:#eef1f0;color:#667873;font-size:9px;white-space:nowrap}.generation-mode-badge[data-mode="gemini"]{background:#e3f4eb;color:#237052}.generation-mode-badge[data-mode="rules"]{background:#fff1d9;color:#89631d}
.generation-button{min-height:30px;padding:5px 9px;font-size:9px;white-space:nowrap}.question-context-warning{margin:0 12px 10px;padding:9px 10px;border:1px solid #d8c28d;border-radius:8px;background:#fffaf0;color:#765b25;font-size:9px;line-height:1.5}
/* 雙方面試問答是主管與 HR 的主要工作區，採一般桌機不需縮放即可閱讀的尺寸。 */
.question-progress>header{padding:18px 20px;gap:20px}.question-progress-title{padding-right:12px}.question-progress>header>div:first-child>small{font-size:12px;letter-spacing:1.2px}.question-progress>header>div:first-child>strong{margin-top:5px;font-size:21px}.question-progress>header>div:first-child>span{margin-top:6px;font-size:13px;line-height:1.65}
.question-stage-tabs{flex-basis:270px;gap:9px}.question-stage-tabs button{gap:3px 8px;padding:11px 13px}.question-stage-tabs button small{font-size:13px}.question-stage-tabs button strong{font-size:19px}.question-stage-tabs button span{font-size:11px}.question-stage-tabs button em{font-size:10px;line-height:1.45}
.question-plan-meta{gap:10px;padding:12px 16px}.question-plan-meta>span,.generation-mode-badge{font-size:12px}.question-plan-meta>small,.question-plan-meta>small.question-plan-note{font-size:12px;line-height:1.55}.generation-button{min-height:38px;padding:8px 13px;font-size:12px}.evaluation-release-chip{font-size:11px}
.question-preview-list li{grid-template-columns:38px minmax(0,1fr);gap:14px;padding:17px 18px}.question-preview-list li>span{width:34px;height:34px;font-size:13px}.question-preview-list li small{font-size:12px}.question-preview-list li strong{margin-top:4px;font-size:15px;line-height:1.7}.question-preview-list li p{margin-top:9px;padding:10px 12px;font-size:13px;line-height:1.7}.question-preview-list li em{font-size:11px}
.question-insights{gap:7px;margin-top:9px;padding:9px 11px}.question-preview-list .question-insights p{grid-template-columns:72px minmax(0,1fr);gap:8px;margin:0;padding:0;border:0;background:transparent;font-size:12px;line-height:1.6}.question-preview-list .question-insights b{font-size:12px}.question-progress>footer{padding:13px 16px}.question-progress>footer>span{font-size:11px;line-height:1.6}.question-progress>footer .button{min-height:40px;padding:9px 15px;font-size:13px}.question-progress-loading,.question-preview-error{font-size:13px}.question-generation-warning,.question-context-warning{font-size:12px;line-height:1.6}
/* 面試工作區採漸進式揭露：面試中先記回答，其餘欄位需要時才展開。 */
.question-builder{padding:0}.question-builder>summary,.record-basic-details>summary,.question-evaluation-details>summary,.record-conclusion-details>summary,.hr-private-notes>summary{list-style:none;cursor:pointer}.question-builder>summary::-webkit-details-marker,.record-basic-details>summary::-webkit-details-marker,.question-evaluation-details>summary::-webkit-details-marker,.record-conclusion-details>summary::-webkit-details-marker,.hr-private-notes>summary::-webkit-details-marker{display:none}
.question-builder>summary{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 17px}.question-builder>summary>div{min-width:0}.question-builder>summary small{color:#ae761d;font-size:10px;font-weight:800;letter-spacing:1px}.question-builder>summary h3{margin:4px 0;font-size:15px}.question-builder>summary p{margin:0;color:#6b7e79;font-size:11px;line-height:1.55}.question-builder>summary>span{flex:0 0 auto;padding:7px 10px;border-radius:99px;background:#eef5f3;color:#386b63;font-size:11px;font-weight:700}.question-builder[open]>summary{border-bottom:1px solid #e1ebe7}.question-builder-body{padding:0 16px 16px}
.workspace-gemini-panel{position:sticky;z-index:4;top:0;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;margin-bottom:14px;padding:14px 16px;border:2px solid #2a8b7d;border-radius:12px;background:#fff;box-shadow:0 8px 22px rgba(24,91,80,.13)}.workspace-gemini-copy small,.workspace-gemini-copy strong,.workspace-gemini-copy span{display:block}.workspace-gemini-copy small{color:#a76f16;font-size:10px;font-weight:800;letter-spacing:1px}.workspace-gemini-copy strong{margin-top:3px;color:#244f48;font-size:15px}.workspace-gemini-copy span{margin-top:4px;color:#657a74;font-size:11px;line-height:1.55}.workspace-gemini-actions{display:flex;align-items:center;gap:9px}.workspace-gemini-actions .button{min-height:42px;padding:9px 14px;font-size:13px;white-space:nowrap}.workspace-gemini-panel>.workspace-gemini-warning,.workspace-gemini-panel>.workspace-token-usage,.workspace-gemini-preview{grid-column:1/-1}.workspace-token-usage{margin:0;padding:7px 10px;border-radius:7px;background:#eef7f4;color:#326d63;font-size:11px;line-height:1.5}.workspace-gemini-warning{margin:0;padding:8px 10px;border-radius:7px;background:#fff5df;color:#805b19;font-size:11px;line-height:1.5}.workspace-gemini-preview{border-top:1px solid #e0e9e6;padding-top:9px}.workspace-gemini-preview>summary{cursor:pointer;color:#2f7166;font-size:11px;font-weight:700}.workspace-gemini-preview ol{display:grid;gap:6px;margin:9px 0 0;padding-left:22px}.workspace-gemini-preview li{color:#496860;font-size:11px;line-height:1.55}.generation-mode-badge[data-mode="none"]{background:#eef2f1;color:#657873}.question-token-usage{color:#2f766a!important;font-weight:700}
.record-editor>header{align-items:center;padding:16px 18px}.record-editor>header>div:first-child{min-width:0;flex:1}.record-editor>header h3{font-size:16px}.record-editor>header p{font-size:11px;line-height:1.55}.record-answer-progress{flex:0 0 auto;display:grid;justify-items:center;min-width:70px;padding:8px 12px;border-radius:9px;background:#eaf6f2;color:#236b60}.record-answer-progress strong{font-size:18px}.record-answer-progress span{font-size:10px}
.record-basic-details{margin:13px 16px 4px;border:1px solid #dce7e3;border-radius:9px;background:#fbfdfc}.record-basic-details>summary,.record-conclusion-details>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px}.record-basic-details>summary strong,.record-basic-details>summary span,.record-conclusion-details>summary strong,.record-conclusion-details>summary span{display:block}.record-basic-details>summary strong,.record-conclusion-details>summary strong{color:#315d55;font-size:12px}.record-basic-details>summary span,.record-conclusion-details>summary span{margin-top:3px;color:#748681;font-size:10px}.record-basic-details>summary em,.record-conclusion-details>summary em{color:#287469;font-size:10px;font-style:normal;font-weight:700}.record-basic-details[open]>summary,.record-conclusion-details[open]>summary{border-bottom:1px solid #e1e9e6}.record-basic-details .record-meta-grid{padding:13px 14px}.record-meta-grid label,.record-conclusion label,.record-answer-grid label,.record-question-card>header label,.record-quick-answer label{font-size:11px}.record-meta-grid input,.record-meta-grid select,.record-conclusion select,.record-conclusion textarea,.record-answer-grid input,.record-answer-grid select,.record-answer-grid textarea,.record-question-card>header input,.record-quick-answer textarea{font-size:13px}
.record-question-section{padding-top:5px}.record-question-section>header strong{font-size:14px}.record-question-section>header span{font-size:10px}.record-question-card{margin-bottom:12px}.record-question-card>header{align-items:center;padding:12px}.record-question-card>header>span{width:32px;height:32px;font-size:12px}.record-question-card>header input{font-weight:650}.record-question-context{display:block;padding:0;background:#f5f9f7}.record-question-context>summary{padding:8px 12px;color:#3b7168;font-size:10px;font-weight:700}.record-question-context>summary:before,.question-evaluation-details>summary:before,.record-basic-details>summary:before,.record-conclusion-details>summary:before,.question-builder>summary:before{content:'＋';margin-right:7px}.record-question-context[open]>summary:before,.question-evaluation-details[open]>summary:before,.record-basic-details[open]>summary:before,.record-conclusion-details[open]>summary:before,.question-builder[open]>summary:before{content:'－'}.record-question-context>div{display:grid;gap:5px;padding:0 12px 10px}.record-question-context small{font-size:10px}
.record-quick-answer{padding:12px}.record-quick-answer label{display:grid;gap:6px;color:#365f58;font-weight:700}.record-quick-answer textarea{width:100%;min-height:92px;padding:11px 12px;border:1px solid #bfd9d1;border-radius:8px;background:#fff;color:#284a44;line-height:1.65;resize:vertical}.record-quick-answer textarea:focus{border-color:#258174;outline:3px solid rgba(37,129,116,.1)}
.question-evaluation-details{margin:0 12px 12px;border:1px solid #e1e9e6;border-radius:8px;background:#fff}.question-evaluation-details>summary{display:flex;align-items:center;padding:9px 11px;color:#60756f;font-size:10px}.question-evaluation-details>summary span{flex:1}.question-evaluation-details>summary em{color:#2e756a;font-size:10px;font-style:normal}.question-evaluation-details[open]>summary{border-bottom:1px solid #e4ebe9}.evaluation-lock-inline.compact{margin:0 12px 12px;padding:8px 10px}.evaluation-lock-inline.compact strong{font-size:10px}.evaluation-lock-inline.compact small{font-size:9px}
.record-conclusion-details{margin:0 16px 14px;border:1px solid #d8e5e1;border-radius:9px;background:#fbfdfc}.record-conclusion-details .record-conclusion{grid-template-columns:1fr 1fr;padding:13px 14px}.record-conclusion .wide{grid-column:1/-1}.record-conclusion-details textarea{width:100%}.record-conclusion-locked{margin-top:10px}
.hr-private-notes{padding:0}.hr-private-notes>summary{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px;padding:12px 13px}.hr-private-notes>summary>span{padding:5px 7px;border-radius:6px;background:#6f5799;color:#fff;font-size:8px;font-weight:800;letter-spacing:.7px}.hr-private-notes>summary strong,.hr-private-notes>summary small{display:block}.hr-private-notes>summary strong{color:#54416f;font-size:11px}.hr-private-notes>summary small{margin-top:2px;color:#81728f;font-size:9px}.hr-private-notes>summary em{color:#705c86;font-size:9px;font-style:normal}.hr-private-notes>label{margin:0 13px 13px}.record-editor>footer{position:sticky;z-index:2;bottom:0;padding:13px 16px;box-shadow:0 -5px 14px rgba(26,71,63,.06)}.record-editor>footer>span{font-size:10px}.record-editor>footer .button{min-height:39px;font-size:12px}
@media(max-width:680px){.workspace-gemini-panel{position:static;grid-template-columns:1fr}.workspace-gemini-actions{align-items:stretch;flex-direction:column}.workspace-gemini-actions .button{width:100%}.question-builder>summary,.record-editor>header{align-items:flex-start;flex-direction:column}.record-answer-progress{justify-items:start}.record-basic-details{margin-inline:10px}.record-conclusion-details,.hr-private-notes{margin-inline:10px}.record-conclusion-details .record-conclusion{grid-template-columns:1fr}.record-conclusion .wide{grid-column:auto}.record-editor>footer{position:static}}

/* 面試題主畫面只保留題目與回答；產生資訊和面試提示按需展開。 */
.question-plan-meta{flex-wrap:wrap}
.question-plan-meta>small{margin-left:auto}
.question-plan-details{margin:0 16px 10px;border:1px solid #e0e9e6;border-radius:8px;background:#fafcfb}
.question-plan-details>summary{cursor:pointer;padding:8px 10px;color:#3a7067;font-size:11px;font-weight:700}
.question-plan-details>span{display:block;padding:0 10px 9px;color:#647b75;font-size:11px;line-height:1.55}
.question-generation-error{display:flex;align-items:flex-start;gap:8px;margin:0 12px 10px;padding:9px 10px;border:1px solid #e5b9b5;border-radius:8px;background:#fff1f0;color:#8c403b;font-size:12px;line-height:1.55}
.question-generation-error strong{white-space:nowrap}
.question-prompt-details{margin-top:9px;border:1px solid #e0e9e6;border-radius:7px;background:#fafcfb}
.question-prompt-details>summary{cursor:pointer;padding:8px 10px;color:#3a7067;font-size:11px;font-weight:700}
.question-prompt-details>div{display:grid;gap:7px;padding:0 10px 10px}
.question-preview-list .question-prompt-details p{display:grid;grid-template-columns:72px minmax(0,1fr);gap:8px;margin:0;padding:0;border:0;background:transparent;color:#627873;font-size:11px;line-height:1.55}
.question-prompt-details b{color:#397268}
.question-preview-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}
.question-preview-heading>strong{min-width:0;flex:1}
.question-regenerate-button{flex:0 0 auto;min-height:34px;padding:6px 10px;border:1px solid #78b8aa;border-radius:8px;background:#f2faf7;color:#1f7165;font-size:11px;font-weight:800;white-space:nowrap;cursor:pointer}
.question-regenerate-button:hover:not(:disabled){border-color:#287f72;background:#e5f5f0}
.question-regenerate-button:disabled{cursor:not-allowed;opacity:.55}
.workspace-gemini-panel{position:static;border:1px solid #cfe0db;box-shadow:none}
.workspace-gemini-panel>.workspace-gemini-warning,.workspace-generation-details,.workspace-gemini-preview{grid-column:1/-1}
.workspace-generation-details{border-top:1px solid #e0e9e6;padding-top:9px}
.workspace-generation-details>summary{cursor:pointer;color:#2f7166;font-size:11px;font-weight:700}
.workspace-generation-details p{margin:7px 0 0;color:#5d756f;font-size:11px}
.workspace-gemini-preview ol{padding-left:24px}
.workspace-gemini-preview li{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start;gap:10px;margin-bottom:8px;padding:9px 10px;border:1px solid #e0eae7;border-radius:8px;background:#fbfdfc}
.workspace-gemini-preview li>div{min-width:0}
.workspace-gemini-preview li strong{color:#345d56;font-size:11px;line-height:1.6}
.interview-sharing-policy{display:block;grid-template-columns:none;padding:0}
.interview-sharing-policy>summary{display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:9px 14px;color:#315a53;font-size:11px}
.interview-sharing-policy>summary span{color:#39776d;font-size:10px}
.interview-sharing-policy>.sharing-policy-details{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:0 14px 10px;border:0;border-radius:0;background:transparent}
.sharing-policy-details p{display:grid;gap:3px;padding:8px 10px;border:1px solid #dbe7e3;border-radius:8px;background:#fff}
.sharing-policy-details b{color:#2e6d62;font-size:10px}
.sharing-policy-details span{color:#71817d;font-size:9px;line-height:1.45}
@media(max-width:900px){.interview-sharing-policy>.sharing-policy-details{grid-template-columns:1fr}}
@media(max-width:680px){.question-preview-heading,.workspace-gemini-preview li{grid-template-columns:1fr;align-items:stretch;flex-direction:column}.question-regenerate-button{width:100%}}

/* 應徵者採一人一列，排程、題目與紀錄只在點開該列後顯示。 */
.interview-list{grid-template-columns:1fr;gap:10px}
.interview-card{padding:0;overflow:hidden;transition:border-color .18s ease,box-shadow .18s ease}
.interview-card.expanded{border-color:#8fc4b7;box-shadow:0 8px 24px rgba(31,91,81,.08)}
.interview-card>.interview-row-summary{display:block;width:100%}
.interview-row-toggle{display:grid;grid-template-columns:minmax(260px,1fr) minmax(310px,auto) 36px;align-items:center;gap:18px;width:100%;padding:14px 16px;border:0;background:#fff;color:inherit;text-align:left;cursor:pointer}
.interview-row-toggle:hover{background:#f5faf8}.interview-row-toggle:focus-visible{outline:3px solid rgba(35,130,116,.2);outline-offset:-3px}
.interview-row-toggle .candidate-identity>div{min-width:0}.interview-row-toggle .candidate-identity h2,.interview-row-toggle .candidate-identity p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.interview-row-progress{display:grid;grid-template-columns:auto minmax(210px,auto);align-items:center;justify-items:end;gap:4px 12px}.interview-row-progress .application-status{grid-row:1/3}.interview-row-progress strong{font-size:10px;color:#315f57}.interview-row-progress small{font-size:8px;color:#71847f}
.interview-row-toggle .row-chevron{width:30px;height:30px;display:grid;place-items:center;border:1px solid #cfe0db;border-radius:50%;background:#f3f8f6;color:#236f64;font-size:18px;font-weight:500}
.interview-card-detail{padding:1px 16px 16px;border-top:1px solid #e0ebe7;background:#fff}
@media(max-width:820px){.interview-row-toggle{grid-template-columns:minmax(0,1fr) 32px;gap:10px;padding:13px}.interview-row-progress{grid-column:1;grid-row:2;justify-items:start;grid-template-columns:auto 1fr}.interview-row-progress .application-status{grid-row:auto}.interview-row-toggle .row-chevron{grid-column:2;grid-row:1/3}.interview-card-detail{padding-inline:12px}.stage-grid{grid-template-columns:1fr}}
@media(max-width:680px){.interview-embedded-heading{align-items:stretch;flex-direction:column}.interview-embedded-actions{align-items:stretch;flex-direction:column}.interview-embedded-actions .button{width:100%}}

/* 面試題目合規檢核（就服法§5 / 性平法§7·§11）：綠=合法、紅=疑似違法。 */
.question-compliance{display:grid !important;gap:2px;margin:7px 0 0 !important;padding:8px 10px !important;border-left:3px solid !important;border-radius:0 6px 6px 0 !important;font-size:11px !important;line-height:1.55 !important}
.question-compliance b{font-weight:800}
.question-compliance span{font-size:10px}
.question-compliance em{font-style:normal;font-size:10px;line-height:1.5}
.question-compliance.ok{border-left-color:#2a8879 !important;background:#edf8f3 !important;color:#1f6b60 !important}
.question-compliance.warning{border-left-color:#c94b43 !important;background:#fdeceb !important;color:#8f342e !important}
.suggested-question .question-compliance{margin-top:6px !important}
.question-compliance-inline{display:inline-block;margin-left:8px;padding:1px 7px;border-radius:99px;font-size:9px;font-weight:700;vertical-align:middle}
.question-compliance-inline.ok{background:#e3f4eb;color:#237052}
.question-compliance-inline.warning{background:#fbe0de;color:#a2352e;cursor:help}
</style>
