"""
Инфраструктурный слой меню.

Реализует стратегию Cache-Aside на Redis:
- Чтение всего меню из Redis (ключ menu:all, TTL 300 секунд)
- Чтение блюд по категории из Redis (ключ menu:category:{id}, TTL 600 секунд)
- Защита от Cache Stampede через распределенную блокировку (lock:menu:all)
- Событийная инвалидация кеша при добавлении/изменении блюд
- Прогрев кеша (Cache Warm-Up) при старте приложения
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.core.redis import redis_client
from app.models import MenuItem

logger = logging.getLogger(__name__)


@dataclass
class MenuItemRecord:
    id: int
    name: str
    price: float
    is_available: bool = True
    category_id: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MenuRepository(ABC):
    """Контракт хранилища меню. Реализации взаимозаменяемы."""

    @abstractmethod
    def get_by_name(self, name: str):
        """Поиск блюда по названию."""

    @abstractmethod
    def get_by_id(self, item_id: int):
        """Поиск блюда по идентификатору."""

    @abstractmethod
    def save_item(self, name: str, price: float, category_id: int = 1) -> int:
        """Создание блюда. Возвращает идентификатор."""

    @abstractmethod
    def save_changes(self, item) -> int:
        """Фиксация изменённого блюда. Возвращает идентификатор."""

    @abstractmethod
    def get_all(self) -> list:
        """Возвращает всё меню с использованием Cache-Aside стратегии."""

    @abstractmethod
    def get_by_category(self, category_id: int) -> list:
        """Возвращает блюда указанной категории с использованием кеша."""

    @abstractmethod
    def invalidate_cache(self) -> None:
        """Сбрасывает кеш меню и категорий."""

    @abstractmethod
    def warm_up_cache(self) -> None:
        """Выполняет прогрев кеша при старте сервиса."""


class SqlAlchemyMenuRepository(MenuRepository):
    """Реализация хранилища на PostgreSQL через SQLAlchemy ORM с Cache-Aside в Redis."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, name: str):
        return self.db.query(MenuItem).filter(MenuItem.name == name).first()

    def get_by_id(self, item_id: int):
        return self.db.query(MenuItem).filter(MenuItem.id == item_id).first()

    def save_item(self, name: str, price: float, category_id: int = 1) -> int:
        new_item = MenuItem(
            name=name,
            price=price,
            is_available=True,
            category_id=category_id,
        )
        self.db.add(new_item)
        self.db.commit()
        self.db.refresh(new_item)
        return new_item.id

    def save_changes(self, item) -> int:
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item.id

    def _fetch_all_from_db(self) -> list[MenuItem]:
        return self.db.query(MenuItem).all()

    def _serialize_items(self, items: list[MenuItem]) -> str:
        data = [
            {
                "id": i.id,
                "name": i.name,
                "price": float(i.price),
                "is_available": i.is_available,
                "category_id": getattr(i, "category_id", 1),
            }
            for i in items
        ]
        return json.dumps(data)

    def get_all(self) -> list:
        """
        Cache-Aside с защитой от Cache Stampede:
        1. Проверяем Redis (menu:all)
        2. При промахе захватываем distributed mutex lock:menu:all
        3. Повторно проверяем кеш (double check)
        4. Если кеша все еще нет — читаем БД, пишем в Redis с TTL=300с
        """
        cache_key = "menu:all"

        # 1. Попытка быстрого чтения из кеша
        try:
            cached_data = redis_client.get(cache_key)
            if cached_data:
                items_data = json.loads(cached_data)
                return [MenuItem(**item) for item in items_data]
        except (redis.RedisError, ConnectionError, OSError) as exc:
            logger.warning("Ошибка чтения кеша меню из Redis: %s", exc)

        # 2. Защита от Cache Stampede через распределенный lock
        lock_acquired = False
        try:
            # Блокировка на 5 секунд с таймаутом ожидания 2 секунды
            lock = redis_client.lock("lock:menu:all", timeout=5, blocking_timeout=2)
            lock_acquired = lock.acquire()
            if lock_acquired:
                # Double-check locking: пока ждали lock, другой воркер мог успеть закешировать
                cached_data = redis_client.get(cache_key)
                if cached_data:
                    items_data = json.loads(cached_data)
                    return [MenuItem(**item) for item in items_data]

                # Читаем из БД
                items = self._fetch_all_from_db()
                # Сохраняем в Redis с TTL 300 секунд (5 минут)
                redis_client.setex(cache_key, 300, self._serialize_items(items))
                return items
        except (redis.RedisError, ConnectionError, OSError) as exc:
            logger.warning("Ошибка распределенной блокировки Redis: %s", exc)
        finally:
            if lock_acquired:
                try:
                    lock.release()
                except Exception:
                    pass

        # Fallback при недоступности Redis или таймауте блокировки
        return self._fetch_all_from_db()

    def get_by_category(self, category_id: int) -> list:
        """
        Кеширование категорий меню с ключом menu:category:{id} и TTL 600 секунд (10 минут).
        """
        cache_key = f"menu:category:{category_id}"

        try:
            cached = redis_client.get(cache_key)
            if cached:
                items_data = json.loads(cached)
                return [MenuItem(**item) for item in items_data]
        except (redis.RedisError, ConnectionError, OSError):
            pass

        items = (
            self.db.query(MenuItem).filter(MenuItem.category_id == category_id).all()
        )

        try:
            redis_client.setex(cache_key, 600, self._serialize_items(items))
        except (redis.RedisError, ConnectionError, OSError):
            pass

        return items

    def invalidate_cache(self) -> None:
        """Событийная инвалидация кеша всего меню и категорий."""
        try:
            redis_client.delete("menu:all")
            # Очистка ключей категорий по паттерну
            cursor = 0
            while True:
                cursor, keys = redis_client.scan(
                    cursor=cursor, match="menu:category:*", count=50
                )
                if keys:
                    redis_client.delete(*keys)
                if cursor == 0:
                    break
        except (redis.RedisError, ConnectionError, OSError) as exc:
            logger.warning("Ошибка инвалидации кеша в Redis: %s", exc)

    def warm_up_cache(self) -> None:
        """Прогрев кеша при старте приложения."""
        try:
            items = self._fetch_all_from_db()
            if items:
                redis_client.setex("menu:all", 300, self._serialize_items(items))
                logger.info("Прогрев кеша меню успешно завершен (%d блюд)", len(items))
        except Exception as exc:
            logger.warning("Прогрев кеша пропущен (Redis или БД не готовы): %s", exc)


class InMemoryMenuRepository(MenuRepository):
    """Реализация хранилища в памяти с локальным имитатором Cache-Aside для unit-тестов."""

    def __init__(self) -> None:
        self.items: dict[int, MenuItemRecord] = {}
        self._next_id = 1
        self.cache: dict[str, str] = {}
        self.hit_count = 0
        self.miss_count = 0

    def get_by_name(self, name: str):
        for item in self.items.values():
            if item.name == name:
                return item
        return None

    def get_by_id(self, item_id: int):
        return self.items.get(item_id)

    def save_item(self, name: str, price: float, category_id: int = 1) -> int:
        item_id = self._next_id
        self._next_id += 1
        self.items[item_id] = MenuItemRecord(
            id=item_id,
            name=name,
            price=price,
            is_available=True,
            category_id=category_id,
        )
        return item_id

    def save_changes(self, item) -> int:
        return item.id

    def get_all(self) -> list:
        cache_key = "menu:all"
        if cache_key in self.cache:
            self.hit_count += 1
            data = json.loads(self.cache[cache_key])
            return [MenuItemRecord(**d) for d in data]

        self.miss_count += 1
        items = list(self.items.values())
        self.cache[cache_key] = json.dumps([i.to_dict() for i in items])
        return items

    def get_by_category(self, category_id: int) -> list:
        cache_key = f"menu:category:{category_id}"
        if cache_key in self.cache:
            self.hit_count += 1
            data = json.loads(self.cache[cache_key])
            return [MenuItemRecord(**d) for d in data]

        self.miss_count += 1
        items = [i for i in self.items.values() if i.category_id == category_id]
        self.cache[cache_key] = json.dumps([i.to_dict() for i in items])
        return items

    def invalidate_cache(self) -> None:
        self.cache.clear()

    def warm_up_cache(self) -> None:
        items = list(self.items.values())
        self.cache["menu:all"] = json.dumps([i.to_dict() for i in items])


_memory_repository: InMemoryMenuRepository | None = None


def create_menu_repository(db: Session | None = None) -> MenuRepository:
    """
    Точка подмены реализации.

    REPOSITORY_BACKEND=memory подключает общее in-memory-хранилище.
    Иначе используется PostgreSQL. service.py и router.py при этом не меняются.
    """
    global _memory_repository
    if os.getenv("REPOSITORY_BACKEND", "sqlalchemy") == "memory":
        if _memory_repository is None:
            _memory_repository = InMemoryMenuRepository()
        return _memory_repository
    if db is None:
        raise ValueError("Для SQL-репозитория нужна сессия базы данных")
    return SqlAlchemyMenuRepository(db)
