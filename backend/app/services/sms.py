from __future__ import annotations

from typing import Iterable, List

import httpx
from sqlalchemy.orm import Session

from app import models
from app.config import settings


def configured_recipients() -> List[str]:
    return [
        number.strip()
        for number in settings.SMS_TO_NUMBERS.split(",")
        if number.strip()
    ]


def build_sms_message(alert: models.Alert) -> str:
    session = alert.session
    location = ""
    if session is not None:
        location = f" GPS {session.lat:.6f},{session.lon:.6f}"
    return (
        f"UABAMS {alert.severity}: {alert.metric} alert on {alert.train_id} "
        f"({alert.route}) {alert.value:.2f}g > {alert.threshold_value:.2f}g "
        f"at {alert.speed_kmph:.1f} kmph.{location}"
    )[:320]


def dispatch_sms_for_alerts(
    db: Session,
    alerts: Iterable[models.Alert],
) -> List[models.SmsNotification]:
    """Send/log SMS notifications for generated alerts.

    The actual SMS server is configured with SMS_PROVIDER_URL. If SMS is not
    enabled or no recipient is configured, the attempt is logged as skipped so
    operators can still prove the alert notification path was evaluated.
    """
    recipients = configured_recipients()
    logs: List[models.SmsNotification] = []

    for alert in alerts:
        message = build_sms_message(alert)
        target_numbers = recipients or ["NOT_CONFIGURED"]
        for recipient in target_numbers:
            status = "skipped"
            provider_response = "SMS disabled or SMS_TO_NUMBERS not configured"

            if settings.SMS_ENABLED and settings.SMS_PROVIDER_URL and recipients:
                payload = {
                    "to": recipient,
                    "from": settings.SMS_FROM,
                    "message": message,
                    "alertId": alert.id,
                    "gatewayId": alert.gateway_id,
                    "trainId": alert.train_id,
                }
                headers = {"Content-Type": "application/json"}
                if settings.SMS_API_KEY:
                    headers["Authorization"] = f"Bearer {settings.SMS_API_KEY}"
                try:
                    response = httpx.post(
                        settings.SMS_PROVIDER_URL,
                        json=payload,
                        headers=headers,
                        timeout=settings.SMS_TIMEOUT_SECONDS,
                    )
                    provider_response = response.text[:1000]
                    status = "sent" if response.status_code < 400 else "failed"
                except Exception as exc:  # pragma: no cover - provider/network dependent
                    provider_response = str(exc)
                    status = "failed"

            log = models.SmsNotification(
                alert_id=alert.id,
                gateway_id=alert.gateway_id,
                train_id=alert.train_id,
                recipient=recipient,
                provider="http",
                message=message,
                status=status,
                provider_response=provider_response,
            )
            db.add(log)
            logs.append(log)

    return logs
