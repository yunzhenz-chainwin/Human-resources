// Interview scoring arithmetic, extracted so it can be tested without mounting a
// component. The same formulas exist in backend/app/services/interview_scoring.py
// and must produce identical numbers; a divergence would let one record show two
// different scores depending on which screen you opened.

export type RatedQuestion = {
  rating?: number | null
  not_asked_reason?: string | null
}

export type ConsensusInput = {
  hrScore: number | null
  managerScore: number | null
  hrRecommendation: string | null
  managerRecommendation: string | null
}

export type ConsensusState = 'pending' | 'aligned' | 'divergent'

/** Scores differing by this much are treated as a disagreement worth discussing. */
export const CONSENSUS_SCORE_GAP = 20

const RECOMMENDATION_TONE: Record<string, 'positive' | 'neutral' | 'negative'> = {
  advance: 'positive', offer: 'positive', hold: 'neutral', reject: 'negative',
}

/** A 1-5 rating an interviewer actually gave. */
export function validRating(value: number | null | undefined): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 5
}

/** A 0-100 total. Integer only: the column is an integer and a fraction 422s. */
export function validScore(value: number | null | undefined): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100
}

export function ratedQuestionCount(questions: RatedQuestion[]): number {
  return questions.filter(question => validRating(question.rating)).length
}

/**
 * Per-question performance on the same 0-100 scale as the interviewer's own
 * total. Questions marked 未詢問 carry no rating and so leave both the numerator
 * and the denominator: four questions rated 4,3,5,4 with one skipped is 80, not
 * 64, because a question never put to the candidate must not count against them.
 *
 * Returns null when nothing was rated. Never 0 — zero is a real score meaning
 * poor performance, and must not be confused with the absence of one.
 */
export function questionScore(questions: RatedQuestion[]): number | null {
  const rated = questions.filter(question => validRating(question.rating))
  if (!rated.length) return null
  const total = rated.reduce((sum, question) => sum + Number(question.rating), 0)
  return Math.round((total / (rated.length * 5)) * 1000) / 10
}

/**
 * Whether the two interviewers agree, decided before any average is shown.
 * 95 and 60 average to the same 77.5 as 78 and 77, but one is a serious
 * disagreement and the other an unremarkable candidate; presenting only the
 * average would hide the case that most needs a human to look at it.
 */
export function evaluateConsensus(input: ConsensusInput): { state: ConsensusState; scoreGap: number } {
  const bothScored = input.hrScore !== null && input.managerScore !== null
  const scoreGap = bothScored ? Math.abs(Number(input.hrScore) - Number(input.managerScore)) : 0
  const hrTone = input.hrRecommendation ? RECOMMENDATION_TONE[input.hrRecommendation] : null
  const managerTone = input.managerRecommendation ? RECOMMENDATION_TONE[input.managerRecommendation] : null
  const recommendationDiffers = Boolean(hrTone && managerTone && hrTone !== managerTone)
  if (recommendationDiffers || scoreGap >= CONSENSUS_SCORE_GAP) return { state: 'divergent', scoreGap }
  return { state: 'aligned', scoreGap }
}

/** Mean of the two interview totals. Null unless both are present. */
export function combinedInterviewScore(hrScore: number | null, managerScore: number | null): string | null {
  if (hrScore === null || managerScore === null) return null
  return ((hrScore + managerScore) / 2).toFixed(1)
}
