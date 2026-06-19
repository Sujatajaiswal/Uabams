"""
Validation rules for incoming Module 2 archive uploads:
  - missing fields            -> handled by pydantic (422) before this runs
  - invalid GPS                -> lat/lon out of valid world bounds
  - invalid threshold (g range) -> any axle vertical/lateral/rms/peak outside 0-100g
  - duplicate sessions         -> same (gatewayId, sessionId) already stored
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models, schemas

G_MIN, G_MAX = 0.0, 100.0


def validate_gps(gps: schemas.GpsIn) -> None:
    if not (-90.0 <= gps.lat <= 90.0):
        raise HTTPException(status_code=400, detail=f"Invalid GPS latitude: {gps.lat}")
    if not (-180.0 <= gps.lon <= 180.0):
        raise HTTPException(status_code=400, detail=f"Invalid GPS longitude: {gps.lon}")


def validate_g_range(label: str, value: float) -> None:
    if value is None or not (G_MIN <= value <= G_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid threshold value for '{label}': {value} (must be within {G_MIN}-{G_MAX}g)",
        )


def validate_axle_data(axle_list) -> None:
    if not axle_list:
        return
    for axle in axle_list:
        validate_g_range(f"{axle.axleId}.verticalG", axle.verticalG)
        validate_g_range(f"{axle.axleId}.lateralG", axle.lateralG)
        validate_g_range(f"{axle.axleId}.rms", axle.rms)
        validate_g_range(f"{axle.axleId}.peak", axle.peak)


def validate_duplicate_session(db: Session, gateway_id: str, session_id: str) -> None:
    if not session_id:
        return
    existing = (
        db.query(models.GatewaySession)
        .filter_by(gateway_id=gateway_id, session_id=session_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate session: sessionId '{session_id}' already received from gateway '{gateway_id}'",
        )


def validate_archive(payload: schemas.ArchiveIn, db: Session) -> None:
    validate_gps(payload.gps)

    if payload.axleData:
        validate_axle_data(payload.axleData)
    elif payload.peak is not None:
        validate_g_range("peak", payload.peak)

    validate_duplicate_session(db, payload.gatewayId, payload.sessionId)
