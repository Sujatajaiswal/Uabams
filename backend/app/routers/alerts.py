from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts", response_model=List[schemas.AlertOut])
def list_alerts(
    severity: Optional[str] = Query(default=None, description="Critical | Warning | Info"),
    route: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(models.Alert)
    if severity:
        query = query.filter(models.Alert.severity == severity)
    if route:
        query = query.filter(models.Alert.route == route)

    rows = query.order_by(models.Alert.created_at.desc()).limit(limit).all()

    return [
        schemas.AlertOut(
            id=r.id,
            time=r.created_at,
            gatewayId=r.gateway_id,
            trainId=r.train_id,
            route=r.route,
            axleId=r.axle_id,
            metric=r.metric,
            peak=r.value,
            threshold=r.threshold_value,
            speedKmph=r.speed_kmph,
            severity=r.severity,
            message=r.message,
            nearestTrackFeatureKm=r.nearest_track_feature_km,
        )
        for r in rows
    ]
