"""HTTP -> service -> repository against a clean migrated PostgreSQL container."""

import os
import subprocess
import sys

import pytest

pytest.importorskip("testcontainers.postgres")
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models import MenuItem, Order, OutboxEvent, User


@pytest.fixture(scope="module")
def postgres():
    with PostgresContainer("postgres:15", driver="psycopg2") as pg:
        url = pg.get_connection_url()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env={**os.environ, "DATABASE_URL": url},
            check=True,
        )
        yield url


def test_create_order(postgres, monkeypatch):
    engine = create_engine(postgres)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        db.query(OutboxEvent).delete()
        db.query(Order).delete()
        db.query(User).filter_by(email="integration@example.com").delete()
        user = User(email="integration@example.com", balance=1000)
        item = MenuItem(name="Integration dish", price=150, is_available=True)
        db.add_all([user, item])
        db.flush()
        user_id, item_id = user.id, item.id

    def get_test_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = lambda: type(
        "CurrentUser", (), {"id": user_id}
    )()
    for task in ("generate_order_pdf", "send_order_email", "send_order_sms"):
        monkeypatch.setattr(
            getattr(__import__("app.modules.orders.service", fromlist=[task]), task),
            "delay",
            lambda *args: None,
        )
    try:
        with TestClient(app) as client:
            response = client.post(
                "/orders/create",
                json={"item_id": item_id, "quantity": 2},
                headers={"X-Correlation-ID": "integration-42"},
            )
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == "integration-42"
        with Session() as db:
            order = db.get(Order, response.json()["order_id"])
            assert order.quantity == 2
            assert db.get(User, user_id).balance == 700
            assert (
                db.query(OutboxEvent).filter_by(correlation_id="integration-42").count()
                == 1
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
