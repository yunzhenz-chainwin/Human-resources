from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from app.core.config import get_settings
from app.schemas.interview_questions import (
    QUESTION_SOURCE_MAX_LENGTH,
    InterviewQuestionPlanItem,
)
from app.services.interview_questions import _bounded_source


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
        expected_head = ScriptDirectory.from_config(config).get_current_head()
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
                (expected_head,)
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


def test_migration_bounds_overlong_stored_question_plan_sources(monkeypatch) -> None:
    """Plans generated before the source cap can hold provenance far beyond 200
    characters, which the read schema now rejects -- turning every read of such a
    plan into a 500 until a force-regenerate replaces it. a9e3d51c7b82 truncates
    the stored copies exactly the way newly generated ones are truncated."""

    backend_root = Path(__file__).resolve().parents[1]
    database_path = backend_root / "tests" / f".question-plan-source-{uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = _alembic_config(backend_root)
    try:
        command.upgrade(config, "f4b8c26d90a7")
        overlong = "Gemini 動態題目｜" + "職缺依據與履歷佐證  補充說明" * 30
        short = "應徵職位：資深後端工程師"
        questions = [
            {
                "category": "經驗轉移",
                "question": "請說明一段最能轉移到本職位的經驗。",
                "purpose": "驗證可轉移能力。",
                "follow_up": "你親自負責哪一部分？",
                "source": overlong,
            },
            {
                "category": "專業能力",
                "question": "請以實際案例說明你的核心技能。",
                "purpose": "驗證技能證據。",
                "follow_up": "成果如何衡量？",
                "source": short,
            },
        ]
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                """
                INSERT INTO interview_question_plans (
                    application_id, stage, context_hash, version, questions,
                    personalization_basis, generation_mode, provider,
                    generated_by_name
                ) VALUES (?, 'manager', ?, 1, ?, '[]', 'gemini', 'gemini', 'Migration fixture')
                """,
                (9001, "a" * 64, json.dumps(questions, ensure_ascii=False)),
            )
            connection.commit()

        command.upgrade(config, "head")

        with closing(sqlite3.connect(database_path)) as connection:
            stored = json.loads(
                connection.execute(
                    "SELECT questions FROM interview_question_plans WHERE application_id = 9001"
                ).fetchone()[0]
            )
        assert stored[0]["source"] == _bounded_source(overlong)
        assert len(stored[0]["source"]) <= QUESTION_SOURCE_MAX_LENGTH
        assert stored[1]["source"] == short
        # The read path must accept the migrated rows again -- this validation is
        # exactly what 500ed on legacy rows before the truncation.
        for item in stored:
            InterviewQuestionPlanItem.model_validate(item)
    finally:
        get_settings.cache_clear()
        database_path.unlink(missing_ok=True)
