"""Async RabbitMQ consumer process for kitchen, delivery or compensation."""

import asyncio
import json

import aio_pika
from aio_pika import IncomingMessage
from sqlalchemy.exc import IntegrityError

from app.core.observability import correlation_id, log
from app.core.tracing import annotate_correlation, setup_tracing, span
from app.database import SessionLocal
from app.events.common import URL, ProcessedEvent, process, setup


async def _handle_message(name: str, message: IncomingMessage):
    headers = message.headers or {}
    token = correlation_id.set(headers.get("correlation_id", ""))
    data = None
    try:
        data = json.loads(message.body)
        with span("consume " + name, dict(headers)):
            annotate_correlation(correlation_id.get())
            processed = await asyncio.to_thread(process, name, data)
        log(
            "event_processed",
            consumer=name,
            order_id=data["order_id"],
            duplicate=not processed,
        )
        await message.ack()
    except (KeyError, ValueError, TypeError) as exc:
        log("event_rejected", consumer=name, error=str(exc))
        await message.reject(requeue=False)
    except IntegrityError as exc:
        event_id = data.get("event_id") if isinstance(data, dict) else None
        with SessionLocal() as db:
            duplicate = (
                event_id is not None
                and db.get(ProcessedEvent, (name, event_id)) is not None
            )
        if duplicate:
            await message.ack()
        else:
            log("event_rejected", consumer=name, error=str(exc))
            await message.reject(requeue=False)
    except Exception as exc:
        log("event_retry", consumer=name, error=str(exc))
        await message.reject(requeue=True)
        await asyncio.sleep(1)
    finally:
        correlation_id.reset(token)


async def consumer(name):
    queue_name = {
        "kitchen": "kitchen_queue",
        "delivery": "delivery_queue",
        "loyalty": "loyalty_queue",
        "compensation": "compensation_queue",
        "cancellation": "cancellation_queue",
    }[name]
    while True:
        connection = None
        try:
            connection = await aio_pika.connect_robust(URL)
            channel = await connection.channel()
            _, declared = await setup(channel)
            async with declared[queue_name].iterator() as queue_iter:
                async for message in queue_iter:
                    await _handle_message(name, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("consumer_reconnect", consumer=name, error=str(exc))
            await asyncio.sleep(3)
        finally:
            if connection and not connection.is_closed:
                await connection.close()


if __name__ == "__main__":
    mode = __import__("sys").argv[1]
    if mode not in ("kitchen", "delivery", "loyalty", "compensation", "cancellation"):
        raise SystemExit("Use kitchen, delivery, loyalty, compensation or cancellation")
    setup_tracing("sirius-" + mode)
    asyncio.run(consumer(mode))
