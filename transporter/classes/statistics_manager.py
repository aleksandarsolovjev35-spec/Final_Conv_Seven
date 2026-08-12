import json
from pathlib import Path
from threading import Lock


import json
from pathlib import Path
from threading import Lock


class StatisticsManager:
    def __init__(self):
        self.lock = Lock()
        self.stats_file = Path("data/production_stats.json")
        self.stats = self.load_stats()
        self.thresholds_file = Path("data/thresholds.json")
        self.thresholds = self.load_thresholds()

    def load_stats(self):
        with self.lock:
            if self.stats_file.exists():
                try:
                    with open(self.stats_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception as e:
                    print(f"Ошибка загрузки статистики: {e}")
            return {"total_good": 0, "total_bad": 0, "total_checked": 0}

    def load_thresholds(self):
        # Пороги не требуют частой синхронизации, можно без блокировки
        default_thresholds = {
            'contacts_area': 1400,
            'platform_area_max': 48500,
            'platform_min_width': 110,
            'platform_min_length': 270,
            'omission_distance': 20,
            'flatness_length': 25,
            'flatness_short_angle': 4.5,
            'contacts_long_angle': 5
        }
        if self.thresholds_file.exists():
            try:
                with open(self.thresholds_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    return {**default_thresholds, **loaded}
            except Exception as e:
                print(f"Ошибка загрузки порогов: {e}")
        return default_thresholds

    def save_thresholds(self, thresholds):
        with self.lock:
            try:
                with open(self.thresholds_file, 'w', encoding='utf-8') as f:
                    json.dump(thresholds, f, indent=4, ensure_ascii=False)
                self.thresholds = self.load_thresholds()
            except Exception as e:
                print(f"Ошибка сохранения порогов: {e}")

    def _save_stats(self):
        """Внутренний метод сохранения статистики (предполагается, что блокировка уже взята)"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения статистики: {e}")

    def update_stats(self, good, bad):
        with self.lock:
            self.stats["total_good"] += good
            self.stats["total_bad"] += bad
            self.stats["total_checked"] += (good + bad)
            self._save_stats()

    def get_stats(self):
        with self.lock:
            return self.stats.copy()

    def get_stats_snapshot(self):
        with self.lock:
            return self.stats.copy()

    def reset_stats(self):
        with self.lock:
            self.stats = {"total_good": 0, "total_bad": 0, "total_checked": 0}
            self._save_stats()

    def get_current_stats(self):
        """Получить текущие значения без копирования (для быстрого доступа)"""
        with self.lock:
            return self.stats