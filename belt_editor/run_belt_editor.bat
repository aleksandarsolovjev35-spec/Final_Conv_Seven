@echo off
rem belt_editor/run_belt_editor.bat — экран сборки ленты в браузере.
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 goto :nopython
python serve.py --host 127.0.0.1 --port 8020 --open
if errorlevel 1 pause
exit /b %errorlevel%

:nopython
echo Python not found. Install Python 3.11+ and add it to PATH.
pause
exit /b 1
