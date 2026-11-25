"""
Транспортный слой доставки.

Принимает HTTP-запрос, выполняет ролевую авторизацию (RBAC) и защиту от IDOR,
переводит доменные исключения в HTTP-статусы.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import require_role
from app.database import get_db
from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.delivery.repository import create_delivery_repository
from app.modules.delivery.service import DeliveryService
from app.schemas import DeliveryAssign, DeliveryStatusUpdate

router = APIRouter()


@router.post("/assign")
def assign_courier(
    payload: DeliveryAssign,
    current_user: Any = Depends(require_role("cook", "admin")),
    db: Session = Depends(get_db),
):
    """
    Назначение курьера на заказ.
    Разрешено только поварам (cook) и администраторам (admin).
    """
    repository = create_delivery_repository(db)
    service = DeliveryService(repository)

    try:
        delivery_id = service.assign_courier(payload.order_id, payload.courier_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc

    return {"status": "success", "delivery_id": delivery_id}


@router.patch("/{delivery_id}/complete")
def complete_delivery(
    delivery_id: int,
    current_user: Any = Depends(require_role("courier", "admin")),
    db: Session = Depends(get_db),
):
    """
    Завершение доставки.
    Курьер может завершить только свою собственную доставку (защита от IDOR).
    """
    repository = create_delivery_repository(db)
    service = DeliveryService(repository)

    user_role = getattr(current_user, "role", None)
    role_name = getattr(user_role, "name", str(user_role) if user_role else "")
    is_admin = role_name == "admin"

    try:
        service.complete_delivery(
            delivery_id=delivery_id,
            current_user_id=current_user.id,
            is_admin=is_admin,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc

    return {"status": "success", "message": "Доставка успешно завершена"}


@router.patch("/{delivery_id}/status")
def update_delivery_status(
    delivery_id: int,
    payload: DeliveryStatusUpdate,
    current_user: Any = Depends(require_role("courier", "admin")),
    db: Session = Depends(get_db),
):
    repository = create_delivery_repository(db)
    service = DeliveryService(repository)
    role = getattr(getattr(current_user, "role", None), "name", "")
    try:
        service.update_status(
            delivery_id, payload.status, current_user.id, role == "admin"
        )
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(403, str(exc)) from exc
    except BusinessRuleError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "status": "success",
        "delivery_id": delivery_id,
        "delivery_status": payload.status,
    }


@router.get("/my")
def get_my_deliveries(
    current_user: Any = Depends(require_role("courier", "admin")),
    db: Session = Depends(get_db),
):
    """Список доставок текущего курьера."""
    repository = create_delivery_repository(db)
    service = DeliveryService(repository)
    return service.get_courier_deliveries(current_user.id)


@router.get("/{delivery_id}/track")
def track_delivery_stream(
    delivery_id: int,
    db: Session = Depends(get_db),
):
    """
    Server Streaming трекинга доставки (9-10 баллов).
    Транслирует поток смены этапов доставки клиенту через Server-Sent Events (SSE).
    Можно открыть прямо в браузере или протестировать через curl/Swagger.
    """
    repository = create_delivery_repository(db)
    service = DeliveryService(repository)

    def event_stream():
        try:
            for event in service.track_delivery(delivery_id):
                payload = json.dumps(event, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{delivery_id}/track/visual", response_class=HTMLResponse)
def track_delivery_visual_page(delivery_id: int):
    """
    Интерактивная визуальная веб-страница живого трекинга доставки курьером.
    Подключается к SSE-потоку gRPC и анимирует этапы движения заказа в браузере.
    """
    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Трекинг доставки #{delivery_id} — Сириус.Еда</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
        }}
        .card {{
            background: #1e293b;
            border-radius: 16px;
            padding: 32px;
            max-width: 600px;
            width: 100%;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5);
            border: 1px solid #334155;
        }}
        h1 {{
            font-size: 24px;
            margin-top: 0;
            color: #38bdf8;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .badge {{
            background: #0369a1;
            color: #e0f2fe;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
        }}
        .steps {{
            margin-top: 30px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        .step {{
            display: flex;
            align-items: flex-start;
            gap: 16px;
            padding: 14px;
            border-radius: 10px;
            background: #0f172a;
            border: 1px solid #334155;
            opacity: 0.35;
            transition: all 0.4s ease;
        }}
        .step.active {{
            opacity: 1;
            border-color: #38bdf8;
            background: rgba(56, 189, 248, 0.1);
            transform: scale(1.02);
        }}
        .step.completed {{
            opacity: 0.9;
            border-color: #22c55e;
            background: rgba(34, 197, 94, 0.08);
        }}
        .icon {{
            font-size: 26px;
            line-height: 1;
        }}
        .info {{
            flex: 1;
        }}
        .status-title {{
            font-weight: 600;
            font-size: 16px;
            color: #f1f5f9;
        }}
        .desc {{
            font-size: 14px;
            color: #94a3b8;
            margin-top: 4px;
        }}
        .time {{
            font-size: 12px;
            color: #64748b;
            margin-top: 4px;
            font-family: monospace;
        }}
        .footer {{
            margin-top: 30px;
            text-align: center;
            font-size: 13px;
            color: #64748b;
            border-top: 1px solid #334155;
            padding-top: 16px;
        }}
        .pulse {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #22c55e;
            box-shadow: 0 0 0 rgba(34, 197, 94, 0.4);
            animation: pulse 1.5s infinite;
        }}
        @keyframes pulse {{
            0% {{ box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); }}
            70% {{ box-shadow: 0 0 0 10px rgba(34, 197, 94, 0); }}
            100% {{ box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>
            <span>🚚 Живой трекинг доставки #{delivery_id}</span>
            <span class="badge"><span class="pulse"></span> HTTP/2 gRPC Stream</span>
        </h1>
        <p style="color: #94a3b8; font-size: 14px; margin-bottom: 0;">
            Поток событий Server Streaming напрямую из микросервиса доставки «Сириус.Еда»:
        </p>

        <div class="steps">
            <div id="step-in_progress" class="step">
                <div class="icon">📦</div>
                <div class="info">
                    <div class="status-title">Этап 1: Назначение курьера (in_progress)</div>
                    <div class="desc">Ожидание...</div>
                    <div class="time"></div>
                </div>
            </div>
            <div id="step-picked_up" class="step">
                <div class="icon">🍳</div>
                <div class="info">
                    <div class="status-title">Этап 2: Заказ приготовлен и забран (picked_up)</div>
                    <div class="desc">Ожидание...</div>
                    <div class="time"></div>
                </div>
            </div>
            <div id="step-in_transit" class="step">
                <div class="icon">🚲</div>
                <div class="info">
                    <div class="status-title">Этап 3: Курьер в пути (in_transit)</div>
                    <div class="desc">Ожидание...</div>
                    <div class="time"></div>
                </div>
            </div>
            <div id="step-arrived" class="step">
                <div class="icon">🏢</div>
                <div class="info">
                    <div class="status-title">Этап 4: Курьер прибыл к зданию (arrived)</div>
                    <div class="desc">Ожидание...</div>
                    <div class="time"></div>
                </div>
            </div>
            <div id="step-delivered" class="step">
                <div class="icon">✅</div>
                <div class="info">
                    <div class="status-title">Этап 5: Заказ вручен клиенту (delivered)</div>
                    <div class="desc">Ожидание...</div>
                    <div class="time"></div>
                </div>
            </div>
        </div>

        <div class="footer">
            gRPC Microservice: <code>localhost:50051</code> • Метод: <code>TrackDelivery</code> (Server Streaming)
        </div>
    </div>

    <script>
        const evtSource = new EventSource('/delivery/{delivery_id}/track');
        let prevElement = null;

        evtSource.onmessage = function(event) {{
            try {{
                const data = JSON.parse(event.data);
                if (data.status) {{
                    const el = document.getElementById('step-' + data.status);
                    if (el) {{
                        if (prevElement && prevElement !== el) {{
                            prevElement.classList.remove('active');
                            prevElement.classList.add('completed');
                        }}
                        el.classList.add('active');
                        el.querySelector('.desc').textContent = data.description;
                        el.querySelector('.time').textContent = 'Время события: ' + data.timestamp;
                        prevElement = el;

                        if (data.status === 'delivered') {{
                            setTimeout(() => {{
                                el.classList.remove('active');
                                el.classList.add('completed');
                                evtSource.close();
                            }}, 1000);
                        }}
                    }}
                }}
            }} catch (e) {{
                console.error(e);
            }}
        }};

        evtSource.onerror = function() {{
            evtSource.close();
        }};
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)
