"""Business rules for versioned recruitment consent notices (PDPA §8/§9).

Keeping the "only one active notice" invariant here means both the API route and
any future automation share one implementation and cannot drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.candidate import Candidate
from app.models.consent import CandidateConsent, ConsentNotice
from app.services.talent_retention import set_candidate_retention


def next_version(db: Session) -> int:
    """Return the next monotonically increasing notice version."""
    current = db.scalar(select(func.max(ConsentNotice.version)))
    return int(current or 0) + 1


def active_notice(db: Session) -> ConsentNotice | None:
    """Return the single currently effective notice, if any."""
    return db.scalar(select(ConsentNotice).where(ConsentNotice.is_active.is_(True)))


def selected_active_notice(
    db: Session,
    notice_id: int,
    notice_version: int,
) -> ConsentNotice | None:
    """Resolve the exact active notice the candidate saw before submitting.

    Matching both the immutable database id and copied version prevents a stale
    or tampered public form from silently consenting to a different notice.
    """

    return db.scalar(
        select(ConsentNotice).where(
            ConsentNotice.id == notice_id,
            ConsentNotice.version == notice_version,
            ConsentNotice.is_active.is_(True),
        )
    )


def record_consent(
    db: Session,
    candidate: Candidate,
    notice: ConsentNotice,
    *,
    channel: str,
    consented_at: datetime | None = None,
) -> tuple[CandidateConsent, bool]:
    """Record consent idempotently and synchronize the candidate projection.

    Repeated submissions against the same notice reuse the active consent row;
    a new notice version (or a fresh consent after withdrawal) creates a new
    immutable event. ``Candidate`` keeps the current, query-friendly projection
    used by matching and retention jobs.
    """

    consent = open_consent_for_notice(db, candidate, notice)
    created = consent is None
    if consent is None:
        consent = CandidateConsent(
            candidate_id=candidate.id,
            notice_id=notice.id,
            notice_version=notice.version,
            consented_at=consented_at or datetime.now(UTC),
            channel=channel,
        )
        db.add(consent)
        db.flush()

    candidate.consent_status = "consented"
    candidate.consent_at = consent.consented_at
    set_candidate_retention(db, candidate, candidate.retention_years_override)
    return consent, created


def open_consent_for_notice(
    db: Session,
    candidate: Candidate,
    notice: ConsentNotice,
) -> CandidateConsent | None:
    """Return an unwithdrawn consent for this exact candidate/notice pair."""

    return db.scalar(
        select(CandidateConsent)
        .where(
            CandidateConsent.candidate_id == candidate.id,
            CandidateConsent.notice_id == notice.id,
            CandidateConsent.notice_version == notice.version,
            CandidateConsent.withdrawn_at.is_(None),
        )
        .order_by(CandidateConsent.consented_at.desc(), CandidateConsent.id.desc())
        .limit(1)
    )


def record_public_consent(
    db: Session,
    candidate: Candidate,
    notice: ConsentNotice,
    *,
    candidate_created: bool,
) -> tuple[CandidateConsent, bool] | None:
    """Record public consent without allowing contact-detail account takeover.

    Email and phone are deduplication hints, not proof of identity. An anonymous
    form may create the first consent for a new candidate or idempotently reuse
    an existing, unwithdrawn consent to the exact same notice. Renewing a
    withdrawn consent or accepting a new notice version requires an authenticated
    HR/invitation workflow.
    """

    if not candidate_created:
        if candidate.consent_status == "withdrawn":
            return None
        if open_consent_for_notice(db, candidate, notice) is None:
            return None
    return record_consent(
        db,
        candidate,
        notice,
        channel="public_form",
    )


def withdraw_consent(
    db: Session,
    consent: CandidateConsent,
    *,
    withdrawn_at: datetime | None = None,
) -> int:
    """Withdraw a candidate's consent and immediately stop downstream use.

    Withdrawal is candidate-wide rather than notice-version-specific. Marking
    every still-open consent avoids an older version accidentally reactivating
    the candidate during a duplicate public submission.
    """

    at = withdrawn_at or datetime.now(UTC)
    open_consents = list(
        db.scalars(
            select(CandidateConsent).where(
                CandidateConsent.candidate_id == consent.candidate_id,
                CandidateConsent.withdrawn_at.is_(None),
            )
        ).all()
    )
    for item in open_consents:
        item.withdrawn_at = at

    candidate = db.get(Candidate, consent.candidate_id)
    if candidate is not None:
        latest_consented_at = db.scalar(
            select(func.max(CandidateConsent.consented_at)).where(
                CandidateConsent.candidate_id == consent.candidate_id
            )
        )
        candidate.consent_status = "withdrawn"
        candidate.consent_at = latest_consented_at or consent.consented_at
        # Make the retention worker eligible to process the record while the
        # matching gate stops using it immediately.
        candidate.retention_until = at.date()
    return len(open_consents)


def activate_notice(db: Session, notice: ConsentNotice) -> ConsentNotice:
    """Make ``notice`` the only active notice, deactivating every other row.

    The caller is responsible for committing the surrounding transaction.
    """
    db.execute(
        update(ConsentNotice)
        .where(ConsentNotice.id != notice.id, ConsentNotice.is_active.is_(True))
        .values(is_active=False)
    )
    notice.is_active = True
    db.flush()
    return notice
