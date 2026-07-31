from logging.config import fileConfig

from sqlalchemy import BigInteger, engine_from_config, pool

from alembic import context
from app import models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def compare_column_type(
    migration_context,
    _inspected_column,
    _metadata_column,
    inspected_type,
    metadata_type,
):
    """Ignore SQLite's equivalent BIGINT spelling while retaining real type checks."""

    if (
        migration_context.dialect.name == "sqlite"
        and isinstance(inspected_type, BigInteger)
        and isinstance(metadata_type, BigInteger)
    ):
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=compare_column_type,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
