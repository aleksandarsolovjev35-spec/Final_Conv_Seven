"""Архивация результатов инспекции каждой детали.

Для детали сохраняются исходные кадры, сырые оверлеи, кадры с разметкой
правил и ``meta.json``. При завершении партии каталог можно упаковать в
ZIP Deflate.

В открытой партии изображения хранятся только для последних
``MAX_RETAINED_PARTS`` корпусов: картинки старших корпусов удаляются
при появлении нового корпуса, а их метаданные, записи в манифесте и
статистика партии сохраняются. При закрытии партии все изображения
удаляются до упаковки: в ZIP-архив остаются только метаданные,
манифест и статистика.

Структура::

    <root>/<date>/<batch>/
      batch.json
      stats.json            (на уровень выше, в <root>)
      GOOD/part_0001/
      BAD/part_0002/
      CLEANUP/part_0003/
        meta.json
        <ROLE>.jpg          — исходный кадр
        <ROLE>_raw.jpg      — сырые детекции нейросети (если есть)
        <ROLE>_debug.jpg    — разметка правил (если есть)
"""

import contextlib
import json
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path

import cv2

from config.operator_store import normalise_operator_fio


class PartArchive:
    """Архиватор деталей: копит кадры по стадиям и пишет их на диск.

    В открытой партии изображения остаются только для последних
    ``retained_parts`` корпусов: при появлении нового корпуса картинки
    старших корпусов удаляются, а их метаданные и статистика партии
    сохраняются.
    """

    # Политика архива фиксирована: всегда сохраняем, максимальное качество
    # JPEG в принятом диапазоне приложения, при выходе — ZIP с удалением
    # исходной папки только после проверки CRC. Изображения остаются только
    # для последних корпусов партии, старые корпуса заменяются новыми.
    JPEG_QUALITY = 98
    MAX_RETAINED_PARTS = 10
    SCHEMA_VERSION = 2
    CATEGORY_DIRS = {
        "GOOD": "GOOD",
        "BAD": "BAD",
        "CLEANUP": "CLEANUP",
    }
    CATEGORY_LABELS = {
        "GOOD": "ГОДНОЕ",
        "BAD": "БРАК",
        "CLEANUP": "ЗАЧИСТКА",
    }
    STATS_FILE = "stats.json"

    def __init__(
        self,
        root_folder: str = "archive",
        batch_id: str | None = None,
        operator: str | None = None,
        *,
        create_manifest: bool = False,
        date_folder: str | None = None,
        retained_parts: int | None = None,
    ):
        self.root_folder = self._normalise_root(root_folder)
        self.date_folder = date_folder or datetime.now().strftime("%Y-%m-%d")

        limit = self.MAX_RETAINED_PARTS if retained_parts is None else int(retained_parts)
        if limit < 1:
            raise ValueError("В партии должен оставаться хотя бы один корпус")
        self.retained_parts = limit

        if batch_id is None:
            batch_id = self.generate_batch_id(
                self.root_folder, date_folder=self.date_folder,
            )
        self.batch_id = self._safe_name(batch_id)
        self.batch_started_at = datetime.now().isoformat(timespec="seconds")
        self.status = "OPEN"
        self.keep_open_on_shutdown = False
        self.operator: str = (
            normalise_operator_fio(operator)
            if isinstance(operator, str) and operator.strip()
            else ""
        )
        self.operators = [self.operator] if self.operator else []
        self.created_by = self.operator

        # Буфер хранит уже JPEG-encoded bytes по ролям.
        self._buffers: dict[int, dict] = {}
        self._archived: list[dict] = []
        self._batch_parts: list[dict] = []
        self._batch_stats = {"total": 0, "good": 0, "bad": 0, "cleanup": 0}
        self.next_part_id = 1

        self.stats: dict = self._load_stats()

        try:
            os.makedirs(self.root_folder, exist_ok=True)
            if create_manifest:
                os.makedirs(self.batch_folder, exist_ok=True)
                self._save_batch_manifest(status="OPEN")
        except OSError as exc:
            print(f"[ARCHIVE] Папка архива недоступна: {exc}")

    # ---------- свойства ----------

    @property
    def batch_folder(self) -> str:
        return os.path.join(self.root_folder, self.date_folder, self.batch_id)

    @classmethod
    def normalise_category(cls, category: str) -> str:
        value = str(category or "").upper()
        return value if value in cls.CATEGORY_DIRS else "BAD"

    @staticmethod
    def _normalise_root(root_folder: str) -> str:
        text = str(root_folder or "").strip()
        if not text:
            raise ValueError("Папка архива не указана")
        return os.path.abspath(
            os.path.expandvars(os.path.expanduser(text))
        )

    @classmethod
    def validate_root(cls, root_folder: str) -> dict:
        candidate = cls._normalise_root(root_folder)
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(
                candidate,
                f".archive_write_test_{os.getpid()}_{time.time_ns()}",
            )
            with open(probe, "xb") as stream:
                stream.write(b"ok")
                stream.flush()
                os.fsync(stream.fileno())
            os.remove(probe)
            usage = shutil.disk_usage(candidate)
        except OSError as exc:
            raise ValueError(f"Папка архива недоступна: {exc}") from exc
        return {
            "path": candidate,
            "writable": True,
            "free_bytes": int(usage.free),
            "free_mb": round(usage.free / (1024 * 1024), 1),
        }

    def can_reconfigure(self) -> bool:
        return not self._buffers and not self._archived and not os.path.exists(
            self.batch_folder
        )

    @classmethod
    def generate_batch_id(
        cls,
        root_folder: str,
        *,
        date_folder: str | None = None,
    ) -> str:
        """Create a date-stamped numeric ID without a textual prefix."""
        root = cls._normalise_root(root_folder)
        date_value = date_folder or datetime.now().strftime("%Y-%m-%d")
        date_parts = date_value.split("-")
        if len(date_parts) != 3 or not all(part.isdigit() for part in date_parts):
            raise ValueError("Недопустимая дата партии")
        date_key = "_".join(date_parts)
        existing_numbers = []
        for item in cls.list_batches(root):
            parts = item["batch_id"].split("_")
            if len(parts) == 4 and parts[1:] == date_parts and parts[0].isdigit():
                existing_numbers.append(int(parts[0]))
        number = max(existing_numbers, default=0) + 1
        while True:
            batch_id = f"{number:04d}_{date_key}"
            folder = os.path.join(root, date_value, batch_id)
            if not os.path.exists(folder) and not os.path.exists(folder + ".zip"):
                return batch_id
            number += 1

    @classmethod
    def list_batches(cls, root_folder: str) -> list[dict]:
        """Return discoverable unpacked batches and closed ZIP archives."""
        root = Path(cls._normalise_root(root_folder))
        batches = []
        if not root.is_dir():
            return batches
        for date_dir in root.iterdir():
            if not date_dir.is_dir():
                continue
            for folder in date_dir.iterdir():
                manifest_path = folder / "batch.json"
                if not folder.is_dir() or not manifest_path.is_file():
                    continue
                try:
                    with manifest_path.open(encoding="utf-8") as stream:
                        manifest = json.load(stream)
                except (OSError, ValueError):
                    continue
                if isinstance(manifest, dict):
                    batches.append(cls._batch_listing(
                        manifest, folder.name, str(folder),
                    ))
        for zip_path in root.rglob("*.zip"):
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    manifest = json.loads(archive.read("batch.json"))
            except (OSError, KeyError, ValueError, zipfile.BadZipFile):
                continue
            if isinstance(manifest, dict):
                batches.append(cls._batch_listing(
                    manifest, zip_path.stem, str(zip_path), zipped=True,
                ))
        return sorted(
            batches, key=lambda item: item.get("updated_at", ""), reverse=True,
        )

    @staticmethod
    def operator_breakdown(parts, known_operators=(), fallback_operator=""):
        """Посчитать, сколько деталей провёл каждый оператор партии.

        ``parts`` — записи деталей (как в манифесте ``batch.json``); у каждой
        записи берётся ``operator``. Записи без оператора (старые манифесты)
        приписываются создателю партии ``fallback_operator``. Операторы из
        ``known_operators`` попадают в отчёт, даже если не провели деталей.
        Возвращается список словарей ``operator``/``parts``/``good``/``bad``/
        ``cleanup``, отсортированный по числу деталей (убывание).
        """
        totals = {}

        def bucket(name):
            label = " ".join(str(name or "").split())
            if not label:
                label = " ".join(str(fallback_operator or "").split()) or "—"
            return totals.setdefault(label.casefold(), {
                "operator": label,
                "parts": 0,
                "good": 0,
                "bad": 0,
                "cleanup": 0,
            })

        for name in known_operators:
            bucket(name)
        for part in parts or []:
            entry = bucket((part or {}).get("operator") or fallback_operator)
            entry["parts"] += 1
            category = str((part or {}).get("category") or "").lower()
            if category in ("good", "bad", "cleanup"):
                entry[category] += 1
        return sorted(
            totals.values(),
            key=lambda entry: (-entry["parts"], entry["operator"]),
        )

    @classmethod
    def _batch_listing(cls, manifest, batch_id, path, zipped=False):
        counts = manifest.get("counts") or {}
        creator = manifest.get("created_by") or manifest.get("operator", "")
        operators = manifest.get("operators") or (
            [manifest["operator"]] if manifest.get("operator") else []
        )
        known = list(operators)
        if creator:
            known.append(creator)
        return {
            "batch_id": str(manifest.get("batch_id") or batch_id),
            "date": manifest.get("date", ""),
            "started_at": manifest.get("started_at", ""),
            "updated_at": manifest.get("updated_at", ""),
            "status": "CLOSED" if zipped else str(
                manifest.get("status") or "OPEN"
            ).upper(),
            "counts": {
                key: int(counts.get(key, 0) or 0)
                for key in ("total", "good", "bad", "cleanup")
            },
            "operator": manifest.get("operator", ""),
            "created_by": creator,
            "operators": operators,
            "operator_stats": cls.operator_breakdown(
                manifest.get("parts") or [], known, creator,
            ),
            "path": path,
            "zipped": zipped,
        }

    @classmethod
    def resume(cls, root_folder: str, batch_id: str) -> "PartArchive":
        """Restore an unpacked OPEN batch and continue its part numbering."""
        safe_id = cls.validate_batch_id(batch_id)
        root = cls._normalise_root(root_folder)
        candidates = [
            Path(root) / date_dir / safe_id
            for date_dir in os.listdir(root)
            if os.path.isdir(os.path.join(root, date_dir))
        ] if os.path.isdir(root) else []
        folder = next((path for path in candidates if path.is_dir()), None)
        if folder is None:
            raise ValueError("Открытая партия не найдена")
        manifest_path = folder / "batch.json"
        try:
            with manifest_path.open(encoding="utf-8") as stream:
                manifest = json.load(stream)
        except (OSError, ValueError) as exc:
            raise ValueError("Не удалось прочитать манифест партии") from exc
        if str(manifest.get("status", "OPEN")).upper() != "OPEN":
            raise ValueError("Можно продолжить только открытую партию")
        obj = cls(
            root, safe_id, manifest.get("operator"),
            date_folder=folder.parent.name,
        )
        obj.batch_started_at = manifest.get("started_at") or obj.batch_started_at
        obj.created_by = (
            manifest.get("created_by") or manifest.get("operator") or ""
        )
        obj.operators = list(manifest.get("operators") or [])
        if obj.operator and obj.operator not in obj.operators:
            obj.operators.append(obj.operator)
        obj._batch_parts = []
        for meta_path in folder.glob("**/part_*/meta.json"):
            try:
                with meta_path.open(encoding="utf-8") as stream:
                    meta = json.load(stream)
            except (OSError, ValueError):
                continue
            part_id = int(meta.get("part_id", 0) or 0)
            category = cls.normalise_category(meta.get("category", "BAD"))
            relative = os.path.relpath(meta_path.parent, folder).replace("\\", "/")
            item = {
                "part_id": part_id, "category": category,
                "decision": meta.get("decision", ""),
                "operator": meta.get("operator", ""),
                "folder": str(meta_path.parent),
                "relative_folder": relative,
                "roles": meta.get("roles", []),
                "time": meta.get("time", ""),
            }
            obj._batch_parts.append(item)
            obj._archived.append(item)
        obj._batch_parts.sort(key=lambda item: item["part_id"])
        obj._archived = list(obj._batch_parts)
        # Счётчики партии накопительные: в манифесте они хранятся даже
        # после удаления изображений старших корпусов по лимиту retention.
        counts = {"total": 0, "good": 0, "bad": 0, "cleanup": 0}
        stored_counts = manifest.get("counts") or {}
        for key in counts:
            value = stored_counts.get(key)
            if (
                isinstance(value, int) and not isinstance(value, bool)
                and value >= 0
            ):
                counts[key] = value
        if counts["total"] <= 0:
            # Старый манифест без счётчиков: пересчитать из оставшихся папок.
            for item in obj._batch_parts:
                counts["total"] += 1
                counts[item["category"].lower()] += 1
        obj._batch_stats = counts
        obj.next_part_id = max((item["part_id"] for item in obj._batch_parts), default=0) + 1
        obj._prune_retained_parts()
        obj._save_batch_manifest(status="OPEN")
        return obj

    def close_batch(self, sender=None) -> str | None:
        """Close the manifest, queue non-empty results, and ZIP the batch."""
        if self._buffers:
            raise RuntimeError("Дождитесь окончания обработки деталей")
        if not os.path.isdir(self.batch_folder):
            self.status = "CLOSED"
            return None
        if self._batch_stats["total"] <= 0:
            shutil.rmtree(self.batch_folder, ignore_errors=True)
            self.status = "CLOSED"
            return None
        self.close_manifest()
        if sender is not None:
            sender(self.batch_folder)
        result = self.compress()
        if result:
            self.status = "CLOSED"
        return result

    def set_operator(self, operator: str) -> str:
        """Установить ФИО оператора для текущей партии (до начала записи)."""
        if not self.can_reconfigure():
            raise RuntimeError(
                "Оператора можно менять только до начала текущей партии"
            )
        cleaned = normalise_operator_fio(operator)
        self.operator = cleaned
        self.created_by = cleaned
        if cleaned and cleaned not in self.operators:
            self.operators.append(cleaned)
        return cleaned

    def reconfigure(self, *, root_folder) -> dict:
        """Изменить папку до начала партии и применить её сразу."""
        if not self.can_reconfigure():
            raise RuntimeError(
                "Папку архива можно менять только до начала партии"
            )
        self.root_folder = self.validate_root(root_folder)["path"]
        self.stats = self._load_stats()
        return self.get_settings()

    def get_settings(self, validate: bool = True) -> dict:
        validation = None
        if validate:
            try:
                validation = self.validate_root(self.root_folder)
            except ValueError as exc:
                validation = {
                    "path": self.root_folder,
                    "writable": False,
                    "error": str(exc),
                }
        return {
            "root_path": self.root_folder,
            "batch_id": self.batch_id,
            "batch_folder": self.batch_folder,
            "operator": self.operator,
            "batch_stats": dict(self._batch_stats),
            "retained_parts": self.retained_parts,
            "editable": self.can_reconfigure(),
            "validation": validation,
        }

    # ---------- public API ----------

    def store_frames(
        self,
        part_id: int,
        raw_frames: dict,
        annotated_frames: dict,
        raw_overlay_frames: dict | None = None,
    ):
        """Сохранить кадры стадии в буфер (JPEG-bytes)."""
        buf = self._buffers.setdefault(part_id, {})

        for role, frame in (raw_frames or {}).items():
            buf.setdefault(role, {})["raw"] = self._encode_image(frame)

        for role, frame in (annotated_frames or {}).items():
            buf.setdefault(role, {})["debug"] = self._encode_image(frame)

        for role, frame in (raw_overlay_frames or {}).items():
            buf.setdefault(role, {})["raw_overlay"] = self._encode_image(frame)

    def finalize(
        self,
        part_id: int,
        category: str,
        decision: str,
        defects: list,
        step: int,
        extra: dict | None = None,
    ) -> str | None:
        """Записать все кадры детали и meta.json на диск."""
        requested_category = str(category or "").upper()
        stored_category = self.normalise_category(requested_category)
        folder_name = f"part_{part_id:04d}"
        folder_path = os.path.join(
            self.batch_folder, self.CATEGORY_DIRS[stored_category], folder_name,
        )
        os.makedirs(folder_path, exist_ok=True)

        roles_saved = []
        buf = self._buffers.get(part_id, {})
        for role, frames in buf.items():
            for kind, filename in (
                ("raw", f"{role}.jpg"),
                ("raw_overlay", f"{role}_raw.jpg"),
                ("debug", f"{role}_debug.jpg"),
            ):
                content = frames.get(kind)
                if content is not None:
                    self._save_image(content, os.path.join(folder_path, filename))
            roles_saved.append(role)

        now = datetime.now()
        meta = {
            "schema_version": self.SCHEMA_VERSION,
            "part_id": part_id,
            "batch_id": self.batch_id,
            "operator": self.operator,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "step": step,
            "category": stored_category,
            "category_label": self.CATEGORY_LABELS[stored_category],
            "requested_category": requested_category,
            "decision": decision,
            "defects": defects,
            "roles": roles_saved,
            "folder": folder_path.replace("\\", "/"),
        }
        if extra:
            meta.update(extra)

        meta_path = os.path.join(folder_path, "meta.json")
        self._write_json(meta_path, meta)

        self._buffers.pop(part_id, None)
        relative_folder = os.path.relpath(
            folder_path, self.batch_folder,
        ).replace("\\", "/")
        item = {
            "part_id": part_id,
            "category": stored_category,
            "decision": decision,
            "operator": self.operator,
            "folder": folder_path.replace("\\", "/"),
            "relative_folder": relative_folder,
            "roles": roles_saved,
            "time": now.strftime("%H:%M:%S"),
        }
        self._archived.append(item)
        self._batch_parts.append(dict(item))
        self.next_part_id = max(self.next_part_id, int(part_id) + 1)

        self.stats["total"] = int(self.stats.get("total") or 0) + 1
        category_key = {
            "GOOD": "good", "BAD": "bad", "CLEANUP": "cleanup",
        }[stored_category]
        self.stats[category_key] = int(self.stats.get(category_key) or 0) + 1
        self._batch_stats["total"] += 1
        self._batch_stats[category_key] += 1
        self._save_stats()
        self._prune_retained_parts()
        self._save_batch_manifest()

        print(
            f"[ARCHIVE] Деталь #{part_id} -> {folder_path} "
            f"({len(roles_saved)} ролей)"
        )
        return folder_path

    def _prune_retained_parts(self) -> list[int]:
        """Удалить изображения корпусов, вышедших из последних ``retained_parts``.

        В открытой партии изображения остаются только для последних корпусов:
        картинки старших корпусов удаляются, а их ``meta.json``, записи в
        манифесте партии и накопительная статистика сохраняются.

        Возвращает список ID корпусов, для которых удалены изображения.
        """
        ordered = sorted(
            self._archived, key=lambda item: int(item["part_id"]),
        )
        if len(ordered) <= self.retained_parts:
            return []
        keep_ids = {int(item["part_id"]) for item in ordered[-self.retained_parts:]}
        removed = []
        for item in ordered:
            part_id = int(item["part_id"])
            if part_id in keep_ids:
                continue
            folder = item.get("folder") or ""
            if folder:
                self._remove_images(folder)
            removed.append(part_id)
        if removed:
            print(f"[ARCHIVE] Изображения старых корпусов удалены: {removed}")
        return removed

    @staticmethod
    def _remove_images(folder: str) -> int:
        """Удалить кадры корпуса, оставив ``meta.json`` и прочие данные.

        Возвращает количество удалённых изображений.
        """
        try:
            with os.scandir(folder) as entries:
                names = [
                    entry.name for entry in entries
                    if entry.is_file(follow_symlinks=False)
                ]
        except OSError:
            return 0
        removed = 0
        for name in names:
            if not name.lower().endswith(
                (".jpg", ".jpeg", ".png", ".bmp", ".webp"),
            ):
                continue
            with contextlib.suppress(OSError):
                os.remove(os.path.join(folder, name))
                removed += 1
        return removed

    def _strip_batch_images(self) -> int:
        """Удалить все кадры партии, оставив метаданные и статистику.

        При закрытии партии изображения больше не нужны: в ZIP-архив
        аналитику идут ``meta.json``, ``batch.json`` и счётчики партии,
        а картинки только раздувают диск.

        Возвращает количество удалённых изображений.
        """
        total = 0
        folders = 0
        for root, _dirs, _files in os.walk(self.batch_folder):
            removed = self._remove_images(root)
            if removed:
                folders += 1
                total += removed
        if total:
            print(
                f"[ARCHIVE] Изображения удалены перед упаковкой: "
                f"{total} файлов в {folders} папках корпусов"
            )
        return total

    def get_part_info(self, part_id: int) -> dict | None:
        for item in self._archived:
            if item["part_id"] == part_id:
                return item
        return None

    def get_part_images(self, part_id: int) -> dict:
        info = self.get_part_info(part_id)
        if not info:
            return {}
        folder = info["folder"]
        result = {}
        for role in info.get("roles", []):
            entry = {}
            for kind, filename in (
                ("raw", f"{role}.jpg"),
                ("raw_overlay", f"{role}_raw.jpg"),
                ("debug", f"{role}_debug.jpg"),
            ):
                path = os.path.join(folder, filename)
                if os.path.exists(path):
                    entry[kind] = path
            if entry:
                result[role] = entry
        return result

    # ---------- статистика и манифест ----------

    def operator_stats(self) -> list:
        """Вклад каждого оператора в текущую партию (по записям деталей)."""
        known = list(self.operators)
        if self.created_by:
            known.append(self.created_by)
        return self.operator_breakdown(
            self._batch_parts, known, self.created_by,
        )

    def _load_stats(self) -> dict:
        stats = {"total": 0, "good": 0, "bad": 0, "cleanup": 0}
        path = os.path.join(self.root_folder, self.STATS_FILE)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return stats
        if not isinstance(data, dict):
            return stats
        for key in stats:
            value = data.get(key)
            if isinstance(value, int) and value >= 0:
                stats[key] = value
        return stats

    def _save_stats(self):
        self._write_json(
            os.path.join(self.root_folder, self.STATS_FILE), self.stats,
        )

    def _save_batch_manifest(self, status: str = "OPEN"):
        os.makedirs(self.batch_folder, exist_ok=True)
        manifest = {
            "schema_version": self.SCHEMA_VERSION,
            "batch_id": self.batch_id,
            "date": self.date_folder,
            "started_at": self.batch_started_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "operator": self.operator,
            "created_by": self.created_by,
            "operators": list(self.operators),
            "root_path": self.root_folder,
            "counts": dict(self._batch_stats),
            "parts": [
                {
                    "part_id": item["part_id"],
                    "category": item["category"],
                    "decision": item["decision"],
                    "operator": item.get("operator", ""),
                    "folder": item["relative_folder"],
                    "time": item["time"],
                }
                for item in self._batch_parts
            ],
        }
        self._write_json(os.path.join(self.batch_folder, "batch.json"), manifest)

    def close_manifest(self) -> None:
        """Дописать финальный ``batch.json`` со статусом ``CLOSED``.

        Вызывается при завершении программы до отправки манифеста
        аналитику и до сжатия партии: аналитик должен получить закрытую
        партию, а не промежуточный ``OPEN``-манифест. Пустая партия (без
        единой детали) манифеста не создаёт: нечего отправлять и сжимать.
        """
        manifest_path = os.path.join(self.batch_folder, "batch.json")
        if not os.path.exists(manifest_path):
            return
        self._save_batch_manifest(status="CLOSED")

    # ---------- сжатие ----------

    def compress(self) -> str | None:
        """Упаковать партию в ZIP и удалить папку после проверки CRC.

        Изображения удаляются до упаковки: закрытый архив содержит только
        метаданные, манифест и статистику партии.
        """
        batch_folder = self.batch_folder
        if not os.path.isdir(batch_folder):
            return None
        with os.scandir(batch_folder) as entries:
            if not any(entries):
                return None

        self._strip_batch_images()
        self._save_batch_manifest(status="CLOSED")
        zip_path = batch_folder + ".zip"
        temp_zip = zip_path + ".tmp"
        try:
            with zipfile.ZipFile(
                temp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
            ) as zf:
                for root, _dirs, files in os.walk(batch_folder):
                    for filename in files:
                        file_path = os.path.join(root, filename)
                        arcname = os.path.relpath(file_path, batch_folder)
                        zf.write(file_path, arcname)
            with zipfile.ZipFile(temp_zip, "r") as archive:
                bad = archive.testzip()
                if bad is not None:
                    raise RuntimeError(f"ZIP CRC failed: {bad}")
            os.replace(temp_zip, zip_path)
        except Exception as exc:
            print(f"[ARCHIVE] Ошибка сжатия: {exc}")
            if os.path.exists(temp_zip):
                with contextlib.suppress(OSError):
                    os.remove(temp_zip)
            return None

        # Папка удаляется только после полной записи ZIP, проверки CRC и
        # атомарной установки итогового файла.
        with contextlib.suppress(Exception):
            shutil.rmtree(batch_folder)
        return zip_path

    # ---------- внутреннее ----------

    def _encode_image(self, frame) -> bytes:
        try:
            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, self.JPEG_QUALITY],
            )
        except Exception as exc:
            raise RuntimeError(f"Ошибка JPEG-кодирования: {exc}") from exc
        if not ok or encoded is None:
            raise RuntimeError("cv2.imencode вернул ошибку")
        return encoded.tobytes()

    @staticmethod
    def _save_image(content: bytes, path: str):
        temp_path = path + ".tmp"
        try:
            with open(temp_path, "xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except Exception:
            if os.path.exists(temp_path):
                with contextlib.suppress(OSError):
                    os.remove(temp_path)
            raise

    @staticmethod
    def _write_json(path: str, payload):
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)

    @staticmethod
    def validate_batch_id(name: str) -> str:
        value = str(name or "").strip()
        allowed = all(character.isalnum() or character in "._-" for character in value)
        device_names = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{index}" for index in range(1, 10)),
            *(f"LPT{index}" for index in range(1, 10)),
        }
        reserved = value.split(".", 1)[0].upper() in device_names
        if (
            len(value) > 50 or not value[:1].isalnum() or not allowed
            or value.endswith(".") or reserved
        ):
            raise ValueError(
                "ID партии: буквы, цифры, точка, дефис или подчёркивание"
            )
        return value

    @staticmethod
    def _safe_name(name: str) -> str:
        if not name:
            return "none"
        return (
            str(name).replace("/", "_").replace("\\", "_")
            .replace(" ", "_").replace(":", "_")[:50]
        )
