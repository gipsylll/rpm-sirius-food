"""
Слой бизнес-логики заказов.

Не зависит от веб-фреймворка и механизмов хранения данных.
Репозиторий передаётся в конструктор (инверсия зависимостей).
"""

from app.exceptions import BusinessRuleError, NotFoundError
from app.modules.orders.repository import OrderRepository


class OrderService:
    """Сценарий оформления заказа."""

    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(self, user_id: int, item_id: int, quantity: int) -> int:
        """
        Исполнение сценария оформления заказа.

        Возвращает идентификатор созданного заказа.
        Возбуждает доменное исключение при нарушении бизнес-правил.
        """
        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if not item.is_available:
            raise BusinessRuleError("Блюдо недоступно")

        total_cost = item.price * quantity
        if user.balance < total_cost:
            raise BusinessRuleError("Недостаточно средств на балансе студента")

        user.balance -= total_cost
        self.repository.update_user_balance(user, user.balance)
        return self.repository.save_order(user_id, item_id, quantity)
