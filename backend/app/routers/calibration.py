from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["calibration"])


@router.post("/calibration", response_model=schemas.CalibrationOut)
def add_calibration(payload: schemas.CalibrationIn, db: Session = Depends(get_db)):
    """
    Append a new calibration record. History is never overwritten -
    each POST is a new row, so the full wear/correction-factor timeline
    per axle is retained (distance = encoderPulse x correctionFactor is
    applied gateway-side using the most recent row's correctionFactor).
    """
    row = models.Calibration(
        gateway_id=payload.gatewayId,
        axle_id=payload.axleId,
        wheel_diameter_mm=payload.wheelDiameterMm,
        wear_percent=payload.wearPercent,
        correction_factor=payload.correctionFactor,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("/calibration", response_model=List[schemas.CalibrationOut])
def list_calibration(
    gatewayId: Optional[str] = Query(default=None),
    axleId: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(models.Calibration)
    if gatewayId:
        query = query.filter(models.Calibration.gateway_id == gatewayId)
    if axleId:
        query = query.filter(models.Calibration.axle_id == axleId)
    rows = query.order_by(models.Calibration.created_at.desc()).limit(limit).all()
    return [_to_out(r) for r in rows]


def _to_out(row: models.Calibration) -> schemas.CalibrationOut:
    return schemas.CalibrationOut(
        id=row.id,
        gatewayId=row.gateway_id,
        axleId=row.axle_id,
        wheelDiameterMm=row.wheel_diameter_mm,
        wearPercent=row.wear_percent,
        correctionFactor=row.correction_factor,
        createdAt=row.created_at,
    )
