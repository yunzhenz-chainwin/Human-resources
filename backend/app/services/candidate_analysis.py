from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
from math import isfinite
from typing import Any

from app.schemas.candidate_analysis import (
    AnalysisComponent,
    AnalysisHighlight,
    CandidateRoleMatchItem,
)

ALGORITHM_VERSION = "candidate-role-rules-v1.0.0"
SUPPORTED_PAYLOAD_SCHEMA = "talenthub.deidentified-resume.v1"

_WEIGHTS = {
    "skills": 0.40,
    "relevance": 0.30,
    "years": 0.20,
    "industry": 0.10,
}
_LABELS = {
    "skills": "技能條件",
    "relevance": "職稱／經歷相關性",
    "years": "相關年資",
    "industry": "產業／可轉移經驗",
}
_SKILL_ALIASES = {
    "fast api": "fastapi",
    "nodejs": "node.js",
    "node js": "node.js",
    "js": "javascript",
    "ts": "typescript",
    "reactjs": "react",
    "vuejs": "vue",
    "postgres": "postgresql",
    "mssql": "sqlserver",
    "sql server": "sqlserver",
    "golang": "go",
    "c sharp": "c#",
    ".net": "dotnet",
    "dot net": "dotnet",
    "amazon web services": "aws",
    "google cloud platform": "gcp",
    "k8s": "kubernetes",
    "ci cd": "cicd",
    "machinelearning": "machine learning",
}
_TITLE_TERMS = {
    "後端": "backend",
    "backend": "backend",
    "back end": "backend",
    "前端": "frontend",
    "frontend": "frontend",
    "front end": "frontend",
    "全端": "fullstack",
    "fullstack": "fullstack",
    "full stack": "fullstack",
    "資料": "data",
    "數據": "data",
    "data": "data",
    "軟體": "software",
    "software": "software",
    "工程師": "engineer",
    "開發": "engineer",
    "engineer": "engineer",
    "developer": "engineer",
    "分析師": "analyst",
    "analyst": "analyst",
    "產品": "product",
    "product": "product",
    "專案": "project",
    "project": "project",
    "經理": "manager",
    "主管": "manager",
    "manager": "manager",
    "設計師": "designer",
    "designer": "designer",
    "資深": "senior",
    "senior": "senior",
    "初階": "junior",
    "junior": "junior",
}


class UnsupportedAnalysisPayload(ValueError):
    """The stored payload is not safe or compatible with this scorer."""


@dataclass(frozen=True)
class ExperienceRole:
    title: str
    years: float | None
    industry: str | None


@dataclass(frozen=True)
class CandidateAnalysisProfile:
    """Strict allow-list copied from the approved de-identified snapshot.

    This type deliberately has no candidate identifier, name, contact information,
    employer, school, free-form description, filename, or source document content.
    """

    current_title: str | None
    total_years: float | None
    skills: tuple[str, ...]
    experience_roles: tuple[ExperienceRole, ...]
    highest_education: str | None


@dataclass(frozen=True)
class RequisitionAnalysisProfile:
    requisition_id: int
    req_no: str
    title: str
    department_name: str | None
    required_skills: tuple[str, ...]
    preferred_skills: tuple[str, ...]
    min_years: float | None
    require_skills: bool
    require_years: bool
    required_skill_ratio: float
    target_industries: tuple[str, ...]


def _short_string(value: Any, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:maximum] if cleaned else None


def _safe_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    number = float(value)
    if not isfinite(number) or number < 0 or number > 80:
        return None
    return number


def _safe_string_list(value: Any, *, maximum_items: int = 100) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for raw in value[:maximum_items]:
        item = _short_string(raw, maximum=100)
        if item is None:
            continue
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def build_candidate_profile(
    payload: Mapping[str, Any],
    *,
    payload_schema_version: str | None = None,
) -> CandidateAnalysisProfile:
    """Copy only the approved analysis fields into an immutable, pure-data profile."""

    if not isinstance(payload, Mapping):
        raise UnsupportedAnalysisPayload("De-identified analysis payload is unavailable")
    embedded_version = payload.get("schema_version")
    if payload_schema_version != SUPPORTED_PAYLOAD_SCHEMA:
        raise UnsupportedAnalysisPayload("Unsupported de-identified payload schema")
    if embedded_version != SUPPORTED_PAYLOAD_SCHEMA:
        raise UnsupportedAnalysisPayload("De-identified payload schema marker is invalid")

    # Only these three keys are read from each role.  In particular, company,
    # description, dates, locations, and any unexpected nested fields are discarded.
    roles_value = payload.get("experience_roles")
    roles: list[ExperienceRole] = []
    if isinstance(roles_value, list):
        for raw_role in roles_value[:50]:
            if not isinstance(raw_role, Mapping):
                continue
            title = _short_string(raw_role.get("title"), maximum=150)
            industry = _short_string(raw_role.get("industry"), maximum=100)
            years = _safe_number(raw_role.get("years"))
            if title is not None or industry is not None or years is not None:
                roles.append(ExperienceRole(title or "", years, industry))

    return CandidateAnalysisProfile(
        current_title=_short_string(payload.get("current_title"), maximum=150),
        total_years=_safe_number(payload.get("total_years")),
        skills=_safe_string_list(payload.get("skills")),
        experience_roles=tuple(roles),
        highest_education=_short_string(payload.get("highest_education"), maximum=50),
    )


def _configuration_list(config: Mapping[str, Any], *keys: str) -> tuple[str, ...]:
    for key in keys:
        value = config.get(key)
        if isinstance(value, str):
            item = _short_string(value, maximum=100)
            return (item,) if item else ()
        if isinstance(value, list):
            return _safe_string_list(value, maximum_items=50)
    return ()


def build_requisition_profile(requisition: Any) -> RequisitionAnalysisProfile:
    """Create the other pure-data input used by the deterministic scorer."""

    config_value = getattr(requisition, "match_weights", None)
    config: Mapping[str, Any] = config_value if isinstance(config_value, Mapping) else {}
    configured_required = config.get("required_skills")
    required_skills = (
        _safe_string_list(configured_required)
        if isinstance(configured_required, list)
        else _safe_string_list(getattr(requisition, "skills", None))
    )
    preferred_skills = _safe_string_list(config.get("preferred_skills"))
    min_years = _safe_number(getattr(requisition, "min_years", None))
    raw_ratio = config.get("required_skill_ratio", 1.0)
    ratio = float(raw_ratio) if isinstance(raw_ratio, int | float) else 1.0
    department = getattr(requisition, "department", None)
    department_name = _short_string(getattr(department, "name", None), maximum=100)
    return RequisitionAnalysisProfile(
        requisition_id=int(requisition.id),
        req_no=str(requisition.req_no),
        title=str(requisition.title),
        department_name=department_name,
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        min_years=min_years,
        require_skills=config.get("require_skills", True) is not False,
        require_years=config.get("require_years", True) is not False,
        required_skill_ratio=max(0.0, min(1.0, ratio)),
        target_industries=_configuration_list(
            config,
            "required_industries",
            "preferred_industries",
            "industries",
            "industry",
        ),
    )


def _normalize_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[a-z0-9+#.]+|[\u3400-\u9fff]+", normalized))


def _canonical_skill(value: str) -> str:
    readable = _normalize_text(value)
    alias = _SKILL_ALIASES.get(readable, readable)
    return re.sub(r"\s+", "", alias)


def _skill_matches(target: str, candidate_skills: tuple[str, ...]) -> bool:
    canonical_target = _canonical_skill(target)
    if not canonical_target:
        return False
    for candidate in candidate_skills:
        canonical_candidate = _canonical_skill(candidate)
        if canonical_target == canonical_candidate:
            return True
        if min(len(canonical_target), len(canonical_candidate)) >= 5:
            if SequenceMatcher(None, canonical_target, canonical_candidate).ratio() >= 0.9:
                return True
    return False


def _title_tokens(value: str) -> set[str]:
    text = _normalize_text(value)
    return {canonical for term, canonical in _TITLE_TERMS.items() if term in text}


def _text_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    containment = (
        min(len(normalized_left), len(normalized_right))
        / max(len(normalized_left), len(normalized_right))
        if normalized_left in normalized_right or normalized_right in normalized_left
        else 0.0
    )
    left_tokens = _title_tokens(normalized_left)
    right_tokens = _title_tokens(normalized_right)
    token_score = (
        len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if left_tokens and right_tokens
        else 0.0
    )
    sequence = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    return max(containment, token_score, sequence)


def _component(
    key: str,
    *,
    score: float | None,
    known: bool,
    hit: list[str] | None = None,
    miss: list[str] | None = None,
) -> AnalysisComponent:
    return AnalysisComponent(
        key=key,
        label=_LABELS[key],
        score=round(score, 2) if score is not None else None,
        known=known,
        weight=_WEIGHTS[key],
        hit=(hit or [])[:20],
        miss=(miss or [])[:20],
    )


def _skill_component(
    candidate: CandidateAnalysisProfile,
    role: RequisitionAnalysisProfile,
    insufficient: list[str],
) -> tuple[AnalysisComponent, list[str], list[str]]:
    targets = role.required_skills + role.preferred_skills
    if not targets:
        insufficient.append("職缺未設定可比較的技能條件")
        return _component("skills", score=None, known=False), [], []
    if not candidate.skills:
        insufficient.append("去識別化履歷未提供技能資料")
        return _component("skills", score=None, known=False), [], []

    required_hits = [
        skill for skill in role.required_skills if _skill_matches(skill, candidate.skills)
    ]
    preferred_hits = [
        skill for skill in role.preferred_skills if _skill_matches(skill, candidate.skills)
    ]
    required_misses = [skill for skill in role.required_skills if skill not in required_hits]
    preferred_misses = [skill for skill in role.preferred_skills if skill not in preferred_hits]
    denominator = len(role.required_skills) * 2 + len(role.preferred_skills)
    numerator = len(required_hits) * 2 + len(preferred_hits)
    score = 100.0 if denominator == 0 else numerator / denominator * 100
    return (
        _component(
            "skills",
            score=score,
            known=True,
            hit=required_hits + preferred_hits,
            miss=required_misses + preferred_misses,
        ),
        required_hits,
        required_misses,
    )


def _relevance_component(
    candidate: CandidateAnalysisProfile,
    role: RequisitionAnalysisProfile,
    insufficient: list[str],
) -> AnalysisComponent:
    candidate_titles = [candidate.current_title] if candidate.current_title else []
    candidate_titles.extend(item.title for item in candidate.experience_roles if item.title)
    if not candidate_titles:
        insufficient.append("去識別化履歷未提供可比較的職稱或經歷角色")
        return _component("relevance", score=None, known=False)
    score = max(_text_similarity(title, role.title) for title in candidate_titles) * 100
    if score >= 60:
        return _component(
            "relevance", score=score, known=True, hit=[f"與「{role.title}」職務方向相關"]
        )
    return _component(
        "relevance", score=score, known=True, miss=[f"與「{role.title}」職務方向關聯較低"]
    )


def _years_component(
    candidate: CandidateAnalysisProfile,
    role: RequisitionAnalysisProfile,
    insufficient: list[str],
) -> AnalysisComponent:
    if candidate.total_years is None:
        insufficient.append("去識別化履歷未提供可確認的總年資")
        return _component("years", score=None, known=False)
    if role.min_years is None or role.min_years <= 0:
        return _component("years", score=100, known=True, hit=["職缺未設定最低年資限制"])
    if candidate.total_years >= role.min_years:
        return _component(
            "years",
            score=100,
            known=True,
            hit=[f"達到最低 {role.min_years:g} 年條件"],
        )
    return _component(
        "years",
        score=candidate.total_years / role.min_years * 100,
        known=True,
        miss=[f"未達最低 {role.min_years:g} 年條件"],
    )


def _industry_component(
    candidate: CandidateAnalysisProfile,
    role: RequisitionAnalysisProfile,
    skill_component: AnalysisComponent,
    relevance_component: AnalysisComponent,
    insufficient: list[str],
) -> AnalysisComponent:
    candidate_industries = tuple(
        item.industry for item in candidate.experience_roles if item.industry
    )
    if role.target_industries:
        if not candidate_industries:
            insufficient.append("去識別化履歷未提供可比較的產業類別")
            return _component("industry", score=None, known=False)
        hits = [
            target
            for target in role.target_industries
            if any(_text_similarity(target, industry) >= 0.6 for industry in candidate_industries)
        ]
        misses = [target for target in role.target_industries if target not in hits]
        score = len(hits) / len(role.target_industries) * 100
        return _component("industry", score=score, known=True, hit=hits, miss=misses)

    # Jobs commonly omit a formal industry field.  In that case, use only the two
    # already-computed, allow-listed dimensions as deterministic transferability
    # evidence.  This never exposes candidate titles, industries, or skill strings.
    available = [
        component
        for component in (relevance_component, skill_component)
        if component.known and component.score is not None
    ]
    if not available:
        insufficient.append("缺少可判斷產業或可轉移經驗的資料")
        return _component("industry", score=None, known=False)
    score = sum(float(component.score) for component in available) / len(available)
    if score >= 60:
        return _component("industry", score=score, known=True, hit=["具備可轉移的相關職務或技能"])
    return _component("industry", score=score, known=True, miss=["可轉移經驗與職缺的關聯較低"])


def _highlights(components: list[AnalysisComponent]) -> list[AnalysisHighlight]:
    highlights: list[AnalysisHighlight] = []
    for component in components:
        if component.hit:
            highlights.append(
                AnalysisHighlight(
                    kind="strength",
                    category=component.key,
                    text=f"{component.label}符合：{'、'.join(component.hit)}",
                )
            )
        if component.miss:
            highlights.append(
                AnalysisHighlight(
                    kind="concern",
                    category=component.key,
                    text=f"{component.label}待確認：{'、'.join(component.miss)}",
                )
            )
    return highlights[:8]


def score_requisition(
    candidate: CandidateAnalysisProfile,
    role: RequisitionAnalysisProfile,
) -> CandidateRoleMatchItem:
    """Deterministically score one pure de-identified profile against one role."""

    insufficient: list[str] = []
    skills, required_hits, required_misses = _skill_component(candidate, role, insufficient)
    relevance = _relevance_component(candidate, role, insufficient)
    years = _years_component(candidate, role, insufficient)
    industry = _industry_component(candidate, role, skills, relevance, insufficient)
    components = [skills, relevance, years, industry]

    # Unknown data is neutral (50), not a mismatch.  Completeness/confidence makes
    # that uncertainty explicit and prevents absence from being reported as failure.
    total_score = sum(
        component.weight * (float(component.score) if component.known else 50.0)
        for component in components
    )
    data_completeness = sum(component.weight for component in components if component.known)
    confidence = (
        "high" if data_completeness >= 0.8 else "medium" if data_completeness >= 0.6 else "low"
    )

    gate_passed = True
    if role.require_skills and role.required_skills:
        if not skills.known:
            gate_passed = False
        else:
            hit_ratio = len(required_hits) / len(role.required_skills)
            if required_misses and hit_ratio < role.required_skill_ratio:
                gate_passed = False
    if role.require_years and role.min_years is not None:
        if candidate.total_years is None or candidate.total_years < role.min_years:
            gate_passed = False

    return CandidateRoleMatchItem(
        requisition_id=role.requisition_id,
        req_no=role.req_no,
        title=role.title,
        department_name=role.department_name,
        total_score=round(max(0.0, min(100.0, total_score)), 2),
        gate_passed=gate_passed,
        confidence=confidence,
        data_completeness=round(data_completeness, 2),
        components=components,
        highlights=_highlights(components),
        insufficient_data=list(dict.fromkeys(insufficient)),
    )


def recommendation_sort_key(item: CandidateRoleMatchItem) -> tuple:
    """Stable order: passed gates, score, evidence completeness, then row id."""

    return (
        not item.gate_passed,
        -item.total_score,
        -item.data_completeness,
        item.requisition_id,
    )
