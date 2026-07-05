from __future__ import annotations

from sqlalchemy import select

from app.db.repositories.base import Repository
from app.models.refresh_token import RefreshToken
from app.models.user import User


class UserRepository(Repository):
    def get(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        return self.session.execute(select(User).where(User.username == username)).scalars().first()


class RefreshTokenRepository(Repository):
    def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        return self.session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).scalars().first()
