from __future__ import annotations

import hashlib
import hmac
import io
import os
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from fpdf import FPDF
from pydantic import ValidationError
from pypdf import PdfReader
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.candidate import Candidate
from app.models.deidentified_resume import DeidentifiedResumeDocument
from app.models.organization import User
from app.models.recruitment import ResumeFile
from app.schemas.deidentified_resume import (
    DeidentifiedAnalysisPayload,
    DeidentifiedExperienceRole,
)
from app.services.file_scanning import FileScanner
from app.services.storage import (
    StorageProvider,
    get_file_scanner,
    get_storage_provider,
    prepare_resume_upload,
    validate_storage_key,
)

DEIDENTIFICATION_VERSION = "allowlist-reflow-v1"
PAYLOAD_SCHEMA_VERSION = "talenthub.deidentified-resume.v1"
VALIDATION_SCHEMA_VERSION = "talenthub.deidentification-validation.v1"

# A manually uploaded, already de-identified file carries no structured
# analysis payload.  These markers let downstream code distinguish a human
# upload from a system-generated allow-list snapshot without a schema change.
MANUAL_DEIDENTIFICATION_VERSION = "manual-upload-v1"
MANUAL_PAYLOAD_SCHEMA_VERSION = "talenthub.deidentified-resume.manual-upload.v1"
MANUAL_ANALYSIS_PAYLOAD: dict = {"manual_upload": True}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
MOBILE_RE = re.compile(r"(?<!\d)(?:\+?886[-\s]?|0)9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)")
LANDLINE_RE = re.compile(
    r"(?<!\d)(?:\+?886[-\s]?(?:2|[3-8]\d?)|0(?:2|[3-8]\d?))[-\s]?\d{6,8}(?!\d)"
)
TW_ID_RE = re.compile(r"(?<![A-Z0-9])[A-Z][12]\d{8}(?![A-Z0-9])", re.I)
URL_RE = re.compile(r"(?i)(?:https?://|www\.)[^\s<>'\"]+")
DATE_RE = re.compile(
    r"(?<!\d)(?:(?:19|20)\d{2}|1\d{2})[./-](?:0?[1-9]|1[0-2])"
    r"(?:[./-](?:0?[1-9]|[12]\d|3[01]))?(?!\d)"
)

GENERIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", EMAIL_RE),
    ("phone", MOBILE_RE),
    ("phone", LANDLINE_RE),
    ("taiwan_id", TW_ID_RE),
    ("url", URL_RE),
    ("exact_date", DATE_RE),
)

PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "current_title",
        "total_years",
        "skills",
        "experience_roles",
        "highest_education",
    }
)
ROLE_KEYS = frozenset({"title", "years", "industry"})


class DeidentificationError(RuntimeError):
    pass


class SourceDocumentError(DeidentificationError):
    pass


class SourceIntegrityError(DeidentificationError):
    pass


class AnalysisPayloadError(DeidentificationError):
    pass


@dataclass(frozen=True)
class SensitiveValue:
    type: str
    value: str


def _font_path() -> Path:
    # PDF_CJK_FONT_PATH pins the font on a host that keeps it elsewhere, the
    # same way TESSERACT_DIR pins the OCR binary.
    override = os.environ.get("PDF_CJK_FONT_PATH")
    candidates = (
        *([Path(override)] if override else []),
        Path(r"C:\Windows\Fonts\msjh.ttc"),
        Path(r"C:\Windows\Fonts\mingliu.ttc"),
        # macOS: the Noto cask lands in one of the two Library trees; PingFang
        # is the system fallback that is always present.
        Path("/Library/Fonts/NotoSansCJK-Regular.ttc"),
        Path.home() / "Library/Fonts/NotoSansCJK-Regular.ttc",
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("A Traditional Chinese PDF font is not installed")


def _plain_text(value: object | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = "".join(
        character for character in text if not unicodedata.category(character).startswith("C")
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def _number(value: object | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if 0 <= result <= 80 else None


def _education_level(value: object | None) -> str | None:
    text = _plain_text(value, 100)
    if not text:
        return None
    folded = text.casefold()
    levels = (
        (("博士", "doctor", "phd"), "博士"),
        (("碩士", "master", "mba"), "碩士"),
        (("學士", "大學", "bachelor", "university"), "學士"),
        (("副學士", "專科", "associate", "college"), "專科"),
        (("高中", "高職", "high school", "vocational"), "高中／高職"),
        (("國中", "junior high"), "國中"),
    )
    for aliases, normalized in levels:
        if any(alias in folded for alias in aliases):
            return normalized
    # Free-form values often contain a school name.  Unknown values are omitted
    # rather than leaking that institution through an ostensibly safe field.
    return None


def _sensitive_values(candidate: Candidate | None, resume: ResumeFile) -> list[SensitiveValue]:
    values: list[SensitiveValue] = []

    def add(kind: str, value: object | None) -> None:
        text = _plain_text(value, 500)
        if text and len(text) >= 2:
            values.append(SensitiveValue(kind, text))

    payload = resume.parsed_payload if isinstance(resume.parsed_payload, dict) else {}
    for field, kind in (
        ("name", "known_name"),
        ("email", "known_contact"),
        ("phone", "known_contact"),
        ("address", "known_address"),
        ("city", "known_address"),
        ("current_company", "known_company"),
        ("company", "known_company"),
        ("school", "known_school"),
        ("candidate_code", "known_candidate_code"),
        ("code", "known_candidate_code"),
    ):
        add(kind, payload.get(field))
    if candidate is not None:
        for kind, value in (
            ("known_name", candidate.name),
            ("known_candidate_code", candidate.code),
            ("known_contact", candidate.email),
            ("known_contact", candidate.phone),
            ("known_address", candidate.address),
            ("known_address", candidate.city),
            ("known_company", candidate.current_company),
        ):
            add(kind, value)
        for experience in candidate.experiences:
            add("known_company", experience.company)
        for education in candidate.educations:
            add("known_school", education.school)

    # Longest first prevents a short substring from hiding a longer finding.
    unique = {(item.type, item.value.casefold()): item for item in values}
    return sorted(unique.values(), key=lambda item: len(item.value), reverse=True)


def _sanitize_value(
    value: object | None,
    *,
    limit: int,
    sensitive_values: list[SensitiveValue],
    redactions: Counter[str],
) -> str | None:
    text = _plain_text(value, limit * 3)
    if not text:
        return None
    for kind, pattern in GENERIC_PATTERNS:
        text, count = pattern.subn("[REDACTED]", text)
        redactions[kind] += count
    for sensitive in sensitive_values:
        pattern = re.compile(re.escape(sensitive.value), re.I)
        text, count = pattern.subn("[REDACTED]", text)
        redactions[sensitive.type] += count
    text = re.sub(r"(?:\[REDACTED\]\s*)+", "[REDACTED] ", text).strip()
    if not text or text == "[REDACTED]":
        return None
    return text[:limit].rstrip()


def build_analysis_payload(
    candidate: Candidate | None,
    resume: ResumeFile,
) -> tuple[dict, Counter[str], list[SensitiveValue]]:
    sensitive_values = _sensitive_values(candidate, resume)
    redactions: Counter[str] = Counter()
    parsed = resume.parsed_payload if isinstance(resume.parsed_payload, dict) else {}

    current_title_source = candidate.current_title if candidate else parsed.get("current_title")
    years_source = candidate.total_years if candidate else parsed.get("total_years")
    education_source = candidate.highest_education if candidate else parsed.get("highest_education")

    raw_skills: list[object] = []
    if candidate is not None:
        raw_skills.extend(skill.skill for skill in candidate.skills)
    elif isinstance(parsed.get("skills"), list):
        raw_skills.extend(parsed["skills"][:50])

    skills: list[str] = []
    seen_skills: set[str] = set()
    for raw_skill in raw_skills:
        skill = _sanitize_value(
            raw_skill,
            limit=100,
            sensitive_values=sensitive_values,
            redactions=redactions,
        )
        if skill and skill.casefold() not in seen_skills:
            seen_skills.add(skill.casefold())
            skills.append(skill)
        if len(skills) >= 50:
            break

    raw_roles: list[dict] = []
    if candidate is not None:
        raw_roles = [
            {
                "title": experience.title,
                "years": experience.years,
                "industry": experience.industry,
            }
            for experience in sorted(
                candidate.experiences,
                key=lambda item: (item.sort_order, item.id),
            )[:20]
        ]
    elif isinstance(parsed.get("experience_roles"), list):
        raw_roles = [item for item in parsed["experience_roles"][:20] if isinstance(item, dict)]

    roles: list[DeidentifiedExperienceRole] = []
    for role in raw_roles:
        title = _sanitize_value(
            role.get("title"),
            limit=150,
            sensitive_values=sensitive_values,
            redactions=redactions,
        )
        if not title:
            continue
        roles.append(
            DeidentifiedExperienceRole(
                title=title,
                years=_number(role.get("years")),
                industry=_sanitize_value(
                    role.get("industry"),
                    limit=100,
                    sensitive_values=sensitive_values,
                    redactions=redactions,
                ),
            )
        )

    payload = DeidentifiedAnalysisPayload(
        schema_version=PAYLOAD_SCHEMA_VERSION,
        current_title=_sanitize_value(
            current_title_source,
            limit=100,
            sensitive_values=sensitive_values,
            redactions=redactions,
        ),
        total_years=_number(years_source),
        skills=skills,
        experience_roles=roles,
        highest_education=_education_level(education_source),
    ).model_dump(mode="json")
    if not any(
        (
            payload["current_title"],
            payload["total_years"] is not None,
            payload["skills"],
            payload["experience_roles"],
            payload["highest_education"],
        )
    ):
        raise AnalysisPayloadError("Resume has no safe job-related fields for analysis")
    return payload, redactions, sensitive_values


def _payload_text(payload: dict) -> str:
    lines = ["去識別化履歷", "", "目前職稱"]
    lines.append(payload.get("current_title") or "資料不足")
    lines.extend(["", "總年資"])
    years = payload.get("total_years")
    lines.append(f"{years:g} 年" if isinstance(years, (int, float)) else "資料不足")
    lines.extend(["", "技能"])
    lines.extend(f"• {skill}" for skill in payload.get("skills", []))
    if not payload.get("skills"):
        lines.append("資料不足")
    lines.extend(["", "工作角色"])
    roles = payload.get("experience_roles", [])
    for role in roles:
        details = [role["title"]]
        if role.get("years") is not None:
            details.append(f"{role['years']:g} 年")
        if role.get("industry"):
            details.append(role["industry"])
        lines.append("｜".join(details))
    if not roles:
        lines.append("資料不足")
    lines.extend(["", "最高學歷層級"])
    lines.append(payload.get("highest_education") or "資料不足")
    return "\n".join(lines)


def render_deidentified_pdf(payload: dict) -> tuple[bytes, str]:
    text = _payload_text(payload)
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(18, 18, 18)
    pdf.add_font("deidentified-cjk", fname=str(_font_path()))
    pdf.set_title("De-identified resume")
    pdf.set_author("TalentHub")
    pdf.set_subject("Approved job-related fields only")
    pdf.add_page()
    pdf.set_font("deidentified-cjk", size=11)
    for line in text.splitlines() or [""]:
        pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output()), text


def _scan_text(
    text: str,
    *,
    prefix: str,
    sensitive_values: list[SensitiveValue],
) -> Counter[str]:
    findings: Counter[str] = Counter()
    for kind, pattern in GENERIC_PATTERNS:
        findings[f"{prefix}_{kind}"] += len(pattern.findall(text))
    for sensitive in sensitive_values:
        findings[f"{prefix}_{sensitive.type}"] += len(
            re.findall(re.escape(sensitive.value), text, re.I)
        )
    return findings


def validate_outputs(
    payload: dict,
    pdf_bytes: bytes,
    expected_pdf_text: str,
    sensitive_values: list[SensitiveValue],
    redactions: Counter[str],
) -> dict:
    findings: Counter[str] = Counter()
    unexpected_payload_keys = set(payload) - PAYLOAD_KEYS
    findings["payload_unexpected_field"] += len(unexpected_payload_keys)
    for role in payload.get("experience_roles", []):
        findings["payload_unexpected_role_field"] += len(set(role) - ROLE_KEYS)

    # Scan values only.  Field names and the fixed schema identifier are trusted
    # constants; including them would create false positives for names such as
    # "Title" or a common source filename such as "resume.pdf".
    payload_values: list[str] = []
    if payload.get("current_title"):
        payload_values.append(payload["current_title"])
    payload_values.extend(payload.get("skills", []))
    for role in payload.get("experience_roles", []):
        payload_values.extend(value for value in (role.get("title"), role.get("industry")) if value)
    if payload.get("highest_education"):
        payload_values.append(payload["highest_education"])
    findings.update(
        _scan_text(
            "\n".join(payload_values),
            prefix="payload",
            sensitive_values=sensitive_values,
        )
    )
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        extracted_pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        extracted_pdf_text = ""
        findings["pdf_unreadable"] += 1
    expected_characters = len(re.sub(r"\s+", "", expected_pdf_text))
    pdf_characters = len(re.sub(r"\s+", "", extracted_pdf_text))
    if expected_characters and pdf_characters < max(20, expected_characters // 2):
        findings["pdf_text_incomplete"] += 1
    findings.update(
        _scan_text(
            extracted_pdf_text,
            prefix="pdf",
            sensitive_values=sensitive_values,
        )
    )
    findings = Counter({key: count for key, count in findings.items() if count})
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "blocker_count": sum(findings.values()),
        "findings": [{"type": key, "count": findings[key]} for key in sorted(findings)],
        "redactions": [
            {"type": key, "count": redactions[key]} for key in sorted(redactions) if redactions[key]
        ],
        "payload_field_count": len(payload),
        "pdf_character_count": pdf_characters,
    }


def _source_hash(resume: ResumeFile, storage: StorageProvider) -> str:
    if not resume.storage_key:
        raise SourceDocumentError("Source resume has no stored file")
    try:
        with storage.materialize(resume.storage_key) as source_path:
            digest = hashlib.sha256()
            with source_path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            source_hash = digest.hexdigest()
    except (FileNotFoundError, ValueError) as exc:
        raise SourceDocumentError("Stored source resume was not found") from exc
    if resume.file_hash and source_hash != resume.file_hash:
        raise SourceIntegrityError("Stored source resume failed its integrity check")
    return source_hash


def create_deidentified_document(
    db: Session,
    resume: ResumeFile,
    actor: User,
    *,
    storage: StorageProvider | None = None,
) -> DeidentifiedResumeDocument:
    storage = storage or get_storage_provider()
    source_hash = _source_hash(resume, storage)
    candidate = db.get(Candidate, resume.candidate_id) if resume.candidate_id else None
    payload, redactions, sensitive_values = build_analysis_payload(candidate, resume)
    latest = db.scalar(
        select(DeidentifiedResumeDocument)
        .where(DeidentifiedResumeDocument.source_resume_id == resume.id)
        .order_by(DeidentifiedResumeDocument.version.desc())
        .limit(1)
    )
    version = (latest.version + 1) if latest else 1
    anonymous_ref = latest.anonymous_ref if latest else str(uuid4())
    storage_key = validate_storage_key(f"deidentified-resumes/{uuid4().hex}.pdf")
    document = DeidentifiedResumeDocument(
        source_resume_id=resume.id,
        anonymous_ref=anonymous_ref,
        version=version,
        storage_key=storage_key,
        file_hash=None,
        file_size=None,
        mime="application/pdf",
        source_file_hash=source_hash,
        deidentification_version=DEIDENTIFICATION_VERSION,
        payload_schema_version=PAYLOAD_SCHEMA_VERSION,
        analysis_payload=payload,
        validation_status="processing",
        validation_summary={
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "blocker_count": 0,
            "findings": [],
            "redactions": [],
            "payload_field_count": len(payload),
            "pdf_character_count": 0,
        },
        created_by=actor.id,
    )
    db.add(document)
    db.flush()  # Reserve the source/version pair before writing an object.

    temporary_path: Path | None = None
    try:
        pdf_bytes, pdf_text = render_deidentified_pdf(payload)
        summary = validate_outputs(
            payload,
            pdf_bytes,
            pdf_text,
            sensitive_values,
            redactions,
        )
        settings = get_settings()
        quarantine_root = Path(settings.resume_quarantine_path).resolve()
        quarantine_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False,
            dir=quarantine_root,
        ) as temporary:
            temporary.write(pdf_bytes)
            temporary_path = Path(temporary.name)
        storage.put_file(temporary_path, storage_key, "application/pdf")
        document.file_hash = hashlib.sha256(pdf_bytes).hexdigest()
        document.file_size = len(pdf_bytes)
        document.validation_summary = summary
        document.validation_status = "review_required"
        db.flush()
        return document
    except Exception:
        # put_file may fail after a partial write, so delete regardless of the
        # promoted flag.  The caller rolls the database transaction back.
        try:
            storage.delete(storage_key)
        except Exception:
            # Preserve the generation error.  Retrying cleanup is an object-store
            # operational concern and must not hide the original failure cause.
            pass
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def is_manual_upload(document: DeidentifiedResumeDocument) -> bool:
    """True when a human uploaded the de-identified file (vs. system-generated)."""

    return document.deidentification_version == MANUAL_DEIDENTIFICATION_VERSION


def has_structured_analysis_payload(document: DeidentifiedResumeDocument) -> bool:
    """True when a valid allow-list payload is available for automated analysis.

    A system-generated snapshot and a manual upload backed by the candidate's
    structured safe fields both carry this schema.  A manual upload for which no
    safe fields could be derived carries only the opaque marker instead.
    """

    return document.payload_schema_version == PAYLOAD_SCHEMA_VERSION


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def scan_uploaded_file_for_leaks(
    pdf_bytes: bytes,
    sensitive_values: list[SensitiveValue],
    redactions: Counter[str] | None = None,
    payload: dict | None = None,
) -> dict:
    """Scan an HR-uploaded 'de-identified' PDF for residual PII.

    This is the security backbone of the manual-upload flow: if the uploaded
    file still contains a known name/email/phone/ID (or a generic contact
    pattern), the returned summary reports a non-zero ``blocker_count`` and
    approval is refused until a properly redacted file is supplied.
    """

    summary = validate_outputs(
        payload or {},
        pdf_bytes,
        "",  # No expected reflow text for an opaque human upload.
        sensitive_values,
        redactions or Counter(),
    )
    summary["manual"] = True
    return summary


async def create_manual_deidentified_document(
    db: Session,
    resume: ResumeFile,
    actor: User,
    upload: UploadFile,
    *,
    storage: StorageProvider | None = None,
    scanner: FileScanner | None = None,
    settings: Settings | None = None,
) -> DeidentifiedResumeDocument:
    """Persist an HR-supplied, already de-identified file as a new version.

    The uploaded bytes are validated with the same type/size/magic-byte/malware
    checks as an original resume, then scanned for residual PII.  The structured
    ``analysis_payload`` is still populated from the candidate's existing safe
    fields (never by parsing the upload) so downstream AI analysis keeps working.
    """

    settings = settings or get_settings()
    storage = storage or get_storage_provider(settings)
    scanner = scanner or get_file_scanner(settings)

    # Only a real PDF can be scanned for residual PII, which is the whole point
    # of accepting a manual upload; reject other types before touching storage.
    original_name = Path(upload.filename or "").name
    if Path(original_name).suffix.lower() != ".pdf" or (
        upload.content_type or ""
    ).lower() != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="A manually de-identified upload must be a PDF file",
        )

    # Reuse the source integrity check so a tampered original still fails fast.
    source_hash = _source_hash(resume, storage)
    candidate = db.get(Candidate, resume.candidate_id) if resume.candidate_id else None

    # The analysis payload is derived from the candidate's structured safe fields
    # (the same allow-list as the retired auto-generation path), NOT from the
    # uploaded bytes.  When no safe fields exist we fall back to an opaque marker.
    try:
        payload, redactions, sensitive_values = build_analysis_payload(candidate, resume)
        payload_schema_version = PAYLOAD_SCHEMA_VERSION
        analysis_payload = payload
    except AnalysisPayloadError:
        payload = {}
        redactions = Counter()
        sensitive_values = _sensitive_values(candidate, resume)
        payload_schema_version = MANUAL_PAYLOAD_SCHEMA_VERSION
        analysis_payload = dict(MANUAL_ANALYSIS_PAYLOAD)

    prepared = await prepare_resume_upload(
        upload,
        provider=storage,
        scanner=scanner,
        settings=settings,
    )
    stored_key: str | None = None
    try:
        upload_data = prepared.upload_data
        uploaded_bytes = prepared.quarantine_path.read_bytes()
        summary = scan_uploaded_file_for_leaks(
            uploaded_bytes,
            sensitive_values,
            redactions,
            payload,
        )
        latest = db.scalar(
            select(DeidentifiedResumeDocument)
            .where(DeidentifiedResumeDocument.source_resume_id == resume.id)
            .order_by(DeidentifiedResumeDocument.version.desc())
            .limit(1)
        )
        version = (latest.version + 1) if latest else 1
        anonymous_ref = latest.anonymous_ref if latest else str(uuid4())
        storage_key = validate_storage_key(f"deidentified-resumes/{uuid4().hex}.pdf")
        # Record the key before writing so a put_file that fails after a partial
        # write is still cleaned up by the except branch below.
        stored_key = storage_key
        storage.put_file(prepared.quarantine_path, storage_key, upload_data.mime)
        document = DeidentifiedResumeDocument(
            source_resume_id=resume.id,
            anonymous_ref=anonymous_ref,
            version=version,
            storage_key=storage_key,
            file_hash=upload_data.file_hash,
            file_size=upload_data.file_size,
            mime=upload_data.mime,
            source_file_hash=source_hash,
            deidentification_version=MANUAL_DEIDENTIFICATION_VERSION,
            payload_schema_version=payload_schema_version,
            analysis_payload=analysis_payload,
            # A residual-PII finding keeps the version in review_required and
            # blocks approval; a clean file lets HR approve it.
            validation_status="review_required",
            validation_summary=summary,
            created_by=actor.id,
        )
        db.add(document)
        db.flush()  # Reserve the source/version pair before returning.
        return document
    except Exception:
        if stored_key is not None:
            try:
                storage.delete(stored_key)
            except Exception:
                pass
        raise
    finally:
        prepared.finish()


def approve_deidentified_document(
    db: Session,
    document: DeidentifiedResumeDocument,
    reviewer: User,
) -> DeidentifiedResumeDocument:
    if document.validation_status == "analysis_ready":
        return document
    if document.validation_status != "review_required":
        raise DeidentificationError("Only a review-required version can be approved")
    summary = document.validation_summary or {}
    if summary.get("schema_version") != VALIDATION_SCHEMA_VERSION:
        raise DeidentificationError("The validation summary is missing or outdated")
    if int(summary.get("blocker_count", 0)) > 0:
        raise DeidentificationError("Validation blockers must be resolved before approval")
    if has_structured_analysis_payload(document):
        try:
            DeidentifiedAnalysisPayload.model_validate(document.analysis_payload)
        except ValidationError as exc:
            raise DeidentificationError("The analysis payload is invalid") from exc
    now = datetime.now(UTC)
    db.execute(
        update(DeidentifiedResumeDocument)
        .where(
            DeidentifiedResumeDocument.source_resume_id == document.source_resume_id,
            DeidentifiedResumeDocument.id != document.id,
            DeidentifiedResumeDocument.validation_status == "analysis_ready",
        )
        .values(validation_status="superseded", updated_at=now)
    )
    document.validation_status = "analysis_ready"
    document.reviewed_by = reviewer.id
    document.reviewed_at = now
    db.flush()
    return document


def reject_deidentified_document(
    db: Session,
    document: DeidentifiedResumeDocument,
    reviewer: User,
) -> DeidentifiedResumeDocument:
    if document.validation_status != "review_required":
        raise DeidentificationError("Only a review-required version can be rejected")
    document.validation_status = "failed"
    document.reviewed_by = reviewer.id
    document.reviewed_at = datetime.now(UTC)
    db.flush()
    return document


def deidentified_storage_keys_for_resume(db: Session, resume_id: int) -> tuple[str, ...]:
    """Return opaque keys for retention/outbox integration before DB cascade."""

    keys = db.scalars(
        select(DeidentifiedResumeDocument.storage_key).where(
            DeidentifiedResumeDocument.source_resume_id == resume_id,
            DeidentifiedResumeDocument.storage_key.is_not(None),
        )
    ).all()
    return tuple(key for key in keys if key)


def read_verified_deidentified_file(
    document: DeidentifiedResumeDocument,
    storage: StorageProvider,
) -> bytes:
    """Read a derivative only when its immutable metadata still matches."""

    if not document.storage_key or not document.file_hash or not document.file_size:
        raise SourceDocumentError("De-identified file metadata is incomplete")
    try:
        with storage.materialize(document.storage_key) as path:
            content = path.read_bytes()
    except (FileNotFoundError, ValueError) as exc:
        raise SourceDocumentError("De-identified file was not found") from exc
    actual_hash = hashlib.sha256(content).hexdigest()
    if len(content) != document.file_size or not hmac.compare_digest(
        actual_hash,
        document.file_hash,
    ):
        raise SourceIntegrityError("De-identified file failed its integrity check")
    return content
