import { apiRequest } from './hrApi'

export type RequestAdapter = <T>(path: string, init?: RequestInit) => Promise<T>

let injectedRequest: RequestAdapter | null = null

export function configureMatchingReportsRequest(adapter: RequestAdapter) {
  injectedRequest = adapter
}

async function defaultRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await apiRequest<T>(path, init)).data
}

function request<T>(path: string, init?: RequestInit) {
  return (injectedRequest || defaultRequest)<T>(path, init)
}

export type MatchStatus = 'ineligible' | 'recommended' | 'shortlisted' | 'contacted' |
  'interview' | 'offered' | 'hired' | 'rejected_by_manager' | 'withdrawn'
export type MatchSource = 'all' | 'applicants' | 'talent_pool'

export type ScorePart = {
  score?: number
  contribution?: number
  weight?: number
  hit?: unknown[]
  miss?: unknown[]
  known?: boolean
}

export type MatchHighlight = {
  kind: 'strength' | 'concern' | 'info'
  category: string
  text: string
}

export type MatchingWeights = {
  skill: number
  relevance: number
  years: number
  salary: number
  education: number
  location: number
}

export type MatchDto = {
  id: number
  requisition_id: number
  candidate_id: number
  candidate: {
    id: number
    code: string
    name: string
    current_title: string | null
    total_years: number | null
    phone: string | null
    email: string | null
  }
  gate_passed: boolean
  total_score: number
  score_breakdown: Record<string, ScorePart>
  rank: number | null
  status: MatchStatus
  recruitment_stage: MatchStatus
  stage_updated_by: number | null
  stage_updated_at: string | null
  manual_override_category: string | null
  manual_override_note: string | null
  manual_override_by: number | null
  manual_override_at: string | null
  feedback_category: string | null
  feedback_note: string | null
  feedback_reason: string | null
  feedback_by: number | null
  feedback_at: string | null
  computed_at: string
  highlights: MatchHighlight[]
  data_completeness: number
  confidence: 'high' | 'medium' | 'low'
}

export type MatchList = { items: MatchDto[]; total: number }
export type CandidateMatchOverviewItem = {
  candidate: MatchDto['candidate']
  match: MatchDto | null
  source: 'applicant' | 'talent_pool'
  application_id: number | null
}
export type CandidateMatchOverview = {
  items: CandidateMatchOverviewItem[]
  source: MatchSource
  total_candidates: number
  computed_count: number
  uncomputed_count: number
  applicants_count: number
  talent_pool_count: number
}
export type MatchingCriteria = {
  required_skills: string[]
  preferred_skills: string[]
  min_years: number | null
  education_req: string | null
  work_city: string
  salary_min: number | null
  salary_max: number | null
  require_skills: boolean
  require_years: boolean
  require_education: boolean
  require_location: boolean
  required_skill_ratio: number
  weights: MatchingWeights
}
export type MatchingCriteriaImpact = {
  source: MatchSource
  total_candidates: number
  current_passed: number
  preview_passed: number
  preview_excluded: number
  changed_count: number
}
export type RejectionReasonCategory = 'skills' | 'experience' | 'salary' | 'location' |
  'education' | 'role_fit' | 'availability' | 'position_closed' | 'other'
export type OverrideReasonCategory = 'transferable_skills' | 'related_experience' |
  'learning_potential' | 'internal_referral' | 'business_need' | 'data_incomplete' | 'other'
export type MatchReadiness = {
  strategy: string
  pilot_status: 'needs_candidates' | 'ready_for_shadow_pilot' | 'ready_for_weight_tuning'
  metrics: {
    candidate_count: number
    eligible_count: number
    eligibility_rate: number
    average_eligible_score: number
    data_completeness: number
    labeled_outcomes: number
    feedback_coverage: number
    positive_outcomes: number
    precision_at_5: number | null
  }
  adopted_capabilities: string[]
  next_experiments: string[]
  excluded_features: string[]
}

export type ReportFilters = { from?: string; to?: string; department_id?: number }
export type FunnelReport = {
  total: number
  stages: { stage: string; count: number; conversion_rate: number }[]
}
export type TimeToFillReport = {
  filled_count: number
  average_days: number
  items: { requisition_id: number; req_no: string; title: string; department_id: number | null; days: number }[]
}
export type SourcesReport = {
  total: number
  items: { source: string; total: number; hired: number; hire_rate: number }[]
}
export type Distribution = { label: string; count: number }
export type TalentPoolReport = {
  total: number
  skills: Distribution[]
  experience: Distribution[]
  cities: Distribution[]
  education: Distribution[]
  monthly_growth: { month: string; count: number }[]
}

function query(filters: ReportFilters) {
  const params = new URLSearchParams()
  if (filters.from) params.set('from', filters.from)
  if (filters.to) params.set('to', filters.to)
  if (filters.department_id) params.set('department_id', String(filters.department_id))
  const value = params.toString()
  return value ? `?${value}` : ''
}

export const matchingReportsApi = {
  candidateOverview: (requisitionId: number, source: MatchSource = 'all') =>
    request<CandidateMatchOverview>(`/requisitions/${requisitionId}/candidate-match-overview?source=${source}`),
  matchingCriteria: (requisitionId: number) =>
    request<MatchingCriteria>(`/requisitions/${requisitionId}/matching-criteria`),
  updateMatchingCriteria: (requisitionId: number, criteria: MatchingCriteria) =>
    request<MatchingCriteria>(`/requisitions/${requisitionId}/matching-criteria`, {
      method: 'PUT', body: JSON.stringify(criteria),
    }),
  previewMatchingCriteria: (requisitionId: number, criteria: MatchingCriteria, source: MatchSource) =>
    request<MatchingCriteriaImpact>(`/requisitions/${requisitionId}/matching-criteria/preview?source=${source}`, {
      method: 'POST', body: JSON.stringify(criteria),
    }),
  matchingWeights: (requisitionId: number) =>
    request<MatchingWeights>(`/requisitions/${requisitionId}/matching-weights`),
  updateMatchingWeights: (requisitionId: number, weights: MatchingWeights) =>
    request<MatchingWeights>(`/requisitions/${requisitionId}/matching-weights`, {
      method: 'PUT', body: JSON.stringify(weights),
    }),
  matches: (requisitionId: number, includeIneligible = true) =>
    request<MatchList>(`/requisitions/${requisitionId}/matches?include_ineligible=${includeIneligible}`),
  candidateMatch: (requisitionId: number, candidateId: number) =>
    request<MatchDto>(`/requisitions/${requisitionId}/candidates/${candidateId}/match`),
  rematch: (requisitionId: number) =>
    request<MatchList>(`/requisitions/${requisitionId}/rematch`, { method: 'POST' }),
  readiness: (requisitionId: number, source: MatchSource = 'all') =>
    request<MatchReadiness>(`/requisitions/${requisitionId}/match-readiness?source=${source}`),
  updateMatchStatus: (matchId: number, status: MatchStatus) =>
    request<MatchDto>(`/matches/${matchId}/status`, {
      method: 'POST', body: JSON.stringify({ status }),
    }),
  rejectMatch: (matchId: number, reasonCategory: RejectionReasonCategory, note: string) =>
    request<MatchDto>(`/matches/${matchId}/feedback`, {
      method: 'POST', body: JSON.stringify({ status: 'rejected_by_manager', reason_category: reasonCategory, note }),
    }),
  overrideMatch: (matchId: number, reasonCategory: OverrideReasonCategory, note: string, targetStage: MatchStatus) =>
    request<MatchDto>(`/matches/${matchId}/manual-override`, {
      method: 'POST', body: JSON.stringify({ reason_category: reasonCategory, note, target_stage: targetStage }),
    }),
  funnel: (filters: ReportFilters) => request<FunnelReport>(`/reports/funnel${query(filters)}`),
  timeToFill: (filters: ReportFilters) =>
    request<TimeToFillReport>(`/reports/time-to-fill${query(filters)}`),
  sources: (filters: ReportFilters) => request<SourcesReport>(`/reports/sources${query(filters)}`),
  talentPool: (filters: ReportFilters) =>
    request<TalentPoolReport>(`/reports/talent-pool${query(filters)}`),
}
