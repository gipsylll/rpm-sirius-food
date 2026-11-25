"""
Транспортный слой меню.

Принимает HTTP-запрос, выполняет техническую валидацию,
проверяет права ролей (cook, admin) для модификации меню и переводит исключения в HTTP-статусы.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import require_role
from app.database import get_db
from app.exceptions import BusinessRuleError, NotFoundError
from app.modules.menu.repository import create_menu_repository
from app.modules.menu.service import MenuService
from app.schemas import MenuItemCreate, MenuItemUpdate

router = APIRouter()


@router.get("/items")
def get_menu_items(db: Session = Depends(get_db)):
    """Публичный эндпоинт получения меню. Обслуживается из кеша Redis (Cache-Aside)."""
    repository = create_menu_repository(db)
    service = MenuService(repository)
    return service.get_all_items()


@router.get("/items/{item_id}")
def get_menu_item(item_id: int, db: Session = Depends(get_db)):
    item = create_menu_repository(db).get_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Блюдо не найдено")
    return item


@router.get("/categories/{category_id}")
def get_menu_by_category(category_id: int, db: Session = Depends(get_db)):
    """Публичный эндпоинт получения блюд категории. Кешируется в Redis на 10 минут."""
    repository = create_menu_repository(db)
    service = MenuService(repository)
    return service.get_items_by_category(category_id)


@router.post("/items")
def create_menu_item(
    payload: MenuItemCreate,
    current_user: Any = Depends(require_role("cook", "admin")),
    db: Session = Depends(get_db),
):
    """Создание блюда. Доступно только поварам и администраторам."""
    if payload.price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Цена должна быть положительной",
        )

    if len(payload.name) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Название блюда слишком короткое",
        )

    repository = create_menu_repository(db)
    service = MenuService(repository)

    try:
        item_id = service.create_item(
            name=payload.name,
            price=payload.price,
            category_id=payload.category_id,
        )
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "item_id": item_id}


@router.patch("/items/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    current_user: Any = Depends(require_role("cook", "admin")),
    db: Session = Depends(get_db),
):
    """Обновление блюда. Доступно только поварам и администраторам."""
    repository = create_menu_repository(db)
    service = MenuService(repository)

    try:
        service.ensure_item_exists(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if payload.price is not None and payload.price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Цена должна быть положительной",
        )

    try:
        saved_id = service.update_item(
            item_id=item_id,
            name=payload.name,
            price=payload.price,
            is_available=payload.is_available,
            category_id=payload.category_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"status": "success", "item_id": saved_id}
