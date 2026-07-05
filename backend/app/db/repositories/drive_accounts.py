from __future__ import annotations

from sqlalchemy import select

from app.db.repositories.base import Repository
from app.models.drive_account import DriveAccount
from app.models.drive_account_lsdir_cache import DriveAccountLsdirCache


class DriveAccountRepository(Repository):
    def get(self, account_id: int) -> DriveAccount | None:
        return self.session.get(DriveAccount, account_id)

    def list_all(self) -> list[DriveAccount]:
        return self.session.execute(select(DriveAccount).order_by(DriveAccount.is_default.desc(), DriveAccount.id.asc())).scalars().all()


class DriveAccountLsdirCacheRepository(Repository):
    model = DriveAccountLsdirCache
