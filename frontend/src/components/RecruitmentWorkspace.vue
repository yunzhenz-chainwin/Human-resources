<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { hrApi, type ApplicationDto, type RequisitionDto } from '../services/hrApi'
import type { UserRole } from '../services/auth'
import type { MatchSource } from '../services/matchingReportsApi'
import InterviewManagement from './InterviewManagement.vue'
import MatchingView from './MatchingView.vue'

type WorkspaceMode = 'matching' | 'interviews'
type InterviewRequest = {
  candidateId: number
  candidateName: string
  requisitionId: number
  source: 'applicant' | 'talent_pool'
  applicationId: number | null
}
// Entry point handed in by another page (today: 人才庫) so the recruiter lands on one
// candidate's interview card instead of searching the matching list again.
type WorkspaceInterviewFocus = {
  candidateId: number
  candidateName: string
  requisitionId: number
  applicationId: number | null
}

const props = withDefaults(defineProps<{
  jobs: RequisitionDto[]
  role: UserRole
  canConfigure?: boolean
  canConfigureWeights?: boolean
  canManage?: boolean
  initialMode?: WorkspaceMode
  initialFocus?: WorkspaceInterviewFocus | null
  refreshKey?: number
}>(), {
  canConfigure: false,
  canConfigureWeights: false,
  canManage: false,
  initialMode: 'matching',
  initialFocus: null,
  refreshKey: 0,
})

// Seed the incoming focus synchronously so the interview card is already the one on screen
// while `openInterview` re-resolves (and, when needed, creates) the application record.
const mode = ref<WorkspaceMode>(props.initialFocus ? 'interviews' : props.initialMode)
const selectedRequisitionId = ref<number | null>(props.initialFocus?.requisitionId ?? props.jobs[0]?.id ?? null)
const selectedSource = ref<Exclude<MatchSource, 'all'>>('applicants')
const focusedCandidateId = ref<number | null>(props.initialFocus?.candidateId ?? null)
const focusedApplicationId = ref<number | null>(props.initialFocus?.applicationId ?? null)
const interviewFocusRequestKey = ref(0)
const pendingCandidateId = ref<number | null>(null)
const bridgeError = ref('')

const canCreateApplication = computed(() => props.role === 'hr')

watch(() => props.jobs, jobs => {
  if (!jobs.length) {
    selectedRequisitionId.value = null
    return
  }
  if (!selectedRequisitionId.value || !jobs.some(job => job.id === selectedRequisitionId.value)) {
    selectedRequisitionId.value = jobs[0].id
  }
}, { immediate: true })

function errorMessage(cause: unknown) {
  return cause instanceof Error ? cause.message : '無法銜接人才評估與面試流程'
}

function selectMatchingMode() {
  mode.value = 'matching'
  bridgeError.value = ''
}

function selectInterviewMode() {
  focusedApplicationId.value = null
  focusedCandidateId.value = null
  interviewFocusRequestKey.value += 1
  mode.value = 'interviews'
  bridgeError.value = ''
}

async function findApplication(candidateId: number, requisitionId: number) {
  const applications = (await hrApi.applications({ requisitionId })).data
  return applications.find(application => (
    application.candidate_id === candidateId && application.requisition_id === requisitionId
  )) || null
}

async function resolveApplication(request: InterviewRequest): Promise<ApplicationDto> {
  const existing = await findApplication(request.candidateId, request.requisitionId)
  if (existing) return existing

  if (request.source === 'applicant') {
    throw new Error('找不到這位人才在目前職缺的應徵紀錄，請重新同步後再試。')
  }
  if (!canCreateApplication.value) {
    throw new Error('人才庫推薦必須先由 HR 加入這個職缺，主管才能安排面試。')
  }

  try {
    return (await hrApi.createApplication({
      candidate_id: request.candidateId,
      requisition_id: request.requisitionId,
    })).data
  } catch (cause) {
    // A second recruiter may have assigned the same person moments earlier.
    // Resolve the exact candidate + requisition pair before surfacing an error.
    const concurrentlyCreated = await findApplication(request.candidateId, request.requisitionId)
    if (concurrentlyCreated) return concurrentlyCreated
    throw cause
  }
}

function syncInterviewRequisition(requisitionId: number | null) {
  selectedRequisitionId.value = requisitionId
  selectedSource.value = 'applicants'
  focusedCandidateId.value = null
  focusedApplicationId.value = null
}

function syncMatchingRequisition(requisitionId: number | null) {
  if (selectedRequisitionId.value !== requisitionId) {
    focusedCandidateId.value = null
    focusedApplicationId.value = null
  }
  selectedRequisitionId.value = requisitionId
}

function syncMatchingSource(source: Exclude<MatchSource, 'all'>) {
  if (selectedSource.value !== source) {
    focusedCandidateId.value = null
    focusedApplicationId.value = null
  }
  selectedSource.value = source
}

async function openInterview(request: InterviewRequest) {
  if (pendingCandidateId.value !== null) return
  pendingCandidateId.value = request.candidateId
  bridgeError.value = ''
  try {
    const application = await resolveApplication(request)
    selectedRequisitionId.value = request.requisitionId
    selectedSource.value = 'applicants'
    focusedCandidateId.value = request.candidateId
    focusedApplicationId.value = application.id
    interviewFocusRequestKey.value += 1
    mode.value = 'interviews'
  } catch (cause) {
    bridgeError.value = `${request.candidateName}：${errorMessage(cause)}`
  } finally {
    pendingCandidateId.value = null
  }
}

// A focus handed in from another page reuses the exact matching-page path, so the
// "create the application if it does not exist yet" behaviour stays in one place.
onMounted(() => {
  if (!props.initialFocus) return
  void openInterview({ ...props.initialFocus, source: 'talent_pool' })
})
</script>

<template>
  <section class="recruitment-workspace" data-testid="unified-talent-workspace">
    <nav class="workspace-tabs" role="tablist" aria-label="人才評估與面試功能">
      <button
        type="button"
        role="tab"
        data-testid="unified-workspace-mode-matching"
        :aria-selected="mode === 'matching'"
        :class="{ active: mode === 'matching' }"
        @click="selectMatchingMode"
      >
        <span><strong>人才評估</strong><small>選職缺、條列比較、按需分析</small></span>
      </button>
      <button
        type="button"
        role="tab"
        data-testid="unified-workspace-mode-interviews"
        :aria-selected="mode === 'interviews'"
        :class="{ active: mode === 'interviews' }"
        @click="selectInterviewMode"
      >
        <span><strong>面試流程</strong><small>安排時間、產生題目與填寫紀錄</small></span>
      </button>
    </nav>

    <div v-if="bridgeError" class="workspace-alert" role="alert">
      <div><strong>無法開啟面試流程</strong><span>{{ bridgeError }}</span></div>
      <button type="button" aria-label="關閉錯誤訊息" @click="bridgeError = ''">×</button>
    </div>

    <MatchingView
      v-if="mode === 'matching'"
      embedded
      :jobs="jobs"
      :role="role"
      :can-configure="canConfigure"
      :can-configure-weights="canConfigureWeights"
      :can-manage="canManage"
      :initial-requisition-id="selectedRequisitionId"
      :initial-source="selectedSource"
      :focused-candidate-id="focusedCandidateId"
      :interview-request-pending-candidate-id="pendingCandidateId"
      :refresh-key="refreshKey"
      @job-selected="syncMatchingRequisition"
      @source-selected="syncMatchingSource"
      @request-interview="openInterview"
    />

    <InterviewManagement
      v-else
      embedded
      :available-jobs="jobs"
      :focus-requisition-id="selectedRequisitionId"
      :focus-application-id="focusedApplicationId"
      :focus-request-key="interviewFocusRequestKey"
      :refresh-key="refreshKey"
      @back-to-assessment="selectMatchingMode"
      @requisition-selected="syncInterviewRequisition"
    />
  </section>
</template>

<style scoped>
.recruitment-workspace{width:100%}.workspace-tabs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:12px}.workspace-tabs button{display:flex;align-items:center;min-height:58px;padding:10px 16px;border:1px solid #d5e3df;border-radius:12px;background:#fff;color:#42645e;text-align:left;box-shadow:0 5px 16px rgba(36,84,78,.04)}.workspace-tabs button:hover{border-color:#82b9ad}.workspace-tabs button.active{border-color:#188578;background:#edf8f5;box-shadow:inset 0 0 0 1px rgba(24,133,120,.12)}.workspace-tabs span,.workspace-tabs strong,.workspace-tabs small{display:block}.workspace-tabs strong{font-size:15px}.workspace-tabs small{margin-top:2px;color:#73847f;font-size:12px}.workspace-alert{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:12px;padding:12px 14px;border:1px solid #efb7b2;border-radius:10px;background:#fff2f1;color:#8b403b}.workspace-alert strong,.workspace-alert span{display:block}.workspace-alert strong{font-size:13px}.workspace-alert span{margin-top:3px;font-size:12px}.workspace-alert button{border:0;background:transparent;color:inherit;font-size:18px;line-height:1}
@media(max-width:620px){.workspace-tabs{grid-template-columns:1fr}}
</style>
