"""
Транспортный слой заказов.

Принимает HTTP-запрос, выполняет аутентификацию/авторизацию через Depends,
техническую валидацию и переводит доменные исключения в HTTP-статусы.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.database import get_db
from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.orders.repository import create_order_repository
from app.modules.orders.service import OrderService
from app.schemas import OrderCreate

router = APIRouter()


@router.post("/create")
def create_order(
    payload: OrderCreate,
    current_user: Any = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Создание заказа. Идентификатор пользователя извлекается из проверенного JWT токена,
    исключая возможность создания заказа от чужого имени.
    """
    if payload.quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Количество должно быть больше нуля",
        )

    repository = create_order_repository(db)
    service = OrderService(repository)

    try:
        order_id = service.create_order(
            user_id=current_user.id,
            item_id=payload.item_id,
            quantity=payload.quantity,
            promo_code=payload.promo_code,
            loyalty_points=payload.loyalty_points,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "order_id": order_id}


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    current_user: Any = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Отмена заказа с проверкой прав доступа (защита от IDOR).
    Студент не может отменить заказ другого студента.
    """
    repository = create_order_repository(db)
    service = OrderService(repository)

    try:
        service.cancel_order(order_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "message": "Заказ успешно отменён"}


@router.get("/kitchen")
def get_kitchen_orders(
    current_user: Any = Depends(require_role("cook", "admin")),
    db: Session = Depends(get_db),
):
    """
    Просмотр заказов для кухни. Доступно только ролям cook и admin.
    Студент при попытке обращения получит 403 Forbidden.
    """
    repository = create_order_repository(db)
    service = OrderService(repository)
    return service.get_kitchen_orders()
