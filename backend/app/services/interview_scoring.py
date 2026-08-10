"""Composite candidate score: one weighted number over the five stored scores.

Five scores already exist for a candidate on one requisition -- the resume match,
each interview stage's per-question average, and each interviewer's own 0-100
total. This module derives the sixth from them and persists it on the application
so candidates stay rankable and the number stays a decision-time snapshot.

Nothing here may touch ``JobApplication.status``: evaluation must never drive
application state (docs/13, section 4 and the blocked-risk table).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InterviewRecord, JobApplication, JobRequisition, MatchResult

# Rationale, so a future edit keeps it: HR and the hiring manager weigh the same
# in total (40 each), and within each side the interviewer's own holistic total
# outweighs the mechanical per-question average, because the total reflects
# judgement the per-question scores do not capture.
DEFAULT_COMPOSITE_WEIGHTS: dict[str, float] = {
    "resume": 20.0,
    "hr_questions": 15.0,
    "hr_overall": 25.0,
    "manager_questions": 15.0,
    "manager_overall": 25.0,
}
COMPOSITE_WEIGHT_KEYS: tuple[str, ...] = tuple(DEFAULT_COMPOSITE_WEIGHTS)
COMPOSITE_BREAKDOWN_VERSION = "composite_v1"

# The two components that carry one interview stage's weight. They are
# interchangeable carriers, which is what lets a missing question score fold its
# weight into that stage's overall instead of shrinking the stage.
_STAGE_COMPONENTS: dict[str, tuple[str, str]] = {
    "hr": ("hr_questions", "hr_overall"),
    "manager": ("manager_questions", "manager_overall"),
}
INTERVIEW_STAGES: tuple[str, ...] = tuple(_STAGE_COMPONENTS)

_MISSING_REASONS = {
    "resume": "no_match_result",
    "hr_questions": "no_rated_questions",
    "manager_questions": "no_rated_questions",
    "hr_overall": "no_overall_score",
    "manager_overall": "no_overall_score",
}


def resolve_composite_weights(overrides: dict | None) -> dict[str, float]:
    """Normalise configured composite weights to sum 1, falling back to defaults.

    Same contract as ``app.services.matching.resolve_weights``: unknown keys and
    non-numeric or negative values are ignored rather than rejected, and a total
    that is not positive carries no decision at all, so the defaults win.
    """

    result = dict(DEFAULT_COMPOSITE_WEIGHTS)
    for key in result:
        value = (overrides or {}).get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value >= 0:
            result[key] = float(value)
    total = sum(result.values())
    if total <= 0:
        default_total = sum(DEFAULT_COMPOSITE_WEIGHTS.values())
        return {
            key: value / default_total for key, value in DEFAULT_COMPOSITE_WEIGHTS.items()
        }
    return {key: value / total for key, value in result.items()}


def _valid_rating(value: Any) -> bool:
    """Mirror the UI's ``validRating``: an integer 1-5 and nothing else."""

    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5


def question_score(questions: Sequence[dict] | None) -> float | None:
    """Per-question score on the same 0-100 scale as the interviewer's own total.

    ``(sum of ratings on rated questions) / (rated question count * 5) * 100``.

    Questions the interviewer marked 未詢問 carry ``not_asked_reason`` and no
    rating, so they drop out of the denominator as well as the numerator: a
    question that was never put to the candidate must not count against them.
    A record with no valid 1-5 rating at all scores ``None``, never zero.

    Deliberately identical to what the interview UI already displays, down to the
    float64 arithmetic and the round-half-up to one decimal place, so the stored
    number and the rendered one can never disagree.
    """

    ratings = [
        item.get("rating")
        for item in (questions or [])
        if isinstance(item, dict) and _valid_rating(item.get("rating"))
    ]
    if not ratings:
        return None
    total = sum(float(value) for value in ratings)
    return math.floor(total / (len(ratings) * 5) * 1000 + 0.5) / 10


def latest_records_by_stage(
    records: Iterable[InterviewRecord],
) -> dict[str, InterviewRecord]:
    """Pick the current record per stage from newest-first ordered records."""

    latest: dict[str, InterviewRecord] = {}
    for record in records:
        latest.setdefault(record.stage, record)
    return latest


def both_stages_submitted(records: Iterable[InterviewRecord]) -> bool:
    """True once the current record of both stages is a submitted evaluation.

    This is exactly the condition under which blind review releases each side's
    scores, which is why the composite may only exist from this point on.
    """

    latest = latest_records_by_stage(records)
    return all(
        latest.get(stage) is not None and latest[stage].status == "completed"
        for stage in INTERVIEW_STAGES
    )


def application_interview_records(
    db: Session,
    application_id: int,
) -> list[InterviewRecord]:
    """Interview records for one application, newest first."""

    return list(
        db.scalars(
            select(InterviewRecord)
            .where(InterviewRecord.application_id == application_id)
            .order_by(
                InterviewRecord.interviewed_at.desc(),
                InterviewRecord.id.desc(),
            )
        ).all()
    )


def _apply_missing_component_rules(
    values: dict[str, float | None],
    weights: dict[str, float],
) -> dict[str, float]:
    """Redistribute the weight of every component that has no value.

    A missing component is never read as zero: zero is a real score meaning "bad",
    missing means "unknown". Within one interview stage the surviving component
    absorbs the other's weight, which keeps that stage's total influence intact.
    Anything still missing after that -- most often the resume match, because a
    manually added candidate never went through matching -- simply drops out, and
    the renormalisation at the end rescales whatever remains back to sum 1.
    """

    applied = dict(weights)
    for question_key, overall_key in _STAGE_COMPONENTS.values():
        if values[question_key] is None and values[overall_key] is not None:
            applied[overall_key] += applied[question_key]
            applied[question_key] = 0.0
        elif values[overall_key] is None and values[question_key] is not None:
            applied[question_key] += applied[overall_key]
            applied[overall_key] = 0.0
    for key in COMPOSITE_WEIGHT_KEYS:
        if values[key] is None:
            applied[key] = 0.0
    total = sum(applied.values())
    if total <= 0:
        return dict.fromkeys(COMPOSITE_WEIGHT_KEYS, 0.0)
    return {key: value / total for key, value in applied.items()}


def _stage_detail(record: InterviewRecord | None) -> dict[str, Any]:
    questions = (record.questions if record is not None else None) or []
    return {
        "record_id": record.id if record is not None else None,
        "submitted_at": (
            record.submitted_at.isoformat()
            if record is not None and record.submitted_at is not None
            else None
        ),
        "revision_number": record.revision_number if record is not None else None,
        "question_count": len(questions),
        "rated_question_count": sum(
            1 for item in questions if isinstance(item, dict) and _valid_rating(item.get("rating"))
        ),
        "not_asked_question_count": sum(
            1
            for item in questions
            if isinstance(item, dict) and bool(item.get("not_asked_reason"))
        ),
    }


def _pending_breakdown(records: Sequence[InterviewRecord]) -> dict[str, Any]:
    """Breakdown for an application whose two stages are not both submitted.

    Carries no component values on purpose. A "partial" composite, or even the
    inputs it would be built from, would hand one interviewer the other side's
    scores before blind review releases them.
    """

    latest = latest_records_by_stage(records)
    return {
        "version": COMPOSITE_BREAKDOWN_VERSION,
        "status": "pending_stages",
        "computed_at": datetime.now(UTC).isoformat(),
        "pending_stages": [
            stage
            for stage in INTERVIEW_STAGES
            if latest.get(stage) is None or latest[stage].status != "completed"
        ],
    }


def _round_weight(value: float) -> float:
    return round(value, 6)


def compute_composite_score(
    *,
    weights: dict[str, float],
    configured_weights: dict | None,
    resume_score: float | None,
    records: Sequence[InterviewRecord],
) -> tuple[float | None, dict[str, Any]]:
    """Weighted composite over the five scores, plus the breakdown that explains it.

    Returns ``(None, breakdown)`` both while the two stages are not both
    submitted and when nothing at all could be scored; ``breakdown["status"]``
    tells those apart.
    """

    if not both_stages_submitted(records):
        return None, _pending_breakdown(records)

    latest = latest_records_by_stage(records)
    hr_record = latest["hr"]
    manager_record = latest["manager"]
    values: dict[str, float | None] = {
        "resume": resume_score,
        "hr_questions": question_score(hr_record.questions),
        "hr_overall": (
            float(hr_record.overall_score) if hr_record.overall_score is not None else None
        ),
        "manager_questions": question_score(manager_record.questions),
        "manager_overall": (
            float(manager_record.overall_score)
            if manager_record.overall_score is not None
            else None
        ),
    }
    applied = _apply_missing_component_rules(values, weights)
    total_weight = sum(applied.values())
    raw_score = (
        sum(
            float(values[key]) * applied[key]
            for key in COMPOSITE_WEIGHT_KEYS
            if values[key] is not None
        )
        if total_weight > 0
        else None
    )
    score = (
        float(Decimal(repr(raw_score)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        if raw_score is not None
        else None
    )
    breakdown: dict[str, Any] = {
        "version": COMPOSITE_BREAKDOWN_VERSION,
        "status": "computed",
        "computed_at": datetime.now(UTC).isoformat(),
        "composite_score": score,
        "configured_weights": configured_weights or None,
        "resolved_weights": {key: _round_weight(value) for key, value in weights.items()},
        "components": {
            key: {
                "value": values[key],
                "weight": _round_weight(weights[key]),
                "applied_weight": _round_weight(applied[key]),
                "included": values[key] is not None,
                "excluded_reason": None if values[key] is not None else _MISSING_REASONS[key],
            }
            for key in COMPOSITE_WEIGHT_KEYS
        },
        "missing_components": [
            key for key in COMPOSITE_WEIGHT_KEYS if values[key] is None
        ],
        "stages": {
            "hr": _stage_detail(hr_record),
            "manager": _stage_detail(manager_record),
        },
    }
    return score, breakdown


def recompute_application_composite_score(
    db: Session,
    application: JobApplication,
    requisition: JobRequisition,
) -> tuple[float | None, dict[str, Any]]:
    """Refresh the stored composite for one application and return what was stored.

    Called whenever an interview record is submitted, resubmitted or reopened, so
    the stored number always reflects the evaluations that are currently
    submitted. It writes ``composite_score`` and ``composite_score_breakdown`` and
    nothing else -- in particular never ``application.status``, which no
    evaluation is allowed to move.
    """

    records = application_interview_records(db, application.id)
    resume_total = db.scalar(
        select(MatchResult.total_score).where(
            MatchResult.requisition_id == application.requisition_id,
            MatchResult.candidate_id == application.candidate_id,
        )
    )
    score, breakdown = compute_composite_score(
        weights=resolve_composite_weights(requisition.composite_score_weights),
        configured_weights=requisition.composite_score_weights,
        resume_score=float(resume_total) if resume_total is not None else None,
        records=records,
    )
    application.composite_score = None if score is None else Decimal(repr(score))
    application.composite_score_breakdown = breakdown
    return score, breakdown


def recompute_requisition_composite_scores(
    db: Session,
    requisition: JobRequisition,
) -> list[dict[str, Any]]:
    """Re-derive every stored composite on one requisition under its current weights.

    Called when the requisition's weights change. A composite is only ever read
    against the other candidates on the same requisition, and that comparison holds
    only while everyone is scored the same way -- leaving the stored numbers on the
    old weights would rank one list on two scales, which ranks it on neither.

    The previous numbers are not lost. The caller writes them into the audit entry
    for the reweighting, which is where "what this looked like when the decision was
    made" lives for every other setting here too.

    Applications whose two stages are not both submitted simply re-derive to None
    and stay pending, exactly as they do on a stage submission.

    Returns one entry per application whose composite actually moved, so the caller
    can record the before/after; an unchanged composite is left out rather than
    padding the audit with no-ops.
    """

    applications = list(
        db.scalars(
            select(JobApplication)
            .where(JobApplication.requisition_id == requisition.id)
            .order_by(JobApplication.id)
        ).all()
    )
    changes: list[dict[str, Any]] = []
    for application in applications:
        previous = application.composite_score
        previous_score = None if previous is None else float(previous)
        score, _ = recompute_application_composite_score(db, application, requisition)
        if previous_score != score:
            changes.append(
                {
                    "application_id": application.id,
                    "from": previous_score,
                    "to": score,
                }
            )
    return changes
