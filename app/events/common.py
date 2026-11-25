"""Shared RabbitMQ declarations and event transaction logic."""

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from aio_pika import ExchangeType

from app.core.observability import correlation_id
from app.core.tracing import (
    get_trace_headers,
)
from app.database import SessionLocal
from app.events.contracts import OrderPaid
from app.models import (
    Delivery,
    KitchenOrder,
    LoyaltyAccount,
    LoyaltyTransaction,
    Order,
    OrderCompensation,
    OutboxEvent,
    ProcessedEvent,
    PromoCode,
    PromoCodeUsage,
    PromoCompensation,
    Role,
    User,
)

URL = os.getenv("RABBITMQ_URL", "amqp://sirius:sirius@localhost:5672//")
EVENT_EXCHANGE = "sirius_events"
DEAD_EXCHANGE = "sirius_dead"


@dataclass(frozen=True)
class QueueSpec:
    name: str
    routing_key: str
    dead_letter_key: str | None = None


queues = [
    QueueSpec("kitchen_queue", "order.paid", "kitchen"),
    QueueSpec("delivery_queue", "order.paid", "delivery"),
    QueueSpec("loyalty_queue", "order.paid"),
    QueueSpec("compensation_queue", "delivery.failed", "compensation"),
    QueueSpec("cancelled_audit_queue", "order.cancelled"),
    QueueSpec("cancellation_queue", "order.cancelled"),
]
dead_queues = [
    QueueSpec(f"{name}_dlq", name) for name in ("kitchen", "delivery", "compensation")
]


async def setup(channel):
    events = await channel.declare_exchange(
        EVENT_EXCHANGE, ExchangeType.TOPIC, durable=True
    )
    dead = await channel.declare_exchange(
        DEAD_EXCHANGE, ExchangeType.DIRECT, durable=True
    )
    declared = {}
    for spec in queues:
        arguments = {}
        if spec.dead_letter_key:
            arguments = {
                "x-dead-letter-exchange": DEAD_EXCHANGE,
                "x-dead-letter-routing-key": spec.dead_letter_key,
            }
        queue = await channel.declare_queue(
            spec.name, durable=True, arguments=arguments
        )
        await queue.bind(events, routing_key=spec.routing_key)
        declared[spec.name] = queue
    for spec in dead_queues:
        queue = await channel.declare_queue(spec.name, durable=True)
        await queue.bind(dead, routing_key=spec.routing_key)
        declared[spec.name] = queue
    return events, declared


def add_event(db, routing_key, payload):
    event_id = str(uuid4())
    db.add(
        OutboxEvent(
            id=event_id,
            routing_key=routing_key,
            payload=json.dumps({"event_id": event_id, **payload}),
            correlation_id=correlation_id.get() or event_id,
            trace_context=json.dumps(get_trace_headers()),
            published=False,
        )
    )


def process(name, data):
    if name in ("kitchen", "delivery", "loyalty"):
        data = OrderPaid.model_validate(data).model_dump()
    event_id = data["event_id"]
    order_id = int(data["order_id"])
    with SessionLocal.begin() as db:
        if db.get(ProcessedEvent, (name, event_id)):
            return False
        order = db.query(Order).filter_by(id=order_id).with_for_update().first()
        if not order:
            raise ValueError("Order does not exist")
        db.add(ProcessedEvent(consumer=name, event_id=event_id))
        if name == "loyalty":
            account = (
                db.query(LoyaltyAccount)
                .filter_by(user_id=order.user_id)
                .with_for_update()
                .first()
            )
            if account is None:
                account = LoyaltyAccount(
                    user_id=order.user_id, balance=0, total_earned=0, level="Bronze"
                )
                db.add(account)
                db.flush()
            rate = (
                7
                if account.total_earned >= 5000
                else 5
                if account.total_earned >= 1000
                else 3
            )
            earned = int(float(data["total"]) * rate / 100)
            if earned:
                account.balance += earned
                account.total_earned += earned
            if account.total_earned >= 5000:
                account.level = "Gold"
            elif account.total_earned >= 1000:
                account.level = "Silver"
            else:
                account.level = "Bronze"
            db.add(
                LoyaltyTransaction(
                    user_id=order.user_id,
                    amount=earned,
                    transaction_type="earn",
                    order_id=order_id,
                    idempotency_key=f"earn_order_{order_id}",
                )
            )
        elif name == "cancellation":
            account = (
                db.query(LoyaltyAccount)
                .filter_by(user_id=order.user_id)
                .with_for_update()
                .first()
            )
            if account:
                spent = int(data.get("loyalty_points", 0) or 0)
                if (
                    spent
                    and not db.query(LoyaltyTransaction)
                    .filter_by(idempotency_key=f"refund_order_{order_id}")
                    .first()
                ):
                    account.balance += spent
                    db.add(
                        LoyaltyTransaction(
                            user_id=order.user_id,
                            amount=spent,
                            transaction_type="refund",
                            order_id=order_id,
                            idempotency_key=f"refund_order_{order_id}",
                        )
                    )
                earn = (
                    db.query(LoyaltyTransaction)
                    .filter_by(order_id=order_id, transaction_type="earn")
                    .first()
                )
                if (
                    earn
                    and not db.query(LoyaltyTransaction)
                    .filter_by(idempotency_key=f"revoke_earn_order_{order_id}")
                    .first()
                ):
                    account.balance = max(0, account.balance - earn.amount)
                    db.add(
                        LoyaltyTransaction(
                            user_id=order.user_id,
                            amount=-earn.amount,
                            transaction_type="revoke",
                            order_id=order_id,
                            idempotency_key=f"revoke_earn_order_{order_id}",
                        )
                    )
            if data.get("promo_code"):
                promo = (
                    db.query(PromoCode)
                    .filter_by(code=str(data["promo_code"]).upper())
                    .with_for_update()
                    .first()
                )
                if (
                    promo
                    and not db.query(PromoCompensation)
                    .filter_by(compensation_key=f"restore_promo_order_{order_id}")
                    .first()
                ):
                    promo.current_uses = max(0, promo.current_uses - 1)
                    usage = (
                        db.query(PromoCodeUsage).filter_by(order_id=order_id).first()
                    )
                    if usage:
                        db.delete(usage)
                    db.add(
                        PromoCompensation(
                            compensation_key=f"restore_promo_order_{order_id}",
                            order_id=order_id,
                            promo_code_id=promo.id,
                        )
                    )
        elif name == "kitchen" and not db.get(KitchenOrder, order_id):
            db.add(KitchenOrder(order_id=order_id, status="received"))
        elif (
            name == "delivery"
            and not db.query(Delivery).filter_by(order_id=order_id).first()
        ):
            courier = (
                db.query(User)
                .join(Role, User.role_id == Role.id)
                .filter(Role.name == "courier", User.is_blocked.is_(False))
                .first()
            )
            if courier:
                db.add(
                    Delivery(
                        order_id=order_id, courier_id=courier.id, status="assigned"
                    )
                )
            else:
                add_event(
                    db,
                    "delivery.failed",
                    {
                        "order_id": order_id,
                        "paid_event_id": event_id,
                        "reason": "courier_unavailable",
                    },
                )
        elif name == "compensation" and not db.get(OrderCompensation, order_id):
            paid = db.get(OutboxEvent, data["paid_event_id"])
            if not paid or paid.routing_key != "order.paid":
                raise ValueError("Original payment event not found")
            original = json.loads(paid.payload)
            if original["order_id"] != order_id:
                raise ValueError("Payment and order do not match")
            amount = Decimal(str(original["total"]))
            customer = (
                db.query(User).filter_by(id=order.user_id).with_for_update().one()
            )
            customer.balance += amount
            order.status = "cancelled"
            db.add(OrderCompensation(order_id=order_id, amount=amount))
            add_event(
                db,
                "order.cancelled",
                {"order_id": order_id, "reason": "delivery_failed"},
            )
    return True
