"""
Инфраструктурный слой заказов.

Единственное место модуля, которое знает структуру SQL-таблиц.
Бизнес-правила здесь отсутствуют.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import MenuItem, Order, User


@dataclass
class UserRecord:
    id: int
    email: str
    phone: str | None
    balance: float
    is_blocked: bool = False


@dataclass
class MenuItemRecord:
    id: int
    name: str
    price: float
    is_available: bool = True


@dataclass
class OrderRecord:
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str = "processing"


class OrderRepository(ABC):
    """Контракт хранилища заказов. Реализации взаимозаменяемы."""

    @abstractmethod
    def get_user_by_id(self, user_id: int):
        """Извлечение пользователя по идентификатору."""

    @abstractmethod
    def get_menu_item_by_id(self, item_id: int):
        """Извлечение блюда из меню по идентификатору."""

    @abstractmethod
    def save_order(self, user_id: int, item_id: int, quantity: int) -> int:
        """Создание заказа. Возвращает идентификатор."""

    @abstractmethod
    def update_user_balance(self, user, new_balance: float) -> None:
        """Изменение баланса пользователя с фиксацией изменения."""


class SqlAlchemyOrderRepository(OrderRepository):
    """Реализация хранилища на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).first()

    def get_menu_item_by_id(self, item_id: int):
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()

    def save_order(self, user_id: int, item_id: int, quantity: int) -> int:
        new_order = Order(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
        )
        self.db.add(new_order)
        self.db.commit()
        self.db.refresh(new_order)
        return new_order.id

    def update_user_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance
        self.db.add(user)
        self.db.commit()


class InMemoryOrderRepository(OrderRepository):
    """Реализация хранилища в памяти. Подходит для unit-тестов без СУБД."""

    def __init__(self) -> None:
        self.users: dict[int, UserRecord] = {}
        self.items: dict[int, MenuItemRecord] = {}
        self.orders: dict[int, OrderRecord] = {}
        self._next_order_id = 1

    def get_user_by_id(self, user_id: int):
        return self.users.get(user_id)

    def get_menu_item_by_id(self, item_id: int):
        return self.items.get(item_id)

    def save_order(self, user_id: int, item_id: int, quantity: int) -> int:
        order_id = self._next_order_id
        self._next_order_id += 1
        self.orders[order_id] = OrderRecord(
            id=order_id,
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
        )
        return order_id

    def update_user_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance


_memory_repository: InMemoryOrderRepository | None = None


def create_order_repository(db: Session | None = None) -> OrderRepository:
    """
    Точка подмены реализации.

    REPOSITORY_BACKEND=memory подключает общее in-memory-хранилище.
    Иначе используется PostgreSQL. service.py и router.py при этом не меняются.
    """
    global _memory_repository
    if os.getenv("REPOSITORY_BACKEND", "sqlalchemy") == "memory":
        if _memory_repository is None:
            _memory_repository = InMemoryOrderRepository()
        return _memory_repository
    if db is None:
        raise ValueError("Для SQL-репозитория нужна сессия базы данных")
    return SqlAlchemyOrderRepository(db)
