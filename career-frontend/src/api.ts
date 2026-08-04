import type { ApplicationForm, ApplicationResult, ConsentNotice, Job } from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, options)
  } catch {
    throw new Error('目前無法連線，請確認網路後再試一次。')
  }

  if (!response.ok) {
    let message = `送出失敗（${response.status}）`
    try {
      const body = await response.json() as { detail?: string | Array<{ msg?: string }>; message?: string }
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map(item => item.msg).filter(Boolean).join('、') || message
      else if (body.message) message = body.message
    } catch { /* non-JSON response */ }
    throw new Error(message)
  }

  return response.json() as Promise<T>
}

function unwrapJobs(payload: Job[] | { items?: Job[]; data?: Job[] }): Job[] {
  if (Array.isArray(payload)) return payload
  return payload.items || payload.data || []
}

function normalizeJob(job: Job): Job {
  return {
    ...job,
    description: job.description || job.jd,
    requirements: job.requirements || job.skills,
    salary_currency: job.salary_currency || 'TWD',
  }
}

export async function getJobs(): Promise<Job[]> {
  const jobs = unwrapJobs(await request<Job[] | { items?: Job[]; data?: Job[] }>('/public/jobs'))
  const publicStatuses = new Set(['approved', 'published', 'open', 'sourcing', 'interviewing'])
  return jobs
    .filter(job => !job.status || publicStatuses.has(job.status.toLowerCase()))
    .map(normalizeJob)
}

export async function getJob(id: string | number): Promise<Job> {
  return normalizeJob(await request<Job>(`/public/jobs/${encodeURIComponent(id)}`))
}

export async function getActiveConsentNotice(): Promise<ConsentNotice> {
  return request<ConsentNotice>('/public/consent-notices/active')
}

export async function createApplication(
  form: ApplicationForm,
  resume: File | null,
  consentNotice: ConsentNotice,
): Promise<ApplicationResult> {
  const body = new FormData()
  if (form.job_id !== null && form.job_id !== '') body.append('job_id', String(form.job_id))
  body.append('name', form.name)
  if (form.email) body.append('email', form.email)
  if (form.phone) body.append('phone', form.phone)
  if (form.city) body.append('city', form.city)
  if (form.current_title) body.append('current_title', form.current_title)
  if (form.total_years !== null) body.append('total_years', String(form.total_years))
  if (form.skills) body.append('skills', form.skills)
  if (form.linkedin_url) body.append('linkedin_url', form.linkedin_url)
  if (form.portfolio_url) body.append('portfolio_url', form.portfolio_url)
  if (form.cover_letter) body.append('cover_letter', form.cover_letter)
  body.append('consent', String(form.consent))
  body.append('consent_notice_id', String(consentNotice.id))
  body.append('consent_notice_version', String(consentNotice.version))
  body.append('source_platform', form.source_platform)
  if (resume) body.append('resume', resume)
  return request<ApplicationResult>('/public/applications', { method: 'POST', body })
}
