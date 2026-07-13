export interface Job {
  id: string | number
  req_no?: string
  title: string
  department?: string
  location?: string
  employment_type?: string
  work_mode?: string
  summary?: string
  jd?: string
  skills?: string[]
  description?: string
  responsibilities?: string[] | string
  requirements?: string[] | string
  benefits?: string[] | string
  salary_min?: number | null
  salary_max?: number | null
  salary_currency?: string
  salary_type?: string | null
  published_at?: string
  status?: string
}

export type SourcePlatform = 'direct' | 'p104' | 'p1111' | 'generic'

export interface ApplicationForm {
  job_id: string | number | null
  name: string
  email: string
  phone: string
  city: string
  current_title: string
  total_years: number | null
  skills: string
  cover_letter: string
  consent: boolean
  source_platform: SourcePlatform
}

export interface ApplicationResult {
  application_id?: number
  candidate_id?: number
  resume_id?: number
  status: string
  duplicate?: boolean
}
