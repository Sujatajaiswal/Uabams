"""
Centralised application settings, read from environment variables.
Keeping this in one place makes the Render / Docker / local configurations
explicit and easy to audit.
"""
import os


class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://uabams:uabams@localhost:5432/uabams",
    )
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")
    DEFAULT_SAMPLING_RATE: int = int(os.getenv("DEFAULT_SAMPLING_RATE", "2500"))
    GATEWAY_OFFLINE_AFTER_SECONDS: int = int(
        os.getenv("GATEWAY_OFFLINE_AFTER_SECONDS", "300")
    )
    SEED_ON_STARTUP: bool = os.getenv("SEED_ON_STARTUP", "true").lower() == "true"

    # Default acceleration thresholds (g) applied when a route has no
    # explicit entry in the threshold table yet.
    DEFAULT_VERTICAL_THRESHOLD: float = 50.0
    DEFAULT_LATERAL_THRESHOLD: float = 80.0
    DEFAULT_ROUTE: str = "Bangalore-Chennai"

    # Module 3 rule: alerts only fire at or above this speed (km/h)
    ALERT_SPEED_GATE_KMPH: float = 80.0

    # Gateway/dashboard API authentication. Set AUTH_API_KEY in deployment
    # and send it as X-API-Key on every /api/v1 request.
    AUTH_API_KEY: str = os.getenv("AUTH_API_KEY", "uabams-demo-api-key")

    # SMS gateway configuration. This is provider-neutral: any company SMS
    # server that accepts JSON over HTTP can be connected by setting these.
    SMS_ENABLED: bool = os.getenv("SMS_ENABLED", "false").lower() == "true"
    SMS_PROVIDER_URL: str = os.getenv("SMS_PROVIDER_URL", "")
    SMS_API_KEY: str = os.getenv("SMS_API_KEY", "")
    SMS_FROM: str = os.getenv("SMS_FROM", "UABAMS")
    SMS_TO_NUMBERS: str = os.getenv("SMS_TO_NUMBERS", "")
    SMS_TIMEOUT_SECONDS: float = float(os.getenv("SMS_TIMEOUT_SECONDS", "10"))


settings = Settings()
