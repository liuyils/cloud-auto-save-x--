from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.runtime import SessionLocal, driver, engine, session_scope
from app.db.uow import UnitOfWork, unit_of_work


def is_lock_error(exc: Exception) -> bool:
    return driver.is_lock_error(exc)


def is_sqlite_locked_error(exc: Exception) -> bool:
    return is_lock_error(exc)


def healthcheck_sql() -> str:
    return driver.healthcheck_sql()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_uow() -> Generator[UnitOfWork, None, None]:
    with unit_of_work() as uow:
        yield uow


__all__ = [
    "SessionLocal",
    "UnitOfWork",
    "driver",
    "engine",
    "get_db",
    "get_uow",
    "healthcheck_sql",
    "is_lock_error",
    "is_sqlite_locked_error",
    "session_scope",
    "unit_of_work",
]
