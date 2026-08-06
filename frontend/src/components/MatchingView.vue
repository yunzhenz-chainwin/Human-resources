<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import CandidateAnalysisPanel from './CandidateAnalysisPanel.vue'
import MatchingBenchmarkPanel from './MatchingBenchmarkPanel.vue'
import SemanticShadowPanel from './SemanticShadowPanel.vue'
import { hrApi, type CandidateDetailDto, type RequisitionDto } from '../services/hrApi'
import type { UserRole } from '../services/auth'
import {
  matchingReportsApi,
  type CandidateMatchOverview,
  type CandidateMatchOverviewItem,
  type MatchDto,
  type MatchReadiness,
  type MatchStatus,
  type MatchSource,
  type MatchingCriteria,
  type MatchingCriteriaImpact,
  type MatchingWeights,
  type MatchHighlight,
  type OverrideReasonCategory,
  type RejectionReasonCategory,
  type ScorePart,
} from '../services/matchingReportsApi'

type InterviewRequest = {
  candidateId: number
  candidateName: string
  requisitionId: number
  source: 'applicant' | 'talent_pool'
  applicationId: number | null
}

const props = withDefaults(defineProps<{
  jobs: RequisitionDto[]
  canConfigure?: boolean
  canConfigureWeights?: boolean
  canManage?: boolean
  role?: UserRole
  embedded?: boolean
  initialRequisitionId?: number | null
  initialSource?: Exclude<MatchSource, 'all'>
  focusedCandidateId?: number | null
  interviewRequestPendingCandidateId?: number | null
  refreshKey?: number
}>(), {
  role: 'manager',
  embedded: false,
  initialRequisitionId: null,
  initialSource: 'applicants',
  focusedCandidateId: null,
  interviewRequestPendingCandidateId: null,
  refreshKey: 0,
})
const emit = defineEmits<{
  'job-selected': [requisitionId: number | null]
  'source-selected': [source: Exclude<MatchSource, 'all'>]
  'request-interview': [request: InterviewRequest]
}>()
const workspaceMode = ref<'matching' | 'benchmark'>('matching')
const selectedJobId = ref<number | null>(null)
const activeSource = ref<Exclude<MatchSource, 'all'>>('applicants')
const overview = ref<CandidateMatchOverview | null>(null)
const readiness = ref<MatchReadiness | null>(null)
const loading = ref(false)
const recalculating = ref(false)
const error = ref('')
const criteria = ref<MatchingCriteria | null>(null)
const requiredSkillsText = ref('')
const preferredSkillsText = ref('')
const showCriteria = ref(false)
const savingCriteria = ref(false)
const criteriaImpact = ref<MatchingCriteriaImpact | null>(null)
const previewingCriteria = ref(false)
const previewSignature = ref('')
const weights = ref<MatchingWeights | null>(null)
const weightDraft = reactive<MatchingWeights>({ skill: 40, relevance: 20, years: 15, salary: 10, education: 10, location: 5 })
const showWeights = ref(false)
const savingWeights = ref(false)
const minDisplayScore = ref(0)
const onlyPassed = ref(false)
const talentSearch = ref('')
const decisionMatch = ref<MatchDto | null>(null)
const decisionMode = ref<'override' | 'reject' | null>(null)
const decisionCategory = ref<OverrideReasonCategory | RejectionReasonCategory | ''>('')
const decisionNote = ref('')
const decisionTargetStage = ref<MatchStatus>('shortlisted')
const savingDecision = ref(false)
const shadowMatchId = ref<number | null>(null)
const expandedCandidateId = ref<number | null>(null)
const candidateDetails = ref<Record<number, CandidateDetailDto>>({})
const candidateDetailLoading = ref<Record<number, boolean>>({})
const candidateDetailErrors = ref<Record<number, string>>({})
let overviewRequestSequence = 0

const allPeople = computed(() => [...(overview.value?.items || [])].sort((a, b) => {
  if (!a.match && b.match) return 1
  if (a.match && !b.match) return -1
  if (a.match && b.match) return b.match.total_score - a.match.total_score
  return a.candidate.name.localeCompare(b.candidate.name, 'zh-Hant')
}))
const people = computed(() => allPeople.value.filter(item => {
  const score = item.match?.total_score ?? -1
  const keyword = talentSearch.value.trim().toLocaleLowerCase('zh-Hant')
  return (minDisplayScore.value === 0 || (!!item.match && score >= minDisplayScore.value))
    && (!onlyPassed.value || !!item.match?.gate_passed)
    && (!keyword || `${item.candidate.name} ${item.candidate.current_title || ''} ${item.candidate.code}`.toLocaleLowerCase('zh-Hant').includes(keyword))
}))
const selectedJob = computed(() => props.jobs.find(job => job.id === selectedJobId.value))
const componentLabels: Record<string, string> = {
  skill: '技能', relevance: '職務相關', years: '年資', salary: '薪資', education: '學歷', location: '地點',
}
const eligibleTotalCount = computed(() => allPeople.value.filter(item => item.match?.gate_passed).length)
const requiredSkillHits = computed(() => Math.ceil(
  skills(requiredSkillsText.value).length * Number(criteria.value?.required_skill_ratio ?? 1),
))
const requiredSkillRatioDescription = computed(() => {
  const total = skills(requiredSkillsText.value).length
  if (!criteria.value?.require_skills) return '必要技能目前不作為系統必要條件。'
  if (!total) return '尚未設定必要技能，這項門檻不會排除人才。'
  return `需符合至少 ${requiredSkillHits.value}／${total} 項必要技能；資料未提供會標示為「資料不足」，不會偽裝成已確認不符合。`
})
const formulaParts = computed(() => {
  const sample = allPeople.value.find(item => item.match)?.match
  return Object.entries(componentLabels).map(([key, label]) => {
    const configured = weights.value?.[key as keyof MatchingWeights]
    const weight = Number(configured ?? sample?.score_breakdown[key]?.weight)
    return { key, label, percent: Number.isFinite(weight) ? Math.round(weight * 100) : null }
  })
})
const weightTotal = computed(() => Object.values(weightDraft).reduce((total, value) => total + (Number(value) || 0), 0))
const weightItems = computed(() => Object.entries(componentLabels).map(([key, label]) => ({
  key: key as keyof MatchingWeights,
  label,
  value: weightDraft[key as keyof MatchingWeights],
})))
const weightPresets: Array<{ label: string; description: string; values: MatchingWeights }> = [
  { label: '均衡', description: '兼顧技能、職務內容與經驗', values: { skill: 40, relevance: 20, years: 15, salary: 10, education: 10, location: 5 } },
  { label: '技能優先', description: '強調必要技術與實作能力', values: { skill: 55, relevance: 20, years: 10, salary: 5, education: 5, location: 5 } },
  { label: '經驗優先', description: '重視相關職務與年資成熟度', values: { skill: 25, relevance: 35, years: 25, salary: 5, education: 5, location: 5 } },
]
const statusLabels: Record<string, string> = {
  ineligible: '未通過必要條件', recommended: '建議人選', shortlisted: '入選名單', contacted: '已聯絡',
  interview: '面試中', offered: '已發 Offer', hired: '已錄取', rejected_by_manager: '主管婉拒', withdrawn: '已退出',
}
const editableStatuses: MatchStatus[] = ['recommended', 'shortlisted', 'contacted', 'interview', 'offered', 'hired', 'withdrawn']
const rejectionCategories: Array<{ value: RejectionReasonCategory; label: string }> = [
  { value: 'skills', label: '技能不足' }, { value: 'experience', label: '相關經驗不足' },
  { value: 'salary', label: '薪資期待不符' }, { value: 'location', label: '地點／通勤不符' },
  { value: 'education', label: '學歷條件不符' }, { value: 'role_fit', label: '職務方向不符' },
  { value: 'availability', label: '到職時間不符' }, { value: 'position_closed', label: '職缺暫停／關閉' },
  { value: 'other', label: '其他' },
]
const overrideCategories: Array<{ value: OverrideReasonCategory; label: string }> = [
  { value: 'transferable_skills', label: '具可轉移技能' }, { value: 'related_experience', label: '具相關經驗' },
  { value: 'learning_potential', label: '學習潛力' }, { value: 'internal_referral', label: '內部推薦' },
  { value: 'business_need', label: '業務需求例外' }, { value: 'data_incomplete', label: '資料不足，需面談確認' },
  { value: 'other', label: '其他' },
]
const decisionCategories = computed(() => decisionMode.value === 'override' ? overrideCategories : rejectionCategories)
const feedbackCategoryLabels = Object.fromEntries(rejectionCategories.map(item => [item.value, item.label]))
const overrideCategoryLabels = Object.fromEntries(overrideCategories.map(item => [item.value, item.label]))
const confidenceLabels = { high: '高', medium: '中', low: '低' } as const

watch([() => props.jobs, () => props.initialRequisitionId], ([jobs, initialRequisitionId]) => {
  if (!jobs.length) {
    selectedJobId.value = null
    return
  }
  if (initialRequisitionId && jobs.some(job => job.id === initialRequisitionId)) {
    if (selectedJobId.value !== initialRequisitionId) selectedJobId.value = initialRequisitionId
    return
  }
  if (!selectedJobId.value || !jobs.some(job => job.id === selectedJobId.value)) selectedJobId.value = jobs[0].id
}, { immediate: true })
watch(() => props.initialSource, source => {
  if (source && source !== activeSource.value) activeSource.value = source
}, { immediate: true })
watch(selectedJobId, requisitionId => emit('job-selected', requisitionId))
watch(activeSource, source => emit('source-selected', source))
watch(() => props.focusedCandidateId, () => focusRequestedCandidate())
watch(() => props.refreshKey, () => {
  void loadOverview()
})
watch([selectedJobId, activeSource], () => {
  shadowMatchId.value = null
  expandedCandidateId.value = null
  loadOverview()
}, { immediate: true })

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : '發生未預期錯誤'
}

// Composite interview score per candidate for this requisition. Loaded beside
// the match list rather than replacing it: the match score exists for everyone
// from the start, the composite only after both interview stages are submitted,
// so most rows would be blank if this took over the column.
const compositeByCandidate = ref<Record<number, number | null>>({})
async function loadCompositeScores(jobId: number, requestId: number) {
  try {
    const applications = (await hrApi.applications({ requisitionId: jobId })).data
    if (requestId !== overviewRequestSequence || selectedJobId.value !== jobId) return
    compositeByCandidate.value = Object.fromEntries(
      applications.map(application => [application.candidate_id, application.composite_score ?? null]),
    )
  } catch {
    // A missing composite is an ordinary state, not an error worth interrupting
    // the match list for.
    if (requestId === overviewRequestSequence) compositeByCandidate.value = {}
  }
}

async function loadOverview() {
  const requestId = ++overviewRequestSequence
  const jobId = selectedJobId.value
  const source = activeSource.value
  if (!jobId) {
    overview.value = null
    readiness.value = null
    criteria.value = null
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  overview.value = null
  readiness.value = null
  criteria.value = null
  criteriaImpact.value = null
  previewSignature.value = ''
  try {
    const [overviewResult, readinessResult, criteriaResult, weightsResult] = await Promise.all([
      matchingReportsApi.candidateOverview(jobId, source),
      matchingReportsApi.readiness(jobId, source),
      matchingReportsApi.matchingCriteria(jobId),
      matchingReportsApi.matchingWeights(jobId),
    ])
    if (requestId !== overviewRequestSequence || selectedJobId.value !== jobId || activeSource.value !== source) return
    overview.value = overviewResult
    readiness.value = readinessResult
    criteria.value = criteriaResult
    weights.value = weightsResult
    setWeightDraft(weightsResult)
    requiredSkillsText.value = criteriaResult.required_skills.join('、')
    preferredSkillsText.value = criteriaResult.preferred_skills.join('、')
    void loadCompositeScores(jobId, requestId)
    await focusRequestedCandidate()
  } catch (cause) {
    if (requestId === overviewRequestSequence) error.value = message(cause)
  } finally {
    if (requestId === overviewRequestSequence) loading.value = false
  }
}

function setWeightDraft(value: MatchingWeights) {
  for (const key of Object.keys(weightDraft) as Array<keyof MatchingWeights>) {
    weightDraft[key] = Math.round(Number(value[key] || 0) * 100)
  }
}

function applyWeightPreset(value: MatchingWeights) {
  Object.assign(weightDraft, value)
}

async function saveWeights() {
  if (!props.canConfigureWeights || !selectedJobId.value || weightTotal.value <= 0) {
    if (weightTotal.value <= 0) error.value = '至少一項媒合權重必須大於 0'
    return
  }
  savingWeights.value = true
  error.value = ''
  try {
    weights.value = await matchingReportsApi.updateMatchingWeights(selectedJobId.value, { ...weightDraft })
    setWeightDraft(weights.value)
    await loadOverview()
    showWeights.value = false
  } catch (cause) {
    error.value = message(cause)
  } finally {
    savingWeights.value = false
  }
}

function clearResultFilters() {
  talentSearch.value = ''
  minDisplayScore.value = 0
  onlyPassed.value = false
}

function skills(value: string) {
  return [...new Set(value.split(/[,，、\n]/).map(item => item.trim()).filter(Boolean))]
}

function nullableNumber(value: number | null | string) {
  return value === null || value === '' ? null : Number(value)
}

function criteriaPayload(): MatchingCriteria | null {
  if (!criteria.value) return null
  return {
    ...criteria.value,
    required_skills: skills(requiredSkillsText.value),
    preferred_skills: skills(preferredSkillsText.value),
    min_years: nullableNumber(criteria.value.min_years),
    salary_min: nullableNumber(criteria.value.salary_min),
    salary_max: nullableNumber(criteria.value.salary_max),
    education_req: criteria.value.education_req?.trim() || null,
    work_city: criteria.value.work_city.trim(),
    required_skill_ratio: Number(criteria.value.required_skill_ratio),
  }
}

async function previewCriteria() {
  if (!props.canConfigure || !selectedJobId.value) return
  const payload = criteriaPayload()
  if (!payload) return
  previewingCriteria.value = true
  error.value = ''
  try {
    criteriaImpact.value = await matchingReportsApi.previewMatchingCriteria(
      selectedJobId.value, payload, activeSource.value,
    )
    previewSignature.value = JSON.stringify(payload)
  } catch (cause) {
    error.value = message(cause)
  } finally {
    previewingCriteria.value = false
  }
}

async function saveCriteria() {
  if (!props.canConfigure || !selectedJobId.value || !criteria.value) return
  const payload = criteriaPayload()
  if (!payload) return
  if (previewSignature.value !== JSON.stringify(payload)) {
    await previewCriteria()
    if (!error.value) error.value = '已完成影響預覽；請確認通過與排除人數後，再按一次儲存。'
    return
  }
  savingCriteria.value = true
  error.value = ''
  try {
    criteria.value = await matchingReportsApi.updateMatchingCriteria(selectedJobId.value, payload)
    await loadOverview()
    showCriteria.value = false
  } catch (cause) {
    error.value = message(cause)
  } finally {
    savingCriteria.value = false
  }
}

async function rematch() {
  if (!props.canConfigure || !selectedJobId.value) return
  recalculating.value = true
  error.value = ''
  try {
    await matchingReportsApi.rematch(selectedJobId.value)
    await loadOverview()
  } catch (cause) {
    error.value = message(cause)
  } finally {
    recalculating.value = false
  }
}

async function updateStatus(match: MatchDto | null, event: Event) {
  if (!match) return
  const previous = match.status
  const next = (event.target as HTMLSelectElement).value as MatchStatus
  match.status = next
  try {
    Object.assign(match, await matchingReportsApi.updateMatchStatus(match.id, next))
  } catch (cause) {
    match.status = previous
    error.value = message(cause)
  }
}

function openDecision(match: MatchDto, mode: 'override' | 'reject') {
  decisionMatch.value = match
  decisionMode.value = mode
  decisionCategory.value = mode === 'override' ? overrideCategories[0].value : rejectionCategories[0].value
  decisionNote.value = ''
  decisionTargetStage.value = 'shortlisted'
}

function closeDecision() {
  if (savingDecision.value) return
  decisionMatch.value = null
  decisionMode.value = null
}

async function submitDecision() {
  const match = decisionMatch.value
  if (!match || !decisionMode.value || !decisionCategory.value) return
  if (decisionCategory.value === 'other' && !decisionNote.value.trim()) {
    error.value = '選擇「其他」時請補充說明。'
    return
  }
  savingDecision.value = true
  error.value = ''
  try {
    const updated = decisionMode.value === 'override'
      ? await matchingReportsApi.overrideMatch(
          match.id,
          decisionCategory.value as OverrideReasonCategory,
          decisionNote.value.trim(),
          decisionTargetStage.value,
        )
      : await matchingReportsApi.rejectMatch(
          match.id,
          decisionCategory.value as RejectionReasonCategory,
          decisionNote.value.trim(),
        )
    Object.assign(match, updated)
    decisionMatch.value = null
    decisionMode.value = null
  } catch (cause) {
    error.value = message(cause)
  } finally {
    savingDecision.value = false
  }
}

function part(match: MatchDto, key: string): ScorePart {
  return match.score_breakdown[key] || {}
}

function values(items: unknown[] | undefined) {
  return (items || []).map(String).filter(Boolean).join('、')
}

function resultLabel(item: CandidateMatchOverviewItem) {
  if (!item.match) return '尚未計算'
  if (!item.match.gate_passed) return '未通過必要條件'
  return `排名 #${item.match.rank ?? '—'}`
}

const gateLabels: Record<string, string> = {
  required_skills: '缺少必要技能', required_skills_unknown: '必要技能資料不足',
  minimum_years: '年資未達門檻', minimum_years_unknown: '工作年資資料不足',
  education: '學歷未達門檻', education_unknown: '學歷資料不足',
  location: '期望工作地點不符', blacklisted: '人才已列入黑名單', consent_withdrawn: '人才已撤回同意',
  candidate_deleted: '人才已刪除',
}

function gateReasons(match: MatchDto) {
  const misses = (match.score_breakdown.gate?.miss || []) as unknown[]
  return misses.map(value => gateLabels[String(value)] || String(value)).join('、')
}

function matchHighlights(match: MatchDto): MatchHighlight[] {
  if (match.highlights?.length) return match.highlights
  const scored = Object.entries(componentLabels)
    .map(([key, label]) => ({ key, label, score: Number(part(match, key).score || 0), known: part(match, key).known !== false }))
    .filter(item => item.known)
    .sort((left, right) => right.score - left.score)
  const result: MatchHighlight[] = []
  scored.filter(item => item.score >= 0.7).slice(0, 2).forEach(item => result.push({
    kind: 'strength', category: item.label, text: `${item.label}契合度 ${Math.round(item.score * 100)}%，是這位人才的主要優勢。`,
  }))
  scored.filter(item => item.score < 0.5).sort((left, right) => left.score - right.score).slice(0, 2).forEach(item => result.push({
    kind: 'concern', category: item.label, text: `${item.label}契合度 ${Math.round(item.score * 100)}%，建議在面談中進一步確認。`,
  }))
  if (!match.gate_passed) result.unshift({ kind: 'concern', category: '必要條件', text: gateReasons(match) || '有必要條件尚未符合。' })
  return result.length ? result : [{ kind: 'info', category: '整體', text: '目前資料有限，建議搭配履歷與面談內容綜合判斷。' }]
}

const highlightKindLabels: Record<MatchHighlight['kind'], string> = { strength: '優勢', concern: '待確認', info: '補充' }
const highlightCategoryLabels: Record<string, string> = {
  gate: '必要條件', skill: '技能', years: '年資', relevance: '職務相關', location: '地點', data_quality: '資料完整度',
}

function decisionCategoryLabel(match: MatchDto, type: 'feedback' | 'override') {
  const category = type === 'feedback' ? match.feedback_category : match.manual_override_category
  if (!category) return '未分類'
  return (type === 'feedback' ? feedbackCategoryLabels : overrideCategoryLabels)[category] || category
}

function dateTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-TW') : ''
}

function toggleShadow(matchId: number) {
  shadowMatchId.value = shadowMatchId.value === matchId ? null : matchId
}

async function loadCandidateDetails(item: CandidateMatchOverviewItem) {
  const candidateId = item.candidate.id
  if (candidateDetails.value[candidateId] || candidateDetailLoading.value[candidateId]) return

  candidateDetailLoading.value = { ...candidateDetailLoading.value, [candidateId]: true }
  candidateDetailErrors.value = { ...candidateDetailErrors.value, [candidateId]: '' }
  try {
    const result = await hrApi.candidate(candidateId)
    candidateDetails.value = { ...candidateDetails.value, [candidateId]: result.data }
  } catch (cause) {
    candidateDetailErrors.value = {
      ...candidateDetailErrors.value,
      [candidateId]: message(cause),
    }
  } finally {
    candidateDetailLoading.value = { ...candidateDetailLoading.value, [candidateId]: false }
  }
}

async function focusRequestedCandidate() {
  const candidateId = props.focusedCandidateId
  if (!candidateId || !overview.value) return
  const item = overview.value.items.find(candidate => candidate.candidate.id === candidateId)
  if (!item) return
  expandedCandidateId.value = candidateId
  await loadCandidateDetails(item)
}

async function toggleCandidateDetails(item: CandidateMatchOverviewItem) {
  const candidateId = item.candidate.id
  if (expandedCandidateId.value === candidateId) {
    expandedCandidateId.value = null
    if (item.match && shadowMatchId.value === item.match.id) shadowMatchId.value = null
    return
  }

  expandedCandidateId.value = candidateId
  await loadCandidateDetails(item)
}

function requestInterview(item: CandidateMatchOverviewItem) {
  if (!selectedJobId.value) return
  emit('request-interview', {
    candidateId: item.candidate.id,
    candidateName: item.candidate.name,
    requisitionId: selectedJobId.value,
    source: item.source,
    applicationId: item.application_id,
  })
}
</script>

<template>
  <section class="matching-view">
    <header v-if="!props.embedded" class="match-hero">
      <div><p>MATCHING EXPLAINABILITY</p><h1>{{ workspaceMode === 'matching' ? '職缺 × 每位人才媒合程度' : '小樣本媒合驗證' }}</h1><span>{{ workspaceMode === 'matching' ? '履歷適配只比對書面條件、不含面試，僅提供排序依據；人工招募階段與例外覆核會分開保存，不因重新計算而消失。' : '使用 50 組無真實個資案例，由 HR 與主管先盲評，再檢查排序與必要條件是否合理。' }}</span></div>
      <strong>{{ workspaceMode === 'matching' ? '系統判斷＋人工決策' : '盲評＋揭盲報表' }}<small>{{ workspaceMode === 'matching' ? '兩條資訊分開呈現' : '未知結果不顯示成 0' }}</small></strong>
    </header>

    <nav v-if="!props.embedded" class="matching-mode-tabs" role="tablist" aria-label="媒合工作模式">
      <button type="button" role="tab" :aria-selected="workspaceMode === 'matching'" :class="{ active: workspaceMode === 'matching' }" @click="workspaceMode = 'matching'">
        <strong>正式媒合</strong><small>檢視實際應徵者與人才庫推薦</small>
      </button>
      <button type="button" role="tab" :aria-selected="workspaceMode === 'benchmark'" :class="{ active: workspaceMode === 'benchmark' }" @click="workspaceMode = 'benchmark'">
        <strong>小樣本驗證</strong><small>HR／主管對合成案例獨立盲評</small>
      </button>
    </nav>

    <div v-else class="matching-advanced-switch">
      <button
        type="button"
        :data-testid="workspaceMode === 'matching' ? 'matching-open-benchmark' : 'matching-back-to-live'"
        @click="workspaceMode = workspaceMode === 'matching' ? 'benchmark' : 'matching'"
      >{{ workspaceMode === 'matching' ? '進階工具：小樣本驗證' : '返回正式人才評估' }}</button>
    </div>

    <MatchingBenchmarkPanel v-if="workspaceMode === 'benchmark'" />

    <template v-else>
    <section v-if="!props.embedded" class="matching-guide panel" aria-labelledby="matching-guide-title">
      <header><div><small>HOW TO USE</small><h2 id="matching-guide-title">依序完成 4 步驟，就能看到兩個分析按鈕</h2></div><p><strong>按鈕在哪裡？</strong>第 3 步點開一位人才後，會立刻出現在展開區最上方。</p></header>
      <ol>
        <li><b>1</b><span><strong>選擇職缺</strong><small>決定要比較的工作</small></span></li>
        <li><b>2</b><span><strong>選擇人才來源</strong><small>實際應徵或人才庫推薦</small></span></li>
        <li><b>3</b><span><strong>點開一位人才</strong><small>人才會以一人一列顯示</small></span></li>
        <li><b>4</b><span><strong>選擇分析方式</strong><small>推薦職位／指定職位匹配</small></span></li>
      </ol>
    </section>
    <section v-if="!props.embedded" class="analysis-scope panel" aria-label="初步媒合與即時分析的差異">
      <article><b>初步媒合排序</b><strong>規則分數，用於排列人才</strong><span>依技能、年資與職缺條件計算；這是可重新計算的招募排序資料。</span></article>
      <article><b>去識別化即時職位分析</b><strong>只有按下兩個分析按鈕才執行</strong><span>只讀取已核准的去識別化履歷；結果只留在目前畫面，不寫入資料庫。</span></article>
    </section>

    <section class="matching-selection panel" aria-labelledby="matching-job-title">
      <header class="selection-heading"><b>1</b><div><strong id="matching-job-title">先選擇要查看的職缺</strong><span>選完會自動載入這個職缺的人才數量。</span></div></header>
      <div class="match-toolbar">
        <label>職缺<select v-model="selectedJobId" data-testid="matching-job-select"><option :value="null" disabled>請選擇</option><option v-for="job in jobs" :key="job.id" :value="job.id">{{ job.req_no }} · {{ job.title }}</option></select></label>
        <span>{{ selectedJob ? `${selectedJob.work_city} · ${selectedJob.skills?.join('、') || '尚未設定技能'}` : '尚未選擇職缺' }}</span>
        <button v-if="props.canConfigure" class="button primary" :disabled="!selectedJobId || recalculating" @click="rematch">{{ recalculating ? '計算中…' : overview?.computed_count ? '重新計算全部人才' : '計算全部人才' }}</button>
      </div>
    </section>

    <section class="source-selector panel" aria-labelledby="matching-source-title">
      <header class="selection-heading"><b>2</b><div><strong id="matching-source-title">再選擇人才來源</strong><span>若實際應徵者是 0 人，可直接改看人才庫推薦。</span></div></header>
      <div class="source-tabs" role="tablist" aria-label="媒合人才來源">
        <button data-testid="matching-source-applicants" :class="{ active: activeSource === 'applicants' }" role="tab" :aria-selected="activeSource === 'applicants'" @click="activeSource = 'applicants'">
          <strong>實際應徵者</strong><span>已投遞此職缺的人才</span><b>{{ overview?.applicants_count ?? '—' }} 人</b>
        </button>
        <button data-testid="matching-source-talent-pool" :class="{ active: activeSource === 'talent_pool' }" role="tab" :aria-selected="activeSource === 'talent_pool'" @click="activeSource = 'talent_pool'">
          <strong>人才庫推薦</strong><span>尚未投遞，由系統協助探索</span><b>{{ overview?.talent_pool_count ?? '—' }} 人</b>
        </button>
      </div>
    </section>

    <details class="matching-settings panel">
      <summary><div><small>進階設定</small><strong>媒合權重與 HR 必要條件</strong><span>一般查看人才不需要調整；只有要改變系統排序規則時才展開。</span></div><b>展開設定</b></summary>
      <div class="matching-settings-body">
        <div class="match-formula" aria-label="目前職缺的媒合權重">
          <article v-for="item in formulaParts" :key="item.key"><b>{{ item.percent === null ? '—' : `${item.percent}%` }}</b><span>{{ item.label }}</span></article>
        </div>

        <div class="weight-explainer panel">
          <div><strong>這個職缺最重視什麼？</strong><span>目前百分比會直接影響總分。HR、管理員與該職缺的部門主管可依招募目標人工調整。</span></div>
          <button v-if="props.canConfigureWeights" class="button secondary" data-testid="matching-weight-toggle" @click="showWeights = !showWeights">{{ showWeights ? '收合權重' : '調整加權比重' }}</button>
        </div>

        <form v-if="props.canConfigureWeights && showWeights && weights" class="weight-panel panel" data-testid="matching-weight-panel" @submit.prevent="saveWeights">
          <header><div><strong>人工調整媒合權重</strong><span>數值代表相對重要程度；總和不必剛好 100，儲存時會自動正規化。</span></div><b :class="{ invalid: weightTotal <= 0 }">目前合計 {{ weightTotal }}</b></header>
          <div class="weight-presets">
            <button v-for="preset in weightPresets" :key="preset.label" type="button" @click="applyWeightPreset(preset.values)"><strong>{{ preset.label }}</strong><small>{{ preset.description }}</small></button>
          </div>
          <div class="weight-grid">
            <label v-for="item in weightItems" :key="item.key"><span><strong>{{ item.label }}</strong><output>{{ weightDraft[item.key] }}</output></span><input v-model.number="weightDraft[item.key]" :data-testid="`matching-weight-${item.key}`" type="range" min="0" max="100" step="1"></label>
          </div>
          <footer><button class="button secondary" type="button" @click="showWeights = false">取消</button><button class="button primary" data-testid="matching-weight-save" :disabled="savingWeights || weightTotal <= 0">{{ savingWeights ? '儲存並重新媒合中…' : '套用權重並重新媒合' }}</button></footer>
        </form>

        <div class="gate-explainer panel">
          <div><strong>「必要條件」是什麼？</strong><span>HR 指定的硬性門檻，例如必要技能、最低年資、學歷與地點。未通過時仍顯示原始適配分數，並清楚標示缺少哪一項，不再全部變成 0.0%。</span></div>
          <button v-if="props.canConfigure" class="button secondary" @click="showCriteria = !showCriteria">{{ showCriteria ? '收合條件' : '設定 HR 媒合條件' }}</button>
        </div>

        <form v-if="props.canConfigure && showCriteria && criteria" class="criteria-panel panel" @submit.prevent="saveCriteria">
          <header><div><strong>HR 媒合條件</strong><span>儲存後系統會立即用新條件重新計算全部人才。</span></div></header>
          <div class="criteria-grid">
            <label class="wide">必要技能（逗號分隔）<input v-model="requiredSkillsText" placeholder="例如：Python、SQL"><small>系統會依下方符合比例判定，不再固定要求全部命中。</small></label>
            <label class="wide">加分技能（逗號分隔）<input v-model="preferredSkillsText" placeholder="例如：FastAPI、Git"></label>
            <label class="wide ratio-field">必要技能最低符合比例<select v-model.number="criteria.required_skill_ratio"><option :value="0.5">50%－適合小樣本探索，保留較多可轉移人才</option><option :value="0.7">70%－兼顧必要技能與候選範圍</option><option :value="1">100%－嚴格要求全部必要技能</option></select><small>{{ requiredSkillRatioDescription }}</small></label>
            <label>最低年資<input v-model.number="criteria.min_years" type="number" min="0" max="80" step="0.5"></label><label>最低學歷<input v-model="criteria.education_req" placeholder="例如：大學"></label><label>工作地點<input v-model="criteria.work_city" required></label><label>薪資下限<input v-model.number="criteria.salary_min" type="number" min="0"></label><label>薪資上限<input v-model.number="criteria.salary_max" type="number" min="0"></label>
          </div>
          <div class="hard-gates"><label><input v-model="criteria.require_skills" type="checkbox">技能列為必要條件</label><label><input v-model="criteria.require_years" type="checkbox">年資列為必要條件</label><label><input v-model="criteria.require_education" type="checkbox">學歷列為必要條件</label><label><input v-model="criteria.require_location" type="checkbox">地點列為必要條件</label></div>
          <div v-if="criteriaImpact" class="criteria-impact"><strong>影響預覽（{{ activeSource === 'applicants' ? '實際應徵者' : '人才庫推薦' }}）</strong><span>目前通過 {{ criteriaImpact.current_passed }} 人</span><span>新條件通過 {{ criteriaImpact.preview_passed }} 人</span><span>新條件排除 {{ criteriaImpact.preview_excluded }} 人</span><small>共 {{ criteriaImpact.changed_count }} 人的必要條件結果會改變；預覽不會修改資料。</small></div>
          <footer><button type="button" class="button secondary" @click="showCriteria = false">取消</button><button type="button" class="button secondary" :disabled="previewingCriteria" @click="previewCriteria">{{ previewingCriteria ? '預覽中…' : '先預覽影響' }}</button><button class="button primary" :disabled="savingCriteria || previewingCriteria">{{ savingCriteria ? '儲存並計算中…' : '確認並重新媒合' }}</button></footer>
        </form>
      </div>
    </details>
    <div class="result-filters panel">
      <label>搜尋人才<input v-model="talentSearch" placeholder="姓名、編號或職稱"></label>
      <label>最低媒合分數<select v-model.number="minDisplayScore"><option :value="0">不限</option><option :value="50">50% 以上</option><option :value="75">75% 以上</option><option :value="90">90% 以上</option></select></label>
      <label class="check"><input v-model="onlyPassed" type="checkbox">只顯示通過必要條件</label>
      <span>顯示 {{ people.length }} / {{ allPeople.length }} 人 · 點人才列展開；只有按下分析按鈕才會計算</span>
    </div>
    <div v-if="error" class="match-error">{{ error }}</div>

    <div v-if="overview" class="people-summary panel">
      <div><span>{{ activeSource === 'applicants' ? '實際應徵者' : '人才庫推薦' }}</span><strong>{{ overview.total_candidates }}</strong></div>
      <div><span>已計算</span><strong>{{ overview.computed_count }}</strong></div>
      <div><span>尚未計算</span><strong>{{ overview.uncomputed_count }}</strong></div>
      <div><span>系統必要條件通過</span><strong>{{ eligibleTotalCount }}</strong></div>
    </div>

    <div v-if="readiness && overview?.computed_count" class="readiness panel">
      <div><span>試行狀態</span><strong>{{ readiness.pilot_status === 'ready_for_weight_tuning' ? '可調整權重' : readiness.pilot_status === 'ready_for_shadow_pilot' ? '可進行影子試行' : '需要更多人才' }}</strong></div>
      <div><span>資料完整度</span><strong>{{ Math.round(readiness.metrics.data_completeness * 100) }}%</strong></div>
      <div><span>可媒合比例</span><strong>{{ Math.round(readiness.metrics.eligibility_rate * 100) }}%</strong></div>
      <div><span>人工回饋</span><strong>{{ readiness.metrics.labeled_outcomes }} 筆</strong></div>
    </div>

    <div v-if="loading" class="match-empty panel"><span class="spinner"></span><strong>讀取每位人才的媒合狀態…</strong></div>
    <div v-else-if="!jobs.length" class="match-empty panel"><strong>尚無職缺</strong><p>請先建立職缺並設定技能與條件。</p></div>
    <div v-else-if="overview && overview.total_candidates === 0" class="match-empty panel" :data-testid="activeSource === 'applicants' ? 'matching-empty-applicants' : 'matching-empty-talent-pool'">
      <strong>{{ activeSource === 'applicants' ? '這個職缺目前沒有實際應徵者' : '目前沒有可見的人才庫推薦' }}</strong>
      <p>{{ activeSource === 'applicants' ? '因此下方不會有人才列，也不會出現職位分析按鈕。你可以直接切換到人才庫推薦，或改選其他職缺。' : '人才庫推薦會排除已投遞此職缺的人才，且主管只能看到自己部門權限範圍。' }}</p>
      <button v-if="activeSource === 'applicants' && overview.talent_pool_count > 0" class="button primary empty-source-action" type="button" data-testid="matching-show-talent-pool" @click="activeSource = 'talent_pool'">查看 {{ overview.talent_pool_count }} 位人才庫推薦</button>
    </div>
    <div v-else-if="overview && !people.length" class="match-empty panel"><strong>沒有符合目前篩選條件的人才</strong><p>請降低最低分數、取消必要條件篩選，或更換搜尋字詞。</p><button class="button secondary" type="button" @click="clearResultFilters">清除篩選</button></div>
    <div v-else-if="overview" class="match-list">
      <article v-for="item in people" :key="item.candidate.id" class="panel match-card" :class="{ pending: !item.match, expanded: expandedCandidateId === item.candidate.id }">
        <header class="match-row-summary">
          <button
            type="button"
            class="match-row-toggle"
            :aria-expanded="expandedCandidateId === item.candidate.id"
            :aria-controls="`match-detail-${item.candidate.id}`"
            :data-testid="`match-row-toggle-${item.candidate.id}`"
            @click="toggleCandidateDetails(item)"
          >
            <div class="candidate"><span>{{ item.candidate.name.slice(0, 1) }}</span><div><h2>{{ item.candidate.name }} <small>{{ item.source === 'applicant' ? '實際應徵' : '人才庫推薦' }}</small></h2><p>{{ item.candidate.code }} · {{ item.candidate.current_title || '職稱資料不足' }} · {{ item.candidate.total_years === null ? '年資資料不足' : `${item.candidate.total_years} 年` }}</p></div></div>
            <div v-if="item.match" class="score" :class="{ failed: !item.match.gate_passed }"><strong>{{ item.match.total_score.toFixed(1) }}<b>%</b></strong><small>履歷適配（未含面試）· {{ resultLabel(item) }}</small><em :data-confidence="item.match.confidence">資料 {{ Math.round(item.match.data_completeness * 100) }}% · 可信度{{ confidenceLabels[item.match.confidence] }}</em><b class="composite-chip" :class="{ empty: compositeByCandidate[item.candidate.id] === null || compositeByCandidate[item.candidate.id] === undefined }">綜合 {{ compositeByCandidate[item.candidate.id] ?? '—' }}<i>{{ compositeByCandidate[item.candidate.id] === null || compositeByCandidate[item.candidate.id] === undefined ? '兩關面試提交後產生' : '面試綜合參考分' }}</i></b></div>
            <div v-else class="score uncomputed"><strong>—</strong><small>尚未計算</small></div>
            <span class="row-action-copy">{{ expandedCandidateId === item.candidate.id ? '收合人才詳情' : '查看評估、分析與面試' }}</span>
            <span class="row-chevron" aria-hidden="true">{{ expandedCandidateId === item.candidate.id ? '−' : '＋' }}</span>
          </button>
        </header>

        <div v-if="expandedCandidateId === item.candidate.id" :id="`match-detail-${item.candidate.id}`" class="match-card-detail">
          <div v-if="candidateDetailLoading[item.candidate.id]" class="candidate-detail-state"><span class="spinner"></span>正在載入履歷與去識別化狀態…</div>
          <div v-else-if="candidateDetailErrors[item.candidate.id]" class="candidate-detail-state error">無法載入完整履歷：{{ candidateDetailErrors[item.candidate.id] }}。仍可查看既有媒合資料。</div>

          <CandidateAnalysisPanel
            v-if="!candidateDetailLoading[item.candidate.id]"
            :candidate="candidateDetails[item.candidate.id] || item.candidate"
            :resumes="candidateDetails[item.candidate.id]?.resumes || []"
            :jobs="jobs"
            :role="props.role"
            :default-requisition-id="selectedJobId"
          />

          <section class="interview-next-step" :data-source="item.source">
            <div>
              <small>NEXT STEP</small>
              <strong>{{ item.source === 'applicant' ? (props.role === 'admin' ? '查看這位應徵者的面試流程' : '安排這位應徵者的面試') : '先加入職缺，再安排面試' }}</strong>
              <p v-if="item.source === 'applicant'">會帶入目前職缺與正確的應徵紀錄，不需要重新搜尋這位人才。管理員僅能檢視，HR 與主管各自維護所屬面試階段。</p>
              <p v-else-if="props.role === 'hr'">按下後會建立這位人才在目前職缺的正式應徵紀錄，再直接帶到面試流程。</p>
              <p v-else>{{ props.role === 'admin' ? '管理員可以檢視媒合與職位分析，但面試階段由 HR 與主管分別維護；請 HR 先將人才加入目前職缺。' : '主管可以檢視媒合與職位分析，但人才庫推薦必須先由 HR 加入目前職缺。' }}</p>
            </div>
            <button
              v-if="item.source === 'applicant'"
              type="button"
              class="button primary"
              :data-testid="`matching-open-interview-${item.candidate.id}`"
              :disabled="props.interviewRequestPendingCandidateId !== null"
              @click="requestInterview(item)"
            >{{ props.interviewRequestPendingCandidateId === item.candidate.id ? '正在開啟…' : props.role === 'admin' ? '查看面試流程（唯讀）' : props.role === 'manager' ? '開啟主管面試流程' : '開啟面試安排' }}</button>
            <button
              v-else-if="props.role === 'hr'"
              type="button"
              class="button primary"
              :data-testid="`matching-add-application-${item.candidate.id}`"
              :disabled="props.interviewRequestPendingCandidateId !== null"
              @click="requestInterview(item)"
            >{{ props.interviewRequestPendingCandidateId === item.candidate.id ? '正在建立應徵紀錄…' : '加入此職缺並安排面試' }}</button>
            <span v-else class="application-required" :data-testid="`matching-application-required-${item.candidate.id}`">請 HR 先加入此職缺</span>
          </section>

          <div v-if="item.match" class="score-grid">
          <div v-for="(label, key) in componentLabels" :key="key">
            <span><b>{{ label }}</b><em>{{ part(item.match, key).known === false ? '資料不足' : `${Math.round((part(item.match, key).score || 0) * 100)}%` }}</em></span>
            <i :class="{ unknown: part(item.match, key).known === false }"><u :style="{ width: part(item.match, key).known === false ? '0%' : `${Math.round((part(item.match, key).score || 0) * 100)}%` }"></u></i>
            <small v-if="part(item.match, key).known === false" class="unknown-text">尚無足夠資料，不視為已確認不符合</small>
            <small v-else-if="part(item.match, key).hit?.length" class="hit">命中：{{ values(part(item.match, key).hit) }}</small>
            <small v-else-if="part(item.match, key).miss?.length" class="miss">缺口：{{ values(part(item.match, key).miss) }}</small>
          </div>
          </div>
          <section v-if="item.match" class="match-highlights" :aria-label="`${item.candidate.name}的媒合重點`">
          <strong>媒合重點</strong>
          <ul><li v-for="(highlight, index) in matchHighlights(item.match)" :key="`${highlight.category}-${index}`" :data-kind="highlight.kind"><b>{{ highlightKindLabels[highlight.kind] }} · {{ highlightCategoryLabels[highlight.category] || highlight.category }}</b><span>{{ highlight.text }}</span></li></ul>
          </section>
          <div v-if="item.match && !item.match.gate_passed" class="gate-warning"><strong>履歷適配 {{ item.match.total_score.toFixed(1) }}%，但必要條件未通過</strong><span>{{ gateReasons(item.match) }}</span><small v-if="!item.match.manual_override_at">這是系統判斷；授權人員可填寫原因後人工覆核，不會改寫原始分數。</small></div>
          <div v-else-if="!item.match" class="pending-message"><b>等待第一次計算</b><span>按上方「計算全部人才」後，這裡會顯示百分比與技能、年資、薪資、學歷、地點等評分依據。</span></div>

          <div v-if="item.match?.manual_override_at" class="manual-override"><strong>已人工覆核 · {{ decisionCategoryLabel(item.match, 'override') }}</strong><span>{{ item.match.manual_override_note || '未補充備註' }}</span><small>操作者 #{{ item.match.manual_override_by }} · {{ dateTime(item.match.manual_override_at) }}；系統必要條件結果仍保留。</small></div>
          <div v-if="item.match?.feedback_at" class="feedback"><strong>人工婉拒 · {{ decisionCategoryLabel(item.match, 'feedback') }}</strong><span>{{ item.match.feedback_note || item.match.feedback_reason || '未補充備註' }}</span><small>操作者 #{{ item.match.feedback_by }} · {{ dateTime(item.match.feedback_at) }}</small></div>
          <div v-if="item.match" class="shadow-tools">
          <div><strong>Gemini 語意影子比較</strong><small>實驗結果不會改變正式分數、排名或招募階段。</small></div>
          <button type="button" class="button secondary" @click="toggleShadow(item.match.id)">{{ shadowMatchId === item.match.id ? '收合影子分析' : '查看影子分析' }}</button>
          </div>
          <SemanticShadowPanel v-if="item.match && shadowMatchId === item.match.id" :match-id="item.match.id" />

          <footer>
          <div><strong>{{ item.candidate.email || '未填寫 Email' }}</strong><small>{{ item.candidate.phone || '未填寫聯絡電話' }}</small></div>
          <template v-if="item.match && props.canManage">
            <label class="stage-select">人工招募階段<select :value="item.match.status" :disabled="item.match.status === 'rejected_by_manager' || (!item.match.gate_passed && !item.match.manual_override_at)" @change="updateStatus(item.match, $event)">
              <option v-if="item.match.status === 'ineligible'" value="ineligible" disabled>未通過必要條件</option>
              <option v-for="status in editableStatuses" :key="status" :value="status">{{ statusLabels[status] }}</option>
              <option v-if="item.match.status === 'rejected_by_manager'" value="rejected_by_manager">主管婉拒</option>
            </select></label>
            <button v-if="!item.match.gate_passed && !item.match.manual_override_at" class="button override" @click="openDecision(item.match, 'override')">人工覆核</button>
            <button class="button danger" :disabled="['rejected_by_manager', 'hired'].includes(item.match.status)" @click="openDecision(item.match, 'reject')">婉拒</button>
          </template>
          <span v-else class="pending-badge">未計算</span>
          </footer>
        </div>
      </article>
    </div>

    <div v-if="decisionMatch && decisionMode" class="decision-backdrop" @click.self="closeDecision">
      <form class="decision-dialog" @submit.prevent="submitDecision">
        <header><div><small>{{ decisionMode === 'override' ? 'MANUAL OVERRIDE' : 'STRUCTURED REJECTION' }}</small><h2>{{ decisionMode === 'override' ? '人工覆核必要條件' : '記錄婉拒原因' }}</h2><p>{{ decisionMatch.candidate.name }} · 履歷適配 {{ decisionMatch.total_score.toFixed(1) }}%</p></div><button type="button" aria-label="關閉" @click="closeDecision">×</button></header>
        <div v-if="decisionMode === 'override'" class="decision-warning">覆核只會允許人才進入人工招募流程；原始必要條件結果與分數仍會保留，重新媒合也不會刪除這次決策。</div>
        <label>原因類別<select v-model="decisionCategory" required><option v-for="item in decisionCategories" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
        <label v-if="decisionMode === 'override'">覆核後階段<select v-model="decisionTargetStage"><option value="shortlisted">入選名單</option><option value="contacted">已聯絡</option><option value="interview">面試中</option></select></label>
        <label>補充備註<textarea v-model="decisionNote" rows="4" :required="decisionCategory === 'other'" :placeholder="decisionMode === 'override' ? '說明為何仍值得進一步確認' : '可補充具體觀察；選擇其他時必填'"></textarea></label>
        <footer><button type="button" class="button secondary" @click="closeDecision">取消</button><button class="button" :class="decisionMode === 'override' ? 'primary' : 'danger'" :disabled="savingDecision">{{ savingDecision ? '儲存中…' : decisionMode === 'override' ? '確認人工覆核' : '確認婉拒' }}</button></footer>
      </form>
    </div>
    </template>
  </section>
</template>

<style scoped>
.match-hero{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:12px;padding:27px 30px;border-radius:20px;background:linear-gradient(120deg,#102f47,#146b71 58%,#52a98f);color:#fff;box-shadow:0 17px 40px rgba(20,74,75,.14)}.match-hero p{margin:0;color:#f5ca77;font-size:8px;font-weight:800;letter-spacing:1.3px}.match-hero h1{margin:7px 0;font-size:25px}.match-hero span{font-size:9px;color:rgba(255,255,255,.72)}.match-hero>strong{flex:0 0 auto;padding:14px 17px;border:1px solid rgba(255,255,255,.28);border-radius:14px;background:rgba(255,255,255,.1);font-size:12px}.match-hero>strong small{display:block;margin-top:4px;color:rgba(255,255,255,.65);font-size:8px}
.match-formula{display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:13px}.match-formula article{display:flex;align-items:center;gap:8px;padding:11px;border:1px solid #deebe7;border-radius:11px;background:#fff}.match-formula b{color:#16776b;font-size:13px}.match-formula span{color:#72847f;font-size:8px}
.weight-explainer{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:15px 17px;margin-bottom:13px;border-color:#cce1dc;background:#f2f9f7}.weight-explainer div{display:flex;flex-direction:column;gap:4px}.weight-explainer strong{font-size:12px;color:#315f57}.weight-explainer span{font-size:10px;color:#61766f;line-height:1.6}.weight-panel{padding:18px;margin-bottom:14px;border-color:#bddbd3}.weight-panel>header{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.weight-panel>header strong,.weight-panel>header span{display:block}.weight-panel>header strong{font-size:14px}.weight-panel>header span{margin-top:4px;color:#71827d;font-size:10px}.weight-panel>header>b{padding:6px 9px;border-radius:99px;background:#eaf4f1;color:#287066;font-size:11px}.weight-panel>header>b.invalid{background:#fff0ef;color:#9a4943}.weight-presets{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:14px}.weight-presets button{padding:10px 11px;border:1px solid #d5e4e0;border-radius:9px;background:#fbfdfc;color:#395f58;text-align:left}.weight-presets button:hover{border-color:#7db8aa;background:#f0f9f6}.weight-presets strong,.weight-presets small{display:block}.weight-presets strong{font-size:11px}.weight-presets small{margin-top:3px;color:#71837e;font-size:9px}.weight-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:11px 18px;margin-top:16px;padding:14px;border-radius:11px;background:#f5f9f8}.weight-grid label>span{display:flex;justify-content:space-between;align-items:center}.weight-grid strong{font-size:10px;color:#45665f}.weight-grid output{min-width:35px;padding:3px 6px;border-radius:6px;background:#fff;color:#1e776b;font-size:11px;font-weight:800;text-align:center}.weight-grid input{width:100%;margin-top:8px;accent-color:#247c70}.weight-panel>footer{display:flex;justify-content:flex-end;gap:8px;margin-top:15px}
.gate-explainer{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:15px 17px;margin-bottom:13px;border-color:#ecd9ac;background:#fffaf0}.gate-explainer div{display:flex;flex-direction:column;gap:4px}.gate-explainer strong{font-size:11px;color:#705120}.gate-explainer span{font-size:9px;color:#806e4f;line-height:1.6}.criteria-panel{padding:18px;margin-bottom:14px;border-color:#cde2dc}.criteria-panel header strong,.criteria-panel header span{display:block}.criteria-panel header strong{font-size:14px}.criteria-panel header span{font-size:9px;color:#71827d;margin-top:4px}.criteria-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}.criteria-grid .wide{grid-column:span 3}.criteria-grid label{font-size:9px;color:#61736e}.criteria-grid input{display:block;width:100%;height:38px;margin-top:5px;border:1px solid #d7e3df;border-radius:8px;padding:0 10px}.criteria-grid small{display:block;margin-top:4px;color:#9a6c3f}.hard-gates{display:flex;flex-wrap:wrap;gap:17px;margin:15px 0;padding:12px;border-radius:9px;background:#f2f8f6}.hard-gates label{font-size:9px;color:#365f58}.hard-gates input{margin-right:5px}.criteria-panel footer{display:flex;justify-content:flex-end;gap:8px}.result-filters{display:flex;align-items:end;gap:12px;padding:12px 14px;margin-bottom:14px}.result-filters label{font-size:8px;color:#657872}.result-filters input:not([type=checkbox]),.result-filters select{display:block;height:36px;margin-top:4px;border:1px solid #dce5e2;border-radius:8px;background:#fff;padding:0 9px}.result-filters .check{display:flex;align-items:center;gap:5px;height:36px}.result-filters>span{margin-left:auto;font-size:9px;color:#54736d}
.match-toolbar{display:flex;align-items:end;gap:14px;padding:14px;margin-bottom:14px}.match-toolbar label{font-size:9px;color:#627570}.match-toolbar select{display:block;margin-top:5px;height:38px;min-width:310px;border:1px solid #dce5e2;border-radius:8px;background:#fff;padding:0 10px}.match-toolbar>span{flex:1;color:#758581;font-size:9px}.match-error{padding:11px 14px;background:#fff0ef;color:#943f3a;border-radius:8px;margin-bottom:12px;font-size:10px}
.people-summary,.readiness{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:14px;margin-bottom:14px}.people-summary{background:#eef8f4;border-color:#d5e9e2}.readiness{background:#fffaf1;border-color:#eadfc8}.people-summary div,.readiness div{padding:8px 10px;border-right:1px solid #d9e9e3}.people-summary div:last-child,.readiness div:last-child{border:0}.people-summary span,.people-summary strong,.readiness span,.readiness strong{display:block}.people-summary span,.readiness span{font-size:8px;color:#71827d}.people-summary strong,.readiness strong{font-size:15px;margin-top:3px;color:#276d64}
.match-empty{text-align:center;padding:70px 20px}.match-empty strong,.match-empty p{display:block;font-size:12px}.match-empty p{font-size:9px;color:#758581}.match-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.match-card{padding:18px}.match-card.pending{border-style:dashed;background:linear-gradient(145deg,#fff,#fbfcfc)}.match-card header{display:flex;justify-content:space-between;align-items:center}.candidate{display:flex;align-items:center;gap:11px}.candidate>span{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:#dfeeea;color:#286e66;font-weight:700}.candidate h2{font-size:14px;margin:0}.candidate p{font-size:8px;color:#7d8d89;margin:4px 0}.score{text-align:right;color:#216b63}.score.failed{color:#a55049}.score.uncomputed{color:#98a6a2}.score strong,.score small{display:block}.composite-chip{display:inline-block;margin-top:6px;padding:4px 9px;border-radius:99px;background:#e3f4eb;color:#1f6b60;font-size:10px;font-weight:800}.composite-chip i{display:block;margin-top:1px;color:#7f918c;font-size:8px;font-style:normal;font-weight:400}.composite-chip.empty{background:#eef2f1;color:#8b9995}.score strong{font-size:27px}.score strong b{font-size:12px;margin-left:2px}.score small{font-size:8px}
.score-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:18px 0}.score-grid>div{background:#f7f9f8;border-radius:8px;padding:10px}.score-grid span{display:flex;justify-content:space-between;font-size:9px}.score-grid em{font-style:normal;color:#47726b}.score-grid i{display:block;height:4px;background:#dfe8e5;border-radius:4px;margin:7px 0}.score-grid u{display:block;height:100%;background:#3e8c80;border-radius:4px;text-decoration:none}.score-grid small{display:block;font-size:7px;line-height:1.5}.hit{color:#39806b}.miss{color:#a65a52}.pending-message{margin:18px 0;padding:18px;border-radius:10px;background:#f4f7f6;text-align:center;color:#768783}.pending-message b,.pending-message span{display:block}.pending-message b{font-size:11px;color:#566c66}.pending-message span{margin-top:6px;font-size:8px;line-height:1.6}.feedback{padding:9px;background:#fff3e9;color:#855b37;border-radius:7px;font-size:9px;margin-bottom:12px}.feedback strong{display:block;margin-bottom:3px}
.match-highlights{margin:-4px 0 14px;padding:12px;border:1px solid #dce8e4;border-radius:9px;background:#fbfdfc}.match-highlights>strong{display:block;margin-bottom:8px;color:#315d56;font-size:11px}.match-highlights ul{list-style:none;display:grid;gap:7px;margin:0;padding:0}.match-highlights li{position:relative;padding-left:14px;color:#526c66}.match-highlights li:before{content:"";position:absolute;left:0;top:6px;width:6px;height:6px;border-radius:50%;background:#6e9189}.match-highlights li[data-kind="strength"]:before{background:#359274}.match-highlights li[data-kind="concern"]:before{background:#d18451}.match-highlights b,.match-highlights span{display:block}.match-highlights b{font-size:9px}.match-highlights span{margin-top:2px;font-size:9px;line-height:1.55}.match-highlights li[data-kind="strength"] b{color:#28765e}.match-highlights li[data-kind="concern"] b{color:#985c34}
.gate-warning{margin:-4px 0 14px;padding:10px 12px;border-left:3px solid #d68850;background:#fff5ec;color:#8a5135;border-radius:7px}.gate-warning strong,.gate-warning span{display:block;font-size:9px}.gate-warning span{margin-top:3px;font-size:8px}
.match-card footer{border-top:1px solid #edf1f0;padding-top:12px;display:flex;align-items:center;gap:8px}.match-card footer>div{flex:1}.match-card footer strong,.match-card footer small{display:block;font-size:9px}.match-card footer small{font-size:8px;color:#81908d;margin-top:3px}.match-card footer select{height:37px;border:1px solid #dce5e2;border-radius:8px;background:#fff;font-size:9px;padding:0 8px}.pending-badge{padding:7px 11px;border-radius:99px;background:#edf1f0;color:#6d7c78;font-size:8px}
.criteria-grid select{display:block;width:100%;min-height:42px;margin-top:5px;border:1px solid #d7e3df;border-radius:8px;background:#fff;padding:7px 10px;color:#3d5b55}.ratio-field small{padding:7px 9px;border-radius:7px;background:#fff8e8}.criteria-impact{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:0 0 14px;padding:13px;border:1px solid #c8dfd8;border-radius:10px;background:#f3faf7}.criteria-impact strong,.criteria-impact small{grid-column:1/-1}.criteria-impact span{padding:8px;border-radius:7px;background:#fff;color:#315f57}.criteria-impact small{color:#61766f}
.source-tabs{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}.source-tabs button{position:relative;display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:14px 16px;border:1px solid #d8e5e1;border-radius:12px;background:#fff;color:#4d6963;text-align:left}.source-tabs button.active{border-color:#3b9284;background:#eef8f5;box-shadow:0 0 0 2px rgba(59,146,132,.08)}.source-tabs strong{font-size:14px}.source-tabs span{grid-column:1;font-size:12px;color:#778883}.source-tabs b{grid-column:2;grid-row:1/3;align-self:center;font-size:22px;color:#28766b}
.candidate h2 small{display:inline-block;margin-left:5px;padding:3px 6px;border-radius:99px;background:#edf5f2;color:#4b736c;font-size:10px;vertical-align:middle}.score>em{display:block;margin-top:4px;font-size:10px;font-style:normal;color:#647a74}.score>em[data-confidence="low"]{color:#a15a43}.score-grid i.unknown{background:repeating-linear-gradient(135deg,#e3e8e6,#e3e8e6 5px,#f2f4f3 5px,#f2f4f3 10px)}.unknown-text{color:#826d4f}.gate-warning small{display:block;margin-top:6px;font-size:11px;color:#7b6757}.manual-override{padding:10px 12px;margin-bottom:12px;border-left:3px solid #3f9381;border-radius:7px;background:#edf8f4;color:#315f56}.manual-override strong,.manual-override span,.manual-override small,.feedback span,.feedback small{display:block}.manual-override span,.feedback span{margin-top:3px}.manual-override small,.feedback small{margin-top:5px;color:#71827d}.stage-select{font-size:10px;color:#60736e}.stage-select select{display:block;margin-top:3px}.button.override{border:1px solid #c28a3b;background:#fff7e8;color:#855b25}
.decision-backdrop{position:fixed;z-index:1000;inset:0;display:grid;place-items:center;padding:22px;background:rgba(15,35,39,.52);backdrop-filter:blur(3px)}.decision-dialog{width:min(520px,100%);padding:22px;border-radius:16px;background:#fff;box-shadow:0 24px 70px rgba(12,38,40,.26)}.decision-dialog>header{display:flex;justify-content:space-between;gap:16px}.decision-dialog>header small{color:#278173;font-weight:800;letter-spacing:1px}.decision-dialog h2{margin:5px 0;font-size:21px}.decision-dialog p{margin:0;color:#73847f}.decision-dialog>header>button{align-self:flex-start;border:0;background:transparent;color:#71817d;font-size:28px}.decision-warning{margin:15px 0;padding:11px;border-radius:8px;background:#fff6e7;color:#77582a;line-height:1.6}.decision-dialog>label{display:block;margin-top:14px;color:#526b65;font-weight:700}.decision-dialog select,.decision-dialog textarea{display:block;width:100%;margin-top:6px;border:1px solid #cfddd9;border-radius:8px;background:#fff;padding:10px;font:inherit}.decision-dialog>footer{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}
.matching-mode-tabs{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:0 0 14px}.matching-mode-tabs button{display:grid;gap:3px;padding:14px 16px;border:1px solid #d8e5e1;border-radius:12px;background:#fff;color:#4d6963;text-align:left;cursor:pointer}.matching-mode-tabs button.active{border-color:#338b7d;background:#edf8f5;box-shadow:0 0 0 2px rgba(51,139,125,.08)}.matching-mode-tabs strong{font-size:15px}.matching-mode-tabs small{font-size:12px;color:#758681}.shadow-tools{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 12px;padding:11px 12px;border:1px dashed #d3dfdc;border-radius:9px;background:#fbfdfc}.shadow-tools div{display:grid;gap:2px}.shadow-tools strong{font-size:13px;color:#315f57}.shadow-tools small{font-size:11px;color:#71827d}
.matching-advanced-switch{display:flex;justify-content:flex-end;margin:-2px 0 8px}.matching-advanced-switch button{padding:6px 9px;border:0;background:transparent;color:#34766c;font:inherit;font-size:12px;font-weight:700;text-decoration:underline;text-underline-offset:3px;cursor:pointer}.matching-advanced-switch button:hover{color:#175f55}.matching-advanced-switch button:focus-visible{outline:2px solid rgba(35,130,116,.3);outline-offset:2px;border-radius:5px}
/* 媒合頁資訊密度高，統一提高閱讀尺寸，避免在一般桌機解析度下需要縮放。 */
.matching-view{font-size:14px;line-height:1.55}
.matching-view .button{min-height:42px;padding:9px 15px;font-size:14px;font-weight:700}
.match-hero p{font-size:12px}.match-hero h1{font-size:28px}.match-hero span{font-size:14px;line-height:1.65}.match-hero>strong{font-size:15px}.match-hero>strong small{font-size:12px}
.match-formula b{font-size:16px}.match-formula span{font-size:13px}
.weight-explainer strong,.gate-explainer strong{font-size:15px}.weight-explainer span,.gate-explainer span{font-size:13px;line-height:1.65}
.weight-panel>header strong,.criteria-panel header strong{font-size:17px}.weight-panel>header span,.criteria-panel header span{font-size:13px;line-height:1.6}.weight-panel>header>b{font-size:13px}
.weight-presets strong{font-size:14px}.weight-presets small{font-size:12px;line-height:1.5}.weight-grid strong{font-size:13px}.weight-grid output{font-size:14px}
.criteria-grid label,.hard-gates label{font-size:13px}.criteria-grid input,.criteria-grid select{font-size:14px}.criteria-grid small{font-size:12px;line-height:1.5}.criteria-impact{font-size:13px}
.match-toolbar label,.result-filters label{font-size:13px;font-weight:600}.match-toolbar select,.result-filters input:not([type=checkbox]),.result-filters select{font-size:14px}.match-toolbar>span,.result-filters>span{font-size:13px}.match-error{font-size:14px}
.people-summary span,.readiness span{font-size:12px}.people-summary strong,.readiness strong{font-size:19px}.match-empty strong{font-size:16px}.match-empty p{font-size:13px}
.candidate>span{width:46px;height:46px;font-size:17px}.candidate h2{font-size:18px}.candidate p{font-size:13px;line-height:1.5}.score strong{font-size:32px}.score strong b{font-size:16px}.score small{font-size:13px}
.score-grid span{font-size:13px}.score-grid small{font-size:12px;line-height:1.65}.score-grid i{height:6px}
.pending-message b{font-size:15px}.pending-message span{font-size:13px}.feedback,.manual-override{font-size:13px;line-height:1.55}
.match-highlights>strong{font-size:15px}.match-highlights b{font-size:13px}.match-highlights span{font-size:13px;line-height:1.65}.match-highlights li:before{top:8px;width:7px;height:7px}
.gate-warning strong{font-size:14px}.gate-warning span{font-size:13px;line-height:1.55}
.match-card footer strong{font-size:14px}.match-card footer small{font-size:13px}.match-card footer select{height:42px;font-size:14px}.pending-badge{font-size:13px}
@media(max-width:1050px){.match-list{grid-template-columns:1fr}.match-toolbar,.result-filters{align-items:stretch;flex-direction:column}.match-toolbar select{width:100%;min-width:0}.result-filters>span{margin-left:0}.people-summary,.readiness{grid-template-columns:1fr 1fr}.match-formula{grid-template-columns:repeat(3,1fr)}.criteria-grid{grid-template-columns:1fr 1fr}.criteria-grid .wide{grid-column:span 2}}@media(max-width:650px){.match-hero,.gate-explainer,.weight-explainer{align-items:flex-start;flex-direction:column;padding:22px 19px}.matching-mode-tabs,.match-formula{grid-template-columns:1fr}.criteria-grid,.weight-grid,.weight-presets,.source-tabs,.criteria-impact{grid-template-columns:1fr}.criteria-grid .wide,.criteria-impact strong,.criteria-impact small{grid-column:span 1}.match-card footer,.shadow-tools{align-items:stretch;flex-direction:column}.stage-select select{width:100%}}

/* 人才結果採單欄摺疊列：摘要永遠可見，昂貴或敏感內容只在使用者展開後掛載。 */
.match-list{grid-template-columns:1fr;gap:10px}
.match-card{padding:0;overflow:hidden;transition:border-color .18s ease,box-shadow .18s ease}
.match-card.expanded{border-color:#8fc4b7;box-shadow:0 8px 24px rgba(31,91,81,.08)}
.match-card>.match-row-summary{display:block;width:100%}
.match-row-toggle{display:grid;grid-template-columns:minmax(0,1fr) auto 36px;align-items:center;gap:18px;width:100%;padding:15px 18px;border:0;background:#fff;color:inherit;text-align:left;cursor:pointer}
.match-row-toggle:hover{background:#f5faf8}.match-row-toggle:focus-visible{outline:3px solid rgba(35,130,116,.2);outline-offset:-3px}
.match-card.pending .match-row-toggle{background:linear-gradient(145deg,#fff,#fbfcfc)}
.match-row-toggle .candidate{min-width:0}.match-row-toggle .candidate>div{min-width:0}.match-row-toggle .candidate h2,.match-row-toggle .candidate p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.match-row-toggle .score{min-width:170px}.match-row-toggle .row-chevron{width:30px;height:30px;display:grid;place-items:center;border:1px solid #cfe0db;border-radius:50%;background:#f3f8f6;color:#236f64;font-size:18px;font-weight:500}
.match-card-detail{padding:2px 18px 18px;border-top:1px solid #e0ebe7;background:#fff}
.candidate-detail-state{display:flex;align-items:center;gap:8px;margin:14px 0 0;padding:10px 12px;border-radius:8px;background:#eef7f4;color:#3b6e65;font-size:12px}.candidate-detail-state.error{background:#fff1ef;color:#93483e}
.match-card-detail>.candidate-analysis-panel{margin:16px 0}
.matching-guide{display:grid;gap:13px;margin-bottom:12px;padding:16px 18px;border-color:#b8dcd3;background:linear-gradient(110deg,#eff9f6,#fff)}
.matching-guide>header{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.matching-guide>header small{color:#268174;font-size:10px;font-weight:900;letter-spacing:1px}.matching-guide h2{margin:3px 0 0;color:#194f48;font-size:17px}.matching-guide>header p{max-width:470px;margin:0;padding:9px 11px;border-radius:8px;background:#fff4d9;color:#72551f;font-size:12px;line-height:1.5}.matching-guide>header p strong{display:block}
.matching-guide ol{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:0;padding:0;list-style:none}.matching-guide li{display:flex;align-items:center;gap:9px;padding:10px 11px;border:1px solid #d7e7e2;border-radius:9px;background:#fff}.matching-guide li>b,.selection-heading>b{width:27px;height:27px;flex:0 0 auto;display:grid;place-items:center;border-radius:50%;background:#1c7c70;color:#fff;font-size:12px}.matching-guide li span,.matching-guide li strong,.matching-guide li small{display:block}.matching-guide li strong{color:#285c54;font-size:12px}.matching-guide li small{margin-top:2px;color:#748681;font-size:10px}
.matching-selection,.source-selector{margin-bottom:12px;padding:14px 16px}.selection-heading{display:flex;align-items:center;gap:10px}.selection-heading>div>*{display:block}.selection-heading strong{color:#235a52;font-size:14px}.selection-heading span{margin-top:2px;color:#72847f;font-size:11px}.matching-selection .match-toolbar{margin:12px 0 0;padding:0;border:0;background:transparent}.matching-selection .match-toolbar label{font-size:12px}.matching-selection .match-toolbar select{min-width:360px}.source-selector .source-tabs{margin:12px 0 0}
.matching-settings{margin-bottom:12px;padding:0;overflow:hidden}.matching-settings>summary{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:13px 16px;cursor:pointer;list-style:none}.matching-settings>summary::-webkit-details-marker{display:none}.matching-settings>summary div>*{display:block}.matching-settings>summary small{color:#8a651f;font-size:9px;font-weight:900;letter-spacing:.8px}.matching-settings>summary strong{margin-top:2px;color:#315c54;font-size:13px}.matching-settings>summary span{margin-top:2px;color:#758681;font-size:10px}.matching-settings>summary>b{padding:7px 10px;border:1px solid #d5e3df;border-radius:7px;background:#fff;color:#286d63;font-size:11px}.matching-settings[open]>summary{border-bottom:1px solid #dfe9e6;background:#f8fbfa}.matching-settings[open]>summary>b{background:#e6f3ef}.matching-settings-body{padding:14px;background:#f8fbfa}.matching-settings-body>.match-formula,.matching-settings-body>.weight-explainer,.matching-settings-body>.gate-explainer{margin-bottom:10px}
.analysis-scope{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:12px;padding:12px;border-color:#cfe2dd;background:#f8fbfa}.analysis-scope article{padding:12px 14px;border:1px solid #dce9e5;border-radius:10px;background:#fff}.analysis-scope article:nth-child(2){border-color:#b9ddd4;background:#eff9f6}.analysis-scope b,.analysis-scope strong,.analysis-scope span{display:block}.analysis-scope b{color:#26776b;font-size:10px;letter-spacing:.4px}.analysis-scope strong{margin-top:3px;color:#315d56;font-size:13px}.analysis-scope span{margin-top:3px;color:#6f827d;font-size:11px;line-height:1.55}
.interview-next-step{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:4px 0 16px;padding:14px 15px;border:1px solid #bcded5;border-radius:11px;background:linear-gradient(105deg,#eef9f6,#fff)}.interview-next-step>div{min-width:0}.interview-next-step small,.interview-next-step strong,.interview-next-step p{display:block}.interview-next-step small{color:#237c70;font-size:9px;font-weight:900;letter-spacing:1px}.interview-next-step strong{margin-top:3px;color:#245a52;font-size:14px}.interview-next-step p{margin:3px 0 0;color:#687c76;font-size:11px;line-height:1.55}.interview-next-step>.button,.application-required{flex:0 0 auto}.application-required{padding:9px 12px;border:1px solid #e6c785;border-radius:8px;background:#fff8e8;color:#7b5a22;font-size:11px;font-weight:800}
.empty-source-action{margin-top:10px}.row-action-copy{padding:7px 10px;border:1px solid #bcd9d2;border-radius:8px;background:#eef8f5;color:#236b61;font-size:11px;font-weight:800;white-space:nowrap}
.match-row-toggle{grid-template-columns:minmax(0,1fr) auto auto 36px}
@media(max-width:900px){.matching-guide>header{align-items:stretch;flex-direction:column}.matching-guide>header p{max-width:none}.matching-guide ol{grid-template-columns:1fr 1fr}.matching-selection .match-toolbar{align-items:stretch;flex-direction:column}.matching-selection .match-toolbar select{width:100%;min-width:0}.interview-next-step{align-items:stretch;flex-direction:column}.interview-next-step>.button,.application-required{width:100%;text-align:center}}
@media(max-width:720px){.matching-guide ol,.analysis-scope{grid-template-columns:1fr}.source-tabs{grid-template-columns:1fr}.match-row-toggle{grid-template-columns:minmax(0,1fr) 32px;gap:10px;padding:13px}.match-row-toggle .score{grid-column:1;grid-row:2;min-width:0;text-align:left}.match-row-toggle .score strong{display:inline;font-size:24px}.match-row-toggle .score small,.match-row-toggle .score em{display:inline;margin-left:8px}.match-row-toggle .row-action-copy{display:none}.match-row-toggle .row-chevron{grid-column:2;grid-row:1/3}.match-card-detail{padding-inline:13px}}
</style>
