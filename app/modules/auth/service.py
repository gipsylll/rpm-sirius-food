"""
Слой бизнес-логики аутентификации.

Не зависит от веб-фреймворка (FastAPI) и механизмов СУБД (SQLAlchemy).
Реализует сценарии логина, безопасной ротации токенов (Refresh Token Rotation)
и экстренного сброса всех сессий при выявлении попытки повторного использования токена.
"""

import hashlib
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.jwt import create_access_token, create_refresh_token, decode_token
from app.core.security import verify_password
from app.exceptions import DomainError, ForbiddenError
from app.modules.auth.repository import AuthRepository


class InvalidCredentialsError(DomainError):
    """Неверный email или пароль."""


class TokenRevokedError(DomainError):
    """Токен отозван или недействителен."""


class SecurityViolationError(DomainError):
    """Обнаружена компрометация сессии: повторное использование отозванного токена."""


class AuthService:
    """Сервис аутентификации."""

    def __init__(self, repository: AuthRepository):
        self.repository = repository

    def _hash_token(self, token_str: str) -> str:
        """Детерминированный криптографический хеш токена для поиска в БД."""
        return hashlib.sha256(token_str.encode("utf-8")).hexdigest()

    def login(self, email: str, password: str) -> dict:
        """
        Проверяет учётные данные и выдаёт пару токенов (access + refresh).
        """
        user = self.repository.get_user_by_email(email)
        if not user:
            raise InvalidCredentialsError("Неверный email или пароль")

        password_hash = getattr(user, "password_hash", None)
        if not password_hash or not verify_password(password, password_hash):
            raise InvalidCredentialsError("Неверный email или пароль")

        if getattr(user, "is_blocked", False):
            raise ForbiddenError("Пользователь заблокирован")

        user_role = getattr(user, "role", None)
        role_name = getattr(
            user_role, "name", str(user_role) if user_role else "student"
        )

        access_token = create_access_token(user.id, role=role_name)
        refresh_token = create_refresh_token(user.id)

        token_hash = self._hash_token(refresh_token)
        expires_at = datetime.now(UTC) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        self.repository.save_refresh_token(user.id, token_hash, expires_at)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    def refresh(self, refresh_token_str: str) -> dict:
        """
        Обновление пары токенов по стратегии Refresh Token Rotation (10 баллов).

        Если токен уже был отозван (is_revoked = True), фиксируется компрометация:
        все активные сессии пользователя сбрасываются.
        """
        try:
            payload = decode_token(refresh_token_str)
        except Exception as exc:
            raise TokenRevokedError("Невалидный или истекший refresh-токен") from exc

        if payload.get("type") != "refresh":
            raise TokenRevokedError("Токен не является refresh-токеном")

        token_hash = self._hash_token(refresh_token_str)
        record = self.repository.get_refresh_token(token_hash)
        if not record:
            raise TokenRevokedError("Refresh-токен не найден")

        # Проверка повторного использования (Token Reuse Detection)
        if getattr(record, "is_revoked", False):
            # АТАКА: злоумышленник пытается повторно использовать старый токен!
            # Сбрасываем ВСЕ сессии пользователя
            self.repository.revoke_all_user_tokens(record.user_id)
            raise SecurityViolationError(
                "Обнаружена попытка повторного использования токена! Все сессии сброшены."
            )

        # Инвалидируем использованный refresh-токен
        self.repository.revoke_refresh_token(token_hash)

        # Выдаем новую пару токенов
        user = self.repository.get_user_by_id(record.user_id)
        if not user or getattr(user, "is_blocked", False):
            raise ForbiddenError("Пользователь не найден или заблокирован")

        user_role = getattr(user, "role", None)
        role_name = getattr(
            user_role, "name", str(user_role) if user_role else "student"
        )

        new_access = create_access_token(user.id, role=role_name)
        new_refresh = create_refresh_token(user.id)
        new_token_hash = self._hash_token(new_refresh)
        new_expires = datetime.now(UTC) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        self.repository.save_refresh_token(user.id, new_token_hash, new_expires)

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
        }

    def logout(self, refresh_token_str: str) -> None:
        """Отзывает refresh-токен текущей сессии."""
        token_hash = self._hash_token(refresh_token_str)
        self.repository.revoke_refresh_token(token_hash)
