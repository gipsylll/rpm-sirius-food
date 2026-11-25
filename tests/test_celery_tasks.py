"""
Тесты для фоновых задач Celery (Лабораторная работа № 5).

Проверяет:
- Идемпотентность generate_order_pdf
- Поведение send_order_email (успех и обработка сбоев с DLQ)
- send_order_sms
- Периодическую задачу aggregate_order_statistics (Celery Beat)
"""

from unittest.mock import MagicMock, patch

from app.tasks.orders import (
    aggregate_order_statistics,
    dead_letter_handler,
    generate_order_pdf,
    send_order_email,
    send_order_sms,
)


def test_generate_order_pdf_success_and_idempotency():
    """Проверка генерации PDF и механизма идемпотентности."""
    mock_redis = MagicMock()
    mock_redis.exists.return_value = False

    with (
        patch("app.tasks.orders.redis_client", mock_redis),
        patch("app.tasks.orders.is_redis_available", return_value=True),
        patch("time.sleep", return_value=None),
    ):
        # Первый вызов: PDF генерируется
        result1 = generate_order_pdf(101)
        assert result1 == "PDF generated for order 101"
        mock_redis.setex.assert_called_once_with("pdf_generated:101", 3600, "1")

        # Второй вызов: ключ уже в Redis -> пропуск
        mock_redis.exists.return_value = True
        result2 = generate_order_pdf(101)
        assert result2 == "PDF already generated for order 101"


def test_send_order_email_success():
    """Успешная отправка email для заказа, не кратного 5."""
    with patch("time.sleep", return_value=None):
        result = send_order_email(7, "student@sirius.ru")
        assert result == "Email sent to student@sirius.ru for order 7"


def test_send_order_sms_success():
    """Отправка SMS-уведомления."""
    with patch("time.sleep", return_value=None):
        result = send_order_sms(7, "+79991234567")
        assert result == "SMS sent to +79991234567 for order 7"


def test_dead_letter_handler():
    """Запись задачи в Dead Letter Queue (DLQ)."""
    mock_redis = MagicMock()
    with (
        patch("app.tasks.orders.redis_client", mock_redis),
        patch("app.tasks.orders.is_redis_available", return_value=True),
    ):
        result = dead_letter_handler(15, "test@sirius.ru", "Network failure")
        assert "DLQ recorded for order 15" in result
        mock_redis.lpush.assert_called_once()


def test_aggregate_order_statistics():
    """Периодическая задача агрегации статистики (Celery Beat)."""
    mock_redis = MagicMock()
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.count.return_value = 42
    mock_query.filter.return_value.count.return_value = 10
    mock_db.query.return_value = mock_query

    with (
        patch("app.database.SessionLocal", return_value=mock_db),
        patch("app.tasks.orders.redis_client", mock_redis),
        patch("app.tasks.orders.is_redis_available", return_value=True),
    ):
        stats = aggregate_order_statistics()
        assert stats["status"] == "ok"
        assert stats["total_orders"] == 42
        assert stats["processing_orders"] == 10
        mock_redis.set.assert_called_once()
