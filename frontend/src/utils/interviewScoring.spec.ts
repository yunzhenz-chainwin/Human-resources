import { describe, expect, it } from 'vitest'

import {
  CONSENSUS_SCORE_GAP,
  combinedInterviewScore,
  evaluateConsensus,
  questionScore,
  ratedQuestionCount,
  validRating,
  validScore,
} from './interviewScoring'

// The same arithmetic exists in backend/app/services/interview_scoring.py and is
// re-implemented nowhere else. These tests pin the behaviour that is easy to get
// wrong by rounding, by counting the wrong denominator, or by treating a missing
// score as a bad one.

describe('questionScore', () => {
  it('excludes 未詢問 questions from the denominator, not just the numerator', () => {
    // Four questions rated 4,3,5,4 with a fifth skipped scores 16/20, not 16/25.
    // A question never put to the candidate must not be scored against them.
    const questions = [
      { rating: 4 }, { rating: 3 }, { rating: 5 }, { rating: 4 },
      { rating: null, not_asked_reason: '時間不足' },
    ]
    expect(questionScore(questions)).toBe(80)
    expect(questionScore(questions)).not.toBe(64)
  })

  it('returns null rather than 0 when nothing was rated', () => {
    // 0 is a real score meaning poor performance. Absent is not the same thing,
    // and a caller that cannot tell them apart will show one as the other.
    expect(questionScore([{ rating: null }, { rating: null }])).toBeNull()
    expect(questionScore([])).toBeNull()
  })

  it('scores a full set at both ends of the scale', () => {
    expect(questionScore([{ rating: 5 }, { rating: 5 }])).toBe(100)
    expect(questionScore([{ rating: 1 }, { rating: 1 }])).toBe(20)
  })

  it('keeps one decimal place instead of an unbounded float', () => {
    // 3 of 5 possible on three questions is 9/15 = 60. Two questions rated 4 and
    // 3 is 7/10 = 70. A third at 5 gives 12/15 = 80.
    expect(questionScore([{ rating: 3 }, { rating: 3 }, { rating: 3 }])).toBe(60)
    expect(questionScore([{ rating: 4 }, { rating: 3 }])).toBe(70)
    expect(questionScore([{ rating: 4 }, { rating: 3 }, { rating: 5 }])).toBe(80)
  })

  it('ignores ratings outside 1-5 rather than trusting the payload', () => {
    expect(questionScore([{ rating: 4 }, { rating: 0 }, { rating: 9 }])).toBe(80)
  })

  it('counts only the questions that carry a rating', () => {
    expect(ratedQuestionCount([
      { rating: 4 }, { rating: null, not_asked_reason: '不適用' }, { rating: 2 },
    ])).toBe(2)
  })
})

describe('validRating and validScore', () => {
  it('accepts an integer 1-5 rating and nothing else', () => {
    expect(validRating(1)).toBe(true)
    expect(validRating(5)).toBe(true)
    expect(validRating(0)).toBe(false)
    expect(validRating(6)).toBe(false)
    expect(validRating(3.5)).toBe(false)
    expect(validRating(null)).toBe(false)
    expect(validRating(undefined)).toBe(false)
  })

  it('rejects a fractional total, which the integer column would 422 on', () => {
    expect(validScore(0)).toBe(true)
    expect(validScore(100)).toBe(true)
    expect(validScore(82)).toBe(true)
    expect(validScore(82.5)).toBe(false)
    expect(validScore(-1)).toBe(false)
    expect(validScore(101)).toBe(false)
    expect(validScore(null)).toBe(false)
  })
})

describe('evaluateConsensus', () => {
  const advance = 'advance'
  const reject = 'reject'
  const hold = 'hold'

  it('flags a disagreement in recommendation even when the scores are close', () => {
    const verdict = evaluateConsensus({
      hrScore: 80, managerScore: 78, hrRecommendation: advance, managerRecommendation: reject,
    })
    expect(verdict.state).toBe('divergent')
  })

  it('flags a wide score gap even when both recommend the same thing', () => {
    // 95 and 60 average to 77.5, the same as 78 and 77. Reporting only the mean
    // would present a serious disagreement and an unremarkable candidate alike.
    const verdict = evaluateConsensus({
      hrScore: 95, managerScore: 60, hrRecommendation: advance, managerRecommendation: advance,
    })
    expect(verdict.state).toBe('divergent')
    expect(verdict.scoreGap).toBe(35)
  })

  it('treats agreement within the gap as aligned', () => {
    const verdict = evaluateConsensus({
      hrScore: 82, managerScore: 75, hrRecommendation: advance, managerRecommendation: advance,
    })
    expect(verdict.state).toBe('aligned')
    expect(verdict.scoreGap).toBe(7)
  })

  it('puts the boundary at the gap itself, not one either side of it', () => {
    const atGap = evaluateConsensus({
      hrScore: 80, managerScore: 80 - CONSENSUS_SCORE_GAP,
      hrRecommendation: advance, managerRecommendation: advance,
    })
    const justInside = evaluateConsensus({
      hrScore: 80, managerScore: 80 - CONSENSUS_SCORE_GAP + 1,
      hrRecommendation: advance, managerRecommendation: advance,
    })
    expect(atGap.state).toBe('divergent')
    expect(justInside.state).toBe('aligned')
  })

  it('does not call two different-but-same-direction recommendations a conflict', () => {
    // advance and offer both mean "yes"; hold is neutral, not a rejection.
    expect(evaluateConsensus({
      hrScore: 80, managerScore: 78, hrRecommendation: advance, managerRecommendation: 'offer',
    }).state).toBe('aligned')
    expect(evaluateConsensus({
      hrScore: 80, managerScore: 78, hrRecommendation: hold, managerRecommendation: reject,
    }).state).toBe('divergent')
  })

  it('does not invent a gap when a score is missing', () => {
    const verdict = evaluateConsensus({
      hrScore: 80, managerScore: null, hrRecommendation: advance, managerRecommendation: advance,
    })
    expect(verdict.scoreGap).toBe(0)
    expect(verdict.state).toBe('aligned')
  })
})

describe('combinedInterviewScore', () => {
  it('averages the two totals to one decimal', () => {
    expect(combinedInterviewScore(85, 82)).toBe('83.5')
    expect(combinedInterviewScore(95, 60)).toBe('77.5')
    expect(combinedInterviewScore(78, 77)).toBe('77.5')
  })

  it('refuses to average a single submission', () => {
    // Half the evidence weighted as if it were all of it would mislead, so the
    // card says who is still pending instead.
    expect(combinedInterviewScore(85, null)).toBeNull()
    expect(combinedInterviewScore(null, 82)).toBeNull()
    expect(combinedInterviewScore(null, null)).toBeNull()
  })
})
