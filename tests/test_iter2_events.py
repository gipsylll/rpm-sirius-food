"""Checks that an order and its event are persisted together and consumers deduplicate."""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.events import worker
from app.models import KitchenOrder, MenuItem, Order, OutboxEvent, ProcessedEvent, User
from app.modules.orders.repository import SqlAlchemyOrderRepository


def test_outbox_and_consumers(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    with sessions.begin() as db:
        user = User(email="event@example.com", balance=100)
        item = MenuItem(name="Soup", price=30, is_available=True)
        db.add_all([user, item])
        db.flush()
        user_id, item_id = user.id, item.id
    with sessions() as db:
        repo = SqlAlchemyOrderRepository(db)
        user = repo.get_user_by_id(user_id)
        repo.update_user_balance(user, 70)
        order_id = repo.save_order(user_id, item_id, 1)
        event = db.query(OutboxEvent).one()
        data = json.loads(event.payload)
        assert data["order_id"] == order_id
        assert data["total"] == 30
        assert db.get(User, user_id).balance == 70
        assert db.get(Order, order_id) is not None
    assert worker.process("kitchen", data)
    assert not worker.process("kitchen", data)
    assert worker.process("delivery", data)
    with sessions() as db:
        assert db.query(KitchenOrder).count() == 1
        assert db.query(ProcessedEvent).count() == 2


def test_order_and_outbox_rollback_together():
    from sqlalchemy import event

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        user = User(email="rollback@example.com", balance=100)
        item = MenuItem(name="Soup", price=30, is_available=True)
        db.add_all([user, item])
        db.flush()
        user_id, item_id = user.id, item.id

    def fail_event(mapper, connection, target):
        raise RuntimeError("simulate outbox failure")

    event.listen(OutboxEvent, "before_insert", fail_event)
    try:
        with sessions() as db:
            repo = SqlAlchemyOrderRepository(db)
            user = repo.get_user_by_id(user_id)
            repo.update_user_balance(user, 70)
            try:
                repo.save_order(user_id, item_id, 1)
                raise AssertionError("transaction should fail")
            except RuntimeError:
                db.rollback()
        with sessions() as db:
            assert db.get(User, user_id).balance == 100
            assert db.query(Order).count() == 0
            assert db.query(OutboxEvent).count() == 0
    finally:
        event.remove(OutboxEvent, "before_insert", fail_event)


def test_failed_delivery_refunds_once_and_creates_cancellation(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    with sessions.begin() as db:
        user = User(email="saga@example.com", balance=100)
        item = MenuItem(name="Soup", price=30, is_available=True)
        db.add_all([user, item])
        db.flush()
        user_id, item_id = user.id, item.id
    with sessions() as db:
        repo = SqlAlchemyOrderRepository(db)
        repo.update_user_balance(repo.get_user_by_id(user_id), 70)
        order_id = repo.save_order(user_id, item_id, 1)
        paid = json.loads(db.query(OutboxEvent).one().payload)
    assert worker.process("delivery", paid)
    with sessions() as db:
        failure = json.loads(
            db.query(OutboxEvent).filter_by(routing_key="delivery.failed").one().payload
        )
    assert worker.process("compensation", failure)
    assert not worker.process("compensation", failure)
    assert worker.process(
        "compensation", {**failure, "event_id": "second-delivery-failure"}
    )
    with sessions() as db:
        assert db.get(User, user_id).balance == 100
        assert db.get(Order, order_id).status == "cancelled"
        assert (
            db.query(OutboxEvent).filter_by(routing_key="order.cancelled").count() == 1
        )


def test_queue_bindings():
    bindings = {queue.name: queue.routing_key for queue in worker.queues}
    assert bindings["kitchen_queue"] == "order.paid"
    assert bindings["delivery_queue"] == "order.paid"
    assert bindings["compensation_queue"] == "delivery.failed"
    assert len(bindings) == len(worker.queues)
    assert any(queue.name == "compensation_dlq" for queue in worker.dead_queues)


def test_bad_event_is_rejected_before_recording(monkeypatch):
    import pytest
    from pydantic import ValidationError

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    with pytest.raises(ValidationError):
        worker.process("kitchen", {"event_id": "event", "order_id": 42, "amount": 300})
    with sessions() as db:
        assert db.query(ProcessedEvent).count() == 0


def test_duplicate_delivery_event_creates_one_delivery(monkeypatch):
    from app.models import Delivery, Role

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    with sessions.begin() as db:
        role = Role(name="courier")
        customer = User(email="duplicate@example.com", balance=100)
        courier = User(
            email="courier@example.com", balance=0, role=role, is_blocked=False
        )
        item = MenuItem(name="Soup", price=30, is_available=True)
        db.add_all([customer, courier, item])
        db.flush()
        order = Order(user_id=customer.id, item_id=item.id, quantity=1)
        db.add(order)
        db.flush()
        event = {
            "event_id": "duplicate-check",
            "order_id": order.id,
            "user_id": customer.id,
            "item_id": item.id,
            "quantity": 1,
            "total": 30.0,
            "currency": "RUB",
        }
        courier_id = courier.id
    assert worker.process("delivery", event) is True
    assert worker.process("delivery", event) is False
    with sessions() as db:
        delivery = db.query(Delivery).one()
        assert delivery.order_id == event["order_id"]
        assert delivery.courier_id == courier_id
        assert (
            db.query(ProcessedEvent)
            .filter_by(consumer="delivery", event_id="duplicate-check")
            .count()
            == 1
        )
