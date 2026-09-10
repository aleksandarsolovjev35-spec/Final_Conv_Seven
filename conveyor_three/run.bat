@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found: .venv
  echo Run setup.bat first: it creates .venv and installs all dependencies
  echo (including CUDA PyTorch when an NVIDIA driver is present).
  exit /b 1
)

".venv\Scripts\python.exe" main.py
endlocal
