from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import (
    Candidate,
    DeidentifiedResumeDocument,
    JobApplication,
    ResumeFile,
    RetentionStorageDeletion,
    SystemSetting,
    User,
)
from app.services.security import write_audit

if TYPE_CHECKING:
    from app.services.storage import StorageProvider

RETENTION_SETTING_KEY = "candidate.retention_years"
RETENTION_SETTING_DESCRIPTION = "Maximum number of years candidate personal data may be retained"
DEFAULT_RETENTION_YEARS = 2
MIN_RETENTION_YEARS = 1
MAX_RETENTION_YEARS = 20
_RETENTION_ADVISORY_LOCK_KEY = 1414024274


@dataclass(frozen=True)
class RetentionPolicy:
    retention_years: int
    defaulted: bool


@dataclass(frozen=True)
class CandidateRetentionSetting:
    candidate_id: int
    retention_years_override: int | None
    effective_retention_years: int
    uses_company_default: bool
    anchor_date: date
    retention_until: date


@dataclass(frozen=True)
class StorageDeletionResult:
    deleted_storage_objects: int = 0
    deleted_photos: int = 0
    failures: int = 0


@dataclass(frozen=True)
class RetentionPurgeResult:
    as_of: date
    dry_run: bool
    lock_acquired: bool
    eligible_candidates: int = 0
    eligible_resume_files: int = 0
    deleted_candidates: int = 0
    deleted_resume_files: int = 0
    remaining_candidates: int = 0
    queued_storage_deletions: int = 0
    deleted_storage_objects: int = 0
    deleted_photos: int = 0
    storage_delete_failures: int = 0


def _valid_years(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < MIN_RETENTION_YEARS or value > MAX_RETENTION_YEARS:
        return None
    return value


def get_retention_policy(db: Session) -> RetentionPolicy:
    setting = db.get(SystemSetting, RETENTION_SETTING_KEY)
    years = _valid_years(setting.value if setting else None)
    return RetentionPolicy(
        retention_years=years or DEFAULT_RETENTION_YEARS,
        defaulted=years is None,
    )


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # February 29 expires on February 28 in a non-leap target year.
        return value.replace(month=2, day=28, year=value.year + years)


def _candidate_retention_anchor(candidate: Candidate) -> date:
    anchor = candidate.consent_at or candidate.created_at
    return anchor.date()


def set_candidate_retention(
    db: Session,
    candidate: Candidate,
    retention_years: int | None,
) -> CandidateRetentionSetting:
    """Apply a candidate-specific period, or restore the company default."""

    if retention_years is not None and _valid_years(retention_years) is None:
        raise ValueError(
            f"retention_years must be between {MIN_RETENTION_YEARS} and "
            f"{MAX_RETENTION_YEARS}"
        )
    policy = get_retention_policy(db)
    effective_years = retention_years or policy.retention_years
    anchor_date = _candidate_retention_anchor(candidate)
    retention_until = _add_years(anchor_date, effective_years)
    candidate.retention_years_override = retention_years
    candidate.retention_until = retention_until
    return CandidateRetentionSetting(
        candidate_id=candidate.id,
        retention_years_override=retention_years,
        effective_retention_years=effective_years,
        uses_company_default=retention_years is None,
        anchor_date=anchor_date,
        retention_until=retention_until,
    )


def candidate_retention_until(
    db: Session,
    anchor: date | datetime | None = None,
) -> date:
    if anchor is None:
        anchor_date = datetime.now(UTC).date()
    elif isinstance(anchor, datetime):
        anchor_date = anchor.date()
    else:
        anchor_date = anchor
    return _add_years(anchor_date, get_retention_policy(db).retention_years)


def set_retention_policy(db: Session, retention_years: int) -> tuple[RetentionPolicy, int]:
    years = _valid_years(retention_years)
    if years is None:
        raise ValueError(f"retention_years must be between {MIN_RETENTION_YEARS} and 20")
    setting = db.get(SystemSetting, RETENTION_SETTING_KEY)
    if setting is None:
        setting = SystemSetting(key=RETENTION_SETTING_KEY)
        db.add(setting)
    setting.value = years
    setting.description = RETENTION_SETTING_DESCRIPTION
    setting.is_secret = False

    # Recalculate only candidates that follow the company default. Individually
    # assigned periods remain intact when HR changes the default policy.
    candidates = db.scalars(
        select(Candidate).where(Candidate.retention_years_override.is_(None))
    ).all()
    for candidate in candidates:
        candidate.retention_until = _add_years(
            _candidate_retention_anchor(candidate), years
        )
    return RetentionPolicy(retention_years=years, defaulted=False), len(candidates)


def _policy_cutoff(as_of: date, years: int) -> datetime:
    cutoff_date = _add_years(as_of, -years)
    # A date-based policy expires at the beginning of the day after the anniversary.
    return datetime.combine(cutoff_date + timedelta(days=1), time.min, tzinfo=UTC)


def _eligible_clause(as_of: date, years: int):
    # Every current candidate has a concrete deadline. The policy cutoff is only a
    # legacy fallback for rows whose deadline predates the retention implementation;
    # applying it to every row would incorrectly erase a five-year individual
    # assignment when the company default is one year.
    return or_(
        Candidate.retention_until <= as_of,
        and_(
            Candidate.retention_until.is_(None),
            Candidate.created_at < _policy_cutoff(as_of, years),
        ),
    )


def _resume_cleanup_clause(candidate_ids):
    application_resume_ids = select(JobApplication.resume_id).where(
        JobApplication.candidate_id.in_(candidate_ids),
        JobApplication.resume_id.is_not(None),
    )
    return or_(
        ResumeFile.candidate_id.in_(candidate_ids),
        # Legacy/imported applications can reference a resume before its candidate_id
        # is populated. It still contains this candidate's PII and must be erased.
        (
            ResumeFile.candidate_id.is_(None)
            & ResumeFile.id.in_(application_resume_ids)
        ),
    )


def _try_retention_lock(db: Session) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return True
    acquired = db.scalar(select(func.pg_try_advisory_xact_lock(_RETENTION_ADVISORY_LOCK_KEY)))
    return bool(acquired)


def _queue_storage_deletions(
    db: Session,
    resume_keys: list[str],
    photo_paths: list[str],
) -> int:
    requested = {
        *(('resume', key) for key in resume_keys if key),
        *(('candidate_photo', path) for path in photo_paths if path),
    }
    if not requested:
        return 0
    existing = set(
        db.execute(
            select(RetentionStorageDeletion.kind, RetentionStorageDeletion.locator).where(
                RetentionStorageDeletion.kind.in_({kind for kind, _ in requested}),
                RetentionStorageDeletion.locator.in_({locator for _, locator in requested}),
            )
        ).all()
    )
    pending = requested - existing
    db.add_all(
        RetentionStorageDeletion(kind=kind, locator=locator)
        for kind, locator in pending
    )
    return len(pending)


def _delete_photo(locator: str, root: Path) -> None:
    photo_path = Path(locator).resolve()
    resolved_root = root.resolve()
    if resolved_root not in photo_path.parents:
        raise ValueError("UnsafePhotoLocator")
    photo_path.unlink(missing_ok=True)


def process_pending_storage_deletions(
    db: Session,
    *,
    limit: int = 500,
    storage_provider: StorageProvider | None = None,
    settings: Settings | None = None,
) -> StorageDeletionResult:
    settings = settings or get_settings()
    tasks = list(
        db.scalars(
            select(RetentionStorageDeletion)
            .order_by(RetentionStorageDeletion.created_at, RetentionStorageDeletion.id)
            .limit(max(1, limit))
            .with_for_update(skip_locked=True)
        ).all()
    )
    deleted = 0
    deleted_photos = 0
    failures = 0
    provider = storage_provider
    for task in tasks:
        try:
            if task.kind == "resume":
                if provider is None:
                    from app.services.storage import get_storage_provider

                    provider = get_storage_provider(settings)
                provider.delete(task.locator)
            elif task.kind == "candidate_photo":
                _delete_photo(task.locator, Path(settings.candidate_photo_storage_path))
                deleted_photos += 1
            else:
                raise ValueError("UnknownStorageDeletionKind")
        except Exception as exc:  # cleanup failures are retained for the next run
            task.attempts += 1
            # Exception messages can contain locators or provider credentials. Keep
            # only the exception class so the outbox remains free of leaked values.
            task.last_error = type(exc).__name__[:100]
            failures += 1
        else:
            db.delete(task)
            deleted += 1
    db.commit()
    return StorageDeletionResult(
        deleted_storage_objects=deleted,
        deleted_photos=deleted_photos,
        failures=failures,
    )


def purge_expired_candidates(
    db: Session,
    *,
    dry_run: bool = True,
    as_of: date | None = None,
    actor: User | None = None,
    batch_size: int = 500,
    storage_provider: StorageProvider | None = None,
    settings: Settings | None = None,
    process_storage: bool = True,
) -> RetentionPurgeResult:
    """Irreversibly erase expired candidate records and queue their files.

    The database deletion and creation of durable file-deletion tasks commit in
    one transaction. A failed object-store or filesystem delete therefore stays
    retryable without retaining the deleted candidate record.
    """

    settings = settings or get_settings()
    today = as_of or datetime.now(UTC).date()
    if not _try_retention_lock(db):
        db.rollback()
        return RetentionPurgeResult(as_of=today, dry_run=dry_run, lock_acquired=False)

    policy = get_retention_policy(db)
    eligible = _eligible_clause(today, policy.retention_years)
    eligible_count = int(
        db.scalar(select(func.count()).select_from(Candidate).where(eligible)) or 0
    )
    eligible_candidate_ids = select(Candidate.id).where(eligible)
    eligible_resume_count = int(
        db.scalar(
            select(func.count())
            .select_from(ResumeFile)
            .where(_resume_cleanup_clause(eligible_candidate_ids))
        )
        or 0
    )
    if dry_run or eligible_count == 0:
        return RetentionPurgeResult(
            as_of=today,
            dry_run=dry_run,
            lock_acquired=True,
            eligible_candidates=eligible_count,
            eligible_resume_files=eligible_resume_count,
            remaining_candidates=eligible_count,
        )

    rows = db.execute(
        select(Candidate.id, Candidate.photo_path)
        .where(eligible)
        .order_by(Candidate.id)
        .limit(max(1, batch_size))
        .with_for_update(skip_locked=True)
    ).all()
    candidate_ids = [row.id for row in rows]
    if not candidate_ids:
        db.rollback()
        return RetentionPurgeResult(
            as_of=today,
            dry_run=False,
            lock_acquired=True,
            eligible_candidates=eligible_count,
            eligible_resume_files=eligible_resume_count,
            remaining_candidates=eligible_count,
        )
    resume_rows = db.execute(
        select(ResumeFile.id, ResumeFile.storage_key).where(
            _resume_cleanup_clause(candidate_ids)
        )
    ).all()
    resume_ids = [row.id for row in resume_rows]
    deidentified_keys = (
        list(
            db.scalars(
                select(DeidentifiedResumeDocument.storage_key).where(
                    DeidentifiedResumeDocument.source_resume_id.in_(resume_ids),
                    DeidentifiedResumeDocument.storage_key.is_not(None),
                )
            ).all()
        )
        if resume_ids
        else []
    )
    # A de-identified PDF is a separately stored derivative, so cascading its
    # database row must also enqueue its object for physical deletion.
    resume_keys = [row.storage_key for row in resume_rows if row.storage_key]
    resume_keys.extend(key for key in deidentified_keys if key)
    photo_paths = [row.photo_path for row in rows if row.photo_path]
    queued = _queue_storage_deletions(db, resume_keys, photo_paths)

    # Applications contain cover letters, personal links, and interview notes, so
    # retaining a skeleton would not satisfy the deletion policy. Delete them before
    # candidates because their FK is intentionally RESTRICT in the normal workflow.
    db.execute(delete(JobApplication).where(JobApplication.candidate_id.in_(candidate_ids)))
    db.execute(
        delete(ResumeFile).where(ResumeFile.id.in_([row.id for row in resume_rows]))
    )
    db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
    write_audit(
        db,
        actor,
        "talent_retention.purge",
        "talent_pool",
        "retention",
        details={
            "as_of": today.isoformat(),
            "retention_years": policy.retention_years,
            "deleted_candidates": len(candidate_ids),
            "deleted_resume_files": len(resume_rows),
            "deleted_deidentified_resume_files": len(deidentified_keys),
            "queued_storage_deletions": queued,
        },
    )
    db.commit()

    storage_result = (
        process_pending_storage_deletions(
            db,
            limit=max(batch_size * 2, 1),
            storage_provider=storage_provider,
            settings=settings,
        )
        if process_storage
        else StorageDeletionResult()
    )
    return RetentionPurgeResult(
        as_of=today,
        dry_run=False,
        lock_acquired=True,
        eligible_candidates=eligible_count,
        eligible_resume_files=eligible_resume_count,
        deleted_candidates=len(candidate_ids),
        deleted_resume_files=len(resume_rows),
        remaining_candidates=max(0, eligible_count - len(candidate_ids)),
        queued_storage_deletions=queued,
        deleted_storage_objects=storage_result.deleted_storage_objects,
        deleted_photos=storage_result.deleted_photos,
        storage_delete_failures=storage_result.failures,
    )
