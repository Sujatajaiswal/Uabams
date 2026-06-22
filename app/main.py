import csv
import hashlib
import io
import json
import os
import re
import struct
import zipfile
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field

try:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except Exception:  # pragma: no cover - keeps PostgreSQL-only deployments usable
    MongoClient = None
    PyMongoError = Exception


app = FastAPI(title="UABAMS Cloud", docs_url=None)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

ALERT_SPEED_LIMIT_KMPH = 80
MIN_MEASUREMENT_SPEED_KMPH = 20
MAX_MEASUREMENT_SPEED_KMPH = 160
SPATIAL_SAMPLE_DISTANCE_M = 0.25
PEAK_WINDOW_DISTANCE_M = 50
AXLE_ACCELERATION_RANGE_G = 100
BOGIE_ACCELERATION_RANGE_G = 5
AXLE_MAX_FREQUENCY_HZ = 500
BOGIE_MAX_FREQUENCY_HZ = 100
AXLE_MIN_SAMPLING_HZ = 2500
BOGIE_MIN_SAMPLING_HZ = 500
PEAK_LOCATION_ACCURACY_M = 5
SPEED_ACCURACY_PERCENT = 2
RAW_TIME_DOMAIN_RETENTION_DAYS = 7
SPATIAL_ALERT_RETENTION_DAYS = 30
MAX_SUPPORTED_TRAIN_SYSTEMS = 100
PEAK_AXIS_THRESHOLDS_MG = {
    "al_x": 10000,
    "al_y": 8000,
    "al_z": 12000,
    "ar_x": 10000,
    "ar_y": 8000,
    "ar_z": 12000,
    "bg_x": 5000,
    "bg_y": 4000,
    "bg_z": 6000,
}
AXIS_ALERT_GROUPS = {
    "al_x": "LATERAL",
    "al_y": "LATERAL",
    "al_z": "VERTICAL",
    "ar_x": "LATERAL",
    "ar_y": "LATERAL",
    "ar_z": "VERTICAL",
    "bg_x": "LATERAL",
    "bg_y": "LATERAL",
    "bg_z": "VERTICAL",
}
ARCHIVE_STORAGE_DIR = Path(os.getenv("ARCHIVE_STORAGE_DIR", "uploaded_archives"))
SUPPORTED_SESSION_SCHEMA_VERSION = "1.0"
SESSION_NAME_RE = re.compile(r"SESSION_\d{8}_\d{6}$")
REQUIRED_ARCHIVE_FILES = [
    "session_metadata.json",
    "rms/rms_25cm.bin",
    "peak/peak_50m.bin",
    "faults/faults.bin",
    "raw/adxl_left.bin",
    "raw/adxl_right.bin",
    "raw/bogie.bin",
    "raw/encoder.bin",
]
FIXED_RECORD_SIZES = {
    "rms/rms_25cm.bin": 70,
    "peak/peak_50m.bin": 302,
    "faults/faults.bin": 75,
}
PEAK_AXIS_THRESHOLDS_G = {
    axis_name: threshold_mg / 1000
    for axis_name, threshold_mg in PEAK_AXIS_THRESHOLDS_MG.items()
}
MONGODB_URL = os.getenv("MONGODB_URL", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "uabams_cloud")
AUTH_API_KEY = os.getenv("AUTH_API_KEY", "uabams-demo-api-key")
SMS_ENABLED = os.getenv("SMS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
SMS_PROVIDER_URL = os.getenv("SMS_PROVIDER_URL", "")
SMS_API_KEY = os.getenv("SMS_API_KEY", "")
SMS_FROM = os.getenv("SMS_FROM", "UABAMS")
SMS_TO_NUMBERS = [number.strip() for number in os.getenv("SMS_TO_NUMBERS", "").split(",") if number.strip()]
_mongo_client = None



MONGO_STORAGE_COLLECTIONS = [
    "gateway_archives",
    "raw_gateway_payloads",
    "archive_uploads",
    "alert_notifications",
    "sms_logs",
    "route_reference",
    "section_reference",
    "device_health",
    "power_status",
    "retention_actions",
    "operation_decisions",
]
CSV_REPORTS = {
    "archives": {
        "title": "Session Archives",
        "filename": "uabams_session_archives.csv",
        "query": """
            SELECT
                archive_id,
                gateway_id,
                train_id,
                session_name,
                archive_name,
                archive_size_bytes,
                upload_received_utc,
                storage_uri,
                checksum,
                validation_status
            FROM archives
            ORDER BY archive_id DESC
            LIMIT :limit
        """,
    },
    "extracted-files": {
        "title": "Extracted Files",
        "filename": "uabams_extracted_files.csv",
        "query": """
            SELECT
                file_id,
                archive_id,
                session_id,
                file_relative_path,
                extracted_at_utc,
                file_size_bytes,
                storage_uri,
                integrity_ok
            FROM extracted_files
            ORDER BY file_id DESC
            LIMIT :limit
        """,
    },
    "cloud-alert-events": {
        "title": "Cloud Alert Events",
        "filename": "uabams_cloud_alert_events.csv",
        "query": """
            SELECT
                alert_event_id,
                gateway_id,
                train_id,
                session_name,
                window_start_mm,
                window_end_mm,
                speed_kmph,
                triggered_axes_count,
                received_utc
            FROM cloud_alert_events
            ORDER BY alert_event_id DESC
            LIMIT :limit
        """,
    },
    "rms-records": {
        "title": "RMS 25cm Records",
        "filename": "uabams_rms_25cm_records.csv",
        "query": """
            SELECT
                rms_id,
                session_id,
                record_index,
                master_count,
                position_mm,
                latitude,
                longitude,
                gps_valid,
                valid_mask,
                al_x_mg,
                al_y_mg,
                al_z_mg,
                ar_x_mg,
                ar_y_mg,
                ar_z_mg,
                bg_x_mg,
                bg_y_mg,
                bg_z_mg
            FROM rms_records
            ORDER BY rms_id DESC
            LIMIT :limit
        """,
    },
    "peak-records": {
        "title": "Peak 50m Records",
        "filename": "uabams_peak_50m_records.csv",
        "query": """
            SELECT
                peak_id,
                session_id,
                record_index,
                window_start_mm,
                window_end_mm,
                speed_kmph,
                valid_mask,
                alert_generated,
                axis_data_json
            FROM peak_records
            ORDER BY peak_id DESC
            LIMIT :limit
        """,
    },
    "fault-records": {
        "title": "Fault Records",
        "filename": "uabams_fault_records.csv",
        "query": """
            SELECT
                fault_id,
                session_id,
                record_index,
                timestamp_ms,
                fault_code,
                node_id,
                severity,
                description
            FROM fault_records
            ORDER BY fault_id DESC
            LIMIT :limit
        """,
    },
    "raw-packet-records": {
        "title": "Raw Packet Metadata",
        "filename": "uabams_raw_packet_records.csv",
        "query": """
            SELECT
                raw_packet_id,
                session_id,
                file_relative_path,
                record_index,
                packet_length,
                sof,
                packet_type,
                node_id,
                sequence_number,
                eof,
                truncated
            FROM raw_packet_records
            ORDER BY raw_packet_id DESC
            LIMIT :limit
        """,
    },
}

TMS_EXPORT_REPORTS = [
    "rms-records",
    "peak-records",
]

TMS_TRANSFER_FILES = {
    "rms-records": {
        "filename": "spatial_acceleration_data.txt",
        "mdb_table": "SpatialAccelerationData",
        "description": "Spatial acceleration data sampled at about 25 cm intervals.",
    },
    "peak-records": {
        "filename": "processed_peak_data.txt",
        "mdb_table": "ProcessedPeakData",
        "description": "Processed peak data summarized per 50 m window.",
    },
}

TMS_SCHEMA_TEXT = """UABAMS TMS Transfer Package

Specification alignment:
- Processing station data is stored in PostgreSQL database tables.
- Open ASCII text exports are generated from the same database records.
- TMS transfer data includes spatial acceleration data and processed peak data.
- MDB is the preferred final TMS transfer format in the specification. Actual MDB file generation requires a Microsoft Access/ODBC-compatible writer in the target CRIS/vendor environment. This package keeps the data open and documented so it can be imported into MDB/TMS.
- Spatial acceleration data uses the 25 cm sampling interval requirement.
- Processed peak data is summarized per 50 m window.
- Alert events are speed-gated at 80 kmph and contain measured value plus GPS latitude/longitude for map and notification output.
- If multiple peaks exceed the configured limits in one 50 m window, the cloud keeps the highest vertical peak and highest lateral peak separately.
- Gateway can retain session archives during network/GSM unavailability and retry upload. Cloud returns HTTP 200/201 only after accepting the data so the gateway can clear local storage.
- Speed measurement band documented for the system is 20-160 kmph.
- Axle box acceleration measurement range is documented as +/-100g; bogie level range is documented as +/-5g.
- Expected frequency range is 0-500 Hz at axle level and 0-100 Hz at bogie level. Minimum sampling frequency is 2500 Hz at axle level and 500 Hz at bogie level.
- Peak location accuracy requirement is better than 5 m. Cloud stores peak latitude/longitude and peak position for map/report output.
- Speed measurement accuracy requirement is +/-2% of actual speed. Cloud stores original and corrected speed values where available.
- Discrete time-domain/raw data retention requirement is 7 days. Spatial acceleration data and alert reports retention requirement is 30 days at the processing station.
- Processing station should scale for up to 100 train systems and route-wise threshold limits from 0 to 100g.
- Data transfer should use suitable encryption; production deployment should use HTTPS/private APN or equivalent secure network.

Included TMS data files:
- spatial_acceleration_data.txt: spatial acceleration data, one record per approx. 25 cm segment. Target MDB table: SpatialAccelerationData.
- processed_peak_data.txt: processed peak data, one record per 50 m window. Target MDB table: ProcessedPeakData.

ASCII transfer format:
- Delimiter: pipe character |
- First row: column names
- Encoding: UTF-8
- Null/empty values: blank field

Key record sizes in source binary files:
- rms/rms_25cm.bin: 70 bytes per record.
- peak/peak_50m.bin: 302 bytes per record.
- faults/faults.bin: 75 bytes per record.

Gateway upload API:
- Method: PUT
- Endpoint: /api/v1/archive
- Body: Raw ZIP archive bytes.
- Archive name: <gatewayId>__<trainId>__<sessionName>.zip
"""


def round_value(value, digits=4):
    if value is None:
        return None
    return round(float(value), digits)


def database_host():
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        return "Not configured"
    return urlparse(database_url).hostname or "Configured"


def utc_now():
    return datetime.utcnow()




def verify_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if not AUTH_API_KEY:
        return True
    if x_api_key != AUTH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return True


def mongo_enabled():
    return bool(MONGODB_URL) and MongoClient is not None


def get_mongo_db():
    global _mongo_client
    if not mongo_enabled():
        return None
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=10000, connectTimeoutMS=20000, socketTimeoutMS=20000, tls=True)
    return _mongo_client[MONGODB_DB_NAME]


def clean_for_mongo(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"byteLength": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {str(key): clean_for_mongo(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_for_mongo(item) for item in value]
    return value


def mongo_insert(collection_name: str, document: dict):
    if not mongo_enabled():
        return None
    db = get_mongo_db()
    prepared = clean_for_mongo(document)
    prepared.setdefault("createdAt", utc_now().isoformat())
    try:
        result = db[collection_name].insert_one(prepared)
        return str(result.inserted_id)
    except PyMongoError as exc:
        return {"error": str(exc)}


def mongo_storage_summary(limit: int = 5):
    safe_limit = max(1, min(limit, 50))
    summary = {
        "configured": bool(MONGODB_URL),
        "driverAvailable": MongoClient is not None,
        "database": MONGODB_DB_NAME,
        "collections": {},
    }
    if not mongo_enabled():
        summary["status"] = "not_configured"
        summary["message"] = "Set MONGODB_URL in Render environment variables to enable MongoDB Atlas storage."
        return summary
    try:
        db = get_mongo_db()
        db.command("ping")
        for name in MONGO_STORAGE_COLLECTIONS:
            collection = db[name]
            rows = list(collection.find({}, {"_id": 0}).sort("createdAt", -1).limit(safe_limit))
            summary["collections"][name] = {
                "count": collection.count_documents({}),
                "latest": clean_for_mongo(rows),
            }
        summary["status"] = "connected"
    except PyMongoError as exc:
        summary["status"] = "error"
        summary["error"] = str(exc)
    return summary


def mirror_archive_to_mongo(payload: dict):
    return mongo_insert("archive_uploads", payload)


def sms_provider_status():
    if SMS_ENABLED and SMS_PROVIDER_URL and SMS_API_KEY and SMS_TO_NUMBERS:
        return "configured"
    if SMS_ENABLED:
        return "incomplete_configuration"
    return "demo_log_only"


def build_sms_message(alert_doc: dict):
    gps = alert_doc.get("gps") or {}
    lat = gps.get("lat") or alert_doc.get("latitude") or "-"
    lon = gps.get("lon") or alert_doc.get("longitude") or "-"
    return (
        f"UABAMS ALERT: Train {alert_doc.get('trainId', '-')} peak "
        f"{alert_doc.get('peakG', alert_doc.get('peakValueMg', '-'))} at "
        f"{alert_doc.get('speedKmph', '-')} kmph. GPS {lat}, {lon}."
    )


def send_sms_notification(alert_doc: dict, message: Optional[str] = None):
    message = message or build_sms_message(alert_doc)
    recipients = SMS_TO_NUMBERS or ["NOT_CONFIGURED"]
    logs = []
    for recipient in recipients:
        log_doc = {
            "gatewayId": alert_doc.get("gatewayId"),
            "trainId": alert_doc.get("trainId"),
            "sessionName": alert_doc.get("sessionName"),
            "routeName": alert_doc.get("routeName"),
            "recipient": recipient,
            "sender": SMS_FROM,
            "message": message,
            "provider": SMS_PROVIDER_URL or "demo",
            "status": "skipped",
            "providerStatus": sms_provider_status(),
            "createdAt": utc_now().isoformat(),
        }
        if SMS_ENABLED and SMS_PROVIDER_URL and SMS_API_KEY and recipient != "NOT_CONFIGURED":
            try:
                payload = json.dumps({
                    "sender": SMS_FROM,
                    "recipient": recipient,
                    "message": message,
                    "alert": clean_for_mongo(alert_doc),
                }).encode("utf-8")
                request = urllib.request.Request(
                    SMS_PROVIDER_URL,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": SMS_API_KEY,
                        "authkey": SMS_API_KEY,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    body = response.read().decode("utf-8", errors="replace")
                log_doc["status"] = "sent"
                log_doc["providerResponse"] = body[:1000]
            except Exception as exc:
                log_doc["status"] = "failed"
                log_doc["error"] = str(exc)
        else:
            log_doc["status"] = "skipped"
            log_doc["note"] = "SMS provider not configured; message stored for demo/logging."
        log_doc["mongoId"] = mongo_insert("sms_logs", log_doc)
        logs.append(log_doc)
    return logs



def extract_archive_filename(request: Request, filename: Optional[str]):
    if filename:
        return Path(filename).name

    header_name = request.headers.get("x-archive-name")
    if header_name:
        return Path(header_name).name

    content_disposition = request.headers.get("content-disposition", "")
    match = re.search(r'filename="?([^";]+)"?', content_disposition)
    if match:
        return Path(match.group(1)).name

    return None


def parse_archive_filename(archive_name: str):
    if not archive_name.endswith(".zip"):
        raise HTTPException(
            status_code=422,
            detail="Invalid archive filename. Expected <gatewayId>__<trainId>__<sessionName>.zip",
        )

    stem = archive_name[:-4]
    parts = stem.split("__")
    if len(parts) != 3:
        raise HTTPException(
            status_code=422,
            detail="Invalid archive filename. Expected exactly three fields separated by double underscores.",
        )
    gateway_id, train_id, session_name = parts

    if not gateway_id or not train_id or not SESSION_NAME_RE.match(session_name):
        raise HTTPException(
            status_code=422,
            detail="Invalid archive filename. Expected <gatewayId>__<trainId>__<sessionName>.zip",
        )
    return {
        "gateway_id": gateway_id,
        "train_id": train_id,
        "session_name": session_name,
    }


def safe_extract_zip(zip_file: zipfile.ZipFile, destination: Path):
    destination = destination.resolve()
    for member in zip_file.infolist():
        target = (destination / member.filename).resolve()
        if not str(target).startswith(str(destination)):
            raise HTTPException(status_code=400, detail="Archive contains unsafe file paths")
    zip_file.extractall(destination)


def read_session_metadata(extract_dir: Path):
    metadata_path = extract_dir / "session_metadata.json"
    if not metadata_path.exists():
        return None
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid session_metadata.json: {exc}") from exc


def validate_archive_contents(extract_dir: Path, filename_parts: dict):
    missing_files = [
        file_path
        for file_path in REQUIRED_ARCHIVE_FILES
        if not (extract_dir / file_path).exists()
    ]
    metadata = read_session_metadata(extract_dir)

    validation_errors = []
    validation_status = "ok"

    if missing_files:
        validation_errors.append(f"Missing files: {', '.join(missing_files)}")
        validation_status = "incomplete"

    if not metadata:
        validation_errors.append("session_metadata.json is missing")
        validation_status = "incomplete"
    else:
        if metadata.get("schemaVersion") != SUPPORTED_SESSION_SCHEMA_VERSION:
            validation_errors.append(
                f"Unsupported schemaVersion: {metadata.get('schemaVersion')}"
            )
            validation_status = "quarantined"

        for meta_key, filename_key in [
            ("gatewayId", "gateway_id"),
            ("trainId", "train_id"),
            ("sessionName", "session_name"),
        ]:
            if metadata.get(meta_key) != filename_parts[filename_key]:
                validation_errors.append(
                    f"{meta_key} mismatch: filename has {filename_parts[filename_key]}, metadata has {metadata.get(meta_key)}"
                )
                validation_status = "quarantined"

        if metadata.get("sessionStatus") != "closed" and validation_status == "ok":
            validation_errors.append("Session is not closed; marked incomplete")
            validation_status = "incomplete"

    integrity_results = []
    for relative_path in REQUIRED_ARCHIVE_FILES:
        file_path = extract_dir / relative_path
        if not file_path.exists():
            continue
        record_size = FIXED_RECORD_SIZES.get(relative_path)
        file_size = file_path.stat().st_size
        integrity_ok = True
        if record_size:
            integrity_ok = file_size % record_size == 0
            if not integrity_ok and validation_status == "ok":
                validation_status = "incomplete"
                validation_errors.append(
                    f"{relative_path} size {file_size} is not divisible by {record_size}"
                )
        integrity_results.append(
            {
                "relative_path": relative_path,
                "file_size_bytes": file_size,
                "integrity_ok": integrity_ok,
            }
        )

    return {
        "metadata": metadata,
        "missing_files": missing_files,
        "validation_status": validation_status,
        "validation_errors": validation_errors,
        "integrity_results": integrity_results,
    }


def parse_created_utc(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def iter_fixed_records(file_path: Path, record_size: int):
    if not file_path.exists():
        return
    data = file_path.read_bytes()
    usable_size = len(data) - (len(data) % record_size)
    for index, offset in enumerate(range(0, usable_size, record_size)):
        yield index, data[offset:offset + record_size]


def parse_rms_records(file_path: Path):
    records = []
    for record_index, raw in iter_fixed_records(file_path, FIXED_RECORD_SIZES["rms/rms_25cm.bin"]) or []:
        values = struct.unpack_from("<QiddBBfffffffff", raw, 0)
        rms_g = values[6:15]
        rms_mg = [int(round(value * 1000)) for value in rms_g]
        records.append(
            {
                "record_index": record_index,
                "master_count": values[0],
                "position_mm": values[1],
                "latitude": values[2],
                "longitude": values[3],
                "gps_valid": bool(values[4]),
                "valid_mask": values[5],
                "al_x_mg": rms_mg[0],
                "al_y_mg": rms_mg[1],
                "al_z_mg": rms_mg[2],
                "ar_x_mg": rms_mg[3],
                "ar_y_mg": rms_mg[4],
                "ar_z_mg": rms_mg[5],
                "bg_x_mg": rms_mg[6],
                "bg_y_mg": rms_mg[7],
                "bg_z_mg": rms_mg[8],
            }
        )
    return records


def parse_peak_axis(raw: bytes, base: int):
    peak_value_g, peak_position_mm, peak_master_count, peak_lat, peak_lon = struct.unpack_from(
        "<fiQdd", raw, base
    )
    peak_value_mg = int(round(peak_value_g * 1000))
    return {
        "peak_value_g": peak_value_g,
        "peak_value_mg": peak_value_mg,
        "peak_position_mm": peak_position_mm,
        "peak_master_count": peak_master_count,
        "peak_lat": peak_lat,
        "peak_lon": peak_lon,
    }


def parse_peak_records(file_path: Path):
    axis_offsets = {
        "al_x": 14,
        "al_y": 46,
        "al_z": 78,
        "ar_x": 110,
        "ar_y": 142,
        "ar_z": 174,
        "bg_x": 206,
        "bg_y": 238,
        "bg_z": 270,
    }
    records = []
    for record_index, raw in iter_fixed_records(file_path, FIXED_RECORD_SIZES["peak/peak_50m.bin"]) or []:
        window_start_mm, window_end_mm, speed_kmph, valid_mask, alert_generated = struct.unpack_from(
            "<iifBB", raw, 0
        )
        axis_data = {
            axis: parse_peak_axis(raw, offset)
            for axis, offset in axis_offsets.items()
        }
        records.append(
            {
                "record_index": record_index,
                "window_start_mm": window_start_mm,
                "window_end_mm": window_end_mm,
                "speed_kmph": speed_kmph,
                "valid_mask": valid_mask,
                "alert_generated": bool(alert_generated),
                "axis_data": axis_data,
            }
        )
    return records


def axis_alert_group(axis_name: str):
    return AXIS_ALERT_GROUPS.get(axis_name)


def axis_threshold_mg(axis_name: str, route_thresholds: Optional[dict] = None):
    alert_group = axis_alert_group(axis_name)
    if route_thresholds and alert_group == "VERTICAL":
        return int(round(route_thresholds["vertical_threshold"] * 1000))
    if route_thresholds and alert_group == "LATERAL":
        return int(round(route_thresholds["lateral_threshold"] * 1000))
    return PEAK_AXIS_THRESHOLDS_MG.get(axis_name)


def axis_threshold_g(axis_name: str, route_thresholds: Optional[dict] = None):
    alert_group = axis_alert_group(axis_name)
    if route_thresholds and alert_group == "VERTICAL":
        return float(route_thresholds["vertical_threshold"])
    if route_thresholds and alert_group == "LATERAL":
        return float(route_thresholds["lateral_threshold"])
    return PEAK_AXIS_THRESHOLDS_G.get(axis_name)


def pick_highest_vertical_and_lateral_axes(triggered_axes: list[dict]):
    highest_by_group = {}
    for axis in triggered_axes:
        alert_group = axis.get("alertType") or axis_alert_group(axis.get("axisName", ""))
        if alert_group not in {"VERTICAL", "LATERAL"}:
            continue
        axis["alertType"] = alert_group
        current = highest_by_group.get(alert_group)
        if current is None or abs(axis.get("peakValueMg") or 0) > abs(current.get("peakValueMg") or 0):
            highest_by_group[alert_group] = axis
    return [
        highest_by_group[group]
        for group in ("VERTICAL", "LATERAL")
        if group in highest_by_group
    ]


def get_latest_route_thresholds(conn, route_name: str = "DEFAULT"):
    row = conn.execute(
        text("""
            SELECT route_name, vertical_threshold, lateral_threshold
            FROM thresholds
            WHERE route_name = :route_name
            ORDER BY id DESC
            LIMIT 1
        """),
        {"route_name": route_name or "DEFAULT"},
    ).fetchone()
    if not row and route_name != "DEFAULT":
        row = conn.execute(
            text("""
                SELECT route_name, vertical_threshold, lateral_threshold
                FROM thresholds
                WHERE route_name = 'DEFAULT'
                ORDER BY id DESC
                LIMIT 1
            """)
        ).fetchone()
    if not row:
        return None
    return {
        "route_name": row.route_name,
        "vertical_threshold": float(row.vertical_threshold),
        "lateral_threshold": float(row.lateral_threshold),
    }


def build_alert_event_from_peak_record(metadata: dict, peak_record: dict, route_thresholds: Optional[dict] = None):
    if not peak_record.get("alert_generated"):
        return None
    if peak_record.get("speed_kmph", 0) < ALERT_SPEED_LIMIT_KMPH:
        return None

    triggered_axes = []
    for axis_name, axis in peak_record.get("axis_data", {}).items():
        threshold_g = axis_threshold_g(axis_name, route_thresholds)
        peak_value_g = axis.get("peak_value_g")
        if threshold_g is None or peak_value_g is None:
            continue
        if peak_value_g > threshold_g:
            triggered_axes.append(
                {
                    "axisName": axis_name,
                    "alertType": axis_alert_group(axis_name),
                    "peakValueG": peak_value_g,
                    "thresholdG": threshold_g,
                    "peakValueMg": int(round(peak_value_g * 1000)),
                    "thresholdMg": int(round(threshold_g * 1000)),
                    "peakPositionMm": axis.get("peak_position_mm"),
                    "peakLat": axis.get("peak_lat"),
                    "peakLon": axis.get("peak_lon"),
                }
            )

    triggered_axes = pick_highest_vertical_and_lateral_axes(triggered_axes)

    if not triggered_axes:
        return None

    return {
        "gatewayId": metadata["gatewayId"],
        "trainId": metadata["trainId"],
        "sessionName": metadata["sessionName"],
        "routeName": metadata.get("routeName") or (route_thresholds or {}).get("route_name") or "DEFAULT",
        "windowStartMm": peak_record["window_start_mm"],
        "windowEndMm": peak_record["window_end_mm"],
        "speedKmph": peak_record["speed_kmph"],
        "triggeredAxes": triggered_axes,
    }


def map_alert_event_row(row):
    try:
        payload = json.loads(row.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}

    axes = payload.get("triggeredAxes") or []
    first_axis = axes[0] if axes else {}
    latitude = first_axis.get("peakLat")
    longitude = first_axis.get("peakLon")

    return {
        "alert_event_id": row.alert_event_id,
        "gateway_id": row.gateway_id,
        "train_id": row.train_id,
        "session_name": row.session_name,
        "window_start_mm": row.window_start_mm,
        "window_end_mm": row.window_end_mm,
        "speed_kmph": row.speed_kmph,
        "triggered_axes_count": row.triggered_axes_count,
        "triggered_axes": axes,
        "latitude": latitude,
        "longitude": longitude,
        "received_utc": str(row.received_utc) if row.received_utc else None,
        "payload": payload,
    }


def parse_fault_records(file_path: Path):
    records = []
    for record_index, raw in iter_fixed_records(file_path, 75) or []:
        timestamp_ms = struct.unpack_from("<Q", raw, 0)[0]
        fault_code = raw[8]
        node_id = raw[9]
        severity = raw[10]
        description = raw[11:75].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        records.append(
            {
                "record_index": record_index,
                "timestamp_ms": timestamp_ms,
                "fault_code": fault_code,
                "node_id": node_id,
                "severity": severity,
                "description": description,
            }
        )
    return records


def parse_raw_packet_records(file_path: Path):
    records = []
    if not file_path.exists():
        return records
    data = file_path.read_bytes()
    offset = 0
    record_index = 0
    truncated = False
    while offset < len(data):
        if len(data) - offset < 4:
            truncated = True
            break
        packet_length = struct.unpack_from("<I", data, offset)[0]
        frame_start = offset + 4
        frame_end = frame_start + packet_length
        if frame_end > len(data):
            truncated = True
            break
        frame = data[frame_start:frame_end]
        records.append(
            {
                "record_index": record_index,
                "packet_length": packet_length,
                "sof": frame[0] if len(frame) > 0 else None,
                "packet_type": frame[1] if len(frame) > 1 else None,
                "node_id": frame[2] if len(frame) > 2 else None,
                "sequence_number": frame[3] if len(frame) > 3 else None,
                "eof": frame[-1] if frame else None,
                "truncated": False,
            }
        )
        offset = frame_end
        record_index += 1

    if truncated:
        records.append(
            {
                "record_index": record_index,
                "packet_length": None,
                "sof": None,
                "packet_type": None,
                "node_id": None,
                "sequence_number": None,
                "eof": None,
                "truncated": True,
            }
        )
    return records


def get_csv_rows(report_name: str, limit: int = 100):
    report = CSV_REPORTS.get(report_name)
    if not report:
        raise HTTPException(status_code=404, detail="CSV report not found")

    safe_limit = max(1, min(limit, 5000))
    with engine.connect() as conn:
        result = conn.execute(text(report["query"]), {"limit": safe_limit})
        return [dict(row._mapping) for row in result.fetchall()]


def csv_fieldnames(report: dict, rows: list):
    if rows:
        return list(rows[0].keys())

    query_words = report["query"].split("FROM", 1)[0].replace("SELECT", "")
    return [
        item.strip().split()[-1]
        for item in query_words.split(",")
        if item.strip()
    ]


def build_delimited_text(report_name: str, limit: int = 100, delimiter: str = ","):
    report = CSV_REPORTS.get(report_name)
    rows = get_csv_rows(report_name, limit)
    output = io.StringIO()

    fieldnames = csv_fieldnames(report, rows)
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
        delimiter=delimiter,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def build_csv_text(report_name: str, limit: int = 100):
    return build_delimited_text(report_name, limit, delimiter=",")


def build_csv_response(report_name: str, limit: int = 100):
    report = CSV_REPORTS.get(report_name)

    return Response(
        content=build_csv_text(report_name, limit),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{report["filename"]}"'
        },
    )


def mdb_column_type(value):
    if isinstance(value, bool):
        return "YESNO"
    if isinstance(value, int):
        return "LONG"
    if isinstance(value, float):
        return "DOUBLE"
    if isinstance(value, datetime):
        return "DATETIME"
    return "TEXT(255)"


def mdb_sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return f"#{value:%Y-%m-%d %H:%M:%S}#"
    return "'" + str(value).replace("'", "''")[:255] + "'"


def create_mdb_with_windows_ado(rows_by_table: dict, output_path: Path):
    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Microsoft Access MDB generation requires Windows with pywin32 and Microsoft Jet/ACE/ADOX installed."
        ) from exc

    if os.name != "nt":
        raise RuntimeError("Microsoft Access MDB generation is only available on Windows/Access environments.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    connection_string = (
        f"Provider=Microsoft.Jet.OLEDB.4.0;Data Source={output_path};"
    )

    catalog = win32com.client.Dispatch("ADOX.Catalog")
    catalog.Create(connection_string)

    connection = win32com.client.Dispatch("ADODB.Connection")
    connection.Open(connection_string)
    try:
        for table_name, rows in rows_by_table.items():
            if rows:
                columns = list(rows[0].keys())
                sample = rows[0]
            else:
                source_report = "rms-records" if table_name == "SpatialAccelerationData" else "peak-records"
                columns = csv_fieldnames(CSV_REPORTS[source_report], [])
                sample = {}

            column_defs = []
            for column in columns:
                column_defs.append(f"[{column}] {mdb_column_type(sample.get(column))}")
            connection.Execute(f"CREATE TABLE [{table_name}] ({', '.join(column_defs)})")

            for row in rows:
                values = ", ".join(mdb_sql_value(row.get(column)) for column in columns)
                quoted_columns = ", ".join(f"[{column}]" for column in columns)
                connection.Execute(f"INSERT INTO [{table_name}] ({quoted_columns}) VALUES ({values})")
    finally:
        connection.Close()


@app.get("/docs", include_in_schema=False)
def custom_docs():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>UABAMS Cloud - API Docs</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
    <style>
        body {
            margin: 0;
            background: #f4f6f8;
            font-family: Arial, Helvetica, sans-serif;
        }

        .docs-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            background: #fff;
            border-bottom: 1px solid #d7dee4;
            padding: 14px 28px;
        }

        .docs-title {
            color: #17202a;
            font-size: 22px;
            font-weight: 700;
        }

        .back-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 40px;
            border-radius: 6px;
            background: #16636b;
            color: #fff;
            font-weight: 700;
            text-decoration: none;
            padding: 0 16px;
        }

        #swagger-ui {
            max-width: 1500px;
            margin: 0 auto;
        }
    </style>
</head>
<body>
    <div class="docs-bar">
        <div class="docs-title">UABAMS Cloud API Docs</div>
        <a class="back-btn" href="/dashboard">Back to Dashboard</a>
    </div>

    <div id="swagger-ui"></div>

    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
        SwaggerUIBundle({
            url: "/openapi.json",
            dom_id: "#swagger-ui",
            deepLinking: true,
            presets: [
                SwaggerUIBundle.presets.apis
            ],
            layout: "BaseLayout"
        });
    </script>
</body>
</html>
    """)


@app.get("/", include_in_schema=False)
def public_home():
    return RedirectResponse(url="/cloud-dashboard")


@app.get("/health")
def health():
    return {"status": "ok", "service": "UABAMS Cloud"}

# =====================================
# Pydantic Models
# =====================================

class Threshold(BaseModel):
    route_name: str = "DEFAULT"
    vertical_threshold: float = Field(ge=0, le=100)
    lateral_threshold: float = Field(ge=0, le=100)


class SensorCalibration(BaseModel):
    sensor_name: str
    sensor_offset: float
    scale_factor: float


class WheelCalibration(BaseModel):
    train_no: str
    axle_no: str = "AXLE-1"
    wheel_position: str = "LEFT"
    wheel_diameter_mm: Optional[float] = Field(default=None, gt=0)
    new_wheel_diameter_mm: float = Field(default=920, gt=0)
    current_wheel_diameter_mm: Optional[float] = Field(default=None, gt=0)
    encoder_pulses_per_rev: int = Field(default=1024, gt=0)


class GatewayData(BaseModel):
    record_index: Optional[int] = Field(default=None, ge=0)
    train_no: str
    route_name: str = "DEFAULT"
    km_marker: Optional[int] = Field(default=None, ge=0)
    meter: Optional[float] = Field(default=None, ge=0, le=999.75)
    vertical_g: float = Field(ge=-100, le=100)
    lateral_g: float = Field(ge=-100, le=100)
    speed_kmph: float = Field(ge=0)
    latitude: float
    longitude: float
    status_code: Optional[int] = Field(default=None, ge=0)
    sample_distance_m: float = Field(default=0.25, gt=0)


class TriggeredAxis(BaseModel):
    axisName: str
    alertType: Optional[str] = None
    peakValueMg: int
    thresholdMg: int
    peakPositionMm: int
    peakLat: float
    peakLon: float


class CloudAlertEvent(BaseModel):
    gatewayId: str
    trainId: str
    sessionName: str
    routeName: str = "DEFAULT"
    windowStartMm: int
    windowEndMm: int
    speedKmph: float
    triggeredAxes: list[TriggeredAxis]


class RouteReferencePoint(BaseModel):
    routeName: str
    kmMarker: int = Field(ge=0)
    latitude: float
    longitude: float
    trackFeature: Optional[str] = None
    description: Optional[str] = None


class SectionReference(BaseModel):
    railway: str
    division: str
    sectionName: str
    routeName: str
    fromKm: float = Field(ge=0)
    toKm: float = Field(ge=0)


class DeviceHealthStatus(BaseModel):
    gatewayId: str
    trainId: str
    firmwareVersion: Optional[str] = None
    softwareVersion: Optional[str] = None
    gsmSignalPercent: Optional[float] = Field(default=None, ge=0, le=100)
    gpsFix: Optional[bool] = None
    storageFreeMb: Optional[float] = Field(default=None, ge=0)
    status: str = "online"


class PowerStatus(BaseModel):
    gatewayId: str
    trainId: str
    batteryPercent: float = Field(ge=0, le=100)
    inputVoltage: Optional[float] = Field(default=None, ge=0)
    charging: Optional[bool] = None
    backupAvailableHours: Optional[float] = Field(default=None, ge=0)
    status: str = "normal"

def init_db():
    with engine.connect() as conn:
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS thresholds (
                    id SERIAL PRIMARY KEY,
                    route_name VARCHAR(100) DEFAULT 'DEFAULT',
                    vertical_threshold DOUBLE PRECISION NOT NULL,
                    lateral_threshold DOUBLE PRECISION NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )
        conn.execute(
            text("ALTER TABLE thresholds ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        )
        conn.execute(
            text("ALTER TABLE thresholds ADD COLUMN IF NOT EXISTS route_name VARCHAR(100) DEFAULT 'DEFAULT'")
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS sensor_calibration (
                    id SERIAL PRIMARY KEY,
                    sensor_name VARCHAR(100) NOT NULL,
                    sensor_offset DOUBLE PRECISION NOT NULL,
                    scale_factor DOUBLE PRECISION NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS wheel_calibration (
                    id SERIAL PRIMARY KEY,
                    train_no VARCHAR(50) NOT NULL,
                    wheel_diameter_mm DOUBLE PRECISION,
                    axle_no VARCHAR(50) DEFAULT 'AXLE-1',
                    wheel_position VARCHAR(50) DEFAULT 'LEFT',
                    new_wheel_diameter_mm DOUBLE PRECISION DEFAULT 920,
                    current_wheel_diameter_mm DOUBLE PRECISION,
                    encoder_pulses_per_rev INTEGER DEFAULT 1024,
                    circumference_mm DOUBLE PRECISION,
                    distance_per_pulse_mm DOUBLE PRECISION,
                    wheel_wear_mm DOUBLE PRECISION,
                    correction_factor DOUBLE PRECISION,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )

        for column_name, column_type in [
            ("axle_no", "VARCHAR(50) DEFAULT 'AXLE-1'"),
            ("wheel_position", "VARCHAR(50) DEFAULT 'LEFT'"),
            ("new_wheel_diameter_mm", "DOUBLE PRECISION DEFAULT 920"),
            ("current_wheel_diameter_mm", "DOUBLE PRECISION"),
            ("encoder_pulses_per_rev", "INTEGER DEFAULT 1024"),
            ("circumference_mm", "DOUBLE PRECISION"),
            ("distance_per_pulse_mm", "DOUBLE PRECISION"),
            ("wheel_wear_mm", "DOUBLE PRECISION"),
            ("correction_factor", "DOUBLE PRECISION"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            conn.execute(
                text(f"ALTER TABLE wheel_calibration ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
            )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS acceleration_data (
                    id SERIAL PRIMARY KEY,
                    record_index INTEGER,
                    train_no VARCHAR(50) NOT NULL,
                    route_name VARCHAR(100) DEFAULT 'DEFAULT',
                    km_marker INTEGER,
                    meter DOUBLE PRECISION,
                    vertical_g DOUBLE PRECISION NOT NULL,
                    lateral_g DOUBLE PRECISION NOT NULL,
                    speed_kmph DOUBLE PRECISION NOT NULL,
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    corrected_speed_kmph DOUBLE PRECISION,
                    wheel_correction_factor DOUBLE PRECISION,
                    status_code INTEGER,
                    sample_distance_m DOUBLE PRECISION DEFAULT 0.25,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )

        for column_name, column_type in [
            ("record_index", "INTEGER"),
            ("route_name", "VARCHAR(100) DEFAULT 'DEFAULT'"),
            ("km_marker", "INTEGER"),
            ("meter", "DOUBLE PRECISION"),
            ("speed_kmph", "DOUBLE PRECISION"),
            ("corrected_speed_kmph", "DOUBLE PRECISION"),
            ("wheel_correction_factor", "DOUBLE PRECISION"),
            ("status_code", "INTEGER"),
            ("sample_distance_m", "DOUBLE PRECISION DEFAULT 0.25"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            conn.execute(
                text(f"ALTER TABLE acceleration_data ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
            )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    route_name VARCHAR(100) DEFAULT 'DEFAULT',
                    record_index INTEGER,
                    train_no VARCHAR(50) NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    measured_value DOUBLE PRECISION NOT NULL,
                    threshold_value DOUBLE PRECISION NOT NULL,
                    km_marker INTEGER,
                    meter DOUBLE PRECISION,
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    speed_kmph DOUBLE PRECISION,
                    status_code INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )

        for column_name, column_type in [
            ("route_name", "VARCHAR(100) DEFAULT 'DEFAULT'"),
            ("record_index", "INTEGER"),
            ("measured_value", "DOUBLE PRECISION"),
            ("threshold_value", "DOUBLE PRECISION"),
            ("km_marker", "INTEGER"),
            ("meter", "DOUBLE PRECISION"),
            ("speed_kmph", "DOUBLE PRECISION"),
            ("status_code", "INTEGER"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            conn.execute(
                text(f"ALTER TABLE alerts ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
            )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS gateways (
                    gateway_id TEXT PRIMARY KEY,
                    gateway_serial TEXT,
                    firmware_version TEXT,
                    gateway_software TEXT,
                    first_seen_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )
        for column_name, column_type in [
            ("gateway_id", "TEXT"),
            ("gateway_serial", "TEXT"),
            ("firmware_version", "TEXT"),
            ("gateway_software", "TEXT"),
            ("first_seen_utc", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            conn.execute(
                text(f"ALTER TABLE gateways ADD COLUMN IF NOT EXISTS {column_name} {column_type}")
            )
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS idx_gateways_gateway_id ON gateways (gateway_id)")
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS trains (
                    train_id TEXT PRIMARY KEY
                )
            """)
        )
        conn.execute(text("ALTER TABLE trains ADD COLUMN IF NOT EXISTS train_id TEXT"))
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS idx_trains_train_id ON trains (train_id)")
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS archives (
                    archive_id SERIAL PRIMARY KEY,
                    gateway_id TEXT NOT NULL,
                    train_id TEXT NOT NULL,
                    session_name TEXT NOT NULL,
                    archive_name TEXT NOT NULL,
                    archive_size_bytes BIGINT NOT NULL,
                    upload_received_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    storage_uri TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    validation_errors TEXT,
                    archive_bytes BYTEA,
                    UNIQUE(gateway_id, session_name)
                )
            """)
        )
        conn.execute(text("ALTER TABLE archives ADD COLUMN IF NOT EXISTS archive_bytes BYTEA"))

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id SERIAL PRIMARY KEY,
                    archive_id INTEGER REFERENCES archives(archive_id),
                    gateway_id TEXT NOT NULL,
                    train_id TEXT NOT NULL,
                    session_name TEXT NOT NULL,
                    session_status TEXT,
                    created_utc TIMESTAMP,
                    schema_version TEXT,
                    gateway_serial TEXT,
                    firmware_version TEXT,
                    gateway_software TEXT,
                    UNIQUE(gateway_id, session_name)
                )
            """)
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS extracted_files (
                    file_id SERIAL PRIMARY KEY,
                    archive_id INTEGER REFERENCES archives(archive_id),
                    session_id INTEGER REFERENCES sessions(session_id),
                    file_relative_path TEXT NOT NULL,
                    extracted_at_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_size_bytes BIGINT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    integrity_ok BOOLEAN NOT NULL,
                    file_bytes BYTEA
                )
            """)
        )
        conn.execute(text("ALTER TABLE extracted_files ADD COLUMN IF NOT EXISTS file_bytes BYTEA"))

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS upload_attempts (
                    attempt_id SERIAL PRIMARY KEY,
                    archive_id INTEGER REFERENCES archives(archive_id),
                    attempted_at_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    http_response_code INTEGER,
                    success BOOLEAN
                )
            """)
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS rms_records (
                    rms_id SERIAL PRIMARY KEY,
                    session_id INTEGER REFERENCES sessions(session_id),
                    record_index INTEGER NOT NULL,
                    master_count BIGINT,
                    position_mm INTEGER,
                    latitude DOUBLE PRECISION,
                    longitude DOUBLE PRECISION,
                    gps_valid BOOLEAN,
                    valid_mask SMALLINT,
                    al_x_mg BIGINT,
                    al_y_mg BIGINT,
                    al_z_mg BIGINT,
                    ar_x_mg BIGINT,
                    ar_y_mg BIGINT,
                    ar_z_mg BIGINT,
                    bg_x_mg BIGINT,
                    bg_y_mg BIGINT,
                    bg_z_mg BIGINT,
                    UNIQUE(session_id, record_index)
                )
            """)
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS peak_records (
                    peak_id SERIAL PRIMARY KEY,
                    session_id INTEGER REFERENCES sessions(session_id),
                    record_index INTEGER NOT NULL,
                    window_start_mm INTEGER,
                    window_end_mm INTEGER,
                    speed_kmph DOUBLE PRECISION,
                    valid_mask SMALLINT,
                    alert_generated BOOLEAN,
                    axis_data_json TEXT,
                    UNIQUE(session_id, record_index)
                )
            """)
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS fault_records (
                    fault_id SERIAL PRIMARY KEY,
                    session_id INTEGER REFERENCES sessions(session_id),
                    record_index INTEGER NOT NULL,
                    timestamp_ms BIGINT,
                    fault_code SMALLINT,
                    node_id SMALLINT,
                    severity SMALLINT,
                    description TEXT,
                    UNIQUE(session_id, record_index)
                )
            """)
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS raw_packet_records (
                    raw_packet_id SERIAL PRIMARY KEY,
                    session_id INTEGER REFERENCES sessions(session_id),
                    file_relative_path TEXT NOT NULL,
                    record_index INTEGER NOT NULL,
                    packet_length INTEGER,
                    sof SMALLINT,
                    packet_type SMALLINT,
                    node_id SMALLINT,
                    sequence_number SMALLINT,
                    eof SMALLINT,
                    truncated BOOLEAN,
                    UNIQUE(session_id, file_relative_path, record_index)
                )
            """)
        )

        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS cloud_alert_events (
                    alert_event_id SERIAL PRIMARY KEY,
                    gateway_id TEXT NOT NULL,
                    train_id TEXT NOT NULL,
                    session_name TEXT NOT NULL,
                    window_start_mm INTEGER NOT NULL,
                    window_end_mm INTEGER NOT NULL,
                    speed_kmph DOUBLE PRECISION NOT NULL,
                    triggered_axes_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )

        conn.commit()


@app.on_event("startup")
def startup():
    try:
        init_db()
    except SQLAlchemyError as exc:
        print(f"Database startup check failed: {exc}")


# =====================================
# Home API
# =====================================

@app.get("/")
def home():
    return {"message": "UABAMS Cloud Running"}


@app.get("/cloud/status")
def cloud_status():
    required_tables = [
        "wheel_calibration",
        "thresholds",
        "acceleration_data",
        "alerts",
    ]

    try:
        init_db()
        with engine.connect() as conn:
            database_time = conn.execute(text("SELECT NOW()")).scalar()
            table_rows = conn.execute(
                text("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(:tables)
                    ORDER BY table_name
                """),
                {"tables": required_tables},
            ).fetchall()
            available_tables = [row.table_name for row in table_rows]
    except SQLAlchemyError as exc:
        return {
            "api_status": "running",
            "database_status": "disconnected",
            "cloud_database": "PostgreSQL",
            "database_host": database_host(),
            "database_error": str(exc.orig) if getattr(exc, "orig", None) else str(exc),
            "required_tables": required_tables,
            "available_tables": [],
            "schema_ready": False,
            "gateway_archive_endpoint": "/api/v1/archive",
            "alert_endpoint": "/api/v1/alert",
            "measurement_speed_band_kmph": f"{MIN_MEASUREMENT_SPEED_KMPH}-{MAX_MEASUREMENT_SPEED_KMPH}",
            "spatial_sample_interval_m": SPATIAL_SAMPLE_DISTANCE_M,
            "peak_window_distance_m": PEAK_WINDOW_DISTANCE_M,
            "alert_speed_gate_kmph": ALERT_SPEED_LIMIT_KMPH,
            "axle_acceleration_range_g": f"+/-{AXLE_ACCELERATION_RANGE_G}",
            "bogie_acceleration_range_g": f"+/-{BOGIE_ACCELERATION_RANGE_G}",
            "axle_min_sampling_hz": AXLE_MIN_SAMPLING_HZ,
            "bogie_min_sampling_hz": BOGIE_MIN_SAMPLING_HZ,
            "peak_location_accuracy_m": PEAK_LOCATION_ACCURACY_M,
            "speed_accuracy_percent": SPEED_ACCURACY_PERCENT,
            "raw_retention_days": RAW_TIME_DOMAIN_RETENTION_DAYS,
            "spatial_alert_retention_days": SPATIAL_ALERT_RETENTION_DAYS,
            "max_supported_train_systems": MAX_SUPPORTED_TRAIN_SYSTEMS,
        }

    return {
        "api_status": "running",
        "database_status": "connected",
        "cloud_database": "PostgreSQL",
        "database_host": database_host(),
        "database_time": str(database_time),
        "required_tables": required_tables,
        "available_tables": available_tables,
        "schema_ready": set(required_tables).issubset(set(available_tables)),
        "gateway_archive_endpoint": "/api/v1/archive",
        "alert_endpoint": "/api/v1/alert",
        "measurement_speed_band_kmph": f"{MIN_MEASUREMENT_SPEED_KMPH}-{MAX_MEASUREMENT_SPEED_KMPH}",
        "spatial_sample_interval_m": SPATIAL_SAMPLE_DISTANCE_M,
        "peak_window_distance_m": PEAK_WINDOW_DISTANCE_M,
        "alert_speed_gate_kmph": ALERT_SPEED_LIMIT_KMPH,
        "axle_acceleration_range_g": f"+/-{AXLE_ACCELERATION_RANGE_G}",
        "bogie_acceleration_range_g": f"+/-{BOGIE_ACCELERATION_RANGE_G}",
        "axle_min_sampling_hz": AXLE_MIN_SAMPLING_HZ,
        "bogie_min_sampling_hz": BOGIE_MIN_SAMPLING_HZ,
        "peak_location_accuracy_m": PEAK_LOCATION_ACCURACY_M,
        "speed_accuracy_percent": SPEED_ACCURACY_PERCENT,
        "raw_retention_days": RAW_TIME_DOMAIN_RETENTION_DAYS,
        "spatial_alert_retention_days": SPATIAL_ALERT_RETENTION_DAYS,
        "max_supported_train_systems": MAX_SUPPORTED_TRAIN_SYSTEMS,
    }


@app.put("/api/v1/archive")
async def upload_session_archive(request: Request, filename: Optional[str] = None):
    init_db()

    archive_name = extract_archive_filename(request, filename)
    if not archive_name:
        raise HTTPException(
            status_code=422,
            detail="Archive filename is required. Use ?filename=..., X-Archive-Name, or Content-Disposition filename.",
        )

    filename_parts = parse_archive_filename(archive_name)
    archive_bytes = await request.body()
    if not archive_bytes:
        raise HTTPException(status_code=400, detail="Archive body is empty")

    checksum = hashlib.sha256(archive_bytes).hexdigest()
    archive_size = len(archive_bytes)
    storage_root = ARCHIVE_STORAGE_DIR / checksum
    extract_dir = storage_root / "extracted"
    archive_path = storage_root / archive_name

    storage_root.mkdir(parents=True, exist_ok=True)
    archive_path.write_bytes(archive_bytes)

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zip_file:
            extract_dir.mkdir(parents=True, exist_ok=True)
            safe_extract_zip(zip_file, extract_dir)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Uploaded body is not a valid ZIP archive") from exc

    validation = validate_archive_contents(extract_dir, filename_parts)
    metadata = validation["metadata"] or {}
    upload_time = utc_now()
    created_utc = parse_created_utc(metadata.get("createdUtc"))

    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO gateways
                (
                    gateway_id,
                    gateway_serial,
                    firmware_version,
                    gateway_software,
                    first_seen_utc
                )
                VALUES
                (
                    :gateway_id,
                    :gateway_serial,
                    :firmware_version,
                    :gateway_software,
                    :first_seen_utc
                )
                ON CONFLICT (gateway_id) DO UPDATE SET
                    gateway_serial = EXCLUDED.gateway_serial,
                    firmware_version = EXCLUDED.firmware_version,
                    gateway_software = EXCLUDED.gateway_software
            """),
            {
                "gateway_id": filename_parts["gateway_id"],
                "gateway_serial": metadata.get("gatewaySerial"),
                "firmware_version": metadata.get("firmwareVersion"),
                "gateway_software": metadata.get("gatewaySoftware"),
                "first_seen_utc": upload_time,
            },
        )

        conn.execute(
            text("""
                INSERT INTO trains (train_id)
                VALUES (:train_id)
                ON CONFLICT (train_id) DO NOTHING
            """),
            {"train_id": filename_parts["train_id"]},
        )

        archive_row = conn.execute(
            text("""
                INSERT INTO archives
                (
                    gateway_id,
                    train_id,
                    session_name,
                    archive_name,
                    archive_size_bytes,
                    upload_received_utc,
                    storage_uri,
                    checksum,
                    validation_status,
                    validation_errors,
                    archive_bytes
                )
                VALUES
                (
                    :gateway_id,
                    :train_id,
                    :session_name,
                    :archive_name,
                    :archive_size_bytes,
                    :upload_received_utc,
                    :storage_uri,
                    :checksum,
                    :validation_status,
                    :validation_errors,
                    :archive_bytes
                )
                ON CONFLICT (gateway_id, session_name) DO NOTHING
                RETURNING archive_id
            """),
            {
                "gateway_id": filename_parts["gateway_id"],
                "train_id": filename_parts["train_id"],
                "session_name": filename_parts["session_name"],
                "archive_name": archive_name,
                "archive_size_bytes": archive_size,
                "upload_received_utc": upload_time,
                "storage_uri": str(archive_path),
                "checksum": checksum,
                "validation_status": validation["validation_status"],
                "validation_errors": "; ".join(validation["validation_errors"]) or None,
                "archive_bytes": archive_bytes,
            },
        ).fetchone()

        if not archive_row:
            existing = conn.execute(
                text("""
                    SELECT archive_id, validation_status, validation_errors
                    FROM archives
                    WHERE gateway_id = :gateway_id
                      AND session_name = :session_name
                """),
                {
                    "gateway_id": filename_parts["gateway_id"],
                    "session_name": filename_parts["session_name"],
                },
            ).fetchone()

            existing_status = existing.validation_status if existing else "duplicate"
            if existing_status == "quarantined":
                conn.execute(
                    text("""
                        INSERT INTO upload_attempts
                        (
                            archive_id,
                            http_response_code,
                            success
                        )
                        VALUES
                        (
                            :archive_id,
                            422,
                            FALSE
                        )
                    """),
                    {"archive_id": existing.archive_id if existing else None},
                )
                conn.commit()
                return JSONResponse(
                    status_code=422,
                    content={
                        "status": "error",
                        "message": "Archive was previously quarantined and must not be acknowledged as successful",
                        "errorCode": "ARCHIVE_QUARANTINED",
                        "archiveId": existing.archive_id if existing else None,
                        "archiveName": archive_name,
                        "archive_name": archive_name,
                        "gatewayId": filename_parts["gateway_id"],
                        "trainId": filename_parts["train_id"],
                        "sessionName": filename_parts["session_name"],
                        "validationStatus": existing_status,
                        "validation_status": existing_status,
                        "validationErrors": existing.validation_errors if existing else None,
                    },
                )

            conn.execute(
                text("""
                    INSERT INTO upload_attempts
                    (
                        archive_id,
                        http_response_code,
                        success
                    )
                    VALUES
                    (
                        :archive_id,
                        200,
                        TRUE
                    )
                """),
                {"archive_id": existing.archive_id if existing else None},
            )
            conn.commit()
            return {
                "status": "success",
                "message": "Duplicate archive already received",
                "archiveId": existing.archive_id if existing else None,
                "archive_name": archive_name,
                "archiveName": archive_name,
                "archive_id": existing.archive_id if existing else None,
                "gatewayId": filename_parts["gateway_id"],
                "trainId": filename_parts["train_id"],
                "sessionName": filename_parts["session_name"],
                "validationStatus": existing_status,
                "validation_status": existing_status,
                "duplicate": True,
            }

        archive_id = archive_row.archive_id
        session_row = conn.execute(
            text("""
                INSERT INTO sessions
                (
                    archive_id,
                    gateway_id,
                    train_id,
                    session_name,
                    session_status,
                    created_utc,
                    schema_version,
                    gateway_serial,
                    firmware_version,
                    gateway_software
                )
                VALUES
                (
                    :archive_id,
                    :gateway_id,
                    :train_id,
                    :session_name,
                    :session_status,
                    :created_utc,
                    :schema_version,
                    :gateway_serial,
                    :firmware_version,
                    :gateway_software
                )
                ON CONFLICT (gateway_id, session_name) DO UPDATE SET
                    archive_id = EXCLUDED.archive_id,
                    session_status = EXCLUDED.session_status,
                    created_utc = EXCLUDED.created_utc,
                    schema_version = EXCLUDED.schema_version,
                    gateway_serial = EXCLUDED.gateway_serial,
                    firmware_version = EXCLUDED.firmware_version,
                    gateway_software = EXCLUDED.gateway_software
                RETURNING session_id
            """),
            {
                "archive_id": archive_id,
                "gateway_id": filename_parts["gateway_id"],
                "train_id": filename_parts["train_id"],
                "session_name": filename_parts["session_name"],
                "session_status": metadata.get("sessionStatus"),
                "created_utc": created_utc,
                "schema_version": metadata.get("schemaVersion"),
                "gateway_serial": metadata.get("gatewaySerial"),
                "firmware_version": metadata.get("firmwareVersion"),
                "gateway_software": metadata.get("gatewaySoftware"),
            },
        ).fetchone()
        session_id = session_row.session_id

        for file_info in validation["integrity_results"]:
            relative_path = file_info["relative_path"]
            conn.execute(
                text("""
                    INSERT INTO extracted_files
                    (
                        archive_id,
                        session_id,
                        file_relative_path,
                    file_size_bytes,
                    storage_uri,
                    integrity_ok,
                    file_bytes
                )
                VALUES
                (
                        :archive_id,
                        :session_id,
                        :file_relative_path,
                    :file_size_bytes,
                    :storage_uri,
                    :integrity_ok,
                    :file_bytes
                )
            """),
                {
                    "archive_id": archive_id,
                    "session_id": session_id,
                    "file_relative_path": relative_path,
                    "file_size_bytes": file_info["file_size_bytes"],
                    "storage_uri": str(extract_dir / relative_path),
                    "integrity_ok": file_info["integrity_ok"],
                    "file_bytes": (extract_dir / relative_path).read_bytes(),
                },
            )

        if validation["validation_status"] != "quarantined":
            route_name = metadata.get("routeName") or metadata.get("route_name") or "DEFAULT"
            route_thresholds = get_latest_route_thresholds(conn, route_name)
            for rms_record in parse_rms_records(extract_dir / "rms/rms_25cm.bin"):
                conn.execute(
                    text("""
                        INSERT INTO rms_records
                        (
                            session_id, record_index, master_count, position_mm,
                            latitude, longitude, gps_valid, valid_mask,
                            al_x_mg, al_y_mg, al_z_mg,
                            ar_x_mg, ar_y_mg, ar_z_mg,
                            bg_x_mg, bg_y_mg, bg_z_mg
                        )
                        VALUES
                        (
                            :session_id, :record_index, :master_count, :position_mm,
                            :latitude, :longitude, :gps_valid, :valid_mask,
                            :al_x_mg, :al_y_mg, :al_z_mg,
                            :ar_x_mg, :ar_y_mg, :ar_z_mg,
                            :bg_x_mg, :bg_y_mg, :bg_z_mg
                        )
                        ON CONFLICT (session_id, record_index) DO NOTHING
                    """),
                    {"session_id": session_id, **rms_record},
                )

            for peak_record in parse_peak_records(extract_dir / "peak/peak_50m.bin"):
                conn.execute(
                    text("""
                        INSERT INTO peak_records
                        (
                            session_id, record_index, window_start_mm, window_end_mm,
                            speed_kmph, valid_mask, alert_generated, axis_data_json
                        )
                        VALUES
                        (
                            :session_id, :record_index, :window_start_mm, :window_end_mm,
                            :speed_kmph, :valid_mask, :alert_generated, :axis_data_json
                        )
                        ON CONFLICT (session_id, record_index) DO NOTHING
                    """),
                    {
                        "session_id": session_id,
                        "record_index": peak_record["record_index"],
                        "window_start_mm": peak_record["window_start_mm"],
                        "window_end_mm": peak_record["window_end_mm"],
                        "speed_kmph": peak_record["speed_kmph"],
                        "valid_mask": peak_record["valid_mask"],
                        "alert_generated": peak_record["alert_generated"],
                        "axis_data_json": json.dumps(peak_record["axis_data"]),
                    },
                )
                alert_payload = build_alert_event_from_peak_record(metadata, peak_record, route_thresholds)
                if alert_payload:
                    conn.execute(
                        text("""
                            INSERT INTO cloud_alert_events
                            (
                                gateway_id,
                                train_id,
                                session_name,
                                window_start_mm,
                                window_end_mm,
                                speed_kmph,
                                triggered_axes_count,
                                payload_json
                            )
                            VALUES
                            (
                                :gateway_id,
                                :train_id,
                                :session_name,
                                :window_start_mm,
                                :window_end_mm,
                                :speed_kmph,
                                :triggered_axes_count,
                                :payload_json
                            )
                        """),
                        {
                            "gateway_id": alert_payload["gatewayId"],
                            "train_id": alert_payload["trainId"],
                            "session_name": alert_payload["sessionName"],
                            "window_start_mm": alert_payload["windowStartMm"],
                            "window_end_mm": alert_payload["windowEndMm"],
                            "speed_kmph": alert_payload["speedKmph"],
                            "triggered_axes_count": len(alert_payload["triggeredAxes"]),
                            "payload_json": json.dumps(alert_payload),
                        },
                    )

            for fault_record in parse_fault_records(extract_dir / "faults/faults.bin"):
                conn.execute(
                    text("""
                        INSERT INTO fault_records
                        (
                            session_id, record_index, timestamp_ms, fault_code,
                            node_id, severity, description
                        )
                        VALUES
                        (
                            :session_id, :record_index, :timestamp_ms, :fault_code,
                            :node_id, :severity, :description
                        )
                        ON CONFLICT (session_id, record_index) DO NOTHING
                    """),
                    {"session_id": session_id, **fault_record},
                )

            for raw_relative_path in [
                "raw/adxl_left.bin",
                "raw/adxl_right.bin",
                "raw/bogie.bin",
                "raw/encoder.bin",
            ]:
                for raw_record in parse_raw_packet_records(extract_dir / raw_relative_path):
                    conn.execute(
                        text("""
                            INSERT INTO raw_packet_records
                            (
                                session_id, file_relative_path, record_index,
                                packet_length, sof, packet_type, node_id,
                                sequence_number, eof, truncated
                            )
                            VALUES
                            (
                                :session_id, :file_relative_path, :record_index,
                                :packet_length, :sof, :packet_type, :node_id,
                                :sequence_number, :eof, :truncated
                            )
                            ON CONFLICT (session_id, file_relative_path, record_index) DO NOTHING
                        """),
                        {
                            "session_id": session_id,
                            "file_relative_path": raw_relative_path,
                            **raw_record,
                        },
                    )

        conn.execute(
            text("""
                INSERT INTO upload_attempts
                (
                    archive_id,
                    http_response_code,
                    success
                )
                VALUES
                (
                    :archive_id,
                    201,
                    TRUE
                )
            """),
            {"archive_id": archive_id},
        )
        conn.commit()

    status_code = 201 if validation["validation_status"] != "quarantined" else 422
    mongo_archive_id = mirror_archive_to_mongo({
        "archiveId": archive_id,
        "sessionId": session_id,
        "archiveName": archive_name,
        "gatewayId": filename_parts["gateway_id"],
        "trainId": filename_parts["train_id"],
        "sessionName": filename_parts["session_name"],
        "archiveSizeBytes": archive_size,
        "checksum": checksum,
        "validationStatus": validation["validation_status"],
        "validationErrors": validation["validation_errors"],
        "storedArchive": str(archive_path),
        "receivedAt": upload_time,
    })
    return JSONResponse(
        status_code=status_code,
        content={
            "mongoArchiveId": mongo_archive_id,
            "status": "success" if status_code == 201 else "error",
            "message": "Archive received",
            "archiveId": archive_id,
            "sessionId": session_id,
            "archive_id": archive_id,
            "session_id": session_id,
            "archiveName": archive_name,
            "archive_name": archive_name,
            "gatewayId": filename_parts["gateway_id"],
            "gateway_id": filename_parts["gateway_id"],
            "trainId": filename_parts["train_id"],
            "train_id": filename_parts["train_id"],
            "sessionName": filename_parts["session_name"],
            "session_name": filename_parts["session_name"],
            "archiveSizeBytes": archive_size,
            "archive_size_bytes": archive_size,
            "checksum": checksum,
            "validationStatus": validation["validation_status"],
            "validation_status": validation["validation_status"],
            "validationErrors": validation["validation_errors"],
            "validation_errors": validation["validation_errors"],
            "missingFiles": validation["missing_files"],
            "missing_files": validation["missing_files"],
            "storedArchive": str(archive_path),
            "stored_archive": str(archive_path),
        },
    )



def latest_mongo_rows(collection_name: str, limit: int = 20):
    if not mongo_enabled():
        return []
    db = get_mongo_db()
    safe_limit = max(1, min(limit, 100))
    return clean_for_mongo(list(db[collection_name].find({}, {"_id": 0}).sort("createdAt", -1).limit(safe_limit)))


@app.post("/api/v1/route-reference")
def save_route_reference(point: RouteReferencePoint, _: bool = Depends(verify_api_key)):
    doc = point.dict()
    doc["createdAt"] = utc_now().isoformat()
    doc["purpose"] = "RDSO route latitude/longitude and track-feature reference point"
    mongo_id = mongo_insert("route_reference", doc)
    return {
        "status": "success" if mongo_id else "mongodb_not_configured",
        "message": "Route reference point stored in MongoDB cloud storage" if mongo_id else "MongoDB is not configured",
        "mongoId": mongo_id,
        "data": doc,
    }


@app.get("/api/v1/route-reference")
def get_route_reference(limit: int = 50, _: bool = Depends(verify_api_key)):
    return {"status": "success", "records": latest_mongo_rows("route_reference", limit)}


@app.post("/api/v1/section-reference")
def save_section_reference(section: SectionReference, _: bool = Depends(verify_api_key)):
    if section.toKm < section.fromKm:
        raise HTTPException(status_code=422, detail="toKm must be greater than or equal to fromKm")
    doc = section.dict()
    doc["createdAt"] = utc_now().isoformat()
    doc["purpose"] = "Railway/Division/Section/KM range for section-wise reporting"
    mongo_id = mongo_insert("section_reference", doc)
    return {
        "status": "success" if mongo_id else "mongodb_not_configured",
        "message": "Section reference stored in MongoDB cloud storage" if mongo_id else "MongoDB is not configured",
        "mongoId": mongo_id,
        "data": doc,
    }


@app.get("/api/v1/section-reference")
def get_section_reference(limit: int = 50, _: bool = Depends(verify_api_key)):
    return {"status": "success", "records": latest_mongo_rows("section_reference", limit)}


@app.post("/api/v1/device-health")
def save_device_health(status: DeviceHealthStatus, _: bool = Depends(verify_api_key)):
    doc = status.dict()
    doc["receivedAt"] = utc_now().isoformat()
    doc["createdAt"] = doc["receivedAt"]
    doc["purpose"] = "Remote gateway/software/GSM/GPS/storage health monitoring"
    mongo_id = mongo_insert("device_health", doc)
    return {
        "status": "success" if mongo_id else "mongodb_not_configured",
        "message": "Device health stored in MongoDB cloud storage" if mongo_id else "MongoDB is not configured",
        "mongoId": mongo_id,
        "data": doc,
    }


@app.get("/api/v1/device-health")
def get_device_health(limit: int = 50, _: bool = Depends(verify_api_key)):
    return {"status": "success", "records": latest_mongo_rows("device_health", limit)}


@app.post("/api/v1/power-status")
def save_power_status(status: PowerStatus, _: bool = Depends(verify_api_key)):
    doc = status.dict()
    doc["receivedAt"] = utc_now().isoformat()
    doc["createdAt"] = doc["receivedAt"]
    doc["purpose"] = "Gateway power supply and backup battery monitoring"
    mongo_id = mongo_insert("power_status", doc)
    return {
        "status": "success" if mongo_id else "mongodb_not_configured",
        "message": "Power status stored in MongoDB cloud storage" if mongo_id else "MongoDB is not configured",
        "mongoId": mongo_id,
        "data": doc,
    }


@app.get("/api/v1/power-status")
def get_power_status(limit: int = 50, _: bool = Depends(verify_api_key)):
    return {"status": "success", "records": latest_mongo_rows("power_status", limit)}


@app.get("/api/v1/retention-status")
def retention_status(_: bool = Depends(verify_api_key)):
    return {
        "status": "configured",
        "rawTimeDomainRetentionDays": RAW_TIME_DOMAIN_RETENTION_DAYS,
        "spatialAlertRetentionDays": SPATIAL_ALERT_RETENTION_DAYS,
        "rawCollections": ["raw_gateway_payloads", "archive_uploads"],
        "spatialAlertCollections": ["gateway_archives", "alert_notifications", "sms_logs", "route_reference", "section_reference", "device_health", "power_status"],
        "cleanupEndpoint": "/api/v1/retention-cleanup",
        "note": "Retention cleanup is API-triggered for demo. Production can call this endpoint from a scheduler/cron job.",
    }


@app.post("/api/v1/retention-cleanup")
def retention_cleanup(dry_run: bool = True, _: bool = Depends(verify_api_key)):
    if not mongo_enabled():
        return {"status": "mongodb_not_configured", "deleted": {}, "dryRun": dry_run}
    db = get_mongo_db()
    now = utc_now()
    policies = {
        "raw_gateway_payloads": RAW_TIME_DOMAIN_RETENTION_DAYS,
        "archive_uploads": RAW_TIME_DOMAIN_RETENTION_DAYS,
        "gateway_archives": SPATIAL_ALERT_RETENTION_DAYS,
        "alert_notifications": SPATIAL_ALERT_RETENTION_DAYS,
        "sms_logs": SPATIAL_ALERT_RETENTION_DAYS,
        "device_health": SPATIAL_ALERT_RETENTION_DAYS,
        "power_status": SPATIAL_ALERT_RETENTION_DAYS,
    }
    results = {}
    for collection_name, retention_days in policies.items():
        cutoff = (now - timedelta(days=retention_days)).isoformat()
        query = {"createdAt": {"$lt": cutoff}}
        count = db[collection_name].count_documents(query)
        if dry_run:
            deleted_count = 0
        else:
            deleted_count = db[collection_name].delete_many(query).deleted_count
        results[collection_name] = {
            "retentionDays": retention_days,
            "cutoffUtc": cutoff,
            "matchingRecords": count,
            "deletedRecords": deleted_count,
        }
    mongo_insert("retention_actions", {"dryRun": dry_run, "results": results, "createdAt": utc_now().isoformat()})
    return {"status": "success", "dryRun": dry_run, "deleted": results}


@app.post("/api/v1/compliance-demo-seed")
def compliance_demo_seed(_: bool = Depends(verify_api_key)):
    samples = [
        ("route_reference", {
            "routeName": "Bangalore-Chennai",
            "kmMarker": 42,
            "latitude": 12.9712,
            "longitude": 77.5912,
            "trackFeature": "curve",
            "description": "Demo RDSO route reference point",
            "createdAt": utc_now().isoformat(),
        }),
        ("section_reference", {
            "railway": "SWR",
            "division": "Bangalore",
            "sectionName": "Bangalore-Chennai Demo Section",
            "routeName": "Bangalore-Chennai",
            "fromKm": 40,
            "toKm": 50,
            "createdAt": utc_now().isoformat(),
        }),
        ("device_health", {
            "gatewayId": "GW_BOGIE_001",
            "trainId": "TRAIN_07",
            "firmwareVersion": "1.0.0",
            "softwareVersion": "cloud-demo",
            "gsmSignalPercent": 82,
            "gpsFix": True,
            "storageFreeMb": 2048,
            "status": "online",
            "createdAt": utc_now().isoformat(),
        }),
        ("power_status", {
            "gatewayId": "GW_BOGIE_001",
            "trainId": "TRAIN_07",
            "batteryPercent": 88,
            "inputVoltage": 24.0,
            "charging": True,
            "backupAvailableHours": 24,
            "status": "normal",
            "createdAt": utc_now().isoformat(),
        }),
    ]
    inserted = {}
    for collection_name, doc in samples:
        inserted[collection_name] = mongo_insert(collection_name, doc)
    return {
        "status": "success" if mongo_enabled() else "mongodb_not_configured",
        "message": "Reference, section, health, and power demo records stored in MongoDB",
        "inserted": inserted,
        "storageView": "/mongodb-page",
    }
@app.get("/api/v1/mongodb-storage")
def get_mongodb_storage(limit: int = 5, _: bool = Depends(verify_api_key)):
    return mongo_storage_summary(limit)


@app.get("/api/v1/auth-check")
def auth_check(_: bool = Depends(verify_api_key)):
    return {"status": "authenticated", "message": "API key accepted"}


@app.post("/api/v1/mongodb-demo-upload")
async def mongodb_demo_upload(request: Request, _: bool = Depends(verify_api_key)):
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    gateway_id = payload.get("gatewayId") or payload.get("gateway_id") or "GW_BOGIE_001"
    train_id = payload.get("trainId") or payload.get("train_id") or "TRAIN_07"
    session_name = payload.get("sessionName") or payload.get("sessionId") or payload.get("session_id") or "MONGO_DEMO_SESSION"
    speed_kmph = float(payload.get("speedKmph") or payload.get("speed_kmph") or 0)
    peak_g = float(payload.get("peak") or payload.get("peakG") or payload.get("peak_g") or 0)
    threshold_g = float(
        payload.get("threshold")
        or payload.get("thresholdG")
        or payload.get("threshold_g")
        or 50
    )
    gps = payload.get("gps") or {}
    lat = gps.get("lat") or payload.get("lat") or payload.get("latitude")
    lon = gps.get("lon") or payload.get("lon") or payload.get("longitude")
    route_name = payload.get("route") or payload.get("routeName") or "DEFAULT"

    received_at = utc_now().isoformat()
    if speed_kmph < MIN_MEASUREMENT_SPEED_KMPH:
        operation_mode = "CALIBRATION_REQUIRED"
        operation_reason = "Speed is below 20 kmph, so wheel/encoder calibration can be reviewed before normal measurement."
    elif speed_kmph >= ALERT_SPEED_LIMIT_KMPH and peak_g > threshold_g:
        operation_mode = "ALERT_MONITORING"
        operation_reason = "Speed is at least 80 kmph and peak acceleration is above the active threshold, so alert processing is enabled."
    else:
        operation_mode = "THRESHOLD_MONITORING"
        operation_reason = "Speed is at least 20 kmph, so route-wise threshold monitoring is active."

    gateway_document = {
        "source": "render-demo-json",
        "gatewayId": gateway_id,
        "trainId": train_id,
        "sessionName": session_name,
        "routeName": route_name,
        "speedKmph": speed_kmph,
        "peakG": peak_g,
        "thresholdG": threshold_g,
        "operationMode": operation_mode,
        "operationReason": operation_reason,
        "gps": {"lat": lat, "lon": lon},
        "receivedAt": received_at,
        "payload": payload,
    }

    inserted = {
        "gateway_archives": mongo_insert("gateway_archives", gateway_document),
        "raw_gateway_payloads": mongo_insert("raw_gateway_payloads", {
            "source": "render-demo-json",
            "gatewayId": gateway_id,
            "trainId": train_id,
            "sessionName": session_name,
            "receivedAt": received_at,
            "payload": payload,
        }),
        "operation_decisions": mongo_insert("operation_decisions", {
            "gatewayId": gateway_id,
            "trainId": train_id,
            "sessionName": session_name,
            "routeName": route_name,
            "speedKmph": speed_kmph,
            "peakG": peak_g,
            "thresholdG": threshold_g,
            "operationMode": operation_mode,
            "operationReason": operation_reason,
            "calibrationSpeedLimitKmph": MIN_MEASUREMENT_SPEED_KMPH,
            "alertSpeedLimitKmph": ALERT_SPEED_LIMIT_KMPH,
            "receivedAt": received_at,
        }),
    }

    alerts_generated = 0
    if speed_kmph >= ALERT_SPEED_LIMIT_KMPH and peak_g > threshold_g:
        alerts_generated = 1
        message = (
            f"UABAMS alert: {train_id} peak {peak_g:.2f}g crossed {threshold_g:.2f}g at {speed_kmph:.2f} kmph "
            f"near GPS {lat}, {lon}"
        )
        alert_doc = {
            "gatewayId": gateway_id,
            "trainId": train_id,
            "sessionName": session_name,
            "routeName": route_name,
            "speedKmph": speed_kmph,
            "peakG": peak_g,
            "thresholdG": threshold_g,
            "thresholdSpeedKmph": ALERT_SPEED_LIMIT_KMPH,
            "gps": {"lat": lat, "lon": lon},
            "message": message,
            "receivedAt": received_at,
        }
        inserted["alert_notifications"] = mongo_insert("alert_notifications", alert_doc)
        sms_results = send_sms_notification(alert_doc, message)
        inserted["sms_logs"] = [result.get("mongoId") for result in sms_results]
        try:
            init_db()
            alert_payload = {
                "gatewayId": gateway_id,
                "trainId": train_id,
                "sessionName": session_name,
                "routeName": route_name,
                "windowStartMm": 0,
                "windowEndMm": 50000,
                "speedKmph": speed_kmph,
                "triggeredAxes": [
                    {
                        "axisName": "bg_z",
                        "alertType": "VERTICAL",
                        "peakValueMg": int(round(peak_g * 1000)),
                        "thresholdMg": int(round(threshold_g * 1000)),
                        "peakPositionMm": 1200,
                        "peakLat": lat,
                        "peakLon": lon,
                    }
                ],
            }
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                        INSERT INTO cloud_alert_events
                        (
                            gateway_id, train_id, session_name, window_start_mm,
                            window_end_mm, speed_kmph, triggered_axes_count, payload_json
                        )
                        VALUES
                        (
                            :gateway_id, :train_id, :session_name, :window_start_mm,
                            :window_end_mm, :speed_kmph, :triggered_axes_count, :payload_json
                        )
                        RETURNING alert_event_id
                    """),
                    {
                        "gateway_id": gateway_id,
                        "train_id": train_id,
                        "session_name": session_name,
                        "window_start_mm": 0,
                        "window_end_mm": 50000,
                        "speed_kmph": speed_kmph,
                        "triggered_axes_count": 1,
                        "payload_json": json.dumps(alert_payload),
                    },
                ).fetchone()
                conn.commit()
            inserted["alert_event_id"] = row.alert_event_id if row else None
        except Exception as exc:
            inserted["alert_event_error"] = str(exc)

    return {
        "status": "success",
        "message": "Demo gateway data stored in MongoDB Atlas" if mongo_enabled() else "MongoDB is not configured on this deployment",
        "mongoEnabled": mongo_enabled(),
        "database": MONGODB_DB_NAME,
        "inserted": inserted,
        "alertsGenerated": alerts_generated,
        "operationMode": operation_mode,
        "operationReason": operation_reason,
        "storageView": "/api/v1/mongodb-storage",
    }


@app.get("/api/v1/sms-notifications")
def get_sms_notifications(limit: int = 20, _: bool = Depends(verify_api_key)):
    safe_limit = max(1, min(limit, 100))
    summary = {
        "smsEnabled": SMS_ENABLED,
        "providerStatus": sms_provider_status(),
        "providerConfigured": bool(SMS_PROVIDER_URL),
        "recipientsConfigured": len(SMS_TO_NUMBERS),
        "database": MONGODB_DB_NAME,
        "logs": [],
    }
    if not mongo_enabled():
        summary["status"] = "mongodb_not_configured"
        return summary
    try:
        db = get_mongo_db()
        rows = list(db["sms_logs"].find({}, {"_id": 0}).sort("createdAt", -1).limit(safe_limit))
        summary["status"] = "connected"
        summary["logs"] = clean_for_mongo(rows)
        summary["count"] = db["sms_logs"].count_documents({})
    except PyMongoError as exc:
        summary["status"] = "error"
        summary["error"] = str(exc)
    return summary


@app.post("/api/v1/sms-test")
async def sms_test(request: Request, _: bool = Depends(verify_api_key)):
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        payload = {}
    alert_doc = {
        "gatewayId": payload.get("gatewayId", "GW_BOGIE_001"),
        "trainId": payload.get("trainId", "TRAIN_07"),
        "sessionName": payload.get("sessionName", "SMS_TEST_SESSION"),
        "routeName": payload.get("routeName", "DEFAULT"),
        "speedKmph": float(payload.get("speedKmph", 90)),
        "peakG": float(payload.get("peakG", payload.get("peak", 95))),
        "gps": payload.get("gps", {"lat": 12.9712, "lon": 77.5912}),
    }
    logs = send_sms_notification(alert_doc, payload.get("message"))
    return {
        "status": "success",
        "smsProviderStatus": sms_provider_status(),
        "smsEnabled": SMS_ENABLED,
        "logs": clean_for_mongo(logs),
    }


@app.get("/api/v1/archives")
def get_session_archives(limit: int = 50):
    init_db()
    safe_limit = max(1, min(limit, 500))
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    archive_id,
                    gateway_id,
                    train_id,
                    session_name,
                    archive_name,
                    archive_size_bytes,
                    upload_received_utc,
                    storage_uri,
                    checksum,
                    validation_status,
                    validation_errors
                FROM archives
                ORDER BY archive_id DESC
                LIMIT :limit
            """),
            {"limit": safe_limit},
        ).fetchall()

    return [
        {
            "archive_id": row.archive_id,
            "gateway_id": row.gateway_id,
            "train_id": row.train_id,
            "session_name": row.session_name,
            "archive_name": row.archive_name,
            "archive_size_bytes": row.archive_size_bytes,
            "upload_received_utc": str(row.upload_received_utc) if row.upload_received_utc else None,
            "storage_uri": row.storage_uri,
            "checksum": row.checksum,
            "validation_status": row.validation_status,
            "validation_errors": row.validation_errors,
        }
        for row in rows
    ]


@app.get("/api/v1/archives/{archive_id}/files")
def get_archive_files(archive_id: int):
    init_db()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    file_relative_path,
                    extracted_at_utc,
                    file_size_bytes,
                    storage_uri,
                    integrity_ok
                FROM extracted_files
                WHERE archive_id = :archive_id
                ORDER BY file_relative_path
            """),
            {"archive_id": archive_id},
        ).fetchall()

    return [
        {
            "file_relative_path": row.file_relative_path,
            "extracted_at_utc": str(row.extracted_at_utc) if row.extracted_at_utc else None,
            "file_size_bytes": row.file_size_bytes,
            "storage_uri": row.storage_uri,
            "integrity_ok": row.integrity_ok,
        }
        for row in rows
    ]


@app.get("/api/v1/alerts")
def get_cloud_alert_events(limit: int = 50):
    init_db()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    alert_event_id,
                    gateway_id,
                    train_id,
                    session_name,
                    window_start_mm,
                    window_end_mm,
                    speed_kmph,
                    triggered_axes_count,
                    payload_json,
                    received_utc
                FROM cloud_alert_events
                ORDER BY alert_event_id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

    return [map_alert_event_row(row) for row in rows]


@app.get("/api/v1/rms-series")
def get_rms_series(limit: int = 1200):
    init_db()
    safe_limit = max(1, min(limit, 5000))
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    r.record_index,
                    r.position_mm,
                    r.latitude,
                    r.longitude,
                    r.gps_valid,
                    r.al_x_mg, r.al_y_mg, r.al_z_mg,
                    r.ar_x_mg, r.ar_y_mg, r.ar_z_mg,
                    r.bg_x_mg, r.bg_y_mg, r.bg_z_mg,
                    s.gateway_id,
                    s.train_id,
                    s.session_name,
                    s.route_name
                FROM rms_records r
                JOIN sessions s ON s.session_id = r.session_id
                ORDER BY r.rms_id DESC
                LIMIT :limit
            """),
            {"limit": safe_limit},
        ).fetchall()

        threshold_row = conn.execute(
            text("""
                SELECT route_name, vertical_threshold, lateral_threshold
                FROM thresholds
                ORDER BY id DESC
                LIMIT 1
            """)
        ).fetchone()

    threshold = {
        "routeName": threshold_row.route_name if threshold_row else "DEFAULT",
        "verticalG": float(threshold_row.vertical_threshold) if threshold_row else 50.0,
        "lateralG": float(threshold_row.lateral_threshold) if threshold_row else 80.0,
        "alertSpeedKmph": ALERT_SPEED_LIMIT_KMPH,
    }

    records = []
    for row in reversed(rows):
        x_g = max(abs(row.al_x_mg or 0), abs(row.ar_x_mg or 0), abs(row.bg_x_mg or 0)) / 1000
        y_g = max(abs(row.al_y_mg or 0), abs(row.ar_y_mg or 0), abs(row.bg_y_mg or 0)) / 1000
        z_g = max(abs(row.al_z_mg or 0), abs(row.ar_z_mg or 0), abs(row.bg_z_mg or 0)) / 1000
        distance_km = (row.position_mm or row.record_index * 250) / 1_000_000
        records.append(
            {
                "recordIndex": row.record_index,
                "distanceKm": round(distance_km, 6),
                "positionMm": row.position_mm,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "gpsValid": row.gps_valid,
                "gatewayId": row.gateway_id,
                "trainId": row.train_id,
                "sessionName": row.session_name,
                "routeName": row.route_name,
                "xG": round(x_g, 6),
                "yG": round(y_g, 6),
                "zG": round(z_g, 6),
                "xAlert": x_g > threshold["lateralG"],
                "yAlert": y_g > threshold["lateralG"],
                "zAlert": z_g > threshold["verticalG"],
            }
        )

    return {"threshold": threshold, "records": records}


@app.post("/api/v1/alerts")
def receive_cloud_alert_event(alert: CloudAlertEvent):
    init_db()
    payload = alert.model_dump()
    if alert.speedKmph < ALERT_SPEED_LIMIT_KMPH:
        raise HTTPException(
            status_code=422,
            detail=f"Alert speed must be at least {ALERT_SPEED_LIMIT_KMPH} kmph",
        )

    triggered_axes = pick_highest_vertical_and_lateral_axes([
        axis.model_dump()
        for axis in alert.triggeredAxes
        if axis.peakValueMg > axis.thresholdMg
    ])
    if not triggered_axes:
        raise HTTPException(
            status_code=422,
            detail="No vertical or lateral axis crossed the configured threshold",
        )

    payload["triggeredAxes"] = triggered_axes
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                INSERT INTO cloud_alert_events
                (
                    gateway_id,
                    train_id,
                    session_name,
                    window_start_mm,
                    window_end_mm,
                    speed_kmph,
                    triggered_axes_count,
                    payload_json
                )
                VALUES
                (
                    :gateway_id,
                    :train_id,
                    :session_name,
                    :window_start_mm,
                    :window_end_mm,
                    :speed_kmph,
                    :triggered_axes_count,
                    :payload_json
                )
                RETURNING alert_event_id
            """),
            {
                "gateway_id": alert.gatewayId,
                "train_id": alert.trainId,
                "session_name": alert.sessionName,
                "window_start_mm": alert.windowStartMm,
                "window_end_mm": alert.windowEndMm,
                "speed_kmph": alert.speedKmph,
                "triggered_axes_count": len(triggered_axes),
                "payload_json": json.dumps(payload),
            },
        ).fetchone()
        conn.commit()

    return {
        "message": "Alert event received",
        "alert_event_id": row.alert_event_id,
        "gateway_id": alert.gatewayId,
        "train_id": alert.trainId,
        "session_name": alert.sessionName,
    }


@app.post("/api/v1/alert")
async def receive_single_cloud_alert_event(request: Request):
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON alert payload") from exc

    if "triggeredAxes" not in payload:
        peak_value_g = float(payload.get("peakValueG") or payload.get("peakG") or payload.get("peak") or 0)
        threshold_g = float(payload.get("thresholdG") or payload.get("threshold") or 100)
        peak_axis = payload.get("peakAxis") or payload.get("axisName") or "AL_Z"
        latitude = float(payload.get("latitude") or payload.get("peakLat") or 0)
        longitude = float(payload.get("longitude") or payload.get("peakLon") or 0)
        payload = {
            "gatewayId": payload.get("gatewayId") or "UNKNOWN_GATEWAY",
            "trainId": payload.get("trainId") or "UNKNOWN_TRAIN",
            "sessionName": payload.get("sessionName") or "UNKNOWN_SESSION",
            "routeName": payload.get("routeName") or "DEFAULT",
            "windowStartMm": int(payload.get("windowStartMm") or 0),
            "windowEndMm": int(payload.get("windowEndMm") or 50000),
            "speedKmph": float(payload.get("speedKmph") or 0),
            "triggeredAxes": [
                {
                    "axisName": str(peak_axis).lower(),
                    "alertType": "VERTICAL" if str(peak_axis).upper().endswith("Z") else "LATERAL",
                    "peakValueMg": int(round(peak_value_g * 1000)),
                    "thresholdMg": int(round(threshold_g * 1000)),
                    "peakPositionMm": int(payload.get("masterCount") or payload.get("peakPositionMm") or payload.get("windowStartMm") or 0),
                    "peakLat": latitude,
                    "peakLon": longitude,
                }
            ],
        }

    return receive_cloud_alert_event(CloudAlertEvent(**payload))


@app.get("/api/v1/calibration/{gateway_id}")
def get_gateway_calibration(gateway_id: str):
    return {
        "gatewayId": gateway_id,
        "targetNode": "ADXL Node (0x01)",
        "version": 1,
        "scaleXQ16": 65536,
        "scaleYQ16": 65536,
        "scaleZQ16": 65536,
        "offsetX": 0,
        "offsetY": 0,
        "offsetZ": 0,
        "message": "Calibration payload ready for gateway pull",
    }


@app.post("/api/v1/gateway/{gateway_id}/ping")
def ping_gateway_nodes(gateway_id: str):
    return {
        "gatewayId": gateway_id,
        "status": "ok",
        "message": "Ping command accepted. ADXL and encoder nodes are RUNNING.",
    }


@app.post("/api/v1/gateway/{gateway_id}/reset")
def reset_gateway_nodes(gateway_id: str):
    return {
        "gatewayId": gateway_id,
        "status": "ok",
        "message": "Reset command accepted. Gateway nodes restarting.",
    }


# =====================================
# Database Test API
# =====================================

@app.get("/db-test")
def db_test():

    with engine.connect() as conn:
        result = conn.execute(text("SELECT NOW()"))

        return {
            "database_time": str(result.scalar())
        }


# =====================================
# Get Latest Threshold
# =====================================

@app.get("/threshold")
def get_threshold(route_name: str = "DEFAULT"):

    with engine.connect() as conn:

        result = conn.execute(
            text("""
                SELECT *
                FROM thresholds
                WHERE route_name = :route_name
                ORDER BY id DESC
                LIMIT 1
            """),
            {"route_name": route_name}
        )

        row = result.fetchone()

        if row:
            return {
                "id": row.id,
                "route_name": row.route_name,
                "vertical_threshold": round_value(row.vertical_threshold, 2),
                "lateral_threshold": round_value(row.lateral_threshold, 2),
                "created_at": str(row.created_at) if hasattr(row, "created_at") else None
            }

        return {
            "message": "No threshold configured"
        }


# =====================================
# Save Threshold
# =====================================

@app.post("/threshold")
def set_threshold(threshold: Threshold):

    with engine.connect() as conn:

        conn.execute(
            text("""
                INSERT INTO thresholds
                (
                    vertical_threshold,
                    lateral_threshold,
                    route_name
                )
                VALUES
                (
                    :vertical_threshold,
                    :lateral_threshold,
                    :route_name
                )
            """),
            {
                "vertical_threshold": threshold.vertical_threshold,
                "lateral_threshold": threshold.lateral_threshold,
                "route_name": threshold.route_name
            }
        )

        conn.commit()

    return {
        "message": "Threshold saved successfully",
        "route_name": threshold.route_name,
        "vertical_threshold": round_value(threshold.vertical_threshold, 2),
        "lateral_threshold": round_value(threshold.lateral_threshold, 2)
    }


# =====================================
# Save Sensor Calibration
# =====================================

@app.post("/sensor-calibration")
def save_sensor_calibration(calibration: SensorCalibration):

    with engine.connect() as conn:

        conn.execute(
            text("""
                INSERT INTO sensor_calibration
                (
                    sensor_name,
                    sensor_offset,
                    scale_factor
                )
                VALUES
                (
                    :sensor_name,
                    :sensor_offset,
                    :scale_factor
                )
            """),
            {
                "sensor_name": calibration.sensor_name,
                "sensor_offset": calibration.sensor_offset,
                "scale_factor": calibration.scale_factor
            }
        )

        conn.commit()

    return {
        "message": "Sensor calibration saved successfully",
        "sensor_name": calibration.sensor_name
    }


# =====================================
# Get Sensor Calibration
# =====================================

@app.get("/sensor-calibration")
def get_sensor_calibration():

    with engine.connect() as conn:

        result = conn.execute(
            text("""
                SELECT *
                FROM sensor_calibration
                ORDER BY id DESC
            """)
        )

        rows = result.fetchall()

        data = []

        for row in rows:
            data.append(
                {
                    "id": row[0],
                    "sensor_name": row[1],
                    "sensor_offset": row[2],
                    "scale_factor": row[3]
                }
            )

        return data


# =====================================
# Save Wheel Calibration
# =====================================

@app.post("/wheel-calibration")
def save_wheel_calibration(calibration: WheelCalibration):
    current_diameter = calibration.current_wheel_diameter_mm or calibration.wheel_diameter_mm

    if current_diameter is None:
        raise HTTPException(
            status_code=400,
            detail="Provide current_wheel_diameter_mm or wheel_diameter_mm"
        )
    if current_diameter > calibration.new_wheel_diameter_mm:
        raise HTTPException(
            status_code=422,
            detail="Current wheel diameter cannot be greater than new wheel diameter"
        )

    circumference_mm = 3.141592653589793 * current_diameter
    distance_per_pulse_mm = circumference_mm / calibration.encoder_pulses_per_rev
    wheel_wear_mm = calibration.new_wheel_diameter_mm - current_diameter
    correction_factor = current_diameter / calibration.new_wheel_diameter_mm

    with engine.connect() as conn:

        conn.execute(
            text("""
                INSERT INTO wheel_calibration
                (
                    train_no,
                    wheel_diameter_mm,
                    axle_no,
                    wheel_position,
                    new_wheel_diameter_mm,
                    current_wheel_diameter_mm,
                    encoder_pulses_per_rev,
                    circumference_mm,
                    distance_per_pulse_mm,
                    wheel_wear_mm,
                    correction_factor
                )
                VALUES
                (
                    :train_no,
                    :wheel_diameter_mm,
                    :axle_no,
                    :wheel_position,
                    :new_wheel_diameter_mm,
                    :current_wheel_diameter_mm,
                    :encoder_pulses_per_rev,
                    :circumference_mm,
                    :distance_per_pulse_mm,
                    :wheel_wear_mm,
                    :correction_factor
                )
            """),
            {
                "train_no": calibration.train_no,
                "wheel_diameter_mm": current_diameter,
                "axle_no": calibration.axle_no,
                "wheel_position": calibration.wheel_position,
                "new_wheel_diameter_mm": calibration.new_wheel_diameter_mm,
                "current_wheel_diameter_mm": current_diameter,
                "encoder_pulses_per_rev": calibration.encoder_pulses_per_rev,
                "circumference_mm": circumference_mm,
                "distance_per_pulse_mm": distance_per_pulse_mm,
                "wheel_wear_mm": wheel_wear_mm,
                "correction_factor": correction_factor
            }
        )

        conn.commit()

    return {
        "message": "Wheel calibration saved successfully",
        "train_no": calibration.train_no,
        "wheel_diameter_mm": round_value(current_diameter, 2),
        "axle_no": calibration.axle_no,
        "wheel_position": calibration.wheel_position,
        "new_wheel_diameter_mm": round_value(calibration.new_wheel_diameter_mm, 2),
        "current_wheel_diameter_mm": round_value(current_diameter, 2),
        "encoder_pulses_per_rev": calibration.encoder_pulses_per_rev,
        "circumference_mm": round_value(circumference_mm, 4),
        "distance_per_pulse_mm": round_value(distance_per_pulse_mm, 4),
        "wheel_wear_mm": round_value(wheel_wear_mm, 2),
        "correction_factor": round_value(correction_factor, 4)
    }


# =====================================
# Get Wheel Calibration
# =====================================

@app.get("/wheel-calibration")
def get_wheel_calibration():

    with engine.connect() as conn:

        result = conn.execute(
            text("""
                SELECT *
                FROM wheel_calibration
                ORDER BY id DESC
            """)
        )

        rows = result.fetchall()

        data = []

        for row in rows:
            data.append(
                {
                    "id": row.id,
                    "train_no": row.train_no,
                    "wheel_diameter_mm": row.wheel_diameter_mm,
                    "axle_no": row.axle_no,
                    "wheel_position": row.wheel_position,
                    "new_wheel_diameter_mm": row.new_wheel_diameter_mm,
                    "current_wheel_diameter_mm": row.current_wheel_diameter_mm,
                    "encoder_pulses_per_rev": row.encoder_pulses_per_rev,
                    "circumference_mm": row.circumference_mm,
                    "distance_per_pulse_mm": row.distance_per_pulse_mm,
                    "wheel_wear_mm": row.wheel_wear_mm,
                    "correction_factor": row.correction_factor,
                    "created_at": str(row.created_at) if row.created_at else None
                }
            )

        return data


@app.post("/api/data", include_in_schema=False)
def receive_gateway_data(data: GatewayData):

    with engine.connect() as conn:
        calibration_result = conn.execute(
            text("""
                SELECT correction_factor
                FROM wheel_calibration
                WHERE train_no = :train_no
                ORDER BY id DESC
                LIMIT 1
            """),
            {"train_no": data.train_no}
        )
        calibration = calibration_result.fetchone()
        correction_factor = calibration.correction_factor if calibration else 1
        corrected_speed_kmph = data.speed_kmph * correction_factor

        # Store acceleration data
        conn.execute(
            text("""
                INSERT INTO acceleration_data
                (
                    record_index,
                    train_no,
                    route_name,
                    km_marker,
                    meter,
                    vertical_g,
                    lateral_g,
                    speed_kmph,
                    latitude,
                    longitude,
                    corrected_speed_kmph,
                    wheel_correction_factor,
                    status_code,
                    sample_distance_m
                )
                VALUES
                (
                    :record_index,
                    :train_no,
                    :route_name,
                    :km_marker,
                    :meter,
                    :vertical_g,
                    :lateral_g,
                    :speed_kmph,
                    :latitude,
                    :longitude,
                    :corrected_speed_kmph,
                    :wheel_correction_factor,
                    :status_code,
                    :sample_distance_m
                )
            """),
            {
                "record_index": data.record_index,
                "train_no": data.train_no,
                "route_name": data.route_name,
                "km_marker": data.km_marker,
                "meter": data.meter,
                "vertical_g": data.vertical_g,
                "lateral_g": data.lateral_g,
                "speed_kmph": data.speed_kmph,
                "latitude": data.latitude,
                "longitude": data.longitude,
                "corrected_speed_kmph": corrected_speed_kmph,
                "wheel_correction_factor": correction_factor,
                "status_code": data.status_code,
                "sample_distance_m": data.sample_distance_m
            }
        )

        # Read latest threshold
        result = conn.execute(
            text("""
                SELECT *
                FROM thresholds
                WHERE route_name = :route_name
                ORDER BY id DESC
                LIMIT 1
            """),
            {"route_name": data.route_name}
        )

        threshold = result.fetchone()
        generated_alerts = []

        if threshold:

            vertical_limit = threshold.vertical_threshold
            lateral_limit = threshold.lateral_threshold
            is_alert_speed = corrected_speed_kmph >= ALERT_SPEED_LIMIT_KMPH

            # Vertical Alert
            if is_alert_speed and abs(data.vertical_g) > vertical_limit:

                conn.execute(
                    text("""
                        INSERT INTO alerts
                        (
                            route_name,
                            record_index,
                            train_no,
                            alert_type,
                            measured_value,
                            threshold_value,
                            km_marker,
                            meter,
                            latitude,
                            longitude,
                            speed_kmph,
                            status_code
                        )
                        VALUES
                        (
                            :route_name,
                            :record_index,
                            :train_no,
                            :alert_type,
                            :measured_value,
                            :threshold_value,
                            :km_marker,
                            :meter,
                            :latitude,
                            :longitude,
                            :speed_kmph,
                            :status_code
                        )
                    """),
                    {
                        "route_name": data.route_name,
                        "record_index": data.record_index,
                        "train_no": data.train_no,
                        "alert_type": "VERTICAL",
                        "measured_value": data.vertical_g,
                        "threshold_value": vertical_limit,
                        "km_marker": data.km_marker,
                        "meter": data.meter,
                        "latitude": data.latitude,
                        "longitude": data.longitude,
                        "speed_kmph": corrected_speed_kmph,
                        "status_code": data.status_code
                    }
                )
                generated_alerts.append("VERTICAL")

            # Lateral Alert
            if is_alert_speed and abs(data.lateral_g) > lateral_limit:

                conn.execute(
                    text("""
                        INSERT INTO alerts
                        (
                            route_name,
                            record_index,
                            train_no,
                            alert_type,
                            measured_value,
                            threshold_value,
                            km_marker,
                            meter,
                            latitude,
                            longitude,
                            speed_kmph,
                            status_code
                        )
                        VALUES
                        (
                            :route_name,
                            :record_index,
                            :train_no,
                            :alert_type,
                            :measured_value,
                            :threshold_value,
                            :km_marker,
                            :meter,
                            :latitude,
                            :longitude,
                            :speed_kmph,
                            :status_code
                        )
                    """),
                    {
                        "route_name": data.route_name,
                        "record_index": data.record_index,
                        "train_no": data.train_no,
                        "alert_type": "LATERAL",
                        "measured_value": data.lateral_g,
                        "threshold_value": lateral_limit,
                        "km_marker": data.km_marker,
                        "meter": data.meter,
                        "latitude": data.latitude,
                        "longitude": data.longitude,
                        "speed_kmph": corrected_speed_kmph,
                        "status_code": data.status_code
                    }
                )
                generated_alerts.append("LATERAL")

        conn.commit()

    return {
        "message": "Gateway data received successfully",
        "route_name": data.route_name,
        "corrected_speed_kmph": corrected_speed_kmph,
        "wheel_correction_factor": correction_factor,
        "alert_speed_limit_kmph": ALERT_SPEED_LIMIT_KMPH,
        "generated_alerts": generated_alerts
    }


# =====================================
# Get Gateway Data
# =====================================

@app.get("/api/data", include_in_schema=False)
def get_gateway_data():

    with engine.connect() as conn:

        result = conn.execute(
            text("""
                SELECT *
                FROM acceleration_data
                ORDER BY id DESC
                LIMIT 100
            """)
        )

        rows = result.fetchall()

        data = []

        for row in rows:
            data.append(
                {
                    "id": row.id,
                    "record_index": row.record_index,
                    "train_no": row.train_no,
                    "route_name": row.route_name,
                    "km_marker": row.km_marker,
                    "meter": row.meter,
                    "vertical_g": row.vertical_g,
                    "lateral_g": row.lateral_g,
                    "speed_kmph": row.speed_kmph,
                    "latitude": row.latitude,
                    "longitude": row.longitude,
                    "corrected_speed_kmph": row.corrected_speed_kmph,
                    "wheel_correction_factor": row.wheel_correction_factor,
                    "status_code": row.status_code,
                    "sample_distance_m": row.sample_distance_m,
                    "created_at": str(row.created_at) if row.created_at else None
                }
            )

        return data
    
    # =====================================
# Get Alerts
# =====================================

@app.get("/alerts")
def get_alerts():

    with engine.connect() as conn:

        result = conn.execute(
            text("""
                SELECT *
                FROM alerts
                ORDER BY id DESC
                LIMIT 100
            """)
        )

        rows = result.fetchall()

        data = []

        for row in rows:

            data.append(
                {
                    "id": row.id,
                    "route_name": row.route_name,
                    "record_index": row.record_index,
                    "train_no": row.train_no,
                    "alert_type": row.alert_type,
                    "measured_value": row.measured_value,
                    "threshold_value": row.threshold_value,
                    "km_marker": row.km_marker,
                    "meter": row.meter,
                    "latitude": row.latitude,
                    "longitude": row.longitude,
                    "speed_kmph": row.speed_kmph,
                    "status_code": row.status_code,
                    "created_at": str(row.created_at) if row.created_at else None
                }
            )

        return data


@app.get("/cloud/export")
def cloud_export(limit: int = 100):
    with engine.connect() as conn:
        gateway_rows = conn.execute(
            text("""
                SELECT *
                FROM acceleration_data
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

        alert_rows = conn.execute(
            text("""
                SELECT *
                FROM alerts
                ORDER BY id DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

    gateway_records = []
    for row in gateway_rows:
        gateway_records.append(
            {
                "record_index": row.record_index,
                "train_no": row.train_no,
                "route_name": row.route_name,
                "position": {
                    "km_marker": row.km_marker,
                    "meter": round_value(row.meter, 2),
                    "sample_distance_m": round_value(row.sample_distance_m, 2),
                    "latitude": round_value(row.latitude, 6),
                    "longitude": round_value(row.longitude, 6),
                },
                "measurement": {
                    "vertical_g": round_value(row.vertical_g, 4),
                    "lateral_g": round_value(row.lateral_g, 4),
                    "speed_kmph": round_value(row.speed_kmph, 4),
                    "corrected_speed_kmph": round_value(row.corrected_speed_kmph, 4),
                    "wheel_correction_factor": round_value(row.wheel_correction_factor, 4),
                    "status_code": row.status_code,
                },
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )

    alert_records = []
    for row in alert_rows:
        alert_records.append(
            {
                "record_index": row.record_index,
                "train_no": row.train_no,
                "route_name": row.route_name,
                "alert_type": row.alert_type,
                "measured_value_g": round_value(row.measured_value, 4),
                "threshold_value_g": round_value(row.threshold_value, 4),
                "speed_kmph": round_value(row.speed_kmph, 4),
                "position": {
                    "km_marker": row.km_marker,
                    "meter": round_value(row.meter, 2),
                    "latitude": round_value(row.latitude, 6),
                    "longitude": round_value(row.longitude, 6),
                },
                "status_code": row.status_code,
                "created_at": str(row.created_at) if row.created_at else None,
            }
        )

    return {
        "system": "UABAMS",
        "target_integration": "production cloud handoff",
        "payload_version": "1.0",
        "cloud_database": "PostgreSQL",
        "gateway_records": gateway_records,
        "alert_records": alert_records,
    }


@app.get("/csv/reports")
def csv_reports():
    return [
        {
            "name": name,
            "title": report["title"],
            "download_url": f"/csv/download/{name}",
            "preview_url": f"/csv/preview/{name}",
        }
        for name, report in CSV_REPORTS.items()
    ]


@app.get("/tms/package")
def tms_transfer_package(limit: int = 5000):
    safe_limit = max(1, min(limit, 5000))
    package = io.BytesIO()
    created_utc = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        init_db()
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as tms_zip:
            manifest = {
                "system": "UABAMS",
                "packageType": "TMS_MDB_HANDOFF_PACKAGE",
                "createdUtc": created_utc,
                "storageModel": "PostgreSQL database plus open ASCII text exports",
                "preferredFinalFormat": "MDB",
                "mdbNote": (
                    "MDB is preferred in the specification. Generation of a true "
                    "Microsoft Access MDB file requires an Access/ODBC-compatible "
                    "writer in the target environment. This package contains the "
                    "documented open ASCII tables and schema needed for MDB/TMS import."
                ),
                "sourceUploadEndpoint": "/api/v1/archive",
                "includedReports": [],
            }

            for report_name in TMS_EXPORT_REPORTS:
                transfer_file = TMS_TRANSFER_FILES[report_name]
                ascii_text = build_delimited_text(report_name, safe_limit, delimiter="|")
                tms_zip.writestr(transfer_file["filename"], ascii_text)
                manifest["includedReports"].append(
                    {
                        "name": report_name,
                        "title": CSV_REPORTS[report_name]["title"],
                        "filename": transfer_file["filename"],
                        "targetMdbTable": transfer_file["mdb_table"],
                        "description": transfer_file["description"],
                    }
                )

            tms_zip.writestr("uabams_tms_schema.txt", TMS_SCHEMA_TEXT)
            tms_zip.writestr(
                "MDB_IMPORT_INSTRUCTIONS.txt",
                "Create/confirm the MDB schema with tables SpatialAccelerationData and ProcessedPeakData. "
                "Import spatial_acceleration_data.txt and processed_peak_data.txt using pipe delimiter, "
                "UTF-8 encoding, and first row as field names. Final MDB field naming/transfer protocol "
                "should be confirmed with CRIS/vendor after award of contract.\n",
            )
            tms_zip.writestr("manifest.json", json.dumps(manifest, indent=2))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable. Check DATABASE_URL. {exc.orig if getattr(exc, 'orig', None) else exc}",
        ) from exc

    package.seek(0)
    return Response(
        content=package.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="uabams_tms_mdb_handoff_package.zip"'
        },
    )


@app.get("/tms/mdb")
def tms_mdb_file(limit: int = 5000):
    safe_limit = max(1, min(limit, 5000))

    try:
        init_db()
        rows_by_table = {
            "SpatialAccelerationData": get_csv_rows("rms-records", safe_limit),
            "ProcessedPeakData": get_csv_rows("peak-records", safe_limit),
        }
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable. Check DATABASE_URL. {exc.orig if getattr(exc, 'orig', None) else exc}",
        ) from exc

    export_dir = ARCHIVE_STORAGE_DIR / "tms_exports"
    output_path = export_dir / "uabams_tms_transfer.mdb"

    try:
        create_mdb_with_windows_ado(rows_by_table, output_path)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=501,
            detail=(
                f"{exc} Deploy this same code on a Windows export machine with Microsoft Access "
                "Database Engine/Jet/ACE and pywin32, or use /tms/package for the documented MDB handoff package."
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"MDB generation failed: {exc}",
        ) from exc

    return Response(
        content=output_path.read_bytes(),
        media_type="application/x-msaccess",
        headers={
            "Content-Disposition": 'attachment; filename="uabams_tms_transfer.mdb"'
        },
    )


@app.get("/csv/preview/{report_name}")
def csv_preview(report_name: str, limit: int = 20):
    report = CSV_REPORTS.get(report_name)
    if not report:
        raise HTTPException(status_code=404, detail="CSV report not found")
    try:
        init_db()
        rows = get_csv_rows(report_name, limit)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable. Check DATABASE_URL. {exc.orig if getattr(exc, 'orig', None) else exc}",
        ) from exc
    return {
        "name": report_name,
        "title": report["title"],
        "download_url": f"/csv/download/{report_name}",
        "rows": rows,
    }


@app.get("/csv/download/{report_name}")
def csv_download(report_name: str, limit: int = 5000):
    try:
        init_db()
        return build_csv_response(report_name, limit)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable. Check DATABASE_URL. {exc.orig if getattr(exc, 'orig', None) else exc}",
        ) from exc


# =====================================
# Dashboard Pages
# =====================================

@app.get("/dashboard")
def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
    )


@app.get("/cloud-dashboard")
def cloud_dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "cloud_dashboard.html",
    )


@app.get("/wheel-page")
def wheel_page(request: Request):
    return templates.TemplateResponse(
        request,
        "wheel.html",
    )


@app.get("/threshold-page")
def threshold_page(request: Request):
    return templates.TemplateResponse(
        request,
        "threshold.html",
    )


@app.get("/gateway-page")
def gateway_page(request: Request):
    return templates.TemplateResponse(
        request,
        "gateway.html",
    )


@app.get("/alerts-page")
def alerts_page(request: Request):
    return templates.TemplateResponse(
        request,
        "alerts.html",
    )


@app.get("/sms-page")
def sms_page(request: Request):
    return templates.TemplateResponse(
        request,
        "sms_server.html",
    )


@app.get("/mongodb-page")
def mongodb_page(request: Request):
    return templates.TemplateResponse(
        request,
        "mongodb_storage.html",
    )



@app.get("/compliance-page")
def compliance_page(request: Request):
    return templates.TemplateResponse(
        "compliance.html",
        {"request": request},
    )
@app.get("/csv-page")
def csv_page(request: Request):
    return templates.TemplateResponse(
        request,
        "csv_reports.html",
    )

