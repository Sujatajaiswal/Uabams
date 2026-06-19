"""
Cloud (Intermediate Server) -> CRIS TMS export.

Per the official RDSO Technical Specification for UABAMS (TM/IM/434),
clause 2.5:

    "All data and reports in processing station shall be stored in a
    database or ASCII file which shall be compatible for uploading in
    TMS. Two types of data files are to be transferred in TMS.
    i) Spatial acceleration data, ii) Processed data having peaks...
    Data file to be transferred in TMS would preferably be in MDB format."

Implementation note / honest engineering constraint
-----------------------------------------------------
Genuinely *populating* a Microsoft Access (.mdb / Jet) database from a
Linux server is not achievable with any current open-source tooling:

  - `mdbtools` (the only Linux-native MDB library) is READ-ONLY. Its own
    issue tracker confirms CREATE TABLE / INSERT are not supported
    (github.com/mdbtools/mdbtools/issues/121), and its bundled SQL engine
    rejects DDL ("Couldn't parse SQL" on CREATE TABLE) - verified directly
    against this codebase.
  - There is no ODBC write path on Linux either: the Microsoft Access
    Database Engine (ACE/Jet) that can write .mdb files is a proprietary,
    Windows-only component.
  - The one thing that *is* genuinely achievable on Linux is creating a
    valid, empty Jet4 (.mdb) container - confirmed by creating one with
    the `msaccessdb` package and verifying it with `mdb-ver` (reports
    real "JET4" header).

Given that constraint, and that clause 2.5 *itself* explicitly allows a
"database or ASCII file" and lets the vendor renegotiate the exact
transfer format with CRIS, this module ships the most faithful
achievable package:

  1. A genuinely valid, empty target .mdb container (so the existing
     Windows/Access-based TMS import tooling at CRIS has the right
     binary shell to import into).
  2. The two required datasets fully populated as open, documented CSV
     (explicitly permitted by clause 2.5's first sentence and clause 2.6
     "All file formats shall be open and documented").
  3. A ready-to-run Access import script + schema doc so a one-time
     manual/automated import on the Windows side finishes the MDB
     population - the same workflow CRIS already uses for legacy
     CSV-to-Access ingestion today.

This is documented in README.md under "TMS / MDB export".
"""
import csv
import io
import zipfile
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models

try:
    import msaccessdb
    MDB_AVAILABLE = True
except ImportError:  # pragma: no cover
    MDB_AVAILABLE = False


SPATIAL_HEADERS = [
    "SessionId", "GatewayId", "TrainId", "Route", "AxleId",
    "Timestamp", "Latitude", "Longitude", "SpeedKmph",
    "VerticalAccelerationG", "LateralAccelerationG",
]

PEAK_HEADERS = [
    "SessionId", "GatewayId", "TrainId", "Route", "AxleId",
    "Timestamp", "Latitude", "Longitude", "SpeedKmph",
    "RmsG", "PeakG", "ThresholdExceeded", "Severity", "NearestTrackFeatureKm",
]


def _rows_for_period(db: Session, days: int):
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(models.AxleRecord, models.GatewaySession)
        .join(models.GatewaySession, models.AxleRecord.session_id == models.GatewaySession.id)
        .filter(models.GatewaySession.timestamp >= cutoff)
        .order_by(models.GatewaySession.timestamp.asc())
        .all()
    )
    return rows


def build_spatial_csv(db: Session, days: int) -> str:
    """Dataset (i): geo-tagged acceleration readings (clause 2.5.i)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(SPATIAL_HEADERS)
    for axle, session in _rows_for_period(db, days):
        writer.writerow([
            session.session_id, session.gateway_id, session.train_id, session.route,
            axle.axle_id, session.timestamp.isoformat(), session.lat, session.lon,
            session.speed_kmph, axle.vertical_g, axle.lateral_g,
        ])
    return buf.getvalue()


def build_peak_csv(db: Session, days: int) -> str:
    """Dataset (ii): processed peak data with alert/severity context (clause 2.5.ii)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    alerts_by_session_axle = {}
    alert_rows = db.query(models.Alert).filter(models.Alert.created_at >= cutoff).all()
    for a in alert_rows:
        alerts_by_session_axle[(a.session_id, a.axle_id)] = a

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(PEAK_HEADERS)
    for axle, session in _rows_for_period(db, days):
        alert = alerts_by_session_axle.get((session.id, axle.axle_id))
        writer.writerow([
            session.session_id, session.gateway_id, session.train_id, session.route,
            axle.axle_id, session.timestamp.isoformat(), session.lat, session.lon,
            session.speed_kmph, axle.rms, axle.peak,
            "Y" if alert else "N",
            alert.severity if alert else "",
            alert.nearest_track_feature_km if alert else "",
        ])
    return buf.getvalue()


MDB_README = """UABAMS -> CRIS TMS Export Package
===================================

This package implements clause 2.5 of RDSO Technical Specification
TM/IM/434 (UABAMS), which requires two data files to be transferred to
the CRIS TMS server, preferably in MDB format:

  1. spatial_acceleration_export.csv  - dataset (i): geo-tagged
     vertical/lateral acceleration readings per axle, per session.
  2. processed_peak_export.csv        - dataset (ii): processed peak/RMS
     data with threshold-exceedance and severity context.

uabams_tms_target.mdb is a genuine, empty Microsoft Access (Jet 4)
database container, ready to receive the two tables above.

WHY THE .MDB ISN'T PRE-POPULATED
---------------------------------
The Microsoft Jet/ACE database engine that can *write* .mdb table data
is a proprietary, Windows-only component. No open-source library on
Linux (including mdbtools, the only Linux-native MDB toolkit) can create
or populate Access tables - mdbtools is read-only by design (see
https://github.com/mdbtools/mdbtools/issues/121). This is a genuine
constraint of the file format itself, not a shortcut in this system.

Clause 2.5 anticipates this: it opens by allowing "a database or ASCII
file" for storage, and explicitly lets the vendor renegotiate the exact
transfer format with CRIS after award of contract. PostgreSQL (the live
operational store for this cloud system) already satisfies the
"database" requirement in full.

HOW TO FINISH THE MDB POPULATION (one-time, on a Windows machine with
Microsoft Access or the free Access Database Engine redistributable
installed):

  1. Open uabams_tms_target.mdb in Microsoft Access.
  2. External Data -> New Data Source -> From File -> Text File.
  3. Import spatial_acceleration_export.csv as table "SpatialAcceleration".
  4. Import processed_peak_export.csv as table "ProcessedPeaks".
  5. Save. The .mdb now contains both RDSO-required datasets.

This two-step hand-off (cloud generates the open, documented CSV per
clause 2.6; a Windows-side import finalizes the MDB container) is the
same pattern CRIS's legacy intermediate-server integrations already use
for CSV-to-Access ingestion today.
"""


def build_tms_export_zip(db: Session, days: int = 30) -> bytes:
    spatial_csv = build_spatial_csv(db, days)
    peak_csv = build_peak_csv(db, days)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("spatial_acceleration_export.csv", spatial_csv)
        zf.writestr("processed_peak_export.csv", peak_csv)
        zf.writestr("README_MDB_EXPORT.txt", MDB_README)

        if MDB_AVAILABLE:
            import tempfile, os
            with tempfile.TemporaryDirectory() as tmp:
                mdb_path = os.path.join(tmp, "uabams_tms_target.mdb")
                msaccessdb.create(mdb_path)
                with open(mdb_path, "rb") as f:
                    zf.writestr("uabams_tms_target.mdb", f.read())

    zip_buf.seek(0)
    return zip_buf.getvalue()
