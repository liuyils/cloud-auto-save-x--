from __future__ import annotations

from sqlalchemy import select

from app.db.repositories.base import Repository
from app.models.permission import Permission
from app.models.role import Role


class RoleRepository(Repository):
    def get_by_name(self, name: str) -> Role | None:
        return self.session.execute(select(Role).where(Role.name == name)).scalars().first()


class PermissionRepository(Repository):
    def get_by_code(self, code: str) -> Permission | None:
        return self.session.execute(select(Permission).where(Permission.code == code)).scalars().first()
