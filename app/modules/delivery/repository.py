"""
Инфраструктурный слой доставки.

Единственное место модуля, которое знает структуру SQL-таблиц
заказов, пользователей и доставок.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import Delivery, Order, User
from app.modules.orders.websocket import publish_order_update


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
    def track_delivery(self, delivery_id: int):
        """Потоковый трекинг смены статусов доставки."""

    @abstractmethod
    def mark_completed(self, delivery) -> None:
        """Завершение доставки и перевод связанного заказа в delivered."""

    @abstractmethod
    def update_status(self, delivery, status: str) -> None:
        """Сохранение промежуточного статуса доставки."""

    @abstractmethod
    def get_courier_deliveries(self, courier_id: int) -> list:
        """Список доставок конкретного курьера."""


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
                Delivery.status.in_(["in_progress", "assigned", "picked_up", "in_transit", "arrived"]),
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
        publish_order_update(order_id, "assigned", "assigned")
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
        publish_order_update(delivery.order_id, "delivered", "delivered")

    def update_status(self, delivery, status: str) -> None:
        delivery.status = status
        order = self.db.query(Order).filter(Order.id == delivery.order_id).first()
        if order:
            order.status = status
            self.db.add(order)
        self.db.add(delivery)
        self.db.commit()
        publish_order_update(delivery.order_id, status, status)

    def get_courier_deliveries(self, courier_id: int) -> list:
        return self.db.query(Delivery).filter(Delivery.courier_id == courier_id).all()

    def track_delivery(self, delivery_id: int):
        stages = [
            ("in_progress", "Курьер назначен на заказ"),
            ("picked_up", "Курьер забрал горячий заказ со столовой"),
            ("in_transit", "Курьер в пути к адресу доставки"),
            ("arrived", "Курьер прибыл к зданию"),
            ("delivered", "Заказ успешно вручен клиенту"),
        ]
        for status, desc in stages:
            yield {
                "delivery_id": delivery_id,
                "status": status,
                "description": desc,
                "timestamp": "2026-10-23T12:00:00Z",
            }


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
            if delivery.courier_id == courier_id and delivery.status in ("in_progress", "assigned", "picked_up", "in_transit", "arrived"):
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
        publish_order_update(order_id, "assigned", "assigned")
        return delivery_id

    def get_delivery(self, delivery_id: int):
        return self.deliveries.get(delivery_id)

    def mark_completed(self, delivery) -> None:
        delivery.status = "completed"
        order = self.orders.get(delivery.order_id)
        if order:
            order.status = "delivered"

    def get_courier_deliveries(self, courier_id: int) -> list:
        return [d for d in self.deliveries.values() if d.courier_id == courier_id]

    def update_status(self, delivery, status: str) -> None:
        delivery.status = status
        order = self.orders.get(delivery.order_id)
        if order:
            order.status = status
        publish_order_update(delivery.order_id, status, status)

    def track_delivery(self, delivery_id: int):
        stages = [
            ("in_progress", "Курьер назначен на заказ"),
            ("picked_up", "Курьер забрал горячий заказ со столовой"),
            ("in_transit", "Курьер в пути к адресу доставки"),
            ("arrived", "Курьер прибыл к зданию"),
            ("delivered", "Заказ успешно вручен клиенту"),
        ]
        for status, desc in stages:
            yield {
                "delivery_id": delivery_id,
                "status": status,
                "description": desc,
                "timestamp": "2026-10-23T12:00:00Z",
            }


class GrpcDeliveryRepository(DeliveryRepository):
    """
    Инфраструктурный адаптер к микросервису доставки по протоколу gRPC.
    Паттерн Strangler Fig: монолит делегирует операции сохранения и завершения
    доставки внешнему микросервису delivery_server.py.
    """

    def __init__(self, db: Session, client: Any | None = None):
        self.db = db
        if client is None:
            from app.modules.delivery.grpc_client import DeliveryGrpcClient

            self.client = DeliveryGrpcClient()
        else:
            self.client = client

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
        """Делегирует создание доставки gRPC микросервису."""
        response = self.client.assign_courier(order_id, courier_id)
        return response["delivery_id"]

    def get_delivery(self, delivery_id: int):
        return self.db.query(Delivery).filter(Delivery.id == delivery_id).first()

    def mark_completed(self, delivery) -> None:
        """Делегирует завершение доставки gRPC микросервису."""
        self.client.complete_delivery(delivery.id)

    def update_status(self, delivery, status: str) -> None:
        # The gRPC adapter may be upgraded independently; keep the local read model
        # in sync and publish the cross-replica event here.
        delivery.status = status
        order = self.db.query(Order).filter(Order.id == delivery.order_id).first()
        if order:
            order.status = status
        self.db.commit()
        publish_order_update(delivery.order_id, status, status)

    def get_courier_deliveries(self, courier_id: int) -> list:
        return self.db.query(Delivery).filter(Delivery.courier_id == courier_id).all()

    def track_delivery(self, delivery_id: int):
        """Делегирует Server Streaming микросервису gRPC."""
        return self.client.track_delivery(delivery_id)


_memory_repository: InMemoryDeliveryRepository | None = None


def create_delivery_repository(db: Session | None = None) -> DeliveryRepository:
    """
    Точка подмены реализации.

    REPOSITORY_BACKEND=memory подключает общее in-memory-хранилище.
    REPOSITORY_BACKEND=grpc подключает gRPC-клиент (паттерн Strangler Fig).
    Иначе используется PostgreSQL (SqlAlchemy).
    """
    global _memory_repository
    backend = os.getenv("REPOSITORY_BACKEND", "sqlalchemy")
    if backend == "memory":
        if _memory_repository is None:
            _memory_repository = InMemoryDeliveryRepository()
        return _memory_repository
    if db is None:
        raise ValueError("Для репозитория нужна сессия базы данных")
    if backend == "grpc":
        return GrpcDeliveryRepository(db)
    return SqlAlchemyDeliveryRepository(db)
