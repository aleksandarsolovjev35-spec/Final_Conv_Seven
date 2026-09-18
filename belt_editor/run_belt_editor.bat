@echo off
rem belt_editor/run_belt_editor.bat — экран сборки ленты в браузере.
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 goto :nopython
start "belt-editor" /min python -m http.server 8020 --bind 127.0.0.1
timeout /t 1 /nobreak >nul
start "" http://127.0.0.1:8020/
echo Открыт http://127.0.0.1:8020/ . Закройте это окно, чтобы остановить.
exit /b 0

:nopython
echo Python not found. Install Python 3.11+ and add it to PATH.
pause
exit /b 1
