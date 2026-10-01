"""
Инфраструктурный слой доставки.

Единственное место модуля, которое знает структуру SQL-таблиц
заказов, пользователей и доставок.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Delivery, Order, User


@dataclass
class UserRecord:
    id: int
    is_blocked: bool = False


@dataclass
class OrderRecord:
    id: int
    status: str


@dataclass
class DeliveryRecord:
    id: int
    order_id: int
    courier_id: int | None
    status: str


class DeliveryRepository(ABC):
    """Контракт хранилища доставок. Реализации взаимозаменяемы."""

    @abstractmethod
    def get_order(self, order_id: int):
        """Поиск заказа по идентификатору."""

    @abstractmethod
    def get_user(self, user_id: int):
        """Поиск курьера по идентификатору."""

    @abstractmethod
    def get_active_delivery(self, courier_id: int):
        """Активная доставка курьера, если она есть."""

    @abstractmethod
    def save_delivery(self, order_id: int, courier_id: int) -> int:
        """Создание доставки в статусе in_progress. Возвращает идентификатор."""

    @abstractmethod
    def get_delivery(self, delivery_id: int):
        """Поиск доставки по идентификатору."""

    @abstractmethod
    def mark_completed(self, delivery) -> None:
        """Завершение доставки и перевод связанного заказа в delivered."""


class SqlAlchemyDeliveryRepository(DeliveryRepository):
    """Реализация хранилища на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_order(self, order_id: int):
        return self.db.query(Order).filter(Order.id == order_id).first()

    def get_user(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).first()

    def get_active_delivery(self, courier_id: int):
        return (
            self.db.query(Delivery)
            .filter(
                Delivery.courier_id == courier_id,
                Delivery.status == "in_progress",
            )
            .first()
        )

    def save_delivery(self, order_id: int, courier_id: int) -> int:
        new_delivery = Delivery(
            order_id=order_id,
            courier_id=courier_id,
            status="in_progress",
        )
        self.db.add(new_delivery)
        self.db.commit()
        self.db.refresh(new_delivery)
        return new_delivery.id

    def get_delivery(self, delivery_id: int):
        return self.db.query(Delivery).filter(Delivery.id == delivery_id).first()

    def mark_completed(self, delivery) -> None:
        delivery.status = "completed"
        order = self.db.query(Order).filter(Order.id == delivery.order_id).first()
        if order:
            order.status = "delivered"
            self.db.add(order)
        self.db.add(delivery)
        self.db.commit()


class InMemoryDeliveryRepository(DeliveryRepository):
    """Реализация хранилища в памяти. Подходит для unit-тестов без СУБД."""

    def __init__(self) -> None:
        self.users: dict[int, UserRecord] = {}
        self.orders: dict[int, OrderRecord] = {}
        self.deliveries: dict[int, DeliveryRecord] = {}
        self._next_id = 1

    def get_order(self, order_id: int):
        return self.orders.get(order_id)

    def get_user(self, user_id: int):
        return self.users.get(user_id)

    def get_active_delivery(self, courier_id: int):
        for delivery in self.deliveries.values():
            if delivery.courier_id == courier_id and delivery.status == "in_progress":
                return delivery
        return None

    def save_delivery(self, order_id: int, courier_id: int) -> int:
        delivery_id = self._next_id
        self._next_id += 1
        self.deliveries[delivery_id] = DeliveryRecord(
            id=delivery_id,
            order_id=order_id,
            courier_id=courier_id,
            status="in_progress",
        )
        return delivery_id

    def get_delivery(self, delivery_id: int):
        return self.deliveries.get(delivery_id)

    def mark_completed(self, delivery) -> None:
        delivery.status = "completed"
        order = self.orders.get(delivery.order_id)
        if order:
            order.status = "delivered"


_memory_repository: InMemoryDeliveryRepository | None = None


def create_delivery_repository(db: Session | None = None) -> DeliveryRepository:
    """
    Точка подмены реализации.

    REPOSITORY_BACKEND=memory подключает общее in-memory-хранилище.
    Иначе используется PostgreSQL. service.py и router.py при этом не меняются.
    """
    global _memory_repository
    if os.getenv("REPOSITORY_BACKEND", "sqlalchemy") == "memory":
        if _memory_repository is None:
            _memory_repository = InMemoryDeliveryRepository()
        return _memory_repository
    if db is None:
        raise ValueError("Для SQL-репозитория нужна сессия базы данных")
    return SqlAlchemyDeliveryRepository(db)
