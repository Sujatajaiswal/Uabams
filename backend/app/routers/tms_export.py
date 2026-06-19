import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.tms_export import build_tms_export_zip

router = APIRouter(prefix="/api/v1", tags=["tms-export"])


@router.get("/export/tms")
def export_to_tms(
    days: int = Query(default=30, ge=1, le=90, description="Lookback window in days"),
    db: Session = Depends(get_db),
):
    """
    Generates the Module 5/clause-2.5 deliverable for the CRIS TMS hand-off:
    a ZIP containing the two required datasets (spatial acceleration data,
    processed peak data) as open CSV, plus a genuine empty target .mdb
    container and an import script - see tms_export.py for the full
    rationale behind this packaging.
    """
    zip_bytes = build_tms_export_zip(db, days=days)
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=uabams_tms_export_{days}d.zip"
        },
    )
