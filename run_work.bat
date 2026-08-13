@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found: .venv
  echo Create it with: py -3.11 -m venv .venv
  echo Then install: .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

rem WORK MODE: clean video stream from all cameras, no overlays, no debug pauses.
set CONVEY_MODE=work
".venv\Scripts\python.exe" main.py
endlocal
