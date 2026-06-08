import csv
import io
import os
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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

CSV_REPORTS = {
    "wheel-calibration": {
        "title": "Wheel Calibration",
        "filename": "uabams_wheel_calibration.csv",
        "query": """
            SELECT
                id,
                train_no,
                axle_no,
                wheel_position,
                new_wheel_diameter_mm,
                current_wheel_diameter_mm,
                encoder_pulses_per_rev,
                circumference_mm,
                distance_per_pulse_mm,
                wheel_wear_mm,
                correction_factor,
                created_at
            FROM wheel_calibration
            ORDER BY id DESC
            LIMIT :limit
        """,
    },
    "thresholds": {
        "title": "Thresholds",
        "filename": "uabams_thresholds.csv",
        "query": """
            SELECT
                id,
                route_name,
                vertical_threshold,
                lateral_threshold,
                created_at
            FROM thresholds
            ORDER BY id DESC
            LIMIT :limit
        """,
    },
    "gateway-data": {
        "title": "Gateway Data",
        "filename": "uabams_gateway_data.csv",
        "query": """
            SELECT
                id,
                record_index,
                train_no,
                route_name,
                km_marker,
                meter,
                vertical_g,
                lateral_g,
                speed_kmph,
                corrected_speed_kmph,
                wheel_correction_factor,
                latitude,
                longitude,
                status_code,
                sample_distance_m,
                created_at
            FROM acceleration_data
            ORDER BY id DESC
            LIMIT :limit
        """,
    },
    "alerts": {
        "title": "Alerts",
        "filename": "uabams_alerts.csv",
        "query": """
            SELECT
                id,
                route_name,
                record_index,
                train_no,
                alert_type,
                measured_value,
                threshold_value,
                speed_kmph,
                km_marker,
                meter,
                latitude,
                longitude,
                status_code,
                created_at
            FROM alerts
            ORDER BY id DESC
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
