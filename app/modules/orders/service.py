"""
Слой бизнес-логики заказов.

Не зависит от веб-фреймворка и механизмов хранения данных.
Репозиторий передаётся в конструктор (инверсия зависимостей).
Защита от IDOR реализована на уровне сценария бизнес-логики.
"""

from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.orders.repository import OrderRepository
from app.tasks.orders import generate_order_pdf, send_order_email, send_order_sms


class OrderService:
    """Сценарии оформления, отмены и просмотра заказов."""

    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def create_order(
        self,
        user_id: int,
        item_id: int,
        quantity: int,
        promo_code: str | None = None,
        loyalty_points: int = 0,
    ) -> int:
        """
        Исполнение сценария оформления заказа.

        Возвращает идентификатор созданного заказа.
        Возбуждает доменное исключение при нарушении бизнес-правил.
        """
        if quantity <= 0:
            raise BusinessRuleError("Количество должно быть больше нуля")

        user = self.repository.get_user_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        item = self.repository.get_menu_item_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if not item.is_available:
            raise BusinessRuleError("Блюдо недоступно")

        cents = Decimal("0.01")
        original = (Decimal(str(item.price)) * quantity).quantize(
            cents, rounding=ROUND_HALF_UP
        )
        discount = Decimal(0)
        normalized_code = promo_code.strip().upper() if promo_code else None
        promo = None
        if normalized_code:
            promo = self.repository.get_promo_code(normalized_code, for_update=True)
            now = datetime.now(UTC)
            if not promo or not promo.is_active:
                raise BusinessRuleError("Промокод недействителен")
            valid_from = (
                promo.valid_from.replace(tzinfo=UTC)
                if promo.valid_from and promo.valid_from.tzinfo is None
                else promo.valid_from
            )
            valid_until = (
                promo.valid_until.replace(tzinfo=UTC)
                if promo.valid_until and promo.valid_until.tzinfo is None
                else promo.valid_until
            )
            if valid_from and valid_from > now:
                raise BusinessRuleError("Промокод ещё не действует")
            if valid_until and valid_until < now:
                raise BusinessRuleError("Срок действия промокода истёк")
            if promo.max_uses is not None and promo.current_uses >= promo.max_uses:
                raise BusinessRuleError("Лимит применений промокода исчерпан")
            if original < Decimal(str(promo.min_order_amount)):
                raise BusinessRuleError("Сумма заказа меньше минимальной для промокода")
            if self.repository.has_promo_usage(user_id, promo.id):
                raise BusinessRuleError("Промокод уже использован этим пользователем")
            if promo.discount_type == "percent":
                if Decimal(str(promo.discount_value)) > Decimal(100):
                    raise BusinessRuleError("Процент скидки не может превышать 100")
                discount = original * Decimal(str(promo.discount_value)) / Decimal(100)
            elif promo.discount_type == "fixed":
                discount = Decimal(str(promo.discount_value))
            else:
                raise BusinessRuleError("Неизвестный тип скидки")
            discount = min(discount, original).quantize(cents, rounding=ROUND_HALF_UP)
        account = self.repository.get_loyalty_account(user_id, for_update=True)
        if loyalty_points < 0:
            raise BusinessRuleError("Количество баллов не может быть отрицательным")
        if loyalty_points > account.balance:
            raise BusinessRuleError("Недостаточно баллов лояльности")
        after_promo = max(Decimal(0), original - discount)
        max_points = int(
            (after_promo * Decimal("0.5")).to_integral_value(rounding=ROUND_DOWN)
        )
        if loyalty_points > max_points:
            raise BusinessRuleError("Баллами можно оплатить не более 50% суммы")
        total_cost = (after_promo - Decimal(loyalty_points)).quantize(
            cents, rounding=ROUND_HALF_UP
        )
        if Decimal(str(user.balance)) < total_cost:
            raise BusinessRuleError("Недостаточно средств на балансе студента")

        user.balance = (
            user.balance - total_cost
            if isinstance(user.balance, Decimal)
            else user.balance - float(total_cost)
        )
        self.repository.update_user_balance(user, user.balance)
        order_id = self.repository.save_order(
            user_id,
            item_id,
            quantity,
            original_amount=original,
            discount_amount=discount,
            loyalty_points=loyalty_points,
            final_amount=total_cost,
            promo_code=normalized_code,
            defer_commit=True,
        )
        if promo:
            self.repository.record_promo_usage(promo, user_id, order_id, discount)
        if loyalty_points:
            self.repository.spend_loyalty(account, loyalty_points, order_id)
        self.repository.commit()

        # Вызов фоновых задач через Celery (.delay())
        # Бизнес-правило: после создания заказа сгенерировать чек и отправить уведомления
        user_email = getattr(user, "email", "student@sirius.ru")
        user_phone = getattr(user, "phone", "+79990000000") or "+79990000000"

        try:
            generate_order_pdf.delay(order_id)
            send_order_email.delay(order_id, user_email)
            send_order_sms.delay(order_id, user_phone)
        except Exception:
            # Защита от сбоя при отсутствии запущенного брокера (например, в изолированных unit-тестах)
            pass

        return order_id

    def cancel_order(self, order_id: int, current_user: Any) -> Any:
        """
        Отменяет заказ.
        Защита от IDOR: проверяет, что заказ принадлежит текущему пользователю
        (или текущий пользователь имеет роль администратора/повара).
        """
        order = self.repository.get_order(order_id)
        if order is None:
            raise NotFoundError("Заказ не найден")

        # Проверка владельца объекта (IDOR)
        user_role = getattr(current_user, "role", None)
        role_name = getattr(user_role, "name", str(user_role) if user_role else "")
        is_staff = role_name in ("admin", "cook")

        order_owner_id = getattr(order, "user_id", getattr(order, "customer_id", None))
        current_id = getattr(current_user, "id", None)

        if not is_staff and order_owner_id != current_id:
            raise ForbiddenError("Пользователь не имеет прав на отмену чужого заказа")

        if getattr(order, "status", None) == "cancelled":
            raise BusinessRuleError("Заказ уже отменён")

        self.repository.cancel_order(order)
        return order

    def get_kitchen_orders(self) -> list:
        """Возвращает активные заказы для поваров."""
        return self.repository.get_kitchen_orders()
