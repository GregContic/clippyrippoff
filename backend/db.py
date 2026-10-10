from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(RuntimeError):
    """Raised when the application cannot safely configure PostgreSQL."""


def database_url() -> str:
    return _normalize_url(os.getenv("DATABASE_URL", "").strip())


def _normalize_url(value: str) -> str:
    if not value:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required for PostgreSQL-backed authentication."
        )
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    if value.startswith("postgresql+psycopg://"):
        return value
    raise DatabaseConfigurationError(
        "DATABASE_URL must use a PostgreSQL connection URL."
    )


def migration_database_url() -> str:
    value = os.getenv("DATABASE_URL_UNPOOLED", "").strip()
    return _normalize_url(value or os.getenv("DATABASE_URL", "").strip())


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
