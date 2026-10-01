"""
Слой бизнес-логики меню.

Не зависит от веб-фреймворка и механизмов хранения данных.
Репозиторий передаётся в конструктор (инверсия зависимостей).
"""

from app.exceptions import BusinessRuleError, NotFoundError
from app.modules.menu.repository import MenuRepository


class MenuService:
    """Сценарии создания и изменения блюд."""

    def __init__(self, repository: MenuRepository):
        self.repository = repository

    def create_item(self, name: str, price: float) -> int:
        """Создаёт блюдо. Название в меню должно быть уникальным."""
        if self.repository.get_by_name(name):
            raise BusinessRuleError("Блюдо с таким названием уже существует")
        return self.repository.save_item(name, price)

    def ensure_item_exists(self, item_id: int) -> None:
        """Нужен роутеру, чтобы проверить наличие блюда до технической валидации цены."""
        if not self.repository.get_by_id(item_id):
            raise NotFoundError("Блюдо не найдено")

    def update_item(
        self,
        item_id: int,
        name: str | None,
        price: float | None,
        is_available: bool | None,
    ) -> int:
        """Применяет переданные поля и возвращает идентификатор блюда."""
        item = self.repository.get_by_id(item_id)
        if not item:
            raise NotFoundError("Блюдо не найдено")

        if name is not None:
            item.name = name
        if price is not None:
            item.price = price
        if is_available is not None:
            item.is_available = is_available

        return self.repository.save_changes(item)
