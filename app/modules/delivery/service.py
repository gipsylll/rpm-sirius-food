"""
Слой бизнес-логики доставки.

Не зависит от веб-фреймворка и механизмов хранения данных.
Репозиторий передаётся в конструктор (инверсия зависимостей).
Защищает от IDOR (курьер не может завершить чужую доставку).
"""

from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.delivery.repository import DeliveryRepository


class DeliveryService:
    """Сценарии назначения курьера, выполнения и завершения доставки."""

    def __init__(self, repository: DeliveryRepository):
        self.repository = repository

    def assign_courier(self, order_id: int, courier_id: int) -> int:
        """Назначает курьера на оплаченный заказ. Возвращает id доставки."""
        order = self.repository.get_order(order_id)
        if not order:
            raise NotFoundError("Заказ не найден")

        if getattr(order, "status", None) != "paid":
            raise BusinessRuleError(
                "Курьера можно назначить только на оплаченный заказ"
            )

        courier = self.repository.get_user(courier_id)
        if not courier:
            raise NotFoundError("Курьер не найден")

        if getattr(courier, "is_blocked", False):
            raise ForbiddenError("Курьер заблокирован и не может быть назначен")

        if self.repository.get_active_delivery(courier_id):
            raise BusinessRuleError("У курьера уже есть активная доставка")

        return self.repository.save_delivery(order_id, courier_id)

    def complete_delivery(
        self,
        delivery_id: int,
        current_user_id: int | None = None,
        is_admin: bool = False,
    ) -> None:
        """
        Завершает доставку и переводит заказ в статус delivered.
        Защита от IDOR: курьер может завершить только назначенную ему доставку.
        """
        delivery = self.repository.get_delivery(delivery_id)
        if not delivery:
            raise NotFoundError("Доставка не найдена")

        if (
            current_user_id is not None
            and not is_admin
            and delivery.courier_id != current_user_id
        ):
            raise ForbiddenError(
                "Курьер может завершать только свою собственную доставку"
            )

        if delivery.status == "completed":
            raise BusinessRuleError("Доставка уже завершена")

        if delivery.status == "cancelled":
            raise BusinessRuleError("Отменённую доставку нельзя завершить")

        self.repository.mark_completed(delivery)

    def get_courier_deliveries(self, courier_id: int) -> list:
        """Возвращает историю и активные доставки курьера."""
        return self.repository.get_courier_deliveries(courier_id)

    def update_status(
        self,
        delivery_id: int,
        status: str,
        current_user_id: int | None = None,
        is_admin: bool = False,
    ) -> None:
        allowed = {
            "assigned": None,
            "picked_up": "assigned",
            "in_transit": "picked_up",
            "arrived": "in_transit",
            "delivered": "arrived",
        }
        if status not in allowed:
            raise BusinessRuleError("Недопустимый статус доставки")
        delivery = self.repository.get_delivery(delivery_id)
        if not delivery:
            raise NotFoundError("Доставка не найдена")
        if (
            current_user_id is not None
            and not is_admin
            and delivery.courier_id != current_user_id
        ):
            raise ForbiddenError("Курьер может менять только свою доставку")
        previous = delivery.status
        if status != "assigned" and previous not in (allowed[status], "in_progress"):
            raise BusinessRuleError(
                f"Статус {status} должен следовать за {allowed[status]}"
            )
        self.repository.update_status(delivery, status)

    def track_delivery(self, delivery_id: int):
        """Возвращает поток событий отслеживания статуса доставки."""
        return self.repository.track_delivery(delivery_id)
