@echo off
setlocal
cd /d "%~dp0"

py -3.11 -m venv .venv || exit /b 1
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1

rem GPU (CUDA): если найден драйвер NVIDIA - ставим CUDA-сборку torch
rem поверх CPU (вместе с Ultralytics ставится CPU-сборка). Индекс
rem переопределяется переменной TORCH_CUDA_INDEX, по умолчанию cu121.

if "%TORCH_CUDA_INDEX%"=="" set TORCH_CUDA_INDEX=cu121

nvidia-smi >nul 2>&1
if %errorlevel% neq 0 goto cpu_setup

echo NVIDIA driver found - installing CUDA PyTorch (%TORCH_CUDA_INDEX%)...
".venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/%TORCH_CUDA_INDEX%
if %errorlevel% neq 0 (
  echo WARN: CUDA PyTorch install failed - continuing with CPU PyTorch
)
goto setup_done

:cpu_setup
echo NVIDIA driver not found - CPU PyTorch will be used.

:setup_done
echo Setup complete.
endlocal
