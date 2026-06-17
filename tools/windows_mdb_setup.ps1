param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "UABAMS Windows MDB export setup"
Write-Host "Checking Python..."
& $PythonCommand --version

if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..."
    & $PythonCommand -m venv venv
}

Write-Host "Installing Python dependencies..."
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\venv\Scripts\pip.exe" install -r requirements-render.txt
& ".\venv\Scripts\pip.exe" install -r requirements-windows-mdb.txt

Write-Host ""
Write-Host "Setup complete."
Write-Host "Next steps:"
Write-Host '1. Install Microsoft Access Database Engine Redistributable if not already installed.'
Write-Host '2. Set DATABASE_URL using setx DATABASE_URL "postgresql://USERNAME:PASSWORD@HOST:5432/DBNAME"'
Write-Host '3. Reopen PowerShell.'
Write-Host '4. Run: venv\Scripts\activate'
Write-Host '5. Run: uvicorn app.main:app --host 0.0.0.0 --port 8000'
Write-Host '6. Open: http://<windows-vm-ip>:8000/csv-page'
