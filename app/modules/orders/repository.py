"""
Инфраструктурный слой заказов.

Единственное место модуля, которое знает структуру SQL-таблиц.
Бизнес-правила здесь отсутствуют.
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.observability import correlation_id, log
from app.core.tracing import get_trace_headers
from app.events.contracts import build_order_paid
from app.models import (
    LoyaltyAccount,
    LoyaltyTransaction,
    MenuItem,
    Order,
    OutboxEvent,
    PromoCode,
    PromoCodeUsage,
    User,
)
from app.modules.orders.websocket import publish_order_update


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
class PromoCodeRecord:
    id: int
    code: str
    discount_type: str
    discount_value: Decimal
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_uses: int | None = None
    current_uses: int = 0
    min_order_amount: Decimal = Decimal(0)
    is_active: bool = True


@dataclass
class LoyaltyAccountRecord:
    user_id: int
    balance: int = 0
    total_earned: int = 0
    level: str = "Bronze"


@dataclass
class OrderRecord:
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str = "processing"
    original_amount: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    loyalty_points_spent: int = 0
    final_amount: Decimal = Decimal(0)
    promo_code: str | None = None

    @property
    def customer_id(self) -> int:
        return self.user_id


class OrderRepository(ABC):
    """Контракт хранилища заказов. Реализации взаимозаменяемы."""

    @abstractmethod
    def get_order(self, order_id: int):
        """Извлечение заказа по идентификатору."""

    @abstractmethod
    def get_user_by_id(self, user_id: int):
        """Извлечение пользователя по идентификатору."""

    @abstractmethod
    def get_menu_item_by_id(self, item_id: int):
        """Извлечение блюда из меню по идентификатору."""

    @abstractmethod
    def save_order(self, user_id: int, item_id: int, quantity: int, **financial) -> int:
        """Создание заказа. Возвращает идентификатор."""

    @abstractmethod
    def update_user_balance(self, user, new_balance: float) -> None:
        """Изменение баланса пользователя с фиксацией изменения."""

    @abstractmethod
    def cancel_order(self, order) -> None:
        """Фиксация отмены заказа."""

    @abstractmethod
    def get_kitchen_orders(self) -> list:
        """Получение списка заказов для кухни."""

    @abstractmethod
    def get_promo_code(self, code: str, for_update: bool = False):
        """Получение промокода с опциональной блокировкой."""

    @abstractmethod
    def has_promo_usage(self, user_id: int, promo_id: int) -> bool:
        """Проверяет одноразовое применение кода пользователем."""

    @abstractmethod
    def get_loyalty_account(self, user_id: int, for_update: bool = False):
        """Получение счёта баллов."""

    @abstractmethod
    def spend_loyalty(self, account, points: int, order_id: int | None = None) -> None:
        """Списывает баллы и записывает ledger."""

    @abstractmethod
    def record_promo_usage(self, promo, user_id: int, order_id: int, discount) -> None:
        """Фиксирует применение промокода."""

    @abstractmethod
    def save_promo(self, promo):
        """Создание промокода."""

    @abstractmethod
    def list_promos(self) -> list:
        """Список промокодов."""

    @abstractmethod
    def deactivate_promo(self, promo_id: int) -> bool:
        """Деактивация промокода."""

    @abstractmethod
    def commit(self) -> None:
        """Фиксация заказа и его финансовых операций одной транзакцией."""


class SqlAlchemyOrderRepository(OrderRepository):
    """Реализация хранилища на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_order(self, order_id: int):
        return self.db.query(Order).filter(Order.id == order_id).first()

    def get_user_by_id(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).with_for_update().first()

    def get_menu_item_by_id(self, item_id: int):
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()

    def save_order(self, user_id: int, item_id: int, quantity: int, **financial) -> int:
        defer_commit = financial.pop("defer_commit", False)
        new_order = Order(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
            original_amount=financial.get("original_amount", 0),
            discount_amount=financial.get("discount_amount", 0),
            loyalty_points_spent=financial.get("loyalty_points", 0),
            final_amount=financial.get(
                "final_amount", financial.get("original_amount", 0)
            ),
            promo_code=financial.get("promo_code"),
        )
        self.db.add(new_order)
        self.db.flush()
        event_id = str(uuid4())
        item = self.get_menu_item_by_id(item_id)
        payload = build_order_paid(
            event_id,
            new_order.id,
            user_id,
            item_id,
            quantity,
            financial.get("final_amount", item.price * quantity),
            discount=financial.get("discount_amount", 0),
            promo_code=financial.get("promo_code"),
            loyalty_points=financial.get("loyalty_points", 0),
        )
        self.db.add(
            OutboxEvent(
                id=event_id,
                routing_key="order.paid",
                payload=json.dumps(payload),
                correlation_id=correlation_id.get() or event_id,
                published=False,
                trace_context=json.dumps(get_trace_headers()),
            )
        )
        if not defer_commit:
            self.db.commit()
        log("order_created", order_id=new_order.id, event_id=event_id)
        return new_order.id

    def commit(self) -> None:
        self.db.commit()

    def update_user_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance
        self.db.add(user)

    def cancel_order(self, order) -> None:
        order.status = "cancelled"
        self.db.add(order)
        event_id = str(uuid4())
        self.db.add(
            OutboxEvent(
                id=event_id,
                routing_key="order.cancelled",
                payload=json.dumps(
                    {
                        "event_id": event_id,
                        "order_id": order.id,
                        "user_id": order.user_id,
                        "promo_code": order.promo_code,
                        "loyalty_points": order.loyalty_points_spent or 0,
                        "final_amount": float(order.final_amount or 0),
                    }
                ),
                correlation_id=correlation_id.get() or event_id,
                published=False,
                trace_context=json.dumps(get_trace_headers()),
            )
        )
        self.db.commit()
        publish_order_update(order.id, "cancelled", "cancelled")

    def get_kitchen_orders(self) -> list:
        return (
            self.db.query(Order).filter(Order.status.in_(["processing", "paid"])).all()
        )

    def get_promo_code(self, code: str, for_update: bool = False):
        query = self.db.query(PromoCode).filter(PromoCode.code == code.upper())
        return (query.with_for_update() if for_update else query).first()

    def has_promo_usage(self, user_id: int, promo_id: int) -> bool:
        return (
            self.db.query(PromoCodeUsage)
            .filter_by(user_id=user_id, promo_code_id=promo_id)
            .first()
            is not None
        )

    def get_loyalty_account(self, user_id: int, for_update: bool = False):
        query = self.db.query(LoyaltyAccount).filter_by(user_id=user_id)
        account = (query.with_for_update() if for_update else query).first()
        if account is None:
            account = LoyaltyAccount(
                user_id=user_id, balance=0, total_earned=0, level="Bronze"
            )
            self.db.add(account)
            self.db.flush()
        return account

    def spend_loyalty(self, account, points: int, order_id: int | None = None) -> None:
        if points:
            account.balance -= points
            self.db.add(
                LoyaltyTransaction(
                    user_id=account.user_id,
                    amount=-points,
                    transaction_type="spend",
                    order_id=order_id,
                    idempotency_key=f"spend_order_{order_id}"
                    if order_id
                    else f"spend_{account.user_id}_{datetime.now(UTC).timestamp()}",
                )
            )

    def record_promo_usage(self, promo, user_id: int, order_id: int, discount) -> None:
        promo.current_uses += 1
        self.db.add(
            PromoCodeUsage(
                user_id=user_id,
                promo_code_id=promo.id,
                order_id=order_id,
                discount_amount=discount,
            )
        )

    def save_promo(self, promo):
        self.db.add(promo)
        self.db.commit()
        self.db.refresh(promo)
        return promo

    def list_promos(self) -> list:
        return self.db.query(PromoCode).order_by(PromoCode.id.desc()).all()

    def deactivate_promo(self, promo_id: int) -> bool:
        promo = self.db.get(PromoCode, promo_id)
        if promo is None:
            return False
        promo.is_active = False
        self.db.commit()
        return True


class InMemoryOrderRepository(OrderRepository):
    """Реализация хранилища в памяти. Подходит для unit-тестов без СУБД."""

    def __init__(self) -> None:
        self.users: dict[int, UserRecord] = {}
        self.items: dict[int, MenuItemRecord] = {}
        self.orders: dict[int, OrderRecord] = {}
        self._next_order_id = 1
        self.promos: dict[int, PromoCodeRecord] = {}
        self.promo_usages: dict[int, tuple] = {}
        self.loyalty: dict[int, LoyaltyAccountRecord] = {}
        self._next_promo_id = 1

    def get_order(self, order_id: int):
        return self.orders.get(order_id)

    def get_user_by_id(self, user_id: int):
        return self.users.get(user_id)

    def get_menu_item_by_id(self, item_id: int):
        return self.items.get(item_id)

    def save_order(self, user_id: int, item_id: int, quantity: int, **financial) -> int:
        order_id = self._next_order_id
        self._next_order_id += 1
        self.orders[order_id] = OrderRecord(
            id=order_id,
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
            original_amount=financial.get("original_amount", 0),
            discount_amount=financial.get("discount_amount", 0),
            loyalty_points_spent=financial.get("loyalty_points", 0),
            final_amount=financial.get(
                "final_amount", financial.get("original_amount", 0)
            ),
            promo_code=financial.get("promo_code"),
        )
        return order_id

    def update_user_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance

    def cancel_order(self, order) -> None:
        order.status = "cancelled"
        self.cancelled_events = getattr(self, "cancelled_events", [])
        self.cancelled_events.append(
            {
                "order_id": order.id,
                "user_id": order.user_id,
                "promo_code": order.promo_code,
                "loyalty_points": order.loyalty_points_spent,
            }
        )

    def get_kitchen_orders(self) -> list:
        return [o for o in self.orders.values() if o.status in ("processing", "paid")]

    def get_promo_code(self, code: str, for_update: bool = False):
        return next((p for p in self.promos.values() if p.code == code.upper()), None)

    def has_promo_usage(self, user_id: int, promo_id: int) -> bool:
        return any(
            u[0] == user_id and u[1] == promo_id for u in self.promo_usages.values()
        )

    def get_loyalty_account(self, user_id: int, for_update: bool = False):
        self.loyalty.setdefault(user_id, LoyaltyAccountRecord(user_id=user_id))
        return self.loyalty[user_id]

    def spend_loyalty(self, account, points: int, order_id: int | None = None) -> None:
        account.balance -= points

    def record_promo_usage(self, promo, user_id: int, order_id: int, discount) -> None:
        promo.current_uses += 1
        self.promo_usages[order_id] = (user_id, promo.id, discount)

    def save_promo(self, promo):
        if getattr(promo, "id", None) in (None, 0):
            promo.id = self._next_promo_id
            self._next_promo_id += 1
        self.promos[promo.id] = promo
        return promo

    def list_promos(self) -> list:
        return list(self.promos.values())

    def deactivate_promo(self, promo_id: int) -> bool:
        promo = self.promos.get(promo_id)
        if promo is None:
            return False
        promo.is_active = False
        return True

    def commit(self) -> None:
        return None


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
