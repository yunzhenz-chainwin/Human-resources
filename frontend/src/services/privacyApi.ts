import { apiRequest } from './hrApi'

export type AnonymizationField =
  | 'name'
  | 'address'
  | 'phone'
  | 'email'
  | 'birth_date'
  | 'national_id'
  | 'personal_url'

export type ResumeAnonymizationSummary = {
  field_counts: Partial<Record<AnonymizationField, number>> & Record<string, number>
  total_replacements: number
  input_characters: number
  output_characters: number
}

export type ResumeAnonymizationResult = {
  operation_id: string
  anonymized_text: string
  summary: ResumeAnonymizationSummary
}

export type TalentRetentionPolicy = {
  setting_key: string
  retention_years: number
  defaulted: boolean
  applied_candidates: number
}

export type TalentRetentionPurgeResult = {
  as_of: string
  dry_run: boolean
  lock_acquired: boolean
  eligible_candidates: number
  eligible_resume_files: number
  deleted_candidates: number
  deleted_resume_files: number
  remaining_candidates: number
  queued_storage_deletions: number
  deleted_storage_objects: number
  deleted_photos: number
  storage_delete_failures: number
}

export type CandidateRetentionSetting = {
  candidate_id: number
  retention_years_override: number | null
  effective_retention_years: number
  uses_company_default: boolean
  anchor_date: string
  retention_until: string
}

export const privacyApi = {
  anonymizeResume: (payload: {
    plain_text: string
    additional_names?: string[]
    additional_addresses?: string[]
  }) => apiRequest<ResumeAnonymizationResult>('/resume-anonymization', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  anonymizationSummary: (operationId: string) =>
    apiRequest<{ operation_id: string; summary: ResumeAnonymizationSummary }>(
      `/resume-anonymization/${encodeURIComponent(operationId)}/summary`,
    ),
  retentionPolicy: () => apiRequest<TalentRetentionPolicy>('/talent-retention/policy'),
  updateRetentionPolicy: (retentionYears: number) => apiRequest<TalentRetentionPolicy>('/talent-retention/policy', {
    method: 'PUT',
    body: JSON.stringify({ retention_years: retentionYears }),
  }),
  updateCandidateRetention: (candidateId: number, retentionYears: number | null) =>
    apiRequest<CandidateRetentionSetting>(`/talent-retention/candidates/${candidateId}`, {
      method: 'PUT',
      body: JSON.stringify({ retention_years: retentionYears }),
    }),
  purgeExpiredTalent: (dryRun = true) => apiRequest<TalentRetentionPurgeResult>('/talent-retention/purge', {
    method: 'POST',
    body: JSON.stringify({ dry_run: dryRun }),
  }),
}
