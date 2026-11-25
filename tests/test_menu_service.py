from app.exceptions import BusinessRuleError, NotFoundError
from app.modules.menu.repository import InMemoryMenuRepository, MenuItemRecord
from app.modules.menu.service import MenuService


def test_create_item_stores_available_dish():
    repository = InMemoryMenuRepository()
    service = MenuService(repository)

    item_id = service.create_item("Борщ", 40.0)

    assert item_id == 1
    assert repository.items[1].is_available is True
    assert repository.items[1].price == 40.0


def test_create_item_rejects_duplicate_name():
    repository = InMemoryMenuRepository()
    service = MenuService(repository)
    service.create_item("Борщ", 40.0)

    try:
        service.create_item("Борщ", 50.0)
    except BusinessRuleError as exc:
        assert str(exc) == "Блюдо с таким названием уже существует"
    else:
        raise AssertionError("ожидалась ошибка")

    assert len(repository.items) == 1


def test_update_item_changes_only_given_fields():
    repository = InMemoryMenuRepository()
    repository.items[3] = MenuItemRecord(
        id=3, name="Борщ", price=40.0, is_available=True
    )
    service = MenuService(repository)

    saved_id = service.update_item(3, name=None, price=55.0, is_available=False)

    assert saved_id == 3
    assert repository.items[3].name == "Борщ"
    assert repository.items[3].price == 55.0
    assert repository.items[3].is_available is False


def test_update_item_rejects_missing_dish():
    service = MenuService(InMemoryMenuRepository())

    try:
        service.update_item(3, name="Суп", price=None, is_available=None)
    except NotFoundError as exc:
        assert str(exc) == "Блюдо не найдено"
    else:
        raise AssertionError("ожидалась ошибка")
