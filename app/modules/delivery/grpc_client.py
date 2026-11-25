"""
gRPC-клиент для межсервисного взаимодействия с микросервисом доставки.

Выступает инфраструктурным адаптером между монолитом и микросервисом,
реализует обработку сетевых сбоев, таймаутов и трансляцию gRPC-статусов
в доменные ошибки Clean Architecture.
"""

import os
from collections.abc import Iterator
from typing import Any

import grpc

import delivery_pb2
import delivery_pb2_grpc
from app.core.config import settings
from app.exceptions import NotFoundError


class DeliveryGrpcClient:
    """Клиент для обращения к Delivery gRPC Server (порт 50051)."""

    def __init__(self, host: str | None = None, port: int | None = None):
        self.host = host or os.getenv("DELIVERY_GRPC_HOST", settings.DELIVERY_GRPC_HOST)
        self.port = port or int(
            os.getenv("DELIVERY_GRPC_PORT", settings.DELIVERY_GRPC_PORT)
        )
        self.channel = grpc.insecure_channel(f"{self.host}:{self.port}")
        self.stub = delivery_pb2_grpc.DeliveryServiceStub(self.channel)

    def assign_courier(self, order_id: int, courier_id: int) -> dict[str, Any]:
        """Назначение курьера через gRPC с таймаутом 5 секунд."""
        try:
            request = delivery_pb2.AssignCourierRequest(
                order_id=order_id, courier_id=courier_id
            )
            response = self.stub.AssignCourier(request, timeout=5)
            return {"delivery_id": response.delivery_id, "status": response.status}
        except grpc.RpcError as exc:
            self._handle_error(exc)

    def complete_delivery(self, delivery_id: int) -> dict[str, Any]:
        """Завершение доставки через gRPC с таймаутом 5 секунд."""
        try:
            request = delivery_pb2.CompleteDeliveryRequest(delivery_id=delivery_id)
            response = self.stub.CompleteDelivery(request, timeout=5)
            return {"status": response.status}
        except grpc.RpcError as exc:
            self._handle_error(exc)

    def get_delivery(self, order_id: int) -> dict[str, Any]:
        """Получение информации о доставке по ID заказа."""
        try:
            request = delivery_pb2.GetDeliveryRequest(order_id=order_id)
            response = self.stub.GetDelivery(request, timeout=5)
            return {
                "id": response.id,
                "status": response.status,
                "courier_id": response.courier_id,
            }
        except grpc.RpcError as exc:
            self._handle_error(exc)

    def track_delivery(self, delivery_id: int) -> Iterator[dict[str, str]]:
        """
        Server Streaming (9 баллов).
        Возвращает итератор по потоку событий изменения статуса заказа.
        """
        try:
            request = delivery_pb2.TrackDeliveryRequest(delivery_id=delivery_id)
            for item in self.stub.TrackDelivery(request):
                yield {
                    "delivery_id": item.delivery_id,
                    "status": item.status,
                    "description": item.description,
                    "timestamp": item.timestamp,
                }
        except grpc.RpcError as exc:
            self._handle_error(exc)

    def chat_with_courier(
        self, messages_stream: Iterator[dict[str, Any]]
    ) -> Iterator[dict[str, str]]:
        """
        Bidirectional Streaming (10 баллов).
        Принимает генератор сообщений от клиента и возвращает генератор ответов курьера.
        """

        def proto_generator():
            for m in messages_stream:
                yield delivery_pb2.ChatMessage(
                    delivery_id=m.get("delivery_id", 0),
                    sender_role=m.get("sender_role", "customer"),
                    message=m.get("message", ""),
                    timestamp=m.get("timestamp", ""),
                )

        try:
            responses = self.stub.ChatWithCourier(proto_generator())
            for resp in responses:
                yield {
                    "delivery_id": resp.delivery_id,
                    "sender_role": resp.sender_role,
                    "message": resp.message,
                    "timestamp": resp.timestamp,
                }
        except grpc.RpcError as exc:
            self._handle_error(exc)

    def _handle_error(self, exc: grpc.RpcError):
        """Трансляция gRPC статус-кодов в понятные системные исключения."""
        code = exc.code()
        details = exc.details() or ""
        if code == grpc.StatusCode.NOT_FOUND:
            raise NotFoundError(details or "Объект доставки не найден")
        if code == grpc.StatusCode.UNAVAILABLE:
            raise ConnectionError(
                f"Микросервис доставки (gRPC {self.host}:{self.port}) недоступен"
            )
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            raise TimeoutError(
                "Превышен таймаут ответа микросервиса доставки (5 секунд)"
            )
        raise RuntimeError(f"Ошибка gRPC ({code}): {details}")
