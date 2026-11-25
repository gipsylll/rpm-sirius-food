"""
Конфигурация приложения.

Загружает настройки из переменных окружения и .env файла.
Использует Pydantic Settings для строгой валидации.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения."""

    SECRET_KEY: str = "super-secret-jwt-signing-key-for-sirius-food-2026"
    DATABASE_URL: str = "postgresql://sirius:sirius@localhost:5432/sirius_food"
    REDIS_URL: str = "redis://localhost:6379/0"
    DEBUG: bool = True
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        "https://sirius-food.ru",
    ]
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    DELIVERY_GRPC_HOST: str = "localhost"
    DELIVERY_GRPC_PORT: int = 50051

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
