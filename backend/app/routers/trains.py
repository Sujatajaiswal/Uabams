from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["trains"])


def _to_out(row: models.Train) -> schemas.TrainOut:
    return schemas.TrainOut(
        trainId=row.train_id,
        label=row.label,
        defaultRoute=row.default_route,
        active=row.active,
        createdAt=row.created_at,
    )


@router.get("/trains", response_model=List[schemas.TrainOut])
def list_trains(db: Session = Depends(get_db)):
    rows = db.query(models.Train).order_by(models.Train.train_id).all()
    return [_to_out(r) for r in rows]


@router.post("/trains", response_model=schemas.TrainOut)
def upsert_train(payload: schemas.TrainIn, db: Session = Depends(get_db)):
    """Add a train, or edit it (by trainId) if it already exists - clause 6.11."""
    row = db.query(models.Train).filter_by(train_id=payload.trainId).first()
    if row is None:
        row = models.Train(train_id=payload.trainId)
        db.add(row)

    row.label = payload.label
    row.default_route = payload.defaultRoute
    row.active = payload.active if payload.active is not None else True

    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/trains/{train_id}")
def delete_train(train_id: str, db: Session = Depends(get_db)):
    row = db.query(models.Train).filter_by(train_id=train_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Train not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "trainId": train_id}
