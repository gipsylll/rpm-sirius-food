"""
Тесты безопасности (Лабораторная работа № 3).

Проверяют:
1. Отсутствие токена -> 401 Unauthorized
2. Невалидный токен -> 401 Unauthorized
3. Нарушение ролевой модели (RBAC: студент пытается открыть кухню или изменить меню) -> 403 Forbidden
4. Защита от IDOR: студент не может отменить чужой заказ -> 403 Forbidden
5. Успешная отмена собственного заказа -> 200 OK
6. Защита от IDOR: пользователь не может пополнить чужой баланс -> 403 Forbidden
7. Ограничение частоты запросов (Rate Limiting) -> 429 Too Many Requests
8. Ротация refresh-токенов (Refresh Token Rotation) и пресечение повторного использования токенов
9. Надежное хеширование паролей (bcrypt)
"""

import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.core.security import hash_password, verify_password
from app.main import app
from app.modules.auth.repository import create_auth_repository
from app.modules.menu.repository import create_menu_repository
from app.modules.orders.repository import create_order_repository
from app.modules.users.repository import create_user_repository


@pytest.fixture(autouse=True)
def reset_repositories(monkeypatch):
    """Сбрасывает состояние in-memory репозиториев перед каждым тестом."""
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")

    user_repo = create_user_repository(None)
    user_repo.users.clear()
    user_repo._next_id = 1

    menu_repo = create_menu_repository(None)
    menu_repo.items.clear()
    menu_repo.cache.clear()
    menu_repo._next_id = 1

    order_repo = create_order_repository(None)
    order_repo.orders.clear()
    order_repo.users = user_repo.users
    order_repo.items = menu_repo.items
    order_repo._next_order_id = 1

    auth_repo = create_auth_repository(None)
    auth_repo.tokens.clear()
    auth_repo._next_id = 1

    from app.core.rate_limit import _memory_counters

    _memory_counters.clear()

    try:
        from app.core.redis import redis_client

        for key in redis_client.scan_iter("rate_limit:*"):
            redis_client.delete(key)
    except Exception:
        ...


@pytest.fixture
def client():
    return TestClient(app)


def test_access_without_token_returns_401(client):
    """Сценарий 1: Запрос к защищенному эндпоинту без токена возвращает 401."""
    response = client.post("/orders/create", json={"item_id": 1, "quantity": 1})
    assert response.status_code == 401
    assert "Not authenticated" in response.text or "Неверный токен" in response.text


def test_access_with_invalid_token_returns_401(client):
    """Запрос с поддельным или испорченным токеном возвращает 401."""
    headers = {"Authorization": "Bearer invalid.fake.token"}
    response = client.post(
        "/orders/create",
        json={"item_id": 1, "quantity": 1},
        headers=headers,
    )
    assert response.status_code == 401


def test_student_cannot_access_kitchen_orders_rbac_403(client):
    """Сценарий 4: Студент не может получить доступ к заказам кухни (требуется роль cook)."""
    user_repo = create_user_repository(None)
    user_id, _ = user_repo.save_user(
        email="student@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("password123"),
        role="student",
    )

    token = create_access_token(user_id=user_id, role="student")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/orders/kitchen", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"


def test_cook_can_access_kitchen_orders_success(client):
    """Повар имеет доступ к кухне."""
    user_repo = create_user_repository(None)
    user_id, _ = user_repo.save_user(
        email="chef@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("password123"),
        role="cook",
    )

    token = create_access_token(user_id=user_id, role="cook")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/orders/kitchen", headers=headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_student_cannot_modify_menu_items_403(client):
    """Студент не может создавать или изменять блюда меню."""
    user_repo = create_user_repository(None)
    user_id, _ = user_repo.save_user(
        email="student2@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("password123"),
        role="student",
    )

    token = create_access_token(user_id=user_id, role="student")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/menu/items",
        json={"name": "Каша", "price": 100.0, "category_id": 1},
        headers=headers,
    )
    assert response.status_code == 403


def test_student_cannot_cancel_other_student_order_idor_403(client):
    """Сценарий 3 (Защита от IDOR): Студент Б не может отменить заказ Студента А."""
    user_repo = create_user_repository(None)
    user_a_id, _ = user_repo.save_user(
        email="student_a@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("password123"),
        role="student",
    )
    user_b_id, _ = user_repo.save_user(
        email="student_b@sirius.ru",
        phone="0987654321",
        password_hash=hash_password("password123"),
        role="student",
    )

    menu_repo = create_menu_repository(None)
    item_id = menu_repo.save_item(name="Суп", price=50.0)

    # Студент А создает заказ
    order_repo = create_order_repository(None)
    order_id = order_repo.save_order(user_id=user_a_id, item_id=item_id, quantity=1)

    # Студент Б пытается отменить заказ Студента А
    token_b = create_access_token(user_id=user_b_id, role="student")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    response = client.post(f"/orders/{order_id}/cancel", headers=headers_b)
    assert response.status_code == 403
    assert "не имеет прав" in response.json()["detail"]


def test_student_can_cancel_own_order_success(client):
    """Студент успешно может отменить свой собственный заказ."""
    user_repo = create_user_repository(None)
    user_id, _ = user_repo.save_user(
        email="student_owner@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("password123"),
        role="student",
    )

    menu_repo = create_menu_repository(None)
    item_id = menu_repo.save_item(name="Борщ", price=60.0)

    order_repo = create_order_repository(None)
    order_id = order_repo.save_order(user_id=user_id, item_id=item_id, quantity=1)

    token = create_access_token(user_id=user_id, role="student")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(f"/orders/{order_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_user_cannot_topup_other_user_balance_idor_403(client):
    """Защита от IDOR в users: Студент не может пополнить баланс другого студента."""
    user_repo = create_user_repository(None)
    user1_id, _ = user_repo.save_user("user1@sirius.ru", "1111111111", role="student")
    user2_id, _ = user_repo.save_user("user2@sirius.ru", "2222222222", role="student")

    token1 = create_access_token(user_id=user1_id, role="student")
    headers1 = {"Authorization": f"Bearer {token1}"}

    response = client.post(f"/users/{user2_id}/topup?amount=500", headers=headers1)
    assert response.status_code == 403
    assert "чужого пользователя" in response.json()["detail"]


def test_rate_limiting_login_returns_429(client):
    """Сценарий 5 (Бонус): 6 вызовов подряд POST /auth/login приводят к HTTP 429."""
    for i in range(5):
        res = client.post(
            "/auth/login",
            json={"email": "wrong@sirius.ru", "password": "wrongpassword"},
        )
        assert res.status_code in (401, 200)

    # 6-й запрос должен превысить лимит и получить 429
    res_6 = client.post(
        "/auth/login",
        json={"email": "wrong@sirius.ru", "password": "wrongpassword"},
    )
    assert res_6.status_code == 429
    assert "Too many requests" in res_6.text


def test_refresh_token_rotation_and_reuse_detection(client):
    """
    Тест Refresh Token Rotation (10 баллов):
    1. Логин выдает пару токенов.
    2. Вызов /auth/refresh выдает НОВУЮ пару и отзывает старый refresh-токен.
    3. Повторный вызов /auth/refresh со СТАРЫМ токеном сбрасывает все сессии пользователя.
    """
    user_repo = create_user_repository(None)
    user_repo.save_user(
        email="rotate_user@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("secretpass"),
        role="student",
    )

    # 1. Логин
    login_res = client.post(
        "/auth/login",
        json={"email": "rotate_user@sirius.ru", "password": "secretpass"},
    )
    assert login_res.status_code == 200
    tokens = login_res.json()
    first_refresh = tokens["refresh_token"]

    # 2. Обновление токена (Rotation)
    refresh_res = client.post(
        "/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert refresh_res.status_code == 200
    new_tokens = refresh_res.json()
    second_refresh = new_tokens["refresh_token"]
    assert first_refresh != second_refresh

    # 3. Повторная попытка использования старого токена (Симуляция атаки перехвата токена)
    reuse_res = client.post(
        "/auth/refresh",
        json={"refresh_token": first_refresh},
    )
    assert reuse_res.status_code == 401
    assert "повторного использования" in reuse_res.json()["detail"]


def test_passwords_are_hashed_with_bcrypt():
    """Пароли не хранятся в открытом виде и проверяются функцией verify_password."""
    raw = "MySuperSecretPassword"
    hashed = hash_password(raw)
    assert hashed != raw
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password(raw, hashed) is True
    assert verify_password("wrong", hashed) is False
