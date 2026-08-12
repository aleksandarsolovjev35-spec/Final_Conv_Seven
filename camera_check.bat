@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found: .venv
  echo Create it with: py -3.11 -m venv .venv
  echo Then install: .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

".venv\Scripts\python.exe" -m vision.camera_diagnostic %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Обнаружены проблемы с камерами. См. отчёт выше.
  pause
)

exit /b %EXIT_CODE%
