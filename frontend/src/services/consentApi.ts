import { apiRequest } from './hrApi'

export type ConsentNotice = {
  id: number
  version: number
  title: string
  body: string
  purpose_code: string | null
  is_active: boolean
  created_by: number | null
  created_at: string
  updated_at: string
}

export type ConsentNoticeCreate = {
  title: string
  body: string
  purpose_code?: string | null
  activate?: boolean
}

export type CandidateConsent = {
  id: number
  candidate_id: number
  notice_id: number
  notice_version: number
  consented_at: string
  channel: string
  withdrawn_at: string | null
}

export type ConsentChannel = 'hr_manual' | 'public_form'

export const consentApi = {
  notices: () => apiRequest<ConsentNotice[]>('/consent/notices'),
  activeNotice: () => apiRequest<ConsentNotice>('/consent/notices/active'),
  createNotice: (payload: ConsentNoticeCreate) => apiRequest<ConsentNotice>('/consent/notices', {
    method: 'POST', body: JSON.stringify(payload),
  }),
  activateNotice: (id: number) => apiRequest<ConsentNotice>(`/consent/notices/${id}/activate`, {
    method: 'POST',
  }),
  candidateConsents: (candidateId: number) => apiRequest<CandidateConsent[]>(
    `/candidates/${candidateId}/consents`,
  ),
  recordCandidateConsent: (candidateId: number, channel: ConsentChannel = 'hr_manual') => apiRequest<CandidateConsent>(
    `/candidates/${candidateId}/consents`,
    { method: 'POST', body: JSON.stringify({ channel }) },
  ),
  withdrawCandidateConsent: (consentId: number) => apiRequest<CandidateConsent>(
    `/consent/candidate-consents/${consentId}/withdraw`,
    { method: 'POST' },
  ),
}
