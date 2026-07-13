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

export type ScorePart = {
  score?: number
  contribution?: number
  weight?: number
  hit?: unknown[]
  miss?: unknown[]
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
  feedback_reason: string | null
  feedback_at: string | null
  computed_at: string
}

export type MatchList = { items: MatchDto[]; total: number }

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
  matches: (requisitionId: number, includeIneligible = true) =>
    request<MatchList>(`/requisitions/${requisitionId}/matches?include_ineligible=${includeIneligible}`),
  rematch: (requisitionId: number) =>
    request<MatchList>(`/requisitions/${requisitionId}/rematch`, { method: 'POST' }),
  updateMatchStatus: (matchId: number, status: MatchStatus) =>
    request<MatchDto>(`/matches/${matchId}/status`, {
      method: 'POST', body: JSON.stringify({ status }),
    }),
  rejectMatch: (matchId: number, reason: string) =>
    request<MatchDto>(`/matches/${matchId}/feedback`, {
      method: 'POST', body: JSON.stringify({ status: 'rejected_by_manager', reason }),
    }),
  funnel: (filters: ReportFilters) => request<FunnelReport>(`/reports/funnel${query(filters)}`),
  timeToFill: (filters: ReportFilters) =>
    request<TimeToFillReport>(`/reports/time-to-fill${query(filters)}`),
  sources: (filters: ReportFilters) => request<SourcesReport>(`/reports/sources${query(filters)}`),
  talentPool: (filters: ReportFilters) =>
    request<TalentPoolReport>(`/reports/talent-pool${query(filters)}`),
}
