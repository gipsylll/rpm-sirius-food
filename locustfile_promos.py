"""Concurrency scenario for a max_uses=1 promo code.
Run: uv run --locked locust -f locustfile_promos.py --users 1000 --spawn-rate 100
"""

import os

from locust import HttpUser, between, task


class PromoConcurrencyUser(HttpUser):
    wait_time = between(0.01, 0.1)

    def on_start(self):
        token = os.environ.get("LOCUST_TOKEN", "")
        if token:
            self.client.headers["Authorization"] = f"Bearer {token}"

    @task
    def apply_single_use_code(self):
        self.client.post(
            "/orders/create",
            json={
                "item_id": int(os.getenv("LOCUST_ITEM_ID", "1")),
                "quantity": 1,
                "promo_code": os.getenv("LOCUST_PROMO_CODE", "STUDENT10"),
                "loyalty_points": 0,
            },
            name="promo max_uses=1",
        )
