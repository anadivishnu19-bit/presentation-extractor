@echo off
cd /d "%~dp0"

if not exist ".venv" (
    echo Setting up (first run only)...
    python -m venv .venv
    .venv\Scripts\pip install --quiet --upgrade pip
    .venv\Scripts\pip install --quiet -r requirements.txt
)

echo Starting Presentation Extractor...
echo Opening http://localhost:8000 in your browser.
.venv\Scripts\python app.py
pause
