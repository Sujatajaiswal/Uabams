# UABAMS Cloud Deployment On Render

## Goal

Deploy the FastAPI cloud dashboard publicly on Render so anyone with the URL can:

- View latest gateway data.
- View generated alerts.
- Check cloud/database status.
- Download CSV reports generated from Render PostgreSQL.
- Open the RailMAN export JSON endpoint.

## Current Render Setup

Your Render project already has:

- `uabams-db`
- PostgreSQL database
- Region: Singapore

This is only the database. To make the dashboard public, add a Render **Web Service** for the FastAPI app.

## Render Web Service Setup

1. Push this project code to GitHub.
2. Open Render Dashboard.
3. Go to your project.
4. Click **New**.
5. Select **Web Service**.
6. Connect the GitHub repository.
7. Use these settings:

```text
Name:
uabams-cloud-api

Runtime:
Python

Build Command:
pip install -r requirements-render.txt

Start Command:
uvicorn app.main:app --host 0.0.0.0 --port $PORT

Health Check Path:
/health
```

8. Add environment variable:

```text
DATABASE_URL = your Render PostgreSQL external/internal database URL
```

Do not paste the database password into code. Keep it only in Render environment variables.

## Public URLs After Deployment

Replace `your-service-name` with your Render Web Service name.

```text
https://your-service-name.onrender.com/
https://your-service-name.onrender.com/cloud-dashboard
https://your-service-name.onrender.com/dashboard
https://your-service-name.onrender.com/csv-page
https://your-service-name.onrender.com/docs
```

## CSV Download URLs

```text
https://your-service-name.onrender.com/csv/download/wheel-calibration
https://your-service-name.onrender.com/csv/download/thresholds
https://your-service-name.onrender.com/csv/download/gateway-data
https://your-service-name.onrender.com/csv/download/alerts
```

## RailMAN Future Integration URL

```text
https://your-service-name.onrender.com/railman/export
```

## Demo Explanation

Say this in the meeting:

> The database is hosted on Render PostgreSQL. I also deployed the FastAPI cloud dashboard on Render as a public Web Service. Anyone with the public URL can view stored gateway data, generated alerts, cloud/database status, and download CSV reports. The RailMAN export endpoint is prepared for future railway cloud integration.

## Important Production Notes

- For public demo, read-only viewing and CSV download are okay.
- For production, add authentication before allowing write endpoints publicly.
- Gateway devices should POST data to the deployed `/api/data` URL.
- RailMAN can later consume `/railman/export` or the CSV endpoints depending on the required format.
