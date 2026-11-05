@echo off
setlocal
cd /d "%~dp0"

rem Веб-разметка зон ROI по семи камерам (открывается в браузере).
rem Дополнительные ключи передаются как есть, например:
rem   run_roi_web.bat --source synthetic --step sim
rem   run_roi_web.bat --step none --web-port 8080

if exist ".venv\Scripts\python.exe" goto run

echo Python environment not found: .venv
echo Run setup.bat first: it creates .venv and installs all dependencies.
echo.
pause
exit /b 1

:run
echo Откройте в браузере: http://127.0.0.1:8077/
".venv\Scripts\python.exe" roi_capture_web.py %*
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" goto ok

echo.
echo roi_capture_web.py stopped with exit code %EXIT_CODE%.
pause
endlocal & exit /b %EXIT_CODE%

:ok
endlocal & exit /b 0
