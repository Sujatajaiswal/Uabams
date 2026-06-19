"""
Module 2 - Gateway ingestion.

PUT /api/v1/archive  -> primary endpoint per the architecture spec, accepts
                        either application/zip (a ZIP containing one .json
                        session file) or application/json (raw body).
POST /api/v1/archive -> identical handler, kept for the "simple demo API"
                        list and for clients/tools that prefer POST for
                        uploads.
"""
import io
import json
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services import validation
from app.services.alerts import evaluate_alerts, get_or_default_threshold
from app.services.sms import dispatch_sms_for_alerts

router = APIRouter(prefix="/api/v1", tags=["archive"])


def _extract_json_payload(content_type: str, raw: bytes) -> dict:
    if "zip" in content_type.lower():
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                json_names = [n for n in zf.namelist() if n.lower().endswith(".json")]
                if not json_names:
                    raise HTTPException(
                        status_code=400,
                        detail="ZIP archive does not contain a .json session file",
                    )
                raw_json = zf.read(json_names[0])
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP archive")
    else:
        raw_json = raw

    try:
        return json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid or missing JSON body")


async def _handle_archive(request: Request, db: Session) -> schemas.ArchiveResponse:
    content_type = request.headers.get("content-type", "")
    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(status_code=400, detail="Empty request body")

    payload_dict = _extract_json_payload(content_type, raw_body)

    try:
        payload = schemas.ArchiveIn(**payload_dict)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    # Field-level business validation (GPS bounds, g-range, duplicates)
    validation.validate_archive(payload, db)

    now = datetime.utcnow()

    # Upsert gateway heartbeat
    gateway = db.get(models.Gateway, payload.gatewayId)
    if gateway is None:
        gateway = models.Gateway(gateway_id=payload.gatewayId)
        db.add(gateway)
    gateway.status = "online"
    gateway.last_seen_at = now
    gateway.last_upload_at = now

    session_id = payload.sessionId or f"AUTO-{int(now.timestamp() * 1000)}"
    route = payload.route or "Bangalore-Chennai"

    db_session = models.GatewaySession(
        session_id=session_id,
        gateway_id=payload.gatewayId,
        train_id=payload.trainId,
        route=route,
        timestamp=payload.timestamp or now,
        lat=payload.gps.lat,
        lon=payload.gps.lon,
        speed_kmph=payload.resolved_speed,
        raw_payload=payload_dict,
    )
    db.add(db_session)
    db.flush()  # get db_session.id without committing yet

    # Normalise axle data: full payloads carry axleData[], the simple demo
    # payload only carries a flat `peak`. In the latter case we synthesize
    # a single AX01 reading so the rest of the pipeline (storage, charts,
    # alerts) behaves identically either way.
    axle_inputs = payload.axleData
    if not axle_inputs:
        peak_val = payload.peak
        axle_inputs = [
            schemas.AxleDataIn(
                axleId="AX01",
                verticalG=round(peak_val, 2),
                lateralG=round(peak_val * 0.6, 2),
                rms=round(peak_val * 0.55, 2),
                peak=round(peak_val, 2),
            )
        ]

    axle_records = []
    for axle in axle_inputs:
        rec = models.AxleRecord(
            session_id=db_session.id,
            axle_id=axle.axleId,
            vertical_g=axle.verticalG,
            lateral_g=axle.lateralG,
            rms=axle.rms,
            peak=axle.peak,
        )
        db.add(rec)
        axle_records.append(rec)
    db.flush()

    threshold = get_or_default_threshold(db, route)
    alerts_created = evaluate_alerts(db_session, axle_records, threshold, db)
    db.flush()
    sms_logs = dispatch_sms_for_alerts(db, alerts_created)

    db.commit()

    return schemas.ArchiveResponse(
        status="success",
        archiveId=db_session.id,
        alertsGenerated=len(alerts_created),
        message=(
            f"Session '{session_id}' stored with {len(axle_records)} axle reading(s); "
            f"SMS notifications logged: {len(sms_logs)}"
        ),
    )


@router.put("/archive", response_model=schemas.ArchiveResponse)
async def upload_archive_put(request: Request, db: Session = Depends(get_db)):
    return await _handle_archive(request, db)


@router.post("/archive", response_model=schemas.ArchiveResponse)
async def upload_archive_post(request: Request, db: Session = Depends(get_db)):
    return await _handle_archive(request, db)
