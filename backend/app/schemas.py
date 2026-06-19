from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Module 2 - Gateway ingestion (PUT/POST /api/v1/archive)
# ---------------------------------------------------------------------------

class GpsIn(BaseModel):
    lat: float
    lon: float


class AxleDataIn(BaseModel):
    axleId: str
    verticalG: float
    lateralG: float
    rms: float
    peak: float


class ArchiveIn(BaseModel):
    """
    Accepts both the full Module 2 payload (with an axleData array) and the
    flat "simple demo" payload (gatewayId/trainId/speed/peak/gps) referenced
    in the quick-start API section. Exactly one of axleData / peak must be
    supplied so every upload yields at least one axle reading.
    """
    gatewayId: str
    trainId: str
    sessionId: Optional[str] = None
    timestamp: Optional[datetime] = None
    route: Optional[str] = "Bangalore-Chennai"
    gps: GpsIn

    speedKmph: Optional[float] = None
    speed: Optional[float] = None  # alias used by the simple demo payload

    axleData: Optional[List[AxleDataIn]] = None
    peak: Optional[float] = None  # flat shorthand used by the simple demo payload

    @model_validator(mode="after")
    def check_speed_and_axle_present(self):
        if self.speedKmph is None and self.speed is None:
            raise ValueError("speedKmph (or speed) is required")
        if self.axleData is None and self.peak is None:
            raise ValueError("axleData[] or a flat peak value is required")
        return self

    @property
    def resolved_speed(self) -> float:
        return self.speedKmph if self.speedKmph is not None else self.speed


class ArchiveResponse(BaseModel):
    status: str
    archiveId: int
    alertsGenerated: int
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# Module 3 - Threshold settings
# ---------------------------------------------------------------------------

class ThresholdIn(BaseModel):
    route: str
    verticalThreshold: float = Field(ge=0, le=100)
    lateralThreshold: float = Field(ge=0, le=100)
    alertsEnabled: Optional[bool] = True


class ThresholdOut(BaseModel):
    id: int
    route: str
    verticalThreshold: float
    lateralThreshold: float
    alertsEnabled: bool
    updatedAt: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Module 4 - Calibration
# ---------------------------------------------------------------------------

class CalibrationIn(BaseModel):
    gatewayId: str
    axleId: str
    wheelDiameterMm: float = Field(gt=0)
    wearPercent: float = Field(ge=0, le=100)
    correctionFactor: float = Field(gt=0)


class CalibrationOut(BaseModel):
    id: int
    gatewayId: str
    axleId: str
    wheelDiameterMm: float
    wearPercent: float
    correctionFactor: float
    createdAt: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class AlertOut(BaseModel):
    id: int
    time: datetime
    gatewayId: str
    trainId: str
    route: str
    axleId: Optional[str]
    metric: str
    peak: float
    threshold: float
    speedKmph: float
    severity: str
    message: str
    nearestTrackFeatureKm: Optional[float] = None

    class Config:
        from_attributes = True


class SmsNotificationOut(BaseModel):
    id: int
    alertId: Optional[int]
    gatewayId: str
    trainId: str
    recipient: str
    provider: str
    message: str
    status: str
    providerResponse: Optional[str] = None
    createdAt: datetime


# ---------------------------------------------------------------------------
# Module 6 - Cloud -> Gateway config sync
# ---------------------------------------------------------------------------

class ConfigOut(BaseModel):
    threshold: float
    wearPercent: float
    samplingRate: int


# ---------------------------------------------------------------------------
# Gateways
# ---------------------------------------------------------------------------

class GatewayOut(BaseModel):
    gatewayId: str
    status: str
    lastSeenAt: Optional[datetime]
    lastUploadAt: Optional[datetime]


# ---------------------------------------------------------------------------
# Dashboard (Module 1)
# ---------------------------------------------------------------------------

class RmsPoint(BaseModel):
    timestamp: datetime
    rms: float
    axleId: str


class PeakPoint(BaseModel):
    timestamp: datetime
    peak: float
    axleId: str


class RouteHeatmapPoint(BaseModel):
    route: str
    violations: int
    avgPeak: float
    sessions: int


class ThresholdViolationPoint(BaseModel):
    date: str
    critical: int
    warning: int
    info: int


class GpsLocationPoint(BaseModel):
    trainId: str
    gatewayId: str
    lat: float
    lon: float
    speedKmph: float
    status: str  # Normal | Alert
    timestamp: datetime


class SessionRow(BaseModel):
    trainId: str
    gatewayId: str
    route: str
    speedKmph: float
    peak: float
    status: str
    timestamp: datetime


class DashboardCards(BaseModel):
    activeTrains: int
    uploadedSessions: int
    alertsGenerated: int
    gatewaysOnline: int
    gatewaysTotal: int
    lastUploadTime: Optional[datetime]


class DashboardOut(BaseModel):
    cards: DashboardCards
    rmsTrend: List[RmsPoint]
    peakTrend: List[PeakPoint]
    routeHeatmap: List[RouteHeatmapPoint]
    thresholdViolations: List[ThresholdViolationPoint]
    gpsLocations: List[GpsLocationPoint]
    sessionsTable: List[SessionRow]


# ---------------------------------------------------------------------------
# Train roster (clause 6.11)
# ---------------------------------------------------------------------------

class TrainIn(BaseModel):
    trainId: str
    label: Optional[str] = None
    defaultRoute: Optional[str] = None
    active: Optional[bool] = True


class TrainOut(BaseModel):
    trainId: str
    label: Optional[str]
    defaultRoute: Optional[str]
    active: bool
    createdAt: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Route track points (clauses 4.10, 6.5) - Annexure-II reference data
# ---------------------------------------------------------------------------

class RouteTrackPointIn(BaseModel):
    km: float
    lat: float
    lon: float


class RouteTrackPointUploadIn(BaseModel):
    route: str
    points: List[RouteTrackPointIn]


class RouteTrackPointOut(BaseModel):
    id: int
    route: str
    km: float
    lat: float
    lon: float

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Route sections (clause 6.7) - Railway / Division / Section reference data
# ---------------------------------------------------------------------------

class RouteSectionIn(BaseModel):
    route: str
    railway: str
    division: str
    section: str
    fromKm: float
    toKm: float


class RouteSectionOut(BaseModel):
    id: int
    route: str
    railway: str
    division: str
    section: str
    fromKm: float
    toKm: float

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Maintenance / retention (clause 6.4)
# ---------------------------------------------------------------------------

class PurgeResponse(BaseModel):
    cutoffDate: datetime
    sessionsDeleted: int
    axleRecordsDeleted: int
    alertsDeleted: int
