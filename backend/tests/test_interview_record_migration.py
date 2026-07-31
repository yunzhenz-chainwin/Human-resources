from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from alembic.config import Config

from alembic import command
from app.core.config import get_settings


def _alembic_config(backend_root: Path) -> Config:
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return config


def test_sqlite_interview_record_id_is_generated_after_migration(
    monkeypatch,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = backend_root / "tests" / f".interview-record-migration-{uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = _alembic_config(backend_root)
    try:
        command.upgrade(config, "c9f6a12e4d70")
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                """
                INSERT INTO interview_records (
                    id, application_id, stage, interviewed_at, duration_minutes,
                    mode, status, questions, summary, private_notes,
                    recommendation, overall_rating, interviewer_id,
                    interviewer_name, updated_by_id, updated_by_name,
                    created_at, updated_at
                ) VALUES (
                    41, 9001, 'hr', '2026-07-24 08:00:00', 60,
                    'video', 'in_progress', '[]', NULL, NULL,
                    NULL, NULL, NULL, 'Migration fixture', NULL,
                    'Migration fixture', '2026-07-24 08:00:00',
                    '2026-07-24 08:00:00'
                )
                """
            )
            connection.commit()

        command.upgrade(config, "d4a7f18c2e63")
        with closing(sqlite3.connect(database_path)) as connection:
            id_column = next(
                column
                for column in connection.execute("PRAGMA table_info(interview_records)")
                if column[1] == "id"
            )
            assert id_column[2].upper() == "INTEGER"
            assert id_column[5] == 1
            assert connection.execute(
                "SELECT interviewer_name FROM interview_records WHERE id = 41"
            ).fetchone() == ("Migration fixture",)

            cursor = connection.execute(
                """
                INSERT INTO interview_records (
                    application_id, stage, interviewed_at, duration_minutes,
                    mode, status, questions, summary, private_notes,
                    recommendation, overall_rating, interviewer_id,
                    interviewer_name, updated_by_id, updated_by_name,
                    created_at, updated_at
                ) VALUES (
                    9002, 'manager', '2026-07-24 09:00:00', 45,
                    'onsite', 'in_progress', '[]', NULL, NULL,
                    NULL, NULL, NULL, 'New interviewer', NULL,
                    'New interviewer', '2026-07-24 09:00:00',
                    '2026-07-24 09:00:00'
                )
                """
            )
            connection.commit()
            assert cursor.lastrowid == 42
            assert connection.execute(
                "SELECT id FROM interview_records WHERE application_id = 9002"
            ).fetchone() == (42,)

        command.upgrade(config, "head")
        with closing(sqlite3.connect(database_path)) as connection:
            plan_columns = {
                column[1]
                for column in connection.execute("PRAGMA table_info(interview_question_plans)")
            }
            assert {
                "application_id",
                "question_plan_id",
                "question_plan_version",
                "stage",
                "interviewed_at",
            }.issubset(
                {
                    column[1]
                    for column in connection.execute("PRAGMA table_info(interview_records)")
                }
            )
            assert {
                "application_id",
                "stage",
                "context_hash",
                "version",
                "questions",
                "personalization_basis",
                "generation_mode",
                "provider",
                "model_name",
                "input_tokens",
                "output_tokens",
                "thinking_tokens",
                "total_tokens",
            }.issubset(plan_columns)
            assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
                ("e63b1f8a2d40",)
            ]
    finally:
        get_settings.cache_clear()
        database_path.unlink(missing_ok=True)


def test_question_plan_stage_migration_can_downgrade_with_parallel_versions(
    monkeypatch,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = backend_root / "tests" / f".question-plan-downgrade-{uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = _alembic_config(backend_root)
    try:
        command.upgrade(config, "head")
        with closing(sqlite3.connect(database_path)) as connection:
            plan_values = (
                9001,
                "a" * 64,
                1,
                "[]",
                "[]",
                "rules",
                "internal",
                "Migration fixture",
            )
            connection.execute(
                """
                INSERT INTO interview_question_plans (
                    application_id, stage, context_hash, version, questions,
                    personalization_basis, generation_mode, provider,
                    generated_by_name
                ) VALUES (?, 'hr', ?, ?, ?, ?, ?, ?, ?)
                """,
                plan_values,
            )
            connection.execute(
                """
                INSERT INTO interview_question_plans (
                    application_id, stage, context_hash, version, questions,
                    personalization_basis, generation_mode, provider,
                    generated_by_name
                ) VALUES (?, 'manager', ?, ?, ?, ?, ?, ?, ?)
                """,
                plan_values,
            )
            connection.commit()

        command.downgrade(config, "f6a2d4c8b901")
        with closing(sqlite3.connect(database_path)) as connection:
            columns = {
                column[1]
                for column in connection.execute("PRAGMA table_info(interview_question_plans)")
            }
            assert "stage" not in columns
            assert connection.execute(
                "SELECT application_id, version FROM interview_question_plans"
            ).fetchall() == [(9001, 1)]
            assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [
                ("f6a2d4c8b901",)
            ]
    finally:
        get_settings.cache_clear()
        database_path.unlink(missing_ok=True)
