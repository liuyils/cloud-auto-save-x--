from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import settings
from app.db.drivers import DatabaseDriver, create_database_driver


@dataclass(frozen=True)
class DatabaseRuntime:
    driver: DatabaseDriver
    engine: object
    SessionLocal: sessionmaker


def build_runtime(*, for_migrations: bool = False) -> DatabaseRuntime:
    driver = create_database_driver(settings)
    errors = driver.validation_errors()
    if errors:
        raise RuntimeError("; ".join(errors))
    driver.prepare_environment()
    engine = create_engine(
        driver.url,
        connect_args=driver.connect_args(),
        **driver.engine_kwargs(for_migrations=for_migrations),
    )
    driver.configure_engine(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    return DatabaseRuntime(driver=driver, engine=engine, SessionLocal=session_local)


runtime = build_runtime()
driver = runtime.driver
engine = runtime.engine
SessionLocal = runtime.SessionLocal


@contextmanager
def session_scope() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
