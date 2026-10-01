"""
Слой бизнес-логики пользователей.

Не зависит от веб-фреймворка и механизмов хранения данных.
Репозиторий передаётся в конструктор (инверсия зависимостей).
"""

from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.users.repository import UserRepository


class UserService:
    """Сценарии регистрации и пополнения баланса."""

    def __init__(self, repository: UserRepository):
        self.repository = repository

    def ensure_email_available(self, email: str) -> None:
        """Уникальность email — правило предметной области, а не формата строки."""
        if self.repository.get_by_email(email):
            raise BusinessRuleError("Пользователь с таким email уже зарегистрирован")

    def register(self, email: str, phone: str | None) -> tuple[int, str]:
        """Создаёт пользователя с нулевым балансом. Возвращает id и email."""
        self.ensure_email_available(email)
        return self.repository.save_user(email, phone)

    def top_up(self, user_id: int, amount: float) -> float:
        """Пополняет баланс. Возвращает новое значение."""
        user = self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        if user.is_blocked:
            raise ForbiddenError("Пользователь заблокирован. Пополнение невозможно")

        if amount > 50000:
            raise BusinessRuleError("Максимальная сумма пополнения — 50000 рублей")

        user.balance += amount
        self.repository.update_balance(user, user.balance)
        return user.balance
