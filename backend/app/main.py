import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import (
    alerts, archive, calibration, config, dashboard, gateways, maintenance, mongodb_storage,
    route_files, sections, sms, threshold, tms_export, trains,
)
from app.security import require_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uabams")

app = FastAPI(
    title="UABAMS Cloud API",
    description=(
        "Unattended Axle Box Acceleration Measurement System - cloud-side "
        "ingestion, processing, alerting and dashboard API for Indian Railways."
    ),
    version="1.0.0",
)

origins = ["*"] if settings.CORS_ORIGINS.strip() == "*" else [
    o.strip() for o in settings.CORS_ORIGINS.split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected_dependencies = [Depends(require_api_key)]

app.include_router(archive.router, dependencies=protected_dependencies)
app.include_router(dashboard.router, dependencies=protected_dependencies)
app.include_router(threshold.router, dependencies=protected_dependencies)
app.include_router(calibration.router, dependencies=protected_dependencies)
app.include_router(alerts.router, dependencies=protected_dependencies)
app.include_router(config.router, dependencies=protected_dependencies)
app.include_router(gateways.router, dependencies=protected_dependencies)
app.include_router(tms_export.router, dependencies=protected_dependencies)
app.include_router(trains.router, dependencies=protected_dependencies)
app.include_router(route_files.router, dependencies=protected_dependencies)
app.include_router(sections.router, dependencies=protected_dependencies)
app.include_router(maintenance.router, dependencies=protected_dependencies)
app.include_router(mongodb_storage.router, dependencies=protected_dependencies)
app.include_router(sms.router, dependencies=protected_dependencies)


@app.on_event("startup")
def on_startup():
    # Demo-friendly schema bootstrap. In a real production rollout this
    # would be replaced by Alembic migrations (see README).
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ensured.")

    if settings.SEED_ON_STARTUP:
        try:
            from app.seed import seed_if_empty

            seed_if_empty()
        except Exception as exc:  # pragma: no cover - seeding is best-effort
            logger.warning("Seed step skipped: %s", exc)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok", "service": "uabams-cloud-api"}


@app.get("/", tags=["health"])
def root():
    return {
        "service": "UABAMS Cloud API",
        "docs": "/docs",
        "health": "/health",
    }


