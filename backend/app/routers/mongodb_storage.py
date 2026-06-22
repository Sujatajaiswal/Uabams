from fastapi import APIRouter, Query

from app.services.mongodb_storage import storage_summary

router = APIRouter(prefix="/api/v1", tags=["mongodb-storage"])


@router.get("/mongodb-storage")
def get_mongodb_storage(limit: int = Query(default=5, ge=1, le=20)):
    return storage_summary(limit=limit)
