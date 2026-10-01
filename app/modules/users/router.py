"""
Транспортный слой пользователей.

Принимает HTTP-запрос, выполняет техническую валидацию
и переводит доменные исключения в HTTP-статусы.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.users.repository import create_user_repository
from app.modules.users.service import UserService
from app.schemas import UserCreate

router = APIRouter()


@router.post("/register")
def register_user(payload: UserCreate, db: Session = Depends(get_db)):
    # Формат email проверяет схема UserCreate (EmailStr).
    repository = create_user_repository(db)
    service = UserService(repository)

    # Уникальность email проверяется раньше формата телефона — как в MVP.
    try:
        service.ensure_email_available(payload.email)
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Техническая проверка номера телефона.
    if payload.phone and len(payload.phone) < 10:
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат номера телефона",
        )

    user_id, email = service.register(payload.email, payload.phone)
    return {
        "status": "success",
        "user_id": user_id,
        "email": email,
    }


@router.post("/{user_id}/topup")
def top_up_balance(user_id: int, amount: float, db: Session = Depends(get_db)):
    # Техническая проверка положительности суммы пополнения.
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Сумма пополнения должна быть положительной",
        )

    repository = create_user_repository(db)
    service = UserService(repository)

    try:
        new_balance = service.top_up(user_id, amount)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "new_balance": new_balance}
