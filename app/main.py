import csv
import hashlib
import io
import json
import os
import re
import struct
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field

app = FastAPI(title="UABAMS Cloud", docs_url=None)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

ALERT_SPEED_LIMIT_KMPH = 80
SPATIAL_SAMPLE_DISTANCE_M = 0.25
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
    "rms/rms_25cm.bin": 66,
    "peak/peak_50m.bin": 302,
    "faults/faults.bin": 75,
}

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
    for record_index, raw in iter_fixed_records(file_path, 66) or []:
        values = struct.unpack_from("<QiddBBIIIIIIIII", raw, 0)
        records.append(
            {
                "record_index": record_index,
                "master_count": values[0],
                "position_mm": values[1],
                "latitude": values[2],
                "longitude": values[3],
                "gps_valid": bool(values[4]),
                "valid_mask": values[5],
                "al_x_mg": values[6],
                "al_y_mg": values[7],
                "al_z_mg": values[8],
                "ar_x_mg": values[9],
                "ar_y_mg": values[10],
                "ar_z_mg": values[11],
                "bg_x_mg": values[12],
                "bg_y_mg": values[13],
                "bg_z_mg": values[14],
            }
        )
    return records


def parse_peak_axis(raw: bytes, base: int):
    peak_value_mg, peak_position_mm, peak_master_count, peak_lat, peak_lon = struct.unpack_from(
        "<IiQdd", raw, base
    )
    return {
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
    for record_index, raw in iter_fixed_records(file_path, 302) or []:
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


def build_csv_response(report_name: str, limit: int = 100):
    report = CSV_REPORTS.get(report_name)
    rows = get_csv_rows(report_name, limit)
    output = io.StringIO()

    if rows:
        fieldnames = list(rows[0].keys())
    else:
        query_words = report["query"].split("FROM", 1)[0].replace("SELECT", "")
        fieldnames = [
            item.strip().split()[-1]
            for item in query_words.split(",")
            if item.strip()
        ]

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{report["filename"]}"'
        },
    )


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
    peakValueMg: int
    thresholdMg: int
    peakPositionMm: int
    peakLat: float
    peakLon: float


class CloudAlertEvent(BaseModel):
    gatewayId: str
    trainId: str
    sessionName: str
    windowStartMm: int
    windowEndMm: int
    speedKmph: float
    triggeredAxes: list[TriggeredAxis]


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
            "cloud_database": "Render PostgreSQL",
            "database_host": database_host(),
            "database_error": str(exc.orig) if getattr(exc, "orig", None) else str(exc),
            "required_tables": required_tables,
            "available_tables": [],
            "schema_ready": False,
            "railman_ready": False,
            "railman_export_endpoint": "/railman/export",
            "gateway_ingest_endpoint": "/api/data",
        }

    return {
        "api_status": "running",
        "database_status": "connected",
        "cloud_database": "Render PostgreSQL",
        "database_host": database_host(),
        "database_time": str(database_time),
        "required_tables": required_tables,
        "available_tables": available_tables,
        "schema_ready": set(required_tables).issubset(set(available_tables)),
        "railman_ready": True,
        "railman_export_endpoint": "/railman/export",
        "gateway_ingest_endpoint": "/api/data",
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
                    SELECT archive_id, validation_status
                    FROM archives
                    WHERE gateway_id = :gateway_id
                      AND session_name = :session_name
                """),
                {
                    "gateway_id": filename_parts["gateway_id"],
                    "session_name": filename_parts["session_name"],
                },
            ).fetchone()
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
                "message": "Duplicate archive already received",
                "archive_name": archive_name,
                "archive_id": existing.archive_id if existing else None,
                "validation_status": existing.validation_status if existing else "duplicate",
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
    return JSONResponse(
        status_code=status_code,
        content={
            "message": "Archive received",
            "archive_id": archive_id,
            "session_id": session_id,
            "archive_name": archive_name,
            "gateway_id": filename_parts["gateway_id"],
            "train_id": filename_parts["train_id"],
            "session_name": filename_parts["session_name"],
            "archive_size_bytes": archive_size,
            "checksum": checksum,
            "validation_status": validation["validation_status"],
            "validation_errors": validation["validation_errors"],
            "missing_files": validation["missing_files"],
            "stored_archive": str(archive_path),
        },
    )


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


@app.post("/api/v1/alerts")
def receive_cloud_alert_event(alert: CloudAlertEvent):
    init_db()
    payload = alert.model_dump()
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
                "triggered_axes_count": len(alert.triggeredAxes),
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


@app.post("/api/data")
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
            is_alert_speed = corrected_speed_kmph > ALERT_SPEED_LIMIT_KMPH

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

@app.get("/api/data")
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


@app.get("/railman/export")
def railman_export(limit: int = 100):
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
        "target_integration": "RailMAN / railway cloud handoff",
        "payload_version": "1.0",
        "cloud_database": "Render PostgreSQL",
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
            detail=f"Database unavailable. Check Render DATABASE_URL. {exc.orig if getattr(exc, 'orig', None) else exc}",
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
            detail=f"Database unavailable. Check Render DATABASE_URL. {exc.orig if getattr(exc, 'orig', None) else exc}",
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


@app.get("/csv-page")
def csv_page(request: Request):
    return templates.TemplateResponse(
        request,
        "csv_reports.html",
    )
