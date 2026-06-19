from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.services.retention import purge_expired_data

router = APIRouter(prefix="/api/v1", tags=["maintenance"])


@router.post("/maintenance/purge", response_model=schemas.PurgeResponse)
def purge(
    retention_days: int = Query(default=30, ge=1, description="Retention window in days (clause 6.4 default: 30)"),
    db: Session = Depends(get_db),
):
    """
    Deletes axle records, alerts, and sessions older than the retention
    window (clause 6.4: 30 days for space-domain data + alert reports).
    Intended to run as a scheduled job in production; exposed as an
    explicit endpoint here for auditability in this demo.
    """
    return purge_expired_data(db, retention_days=retention_days)
