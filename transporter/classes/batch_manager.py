import os
from datetime import datetime
from pathlib import Path
import json
import csv
from collections import defaultdict

from utils.json_sender import send_batch_json, sync_local_queue

class BatchManager:
    def __init__(self, base_screenshots_dir="utils/screenshots", on_batch_finished=None):
        """
        Менеджер для управления партиями сохранения скриншотов.

        :param base_screenshots_dir: Базовая директория для сохранения скриншотов
        """
        print(f"Инициализация BatchManager...")

        # Путь относительно корня проекта
        self.base_dir = Path(base_screenshots_dir)

        # Проверяем существование папки
        if not self.base_dir.exists():
            print(f"Создаем папку: {self.base_dir}")
            self.base_dir.mkdir(parents=True, exist_ok=True)

        self.on_batch_finished = on_batch_finished
        # Загружаем индекс партии
        self.batch_index = self._load_batch_index()
        print(f"Загружен индекс партии: {self.batch_index}")

        # Пытаемся восстановить последнюю активную партию
        self.current_batch_path = self._restore_last_active_batch()

        if self.current_batch_path:
            print(f"Восстановлена активная партия: {self.current_batch_path}")
            # Загружаем статистику активной партии
            self.batch_stats = self._load_batch_stats()
        else:
            print("Активная партия не найдена")
            self.current_batch_path = None
            self.batch_stats = self._create_empty_stats()

    def _load_batch_index(self):
        """Загружает текущий индекс партии из файла в папке data."""
        index_file = Path("data/batch_index.json")

        # Создаем папку data, если ее нет
        data_dir = Path("data")
        if not data_dir.exists():
            print(f"Создаем папку data")
            data_dir.mkdir(parents=True, exist_ok=True)

        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    index = int(data.get("last_index", 0))
                    print(f"Загружен индекс партии: {index}")
                    return index
            except Exception as e:
                print(f"Ошибка загрузки индекса партии: {e}")
                return 0
        return 0

    def _restore_last_active_batch(self):
        """
        Восстанавливает последнюю активную партию.
        Активной считается партия, у которой нет end_time в статистике.
        """
        if self.batch_index == 0:
            print("Нет сохраненных партий")
            return None

        # Проверяем все партии, начиная с последней
        for index in range(self.batch_index, 0, -1):
            try:
                # Загружаем информацию о партии
                info_file = Path("data") / f"batch_{index}_info.json"
                if not info_file.exists():
                    continue

                with open(info_file, 'r', encoding='utf-8') as f:
                    batch_info = json.load(f)

                batch_path = Path(batch_info.get("batch_path", ""))
                if not batch_path.exists():
                    print(f"Папка партии не существует: {batch_path}")
                    continue

                # Проверяем, завершена ли партия
                stats_file = batch_path / "batch_statistics.json"
                if stats_file.exists():
                    with open(stats_file, 'r', encoding='utf-8') as f:
                        stats = json.load(f)

                    # Если партия не завершена (нет end_time или end_time пустое)
                    if not stats.get("end_time"):
                        print(f"Найдена активная партия: {batch_path}")
                        self.batch_index = index  # Восстанавливаем правильный индекс
                        return batch_path
                    else:
                        print(f"Партия {index} завершена: {stats.get('end_time')}")
                else:
                    print(f"Статистика партии {index} не найдена, считаем активной")
                    self.batch_index = index
                    return batch_path

            except Exception as e:
                print(f"Ошибка при проверке партии {index}: {e}")
                continue

        print("Активных партий не найдено")
        return None

    def _create_empty_stats(self):
        """Создает пустую статистику."""
        return {
            "batch_name": "",
            "start_time": "",
            "end_time": "",
            "total_checked": 0,
            "total_good": 0,
            "total_bad": 0,
            "defects_by_type": defaultdict(int),
            "multiple_defects": 0,
            "defects_details": defaultdict(list)
        }

    def _load_batch_stats(self):
        """Загружает статистику активной партии."""
        if not self.current_batch_path:
            return self._create_empty_stats()

        stats_file = self.current_batch_path / "batch_statistics.json"
        if not stats_file.exists():
            print(f"Статистика партии не найдена, создаем новую")
            return self._create_empty_stats()

        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)

            # Преобразуем обратно в defaultdict
            stats["defects_by_type"] = defaultdict(int, stats.get("defects_by_type", {}))

            # Преобразуем defects_details
            defects_details = defaultdict(list)
            for key, value in stats.get("defects_details", {}).items():
                if isinstance(value, list):
                    defects_details[key] = value

            stats["defects_details"] = defects_details

            return stats
        except Exception as e:
            print(f"Ошибка загрузки статистики партии: {e}")
            return self._create_empty_stats()

    def _save_batch_index(self):
        """Сохраняет текущий индекс партии в файл в папке data."""
        index_file = Path("data/batch_index.json")
        data = {"last_index": self.batch_index}
        try:
            # Убедимся, что папка data существует
            index_file.parent.mkdir(exist_ok=True)
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"Индекс партии сохранен: {self.batch_index}")
        except Exception as e:
            print(f"Ошибка сохранения индекса партии: {e}")

    def start_new_batch(self, custom_name=None):
        """
        Создаёт новую партию.
        Если есть активная партия, сначала завершает её.
        """
        # Если есть активная партия – завершаем её
        if self.is_batch_active():
            print("Завершаем текущую партию перед созданием новой...")
            self.finish_batch()

        """Создает новую папку для партии и возвращает путь к ней."""
        try:
            print(f"Начинаем создание новой партии...")

            # Увеличиваем индекс
            self.batch_index += 1
            print(f"Новый индекс: {self.batch_index}")

            # Создаем имя партии
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            if custom_name and custom_name.strip():
                # Очищаем от недопустимых символов в имени файла
                safe_name = "".join(c for c in custom_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
                if not safe_name:
                    safe_name = f"партия_{self.batch_index}"
                batch_name = f"{safe_name}_{timestamp}"
            else:
                batch_name = f"партия_{self.batch_index}_{timestamp}"

            # Создаем путь к папке партии
            self.current_batch_path = self.base_dir / batch_name
            print(f"Полный путь к папке партии: {self.current_batch_path.absolute()}")

            # Создаем папку партии
            print(f"Создаем папку партии...")
            self.current_batch_path.mkdir(parents=True, exist_ok=True)
            print(f"Папка партии создана: {self.current_batch_path}")

            # Создаем подпапки для каждой камеры
            for i in range(3):  # 3 камеры
                (self.current_batch_path / f"Camera_{i}").mkdir(exist_ok=True)

            # Создаем папку для метаданных
            metadata_dir = self.current_batch_path / "metadata"
            metadata_dir.mkdir(exist_ok=True)

            # Инициализируем статистику партии
            self.batch_stats = {
                "batch_name": batch_name,
                "start_time": timestamp,
                "end_time": "",
                "total_checked": 0,
                "total_good": 0,
                "total_bad": 0,
                "defects_by_type": defaultdict(int),
                "multiple_defects": 0,
                "defects_details": defaultdict(list)
            }

            # Сохраняем начальную статистику
            self._save_batch_stats()

            # Сохраняем информацию о партии в data папку
            info_file = Path("data") / f"batch_{self.batch_index}_info.json"

            # Создаем папку data, если нет
            info_file.parent.mkdir(exist_ok=True)

            batch_info = {
                "batch_name": batch_name,
                "start_time": timestamp,
                "batch_index": self.batch_index,
                "batch_path": str(self.current_batch_path),
                "is_active": True
            }

            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(batch_info, f, indent=2, ensure_ascii=False)
            print(f"Информация о партии сохранена")

            # Сохраняем индекс
            self._save_batch_index()

            print(f"Успешно создана новая партия")
            return self.current_batch_path

        except Exception as e:
            print(f"Критическая ошибка при создании партии: {e}")
            import traceback
            traceback.print_exc()
            return None

    def save_screenshot_metadata(self, timestamp, camera_data_list, verdict, defect_types):
        """
        Сохраняет метаданные скриншота.
        """
        if not self.is_batch_active():
            return

        # Проверяем, был ли брак разновысотности
        has_uneven_defect = 2 in defect_types

        metadata = {
            "timestamp": timestamp,
            "screenshot_name": f"{timestamp}.jpg",
            "verdict": verdict,
            "defect_types": defect_types,
            "cameras": {}
        }

        camera_names = {
            0: "Ближняя камера",
            1: "Центральная камера",
            2: "Дальняя камера"
        }

        for i in range(3):
            camera_key = f"camera_{i}"
            camera_name = camera_names.get(i, f"Камера {i}")

            if i < len(camera_data_list):
                camera_data = camera_data_list[i]
                if camera_data:
                    # Если брака разновысотности нет – удаляем все объекты этого типа
                    if not has_uneven_defect:
                        filtered_objects = [obj for obj in camera_data if obj.get("class_name") != "uneven_heights"]
                    else:
                        filtered_objects = camera_data

                    if filtered_objects:
                        metadata["cameras"][camera_key] = {
                            "name": camera_name,
                            "status": "Объекты обнаружены",
                            "objects": filtered_objects
                        }
                    else:
                        metadata["cameras"][camera_key] = {
                            "name": camera_name,
                            "status": "Дефектов не обнаружено",
                            "objects": []
                        }
                else:
                    metadata["cameras"][camera_key] = {
                        "name": camera_name,
                        "status": "Дефектов не обнаружено",
                        "objects": []
                    }
            else:
                metadata["cameras"][camera_key] = {
                    "name": camera_name,
                    "status": "Данные отсутствуют",
                    "objects": []
                }

        # Сохраняем метаданные в JSON файл
        metadata_file = self.current_batch_path / "metadata" / f"{timestamp}.json"
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False, default=str)
            print(f"Метаданные сохранены: {metadata_file}")
        except Exception as e:
            print(f"Ошибка сохранения метаданных: {e}")

        # Сохраняем в CSV для удобства анализа
        self._save_to_csv(timestamp, camera_data_list, verdict, defect_types)

    def _save_to_csv(self, timestamp, camera_data_list, verdict, defect_types):
        """Сохраняет данные в CSV файл."""
        csv_file = self.current_batch_path / "screenshots_log.csv"

        # Если файл не существует, создаем его с заголовком
        if not csv_file.exists():
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'screenshot_name', 'verdict', 'defect_types',
                    'camera_0_status', 'camera_0_objects_count',
                    'camera_1_status', 'camera_1_objects_count',
                    'camera_2_status', 'camera_2_objects_count'
                ])

        # Подготавливаем данные для CSV
        camera_statuses = []
        camera_counts = []

        for i in range(3):
            if i < len(camera_data_list):
                camera_data = camera_data_list[i]
                if camera_data:
                    camera_statuses.append("Объекты обнаружены")
                    camera_counts.append(len(camera_data))
                else:
                    camera_statuses.append("Дефектов не обнаружено")
                    camera_counts.append(0)
            else:
                camera_statuses.append("Данные отсутствуют")
                camera_counts.append(0)

        # Записываем строку в CSV
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                timestamp, f"{timestamp}.jpg", verdict, str(defect_types),
                camera_statuses[0], camera_counts[0],
                camera_statuses[1], camera_counts[1],
                camera_statuses[2], camera_counts[2]
            ])

    def update_batch_stats(self, verdict, defect_types, object_data=None):
        """
        Обновляет статистику партии.
        """
        if not self.is_batch_active():
            return

        self.batch_stats["total_checked"] += 1

        # Очищаем object_data от поля 'segment' для экономии места
        object_data_clean = None
        if object_data:
            object_data_clean = []
            for obj in object_data:
                obj_clean = obj.copy()
                obj_clean.pop('segment', None)
                object_data_clean.append(obj_clean)

        if verdict == 0:
            self.batch_stats["total_good"] += 1
        else:
            self.batch_stats["total_bad"] += 1

            # Если несколько типов брака
            if len(defect_types) > 1:
                self.batch_stats["multiple_defects"] += 1
                self.batch_stats["defects_by_type"]["multiple"] += 1
                self.batch_stats["defects_details"]["multiple"].append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "defect_types": defect_types,
                    "object_data": object_data_clean  # <-- очищенные данные
                })
            else:
                # Один тип брака
                defect_type = defect_types[0]
                self.batch_stats["defects_by_type"][defect_type] += 1
                self.batch_stats["defects_details"][defect_type].append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "defect_type": defect_type,
                    "object_data": object_data_clean  # <-- очищенные данные
                })

        # Сохраняем обновлённую статистику
        self._save_batch_stats()

    def _save_batch_stats(self):
        """Сохраняет статистику партии в файл."""
        if not self.current_batch_path:
            return

        stats_file = self.current_batch_path / "batch_statistics.json"

        # Преобразуем defaultdict в обычные dict для сериализации
        stats = self.batch_stats.copy()
        stats["defects_by_type"] = dict(stats["defects_by_type"])

        # Преобразуем defects_details
        details_dict = {}
        for key, value in stats["defects_details"].items():
            details_dict[str(key)] = value
        stats["defects_details"] = details_dict

        try:
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False, default=str)
            print(f"Статистика партии сохранена: {stats_file}")
        except Exception as e:
            print(f"Ошибка сохранения статистики партии: {e}")

    def get_camera_batch_dir(self, camera_id):
        """
        Возвращает путь к папке камеры в текущей партии.
        Если партия не начата, возвращает None.
        """
        if self.current_batch_path is None:
            return None

        camera_dir = self.current_batch_path / f"Camera_{camera_id}"
        camera_dir.mkdir(exist_ok=True)
        return camera_dir

    def get_current_batch_info(self):
        """Возвращает информацию о текущей партии."""
        if self.current_batch_path is None:
            return None

        # Ищем информацию в папке data
        info_file = Path("data") / f"batch_{self.batch_index}_info.json"
        if info_file.exists():
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    return info
            except Exception as e:
                print(f"Ошибка загрузки информации о партии: {e}")
                pass

        # Если файл не найден, создаем базовую информацию
        return {
            "batch_name": self.current_batch_path.name,
            "batch_index": self.batch_index,
            "batch_path": str(self.current_batch_path),
            "is_active": True
        }

    def is_batch_active(self):
        """Проверяет, активна ли партия."""
        return self.current_batch_path is not None

    def finish_batch(self):
        """Завершает текущую партию."""
        if self.current_batch_path:
            finished_batch_path = self.current_batch_path

            # Обновляем время окончания
            self.batch_stats["end_time"] = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self._save_batch_stats()

            # Обновляем информацию о партии в data
            info_file = Path("data") / f"batch_{self.batch_index}_info.json"
            if info_file.exists():
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        info = json.load(f)

                    info["is_active"] = False
                    info["end_time"] = self.batch_stats["end_time"]

                    with open(info_file, 'w', encoding='utf-8') as f:
                        json.dump(info, f, indent=2, ensure_ascii=False)

                except Exception as e:
                    print(f"Ошибка обновления информации о партии: {e}")

            # Сначала пробуем догрузить старые JSON, если ПК аналитики раньше был выключен
            try:
                sync_local_queue()
            except Exception as e:
                print(f"Ошибка догрузки старых JSON на ПК аналитики: {e}")

            # Отправляем JSON текущей завершенной партии
            try:
                send_batch_json(finished_batch_path)
            except Exception as e:
                print(f"Ошибка отправки batch_statistics.json на ПК аналитики: {e}")

            # Вызываем callback, если он задан
            if self.on_batch_finished:
                try:
                    self.on_batch_finished(finished_batch_path)
                except Exception as e:
                    print(f"Ошибка в callback завершения партии: {e}")

            print(f"Партия завершена: {finished_batch_path}")
            self.current_batch_path = None
    #
    # def cleanup_incomplete_batches(self):
    #     """
    #     Очищает информацию о неполных партиях (у которых есть info файл, но нет папки).
    #     """
    #     data_dir = Path("data")
    #     if not data_dir.exists():
    #         return
    #
    #     for info_file in data_dir.glob("batch_*_info.json"):
    #         try:
    #             with open(info_file, 'r', encoding='utf-8') as f:
    #                 info = json.load(f)
    #
    #             batch_path = Path(info.get("batch_path", ""))
    #             if not batch_path.exists():
    #                 print(f"Удаляем информацию о несуществующей партии: {info_file}")
    #                 info_file.unlink()
    #
    #         except Exception as e:
    #             print(f"Ошибка при очистке партии {info_file}: {e}")