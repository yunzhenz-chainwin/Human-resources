import { apiRequest } from './hrApi'

// Anti-discrimination JD lint (就服法 §5 / 中高齡就業促進法 / 性別平等工作法).
// Advisory only: a "warning" result never blocks saving a requisition.

export type JobTextField = 'title' | 'summary' | 'jd'

export type JobComplianceCategory =
  | 'gender'
  | 'age'
  | 'marital_pregnancy'
  | 'military'
  | 'appearance'
  | 'nationality_race'
  | 'religion'
  | 'disability'
  | 'astrology'

export type JobComplianceFinding = {
  category: JobComplianceCategory
  matched: string
  field: JobTextField
  suggestion: string
}

export type JobComplianceResult = {
  status: 'ok' | 'warning'
  findings: JobComplianceFinding[]
  rules_version: string
}

export type JobComplianceInput = {
  title?: string | null
  summary?: string | null
  jd?: string | null
}

export const jobComplianceCategoryLabels: Record<JobComplianceCategory, string> = {
  gender: '性別',
  age: '年齡',
  marital_pregnancy: '婚姻／懷孕生育',
  military: '兵役',
  appearance: '容貌／體格',
  nationality_race: '國籍／出生地／種族',
  religion: '宗教信仰',
  disability: '身心障礙／健康',
  astrology: '星座／血型／生肖',
}

export async function lintJobText(input: JobComplianceInput): Promise<JobComplianceResult> {
  const { data } = await apiRequest<JobComplianceResult>('/requisitions/lint', {
    method: 'POST',
    body: JSON.stringify({
      title: input.title ?? null,
      summary: input.summary ?? null,
      jd: input.jd ?? null,
    }),
  })
  return data
}
