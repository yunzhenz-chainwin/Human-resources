export type ApiResult<T> = { data: T }

export type CandidateStatus = 'new' | 'contacted' | 'priority' | 'interviewing' | 'archived'
export type CandidateDto = {
  id: number
  code: string
  name: string
  email: string | null
  phone: string | null
  city: string | null
  current_title: string | null
  total_years: number | null
  source: string | null
  status: CandidateStatus | string
  has_photo: boolean
  photo_updated_at: string | null
  retention_years_override: number | null
  retention_until?: string | null
  created_at: string
  updated_at: string
}
export type CandidateEducationDto = {
  id: number
  school: string
  major: string | null
  degree: string | null
  start_ym: string | null
  end_ym: string | null
  is_graduated: boolean | null
  sort_order: number
}
export type CandidateExperienceDto = {
  id: number
  company: string
  title: string
  industry: string | null
  start_ym: string | null
  end_ym: string | null
  years: number | null
  description: string | null
  sort_order: number
}
export type CandidateWrite = {
  name?: string
  email?: string | null
  phone?: string | null
  city?: string | null
  current_title?: string | null
  total_years?: number | null
  source?: string
  status?: CandidateStatus | string
}
export type ActivityDto = {
  id: number
  candidate_id: number
  user_id: number | null
  author_name: string | null
  author_role: string | null
  author_department_id: number | null
  author_department_name: string | null
  type: string
  content: string
  happened_at: string
  created_at: string
}
export type ActivityWrite = { type: string; content: string; happened_at?: string; next_status?: string }

// The five scores the composite combines, and how much each counts. Server defaults are
// resume 20 / hr_questions 15 / hr_overall 25 / manager_questions 15 / manager_overall 25:
// HR and the hiring manager weigh the same in total, and within each side the interviewer's
// own holistic total outweighs the mechanical per-question average. Values are relative and
// need not sum to anything in particular; the server rescales them to sum 1.
export type CompositeScoreComponent = 'resume' | 'hr_questions' | 'hr_overall' | 'manager_questions' | 'manager_overall'
export type CompositeScoreWeights = Partial<Record<CompositeScoreComponent, number>>

export type RequisitionDto = {
  id: number
  req_no: string
  title: string
  department_id: number | null
  department_name: string | null
  requested_by: number | null
  employment_type: string
  work_city: string
  jd: string
  summary: string | null
  skills: string[] | null
  salary_min: number | null
  salary_max: number | null
  salary_type: string | null
  headcount: number
  status: string
  /** Blind review: hide each side's interview evaluation until both stages submit. */
  blind_review_enabled: boolean
  /** Derived and read-only: true once any interview here has been submitted, after which blind_review_enabled can no longer change. */
  blind_review_locked: boolean
  /** Configured composite-score weights, or null when this requisition uses the defaults. A partial object overrides only the keys it names. */
  composite_score_weights: CompositeScoreWeights | null
  /** Derived and read-only: the same weights rescaled to sum 1, which is what a composite is actually computed with. */
  composite_score_weights_resolved: Required<CompositeScoreWeights>
  published_at: string | null
  created_at: string
}
// blind_review_enabled and composite_score_weights are optional on write and HR-only on the
// server; blind_review_locked and composite_score_weights_resolved are never written.
export type RequisitionWrite = Omit<RequisitionDto, 'id' | 'department_name' | 'requested_by' | 'published_at' | 'created_at' | 'blind_review_enabled' | 'blind_review_locked' | 'composite_score_weights' | 'composite_score_weights_resolved'> & { blind_review_enabled?: boolean; composite_score_weights?: CompositeScoreWeights | null }
export type DepartmentRequisitionWrite = {
  title: string
  employment_type: string
  work_city: string
  jd: string
  summary: string | null
  skills: string[]
  salary_min: number | null
  salary_max: number | null
  salary_type: string | null
  headcount: number
}
export type DepartmentApplicantDto = {
  application_id: number
  application_status: string
  application_source: string
  applied_at: string
  match_score: number | null
  match_status: string | null
  candidate: CandidateDto
}
export type DepartmentJobDto = {
  requisition: RequisitionDto
  applicants: DepartmentApplicantDto[]
}
export type DepartmentWorkspaceDto = {
  department_id: number
  department_name: string
  total_jobs: number
  total_applications: number
  total_candidates: number
  jobs: DepartmentJobDto[]
}

export type ApplicationDto = {
  id: number
  candidate_id: number
  requisition_id: number
  status: string
  source: string
  applied_at: string
  resume_id: number | null
  cover_letter: string | null
  linkedin_url: string | null
  portfolio_url: string | null
  interview_at: string | null
  interview_result: InterviewResult | null
  interview_notes: string | null
  hr_interview: InterviewStageDto
  manager_interview: InterviewStageDto
  /**
   * Sixth score: the weighted combination of the resume match, both stages' per-question
   * scores and both interviewers' own totals, on the same 0-100 scale. Null until both
   * interview stages are submitted — which is exactly when blind review releases the
   * underlying scores — and null again after a reopen.
   */
  composite_score: number | null
  /**
   * Why the composite is what it is. Null only while no composite has ever been computed,
   * which is what tells "not computed yet" apart from "computed as null".
   */
  composite_score_breakdown: CompositeScoreBreakdownDto | null
  candidate: CandidateDto
  requisition: RequisitionDto
}
export type CompositeScoreComponentDetailDto = {
  /** The component's 0-100 score, or null when it is missing. Missing is never read as zero. */
  value: number | null
  /** This component's configured share, before the missing-component rules. */
  weight: number
  /**
   * The share actually used. A stage whose questions were all 未詢問 folds that weight into
   * the same stage's overall score; a missing resume match is renormalised across the rest.
   */
  applied_weight: number
  included: boolean
  excluded_reason: 'no_match_result' | 'no_rated_questions' | 'no_overall_score' | null
}
export type CompositeScoreStageDetailDto = {
  record_id: number | null
  submitted_at: string | null
  revision_number: number | null
  question_count: number
  rated_question_count: number
  not_asked_question_count: number
}
export type CompositeScoreBreakdownDto =
  | {
      version: string
      /** Not both stages submitted yet, so no composite exists and no component values are exposed. */
      status: 'pending_stages'
      computed_at: string
      pending_stages: InterviewStage[]
    }
  | {
      version: string
      status: 'computed'
      computed_at: string
      composite_score: number | null
      configured_weights: CompositeScoreWeights | null
      resolved_weights: Required<CompositeScoreWeights>
      components: Record<CompositeScoreComponent, CompositeScoreComponentDetailDto>
      missing_components: CompositeScoreComponent[]
      stages: Record<InterviewStage, CompositeScoreStageDetailDto>
    }
export type CandidateResumeSummaryDto = {
  id: number
  target_requisition_id: number | null
  target_requisition_title: string | null
  original_filename: string | null
  source_platform: string
  parse_status: string
  resume_url: string | null
  has_file: boolean
  document_origin: 'applicant_upload' | 'system_generated'
}
export type CandidateApplicationDetailDto = {
  id: number
  requisition_id: number
  status: string
  source: string
  applied_at: string
  resume_id: number | null
  cover_letter: string | null
  linkedin_url: string | null
  portfolio_url: string | null
  requisition: RequisitionDto
  resume: CandidateResumeSummaryDto | null
}
export type CandidateDetailDto = CandidateDto & {
  current_company: string | null
  highest_education: string | null
  expected_title: string | null
  expected_cities: string[] | null
  expected_salary_min: number | null
  expected_salary_max: number | null
  salary_type: string | null
  availability: string | null
  job_type: string | null
  summary: string | null
  skills: string[]
  educations: CandidateEducationDto[]
  experiences: CandidateExperienceDto[]
  applications: CandidateApplicationDetailDto[]
  resumes: CandidateResumeSummaryDto[]
}
// job_applications.status values the UI reasons about. `interview_ready`（確定面試）is the HR
// hand-off that unlocks the interview workspace for a candidate sourced from the talent pool.
export type ApplicationStatus = 'submitted' | 'screening' | 'interview_ready' | 'interview' | 'interviewing' | 'offered' | 'hired' | 'rejected' | 'withdrawn'
// Statuses that already grant access to the interview flow, so 「進入面試」 may be offered.
export const INTERVIEW_ENTRY_STATUSES: readonly ApplicationStatus[] = ['interview_ready', 'interview', 'interviewing']
export function isInterviewEntryStatus(status: string): boolean {
  return (INTERVIEW_ENTRY_STATUSES as readonly string[]).includes(status)
}
export type ApplicationWrite = { candidate_id: number; requisition_id: number }
export type ApplicationAssignmentWrite = { requisition_id: number }
export type InterviewResult = 'pending' | 'advance' | 'hold' | 'rejected' | 'offered' | 'hired' | 'no_show' | 'cancelled'
export type InterviewStage = 'hr' | 'manager'
export type InterviewStageDto = {
  stage: InterviewStage
  interview_at: string | null
  interview_result: InterviewResult | null
  interview_notes: string | null
  updated_by: number | null
  updated_at: string | null
}
export type InterviewWrite = {
  interview_at: string | null
  interview_result: InterviewResult | null
  interview_notes: string | null
}

export type InterviewRecordMode = 'onsite' | 'video' | 'phone' | 'other'
export type InterviewRecordStatus = 'planned' | 'in_progress' | 'completed' | 'cancelled' | 'no_show'
export type InterviewRecommendation = 'advance' | 'hold' | 'reject' | 'offer'
export type InterviewRecordQuestion = {
  question: string
  trait?: string | null
  response?: string | null
  rating?: number | null
  not_asked_reason?: string | null
  notes?: string | null
  purpose?: string | null
  follow_up?: string | null
  source?: string | null
}
export type InterviewRecordWrite = {
  stage: InterviewStage
  question_plan_id?: number | null
  interviewed_at: string
  duration_minutes?: number | null
  mode: InterviewRecordMode
  status: InterviewRecordStatus
  questions: InterviewRecordQuestion[]
  summary?: string | null
  private_notes?: string | null
  recommendation?: InterviewRecommendation | null
  overall_score?: number | null
  overall_rating?: number | null
}
export type InterviewRecordDto = InterviewRecordWrite & {
  id: number
  application_id: number
  question_plan_id: number | null
  question_plan_version: number | null
  interviewer_id: number | null
  interviewer_name: string
  updated_by_id: number | null
  updated_by_name: string
  created_at: string
  updated_at: string
  submitted_at: string | null
  submitted_by_id: number | null
  submitted_by_name: string | null
  revision_number: number
  last_reopen_reason: string | null
  evaluation_revealed: boolean
  private_notes_visible: boolean
}
export type InterviewQuestion = {
  question: string
  purpose: string
  follow_up: string
  source?: string | null
}
export type InterviewQuestionSuggestion = {
  trait: string
  questions: InterviewQuestion[]
}
export type InterviewQuestionSuggestions = {
  requisition_id: number
  job_title: string
  suggestions: InterviewQuestionSuggestion[]
  guidance: string
  application_id?: number | null
  personalization_basis: string[]
}
export type InterviewQuestionPlanItem = {
  category: string
  question: string
  purpose: string
  follow_up: string
  source: string
}
export type InterviewQuestionPlan = {
  id?: number | null
  application_id: number
  stage: InterviewStage
  job_title: string
  questions: InterviewQuestionPlanItem[]
  personalization_basis: string[]
  guidance: string
  generation_mode?: 'gemini' | 'rules' | 'not_generated'
  generation_warning?: string | null
  provider?: string | null
  model_name?: string | null
  version?: number | null
  generated_at?: string | null
  context_matches?: boolean
  input_tokens: number
  output_tokens: number
  thinking_tokens: number
  total_tokens: number
}

export type ResumeSource = 'p104' | 'p1111' | 'generic' | 'direct'
export type ParsedResume = {
  name?: string
  email?: string
  phone?: string
  city?: string
  current_title?: string
  total_years?: number
  skills?: string[]
  education?: string
  experience?: string
  [key: string]: unknown
}
export type ResumeDto = {
  id: number
  candidate_id: number | null
  target_requisition_id: number | null
  original_filename: string | null
  source_platform: string
  requested_source_platform: string | null
  source_confidence: number | null
  source_evidence: Record<string, unknown>[] | null
  source_review_required: boolean
  source_reviewed_by: number | null
  source_reviewed_at: string | null
  parse_status: 'pending' | 'processing' | 'parsed' | 'needs_review' | 'confirmed' | 'failed' | string
  parsed_payload: ParsedResume | null
  field_confidence: Record<string, number> | null
  overall_confidence: number | null
  parser_version: string | null
  error_message: string | null
  resume_text: string | null
  file_hash: string | null
  file_size: number | null
  mime: string | null
  document_origin: 'applicant_upload' | 'system_generated'
  resume_url: string | null
  uploaded_at: string
  updated_at: string
  confirmed_at: string | null
}
export type ResumeUploadResult = Pick<ResumeDto, 'id' | 'original_filename' | 'source_platform' | 'source_confidence' | 'source_evidence' | 'source_review_required' | 'parse_status' | 'target_requisition_id'> & { duplicate: boolean }
export type ResumeConfirmResult = { resume_id: number; candidate_id: number; candidate_code: string; created: boolean }

import { API_BASE, authSession } from './auth'

export { API_BASE }

export async function apiRequest<T>(path: string, init: RequestInit = {}, retry = true): Promise<ApiResult<T>> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const accessToken = authSession.state.accessToken
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  } catch {
    throw new Error('無法連線至後端 API，請確認服務是否啟動')
  }
  if (response.status === 401 && retry && authSession.state.refreshToken) {
    await authSession.refreshAccess(accessToken)
    return apiRequest<T>(path, init, false)
  }
  if (!response.ok) {
    let detail = response.statusText || '請求失敗'
    try {
      const body = await response.json() as { detail?: string | { msg?: string }[] }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = body.detail.map(item => item.msg).filter(Boolean).join('、') || detail
    } catch { /* response is not JSON */ }
    throw new Error(`${response.status}：${detail}`)
  }
  if (response.status === 204) return { data: undefined as T }
  return { data: await response.json() as T }
}

async function apiBlob(path: string, retry = true): Promise<Blob> {
  const headers = new Headers()
  const accessToken = authSession.state.accessToken
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 30_000)
  try {
    let response: Response
    try {
      response = await fetch(`${API_BASE}${path}`, { headers, signal: controller.signal })
    } catch (cause) {
      if (cause instanceof Error && cause.name === 'AbortError') {
        throw new Error('檔案讀取逾時，請稍後再試')
      }
      throw new Error('無法連線至檔案服務')
    }
    if (response.status === 401 && retry && authSession.state.refreshToken) {
      await authSession.refreshAccess(accessToken)
      return apiBlob(path, false)
    }
    if (!response.ok) {
      let detail = response.statusText || '檔案無法讀取'
      try {
        const body = await response.json() as { detail?: string }
        if (body.detail) detail = body.detail
      } catch { /* response is not JSON */ }
      throw new Error(`${response.status}：${detail}`)
    }
    return await response.blob()
  } finally {
    window.clearTimeout(timeout)
  }
}

// Hard cap so a backend that ignores the `page` param cannot spin the fetch-all loops into an infinite loop / OOM.
const MAX_FETCH_PAGES = 100

export const hrApi = {
  health: () => apiRequest<{ status: string }>('/health'),
  candidates: async (
    params: {
      page?: number
      page_size?: number
      q?: string
      skill?: string
      status?: string
      city?: string
      min_years?: number
      department_id?: number
    } = {},
  ): Promise<ApiResult<CandidateDto[]>> => {
    const pageSize = params.page_size || 100
    // Optional AND filters resolved server-side; omitted params keep the original "return everything" behaviour.
    const filters: Record<string, string> = {}
    if (params.q) filters.q = params.q
    if (params.skill) filters.skill = params.skill
    if (params.status) filters.status = params.status
    if (params.city) filters.city = params.city
    if (params.min_years !== undefined) filters.min_years = String(params.min_years)
    if (params.department_id !== undefined) filters.department_id = String(params.department_id)
    // An explicit page returns just that page; the default (no page) walks every page so counts stay accurate.
    if (params.page !== undefined) {
      const query = new URLSearchParams({ page: String(params.page), page_size: String(pageSize), ...filters })
      return apiRequest<CandidateDto[]>(`/candidates?${query}`)
    }
    const all: CandidateDto[] = []
    let batch: CandidateDto[]
    let page = 1
    do {
      const query = new URLSearchParams({ page: String(page), page_size: String(pageSize), ...filters })
      batch = (await apiRequest<CandidateDto[]>(`/candidates?${query}`)).data
      all.push(...batch)
      page += 1
    } while (batch.length === pageSize && page <= MAX_FETCH_PAGES)
    if (batch.length === pageSize && page > MAX_FETCH_PAGES) {
      console.warn(`hrApi.candidates: stopped after ${MAX_FETCH_PAGES} pages (${all.length} records); results may be truncated if the backend ignores the page param`)
    }
    return { data: all }
  },
  candidate: (id: number) => apiRequest<CandidateDetailDto>(`/candidates/${id}`),
  saveCandidate: (payload: CandidateWrite, id?: number) => apiRequest<CandidateDto>(`/candidates${id ? `/${id}` : ''}`, {
    method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload),
  }),
  deleteCandidate: (id: number) => apiRequest<void>(`/candidates/${id}`, { method: 'DELETE' }),
  candidatePhoto: (id: number) => apiBlob(`/candidates/${id}/photo`),
  uploadCandidatePhoto: (id: number, photo: File) => {
    const body = new FormData()
    body.append('photo', photo)
    return apiRequest<CandidateDto>(`/candidates/${id}/photo`, { method: 'PUT', body })
  },
  deleteCandidatePhoto: (id: number) => apiRequest<void>(`/candidates/${id}/photo`, { method: 'DELETE' }),
  activities: (candidateId: number) => apiRequest<ActivityDto[]>(`/candidates/${candidateId}/activities`),
  addActivity: (candidateId: number, payload: ActivityWrite) => apiRequest<ActivityDto>(`/candidates/${candidateId}/activities`, {
    method: 'POST', body: JSON.stringify(payload),
  }),

  requisitions: (status?: string) => apiRequest<RequisitionDto[]>(`/requisitions${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  saveRequisition: (payload: RequisitionWrite | Partial<RequisitionWrite>, id?: number) => apiRequest<RequisitionDto>(`/requisitions${id ? `/${id}` : ''}`, {
    method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload),
  }),
  approveRequisition: (id: number) => apiRequest<RequisitionDto>(`/requisitions/${id}/approve`, { method: 'POST' }),
  departmentWorkspace: () => apiRequest<DepartmentWorkspaceDto>('/department/workspace'),
  createDepartmentRequisition: (payload: DepartmentRequisitionWrite) => apiRequest<RequisitionDto>('/department/requisitions', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  updateDepartmentRequisition: (id: number, payload: DepartmentRequisitionWrite) => apiRequest<RequisitionDto>(`/department/requisitions/${id}`, {
    method: 'PUT', body: JSON.stringify(payload),
  }),
  deleteDepartmentRequisition: (id: number) => apiRequest<void>(`/department/requisitions/${id}`, { method: 'DELETE' }),

  applications: (filters: { requisitionId?: number | null } = {}) => {
    const query = filters.requisitionId ? `?requisition_id=${encodeURIComponent(String(filters.requisitionId))}` : ''
    return apiRequest<ApplicationDto[]>(`/applications${query}`)
  },
  createApplication: (payload: ApplicationWrite) => apiRequest<ApplicationDto>('/applications', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  reassignApplication: (id: number, payload: ApplicationAssignmentWrite) => apiRequest<ApplicationDto>(`/applications/${id}/assignment`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  // HR-only hand-off that moves an application to `interview_ready`（確定面試）.
  markApplicationInterviewReady: (applicationId: number) => apiRequest<ApplicationDto>(`/applications/${applicationId}/mark-interview-ready`, {
    method: 'POST',
  }),
  downloadResume: (id: number) => apiBlob(`/resumes/${id}/file`),
  previewResume: (id: number) => apiBlob(`/resumes/${id}/preview`),
  updateApplicationInterview: (id: number, payload: InterviewWrite) => apiRequest<ApplicationDto>(`/applications/${id}/interview`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  updateApplicationInterviewStage: (id: number, stage: InterviewStage, payload: InterviewWrite) => apiRequest<ApplicationDto>(`/applications/${id}/interviews/${stage}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  interviewQuestionSuggestions: (requisitionId: number, personalityTraits: string[]) =>
    apiRequest<InterviewQuestionSuggestions>(`/requisitions/${requisitionId}/interview-question-suggestions`, {
      method: 'POST', body: JSON.stringify({ personality_traits: personalityTraits }),
    }),
  applicationInterviewQuestionSuggestions: (applicationId: number, personalityTraits: string[]) =>
    apiRequest<InterviewQuestionSuggestions>(`/applications/${applicationId}/interview-question-suggestions`, {
      method: 'POST', body: JSON.stringify({ personality_traits: personalityTraits }),
    }),
  interviewQuestionPlan: (applicationId: number, stage: InterviewStage) =>
    apiRequest<InterviewQuestionPlan>(`/applications/${applicationId}/interview-question-plan?stage=${stage}`),
  generateInterviewQuestionPlan: (applicationId: number, stage: InterviewStage, force = false) =>
    apiRequest<InterviewQuestionPlan>(`/applications/${applicationId}/interview-question-plan/generate?stage=${stage}&force=${force}`, {
      method: 'POST',
    }),
  regenerateInterviewQuestion: (applicationId: number, stage: InterviewStage, questionIndex: number) =>
    apiRequest<InterviewQuestionPlan>(
      `/applications/${applicationId}/interview-question-plan/questions/${questionIndex}/regenerate?stage=${stage}`,
      { method: 'POST' },
    ),
  interviewRecords: (applicationId: number) =>
    apiRequest<InterviewRecordDto[]>(`/applications/${applicationId}/interview-records`),
  createInterviewRecord: (applicationId: number, payload: InterviewRecordWrite) =>
    apiRequest<InterviewRecordDto>(`/applications/${applicationId}/interview-records`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  updateInterviewRecord: (applicationId: number, recordId: number, payload: Partial<Omit<InterviewRecordWrite, 'stage' | 'question_plan_id'>>) =>
    apiRequest<InterviewRecordDto>(`/applications/${applicationId}/interview-records/${recordId}`, {
      method: 'PATCH', body: JSON.stringify(payload),
    }),
  reopenInterviewRecord: (applicationId: number, recordId: number, reason: string) =>
    apiRequest<InterviewRecordDto>(`/applications/${applicationId}/interview-records/${recordId}/reopen`, {
      method: 'POST', body: JSON.stringify({ reason }),
    }),

  resumes: async (status?: string, includeConfirmed = false): Promise<ApiResult<ResumeDto[]>> => {
    const pageSize = 100
    const all: ResumeDto[] = []
    let batch: ResumeDto[]
    let page = 1
    do {
      const query = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        include_confirmed: String(includeConfirmed),
      })
      if (status) query.set('parse_status', status)
      batch = (await apiRequest<ResumeDto[]>(`/resumes?${query}`)).data
      all.push(...batch)
      page += 1
    } while (batch.length === pageSize && page <= MAX_FETCH_PAGES)
    if (batch.length === pageSize && page > MAX_FETCH_PAGES) {
      console.warn(`hrApi.resumes: stopped after ${MAX_FETCH_PAGES} pages (${all.length} records); results may be truncated if the backend ignores the page param`)
    }
    return { data: all }
  },
  resume: (id: number) => apiRequest<ResumeDto>(`/resumes/${id}`),
  uploadResumes: (files: File[], source: ResumeSource, candidateId?: number, requisitionId?: number) => {
    const body = new FormData()
    files.forEach(file => body.append('files', file))
    body.append('source_platform', source)
    if (candidateId !== undefined) body.append('candidate_id', String(candidateId))
    if (requisitionId !== undefined) body.append('requisition_id', String(requisitionId))
    return apiRequest<ResumeUploadResult[]>('/resumes/upload', { method: 'POST', body })
  },
  updateResumeParsed: (id: number, parsed_payload: ParsedResume) => apiRequest<ResumeDto>(`/resumes/${id}/parsed`, {
    method: 'PUT', body: JSON.stringify({ parsed_payload }),
  }),
  confirmResume: (id: number, candidateId?: number) => apiRequest<ResumeConfirmResult>(`/resumes/${id}/confirm`, {
    method: 'POST', body: candidateId ? JSON.stringify({ candidate_id: candidateId }) : undefined,
  }),
  reparseResume: (id: number) => apiRequest<ResumeDto>(`/resumes/${id}/reparse`, { method: 'POST' }),
  reviewResumeSource: (id: number, source_platform: ResumeSource) => apiRequest<ResumeDto>(`/resumes/${id}/source`, {
    method: 'PUT', body: JSON.stringify({ source_platform }),
  }),
}
