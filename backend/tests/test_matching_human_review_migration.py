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


def test_matching_human_review_migration_preserves_legacy_decisions(monkeypatch) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = backend_root / "tests" / f".matching-review-{uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = _alembic_config(backend_root)
    try:
        command.upgrade(config, "b91e6d4f2a30")
        with closing(sqlite3.connect(database_path)) as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id, username, email, password_hash, display_name, role, is_active
                ) VALUES (1, 'reviewer', 'reviewer@example.com', 'hash', 'Reviewer', 'hr', 1)
                """
            )
            connection.execute(
                """
                INSERT INTO candidates (id, code, name, status, is_blacklisted)
                VALUES (1, 'LEGACY-1', 'Legacy Candidate', 'new', 0)
                """
            )
            connection.execute(
                """
                INSERT INTO job_requisitions (
                    id, req_no, title, headcount, employment_type, work_city,
                    jd, urgency, status
                ) VALUES (
                    1, 'LEGACY-JOB', 'Legacy Job', 1, 'full_time', '台北市',
                    'Legacy JD', 'normal', 'sourcing'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO match_results (
                    id, requisition_id, candidate_id, gate_passed, total_score,
                    score_breakdown, rank, status, feedback_reason, feedback_by,
                    feedback_at, computed_at, created_at, updated_at
                ) VALUES (
                    1, 1, 1, 0, 65, '{}', NULL, 'interview',
                    'Legacy free text', 1, '2026-07-01 09:00:00',
                    '2026-07-01 08:00:00', '2026-07-01 08:00:00',
                    '2026-07-01 09:00:00'
                )
                """
            )
            connection.commit()

        command.upgrade(config, "c27d8e5f4a61")
        with closing(sqlite3.connect(database_path)) as connection:
            columns = {
                column[1] for column in connection.execute("PRAGMA table_info(match_results)")
            }
            assert {
                "stage_updated_by",
                "stage_updated_at",
                "manual_override_category",
                "manual_override_note",
                "manual_override_by",
                "manual_override_at",
                "feedback_category",
                "feedback_note",
            }.issubset(columns)
            row = connection.execute(
                """
                SELECT status, feedback_reason, feedback_category, feedback_note,
                       stage_updated_by, manual_override_category,
                       manual_override_note, manual_override_by
                FROM match_results WHERE id = 1
                """
            ).fetchone()
            assert row == (
                "interview",
                "Legacy free text",
                "other",
                "Legacy free text",
                1,
                "legacy_decision",
                "既有人工決策（系統升級時保留）",
                1,
            )

        command.downgrade(config, "b91e6d4f2a30")
        with closing(sqlite3.connect(database_path)) as connection:
            columns = {
                column[1] for column in connection.execute("PRAGMA table_info(match_results)")
            }
            assert "manual_override_at" not in columns
            assert connection.execute(
                "SELECT status, feedback_reason FROM match_results WHERE id = 1"
            ).fetchone() == ("interview", "Legacy free text")
    finally:
        get_settings.cache_clear()
        database_path.unlink(missing_ok=True)
