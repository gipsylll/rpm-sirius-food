"""
Определение ORM-моделей предметной области «Сириус.Еда».
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Role(Base):
    """Роль пользователя: student, cook, courier, admin."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)


class User(Base):
    """Пользователь системы."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    balance = Column(Numeric(12, 2), default=0)
    is_blocked = Column(Boolean, default=False)
    password_hash = Column(String, nullable=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)

    role = relationship("Role")


class RefreshToken(Base):
    """Refresh-токен для обновления access-токена (хранит хеш)."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False)

    user = relationship("User")


class MenuItem(Base):
    """Позиция меню."""

    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Numeric(12, 2), nullable=False)
    is_available = Column(Boolean, default=True)
    category_id = Column(Integer, nullable=True, default=1)


class Order(Base):
    """Заказ пользователя."""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    item_id = Column(Integer, ForeignKey("menu_items.id"))
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="processing")
    original_amount = Column(Numeric(12, 2), nullable=False, default=0)
    discount_amount = Column(Numeric(12, 2), nullable=False, default=0)
    loyalty_points_spent = Column(Integer, nullable=False, default=0)
    final_amount = Column(Numeric(12, 2), nullable=False, default=0)
    promo_code = Column(String(64), nullable=True)

    user = relationship("User")
    item = relationship("MenuItem")


class Delivery(Base):
    """Доставка заказа."""

    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    courier_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")

    order = relationship("Order")
    courier = relationship("User")


class OutboxEvent(Base):
    """Событие записывается в той же транзакции, что и заказ."""

    __tablename__ = "outbox_events"
    id = Column(String(36), primary_key=True)
    routing_key = Column(String(80), nullable=False)
    payload = Column(String, nullable=False)
    correlation_id = Column(String(128), nullable=False)
    published = Column(Boolean, nullable=False, default=False)
    trace_context = Column(String, nullable=True)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    consumer = Column(String(40), primary_key=True)
    event_id = Column(String(36), primary_key=True)


class KitchenOrder(Base):
    __tablename__ = "kitchen_orders"
    order_id = Column(Integer, ForeignKey("orders.id"), primary_key=True)
    status = Column(String(32), nullable=False, default="received")


class OrderCompensation(Base):
    """One refund per order, including repeated or distinct failure events."""

    __tablename__ = "order_compensations"
    order_id = Column(Integer, ForeignKey("orders.id"), primary_key=True)
    amount = Column(Numeric(12, 2), nullable=False)


class PromoCode(Base):
    """Discount code with a bounded validity window and usage limit."""

    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    discount_type = Column(String(16), nullable=False)  # percent | fixed
    discount_value = Column(Numeric(12, 2), nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    max_uses = Column(Integer, nullable=True)
    current_uses = Column(Integer, nullable=False, default=0)
    min_order_amount = Column(Numeric(12, 2), nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromoCodeUsage(Base):
    """A user's application of a code. Unique constraints make retries safe."""

    __tablename__ = "promo_code_usages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    discount_amount = Column(Numeric(12, 2), nullable=False)
    compensation_key = Column(String(128), nullable=True, unique=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("user_id", "promo_code_id", name="uq_promo_user_code"),
        UniqueConstraint("order_id", name="uq_promo_order"),
        Index("ix_promo_usage_user", "user_id"),
    )


class PromoCompensation(Base):
    """Idempotency record for restoring a promo after cancellation."""

    __tablename__ = "promo_compensations"

    id = Column(Integer, primary_key=True, index=True)
    compensation_key = Column(String(128), unique=True, nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    restored = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LoyaltyAccount(Base):
    """Points account and tier progression for a user."""

    __tablename__ = "loyalty_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Integer, nullable=False, default=0)
    total_earned = Column(Integer, nullable=False, default=0)
    level = Column(String(16), nullable=False, default="Bronze")
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LoyaltyTransaction(Base):
    """Append-only points ledger with an idempotency key."""

    __tablename__ = "loyalty_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    transaction_type = Column(String(16), nullable=False)  # earn/spend/refund/revoke
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    idempotency_key = Column(String(160), unique=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (Index("ix_loyalty_tx_user", "user_id"),)
