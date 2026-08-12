import os
import sys
import json
from pathlib import Path
import serial
from PyQt5.QtWidgets import QApplication
from classes.camera_manager import CameraManager
from classes.camera_viewer import CameraViewer
from utils.test_camera import TestVideoCapture


# Заглушка для Arduino
class MockSerial:
    def __init__(self, *args, **kwargs):
        pass

    def write(self, data):
        print(f"[MOCK] Отправка команды: {data.decode().strip()}")

    def close(self):
        pass


def load_model_configs():
    """Загружает конфигурацию моделей так же, как в main.py."""
    # Здесь можно скопировать код из main.py, который читает data/models_config.json
    # или использует MODELS_DISTRIBUTION.
    # Для простоты возьмём дефолтную конфигурацию из main.py, но можно и из файла.
    # В реальном проекте этот код должен быть вынесен в отдельную функцию, чтобы не дублировать.
    # Пока скопируем упрощённо.

    # Попробуем загрузить из data/models_config.json
    config_file = Path("data/models_config.json")
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    # Если нет, вернём дефолтную (как в main.py)
    return {
        "middle": {
            "1": {
                "name": "Стекло на дне",
                "path": "new_weights/bottom_glass_new_v3.pt",
                "conf": "0.48",
                "color": [240, 120, 50]
            },
            "2": {
                "name": "Брак сварки",
                "path": "new_weights/welding_new_2.pt",
                "conf": "0.30",
                "color": [240, 120, 50]
            }
        },
        "near": {
            "1": {
                "name": "разновысотность",
                "path": "new_weights/uneven_heights_and_unfilled_windows_new1.pt",
                "conf": "0.5",
                "color": [200, 155, 0]
            },
            "2": {
                "name": "Раковины окон",
                "path": "new_weights/shells26_v2.pt",
                "conf": "0.54",
                "color": [0, 150, 255]
            }
        },
        "far": {
            "1": {
                "name": "разновысотность",
                "path": "new_weights/uneven_heights_and_unfilled_windows_new1.pt",
                "conf": "0.5",
                "color": [200, 155, 0]
            },
            "2": {
                "name": "Раковины окон",
                "path": "new_weights/shells26_v2.pt",
                "conf": "0.45",
                "color": [0, 150, 255]
            }
        }
    }


def main():
    # Параметры тестирования
    test_images_root = "test_images"  # папка с подпапками Camera_0, Camera_1, Camera_2
    cam_caps = []
    for i in range(3):
        folder = os.path.join(test_images_root, f"Camera_{i}")
        if not os.path.exists(folder):
            print(f"Папка {folder} не найдена. Создайте её и положите тестовые изображения.")
            sys.exit(1)
        cam_caps.append(TestVideoCapture(folder, loop=True))

    # Заглушка для Arduino
    ser = MockSerial()

    # Определяем роли камер (как в main.py)
    cam_ids = [0, 1, 2]
    # По умолчанию: 0 - near, 1 - middle, 2 - far
    # Можно загрузить из data/camera_roles.json, но для теста оставим так
    role_by_cam_id = {0: "near", 1: "middle", 2: "far"}
    camera_roles_per_cam = [role_by_cam_id.get(cid, "near") for cid in cam_ids]

    # Загружаем конфигурацию моделей
    MODELS_DISTRIBUTION = load_model_configs()

    # Собираем конфиги для каждой камеры
    model_configs_per_camera = []
    for cam_id, role in zip(cam_ids, camera_roles_per_cam):
        role_models = MODELS_DISTRIBUTION.get(role, {})
        cam_models = []
        for key in sorted(role_models.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
            cfg = role_models[key]
            kind = ""
            if role == "middle" and str(key) == "1":
                kind = "bottom_glass"
            elif role == "middle" and str(key) == "2":
                kind = "welding"
            elif role in ("near", "far") and str(key) == "1":
                kind = "uneven_heights"
            elif role in ("near", "far") and str(key) == "2":
                kind = "window_sinks"
            cam_models.append({
                "name": cfg.get("name", ""),
                "path": cfg["path"],
                "conf": float(cfg.get("conf", 0.3)),
                "color": cfg.get("color"),
                "kind": kind,
            })
        model_configs_per_camera.append(cam_models)
        print(f"Камера {cam_id} -> роль '{role}': " + ", ".join([m.get("name", "") for m in cam_models]))

    # Создаём CameraManager с тестовыми камерами
    cam_manager = CameraManager(
        cam_caps,  # передаём объекты камер вместо индексов
        model_configs_per_camera,
        ser=ser,
        inspection_slot_index=1,
        output_slot_index=3
    )

    app = QApplication(sys.argv)
    viewer = CameraViewer(cam_manager)
    viewer.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()