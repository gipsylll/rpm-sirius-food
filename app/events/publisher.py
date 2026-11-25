"""Async Transactional Outbox publisher process."""

import asyncio
import json

import aio_pika
from aio_pika import DeliveryMode, Message

from app.core.observability import correlation_id, log
from app.core.tracing import (
    annotate_correlation,
    get_trace_headers,
    setup_tracing,
    span,
)
from app.database import SessionLocal
from app.events.common import URL, OutboxEvent, setup


async def publisher():
    while True:
        connection = None
        try:
            connection = await aio_pika.connect_robust(URL)
            channel = await connection.channel(publisher_confirms=True)
            events, _ = await setup(channel)
            while True:
                with SessionLocal.begin() as db:
                    row = (
                        db.query(OutboxEvent)
                        .filter_by(published=False)
                        .order_by(OutboxEvent.id)
                        .with_for_update(skip_locked=True)
                        .first()
                    )
                    if row:
                        with span(
                            "publish " + row.routing_key,
                            json.loads(row.trace_context or "{}"),
                        ):
                            annotate_correlation(row.correlation_id)
                            headers = {
                                "correlation_id": row.correlation_id,
                                **get_trace_headers(),
                            }
                            await events.publish(
                                Message(
                                    json.dumps(json.loads(row.payload)).encode(),
                                    delivery_mode=DeliveryMode.PERSISTENT,
                                    headers=headers,
                                ),
                                routing_key=row.routing_key,
                            )
                        row.published = True
                        token = correlation_id.set(row.correlation_id)
                        log("event_published", event_id=row.id)
                        correlation_id.reset(token)
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("publisher_retry", error=str(exc))
            await asyncio.sleep(3)
        finally:
            if connection and not connection.is_closed:
                await connection.close()


if __name__ == "__main__":
    setup_tracing("sirius-publisher")
    asyncio.run(publisher())
