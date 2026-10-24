from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, urlunparse
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

PROTECTED_DATABASES = {
    "ai_employee",
    "ai_employee_prod",
    "ai_employee_production",
    "ai_employee_staging",
    "postgres",
}


def get_actual_connected_database(target: Connection | Engine) -> str:
    """Queries PostgreSQL directly via SQL to get the active database name."""
    if hasattr(target, "connect"):
        with target.connect() as conn:
            actual_db = conn.execute(text("SELECT current_database();")).scalar()
    else:
        actual_db = target.execute(text("SELECT current_database();")).scalar()
    return str(actual_db or "").strip().lower()


def verify_test_database_isolation(target: Connection | Engine) -> str:
    """
    SAFETY GUARD: Queries PostgreSQL directly via 'SELECT current_database()'
    to verify that the active connection is strictly connected to an isolated test database.
    
    Raises RuntimeError immediately if connected to 'ai_employee' or any non-test database.
    """
    actual_db = get_actual_connected_database(target)
    
    if actual_db in PROTECTED_DATABASES:
        raise RuntimeError(
            f"CRITICAL SAFETY VIOLATION: Execution aborted! Connected to protected database '{actual_db}'. "
            f"Test and destructive migration operations are strictly forbidden on protected databases."
        )
    
    if not (actual_db.endswith("_test") or "test" in actual_db):
        raise RuntimeError(
            f"CRITICAL SAFETY VIOLATION: Target database '{actual_db}' does not have a '_test' suffix. "
            f"Operation aborted to protect non-test environments."
        )
    
    return actual_db


def derive_test_database_url(base_url: str, test_db_name: str = "ai_employee_test") -> str:
    """
    Derives an isolated test database connection URL from a base URL by substituting
    the database name in the path. Preserves credentials, driver, host, and port without hardcoding.
    """
    u = urlparse(base_url)
    clean_path = f"/{test_db_name.lstrip('/')}"
    new_u = u._replace(path=clean_path)
    return urlunparse(new_u)
