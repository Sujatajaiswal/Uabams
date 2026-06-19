"""
Data retention per clauses 6.3 and 6.4.

Clause 6.3 ("discrete data in time domain... retained for seven days...
afterwards deleted") governs raw waveform capture. This cloud system never
stores raw waveform - the gateway only ever sends processed per-axle
peak/RMS summaries (see README "Spec alignment notes") - so clause 6.3 has
no corresponding data here to purge.

Clause 6.4 ("acceleration data in space domain at the sampling interval of
25cm and generated alert reports are to be stored in intermediate server
for every run for latest 30 days from date of recording") DOES apply: the
axle_records and alerts tables are exactly that space-domain/alert data,
so this module purges anything older than the configured retention window.

In production this would run as a daily scheduled job (e.g. a Render cron
job or APScheduler). It's exposed here as an explicit, auditable endpoint
instead, since silently deleting data on a timer is a much bigger surprise
to bake into a demo than an operator-triggered action.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models


def purge_expired_data(db: Session, retention_days: int = 30):
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    expired_sessions = (
        db.query(models.GatewaySession)
        .filter(models.GatewaySession.timestamp < cutoff)
        .all()
    )
    session_ids = [s.id for s in expired_sessions]

    axle_deleted = 0
    alerts_deleted = 0
    if session_ids:
        axle_deleted = (
            db.query(models.AxleRecord)
            .filter(models.AxleRecord.session_id.in_(session_ids))
            .delete(synchronize_session=False)
        )
        alerts_deleted = (
            db.query(models.Alert)
            .filter(models.Alert.session_id.in_(session_ids))
            .delete(synchronize_session=False)
        )

    sessions_deleted = (
        db.query(models.GatewaySession)
        .filter(models.GatewaySession.timestamp < cutoff)
        .delete(synchronize_session=False)
    )

    db.commit()
    return {
        "cutoffDate": cutoff,
        "sessionsDeleted": sessions_deleted,
        "axleRecordsDeleted": axle_deleted,
        "alertsDeleted": alerts_deleted,
    }
