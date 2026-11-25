"""Consumer-driven Pact: kitchen receives a real OrderPaid message."""

import json

import pytest

pytest.importorskip("pact")
from pact import Pact, Verifier
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.events import worker
from app.events.contracts import build_order_paid
from app.models import KitchenOrder, MenuItem, Order, User


def test_order_paid_consumer_and_provider(tmp_path, monkeypatch):
    example = {
        "event_id": "event-42",
        "order_id": 42,
        "user_id": 1,
        "item_id": 2,
        "quantity": 2,
        "total": 300.0,
        "currency": "RUB",
    }
    pact = Pact("Kitchen", "OrderService").with_specification("V3")
    pact.upon_receiving("an order paid", "Async").with_body(
        json.dumps(example), "application/json"
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    with sessions.begin() as db:
        db.add(User(id=1, email="pact@example.com", balance=0))
        db.add(MenuItem(id=2, name="Soup", price=150))
        db.add(Order(id=42, user_id=1, item_id=2, quantity=2))
    pact.verify(
        lambda body, metadata: worker.process("kitchen", json.loads(body)), "Async"
    )
    with sessions() as db:
        assert db.get(KitchenOrder, 42) is not None
    pact.write_file(tmp_path, overwrite=True)

    def verify(data):
        response = {
            "contents": json.dumps(data).encode(),
            "content_type": "application/json",
        }
        (
            Verifier("OrderService")
            .message_handler({"an order paid": response})
            .add_source(tmp_path)
            .verify()
        )

    verify(build_order_paid("event-42", 42, 1, 2, 2, 300))
    incompatible = build_order_paid("event-42", 42, 1, 2, 2, 300)
    incompatible["amount"] = incompatible.pop("total")
    with pytest.raises(Exception):
        verify(incompatible)
