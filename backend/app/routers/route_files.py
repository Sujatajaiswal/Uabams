from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["route-files"])


def _to_out(row: models.RouteTrackPoint) -> schemas.RouteTrackPointOut:
    return schemas.RouteTrackPointOut(id=row.id, route=row.route, km=row.km, lat=row.lat, lon=row.lon)


@router.post("/route-files", response_model=List[schemas.RouteTrackPointOut])
def upload_route_file(payload: schemas.RouteTrackPointUploadIn, db: Session = Depends(get_db)):
    """
    Loads RDSO-provided route reference data (clause 4.10) - the KM-marker
    lat/lon rows shown in Annexure-II of TM/IM/434 - for a named route.
    Re-uploading a route replaces its existing reference points.
    """
    db.query(models.RouteTrackPoint).filter_by(route=payload.route).delete()
    rows = [
        models.RouteTrackPoint(route=payload.route, km=p.km, lat=p.lat, lon=p.lon)
        for p in payload.points
    ]
    db.add_all(rows)
    db.commit()
    return [_to_out(r) for r in rows]


@router.get("/route-files", response_model=List[schemas.RouteTrackPointOut])
def list_route_file(route: str = Query(...), db: Session = Depends(get_db)):
    rows = (
        db.query(models.RouteTrackPoint)
        .filter_by(route=route)
        .order_by(models.RouteTrackPoint.km)
        .all()
    )
    return [_to_out(r) for r in rows]
