from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.fixtures.matching_benchmark_v1 import (
    FIXTURE_VERSION,
    SCORING_VERSION,
    SUITE_KEY,
    SUITE_TITLE,
    build_fixture_cases,
)
from app.models.candidate import Candidate
from app.models.matching_benchmark import (
    MatchingBenchmarkCase,
    MatchingBenchmarkRating,
    MatchingBenchmarkSuite,
)
from app.models.organization import User
from app.models.recruitment import JobRequisition
from app.schemas.matching_benchmark import BenchmarkRatingWrite, MetricResult
from app.services.matching import score_candidate

TOP_K = 5
MIN_REPORT_CASES = 20
MIN_ROLE_AGREEMENT_PAIRS = 10
MIN_POSITIVE_CASES = 5
MIN_TOP_K_JOB_GROUPS = 3
POSITIVE_VERDICTS = frozenset({"interview", "consider"})
VERDICT_ORDER = {
    "interview": 0,
    "consider": 1,
    "insufficient_data": 2,
    "reject": 3,
}


class BenchmarkError(RuntimeError):
    pass


class BenchmarkNotFoundError(BenchmarkError):
    pass


class BenchmarkAccessError(BenchmarkError):
    pass


class BenchmarkStateError(BenchmarkError):
    pass


class BenchmarkConflictError(BenchmarkError):
    pass


def _require_non_production(settings: Settings) -> None:
    environment = settings.app_env.strip().lower()
    if environment in {"production", "prod", "staging"}:
        raise RuntimeError(f"Matching benchmark seed is disabled in {environment}")


def _fixture_hash(cases: list[dict[str, Any]]) -> str:
    payload = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _data_completeness(profile: dict[str, Any]) -> float:
    values = (
        profile.get("current_title"),
        profile.get("total_years"),
        profile.get("skills"),
        profile.get("highest_education"),
        profile.get("expected_cities"),
        profile.get("expected_salary_min") or profile.get("expected_salary_max"),
        profile.get("summary"),
    )
    known = sum(value is not None and value != [] and value != "" for value in values)
    return round(known / len(values) * 100, 2)


def _score_fixture_case(definition: dict[str, Any]):
    job_profile = definition["job_profile"]
    candidate_profile = definition["candidate_profile"]
    requisition = JobRequisition(
        req_no=f"BENCH-{definition['job_key'].upper()}",
        title=job_profile["title"],
        employment_type=job_profile["employment_type"],
        work_city=job_profile["work_city"],
        salary_min=job_profile["salary_min"],
        salary_max=job_profile["salary_max"],
        min_years=Decimal(str(job_profile["min_years"])),
        education_req=job_profile.get("education_req"),
        jd=job_profile["summary"],
        skills=job_profile["required_skills"] + job_profile["preferred_skills"],
        match_weights={
            "required_skills": list(job_profile["required_skills"]),
            "preferred_skills": list(job_profile["preferred_skills"]),
            "required_skill_ratio": 1.0,
            "require_skills": True,
            "require_years": True,
            "require_education": False,
            "require_location": True,
        },
        status="benchmark",
    )
    candidate = Candidate(
        code=candidate_profile["synthetic_code"],
        name="合成候選人",
        current_title=candidate_profile.get("current_title"),
        total_years=(
            Decimal(str(candidate_profile["total_years"]))
            if candidate_profile.get("total_years") is not None
            else None
        ),
        highest_education=candidate_profile.get("highest_education"),
        expected_cities=candidate_profile.get("expected_cities"),
        expected_salary_min=candidate_profile.get("expected_salary_min"),
        expected_salary_max=candidate_profile.get("expected_salary_max"),
        summary=candidate_profile.get("summary"),
        source="benchmark",
        status="new",
        consent_status="synthetic_benchmark",
        is_blacklisted=False,
        deleted_at=None,
    )
    return score_candidate(requisition, candidate, list(candidate_profile.get("skills") or []))


def seed_matching_benchmark(
    db: Session,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Idempotently seed an isolated 50-case suite and recompute current rule scores.

    This intentionally does not create Candidate, JobRequisition, ResumeFile, or
    MatchResult rows. A fixture definition change must use a new suite/version once
    the old suite exists, so blind ratings can never be silently reinterpreted.
    """

    _require_non_production(settings or get_settings())
    definitions = build_fixture_cases()
    if not 40 <= len(definitions) <= 60:
        raise RuntimeError("Benchmark fixture must contain between 40 and 60 cases")
    fixture_hash = _fixture_hash(definitions)
    suite = db.scalar(select(MatchingBenchmarkSuite).where(MatchingBenchmarkSuite.key == SUITE_KEY))
    unchanged_fixture = suite is not None
    if suite is None:
        suite = MatchingBenchmarkSuite(
            key=SUITE_KEY,
            title=SUITE_TITLE,
            fixture_version=FIXTURE_VERSION,
            fixture_hash=fixture_hash,
            scoring_version=SCORING_VERSION,
            status="blind",
            case_count=0,
        )
        db.add(suite)
        db.flush()
    elif suite.fixture_version != FIXTURE_VERSION or suite.fixture_hash != fixture_hash:
        raise BenchmarkConflictError(
            "Fixture content changed; publish it under a new suite key/version to preserve ratings"
        )

    existing = {
        item.case_key: item
        for item in db.scalars(
            select(MatchingBenchmarkCase).where(MatchingBenchmarkCase.suite_id == suite.id)
        ).all()
    }
    created_cases = 0
    updated_cases = 0
    fixture_keys: set[str] = set()
    for definition in definitions:
        fixture_keys.add(definition["case_key"])
        score = _score_fixture_case(definition)
        values = {
            "sequence": definition["sequence"],
            "job_key": definition["job_key"],
            "scenario": definition["scenario"],
            "job_profile": definition["job_profile"],
            "candidate_profile": definition["candidate_profile"],
            "expected_verdict": definition["expected_verdict"],
            "system_score": Decimal(str(score.total_score)),
            "system_gate_passed": score.gate_passed,
            "system_breakdown": score.breakdown,
            "data_completeness": Decimal(str(_data_completeness(definition["candidate_profile"]))),
            "is_active": True,
        }
        item = existing.get(definition["case_key"])
        if item is None:
            db.add(
                MatchingBenchmarkCase(
                    suite_id=suite.id,
                    case_key=definition["case_key"],
                    **values,
                )
            )
            created_cases += 1
        else:
            for field, value in values.items():
                setattr(item, field, value)
            updated_cases += 1

    for case_key, item in existing.items():
        if case_key not in fixture_keys:
            item.is_active = False

    suite.case_count = len(definitions)
    suite.scoring_version = SCORING_VERSION
    db.commit()
    return {
        "suite_key": suite.key,
        "fixture_version": suite.fixture_version,
        "total_cases": len(definitions),
        "created_cases": created_cases,
        "updated_cases": updated_cases,
        "unchanged_fixture": unchanged_fixture,
    }


def get_benchmark_suite(db: Session, suite_key: str) -> MatchingBenchmarkSuite:
    suite = db.scalar(
        select(MatchingBenchmarkSuite).where(MatchingBenchmarkSuite.key == suite_key)
    )
    if suite is None:
        raise BenchmarkNotFoundError("Benchmark suite not found; run the development seed first")
    return suite


def _active_cases(db: Session, suite_id: int) -> list[MatchingBenchmarkCase]:
    return list(
        db.scalars(
            select(MatchingBenchmarkCase)
            .where(
                MatchingBenchmarkCase.suite_id == suite_id,
                MatchingBenchmarkCase.is_active.is_(True),
            )
            .order_by(MatchingBenchmarkCase.sequence)
        ).all()
    )


def benchmark_progress(db: Session, suite: MatchingBenchmarkSuite) -> list[dict[str, Any]]:
    total = db.scalar(
        select(func.count(MatchingBenchmarkCase.id)).where(
            MatchingBenchmarkCase.suite_id == suite.id,
            MatchingBenchmarkCase.is_active.is_(True),
        )
    ) or 0
    rows = db.execute(
        select(
            MatchingBenchmarkRating.reviewer_role,
            MatchingBenchmarkRating.reviewer_id,
            func.count(MatchingBenchmarkRating.id),
        )
        .join(MatchingBenchmarkCase, MatchingBenchmarkCase.id == MatchingBenchmarkRating.case_id)
        .where(
            MatchingBenchmarkCase.suite_id == suite.id,
            MatchingBenchmarkCase.is_active.is_(True),
        )
        .group_by(
            MatchingBenchmarkRating.reviewer_role,
            MatchingBenchmarkRating.reviewer_id,
        )
    ).all()
    counts: dict[str, list[int]] = defaultdict(list)
    for role, _reviewer_id, count in rows:
        counts[str(role)].append(int(count))
    return [
        {
            "role": role,
            "completed": max(counts[role], default=0),
            "total": int(total),
            "complete_reviewer_count": (
                sum(value == total for value in counts[role]) if total else 0
            ),
        }
        for role in ("hr", "manager")
    ]


def _complete_reviewer_ids(db: Session, suite: MatchingBenchmarkSuite) -> set[int]:
    total = db.scalar(
        select(func.count(MatchingBenchmarkCase.id)).where(
            MatchingBenchmarkCase.suite_id == suite.id,
            MatchingBenchmarkCase.is_active.is_(True),
        )
    ) or 0
    if total == 0:
        return set()
    rows = db.execute(
        select(
            MatchingBenchmarkRating.reviewer_id,
            func.count(MatchingBenchmarkRating.id),
        )
        .join(MatchingBenchmarkCase, MatchingBenchmarkCase.id == MatchingBenchmarkRating.case_id)
        .where(
            MatchingBenchmarkCase.suite_id == suite.id,
            MatchingBenchmarkCase.is_active.is_(True),
        )
        .group_by(MatchingBenchmarkRating.reviewer_id)
    ).all()
    return {int(reviewer_id) for reviewer_id, count in rows if count == total}


def suite_payload(db: Session, suite: MatchingBenchmarkSuite) -> dict[str, Any]:
    return {
        "key": suite.key,
        "title": suite.title,
        "fixture_version": suite.fixture_version,
        "scoring_version": suite.scoring_version,
        "status": suite.status,
        "case_count": suite.case_count,
        "revealed_at": suite.revealed_at,
        "progress": benchmark_progress(db, suite),
    }


def list_suite_payloads(db: Session) -> list[dict[str, Any]]:
    suites = list(db.scalars(select(MatchingBenchmarkSuite).order_by(MatchingBenchmarkSuite.id)))
    return [suite_payload(db, suite) for suite in suites]


def blind_cases_payload(db: Session, suite: MatchingBenchmarkSuite, user: User) -> dict[str, Any]:
    if user.role not in {"hr", "manager"}:
        raise BenchmarkAccessError("Only HR and department managers can perform blind ratings")
    cases = _active_cases(db, suite.id)
    case_ids = [item.id for item in cases]
    ratings = {
        rating.case_id: rating
        for rating in db.scalars(
            select(MatchingBenchmarkRating).where(
                MatchingBenchmarkRating.reviewer_id == user.id,
                MatchingBenchmarkRating.case_id.in_(case_ids),
            )
        ).all()
    } if case_ids else {}
    return {
        "suite": suite_payload(db, suite),
        "reviewer_role": user.role,
        "cases": [
            {
                "case_key": item.case_key,
                "sequence": item.sequence,
                "job_key": item.job_key,
                "job_profile": item.job_profile,
                "candidate_profile": item.candidate_profile,
                "my_rating": ratings.get(item.id),
            }
            for item in cases
        ],
    }


def save_blind_rating(
    db: Session,
    suite: MatchingBenchmarkSuite,
    case_key: str,
    user: User,
    payload: BenchmarkRatingWrite,
) -> MatchingBenchmarkRating:
    if user.role not in {"hr", "manager"}:
        raise BenchmarkAccessError("Only HR and department managers can rate benchmark cases")
    if suite.status != "blind":
        raise BenchmarkStateError("Ratings are locked after the suite is revealed")
    case = db.scalar(
        select(MatchingBenchmarkCase).where(
            MatchingBenchmarkCase.suite_id == suite.id,
            MatchingBenchmarkCase.case_key == case_key,
            MatchingBenchmarkCase.is_active.is_(True),
        )
    )
    if case is None:
        raise BenchmarkNotFoundError("Benchmark case not found")
    if payload.priority_rank is not None:
        duplicate_rank = db.scalar(
            select(MatchingBenchmarkRating.id)
            .join(
                MatchingBenchmarkCase,
                MatchingBenchmarkCase.id == MatchingBenchmarkRating.case_id,
            )
            .where(
                MatchingBenchmarkCase.suite_id == suite.id,
                MatchingBenchmarkCase.job_key == case.job_key,
                MatchingBenchmarkRating.reviewer_id == user.id,
                MatchingBenchmarkRating.priority_rank == payload.priority_rank,
                MatchingBenchmarkRating.case_id != case.id,
            )
        )
        if duplicate_rank is not None:
            raise BenchmarkConflictError(
                f"Priority rank {payload.priority_rank} is already used for this job"
            )
    rating = db.scalar(
        select(MatchingBenchmarkRating).where(
            MatchingBenchmarkRating.case_id == case.id,
            MatchingBenchmarkRating.reviewer_id == user.id,
        )
    )
    if rating is None:
        rating = MatchingBenchmarkRating(
            case_id=case.id,
            reviewer_id=user.id,
            reviewer_role=user.role,
            verdict=payload.verdict,
            reasons=list(payload.reasons),
        )
        db.add(rating)
    rating.reviewer_role = user.role
    rating.verdict = payload.verdict
    rating.reasons = list(payload.reasons)
    rating.note = payload.note.strip() if payload.note and payload.note.strip() else None
    rating.priority_rank = payload.priority_rank
    db.commit()
    db.refresh(rating)
    return rating


def reveal_benchmark_suite(
    db: Session,
    suite: MatchingBenchmarkSuite,
    user: User,
) -> MatchingBenchmarkSuite:
    if user.role != "hr":
        raise BenchmarkAccessError("Only HR can reveal a completed benchmark suite")
    if suite.status == "revealed":
        return suite
    progress = benchmark_progress(db, suite)
    incomplete = [item["role"] for item in progress if item["complete_reviewer_count"] < 1]
    if incomplete:
        roles = ", ".join(incomplete)
        raise BenchmarkStateError(
            f"Cannot reveal until one reviewer has completed every case for: {roles}"
        )
    suite.status = "revealed"
    suite.revealed_at = datetime.now(UTC)
    suite.revealed_by_user_id = user.id
    db.commit()
    db.refresh(suite)
    return suite


def _consensus(ratings: Iterable[MatchingBenchmarkRating]) -> str | None:
    counts = Counter(item.verdict for item in ratings)
    if not counts:
        return None
    highest = max(counts.values())
    winners = [verdict for verdict, count in counts.items() if count == highest]
    return winners[0] if len(winners) == 1 else None


def _available_percent(
    numerator: int,
    denominator: int,
    *,
    minimum: int,
    explanation: str,
) -> MetricResult:
    if denominator < minimum:
        return MetricResult(
            status="insufficient_data",
            value=None,
            numerator=None,
            denominator=denominator,
            unit="percent",
            explanation=f"{explanation}；至少需要 {minimum} 筆，目前不足。",
        )
    return MetricResult(
        status="available",
        value=round(numerator / denominator * 100, 2),
        numerator=numerator,
        denominator=denominator,
        unit="percent",
        explanation=explanation,
    )


def _role_top_k_metrics(
    cases: list[MatchingBenchmarkCase],
    consensus_by_case_role: dict[tuple[int, str], str | None],
    priority_by_case_role: dict[tuple[int, str], float],
    role: str,
) -> tuple[MetricResult, MetricResult, int]:
    jobs: dict[str, list[MatchingBenchmarkCase]] = defaultdict(list)
    for case in cases:
        jobs[case.job_key].append(case)
    overlap = 0
    false_negative = 0
    denominator = 0
    eligible_groups = 0
    for job_cases in jobs.values():
        labelled = [
            case
            for case in job_cases
            if consensus_by_case_role.get((case.id, role)) is not None
        ]
        if len(job_cases) < TOP_K or len(labelled) != len(job_cases):
            continue
        system_top = {
            case.id
            for case in sorted(
                job_cases,
                key=lambda item: (
                    not item.system_gate_passed,
                    -float(item.system_score),
                    item.sequence,
                ),
            )[:TOP_K]
        }
        human_top = {
            case.id
            for case in sorted(
                labelled,
                key=lambda item: (
                    VERDICT_ORDER[consensus_by_case_role[(item.id, role)]],
                    priority_by_case_role.get((item.id, role), 999.0),
                    item.sequence,
                ),
            )[:TOP_K]
        }
        intersection = len(system_top & human_top)
        overlap += intersection
        false_negative += TOP_K - intersection
        denominator += TOP_K
        eligible_groups += 1
    explanation = (
        f"每個職缺比較系統前 {TOP_K} 名與 {role.upper()} 盲評前 {TOP_K} 名；"
        "同類評語先依選填優先序，再依固定案例順序處理。"
    )
    overlap_metric = _available_percent(
        overlap,
        denominator,
        minimum=TOP_K * MIN_TOP_K_JOB_GROUPS,
        explanation=explanation,
    )
    false_negative_metric = _available_percent(
        false_negative,
        denominator,
        minimum=TOP_K * MIN_TOP_K_JOB_GROUPS,
        explanation=f"{role.upper()} 前 {TOP_K} 名未進入系統前 {TOP_K} 名的比例。",
    )
    return overlap_metric, false_negative_metric, eligible_groups


def build_benchmark_report(db: Session, suite: MatchingBenchmarkSuite) -> dict[str, Any]:
    if suite.status != "revealed":
        raise BenchmarkStateError("Report remains hidden until the suite is revealed")
    cases = _active_cases(db, suite.id)
    case_ids = [case.id for case in cases]
    complete_reviewer_ids = _complete_reviewer_ids(db, suite)
    ratings = list(
        db.scalars(
            select(MatchingBenchmarkRating).where(
                MatchingBenchmarkRating.case_id.in_(case_ids),
                MatchingBenchmarkRating.reviewer_id.in_(complete_reviewer_ids),
            )
        ).all()
    ) if case_ids and complete_reviewer_ids else []
    grouped: dict[tuple[int, str], list[MatchingBenchmarkRating]] = defaultdict(list)
    priorities: dict[tuple[int, str], list[int]] = defaultdict(list)
    for rating in ratings:
        key = (rating.case_id, rating.reviewer_role)
        grouped[key].append(rating)
        if rating.priority_rank is not None:
            priorities[key].append(rating.priority_rank)
    consensus_by_case_role = {key: _consensus(items) for key, items in grouped.items()}
    priority_by_case_role = {key: mean(values) for key, values in priorities.items()}

    metrics: dict[str, MetricResult] = {}
    top_k_groups: dict[str, int] = {}
    for role in ("hr", "manager"):
        overlap, false_negative, group_count = _role_top_k_metrics(
            cases,
            consensus_by_case_role,
            priority_by_case_role,
            role,
        )
        metrics[f"top5_overlap_{role}"] = overlap
        metrics[f"top5_false_negative_{role}"] = false_negative
        top_k_groups[role] = group_count

        positives = [
            case
            for case in cases
            if consensus_by_case_role.get((case.id, role)) in POSITIVE_VERDICTS
        ]
        gate_misses = sum(not case.system_gate_passed for case in positives)
        metrics[f"gate_miss_{role}"] = _available_percent(
            gate_misses,
            len(positives),
            minimum=MIN_POSITIVE_CASES,
            explanation=f"{role.upper()} 認為可面試或可考慮，但系統必要條件未通過的比例。",
        )

    paired = [
        case
        for case in cases
        if consensus_by_case_role.get((case.id, "hr")) is not None
        and consensus_by_case_role.get((case.id, "manager")) is not None
    ]
    agreements = sum(
        consensus_by_case_role[(case.id, "hr")]
        == consensus_by_case_role[(case.id, "manager")]
        for case in paired
    )
    metrics["role_agreement"] = _available_percent(
        agreements,
        len(paired),
        minimum=MIN_ROLE_AGREEMENT_PAIRS,
        explanation="HR 與主管對同一案例給出完全相同四分類評語的比例。",
    )

    any_role_positives = [
        case
        for case in cases
        if any(
            consensus_by_case_role.get((case.id, role)) in POSITIVE_VERDICTS
            for role in ("hr", "manager")
        )
    ]
    metrics["gate_miss_any_role"] = _available_percent(
        sum(not case.system_gate_passed for case in any_role_positives),
        len(any_role_positives),
        minimum=MIN_POSITIVE_CASES,
        explanation="任一角色認為正向，但系統必要條件未通過的案例比例。",
    )
    if len(cases) < MIN_REPORT_CASES:
        metrics["data_completeness"] = MetricResult(
            status="insufficient_data",
            value=None,
            numerator=None,
            denominator=len(cases),
            unit="score",
            explanation=f"至少需要 {MIN_REPORT_CASES} 個案例才呈現平均完整度。",
        )
    else:
        metrics["data_completeness"] = MetricResult(
            status="available",
            value=round(mean(float(case.data_completeness) for case in cases), 2),
            numerator=None,
            denominator=len(cases),
            unit="score",
            explanation="七項履歷資訊維度的平均填寫完整度（0–100），不是人才適合度。",
        )

    progress = benchmark_progress(db, suite)
    warnings = [
        "本報表使用合成案例，只能驗證流程與相對排序；不可宣稱為真實錄取預測準確率。",
        "50 組案例仍屬小樣本；建議累積匿名化實務覆核後再調整正式門檻或權重。",
    ]
    for item in progress:
        if item["complete_reviewer_count"] < 2:
            warnings.append(
                f"{item['role'].upper()} 目前只有 {item['complete_reviewer_count']} 位完整評審，"
                "個人偏好可能明顯影響結果。"
            )
    for role, count in top_k_groups.items():
        if count < MIN_TOP_K_JOB_GROUPS:
            warnings.append(
                f"{role.upper()} 可計算 Top-5 的職缺群組只有 {count} 個，相關指標顯示為未知。"
            )
    if any(metric.status == "insufficient_data" for metric in metrics.values()):
        warnings.append("部分分母未達最低門檻；未知值保留為 null，沒有以 0 代替。")

    return {
        "suite": suite_payload(db, suite),
        "generated_at": datetime.now(UTC),
        "metrics": metrics,
        "warnings": warnings,
        "cases": [
            {
                "case_key": case.case_key,
                "job_key": case.job_key,
                "scenario": case.scenario,
                "expected_verdict": case.expected_verdict,
                "system_score": float(case.system_score),
                "system_gate_passed": case.system_gate_passed,
                "data_completeness": float(case.data_completeness),
                "system_gate_misses": list(
                    (case.system_breakdown or {}).get("gate", {}).get("miss", [])
                ),
                "hr_verdict": consensus_by_case_role.get((case.id, "hr")),
                "manager_verdict": consensus_by_case_role.get((case.id, "manager")),
            }
            for case in cases
        ],
    }
