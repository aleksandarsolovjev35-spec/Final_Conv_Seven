import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import cv2
from ultralytics.models import YOLO
import json
from pathlib import Path

from classes.squares_widget import STATE_PRIORITY
from classes.statistics_manager import StatisticsManager
from processing.process_frame import process_frame, infer_model_kind
from utils.auto_move import send_command, capture_camera_frames_parallel, save_processed_frames_parallel
from utils.logs.logger import logger
from utils.excel_processing import generate_report

# Добавляем импорт BatchManager из той же папки classes
try:
    from classes.batch_manager import BatchManager
    BATCH_MANAGER_AVAILABLE = True
    print("BatchManager успешно импортирован")
except ImportError as e:
    print(f"Ошибка импорта BatchManager: {e}")
    BATCH_MANAGER_AVAILABLE = False

# Глобальный словарь для хранения данных о контурах
contour_storage = {
    "contacts": [],
    "platform": None
}


def merge_states(current: int, new: int) -> int:
    """Объединяет состояния (0=OK, иначе брак/причина) по приоритету.
    """
    if new is None:
        return current

    if new == 0:
        return current
    if current is None:
        return new
    if current == 0:
        return new

    return new if STATE_PRIORITY.get(new, 10) > STATE_PRIORITY.get(current, 10) else current


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


def on_batch_finished(batch_path):
    try:
        print(f"Автоматическая генерация отчёта для партии: {batch_path}")
        # Генерируем отчёт со всеми данными (max_items=None)
        output_file = Path(batch_path) / "final_report.xlsx"
        result = generate_report(batch_path, output_path=output_file, max_items=None)
        if result:
            print(f"Отчёт для завершённой партии сохранён: {result}")
        else:
            print("Не удалось создать отчёт для завершённой партии")
    except Exception as e:
        print(f"Ошибка при автоматической генерации отчёта: {e}")


class CameraManager:
    def __init__(self, cam_ids, model_configs, ser, frame_width=1280, frame_height=720,
                 inspection_slot_index=0, output_slot_index=3, camera_roles=None):
        self.cam_ids = cam_ids
        self.caps = []
        self.frames = [None] * len(cam_ids)
        self.lock = threading.Lock()
        self.running = False
        self.preview_active = False  # Флаг для режима прямого эфира
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.ser = ser
        self.ser_lock = threading.Lock()

        self.object_data = [{} for _ in cam_ids]
        self.object_data_lock = threading.Lock()

        self.squares_state = [0] * 8
        self.inspection_slot_index = int(inspection_slot_index)
        self.output_slot_index = int(output_slot_index)
        self.squares_lock = threading.Lock()

        self.good_count = 0
        self.bad_count = 0
        self.stats_manager = StatisticsManager()
        self.thresholds = self.stats_manager.thresholds

        # Инициализация BatchManager
        self.batch_manager = None
        if BATCH_MANAGER_AVAILABLE:
            try:
                self.batch_manager = BatchManager(on_batch_finished=on_batch_finished)
                print("BatchManager инициализирован с callback")
            except Exception as e:
                print(f"Ошибка инициализации BatchManager: {e}")
                self.batch_manager = None
        else:
            self.batch_manager = None

        # На всякий случай приводим конфиги моделей к количеству камер
        if len(model_configs) < len(cam_ids):
            model_configs = list(model_configs) + [[] for _ in range(len(cam_ids) - len(model_configs))]
        elif len(model_configs) > len(cam_ids):
            model_configs = list(model_configs)[:len(cam_ids)]

        # Открываем камеры
        logger.info("Идет открытие камер...")
        for i, cam in enumerate(cam_ids):
            if isinstance(cam, int):
                cap = cv2.VideoCapture(cam, cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
            else:
                cap = cam
            self.caps.append(cap)

        # Грузим модели (по списку на каждую камеру)
        self.models_configs = []
        for configs in model_configs:
            camera_models = []
            for config in configs:
                model = uploading_a_neural_network_model(config["path"])
                camera_models.append(
                    {
                        "model": model,
                        "conf": float(config.get("conf", 0.3)),
                        "name": config.get("name", ""),
                        "kind": config.get("kind") or infer_model_kind(config),
                        "color": config.get("color"),
                    }
                )
            self.models_configs.append(camera_models)

        self.executor = ThreadPoolExecutor(max_workers=max(1, len(cam_ids)))
        self.thread = threading.Thread(target=self.main_loop, daemon=True)
        self.thread.start()
        self.safe_send_command("I0")#Информационная команда прошивки
        self.safe_send_command("G28 P0")
        self.safe_send_command("G28 P1")
        self.shift_point = [0, 0]

        self.camera_roles = camera_roles if camera_roles else ["near"] * len(cam_ids)
        self.heights_config = self._load_heights_config()

    def _load_heights_config(self):
        """загрузка граничных значений для контроля качества из конфигурационных json файлов"""
        default_config = {
            "near": {"min": 23.0, "max": 37.0, "avg": 8.0},
            "far": {"min": 24.0, "max": 38.0, "avg": 9.0},
        }
        try:
            default_config["near"]["min"] = self.thresholds.get('near_cam_minimum', default_config["near"]["min"])
            default_config["near"]["max"] = self.thresholds.get('near_cam_maximum', default_config["near"]["max"])
            default_config["near"]["avg"] = self.thresholds.get('near_cam_difference', default_config["near"]["avg"])
            default_config["far"]["min"] = self.thresholds.get('far_cam_minimum', default_config["far"]["min"])
            default_config["far"]["max"] = self.thresholds.get('far_cam_maximum', default_config["far"]["max"])
            default_config["far"]["avg"] = self.thresholds.get('far_cam_difference', default_config["far"]["avg"])
            print(self.thresholds.get('near_cam_difference', default_config["near"]["avg"]))
        except Exception as e:
            print(f"Ошибка загрузки настроек разновысотности: {e}")
        return default_config

    def get_heights_thresholds(self, camera_index):
        """загрузка соответствующих граничных параметров"""
        if camera_index == 0 or 2:
            role = self.camera_roles[camera_index]
        else:
            role = "near"
        return self.heights_config.get(role, self.heights_config["near"])

    def save_states(self):
        """Сохраняет первые 4 состояния конвейера в JSON файл для возможной последующей загрузки"""
        file_path = Path("data/first_four_states.json")
        try:
            file_path.parent.mkdir(exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.squares_state[:4], f, indent=2)
            logger.debug(f"Первые 4 состояния конвейера сохранены: {self.squares_state[:4]}")
        except Exception as e:
            logger.exception(f"Ошибка сохранения первых 4 состояний: {e}")

    def start_processing(self):
        """запуск инспекции"""
        self.running = True
        self.safe_send_command("G1")

    def stop_processing(self):
        """остановка инспекции"""
        self.running = False
        self.preview_active = False  # Флаг для режима прямого эфира
        self.safe_send_command("G2")

    def safe_send_command(self, cmd):
        """Потокобезопасная отправка команды с защитой от закрытого дескриптора."""
        with self.ser_lock:
            try:
                if not self.ser.is_open:
                    logger.warning("Порт закрыт. Попытка повторного открытия...")
                    self.ser.open()
                send_command(self.ser, cmd)
            except Exception as e:
                logger.error(f"Ошибка отправки команды '{cmd}': {e}")

    def load_initial_states(self):
        """Загружает первые 4 состояния из файла, если он существует."""
        file_path = Path("data/first_four_states.json")
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list) and len(data) >= 4:
                    return data[:4]
            except Exception as e:
                logger.exception(f"Ошибка загрузки состояний: {e}")
        return None

    def restore_states(self, states):
        """Восстанавливает первые 4 позиции конвейера, остальные обнуляет."""
        with self.squares_lock:
            for i in range(4):
                self.squares_state[i] = states[i] if i < len(states) else 0
            for i in range(4, len(self.squares_state)):
                self.squares_state[i] = 0
            # Сохраняем обновлённое состояние
        logger.info(f"Состояния восстановлены: {self.squares_state[:4]}")

    def clear_initial_states(self):
        """Обнуляет файл с первыми четырьмя состояниями."""
        file_path = Path("data/first_four_states.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump([0, 0, 0, 0], f)
            logger.info("Файл состояний очищен")
        except Exception as e:
            logger.exception(f"Ошибка очистки файла состояний: {e}")

    def update_slot_state(self, new_state: int, slot_index=None):
        """Обновляет состояние конкретной позиции в squares_state с мерджем по приоритету."""
        idx = self.inspection_slot_index if slot_index is None else int(slot_index)
        if idx < 0 or idx >= len(self.squares_state):
            return
        with self.squares_lock:
            self.squares_state[idx] = merge_states(self.squares_state[idx], int(new_state))

    def capture_all_frames(self):
        """Синхронный захват кадров со всех камер."""
        frames = {}
        for cap in self.caps:
            try:
                cap.grab()
            except Exception:
                pass

        # Потом "достаём" кадры (decode)
        for idx, cap in enumerate(self.caps):
            frame = None
            ret = False
            try:
                ret, frame = cap.retrieve()
            except Exception:
                ret = False

            # Fallback: если retrieve не сработал — читаем обычным способом
            if not ret or frame is None:
                try:
                    ret, frame = cap.read()
                except Exception:
                    ret = False

            if ret and frame is not None:
                frames[idx] = frame

        return frames

    def process_single_camera(self, cap_index: int, frame=None):
        """Обработка одной камеры соответствующими ею нейромоделями"""
        if frame is None:
            cap = self.caps[cap_index]
            ret, frame = cap.read()
            if not ret or frame is None:
                return None, []

        processed_frame = frame.copy()
        models_configs = self.models_configs[cap_index]
        object_data = []

        # Локальное хранилище контуров — только для этой камеры (важно при параллельной обработке)
        contour_storage_local = {"contacts": [], "platform": None}

        for config in models_configs:
            model = config["model"]
            conf = config["conf"]
            processed_frame, current_object_data, _lengths = process_frame(
                processed_frame,
                model,
                self,
                model_cfg=config,
                conf=conf,
                contour_storage=contour_storage_local,
                camera_index=cap_index
            )
            object_data.extend(current_object_data)

        with self.object_data_lock:
            self.object_data[cap_index] = object_data

        return processed_frame, object_data

    def get_object_data(self, index):
        """гетер данных об объекте"""
        with self.object_data_lock:
            return self.object_data[index].copy()

    def start_new_batch(self):
        """Начинает новую партию сохранения фотографий."""
        if self.batch_manager:
            try:
                return self.batch_manager.start_new_batch()
            except Exception as e:
                logger.exception(f"Ошибка при создании партии: {e}")
                return None
        else:
            print("BatchManager не инициализирован")
            return None

    def is_batch_active(self):
        """Проверяет, активна ли партия."""
        if self.batch_manager:
            return self.batch_manager.is_batch_active()
        return False

    def get_current_batch_info(self):
        """Возвращает информацию о текущей партии."""
        if self.batch_manager:
            return self.batch_manager.get_current_batch_info()
        return None

    def save_conveyor_states(self):
        """Сохраняет текущее состояние всех позиций конвейера (0-7) в JSON файл."""
        with self.squares_lock:
            states = self.squares_state.copy()  # копируем, чтобы избежать изменений во время записи
        file_path = Path("../data/conveyor_states.json")
        file_path.parent.mkdir(exist_ok=True)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(states, f, indent=2)
            logger.debug(f"Состояния конвейера сохранены: {states}")
        except Exception as e:
            logger.exception(f"Ошибка сохранения состояний конвейера: {e}")

    def main_loop(self):
        """основной алгоритм инспекции"""
        while True:
            start_detection = time.time()
            # Захватываем кадры, если работает инспекция ИЛИ включён прямой эфир
            is_active = self.running or self.preview_active
            if not is_active:
                time.sleep(0.1)
                continue

            # 1) Захват кадров (аппаратный)
            try:
                raw_frames = self.capture_all_frames()
            except Exception:
                logger.exception("Ошибка захвата кадров")
                time.sleep(0.1)
                continue

            # Сразу сохраняем сырые кадры в буфер для UI
            with self.lock:
                for idx, frame in raw_frames.items():
                    self.frames[idx] = frame

            # Если включён только прямой эфир, пропускаем тяжёлую обработку конвейера
            if not self.running:
                time.sleep(0.03)  # ~30 FPS для превью
                continue

            # 2) Сдвигаем конвейер для следующей детали
            self.safe_send_command("G3")
            start = time.time()

            # 3) Обработка камер параллельно (исходный код инспекции)
            results = {}
            try:
                futures = {
                    self.executor.submit(self.process_single_camera, i, raw_frames.get(i)): i
                    for i in range(len(self.caps))
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    processed_frame, _ = future.result()
                    if processed_frame is not None:
                        results[idx] = processed_frame
            except:
                logger.exception("Ошибка обработки кадров с камер: ")
            self.save_states()


            # 4) Проверяем, была ли обнаружена деталь
            detected_flatness = False
            with self.object_data_lock:
                for camera_data in self.object_data:
                    for obj in camera_data:
                        # Проверяем классы, связанные с плоскостностью
                        if obj["class_name"] in ["flatness", "uneven_heights", "window_sinks",
                                                 "flatness_short", "flatness_long"]:
                            detected_flatness = True
                            break
                    if detected_flatness:
                        break
            if detected_flatness:
                # 5) Определяем вердикт на основе инспекции (позиция 1)
                with self.squares_lock:
                    verdict = self.squares_state[self.inspection_slot_index]
                logger.info(f"Вердикт инспекции на позиции {self.inspection_slot_index}: {verdict}")

                # 6) Получаем данные объектов для каждой камеры
                with self.object_data_lock:
                    camera_data_list = [self.object_data[i] for i in range(len(self.caps))]

                # создаём копию без поля 'segment' для сохранения
                camera_data_clean = []
                for cam_data in camera_data_list:
                    cam_clean = []
                    for obj in cam_data:
                        obj_clean = obj.copy()
                        obj_clean.pop('segment', None)
                        cam_clean.append(obj_clean)
                    camera_data_clean.append(cam_clean)

                # Определяем типы браков
                defect_types = []
                if verdict != 0:
                    defect_types = [verdict]

                # Если деталь обнаружена и вердикт 0, меняем состояние для отображения на 1
                if verdict == 0:
                    with self.squares_lock:
                        self.squares_state[self.inspection_slot_index] = 1

            stop_detection = time.time()
            print(f"ВРЕМЯ ДЕТЕКЦИИ БРАКА НА ДЕТАЛИ: {start_detection - stop_detection}")
            start_stat = time.time()

            # 7) Отдаём обработанные кадры в UI
            try:
                with self.lock:
                    for idx, frame in results.items():
                        self.frames[idx] = frame

                if self.batch_manager and self.batch_manager.is_batch_active():
                    from utils.auto_move import save_processed_frames_parallel
                    save_processed_frames_parallel(results, self.batch_manager)
            except:
                logger.exception("Ошибка обновления UI кадров или сохранения обработанных: ")

            # 8) обновляем статистику сразу после инспекции
            if detected_flatness:
                print(f"Деталь обнаружена! Вердикт: {verdict}")

                # Обновляем статистику
                if verdict == 0:
                    self.good_count = 1
                    self.bad_count = 0
                    logger.info("Деталь признана ГОДНОЙ (статистика обновлена)")
                else:
                    self.good_count = 0
                    self.bad_count = 1
                    logger.info(f"Деталь признана БРАКОВАННОЙ, код: {verdict} (статистика обновлена)")

                # Сразу обновляем глобальную статистику
                try:
                    self.stats_manager.update_stats(self.good_count, self.bad_count)
                    self.good_count = 0
                    self.bad_count = 0
                    print(f"Статистика обновлена")
                except Exception as e:
                    logger.exception(f"Ошибка обновления статистики: {e}")

                # Сохраняем кадры с метаданными
                try:
                    capture_camera_frames_parallel(
                        raw_frames,
                        self.batch_manager,
                        camera_data_clean,
                        verdict,
                        defect_types
                    )
                    logger.info("Сохранение кадров с камер и метаданных")
                except:
                    logger.exception("Ошибка сохранения кадров с камер:")
            else:
                logger.info("Деталь не обнаружена - статистика не обновляется")
                self.good_count = 0
                self.bad_count = 0
            stop_stat = time.time()
            print(f"\n\nВРЕМЯ обновления статистики : {start_stat - stop_stat}\n\n")
            start_rasp = time.time()
            # 9) Проверяем распределение на позиции output_slot_index
            with self.squares_lock:
                output_state = self.squares_state[self.output_slot_index]

            # 10) распределяем деталь если она присутствует на позиции output_slot_index
            logger.debug(f"начало движения конвейера: {time.time()}")
            delay = self.thresholds.get('delay_after_distribution', 1.0)
            time.sleep(delay)
            logger.debug(f"переключение распределителя: {time.time()}, {time.time() - start}")

            if output_state != 0:
                logger.info(f"Распределение на позиции {self.output_slot_index}: {output_state}")
                if output_state == 1:
                    logger.info("Распределение: ГОДНАЯ деталь")
                    self.safe_send_command(f"G20 S{0 - self.shift_point[1]} P1")
                    time.sleep(0.35)
                    self.safe_send_command(f"G20 S{340 - self.shift_point[0]} P0")
                    time.sleep(0.35)
                    self.shift_point = [340, 0]

                elif output_state == 2 or output_state == 3:
                    logger.info(f"Распределение: БРАК (код {output_state})")
                    self.safe_send_command(f"G20 S{0 - self.shift_point[0]} P0")
                    time.sleep(0.35)
                    self.shift_point[0] = 0

                else:
                    logger.info(f"Распределение: ЧИСТКА (код {output_state})")
                    self.safe_send_command(f"G20 S{340 - self.shift_point[1]} P1")
                    time.sleep(0.35)
                    self.safe_send_command(f"G20 S{340 - self.shift_point[0]} P0")
                    time.sleep(0.35)
                    self.shift_point = [340, 340]

                    # Сбрасываем состояние после распределения
                with self.squares_lock:
                    self.squares_state[self.output_slot_index] = 0
                    logger.info(f"Сброс состояния на позиции {self.output_slot_index}")
            else:
                logger.info(f"На позиции {self.output_slot_index} нет детали для распределения")
            stop_rasp = time.time()
            print(f"\n\nВРЕМЯ распределения: {start_rasp - stop_rasp}")

            # 11) Сдвигаем "буфер" состояний
            try:
                with self.squares_lock:
                    self.squares_state.pop()
                    self.squares_state.insert(0, 0)

                # Отладочная информация
                print(f"Состояния после сдвига: {self.squares_state}")
                print(f"  Позиция {self.inspection_slot_index}: {self.squares_state[self.inspection_slot_index]}")
                print(f"  Позиция {self.output_slot_index}: {self.squares_state[self.output_slot_index]}")
                end = time.time() - start
                print(f"\n\nВРЕМЯ : {end}")
                end = min(10.0, end)
                time.sleep(10 - end)

                # Запускаем конвейер для следующего цикла
                self.safe_send_command("G1")
                logger.info("Конвейер запущен для следующей детали")

            except Exception as e:
                logger.exception(f"Ошибка сдвига буфера состояний: {e}")

            # 13) Очищаем данные объектов для следующей итерации
            with self.object_data_lock:
                self.object_data = [{} for _ in range(len(self.cam_ids))]

    def get_frame(self, index):
        """получение кадра"""
        with self.lock:
            frame = self.frames[index]
            if frame is None:
                return None
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return rgb_frame

    def get_squares_state(self):
        """гетер состояния"""
        with self.squares_lock:
            return self.squares_state.copy()

    def release(self):
        """Освобождает ресурсы камер."""
        self.running = False
        self.preview_active = False  # Флаг для режима прямого эфира
        try:
            self.thread.join(timeout=2)
        except Exception:
            pass
        self.executor.shutdown(wait=True)
        for cap in self.caps:
            try:
                cap.release()
            except Exception:
                pass
