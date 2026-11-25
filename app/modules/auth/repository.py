"""
Инфраструктурный слой аутентификации.

Отвечает за сохранение, поиск и аннулирование refresh-токенов в БД или памяти.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import RefreshToken, User
from app.modules.users.repository import create_user_repository


@dataclass
class RefreshTokenRecord:
    id: int
    user_id: int
    token_hash: str
    expires_at: datetime
    is_revoked: bool = False


class AuthRepository(ABC):
    """Контракт хранилища данных аутентификации."""

    @abstractmethod
    def get_user_by_email(self, email: str) -> Any:
        """Поиск пользователя по email."""

    @abstractmethod
    def get_user_by_id(self, user_id: int) -> Any:
        """Поиск пользователя по id."""

    @abstractmethod
    def save_refresh_token(
        self,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        """Сохранение refresh-токена."""

    @abstractmethod
    def get_refresh_token(self, token_hash: str) -> Any:
        """Получение refresh-токена по его хешу."""

    @abstractmethod
    def revoke_refresh_token(self, token_hash: str) -> None:
        """Отзыв конкретного refresh-токена."""

    @abstractmethod
    def revoke_all_user_tokens(self, user_id: int) -> None:
        """Отзыв всех активных refresh-токенов пользователя при компрометации."""


class SqlAlchemyAuthRepository(AuthRepository):
    """Реализация хранилища аутентификации через PostgreSQL и SQLAlchemy."""

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_email(self, email: str) -> Any:
        return self.db.query(User).filter(User.email == email).first()

    def get_user_by_id(self, user_id: int) -> Any:
        return self.db.query(User).filter(User.id == user_id).first()

    def save_refresh_token(
        self,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        token_obj = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_revoked=False,
        )
        self.db.add(token_obj)
        self.db.commit()

    def get_refresh_token(self, token_hash: str) -> Any:
        return (
            self.db.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .first()
        )

    def revoke_refresh_token(self, token_hash: str) -> None:
        token_obj = (
            self.db.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .first()
        )
        if token_obj:
            token_obj.is_revoked = True
            self.db.commit()

    def revoke_all_user_tokens(self, user_id: int) -> None:
        tokens = (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked.is_(False),
            )
            .all()
        )
        for token_obj in tokens:
            token_obj.is_revoked = True
        self.db.commit()


class InMemoryAuthRepository(AuthRepository):
    """In-memory реализация хранилища аутентификации для изолированных тестов."""

    def __init__(self) -> None:
        self.tokens: dict[str, RefreshTokenRecord] = {}
        self._next_id = 1

    def get_user_by_email(self, email: str) -> Any:
        user_repo = create_user_repository(None)
        return user_repo.get_by_email(email)

    def get_user_by_id(self, user_id: int) -> Any:
        user_repo = create_user_repository(None)
        return user_repo.get_by_id(user_id)

    def save_refresh_token(
        self,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        record = RefreshTokenRecord(
            id=self._next_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            is_revoked=False,
        )
        self._next_id += 1
        self.tokens[token_hash] = record

    def get_refresh_token(self, token_hash: str) -> Any:
        return self.tokens.get(token_hash)

    def revoke_refresh_token(self, token_hash: str) -> None:
        record = self.tokens.get(token_hash)
        if record:
            record.is_revoked = True

    def revoke_all_user_tokens(self, user_id: int) -> None:
        for record in self.tokens.values():
            if record.user_id == user_id:
                record.is_revoked = True


_memory_repository: InMemoryAuthRepository | None = None


def create_auth_repository(db: Session | None = None) -> AuthRepository:
    """Фабрика для выбора реализации репозитория."""
    global _memory_repository
    if os.getenv("REPOSITORY_BACKEND", "sqlalchemy") == "memory":
        if _memory_repository is None:
            _memory_repository = InMemoryAuthRepository()
        return _memory_repository
    if db is None:
        raise ValueError("Для SQL-репозитория нужна сессия базы данных")
    return SqlAlchemyAuthRepository(db)
