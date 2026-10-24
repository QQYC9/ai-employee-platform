import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from packages.core.config import settings
from packages.core.database import Base
import packages.models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Preserve explicit sqlalchemy.url if provided (e.g. by isolated test runners)
existing_url = config.get_main_option("sqlalchemy.url")
if not existing_url or "localhost/dbname" in existing_url:
    config.set_main_option(
        "sqlalchemy.url",
        settings.database_url.replace("%", "%%"),
    )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url")
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Safety Guard: If executing inside pytest or test environment, strictly verify database isolation
        if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("TEST_ENV") == "true":
            from packages.core.safety_guard import verify_test_database_isolation
            verify_test_database_isolation(connection)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()

        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
