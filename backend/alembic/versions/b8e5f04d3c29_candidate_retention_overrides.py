"""add per-candidate retention period overrides

Revision ID: b8e5f04d3c29
Revises: a7d4e93c2b18
"""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa

from alembic import op

revision: str = "b8e5f04d3c29"
down_revision: str | None = "a7d4e93c2b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def upgrade() -> None:
    with op.batch_alter_table("candidates") as batch:
        batch.add_column(
            sa.Column("retention_years_override", sa.SmallInteger(), nullable=True)
        )
        batch.create_check_constraint(
            "retention_years_override_range",
            "retention_years_override IS NULL OR "
            "retention_years_override BETWEEN 1 AND 20",
        )

    # Existing rows previously had no way to distinguish a global deadline from
    # an individual one. They now follow the current company policy, so synchronize
    # their concrete deadlines during the migration instead of showing stale dates.
    settings = sa.table(
        "system_settings",
        sa.column("key", sa.String()),
        sa.column("value", sa.JSON()),
    )
    candidates = sa.table(
        "candidates",
        sa.column("id", sa.BigInteger()),
        sa.column("consent_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("retention_until", sa.Date()),
    )
    connection = op.get_bind()
    configured_years = connection.execute(
        sa.select(settings.c.value).where(
            settings.c.key == "candidate.retention_years"
        )
    ).scalar_one_or_none()
    years = (
        configured_years
        if isinstance(configured_years, int) and not isinstance(configured_years, bool)
        else 2
    )
    if years < 1 or years > 20:
        years = 2
    for row in connection.execute(
        sa.select(
            candidates.c.id,
            candidates.c.consent_at,
            candidates.c.created_at,
        )
    ):
        anchor = row.consent_at or row.created_at
        if anchor is None:
            continue
        connection.execute(
            candidates.update()
            .where(candidates.c.id == row.id)
            .values(retention_until=_add_years(anchor.date(), years))
        )


def downgrade() -> None:
    with op.batch_alter_table("candidates") as batch:
        batch.drop_constraint(
            "retention_years_override_range",
            type_="check",
        )
        batch.drop_column("retention_years_override")
