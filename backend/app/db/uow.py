from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.repositories import (
    CacheRepository,
    DriveAccountLsdirCacheRepository,
    DriveAccountRepository,
    PermissionRepository,
    RefreshTokenRepository,
    RoleRepository,
    SettingsRepository,
    SyncExecutionRepository,
    SyncLockRepository,
    SyncTaskRepository,
    TaskExecutionRepository,
    TaskRepository,
    TaskSnapshotRepository,
    TelegramRepository,
    TMDBRepository,
    UserRepository,
)
from app.db.runtime import SessionLocal


@dataclass
class UnitOfWork:
    session: Session

    def __post_init__(self) -> None:
        self.users = UserRepository(self.session)
        self.refresh_tokens = RefreshTokenRepository(self.session)
        self.roles = RoleRepository(self.session)
        self.permissions = PermissionRepository(self.session)
        self.tasks = TaskRepository(self.session)
        self.task_executions = TaskExecutionRepository(self.session)
        self.task_snapshots = TaskSnapshotRepository(self.session)
        self.sync_tasks = SyncTaskRepository(self.session)
        self.sync_executions = SyncExecutionRepository(self.session)
        self.sync_locks = SyncLockRepository(self.session)
        self.drive_accounts = DriveAccountRepository(self.session)
        self.drive_account_lsdir_cache = DriveAccountLsdirCacheRepository(self.session)
        self.settings = SettingsRepository(self.session)
        self.tmdb = TMDBRepository(self.session)
        self.caches = CacheRepository(self.session)
        self.telegram = TelegramRepository(self.session)

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()


@contextmanager
def unit_of_work() -> UnitOfWork:
    session = SessionLocal()
    uow = UnitOfWork(session)
    try:
        yield uow
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()
