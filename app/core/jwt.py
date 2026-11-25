"""
Модуль генерации и валидации JWT (JSON Web Tokens).

Реализует выпуск короткоживущих access-токенов (15 минут)
и долгоживущих refresh-токенов (7 дней) по алгоритму HS256.
"""

import uuid
from datetime import UTC, datetime, timedelta

from jose import jwt

from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: int, role: str | None = None) -> str:
    """Создаёт короткоживущий access-токен (15 минут)."""
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
        "type": "access",
    }
    if role:
        payload["role"] = role
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    """Создаёт долгоживущий refresh-токен (7 дней) с уникальным идентификатором jti."""
    now = datetime.now(UTC)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
        "jti": uuid.uuid4().hex,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Декодирует и проверяет подпись токена. При ошибке возбуждает JWTError."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
