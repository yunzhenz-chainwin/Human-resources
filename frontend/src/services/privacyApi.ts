import { apiRequest } from './hrApi'

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
