"""
Слой бизнес-логики доставки.

Не зависит от веб-фреймворка и механизмов хранения данных.
Репозиторий передаётся в конструктор (инверсия зависимостей).
"""

from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.delivery.repository import DeliveryRepository


class DeliveryService:
    """Сценарии назначения курьера и завершения доставки."""

    def __init__(self, repository: DeliveryRepository):
        self.repository = repository

    def assign_courier(self, order_id: int, courier_id: int) -> int:
        """Назначает курьера на оплаченный заказ. Возвращает id доставки."""
        order = self.repository.get_order(order_id)
        if not order:
            raise NotFoundError("Заказ не найден")

        if order.status != "paid":
            raise BusinessRuleError("Курьера можно назначить только на оплаченный заказ")

        courier = self.repository.get_user(courier_id)
        if not courier:
            raise NotFoundError("Курьер не найден")

        if courier.is_blocked:
            raise ForbiddenError("Курьер заблокирован и не может быть назначен")

        if self.repository.get_active_delivery(courier_id):
            raise BusinessRuleError("У курьера уже есть активная доставка")

        return self.repository.save_delivery(order_id, courier_id)

    def complete_delivery(self, delivery_id: int) -> None:
        """Завершает доставку и переводит заказ в статус delivered."""
        delivery = self.repository.get_delivery(delivery_id)
        if not delivery:
            raise NotFoundError("Доставка не найдена")

        if delivery.status == "completed":
            raise BusinessRuleError("Доставка уже завершена")

        if delivery.status == "cancelled":
            raise BusinessRuleError("Отменённую доставку нельзя завершить")

        self.repository.mark_completed(delivery)
