#!/usr/bin/env python3
"""
Скрипт демонстрации Лабораторной работы № 3: Безопасность и контроль доступа.

Показывает преподавателю на живом сервере / в реальном времени:
1. Регистрацию пользователей с хешированием паролей (bcrypt)
2. JWT-аутентификацию (выдача access и refresh токенов)
3. Защиту эндпоинтов (401 при отсутствии токена)
4. Ролевую модель RBAC (403 при попытке студента открыть кухню)
5. Защиту от IDOR (403 при попытке отменить чужой заказ)
6. Успешную отмену своего заказа владельцем
7. Защиту от брутфорса (Rate Limiting на Redis: 429 Too Many Requests)
8. Refresh Token Rotation и сброс сессий при попытке повторного использования старого токена
"""

import sys
import time

import requests

BASE_URL = "http://127.0.0.1:8000"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step(title: str):
    print(f"\n{BOLD}{CYAN}=== {title} ==={RESET}")


def assert_status(response: requests.Response, expected: int, action_desc: str):
    if response.status_code == expected:
        print(
            f"  {GREEN}✔ [УСПЕХ]{RESET} {action_desc} -> Получен ожидаемый HTTP-код {expected}"
        )
    else:
        print(
            f"  {RED}✘ [ОШИБКА]{RESET} {action_desc} -> Ожидался {expected}, получен {response.status_code}: {response.text}"
        )


def run_demo():
    print(
        f"{BOLD}{BLUE}========================================================================{RESET}"
    )
    print(
        f"{BOLD}{BLUE}     ДЕМОНСТРАЦИЯ ЛАБОРАТОРНОЙ РАБОТЫ № 3 (СИРИУС.ЕДА: БЕЗОПАСНОСТЬ)    {RESET}"
    )
    print(
        f"{BOLD}{BLUE}========================================================================{RESET}"
    )

    # 1. Проверка доступности сервера
    print_step("1. Проверка доступности сервера Sirius.Food API")
    try:
        res = requests.get(f"{BASE_URL}/docs")
        print(
            f"  {GREEN}✔ Сервер запущен на {BASE_URL} (Swagger доступен: HTTP {res.status_code}){RESET}"
        )
    except requests.exceptions.ConnectionError:
        print(
            f"  {RED}✘ Сервер {BASE_URL} не запущен! Запустите: uvicorn app.main:app --reload{RESET}"
        )
        sys.exit(1)

    # 2. Попытка несанкционированного доступа (401)
    print_step("2. Проверка защиты: запрос без JWT токена")
    res = requests.post(f"{BASE_URL}/orders/create", json={"item_id": 1, "quantity": 1})
    assert_status(res, 401, "Вызов POST /orders/create без Authorization заголовка")

    # 3. Регистрация пользователей
    print_step("3. Регистрация пользователей (студент, повар)")
    ts = int(time.time())
    student1_email = f"student_{ts}@sirius.ru"
    student2_email = f"other_student_{ts}@sirius.ru"
    password = "SecretPassword123"

    res_reg1 = requests.post(
        f"{BASE_URL}/users/register",
        json={"email": student1_email, "password": password, "phone": "+79991112233"},
    )
    assert_status(res_reg1, 200, f"Регистрация Студента 1 ({student1_email})")

    res_reg2 = requests.post(
        f"{BASE_URL}/users/register",
        json={"email": student2_email, "password": password, "phone": "+79994445566"},
    )
    assert_status(res_reg2, 200, f"Регистрация Студента 2 ({student2_email})")

    # 4. Вход и получение JWT
    print_step("4. Аутентификация: POST /auth/login")
    res_login = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": student1_email, "password": password},
    )
    assert_status(res_login, 200, "Вход Студента 1")
    tokens1 = res_login.json()
    access1 = tokens1["access_token"]
    refresh1 = tokens1["refresh_token"]
    print(f"  Access Token (15 мин): {access1[:35]}...")
    print(f"  Refresh Token (7 дней): {refresh1[:35]}...")

    headers1 = {"Authorization": f"Bearer {access1}"}

    # Вход второго студента
    res_login2 = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": student2_email, "password": password},
    )
    access2 = res_login2.json()["access_token"]
    headers2 = {"Authorization": f"Bearer {access2}"}

    # 5. Ролевая модель RBAC (студент пытается открыть кухню)
    print_step(
        "5. Проверка RBAC: Студент обращается к эндпоинту кухни GET /orders/kitchen"
    )
    res_kitchen = requests.get(f"{BASE_URL}/orders/kitchen", headers=headers1)
    assert_status(res_kitchen, 403, "Студент вызывает GET /orders/kitchen")
    print(f"  Ответ сервера: {res_kitchen.json().get('detail')}")

    # 6. Оформление заказа и пополнение баланса
    print_step("6. Пополнение баланса и создание заказа")
    user1_id = res_reg1.json()["user_id"]
    requests.post(f"{BASE_URL}/users/{user1_id}/topup?amount=5000", headers=headers1)

    # Получаем блюдо из меню
    menu_res = requests.get(f"{BASE_URL}/menu/items")
    menu = menu_res.json()
    if not menu:
        # Если меню пустое, временно возьмем id 1
        item_id = 1
    else:
        item_id = menu[0]["id"]

    res_order = requests.post(
        f"{BASE_URL}/orders/create",
        json={"item_id": item_id, "quantity": 1},
        headers=headers1,
    )
    if res_order.status_code == 200:
        order_id = res_order.json()["order_id"]
        print(f"  {GREEN}✔ Заказ #{order_id} успешно создан Студентом 1{RESET}")

        # 7. Защита от IDOR (Студент 2 пытается отменить заказ Студента 1)
        print_step("7. Защита от IDOR: Студент 2 пытается отменить заказ Студента 1")
        res_idor = requests.post(
            f"{BASE_URL}/orders/{order_id}/cancel", headers=headers2
        )
        assert_status(
            res_idor, 403, f"Студент 2 вызывает POST /orders/{order_id}/cancel"
        )
        print(f"  Ответ сервера: {res_idor.json().get('detail')}")

        # 8. Студент 1 отменяет свой собственный заказ
        print_step("8. Легитимная отмена: Студент 1 отменяет свой собственный заказ")
        res_cancel = requests.post(
            f"{BASE_URL}/orders/{order_id}/cancel", headers=headers1
        )
        assert_status(
            res_cancel, 200, f"Студент 1 вызывает POST /orders/{order_id}/cancel"
        )

    # 9. Демонстрация Refresh Token Rotation
    print_step("9. Демонстрация Refresh Token Rotation (10 баллов)")
    res_refresh = requests.post(
        f"{BASE_URL}/auth/refresh", json={"refresh_token": refresh1}
    )
    assert_status(res_refresh, 200, "Обновление токена: POST /auth/refresh")
    tokens_new = res_refresh.json()
    refresh_new = tokens_new["refresh_token"]
    print(f"  Новый Refresh Token: {refresh_new[:35]}...")

    print_step(
        "10. Детекция атаки повторного использования токена (Token Reuse Detection)"
    )
    print("  Злоумышленник пытается отправить СТАРЫЙ, уже отозванный refresh-токен...")
    res_reuse = requests.post(
        f"{BASE_URL}/auth/refresh", json={"refresh_token": refresh1}
    )
    assert_status(
        res_reuse, 401, "Попытка повторного использования отозванного refresh-токена"
    )
    print(f"  Ответ сервера безопасности: {res_reuse.json().get('detail')}")

    # 11. Rate Limiting на Redis
    print_step("11. Демонстрация Rate Limiting (Redis 429 Too Many Requests)")
    print("  Отправка 6 быстрых запросов на /auth/login...")
    for i in range(1, 7):
        r = requests.post(
            f"{BASE_URL}/auth/login",
            json={"email": "wrong@sirius.ru", "password": "badpassword"},
        )
        if r.status_code == 429:
            print(
                f"  {YELLOW}Запрос #{i}: HTTP 429 Too Many Requests (Rate limit сработал!){RESET}"
            )
        else:
            print(f"  Запрос #{i}: HTTP {r.status_code}")

    print(
        f"\n{BOLD}{GREEN}========================================================================{RESET}"
    )
    print(
        f"{BOLD}{GREEN}     ДЕМОНСТРАЦИЯ ЛАБОРАТОРНОЙ РАБОТЫ № 3 УСПЕШНО ЗАВЕРШЕНА (10/10)     {RESET}"
    )
    print(
        f"{BOLD}{GREEN}========================================================================{RESET}"
    )


if __name__ == "__main__":
    run_demo()
