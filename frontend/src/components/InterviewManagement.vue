<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

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
} from '../services/hrApi'
import { authSession } from '../services/auth'
import { formatApiDateTime, parseApiDateTime } from '../utils/dateTime'

const applications = ref<ApplicationDto[]>([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const departmentId = ref<number | null>(null)
const requisitionId = ref<number | null>(null)
const editingApplicationId = ref<number | null>(null)
const editingStage = ref<InterviewStage | null>(null)
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
const cardInterviewLoading = ref(false)
const cardInterviewErrors = ref<Record<number, string>>({})
const recordsByApplication = ref<Record<number, InterviewRecordDto[]>>({})
const plansByApplicationStage = ref<Record<string, InterviewQuestionPlan>>({})
const inlineStageByApplication = reactive<Record<number, InterviewStage>>({})
const selectedTraits = ref<string[]>([])
const customTrait = ref('')
const recordForm = reactive<InterviewRecordWrite>({
  stage: 'hr',
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
    .map(value => parseApiDateTime(value).getTime())
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

async function load() {
  loading.value = true
  error.value = ''
  try {
    applications.value = (await hrApi.applications()).data
    applications.value.forEach(application => {
      if (!inlineStageByApplication[application.id]) {
        inlineStageByApplication[application.id] = defaultRecordStage()
      }
    })
    await loadCardInterviewData(applications.value)
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

function sortInterviewRecords(records: InterviewRecordDto[]) {
  return [...records].sort((left, right) => (
    parseApiDateTime(right.interviewed_at).getTime() - parseApiDateTime(left.interviewed_at).getTime()
  ))
}

async function loadCardInterviewData(items: ApplicationDto[]) {
  if (!items.length) {
    recordsByApplication.value = {}
    plansByApplicationStage.value = {}
    cardInterviewErrors.value = {}
    return
  }
  cardInterviewLoading.value = true
  const nextRecords: Record<number, InterviewRecordDto[]> = {}
  const nextPlans: Record<string, InterviewQuestionPlan> = {}
  const nextErrors: Record<number, string> = {}

  let hrTemplate: InterviewQuestionPlan | null = null
  try {
    hrTemplate = (await hrApi.interviewQuestionPlan(items[0].id, 'hr')).data
  } catch {
    // Each card remains usable even if the preview endpoint is temporarily unavailable.
  }

  await Promise.all(items.map(async application => {
    const [recordResult, managerPlanResult] = await Promise.allSettled([
      hrApi.interviewRecords(application.id),
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
    if (managerPlanResult.status === 'fulfilled') {
      nextPlans[planKey(application.id, 'manager')] = managerPlanResult.value.data
    } else if (!nextErrors[application.id]) {
      nextErrors[application.id] = managerPlanResult.reason instanceof Error
        ? managerPlanResult.reason.message
        : '無法載入主管題目'
    }
    if (hrTemplate) {
      nextPlans[planKey(application.id, 'hr')] = {
        ...hrTemplate,
        application_id: application.id,
        job_title: application.requisition.title,
      }
    }
  }))

  recordsByApplication.value = nextRecords
  plansByApplicationStage.value = nextPlans
  cardInterviewErrors.value = nextErrors
  cardInterviewLoading.value = false
}

async function ensureQuestionPlan(application: ApplicationDto, stage: InterviewStage) {
  const key = planKey(application.id, stage)
  const existing = plansByApplicationStage.value[key]
  if (existing) return existing
  const plan = (await hrApi.interviewQuestionPlan(application.id, stage)).data
  plansByApplicationStage.value = { ...plansByApplicationStage.value, [key]: plan }
  return plan
}

function latestStageRecord(applicationId: number, stage: InterviewStage) {
  return (recordsByApplication.value[applicationId] || []).find(record => record.stage === stage) || null
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
  const recordQuestions = latestStageRecord(applicationId, stage)?.questions || []
  return mergeQuestionsToFive(recordQuestions, planQuestions(applicationId, stage))
}

function inlineStage(applicationId: number): InterviewStage {
  return inlineStageByApplication[applicationId] || defaultRecordStage()
}

function questionIsAnswered(question: InterviewRecordQuestion) {
  return Boolean(question.response?.trim())
}

function stageAnsweredCount(applicationId: number, stage: InterviewStage) {
  const record = latestStageRecord(applicationId, stage)
  return record ? record.questions.slice(0, 5).filter(questionIsAnswered).length : 0
}

function questionAnswer(question: InterviewRecordQuestion) {
  if (question.response?.trim()) return question.response.trim()
  return '尚未紀錄答案'
}

function stageSubmissionLabel(applicationId: number, stage: InterviewStage) {
  const record = latestStageRecord(applicationId, stage)
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
  const hrRecord = latestStageRecord(applicationId, 'hr')
  const managerRecord = latestStageRecord(applicationId, 'manager')
  return hrRecord?.status === 'completed' && managerRecord?.status === 'completed'
}

const editorEvaluationVisible = computed(() => (
  !editingRecord.value || editingRecord.value.evaluation_revealed
))

function inlineActionLabel(applicationId: number, stage: InterviewStage) {
  const record = latestStageRecord(applicationId, stage)
  if (record) return canEditStage(stage) ? '繼續填答' : '查看完整紀錄'
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
    await ensureQuestionPlan(workspaceApplication.value, stage)
    if (!editingRecord.value && recordForm.stage === stage) {
      recordForm.questions = planQuestions(workspaceApplication.value.id, stage)
    }
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法載入系統面試題'
  }
}

async function openInlineRecord(application: ApplicationDto) {
  const stage = inlineStage(application.id)
  await openRecordWorkspace(application)
  const record = interviewRecords.value.find(item => item.stage === stage)
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

async function changeNewRecordStage() {
  if (editingRecord.value || !workspaceApplication.value) return
  workspaceError.value = ''
  try {
    await ensureQuestionPlan(workspaceApplication.value, recordForm.stage)
    recordForm.questions = planQuestions(workspaceApplication.value.id, recordForm.stage)
  } catch (cause) {
    workspaceError.value = cause instanceof Error ? cause.message : '無法載入系統面試題'
  }
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
            <div><small>SHARED Q&amp;A · INDEPENDENT REVIEW</small><strong>雙方面試問答與進度</strong><span>HR 使用公司固定 5 題；主管使用職位 × 履歷客製 5 題。問題與回答即時共享，評分各自獨立。</span></div>
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

          <div v-if="cardInterviewLoading && !fiveQuestionSet(application.id, inlineStage(application.id)).length" class="question-progress-loading"><span class="spinner"></span>正在準備 5 題…</div>
          <template v-else>
            <div class="question-plan-meta">
              <span :data-stage="inlineStage(application.id)">{{ inlineStage(application.id) === 'hr' ? '全公司固定題' : '職位 × 個人背景客製題' }}</span>
              <b class="evaluation-release-chip" :class="{ unlocked: peerEvaluationsReleased(application.id) }">{{ peerEvaluationsReleased(application.id) ? '雙方已提交 · 評分已公開' : '評分鎖定至雙方提交' }}</b>
              <small v-if="latestStageRecord(application.id, inlineStage(application.id))">最後更新：{{ formatDate(latestStageRecord(application.id, inlineStage(application.id))?.updated_at || null) }}</small>
              <small v-else>尚未開始填答</small>
            </div>

            <ol v-if="fiveQuestionSet(application.id, inlineStage(application.id)).length" class="question-preview-list">
              <li
                v-for="(question, index) in fiveQuestionSet(application.id, inlineStage(application.id))"
                :key="`${index}-${question.question}`"
                :class="{ answered: questionIsAnswered(question) }"
              >
                <span>{{ questionIsAnswered(question) ? '✓' : index + 1 }}</span>
                <div>
                  <small v-if="question.source">設計依據｜{{ question.source }}</small>
                  <strong>{{ question.question }}</strong>
                  <p :class="{ empty: !questionIsAnswered(question) }">{{ questionAnswer(question) }}</p>
                  <em v-if="question.rating">{{ question.rating }} / 5 分</em>
                  <em v-else-if="latestStageRecord(application.id, inlineStage(application.id)) && !latestStageRecord(application.id, inlineStage(application.id))?.evaluation_revealed" class="evaluation-locked">🔒 評分與觀察於雙方提交後顯示</em>
                </div>
              </li>
            </ol>
            <div v-else class="question-preview-error">{{ cardInterviewErrors[application.id] || '目前無法載入題目，仍可開啟完整紀錄畫面。' }}</div>

            <footer>
              <span v-if="latestStageRecord(application.id, inlineStage(application.id))">
                {{ inlineStage(application.id) === 'hr' ? 'HR' : '主管' }} 紀錄者：{{ latestStageRecord(application.id, inlineStage(application.id))?.interviewer_name }}。雙方可同步查看問答；只有紀錄者能修改自己的內容。
              </span>
              <span v-else>{{ inlineStage(application.id) === 'hr' ? '由 HR 維護固定題答案' : '由部門主管維護客製題答案' }}</span>
              <button
                class="button primary"
                type="button"
                :disabled="!canEditStage(inlineStage(application.id)) && !latestStageRecord(application.id, inlineStage(application.id))"
                :data-testid="`interview-workspace-${application.id}`"
                @click="openInlineRecord(application)"
              >{{ inlineActionLabel(application.id, inlineStage(application.id)) }}</button>
            </footer>
          </template>
        </section>
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

      <section class="interview-sharing-policy" aria-label="面試資料共享規則">
        <div><span>✓</span><p><strong>問答即時共享</strong><small>HR 與主管都能看到彼此問了什麼、候選人如何回答及目前進度。</small></p></div>
        <div><span>🔒</span><p><strong>評分獨立作答</strong><small>單題評分、觀察、總結與錄用建議，等雙方都提交後才互相公開。</small></p></div>
        <div v-if="authSession.state.user?.role === 'hr' || authSession.state.user?.role === 'admin'"><span>HR</span><p><strong>HR 私密備註</strong><small>敏感資訊只提供 HR／管理員查看，部門主管無法取得。</small></p></div>
      </section>

      <div class="record-workspace-body">
        <aside class="record-history">
          <header><div><strong>面試紀錄</strong><span>{{ interviewRecords.length }} 筆歷程</span></div><button class="button primary" type="button" data-testid="interview-record-new" @click="newRecord()">＋ 新增</button></header>
          <div v-if="recordsLoading" class="workspace-loading"><span class="spinner"></span>載入紀錄中…</div>
          <button v-for="record in interviewRecords" v-else :key="record.id" class="record-history-item" :class="{ active: editingRecord?.id === record.id }" type="button" @click="editRecord(record)">
            <span class="record-status" :data-status="record.status">{{ recordStatusLabels[record.status] }}</span>
            <strong>{{ record.stage === 'hr' ? 'HR 初談' : '主管複試' }} · {{ formatDate(record.interviewed_at) }}</strong>
            <small>{{ recordModeLabels[record.mode] }}<template v-if="record.duration_minutes"> · {{ record.duration_minutes }} 分鐘</template></small>
            <small>{{ record.interviewer_name }} · 已記錄 {{ answeredQuestionCount(record) }}/{{ record.questions.length }} 題</small>
            <small class="history-visibility" :class="{ unlocked: record.evaluation_revealed }">{{ record.evaluation_revealed ? '評分可見' : '僅共享問答 · 評分保護中' }}</small>
            <em>{{ canEditRecord(record) ? '可編輯' : '唯讀' }} →</em>
          </button>
          <div v-if="!recordsLoading && !interviewRecords.length" class="record-history-empty"><strong>尚無過程紀錄</strong><p>建立第一筆紀錄，面試中即可逐題輸入回答與評分。</p></div>
        </aside>

        <main class="record-workspace-main">
          <section class="question-builder">
            <header><div><small>RESUME-BASED QUESTION GUIDE</small><h3>履歷背景 × 人格特質 × 應徵職位</h3><p>系統會讀取這位候選人的職稱、年資、技能與最近經歷，再結合所選特質及 {{ workspaceApplication.requisition.title }} 產生專屬加問題。</p></div><span>{{ selectedTraits.length }}/10 項</span></header>
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
                    <div><small v-if="question.source" class="question-source">履歷依據｜{{ question.source }}</small><strong>{{ question.question }}</strong><p><b>提問目的</b>{{ question.purpose }}</p><p><b>追問方向</b>{{ question.follow_up }}</p></div>
                    <button class="button secondary" type="button" :disabled="recordForm.questions.some(item => item.question === question.question) || (recordEditorOpen && !canEditStage(recordForm.stage))" @click="addSuggestedQuestion(question, suggestion.trait)">{{ recordForm.questions.some(item => item.question === question.question) ? '已加入' : '加入紀錄' }}</button>
                  </div>
                </article>
              </div>
            </template>
          </section>

          <form v-if="recordEditorOpen" class="record-editor" data-testid="interview-record-form" @submit.prevent="saveRecord">
            <header><div><small>{{ editingRecord ? `RECORD #${editingRecord.id}` : 'NEW INTERVIEW RECORD' }}</small><h3>{{ editingRecord ? '檢視／更新面試過程' : '建立面試過程紀錄' }}</h3><p>依實際面試進度逐題記錄，不必等到面試結束才一次補寫。</p></div><span v-if="!canEditStage(recordForm.stage)" class="read-only-badge">唯讀</span></header>
            <div v-if="editingRecord && !editorEvaluationVisible" class="evaluation-lock-notice"><span>🔒</span><div><strong>對方的問答已與你共享，評分仍保持獨立</strong><p>待 HR 與主管都將最新紀錄標記為「已提交評分」，系統才會顯示單題評分、面試官觀察、總結與錄用建議。</p></div></div>
            <fieldset :disabled="recordSaving || !canEditStage(recordForm.stage)">
              <div class="record-meta-grid">
                <label>面試階段<select v-model="recordForm.stage" :disabled="authSession.state.user?.role !== 'admin' || !!editingRecord" @change="changeNewRecordStage"><option value="hr">HR 初談</option><option value="manager">主管複試</option></select></label>
                <label>面試日期與時間 *<input v-model="recordForm.interviewed_at" type="datetime-local" required></label>
                <label>面試方式<select v-model="recordForm.mode"><option v-for="(label, value) in recordModeLabels" :key="value" :value="value">{{ label }}</option></select></label>
                <label>目前狀態<select v-model="recordForm.status"><option v-for="(label, value) in recordStatusLabels" :key="value" :value="value">{{ label }}</option></select></label>
                <label>面試時長（分鐘）<input v-model.number="recordForm.duration_minutes" type="number" min="1" max="1440"></label>
                <label v-if="editorEvaluationVisible">整體評分<select v-model="recordForm.overall_rating"><option :value="null">尚未評分</option><option v-for="rating in 5" :key="rating" :value="rating">{{ rating }} 分</option></select></label>
                <div v-else class="locked-field"><small>整體評分</small><strong>🔒 雙方提交後顯示</strong></div>
              </div>

              <section class="record-question-section">
                <header><div><strong>提問與回答紀錄</strong><span>{{ recordForm.questions.length }} 題；可從上方建議題庫加入，或自行新增。</span></div><button class="button secondary" type="button" @click="addBlankQuestion">＋ 自訂問題</button></header>
                <article v-for="(question, index) in recordForm.questions" :key="index" class="record-question-card">
                  <header><span>{{ index + 1 }}</span><label>問題<input v-model="question.question" maxlength="500" placeholder="輸入面試問題" required></label><button type="button" aria-label="移除這個問題" @click="removeRecordQuestion(index)">×</button></header>
                  <div v-if="question.source || question.purpose || question.follow_up" class="record-question-context">
                    <small v-if="question.source"><b>設計依據</b>{{ question.source }}</small>
                    <small v-if="question.purpose"><b>提問目的</b>{{ question.purpose }}</small>
                    <small v-if="question.follow_up"><b>追問方向</b>{{ question.follow_up }}</small>
                  </div>
                  <div class="record-answer-grid">
                    <label class="wide">應徵者回答<textarea v-model="question.response" rows="3" maxlength="5000" placeholder="記錄具體案例、行動與結果…"></textarea></label>
                    <label>對應特質<input v-model="question.trait" maxlength="100" placeholder="例如：團隊合作"></label>
                    <template v-if="editorEvaluationVisible">
                      <label>單題評分<select v-model="question.rating"><option :value="null">未評分</option><option v-for="rating in 5" :key="rating" :value="rating">{{ rating }} 分</option></select></label>
                      <label class="wide">面試官觀察（評分區）<textarea v-model="question.notes" rows="2" maxlength="2000" placeholder="記錄非語言反應、待查證處或追問結果…"></textarea></label>
                    </template>
                    <div v-else class="evaluation-lock-inline"><span>🔒</span><p><strong>評分與面試官觀察尚未公開</strong><small>候選人回答可立即查看，評價內容於雙方提交後開放。</small></p></div>
                  </div>
                </article>
                <div v-if="!recordForm.questions.length" class="record-question-empty"><strong>還沒有問題</strong><p>從上方建議題庫加入，或按「自訂問題」開始紀錄。</p></div>
              </section>

              <div v-if="editorEvaluationVisible" class="record-conclusion">
                <label>面試總結<textarea v-model="recordForm.summary" rows="5" maxlength="5000" placeholder="摘要主要優勢、風險、待確認事項與共識…"></textarea></label>
                <label>錄用建議<select v-model="recordForm.recommendation"><option :value="null">尚未決定</option><option v-for="(label, value) in recommendationLabels" :key="value" :value="value">{{ label }}</option></select></label>
              </div>
              <div v-else class="record-conclusion-locked"><span>🔒</span><div><strong>面試總結與錄用建議尚未公開</strong><p>雙方完成各自評估前，不會互相影響判斷。</p></div></div>

              <section v-if="recordForm.stage === 'hr' && (canEditStage('hr') || editingRecord?.private_notes_visible)" class="hr-private-notes">
                <header><span>HR ONLY</span><div><strong>HR 限定敏感備註</strong><small>此區內容不會出現在主管的畫面或 API 回應中。</small></div></header>
                <label>私密備註<textarea v-model="recordForm.private_notes" rows="4" maxlength="10000" placeholder="例如：薪資個資、合理調整需求或其他僅限 HR 處理的敏感事項…"></textarea></label>
              </section>
            </fieldset>
            <footer><span>{{ editingRecord ? `建立者：${editingRecord.interviewer_name} · 更新：${formatDate(editingRecord.updated_at)}` : '儲存後會保留建立者、修改者與完整時間紀錄。' }}</span><div><button class="button secondary" type="button" :disabled="recordSaving" @click="cancelRecordEdit">關閉表單</button><button v-if="canEditStage(recordForm.stage)" class="button primary" data-testid="interview-record-save" :disabled="recordSaving">{{ recordSaving ? '儲存中…' : editingRecord ? '更新過程紀錄' : '建立過程紀錄' }}</button></div></footer>
          </form>
          <section v-else class="record-editor-empty"><span>記</span><strong>選擇既有紀錄或建立新紀錄</strong><p>建立後會先帶入所屬階段的 5 題，再依面試進度逐題填答。</p><button class="button primary" type="button" @click="newRecord()">建立面試紀錄</button></section>
        </main>
      </div>
    </section>
  </div>
</template>

<style scoped>
.interview-page{display:grid;gap:14px}.interview-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:25px 28px;border-radius:18px;background:linear-gradient(120deg,#153f3b,#17695f 62%,#74ad91);color:#fff;box-shadow:0 16px 38px rgba(20,74,68,.14)}.interview-hero p{margin:0;color:#f2c96d;font-size:8px;font-weight:800;letter-spacing:1.3px}.interview-hero h1{margin:6px 0;font-size:25px}.interview-hero span{font-size:10px;color:rgba(255,255,255,.76)}.interview-hero .button{background:rgba(255,255,255,.95)}.interview-alert{display:flex;align-items:center;gap:10px;padding:11px 14px;border:1px solid;border-radius:10px;font-size:9px}.interview-alert>strong{width:22px;height:22px;border-radius:50%;display:grid;place-items:center}.interview-alert>span{flex:1}.interview-alert>button{border:0;background:transparent;color:inherit;font-size:18px}.interview-alert.error{border-color:#efd0cd;background:#fff0ef;color:#893d39}.interview-alert.error>strong{background:#e5b0ac}.interview-alert.success{border-color:#baddc3;background:#ecf8ef;color:#286547}.interview-alert.success>strong{background:#cbe8d2}.interview-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.interview-metrics article{padding:16px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-metrics small,.interview-metrics span{display:block;color:var(--muted);font-size:8px}.interview-metrics strong{display:block;margin:4px 0;color:#185e56;font-size:23px}.interview-filters{display:flex;align-items:end;gap:12px;padding:13px 15px;border:1px solid var(--line);border-radius:12px;background:#fff}.interview-filters>div{margin-right:auto}.interview-filters>div strong,.interview-filters>div span{display:block}.interview-filters>div strong{font-size:11px}.interview-filters>div span{margin-top:3px;color:var(--muted);font-size:8px}.interview-filters label{display:grid;gap:5px;color:#61756f;font-size:8px}.interview-filters select{width:210px;height:37px;padding:0 10px;border:1px solid #d8e3df;border-radius:8px;background:#fff;color:#31534d;font-size:9px}.interview-filters em{padding-bottom:10px;color:var(--muted);font-size:8px;font-style:normal}.interview-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.interview-card{min-width:0;padding:16px}.interview-card>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.candidate-identity{display:flex;align-items:center;gap:10px;min-width:0}.candidate-identity>span{width:40px;height:40px;flex:0 0 auto;border-radius:50%;display:grid;place-items:center;background:#dceee8;color:#1f6b61;font-weight:800}.candidate-identity h2{margin:0;font-size:13px}.candidate-identity p{margin:3px 0 0;color:var(--muted);font-size:8px}.application-status{padding:4px 8px;border-radius:99px;background:#edf2f0;color:#60736e;font-size:8px;white-space:nowrap}.application-status[data-status="interview"],.application-status[data-status="interviewing"]{background:#e3eff9;color:#326f9d}.application-status[data-status="offered"],.application-status[data-status="hired"]{background:#e1f2e9;color:#27725b}.application-status[data-status="rejected"],.application-status[data-status="withdrawn"]{background:#f8e7e5;color:#a64b46}.application-job{display:grid;gap:3px;margin:14px 0;padding:11px;border-radius:9px;background:#f3f8f6}.application-job small{color:#2c786c;font-size:8px;font-weight:700}.application-job strong{font-size:10px}.application-job span{color:var(--muted);font-size:8px}.application-details{display:grid;grid-template-columns:1fr 1fr;gap:7px}.application-details>div{min-width:0;padding:8px;border:1px solid #e8eeec;border-radius:7px}.application-details small,.application-details strong{display:block;font-size:7px}.application-details small{color:var(--muted)}.application-details strong{margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:8px}.schedule-summary{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:11px;padding:11px 12px;border:1px solid #cde5dc;border-radius:9px;background:#f0f9f5}.schedule-summary.unscheduled{border-style:dashed;background:#fafcfb}.schedule-summary>div{min-width:0}.schedule-summary small,.schedule-summary strong{display:block}.schedule-summary small{color:var(--muted);font-size:7px}.schedule-summary strong{margin-top:3px;color:#245f56;font-size:10px}.schedule-summary p{margin:4px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#71847f;font-size:8px}.schedule-summary .button{flex:0 0 auto}.interview-editor{margin-top:12px;border:1px solid #bcdcd2;border-radius:11px;background:#fbfdfc;overflow:hidden}.interview-editor>header{display:flex;align-items:flex-start;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #dce9e5}.interview-editor>header small{color:#b37c20;font-size:7px;font-weight:800;letter-spacing:1px}.interview-editor>header h3{margin:3px 0 0;font-size:11px}.interview-editor>header button{border:0;background:transparent;color:#61736f;font-size:19px}.editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px}.editor-grid label{display:grid;gap:5px;color:#536e68;font-size:8px}.editor-grid .wide{grid-column:1/-1}.editor-grid input,.editor-grid select,.editor-grid textarea{width:100%;padding:9px 10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit}.editor-grid textarea{resize:vertical;line-height:1.6}.interview-editor>footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 14px;border-top:1px solid #dce9e5;background:#f5f9f7}.interview-editor>footer>span{color:var(--muted);font-size:7px}.interview-editor>footer>div{display:flex;gap:7px}.interview-empty{text-align:center;padding:60px 20px;color:var(--muted)}.interview-empty strong,.interview-empty p{display:block}.interview-empty strong{font-size:11px}.interview-empty p{font-size:8px}.interview-empty .spinner{margin-bottom:12px}
.stage-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:11px}.interview-stage{min-width:0;border:1px solid #cde5dc;border-radius:10px;background:#f0f9f5;overflow:hidden}.interview-stage.unscheduled{border-style:dashed;background:#fafcfb}.interview-stage>header{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;padding:10px 11px;border-bottom:1px solid #dce9e5}.interview-stage>header small{display:block;color:#b37c20;font-size:6px;font-weight:800;letter-spacing:.8px}.interview-stage>header h3{margin:3px 0 0;font-size:9px}.interview-stage>header>span{padding:3px 6px;border-radius:99px;background:#fff;color:#28675d;font-size:7px;white-space:nowrap}.stage-content{display:grid;gap:3px;padding:10px 11px}.stage-content small{margin-top:4px;color:var(--muted);font-size:7px}.stage-content strong{color:#245f56;font-size:9px}.stage-content p{min-height:32px;margin:1px 0 0;color:#5f746f;font-size:8px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}.stage-content p.structured-record-locked{padding:7px 8px;border:1px dashed #dfc994;border-radius:6px;background:#fffaf0;color:#876323}.interview-stage>footer{display:flex;align-items:center;justify-content:flex-end;min-height:43px;padding:8px 10px;border-top:1px solid #dce9e5;background:rgba(255,255,255,.5)}.interview-stage>footer>span{margin-right:auto;color:var(--muted);font-size:7px}.interview-stage .interview-editor{margin:0;border-width:1px 0 0;border-radius:0}.interview-stage .interview-editor>footer{min-height:0;background:#f5f9f7}
.record-workspace-entry{display:flex;align-items:center;gap:13px;margin-top:11px;padding:11px 12px;border:1px solid #d7e4e0;border-radius:9px;background:linear-gradient(110deg,#f5faf8,#fffaf1)}.record-workspace-entry>div{flex:1}.record-workspace-entry strong,.record-workspace-entry span{display:block}.record-workspace-entry strong{font-size:10px;color:#315f57}.record-workspace-entry span{margin-top:3px;color:#6a7d78;font-size:8px;line-height:1.5}.record-workspace-overlay{position:fixed;z-index:180;inset:0;display:grid;place-items:center;padding:18px;background:rgba(12,35,32,.58);backdrop-filter:blur(5px)}.record-workspace{width:min(1480px,100%);height:calc(100dvh - 36px);display:flex;flex-direction:column;overflow:hidden;border:1px solid rgba(255,255,255,.45);border-radius:18px;background:#f3f7f5;box-shadow:0 28px 80px rgba(5,31,27,.3)}.record-workspace-header{flex:0 0 auto;display:flex;align-items:center;justify-content:space-between;gap:18px;padding:17px 21px;background:linear-gradient(110deg,#133f3a,#176f64);color:#fff}.workspace-person{display:flex;align-items:center;gap:12px}.workspace-person>span{width:43px;height:43px;display:grid;place-items:center;border-radius:50%;background:rgba(255,255,255,.16);font-size:17px;font-weight:800}.workspace-person small{color:#f1cb75;font-size:9px;font-weight:800;letter-spacing:1px}.workspace-person h2{margin:3px 0;font-size:18px}.workspace-person p{margin:0;color:rgba(255,255,255,.75);font-size:11px}.record-workspace-header>button{width:38px;height:38px;border:1px solid rgba(255,255,255,.22);border-radius:50%;background:rgba(255,255,255,.08);color:#fff;font-size:24px}.workspace-message{flex:0 0 auto;display:flex;align-items:center;gap:8px;padding:9px 14px;border-bottom:1px solid;font-size:11px}.workspace-message>span{flex:1}.workspace-message>button{border:0;background:transparent;color:inherit;font-size:18px}.workspace-message.error{border-color:#eac6c2;background:#fff0ef;color:#8e403b}.workspace-message.success{border-color:#c7dfcf;background:#edf8f1;color:#2d674a}.record-workspace-body{min-height:0;flex:1;display:grid;grid-template-columns:280px minmax(0,1fr)}.record-history{min-height:0;overflow:auto;border-right:1px solid #dbe6e2;background:#fff}.record-history>header{position:sticky;z-index:1;top:0;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:13px;border-bottom:1px solid #e0e9e6;background:rgba(255,255,255,.96)}.record-history>header strong,.record-history>header span{display:block}.record-history>header strong{font-size:12px}.record-history>header span{margin-top:2px;color:#748580;font-size:9px}.workspace-loading{display:flex;align-items:center;gap:8px;padding:24px 14px;color:#6d807a;font-size:10px}.record-history-item{position:relative;width:100%;display:grid;gap:4px;padding:13px 14px;border:0;border-bottom:1px solid #e9efed;background:#fff;color:#34554f;text-align:left}.record-history-item:hover,.record-history-item.active{background:#eef8f5}.record-history-item.active:before{content:"";position:absolute;inset:8px auto 8px 0;width:4px;border-radius:0 4px 4px 0;background:#218174}.record-history-item strong{font-size:10px}.record-history-item small{color:#71827d;font-size:8px}.record-history-item em{justify-self:end;color:#31786d;font-size:8px;font-style:normal}.record-status{justify-self:start;padding:3px 6px;border-radius:99px;background:#e8f3ef;color:#2b7365;font-size:8px}.record-status[data-status="planned"]{background:#e8f0f8;color:#326c99}.record-status[data-status="cancelled"],.record-status[data-status="no_show"]{background:#f7e9e7;color:#a04f49}.record-history-empty{padding:35px 20px;text-align:center;color:#758681}.record-history-empty strong{font-size:11px}.record-history-empty p{font-size:9px;line-height:1.6}.record-workspace-main{min-height:0;overflow:auto;padding:15px}.question-builder,.record-editor,.record-editor-empty{border:1px solid #d8e5e1;border-radius:12px;background:#fff;box-shadow:0 5px 18px rgba(24,74,65,.05)}.question-builder{padding:16px;margin-bottom:14px}.question-builder>header{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.question-builder>header small{color:#ae761d;font-size:8px;font-weight:800;letter-spacing:1px}.question-builder>header h3{margin:3px 0;font-size:13px}.question-builder>header p{margin:0;color:#6b7e79;font-size:9px;line-height:1.55}.question-builder>header>span{padding:5px 8px;border-radius:99px;background:#eef5f3;color:#50716a;font-size:9px;white-space:nowrap}.trait-picker,.selected-custom-traits{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.trait-picker button,.selected-custom-traits button{padding:6px 9px;border:1px solid #d6e3df;border-radius:99px;background:#fff;color:#516d67;font-size:9px}.trait-picker button.selected{border-color:#2c897b;background:#e4f4ef;color:#1d6e62;font-weight:700}.selected-custom-traits button{border-color:#d6c590;background:#fff9e9;color:#79602b}.custom-trait{display:flex;gap:7px;margin-top:10px}.custom-trait input{min-width:0;flex:1;height:36px;padding:0 10px;border:1px solid #d5e2de;border-radius:8px}.generate-questions{margin-top:11px}.question-guidance{margin:13px 0 0;padding:10px 12px;border-left:3px solid #d5a74c;border-radius:7px;background:#fff9eb;color:#735c33;font-size:9px;line-height:1.6}.suggestion-groups{display:grid;gap:9px;margin-top:11px}.suggestion-groups>article{overflow:hidden;border:1px solid #dce7e3;border-radius:9px}.suggestion-groups>article>header{display:flex;justify-content:space-between;gap:10px;padding:8px 11px;background:#f2f7f5}.suggestion-groups>article>header strong{font-size:10px;color:#2d6d62}.suggestion-groups>article>header span{color:#758681;font-size:8px}.suggested-question{display:flex;align-items:flex-start;gap:12px;padding:11px;border-top:1px solid #e5ece9}.suggested-question:first-of-type{border-top:0}.suggested-question>div{min-width:0;flex:1}.suggested-question>div>strong{display:block;font-size:10px;line-height:1.5}.suggested-question p{margin:5px 0 0;color:#667b75;font-size:8px;line-height:1.55}.suggested-question p b{margin-right:5px;color:#397268}.suggested-question>.button{flex:0 0 auto}.record-editor>header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid #e0e9e6}.record-editor>header small{color:#ad761f;font-size:8px;font-weight:800;letter-spacing:1px}.record-editor>header h3{margin:3px 0;font-size:13px}.record-editor>header p{margin:0;color:#70817d;font-size:9px}.read-only-badge{padding:5px 8px;border-radius:99px;background:#eef2f1;color:#667873;font-size:9px}.record-editor fieldset{margin:0;padding:0;border:0}.record-meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:15px 16px}.record-meta-grid label,.record-conclusion label,.record-answer-grid label,.record-question-card>header label{display:grid;gap:5px;color:#536e68;font-size:9px}.record-meta-grid input,.record-meta-grid select,.record-conclusion select,.record-conclusion textarea,.record-answer-grid input,.record-answer-grid select,.record-answer-grid textarea,.record-question-card>header input{width:100%;padding:9px 10px;border:1px solid #d5e2de;border-radius:7px;background:#fff;color:#284a44;font:inherit}.record-question-section{padding:0 16px 15px}.record-question-section>header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid #e1e9e6}.record-question-section>header strong,.record-question-section>header span{display:block}.record-question-section>header strong{font-size:11px}.record-question-section>header span{margin-top:3px;color:#748580;font-size:8px}.record-question-card{overflow:hidden;margin-bottom:9px;border:1px solid #dbe6e2;border-radius:9px;background:#fbfdfc}.record-question-card>header{display:grid;grid-template-columns:29px minmax(0,1fr) 28px;align-items:end;gap:8px;padding:10px;border-bottom:1px solid #e2ebe8}.record-question-card>header>span{width:28px;height:28px;display:grid;place-items:center;border-radius:50%;background:#dff0eb;color:#226e63;font-size:10px;font-weight:800}.record-question-card>header>button{height:29px;border:0;background:transparent;color:#a05b54;font-size:18px}.record-answer-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:10px}.record-answer-grid .wide{grid-column:1/-1}.record-answer-grid textarea,.record-conclusion textarea{resize:vertical;line-height:1.55}.record-question-empty{padding:28px;border:1px dashed #cfded9;border-radius:9px;text-align:center;color:#768782}.record-question-empty strong{font-size:10px}.record-question-empty p{margin:4px 0 0;font-size:8px}.record-conclusion{display:grid;grid-template-columns:minmax(0,2fr) minmax(180px,1fr);align-items:start;gap:10px;padding:0 16px 16px}.record-editor>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-top:1px solid #dde7e3;background:#f5f9f7}.record-editor>footer>span{color:#71837e;font-size:8px}.record-editor>footer>div{display:flex;gap:7px}.record-editor-empty{min-height:280px;display:grid;place-content:center;justify-items:center;padding:35px;text-align:center;color:#748681}.record-editor-empty>span{width:47px;height:47px;display:grid;place-items:center;border-radius:50%;background:#e3f1ed;color:#267267;font-size:16px;font-weight:800}.record-editor-empty strong{margin-top:12px;color:#395d56;font-size:12px}.record-editor-empty p{margin:5px 0 13px;font-size:9px}
.question-progress{overflow:hidden;margin-top:12px;border:1px solid #cfdfda;border-radius:12px;background:#fff}.question-progress>header{display:flex;align-items:center;gap:14px;padding:13px 14px;border-bottom:1px solid #dce8e4;background:linear-gradient(110deg,#eef8f5,#fffaf0)}.question-progress>header>div:first-child{min-width:0;flex:1}.question-progress>header small,.question-progress>header strong,.question-progress>header span{display:block}.question-progress>header>div:first-child>small{color:#ad761f;font-size:7px;font-weight:800;letter-spacing:1px}.question-progress>header>div:first-child>strong{margin-top:3px;color:#244f48;font-size:12px}.question-progress>header>div:first-child>span{margin-top:4px;color:#667a75;font-size:8px;line-height:1.5}.question-stage-tabs{display:grid;grid-template-columns:1fr 1fr;gap:6px;flex:0 0 190px}.question-stage-tabs button{display:grid;grid-template-columns:1fr auto;align-items:center;gap:1px 6px;padding:7px 9px;border:1px solid #d4e2de;border-radius:8px;background:#fff;color:#5b706b;text-align:left}.question-stage-tabs button small{grid-row:1;color:inherit;font-size:7px;font-weight:700}.question-stage-tabs button strong{grid-area:1/2/3/3;color:#1e665b;font-size:13px}.question-stage-tabs button span{grid-row:2;color:#82918d;font-size:6px}.question-stage-tabs button.active{border-color:#278477;background:#e7f5f1;color:#1e665b;box-shadow:0 0 0 2px rgba(39,132,119,.08)}.question-plan-meta{display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid #e6eeeb}.question-plan-meta>span{padding:4px 7px;border-radius:99px;background:#e7f3ef;color:#216d61;font-size:7px;font-weight:700}.question-plan-meta>span[data-stage="manager"]{background:#fff3d8;color:#8a621a}.question-plan-meta>small{margin-left:auto;color:#798984;font-size:7px}.question-preview-list{display:grid;gap:0;margin:0;padding:0;list-style:none}.question-preview-list li{display:grid;grid-template-columns:25px minmax(0,1fr);gap:9px;padding:10px 12px;border-bottom:1px solid #edf1f0}.question-preview-list li>span{width:23px;height:23px;display:grid;place-items:center;border-radius:50%;background:#edf2f0;color:#6d7d79;font-size:8px;font-weight:800}.question-preview-list li.answered>span{background:#2a8879;color:#fff}.question-preview-list li>div{min-width:0}.question-preview-list li small{color:#987022;font-size:6px}.question-preview-list li strong{display:block;margin-top:2px;color:#2b4f49;font-size:9px;line-height:1.5}.question-preview-list li p{margin:5px 0 0;padding:6px 8px;border-left:2px solid #72ad9f;border-radius:0 5px 5px 0;background:#f3f9f7;color:#42645e;font-size:8px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}.question-preview-list li p.empty{border-left-color:#d7dfdd;background:#f8faf9;color:#8a9693;font-style:italic}.question-preview-list li em{display:inline-block;margin-top:4px;color:#267367;font-size:7px;font-style:normal;font-weight:700}.question-progress>footer{display:flex;align-items:center;gap:10px;padding:10px 12px;background:#f8faf9}.question-progress>footer>span{min-width:0;flex:1;color:#6f817c;font-size:7px;line-height:1.45}.question-progress-loading,.question-preview-error{display:flex;align-items:center;justify-content:center;gap:8px;min-height:90px;padding:20px;color:#748681;font-size:9px}.question-preview-error{color:#96524c}.record-question-context{display:grid;gap:4px;padding:9px 11px;border-bottom:1px solid #e2ebe8;background:#f5f9f7}.record-question-context small{color:#617771;font-size:8px;line-height:1.5}.record-question-context b{margin-right:7px;color:#2f7065}
.question-personalization-basis{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin-top:10px;padding:9px 10px;border:1px solid #d7e7e2;border-radius:8px;background:#f3f9f7}.question-personalization-basis strong{margin-right:3px;color:#315f57;font-size:8px}.question-personalization-basis span{padding:4px 7px;border-radius:99px;background:#fff;color:#527069;font-size:7px}.suggested-question .question-source{display:block;margin-bottom:5px;color:#a16e18;font-size:7px;font-weight:700}
.interview-sharing-policy{flex:0 0 auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;padding:10px 14px;border-bottom:1px solid #d8e5e1;background:#f8fbfa}.interview-sharing-policy>div{display:flex;align-items:center;gap:9px;padding:9px 11px;border:1px solid #dbe7e3;border-radius:9px;background:#fff}.interview-sharing-policy>div>span{width:30px;height:30px;flex:0 0 auto;display:grid;place-items:center;border-radius:50%;background:#e2f2ed;color:#216f63;font-size:9px;font-weight:800}.interview-sharing-policy p,.evaluation-lock-notice p,.evaluation-lock-inline p,.record-conclusion-locked p{margin:0}.interview-sharing-policy strong,.interview-sharing-policy small{display:block}.interview-sharing-policy strong{color:#315a53;font-size:9px}.interview-sharing-policy small{margin-top:2px;color:#71817d;font-size:7px;line-height:1.45}.evaluation-release-chip{padding:4px 7px;border-radius:99px;background:#fff0df;color:#93601c;font-size:7px;font-weight:700}.evaluation-release-chip.unlocked{background:#e1f3e9;color:#257052}.question-preview-list li em.evaluation-locked{color:#8a641f;font-weight:600}.history-visibility{justify-self:start;padding:3px 6px;border-radius:99px;background:#fff1dc!important;color:#8a601b!important}.history-visibility.unlocked{background:#e3f3ea!important;color:#267052!important}.evaluation-lock-notice{display:flex;align-items:flex-start;gap:10px;margin:13px 16px 0;padding:11px 12px;border:1px solid #ead7ad;border-radius:9px;background:#fff9eb;color:#765722}.evaluation-lock-notice>span{font-size:14px}.evaluation-lock-notice strong{display:block;font-size:10px}.evaluation-lock-notice p{margin-top:4px;font-size:8px;line-height:1.55}.locked-field{display:grid;gap:5px;color:#536e68;font-size:9px}.locked-field strong{min-height:36px;display:flex;align-items:center;padding:9px 10px;border:1px solid #e5d8ba;border-radius:7px;background:#fff9ec;color:#876323;font-size:8px}.evaluation-lock-inline{grid-column:1/-1;display:flex;align-items:center;gap:9px;padding:10px;border:1px dashed #dfc994;border-radius:8px;background:#fffaf0;color:#785b22}.evaluation-lock-inline strong,.evaluation-lock-inline small{display:block}.evaluation-lock-inline strong{font-size:9px}.evaluation-lock-inline small{margin-top:2px;font-size:7px}.record-conclusion-locked{display:flex;align-items:center;gap:10px;margin:0 16px 16px;padding:13px;border:1px dashed #dfc994;border-radius:9px;background:#fffaf0;color:#795c25}.record-conclusion-locked strong{display:block;font-size:10px}.record-conclusion-locked p{margin-top:3px;font-size:8px}.hr-private-notes{margin:0 16px 16px;padding:13px;border:1px solid #d3c6eb;border-radius:10px;background:#faf7ff}.hr-private-notes>header{display:flex;align-items:center;gap:10px;margin-bottom:10px}.hr-private-notes>header>span{padding:5px 7px;border-radius:6px;background:#6f5799;color:#fff;font-size:7px;font-weight:800;letter-spacing:.7px}.hr-private-notes>header strong,.hr-private-notes>header small{display:block}.hr-private-notes>header strong{color:#54416f;font-size:10px}.hr-private-notes>header small{margin-top:2px;color:#81728f;font-size:7px}.hr-private-notes label{display:grid;gap:5px;color:#665577;font-size:9px}.hr-private-notes textarea{width:100%;padding:10px;border:1px solid #d8cee7;border-radius:8px;background:#fff;color:#453952;font:inherit;line-height:1.55;resize:vertical}
@media(max-width:1120px){.interview-list{grid-template-columns:1fr}.interview-filters{align-items:stretch;flex-wrap:wrap}.interview-filters>div{flex-basis:100%}.interview-filters label{flex:1}.interview-filters select{width:100%}}
@media(max-width:900px){.interview-sharing-policy{grid-template-columns:1fr}.record-workspace-body{grid-template-columns:1fr}.record-history{max-height:210px;border-right:0;border-bottom:1px solid #dbe6e2}.record-history>header{position:static}.record-meta-grid{grid-template-columns:1fr 1fr}}
@media(max-width:680px){.interview-hero{align-items:flex-start;flex-direction:column}.interview-metrics,.stage-grid{grid-template-columns:1fr}.interview-filters label{flex-basis:100%}.application-details,.editor-grid{grid-template-columns:1fr}.editor-grid .wide{grid-column:auto}.schedule-summary,.interview-editor>footer,.record-workspace-entry,.record-editor>footer,.question-progress>header,.question-progress>footer{align-items:flex-start;flex-direction:column}.interview-editor>footer>div,.record-workspace-entry .button,.record-editor>footer>div,.question-stage-tabs,.question-progress>footer .button{width:100%}.question-stage-tabs{flex-basis:auto}.interview-editor>footer .button,.record-editor>footer .button{flex:1}.record-workspace-overlay{padding:0}.record-workspace{height:100dvh;border-radius:0}.record-workspace-header{padding:13px}.workspace-person>span{display:none}.workspace-person h2{font-size:15px}.record-workspace-main{padding:10px}.record-meta-grid,.record-answer-grid,.record-conclusion{grid-template-columns:1fr}.record-answer-grid .wide{grid-column:auto}.suggested-question{flex-direction:column}.suggested-question>.button{width:100%}.record-conclusion{padding-top:0}}
</style>
