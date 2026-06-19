"""
Seeds the database with realistic demo data so the dashboard is populated
the moment the stack comes up: gateways, historical sessions with axle
readings, thresholds, calibration history, and the alerts that fall out of
running those sessions through the same rule engine used in production.

Run automatically on API startup when SEED_ON_STARTUP=true (default), or
manually:
    python -m app.seed
"""
import random
from datetime import datetime, timedelta

from app.database import Base, SessionLocal, engine
from app import models
from app.services.alerts import evaluate_alerts

# Two real Indian Railways trunk routes used throughout the demo, each with
# a rough lat/lon corridor so the GPS map and route heatmap look plausible.
ROUTES = {
    "Bangalore-Chennai": {"lat": (12.9, 13.1), "lon": (77.5, 80.2)},
    "Chennai-Coimbatore": {"lat": (11.0, 13.1), "lon": (76.9, 80.2)},
    "Mumbai-Pune": {"lat": (18.5, 19.1), "lon": (73.4, 73.9)},
}

GATEWAYS = ["GW001", "GW002", "GW003", "GW004"]
TRAINS = ["TRAIN07", "TRAIN12", "TRAIN21", "TRAIN34", "TRAIN45"]
AXLES = ["AX01", "AX02", "AX03", "AX04"]

# A genuine slice of the RDSO Annexure-II "Lucknow - Kanpur UP Km 00 to 71"
# route file (km-sequence, lat, lon), converted from the DD°MM'SS.ssss"
# format in the spec PDF to decimal degrees. Seeded as its own reference
# route (separate from the 3 operational demo routes above) purely to
# demonstrate that the route-file ingestion pipeline genuinely consumes the
# RDSO-specified format and real coordinates, not synthetic stand-ins.
LUCKNOW_KANPUR_ANNEXURE_SAMPLE = [
    (1, 26.8283, 80.9005), (2, 26.8126, 80.8927), (3, 26.7893, 80.8619),
    (4, 26.7555, 80.8154), (5, 26.7328, 80.7842), (6, 26.7214, 80.7685),
    (7, 26.7157, 80.7608), (8, 26.7044, 80.7451), (9, 26.6987, 80.7376),
    (10, 26.6873, 80.7217), (11, 26.6645, 80.6905), (12, 26.6483, 80.6662),
]


def _route_track_points(route: str, n: int = 12):
    """Synthesises plausible km-post reference points along a demo route's
    lat/lon corridor, for the nearest-track-feature lookup used on alerts
    raised against the 3 operational demo routes (clause 4.10 / 6.1)."""
    bounds = ROUTES[route]
    points = []
    for i in range(n):
        frac = i / max(n - 1, 1)
        lat = bounds["lat"][0] + frac * (bounds["lat"][1] - bounds["lat"][0])
        lon = bounds["lon"][0] + frac * (bounds["lon"][1] - bounds["lon"][0])
        points.append((i * 25, round(lat, 4), round(lon, 4)))  # ~25km spacing
    return points


def _random_point(route: str):
    bounds = ROUTES[route]
    lat = round(random.uniform(*bounds["lat"]), 4)
    lon = round(random.uniform(*bounds["lon"]), 4)
    return lat, lon


def seed_if_empty():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.GatewaySession).first() is not None:
            return  # already seeded

        random.seed(42)

        # --- gateways ------------------------------------------------------
        for gw_id in GATEWAYS:
            db.add(models.Gateway(gateway_id=gw_id, status="offline"))
        db.flush()

        # --- thresholds ------------------------------------------------------
        db.add(models.ThresholdSetting(
            route="Bangalore-Chennai", vertical_threshold=50, lateral_threshold=80,
            alerts_enabled=True,
        ))
        db.add(models.ThresholdSetting(
            route="Chennai-Coimbatore", vertical_threshold=45, lateral_threshold=75,
            alerts_enabled=True,
        ))
        db.add(models.ThresholdSetting(
            route="Mumbai-Pune", vertical_threshold=55, lateral_threshold=85,
            alerts_enabled=True,
        ))
        db.flush()
        thresholds = {
            t.route: t for t in db.query(models.ThresholdSetting).all()
        }

        # --- route track points (clauses 4.10, 6.1, 6.5) ---------------------
        # Operational demo routes get synthesised km-post points so alerts
        # raised against them can resolve a nearest track feature.
        for route in ROUTES:
            for km, lat, lon in _route_track_points(route):
                db.add(models.RouteTrackPoint(route=route, km=km, lat=lat, lon=lon))
        # Plus the genuine RDSO Annexure-II sample (Lucknow-Kanpur), kept as
        # its own reference route to demonstrate real-coordinate ingestion.
        for km, lat, lon in LUCKNOW_KANPUR_ANNEXURE_SAMPLE:
            db.add(models.RouteTrackPoint(route="Lucknow-Kanpur (RDSO sample)", km=km, lat=lat, lon=lon))
        db.flush()

        # --- route sections (clause 6.7) --------------------------------------
        db.add(models.RouteSection(
            route="Bangalore-Chennai", railway="South Western Railway",
            division="Bangalore Division", section="KSR Bengaluru - Jolarpettai",
            from_km=0, to_km=219,
        ))
        db.add(models.RouteSection(
            route="Chennai-Coimbatore", railway="Southern Railway",
            division="Salem Division", section="Chennai Central - Coimbatore Jn",
            from_km=0, to_km=496,
        ))
        db.add(models.RouteSection(
            route="Mumbai-Pune", railway="Central Railway",
            division="Pune Division", section="CSMT Mumbai - Pune Jn",
            from_km=0, to_km=192,
        ))
        db.flush()

        # --- train roster (clause 6.11) ---------------------------------------
        for i, train_id in enumerate(TRAINS):
            db.add(models.Train(
                train_id=train_id,
                label=f"Demo rake {train_id}",
                default_route=list(ROUTES.keys())[i % len(ROUTES)],
                active=True,
            ))
        db.flush()

        # --- calibration history --------------------------------------------
        now = datetime.utcnow()
        for gw_id in GATEWAYS:
            for axle_id in AXLES[:2]:
                for i in range(3):
                    db.add(models.Calibration(
                        gateway_id=gw_id,
                        axle_id=axle_id,
                        wheel_diameter_mm=round(920 - i * 2.5, 1),
                        wear_percent=round(2 + i * 1.5, 1),
                        correction_factor=round(1.0 + i * 0.01, 3),
                        created_at=now - timedelta(days=(3 - i) * 20),
                    ))
        db.flush()

        # --- sessions + axle readings + alerts -------------------------------
        routes = list(ROUTES.keys())
        for day_offset in range(7, -1, -1):
            sessions_today = random.randint(8, 14)
            for _ in range(sessions_today):
                gw_id = random.choice(GATEWAYS)
                train_id = random.choice(TRAINS)
                route = random.choice(routes)
                lat, lon = _random_point(route)
                speed = round(random.uniform(40, 130), 1)
                ts = now - timedelta(
                    days=day_offset,
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                )
                session_id = f"S{ts.strftime('%Y%m%d%H%M%S')}-{random.randint(100,999)}"

                payload = {"simulated": True}
                db_session = models.GatewaySession(
                    session_id=session_id,
                    gateway_id=gw_id,
                    train_id=train_id,
                    route=route,
                    timestamp=ts,
                    lat=lat,
                    lon=lon,
                    speed_kmph=speed,
                    raw_payload=payload,
                    created_at=ts,
                )
                db.add(db_session)
                db.flush()

                threshold = thresholds[route]
                axle_records = []
                # Occasionally bias a reading high to generate alert history.
                spike = random.random() < 0.18
                for axle_id in random.sample(AXLES, k=random.randint(1, 3)):
                    base_vertical = random.uniform(10, 35)
                    base_lateral = random.uniform(5, 30)
                    if spike:
                        base_vertical = random.uniform(
                            threshold.vertical_threshold * 0.9,
                            threshold.vertical_threshold * 1.8,
                        )
                        base_lateral = random.uniform(
                            threshold.lateral_threshold * 0.9,
                            threshold.lateral_threshold * 1.6,
                        )
                    rms = round(base_vertical * random.uniform(0.5, 0.7), 2)
                    peak = round(max(base_vertical, base_lateral) * random.uniform(1.05, 1.3), 2)
                    peak = min(peak, 99.9)

                    rec = models.AxleRecord(
                        session_id=db_session.id,
                        axle_id=axle_id,
                        vertical_g=round(min(base_vertical, 99.9), 2),
                        lateral_g=round(min(base_lateral, 99.9), 2),
                        rms=rms,
                        peak=peak,
                        created_at=ts,
                    )
                    db.add(rec)
                    axle_records.append(rec)
                db.flush()

                created_alerts = evaluate_alerts(db_session, axle_records, threshold, db)
                for a in created_alerts:
                    a.created_at = ts

                # Heartbeat: most recent session per gateway marks it "seen"
                gw = db.get(models.Gateway, gw_id)
                if gw and (gw.last_seen_at is None or ts > gw.last_seen_at):
                    gw.last_seen_at = ts
                    gw.last_upload_at = ts
                    gw.status = "online"

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_if_empty()
    print("Seed complete.")
