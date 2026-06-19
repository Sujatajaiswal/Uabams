from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.gateway_status import live_status

router = APIRouter(prefix="/api/v1", tags=["gateways"])


@router.get("/gateways", response_model=List[schemas.GatewayOut])
def list_gateways(db: Session = Depends(get_db)):
    rows = db.query(models.Gateway).order_by(models.Gateway.gateway_id).all()
    return [
        schemas.GatewayOut(
            gatewayId=r.gateway_id,
            status=live_status(r),
            lastSeenAt=r.last_seen_at,
            lastUploadAt=r.last_upload_at,
        )
        for r in rows
    ]
