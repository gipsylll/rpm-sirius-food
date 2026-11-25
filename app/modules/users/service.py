"""
Слой бизнес-логики пользователей.

Не зависит от веб-фреймворка и механизмов хранения данных.
Репозиторий передаётся в конструктор (инверсия зависимостей).
"""

from decimal import Decimal

from app.core.security import hash_password
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

    def register(
        self,
        email: str,
        phone: str | None = None,
        password: str | None = None,
        role: str = "student",
    ) -> tuple[int, str]:
        """Создаёт пользователя с хешем пароля и ролью student. Возвращает id и email."""
        self.ensure_email_available(email)
        pwd_hash = hash_password(password) if password else None
        return self.repository.save_user(
            email=email,
            phone=phone,
            password_hash=pwd_hash,
            role=role,
        )

    def top_up(
        self,
        user_id: int,
        amount: float,
        current_user_id: int | None = None,
        is_admin: bool = False,
    ) -> float:
        """
        Пополняет баланс пользователя.
        Защита от IDOR: пользователь может пополнить только свой собственный баланс (или admin).
        """
        if current_user_id is not None and not is_admin and user_id != current_user_id:
            raise ForbiddenError("Нельзя пополнить баланс чужого пользователя")

        user = self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundError("Пользователь не найден")

        if getattr(user, "is_blocked", False):
            raise ForbiddenError("Пользователь заблокирован. Пополнение невозможно")

        if amount > 50000:
            raise BusinessRuleError("Максимальная сумма пополнения — 50000 рублей")

        user.balance = (
            user.balance + Decimal(str(amount))
            if isinstance(user.balance, Decimal)
            else user.balance + amount
        )
        self.repository.update_balance(user, user.balance)
        return user.balance
