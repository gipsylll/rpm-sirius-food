from types import SimpleNamespace

from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
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


def test_create_order_allows_exact_balance():
    service, repository = _service()
    repository.users[1].balance = 80.0
    service.create_order(user_id=1, item_id=5, quantity=2)
    assert repository.users[1].balance == 0


def test_create_order_rejects_zero_and_negative_quantity():
    import pytest

    service, repository = _service()
    for quantity in (0, -1):
        with pytest.raises(BusinessRuleError):
            service.create_order(user_id=1, item_id=5, quantity=quantity)
    assert repository.users[1].balance == 100
    assert not repository.orders


def test_cancel_order_allows_owner_and_persists_cancelled_status():
    service, repository = _service()
    order_id = service.create_order(user_id=1, item_id=5, quantity=1)

    service.cancel_order(order_id, SimpleNamespace(id=1, role=None))

    assert repository.orders[order_id].status == "cancelled"


def test_cancel_order_rejects_different_user():
    service, repository = _service()
    order_id = service.create_order(user_id=1, item_id=5, quantity=1)

    import pytest

    with pytest.raises(ForbiddenError):
        service.cancel_order(order_id, SimpleNamespace(id=2, role=None))
    assert repository.orders[order_id].status == "processing"


def test_cancel_order_allows_staff_role():
    service, repository = _service()
    order_id = service.create_order(user_id=1, item_id=5, quantity=1)
    cook_role = SimpleNamespace(name="cook")

    service.cancel_order(order_id, SimpleNamespace(id=99, role=cook_role))

    assert repository.orders[order_id].status == "cancelled"


def test_cancel_order_rejects_missing_and_already_cancelled_orders():
    import pytest

    service, repository = _service()
    with pytest.raises(NotFoundError):
        service.cancel_order(999, SimpleNamespace(id=1, role=None))

    order_id = service.create_order(user_id=1, item_id=5, quantity=1)
    service.cancel_order(order_id, SimpleNamespace(id=1, role=None))
    with pytest.raises(BusinessRuleError):
        service.cancel_order(order_id, SimpleNamespace(id=1, role=None))
    assert repository.orders[order_id].status == "cancelled"
