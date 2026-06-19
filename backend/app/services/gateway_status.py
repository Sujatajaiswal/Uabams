from datetime import datetime, timedelta

from app import models
from app.config import settings


def live_status(gw: models.Gateway) -> str:
    """Returns 'online' if the gateway has uploaded within the configured
    freshness window, else 'offline'."""
    if not gw.last_seen_at:
        return "offline"
    cutoff = datetime.utcnow() - timedelta(seconds=settings.GATEWAY_OFFLINE_AFTER_SECONDS)
    return "online" if gw.last_seen_at >= cutoff else "offline"
