from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["threshold"])


@router.post("/threshold", response_model=schemas.ThresholdOut)
def upsert_threshold(payload: schemas.ThresholdIn, db: Session = Depends(get_db)):
    """Create or update the vertical/lateral threshold for a route."""
    row = db.query(models.ThresholdSetting).filter_by(route=payload.route).first()
    if row is None:
        row = models.ThresholdSetting(route=payload.route)
        db.add(row)

    row.vertical_threshold = payload.verticalThreshold
    row.lateral_threshold = payload.lateralThreshold
    row.alerts_enabled = payload.alertsEnabled if payload.alertsEnabled is not None else True

    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("/threshold", response_model=List[schemas.ThresholdOut])
def list_thresholds(db: Session = Depends(get_db)):
    rows = db.query(models.ThresholdSetting).order_by(models.ThresholdSetting.route).all()
    return [_to_out(r) for r in rows]


def _to_out(row: models.ThresholdSetting) -> schemas.ThresholdOut:
    return schemas.ThresholdOut(
        id=row.id,
        route=row.route,
        verticalThreshold=row.vertical_threshold,
        lateralThreshold=row.lateral_threshold,
        alertsEnabled=row.alerts_enabled,
        updatedAt=row.updated_at,
    )
