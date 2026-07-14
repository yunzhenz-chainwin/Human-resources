from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Candidate, JobRequisition, MatchResult

DEFAULT_WEIGHTS = {
    "skill": 0.40,
    "relevance": 0.20,
    "years": 0.15,
    "salary": 0.10,
    "education": 0.10,
    "location": 0.05,
}
AUTO_STATUSES = {"recommended", "ineligible"}
EXCLUDED_CANDIDATE_STATUSES = {"hired", "declined", "archived", "withdrawn"}
POSITIVE_OUTCOME_STATUSES = {"interview", "offered", "hired"}
NEGATIVE_OUTCOME_STATUSES = {"rejected_by_manager", "withdrawn"}
EDUCATION_RANK = {
    "國中": 1,
    "高中": 2,
    "高職": 2,
    "專科": 3,
    "副學士": 3,
    "大學": 4,
    "學士": 4,
    "碩士": 5,
    "研究所": 5,
    "博士": 6,
}
ADJACENT_CITIES = {
    "台北市": {"新北市", "基隆市", "桃園市"},
    "新北市": {"台北市", "基隆市", "桃園市", "宜蘭縣"},
    "桃園市": {"台北市", "新北市", "新竹縣", "新竹市"},
    "新竹市": {"桃園市", "新竹縣", "苗栗縣"},
    "新竹縣": {"桃園市", "新竹市", "苗栗縣"},
    "台中市": {"苗栗縣", "彰化縣", "南投縣"},
    "台南市": {"嘉義縣", "嘉義市", "高雄市"},
    "高雄市": {"台南市", "屏東縣"},
}
SKILL_ALIASES = {
    "fast api": "fastapi",
    "nodejs": "node.js",
    "node js": "node.js",
    "postgres": "postgresql",
    "postgres sql": "postgresql",
    "powerbi": "power bi",
    "vue.js": "vue",
    "vuejs": "vue",
}


@dataclass(frozen=True)
class ScoreResult:
    gate_passed: bool
    total_score: float
    breakdown: dict[str, Any]


def normalize_text(value: str | None) -> str:
    return "".join((value or "").strip().casefold().replace("臺", "台").split())


def canonical_skill(value: str | None) -> str:
    """Normalize conservative spelling variants without guessing proficiency."""

    readable = " ".join((value or "").strip().casefold().split())
    return normalize_text(SKILL_ALIASES.get(readable, readable))


def _education_rank(value: str | None) -> int:
    normalized = normalize_text(value)
    return next((rank for label, rank in EDUCATION_RANK.items() if label in normalized), 0)


def resolve_weights(overrides: dict | None) -> dict[str, float]:
    result = dict(DEFAULT_WEIGHTS)
    for key in result:
        value = (overrides or {}).get(key)
        if isinstance(value, int | float) and value >= 0:
            result[key] = float(value)
    total = sum(result.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {key: value / total for key, value in result.items()}


def _skill_requirements(requisition: JobRequisition) -> tuple[list[str], list[str]]:
    config = requisition.match_weights or {}
    configured_required = config.get("required_skills")
    configured_preferred = config.get("preferred_skills", [])
    raw_required = (
        configured_required if isinstance(configured_required, list) else requisition.skills
    )
    required = [str(value) for value in (raw_required or []) if str(value).strip()]
    preferred = [str(value) for value in configured_preferred if str(value).strip()]
    return required, preferred


def _salary_score(candidate: Candidate, requisition: JobRequisition) -> float:
    c_min, c_max = candidate.expected_salary_min, candidate.expected_salary_max
    j_min, j_max = requisition.salary_min, requisition.salary_max
    if c_min is None and c_max is None:
        return 0.5
    if j_min is None and j_max is None:
        return 0.5
    c_min = c_min if c_min is not None else c_max
    c_max = c_max if c_max is not None else c_min
    j_min = j_min if j_min is not None else 0
    j_max = j_max if j_max is not None else j_min
    if c_min is None or c_max is None or j_max is None:
        return 0.5
    if c_min == c_max:
        return 1.0 if j_min <= c_min <= j_max else 0.0
    overlap = max(0, min(c_max, j_max) - max(c_min, j_min))
    return min(1.0, overlap / (c_max - c_min))


def _location_score(candidate: Candidate, work_city: str) -> float:
    candidate_cities = candidate.expected_cities or ([candidate.city] if candidate.city else [])
    if not candidate_cities:
        return 0.5
    work = normalize_text(work_city)
    cities = {normalize_text(city) for city in candidate_cities}
    if work in cities:
        return 1.0
    adjacent = {
        normalize_text(city) for city in ADJACENT_CITIES.get(normalize_text(work_city), set())
    }
    return 0.6 if cities & adjacent else 0.2


def score_candidate(
    requisition: JobRequisition,
    candidate: Candidate,
    candidate_skills: list[str],
) -> ScoreResult:
    weights = resolve_weights(requisition.match_weights)
    required, preferred = _skill_requirements(requisition)
    normalized_candidate_skills = {
        canonical_skill(skill): skill for skill in candidate_skills if canonical_skill(skill)
    }
    required_hits = [
        skill for skill in required if canonical_skill(skill) in normalized_candidate_skills
    ]
    required_misses = [
        skill for skill in required if canonical_skill(skill) not in normalized_candidate_skills
    ]
    preferred_hits = [
        skill for skill in preferred if canonical_skill(skill) in normalized_candidate_skills
    ]
    preferred_misses = [
        skill for skill in preferred if canonical_skill(skill) not in normalized_candidate_skills
    ]
    skill_evidence = {
        skill: normalized_candidate_skills[canonical_skill(skill)]
        for skill in required_hits + preferred_hits
    }

    candidate_education = max(
        [_education_rank(candidate.highest_education)]
        + [_education_rank(education.degree) for education in candidate.educations]
    )
    required_education = _education_rank(requisition.education_req)
    years = float(candidate.total_years) if candidate.total_years is not None else None
    min_years = float(requisition.min_years) if requisition.min_years is not None else None
    expected_cities = {normalize_text(city) for city in candidate.expected_cities or []}
    work_city = normalize_text(requisition.work_city)

    gate_misses: list[str] = []
    config = requisition.match_weights or {}
    if candidate.deleted_at is not None:
        gate_misses.append("candidate_deleted")
    if candidate.is_blacklisted:
        gate_misses.append("blacklisted")
    if candidate.consent_status == "withdrawn":
        gate_misses.append("consent_withdrawn")
    if candidate.status in EXCLUDED_CANDIDATE_STATUSES:
        gate_misses.append(f"status:{candidate.status}")
    if config.get("require_skills", True) and required_misses:
        gate_misses.append("required_skills")
    if (
        config.get("require_years", True)
        and min_years is not None
        and (years is None or years < min_years)
    ):
        gate_misses.append("minimum_years")
    if (
        config.get("require_education", True)
        and required_education
        and candidate_education < required_education
    ):
        gate_misses.append("education")
    if (
        config.get("require_location", True)
        and expected_cities
        and work_city not in expected_cities
    ):
        gate_misses.append("location")

    skill_denominator = len(required) * 2 + len(preferred)
    skill_score = (
        (len(required_hits) * 2 + len(preferred_hits)) / skill_denominator
        if skill_denominator
        else 1.0
    )
    title_score = (
        SequenceMatcher(
            None, normalize_text(candidate.current_title), normalize_text(requisition.title)
        ).ratio()
        if candidate.current_title
        else 0.5
    )
    years_score = 1.0 if min_years is None else min(1.0, (years or 0) / max(min_years, 0.1))
    salary_score = _salary_score(candidate, requisition)
    education_score = (
        1.0
        if required_education == 0 or candidate_education >= required_education
        else candidate_education / required_education
    )
    location_score = _location_score(candidate, requisition.work_city)
    components = {
        "skill": (skill_score, required_hits + preferred_hits, required_misses + preferred_misses),
        "relevance": (
            title_score,
            [candidate.current_title] if candidate.current_title else [],
            [],
        ),
        "years": (years_score, [years] if years is not None else [], []),
        "salary": (salary_score, [], []),
        "education": (
            education_score,
            [],
            [requisition.education_req] if "education" in gate_misses else [],
        ),
        "location": (location_score, [requisition.work_city] if location_score == 1 else [], []),
    }
    breakdown: dict[str, Any] = {
        "gate": {"passed": not gate_misses, "miss": gate_misses},
        "data_quality": {
            "missing": [
                field
                for field, value in (
                    ("current_title", candidate.current_title),
                    ("total_years", candidate.total_years),
                    ("highest_education", candidate.highest_education),
                    (
                        "expected_salary",
                        candidate.expected_salary_min or candidate.expected_salary_max,
                    ),
                    ("location", candidate.expected_cities or candidate.city),
                )
                if value is None
            ]
        },
    }
    weighted_total = 0.0
    for key, (component_score, hits, misses) in components.items():
        contribution = weights[key] * component_score
        weighted_total += contribution
        breakdown[key] = {
            "weight": round(weights[key], 4),
            "score": round(component_score, 4),
            "contribution": round(contribution * 100, 2),
            "hit": hits,
            "miss": misses,
        }
        if key == "skill":
            breakdown[key]["evidence"] = skill_evidence
    passed = not gate_misses
    # Keep the fit score visible even when a hard requirement fails.  The gate and
    # its concrete reasons remain separate, so HR sees useful evidence instead of
    # a misleading 0.0% for every ineligible person.
    total = round(min(100.0, max(0.0, weighted_total * 100)), 2)
    breakdown["recommendation"] = (
        "ineligible"
        if not passed
        else "strong"
        if total >= 80
        else "potential"
        if total >= 60
        else "review"
    )
    return ScoreResult(passed, total, breakdown)


def rematch_requisition(db: Session, requisition: JobRequisition) -> list[MatchResult]:
    candidates = list(
        db.scalars(
            select(Candidate)
            .options(selectinload(Candidate.skills), selectinload(Candidate.educations))
            .where(Candidate.deleted_at.is_(None))
        ).all()
    )
    existing = {
        item.candidate_id: item
        for item in db.scalars(
            select(MatchResult).where(MatchResult.requisition_id == requisition.id)
        ).all()
    }
    computed: list[tuple[Candidate, ScoreResult, MatchResult]] = []
    now = datetime.now(UTC)
    for candidate in candidates:
        score = score_candidate(
            requisition, candidate, [candidate_skill.skill for candidate_skill in candidate.skills]
        )
        result = existing.get(candidate.id)
        if result is None:
            result = MatchResult(
                requisition_id=requisition.id,
                candidate_id=candidate.id,
                gate_passed=score.gate_passed,
                total_score=score.total_score,
                score_breakdown=score.breakdown,
                status="recommended" if score.gate_passed else "ineligible",
                computed_at=now,
            )
            db.add(result)
        else:
            result.gate_passed = score.gate_passed
            result.total_score = score.total_score
            result.score_breakdown = score.breakdown
            result.computed_at = now
            if result.status in AUTO_STATUSES:
                result.status = "recommended" if score.gate_passed else "ineligible"
        result.rank = None
        computed.append((candidate, score, result))

    eligible = sorted(
        (item for item in computed if item[1].gate_passed),
        key=lambda item: (-item[1].total_score, item[0].id),
    )
    for rank, (_, _, result) in enumerate(eligible, start=1):
        result.rank = rank
    db.commit()
    return [
        item[2]
        for item in sorted(computed, key=lambda item: (item[2].rank is None, item[2].rank or 0))
    ]


def assess_matching_readiness(results: list[MatchResult]) -> dict[str, Any]:
    """Summarize whether current results are ready for a measured skills-first pilot."""

    total = len(results)
    eligible = [item for item in results if item.gate_passed]
    labeled = [
        item
        for item in results
        if item.status in POSITIVE_OUTCOME_STATUSES | NEGATIVE_OUTCOME_STATUSES
    ]
    positives = [item for item in labeled if item.status in POSITIVE_OUTCOME_STATUSES]
    top_five = sorted(
        eligible,
        key=lambda item: (item.rank is None, item.rank or 0, -float(item.total_score)),
    )[:5]
    labeled_top_five = [item for item in top_five if item in labeled]
    precision_at_five = (
        sum(item.status in POSITIVE_OUTCOME_STATUSES for item in labeled_top_five)
        / len(labeled_top_five)
        if labeled_top_five
        else None
    )
    completeness_scores: list[float] = []
    for item in results:
        missing = (item.score_breakdown or {}).get("data_quality", {}).get("missing", [])
        completeness_scores.append(max(0.0, 1 - len(set(missing)) / 5))
    completeness = sum(completeness_scores) / total if total else 0.0
    average_score = (
        sum(float(item.total_score) for item in eligible) / len(eligible) if eligible else 0.0
    )
    pilot_status = (
        "needs_candidates"
        if not total
        else "ready_for_weight_tuning"
        if len(labeled) >= 30
        else "ready_for_shadow_pilot"
    )
    return {
        "strategy": "explainable_skills_first_v2",
        "pilot_status": pilot_status,
        "metrics": {
            "candidate_count": total,
            "eligible_count": len(eligible),
            "eligibility_rate": round(len(eligible) / total, 4) if total else 0.0,
            "average_eligible_score": round(average_score, 2),
            "data_completeness": round(completeness, 4),
            "labeled_outcomes": len(labeled),
            "feedback_coverage": round(len(labeled) / total, 4) if total else 0.0,
            "positive_outcomes": len(positives),
            "precision_at_5": round(precision_at_five, 4)
            if precision_at_five is not None
            else None,
        },
        "adopted_capabilities": [
            "required_and_preferred_skills",
            "skill_alias_normalization",
            "hard_eligibility_gates",
            "weighted_structured_ranking",
            "explainable_evidence",
            "human_feedback_loop",
            "data_quality_signals",
        ],
        "next_experiments": [
            "external_skill_taxonomy",
            "semantic_embeddings_shadow_score",
            "hybrid_rank_fusion",
            "learning_to_rank_after_30_labeled_outcomes",
        ],
        "excluded_features": [
            "age",
            "gender",
            "photo",
            "religion",
            "disability",
            "marital_status",
        ],
    }
