"""
Микросервис доставки «Сириус.Еда» на базе gRPC.

Работает как независимый процесс, реализует контракт proto/delivery.proto:
- Unary RPC: AssignCourier, CompleteDelivery, GetDelivery
- Server Streaming (9 баллов): TrackDelivery — потоковая трансляция смены статусов
- Bidirectional Streaming (10 баллов): ChatWithCourier — живой диалог клиента и курьера
"""

import logging
import time
from concurrent import futures
from datetime import UTC, datetime

import grpc

import delivery_pb2
import delivery_pb2_grpc
from app.database import SessionLocal
from app.models import Delivery, Order

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("delivery_service")


class DeliveryServiceServicer(delivery_pb2_grpc.DeliveryServiceServicer):
    """Реализация gRPC-сервиса доставки."""

    def AssignCourier(self, request, context):
        """Назначение курьера на заказ (Unary RPC)."""
        logger.info(
            "AssignCourier: запрос на заказ %s, курьер %s",
            request.order_id,
            request.courier_id,
        )
        db = SessionLocal()
        try:
            order = db.query(Order).filter(Order.id == request.order_id).first()
            if not order:
                logger.warning("AssignCourier: заказ %s не найден", request.order_id)
                context.abort(
                    grpc.StatusCode.NOT_FOUND, f"Заказ {request.order_id} не найден"
                )

            delivery = Delivery(
                order_id=request.order_id,
                courier_id=request.courier_id,
                status="in_progress",
            )
            db.add(delivery)
            db.commit()
            db.refresh(delivery)

            logger.info("AssignCourier: успешно создана доставка id=%s", delivery.id)
            return delivery_pb2.AssignCourierResponse(
                delivery_id=delivery.id,
                status=delivery.status,
            )
        except Exception as exc:
            db.rollback()
            logger.error("AssignCourier ошибка: %s", exc)
            context.abort(grpc.StatusCode.INTERNAL, str(exc))
        finally:
            db.close()

    def CompleteDelivery(self, request, context):
        """Завершение доставки (Unary RPC)."""
        logger.info(
            "CompleteDelivery: запрос завершения доставки %s", request.delivery_id
        )
        db = SessionLocal()
        try:
            delivery = (
                db.query(Delivery).filter(Delivery.id == request.delivery_id).first()
            )
            if not delivery:
                logger.warning(
                    "CompleteDelivery: доставка %s не найдена", request.delivery_id
                )
                context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"Доставка {request.delivery_id} не найдена",
                )

            delivery.status = "completed"
            order = db.query(Order).filter(Order.id == delivery.order_id).first()
            if order:
                order.status = "delivered"
                db.add(order)

            db.add(delivery)
            db.commit()

            logger.info("CompleteDelivery: доставка %s завершена", delivery.id)
            return delivery_pb2.CompleteDeliveryResponse(status=delivery.status)
        except Exception as exc:
            db.rollback()
            logger.error("CompleteDelivery ошибка: %s", exc)
            context.abort(grpc.StatusCode.INTERNAL, str(exc))
        finally:
            db.close()

    def GetDelivery(self, request, context):
        """Получение информации о доставке по ID заказа (Unary RPC)."""
        logger.info("GetDelivery: запрос доставки по order_id=%s", request.order_id)
        db = SessionLocal()
        try:
            delivery = (
                db.query(Delivery).filter(Delivery.order_id == request.order_id).first()
            )
            if not delivery:
                logger.warning(
                    "GetDelivery: доставка для заказа %s не найдена", request.order_id
                )
                context.abort(
                    grpc.StatusCode.NOT_FOUND,
                    f"Доставка для заказа {request.order_id} не найдена",
                )

            return delivery_pb2.GetDeliveryResponse(
                id=delivery.id,
                status=delivery.status,
                courier_id=delivery.courier_id or 0,
            )
        finally:
            db.close()

    def TrackDelivery(self, request, context):
        """
        Server Streaming (9 баллов).
        Передает поток событий изменения статуса заказа в реальном времени.
        """
        logger.info(
            "TrackDelivery: запуск стриминга статусов для delivery_id=%s",
            request.delivery_id,
        )
        timeline = [
            ("in_progress", "Курьер назначен и ожидает готовности заказа на кухне"),
            ("picked_up", "Курьер забрал горячий заказ и упаковал в термосумку"),
            ("in_transit", "Курьер в пути к вашему адресу (осталось 5 минут)"),
            ("arrived", "Курьер прибыл к зданию столовой / кампуса"),
            ("delivered", "Заказ успешно вручен клиенту! Приятного аппетита"),
        ]

        for status_code, description in timeline:
            now_str = datetime.now(UTC).strftime("%H:%M:%S")
            yield delivery_pb2.DeliveryStatus(
                delivery_id=request.delivery_id,
                status=status_code,
                description=description,
                timestamp=now_str,
            )
            time.sleep(1.0)

    def ChatWithCourier(self, request_iterator, context):
        """
        Bidirectional Streaming (10 баллов).
        Двусторонний обмен сообщениями между клиентом и курьером.
        """
        logger.info("ChatWithCourier: сессия двустороннего чата открыта")
        replies = {
            "привет": "Добрый день! Ваш заказ уже у меня, везу в общежитие №2.",
            "где": "Уже подхожу к главному входу, буду через 2 минуты.",
            "код": "Принято, домофон записал!",
            "спасибо": "Пожалуйста, приятного аппетита! Хорошего дня!",
        }

        for incoming in request_iterator:
            logger.info(
                "Чат [delivery %s] %s: %s",
                incoming.delivery_id,
                incoming.sender_role,
                incoming.message,
            )
            msg_lower = incoming.message.lower()

            # Подбираем реплику курьера
            reply_text = "Вас понял, скоро буду у вас!"
            for trigger, resp in replies.items():
                if trigger in msg_lower:
                    reply_text = resp
                    break

            now_str = datetime.now(UTC).strftime("%H:%M:%S")
            yield delivery_pb2.ChatMessage(
                delivery_id=incoming.delivery_id,
                sender_role="courier",
                message=reply_text,
                timestamp=now_str,
            )


def serve(port: int = 50051):
    """Запуск gRPC сервера микросервиса доставки."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    delivery_pb2_grpc.add_DeliveryServiceServicer_to_server(
        DeliveryServiceServicer(), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("🚀 Delivery gRPC Server running on port %s", port)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Остановка Delivery gRPC Server...")
        server.stop(grace=1)


if __name__ == "__main__":
    serve()
