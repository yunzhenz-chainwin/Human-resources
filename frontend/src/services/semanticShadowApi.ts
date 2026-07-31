import { apiRequest } from './hrApi'

export type ShadowSource = 'gemini' | 'rules_fallback'
export type ShadowGenerationStatus = 'completed' | 'fallback'

export type SkillSynonymEvidence = {
  required_skill: string
  candidate_skill: string
  rationale: string
}

export type TransferableExperienceEvidence = {
  experience: string
  target_requirement: string
  rationale: string
}

export type ShadowInterviewQuestion = {
  gap: string
  question: string
  reason: string
}

export type SemanticShadowEvaluation = {
  id: number
  match_result_id: number
  requisition_id: number
  candidate_id: number
  requested_by: number | null
  formal_total_score: number
  formal_gate_passed: boolean
  formal_rank: number | null
  formal_status: string
  semantic_score: number
  synonym_evidence: SkillSynonymEvidence[]
  transferable_experience_evidence: TransferableExperienceEvidence[]
  concerns: string[]
  insufficient_data: string[]
  interview_questions: ShadowInterviewQuestion[]
  source: ShadowSource
  generation_status: ShadowGenerationStatus
  model_name: string
  prompt_version: string
  input_tokens: number
  output_tokens: number
  thinking_tokens: number
  total_tokens: number
  error_code: string | null
  generated_at: string
  experiment_only: true
  disclaimer: string
}

export type SemanticShadowComparison = {
  match_result_id: number
  formal: {
    total_score: number
    gate_passed: boolean
    rank: number | null
    status: string
    computed_at: string
  }
  latest_shadow: SemanticShadowEvaluation | null
  evaluation_count: number
  experiment_only: true
  disclaimer: string
}

export const semanticShadowApi = {
  comparison: async (matchId: number) => (
    await apiRequest<SemanticShadowComparison>(
      `/semantic-shadow/matches/${matchId}/comparison`,
    )
  ).data,
  generate: async (matchId: number) => (
    await apiRequest<SemanticShadowEvaluation>(
      `/semantic-shadow/matches/${matchId}/evaluations`,
      {
        method: 'POST',
        body: JSON.stringify({ acknowledge_experimental: true }),
      },
    )
  ).data,
  history: async (matchId: number) => (
    await apiRequest<SemanticShadowEvaluation[]>(
      `/semantic-shadow/matches/${matchId}/evaluations`,
    )
  ).data,
}

