from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)


def _load_normalization_migration():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "e7b2c91d5f40_normalize_password_change_boolean.py"
    )
    spec = spec_from_file_location("password_change_boolean_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migrated_sqlite_boolean_preserves_credentials_and_real_forced_flags() -> None:
    engine = create_engine("sqlite://")
    metadata = MetaData()
    users = Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("username", String(100), nullable=False),
        Column("password_hash", String(255), nullable=False),
        Column(
            "must_change_password",
            Boolean,
            nullable=False,
            # Reproduce e15b9d4c7a83's original quoted default. On SQLite this
            # stores the TEXT value ``'false'`` instead of native integer 0.
            server_default="false",
        ),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        # Reproduce rows produced by the old quoted SQLite default. Include a real
        # textual true value to prove that forced-change accounts remain forced.
        connection.exec_driver_sql(
            """
            INSERT INTO users (id, username, password_hash, must_change_password)
            VALUES
                (1, 'legacy_false', 'hash-must-not-change-1', 'false'),
                (2, 'legacy_true',  'hash-must-not-change-2', 'true'),
                (3, 'native_false', 'hash-must-not-change-3', 0),
                (4, 'native_true',  'hash-must-not-change-4', 1)
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO users (id, username, password_hash) "
            "VALUES (5, 'legacy_default', 'hash-must-not-change-5')"
        )
        assert connection.exec_driver_sql(
            """
            SELECT must_change_password, typeof(must_change_password)
              FROM users
             WHERE id = 5
            """
        ).one() == ("false", "text")
        assert (
            connection.execute(
                select(users.c.must_change_password).where(users.c.id == 5)
            ).scalar_one()
            is True
        )

        migration = _load_normalization_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        raw_rows = connection.exec_driver_sql(
            """
            SELECT username, must_change_password, typeof(must_change_password), password_hash
              FROM users
             ORDER BY id
            """
        ).all()
        assert raw_rows == [
            ("legacy_false", 0, "integer", "hash-must-not-change-1"),
            ("legacy_true", 1, "integer", "hash-must-not-change-2"),
            ("native_false", 0, "integer", "hash-must-not-change-3"),
            ("native_true", 1, "integer", "hash-must-not-change-4"),
            ("legacy_default", 0, "integer", "hash-must-not-change-5"),
        ]

        # Exercise SQLAlchemy's Boolean result processor: this is where TEXT
        # ``'false'`` previously became True and caused the erroneous HTTP 403.
        typed_flags = dict(
            connection.execute(
                select(users.c.username, users.c.must_change_password).order_by(users.c.id)
            ).all()
        )
        assert typed_flags == {
            "legacy_false": False,
            "legacy_true": True,
            "native_false": False,
            "native_true": True,
            "legacy_default": False,
        }

        # The corrected SQL default also creates a native SQLite integer, not TEXT.
        connection.exec_driver_sql(
            "INSERT INTO users (id, username, password_hash) "
            "VALUES (6, 'new_default', 'hash-must-not-change-6')"
        )
        assert connection.exec_driver_sql(
            """
            SELECT must_change_password, typeof(must_change_password), password_hash
              FROM users
             WHERE id = 6
            """
        ).one() == (0, "integer", "hash-must-not-change-6")
