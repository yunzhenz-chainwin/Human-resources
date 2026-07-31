"""Business rules for versioned recruitment consent notices (PDPA §8/§9).

Keeping the "only one active notice" invariant here means both the API route and
any future automation share one implementation and cannot drift apart.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.consent import ConsentNotice


def next_version(db: Session) -> int:
    """Return the next monotonically increasing notice version."""
    current = db.scalar(select(func.max(ConsentNotice.version)))
    return int(current or 0) + 1


def active_notice(db: Session) -> ConsentNotice | None:
    """Return the single currently effective notice, if any."""
    return db.scalar(select(ConsentNotice).where(ConsentNotice.is_active.is_(True)))


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
