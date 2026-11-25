"""
Модуль подключения к Redis.

Предоставляет клиент redis_client для кеширования (Cache-Aside),
ограничения частоты запросов (Rate Limiting) и распределенных блокировок (Locks).
"""

import logging

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# Клиент Redis с decode_responses=True для автоматической декодировки строк JSON
redis_client = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=2.0,
    socket_timeout=2.0,
)


def is_redis_available() -> bool:
    """Проверяет доступность Redis-сервера."""
    try:
        return bool(redis_client.ping())
    except Exception as exc:
        logger.warning("Redis недоступен: %s", exc)
        return False
