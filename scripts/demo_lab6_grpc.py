#!/usr/bin/env python3
"""
Скрипт демонстрации Практической работы № 6 (10/10 баллов):
«Удушение монолита: вынос модуля delivery в gRPC-микросервис»

Сценарий:
1. Запуск / проверка автономного gRPC-микросервиса доставки на порту 50051.
2. Демонстрация Unary RPC (AssignCourier, GetDelivery, CompleteDelivery).
3. Демонстрация отказоустойчивости (обработка 404 Not Found, 503 Service Unavailable, таймауты).
4. Демонстрация Server Streaming (TrackDelivery — 9 баллов).
5. Демонстрация Bidirectional Streaming (ChatWithCourier — 10 баллов).
"""

import os
import sys
import time
from concurrent import futures
from datetime import UTC, datetime

import grpc

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import delivery_pb2_grpc
from app.exceptions import NotFoundError
from app.modules.delivery.grpc_client import DeliveryGrpcClient
from delivery_server import DeliveryServiceServicer

GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RED = "\033[91m"
RESET = "\033[0m"


def print_header(title: str):
    print(f"\n{BLUE}{'=' * 75}{RESET}")
    print(f"{BLUE}>>> {title}{RESET}")
    print(f"{BLUE}{'=' * 75}{RESET}")


class InProcessGrpcServer:
    """Вспомогательный класс для гарантированного запуска gRPC-сервера в рамках демонстрации."""

    def __init__(self, port: int = 50051):
        self.port = port
        self.server = None

    def start_if_needed(self):
        # Проверяем, слушает ли уже порт 50051
        channel = grpc.insecure_channel(f"localhost:{self.port}")
        try:
            grpc.channel_ready_future(channel).result(timeout=1.0)
            print(
                f"{GREEN}✅ Внешний Delivery gRPC Server уже запущен на порту {self.port}.{RESET}"
            )
            return False
        except Exception:
            print(
                f"{YELLOW}ℹ️  Запуск локального инстанса Delivery gRPC Server на порту {self.port}...{RESET}"
            )
            self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=5))
            delivery_pb2_grpc.add_DeliveryServiceServicer_to_server(
                DeliveryServiceServicer(), self.server
            )
            self.server.add_insecure_port(f"[::]:{self.port}")
            self.server.start()
            time.sleep(0.5)
            print(f"{GREEN}🚀 gRPC Server успешно поднят на порту {self.port}!{RESET}")
            return True

    def stop(self):
        if self.server:
            self.server.stop(0)
            print(f"{CYAN}Остановлен локальный gRPC Server.{RESET}")


def step_1_unary_calls(client: DeliveryGrpcClient):
    print_header("ШАГ 1: Межсервисные вызовы Unary RPC (Strangler Fig)")
    print(
        "Монолит обращается к микросервису доставки через бинарный протокол gRPC/HTTP/2.\n"
    )

    print(f"1. Вызов {CYAN}AssignCourier(order_id=1, courier_id=4){RESET}...")
    try:
        assign_res = client.assign_courier(order_id=1, courier_id=4)
        print(f"   Ответ gRPC-сервиса: {GREEN}{assign_res}{RESET}")
        delivery_id = assign_res.get("delivery_id", 1)
    except NotFoundError:
        print(
            f"   {YELLOW}Заказ 1 не найден в БД, симулируем ответ для демонстрации...{RESET}"
        )
        delivery_id = 1
    except Exception as exc:
        print(f"   {RED}Ошибка: {exc}{RESET}")
        delivery_id = 1

    print(f"\n2. Вызов {CYAN}GetDelivery(order_id=1){RESET}...")
    try:
        get_res = client.get_delivery(order_id=1)
        print(f"   Ответ gRPC-сервиса: {GREEN}{get_res}{RESET}")
    except Exception as exc:
        print(f"   {YELLOW}Информация по заказу: {exc}{RESET}")

    print(f"\n3. Вызов {CYAN}CompleteDelivery(delivery_id={delivery_id}){RESET}...")
    try:
        comp_res = client.complete_delivery(delivery_id=delivery_id)
        print(f"   Ответ gRPC-сервиса: {GREEN}{comp_res}{RESET}")
    except Exception as exc:
        print(f"   {YELLOW}Завершение доставки: {exc}{RESET}")


def step_2_resilience_and_errors(client: DeliveryGrpcClient):
    print_header("ШАГ 2: Обработка сетевых сбоев и таймаутов (Отказоустойчивость)")
    print(
        "Проверяем, как монолит реагирует на ошибки сети и недоступность микросервиса:\n"
    )

    # 1. Попытка запроса несуществующего ресурса (NOT_FOUND -> 404)
    print(
        f"1. Запрос несуществующего заказа: {CYAN}GetDelivery(order_id=99999){RESET}..."
    )
    try:
        client.get_delivery(order_id=99999)
    except NotFoundError as exc:
        print(f"   {GREEN}✅ Перехвачено NotFoundError (HTTP 404): {exc}{RESET}")
    except Exception as exc:
        print(f"   {YELLOW}Перехвачено исключение: {exc}{RESET}")

    # 2. Попытка обращения к отключенному сервису (UNAVAILABLE -> 503)
    print("\n2. Попытка соединения с несуществующим адресом (UNAVAILABLE):")
    dead_client = DeliveryGrpcClient(host="localhost", port=59999)
    try:
        dead_client.assign_courier(order_id=1, courier_id=2)
    except ConnectionError as exc:
        print(
            f"   {GREEN}✅ Перехвачено ConnectionError (HTTP 503 Service Unavailable): {exc}{RESET}"
        )
        print(
            "   Монолит НЕ падает с трейсбеком, а возвращает клиенту контролируемый статус 503."
        )


def step_3_server_streaming(client: DeliveryGrpcClient):
    print_header("ШАГ 3: Server Streaming (TrackDelivery — Задание на 9 баллов)")
    print("Клиент отправляет 1 запрос TrackDelivery, а сервер непрерывно транслирует")
    print("поток изменений статусов доставки в реальном времени через HTTP/2 Stream:\n")

    delivery_id = 42
    print(f"Подключение к потоку статусов для доставки ID={delivery_id}...\n")

    stream = client.track_delivery(delivery_id)
    step_num = 1
    for event in stream:
        ts = event["timestamp"]
        status = event["status"]
        desc = event["description"]
        print(
            f"  [{ts}] {YELLOW}Этап {step_num}{RESET} | Статус: {CYAN}{status:<15}{RESET} -> {GREEN}{desc}{RESET}"
        )
        step_num += 1

    print(
        f"\n{GREEN}✅ Server Streaming успешно завершен: клиент получил всю цепочку обновлений!{RESET}"
    )


def step_4_bidirectional_streaming(client: DeliveryGrpcClient):
    print_header(
        "ШАГ 4: Bidirectional Streaming (ChatWithCourier — Задание на 10 баллов)"
    )
    print("Двусторонний полнодуплексный обмен сообщениями: клиент и курьер отправляют")
    print("сообщения независимо друг от друга в рамках одного сетевого соединения:\n")

    delivery_id = 42
    customer_dialogue = [
        "Привет, курьер! Где вы сейчас находитесь?",
        "Хорошо, код домофона 42, 3 этаж.",
        "Большое спасибо за быструю доставку!",
    ]

    def message_generator():
        for text in customer_dialogue:
            now_str = datetime.now(UTC).strftime("%H:%M:%S")
            print(f"  [{now_str}] {CYAN}Клиент:{RESET} {text}")
            yield {
                "delivery_id": delivery_id,
                "sender_role": "customer",
                "message": text,
                "timestamp": now_str,
            }
            time.sleep(1.0)

    print("Запуск двусторонней сессии чата:\n")
    responses = client.chat_with_courier(message_generator())

    for resp in responses:
        ts = resp["timestamp"]
        msg = resp["message"]
        print(f"  [{ts}] {GREEN}Курьер:{RESET} {msg}\n")

    print(f"{GREEN}✅ Bidirectional Streaming успешно продемонстрирован!{RESET}")


def main():
    print(
        f"{GREEN}========================================================================{RESET}"
    )
    print(
        f"{GREEN}     СИРИУС.ЕДА: ПОЛНАЯ ДЕМОНСТРАЦИЯ ПРАКТИЧЕСКОЙ РАБОТЫ № 6 (gRPC)    {RESET}"
    )
    print(
        f"{GREEN}========================================================================{RESET}"
    )

    server_wrapper = InProcessGrpcServer(port=50051)
    server_wrapper.start_if_needed()

    client = DeliveryGrpcClient(host="localhost", port=50051)

    try:
        step_1_unary_calls(client)
        step_2_resilience_and_errors(client)
        step_3_server_streaming(client)
        step_4_bidirectional_streaming(client)
    finally:
        server_wrapper.stop()

    print(
        f"\n{GREEN}========================================================================{RESET}"
    )
    print(
        f"{GREEN}      ДЕМОНСТРАЦИЯ ПРАКТИЧЕСКОЙ РАБОТЫ № 6 УСПЕШНО ЗАВЕРШЕНА!          {RESET}"
    )
    print(
        f"{GREEN}========================================================================{RESET}\n"
    )


if __name__ == "__main__":
    main()
