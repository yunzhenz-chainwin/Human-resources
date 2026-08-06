<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import {
  candidateAnalysisApi,
  type AnalysisEnvelope,
  type DeidentifiedResumeDocument,
  type MatchComponent,
  type RecommendedRolesAnalysis,
  type RoleMatchAnalysis,
  type RoleMatchItem,
} from '../services/candidateAnalysisApi'
import {
  hrApi,
  type ApplicationDto,
  type CandidateDto,
  type CandidateResumeSummaryDto,
  type CompositeScoreComponent,
  type CompositeScoreComponentDetailDto,
  type CompositeScoreStageDetailDto,
  type InterviewRecordDto,
  type InterviewStage,
  type RequisitionDto,
} from '../services/hrApi'
import { matchingReportsApi } from '../services/matchingReportsApi'

type AnalysisRole = 'it' | 'hr' | 'admin' | 'manager'
type PreviewTarget =
  | { kind: 'original'; id: number; filename: string }
  | { kind: 'deidentified'; id: number; filename: string }
// `masked` is blind review hiding the other side; it is deliberately distinct from
// `unscored` (nobody scored) and `unavailable` (no such score exists at all).
type ScoreFigureState = 'scored' | 'masked' | 'pending' | 'unscored' | 'unavailable'
type ScoreFigure = {
  key: string
  index: string
  label: string
  source: string
  badge: string
  value: number | null
  state: ScoreFigureState
  note: string
}

const props = withDefaults(defineProps<{
  candidate: Pick<CandidateDto, 'id' | 'code' | 'name'>
  resumes?: CandidateResumeSummaryDto[]
  jobs?: RequisitionDto[]
  role: AnalysisRole
  defaultRequisitionId?: number | null
  autoExpandFirstDocument?: boolean
}>(), {
  resumes: () => [],
  jobs: () => [],
  defaultRequisitionId: null,
  autoExpandFirstDocument: false,
})

const emit = defineEmits<{
  (event: 'open-parsed-resume', resumeId: number): void
}>()

const RESULT_TTL_MS = 15 * 60 * 1000
const documents = ref<DeidentifiedResumeDocument[]>([])
const documentLoading = ref(false)
const documentError = ref('')
const actionError = ref('')
const actionNotice = ref('')
const workingDocumentKey = ref('')
const uploadInputRef = ref<HTMLInputElement | null>(null)
const uploadTargetResumeId = ref<number | null>(null)
const expandedDocumentKey = ref<string | null>(null)
const selectedRequisitionId = ref<number | null>(null)
const selectedSourceResumeId = ref<number | null>(null)
const recommendedResult = ref<RecommendedRolesAnalysis | null>(null)
const roleMatchResult = ref<RoleMatchAnalysis | null>(null)
const recommendedLoading = ref(false)
const roleMatchLoading = ref(false)
const analysisError = ref('')
const expandedRecommendedId = ref<number | null>(null)
const roleMatchExpanded = ref(false)
const previewTarget = ref<PreviewTarget | null>(null)
const previewUrl = ref('')
const previewIsPdf = ref(false)
const previewLoadingKey = ref('')
const previewError = ref('')
const scoreApplication = ref<ApplicationDto | null>(null)
const scoreRecords = ref<InterviewRecordDto[]>([])
const resumeMatchScore = ref<number | null>(null)
const resumeMatchUnreadable = ref(false)
const recordsUnreadable = ref(false)
const scoresLoading = ref(false)
const scoresError = ref('')

let documentLoadSequence = 0
let scoreLoadSequence = 0
let resultExpiryTimer: number | null = null

const canManageDocuments = computed(() => props.role === 'hr' || props.role === 'admin')
const candidateId = computed(() => props.candidate.id)
const originalRows = computed(() => canManageDocuments.value ? props.resumes : [])
const visibleDocuments = computed(() => {
  const allowed = props.role === 'manager'
    ? documents.value.filter(item => item.validation_status === 'analysis_ready')
    : documents.value
  return [...allowed].sort(compareDocumentRecency)
})
const analysisReadyDocument = computed(() => visibleDocuments.value.find(
  item => item.validation_status === 'analysis_ready',
) || null)
const currentDocument = computed(() => visibleDocuments.value[0] || null)
const selectedSourceResume = computed(() => originalRows.value.find(
  resume => resume.id === selectedSourceResumeId.value,
) || originalRows.value.find(resume => resume.has_file) || originalRows.value[0] || null)
const preparationStep = computed<1 | 2 | 3>(() => {
  if (analysisReadyDocument.value) return 3
  if (currentDocument.value) return 2
  return 1
})
const analysisJobs = computed(() => props.jobs.filter(job => ['approved', 'sourcing', 'interviewing'].includes(job.status)))
const analysisBusy = computed(() => recommendedLoading.value || roleMatchLoading.value)
const hasDocumentRows = computed(() => originalRows.value.length > 0 || visibleDocuments.value.length > 0)
const latestDocumentByResumeId = computed(() => {
  const result = new Map<number, DeidentifiedResumeDocument>()
  visibleDocuments.value.forEach((document) => {
    if (!result.has(document.source_resume_id)) result.set(document.source_resume_id, document)
  })
  return result
})

const statusLabels: Record<string, string> = {
  processing: '處理中',
  review_required: '待 HR 確認',
  analysis_ready: '可供分析',
  superseded: '已被新版取代',
  failed: '處理失敗',
  stale: '來源已更新',
}

const stageLabels: Record<InterviewStage, string> = { hr: 'HR', manager: '主管' }
const compositeComponentOrder: CompositeScoreComponent[] = [
  'resume', 'hr_questions', 'hr_overall', 'manager_questions', 'manager_overall',
]
const compositeComponentLabels: Record<CompositeScoreComponent, string> = {
  resume: '① 履歷條件匹配',
  hr_questions: '② HR 題目評分',
  hr_overall: '③ HR 面試總分',
  manager_questions: '④ 主管題目評分',
  manager_overall: '⑤ 主管面試總分',
}
// Wording follows the backend's excluded_reason values; a component that was left
// out must say why, otherwise the reweighting below it looks arbitrary.
const compositeExclusionLabels: Record<NonNullable<CompositeScoreComponentDetailDto['excluded_reason']>, string> = {
  no_match_result: '沒有履歷媒合結果，權重已分攤給其餘項目',
  no_rated_questions: '沒有已評分題目（未詢問不計分），權重併入同一關的面試總分',
  no_overall_score: '面試官未填寫面試總分，權重併入同一關的題目評分',
}

function compareDocumentRecency(left: DeidentifiedResumeDocument, right: DeidentifiedResumeDocument) {
  const leftTime = Date.parse(left.reviewed_at || left.created_at)
  const rightTime = Date.parse(right.reviewed_at || right.created_at)
  if (rightTime !== leftTime) return rightTime - leftTime
  if (left.source_resume_id === right.source_resume_id && right.version !== left.version) {
    return right.version - left.version
  }
  return right.id - left.id
}

function errorMessage(cause: unknown, fallback: string) {
  return cause instanceof Error ? cause.message : fallback
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('zh-TW', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(parsed)
}

function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${Math.round(value * 10) / 10}%`
}

function formatRatio(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const percentage = value >= 0 && value <= 1 ? value * 100 : value
  return `${Math.round(percentage * 10) / 10}%`
}

// All six stored scores share the 0-100 scale, so they share one unit here too.
function formatPoints(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${Math.round(value * 10) / 10} 分`
}

function confidenceLabel(value: RoleMatchItem['confidence']) {
  return { high: '高', medium: '中', low: '低' }[value] || value
}

function totalTokens(envelope: AnalysisEnvelope | null) {
  return envelope?.token_usage || 0
}

function tokenLabel(envelope: AnalysisEnvelope | null) {
  if (!envelope?.ai_used) return '0 Token（本機規則）'
  return `${new Intl.NumberFormat('zh-TW').format(totalTokens(envelope))} Token`
}

function validationSummaryText(document: DeidentifiedResumeDocument) {
  const summary = document.validation_summary
  if (summary.blocker_count > 0) return `仍有 ${summary.blocker_count} 項阻擋問題，不能進入分析。`
  if (document.validation_status === 'review_required') return '自動檢查已完成，請由 HR 預覽後確認。'
  if (document.validation_status === 'analysis_ready') return '已通過 HR 確認，可供按需分析。'
  if (document.validation_status === 'processing') return '正在檢查上傳的去識別化內容。'
  if (document.validation_status === 'stale') return document.stale_reason || '原始履歷已更新，請重新上傳去識別化版本。'
  if (document.validation_status === 'failed') return '檔案驗證失敗，請檢查後重新上傳。'
  return '此版本不再作為目前的分析來源。'
}

function normalizedComponents(item: RoleMatchItem): MatchComponent[] {
  return Array.isArray(item.components) ? item.components : []
}

function clearResultExpiryTimer() {
  if (resultExpiryTimer !== null) window.clearTimeout(resultExpiryTimer)
  resultExpiryTimer = null
}

function clearAnalysisResults() {
  clearResultExpiryTimer()
  recommendedResult.value = null
  roleMatchResult.value = null
  analysisError.value = ''
  expandedRecommendedId.value = null
  roleMatchExpanded.value = false
}

function scheduleResultExpiry() {
  clearResultExpiryTimer()
  resultExpiryTimer = window.setTimeout(clearAnalysisResults, RESULT_TTL_MS)
}

function closePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewTarget.value = null
  previewUrl.value = ''
  previewIsPdf.value = false
  previewError.value = ''
}

function resetForCandidate() {
  documentLoadSequence += 1
  documents.value = []
  documentError.value = ''
  actionError.value = ''
  actionNotice.value = ''
  workingDocumentKey.value = ''
  expandedDocumentKey.value = null
  selectedRequisitionId.value = null
  selectedSourceResumeId.value = props.resumes.find(resume => resume.has_file)?.id || props.resumes[0]?.id || null
  previewLoadingKey.value = ''
  closePreview()
  clearAnalysisResults()
  scoreLoadSequence += 1
  resetScores()
}

async function loadDocuments() {
  const requestedCandidateId = props.candidate.id
  const sequence = ++documentLoadSequence
  const previousReadyId = analysisReadyDocument.value?.id || null
  documentLoading.value = true
  documentError.value = ''
  try {
    const result = await candidateAnalysisApi.deidentificationsForCandidate(requestedCandidateId)
    if (sequence !== documentLoadSequence || requestedCandidateId !== props.candidate.id) return
    const permittedDocuments = props.role === 'manager'
      ? result.data.filter(item => item.validation_status === 'analysis_ready')
      : result.data
    documents.value = permittedDocuments
    if (props.autoExpandFirstDocument && expandedDocumentKey.value === null) {
      const newestDocument = [...permittedDocuments].sort(compareDocumentRecency)[0]
      expandedDocumentKey.value = newestDocument
        ? `deidentified-${newestDocument.id}`
        : props.resumes[0]
          ? `original-${props.resumes[0].id}`
          : null
    }
    const currentReady = permittedDocuments
      .filter(item => item.validation_status === 'analysis_ready')
      .sort(compareDocumentRecency)[0]?.id || null
    if (previousReadyId !== null && previousReadyId !== currentReady) clearAnalysisResults()
  } catch (cause) {
    if (sequence === documentLoadSequence) {
      documentError.value = errorMessage(cause, '無法載入去識別化履歷')
    }
  } finally {
    if (sequence === documentLoadSequence) documentLoading.value = false
  }
}

function toggleDocument(key: string) {
  expandedDocumentKey.value = expandedDocumentKey.value === key ? null : key
}

function promptUpload(resume: CandidateResumeSummaryDto) {
  uploadTargetResumeId.value = resume.id
  actionError.value = ''
  actionNotice.value = ''
  uploadInputRef.value?.click()
}

function promptUploadForSelected() {
  if (!selectedSourceResume.value) {
    actionError.value = '目前沒有可對應的原始履歷，請先完成履歷入庫。'
    return
  }
  promptUpload(selectedSourceResume.value)
}

async function onUploadFileSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const resumeId = uploadTargetResumeId.value
  uploadTargetResumeId.value = null
  if (!file || resumeId === null) return
  await uploadDeidentification(resumeId, file)
}

async function uploadDeidentification(resumeId: number, file: File) {
  const key = `upload-${resumeId}`
  workingDocumentKey.value = key
  actionError.value = ''
  actionNotice.value = ''
  clearAnalysisResults()
  try {
    const created = (await candidateAnalysisApi.uploadDeidentification(resumeId, file)).data
    actionNotice.value = `去識別化檔案 v${created.version} 已上傳並保存，請預覽內容確認無誤後再核准。`
    await loadDocuments()
    expandedDocumentKey.value = `deidentified-${created.id}`
  } catch (cause) {
    actionError.value = errorMessage(cause, '無法上傳去識別化檔案')
  } finally {
    workingDocumentKey.value = ''
  }
}

async function approveDocument(document: DeidentifiedResumeDocument) {
  workingDocumentKey.value = `approve-${document.id}`
  actionError.value = ''
  actionNotice.value = ''
  clearAnalysisResults()
  try {
    await candidateAnalysisApi.approveDeidentification(document.id)
    actionNotice.value = `去識別化履歷 v${document.version} 已核准，可開始職位分析。`
    await loadDocuments()
  } catch (cause) {
    actionError.value = errorMessage(cause, '無法核准去識別化履歷')
  } finally {
    workingDocumentKey.value = ''
  }
}

async function rejectDocument(document: DeidentifiedResumeDocument) {
  workingDocumentKey.value = `reject-${document.id}`
  actionError.value = ''
  actionNotice.value = ''
  clearAnalysisResults()
  try {
    await candidateAnalysisApi.rejectDeidentification(document.id)
    actionNotice.value = `去識別化履歷 v${document.version} 已退回。`
    await loadDocuments()
  } catch (cause) {
    actionError.value = errorMessage(cause, '無法退回去識別化履歷')
  } finally {
    workingDocumentKey.value = ''
  }
}

async function openPreview(target: PreviewTarget) {
  closePreview()
  const key = `${target.kind}-${target.id}`
  previewLoadingKey.value = key
  actionError.value = ''
  try {
    const blob = target.kind === 'original'
      ? await hrApi.previewResume(target.id)
      : await candidateAnalysisApi.previewDeidentifiedResume(target.id)
    previewUrl.value = URL.createObjectURL(blob)
    previewIsPdf.value = blob.type.toLowerCase().includes('pdf') || target.filename.toLowerCase().endsWith('.pdf')
    previewTarget.value = target
  } catch (cause) {
    actionError.value = errorMessage(cause, '無法預覽履歷')
  } finally {
    previewLoadingKey.value = ''
  }
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function downloadTarget(target: PreviewTarget) {
  const key = `download-${target.kind}-${target.id}`
  workingDocumentKey.value = key
  actionError.value = ''
  try {
    const blob = target.kind === 'original'
      ? await hrApi.downloadResume(target.id)
      : await candidateAnalysisApi.downloadDeidentifiedResume(target.id)
    saveBlob(blob, target.filename)
  } catch (cause) {
    actionError.value = errorMessage(cause, '無法下載履歷')
  } finally {
    workingDocumentKey.value = ''
  }
}

async function runRecommendedAnalysis() {
  if (!analysisReadyDocument.value) {
    analysisError.value = '尚無通過確認、可供分析的去識別化履歷。'
    return
  }
  recommendedLoading.value = true
  recommendedResult.value = null
  expandedRecommendedId.value = null
  analysisError.value = ''
  try {
    recommendedResult.value = (await candidateAnalysisApi.recommendRoles(analysisReadyDocument.value.id)).data
    scheduleResultExpiry()
  } catch (cause) {
    analysisError.value = errorMessage(cause, '無法完成適合職位推薦；系統不會自動重試。')
  } finally {
    recommendedLoading.value = false
  }
}

async function runRoleMatchAnalysis() {
  if (!analysisReadyDocument.value) {
    analysisError.value = '尚無通過確認、可供分析的去識別化履歷。'
    return
  }
  if (selectedRequisitionId.value === null) {
    analysisError.value = '請先選擇要評估的職位。'
    return
  }
  roleMatchLoading.value = true
  roleMatchResult.value = null
  roleMatchExpanded.value = false
  analysisError.value = ''
  try {
    roleMatchResult.value = (await candidateAnalysisApi.evaluateRoleMatch(
      analysisReadyDocument.value.id,
      { requisition_id: selectedRequisitionId.value },
    )).data
    scheduleResultExpiry()
  } catch (cause) {
    analysisError.value = errorMessage(cause, '無法完成指定職位評估；系統不會自動重試。')
  } finally {
    roleMatchLoading.value = false
  }
}

function validRating(value: number | null | undefined) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 5
}

// The backend stores overall_score as an integer 0-100; anything else is not a score.
function validScore(value: number | null | undefined) {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100
}

function stageRecord(stage: InterviewStage) {
  return scoreRecords.value.find(record => record.stage === stage) || null
}

function stageQuestionCounts(record: InterviewRecordDto) {
  const questions = record.questions || []
  return {
    total: questions.length,
    rated: questions.filter(question => validRating(question.rating)).length,
    notAsked: questions.filter(question => Boolean(question.not_asked_reason)).length,
  }
}

// Identical arithmetic to InterviewManagement.vue's stageQuestionScore and to the
// backend's interview_scoring.question_score: rated ratings over (rated count x 5),
// 未詢問 questions dropped from numerator and denominator alike, and null - never
// zero - when nothing is rated. A third variant that rounded differently would make
// the stored composite disagree with the stage scores rendered beside it.
function stageQuestionScore(stage: InterviewStage): number | null {
  const record = stageRecord(stage)
  if (!record) return null
  const rated = (record.questions || []).filter(question => validRating(question.rating))
  if (!rated.length) return null
  const total = rated.reduce((sum, question) => sum + Number(question.rating), 0)
  return Math.round((total / (rated.length * 5)) * 1000) / 10
}

// Blind review masks the other side's evaluation until both stages submit, and the
// masked fields arrive as null. A masked figure must therefore never be described as
// "尚未評分", and must never hint at whether the hidden number was high or low.
function interviewFigure(stage: InterviewStage, kind: 'questions' | 'overall'): Pick<ScoreFigure, 'value' | 'state' | 'note'> {
  const record = stageRecord(stage)
  const label = stageLabels[stage]
  if (recordsUnreadable.value) return { value: null, state: 'unavailable', note: '無法讀取面試評分紀錄，請重新整理後再試。' }
  if (!record) return { value: null, state: 'pending', note: `${label}尚未建立面試紀錄。` }
  if (!record.evaluation_revealed) {
    return { value: null, state: 'masked', note: '評分保護中：HR 與主管都提交後才會公開，此處不顯示任何分數線索。' }
  }
  const counts = stageQuestionCounts(record)
  const value = kind === 'questions'
    ? stageQuestionScore(stage)
    : validScore(record.overall_score) ? Number(record.overall_score) : null
  const draftSuffix = record.status === 'completed' ? '' : `（${label}尚未提交，為草稿評分）`
  if (value === null) {
    return kind === 'questions'
      ? { value: null, state: 'unscored', note: `${label}這一關沒有已評分的題目（共 ${counts.total} 題，未詢問 ${counts.notAsked} 題不計分），資料不足。` }
      : { value: null, state: 'unscored', note: `${label}尚未填寫面試總分。` }
  }
  return kind === 'questions'
    ? { value, state: 'scored', note: `已評分 ${counts.rated}／${counts.total} 題${counts.notAsked ? ` · 未詢問 ${counts.notAsked} 題不計分` : ''}${draftSuffix}` }
    : { value, state: 'scored', note: `由${label}面試官填寫的 0-100 總分${draftSuffix}` }
}

const canReadScores = computed(() => props.role === 'hr' || props.role === 'admin' || props.role === 'manager')
// Interview scores belong to an application (candidate x requisition), so the section
// only exists once this panel has a requisition in context.
const contextRequisitionId = computed(() => props.defaultRequisitionId ?? selectedRequisitionId.value)
const scoreRequisition = computed(() => (
  scoreApplication.value?.requisition
  || props.jobs.find(job => job.id === contextRequisitionId.value)
  || null
))
const scoreRequisitionLabel = computed(() => (
  scoreRequisition.value ? `${scoreRequisition.value.req_no} · ${scoreRequisition.value.title}` : '此職缺'
))
const compositeBreakdown = computed(() => scoreApplication.value?.composite_score_breakdown ?? null)
const computedBreakdown = computed(() => (
  compositeBreakdown.value?.status === 'computed' ? compositeBreakdown.value : null
))
const compositeScoreValue = computed(() => {
  const stored = scoreApplication.value?.composite_score
  if (typeof stored === 'number' && Number.isFinite(stored)) return stored
  const fromBreakdown = computedBreakdown.value?.composite_score
  return typeof fromBreakdown === 'number' && Number.isFinite(fromBreakdown) ? fromBreakdown : null
})
// The breakdown names the pending stages itself; falling back to the records keeps the
// message honest on a deployment whose stored breakdown predates this field.
const pendingStages = computed<InterviewStage[]>(() => {
  const breakdown = compositeBreakdown.value
  if (breakdown?.status === 'pending_stages' && Array.isArray(breakdown.pending_stages)) {
    return breakdown.pending_stages.filter(stage => stage === 'hr' || stage === 'manager')
  }
  return (['hr', 'manager'] as InterviewStage[]).filter(stage => stageRecord(stage)?.status !== 'completed')
})
// The stored breakdown decides, because it is what the composite was actually built
// from; the records are only consulted when no breakdown has been stored at all.
const compositeState = computed<'computed' | 'pending' | 'insufficient' | 'unavailable'>(() => {
  if (computedBreakdown.value) return compositeScoreValue.value === null ? 'insufficient' : 'computed'
  if (compositeBreakdown.value?.status === 'pending_stages') return 'pending'
  if (compositeScoreValue.value !== null) return 'computed'
  return pendingStages.value.length && !recordsUnreadable.value ? 'pending' : 'unavailable'
})
const compositeStateNote = computed(() => {
  if (compositeState.value === 'pending') {
    const waiting = pendingStages.value.map(stage => stageLabels[stage]).join('與') || '雙方'
    return `等待${waiting}提交面試評分。兩關都提交前不會產生綜合分，也不會顯示任何部分計算結果或對方的評分。`
  }
  if (compositeState.value === 'insufficient') return '兩關都已提交，但沒有任何一項分數可納入計算，資料不足。'
  if (compositeState.value === 'unavailable') return '尚無綜合分的計算紀錄；兩關評分提交後由系統計算並保存。'
  return ''
})
const compositeComponentRows = computed(() => {
  const breakdown = computedBreakdown.value
  if (!breakdown) return []
  return compositeComponentOrder
    .map(key => ({ key, label: compositeComponentLabels[key], detail: breakdown.components?.[key] || null }))
    .filter((row): row is { key: CompositeScoreComponent; label: string; detail: CompositeScoreComponentDetailDto } => row.detail !== null)
})
const compositeStageRows = computed(() => {
  const stages = computedBreakdown.value?.stages
  if (!stages) return []
  return (['hr', 'manager'] as InterviewStage[])
    .map(stage => ({ stage, label: stageLabels[stage], detail: stages[stage] || null }))
    .filter((row): row is { stage: InterviewStage; label: string; detail: CompositeScoreStageDetailDto } => row.detail !== null)
})
// Before a composite exists the breakdown carries no weights, but the requisition still
// says whether this job overrides them, so the line stays truthful in both states.
const compositeWeightSourceLabel = computed(() => (
  computedBreakdown.value?.configured_weights || scoreRequisition.value?.composite_score_weights
    ? '採用此職缺自訂的權重設定'
    : '採用系統預設權重'
))
// Same phrasing the interview card uses, so the two screens never disagree about who
// is still pending. It reports submission state only, never a score.
const evaluationReleaseHint = computed(() => {
  if (scoreRequisition.value?.blind_review_enabled === false) return '本職缺採即時共享評分'
  const hrDone = stageRecord('hr')?.status === 'completed'
  const managerDone = stageRecord('manager')?.status === 'completed'
  if (hrDone && managerDone) return '雙方已提交 · 評分已公開'
  if (hrDone) return 'HR 已提交 · 待主管提交後自動公開'
  if (managerDone) return '主管已提交 · 待 HR 提交後自動公開'
  return '雙方提交後自動公開評分'
})
const resumeFigure = computed<Pick<ScoreFigure, 'value' | 'state' | 'note'>>(() => {
  const fallback = computedBreakdown.value?.components?.resume?.value
  const value = resumeMatchScore.value !== null
    ? resumeMatchScore.value
    : typeof fallback === 'number' && Number.isFinite(fallback) ? fallback : null
  if (value !== null) return { value, state: 'scored', note: '此職缺的履歷媒合結果（職位條件匹配度）。' }
  if (resumeMatchUnreadable.value) return { value: null, state: 'unavailable', note: '無法讀取此職缺的媒合結果，請重新整理後再試。' }
  return { value: null, state: 'unavailable', note: '這位人才在此職缺沒有媒合結果（例如由人才庫手動加入），綜合分會將這項權重分攤給其餘項目。' }
})
const scoreFigures = computed<ScoreFigure[]>(() => [
  { key: 'resume', index: '①', label: '履歷條件匹配', source: '履歷媒合結果', badge: '', ...resumeFigure.value },
  { key: 'hr-questions', index: '②', label: 'HR 題目評分', source: 'HR 面試逐題評分換算', badge: '', ...interviewFigure('hr', 'questions') },
  { key: 'hr-overall', index: '③', label: 'HR 面試總分', source: 'HR 面試官填寫', badge: '', ...interviewFigure('hr', 'overall') },
  { key: 'manager-questions', index: '④', label: '主管題目評分', source: '主管面試逐題評分換算', badge: '', ...interviewFigure('manager', 'questions') },
  { key: 'manager-overall', index: '⑤', label: '主管面試總分', source: '主管面試官填寫', badge: '', ...interviewFigure('manager', 'overall') },
  {
    key: 'composite',
    index: '⑥',
    label: '綜合分',
    source: '由前五項加權計算並保存',
    badge: '參考值',
    value: compositeState.value === 'computed' ? compositeScoreValue.value : null,
    state: compositeState.value === 'computed' ? 'scored' : compositeState.value === 'pending' ? 'pending' : 'unavailable',
    note: compositeState.value === 'computed' ? '僅供排序與討論參考，不代表錄用結論。' : compositeStateNote.value,
  },
])
const showScoreSummary = computed(() => (
  canReadScores.value
  && contextRequisitionId.value !== null
  && (scoresLoading.value || Boolean(scoreApplication.value) || Boolean(scoresError.value))
))
// Scores are per candidate-per-requisition, so without a job in context there is
// nothing to show. Rendering nothing at all reads as "this feature is missing",
// so say what is needed instead of disappearing silently.
const scoreSummaryHint = computed(() => {
  if (!canReadScores.value) return ''
  if (contextRequisitionId.value === null) return '尚未選擇職缺。六項分數是「這位人才 × 這個職缺」的結果，請先於上方選擇要比對的職缺。'
  if (!scoresLoading.value && !scoreApplication.value && !scoresError.value) {
    return '這位人才尚未應徵此職缺，因此沒有面試與綜合分數。請改選其他職缺，或先於招募流程建立應徵紀錄。'
  }
  return ''
})

function figurePlaceholder(state: ScoreFigure['state']) {
  if (state === 'masked') return '評分保護中'
  if (state === 'pending') return '等待提交'
  if (state === 'unscored') return '尚未評分'
  return '資料不足'
}

function componentExclusionText(detail: CompositeScoreComponentDetailDto) {
  return detail.excluded_reason ? compositeExclusionLabels[detail.excluded_reason] : '資料不足，未納入計算'
}

function stageDetailText(detail: CompositeScoreStageDetailDto) {
  const parts = [`已評分 ${detail.rated_question_count}／${detail.question_count} 題`]
  if (detail.not_asked_question_count) parts.push(`未詢問 ${detail.not_asked_question_count} 題`)
  if (detail.submitted_at) parts.push(`提交於 ${formatDate(detail.submitted_at)}`)
  if (detail.revision_number) parts.push(`第 ${detail.revision_number} 次提交`)
  return parts.join(' · ')
}

function resetScores() {
  scoreApplication.value = null
  scoreRecords.value = []
  resumeMatchScore.value = null
  resumeMatchUnreadable.value = false
  recordsUnreadable.value = false
  scoresError.value = ''
  scoresLoading.value = false
}

// The three screens that mount this panel only hold a candidate and a requisition id,
// so the application - which carries composite_score - is resolved here rather than
// passed in. Every fetch is read-only; nothing here can move an application's status.
async function loadScores() {
  const requisitionId = contextRequisitionId.value
  const requestedCandidateId = props.candidate.id
  const sequence = ++scoreLoadSequence
  resetScores()
  if (!canReadScores.value || requisitionId === null) return
  scoresLoading.value = true
  try {
    const applications = (await hrApi.applications({ requisitionId })).data
    if (sequence !== scoreLoadSequence) return
    const application = applications.find(item => item.candidate_id === requestedCandidateId) || null
    scoreApplication.value = application
    if (!application) return
    const [records, matches] = await Promise.allSettled([
      hrApi.interviewRecords(application.id),
      matchingReportsApi.matches(requisitionId, true),
    ])
    if (sequence !== scoreLoadSequence) return
    if (records.status === 'fulfilled') {
      scoreRecords.value = records.value.data
    } else {
      recordsUnreadable.value = true
      scoresError.value = errorMessage(records.reason, '無法載入面試評分紀錄')
    }
    if (matches.status === 'fulfilled') {
      const match = matches.value.items.find(item => item.candidate_id === requestedCandidateId)
      resumeMatchScore.value = match && Number.isFinite(match.total_score) ? match.total_score : null
    } else {
      resumeMatchUnreadable.value = true
    }
  } catch (cause) {
    if (sequence === scoreLoadSequence) scoresError.value = errorMessage(cause, '無法載入分數總覽')
  } finally {
    if (sequence === scoreLoadSequence) scoresLoading.value = false
  }
}

function selectDefaultRequisition() {
  if (props.defaultRequisitionId !== null && analysisJobs.value.some(job => job.id === props.defaultRequisitionId)) {
    selectedRequisitionId.value = props.defaultRequisitionId
  } else if (!analysisJobs.value.some(job => job.id === selectedRequisitionId.value)) {
    selectedRequisitionId.value = null
  }
}

watch(() => props.candidate.id, () => {
  resetForCandidate()
  selectDefaultRequisition()
  void loadDocuments()
}, { immediate: true })

watch(() => props.resumes.map(resume => `${resume.id}:${resume.has_file}`).join(','), () => {
  if (!props.resumes.some(resume => resume.id === selectedSourceResumeId.value)) {
    selectedSourceResumeId.value = props.resumes.find(resume => resume.has_file)?.id || props.resumes[0]?.id || null
  }
})

watch([() => props.defaultRequisitionId, () => props.jobs], selectDefaultRequisition)

watch([() => props.candidate.id, contextRequisitionId], () => { void loadScores() }, { immediate: true })

onBeforeUnmount(() => {
  documentLoadSequence += 1
  scoreLoadSequence += 1
  closePreview()
  clearAnalysisResults()
})
</script>

<template>
  <section class="candidate-analysis-panel" data-testid="candidate-analysis-panel">
    <header class="panel-heading">
      <div>
        <small>SAFE ANALYSIS FLOW</small>
        <h3>{{ analysisReadyDocument ? '選擇你要的分析方式' : '先完成資料準備，再選 A 或 B' }}</h3>
        <p>{{ analysisReadyDocument ? 'A 由人才推薦職位；B 由指定職位計算匹配度。只有按下分析按鈕才會開始計算。' : '頁面不會自動分析；只有最後按下 A 或 B 才會開始計算與使用 Token。' }}</p>
      </div>
      <button class="refresh-button" type="button" :disabled="documentLoading" data-testid="deidentification-refresh" @click="loadDocuments">
        {{ documentLoading ? '同步中…' : '重新整理狀態' }}
      </button>
    </header>

    <div v-if="documentError" class="analysis-message error" role="alert" data-testid="deidentification-error">
      <strong>無法取得文件狀態</strong><span>{{ documentError }}</span>
    </div>
    <div v-if="actionError" class="analysis-message error" role="alert" data-testid="deidentification-action-error">
      <strong>操作未完成</strong><span>{{ actionError }}</span>
    </div>
    <div v-if="actionNotice && !analysisReadyDocument" class="analysis-message success" role="status" data-testid="deidentification-notice">
      <strong>操作完成</strong><span>{{ actionNotice }}</span>
    </div>

    <input
      ref="uploadInputRef"
      type="file"
      accept=".pdf,application/pdf"
      style="display: none"
      data-testid="deidentification-upload-input"
      @change="onUploadFileSelected"
    />

    <ol v-if="preparationStep < 3" class="analysis-steps" aria-label="分析準備步驟" data-testid="analysis-preparation-steps">
      <li :class="{ active: preparationStep === 1, done: preparationStep > 1 }"><span>{{ preparationStep > 1 ? '✓' : '1' }}</span><div><strong>上傳去識別化檔案</strong><small>由 HR 上傳已去識別化的檔案</small></div></li>
      <li :class="{ active: preparationStep === 2, done: preparationStep > 2 }"><span>{{ preparationStep > 2 ? '✓' : '2' }}</span><div><strong>HR 預覽並核准</strong><small>確認沒有姓名與聯絡資訊</small></div></li>
      <li :class="{ active: preparationStep === 3 }"><span>3</span><div><strong>選擇 A 或 B</strong><small>按下分析按鈕才開始計算</small></div></li>
    </ol>

    <section class="analysis-next-action" :data-step="preparationStep" data-testid="analysis-next-action">
      <div v-if="documentLoading && !currentDocument" class="next-action-loading"><span class="analysis-spinner" aria-hidden="true"></span><div><strong>正在確認檔案狀態</strong><small>不會執行職位分析，也不使用 Token。</small></div></div>

      <template v-else-if="!currentDocument">
        <header><span>現在請做第 1 步</span><h4>{{ canManageDocuments ? '上傳去識別化檔案' : '等待 HR 準備分析檔案' }}</h4><p>{{ canManageDocuments ? '選擇要對應的原始履歷，再上傳一份已去識別化的 PDF 檔；系統會版本化保存並自動掃描是否殘留個資，不會覆蓋原始檔。' : '目前沒有 HR 已核准的去識別化履歷。' }}</p></header>
        <div v-if="canManageDocuments && selectedSourceResume" class="next-action-controls">
          <label v-if="originalRows.length > 1">對應哪份原始履歷<select v-model="selectedSourceResumeId"><option v-for="resume in originalRows" :key="resume.id" :value="resume.id">{{ resume.original_filename || `原始履歷 #${resume.id}` }}</option></select></label>
          <div class="next-action-buttons"><button v-if="selectedSourceResume.has_file" type="button" class="secondary-action" :disabled="previewLoadingKey === `original-${selectedSourceResume.id}`" @click="openPreview({ kind: 'original', id: selectedSourceResume.id, filename: selectedSourceResume.original_filename || `resume-${selectedSourceResume.id}.pdf` })">先預覽原始履歷</button><button type="button" class="primary-action" :disabled="Boolean(workingDocumentKey)" data-testid="deidentification-primary-upload" @click="promptUploadForSelected">{{ workingDocumentKey === `upload-${selectedSourceResume.id}` ? '正在上傳…' : '上傳去識別化檔案' }}</button></div>
        </div>
      </template>

      <template v-else-if="!analysisReadyDocument">
        <header><span>現在請做第 2 步</span><h4>{{ currentDocument.validation_status === 'processing' ? '等待檔案處理完成' : currentDocument.validation_status === 'review_required' ? '預覽去識別化檔案並核准' : '這個版本需要重新處理' }}</h4><p>{{ validationSummaryText(currentDocument) }}</p></header>
        <div class="current-document-summary" data-testid="analysis-current-document"><div><strong>去識別化履歷 v{{ currentDocument.version }}</strong><small>{{ currentDocument.anonymous_ref }} · {{ formatDate(currentDocument.created_at) }}</small></div><span class="row-status" :data-status="currentDocument.validation_status">{{ statusLabels[currentDocument.validation_status] || currentDocument.validation_status }}</span></div>
        <div class="next-action-buttons">
          <button type="button" class="secondary-action" :disabled="previewLoadingKey === `deidentified-${currentDocument.id}`" data-testid="deidentification-primary-preview" @click="openPreview({ kind: 'deidentified', id: currentDocument.id, filename: `deidentified-resume-v${currentDocument.version}.pdf` })">{{ previewLoadingKey === `deidentified-${currentDocument.id}` ? '開啟中…' : '預覽去識別化檔案' }}</button>
          <button type="button" class="secondary-action" :disabled="workingDocumentKey === `download-deidentified-${currentDocument.id}`" @click="downloadTarget({ kind: 'deidentified', id: currentDocument.id, filename: `deidentified-resume-v${currentDocument.version}.pdf` })">下載檔案</button>
          <button v-if="canManageDocuments && currentDocument.validation_status === 'review_required'" type="button" class="primary-action" :disabled="Boolean(workingDocumentKey) || currentDocument.validation_summary.blocker_count > 0" data-testid="deidentification-primary-approve" @click="approveDocument(currentDocument)">{{ workingDocumentKey === `approve-${currentDocument.id}` ? '正在核准…' : currentDocument.validation_summary.blocker_count > 0 ? '有阻擋項目，無法核准' : '核准並開啟 A／B 分析' }}</button>
          <button v-else-if="canManageDocuments && ['failed', 'stale', 'superseded'].includes(currentDocument.validation_status) && selectedSourceResume" type="button" class="primary-action" :disabled="Boolean(workingDocumentKey)" @click="promptUploadForSelected">重新上傳去識別化檔案</button>
          <button v-else-if="currentDocument.validation_status === 'processing'" type="button" class="primary-action" :disabled="documentLoading" @click="loadDocuments">重新整理處理狀態</button>
        </div>
      </template>

      <template v-else>
        <div class="analysis-ready-banner" data-testid="analysis-ready-banner"><span>✓</span><div><strong>去識別化檔案已核准</strong><p>{{ analysisReadyDocument.anonymous_ref }} v{{ analysisReadyDocument.version }} 已可分析，請直接選擇下方 A 或 B。</p></div><button type="button" class="secondary-action" @click="openPreview({ kind: 'deidentified', id: analysisReadyDocument.id, filename: `deidentified-resume-v${analysisReadyDocument.version}.pdf` })">再次預覽檔案</button></div>
      </template>
    </section>

    <section v-if="scoreSummaryHint" class="analysis-section" data-testid="candidate-score-summary-hint">
      <header class="section-heading"><div><h4>六項分數總覽</h4><p>履歷匹配、兩關面試各自的題目評分與面試總分，加上系統保存的綜合參考分。</p></div></header>
      <div class="analysis-empty"><strong>目前無法顯示分數</strong><p>{{ scoreSummaryHint }}</p></div>
    </section>

    <section v-if="showScoreSummary" class="analysis-section score-summary" aria-labelledby="candidate-score-summary-title" data-testid="candidate-score-summary">
      <header class="section-heading">
        <div><h4 id="candidate-score-summary-title">六項分數總覽</h4><p>{{ scoreRequisitionLabel }}：履歷匹配、兩關面試各自的題目評分與面試總分，再加上系統保存的綜合參考分。六項都是 0–100 分制；缺少的項目一律標示原因，不以 0 分計。</p></div>
        <span class="ready-source">{{ evaluationReleaseHint }}</span>
      </header>

      <div v-if="scoresLoading && !scoreApplication" class="analysis-empty" data-testid="score-summary-loading"><span class="analysis-spinner" aria-hidden="true"></span><p>正在載入此職缺的分數…</p></div>
      <div v-if="scoresError" class="analysis-message error" role="alert" data-testid="score-summary-error"><strong>分數未完整載入</strong><span>{{ scoresError }}</span></div>

      <template v-if="scoreApplication">
        <ul class="score-figure-grid" data-testid="score-figure-grid">
          <li v-for="figure in scoreFigures" :key="figure.key" :data-state="figure.state" :data-testid="`score-figure-${figure.key}`">
            <span class="figure-index" aria-hidden="true">{{ figure.index }}</span>
            <span class="figure-copy"><strong>{{ figure.label }}<b v-if="figure.badge" class="figure-badge">{{ figure.badge }}</b></strong><small>{{ figure.source }}</small></span>
            <b class="figure-value">{{ figure.value === null ? figurePlaceholder(figure.state) : formatPoints(figure.value) }}</b>
            <small class="figure-note">{{ figure.note }}</small>
          </li>
        </ul>

        <div class="composite-breakdown" data-testid="composite-breakdown">
          <header><strong>綜合分的組成與權重</strong><small>{{ compositeWeightSourceLabel }}<template v-if="computedBreakdown"> · 計算於 {{ formatDate(computedBreakdown.computed_at) }}</template></small></header>
          <p class="composite-reference-note"><strong>綜合分是參考值。</strong>它只用於排序與討論，不是錄用結論，也不會改變應徵狀態；是否錄用仍由 HR 與主管依面試證據判斷。</p>
          <p v-if="compositeState !== 'computed'" class="composite-pending" data-testid="composite-pending">{{ compositeStateNote }}</p>
          <ul v-if="compositeComponentRows.length" class="component-list" data-testid="composite-component-list">
            <li v-for="row in compositeComponentRows" :key="row.key" :data-included="row.detail.included">
              <span class="component-copy"><b>{{ row.label }}</b><small>設定權重 {{ formatRatio(row.detail.weight) }} · 實際計入 {{ formatRatio(row.detail.applied_weight) }}</small><small v-if="!row.detail.included" class="component-miss">{{ componentExclusionText(row.detail) }}</small><small v-else-if="row.detail.applied_weight > row.detail.weight" class="component-hit">已承接同一關另一項的權重</small></span>
              <strong>{{ row.detail.included ? formatPoints(row.detail.value) : '未納入' }}</strong>
            </li>
          </ul>
          <dl v-if="compositeStageRows.length" class="detail-list"><div v-for="row in compositeStageRows" :key="row.stage"><dt>{{ row.label }} 這一關</dt><dd>{{ stageDetailText(row.detail) }}</dd></div></dl>
        </div>
      </template>
    </section>

    <details class="document-version-details">
      <summary><span><strong>檔案版本與驗證細節</strong><small>需要查看原始檔、歷史版本、遮蔽項目或重新產生時再展開。</small></span><b>展開</b></summary>
    <section class="analysis-section document-analysis" aria-labelledby="deidentified-documents-title">
      <header class="section-heading">
        <div><h4 id="deidentified-documents-title">全部檔案版本</h4><p>{{ canManageDocuments ? '原始履歷、去識別化版本與完整驗證狀態。' : '只顯示已核准、可供分析的去識別化版本。' }}</p></div>
        <span v-if="analysisReadyDocument" class="ready-source" data-testid="analysis-ready-source">分析來源：{{ analysisReadyDocument.anonymous_ref }} v{{ analysisReadyDocument.version }}</span>
      </header>

      <div v-if="documentLoading && !hasDocumentRows" class="analysis-empty" data-testid="deidentification-loading">
        <span class="analysis-spinner" aria-hidden="true"></span><p>正在載入去識別化履歷狀態…</p>
      </div>
      <div v-else-if="!hasDocumentRows && !documentError" class="analysis-empty" data-testid="deidentification-empty">
        <strong>{{ canManageDocuments && resumes.length ? '尚未上傳去識別化版本' : '目前沒有可供分析的履歷' }}</strong>
        <p>{{ canManageDocuments && resumes.length ? '請展開原始履歷並按下「上傳此履歷的去識別化檔案」。' : '完成履歷入庫及 HR 核准後即可使用職位分析。' }}</p>
      </div>

      <div v-else class="accordion-list" data-testid="deidentification-list">
        <article v-for="(resume, index) in originalRows" :key="`original-${resume.id}`" class="accordion-row" :data-testid="`original-resume-row-${resume.id}`">
          <button
            class="accordion-toggle"
            type="button"
            :aria-expanded="expandedDocumentKey === `original-${resume.id}`"
            :aria-controls="`original-resume-detail-${candidateId}-${resume.id}`"
            :data-testid="`original-resume-toggle-${resume.id}`"
            @click="toggleDocument(`original-${resume.id}`)"
          >
            <span class="row-number">{{ index + 1 }}</span>
            <span class="row-copy"><strong>{{ resume.original_filename || `原始履歷 #${resume.id}` }}</strong><small>原始履歷 · {{ resume.target_requisition_title || '未標示應徵職缺' }}</small></span>
            <span class="row-status neutral">{{ latestDocumentByResumeId.has(resume.id) ? `已有去識別化 v${latestDocumentByResumeId.get(resume.id)?.version}` : '可上傳去識別化檔案' }}</span>
            <span class="chevron" aria-hidden="true">{{ expandedDocumentKey === `original-${resume.id}` ? '⌃' : '⌄' }}</span>
          </button>
          <div v-if="expandedDocumentKey === `original-${resume.id}`" :id="`original-resume-detail-${candidateId}-${resume.id}`" class="accordion-detail">
            <dl class="detail-list"><div><dt>保存方式</dt><dd>原始檔維持不變；上傳後會另外保存一份版本化的去識別化檔案。</dd></div><div><dt>分析規則</dt><dd>原始檔不會直接交給職位分析，只有 HR 核准後的去識別化版本可使用。</dd></div><div><dt>來源</dt><dd>{{ resume.source_platform }} · Resume #{{ resume.id }}</dd></div></dl>
            <div class="row-actions">
              <button v-if="resume.has_file" type="button" :disabled="previewLoadingKey === `original-${resume.id}`" :data-testid="`original-preview-${resume.id}`" @click="openPreview({ kind: 'original', id: resume.id, filename: resume.original_filename || `resume-${resume.id}.pdf` })">{{ previewLoadingKey === `original-${resume.id}` ? '開啟中…' : '預覽原始履歷' }}</button>
              <button v-if="resume.has_file" type="button" :disabled="workingDocumentKey === `download-original-${resume.id}`" @click="downloadTarget({ kind: 'original', id: resume.id, filename: resume.original_filename || `resume-${resume.id}.pdf` })">下載原檔</button>
              <button type="button" @click="emit('open-parsed-resume', resume.id)">查看解析內容</button>
              <button class="primary-action" type="button" :disabled="Boolean(workingDocumentKey)" :data-testid="`deidentification-upload-${resume.id}`" @click="promptUpload(resume)">{{ workingDocumentKey === `upload-${resume.id}` ? '上傳中…' : '上傳此履歷的去識別化檔案' }}</button>
            </div>
          </div>
        </article>

        <article v-for="(document, index) in visibleDocuments" :key="`deidentified-${document.id}`" class="accordion-row" :data-status="document.validation_status" :data-testid="`deidentified-resume-row-${document.id}`">
          <button
            class="accordion-toggle"
            type="button"
            :aria-expanded="expandedDocumentKey === `deidentified-${document.id}`"
            :aria-controls="`deidentified-resume-detail-${candidateId}-${document.id}`"
            :data-testid="`deidentified-resume-toggle-${document.id}`"
            @click="toggleDocument(`deidentified-${document.id}`)"
          >
            <span class="row-number">{{ originalRows.length + index + 1 }}</span>
            <span class="row-copy"><strong>去識別化履歷 v{{ document.version }}</strong><small>{{ document.anonymous_ref }} · {{ formatDate(document.created_at) }}</small></span>
            <span class="row-status" :data-status="document.validation_status">{{ statusLabels[document.validation_status] || document.validation_status }}</span>
            <span class="chevron" aria-hidden="true">{{ expandedDocumentKey === `deidentified-${document.id}` ? '⌃' : '⌄' }}</span>
          </button>
          <div v-if="expandedDocumentKey === `deidentified-${document.id}`" :id="`deidentified-resume-detail-${candidateId}-${document.id}`" class="accordion-detail" :data-testid="`deidentified-resume-detail-${document.id}`">
            <dl class="detail-list">
              <div><dt>狀態說明</dt><dd>{{ validationSummaryText(document) }}</dd></div>
              <div><dt>規則版本</dt><dd>{{ document.deidentification_version }}<template v-if="document.payload_schema_version"> · Schema {{ document.payload_schema_version }}</template></dd></div>
              <div><dt>匿名文件</dt><dd>#{{ document.id }}<template v-if="canManageDocuments"> · 原始履歷 #{{ document.source_resume_id }}</template></dd></div>
            </dl>
            <ul v-if="document.validation_summary.findings.some(item => item.count > 0) || document.validation_summary.redactions.some(item => item.count > 0)" class="finding-list" aria-label="驗證檢查結果">
              <li v-for="finding in document.validation_summary.findings.filter(item => item.count > 0)" :key="`finding-${finding.type}`" :data-severity="document.validation_summary.blocker_count > 0 ? 'error' : 'warning'">
                <strong>{{ finding.type }}</strong><span>偵測到 {{ finding.count }} 項，請由 HR 核對。</span>
              </li>
              <li v-for="redaction in document.validation_summary.redactions.filter(item => item.count > 0)" :key="`redaction-${redaction.type}`" data-severity="info">
                <strong>{{ redaction.type }}</strong><span>已遮蔽 {{ redaction.count }} 項。</span>
              </li>
            </ul>
            <div class="row-actions">
              <button type="button" :disabled="previewLoadingKey === `deidentified-${document.id}`" :data-testid="`deidentified-preview-${document.id}`" @click="openPreview({ kind: 'deidentified', id: document.id, filename: `deidentified-resume-v${document.version}.pdf` })">{{ previewLoadingKey === `deidentified-${document.id}` ? '開啟中…' : '預覽去識別化履歷' }}</button>
              <button type="button" :disabled="workingDocumentKey === `download-deidentified-${document.id}`" @click="downloadTarget({ kind: 'deidentified', id: document.id, filename: `deidentified-resume-v${document.version}.pdf` })">下載</button>
              <template v-if="canManageDocuments && document.validation_status === 'review_required'">
                <button type="button" :disabled="Boolean(workingDocumentKey)" :data-testid="`deidentification-reject-${document.id}`" @click="rejectDocument(document)">{{ workingDocumentKey === `reject-${document.id}` ? '退回中…' : '退回' }}</button>
                <button class="primary-action" type="button" :disabled="Boolean(workingDocumentKey) || document.validation_summary.blocker_count > 0" :data-testid="`deidentification-approve-${document.id}`" @click="approveDocument(document)">{{ workingDocumentKey === `approve-${document.id}` ? '核准中…' : document.validation_summary.blocker_count > 0 ? '有阻擋項目' : '核准供分析' }}</button>
              </template>
            </div>
          </div>
        </article>
      </div>
    </section>
    </details>

    <section class="analysis-section role-analysis" aria-labelledby="role-analysis-title">
      <header class="section-heading">
        <div><h4 id="role-analysis-title">{{ analysisReadyDocument ? '選擇 A 或 B' : '第 3 步：選擇 A 或 B' }}</h4><p>A 是從人才找職位；B 是先指定職位再計算匹配度。只有按下按鈕才開始計算。</p></div>
        <span class="ready-source" :class="{ locked: !analysisReadyDocument }">{{ analysisReadyDocument ? '可以開始分析' : '完成上方準備後開啟' }}</span>
      </header>

      <div class="analysis-mode-grid" data-testid="analysis-mode-grid">
        <article class="analysis-mode-card recommended-mode">
          <header><b>A</b><div><strong>我想知道這個人適合什麼職位</strong><small>系統會比較目前開放職缺並列出推薦結果。</small></div></header>
          <button class="analysis-submit" type="button" :disabled="!analysisReadyDocument || analysisBusy" data-testid="recommend-roles-button" @click="runRecommendedAnalysis">
            {{ recommendedLoading ? '正在分析…' : 'A｜推薦適合職位' }}
          </button>
          <small v-if="!analysisReadyDocument" class="mode-lock-hint">完成上方第 2 步後即可使用</small>
        </article>
        <article class="analysis-mode-card role-match-mode">
          <header><b>B</b><div><strong>我想知道這個人符合某職位幾％</strong><small>先選一個職位，再查看條件匹配度與依據。</small></div></header>
          <div class="role-match-control">
            <label :for="`analysis-job-${candidateId}`">先選擇要比較的職位</label>
            <select :id="`analysis-job-${candidateId}`" v-model="selectedRequisitionId" :disabled="analysisBusy || !analysisJobs.length" data-testid="role-match-job-select">
              <option :value="null">{{ analysisJobs.length ? '請選擇職位' : '目前沒有可分析的開放職缺' }}</option>
              <option v-for="job in analysisJobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}<template v-if="job.department_name">（{{ job.department_name }}）</template></option>
            </select>
            <button class="analysis-submit secondary" type="button" :disabled="!analysisReadyDocument || selectedRequisitionId === null || analysisBusy" data-testid="role-match-button" @click="runRoleMatchAnalysis">
              {{ roleMatchLoading ? '正在分析…' : 'B｜計算此職位匹配度' }}
            </button>
            <small v-if="!analysisReadyDocument" class="mode-lock-hint">完成上方第 2 步後即可使用</small><small v-else-if="!analysisJobs.length" class="mode-lock-hint job-empty">請先到「職缺管理」建立並開放職缺</small><small v-else-if="selectedRequisitionId === null" class="mode-lock-hint">選擇職位後即可按下 B</small>
          </div>
        </article>
      </div>

      <p class="privacy-note" data-testid="analysis-privacy-note"><strong>本次結果不保存。</strong>結果只暫存在目前畫面，切換人才、關閉視窗、重新整理或 15 分鐘後即清除。</p>
      <div v-if="analysisError" class="analysis-message error" role="alert" data-testid="analysis-error"><strong>分析未完成</strong><span>{{ analysisError }}</span></div>

      <section v-if="recommendedResult" class="result-block" data-testid="recommended-role-results">
        <header class="result-heading">
          <div><h5>適合職位推薦</h5><span>{{ recommendedResult.items.length }} 項 · {{ tokenLabel(recommendedResult) }}</span></div>
          <small>{{ recommendedResult.algorithm_version }} · {{ formatDate(recommendedResult.generated_at) }}</small>
        </header>
        <div v-if="recommendedResult.items.length" class="accordion-list result-list">
          <article v-for="(item, index) in recommendedResult.items" :key="item.requisition_id" class="accordion-row" :data-testid="`recommended-role-row-${item.requisition_id}`">
            <button
              class="accordion-toggle result-toggle"
              type="button"
              :aria-expanded="expandedRecommendedId === item.requisition_id"
              :aria-controls="`recommended-detail-${candidateId}-${item.requisition_id}`"
              :data-testid="`recommended-role-toggle-${item.requisition_id}`"
              @click="expandedRecommendedId = expandedRecommendedId === item.requisition_id ? null : item.requisition_id"
            >
              <span class="row-number">{{ index + 1 }}</span>
              <span class="row-copy"><strong>{{ item.title }}</strong><small>{{ item.req_no }} · {{ item.department_name || '未標示部門' }}</small></span>
              <span class="score-summary"><strong>{{ formatScore(item.total_score) }}</strong><small>職位條件匹配度</small></span>
              <span class="gate-status" :class="{ failed: !item.gate_passed }">{{ item.gate_passed ? '必要條件通過' : '必要條件未通過' }}</span>
              <span class="chevron" aria-hidden="true">{{ expandedRecommendedId === item.requisition_id ? '⌃' : '⌄' }}</span>
            </button>
            <div v-if="expandedRecommendedId === item.requisition_id" :id="`recommended-detail-${candidateId}-${item.requisition_id}`" class="accordion-detail result-detail" :data-testid="`recommended-role-detail-${item.requisition_id}`">
              <div class="metric-lines"><span><small>分析信心</small><strong>{{ confidenceLabel(item.confidence) }}</strong></span><span><small>資料完整度</small><strong>{{ formatRatio(item.data_completeness) }}</strong></span></div>
              <section v-if="normalizedComponents(item).length"><h6>分項匹配度</h6><ul class="component-list"><li v-for="component in normalizedComponents(item)" :key="component.key"><span class="component-copy"><b>{{ component.label }}</b><small>權重 {{ formatRatio(component.weight) }}</small><small v-if="component.hit.length" class="component-hit">符合：{{ component.hit.join('、') }}</small><small v-if="component.miss.length" class="component-miss">缺少／待確認：{{ component.miss.join('、') }}</small></span><strong>{{ component.known ? formatScore(component.score) : '資料不足' }}</strong></li></ul></section>
              <section v-if="item.highlights.length"><h6>符合依據</h6><ul class="highlight-list"><li v-for="highlight in item.highlights" :key="`${highlight.kind}-${highlight.category}-${highlight.text}`" :data-kind="highlight.kind"><strong>{{ highlight.category }}</strong><span>{{ highlight.text }}</span></li></ul></section>
              <section v-if="item.insufficient_data.length"><h6>資料不足／待確認</h6><ul class="bullet-list muted"><li v-for="gap in item.insufficient_data" :key="gap">{{ gap }}</li></ul></section>
              <p class="result-disclaimer">{{ recommendedResult.disclaimer }}</p>
            </div>
          </article>
        </div>
        <div v-else class="analysis-empty"><strong>沒有找到可推薦職位</strong><p>請確認目前權限範圍內是否有有效職缺。</p></div>
      </section>

      <section v-if="roleMatchResult" class="result-block" data-testid="role-match-result">
        <header class="result-heading">
          <div><h5>指定職位評估</h5><span>{{ tokenLabel(roleMatchResult) }}</span></div>
          <small>{{ roleMatchResult.algorithm_version }} · {{ formatDate(roleMatchResult.generated_at) }}</small>
        </header>
        <article class="accordion-row">
          <button
            class="accordion-toggle result-toggle"
            type="button"
            :aria-expanded="roleMatchExpanded"
            :aria-controls="`role-match-detail-${candidateId}-${roleMatchResult.item.requisition_id}`"
            data-testid="role-match-result-toggle"
            @click="roleMatchExpanded = !roleMatchExpanded"
          >
            <span class="row-number">1</span>
            <span class="row-copy"><strong>{{ roleMatchResult.item.title }}</strong><small>{{ roleMatchResult.item.req_no }} · {{ roleMatchResult.item.department_name || '未標示部門' }}</small></span>
            <span class="score-summary"><strong>{{ formatScore(roleMatchResult.item.total_score) }}</strong><small>職位條件匹配度</small></span>
            <span class="gate-status" :class="{ failed: !roleMatchResult.item.gate_passed }">{{ roleMatchResult.item.gate_passed ? '必要條件通過' : '必要條件未通過' }}</span>
            <span class="chevron" aria-hidden="true">{{ roleMatchExpanded ? '⌃' : '⌄' }}</span>
          </button>
          <div v-if="roleMatchExpanded" :id="`role-match-detail-${candidateId}-${roleMatchResult.item.requisition_id}`" class="accordion-detail result-detail" data-testid="role-match-result-detail">
            <div class="metric-lines"><span><small>分析信心</small><strong>{{ confidenceLabel(roleMatchResult.item.confidence) }}</strong></span><span><small>資料完整度</small><strong>{{ formatRatio(roleMatchResult.item.data_completeness) }}</strong></span></div>
            <section v-if="normalizedComponents(roleMatchResult.item).length"><h6>分項匹配度</h6><ul class="component-list"><li v-for="component in normalizedComponents(roleMatchResult.item)" :key="component.key"><span class="component-copy"><b>{{ component.label }}</b><small>權重 {{ formatRatio(component.weight) }}</small><small v-if="component.hit.length" class="component-hit">符合：{{ component.hit.join('、') }}</small><small v-if="component.miss.length" class="component-miss">缺少／待確認：{{ component.miss.join('、') }}</small></span><strong>{{ component.known ? formatScore(component.score) : '資料不足' }}</strong></li></ul></section>
            <section v-if="roleMatchResult.item.highlights.length"><h6>符合依據</h6><ul class="highlight-list"><li v-for="highlight in roleMatchResult.item.highlights" :key="`${highlight.kind}-${highlight.category}-${highlight.text}`" :data-kind="highlight.kind"><strong>{{ highlight.category }}</strong><span>{{ highlight.text }}</span></li></ul></section>
            <section v-if="roleMatchResult.item.insufficient_data.length"><h6>資料不足／待確認</h6><ul class="bullet-list muted"><li v-for="gap in roleMatchResult.item.insufficient_data" :key="gap">{{ gap }}</li></ul></section>
            <p class="result-disclaimer">{{ roleMatchResult.disclaimer }}</p>
          </div>
        </article>
      </section>
    </section>

    <div v-if="previewTarget" class="preview-backdrop" role="presentation" @click.self="closePreview" @keydown.esc="closePreview">
      <section class="preview-dialog" role="dialog" aria-modal="true" aria-labelledby="deidentified-preview-title" data-testid="candidate-analysis-preview">
        <header><div><small>{{ previewTarget.kind === 'original' ? 'ORIGINAL DOCUMENT' : 'DE-IDENTIFIED DOCUMENT' }}</small><h4 id="deidentified-preview-title">{{ previewTarget.filename }}</h4></div><button type="button" aria-label="關閉預覽" @click="closePreview">×</button></header>
        <iframe v-if="previewIsPdf && previewUrl" :src="previewUrl" :title="`${previewTarget.filename} 預覽`"></iframe>
        <div v-else class="unsupported-preview"><strong>瀏覽器無法直接顯示這個檔案格式</strong><p>請使用下載功能並在本機開啟。</p></div>
        <p v-if="previewError" class="analysis-message error">{{ previewError }}</p>
        <footer><span>預覽不會觸發職位分析，也不使用 Token。</span><button type="button" @click="downloadTarget(previewTarget)">下載檔案</button></footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.component-copy{min-width:0}.component-copy>b{display:block}.component-copy .component-hit{color:#24715f}.component-copy .component-miss{color:#94603b}.component-list>li>strong{flex:0 0 auto}.highlight-list{display:grid;gap:5px;margin:9px 0 0;padding:0;list-style:none}.highlight-list li{display:grid;grid-template-columns:minmax(70px,auto) 1fr;gap:8px;padding:7px 9px;border-radius:7px;background:#eef7f3;color:#365f57;font-size:8px;line-height:1.5}.highlight-list li[data-kind="concern"]{background:#fff3e5;color:#805b34}.highlight-list li[data-kind="info"]{background:#eef5f8;color:#426473}
.candidate-analysis-panel{display:grid;gap:16px;margin:18px 0;padding:16px;border:2px solid #6eb5a6;border-radius:13px;background:#fff;color:#183f39;box-shadow:0 8px 24px rgba(28,103,91,.08)}.panel-heading,.section-heading,.result-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.panel-heading small{color:#2a8074;font-size:8px;font-weight:900;letter-spacing:1px}.panel-heading h3,.section-heading h4,.result-heading h5{margin:4px 0;color:#174d46}.panel-heading h3{font-size:15px}.panel-heading p,.section-heading p{margin:0;color:#748681;font-size:9px;line-height:1.55}.refresh-button,.row-actions button,.analysis-submit,.preview-dialog footer button{border:1px solid #cbded8;border-radius:8px;background:#fff;padding:8px 11px;color:#24665d;font:inherit;font-size:9px;font-weight:800}.refresh-button:disabled,.row-actions button:disabled,.analysis-submit:disabled{cursor:not-allowed;opacity:.55}.analysis-section{display:grid;gap:10px}.analysis-section+.analysis-section{padding-top:15px;border-top:1px solid #e2ece9}.section-heading h4{font-size:12px}.ready-source{align-self:center;padding:5px 8px;border-radius:99px;background:#e2f2ed;color:#1b6b61;font-size:8px;font-weight:800;white-space:nowrap}.analysis-message{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border:1px solid #ead8b4;border-radius:8px;background:#fff9ec;color:#765d2f;font-size:9px;line-height:1.55}.analysis-message strong{white-space:nowrap}.analysis-message.error{border-color:#efc7c0;background:#fff2f0;color:#8e4438}.analysis-message.success{border-color:#c8e4d4;background:#eff9f3;color:#286b4c}.analysis-message.warning{border-color:#ead8b4;background:#fff9ec}.analysis-empty{display:grid;justify-items:center;gap:5px;padding:24px;border:1px dashed #d3e2dd;border-radius:9px;background:#fafcfb;text-align:center;color:#71847f}.analysis-empty strong{font-size:10px}.analysis-empty p{margin:0;font-size:9px}.analysis-spinner{width:18px;height:18px;border:2px solid #c8ddd6;border-top-color:#258175;border-radius:50%;animation:analysis-spin .8s linear infinite}@keyframes analysis-spin{to{transform:rotate(360deg)}}.accordion-list{display:grid;border:1px solid #dce8e4;border-radius:10px;overflow:hidden}.accordion-row{min-width:0;background:#fff}.accordion-row+.accordion-row{border-top:1px solid #e1ebe8}.accordion-toggle{display:grid;grid-template-columns:28px minmax(160px,1fr) auto auto;align-items:center;gap:10px;width:100%;padding:12px;border:0;background:#fff;color:inherit;text-align:left}.accordion-toggle:hover,.accordion-toggle:focus-visible{background:#f4faf8;outline:none}.row-number{width:26px;height:26px;display:grid;place-items:center;border-radius:50%;background:#edf3f1;color:#4d6862;font-size:9px;font-weight:800}.row-copy{min-width:0}.row-copy strong,.row-copy small{display:block}.row-copy strong{overflow:hidden;text-overflow:ellipsis;color:#174e47;font-size:10px}.row-copy small{margin-top:4px;color:#758782;font-size:8px}.row-status,.gate-status{padding:5px 8px;border-radius:99px;background:#edf3f1;color:#596d68;font-size:8px;font-weight:800;white-space:nowrap}.row-status[data-status="analysis_ready"]{background:#dcf1e9;color:#116c5e}.row-status[data-status="review_required"]{background:#fff0cf;color:#8a641f}.row-status[data-status="failed"],.row-status[data-status="stale"]{background:#fde8e4;color:#93483d}.row-status[data-status="processing"]{background:#e7f0f7;color:#416a86}.chevron{color:#6b817b;font-size:12px}.accordion-detail{padding:0 13px 13px 51px;background:#fbfdfc}.detail-list{display:grid;gap:7px;margin:0;padding:10px 11px;border-left:2px solid #c7e0d8;background:#f4f9f7}.detail-list>div{display:grid;grid-template-columns:86px 1fr;gap:9px}.detail-list dt{color:#2a6b62;font-size:8px;font-weight:800}.detail-list dd{margin:0;color:#526d66;font-size:8px;line-height:1.55}.finding-list,.component-list,.bullet-list{margin:9px 0 0;padding:0;list-style:none}.finding-list{display:grid;gap:5px}.finding-list li{display:flex;gap:8px;padding:7px 9px;border-radius:7px;background:#f1f6f4;font-size:8px}.finding-list li[data-severity="error"]{background:#fff0ed;color:#8d493e}.finding-list strong{min-width:90px}.row-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px;margin-top:10px}.row-actions .primary-action,.analysis-submit{border-color:#1c7569;background:#1c7569;color:#fff}.role-analysis{order:1;gap:12px;padding-top:0!important;border-top:0!important}.document-analysis{order:2;padding-top:15px;border-top:1px solid #e2ece9}.analysis-controls{display:grid;gap:9px}.analysis-submit{justify-self:start;padding:10px 14px}.analysis-submit.secondary{background:#fff;color:#21695f}.analysis-mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.analysis-mode-card{display:grid;align-content:start;gap:12px;padding:14px;border:1px solid #cfe2dc;border-radius:11px;background:#f7fbfa}.analysis-mode-card>header{display:flex;align-items:flex-start;gap:9px}.analysis-mode-card>header>b{padding:4px 7px;border-radius:99px;background:#1e786c;color:#fff;font-size:8px;white-space:nowrap}.analysis-mode-card>header strong,.analysis-mode-card>header small{display:block}.analysis-mode-card>header strong{color:#215c54;font-size:11px}.analysis-mode-card>header small{margin-top:3px;color:#6d817b;font-size:9px;line-height:1.5}.analysis-mode-card .analysis-submit{min-height:39px;font-size:10px}.recommended-mode .analysis-submit{width:100%;justify-self:stretch}.role-match-control{display:grid;grid-template-columns:1fr;align-items:center;gap:8px;padding:0;border:0;background:transparent}.role-match-control label{font-size:9px;font-weight:800}.role-match-control select{width:100%;padding:9px 10px;border:1px solid #cdded9;border-radius:7px;background:#fff;color:#214c46;font:inherit;font-size:9px}.role-match-control .analysis-submit{width:100%;justify-self:stretch}.privacy-note{margin:0;padding:9px 11px;border-left:3px solid #d6a746;background:#fff9ed;color:#796039;font-size:8px;line-height:1.55}.result-block{display:grid;gap:8px;margin-top:4px}.result-heading{align-items:center;padding:9px 2px}.result-heading h5{font-size:11px}.result-heading span,.result-heading small{color:#758782;font-size:8px}.result-toggle{grid-template-columns:28px minmax(150px,1fr) auto auto auto}.score-summary{text-align:right}.score-summary strong,.score-summary small{display:block}.score-summary strong{color:#176d62;font-size:14px}.score-summary small{color:#71847f;font-size:7px}.gate-status{background:#e4f2ed;color:#1b695f}.gate-status.failed{background:#fff0df;color:#9a5a2f}.result-detail{display:grid;gap:10px}.metric-lines{display:flex;gap:8px}.metric-lines span{min-width:120px;padding:8px 10px;border-radius:7px;background:#eef6f3}.metric-lines small,.metric-lines strong{display:block}.metric-lines small{color:#71847f;font-size:7px}.metric-lines strong{margin-top:3px;color:#1f6259;font-size:10px}.result-detail h6{margin:0;color:#285b54;font-size:9px}.component-list{display:grid;gap:5px}.component-list li{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 9px;border-radius:7px;background:#f2f7f5;color:#41625c;font-size:8px}.component-list span small{display:block;margin-top:2px;color:#80908c}.component-list strong{color:#1c6b61}.bullet-list{display:grid;gap:5px;padding-left:16px;list-style:disc;color:#42615b;font-size:8px;line-height:1.55}.bullet-list.muted{color:#765e43}.result-disclaimer{margin:0;padding:8px 10px;border-radius:7px;background:#fff8e9;color:#78613c;font-size:8px;line-height:1.55}.preview-backdrop{position:fixed;inset:0;z-index:1400;display:grid;place-items:center;padding:20px;background:rgba(7,31,28,.7)}.preview-dialog{display:flex;flex-direction:column;width:min(1050px,100%);height:min(88vh,820px);overflow:hidden;border-radius:14px;background:#fff;box-shadow:0 24px 70px rgba(0,0,0,.3)}.preview-dialog>header{display:flex;align-items:flex-start;justify-content:space-between;padding:15px 18px;border-bottom:1px solid #dce7e4}.preview-dialog>header small{color:#218073;font-size:8px;font-weight:900;letter-spacing:1px}.preview-dialog>header h4{margin:4px 0;font-size:14px}.preview-dialog>header button{border:0;background:transparent;color:#687c77;font-size:24px}.preview-dialog iframe{flex:1;width:100%;border:0;background:#e3e8e6}.unsupported-preview{flex:1;display:grid;place-content:center;text-align:center;color:#6f827d}.unsupported-preview strong{font-size:12px}.unsupported-preview p{font-size:9px}.preview-dialog>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 16px;border-top:1px solid #dce7e4}.preview-dialog>footer span{color:#71847f;font-size:8px}
/* Simple three-step preparation flow keeps the next required action visible. */
.analysis-steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0;padding:0;list-style:none}.analysis-steps li{min-width:0;display:flex;align-items:center;gap:9px;padding:10px 11px;border:1px solid #dce8e4;border-radius:10px;background:#f7faf9;color:#6c7e79}.analysis-steps li>span{width:29px;height:29px;flex:0 0 auto;display:grid;place-items:center;border-radius:50%;background:#e7efec;color:#557069;font-size:12px;font-weight:900}.analysis-steps li strong,.analysis-steps li small{display:block}.analysis-steps li strong{font-size:12px}.analysis-steps li small{margin-top:2px;font-size:10px;line-height:1.35}.analysis-steps li.active{border-color:#5aab9b;background:#edf8f5;color:#175e54}.analysis-steps li.active>span{background:#188477;color:#fff}.analysis-steps li.done{border-color:#b9ddcf;background:#f0f9f4;color:#28694f}.analysis-steps li.done>span{background:#49a476;color:#fff}
.analysis-next-action{display:grid;gap:12px;padding:15px 16px;border:1px solid #ddc585;border-radius:11px;background:#fff9ec}.analysis-next-action[data-step="3"]{gap:0;padding:10px 12px;border-color:#9fd1bc;background:#eff9f3}.analysis-next-action header>span{display:block;color:#9a6b1d;font-size:11px;font-weight:900}.analysis-next-action header h4{margin:3px 0;color:#654c24;font-size:16px}.analysis-next-action header p{margin:0;color:#735f3e;font-size:12px;line-height:1.6}.next-action-loading{display:flex;align-items:center;gap:11px}.next-action-loading .analysis-spinner{margin:0}.next-action-loading strong,.next-action-loading small{display:block}.next-action-loading strong{font-size:13px}.next-action-loading small{margin-top:2px;color:#71837e;font-size:11px}.next-action-controls{display:grid;gap:9px}.next-action-controls label{display:grid;gap:5px;color:#5c5c4c;font-size:12px;font-weight:800}.next-action-controls select{width:100%;height:40px;padding:0 10px;border:1px solid #cfddda;border-radius:8px;background:#fff;color:#264e48;font-size:13px}.next-action-buttons{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}.analysis-next-action button{min-height:39px;padding:8px 13px;border:1px solid #c9dcd6;border-radius:8px;background:#fff;color:#24665d;font-size:12px;font-weight:800}.analysis-next-action button.primary-action{border-color:#167b6e;background:#167b6e;color:#fff}.analysis-next-action button:disabled{cursor:not-allowed;opacity:.55}.next-action-warning{color:#934d3f;font-size:11px}.current-document-summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border-radius:9px;background:rgba(255,255,255,.76)}.current-document-summary strong,.current-document-summary small{display:block}.current-document-summary strong{color:#315e55;font-size:13px}.current-document-summary small{margin-top:3px;color:#72847f;font-size:11px}.analysis-ready-banner{display:flex;align-items:center;gap:12px}.analysis-ready-banner>span{width:37px;height:37px;flex:0 0 auto;display:grid;place-items:center;border-radius:50%;background:#3d9f70;color:#fff;font-size:18px;font-weight:900}.analysis-next-action[data-step="3"] .analysis-ready-banner>span{width:31px;height:31px;font-size:15px}.analysis-ready-banner>div{min-width:0;flex:1}.analysis-ready-banner strong{display:block;color:#245f48;font-size:15px}.analysis-ready-banner p{margin:3px 0 0;color:#557368;font-size:12px}.document-version-details{order:3;overflow:hidden;border:1px solid #dce8e4;border-radius:10px;background:#fbfdfc}.document-version-details>summary{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 13px;cursor:pointer;list-style:none}.document-version-details>summary::-webkit-details-marker{display:none}.document-version-details>summary span{min-width:0}.document-version-details>summary strong,.document-version-details>summary small{display:block}.document-version-details>summary strong{color:#315d56;font-size:12px}.document-version-details>summary small{margin-top:2px;color:#758782;font-size:11px}.document-version-details>summary b{padding:5px 8px;border-radius:7px;background:#edf4f2;color:#4c6e67;font-size:10px}.document-version-details[open]>summary{border-bottom:1px solid #dfe9e6;background:#f4f9f7}.document-version-details[open]>summary b{font-size:0}.document-version-details[open]>summary b:after{content:"收合";font-size:10px}.document-version-details .document-analysis{padding:13px!important}.ready-source.locked{background:#eef1f0;color:#788681}.mode-lock-hint{display:block;color:#8a6b34!important;font-size:11px!important;text-align:center}
/* 這個區塊承載操作決策，不使用舊版的 8–10px 高密度字級。 */
.document-analysis{order:1;padding-top:0!important;border-top:0!important}.role-analysis{order:2;padding-top:15px!important;border-top:1px solid #e2ece9!important}
.candidate-analysis-panel{font-size:14px;line-height:1.6}
.panel-heading small,.ready-source,.row-number,.row-status,.gate-status,.analysis-mode-card>header>b{font-size:11px}
.panel-heading h3{font-size:19px}.section-heading h4{font-size:16px}.result-heading h5{font-size:15px}
.panel-heading p,.section-heading p,.analysis-message,.analysis-empty p{font-size:13px}
.refresh-button,.row-actions button,.analysis-submit,.preview-dialog footer button{font-size:13px}
.analysis-empty strong,.row-copy strong{font-size:14px}.row-copy small{font-size:12px}
.detail-list dt{font-size:12px}.detail-list dd,.finding-list li,.highlight-list li{font-size:12px}
.analysis-mode-card>header strong{font-size:14px}.analysis-mode-card>header small{font-size:12px}
.analysis-mode-card .analysis-submit,.role-match-control label,.role-match-control select{font-size:13px}.mode-lock-hint.job-empty{color:#a35b3d!important}
.privacy-note,.result-heading span,.result-heading small,.score-summary small,.metric-lines small,.component-list li,.bullet-list,.result-disclaimer{font-size:12px}
.score-summary strong{font-size:18px}.metric-lines strong{font-size:14px}.result-detail h6{font-size:13px}
.preview-dialog>header small,.preview-dialog>footer span{font-size:11px}.unsupported-preview p{font-size:12px}
/* Six stored scores side by side, below the A／B chooser and above the file-version details. */
.score-summary{order:3;gap:12px;padding-top:15px;border-top:1px solid #e2ece9}.score-figure-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:0;padding:0;list-style:none}.score-figure-grid>li{display:grid;grid-template-columns:26px minmax(0,1fr) auto;align-items:center;gap:8px;padding:10px 11px;border:1px solid #dce8e4;border-radius:10px;background:#fbfdfc}.score-figure-grid>li[data-state="scored"]{border-color:#bfded2;background:#f4faf8}.score-figure-grid>li[data-state="masked"]{border-color:#d3dee4;background:#f4f8fa}.score-figure-grid>li[data-state="pending"]{border-color:#e6d5ae;background:#fffaf0}.figure-index{width:26px;height:26px;display:grid;place-items:center;border-radius:50%;background:#edf3f1;color:#4d6862;font-size:12px;font-weight:800}.figure-copy{min-width:0}.figure-copy strong,.figure-copy small{display:block}.figure-copy strong{color:#174e47;font-size:13px}.figure-copy small{margin-top:2px;color:#758782;font-size:11px}.figure-badge{margin-left:6px;padding:2px 6px;border-radius:99px;background:#e6f1ee;color:#256a60;font-size:10px;font-weight:800;vertical-align:middle}.figure-value{color:#12695c;font-size:17px;font-weight:800;text-align:right;white-space:nowrap}.score-figure-grid>li:not([data-state="scored"]) .figure-value{color:#7b6a48;font-size:12px}.figure-note{grid-column:2/4;margin-top:2px;color:#6d7f7a;font-size:11px;line-height:1.5}
.composite-breakdown{display:grid;gap:8px;padding:12px 13px;border:1px solid #d8e5e0;border-radius:10px;background:#f7fbfa}.composite-breakdown>header strong{display:block;color:#215c54;font-size:13px}.composite-breakdown>header small{display:block;margin-top:2px;color:#758782;font-size:11px}.composite-reference-note{margin:0;padding:8px 10px;border-left:3px solid #d6a746;background:#fff9ed;color:#796039;font-size:12px;line-height:1.55}.composite-pending{margin:0;padding:9px 11px;border-radius:7px;background:#fff4e2;color:#7d5f30;font-size:12px;line-height:1.55}.composite-breakdown .component-list{margin:0}.composite-breakdown .component-list li[data-included="false"]{background:#f6f4ef;color:#6f6552}.composite-breakdown .detail-list{margin:0}
@media(max-width:760px){.score-figure-grid{grid-template-columns:1fr}}
@media(max-width:760px){.candidate-analysis-panel{padding:12px}.panel-heading,.section-heading,.result-heading{align-items:stretch;flex-direction:column}.refresh-button{align-self:flex-start}.analysis-steps{grid-template-columns:1fr}.analysis-steps li{min-height:54px}.analysis-ready-banner{align-items:flex-start;flex-wrap:wrap}.analysis-ready-banner button{width:100%}.next-action-buttons{align-items:stretch;flex-direction:column}.next-action-buttons button{width:100%}.current-document-summary{align-items:flex-start;flex-direction:column}.analysis-mode-grid{grid-template-columns:1fr}.accordion-toggle,.result-toggle{grid-template-columns:28px minmax(0,1fr) auto}.row-status,.gate-status{grid-column:2/3;justify-self:start}.chevron{grid-column:3;grid-row:1/3}.score-summary{grid-column:3;grid-row:1}.result-toggle .chevron{grid-row:2}.accordion-detail{padding-left:13px}.role-match-control{grid-template-columns:1fr}.role-match-control .analysis-submit{width:100%}.metric-lines{flex-direction:column}.preview-backdrop{padding:0}.preview-dialog{width:100%;height:100vh;border-radius:0}.preview-dialog>footer span{display:none}}
</style>
