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
  published_at: string | null
  created_at: string
}
export type RequisitionWrite = Omit<RequisitionDto, 'id' | 'department_name' | 'requested_by' | 'published_at' | 'created_at'>
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
  candidate: CandidateDto
  requisition: RequisitionDto
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
  const response = await fetch(`${API_BASE}${path}`, { headers })
  if (response.status === 401 && retry && authSession.state.refreshToken) {
    await authSession.refreshAccess(accessToken)
    return apiBlob(path, false)
  }
  if (!response.ok) throw new Error(`無法讀取檔案（${response.status}）`)
  return response.blob()
}

// Hard cap so a backend that ignores the `page` param cannot spin the fetch-all loops into an infinite loop / OOM.
const MAX_FETCH_PAGES = 100

export const hrApi = {
  health: () => apiRequest<{ status: string }>('/health'),
  candidates: async (params: { page?: number; page_size?: number } = {}): Promise<ApiResult<CandidateDto[]>> => {
    const pageSize = params.page_size || 100
    // An explicit page returns just that page; the default (no page) walks every page so counts stay accurate.
    if (params.page !== undefined) {
      const query = new URLSearchParams({ page: String(params.page), page_size: String(pageSize) })
      return apiRequest<CandidateDto[]>(`/candidates?${query}`)
    }
    const all: CandidateDto[] = []
    let batch: CandidateDto[]
    let page = 1
    do {
      const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
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

  applications: () => apiRequest<ApplicationDto[]>('/applications'),
  createApplication: (payload: ApplicationWrite) => apiRequest<ApplicationDto>('/applications', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  reassignApplication: (id: number, payload: ApplicationAssignmentWrite) => apiRequest<ApplicationDto>(`/applications/${id}/assignment`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  downloadResume: (id: number) => apiBlob(`/resumes/${id}/file`),
  updateApplicationInterview: (id: number, payload: InterviewWrite) => apiRequest<ApplicationDto>(`/applications/${id}/interview`, {
    method: 'PATCH', body: JSON.stringify(payload),
  }),
  updateApplicationInterviewStage: (id: number, stage: InterviewStage, payload: InterviewWrite) => apiRequest<ApplicationDto>(`/applications/${id}/interviews/${stage}`, {
    method: 'PATCH', body: JSON.stringify(payload),
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
