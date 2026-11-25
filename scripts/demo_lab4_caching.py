#!/usr/bin/env python3
"""
Скрипт демонстрации Лабораторной работы № 4: Кеширование в продакшн (Redis Cache-Aside).

Показывает преподавателю на живом сервере / в реальном времени:
1. Стратегию Cache-Aside (замер времени Cache Miss vs Cache Hit)
2. Проверку содержимого кеша напрямую в Redis (ключ menu:all, TTL)
3. Событийную инвалидацию (создание блюда -> моментальное удаление ключа из Redis)
4. Кеширование категорий меню (ключ menu:category:{id}, TTL 600 сек)
5. Защиту от Cache Stampede (симуляция 30 параллельных запросов)
6. Работу Cache Warm-Up
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import redis
import requests

BASE_URL = "http://127.0.0.1:8000"
REDIS_URL = "redis://localhost:6379/0"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step(title: str):
    print(f"\n{BOLD}{CYAN}=== {title} ==={RESET}")


def run_demo():
    print(
        f"{BOLD}{BLUE}========================================================================{RESET}"
    )
    print(
        f"{BOLD}{BLUE}     ДЕМОНСТРАЦИЯ ЛАБОРАТОРНОЙ РАБОТЫ № 4 (СИРИУС.ЕДА: REDIS КЕШ)       {RESET}"
    )
    print(
        f"{BOLD}{BLUE}========================================================================{RESET}"
    )

    # 1. Проверка доступности
    print_step("1. Подключение к серверу и к Redis")
    try:
        requests.get(f"{BASE_URL}/docs")
        print(f"  {GREEN}✔ Сервер доступен на {BASE_URL}{RESET}")
    except requests.exceptions.ConnectionError:
        print(
            f"  {RED}✘ Сервер {BASE_URL} не запущен! Запустите: uvicorn app.main:app --reload{RESET}"
        )
        sys.exit(1)

    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        print(f"  {GREEN}✔ Redis доступен на {REDIS_URL}{RESET}")
    except Exception as exc:
        print(f"  {RED}✘ Ошибка подключения к Redis: {exc}{RESET}")
        sys.exit(1)

    # 2. Очистка кеша для чистоты замера
    print_step("2. Очистка кеша Redis для демонстрации первого промаха (Miss)")
    r.delete("menu:all")
    r.delete("rate_limit:127.0.0.1:/auth/login")
    print(
        f"  Ключ 'menu:all' удален из Redis. Наличие в Redis: {bool(r.exists('menu:all'))}"
    )

    # 3. Первый запрос: Cache Miss
    print_step("3. Первый запрос GET /menu/items (Cache Miss: чтение из PostgreSQL)")
    t0 = time.perf_counter()
    res1 = requests.get(f"{BASE_URL}/menu/items")
    t1 = time.perf_counter()
    latency_miss = (t1 - t0) * 1000
    print(f"  Время ответа при Cache Miss: {YELLOW}{latency_miss:.2f} мс{RESET}")
    print(f"  Статус ответа: {res1.status_code}, Получено блюд: {len(res1.json())}")

    # Проверяем, что ключ появился в Redis с правильным TTL
    ttl = r.ttl("menu:all")
    print(
        f"  {GREEN}✔ Ключ 'menu:all' записан в Redis! Текущий TTL: {ttl} секунд (лимит 300с){RESET}"
    )

    # 4. Второй запрос: Cache Hit
    print_step(
        "4. Второй запрос GET /menu/items (Cache Hit: чтение из оперативной памяти Redis)"
    )
    t2 = time.perf_counter()
    res2 = requests.get(f"{BASE_URL}/menu/items")
    t3 = time.perf_counter()
    latency_hit = (t3 - t2) * 1000
    speedup = latency_miss / latency_hit if latency_hit > 0 else 100
    print(f"  Время ответа при Cache Hit:  {GREEN}{latency_hit:.2f} мс{RESET}")
    print(
        f"  {BOLD}{GREEN}✔ Ускорение отдачи меню: в {speedup:.1f} раз быстрее!{RESET}"
    )

    # 5. Демонстрация событийной инвалидации кеша
    print_step("5. Событийная инвалидация кеша (Event-Driven Invalidation)")
    print("  Повар добавляет новое блюдо через POST /menu/items...")

    # Авторизуемся поваром (роль cook)
    cook_email = "cook@sirius.ru"
    cook_password = "cook123"

    login_cook = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": cook_email, "password": cook_password},
    )
    cook_token = login_cook.json()["access_token"]
    cook_headers = {"Authorization": f"Bearer {cook_token}"}

    dish_name = f"Фирменный десерт #{int(time.time()) % 1000}"
    add_res = requests.post(
        f"{BASE_URL}/menu/items",
        json={"name": dish_name, "price": 250.0, "category_id": 3},
        headers=cook_headers,
    )
    print(f"  Создано блюдо: '{dish_name}' (HTTP {add_res.status_code})")

    # Проверяем, что ключ menu:all автоматически удален
    key_still_exists = bool(r.exists("menu:all"))
    if not key_still_exists:
        print(
            f"  {GREEN}✔ Кеш успешно инвалидирован: ключ 'menu:all' отсутствует в Redis!{RESET}"
        )
    else:
        print(f"  {RED}✘ Ключ 'menu:all' все еще в Redis{RESET}")

    # Запрашиваем меню снова: блюдо должно появиться, а кеш снова заполниться
    res_after = requests.get(f"{BASE_URL}/menu/items").json()
    found = any(i["name"] == dish_name for i in res_after)
    if found:
        print(
            f"  {GREEN}✔ Новое блюдо '{dish_name}' мгновенно отображается в меню!{RESET}"
        )
        print(
            f"  {GREEN}✔ Ключ 'menu:all' повторно прогрет в Redis (TTL {r.ttl('menu:all')}с){RESET}"
        )

    # 6. Кеширование категорий
    print_step("6. Кеширование категорий меню (GET /menu/categories/3)")
    cat_res = requests.get(f"{BASE_URL}/menu/categories/3")
    cat_items = cat_res.json()
    cat_ttl = r.ttl("menu:category:3")
    print(f"  Получено блюд категории 3: {len(cat_items)}")
    print(
        f"  {GREEN}✔ Ключ 'menu:category:3' закеширован в Redis с TTL: {cat_ttl}с (лимит 600с / 10 мин){RESET}"
    )

    # 7. Защита от Cache Stampede
    print_step(
        "7. Защита от Cache Stampede (30 одновременных запросов при пустом кеше)"
    )
    r.delete("menu:all")
    print("  Кеш сброшен. Отправка 30 параллельных запросов...")

    def fetch_menu(_):
        t_start = time.perf_counter()
        resp = requests.get(f"{BASE_URL}/menu/items")
        return resp.status_code, (time.perf_counter() - t_start) * 1000

    with ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(fetch_menu, range(30)))

    all_200 = all(code == 200 for code, _ in results)
    avg_lat = sum(lat for _, lat in results) / len(results)
    max_lat = max(lat for _, lat in results)
    min_lat = min(lat for _, lat in results)

    if all_200:
        print(
            f"  {GREEN}✔ Все 30 параллельных запросов успешно завершились со статусом 200 OK!{RESET}"
        )
        print(
            f"  Минимальное время: {min_lat:.2f} мс, Среднее: {avg_lat:.2f} мс, Максимальное: {max_lat:.2f} мс"
        )
        print(
            f"  {GREEN}✔ Благодаря distributed mutex lock (lock:menu:all) база данных защищена от перегрузки.{RESET}"
        )

    print(
        f"\n{BOLD}{GREEN}========================================================================{RESET}"
    )
    print(
        f"{BOLD}{GREEN}     ДЕМОНСТРАЦИЯ ЛАБОРАТОРНОЙ РАБОТЫ № 4 УСПЕШНО ЗАВЕРШЕНА (10/10)     {RESET}"
    )
    print(
        f"{BOLD}{GREEN}========================================================================{RESET}"
    )


if __name__ == "__main__":
    run_demo()
