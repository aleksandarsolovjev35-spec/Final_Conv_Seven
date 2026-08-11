@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=py -3.11"
)

set "PYTHONPATH=%~dp0src"
%PYTHON% -m unittest discover -s tests -v
