@echo off
setlocal
cd /d "%~dp0"

py -3.11 -m venv .venv || exit /b 1
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1

rem GPU (CUDA): если найден драйвер NVIDIA - ставим CUDA-сборку torch
rem поверх CPU (вместе с Ultralytics ставится CPU-сборка). Индекс
rem переопределяется переменной TORCH_CUDA_INDEX, по умолчанию cu128:
rem RTX 50xx (Blackwell, sm_120) поддерживается только сборками cu128+;
rem cu126/cu121 нужны лишь для очень старых GPU и драйверов (<570).

if "%TORCH_CUDA_INDEX%"=="" set TORCH_CUDA_INDEX=cu128

nvidia-smi >nul 2>&1
if %errorlevel% neq 0 goto cpu_setup

echo NVIDIA driver found - installing CUDA PyTorch (%TORCH_CUDA_INDEX%)...
rem --force-reinstall обязателен: без него pip находит уже установленный
rem CPU-torch из requirements.txt и пропускает установку CUDA-сборки.
".venv\Scripts\python.exe" -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/%TORCH_CUDA_INDEX%
if %errorlevel% neq 0 (
  echo WARN: CUDA PyTorch install failed - continuing with CPU PyTorch
  goto setup_done
)

rem Неподходящий индекс ставится без ошибок, но ядер для GPU в нём нет
rem (например cu121 для RTX 50xx) - проверяем реальный запуск на CUDA.
".venv\Scripts\python.exe" -c "import torch; x = torch.zeros(1, device='cuda'); torch.cuda.synchronize(); print('CUDA OK:', torch.cuda.get_device_name(0), torch.version.cuda)"
if %errorlevel% neq 0 (
  echo WARN: CUDA PyTorch installed, but the GPU is not usable with index %TORCH_CUDA_INDEX%.
  echo WARN: For RTX 50xx Blackwell GPUs use TORCH_CUDA_INDEX=cu128 or newer, then re-run setup.bat.
)
goto setup_done

:cpu_setup
echo NVIDIA driver not found - CPU PyTorch will be used.

:setup_done
echo Setup complete.
endlocal

