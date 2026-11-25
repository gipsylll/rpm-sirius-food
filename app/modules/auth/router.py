"""
Транспортный слой аутентификации.

Обрабатывает HTTP-запросы аутентификации, обновления и отзыва токенов.
Переводит доменные исключения безопасности в соответствующие HTTP-статусы (401, 403).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.rate_limit import rate_limit
from app.database import get_db
from app.exceptions import ForbiddenError
from app.modules.auth.repository import create_auth_repository
from app.modules.auth.service import (
    AuthService,
    InvalidCredentialsError,
    SecurityViolationError,
    TokenRevokedError,
)
from app.schemas import LoginSchema, RefreshTokenRequest, TokenResponse

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit(max_requests=5, window=60))],
)
def login(payload: LoginSchema, db: Session = Depends(get_db)):
    """Аутентификация пользователя и выдача пары токенов с защитой от брутфорса."""
    repo = create_auth_repository(db)
    service = AuthService(repo)

    try:
        return service.login(payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Обновление пары токенов по стратегии Refresh Token Rotation."""
    repo = create_auth_repository(db)
    service = AuthService(repo)

    try:
        return service.refresh(payload.refresh_token)
    except SecurityViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except (TokenRevokedError, ForbiddenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.post("/logout")
def logout(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Отзыв refresh-токена текущей сессии."""
    repo = create_auth_repository(db)
    service = AuthService(repo)
    service.logout(payload.refresh_token)
    return {"status": "success", "message": "Сессия успешно завершена"}
