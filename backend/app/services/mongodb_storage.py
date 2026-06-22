from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.config import settings

logger = logging.getLogger("uabams.mongodb")
_client: Optional[MongoClient] = None


def mongo_enabled() -> bool:
    return bool(settings.MONGODB_URL.strip())


def get_mongo_db():
    global _client
    if not mongo_enabled():
        return None
    if _client is None:
        _client = MongoClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000)
    return _client[settings.MONGODB_DB_NAME]


def _clean(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def insert_document(collection: str, document: Dict[str, Any]) -> Optional[str]:
    db = get_mongo_db()
    if db is None:
        return None
    try:
        doc = _clean(document)
        doc.setdefault("storedAt", datetime.utcnow().isoformat())
        result = db[collection].insert_one(doc)
        return str(result.inserted_id)
    except PyMongoError as exc:
        logger.warning("MongoDB insert skipped for %s: %s", collection, exc)
        return None


def mirror_archive_upload(
    *,
    archive: Dict[str, Any],
    raw_payload: Dict[str, Any],
    axle_records: Iterable[Dict[str, Any]],
    alerts: Iterable[Dict[str, Any]],
    sms_logs: Iterable[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    """Mirror one gateway upload into MongoDB document collections.

    PostgreSQL remains the source of truth. This mirror gives the team a
    visible cloud document store for raw gateway data and alert/SMS audit logs.
    """
    if not mongo_enabled():
        return {}

    axle_list = list(axle_records)
    alert_list = list(alerts)
    sms_list = list(sms_logs)
    archive_doc = {
        **archive,
        "rawPayload": raw_payload,
        "axleRecords": axle_list,
        "alerts": alert_list,
        "smsNotifications": sms_list,
    }

    return {
        "gateway_archives": insert_document("gateway_archives", archive_doc),
        "raw_gateway_payloads": insert_document(
            "raw_gateway_payloads",
            {**archive, "payload": raw_payload},
        ),
        "alert_notifications": insert_document(
            "alert_notifications",
            {**archive, "alerts": alert_list},
        ) if alert_list else None,
        "sms_logs": insert_document(
            "sms_logs",
            {**archive, "smsNotifications": sms_list},
        ) if sms_list else None,
    }


def storage_summary(limit: int = 5) -> Dict[str, Any]:
    db = get_mongo_db()
    if db is None:
        return {"enabled": False, "database": settings.MONGODB_DB_NAME, "collections": []}

    collections: List[Dict[str, Any]] = []
    for name in [
        "gateway_archives",
        "raw_gateway_payloads",
        "alert_notifications",
        "sms_logs",
    ]:
        count = db[name].count_documents({})
        latest = list(db[name].find({}, {"_id": 0}).sort("storedAt", -1).limit(limit))
        collections.append({"name": name, "count": count, "latest": _clean(latest)})

    return {"enabled": True, "database": settings.MONGODB_DB_NAME, "collections": collections}
