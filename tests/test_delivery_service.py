from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.delivery.repository import (
    DeliveryRecord,
    InMemoryDeliveryRepository,
    OrderRecord,
    UserRecord,
)
from app.modules.delivery.service import DeliveryService


def _repository() -> InMemoryDeliveryRepository:
    repository = InMemoryDeliveryRepository()
    repository.orders[7] = OrderRecord(id=7, status="paid")
    repository.users[4] = UserRecord(id=4, is_blocked=False)
    return repository


def test_assign_courier_creates_active_delivery():
    repository = _repository()
    service = DeliveryService(repository)

    delivery_id = service.assign_courier(order_id=7, courier_id=4)

    assert delivery_id == 1
    assert repository.deliveries[1].status == "in_progress"
    assert repository.deliveries[1].order_id == 7


def test_assign_courier_enforces_domain_rules():
    repository = _repository()
    service = DeliveryService(repository)

    try:
        service.assign_courier(order_id=99, courier_id=4)
    except NotFoundError as exc:
        assert str(exc) == "Заказ не найден"
    else:
        raise AssertionError("ожидалась ошибка")

    repository.orders[7].status = "processing"
    try:
        service.assign_courier(order_id=7, courier_id=4)
    except BusinessRuleError as exc:
        assert str(exc) == "Курьера можно назначить только на оплаченный заказ"
    else:
        raise AssertionError("ожидалась ошибка")

    repository.orders[7].status = "paid"
    try:
        service.assign_courier(order_id=7, courier_id=99)
    except NotFoundError as exc:
        assert str(exc) == "Курьер не найден"
    else:
        raise AssertionError("ожидалась ошибка")

    repository.users[4].is_blocked = True
    try:
        service.assign_courier(order_id=7, courier_id=4)
    except ForbiddenError as exc:
        assert str(exc) == "Курьер заблокирован и не может быть назначен"
    else:
        raise AssertionError("ожидалась ошибка")

    repository.users[4].is_blocked = False
    repository.deliveries[1] = DeliveryRecord(
        id=1,
        order_id=7,
        courier_id=4,
        status="in_progress",
    )
    try:
        service.assign_courier(order_id=7, courier_id=4)
    except BusinessRuleError as exc:
        assert str(exc) == "У курьера уже есть активная доставка"
    else:
        raise AssertionError("ожидалась ошибка")


def test_complete_delivery_marks_order_delivered():
    repository = _repository()
    service = DeliveryService(repository)
    delivery_id = service.assign_courier(order_id=7, courier_id=4)

    service.complete_delivery(delivery_id)

    assert repository.deliveries[delivery_id].status == "completed"
    assert repository.orders[7].status == "delivered"


def test_complete_delivery_rejects_finished_and_missing():
    repository = _repository()
    service = DeliveryService(repository)

    try:
        service.complete_delivery(50)
    except NotFoundError as exc:
        assert str(exc) == "Доставка не найдена"
    else:
        raise AssertionError("ожидалась ошибка")

    repository.deliveries[2] = DeliveryRecord(
        id=2,
        order_id=7,
        courier_id=4,
        status="completed",
    )
    try:
        service.complete_delivery(2)
    except BusinessRuleError as exc:
        assert str(exc) == "Доставка уже завершена"
    else:
        raise AssertionError("ожидалась ошибка")

    repository.deliveries[2].status = "cancelled"
    try:
        service.complete_delivery(2)
    except BusinessRuleError as exc:
        assert str(exc) == "Отменённую доставку нельзя завершить"
    else:
        raise AssertionError("ожидалась ошибка")
