import { API_BASE, apiRequest, type ApiResult } from './hrApi'
import { authSession } from './auth'

export type DeidentificationStatus =
  | 'processing'
  | 'review_required'
  | 'analysis_ready'
  | 'superseded'
  | 'failed'
  | 'stale'

export type DeidentifiedExperienceRole = {
  title: string
  years: number | null
  industry: string | null
}

export type DeidentifiedAnalysisPayload = {
  schema_version: 'talenthub.deidentified-resume.v1' | string
  current_title: string | null
  total_years: number | null
  skills: string[]
  experience_roles: DeidentifiedExperienceRole[]
  highest_education: string | null
}

export type DeidentificationValidationCount = {
  type: string
  count: number
}

export type DeidentificationValidationSummary = {
  schema_version: 'talenthub.deidentification-validation.v1' | string
  blocker_count: number
  findings: DeidentificationValidationCount[]
  redactions: DeidentificationValidationCount[]
  payload_field_count: number
  pdf_character_count: number
}

export type DeidentifiedResumeDocument = {
  id: number
  source_resume_id: number
  anonymous_ref: string
  version: number
  file_hash: string | null
  file_size: number | null
  mime: string
  source_file_hash: string
  deidentification_version: string
  payload_schema_version: string
  analysis_payload: DeidentifiedAnalysisPayload
  validation_status: DeidentificationStatus
  validation_summary: DeidentificationValidationSummary
  stale_reason?: string | null
  created_by: number | null
  reviewed_by: number | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
  has_file: boolean
}

export type MatchComponent = {
  key: 'skills' | 'relevance' | 'years' | 'industry'
  label: string
  score: number | null
  known: boolean
  weight: number
  hit: string[]
  miss: string[]
}

export type RoleMatchHighlight = {
  kind: 'strength' | 'concern' | 'info'
  category: string
  text: string
}

export type RoleMatchItem = {
  requisition_id: number
  req_no: string
  title: string
  department_name: string | null
  total_score: number
  gate_passed: boolean
  confidence: 'high' | 'medium' | 'low'
  data_completeness: number
  components: MatchComponent[]
  highlights: RoleMatchHighlight[]
  insufficient_data: string[]
}

export type AnalysisEnvelope = {
  generated_at: string
  algorithm_version: string
  ai_used: false
  token_usage: 0
  disclaimer: string
}

export type RecommendedRolesAnalysis = AnalysisEnvelope & {
  items: RoleMatchItem[]
}

export type RoleMatchAnalysis = AnalysisEnvelope & {
  item: RoleMatchItem
}

export type RoleMatchRequest = {
  requisition_id: number
}

async function apiBlob(path: string, retry = true): Promise<Blob> {
  const headers = new Headers({ Accept: 'application/pdf,application/octet-stream' })
  const accessToken = authSession.state.accessToken
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { headers, cache: 'no-store' })
  } catch {
    throw new Error('無法連線至後端 API')
  }

  if (response.status === 401 && retry && authSession.state.refreshToken) {
    await authSession.refreshAccess(accessToken)
    return apiBlob(path, false)
  }
  if (!response.ok) {
    let detail = response.statusText || '檔案讀取失敗'
    try {
      const body = await response.json() as { detail?: string }
      if (body.detail) detail = body.detail
    } catch { /* non-JSON error */ }
    throw new Error(`${response.status}：${detail}`)
  }
  return response.blob()
}

export const candidateAnalysisApi = {
  uploadDeidentification: (resumeId: number, file: File): Promise<ApiResult<DeidentifiedResumeDocument>> => {
    const body = new FormData()
    body.append('file', file)
    return apiRequest<DeidentifiedResumeDocument>(`/resumes/${resumeId}/deidentifications`, {
      method: 'POST',
      body,
      cache: 'no-store',
    })
  },

  deidentificationsForResume: (resumeId: number): Promise<ApiResult<DeidentifiedResumeDocument[]>> =>
    apiRequest<DeidentifiedResumeDocument[]>(`/resumes/${resumeId}/deidentifications`, { cache: 'no-store' }),

  deidentificationsForCandidate: (candidateId: number): Promise<ApiResult<DeidentifiedResumeDocument[]>> =>
    apiRequest<DeidentifiedResumeDocument[]>(`/candidates/${candidateId}/deidentified-resumes`, { cache: 'no-store' }),

  previewDeidentifiedResume: (documentId: number): Promise<Blob> =>
    apiBlob(`/deidentified-resumes/${documentId}/preview`),

  downloadDeidentifiedResume: (documentId: number): Promise<Blob> =>
    apiBlob(`/deidentified-resumes/${documentId}/file`),

  approveDeidentification: (documentId: number): Promise<ApiResult<DeidentifiedResumeDocument>> =>
    apiRequest<DeidentifiedResumeDocument>(`/deidentified-resumes/${documentId}/approve`, {
      method: 'POST',
      cache: 'no-store',
    }),

  rejectDeidentification: (documentId: number): Promise<ApiResult<DeidentifiedResumeDocument>> =>
    apiRequest<DeidentifiedResumeDocument>(`/deidentified-resumes/${documentId}/reject`, {
      method: 'POST',
      cache: 'no-store',
    }),

  recommendRoles: (documentId: number): Promise<ApiResult<RecommendedRolesAnalysis>> =>
    apiRequest<RecommendedRolesAnalysis>(`/deidentified-resumes/${documentId}/analyses/recommended-roles`, {
      method: 'POST',
      cache: 'no-store',
    }),

  evaluateRoleMatch: (documentId: number, payload: RoleMatchRequest): Promise<ApiResult<RoleMatchAnalysis>> =>
    apiRequest<RoleMatchAnalysis>(`/deidentified-resumes/${documentId}/analyses/role-match`, {
      method: 'POST',
      body: JSON.stringify(payload),
      cache: 'no-store',
    }),
}
