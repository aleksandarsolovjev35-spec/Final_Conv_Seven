"""Хранилище списка операторов (пользователей) для входа в HMI.

При каждом запуске программы оператор вводит своё ФИО или выбирает его из
ранее сохранённого списка. Список хранится в ``operators.json`` внутри
корневой папки архива (атомарная запись через временный файл).
"""

from __future__ import annotations

import contextlib
import json
import os
import threading


OPERATORS_FILENAME = "operators.json"
MIN_OPERATOR_LENGTH = 2
MAX_OPERATOR_LENGTH = 120
MAX_STORED_OPERATORS = 50


def normalise_operator_fio(value: str | None) -> str:
    """Проверить и нормализовать ФИО оператора."""
    if not isinstance(value, str):
        raise ValueError("Укажите ФИО оператора")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Укажите ФИО оператора")
    if len(cleaned) < MIN_OPERATOR_LENGTH:
        raise ValueError("ФИО оператора слишком короткое")
    if len(cleaned) > MAX_OPERATOR_LENGTH:
        raise ValueError(
            f"ФИО оператора не должно превышать {MAX_OPERATOR_LENGTH} символов"
        )
    return cleaned


class OperatorStore:
    """Потокобезопасный реестр известных операторов."""

    OPERATORS_FILENAME = OPERATORS_FILENAME

    def __init__(self, root_folder: str | None = None):
        self._lock = threading.Lock()
        self._operators: list[str] = []
        self.root_folder: str | None = None
        if root_folder is not None:
            self.set_root_folder(root_folder)

    @property
    def storage_path(self) -> str | None:
        if not self.root_folder:
            return None
        return os.path.join(self.root_folder, self.OPERATORS_FILENAME)

    @staticmethod
    def _normalise_folder(root_folder: str | None) -> str | None:
        text = str(root_folder or "").strip()
        if not text:
            return None
        return os.path.abspath(os.path.expandvars(os.path.expanduser(text)))

    def set_root_folder(self, root_folder: str | None) -> None:
        normalised = self._normalise_folder(root_folder)
        with self._lock:
            if normalised == self.root_folder:
                return
            previous = list(self._operators)
            self.root_folder = normalised
            loaded = self._load_unlocked()
            merged: list[str] = []
            seen: set[str] = set()
            for item in [*previous, *loaded]:
                key = item.casefold()
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
            self._operators = merged[:MAX_STORED_OPERATORS]
            if self.root_folder and previous and self._operators != loaded:
                self._save_unlocked()

    def list_operators(self) -> list[str]:
        with self._lock:
            return list(self._operators)

    def register_operator(self, fio: str) -> str:
        cleaned = normalise_operator_fio(fio)
        target = cleaned.casefold()
        with self._lock:
            filtered = [
                item for item in self._operators if item.casefold() != target
            ]
            self._operators = [cleaned, *filtered][:MAX_STORED_OPERATORS]
            self._save_unlocked()
        return cleaned

    def remove_operator(self, fio: str) -> list[str]:
        if not isinstance(fio, str):
            return self.list_operators()
        target = " ".join(fio.split()).casefold()
        if not target:
            return self.list_operators()
        with self._lock:
            before = len(self._operators)
            self._operators = [
                item for item in self._operators if item.casefold() != target
            ]
            if len(self._operators) != before:
                self._save_unlocked()
            return list(self._operators)

    def _load_unlocked(self) -> list[str]:
        path = self.storage_path
        if not path:
            return []
        try:
            with open(path, encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            return []
        raw_items = (
            data.get("operators")
            if isinstance(data, dict)
            else data if isinstance(data, list) else []
        )
        if not isinstance(raw_items, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for raw in raw_items:
            if not isinstance(raw, str):
                continue
            try:
                cleaned = normalise_operator_fio(raw)
            except ValueError:
                continue
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                result.append(cleaned)
        return result[:MAX_STORED_OPERATORS]

    def _save_unlocked(self) -> None:
        path = self.storage_path
        if not path:
            return
        temp_path = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {"operators": self._operators}
            with open(temp_path, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        except OSError as exc:
            print(f"[OPERATOR] Не удалось сохранить список операторов: {exc}")
            if os.path.exists(temp_path):
                with contextlib.suppress(OSError):
                    os.remove(temp_path)
