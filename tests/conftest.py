from __future__ import annotations

import logging
import os
os.environ["TEST_ENV"] = "true"
from typing import Generator
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from packages.core.config import settings
import packages.core.database as core_db
from packages.core.safety_guard import (
    get_actual_connected_database,
    verify_test_database_isolation,
)

logger = logging.getLogger(__name__)


def pytest_configure(config: pytest.Config) -> None:
    """
    SAFETY PROTOCOL & TEST ENVIRONMENT ISOLATION
    Executed before any test collection or execution begins.
    1. Enforces TEST_ENV='true'.
    2. Overrides settings.database_url to point exclusively to the isolated test database.
    3. Re-initializes packages.core.database engine and SessionLocal to target ai_employee_test.
    4. Executes a live SQL query (SELECT current_database()) to prove isolation.
       If the database is 'ai_employee' or any protected database, pytest aborts immediately.
    """
    os.environ["TEST_ENV"] = "true"
    test_db_url = settings.effective_test_database_url

    # Override process settings
    os.environ["DATABASE_URL"] = test_db_url
    settings.database_url = test_db_url

    # Rebind core database engine and sessionmaker to test database
    isolated_engine = create_engine(
        test_db_url,
        pool_pre_ping=True,
    )

    # Live SQL verification: fail fast if connected to application database
    actual_db = verify_test_database_isolation(isolated_engine)
    logger.info("Test environment isolated successfully. Connected to: %s", actual_db)

    # Rebind global references in packages.core.database
    core_db.engine = isolated_engine
    core_db.SessionLocal = sessionmaker(
        bind=isolated_engine,
        autoflush=False,
        autocommit=False,
    )


@pytest.fixture(scope="session", autouse=True)
def verify_test_database_isolation_session() -> Generator[None, None, None]:
    """
    Session-level autouse safety guard: proves live SQL isolation at session start and end.
    """
    actual_db = verify_test_database_isolation(core_db.engine)
    assert actual_db == "ai_employee_test", (
        f"CRITICAL TEST ISOLATION FAILURE: Expected database 'ai_employee_test', "
        f"but live connection is to '{actual_db}'."
    )
    yield
    # Verify isolation still holds upon teardown
    actual_db_end = verify_test_database_isolation(core_db.engine)
    assert actual_db_end == "ai_employee_test"


@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """
    Provides a database session strictly bound to the isolated test database.
    """
    actual_db = verify_test_database_isolation(core_db.engine)
    assert actual_db == "ai_employee_test"
    session = core_db.SessionLocal()
    try:
        yield session
    finally:
        session.close()
