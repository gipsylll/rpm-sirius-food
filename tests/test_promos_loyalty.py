from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.exceptions import BusinessRuleError
from app.modules.orders.repository import InMemoryOrderRepository, MenuItemRecord, PromoCodeRecord, UserRecord
from app.modules.orders.service import OrderService


def setup_service(price=100):
    repo = InMemoryOrderRepository()
    repo.users[1] = UserRecord(1, "student@example.test", None, 500)
    repo.items[1] = MenuItemRecord(1, "Lunch", price)
    return OrderService(repo), repo


def test_percent_promo_and_points_are_capped_at_half():
    service, repo = setup_service()
    repo.promos[1] = PromoCodeRecord(1, "STUDENT10", "percent", Decimal("10"), max_uses=1)
    repo.loyalty[1] = repo.get_loyalty_account(1)
    repo.loyalty[1].balance = 100
    order_id = service.create_order(1, 1, 1, " student10 ", 45)
    order = repo.orders[order_id]
    assert order.discount_amount == Decimal("10")
    assert order.final_amount == Decimal("45")
    assert repo.promos[1].current_uses == 1
    assert repo.loyalty[1].balance == 55


def test_expired_and_reused_codes_are_rejected():
    service, repo = setup_service()
    repo.promos[1] = PromoCodeRecord(1, "OLD", "fixed", Decimal("5"), valid_until=datetime.now(UTC) - timedelta(days=1))
    with pytest.raises(BusinessRuleError, match="истёк"):
        service.create_order(1, 1, 1, "old")
    repo.promos[1].valid_until = None
    service.create_order(1, 1, 1, "old")
    with pytest.raises(BusinessRuleError, match="уже использован"):
        service.create_order(1, 1, 1, "old")
