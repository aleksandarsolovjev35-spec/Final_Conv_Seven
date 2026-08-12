import json
import os
import sys

import serial
from ultralytics import YOLO
import os, sys, ctypes
from ctypes import wintypes

import PyQt5

# Путь к Qt DLL
dll_dir = os.path.join(os.path.dirname(PyQt5.__file__), 'Qt5', 'bin')
qt_widgets = os.path.join(dll_dir, 'Qt5Widgets.dll')

# Включаем отладку загрузки DLL в Windows (только для этого процесса)
os.environ['QT_DEBUG_PLUGINS'] = '1'

# Попытка загрузить с отладкой
try:
    # Для Python 3.8+ важно добавить путь ДО загрузки
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(dll_dir)
    os.environ['PATH'] = dll_dir + ';' + os.environ.get('PATH', '')

    # Пробуем загрузить через ctypes с флагом LOAD_WITH_ALTERED_SEARCH_PATH
    LOAD_WITH_ALTERED_SEARCH_PATH = 0x00000008
    handle = ctypes.WinDLL(qt_widgets, mode=LOAD_WITH_ALTERED_SEARCH_PATH)
    print("✅ Qt5Widgets.dll загружен через ctypes")
except OSError as e:
    print(f"❌ Ошибка загрузки: {e}")
    import traceback

    traceback.print_exc()
from PyQt5.QtWidgets import QApplication
from classes.camera_manager import CameraManager
from classes.camera_viewer import CameraViewer
from utils.auto_move import find_arduino_port


def uploading_a_neural_network_model(model_path):
    """
    Загружает нейросетевую модель по заданному пути.
    :param model_path: Путь до модели.
    :return: Веса указанной модели.
    """
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"Модель не найдена по пути: {model_path}")
    weight = YOLO(model_path)
    weight.fuse()
    return weight


# Глобальный словарь для хранения данных о контурах
contour_storage = {
    "contacts": [],
    "platform": None
}


def main():
    # try:
    port = find_arduino_port()
    ser = serial.Serial(port, 115200, timeout=0.1)
    import time
    time.sleep(2)  # Ждём загрузку Arduino после DTR-reset
    # except:
    #     print("не подключено")
    cam_ids = [0, 1, 2]

    # Явное сопоставление cam_id -> роль камеры ("near"/"middle"/"far").
    # Чтобы не путать центральную и дальнюю камеры, задаём map один раз и используем его везде.
    # ДЕФОЛТ под ваш кейс: 0=near, 1=far, 2=middle (т.е. "middle" и "far" поменяны местами относительно прежнего варианта).
    # При желании можно переопределить через файл:
    #   project\configuration\camera_roles.json
    # Формат файла: {"0":"near","1":"middle","2":"far"} (ключи могут быть и числами).
    role_map_path = r"project\configuration\camera_roles.json"
    role_by_cam_id = {}
    if len(cam_ids) >= 3:
        role_by_cam_id = {cam_ids[1]: "middle", cam_ids[0]: "near", cam_ids[2]: "far"}

    try:
        if os.path.isfile(role_map_path):
            with open(role_map_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                tmp = {}
                for k, v in data.items():
                    try:
                        tmp[int(k)] = str(v)
                    except Exception:
                        continue
                if tmp:
                    role_by_cam_id.update(tmp)
    except Exception as e:
        print(f"[WARNING] Не удалось прочитать {role_map_path}: {e}")

    camera_roles_per_cam = [role_by_cam_id.get(cid, "near") for cid in cam_ids]
    print("[INFO] Camera roles:", {cid: camera_roles_per_cam[i] for i, cid in enumerate(cam_ids)})

    MODELS_DISTRIBUTION = {
        "middle": {
            "1": {
                "name": "Стекло на дне",
                "description": "определяет стекло на задней части изделия",
                "color": [240, 120, 50],
                "path": r"new_weights/bottom_glass_new_v3.pt",
                "conf": "0.65",
            },
            "2": {
                "name": "Брак сварки",
                "description": "определяет брак сварки",
                "color": [240, 120, 50],
                "path": r"new_weights/welding_new_2.pt",
                "conf": "0.65",
            },
        },
        "near": {
            "1": {
                "name": "разновысотность",
                "description": "",
                "color": [200, 155, 0],
                "path": r"new_weights/windows_4.pt",
                "conf": "0.7",
            },
            "2": {
                "name": "Раковины окон",
                "description": "определяет раковыны в окнах",
                "color": [0, 150, 255],
                "path": r"new_weights/shells.pt",
                "conf": "0.80",
            },
            # "3": {
            #     "name": "Раковины окон 2",
            #     "description": "определяет раковыны в окнах",
            #     "color": [0, 150, 255],
            #     "path": r"new_weights/shells_v26_newest.pt",
            #     "conf": "0.45",
            # },
        },
        "far": {
            "1": {
                "name": "разновысотность",
                "description": "",
                "color": [200, 155, 0],
                "path": r"new_weights/windows_4.pt",
                "conf": "0.7",
            },
            "2": {
                "name": "Раковины окон",
                "description": "определяет раковыны в окнах",
                "color": [0, 150, 255],
                "path": r"new_weights/shells.pt",
                "conf": "0.80",
            },
            # "3": {
            #     "name": "Раковины окон 2",
            #     "description": "определяет раковыны в окнах",
            #     "color": [0, 150, 255],
            #     "path": r"new_weights/shells_v26_newest.pt",
            #     "conf": "0.45",
            # },
        },
    }

    # Собираем список конфигов в формате, который ожидает CameraManager:
    # model_configs_per_camera = [ [cfg_model1, cfg_model2, ...],  [..], [..] ]
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
            elif role in ("near", "far") and (str(key) == "2"):
                kind = "window_sinks"

            cam_models.append(
                {
                    "name": cfg.get("name", ""),
                    "path": cfg["path"],
                    "conf": float(cfg.get("conf", 0.3)),
                    "color": cfg.get("color"),
                    "kind": kind,
                }
            )
        model_configs_per_camera.append(cam_models)

        # Быстрая проверка, что к нужной камере привязались нужные веса:
        try:
            print(f"[INFO] Camera {cam_id} -> role '{role}': " + ", ".join([m.get("name", "") for m in cam_models]))
        except Exception:
            pass

    # Если все 3 камеры стоят в ОДНОЙ зоне инспекции — пишем результаты в один слот конвейера.
    # Обычно это слот 0 (первая клетка). Если инспекция физически в другой позиции — поменяйте inspection_slot_index.
    cam_manager = CameraManager(cam_ids, model_configs_per_camera, ser=ser, inspection_slot_index=0, camera_roles=camera_roles_per_cam)

    app = QApplication(sys.argv)
    viewer = CameraViewer(cam_manager)
    viewer.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

