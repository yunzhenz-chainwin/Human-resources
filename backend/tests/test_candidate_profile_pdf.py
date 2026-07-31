import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Candidate, CandidateSkill, ResumeFile
from app.services.candidate_profile_pdf import backfill_candidate_profile_pdfs
from app.services.storage import LocalStorageProvider


def test_backfill_creates_labelled_pdf_and_is_idempotent() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    storage_root = Path("storage") / f"candidate-profile-test-{uuid4().hex}"
    storage = LocalStorageProvider(storage_root)
    try:
        with testing_session() as db:
            candidate = Candidate(
                code="PROFILE-PDF-001",
                name="系統補建測試人才",
                email="profile@example.test",
                phone="0900-000-001",
                city="台北市",
                current_title="資料分析師",
                total_years=3,
                source="manual",
                summary="具備資料整理與儀表板經驗。",
            )
            db.add(candidate)
            db.flush()
            db.add(CandidateSkill(candidate_id=candidate.id, skill="SQL", skill_norm="sql"))
            db.add(
                ResumeFile(
                    candidate_id=candidate.id,
                    storage_key="resumes/missing-original.pdf",
                    original_filename="original.pdf",
                    file_hash="0" * 64,
                    file_size=123,
                    mime="application/pdf",
                    source_platform="direct",
                    source_review_required=False,
                    parse_status="confirmed",
                    resume_text="原始履歷解析文字",
                )
            )
            db.commit()

            preview = backfill_candidate_profile_pdfs(db, storage=storage, dry_run=True)
            assert preview.candidates_scanned == 1
            assert preview.candidates_without_available_pdf == 1
            assert preview.missing_storage_objects == 1
            assert preview.generated_pdfs == 0

            result = backfill_candidate_profile_pdfs(db, storage=storage, dry_run=False)
            db.commit()
            assert result.generated_pdfs == 1

            resumes = list(
                db.scalars(
                    select(ResumeFile)
                    .where(ResumeFile.candidate_id == candidate.id)
                    .order_by(ResumeFile.id)
                ).all()
            )
            assert len(resumes) == 2
            original, generated = resumes
            assert original.document_origin == "applicant_upload"
            assert generated.document_origin == "system_generated"
            assert generated.original_filename == "系統補建_PROFILE-PDF-001_人才履歷.pdf"
            assert generated.storage_key is not None
            assert storage.exists(generated.storage_key)
            with storage.materialize(generated.storage_key) as path:
                content = path.read_bytes()
            assert content.startswith(b"%PDF-")
            assert len(content) > 1_000
            assert "非應徵者原始上傳檔" in (generated.resume_text or "")

            repeated = backfill_candidate_profile_pdfs(db, storage=storage, dry_run=False)
            db.commit()
            assert repeated.generated_pdfs == 0
            assert repeated.reused_pdfs == 1
            assert db.scalar(select(ResumeFile).where(ResumeFile.id == generated.id)) is not None
    finally:
        shutil.rmtree(storage_root, ignore_errors=True)
