"""allow the interview_ready application status

Revision ID: d38c1a5e97b4
Revises: c4e9b7d21f65
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d38c1a5e97b4"
down_revision: str | None = "c4e9b7d21f65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# job_applications.status is an unconstrained VARCHAR(20): no CHECK constraint or
# enum type governs it, and "interview_ready" fits the existing width. The value
# therefore needs no DDL, and this revision is a schema-history marker recording
# when the status became part of the contract. Its downgrade returns applications
# still parked in that state to "submitted", the pre-interview status they were
# marked from, so an older deployment never sees a value it does not know.
_INTERVIEW_READY = "interview_ready"
_PRE_INTERVIEW_FALLBACK = "submitted"


def upgrade() -> None:
    pass


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE job_applications SET status = :fallback WHERE status = :ready"
        ).bindparams(fallback=_PRE_INTERVIEW_FALLBACK, ready=_INTERVIEW_READY)
    )
