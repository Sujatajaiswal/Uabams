"""
Module 3 alert rule:

    IF speedKmph >= ALERT_SPEED_GATE_KMPH AND peak > threshold -> generate alert

Severity is graded by how far the reading exceeds the threshold:
    >= 50% over threshold  -> Critical
    >= 20% over threshold  -> Warning
    >  0% over threshold   -> Info

verticalG is compared against the route's verticalThreshold and lateralG
against lateralThreshold independently, so a single axle reading can raise
zero, one, or two alerts (one per metric).
"""
from typing import List

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.services.route_matching import nearest_track_feature_km


def _severity_for(value: float, threshold: float) -> str:
    if threshold <= 0:
        return "Info"
    overshoot_ratio = (value - threshold) / threshold
    if overshoot_ratio >= 0.5:
        return "Critical"
    if overshoot_ratio >= 0.2:
        return "Warning"
    return "Info"


def evaluate_alerts(
    db_session: models.GatewaySession,
    axle_records: List[models.AxleRecord],
    threshold: models.ThresholdSetting,
    db: Session,
) -> List[models.Alert]:
    created: List[models.Alert] = []

    if not threshold.alerts_enabled:
        return created

    if db_session.speed_kmph < settings.ALERT_SPEED_GATE_KMPH:
        return created

    nearest_km = nearest_track_feature_km(db, db_session.route, db_session.lat, db_session.lon)

    for axle in axle_records:
        if axle.vertical_g > threshold.vertical_threshold:
            severity = _severity_for(axle.vertical_g, threshold.vertical_threshold)
            alert = models.Alert(
                session_id=db_session.id,
                gateway_id=db_session.gateway_id,
                train_id=db_session.train_id,
                route=db_session.route,
                axle_id=axle.axle_id,
                metric="vertical",
                value=axle.vertical_g,
                threshold_value=threshold.vertical_threshold,
                speed_kmph=db_session.speed_kmph,
                severity=severity,
                nearest_track_feature_km=nearest_km,
                message=(
                    f"{severity} vertical acceleration on {axle.axle_id}: "
                    f"{axle.vertical_g:.1f}g exceeds threshold {threshold.vertical_threshold:.1f}g "
                    f"at {db_session.speed_kmph:.0f} km/h"
                ),
            )
            db.add(alert)
            created.append(alert)

        if axle.lateral_g > threshold.lateral_threshold:
            severity = _severity_for(axle.lateral_g, threshold.lateral_threshold)
            alert = models.Alert(
                session_id=db_session.id,
                gateway_id=db_session.gateway_id,
                train_id=db_session.train_id,
                route=db_session.route,
                axle_id=axle.axle_id,
                metric="lateral",
                value=axle.lateral_g,
                threshold_value=threshold.lateral_threshold,
                speed_kmph=db_session.speed_kmph,
                severity=severity,
                nearest_track_feature_km=nearest_km,
                message=(
                    f"{severity} lateral acceleration on {axle.axle_id}: "
                    f"{axle.lateral_g:.1f}g exceeds threshold {threshold.lateral_threshold:.1f}g "
                    f"at {db_session.speed_kmph:.0f} km/h"
                ),
            )
            db.add(alert)
            created.append(alert)

    return created


def get_or_default_threshold(db: Session, route: str) -> models.ThresholdSetting:
    threshold = db.query(models.ThresholdSetting).filter_by(route=route).first()
    if threshold:
        return threshold
    # Fall back to a global default row (created on first use, not persisted
    # unless the operator explicitly saves one via the settings page).
    return models.ThresholdSetting(
        route=route,
        vertical_threshold=settings.DEFAULT_VERTICAL_THRESHOLD,
        lateral_threshold=settings.DEFAULT_LATERAL_THRESHOLD,
        alerts_enabled=True,
    )
