"""
Точка входа приложения «Сириус.Еда».

Выполняет инициализацию FastAPI, подключение CORS, отключение Swagger в проде,
прогрев кеша при старте (Cache Warm-Up) и регистрацию роутеров всех модулей:
auth, users, menu, orders, delivery.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.observability import metrics, observe
from app.core.tracing import setup_tracing
from app.database import Base, SessionLocal, engine
from app.models import Delivery, Order
from app.modules.auth.router import router as auth_router
from app.modules.delivery.router import router as delivery_router
from app.modules.menu.repository import create_menu_repository
from app.modules.menu.router import router as menu_router
from app.modules.orders.router import router as orders_router
from app.modules.orders.websocket import manager, user_id_from_token
from app.modules.promos.router import router as promos_router
from app.modules.users.router import router as users_router

logger = logging.getLogger(__name__)

# Безопасное создание таблиц БД при наличии подключения
try:
    Base.metadata.create_all(bind=engine)
except Exception as exc:
    logger.warning("Не удалось выполнить автосоздание таблиц БД при импорте: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения.
    Выполняет Cache Warm-Up меню при старте сервиса (ЛР №4).
    """
    logger.info("Запуск приложения. Выполняется прогрев кеша...")
    try:
        with SessionLocal() as db:
            menu_repo = create_menu_repository(db)
            menu_repo.warm_up_cache()
    except Exception as exc:
        logger.warning("Прогрев кеша при старте пропущен: %s", exc)

    manager.start()

    yield

    await manager.stop()

    logger.info("Остановка приложения.")


# Инициализация FastAPI с принципом Secure by Default (отключение Swagger в проде при DEBUG=False)
app = FastAPI(
    title="Sirius.Food API",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    lifespan=lifespan,
)

setup_tracing("sirius-api", app)
app.middleware("http")(observe)
app.add_api_route("/metrics", metrics, include_in_schema=False)

# Настройка CORS с ограничением доменов
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
)

# Редирект с корня на Swagger UI для удобства


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


# Явно включаемая ошибка для демонстрации Sentry; по умолчанию маршрута нет.
if os.getenv("SENTRY_TEST_ENABLED") == "1":

    @app.get("/__debug__/sentry", include_in_schema=False)
    def sentry_test_error():
        raise RuntimeError("Sirius Food Sentry test")


# Подключение маршрутизаторов модулей

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(users_router, prefix="/users", tags=["users"])
app.include_router(menu_router, prefix="/menu", tags=["menu"])
app.include_router(orders_router, prefix="/orders", tags=["orders"])
app.include_router(promos_router, prefix="/promocodes", tags=["promocodes"])
app.include_router(promos_router, prefix="/admin/promocodes", tags=["promocodes"])


@app.websocket("/ws/orders/{order_id}")
async def order_tracking_websocket(
    websocket: WebSocket, order_id: int, token: str | None = None
):
    """Authenticated, reconnectable order status stream."""
    if not token:
        await websocket.close(code=1008, reason="token is required")
        return
    try:
        user_id = user_id_from_token(token)
    except Exception:
        await websocket.close(code=1008, reason="invalid token")
        return
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.id == order_id).first()
        if order is None or order.user_id != user_id:
            await websocket.close(code=1008, reason="order access denied")
            return
        delivery = db.query(Delivery).filter(Delivery.order_id == order_id).first()
        snapshot = {
            "type": "snapshot",
            "order_id": order_id,
            "status": order.status,
            "delivery_status": delivery.status if delivery else None,
            "history": [
                {
                    "status": order.status,
                    "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            ],
        }
    await manager.connect(order_id, websocket)
    await websocket.send_json(snapshot)

    async def heartbeat():
        while True:
            await asyncio.sleep(20)
            await websocket.send_json(
                {
                    "type": "ping",
                    "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            )

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "pong":
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        manager.disconnect(order_id, websocket)


app.include_router(delivery_router, prefix="/delivery", tags=["delivery"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
