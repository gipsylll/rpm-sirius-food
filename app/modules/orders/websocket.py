"""Redis Pub/Sub backed WebSocket order tracking."""

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import WebSocket

from app.core.jwt import decode_token
from app.core.redis import redis_client

logger = logging.getLogger(__name__)


class OrderConnectionManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = {}
        self._listener_task: asyncio.Task | None = None

    async def connect(self, order_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections.setdefault(order_id, set()).add(websocket)

    def disconnect(self, order_id: int, websocket: WebSocket):
        clients = self.connections.get(order_id, set())
        clients.discard(websocket)
        if not clients:
            self.connections.pop(order_id, None)

    async def broadcast(self, event: dict):
        order_id = int(event.get("order_id", 0))
        clients = list(self.connections.get(order_id, set()))
        for websocket in clients:
            try:
                await websocket.send_json(event)
            except Exception:
                self.disconnect(order_id, websocket)

    async def listen(self):
        """Subscribe once per API replica and fan out to local sockets."""
        while True:
            pubsub = None
            try:
                pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
                await asyncio.to_thread(pubsub.subscribe, "order_updates")
                while True:
                    message = await asyncio.to_thread(pubsub.get_message, True, 1.0)
                    if message and message.get("type") == "message":
                        try:
                            await self.broadcast(json.loads(message["data"]))
                        except (TypeError, ValueError, KeyError) as exc:
                            logger.warning("Invalid order update: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Redis Pub/Sub unavailable: %s", exc)
                await asyncio.sleep(2)
            finally:
                if pubsub is not None:
                    try:
                        await asyncio.to_thread(pubsub.close)
                    except Exception:
                        pass

    def start(self):
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(
                self.listen(), name="order-updates-listener"
            )
        return self._listener_task

    async def stop(self):
        if self._listener_task:
            self._listener_task.cancel()
            await asyncio.gather(self._listener_task, return_exceptions=True)
            self._listener_task = None


manager = OrderConnectionManager()


def publish_order_update(
    order_id: int, status: str, delivery_status: str | None = None
):
    event = {
        "type": "status_update",
        "order_id": order_id,
        "status": status,
        "delivery_status": delivery_status or status,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    try:
        redis_client.publish("order_updates", json.dumps(event))
    except Exception as exc:
        logger.debug("Could not publish order update: %s", exc)
    return event


def user_id_from_token(token: str) -> int:
    payload = decode_token(token)
    if payload.get("type") != "access" or not payload.get("sub"):
        raise ValueError("invalid access token")
    return int(payload["sub"])
