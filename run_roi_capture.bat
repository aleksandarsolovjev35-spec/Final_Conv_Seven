@echo off
setlocal
cd /d "%~dp0"

rem Окно разметки зон ROI по семи камерам с шагом конвейера.
rem Дополнительные ключи передаются как есть, например:
rem   run_roi_capture.bat --source synthetic --step sim
rem   run_roi_capture.bat --step none --scale 0.8

if exist ".venv\Scripts\python.exe" goto run

echo Python environment not found: .venv
echo Run setup.bat first: it creates .venv and installs all dependencies.
echo.
pause
exit /b 1

:run
".venv\Scripts\python.exe" roi_capture.py %*
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" goto ok

echo.
echo roi_capture.py stopped with exit code %EXIT_CODE%.
pause
endlocal & exit /b %EXIT_CODE%

:ok
endlocal & exit /b 0
