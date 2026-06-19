from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["config"])


@router.get("/config", response_model=schemas.ConfigOut)
def get_gateway_config(
    gatewayId: str = Query(default=None, description="Gateway requesting its config"),
    route: str = Query(default=None, description="Route to fetch threshold for"),
    db: Session = Depends(get_db),
):
    """
    Called periodically by each gateway over HTTPS (Bearer token, retry
    every 30s on failure per Module 6) to pull its latest threshold,
    calibration wear%, and sampling rate.
    """
    # Resolve the relevant route: explicit query param, else the gateway's
    # most recent session route, else the system default.
    resolved_route = route
    if not resolved_route and gatewayId:
        last_session = (
            db.query(models.GatewaySession)
            .filter_by(gateway_id=gatewayId)
            .order_by(models.GatewaySession.timestamp.desc())
            .first()
        )
        if last_session:
            resolved_route = last_session.route
    resolved_route = resolved_route or settings.DEFAULT_ROUTE

    threshold_row = db.query(models.ThresholdSetting).filter_by(route=resolved_route).first()
    threshold_value = (
        threshold_row.vertical_threshold if threshold_row else settings.DEFAULT_VERTICAL_THRESHOLD
    )

    wear_percent = 0.0
    if gatewayId:
        last_calibration = (
            db.query(models.Calibration)
            .filter_by(gateway_id=gatewayId)
            .order_by(models.Calibration.created_at.desc())
            .first()
        )
        if last_calibration:
            wear_percent = last_calibration.wear_percent
        else:
            wear_percent = 0.0
    else:
        wear_percent = 0.0

    return schemas.ConfigOut(
        threshold=threshold_value,
        wearPercent=wear_percent,
        samplingRate=settings.DEFAULT_SAMPLING_RATE,
    )
