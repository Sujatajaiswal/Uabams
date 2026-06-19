"""
Database models for UABAMS.

Design note on Module 5's requested tables:
    gateway_sessions, rms_records, peak_records, alerts, calibration, threshold

`rms_records` and `peak_records` are normalised here into a single
`axle_records` table (one row per axle reading per session, holding both
the RMS and peak values together with verticalG/lateralG). Every incoming
axle reading always carries both numbers together, so splitting them into
two physically separate tables would only require a join to reconstruct
a single sensor reading and would duplicate axleId/sessionId twice over.
The RMS Trend and Peak Acceleration charts are simply two different
projections (rms vs peak) of this one table. This is noted here, and in
the README, for transparency since it is a deliberate deviation from the
literal table list for the sake of normalisation.
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Boolean,
    JSON, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Gateway(Base):
    """Edge gateway device mounted on a coach. Tracks online/offline state."""
    __tablename__ = "gateways"

    gateway_id = Column(String(64), primary_key=True)
    status = Column(String(16), default="offline", nullable=False)  # online | offline
    last_seen_at = Column(DateTime, nullable=True)
    last_upload_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    sessions = relationship("GatewaySession", back_populates="gateway")


class GatewaySession(Base):
    """One uploaded measurement session (one ZIP/JSON archive) from a gateway."""
    __tablename__ = "gateway_sessions"
    __table_args__ = (
        UniqueConstraint("gateway_id", "session_id", name="uq_gateway_session"),
        Index("ix_session_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False)
    gateway_id = Column(String(64), ForeignKey("gateways.gateway_id"), nullable=False)
    train_id = Column(String(64), nullable=False, index=True)
    route = Column(String(128), nullable=False, default="Bangalore-Chennai")
    timestamp = Column(DateTime, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    speed_kmph = Column(Float, nullable=False)
    raw_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    gateway = relationship("Gateway", back_populates="sessions")
    axle_records = relationship(
        "AxleRecord", back_populates="session", cascade="all, delete-orphan"
    )
    alerts = relationship("Alert", back_populates="session")


class AxleRecord(Base):
    """
    Per-axle sensor reading for a session. Serves both the 'rms_records'
    and 'peak_records' roles described in the spec (see module docstring).
    """
    __tablename__ = "axle_records"
    __table_args__ = (Index("ix_axle_session", "session_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("gateway_sessions.id"), nullable=False)
    axle_id = Column(String(32), nullable=False)
    vertical_g = Column(Float, nullable=False)
    lateral_g = Column(Float, nullable=False)
    rms = Column(Float, nullable=False)
    peak = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("GatewaySession", back_populates="axle_records")


class Alert(Base):
    """A generated threshold-violation alert (Module 3 rule engine output)."""
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alert_created", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("gateway_sessions.id"), nullable=True)
    gateway_id = Column(String(64), nullable=False)
    train_id = Column(String(64), nullable=False)
    route = Column(String(128), nullable=False)
    axle_id = Column(String(32), nullable=True)
    metric = Column(String(16), nullable=False)  # vertical | lateral
    value = Column(Float, nullable=False)
    threshold_value = Column(Float, nullable=False)
    speed_kmph = Column(Float, nullable=False)
    severity = Column(String(16), nullable=False)  # Critical | Warning | Info
    message = Column(String(255), nullable=False)
    nearest_track_feature_km = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("GatewaySession", back_populates="alerts")


class SmsNotification(Base):
    """Audit log for SMS/notification delivery attempts generated from alerts."""
    __tablename__ = "sms_notifications"
    __table_args__ = (Index("ix_sms_alert", "alert_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    gateway_id = Column(String(64), nullable=False)
    train_id = Column(String(64), nullable=False)
    recipient = Column(String(32), nullable=False)
    provider = Column(String(64), nullable=False, default="http")
    message = Column(String(320), nullable=False)
    status = Column(String(16), nullable=False)  # sent | failed | skipped
    provider_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ThresholdSetting(Base):
    """Per-route acceleration thresholds (Module 3)."""
    __tablename__ = "threshold_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route = Column(String(128), unique=True, nullable=False)
    vertical_threshold = Column(Float, nullable=False, default=50.0)
    lateral_threshold = Column(Float, nullable=False, default=80.0)
    alerts_enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Train(Base):
    """
    Train roster (clause 6.11: 'facility to add, delete and edit details of
    train in processing station shall be available').
    """
    __tablename__ = "trains"

    train_id = Column(String(64), primary_key=True)
    label = Column(String(128), nullable=True)
    default_route = Column(String(128), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RouteTrackPoint(Base):
    """
    Reference track-feature points for a route (clause 4.10: route data file
    with lat/lon provided by RDSO; clause 6.5: route file format per
    Annexure-II). Used to tag every alert with the nearest known KM marker
    (clause 6.1: 'report of safety alerts shall be stored... along with
    nearest track feature').
    """
    __tablename__ = "route_track_points"
    __table_args__ = (Index("ix_route_track_route", "route"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    route = Column(String(128), nullable=False)
    km = Column(Float, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)


class RouteSection(Base):
    """
    Railway / Division / Section reference data for section-wise reporting
    (clause 6.7: 'details of section will include Railway, Division,
    Section, From KM and To KM').
    """
    __tablename__ = "route_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route = Column(String(128), nullable=False, index=True)
    railway = Column(String(128), nullable=False)
    division = Column(String(128), nullable=False)
    section = Column(String(128), nullable=False)
    from_km = Column(Float, nullable=False)
    to_km = Column(Float, nullable=False)


class Calibration(Base):
    """
    Wheel calibration history (Module 4). Every POST appends a new row so
    the full calibration history is retained per gateway/axle.
    """
    __tablename__ = "calibration"

    id = Column(Integer, primary_key=True, autoincrement=True)
    gateway_id = Column(String(64), nullable=False, index=True)
    axle_id = Column(String(32), nullable=False)
    wheel_diameter_mm = Column(Float, nullable=False)
    wear_percent = Column(Float, nullable=False)
    correction_factor = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
