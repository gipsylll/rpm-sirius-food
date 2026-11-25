"""
Конфигурация тестового окружения pytest.

Включает режим task_always_eager для задач Celery,
что позволяет выполнять unit-тесты синхронно в памяти без внешнего Redis.
"""

import pytest

from app.core.celery_app import celery_app


@pytest.fixture(autouse=True)
def configure_celery_test_mode():
    """Автоматическая фикстура для изолированного выполнения задач Celery в тестах."""
    original_eager = celery_app.conf.task_always_eager
    original_propagate = celery_app.conf.task_eager_propagates

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False

    yield

    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.task_eager_propagates = original_propagate
