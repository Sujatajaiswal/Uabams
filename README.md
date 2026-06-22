# UABAMS Cloud — Unattended Axle Box Acceleration Measurement System

A production-style cloud reference implementation for Indian Railways' UABAMS,
covering gateway ingestion, validation, processing, alerting, a monitoring
dashboard, and config sync back to the gateway — built to demonstrate the
**cloud-side** half of the system end to end.

This implementation follows both the architecture brief given for this demo
and the official RDSO Technical Specification **TM/IM/434** ("Unattended
Axle Box Level Acceleration Measurement System"). Where the two differ, the
divergence and rationale are called out explicitly below (see *Spec
alignment notes*).

```
Train Sensors -> Gateway -> Upload ZIP/JSON -> Cloud Receive -> Validation
   -> Processing -> Database -> Alerts -> Dashboard -> Config Sync to Gateway
   -> (periodic) TMS Export to CRIS, per RDSO clause 2.5
```

## Tech stack

- **Frontend:** React + TypeScript, Tailwind CSS, Recharts
- **Backend:** FastAPI (Python), SQLAlchemy, PostgreSQL
- **Deployment:** Docker / docker-compose locally; Render (web service +
  managed Postgres + static site) for a one-click cloud demo

## Folder structure

```
uabams-cloud/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI app, router wiring, startup seed
│   │   ├── config.py            Centralised settings (env vars)
│   │   ├── database.py          SQLAlchemy engine/session
│   │   ├── models.py            ORM schema (Module 5 tables)
│   │   ├── schemas.py           Pydantic request/response models
│   │   ├── seed.py               Demo data seeding
│   │   ├── routers/
│   │   │   ├── archive.py        Module 2 — PUT/POST /api/v1/archive
│   │   │   ├── dashboard.py      Module 1 — GET /api/v1/dashboard
│   │   │   ├── threshold.py      Module 3 — /api/v1/threshold
│   │   │   ├── calibration.py    Module 4 — /api/v1/calibration
│   │   │   ├── alerts.py         GET /api/v1/alerts
│   │   │   ├── config.py         Module 6 — GET /api/v1/config
│   │   │   ├── gateways.py       GET /api/v1/gateways
│   │   │   └── tms_export.py     GET /api/v1/export/tms (RDSO clause 2.5)
│   │   └── services/
│   │       ├── validation.py     Field/GPS/threshold/duplicate validation
│   │       ├── alerts.py         Threshold rule engine + severity grading
│   │       ├── gateway_status.py Online/offline heartbeat logic
│   │       └── tms_export.py     CRIS TMS export package builder
│   ├── scripts/
│   │   └── gateway_simulator.py  Standalone "Gateway" simulator (continuous upload feed)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/                5 screens (Dashboard, Gateway Upload, Threshold, Calibration, Alerts)
│   │   ├── components/           Layout, Sidebar, Topbar, StatCard, SeverityBadge, StatusPill
│   │   ├── api/client.ts         Typed API client
│   │   └── types/index.ts        Shared TS types mirroring backend schemas
│   ├── package.json
│   ├── Dockerfile
│   ├── nginx.conf
│   └── .env.example
├── docker-compose.yml
├── render.yaml
└── README.md
```

## Running locally with Docker

```bash
git clone <this-repo> uabams-cloud && cd uabams-cloud
docker compose up --build
```

- Backend API + docs: http://localhost:8000/docs
- Frontend dashboard: http://localhost:5173
- Postgres: localhost:5432 (`uabams` / `uabams`)

The backend seeds ~7 days of realistic demo data (gateways, sessions, axle
readings, alerts, thresholds, calibration history) on first startup
(`SEED_ON_STARTUP=true`), so the dashboard is populated immediately.

To see a continuous live feed instead of static seed data, run the gateway
simulator against the running backend:

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python scripts/gateway_simulator.py --url http://localhost:8000 --interval 5
```

## Running without Docker

**Backend**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit DATABASE_URL to point at your Postgres instance
uvicorn app.main:app --reload
```

**Frontend**
```bash
cd frontend
cp .env.example .env   # set VITE_API_BASE_URL
npm install
npm run dev
```

## Deploying to Render (Option 1 from the architecture brief)

1. Push this repo to GitHub.
2. In Render: **New +** → **Blueprint** → point it at the repo. `render.yaml`
   provisions a managed Postgres database, the FastAPI backend as a Docker
   web service, and the React app as a static site automatically.
3. Once the backend is live, update the frontend's `VITE_API_BASE_URL` env
   var (in `render.yaml` or the Render dashboard) to the backend's public
   `.onrender.com` URL and redeploy the static site.

This gives a public HTTPS URL for both the API and dashboard with no server
management, matching the "Option 1: Render + PostgreSQL" architecture in
the brief.

## Module mapping

| Module | What it covers | Where |
|---|---|---|
| 1 — Dashboard | Overview cards, RMS/Peak/Heatmap/Violations charts, GPS map, sessions table | `frontend/src/pages/DashboardPage.tsx`, `backend/app/routers/dashboard.py` |
| 2 — Gateway ingestion | `PUT`/`POST /api/v1/archive`, ZIP or JSON, full validation | `backend/app/routers/archive.py`, `services/validation.py` |
| 3 — Threshold settings | Per-route vertical/lateral thresholds, alert toggle, rule engine | `frontend/src/pages/ThresholdSettingsPage.tsx`, `backend/app/services/alerts.py` |
| 4 — Calibration | Wheel wear / diameter / correction factor, append-only history | `frontend/src/pages/CalibrationPage.tsx`, `backend/app/routers/calibration.py` |
| 5 — Cloud processing | Receive → Validate → Extract → Parse → Store → Alert pipeline | `backend/app/routers/archive.py` (orchestrates all of the above per request) |
| 6 — Cloud → Gateway config sync | `GET /api/v1/config` (threshold, wear%, sampling rate) | `backend/app/routers/config.py` |
| 7 — UI design | Industrial railway monitoring theme (navy/blue/white/steel-gray, Oswald/Inter/IBM Plex Mono) | `frontend/tailwind.config.js`, `frontend/src/index.css` |

## API reference

All `/api/v1/*` endpoints require API-key authentication:

```bash
X-API-Key: <AUTH_API_KEY>
```

The key is configured on the backend with `AUTH_API_KEY`. The React
frontend sends the same value through `VITE_API_KEY`. Health checks
(`/health` and `/`) remain public for deployment monitoring.

| Method | Path | Purpose |
|---|---|---|
| `PUT`/`POST` | `/api/v1/archive` | Upload a session archive (ZIP or JSON body). Accepts both the full Module 2 payload (`axleData[]`) and the flat "simple demo" payload (`speed`/`peak`). |
| `GET` | `/api/v1/dashboard` | All Module 1 dashboard data in one call. |
| `GET`/`POST` | `/api/v1/threshold` | List / upsert per-route thresholds. |
| `GET`/`POST` | `/api/v1/calibration` | List / append calibration history. |
| `GET` | `/api/v1/alerts` | List alerts, optional `severity`/`route` filters. |
| `GET` | `/api/v1/config` | Gateway config sync (threshold, wearPercent, samplingRate). |
| `GET` | `/api/v1/gateways` | Gateway online/offline status. |
| `GET` | `/api/v1/export/tms` | CRIS TMS export package (see below). |
| `GET`/`POST`/`DELETE` | `/api/v1/trains` | Train roster — add/edit/delete (clause 6.11). |
| `GET`/`POST` | `/api/v1/route-files` | Load/list RDSO route reference points for nearest-track-feature lookups (clauses 4.10, 6.5). |
| `GET`/`POST` | `/api/v1/sections` | Railway/Division/Section reference data for section-wise reporting (clause 6.7). |
| `POST` | `/api/v1/maintenance/purge` | Purge data past the retention window (clause 6.4). |
| `GET` | `/api/v1/sms-notifications` | SMS/notification delivery audit log for generated alerts. |

Full interactive docs (OpenAPI/Swagger) are always available at `/docs` on
the running backend.

### Example upload (simple demo payload)

```bash
curl -X POST http://localhost:8000/api/v1/archive \
  -H "X-API-Key: uabams-demo-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "gatewayId": "GW001",
    "trainId": "TRAIN07",
    "speed": 95,
    "peak": 72,
    "gps": { "lat": 12.97, "lon": 77.59 }
  }'
```

### Example upload (full Module 2 payload)

```bash
curl -X PUT http://localhost:8000/api/v1/archive \
  -H "X-API-Key: uabams-demo-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "gatewayId": "GW001",
    "trainId": "TRAIN07",
    "sessionId": "S001",
    "timestamp": "2026-06-16T09:00:00Z",
    "gps": { "lat": 12.9716, "lon": 77.5946 },
    "speedKmph": 95,
    "axleData": [
      { "axleId": "AX01", "verticalG": 12.5, "lateralG": 6.2, "rms": 4.8, "peak": 18 }
    ]
  }'
```

## Validation rules (Module 2)

- **Missing fields** → `422` with field-level detail (Pydantic).
- **Invalid GPS** → latitude outside ±90° or longitude outside ±180° → `400`.
- **Invalid threshold (g-range)** → any vertical/lateral/RMS/peak reading
  outside 0–100g → `400`.
- **Duplicate session** → same `(gatewayId, sessionId)` already stored →
  `409`.

## Alert rule engine (Module 3)

```
IF speedKmph >= 80 AND axle.verticalG > route.verticalThreshold:
    raise alert(metric="vertical", ...)
IF speedKmph >= 80 AND axle.lateralG > route.lateralThreshold:
    raise alert(metric="lateral", ...)
```

Severity is graded by how far the reading exceeds the threshold:
**Critical** ≥ 50% over, **Warning** ≥ 20% over, **Info** for anything else
above the limit. Vertical and lateral are evaluated independently per axle,
so a single reading can raise zero, one, or two alerts.

## Authentication and SMS notification server

Authentication is implemented with a shared API key because the gateway and
cloud communicate server-to-server. The gateway, dashboard, and scripts send
the configured key in the `X-API-Key` header. In production, replace the demo
key in Render with a secret value and distribute it only to approved gateway
devices and dashboard users.

SMS alerting is implemented as a provider-neutral HTTP SMS gateway. When an
alert is generated, the backend creates an entry in `sms_notifications` and,
if SMS is enabled, sends a JSON request to the configured SMS server.

| Environment variable | Purpose |
|---|---|
| `AUTH_API_KEY` | Required API key for `/api/v1/*` requests. |
| `VITE_API_KEY` | Frontend copy of the API key used by the dashboard. |
| `SMS_ENABLED` | Set to `true` to send SMS; `false` logs skipped attempts. |
| `SMS_PROVIDER_URL` | Company/SMS-provider HTTP endpoint. |
| `SMS_API_KEY` | Optional bearer token for the SMS provider. |
| `SMS_FROM` | Sender label, default `UABAMS`. |
| `SMS_TO_NUMBERS` | Comma-separated recipient mobile numbers. |

Expected SMS provider payload:

```json
{
  "to": "+91XXXXXXXXXX",
  "from": "UABAMS",
  "message": "UABAMS Critical: vertical alert...",
  "alertId": 101,
  "gatewayId": "GW001",
  "trainId": "TRAIN07"
}
```

The SMS log can be reviewed using `GET /api/v1/sms-notifications`.

## Database schema (Module 5)

| Table | Purpose |
|---|---|
| `gateways` | One row per edge gateway; online/offline heartbeat. |
| `gateway_sessions` | One row per uploaded archive (session). |
| `axle_records` | One row per axle reading per session — see note below. |
| `alerts` | One row per generated alert. |
| `threshold_settings` | One row per route (vertical/lateral limits, alerts on/off). |
| `calibration` | Append-only wheel wear/diameter/correction-factor history. |
| `trains` | Train roster — add/edit/delete (clause 6.11). |
| `route_track_points` | RDSO route reference points (lat/lon per KM marker) used for nearest-track-feature lookups (clauses 4.10, 6.5). |
| `route_sections` | Railway/Division/Section/From KM/To KM reference data for section-wise reporting (clause 6.7). |
| `sms_notifications` | SMS/notification delivery audit log for each generated alert. |

**Design note:** the spec lists `rms_records` and `peak_records` as
separate tables. They're normalised here into a single `axle_records`
table, since every incoming axle reading always carries RMS and peak
together — splitting them would only force a join to reconstruct one
sensor reading, with no benefit. The RMS Trend and Peak Acceleration
dashboard charts are simply two projections of this same table.

## TMS / MDB export (RDSO clause 2.5)

The official RDSO spec (TM/IM/434, clause 2.5) requires two datasets to be
handed off from the intermediate processing station to CRIS's TMS server —
**spatial acceleration data** and **processed peak data** — "preferably"
in MDB (Microsoft Access) format, while explicitly allowing "a database or
ASCII file" and letting the vendor renegotiate the format with CRIS.

`GET /api/v1/export/tms?days=30` builds that hand-off package as a ZIP:

- `spatial_acceleration_export.csv` — dataset (i)
- `processed_peak_export.csv` — dataset (ii)
- `uabams_tms_target.mdb` — a genuine, valid empty Jet4 Access database container
- `README_MDB_EXPORT.txt` — the two-step finish (Access import) and full rationale

**Why the .mdb isn't pre-populated:** writing table data into a Microsoft
Access (.mdb/Jet) file requires Microsoft's proprietary ACE/Jet engine,
which is Windows-only. This was verified directly against this codebase:
`mdbtools` (the only Linux-native MDB library) is read-only — its own
issue tracker confirms `CREATE TABLE`/`INSERT` aren't supported
([mdbtools/mdbtools#121](https://github.com/mdbtools/mdbtools/issues/121)),
and its SQL engine rejects DDL outright. What *is* achievable on Linux —
and is what this endpoint does — is generating a real, valid empty Jet4
container (verified with `mdb-ver`) plus the two datasets as open,
documented CSV (explicitly permitted by clause 2.5's first sentence and
clause 2.6, "all file formats shall be open and documented"). The bundled
README explains the one-time Windows-side Access import that finishes the
MDB population — the same CSV-to-Access workflow legacy intermediate-server
integrations already use today.

This is a deliberate, documented engineering trade-off rather than a
shortcut — see `backend/app/services/tms_export.py` for the full writeup
and the verification steps taken.

## Route/track-feature matching, sections, retention & train roster (clauses 4.10, 6.1, 6.4, 6.7, 6.11)

Several clauses describe intermediate-server software behaviour beyond the
original 7-module brief, and are implemented here:

- **Nearest track feature (clauses 4.10, 6.1).** RDSO's Annexure-II shows
  the real route-file format: KM-marker rows, many carrying lat/lon. The
  `route_track_points` table stores exactly that, and every alert is
  tagged with the nearest KM marker on its route via a haversine
  nearest-neighbour lookup (`services/route_matching.py`), satisfying
  clause 6.1's "report of safety alerts shall be stored... along with
  nearest track feature." The seed data includes synthesised km-posts for
  the 3 operational demo routes, **plus a genuine 12-point slice of the
  actual "Lucknow-Kanpur" Annexure-II sample from the spec**, with its
  DD°MM'SS.ssss" coordinates converted to decimal degrees, loaded as its
  own reference route purely to demonstrate the real format round-trips
  correctly through `POST /api/v1/route-files`.
- **Section-wise reporting (clause 6.7).** `route_sections` stores
  Railway/Division/Section/From KM/To KM reference rows per route, seeded
  with the real zonal railway and division names for each demo route.
- **Data retention (clause 6.4).** `POST /api/v1/maintenance/purge` deletes
  axle records, alerts, and sessions older than a configurable window
  (30 days by default, matching the clause). Clause 6.3's 7-day raw
  time-domain retention doesn't apply here — this cloud system never
  stores raw waveform in the first place (see below).
- **Train roster (clause 6.11).** `GET`/`POST`/`DELETE /api/v1/trains`
  gives the "add, delete and edit details of train in processing station"
  facility the clause calls for.

## Spec alignment notes

The RDSO spec (TM/IM/434) covers the entire UABAMS system — physical
sensors, edge hardware, the GSM/GPS link, the intermediate processing
station, and contractual terms. This project implements the **cloud /
intermediate-server software** half. Clause by clause:

- **Gateway → Cloud upload format.** The architecture brief for this demo
  specifies ZIP/JSON for the gateway→cloud hop, which is what's
  implemented (`PUT/POST /api/v1/archive`). RDSO's clause 2.5 (MDB) governs
  the *separate* hop downstream — intermediate server → CRIS TMS — which is
  the `/api/v1/export/tms` endpoint described above. These are two
  different legs of the pipeline and aren't in conflict.
- **Clause 3 (Environmental Conditions) and 4.2–4.9 (sensor/junction-box
  mounting, power backup, GSM/GPS antenna placement).** These describe the
  physical accelerometer, data logger, and junction box hardware bolted to
  a bogie/coach — operating temperature range, humidity, vibration from
  25kV traction current, tamper-proof mounting, battery backup, etc. None
  of this has a cloud-software analogue; it's implemented entirely in the
  edge gateway hardware this project receives data *from*.
- **Clause 4.1 / 5.1 / 5.2 (speed band, sensor range, sampling rate).** The
  full system measures in the 20–160 km/h band, samples at ≥2500 Hz at
  axle level, and uses accelerometers rated to ±100g. This cloud demo
  receives already-summarised per-axle peak/RMS values from the gateway
  (matching the Module 2 example payload), not raw waveform — raw
  time-domain capture at 25 cm spatial intervals happens at the edge
  gateway, which is out of scope for a cloud-side dashboard demo. This is
  also why clause 6.3's 7-day raw-data retention rule has nothing to purge
  here (see the retention section above).
- **Clause 4.3 (alert speed gate / SMS dedup).** The ≥80 km/h gate is
  implemented exactly in the rule engine. The "one SMS per 50m for the
  highest peak" dedup rule is a concern for whichever SMS/notification
  channel ultimately consumes alerts; this demo's alert table records
  every qualifying exceedance (each tagged with its nearest track feature
  and instantaneous speed, per clause 6.1) so a downstream notification
  layer has everything it needs to apply that dedup rule.
- **Clause 5.3–5.5 (peak-location GPS accuracy, least-count, speed
  accuracy).** These are sensor/encoder hardware accuracy specs (≤5m GPS
  accuracy, ≤0.1g least count, ≤2% speed error) — properties of the
  physical measurement chain, not something cloud software can satisfy or
  violate; the cloud layer just stores whatever values it's sent.
- **Clause 6.1, 6.4, 6.7, 6.11.** Implemented — see the section above.
- **Clause 6.2 (scale: up to 100 train systems, 30,000–40,000 km/month
  each).** Nothing in this architecture caps concurrent gateways; Postgres
  and FastAPI both scale well past this volume on a single small instance,
  and Render/any container host can scale the backend horizontally if
  needed.
- **Clause 6.6 (store/process/forward to CRIS).** This is the
  receive→validate→process→store→alert pipeline already implemented
  end-to-end in `routers/archive.py`.
- **Clause 6.9 (GSM 5G/4G/3G fallback, M2M SIM/private APN, encrypted
  transfer).** Network/radio-layer concerns for the gateway's cellular
  uplink, not applicable to a cloud HTTP API. The one analogous item that
  *is* this project's responsibility — encrypting data in transit — is
  satisfied by deploying the API behind HTTPS (Render terminates TLS
  automatically; for self-hosted Docker deployments, put it behind any
  reverse proxy with a TLS certificate).
- **Clause 6.10 (0% data loss in transfer).** Addressed by the duplicate-
  session check (`409` on retry of an already-stored `gatewayId` +
  `sessionId`) — a gateway can safely retry an upload after a dropped
  connection without double-counting data.
- **Clauses 7–10 (maintenance/calibration *of physical equipment* in the
  field, warranty, downtime penalties, lab/field acceptance tests like
  vibration/shock/EMC).** These are hardware servicing, contractual, and
  lab-certification clauses for the deployed sensor units and the firm's
  obligations under the tender — there's no cloud-software equivalent.
  (Note: this project's own Module 4 "Calibration" is a different,
  software-side concept — recording wheel wear/diameter/correction-factor
  history per axle — not the clause 7 dynamic accelerometer recalibration,
  which happens at an accredited lab on physical hardware.)

## Design tokens (Module 7)

Industrial railway monitoring theme: deep navy (`#0B2440`) sidebar/panels,
signal blue (`#1B5FAE`) primary actions, steel gray text/borders, off-white
fog background. Headings use Oswald (condensed, signage-like), body text
Inter, and all numeric/ID readouts (gateway IDs, g-values, timestamps) use
IBM Plex Mono for an instrumentation feel. A small LED-style "status rail"
in the topbar shows live gateway health, SCADA-panel style.

## What's deliberately out of scope for this demo

- Real SMS/notification delivery (clause 6.1) — the alert pipeline stops at
  storing + surfacing alerts in the dashboard/API; wiring an SMS gateway
  (Twilio, AWS SNS, or an Indian Railways-approved provider) is a drop-in
  addition to `services/alerts.py`.
- Authentication/RBAC for the dashboard and Bearer-token auth for the
  gateway↔cloud hop (Module 6 mentions Bearer tokens) — both are
  straightforward additions (FastAPI's `OAuth2PasswordBearer` /
  `HTTPBearer`) but were left out to keep the demo's surface area focused.
- Tile-based GPS map (Leaflet/Google Maps) — the dashboard currently plots
  GPS points on a lat/lon scatter chart to avoid an external map-tile
  dependency in a sandboxed demo; swapping in `react-leaflet` is a
  contained change to `DashboardPage.tsx`.

## Current security and SMS status

API-key authentication is now implemented for `/api/v1/*` using the
`X-API-Key` header. The backend key is configured with `AUTH_API_KEY`, and
the frontend sends `VITE_API_KEY`.

SMS-server integration is now implemented as a configurable HTTP provider.
When alerts are generated, the cloud creates `sms_notifications` audit rows.
If `SMS_ENABLED=true` and `SMS_PROVIDER_URL` is configured, the backend sends
the SMS JSON payload to that provider. If SMS is not configured, the attempt
is stored as `skipped` so the notification path remains auditable.
## MongoDB Atlas mirror storage

PostgreSQL remains the main processing database for thresholds, calibration, reports, alerts, and TMS export. For cloud-storage visibility, the backend can also mirror every gateway archive upload into MongoDB Atlas when `MONGODB_URL` is configured.

Backend environment variables:

```text
MONGODB_URL=mongodb+srv://<user>:<password>@<cluster>/uabams_cloud?retryWrites=true&w=majority
MONGODB_DB_NAME=uabams_cloud
```

Collections written for demo:

- `gateway_archives` - full received upload summary with raw payload, parsed axle records, alerts, and SMS logs.
- `raw_gateway_payloads` - raw gateway JSON/archive payload copy.
- `alert_notifications` - generated alert documents.
- `sms_logs` - SMS notification audit logs, including demo `skipped` status when no provider is connected.

Protected API to show MongoDB storage status:

```powershell
curl -H "X-API-Key: uabams-demo-api-key" https://<backend-url>/api/v1/mongodb-storage
```

