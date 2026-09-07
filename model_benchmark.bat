@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found: .venv
  echo Create it with: py -3.11 -m venv .venv
  echo Then install: .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)

rem Тест скорости нейросетей: все модели линии на CPU и GPU по кадру одной камеры.
rem Примеры:
rem   model_benchmark.bat
rem   model_benchmark.bat --camera 1 --iterations 20
rem   model_benchmark.bat --image frame.png --json bench.json
".venv\Scripts\python.exe" -m vision.model_benchmark %*
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Замер не выполнен. См. сообщения выше.
)
pause
exit /b %EXIT_CODE%
