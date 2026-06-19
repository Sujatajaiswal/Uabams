from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.gateway_status import live_status

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/dashboard", response_model=schemas.DashboardOut)
def get_dashboard(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    # ---- Overview cards --------------------------------------------------
    active_trains = (
        db.query(func.count(func.distinct(models.GatewaySession.train_id)))
        .filter(models.GatewaySession.timestamp >= last_24h)
        .scalar()
        or 0
    )
    uploaded_sessions = db.query(func.count(models.GatewaySession.id)).scalar() or 0
    alerts_generated = db.query(func.count(models.Alert.id)).scalar() or 0

    gateways = db.query(models.Gateway).all()
    gateways_online = sum(1 for g in gateways if live_status(g) == "online")
    last_upload_time = db.query(func.max(models.GatewaySession.created_at)).scalar()

    cards = schemas.DashboardCards(
        activeTrains=active_trains,
        uploadedSessions=uploaded_sessions,
        alertsGenerated=alerts_generated,
        gatewaysOnline=gateways_online,
        gatewaysTotal=len(gateways),
        lastUploadTime=last_upload_time,
    )

    # ---- RMS trend & Peak trend (last 60 axle readings, chronological) ---
    recent_axles = (
        db.query(models.AxleRecord, models.GatewaySession.timestamp)
        .join(models.GatewaySession, models.AxleRecord.session_id == models.GatewaySession.id)
        .order_by(models.GatewaySession.timestamp.asc())
        .filter(models.GatewaySession.timestamp >= last_7d)
        .limit(60)
        .all()
    )
    rms_trend = [
        schemas.RmsPoint(timestamp=ts, rms=axle.rms, axleId=axle.axle_id)
        for axle, ts in recent_axles
    ]
    peak_trend = [
        schemas.PeakPoint(timestamp=ts, peak=axle.peak, axleId=axle.axle_id)
        for axle, ts in recent_axles
    ]

    # ---- Route heatmap: violations + avg peak per route ------------------
    route_rows = (
        db.query(
            models.GatewaySession.route,
            func.count(func.distinct(models.GatewaySession.id)).label("sessions"),
        )
        .group_by(models.GatewaySession.route)
        .all()
    )
    route_heatmap = []
    for route, session_count in route_rows:
        violations = (
            db.query(func.count(models.Alert.id)).filter(models.Alert.route == route).scalar()
            or 0
        )
        avg_peak = (
            db.query(func.avg(models.AxleRecord.peak))
            .join(models.GatewaySession, models.AxleRecord.session_id == models.GatewaySession.id)
            .filter(models.GatewaySession.route == route)
            .scalar()
            or 0.0
        )
        route_heatmap.append(
            schemas.RouteHeatmapPoint(
                route=route,
                violations=violations,
                avgPeak=round(float(avg_peak), 2),
                sessions=session_count,
            )
        )

    # ---- Threshold violations over time (last 14 days, by severity) ------
    violation_rows = (
        db.query(
            func.date(models.Alert.created_at).label("day"),
            models.Alert.severity,
            func.count(models.Alert.id),
        )
        .filter(models.Alert.created_at >= now - timedelta(days=14))
        .group_by("day", models.Alert.severity)
        .all()
    )
    by_day: dict = {}
    for day, severity, count in violation_rows:
        day_str = str(day)
        by_day.setdefault(day_str, {"critical": 0, "warning": 0, "info": 0})
        by_day[day_str][severity.lower()] = count
    threshold_violations = [
        schemas.ThresholdViolationPoint(
            date=day_str,
            critical=vals["critical"],
            warning=vals["warning"],
            info=vals["info"],
        )
        for day_str, vals in sorted(by_day.items())
    ]

    # ---- GPS locations: latest session per train --------------------------
    latest_ids_subq = (
        db.query(
            models.GatewaySession.train_id,
            func.max(models.GatewaySession.id).label("max_id"),
        )
        .group_by(models.GatewaySession.train_id)
        .subquery()
    )
    latest_sessions = (
        db.query(models.GatewaySession)
        .join(latest_ids_subq, models.GatewaySession.id == latest_ids_subq.c.max_id)
        .all()
    )
    gps_locations = []
    for s in latest_sessions:
        has_alert = db.query(models.Alert).filter_by(session_id=s.id).first() is not None
        gps_locations.append(
            schemas.GpsLocationPoint(
                trainId=s.train_id,
                gatewayId=s.gateway_id,
                lat=s.lat,
                lon=s.lon,
                speedKmph=s.speed_kmph,
                status="Alert" if has_alert else "Normal",
                timestamp=s.timestamp,
            )
        )

    # ---- Sessions table: most recent 25 sessions with max peak ------------
    recent_sessions = (
        db.query(models.GatewaySession)
        .order_by(models.GatewaySession.timestamp.desc())
        .limit(25)
        .all()
    )
    sessions_table = []
    for s in recent_sessions:
        max_peak = (
            db.query(func.max(models.AxleRecord.peak)).filter_by(session_id=s.id).scalar() or 0.0
        )
        has_alert = db.query(models.Alert).filter_by(session_id=s.id).first() is not None
        sessions_table.append(
            schemas.SessionRow(
                trainId=s.train_id,
                gatewayId=s.gateway_id,
                route=s.route,
                speedKmph=s.speed_kmph,
                peak=round(float(max_peak), 2),
                status="Alert" if has_alert else "Normal",
                timestamp=s.timestamp,
            )
        )

    return schemas.DashboardOut(
        cards=cards,
        rmsTrend=rms_trend,
        peakTrend=peak_trend,
        routeHeatmap=route_heatmap,
        thresholdViolations=threshold_violations,
        gpsLocations=gps_locations,
        sessionsTable=sessions_table,
    )
