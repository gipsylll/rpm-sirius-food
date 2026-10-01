"""
Транспортный слой доставки.

Принимает HTTP-запрос и переводит доменные исключения в HTTP-статусы.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.modules.delivery.repository import create_delivery_repository
from app.modules.delivery.service import DeliveryService
from app.schemas import DeliveryAssign

router = APIRouter()


@router.post("/assign")
def assign_courier(payload: DeliveryAssign, db: Session = Depends(get_db)):
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

    return {"status": "success", "delivery_id": delivery_id}


@router.patch("/{delivery_id}/complete")
def complete_delivery(delivery_id: int, db: Session = Depends(get_db)):
    repository = create_delivery_repository(db)
    service = DeliveryService(repository)

    try:
        service.complete_delivery(delivery_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success"}
