#!/usr/bin/env python3
"""Check lab 7 against the project's running Docker Compose stack."""

import asyncio
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import aio_pika
import requests
from aio_pika import DeliveryMode, ExchangeType, Message
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = uuid.uuid4().hex[:12]
API = "http://127.0.0.1:8000"
BROKER = "amqp://sirius:sirius@127.0.0.1:5672//"
DB = "postgresql://sirius:sirius@127.0.0.1:5432/sirius_food"
COMPOSE = ["docker", "compose"]
RABBIT_UI = "http://localhost:15672"


def step(number, message):
    print(f"\n[{number}] {message}", flush=True)


def rabbit_queue_url(queue):
    return f"{RABBIT_UI}/#/queues/%2F/{queue}"


def compose(*args, capture=False):
    result = subprocess.run(
        COMPOSE + list(args),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.stdout


def eventually(label, check, timeout=90):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            last = check()
            if last:
                return last
        except (requests.RequestException, ConnectionError) as exc:
            last = exc
        time.sleep(1)
    raise AssertionError(
        f"{label}: превышено время ожидания; последнее значение: {last}"
    )


def run():
    engine = create_engine(DB)
    changed_couriers = []
    broker_stopped = False

    def query(sql, **params):
        with engine.begin() as conn:
            result = conn.execute(text(sql), params)
            return result.mappings().all() if result.returns_rows else None

    def restore_couriers():
        if changed_couriers:
            query(
                "UPDATE users SET is_blocked=false WHERE id = ANY(:ids)",
                ids=changed_couriers,
            )
            changed_couriers.clear()

    def management(path):
        response = requests.get(
            "http://127.0.0.1:15672/api/" + path, auth=("sirius", "sirius"), timeout=5
        )
        response.raise_for_status()
        return response.json()

    try:
        print(f"Проверка основного стека, запуск {RUN_ID}", flush=True)
        step(
            "1/7",
            "Запускаю основной Docker Compose стек и жду API, PostgreSQL и RabbitMQ",
        )
        compose("up", "-d", "--build", capture=True)
        for service in (
            "db",
            "app_redis",
            "rabbitmq",
            "api",
            "event_publisher",
            "kitchen",
            "delivery_events",
            "compensation",
        ):
            if not compose(
                "ps", "--status", "running", "--services", service, capture=True
            ).strip():
                raise RuntimeError(
                    f"Сервис {service} не запущен. Выполните docker compose up -d --build"
                )
        eventually(
            "API", lambda: requests.get(API + "/menu/items", timeout=5).ok, timeout=120
        )
        eventually(
            "RabbitMQ Management API", lambda: bool(management("overview")), timeout=120
        )

        step("2/7", "Создаю тестового пользователя и пополняю его баланс")
        email = f"lab7-{RUN_ID}@example.com"
        password = "lab7-test-password"
        response = requests.post(
            API + "/users/register",
            json={"email": email, "password": password},
            timeout=10,
        )
        response.raise_for_status()
        user_id = response.json()["user_id"]
        response = requests.post(
            API + "/auth/login", json={"email": email, "password": password}, timeout=10
        )
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        response = requests.post(
            f"{API}/users/{user_id}/topup",
            params={"amount": 10000},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        item = query(
            "SELECT id, price FROM menu_items WHERE is_available=true AND price>0 AND price<10000 ORDER BY id LIMIT 1"
        )
        if not item:
            raise RuntimeError("Нет доступного блюда стоимостью от 0 до 10000")
        item = item[0]

        def order(cid):
            response = requests.post(
                API + "/orders/create",
                headers={**headers, "X-Correlation-ID": cid},
                json={"item_id": item["id"], "quantity": 1},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()["order_id"]

        def paid(order_id):
            rows = query(
                "SELECT id, payload, published FROM outbox_events WHERE routing_key='order.paid' AND cast(payload AS json)->>'order_id'=:oid",
                oid=str(order_id),
            )
            return rows[0] if rows else None

        def processed(event_id):
            return query(
                "SELECT consumer FROM processed_events WHERE event_id=:eid",
                eid=event_id,
            )

        def both(event_id):
            return {row["consumer"] for row in processed(event_id)} >= {
                "kitchen",
                "delivery",
            }

        async def async_publish(key, data, cid):
            connection = await aio_pika.connect_robust(BROKER)
            try:
                channel = await connection.channel(publisher_confirms=True)
                exchange = await channel.declare_exchange(
                    "sirius_events", ExchangeType.TOPIC, durable=True
                )
                await exchange.publish(
                    Message(
                        json.dumps(data).encode(),
                        delivery_mode=DeliveryMode.PERSISTENT,
                        headers={"correlation_id": cid},
                    ),
                    routing_key=key,
                )
            finally:
                await connection.close()

        def publish(key, data, cid):
            asyncio.run(async_publish(key, data, cid))

        step(
            "3/7",
            "Проверяю обычный маршрут: API → Outbox → RabbitMQ → кухня и доставка",
        )
        oid = order(f"lab7-{RUN_ID}-normal")
        event = paid(oid)
        eventually("кухня и доставка", lambda: both(event["id"]))
        assert (
            query(
                "SELECT count(*) AS n FROM kitchen_orders WHERE order_id=:oid", oid=oid
            )[0]["n"]
            == 1
        )
        assert (
            query("SELECT count(*) AS n FROM deliveries WHERE order_id=:oid", oid=oid)[
                0
            ]["n"]
            == 1
        )
        print(f"PASS: POST /orders/create создал заказ {oid}", flush=True)
        print("      OrderPaid опубликован и обработан обоими consumer", flush=True)
        print(f"      kitchen_queue: {rabbit_queue_url('kitchen_queue')}", flush=True)
        print(f"      delivery_queue: {rabbit_queue_url('delivery_queue')}", flush=True)

        step("4/7", "Повторно публикую то же OrderPaid и проверяю идемпотентность")
        dup_cid = f"lab7-{RUN_ID}-duplicate"
        publish("order.paid", json.loads(event["payload"]), dup_cid)

        def duplicate_seen():
            logs = compose(
                "logs",
                "--no-color",
                "--since=5m",
                "kitchen",
                "delivery_events",
                capture=True,
            )
            matched = [
                line
                for line in logs.splitlines()
                if dup_cid in line and '"duplicate": true' in line
            ]
            return len(matched) >= 2

        eventually("повторная обработка", duplicate_seen)
        assert (
            query(
                "SELECT count(*) AS n FROM kitchen_orders WHERE order_id=:oid", oid=oid
            )[0]["n"]
            == 1
        )
        assert (
            query("SELECT count(*) AS n FROM deliveries WHERE order_id=:oid", oid=oid)[
                0
            ]["n"]
            == 1
        )
        print("PASS: повторное событие не создало дубликатов", flush=True)

        step("5/7", "Публикую битое сообщение и проверяю Dead Letter Queue")
        dlq_before = management("queues/%2F/kitchen_dlq")["messages"]
        bad_cid = f"lab7-{RUN_ID}-bad"
        publish("order.paid", {"event_id": "bad-" + RUN_ID, "order_id": oid}, bad_cid)

        def rejected_to_dlq():
            logs = compose("logs", "--no-color", "--since=5m", "kitchen", capture=True)
            rejected = any(
                bad_cid in line and "event_rejected" in line
                for line in logs.splitlines()
            )
            return (
                rejected
                and management("queues/%2F/kitchen_dlq")["messages"] > dlq_before
            )

        eventually("DLQ", rejected_to_dlq)
        print(
            "PASS: некорректное сообщение отклонено и очередь kitchen_dlq увеличилась",
            flush=True,
        )
        print(f"      RabbitMQ DLQ: {rabbit_queue_url('kitchen_dlq')}", flush=True)

        step("6/7", "Блокирую доступных курьеров и проверяю Saga-компенсацию")
        changed = query(
            "UPDATE users SET is_blocked=true WHERE role_id=(SELECT id FROM roles WHERE name='courier') AND is_blocked=false RETURNING id"
        )
        changed_couriers.extend(row["id"] for row in changed)
        before = query("SELECT balance FROM users WHERE id=:uid", uid=user_id)[0][
            "balance"
        ]
        saga_order = order(f"lab7-{RUN_ID}-saga")

        def delivery_failed_event():
            rows = query(
                "SELECT payload, published FROM outbox_events WHERE routing_key='delivery.failed' AND cast(payload AS json)->>'order_id'=:oid",
                oid=str(saga_order),
            )
            if len(rows) != 1:
                return None
            payload = json.loads(rows[0]["payload"])
            if payload.get("reason") != "courier_unavailable":
                raise AssertionError(
                    "delivery.failed содержит неправильную причину отказа"
                )
            return rows[0]

        failed = eventually("создание delivery.failed", delivery_failed_event)
        assert (
            query(
                "SELECT count(*) AS n FROM deliveries WHERE order_id=:oid",
                oid=saga_order,
            )[0]["n"]
            == 0
        )
        print(
            "PASS: при отсутствии доступных курьеров создано delivery.failed "
            "с причиной courier_unavailable и доставка не назначена",
            flush=True,
        )

        def published_delivery_failed():
            rows = query(
                "SELECT payload FROM outbox_events WHERE routing_key='delivery.failed' AND published=true AND cast(payload AS json)->>'order_id'=:oid",
                oid=str(saga_order),
            )
            return rows if len(rows) == 1 else None

        failed_published = eventually(
            "публикация delivery.failed", published_delivery_failed
        )

        def compensation():
            rows = query(
                "SELECT o.status, u.balance, c.amount FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN order_compensations c ON c.order_id=o.id WHERE o.id=:oid",
                oid=saga_order,
            )
            return (
                rows[0]
                if rows
                and rows[0]["status"] == "cancelled"
                and rows[0]["amount"] is not None
                else None
            )

        result = eventually("компенсация", compensation)
        assert abs(result["balance"] - before) < 0.001
        assert abs(result["amount"] - item["price"]) < 0.001
        cancelled = eventually(
            "order.cancelled",
            lambda: query(
                "SELECT published FROM outbox_events WHERE routing_key='order.cancelled' AND published=true AND cast(payload AS json)->>'order_id'=:oid",
                oid=str(saga_order),
            ),
        )
        assert len(failed_published) == 1 and len(cancelled) == 1
        failure = json.loads(failed["payload"])
        publish("delivery.failed", failure, f"lab7-{RUN_ID}-repeat")
        failure["event_id"] = str(uuid.uuid4())
        publish("delivery.failed", failure, f"lab7-{RUN_ID}-repeat-new")
        eventually(
            "повторная компенсация",
            lambda: any(
                row["consumer"] == "compensation"
                for row in processed(failure["event_id"])
            ),
        )
        assert (
            query(
                "SELECT count(*) AS n FROM order_compensations WHERE order_id=:oid",
                oid=saga_order,
            )[0]["n"]
            == 1
        )
        assert (
            abs(
                query("SELECT balance FROM users WHERE id=:uid", uid=user_id)[0][
                    "balance"
                ]
                - before
            )
            < 0.001
        )
        print(
            f"PASS: Saga отменила заказ {saga_order}, вернула деньги один раз и опубликовала order.cancelled",
            flush=True,
        )
        restore_couriers()

        step(
            "7/7",
            "Останавливаю основной RabbitMQ, проверяю Outbox и восстанавливаю брокер",
        )
        broker_stopped = True
        compose("stop", "rabbitmq")
        offline_oid = order(f"lab7-{RUN_ID}-offline")
        offline_event = paid(offline_oid)
        assert not offline_event["published"]
        print(
            f"PASS: при остановленном RabbitMQ заказ {offline_oid} и событие сохранены в Outbox",
            flush=True,
        )
        compose("start", "rabbitmq")
        eventually(
            "публикация после восстановления",
            lambda: paid(offline_oid)["published"],
            timeout=120,
        )
        eventually(
            "обработка после восстановления",
            lambda: both(offline_event["id"]),
            timeout=120,
        )
        broker_stopped = False
        print(
            "PASS: после восстановления RabbitMQ событие доставлено обоим consumer",
            flush=True,
        )
        print(
            f"Тестовый пользователь: {email}; заказы: {oid}, {saga_order}, {offline_oid}",
            flush=True,
        )
        print("\nСсылки для проверки:", flush=True)
        print(f"  RabbitMQ overview: {RABBIT_UI}", flush=True)
        print(f"  kitchen_dlq: {rabbit_queue_url('kitchen_dlq')}", flush=True)
        print(f"  delivery_dlq: {rabbit_queue_url('delivery_dlq')}", flush=True)
        print(f"  compensation_dlq: {rabbit_queue_url('compensation_dlq')}", flush=True)
        print("\nКоманда для проверки результатов в PostgreSQL:", flush=True)
        print(
            f'''docker compose exec -T db psql -U sirius -d sirius_food -c "SELECT id, user_id, status FROM orders WHERE id IN ({oid}, {saga_order}, {offline_oid}) ORDER BY id; SELECT id, routing_key, published, payload FROM outbox_events WHERE cast(payload AS json)->>'order_id' IN ('{oid}', '{saga_order}', '{offline_oid}') ORDER BY id; SELECT order_id, amount FROM order_compensations WHERE order_id={saga_order}; SELECT order_id, status FROM kitchen_orders WHERE order_id={oid}; SELECT order_id, courier_id, status FROM deliveries WHERE order_id={oid};"''',
            flush=True,
        )
    finally:
        try:
            restore_couriers()
        finally:
            engine.dispose()
            if broker_stopped:
                print("Восстанавливаем RabbitMQ...", flush=True)
                compose("start", "rabbitmq")


if __name__ == "__main__":
    try:
        run()
    except (Exception, KeyboardInterrupt) as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    print("ИТОГ: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")
