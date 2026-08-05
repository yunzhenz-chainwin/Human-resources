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


def test_submission_revision_migration_backfills_completed_records(
    monkeypatch,
) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = backend_root / "tests" / f".interview-submission-{uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = _alembic_config(backend_root)
    try:
        command.upgrade(config, "a1c7e5f9b340")
        with closing(sqlite3.connect(database_path)) as connection:
            connection.executemany(
                """
                INSERT INTO interview_records (
                    id, application_id, stage, interviewed_at, duration_minutes,
                    mode, status, questions, summary, private_notes,
                    recommendation, overall_rating, interviewer_id,
                    interviewer_name, updated_by_id, updated_by_name,
                    created_at, updated_at
                ) VALUES (?, ?, 'hr', ?, 45, 'video', ?, '[]', NULL, NULL,
                          NULL, NULL, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        1,
                        9001,
                        "2026-08-01 01:00:00",
                        "completed",
                        10,
                        "Original interviewer",
                        11,
                        "Latest editor",
                        "2026-08-01 01:00:00",
                        "2026-08-01 02:00:00",
                    ),
                    (
                        2,
                        9002,
                        "2026-08-02 01:00:00",
                        "in_progress",
                        12,
                        "Draft interviewer",
                        12,
                        "Draft interviewer",
                        "2026-08-02 01:00:00",
                        "2026-08-02 01:30:00",
                    ),
                ],
            )
            connection.commit()

        command.upgrade(config, "b6f0e4a2c913")
        with closing(sqlite3.connect(database_path)) as connection:
            columns = {
                column[1]: column
                for column in connection.execute("PRAGMA table_info(interview_records)")
            }
            assert {
                "submitted_at",
                "submitted_by_id",
                "submitted_by_name",
                "revision_number",
                "last_reopen_reason",
            } <= columns.keys()
            assert columns["id"][2].upper() == "INTEGER"
            assert columns["id"][5] == 1

            completed = connection.execute(
                """
                SELECT submitted_at, submitted_by_id, submitted_by_name,
                       revision_number, last_reopen_reason
                FROM interview_records WHERE id = 1
                """
            ).fetchone()
            assert completed == (
                "2026-08-01 02:00:00",
                11,
                "Latest editor",
                1,
                None,
            )
            draft = connection.execute(
                """
                SELECT submitted_at, submitted_by_id, submitted_by_name,
                       revision_number, last_reopen_reason
                FROM interview_records WHERE id = 2
                """
            ).fetchone()
            assert draft == (None, None, None, 0, None)

            cursor = connection.execute(
                """
                INSERT INTO interview_records (
                    application_id, stage, interviewed_at, mode, status,
                    questions, interviewer_name, updated_by_name
                ) VALUES (
                    9003, 'manager', '2026-08-03 01:00:00', 'onsite',
                    'in_progress', '[]', 'New manager', 'New manager'
                )
                """
            )
            connection.commit()
            assert cursor.lastrowid == 3
            assert connection.execute(
                "SELECT revision_number FROM interview_records WHERE id = 3"
            ).fetchone() == (0,)

        command.downgrade(config, "a1c7e5f9b340")
        with closing(sqlite3.connect(database_path)) as connection:
            columns = {
                column[1]
                for column in connection.execute("PRAGMA table_info(interview_records)")
            }
            assert "revision_number" not in columns
            assert "submitted_at" not in columns
            assert connection.execute(
                "SELECT status FROM interview_records ORDER BY id"
            ).fetchall() == [("completed",), ("in_progress",), ("in_progress",)]
    finally:
        get_settings.cache_clear()
        database_path.unlink(missing_ok=True)
