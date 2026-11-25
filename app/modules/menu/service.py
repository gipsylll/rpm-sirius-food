"""
Слой бизнес-логики меню.

Не зависит от веб-фреймворка, механизмов хранения данных и системы кеширования.
Репозиторий передаётся в конструктор (инверсия зависимостей).
При изменении меню инициирует инвалидацию кеша через контракт репозитория.
"""

from app.exceptions import BusinessRuleError, NotFoundError
from app.modules.menu.repository import MenuRepository


class MenuService:
    """Сценарии создания, изменения и чтения блюд."""

    def __init__(self, repository: MenuRepository):
        self.repository = repository

    def create_item(self, name: str, price: float, category_id: int = 1) -> int:
        """Создаёт блюдо и инициирует сброс кеша. Название блюда должно быть уникальным."""
        if self.repository.get_by_name(name):
            raise BusinessRuleError("Блюдо с таким названием уже существует")
        item_id = self.repository.save_item(name, price, category_id)
        self.repository.invalidate_cache()
        return item_id

    def ensure_item_exists(self, item_id: int) -> None:
        """Проверяет наличие блюда."""
        if not self.repository.get_by_id(item_id):
            raise NotFoundError("Блюдо не найдено")

    def update_item(
        self,
        item_id: int,
        name: str | None,
        price: float | None,
        is_available: bool | None,
        category_id: int | None = None,
    ) -> int:
        """Применяет переданные поля, сбрасывает кеш и возвращает id блюда."""
        item = self.repository.get_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if name is not None:
            item.name = name
        if price is not None:
            item.price = price
        if is_available is not None:
            item.is_available = is_available
        if category_id is not None:
            item.category_id = category_id

        saved_id = self.repository.save_changes(item)
        self.repository.invalidate_cache()
        return saved_id

    def get_all_items(self) -> list:
        """Получает полный список блюд через репозиторий (с поддержкой кеша)."""
        return self.repository.get_all()

    def get_items_by_category(self, category_id: int) -> list:
        """Получает блюда конкретной категории через репозиторий."""
        return self.repository.get_by_category(category_id)
