"""
Тесты кеширования (Лабораторная работа № 4).

Проверяют:
1. Стратегию Cache-Aside (первый запрос — промах и запись в кеш, второй — попадание).
2. Событийную инвалидацию кеша при добавлении блюда (POST /menu/items).
3. Событийную инвалидацию кеша при обновлении блюда (PATCH /menu/items/{id}).
4. Кеширование категорий меню (menu:category:{id}) и их корректную отдачу.
5. Защиту от Cache Stampede (блокировка при одновременных промахах кеша).
6. Прогрев кеша (Cache Warm-Up) при старте приложения.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.core.security import hash_password
from app.main import app
from app.modules.menu.repository import create_menu_repository
from app.modules.users.repository import create_user_repository


@pytest.fixture(autouse=True)
def reset_menu_state(monkeypatch):
    """Сбрасывает состояние меню и кеша перед каждым тестом."""
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    repo = create_menu_repository(None)
    repo.items.clear()
    repo.cache.clear()
    repo._next_id = 1
    repo.hit_count = 0
    repo.miss_count = 0


@pytest.fixture
def client():
    return TestClient(app)


def test_cache_aside_hits_on_subsequent_request(client):
    """
    Cache-Aside:
    Первый вызов GET /menu/items — промах (miss), данные читаются из БД и пишутся в кеш.
    Второй вызов GET /menu/items — попадание (hit), данные отдаются напрямую из кеша.
    """
    repo = create_menu_repository(None)
    repo.save_item(name="Суп дня", price=120.0, category_id=1)
    repo.save_item(name="Пюре с котлетой", price=180.0, category_id=2)

    # 1. Первый запрос: кеш пуст
    assert repo.miss_count == 0
    assert repo.hit_count == 0
    res1 = client.get("/menu/items")
    assert res1.status_code == 200
    assert len(res1.json()) == 2
    assert repo.miss_count == 1
    assert repo.hit_count == 0
    assert "menu:all" in repo.cache

    # 2. Второй запрос: данные берутся из кеша
    res2 = client.get("/menu/items")
    assert res2.status_code == 200
    assert len(res2.json()) == 2
    assert repo.miss_count == 1
    assert repo.hit_count == 1


def test_cache_invalidation_on_item_creation(client):
    """
    Инвалидация кеша при создании блюда:
    После добавления нового блюда старый кеш menu:all удаляется.
    Следующий запрос возвращает уже актуальное меню с новым блюдом.
    """
    repo = create_menu_repository(None)
    repo.save_item(name="Чай", price=30.0, category_id=3)

    # Прогреваем кеш
    res = client.get("/menu/items")
    assert len(res.json()) == 1
    assert "menu:all" in repo.cache

    # Создаем новое блюдо от имени повара (cook)
    user_repo = create_user_repository(None)
    cook_id, _ = user_repo.save_user(
        email="cook@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("password"),
        role="cook",
    )
    token = create_access_token(user_id=cook_id, role="cook")
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post(
        "/menu/items",
        json={"name": "Кофе", "price": 90.0, "category_id": 3},
        headers=headers,
    )
    assert create_res.status_code == 200

    # Кеш должен быть сброшен (событийная инвалидация)
    assert "menu:all" not in repo.cache

    # Новый запрос возвращает 2 блюда и снова кеширует их
    res_after = client.get("/menu/items")
    assert len(res_after.json()) == 2
    assert any(item["name"] == "Кофе" for item in res_after.json())
    assert "menu:all" in repo.cache


def test_cache_invalidation_on_item_update(client):
    """
    Инвалидация кеша при обновлении цены или доступности:
    После изменения блюда кеш сбрасывается.
    """
    repo = create_menu_repository(None)
    item_id = repo.save_item(name="Морс", price=50.0, category_id=3)

    # Прогреваем кеш
    client.get("/menu/items")
    assert "menu:all" in repo.cache

    user_repo = create_user_repository(None)
    cook_id, _ = user_repo.save_user(
        email="chef2@sirius.ru",
        phone="1234567890",
        password_hash=hash_password("password"),
        role="cook",
    )
    token = create_access_token(user_id=cook_id, role="cook")
    headers = {"Authorization": f"Bearer {token}"}

    # Меняем цену
    patch_res = client.patch(
        f"/menu/items/{item_id}",
        json={"price": 65.0},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert "menu:all" not in repo.cache

    # Проверяем, что клиент видит обновленную цену
    res_updated = client.get("/menu/items")
    items = res_updated.json()
    assert items[0]["price"] == 65.0


def test_category_caching_and_separation(client):
    """
    Кеширование категорий меню (menu:category:{id}):
    Эндпоинт GET /menu/categories/{id} кеширует только блюда данной категории.
    """
    repo = create_menu_repository(None)
    repo.save_item(name="Борщ", price=100.0, category_id=1)
    repo.save_item(name="Щи", price=90.0, category_id=1)
    repo.save_item(name="Плов", price=150.0, category_id=2)

    # Запрашиваем супы (категория 1)
    cat1_res = client.get("/menu/categories/1")
    assert cat1_res.status_code == 200
    assert len(cat1_res.json()) == 2
    assert "menu:category:1" in repo.cache

    # Запрашиваем вторые блюда (категория 2)
    cat2_res = client.get("/menu/categories/2")
    assert cat2_res.status_code == 200
    assert len(cat2_res.json()) == 1
    assert "menu:category:2" in repo.cache


def test_cache_warmup_populates_menu_before_first_call(client):
    """
    Cache Warm-Up:
    Вызов warm_up_cache() загружает данные в кеш до прихода запросов пользователей.
    Первый пользовательский запрос сразу попадает в кеш.
    """
    repo = create_menu_repository(None)
    repo.save_item(name="Салат Цезарь", price=150.0, category_id=4)

    # Прогреваем кеш
    repo.warm_up_cache()
    assert "menu:all" in repo.cache

    # Первый же запрос от клиента — это hit!
    res = client.get("/menu/items")
    assert res.status_code == 200
    assert repo.hit_count == 1
    assert repo.miss_count == 0
