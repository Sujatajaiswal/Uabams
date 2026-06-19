"""
UABAMS Gateway Simulator
=========================
Stands in for the real on-train gateway hardware in the architecture
diagram:

    Train Sensors -> Gateway -> Upload ZIP/JSON -> Cloud Receive -> ...

Run it against a live backend to generate a continuous stream of session
uploads, the same way a real gateway would on a retry/upload cycle. Useful
for demoing the dashboard with live-looking data instead of only the
static seed data.

Usage:
    python gateway_simulator.py --url http://localhost:8000 --interval 5
    python gateway_simulator.py --url https://your-app.onrender.com --once
"""
import argparse
import json
import os
import random
import time
import zipfile
import io
from datetime import datetime, timezone

import httpx

GATEWAYS = ["GW001", "GW002", "GW003", "GW004"]
TRAINS = ["TRAIN07", "TRAIN12", "TRAIN21", "TRAIN34"]
ROUTES = {
    "Bangalore-Chennai": {"lat": (12.9, 13.1), "lon": (77.5, 80.2)},
    "Chennai-Coimbatore": {"lat": (11.0, 13.1), "lon": (76.9, 80.2)},
    "Mumbai-Pune": {"lat": (18.5, 19.1), "lon": (73.4, 73.9)},
}
AXLES = ["AX01", "AX02", "AX03", "AX04"]


def build_payload(spike: bool = False) -> dict:
    route = random.choice(list(ROUTES.keys()))
    bounds = ROUTES[route]
    speed = round(random.uniform(60, 130), 1)

    axle_data = []
    for axle_id in random.sample(AXLES, k=random.randint(1, 3)):
        vertical = random.uniform(10, 35) if not spike else random.uniform(55, 90)
        lateral = random.uniform(5, 30) if not spike else random.uniform(85, 95)
        peak = min(max(vertical, lateral) * random.uniform(1.05, 1.25), 99.9)
        axle_data.append({
            "axleId": axle_id,
            "verticalG": round(vertical, 2),
            "lateralG": round(lateral, 2),
            "rms": round(vertical * random.uniform(0.5, 0.7), 2),
            "peak": round(peak, 2),
        })

    return {
        "gatewayId": random.choice(GATEWAYS),
        "trainId": random.choice(TRAINS),
        "sessionId": f"SIM-{int(time.time() * 1000)}-{random.randint(100, 999)}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "route": route,
        "gps": {
            "lat": round(random.uniform(*bounds["lat"]), 4),
            "lon": round(random.uniform(*bounds["lon"]), 4),
        },
        "speedKmph": speed,
        "axleData": axle_data,
    }


def auth_headers(api_key: str) -> dict:
    return {"X-API-Key": api_key} if api_key else {}


def send_json(base_url: str, payload: dict, api_key: str) -> None:
    resp = httpx.put(
        f"{base_url}/api/v1/archive",
        json=payload,
        headers=auth_headers(api_key),
        timeout=10,
    )
    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"{payload['gatewayId']} / {payload['trainId']} -> {resp.status_code} {resp.text}")


def send_zip(base_url: str, payload: dict, api_key: str) -> None:
    """Demonstrates the ZIP upload path described in Module 2."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("session.json", json.dumps(payload))
    buf.seek(0)
    resp = httpx.put(
        f"{base_url}/api/v1/archive",
        content=buf.read(),
        headers={"Content-Type": "application/zip", **auth_headers(api_key)},
        timeout=10,
    )
    print(f"[{datetime.now().strftime('%H:%M:%S')}] (ZIP) "
          f"{payload['gatewayId']} / {payload['trainId']} -> {resp.status_code} {resp.text}")


def main():
    parser = argparse.ArgumentParser(description="UABAMS gateway simulator")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend base URL")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between uploads")
    parser.add_argument("--once", action="store_true", help="Send a single upload and exit")
    parser.add_argument("--zip", action="store_true", help="Send as ZIP instead of raw JSON")
    parser.add_argument(
        "--api-key",
        default=os.getenv("AUTH_API_KEY", "uabams-demo-api-key"),
        help="API key sent in X-API-Key header",
    )
    parser.add_argument(
        "--spike-rate", type=float, default=0.2,
        help="Probability (0-1) that a given upload simulates a threshold-exceeding reading",
    )
    args = parser.parse_args()

    print(f"UABAMS Gateway Simulator -> {args.url}")
    while True:
        payload = build_payload(spike=random.random() < args.spike_rate)
        try:
            if args.zip:
                send_zip(args.url, payload, args.api_key)
            else:
                send_json(args.url, payload, args.api_key)
        except httpx.HTTPError as exc:
            print(f"Upload failed, will retry per Module 6 policy: {exc}")

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
