"""
Транспортный слой меню.

Принимает HTTP-запрос, выполняет техническую валидацию
и переводит доменные исключения в HTTP-статусы.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import BusinessRuleError, NotFoundError
from app.modules.menu.repository import create_menu_repository
from app.modules.menu.service import MenuService
from app.schemas import MenuItemCreate, MenuItemUpdate

router = APIRouter()


@router.post("/items")
def create_menu_item(payload: MenuItemCreate, db: Session = Depends(get_db)):
    # Техническая валидация цены и названия.
    if payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    if len(payload.name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Название блюда слишком короткое",
        )

    repository = create_menu_repository(db)
    service = MenuService(repository)

    try:
        item_id = service.create_item(payload.name, payload.price)
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "item_id": item_id}


@router.patch("/items/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    db: Session = Depends(get_db),
):
    repository = create_menu_repository(db)
    service = MenuService(repository)

    # Сначала существование блюда, затем формат новой цены — как в MVP.
    try:
        service.ensure_item_exists(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.price is not None and payload.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    try:
        saved_id = service.update_item(
            item_id,
            payload.name,
            payload.price,
            payload.is_available,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"status": "success", "item_id": saved_id}
