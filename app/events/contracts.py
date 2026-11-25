"""OrderPaid wire format shared by publisher and message consumers."""

from pydantic import BaseModel, ConfigDict, Field


class OrderPaid(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    event_id: str = Field(min_length=1)
    order_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    item_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    total: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    discount: float = 0
    promo_code: str | None = None
    loyalty_points: int = 0


def build_order_paid(
    event_id,
    order_id,
    user_id,
    item_id,
    quantity,
    total,
    discount=0,
    promo_code=None,
    loyalty_points=0,
):
    return {
        "event_id": event_id,
        "order_id": order_id,
        "user_id": user_id,
        "item_id": item_id,
        "quantity": quantity,
        "total": float(total),
        "currency": "RUB",
        "discount": float(discount or 0),
        "promo_code": promo_code,
        "loyalty_points": loyalty_points,
    }
