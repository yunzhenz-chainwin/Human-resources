import re
from dataclasses import dataclass
from types import ModuleType

from app.parsers import generic, p104, p1111
from app.parsers.common import extract_fields


@dataclass(frozen=True)
class AdapterOutput:
    platform: str
    version: str
    layout_recognized: bool
    payload: dict
    confidence: dict[str, float]
    source_confidence: float
    source_evidence: list[dict]
    source_review_required: bool


PLATFORM_MODULES: dict[str, ModuleType] = {"p104": p104, "p1111": p1111}


def _platform_scores(text: str) -> tuple[dict[str, float], dict[str, list[dict]]]:
    """Score platform origin from document content, never filename/extension.

    Brand/domain markers are strongest. Platform-specific title and field labels
    provide supporting layout evidence. Evidence is persisted so HR can explain
    or override a low-confidence classification.
    """
    lowered = text.casefold()
    scores = {"p104": 0.0, "p1111": 0.0}
    evidence: dict[str, list[dict]] = {"p104": [], "p1111": []}
    signals = {
        "p104": (
            ("pda.104.com.tw", 0.80, "platform_domain"),
            ("104人力銀行", 0.20, "platform_brand"),
            ("104求職者履歷", 0.10, "document_title"),
            ("求職者履歷", 0.10, "document_title"),
            ("求職者姓名", 0.03, "platform_field"),
            ("累積年資", 0.03, "platform_field"),
            ("工作技能", 0.03, "platform_field"),
            ("最近工作", 0.03, "platform_field"),
        ),
        "p1111": (
            ("careermaster.1111.com.tw", 0.80, "platform_domain"),
            ("1111人力銀行", 0.20, "platform_brand"),
            ("1111履歷表", 0.10, "document_title"),
            ("履歷姓名", 0.03, "platform_field"),
            ("累計年資", 0.03, "platform_field"),
            ("專長技能", 0.03, "platform_field"),
            ("中文姓名", 0.03, "platform_field"),
            ("所在地", 0.03, "platform_field"),
            ("希望職務", 0.03, "platform_field"),
            ("現職", 0.03, "platform_field"),
        ),
    }
    for platform, platform_signals in signals.items():
        for marker, weight, kind in platform_signals:
            if marker.casefold() in lowered:
                scores[platform] += weight
                evidence[platform].append(
                    {"type": kind, "marker": marker, "weight": weight}
                )
        # Keep adapter signatures extensible without counting a marker twice.
        for signature in PLATFORM_MODULES[platform].SIGNATURES:
            if (
                signature.casefold() in lowered
                and not any(item["marker"] == signature for item in evidence[platform])
            ):
                scores[platform] += 0.10
                evidence[platform].append(
                    {"type": "adapter_signature", "marker": signature, "weight": 0.10}
                )
        field_count = sum(item["type"] == "platform_field" for item in evidence[platform])
        if field_count >= 3:
            scores[platform] += 0.10
            evidence[platform].append(
                {
                    "type": "platform_field_cluster",
                    "marker": f"{field_count} platform-specific fields",
                    "weight": 0.10,
                }
            )
        scores[platform] = min(scores[platform], 1.0)
    return scores, evidence


def detect_source(
    text: str, requested_platform: str = "generic"
) -> tuple[str, float, list[dict], bool]:
    scores, evidence_by_platform = _platform_scores(text)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_platform, top_score = ranked[0]
    margin = top_score - ranked[1][1]
    top_evidence = evidence_by_platform[top_platform]
    has_export_domain = any(item["type"] == "platform_domain" for item in top_evidence)
    if has_export_domain and top_score >= 0.80 and margin >= 0.50:
        confidence = round(min(0.95, 0.60 + top_score * 0.35), 2)
        return top_platform, confidence, top_evidence, False

    # No board branding means a self-made/general resume. Identity/contact and
    # common section headings are positive evidence, rather than an extension guess.
    generic_evidence: list[dict] = []
    lowered = text.casefold()
    generic_markers = (
        "姓名", "name", "email", "電子郵件", "手機", "電話",
        "工作經歷", "學歷", "skills", "技能",
    )
    for marker in generic_markers:
        if marker.casefold() in lowered:
            generic_evidence.append(
                {"type": "generic_resume_field", "marker": marker, "weight": 0.08}
            )
    if re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
        generic_evidence.append(
            {"type": "contact_pattern", "marker": "email", "weight": 0.12}
        )
    if re.search(r"(?<!\d)0?9\d(?:[\s-]?\d){7}(?!\d)", text):
        generic_evidence.append(
            {"type": "contact_pattern", "marker": "mobile", "weight": 0.12}
        )
    has_platform_claim = any(
        item["type"]
        in {
            "platform_domain",
            "platform_brand",
            "document_title",
            "adapter_signature",
            "platform_field_cluster",
        }
        for item in top_evidence
    )
    if has_platform_claim:
        generic_evidence.append(
            {
                "type": "unverified_platform_claim",
                "scores": scores,
                "weight": 0.0,
                "note": "brand or field labels do not prove an official platform export",
            }
        )
        return "generic", 0.40, generic_evidence, True
    if requested_platform == "direct" and top_score < 0.55:
        generic_evidence.append(
            {"type": "submission_channel", "marker": "direct", "weight": 0.20}
        )
        confidence = min(0.90, 0.55 + len(generic_evidence) * 0.05)
        return "direct", round(confidence, 2), generic_evidence, confidence < 0.70
    if requested_platform in PLATFORM_MODULES and top_score < 0.55:
        generic_evidence.append(
            {
                "type": "uploader_claim",
                "marker": requested_platform,
                "weight": 0.15,
                "note": "not independently verified from document content",
            }
        )
        return requested_platform, 0.35, generic_evidence, True
    confidence = min(0.90, 0.50 + len(generic_evidence) * 0.07)
    if confidence >= 0.70:
        generic_evidence.append(
            {"type": "no_platform_brand", "marker": "self-made resume", "weight": 0.0}
        )
        return "direct", round(confidence, 2), generic_evidence, False
    return "generic", round(confidence, 2), generic_evidence, True


def select_adapter(text: str, requested_platform: str = "generic") -> AdapterOutput:
    platform, source_confidence, source_evidence, source_review_required = detect_source(
        text, requested_platform
    )
    if platform not in {"p104", "p1111", "direct", "generic"}:
        platform = "generic"
    module = PLATFORM_MODULES.get(platform, generic)
    payload, confidence = extract_fields(text, module.RULES)

    # A claimed job-board export without its stable brand marker is an unknown
    # layout.  Never silently treat it as calibrated, even if generic fields parse.
    if platform in PLATFORM_MODULES:
        recognized = source_confidence >= 0.70 and not source_review_required
    else:
        recognized = bool(payload["name"] and (payload["email"] or payload["phone"]))
    return AdapterOutput(
        platform=platform,
        version=module.VERSION,
        layout_recognized=recognized,
        payload=payload,
        confidence=confidence,
        source_confidence=source_confidence,
        source_evidence=source_evidence,
        source_review_required=source_review_required,
    )
