from app.exceptions import BusinessRuleError, NotFoundError
from app.modules.orders.repository import (
    InMemoryOrderRepository,
    MenuItemRecord,
    UserRecord,
)
from app.modules.orders.service import OrderService


def _service() -> tuple[OrderService, InMemoryOrderRepository]:
    repository = InMemoryOrderRepository()
    repository.users[1] = UserRecord(
        id=1,
        email="student@sirius.ru",
        phone=None,
        balance=100.0,
    )
    repository.items[5] = MenuItemRecord(
        id=5,
        name="Борщ",
        price=40.0,
        is_available=True,
    )
    return OrderService(repository), repository


def test_create_order_debits_balance_and_returns_id():
    service, repository = _service()

    order_id = service.create_order(user_id=1, item_id=5, quantity=2)

    assert order_id == 1
    assert repository.users[1].balance == 20.0
    assert repository.orders[1].status == "processing"
    assert repository.orders[1].quantity == 2


def test_create_order_rejects_unknown_user():
    service, repository = _service()

    try:
        service.create_order(user_id=99, item_id=5, quantity=1)
    except NotFoundError as exc:
        assert str(exc) == "Пользователь не найден"
    else:
        raise AssertionError("ожидалась ошибка")

    assert repository.orders == {}


def test_create_order_rejects_unknown_item():
    service, _repository = _service()

    try:
        service.create_order(user_id=1, item_id=99, quantity=1)
    except NotFoundError as exc:
        assert str(exc) == "Блюдо не найдено"
    else:
        raise AssertionError("ожидалась ошибка")


def test_create_order_rejects_unavailable_item_without_debit():
    service, repository = _service()
    repository.items[5].is_available = False

    try:
        service.create_order(user_id=1, item_id=5, quantity=1)
    except BusinessRuleError as exc:
        assert str(exc) == "Блюдо недоступно"
    else:
        raise AssertionError("ожидалась ошибка")

    assert repository.users[1].balance == 100.0
    assert repository.orders == {}


def test_create_order_rejects_insufficient_balance():
    service, repository = _service()

    try:
        service.create_order(user_id=1, item_id=5, quantity=3)
    except BusinessRuleError as exc:
        assert str(exc) == "Недостаточно средств на балансе студента"
    else:
        raise AssertionError("ожидалась ошибка")

    assert repository.users[1].balance == 100.0
    assert repository.orders == {}
