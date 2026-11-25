"""
Фоновые задачи Celery для модуля заказов.

Включает:
- generate_order_pdf: генерация PDF с проверкой идемпотентности через Redis.
- send_order_email: отправка email с экспоненциальными ретраями и маршрутизацией в DLQ.
- send_order_sms: отправка SMS уведомления.
- dead_letter_handler: обработчик задач в Dead Letter Queue.
- aggregate_order_statistics: периодическая задача Celery Beat.
"""

import json
import logging
import time
from datetime import UTC, datetime

from app.core.celery_app import celery_app
from app.core.redis import is_redis_available, redis_client

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def generate_order_pdf(self, order_id: int) -> str:
    """
    Генерация PDF-чека для заказа с проверкой идемпотентности.
    Имитация тяжёлой операции через time.sleep(2).
    Повторные вызовы для одного order_id пропускаются благодаря ключу в Redis.
    """
    key = f"pdf_generated:{order_id}"

    # Проверка идемпотентности
    if is_redis_available():
        try:
            if redis_client.exists(key):
                logger.info("PDF уже сгенерирован для заказа %s (пропуск)", order_id)
                return f"PDF already generated for order {order_id}"
        except Exception as exc:
            logger.warning("Ошибка проверки ключа идемпотентности в Redis: %s", exc)

    # Имитация тяжелой операции
    time.sleep(2)

    # Фиксация факта генерации на 1 час (3600 секунд)
    if is_redis_available():
        try:
            redis_client.setex(key, 3600, "1")
        except Exception as exc:
            logger.warning("Ошибка записи ключа идемпотентности в Redis: %s", exc)

    logger.info("PDF успешно сгенерирован для заказа %s", order_id)
    return f"PDF generated for order {order_id}"


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def send_order_email(self, order_id: int, email: str) -> str:
    """
    Отправка email с экспоненциальными ретраями.
    Имитация сбоя внешнего шлюза для каждого 5-го заказа (order_id % 5 == 0).
    При превышении max_retries задача перенаправляется в Dead Letter Queue (DLQ).
    """
    time.sleep(1)

    if order_id % 5 == 0:
        logger.warning(
            "Имитация недоступности почтового шлюза для заказа %s (попытка %s/%s)",
            order_id,
            self.request.retries,
            self.max_retries,
        )
        if self.request.retries >= self.max_retries:
            # Превышен лимит попыток -> направляем в Dead Letter Queue (dlq)
            logger.error(
                "Заказ %s превысил max_retries. Отправка в очередь DLQ...", order_id
            )
            dead_letter_handler.apply_async(
                args=[order_id, email, "Email service unavailable after max retries"],
                queue="dlq",
            )
        raise Exception("Email service unavailable")

    logger.info("Email успешно отправлен на %s для заказа %s", email, order_id)
    return f"Email sent to {email} for order {order_id}"


@celery_app.task
def send_order_sms(order_id: int, phone: str) -> str:
    """Отправка SMS о создании заказа."""
    time.sleep(1)
    logger.info("SMS успешно отправлено на %s для заказа %s", phone, order_id)
    return f"SMS sent to {phone} for order {order_id}"


@celery_app.task(queue="dlq")
def dead_letter_handler(order_id: int, target: str, error_reason: str) -> str:
    """
    Обработчик очереди недоставленных сообщений (Dead Letter Queue - dlq).
    Сохраняет информацию о сбойной задаче в Redis для ручного разбора.
    """
    record = {
        "order_id": order_id,
        "target": target,
        "error_reason": error_reason,
        "failed_at": datetime.now(UTC).isoformat(),
    }
    if is_redis_available():
        try:
            redis_client.lpush(
                "dlq:failures",
                json.dumps(record),
            )
        except Exception as exc:
            logger.warning("Ошибка сохранения в dlq:failures: %s", exc)

    logger.warning(
        "DLQ: Зафиксирована неудачная задача для заказа %s: %s", order_id, error_reason
    )
    return f"DLQ recorded for order {order_id}: {error_reason}"


@celery_app.task
def aggregate_order_statistics() -> dict:
    """
    Периодическая задача Celery Beat (10 баллов).
    Выполняется каждую минуту, агрегирует статистику по заказам и сохраняет в Redis.
    """
    from app.database import SessionLocal
    from app.models import Order

    stats = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_orders": 0,
        "processing_orders": 0,
        "status": "ok",
    }

    try:
        db = SessionLocal()
        try:
            stats["total_orders"] = db.query(Order).count()
            stats["processing_orders"] = (
                db.query(Order).filter(Order.status == "processing").count()
            )
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Не удалось получить статистику из БД: %s", exc)
        stats["status"] = f"db_unavailable: {exc}"

    if is_redis_available():
        try:
            redis_client.set("stats:orders:daily", json.dumps(stats), ex=300)
        except Exception as exc:
            logger.warning("Ошибка сохранения статистики в Redis: %s", exc)

    logger.info("Celery Beat: статистика заказов обновлена: %s", stats)
    return stats


@celery_app.task
def deactivate_expired_promos() -> int:
    """Deactivate expired promo codes; safe to run repeatedly from Beat."""
    from app.database import SessionLocal
    from app.models import PromoCode

    now = datetime.now(UTC)
    db = SessionLocal()
    try:
        count = (
            db.query(PromoCode)
            .filter(
                PromoCode.is_active.is_(True),
                PromoCode.valid_until.is_not(None),
                PromoCode.valid_until < now,
            )
            .update({PromoCode.is_active: False}, synchronize_session=False)
        )
        db.commit()
        return count
    finally:
        db.close()
