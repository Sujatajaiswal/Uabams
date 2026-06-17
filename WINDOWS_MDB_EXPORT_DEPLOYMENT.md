# UABAMS Windows MDB Export Deployment

This document explains how to run the UABAMS cloud backend in a Windows environment when actual Microsoft Access `.mdb` generation is required.

## Why Windows Is Required

The UABAMS Render deployment is suitable for the cloud prototype:

- receiving gateway ZIP archives
- storing parsed data in PostgreSQL
- showing dashboards, alerts, GPS map, and reports
- exporting ASCII/TMS handoff packages

Actual `.mdb` generation requires Microsoft Access database drivers such as Jet/ACE/OLEDB. These are Windows components, so the MDB export should run on a Windows VM or Windows server.

## Recommended Architecture

Use this architecture for final MDB work:

```text
Gateway
  |
  | HTTPS PUT /api/v1/archive
  v
Render / Cloud API
  |
  v
PostgreSQL database
  |
  v
Windows MDB Export Service
  |
  v
Actual .mdb file
  |
  v
CRIS / TMS handoff
```

Render can continue to receive and process data. The Windows VM only needs to read the processed PostgreSQL records and generate the actual MDB file.

## Windows VM Requirements

Install these on the Windows VM:

- Windows Server 2019 or 2022
- Python 3.11 or 3.12
- Git
- Microsoft Access Database Engine Redistributable
- Project dependencies from `requirements-render.txt`
- Windows-only dependency from `requirements-windows-mdb.txt`

## Deployment Steps

### 1. Create Windows VM

Create a Windows Server VM in Azure, AWS, or Google Cloud. Azure Windows VM is easiest to explain because MDB is Microsoft Access-based.

### 2. Install Python And Git

Install Python and Git on the Windows VM.

### 3. Install Microsoft Access Database Engine

Install Microsoft Access Database Engine Redistributable so the server has the Access OLEDB/ODBC driver required for `.mdb` creation.

### 4. Clone Project

```powershell
git clone https://github.com/Sujatajaiswal/Uabams.git
cd Uabams
```

### 5. Run Setup Script

```powershell
powershell -ExecutionPolicy Bypass -File tools\windows_mdb_setup.ps1
```

### 6. Set Database URL

Use the same PostgreSQL database that already stores parsed UABAMS cloud data.

```powershell
setx DATABASE_URL "postgresql://USERNAME:PASSWORD@HOST:5432/DBNAME"
```

Close and reopen PowerShell after running `setx`.

### 7. Run The API

```powershell
venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 8. Open The Handoff Page

Open:

```text
http://<windows-vm-public-ip>:8000/csv-page
```

Click:

```text
Download Actual MDB
```

Expected output:

```text
uabams_tms_transfer.mdb
```

## MDB Tables

The actual MDB export should contain the two datasets required for TMS:

| MDB Table | Source Data | Purpose |
| --- | --- | --- |
| SpatialAccelerationData | RMS 25 cm records | Spatial acceleration data with GPS/location |
| ProcessedPeakData | Peak 50 m records | Processed peak data for abnormal acceleration events |

## Demo Explanation

Use this explanation:

> Render is used as the prototype intermediate processing station. It receives gateway ZIP archives, stores and parses records in PostgreSQL, generates GPS alerts, and prepares TMS handoff data. Actual MDB generation should run on a Windows VM because MDB requires Microsoft Access Jet/ACE/OLEDB drivers.

## Important Notes

- Do not hardcode database passwords in source code.
- Use HTTPS in production.
- Keep the Render deployment for cloud visualization and API demo.
- Use Windows VM for actual MDB export testing.
- Final MDB columns should be confirmed with the CRIS/TMS integration team.
