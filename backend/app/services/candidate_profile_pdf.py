from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Candidate, ResumeFile
from app.services.storage import StorageProvider, get_storage_provider

SYSTEM_PROFILE_ORIGIN = "system_generated_profile"
SYSTEM_PROFILE_PARSER_VERSION = "system-profile-v1"


@dataclass(frozen=True)
class CandidateProfileBackfillResult:
    candidates_scanned: int
    candidates_without_available_pdf: int
    missing_storage_objects: int
    generated_pdfs: int
    reused_pdfs: int
    dry_run: bool


def _pdf_font_path(*, bold: bool = False) -> Path:
    # A host that keeps its CJK font somewhere else pins it here, the same way
    # the OCR toolchain is pinned with TESSERACT_DIR.
    override = os.environ.get("PDF_CJK_FONT_BOLD_PATH" if bold else "PDF_CJK_FONT_PATH")
    regular = [
        Path(r"C:\Windows\Fonts\msjh.ttc"),
        # macOS: the Noto cask lands in one of the two Library trees; PingFang
        # is the system fallback that is always present.
        Path("/Library/Fonts/NotoSansCJK-Regular.ttc"),
        Path.home() / "Library/Fonts/NotoSansCJK-Regular.ttc",
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    bold_candidates = [
        Path(r"C:\Windows\Fonts\msjhbd.ttc"),
        Path("/Library/Fonts/NotoSansCJK-Bold.ttc"),
        Path.home() / "Library/Fonts/NotoSansCJK-Bold.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    ]
    # No bold face on this host is not fatal: falling through to the regular
    # list registers it under the bold style rather than failing the render.
    candidates = [
        *([Path(override)] if override else []),
        *(bold_candidates if bold else []),
        *regular,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError(
        "找不到支援繁體中文的 PDF 字型（需要 Microsoft JhengHei、Noto Sans CJK 或 PingFang）"
    )


def _clean_pdf_text(value: object | None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        for character in text
        if character in {"\n", "\t"} or not unicodedata.category(character).startswith("C")
    ).strip()


def _joined(values: list[str] | None) -> str:
    return "、".join(value for value in (values or []) if value)


def _education_lines(candidate: Candidate) -> list[str]:
    lines: list[str] = []
    for education in sorted(candidate.educations, key=lambda item: (item.sort_order, item.id)):
        period = "－".join(value for value in [education.start_ym, education.end_ym] if value)
        detail = " · ".join(value for value in [education.degree, education.major] if value)
        line = education.school
        if detail:
            line += f"｜{detail}"
        if period:
            line += f"｜{period}"
        lines.append(line)
    return lines


def _experience_lines(candidate: Candidate) -> list[str]:
    lines: list[str] = []
    for experience in sorted(candidate.experiences, key=lambda item: (item.sort_order, item.id)):
        period = "－".join(value for value in [experience.start_ym, experience.end_ym] if value)
        line = f"{experience.company}｜{experience.title}"
        if period:
            line += f"｜{period}"
        if experience.description:
            line += f"\n{experience.description}"
        lines.append(line)
    return lines


def candidate_profile_payload(candidate: Candidate) -> dict[str, object]:
    skills = [skill.skill for skill in candidate.skills]
    educations = _education_lines(candidate)
    experiences = _experience_lines(candidate)
    return {
        "_document_origin": SYSTEM_PROFILE_ORIGIN,
        "name": candidate.name,
        "email": candidate.email,
        "phone": candidate.phone,
        "city": candidate.city,
        "current_title": candidate.current_title,
        "current_company": candidate.current_company,
        "total_years": float(candidate.total_years) if candidate.total_years is not None else None,
        "highest_education": candidate.highest_education,
        "expected_title": candidate.expected_title,
        "expected_cities": candidate.expected_cities or [],
        "skills": skills,
        "education": "\n".join(educations),
        "experience": "\n\n".join(experiences),
        "summary": candidate.summary,
    }


def candidate_profile_text(
    candidate: Candidate,
    source_resume: ResumeFile | None = None,
) -> str:
    payload = candidate_profile_payload(candidate)
    lines = [
        "系統產生的人才履歷",
        "重要：本檔依人才庫結構化資料補建，非應徵者原始上傳檔。",
        "",
        "【基本資料】",
        f"人才編號：{candidate.code}",
        f"姓名：{candidate.name}",
        f"目前職稱：{candidate.current_title or '未提供'}",
        f"目前公司：{candidate.current_company or '未提供'}",
        f"總年資：{candidate.total_years if candidate.total_years is not None else '未提供'}",
        f"地區：{candidate.city or '未提供'}",
        f"Email：{candidate.email or '未提供'}",
        f"電話：{candidate.phone or '未提供'}",
        "",
        "【求職條件】",
        f"期望職稱：{candidate.expected_title or '未提供'}",
        f"期望地區：{_joined(candidate.expected_cities) or '未提供'}",
        f"到職狀態：{candidate.availability or '未提供'}",
        f"工作型態：{candidate.job_type or '未提供'}",
        "",
        "【技能】",
        _joined(payload["skills"]) or "未提供",
        "",
        "【人才摘要】",
        candidate.summary or "未提供",
        "",
        "【工作經歷】",
        payload["experience"] or "未提供",
        "",
        "【學歷】",
        payload["education"] or candidate.highest_education or "未提供",
    ]
    if source_resume is not None and source_resume.resume_text:
        lines.extend(
            [
                "",
                "【既有履歷解析文字】",
                "以下內容來自先前解析紀錄；原始檔案目前不在儲存空間。",
                source_resume.resume_text[:20_000],
            ]
        )
    return _clean_pdf_text("\n".join(str(line) for line in lines))


def render_candidate_profile_pdf(
    candidate: Candidate,
    source_resume: ResumeFile | None = None,
) -> tuple[bytes, str, dict[str, object]]:
    profile_text = candidate_profile_text(candidate, source_resume)
    payload = candidate_profile_payload(candidate)
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(17, 16, 17)
    pdf.add_font("talent-cjk", fname=str(_pdf_font_path()))
    pdf.add_font("talent-cjk", style="B", fname=str(_pdf_font_path(bold=True)))
    pdf.set_title(f"{candidate.name}－系統產生人才履歷")
    pdf.set_author("TalentHub")
    pdf.add_page()

    pdf.set_fill_color(13, 116, 103)
    pdf.rect(0, 0, 210, 34, style="F")
    pdf.set_xy(17, 9)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("talent-cjk", style="B", size=18)
    pdf.cell(0, 8, candidate.name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(17)
    pdf.set_font("talent-cjk", size=9)
    pdf.cell(
        0,
        6,
        f"{candidate.current_title or '人才資料'}　｜　{candidate.code}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_y(40)
    pdf.set_fill_color(255, 247, 230)
    pdf.set_text_color(112, 82, 30)
    pdf.set_font("talent-cjk", style="B", size=9)
    pdf.multi_cell(
        0,
        6,
        "系統補建 PDF：依人才庫資料產生，非應徵者原始上傳檔。",
        fill=True,
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(3)
    pdf.set_text_color(35, 66, 61)
    pdf.set_font("talent-cjk", size=10)
    for line in profile_text.splitlines()[2:]:
        stripped = line.strip()
        if stripped.startswith("【") and stripped.endswith("】"):
            pdf.ln(2)
            pdf.set_text_color(13, 116, 103)
            pdf.set_font("talent-cjk", style="B", size=11)
            pdf.multi_cell(0, 7, stripped, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(35, 66, 61)
            pdf.set_font("talent-cjk", size=10)
        elif stripped:
            pdf.multi_cell(0, 6, stripped, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.ln(2)
    return bytes(pdf.output()), profile_text, payload


def _safe_code(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-")
    return cleaned[:80] or "candidate"


def _is_pdf(resume: ResumeFile) -> bool:
    return (resume.mime or "").lower() == "application/pdf" or (
        resume.original_filename or ""
    ).lower().endswith(".pdf")


def _available(resume: ResumeFile, storage: StorageProvider) -> bool:
    return bool(resume.storage_key and storage.exists(resume.storage_key))


def ensure_candidate_profile_pdf(
    db: Session,
    candidate: Candidate,
    *,
    storage: StorageProvider | None = None,
) -> tuple[ResumeFile, bool]:
    storage = storage or get_storage_provider()
    resumes = list(
        db.scalars(
            select(ResumeFile)
            .where(ResumeFile.candidate_id == candidate.id)
            .order_by(ResumeFile.uploaded_at.desc(), ResumeFile.id.desc())
        ).all()
    )
    generated = next(
        (resume for resume in resumes if resume.document_origin == "system_generated"),
        None,
    )
    if generated is not None and _available(generated, storage):
        return generated, False

    source_resume = next(
        (
            resume
            for resume in resumes
            if resume.document_origin == "applicant_upload" and resume.resume_text
        ),
        None,
    )
    pdf_bytes, profile_text, payload = render_candidate_profile_pdf(candidate, source_resume)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    storage_key = f"resumes/system-generated/{uuid4().hex}.pdf"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
            temporary.write(pdf_bytes)
            temporary_path = Path(temporary.name)
        storage.put_file(temporary_path, storage_key, "application/pdf")
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    previous_key = generated.storage_key if generated is not None else None
    resume = generated or ResumeFile(candidate_id=candidate.id)
    resume.target_requisition_id = None
    resume.storage_key = storage_key
    resume.original_filename = f"系統補建_{_safe_code(candidate.code)}_人才履歷.pdf"
    resume.file_hash = digest
    resume.file_size = len(pdf_bytes)
    resume.mime = "application/pdf"
    resume.source_platform = "generic"
    resume.requested_source_platform = "generic"
    resume.source_confidence = 1
    resume.source_evidence = [
        {
            "type": SYSTEM_PROFILE_ORIGIN,
            "marker": "candidate_structured_data",
            "note": "not_applicant_original",
        }
    ]
    resume.source_review_required = False
    resume.parse_status = "confirmed"
    resume.parsed_payload = payload
    resume.field_confidence = {
        key: 1.0 for key, value in payload.items() if not key.startswith("_") and value
    }
    resume.overall_confidence = 1
    resume.parser_version = SYSTEM_PROFILE_PARSER_VERSION
    resume.error_message = None
    resume.resume_url = None
    resume.resume_text = profile_text
    resume.confirmed_at = datetime.now(UTC)
    db.add(resume)
    try:
        db.flush()
    except Exception:
        storage.delete(storage_key)
        raise
    if previous_key and previous_key != storage_key:
        storage.delete(previous_key)
    return resume, True


def backfill_candidate_profile_pdfs(
    db: Session,
    *,
    storage: StorageProvider | None = None,
    dry_run: bool = True,
) -> CandidateProfileBackfillResult:
    storage = storage or get_storage_provider()
    candidates = list(
        db.scalars(
            select(Candidate)
            .options(
                selectinload(Candidate.educations),
                selectinload(Candidate.experiences),
                selectinload(Candidate.skills),
            )
            .where(Candidate.deleted_at.is_(None))
            .order_by(Candidate.id)
        ).all()
    )
    resume_rows = list(db.scalars(select(ResumeFile)).all())
    resumes_by_candidate: dict[int, list[ResumeFile]] = {}
    missing_storage_objects = 0
    for resume in resume_rows:
        if resume.storage_key and not storage.exists(resume.storage_key):
            missing_storage_objects += 1
        if resume.candidate_id is not None:
            resumes_by_candidate.setdefault(resume.candidate_id, []).append(resume)

    candidates_without_pdf = 0
    generated_pdfs = 0
    reused_pdfs = 0
    for candidate in candidates:
        available_pdf = any(
            _is_pdf(resume) and _available(resume, storage)
            for resume in resumes_by_candidate.get(candidate.id, [])
        )
        if available_pdf:
            reused_pdfs += 1
            continue
        candidates_without_pdf += 1
        if not dry_run:
            _, created = ensure_candidate_profile_pdf(db, candidate, storage=storage)
            generated_pdfs += int(created)

    return CandidateProfileBackfillResult(
        candidates_scanned=len(candidates),
        candidates_without_available_pdf=candidates_without_pdf,
        missing_storage_objects=missing_storage_objects,
        generated_pdfs=generated_pdfs,
        reused_pdfs=reused_pdfs,
        dry_run=dry_run,
    )
