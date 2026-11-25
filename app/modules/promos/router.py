"""Administrative promo-code endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import require_role
from app.database import get_db
from app.models import PromoCode
from app.modules.orders.repository import create_order_repository
from app.schemas import PromoCodeCreate, PromoCodeResponse

router = APIRouter()


@router.post("", response_model=PromoCodeResponse, status_code=201)
def create_promo(
    payload: PromoCodeCreate,
    current_user: Any = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if payload.discount_type not in ("percent", "fixed"):
        raise HTTPException(400, "discount_type должен быть percent или fixed")
    if payload.discount_type == "percent" and payload.discount_value > 100:
        raise HTTPException(400, "Процент скидки не может превышать 100")
    if (
        payload.valid_until
        and payload.valid_from
        and payload.valid_until <= payload.valid_from
    ):
        raise HTTPException(400, "Некорректный период действия")
    repo = create_order_repository(db)
    if repo.get_promo_code(payload.code.strip().upper()):
        raise HTTPException(409, "Промокод уже существует")
    promo = PromoCode(
        code=payload.code.strip().upper(),
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        max_uses=payload.max_uses,
        min_order_amount=payload.min_order_amount,
        current_uses=0,
        is_active=True,
    )
    return repo.save_promo(promo)


@router.get("", response_model=list[PromoCodeResponse])
def list_promos(
    current_user: Any = Depends(require_role("admin")), db: Session = Depends(get_db)
):
    return create_order_repository(db).list_promos()


@router.delete("/{promo_id}")
def deactivate_promo(
    promo_id: int,
    current_user: Any = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not create_order_repository(db).deactivate_promo(promo_id):
        raise HTTPException(404, "Промокод не найден")
    return {"status": "success", "message": "Промокод деактивирован"}
