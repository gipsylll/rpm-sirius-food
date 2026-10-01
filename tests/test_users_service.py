from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.users.repository import InMemoryUserRepository, UserRecord
from app.modules.users.service import UserService


def test_register_creates_user_with_zero_balance():
    repository = InMemoryUserRepository()
    service = UserService(repository)

    user_id, email = service.register("student@sirius.ru", "+79990001122")

    assert user_id == 1
    assert email == "student@sirius.ru"
    assert repository.users[1].balance == 0.0
    assert repository.users[1].is_blocked is False


def test_register_rejects_duplicate_email():
    repository = InMemoryUserRepository()
    service = UserService(repository)
    service.register("student@sirius.ru", None)

    try:
        service.register("student@sirius.ru", None)
    except BusinessRuleError as exc:
        assert str(exc) == "Пользователь с таким email уже зарегистрирован"
    else:
        raise AssertionError("ожидалась ошибка")

    assert len(repository.users) == 1


def test_top_up_increases_balance():
    repository = InMemoryUserRepository()
    repository.users[1] = UserRecord(
        id=1,
        email="student@sirius.ru",
        phone=None,
        balance=10.0,
    )
    service = UserService(repository)

    assert service.top_up(1, 50000) == 50010.0


def test_top_up_rejects_missing_blocked_and_oversized_amounts():
    repository = InMemoryUserRepository()
    repository.users[1] = UserRecord(
        id=1,
        email="student@sirius.ru",
        phone=None,
        balance=10.0,
        is_blocked=True,
    )
    service = UserService(repository)

    try:
        service.top_up(99, 100)
    except NotFoundError as exc:
        assert str(exc) == "Пользователь не найден"
    else:
        raise AssertionError("ожидалась ошибка")

    try:
        service.top_up(1, 100)
    except ForbiddenError as exc:
        assert str(exc) == "Пользователь заблокирован. Пополнение невозможно"
    else:
        raise AssertionError("ожидалась ошибка")

    repository.users[1].is_blocked = False
    try:
        service.top_up(1, 50000.01)
    except BusinessRuleError as exc:
        assert str(exc) == "Максимальная сумма пополнения — 50000 рублей"
    else:
        raise AssertionError("ожидалась ошибка")

    assert repository.users[1].balance == 10.0
