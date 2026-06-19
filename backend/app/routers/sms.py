from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["sms"])


@router.get("/sms-notifications", response_model=List[schemas.SmsNotificationOut])
def list_sms_notifications(
    status: Optional[str] = Query(default=None, description="sent | failed | skipped"),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(models.SmsNotification)
    if status:
        query = query.filter(models.SmsNotification.status == status)
    rows = query.order_by(models.SmsNotification.created_at.desc()).limit(limit).all()
    return [
        schemas.SmsNotificationOut(
            id=row.id,
            alertId=row.alert_id,
            gatewayId=row.gateway_id,
            trainId=row.train_id,
            recipient=row.recipient,
            provider=row.provider,
            message=row.message,
            status=row.status,
            providerResponse=row.provider_response,
            createdAt=row.created_at,
        )
        for row in rows
    ]
