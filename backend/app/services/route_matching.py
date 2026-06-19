"""
Nearest track-feature lookup.

Clause 4.10 requires the system to identify the track/route using a
pre-prepared route data file (lat/lon, provided by RDSO). Clause 6.1
requires every stored safety alert to carry the nearest track feature
alongside its instantaneous speed. Annexure-II of the spec shows the
actual route file format (KM marker rows, some with lat/lon).

This module loads whatever RouteTrackPoint reference rows exist for a
route (seeded from real Annexure-II-shaped data, or uploaded via
POST /api/v1/route-files) and finds the nearest KM marker to a given
GPS fix using the haversine great-circle distance. With only a few
hundred reference points per route this linear scan is fast enough;
a real CRIS-scale deployment would add a spatial index (e.g. PostGIS)
if route files grew very large.
"""
import math
from typing import Optional

from sqlalchemy.orm import Session

from app import models

EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_track_feature_km(db: Session, route: str, lat: float, lon: float) -> Optional[float]:
    """Returns the KM marker of the closest reference point on `route`, or
    None if no route file has been loaded for that route yet."""
    points = db.query(models.RouteTrackPoint).filter_by(route=route).all()
    if not points:
        return None

    best_km, best_dist = None, None
    for p in points:
        d = _haversine_km(lat, lon, p.lat, p.lon)
        if best_dist is None or d < best_dist:
            best_dist, best_km = d, p.km
    return best_km
