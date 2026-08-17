"""Composition root и публичный запуск production-приложения (3 камеры)."""

from __future__ import annotations

import os

from application.callbacks import ExitCoordinator
from application.factory import ProductionSystemFactory
from application.lifecycle import ProductionApplication
from application.runtime import RuntimeState
from application.shutdown import ShutdownManager
from application.startup import SystemInitializer
from application.ui import OperatorUI
from vision.camera_calibration_console import launch_camera_calibrator
from vision.ui import LiveMonitor


CAMERA_MAPPING_PATH = "camera_mapping.json"

# Переменная окружения, выбирающая режим запуска HMI:
#   CONVEY_MODE=work  -> РАБОТА (чистый поток, без разметки и отладочных пауз);
#   иначе             -> ОТЛАДКА (текущее поведение по умолчанию).
CONVEY_MODE_ENV = "CONVEY_MODE"
CONVEY_MODE_WORK = "work"


def resolve_debug_enabled() -> bool:
    """True в режиме ОТЛАДКА, False в режиме РАБОТА (``CONVEY_MODE=work``)."""
    mode = os.environ.get(CONVEY_MODE_ENV, "").strip().lower()
    return mode != CONVEY_MODE_WORK


def ensure_camera_mapping(path: str = CAMERA_MAPPING_PATH) -> bool:
    if os.path.exists(path):
        return True
    if launch_camera_calibrator(path):
        return True
    print(f"[STARTUP] {path} не создан; основное приложение не запускается")
    return False


def create_application() -> ProductionApplication:
    """Собирает владельцев приложения и их production-зависимости."""

    debug_enabled = resolve_debug_enabled()
    monitor = LiveMonitor(
        start_callback=None,
        stop_callback=None,
        exit_callback=None,
        fullscreen=True,
        debug_enabled=debug_enabled,
    )
    runtime = RuntimeState(monitor=monitor)
    factory = ProductionSystemFactory(debug_enabled=debug_enabled)
    exit_coordinator = ExitCoordinator(runtime)
    initializer = SystemInitializer(runtime, factory, exit_coordinator)
    operator_ui = OperatorUI(monitor)
    shutdown_manager = ShutdownManager(runtime)
    return ProductionApplication(
        runtime=runtime,
        initializer=initializer,
        exit_coordinator=exit_coordinator,
        operator_ui=operator_ui,
        shutdown_manager=shutdown_manager,
    )


def run_application() -> None:
    if not ensure_camera_mapping():
        return
    create_application().run()
