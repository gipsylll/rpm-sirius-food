"""
Конфигурация и инициализация Celery для проекта «Сириус.Еда».

Использует Redis в качестве брокера сообщений и бэкенда результатов.
Реализует разделение очередей на default и dlq (Dead Letter Queue),
а также расписание периодических задач Celery Beat.
"""

from celery import Celery
from kombu import Exchange, Queue

from app.core.config import settings

celery_app = Celery(
    "sirius_food",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.orders"],
)

# Базовые настройки сериализации и часового пояса
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Настройка очередей: default и dlq (Dead Letter Queue)
celery_app.conf.task_queues = (
    Queue("default", Exchange("default"), routing_key="default"),
    Queue("dlq", Exchange("dlq"), routing_key="dlq"),
)

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

# Настройка периодических задач через Celery Beat (10 баллов)
celery_app.conf.beat_schedule = {
    "aggregate-order-statistics-every-minute": {
        "task": "app.tasks.orders.aggregate_order_statistics",
        "schedule": 60.0,
    },
    "deactivate-expired-promos-every-minute": {
        "task": "app.tasks.orders.deactivate_expired_promos",
        "schedule": 60.0,
    },
}
