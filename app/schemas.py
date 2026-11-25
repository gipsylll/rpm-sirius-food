"""
Pydantic-схемы для валидации входных и выходных данных.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Схема регистрации пользователя."""

    email: EmailStr
    password: str
    phone: str | None = None


class UserResponse(BaseModel):
    """Схема профиля пользователя."""

    id: int
    email: str
    balance: float
    role: str = "student"

    model_config = ConfigDict(from_attributes=True)


class LoginSchema(BaseModel):
    """Схема входа в систему."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Схема ответа с JWT токенами."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """Схема запроса обновления токенов."""

    refresh_token: str


class MenuItemCreate(BaseModel):
    """Схема создания блюда."""

    name: str
    price: float
    category_id: int = 1


class MenuItemUpdate(BaseModel):
    """Схема обновления блюда."""

    name: str | None = None
    price: float | None = None
    is_available: bool | None = None
    category_id: int | None = None


class MenuItemResponse(BaseModel):
    """Схема ответа блюда."""

    id: int
    name: str
    price: float
    is_available: bool = True
    category_id: int = 1

    model_config = ConfigDict(from_attributes=True)


class OrderCreate(BaseModel):
    """Схема создания заказа. user_id извлечен из payload в целях безопасности."""

    item_id: int
    quantity: int
    promo_code: str | None = Field(default=None, max_length=64)
    loyalty_points: int = Field(default=0, ge=0)


class PromoCodeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    discount_type: str
    discount_value: Decimal = Field(gt=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    max_uses: int | None = Field(default=None, gt=0)
    min_order_amount: Decimal = Field(default=Decimal(0), ge=0)


class PromoCodeResponse(PromoCodeCreate):
    id: int
    current_uses: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class DeliveryStatusUpdate(BaseModel):
    status: str


class DeliveryAssign(BaseModel):
    """Схема назначения курьера на доставку."""

    order_id: int
    courier_id: int
