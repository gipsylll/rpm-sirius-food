"""
Тесты для gRPC микросервиса доставки и gRPC клиента (Практическая работа № 6).

Проверяет:
- Unary RPC: AssignCourier, CompleteDelivery, GetDelivery
- Обработку сетевых сбоев и таймаутов (UNAVAILABLE -> ConnectionError, DEADLINE_EXCEEDED -> TimeoutError)
- Server Streaming (TrackDelivery на 9 баллов)
- Bidirectional Streaming (ChatWithCourier на 10 баллов)
- Интеграцию GrpcDeliveryRepository в монолит
"""

from unittest.mock import MagicMock, patch

import grpc
import pytest

import delivery_pb2
from app.exceptions import NotFoundError
from app.modules.delivery.grpc_client import DeliveryGrpcClient
from app.modules.delivery.repository import GrpcDeliveryRepository
from delivery_server import DeliveryServiceServicer


def test_servicer_assign_courier_success():
    """Тест успешного назначения курьера через DeliveryServiceServicer."""
    servicer = DeliveryServiceServicer()
    request = delivery_pb2.AssignCourierRequest(order_id=1, courier_id=2)
    context = MagicMock()

    mock_db = MagicMock()
    mock_order = MagicMock()
    mock_order.id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = mock_order

    with patch("delivery_server.SessionLocal", return_value=mock_db):
        response = servicer.AssignCourier(request, context)
        assert response.status == "in_progress"
        assert context.abort.call_count == 0


def test_servicer_assign_courier_not_found():
    """Тест ошибки NOT_FOUND при отсутствии заказа."""
    servicer = DeliveryServiceServicer()
    request = delivery_pb2.AssignCourierRequest(order_id=999, courier_id=2)
    context = MagicMock()

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with patch("delivery_server.SessionLocal", return_value=mock_db):
        servicer.AssignCourier(request, context)
        context.abort.assert_called_once_with(
            grpc.StatusCode.NOT_FOUND, "Заказ 999 не найден"
        )


def test_servicer_complete_delivery_success():
    """Тест завершения доставки в сервисе."""
    servicer = DeliveryServiceServicer()
    request = delivery_pb2.CompleteDeliveryRequest(delivery_id=10)
    context = MagicMock()

    mock_db = MagicMock()
    mock_delivery = MagicMock()
    mock_delivery.id = 10
    mock_delivery.order_id = 5
    mock_order = MagicMock()
    mock_order.id = 5

    def query_mock(model):
        m = MagicMock()
        from app.models import Order

        if model is Order:
            m.filter.return_value.first.return_value = mock_order
        else:
            m.filter.return_value.first.return_value = mock_delivery
        return m

    mock_db.query.side_effect = query_mock

    with patch("delivery_server.SessionLocal", return_value=mock_db):
        response = servicer.CompleteDelivery(request, context)
        assert response.status == "completed"
        assert mock_delivery.status == "completed"


def test_servicer_server_streaming_track_delivery():
    """Тест Server Streaming (TrackDelivery — 9 баллов)."""
    servicer = DeliveryServiceServicer()
    request = delivery_pb2.TrackDeliveryRequest(delivery_id=10)
    context = MagicMock()

    with patch("time.sleep", return_value=None):
        statuses = list(servicer.TrackDelivery(request, context))
        assert len(statuses) >= 4
        status_names = [s.status for s in statuses]
        assert "in_progress" in status_names
        assert "delivered" in status_names


def test_servicer_bidirectional_streaming_chat():
    """Тест Bidirectional Streaming (ChatWithCourier — 10 баллов)."""
    servicer = DeliveryServiceServicer()
    context = MagicMock()

    messages = [
        delivery_pb2.ChatMessage(
            delivery_id=10,
            sender_role="customer",
            message="Привет, где вы?",
            timestamp="12:00:00",
        ),
        delivery_pb2.ChatMessage(
            delivery_id=10,
            sender_role="customer",
            message="Код домофона 42",
            timestamp="12:01:00",
        ),
    ]

    replies = list(servicer.ChatWithCourier(iter(messages), context))
    assert len(replies) == 2
    assert replies[0].sender_role == "courier"
    assert "везу" in replies[0].message or "подхожу" in replies[0].message
    assert "домофон" in replies[1].message


def test_grpc_client_error_mapping():
    """Тест трансляции ошибок gRPC в доменные исключения монолита."""
    client = DeliveryGrpcClient()

    class FakeRpcError(grpc.RpcError):
        def __init__(self, code, details):
            self._code = code
            self._details = details

        def code(self):
            return self._code

        def details(self):
            return self._details

    client.stub.AssignCourier = MagicMock(
        side_effect=FakeRpcError(grpc.StatusCode.NOT_FOUND, "Delivery missing")
    )
    with pytest.raises(NotFoundError):
        client.assign_courier(1, 2)

    client.stub.AssignCourier = MagicMock(
        side_effect=FakeRpcError(grpc.StatusCode.UNAVAILABLE, "Connect failed")
    )
    with pytest.raises(ConnectionError) as exc_info:
        client.assign_courier(1, 2)
    assert "недоступен" in str(exc_info.value)

    client.stub.AssignCourier = MagicMock(
        side_effect=FakeRpcError(grpc.StatusCode.DEADLINE_EXCEEDED, "Timeout")
    )
    with pytest.raises(TimeoutError) as exc_info:
        client.assign_courier(1, 2)
    assert "таймаут" in str(exc_info.value)


def test_grpc_delivery_repository_adapter():
    """Тест работы GrpcDeliveryRepository как адаптера к DeliveryGrpcClient."""
    mock_client = MagicMock()
    mock_client.assign_courier.return_value = {
        "delivery_id": 77,
        "status": "in_progress",
    }
    mock_client.complete_delivery.return_value = {"status": "completed"}

    mock_db = MagicMock()
    repo = GrpcDeliveryRepository(db=mock_db, client=mock_client)

    delivery_id = repo.save_delivery(order_id=5, courier_id=3)
    assert delivery_id == 77
    mock_client.assign_courier.assert_called_once_with(5, 3)

    mock_delivery = MagicMock()
    mock_delivery.id = 77
    repo.mark_completed(mock_delivery)
    mock_client.complete_delivery.assert_called_once_with(77)
