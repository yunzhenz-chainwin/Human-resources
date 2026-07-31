import { apiRequest } from './hrApi'

export type BenchmarkVerdict = 'interview' | 'consider' | 'reject' | 'insufficient_data'
export type BenchmarkReason =
  | 'strong_evidence'
  | 'skill_gap'
  | 'experience_gap'
  | 'role_relevance'
  | 'salary_mismatch'
  | 'location_mismatch'
  | 'education_gap'
  | 'transferable_experience'
  | 'missing_information'
  | 'other'

export type BenchmarkProgressRole = {
  role: 'hr' | 'manager'
  completed: number
  total: number
  complete_reviewer_count: number
}

export type BenchmarkSuite = {
  key: string
  title: string
  fixture_version: string
  scoring_version: string
  status: 'blind' | 'revealed'
  case_count: number
  revealed_at: string | null
  progress: BenchmarkProgressRole[]
}

export type BenchmarkRating = {
  verdict: BenchmarkVerdict
  reasons: BenchmarkReason[]
  note: string | null
  priority_rank: number | null
  updated_at: string
}

export type BlindBenchmarkCase = {
  case_key: string
  sequence: number
  job_key: string
  job_profile: {
    title: string
    work_city: string
    salary_min: number
    salary_max: number
    min_years: number
    required_skills: string[]
    preferred_skills: string[]
    [key: string]: unknown
  }
  candidate_profile: {
    synthetic_code: string
    current_title: string | null
    total_years: number | null
    skills: string[]
    highest_education: string | null
    expected_cities: string[] | null
    expected_salary_min: number | null
    expected_salary_max: number | null
    summary: string | null
  }
  my_rating: BenchmarkRating | null
}

export type BlindBenchmarkCaseList = {
  suite: BenchmarkSuite
  reviewer_role: 'hr' | 'manager'
  cases: BlindBenchmarkCase[]
}

export type MetricResult = {
  status: 'available' | 'insufficient_data'
  value: number | null
  numerator: number | null
  denominator: number | null
  unit: 'percent' | 'count' | 'score'
  explanation: string
}

export type BenchmarkReport = {
  suite: BenchmarkSuite
  generated_at: string
  metrics: Record<string, MetricResult>
  warnings: string[]
  cases: Array<{
    case_key: string
    job_key: string
    scenario: string
    expected_verdict: BenchmarkVerdict
    system_score: number
    system_gate_passed: boolean
    data_completeness: number
    system_gate_misses: string[]
    hr_verdict: BenchmarkVerdict | null
    manager_verdict: BenchmarkVerdict | null
  }>
}

export type BenchmarkRatingWrite = {
  verdict: BenchmarkVerdict
  reasons: BenchmarkReason[]
  note?: string | null
  priority_rank?: number | null
}

export const matchingBenchmarkApi = {
  suites: async () => (await apiRequest<BenchmarkSuite[]>('/matching-benchmark/suites')).data,
  cases: async (suiteKey: string) => (
    await apiRequest<BlindBenchmarkCaseList>(
      `/matching-benchmark/suites/${encodeURIComponent(suiteKey)}/cases`,
    )
  ).data,
  saveRating: async (suiteKey: string, caseKey: string, payload: BenchmarkRatingWrite) => (
    await apiRequest<BenchmarkRating>(
      `/matching-benchmark/suites/${encodeURIComponent(suiteKey)}/cases/${encodeURIComponent(caseKey)}/my-rating`,
      { method: 'PUT', body: JSON.stringify(payload) },
    )
  ).data,
  reveal: async (suiteKey: string) => (
    await apiRequest<BenchmarkSuite>(
      `/matching-benchmark/suites/${encodeURIComponent(suiteKey)}/reveal`,
      { method: 'POST' },
    )
  ).data,
  report: async (suiteKey: string) => (
    await apiRequest<BenchmarkReport>(
      `/matching-benchmark/suites/${encodeURIComponent(suiteKey)}/report`,
    )
  ).data,
}

