$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --app-dir backend

