"""Менеджер партий: номер партии и учёт корпусов в её составе.

Логика учёта: оператор входит в программу (``OperatorStore``), затем
открывает партию, указав её номер, а программа лишь пишет корпуса в
открытую партию. Незакрытая партия остаётся на диске (папка + манифест
``batch.json`` со статусом ``OPEN``) и после перезапуска продолжается с
того же места: счётчики и список деталей восстанавливаются из манифеста.

Реестр партий хранится рядом с архивом — ``<root>/batches.json``:

.. code-block:: json

    {
      "schema_version": 1,
      "batches": [
        {
          "batch_id": "batch_12.10.2026-1",
          "label": "12.10.2026-1",
          "operator": "Иванов Иван Иванович",
          "started_by": "Иванов Иван Иванович",
          "status": "OPEN",
          "date": "2026-10-12",
          "started_at": "2026-10-12T09:14:02",
          "updated_at": "2026-10-12T09:41:55",
          "closed_at": null,
          "counts": {"total": 12, "good": 9, "bad": 2, "cleanup": 1},
          "zip": null
        }
      ]
    }

Менеджер реализует и архивный контракт (``finalize``, ``store_frames``,
``get_part_info``, ``get_settings``, ``reconfigure``): производственный цикл
работает с ним так же, как раньше с :class:`inspection.part_archive.
PartArchive`, но запись корпуса уходит в ту партию, которую открыл оператор.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from inspection.part_archive import (
    PartArchive,
    normalise_root,
    safe_component,
    validate_root,
)


STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"
REGISTRY_FILE = "batches.json"

OPERATOR_MIN_LENGTH = 3
LABEL_MAX_LENGTH = 40
# Имя папки партии по умолчанию и код партии собираются из одного и того же
# сжатого номера, поэтому подсказка в карточке совпадает с реальным путём.
FOLDER_NAME_LIMIT = 36
RECENT_LIMIT = 5

# Сообщение, которое HMI показывает, когда пуск сделан без номера партии.
# Партию открывает сама кнопка ПУСК: оператор вводит номер (и путь) в
# карточке партии и пускает линию. Оператор берётся из сессии входа.
NO_BATCH_MESSAGE = "Укажите номер партии: ПУСК начнёт учёт в новой партии"


def _empty_counts() -> dict:
    return {"total": 0, "good": 0, "bad": 0, "cleanup": 0}


def _default_batch_sender(batch_folder: str) -> bool:
    """Штатная отправка ``batch.json`` закрытой партии аналитику."""
    from json_sender import send_batch_json

    return send_batch_json(batch_folder)


class BatchManager:
    """Реестр партий и текущая учётная партия для производственного цикла."""

    def __init__(
        self,
        root_folder: str = "archive",
        *,
        registry_file: str = REGISTRY_FILE,
        batch_sender=None,
    ):
        self.registry_file = registry_file
        self.root_folder = normalise_root(root_folder)
        self._lock = threading.RLock()
        self._current: PartArchive | None = None
        self._closed: PartArchive | None = None
        self._registry = self._read_registry()
        self._batch_sender = batch_sender or _default_batch_sender

    # ---------- состояние партии ----------

    @property
    def active(self) -> bool:
        """Открыта ли партия: без неё пуск линии запрещён."""
        return self._current is not None

    @property
    def current(self) -> PartArchive | None:
        return self._current

    @property
    def batch_id(self) -> str | None:
        return self._current.batch_id if self._current else None

    @property
    def batch_folder(self) -> str | None:
        return self._current.batch_folder if self._current else None

    @property
    def registry_path(self) -> str:
        return os.path.join(self.root_folder, self.registry_file)

    def counts(self) -> dict:
        """Счётчики открытой партии (нули, если партия не открыта)."""
        if self._current is None:
            return _empty_counts()
        return dict(self._current.counts)

    def accounting(self) -> dict | None:
        """Счётчики открытой партии для учёта линии и HMI.

        ``None`` означает «партии нет»: производственный цикл в этом случае
        учёт не переключает, а HMI видит нули из ``counts()``.
        """
        with self._lock:
            if self._current is None:
                return None
            counters = dict(self._current.counts)
            counters["last_part_id"] = self._current.last_part_id
            return counters

    def suggest_label(self) -> str:
        """Номер партии по умолчанию: дата и порядковый номер за день."""
        today = datetime.now().strftime("%Y-%m-%d")
        used = sum(
            1 for item in self._registry["batches"]
            if item.get("date") == today
        )
        return f"{datetime.now().strftime('%d.%m.%Y')}-{used + 1}"

    def today_folder(self) -> str:
        """Каталог даты партий (``YYYY-MM-DD`` в корне хранения)."""
        return datetime.now().strftime("%Y-%m-%d")

    def default_folder(self, label: str = "") -> str:
        """Путь партии по умолчанию: ``<корень>/<дата>/<номер>``.

        По этому пути собирается папка новой партии, если оператор не задал
        свой путь в поле «ПУТЬ ПАРТИИ».
        """
        value = safe_component(label, limit=FOLDER_NAME_LIMIT) or "partiya"
        return os.path.join(self.root_folder, self.today_folder(), value)

    def batch_info(self) -> dict | None:
        """Карточка открытой партии для HMI."""
        current = self._current
        if current is None:
            return None
        entry = self._current_entry()
        return {
            "batch_id": current.batch_id,
            "label": current.display_label,
            "operator": current.operator,
            "status": STATUS_OPEN,
            "date": current.date_folder,
            "started_at": current.batch_started_at,
            "started_by": (entry or {}).get("started_by") or current.operator,
            "counts": dict(current.counts),
            "folder": current.batch_folder,
        }

    def status_payload(self) -> dict:
        """Полное состояние менеджера партий: его читает карточка HMI."""
        with self._lock:
            suggestion = self.suggest_label()
            return {
                "root_path": self.root_folder,
                "date": self.today_folder(),
                "default_folder": self.default_folder(suggestion),
                "active": self.active,
                "batch": self.batch_info(),
                "suggestion": suggestion,
                "open": self._summaries(STATUS_OPEN),
                "recent": self._summaries(STATUS_CLOSED)[-RECENT_LIMIT:],
            }

    # ---------- действия оператора ----------

    def open_batch(
        self,
        *,
        label: str = "",
        operator: str = "",
        batch_id: str | None = None,
        folder: str = "",
    ) -> dict:
        """Начать новую партию или продолжить открытую.

        ``batch_id`` задан — продолжение существующей партии (её номер,
        путь и счётчики берутся из реестра и манифеста), иначе создаётся
        новая партия с введённым номером. ``folder`` — «ПУТЬ ПАРТИИ» из
        карточки: папка, в которую пишется партия; пусто — путь по
        умолчанию от корня хранения.
        """
        operator = PartArchive.normalise_operator(operator)
        self._validate_operator(operator)

        with self._lock:
            if self._current is not None:
                raise RuntimeError(
                    "Партия уже открыта: сначала завершите текущую партию"
                )
            if batch_id:
                entry = self._find_entry(batch_id)
                if entry is None:
                    raise ValueError("Партия не найдена в реестре архива")
                if entry.get("status") != STATUS_OPEN:
                    raise RuntimeError("Партия уже завершена")
                # Путь продолжения берётся из реестра: партия пишется туда,
                # куда её открыли, даже если корень хранения изменился.
                resume_folder = str(
                    folder or entry.get("folder") or ""
                ).strip()
                archive = PartArchive.resume(
                    self.root_folder,
                    batch_id=entry["batch_id"],
                    date_folder=entry.get("date"),
                    operator=operator,
                    label=entry.get("label") or entry["batch_id"],
                    batch_folder=resume_folder or None,
                )
                entry["operator"] = operator
                entry["folder"] = archive.batch_folder
                entry["resumed_at"] = self._now()
                entry["updated_at"] = self._now()
                archive.open_manifest()
                self._current = archive
                action = f"продолжена ({archive.display_label})"
            else:
                label = self._validate_label(label)
                batch_id = self._unique_batch_id(label)
                date_folder = datetime.now().strftime("%Y-%m-%d")
                archive = PartArchive(
                    self.root_folder,
                    batch_id=batch_id,
                    date_folder=date_folder,
                    operator=operator,
                    label=label,
                    batch_folder=self._validated_folder(
                        folder or os.path.join(
                            self.root_folder, date_folder,
                            self._folder_name(batch_id),
                        ),
                    ),
                )
                self._registry["batches"].append({
                    "batch_id": archive.batch_id,
                    "label": label,
                    "operator": operator,
                    "started_by": operator,
                    "status": STATUS_OPEN,
                    "date": archive.date_folder,
                    "folder": archive.batch_folder,
                    "started_at": archive.batch_started_at,
                    "updated_at": archive.batch_started_at,
                    "closed_at": None,
                    "counts": _empty_counts(),
                    "zip": None,
                })
                archive.open_manifest()
                self._current = archive
                action = f"открыта ({label})"

            self._save_registry()
            print(
                f"[BATCH] Партия {archive.batch_id} {action}; "
                f"оператор: {operator}"
            )
            return self.status_payload()

    def finish_batch(self) -> dict:
        """Закрыть партию: манифест CLOSED, отправка аналитику, ZIP."""
        with self._lock:
            current = self._current
            if current is None:
                raise RuntimeError("Партия не открыта")
            entry = self._current_entry()
            batch_id = current.batch_id
            counts = dict(current.counts)
            folder = current.batch_folder
            print(f"[BATCH] Завершение партии {batch_id}...")
            current.close_manifest()
            try:
                self._batch_sender(folder)
            except Exception as exc:
                # Недоступный ПК аналитика не мешает закрыть партию: копия
                # манифеста остаётся в локальной очереди (json_sender).
                print(f"[BATCH] Отправка манифеста не удалась: {exc}")
            zip_path = current.compress()
            self._closed = current
            self._current = None
            if entry is not None:
                entry["status"] = STATUS_CLOSED
                entry["closed_at"] = self._now()
                entry["updated_at"] = entry["closed_at"]
                entry["counts"] = counts
                entry["zip"] = (
                    os.path.basename(zip_path) if zip_path else None
                )
            self._save_registry()
            print(
                f"[BATCH] Партия {batch_id} закрыта"
                + (f", архив: {zip_path}" if zip_path else "")
            )
            return self.status_payload()

    def prepare_shutdown(self) -> None:
        """Завершение программы: партия остаётся открытой для продолжения.

        Партия не закрывается, не сжимается и не отправляется аналитику:
        оператор продолжит её при следующем запуске программы и завершит
        сам. На диск попадают только актуальные счётчики реестра.
        """
        with self._lock:
            current = self._current
            if current is None:
                return
            entry = self._current_entry()
            if entry is not None:
                entry["counts"] = dict(current.counts)
                entry["operator"] = current.operator
                entry["updated_at"] = self._now()
            self._save_registry()
            print(
                f"[BATCH] Партия {current.batch_id} остаётся открытой: "
                f"продолжить можно при следующем запуске "
                f"(учтено корпусов {current.counts['total']})"
            )

    # ---------- архивный контракт для производственного цикла ----------

    def store_frames(
        self,
        part_id: int,
        raw_frames: dict,
        annotated_frames: dict,
        raw_overlay_frames: dict | None = None,
    ) -> None:
        current = self._require_current()
        current.store_frames(
            part_id, raw_frames, annotated_frames, raw_overlay_frames,
        )

    def finalize(
        self,
        part_id: int,
        category: str,
        decision: str,
        defects: list,
        step: int,
        extra: dict | None = None,
    ) -> str | None:
        with self._lock:
            current = self._require_current()
            folder = current.finalize(
                part_id=part_id,
                category=category,
                decision=decision,
                defects=defects,
                step=step,
                extra=extra,
            )
            entry = self._current_entry()
            if entry is not None:
                entry["counts"] = dict(current.counts)
                entry["updated_at"] = self._now()
                self._save_registry()
            return folder

    def get_part_info(self, part_id: int) -> dict | None:
        for archive in (self._current, self._closed):
            if archive is None:
                continue
            info = archive.get_part_info(part_id)
            if info:
                return info
        return None

    def get_part_images(self, part_id: int) -> dict:
        for archive in (self._current, self._closed):
            if archive is None:
                continue
            images = archive.get_part_images(part_id)
            if images:
                return images
        return {}

    # ---------- настройки корня архива ----------

    @staticmethod
    def validate_root(root_folder: str) -> dict:
        return validate_root(root_folder)

    def can_reconfigure(self) -> bool:
        """Папку архива меняют до открытия партии."""
        return self._current is None

    def reconfigure(self, *, root_folder) -> dict:
        if not self.can_reconfigure():
            raise RuntimeError(
                "Папку архива можно менять только до начала партии"
            )
        self.root_folder = validate_root(root_folder)["path"]
        self._registry = self._read_registry()
        return self.get_settings()

    def get_settings(self, validate: bool = True) -> dict:
        validation = None
        if validate:
            try:
                validation = validate_root(self.root_folder)
            except ValueError as exc:
                validation = {
                    "path": self.root_folder,
                    "writable": False,
                    "error": str(exc),
                }
        info = self.batch_info()
        return {
            "root_path": self.root_folder,
            "batch_id": (info or {}).get("batch_id"),
            "batch_folder": (info or {}).get("folder"),
            "batch_label": (info or {}).get("label"),
            "operator": (info or {}).get("operator"),
            "batch_stats": self.counts(),
            "editable": self.can_reconfigure(),
            "validation": validation,
        }

    # ---------- внутреннее ----------

    def _require_current(self) -> PartArchive:
        if self._current is None:
            raise RuntimeError(
                "Партия не открыта: запись корпусов невозможна"
            )
        return self._current

    def _current_entry(self) -> dict | None:
        batch_id = self.batch_id
        return self._find_entry(batch_id) if batch_id else None

    @staticmethod
    def _validated_folder(folder: str) -> str:
        """Проверить «ПУТЬ ПАРТИИ»: папка создаётся и должна быть доступна."""
        try:
            return validate_root(folder)["path"]
        except ValueError as exc:
            raise ValueError(f"Папка партии недоступна: {exc}") from exc

    def _entry_folder(self, item: dict) -> str:
        """Папка партии по записи реестра (со старым форматом без пути)."""
        folder = str(item.get("folder") or "").strip()
        if folder:
            return folder
        return os.path.join(
            self.root_folder,
            str(item.get("date") or ""),
            str(item.get("batch_id") or ""),
        )

    def _find_entry(self, batch_id) -> dict | None:
        for item in self._registry["batches"]:
            if item.get("batch_id") == batch_id:
                return item
        return None

    def _summaries(self, status: str) -> list:
        result = []
        for item in self._registry["batches"]:
            if item.get("status") != status:
                continue
            batch_id = str(item.get("batch_id") or "")
            folder = self._entry_folder(item)
            summary = {
                "batch_id": batch_id,
                "label": item.get("label") or batch_id,
                # Путь партии: его подставляет карточка при выборе
                # незавершённой партии и по нему же продолжает учёт.
                "folder": folder,
                "operator": item.get("operator") or "",
                "status": status,
                "date": item.get("date"),
                "started_at": item.get("started_at"),
                "updated_at": item.get("updated_at"),
                "closed_at": item.get("closed_at"),
                "counts": dict(item.get("counts") or _empty_counts()),
                "zip": item.get("zip"),
                # Папку могли убрать вручную: продолжать такую партию нечем.
                "available": (
                    os.path.isdir(folder) if status == STATUS_OPEN else True
                ),
            }
            result.append(summary)
        return result

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _validate_operator(operator: str) -> None:
        if len(operator) < OPERATOR_MIN_LENGTH:
            raise ValueError("Укажите ФИО оператора")
        if not any(char.isalpha() for char in operator):
            raise ValueError("ФИО оператора должно содержать буквы")

    @staticmethod
    def _validate_label(label: str) -> str:
        value = " ".join(str(label or "").split())
        if not value:
            raise ValueError("Укажите номер партии")
        if len(value) > LABEL_MAX_LENGTH:
            raise ValueError(
                f"Номер партии не длиннее {LABEL_MAX_LENGTH} символов"
            )
        return value

    def _folder_name(self, batch_id: str) -> str:
        """Имя папки партии по её коду: ``batch_П-1`` → ``П-1``."""
        prefix = "batch_"
        return batch_id[len(prefix):] if batch_id.startswith(prefix) else batch_id

    def _unique_batch_id(self, label: str) -> str:
        base = f"batch_{safe_component(label, limit=FOLDER_NAME_LIMIT) or 'partiya'}"
        candidate = base
        index = 2
        existing = {item.get("batch_id") for item in self._registry["batches"]}
        while (
            candidate in existing
            or os.path.exists(os.path.join(
                self.root_folder,
                datetime.now().strftime("%Y-%m-%d"),
                candidate,
            ))
        ):
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _read_registry(self) -> dict:
        registry = {
            "schema_version": 1,
            "batches": [],
        }
        try:
            with open(self.registry_path, encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return registry
        except (OSError, ValueError) as exc:
            print(f"[BATCH] Реестр партий не прочитан: {exc}")
            return registry
        if not isinstance(data, dict):
            return registry

        batches = []
        for item in data.get("batches") or []:
            if not isinstance(item, dict):
                continue
            batch_id = str(item.get("batch_id") or "").strip()
            if not batch_id:
                continue
            status = str(item.get("status") or "").upper()
            batches.append({
                "batch_id": batch_id,
                "label": str(item.get("label") or batch_id).strip(),
                "operator": PartArchive.normalise_operator(
                    item.get("operator") or ""
                ),
                "started_by": PartArchive.normalise_operator(
                    item.get("started_by") or item.get("operator") or ""
                ),
                "status": (
                    status if status in (STATUS_OPEN, STATUS_CLOSED)
                    else STATUS_CLOSED
                ),
                "date": str(item.get("date") or "").strip(),
                # Путь партии задаёт оператор: он же берётся при
                # продолжении, даже если корень хранения изменился.
                "folder": str(item.get("folder") or "").strip(),
                "started_at": str(item.get("started_at") or "").strip(),
                "updated_at": str(item.get("updated_at") or "").strip(),
                "closed_at": item.get("closed_at"),
                "counts": {
                    key: max(0, int((item.get("counts") or {}).get(key) or 0))
                    for key in _empty_counts()
                },
                "zip": item.get("zip"),
            })
        registry["batches"] = batches
        return registry

    def _save_registry(self) -> None:
        payload = dict(self._registry)
        payload["schema_version"] = 1
        payload["updated_at"] = self._now()
        try:
            os.makedirs(self.root_folder, exist_ok=True)
            temp_path = self.registry_path + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.registry_path)
        except OSError as exc:
            print(f"[BATCH] Реестр партий не сохранён: {exc}")
