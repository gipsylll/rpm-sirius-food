"""
Зависимости (Dependencies) для аутентификации и авторизации в FastAPI.

Реализует извлечение пользователя из JWT-токена и проверку ролей (RBAC).
"""

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.jwt import decode_token
from app.database import get_db
from app.modules.users.repository import create_user_repository

# Схема извлечения токена: в Swagger UI появляется удобное окно ввода "Value: <token>"
security = HTTPBearer(auto_error=False)


def get_current_user(
    auth: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> Any:
    """
    Извлекает и верифицирует текущего пользователя из JWT-токена.

    Возбуждает HTTPException 401 при невалидном токене или отсутствии пользователя.
    Возбуждает HTTPException 403, если пользователь заблокирован.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный токен аутентификации",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if auth is None or not auth.credentials:
        raise credentials_exception

    token = auth.credentials

    try:
        payload = decode_token(token)
        sub: str = payload.get("sub")
        token_type: str = payload.get("type")
        if sub is None or token_type != "access":
            raise credentials_exception
        user_id = int(sub)
    except (JWTError, ValueError, KeyError):
        raise credentials_exception

    repo = create_user_repository(db)
    user = repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
        )

    if getattr(user, "is_blocked", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь заблокирован",
        )

    return user


def require_role(*allowed_roles: str):
    """
    Фабрика FastAPI Dependency для ролевой модели доступа (RBAC).

    Возбуждает HTTPException 403, если роль пользователя не входит в список разрешенных.
    """

    def role_checker(current_user: Any = Depends(get_current_user)) -> Any:
        user_role = getattr(current_user, "role", None)
        # Обработка как ORM-связи Role(name="..."), так и строки/атрибута role_name
        role_name = getattr(user_role, "name", str(user_role) if user_role else "")

        if role_name not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        return current_user

    return role_checker
