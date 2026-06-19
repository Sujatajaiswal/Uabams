from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["sections"])


def _to_out(row: models.RouteSection) -> schemas.RouteSectionOut:
    return schemas.RouteSectionOut(
        id=row.id, route=row.route, railway=row.railway, division=row.division,
        section=row.section, fromKm=row.from_km, toKm=row.to_km,
    )


@router.get("/sections", response_model=List[schemas.RouteSectionOut])
def list_sections(db: Session = Depends(get_db)):
    """Railway / Division / Section reference data, for section-wise alert
    reporting per clause 6.7."""
    rows = db.query(models.RouteSection).order_by(models.RouteSection.route).all()
    return [_to_out(r) for r in rows]


@router.post("/sections", response_model=schemas.RouteSectionOut)
def add_section(payload: schemas.RouteSectionIn, db: Session = Depends(get_db)):
    row = models.RouteSection(
        route=payload.route, railway=payload.railway, division=payload.division,
        section=payload.section, from_km=payload.fromKm, to_km=payload.toKm,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)
