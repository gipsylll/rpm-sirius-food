"""
Инфраструктурный слой пользователей.

Единственное место модуля, которое знает структуру SQL-таблицы users.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Role, User


@dataclass
class UserRecord:
    id: int
    email: str
    phone: str | None
    balance: float = 0.0
    is_blocked: bool = False
    password_hash: str | None = None
    role: str = "student"


class UserRepository(ABC):
    """Контракт хранилища пользователей. Реализации взаимозаменяемы."""

    @abstractmethod
    def get_by_email(self, email: str):
        """Поиск пользователя по адресу электронной почты."""

    @abstractmethod
    def get_by_id(self, user_id: int):
        """Поиск пользователя по идентификатору."""

    @abstractmethod
    def save_user(
        self,
        email: str,
        phone: str | None,
        password_hash: str | None = None,
        role: str = "student",
    ) -> tuple[int, str]:
        """Создание пользователя с нулевым балансом. Возвращает id и email."""

    @abstractmethod
    def update_balance(self, user, new_balance: float) -> None:
        """Фиксация нового баланса пользователя."""


class SqlAlchemyUserRepository(UserRepository):
    """Реализация хранилища на PostgreSQL через SQLAlchemy ORM."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str):
        return self.db.query(User).filter(User.email == email).first()

    def get_by_id(self, user_id: int):
        return self.db.query(User).filter(User.id == user_id).first()

    def _get_or_create_role(self, role_name: str) -> Role:
        role = self.db.query(Role).filter(Role.name == role_name).first()
        if not role:
            role = Role(name=role_name)
            self.db.add(role)
            self.db.commit()
            self.db.refresh(role)
        return role

    def save_user(
        self,
        email: str,
        phone: str | None,
        password_hash: str | None = None,
        role: str = "student",
    ) -> tuple[int, str]:
        role_obj = self._get_or_create_role(role)
        new_user = User(
            email=email,
            phone=phone,
            balance=0.0,
            is_blocked=False,
            password_hash=password_hash,
            role_id=role_obj.id,
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user.id, new_user.email

    def update_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)


class InMemoryUserRepository(UserRepository):
    """Реализация хранилища в памяти. Подходит для unit-тестов без СУБД."""

    def __init__(self) -> None:
        self.users: dict[int, UserRecord] = {}
        self._next_id = 1

    def get_by_email(self, email: str):
        for user in self.users.values():
            if user.email == email:
                return user
        return None

    def get_by_id(self, user_id: int):
        return self.users.get(user_id)

    def save_user(
        self,
        email: str,
        phone: str | None,
        password_hash: str | None = None,
        role: str = "student",
    ) -> tuple[int, str]:
        user_id = self._next_id
        self._next_id += 1
        self.users[user_id] = UserRecord(
            id=user_id,
            email=email,
            phone=phone,
            balance=0.0,
            is_blocked=False,
            password_hash=password_hash,
            role=role,
        )
        return user_id, email

    def update_balance(self, user, new_balance: float) -> None:
        user.balance = new_balance


_memory_repository: InMemoryUserRepository | None = None


def create_user_repository(db: Session | None = None) -> UserRepository:
    """
    Точка подмены реализации.

    REPOSITORY_BACKEND=memory подключает общее in-memory-хранилище.
    Иначе используется PostgreSQL. service.py и router.py при этом не меняются.
    """
    global _memory_repository
    if os.getenv("REPOSITORY_BACKEND", "sqlalchemy") == "memory":
        if _memory_repository is None:
            _memory_repository = InMemoryUserRepository()
        return _memory_repository
    if db is None:
        raise ValueError("Для SQL-репозитория нужна сессия базы данных")
    return SqlAlchemyUserRepository(db)
