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
    # JavaScript / web ecosystem
    "fast api": "fastapi",
    "nodejs": "node.js",
    "node js": "node.js",
    "node": "node.js",
    "js": "javascript",
    "ts": "typescript",
    "react.js": "react",
    "reactjs": "react",
    "react js": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "vue js": "vue",
    "angular.js": "angular",
    "angularjs": "angular",
    "nextjs": "next.js",
    "nestjs": "nest.js",
    # databases
    "postgres": "postgresql",
    "postgres sql": "postgresql",
    "postgre sql": "postgresql",
    "ms sql": "sql server",
    "mssql": "sql server",
    "sqlserver": "sql server",
    "資料庫": "database",
    # languages
    "golang": "go",
    "c#": "csharp",
    "c sharp": "csharp",
    "c++": "cpp",
    "c plus plus": "cpp",
    ".net": "dotnet",
    "dot net": "dotnet",
    "objective c": "objective-c",
    # cloud / devops
    "amazon web services": "aws",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "microsoft azure": "azure",
    "k8s": "kubernetes",
    "ci/cd": "cicd",
    "ci cd": "cicd",
    "powerbi": "power bi",
    # data / ml (Chinese <-> English)
    "ml": "machine learning",
    "機器學習": "machine learning",
    "dl": "deep learning",
    "深度學習": "deep learning",
    "nlp": "natural language processing",
    "自然語言處理": "natural language processing",
    "資料分析": "data analysis",
    "數據分析": "data analysis",
    "資料科學": "data science",
    "數據科學": "data science",
    # roles / soft skills (Chinese <-> English)
    "專案管理": "project management",
    "跨部門溝通": "cross-functional communication",
    "使用者經驗": "ux",
    "user experience": "ux",
    "使用者介面": "ui",
    "user interface": "ui",
    "品質保證": "qa",
    "quality assurance": "qa",
    "資訊安全": "cybersecurity",
    "網路安全": "cybersecurity",
    "information security": "cybersecurity",
}
# Conservative fuzzy fallback for skills that aren't in the alias table (e.g. minor
# spelling variants). Only applied to canonical tokens of length >= 5 to avoid
# false merges of short/unrelated skills.
SKILL_FUZZY_THRESHOLD = 0.86
# Canonical role tokens for title relevance, bilingual so a Chinese title aligns
# with an English one (e.g. 資深後端工程師 -> {senior, backend, engineer}).
TITLE_TOKEN_SYNONYMS = {
    # seniority
    "資深": "senior", "senior": "senior", "sr": "senior",
    "初級": "junior", "junior": "junior", "jr": "junior",
    "首席": "principal", "principal": "principal", "lead": "lead", "leader": "lead",
    # function
    "工程師": "engineer", "engineer": "engineer", "developer": "engineer",
    "開發": "engineer", "programmer": "engineer",
    "設計師": "designer", "designer": "designer",
    "分析師": "analyst", "analyst": "analyst",
    "經理": "manager", "manager": "manager", "主管": "manager",
    "專員": "specialist", "specialist": "specialist",
    "架構師": "architect", "architect": "architect",
    "科學家": "scientist", "scientist": "scientist",
    "顧問": "consultant", "consultant": "consultant",
    # domain
    "後端": "backend", "backend": "backend", "back end": "backend", "back-end": "backend",
    "前端": "frontend", "frontend": "frontend", "front end": "frontend", "front-end": "frontend",
    "全端": "fullstack", "fullstack": "fullstack", "full stack": "fullstack",
    "軟體": "software", "software": "software",
    "資料": "data", "數據": "data", "data": "data",
    "雲端": "cloud", "cloud": "cloud",
    "行動": "mobile", "mobile": "mobile",
    "產品": "product", "product": "product",
    "專案": "project", "project": "project",
    "行銷": "marketing", "marketing": "marketing",
    "業務": "sales", "sales": "sales",
    "財務": "finance", "finance": "finance",
    "會計": "accounting", "accounting": "accounting",
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


def _skill_similarity(a: str, b: str) -> float:
    """Similarity of two already-canonical skill tokens; conservative fuzzy match
    only for tokens long enough that a high ratio is unlikely to be coincidental."""
    if a == b:
        return 1.0
    if len(a) < 5 or len(b) < 5:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _match_skill(target_canonical: str, candidate_map: dict[str, str]) -> str | None:
    """Return the candidate's original skill label that satisfies target_canonical
    (exact canonical match first, then conservative fuzzy), or None if unmet."""
    exact = candidate_map.get(target_canonical)
    if exact is not None:
        return exact
    best_label, best_sim = None, 0.0
    for canonical, original in candidate_map.items():
        similarity = _skill_similarity(target_canonical, canonical)
        if similarity >= SKILL_FUZZY_THRESHOLD and similarity > best_sim:
            best_label, best_sim = original, similarity
    return best_label


def _title_tokens(title: str | None) -> set[str]:
    text = " ".join((title or "").strip().casefold().replace("臺", "台").split())
    return {canonical for token, canonical in TITLE_TOKEN_SYNONYMS.items() if token in text}


def _title_relevance(candidate_title: str | None, requisition_title: str | None) -> float:
    """Role-family similarity via canonical role tokens, so a Chinese title aligns
    with an English one. Falls back to character similarity only when neither side
    exposes a known role token."""
    if not candidate_title:
        return 0.5
    candidate_tokens = _title_tokens(candidate_title)
    requisition_tokens = _title_tokens(requisition_title)
    if candidate_tokens and requisition_tokens:
        overlap = len(candidate_tokens & requisition_tokens)
        return overlap / len(candidate_tokens | requisition_tokens)
    return SequenceMatcher(
        None, normalize_text(candidate_title), normalize_text(requisition_title)
    ).ratio()


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


def _candidate_cities(candidate: Candidate) -> list[str]:
    return candidate.expected_cities or ([candidate.city] if candidate.city else [])


def _location_score(candidate: Candidate, work_city: str) -> float:
    candidate_cities = _candidate_cities(candidate)
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


def _match_highlights(
    *,
    required_hits: list[str],
    preferred_hits: list[str],
    required_misses: list[str],
    preferred_misses: list[str],
    gate_misses: list[str],
    years: float | None,
    min_years: float | None,
    title_score: float,
    location_score: float,
    work_city: str,
    missing_fields: list[str],
) -> list[dict[str, str]]:
    """Build concise, ordered evidence bullets for humans reviewing a score."""

    gate_labels = {
        "candidate_deleted": "人才資料已刪除",
        "blacklisted": "人才列入黑名單",
        "consent_withdrawn": "人才已撤回資料使用同意",
        "required_skills": "必要技能",
        "required_skills_unknown": "必要技能資料不足",
        "minimum_years": "最低年資",
        "minimum_years_unknown": "工作年資資料不足",
        "education": "學歷要求",
        "education_unknown": "學歷資料不足",
        "location": "工作地點",
    }

    def gate_label(code: str) -> str:
        if code.startswith("status:"):
            return f"人才狀態（{code.removeprefix('status:')}）"
        return gate_labels.get(code, code)

    highlights: list[dict[str, str]] = []
    skill_hits = required_hits + preferred_hits
    skill_misses = required_misses + preferred_misses
    if skill_hits:
        highlights.append(
            {
                "kind": "strength",
                "category": "skill",
                "text": f"符合技能：{'、'.join(skill_hits)}",
            }
        )
    if skill_misses:
        highlights.append(
            {
                "kind": "concern",
                "category": "skill",
                "text": f"尚缺技能：{'、'.join(skill_misses)}",
            }
        )
    if min_years is not None:
        if years is None:
            highlights.append(
                {
                    "kind": "concern",
                    "category": "years",
                    "text": f"未提供年資；職缺最低要求 {min_years:g} 年",
                }
            )
        elif years >= min_years:
            highlights.append(
                {
                    "kind": "strength",
                    "category": "years",
                    "text": f"年資 {years:g} 年，達到最低要求 {min_years:g} 年",
                }
            )
        else:
            highlights.append(
                {
                    "kind": "concern",
                    "category": "years",
                    "text": f"年資 {years:g} 年，低於最低要求 {min_years:g} 年",
                }
            )
    if title_score >= 0.7:
        highlights.append(
            {
                "kind": "strength",
                "category": "relevance",
                "text": "目前職稱與應徵職稱高度相關",
            }
        )
    elif title_score < 0.4:
        highlights.append(
            {
                "kind": "concern",
                "category": "relevance",
                "text": "目前職稱與應徵職稱相關度偏低，建議人工確認可轉移經驗",
            }
        )
    if location_score == 1:
        highlights.append(
            {
                "kind": "strength",
                "category": "location",
                "text": f"期望工作地點符合：{work_city}",
            }
        )
    elif location_score == 0.6:
        highlights.append(
            {
                "kind": "info",
                "category": "location",
                "text": f"期望地點鄰近工作地點 {work_city}，建議確認通勤意願",
            }
        )
    elif location_score < 0.5:
        highlights.append(
            {
                "kind": "concern",
                "category": "location",
                "text": f"期望地點與工作地點 {work_city} 不符",
            }
        )
    if gate_misses:
        highlights.insert(
            0,
            {
                "kind": "concern",
                "category": "gate",
                "text": f"未通過必要條件：{'、'.join(map(gate_label, gate_misses))}",
            },
        )
    if missing_fields:
        highlights.append(
            {
                "kind": "info",
                "category": "data_quality",
                "text": f"資料待補：{'、'.join(missing_fields)}",
            }
        )
    return highlights[:8]


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
    required_hits: list[str] = []
    required_misses: list[str] = []
    preferred_hits: list[str] = []
    preferred_misses: list[str] = []
    skill_evidence: dict[str, str] = {}
    for skill in required:
        matched = _match_skill(canonical_skill(skill), normalized_candidate_skills)
        if matched is not None:
            required_hits.append(skill)
            skill_evidence[skill] = matched
        else:
            required_misses.append(skill)
    for skill in preferred:
        matched = _match_skill(canonical_skill(skill), normalized_candidate_skills)
        if matched is not None:
            preferred_hits.append(skill)
            skill_evidence[skill] = matched
        else:
            preferred_misses.append(skill)

    candidate_education = max(
        [_education_rank(candidate.highest_education)]
        + [_education_rank(education.degree) for education in candidate.educations]
    )
    required_education = _education_rank(requisition.education_req)
    years = float(candidate.total_years) if candidate.total_years is not None else None
    min_years = float(requisition.min_years) if requisition.min_years is not None else None
    expected_cities = {normalize_text(city) for city in _candidate_cities(candidate)}
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
    required_ratio = config.get("required_skill_ratio", 1.0)
    if not isinstance(required_ratio, int | float) or not 0 <= required_ratio <= 1:
        required_ratio = 1.0
    if config.get("require_skills", True) and required:
        if not normalized_candidate_skills:
            gate_misses.append("required_skills_unknown")
        elif len(required_hits) / len(required) < required_ratio:
            gate_misses.append("required_skills")
    if config.get("require_years", True) and min_years is not None:
        if years is None:
            gate_misses.append("minimum_years_unknown")
        elif years < min_years:
            gate_misses.append("minimum_years")
    if config.get("require_education", True) and required_education:
        if candidate_education == 0:
            gate_misses.append("education_unknown")
        elif candidate_education < required_education:
            gate_misses.append("education")
    work_adjacent = {
        normalize_text(city)
        for city in ADJACENT_CITIES.get(normalize_text(requisition.work_city), set())
    }
    if (
        config.get("require_location", True)
        and expected_cities
        and work_city not in expected_cities
        and not (expected_cities & work_adjacent)
    ):
        gate_misses.append("location")

    skill_denominator = len(required) * 2 + len(preferred)
    skill_known = bool(normalized_candidate_skills) or not skill_denominator
    skill_score = (
        (len(required_hits) * 2 + len(preferred_hits)) / skill_denominator
        if skill_denominator and skill_known
        else 0.5
        if skill_denominator
        else 1.0
    )
    title_score = _title_relevance(candidate.current_title, requisition.title)
    years_score = (
        1.0
        if min_years is None
        else 0.5
        if years is None
        else min(1.0, years / max(min_years, 0.1))
    )
    salary_score = _salary_score(candidate, requisition)
    education_score = (
        1.0
        if required_education == 0 or candidate_education >= required_education
        else 0.5
        if candidate_education == 0
        else candidate_education / required_education
    )
    location_score = _location_score(candidate, requisition.work_city)
    salary_known = bool(
        (candidate.expected_salary_min is not None or candidate.expected_salary_max is not None)
        and (requisition.salary_min is not None or requisition.salary_max is not None)
    )
    location_known = bool(_candidate_cities(candidate))
    education_known = candidate_education > 0 or required_education == 0
    components = {
        "skill": (
            skill_score,
            required_hits + preferred_hits,
            required_misses + preferred_misses,
            skill_known,
        ),
        "relevance": (
            title_score,
            [candidate.current_title] if candidate.current_title else [],
            [],
            bool(candidate.current_title),
        ),
        "years": (years_score, [years] if years is not None else [], [], years is not None),
        "salary": (salary_score, [], [], salary_known),
        "education": (
            education_score,
            [],
            [requisition.education_req]
            if "education" in gate_misses or "education_unknown" in gate_misses
            else [],
            education_known,
        ),
        "location": (
            location_score,
            [requisition.work_city] if location_score == 1 else [],
            [],
            location_known,
        ),
    }
    missing_fields = [
        field
        for field, value in (
            ("skills", normalized_candidate_skills or None),
            ("current_title", candidate.current_title),
            ("total_years", candidate.total_years),
            ("highest_education", candidate_education if candidate_education else None),
            (
                "expected_salary",
                candidate.expected_salary_min
                if candidate.expected_salary_min is not None
                else candidate.expected_salary_max,
            ),
            ("location", candidate.expected_cities or candidate.city),
        )
        if value is None
    ]
    completeness = max(0.0, 1 - len(set(missing_fields)) / 6)
    confidence = (
        "high" if completeness >= 0.8 else "medium" if completeness >= 0.6 else "low"
    )
    breakdown: dict[str, Any] = {
        "gate": {"passed": not gate_misses, "miss": gate_misses},
        "data_quality": {
            "missing": missing_fields,
            "total_fields": 6,
            "completeness": round(completeness, 4),
            "confidence": confidence,
        },
    }
    weighted_total = 0.0
    for key, (component_score, hits, misses, known) in components.items():
        contribution = weights[key] * component_score
        weighted_total += contribution
        breakdown[key] = {
            "weight": round(weights[key], 4),
            "score": round(component_score, 4),
            "contribution": round(contribution * 100, 2),
            "hit": hits,
            "miss": misses,
            "known": known,
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
    # Surface "so close" candidates: gated by a single hard requirement yet still a
    # strong fit, so HR can review stretch picks instead of never seeing them.
    breakdown["near_miss"] = (not passed) and len(gate_misses) == 1 and total >= 60
    breakdown["highlights"] = _match_highlights(
        required_hits=required_hits,
        preferred_hits=preferred_hits,
        required_misses=required_misses if skill_known else [],
        preferred_misses=preferred_misses if skill_known else [],
        gate_misses=gate_misses,
        years=years,
        min_years=min_years,
        title_score=title_score,
        location_score=location_score,
        work_city=requisition.work_city,
        missing_fields=missing_fields,
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
            if (
                result.status in AUTO_STATUSES
                and result.stage_updated_at is None
                and result.manual_override_at is None
            ):
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
        completeness_scores.append(item.data_completeness)
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


def evaluate_matching(results: list[MatchResult]) -> dict[str, Any]:
    """Grade the matching engine against human outcome labels so HR can judge accuracy.

    Ground truth is the human `status`: POSITIVE_OUTCOME_STATUSES are people the engine
    surfaced who advanced (interview/offered/hired); NEGATIVE_OUTCOME_STATUSES are ones a
    manager turned down. Precision asks "are the top ranks worth reviewing?"; recall asks
    "did the gate or ranking bury someone good?"; calibration asks "does a higher score
    really mean a better outcome?". Every metric returns None instead of dividing by an
    empty set, so unlabeled or empty data reads as "unknown", not a misleading zero.
    """

    eligible = [item for item in results if item.gate_passed]
    labeled = [
        item
        for item in results
        if item.status in POSITIVE_OUTCOME_STATUSES | NEGATIVE_OUTCOME_STATUSES
    ]
    positives = [item for item in labeled if item.status in POSITIVE_OUTCOME_STATUSES]
    negatives = [item for item in labeled if item.status in NEGATIVE_OUTCOME_STATUSES]

    def precision_at_k(k: int) -> float | None:
        # Of the top-K eligible results by rank (None last), the labeled fraction that
        # ended positive.  Generalizes assess_matching_readiness's precision_at_5.
        top_k = sorted(
            eligible,
            key=lambda item: (item.rank is None, item.rank or 0, -float(item.total_score)),
        )[:k]
        labeled_top_k = [item for item in top_k if item in labeled]
        if not labeled_top_k:
            return None
        return round(
            sum(item.status in POSITIVE_OUTCOME_STATUSES for item in labeled_top_k)
            / len(labeled_top_k),
            4,
        )

    def recall_at_k(k: int) -> float | None:
        # Of every positive-labeled result, the fraction the ranking placed within K.
        # A low value means good people were buried below the fold (false negatives).
        if not positives:
            return None
        found = sum(1 for item in positives if item.rank is not None and item.rank <= k)
        return round(found / len(positives), 4)

    # A human advanced an "ineligible" match to a positive outcome, so the hard gate
    # wrongly excluded a good candidate.
    gate_false_negatives = [
        item
        for item in results
        if not item.gate_passed and item.status in POSITIVE_OUTCOME_STATUSES
    ]

    score_buckets = (
        ("0-39", 0.0, 40.0),
        ("40-59", 40.0, 60.0),
        ("60-79", 60.0, 80.0),
        ("80-100", 80.0, 101.0),
    )
    score_calibration = []
    for label, low, high in score_buckets:
        bucket = [item for item in labeled if low <= float(item.total_score) < high]
        bucket_positives = sum(item.status in POSITIVE_OUTCOME_STATUSES for item in bucket)
        score_calibration.append(
            {
                "bucket": label,
                "count": len(bucket),
                "positive_rate": round(bucket_positives / len(bucket), 4) if bucket else None,
            }
        )

    positive_ranks = [item.rank for item in positives if item.rank is not None]
    negative_ranks = [item.rank for item in negatives if item.rank is not None]

    notes: list[str] = []
    if len(labeled) < 10:
        notes.append("small_sample")
    if len(labeled) < 30:
        notes.append("insufficient_for_tuning")

    return {
        "sample_size": len(results),
        "labeled_outcomes": len(labeled),
        "positive_outcomes": len(positives),
        "negative_outcomes": len(negatives),
        "precision_at_k": {"5": precision_at_k(5), "10": precision_at_k(10)},
        "recall_at_k": {"5": recall_at_k(5), "10": recall_at_k(10)},
        "gate_false_negatives": len(gate_false_negatives),
        "gate_false_negative_candidates": [item.candidate_id for item in gate_false_negatives],
        "score_calibration": score_calibration,
        "rank_effectiveness": {
            "avg_rank_positive": round(sum(positive_ranks) / len(positive_ranks), 2)
            if positive_ranks
            else None,
            "avg_rank_negative": round(sum(negative_ranks) / len(negative_ranks), 2)
            if negative_ranks
            else None,
        },
        "notes": notes,
    }
