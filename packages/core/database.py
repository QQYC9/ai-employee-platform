import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from packages.core.config import settings


class Base(DeclarativeBase):
    pass


def get_current_database_url() -> str:
    """Returns test database URL when running under tests, otherwise application database URL."""
    if os.environ.get("TEST_ENV") == "true" or "PYTEST_CURRENT_TEST" in os.environ:
        return settings.effective_test_database_url
    return settings.database_url


engine = create_engine(
    get_current_database_url(),
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)
