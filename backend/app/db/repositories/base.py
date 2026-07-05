from __future__ import annotations

from sqlalchemy.orm import Session


class Repository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, entity) -> None:
        self.session.add(entity)

    def delete(self, entity) -> None:
        self.session.delete(entity)

    def flush(self) -> None:
        self.session.flush()
