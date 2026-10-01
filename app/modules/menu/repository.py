"""
Инфраструктурный слой меню.

Единственное место модуля, которое знает структуру SQL-таблицы menu_items.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import MenuItem


@dataclass
class MenuItemRecord:
    id: int
    name: str
    price: float
    is_available: bool = True


class MenuRepository(ABC):
    """Контракт хранилища меню. Реализации взаимозаменяемы."""

    @abstractmethod
    def get_by_name(self, name: str):
        """Поиск блюда по названию."""

    @abstractmethod
    def get_by_id(self, item_id: int):
        """Поиск блюда по идентификатору."""

    @abstractmethod
    def save_item(self, name: str, price: float) -> int:
        """Создание блюда. Возвращает идентификатор."""

    @abstractmethod
    def save_changes(self, item) -> int:
        """Фиксация изменённого блюда. Возвращает идентификатор."""


class SqlAlchemyMenuRepository(MenuRepository):
    """Реализация хранилища на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, name: str):
        return self.db.query(MenuItem).filter(MenuItem.name == name).first()

    def get_by_id(self, item_id: int):
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()

    def save_item(self, name: str, price: float) -> int:
        new_item = MenuItem(
            name=name,
            price=price,
            is_available=True,
        )
        self.db.add(new_item)
        self.db.commit()
        self.db.refresh(new_item)
        return new_item.id

    def save_changes(self, item) -> int:
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item.id


class InMemoryMenuRepository(MenuRepository):
    """Реализация хранилища в памяти. Подходит для unit-тестов без СУБД."""

    def __init__(self) -> None:
        self.items: dict[int, MenuItemRecord] = {}
        self._next_id = 1

    def get_by_name(self, name: str):
        for item in self.items.values():
            if item.name == name:
                return item
        return None

    def get_by_id(self, item_id: int):
        return self.items.get(item_id)

    def save_item(self, name: str, price: float) -> int:
        item_id = self._next_id
        self._next_id += 1
        self.items[item_id] = MenuItemRecord(
            id=item_id,
            name=name,
            price=price,
            is_available=True,
        )
        return item_id

    def save_changes(self, item) -> int:
        return item.id


_memory_repository: InMemoryMenuRepository | None = None


def create_menu_repository(db: Session | None = None) -> MenuRepository:
    """
    Точка подмены реализации.

    REPOSITORY_BACKEND=memory подключает общее in-memory-хранилище.
    Иначе используется PostgreSQL. service.py и router.py при этом не меняются.
    """
    global _memory_repository
    if os.getenv("REPOSITORY_BACKEND", "sqlalchemy") == "memory":
        if _memory_repository is None:
            _memory_repository = InMemoryMenuRepository()
        return _memory_repository
    if db is None:
        raise ValueError("Для SQL-репозитория нужна сессия базы данных")
    return SqlAlchemyMenuRepository(db)
