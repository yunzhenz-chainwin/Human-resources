"""bound stored question-plan sources to what a record can store

Revision ID: a9e3d51c7b82
Revises: f4b8c26d90a7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9e3d51c7b82"
down_revision: str | None = "f4b8c26d90a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors QUESTION_SOURCE_MAX_LENGTH / _bounded_source in the application, inlined
# here because a migration must keep working even after the application code moves.
_MAX_SOURCE = 200


def _bounded(value: str) -> str:
    clean = " ".join(value.split())
    if len(clean) <= _MAX_SOURCE:
        return clean
    return clean[: _MAX_SOURCE - 1] + "…"


_plans = sa.table(
    "interview_question_plans",
    sa.column("id", sa.BigInteger()),
    sa.column("questions", sa.JSON()),
)


def upgrade() -> None:
    # Plans generated before the source cap existed can hold provenance strings of
    # several hundred characters (Gemini scratch text included). The read schema now
    # rejects anything over 200, which turns every read of such a plan -- including
    # the regenerate path that could have replaced it -- into a 500. Truncate the
    # stored copies the same way newly generated ones are truncated.
    bind = op.get_bind()
    rows = bind.execute(sa.select(_plans.c.id, _plans.c.questions)).fetchall()
    for plan_id, questions in rows:
        if not isinstance(questions, list):
            continue
        changed = False
        for item in questions:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            if isinstance(source, str) and len(source) > _MAX_SOURCE:
                item["source"] = _bounded(source)
                changed = True
        if changed:
            bind.execute(
                _plans.update().where(_plans.c.id == plan_id).values(questions=questions)
            )


def downgrade() -> None:
    # Truncation is lossy: the discarded provenance text cannot be restored.
    pass
