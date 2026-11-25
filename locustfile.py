"""Нагрузка на меню и, при наличии токена, оформление заказов.

Получите JWT через /auth/login и передайте LOCUST_TOKEN. Заказы списывают
реальные деньги с демонстрационного баланса; запускайте только на тестовых данных.
"""

import os

from locust import HttpUser, between, task


class SiriusUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        token = os.getenv("LOCUST_TOKEN")
        if token:
            self.client.headers["Authorization"] = f"Bearer {token}"

    @task(7)
    def get_menu(self):
        self.client.get("/menu/items", name="menu list")

    @task(2)
    def get_item(self):
        self.client.get(
            f"/menu/items/{os.getenv('LOCUST_ITEM_ID', '1')}", name="menu detail"
        )

    @task(1)
    def create_order(self):
        if os.getenv("LOCUST_TOKEN"):
            self.client.post(
                "/orders/create",
                json={"item_id": int(os.getenv("LOCUST_ITEM_ID", "1")), "quantity": 1},
                name="create order",
            )
