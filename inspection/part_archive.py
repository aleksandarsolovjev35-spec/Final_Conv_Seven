"""Архивация результатов инспекции каждой детали.

Для детали сохраняются исходные кадры, сырые оверлеи, кадры с разметкой
правил и ``meta.json``. При завершении партии каталог упаковывается в
ZIP Deflate (выполняет :class:`inspection.batch_manager.BatchManager`).

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

Партия, открытая оператором, доживает до нового запуска программы: экземпляр
архива восстанавливается методом :meth:`PartArchive.resume`, а манифест
``batch.json`` со статусом ``OPEN`` служит точкой возобновления учёта.
"""

import contextlib
import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime

import cv2


# Имя партии превращается в компонент пути: остаются буквы (в том числе
# кириллица), цифры, точка, тире и подчёркивание. Всё остальное — «_»,
# ведущие точки и повторы «_» убираются, поэтому «..» через имя партии
# не может вывести запись за пределы корня архива.
_COMPONENT_ALLOWED = re.compile(r"[^0-9A-Za-zА-Яа-яЁё._-]+")
_DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalise_root(root_folder: str) -> str:
    """Абсолютный путь корня архива из значения конфигурации."""
    text = str(root_folder or "").strip()
    if not text:
        raise ValueError("Папка архива не указана")
    return os.path.abspath(
        os.path.expandvars(os.path.expanduser(text))
    )


def validate_root(root_folder: str) -> dict:
    """Проверить, что корень архива существует и доступен на запись."""
    candidate = normalise_root(root_folder)
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


def safe_component(text: str, *, limit: int = 40) -> str:
    """Компонент пути из человекочитаемого названия партии."""
    value = str(text or "").strip()
    value = _COMPONENT_ALLOWED.sub("_", value)
    value = re.sub(r"_{2,}", "_", value).strip("._")
    return value[:limit]


def safe_date_folder(value) -> str:
    """Каталог даты: ``YYYY-MM-DD`` или сегодняшняя дата."""
    text = str(value or "").strip()
    if _DATE_FOLDER.match(text):
        return text
    return datetime.now().strftime("%Y-%m-%d")


class PartArchive:
    """Архиватор деталей: копит кадры по стадиям и пишет их на диск."""

    # Политика архива фиксирована: всегда сохраняем, максимальное качество
    # JPEG в принятом диапазоне приложения, при выходе — ZIP с удалением
    # исходной папки только после проверки CRC.
    JPEG_QUALITY = 98
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
        *,
        date_folder: str | None = None,
        operator: str = "",
        label: str = "",
        batch_folder: str | None = None,
    ):
        self.root_folder = normalise_root(root_folder)

        if batch_id is None:
            batch_id = datetime.now().strftime("batch_%Y%m%d_%H%M%S")
        self.batch_id = self._safe_name(batch_id)
        self.date_folder = safe_date_folder(date_folder)
        # Путь партии задаёт оператор (поле «ПУТЬ ПАРТИИ» в карточке): папка
        # партии может лежать вне корня архива. Пусто — папка собирается как
        # <корень>/<дата>/<код партии>.
        self._batch_folder = (
            os.path.abspath(os.path.expandvars(os.path.expanduser(
                str(batch_folder).strip()
            )))
            if str(batch_folder or "").strip() else None
        )
        # Оператор и номер партии — обязательная часть учёта: они попадают
        # и в манифест партии, и в meta.json каждой детали.
        self.operator = self.normalise_operator(operator)
        # Номер партии: пустая строка означает «взять из манифеста или
        # показать код партии» — так продолжение партии не теряет номер,
        # который ввёл оператор при её открытии.
        self.label = str(label or "").strip()
        self.batch_started_at = datetime.now().isoformat(timespec="seconds")

        # Буфер хранит уже JPEG-encoded bytes по ролям.
        self._buffers: dict[int, dict] = {}
        self._archived: list[dict] = []
        self._batch_parts: list[dict] = []
        self._batch_stats = {"total": 0, "good": 0, "bad": 0, "cleanup": 0}

        self.stats: dict = self._load_stats()

        try:
            os.makedirs(self.root_folder, exist_ok=True)
        except OSError as exc:
            print(f"[ARCHIVE] Папка архива недоступна: {exc}")

    # ---------- свойства ----------

    @property
    def batch_folder(self) -> str:
        if self._batch_folder:
            return self._batch_folder
        return os.path.join(self.root_folder, self.date_folder, self.batch_id)

    @property
    def display_label(self) -> str:
        """Номер партии для документов и HMI (код партии как запасной)."""
        return self.label or self.batch_id

    @property
    def counts(self) -> dict:
        """Счётчики партии: их читает менеджер партий и HMI."""
        return dict(self._batch_stats)

    @property
    def last_part_id(self) -> int:
        """Наибольший номер детали в партии (нумерация продолжается с него).

        Продолжение партии обязано писать новые детали в свободные имена
        ``part_NNNN``: нумерация берётся не из счётчика запуска программы,
        а из манифеста, иначе новый сеанс затрёт уже сохранённые детали.
        """
        ids = [
            int(item.get("part_id") or 0)
            for item in self._batch_parts
            if str(item.get("part_id") or "").lstrip("-").isdigit()
        ]
        return max(ids) if ids else 0

    @classmethod
    def normalise_category(cls, category: str) -> str:
        value = str(category or "").upper()
        return value if value in cls.CATEGORY_DIRS else "BAD"

    @staticmethod
    def normalise_operator(operator: str) -> str:
        """ФИО оператора без лишних пробелов по краям и внутри."""
        return " ".join(str(operator or "").split())

    @staticmethod
    def _normalise_root(root_folder: str) -> str:
        return normalise_root(root_folder)

    @classmethod
    def validate_root(cls, root_folder: str) -> dict:
        return validate_root(root_folder)

    @classmethod
    def resume(
        cls,
        root_folder: str,
        *,
        batch_id: str,
        date_folder: str,
        operator: str = "",
        label: str = "",
        batch_folder: str | None = None,
    ) -> "PartArchive":
        """Восстановить открытую партию для продолжения учёта.

        Счётчики и список деталей берутся из ``batch.json``: следующий
        ``finalize`` продолжит нумерацию и манифест, а не начнёт партию
        заново.
        """
        archive = cls(
            root_folder,
            batch_id=batch_id,
            date_folder=date_folder,
            operator=operator,
            label=label,
            batch_folder=batch_folder,
        )
        archive._restore_manifest()
        return archive

    def _restore_manifest(self) -> bool:
        """Прочитать манифест существующей партии; True — партия найдена."""
        manifest_path = os.path.join(self.batch_folder, "batch.json")
        try:
            with open(manifest_path, encoding="utf-8") as stream:
                manifest = json.load(stream)
        except (OSError, ValueError) as exc:
            print(f"[ARCHIVE] Манифест партии не прочитан ({exc})")
            return False
        if not isinstance(manifest, dict):
            return False

        if not str(self.operator or "").strip():
            self.operator = self.normalise_operator(
                manifest.get("operator") or ""
            )
        self.label = (
            str(self.label or "").strip()
            or str(manifest.get("batch_label") or "").strip()
        )
        started_at = str(manifest.get("started_at") or "").strip()
        if started_at:
            self.batch_started_at = started_at

        parts = []
        for item in manifest.get("parts") or []:
            if not isinstance(item, dict):
                continue
            parts.append({
                "part_id": item.get("part_id"),
                "category": item.get("category"),
                "decision": item.get("decision"),
                "folder": os.path.join(
                    self.batch_folder, str(item.get("folder") or ""),
                ).replace("\\", "/"),
                "relative_folder": item.get("folder"),
                "roles": list(item.get("roles") or []),
                "time": item.get("time"),
            })
        self._batch_parts = parts
        self._archived = list(parts)

        counts = manifest.get("counts")
        if isinstance(counts, dict):
            restored = {
                key: max(0, int(counts.get(key) or 0))
                for key in ("total", "good", "bad", "cleanup")
            }
            # Учёт корпусов нулевого доверия: детали в манифесте — источник
            # истины, счётчики уточняются по нему.
            restored["total"] = max(restored["total"], len(parts))
            self._batch_stats = restored
        print(
            f"[ARCHIVE] Партия {self.batch_id} продолжена: "
            f"учтено корпусов {self._batch_stats['total']}"
        )
        return True

    def can_reconfigure(self) -> bool:
        return not self._buffers and not self._archived and not os.path.exists(
            self.batch_folder
        )

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
            "batch_label": self.display_label,
            "operator": self.operator,
            "batch_stats": dict(self._batch_stats),
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
            "batch_label": self.display_label,
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
            "folder": folder_path.replace("\\", "/"),
            "relative_folder": relative_folder,
            "roles": roles_saved,
            "time": now.strftime("%H:%M:%S"),
        }
        self._archived.append(item)
        self._batch_parts.append(dict(item))

        self.stats["total"] = int(self.stats.get("total") or 0) + 1
        category_key = {
            "GOOD": "good", "BAD": "bad", "CLEANUP": "cleanup",
        }[stored_category]
        self.stats[category_key] = int(self.stats.get(category_key) or 0) + 1
        self._batch_stats["total"] += 1
        self._batch_stats[category_key] += 1
        self._save_stats()
        self._save_batch_manifest()

        print(
            f"[ARCHIVE] Деталь #{part_id} -> {folder_path} "
            f"({len(roles_saved)} ролей)"
        )
        return folder_path

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
            "batch_label": self.display_label,
            "operator": self.operator,
            "date": self.date_folder,
            "started_at": self.batch_started_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "root_path": self.root_folder,
            "counts": dict(self._batch_stats),
            "parts": [
                {
                    "part_id": item["part_id"],
                    "category": item["category"],
                    "decision": item["decision"],
                    "folder": item["relative_folder"],
                    "time": item["time"],
                }
                for item in self._batch_parts
            ],
        }
        self._write_json(os.path.join(self.batch_folder, "batch.json"), manifest)

    def open_manifest(self) -> None:
        """Создать манифест партии со статусом ``OPEN``.

        Вызывается сразу при открытии партии оператором: партия становится
        видимой на диске ещё до первой детали, а после перезапуска
        программы её можно найти и продолжить.
        """
        self._save_batch_manifest(status="OPEN")

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
        """Упаковать партию в ZIP и удалить папку после проверки CRC."""
        batch_folder = self.batch_folder
        if not os.path.isdir(batch_folder):
            return None
        with os.scandir(batch_folder) as entries:
            if not any(entries):
                return None

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
    def _safe_name(name: str) -> str:
        if not name:
            return "none"
        return (
            name.replace("/", "_")
            .replace("\\", "_")
            .replace(" ", "_")
            .replace(":", "_")
            [:50]
        )
