from __future__ import annotations

import os
import pytest
from sqlalchemy import create_engine, text

from packages.core.config import settings
from packages.core.database import SessionLocal, engine
from packages.core.safety_guard import (
    derive_test_database_url,
    get_actual_connected_database,
    verify_test_database_isolation,
)


def test_safety_guard_rejects_protected_databases():
    """
    Requirement 5: Proves that the safety guard strictly aborts and raises
    RuntimeError if given a connection to 'ai_employee' or any non-test database.
    """
    # Create an engine connected to the application database
    app_engine = create_engine(settings.database_url.replace("ai_employee_test", "ai_employee"))
    
    with pytest.raises(RuntimeError) as exc_info:
        verify_test_database_isolation(app_engine)
    
    assert "CRITICAL SAFETY VIOLATION" in str(exc_info.value)
    assert "ai_employee" in str(exc_info.value)


def test_safety_guard_accepts_test_database():
    """
    Requirement 5: Proves that the safety guard passes and returns the database name
    when connected to the verified isolated test database 'ai_employee_test'.
    """
    verified = verify_test_database_isolation(engine)
    assert verified == "ai_employee_test"


def test_live_session_connected_strictly_to_test_database():
    """
    Requirement 6: Executes a live SQL query (SELECT current_database()) on the session
    to prove beyond doubt that tests operate in the isolated database.
    """
    with SessionLocal() as session:
        current_db = session.execute(text("SELECT current_database();")).scalar()
        assert current_db == "ai_employee_test", (
            f"Isolation failure: expected 'ai_employee_test', got '{current_db}'"
        )


def test_derive_test_database_url_preserves_connection_topology():
    """
    Requirement 2 & 5: Verifies that test URL derivation accurately updates
    the database name to 'ai_employee_test' without exposing or breaking credentials.
    """
    sample_url = "postgresql+psycopg://myuser:secret123@localhost:5433/ai_employee?sslmode=prefer"
    test_url = derive_test_database_url(sample_url, "ai_employee_test")
    assert "/ai_employee_test" in test_url
    assert "myuser" in test_url
    assert "5433" in test_url
    assert "sslmode=prefer" in test_url
    assert test_url.split("?")[0].endswith("/ai_employee_test")
    assert not test_url.split("?")[0].endswith("/ai_employee")
