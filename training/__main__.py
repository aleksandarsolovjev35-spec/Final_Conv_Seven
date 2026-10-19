"""Запуск отдельного мастера сбора датасета.

Windows:
    .venv\\Scripts\\python.exe -m training

Мастер нужно запускать при остановленной производственной программе: обе
программы используют USB-камеры, и один и тот же VideoCapture нельзя
безопасно открыть одновременно. Контроллер ленты при этом может быть занят
мастером: кнопка «ДАЛЕЕ» сдвигает ленту на шаг между деталями.
"""

from __future__ import annotations

import argparse
import json
import os
import webbrowser
from pathlib import Path

import uvicorn

from training.collector import (
    DEFAULT_CAMERA_ROLES,
    DEFAULT_DEFECT_CLASSES,
    CollectorCameraSource,
    TrainingCollector,
    TrainingConfig,
)
from training.server import create_app


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Отдельный мастер ручной разметки кадров для YOLO"
    )
    parser.add_argument("--host", default=os.environ.get("TRAINING_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TRAINING_PORT", "8010")))
    parser.add_argument("--root", default=os.environ.get("TRAINING_ROOT", "training_datasets"))
    parser.add_argument("--mapping", default="camera_mapping.json")
    parser.add_argument("--config", help="JSON с camera_roles и defect_classes")
    parser.add_argument(
        "--conveyor",
        choices=("auto", "on", "off"),
        default=os.environ.get("TRAINING_CONVEYOR", "auto"),
        help="лента: auto — найти контроллер, on — только с ним, off — без шагов",
    )
    parser.add_argument(
        "--conveyor-port",
        default=os.environ.get("TRAINING_CONVEYOR_PORT"),
        help="COM-порт контроллера ленты (иначе автопоиск)",
    )
    parser.add_argument(
        "--calibration",
        default=os.environ.get("TRAINING_CALIBRATION", "calibration.json"),
        help="JSON с параметрами ленты (conveyor_speed, normal_steps, settle_time)",
    )
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)

    options = _load_options(args.config)
    roles = tuple(options.get("camera_roles") or DEFAULT_CAMERA_ROLES)
    classes = tuple(options.get("defect_classes") or DEFAULT_DEFECT_CLASSES)
    config = TrainingConfig(
        root_folder=args.root,
        camera_roles=roles,
        defect_classes=classes,
    )

    belt, transport = _create_belt(args)

    # Импорт камеры и её открытие происходят только при запуске CLI, поэтому
    # ``import training`` не требует наличия физического оборудования.
    from vision.camera_manager import CameraManager

    cameras = CameraManager(config_file=args.mapping)
    collector = TrainingCollector(
        config,
        frame_source=CollectorCameraSource(cameras),
        belt=belt,
    )
    app = create_app(collector)
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 64)
    print("Мастер сбора датасета YOLO")
    print(f"Откройте {url}")
    print("Линия должна быть остановлена; камеры заняты только этим мастером.")
    if belt is not None:
        print("Лента подключена: «ДАЛЕЕ» сдвигает её на шаг между деталями.")
    else:
        print("Лента не подключена: детали переключаются без движения конвейера.")
    print("=" * 64)
    if args.open_browser:
        webbrowser.open(url)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        cameras.release()
        if transport is not None:
            try:
                transport.close()
            except Exception as exc:  # noqa: BLE001 — закрытие порта не роняет мастер
                print(f"[CONVEYOR] Ошибка закрытия порта: {exc}")


def _create_belt(args):
    """Подключить ленту и вернуть (BeltStepSource | None, transport | None)."""
    if args.conveyor == "off":
        return None, None

    from hardware.conveyor import Conveyor
    from hardware.port_discovery import find_controller
    from hardware.serial_transport import SerialTransport
    from training.motion import ConveyorBeltStep

    calibration = _load_calibration(args.calibration)
    port, message = find_controller(
        baudrate=115200,
        preferred_port=args.conveyor_port,
    )
    print(f"[CONVEYOR] {message}")
    if port is None:
        if args.conveyor == "on":
            raise SystemExit(
                "Контроллер ленты не найден, а запрошен --conveyor on"
            )
        return None, None

    transport = SerialTransport(port=port, baudrate=115200)
    conveyor = Conveyor(
        transport,
        speed=int(calibration.get("conveyor_speed", 18000)),
        accel=int(calibration.get("conveyor_accel", 60000)),
        steps_per_division=int(calibration.get("normal_steps", 9524)),
        divisions_per_movement=2,
    )
    settle = float(calibration.get("settle_time", 0.2))
    return (
        ConveyorBeltStep(conveyor, settle_seconds=settle),
        transport,
    )


def _load_calibration(path: str) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        with file_path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Не удалось прочитать {path}: {exc}") from exc
    return value if isinstance(value, dict) else {}


def _load_options(path: str | None) -> dict:
    if not path:
        return {}
    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Не удалось прочитать {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("Конфигурация мастера должна быть JSON-объектом")
    return value


if __name__ == "__main__":
    main()
