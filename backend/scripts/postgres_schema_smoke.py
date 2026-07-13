"""Fail fast when a migrated PostgreSQL schema is incomplete or on the wrong head."""

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import BigInteger, create_engine, inspect, text

from app.core.config import get_settings

REQUIRED_TABLES = {
    "alembic_version",
    "departments",
    "users",
    "candidates",
    "candidate_educations",
    "candidate_experiences",
    "candidate_activities",
    "candidate_skills",
    "job_requisitions",
    "resume_files",
    "job_applications",
    "match_results",
}


def main() -> None:
    engine = create_engine(get_settings().database_url)
    if engine.dialect.name != "postgresql":
        raise SystemExit(f"PostgreSQL is required; got {engine.dialect.name}")

    inspector = inspect(engine)
    missing = REQUIRED_TABLES - set(inspector.get_table_names())
    if missing:
        raise SystemExit(f"Missing migrated tables: {', '.join(sorted(missing))}")

    alembic_config = Config("alembic.ini")
    expected_heads = set(ScriptDirectory.from_config(alembic_config).get_heads())
    with engine.begin() as connection:
        database_heads = set(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        if database_heads != expected_heads:
            raise SystemExit(
                f"Migration head mismatch: database={database_heads}, code={expected_heads}"
            )
        generated_id = connection.execute(
            text("INSERT INTO departments (name) VALUES (:name) RETURNING id"),
            {"name": "__postgres_schema_smoke__"},
        ).scalar_one()
        if generated_id <= 0:
            raise SystemExit("BIGINT identity/default did not generate a positive id")
        connection.execute(text("DELETE FROM departments WHERE id = :id"), {"id": generated_id})

    candidate_id = next(
        column for column in inspector.get_columns("candidates") if column["name"] == "id"
    )
    if not isinstance(candidate_id["type"], BigInteger):
        raise SystemExit(f"candidates.id must be BIGINT on PostgreSQL; got {candidate_id['type']}")
    application_fks = {
        tuple(foreign_key["constrained_columns"])
        for foreign_key in inspector.get_foreign_keys("job_applications")
    }
    required_fks = {("candidate_id",), ("requisition_id",), ("resume_id",)}
    if not required_fks.issubset(application_fks):
        raise SystemExit("job_applications is missing a required foreign key")

    print(f"PostgreSQL schema smoke passed at head(s): {', '.join(sorted(expected_heads))}")


if __name__ == "__main__":
    main()
