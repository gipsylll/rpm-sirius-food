"""
Модуль ограничения частоты запросов (Rate Limiting).

Защищает эндпоинты от брутфорса, спама и DoS-атак с использованием Redis.
При недоступности Redis использует локальный счетчик в памяти для обеспечения работы тестов.
"""

import time
from collections import defaultdict

import redis
from fastapi import HTTPException, Request

from app.core.redis import redis_client

# Резервный in-memory счетчик для тестов, когда Redis не запущен
_memory_counters: dict[str, list[float]] = defaultdict(list)


def rate_limit(max_requests: int = 5, window: int = 60):
    """
    FastAPI dependency для ограничения количества запросов.

    :param max_requests: Максимальное число разрешенных запросов в окне.
    :param window: Размер скользящего окна в секундах.
    """

    def checker(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        key = f"rate_limit:{client_ip}:{request.url.path}"

        try:
            current = redis_client.incr(key)
            if current == 1:
                redis_client.expire(key, window)
            if current > max_requests:
                raise HTTPException(status_code=429, detail="Too many requests")
        except (redis.RedisError, ConnectionError, OSError):
            # Резервный fallback в память для изолированного тестирования без внешнего Redis
            now = time.time()
            timestamps = [t for t in _memory_counters[key] if now - t < window]
            timestamps.append(now)
            _memory_counters[key] = timestamps
            if len(timestamps) > max_requests:
                raise HTTPException(status_code=429, detail="Too many requests")

    return checker
