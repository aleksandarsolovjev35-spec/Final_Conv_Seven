"""Операторы HMI: вход в программу по ФИО и паролю.

Учётные записи лежат в JSON рядом с реестром партий
(``<корень архива>/operators.json``). Это единственное место, знающее о
формате хранения: подключение БД заменит только внутренности класса, а
публичные методы (``authenticate`` / ``add_user`` / ``logins``) останутся.

Пароли не хранятся в открытом виде: PBKDF2-HMAC-SHA256 со случайной солью
на пользователя. ФИО сравниваются без учёта регистра и лишних пробелов —
оператор печатает себя так, как привык.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import tempfile
from datetime import datetime

FILE_NAME = "operators.json"
SCHEMA_VERSION = 1

LOGIN_MIN_LENGTH = 3
PASSWORD_MIN_LENGTH = 4
ITERATIONS = 120_000
SALT_BYTES = 16

# Что HMI показывает вместо кнопки ПУСК, если оператор не назначен.
NO_OPERATOR_MESSAGE = "Оператор не назначен: войдите в программу"


def normalise_login(login: str) -> str:
    """ФИО без лишних пробелов по краям и внутри."""
    return " ".join(str(login or "").split())


def _login_key(login: str) -> str:
    """Ключ сравнения ФИО: регистр и пробелы не важны."""
    return normalise_login(login).casefold()


def validate_login(login: str) -> str:
    """Проверить ФИО оператора и вернуть его в нормальном виде."""
    value = normalise_login(login)
    if len(value) < LOGIN_MIN_LENGTH:
        raise ValueError("Укажите ФИО оператора")
    if not any(char.isalpha() for char in value):
        raise ValueError("ФИО оператора должно содержать буквы")
    return value


def validate_password(password: str) -> str:
    """Пароль оператора: без внешних пробелов, не короче минимума."""
    value = str(password or "")
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Пароль: минимум {PASSWORD_MIN_LENGTH} символа"
        )
    return value


def hash_password(
    password: str,
    salt: bytes | None = None,
    *,
    iterations: int = ITERATIONS,
) -> tuple[str, str]:
    """Вернуть ``(salt_hex, hash_hex)`` для пароля."""
    salt = salt or secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return salt.hex(), digest.hex()


class OperatorStore:
    """Список операторов и проверка пароля при входе в программу."""

    def __init__(
        self,
        root_folder: str = "archive",
        *,
        file_name: str = FILE_NAME,
        iterations: int = ITERATIONS,
    ):
        self.root_folder = str(root_folder or "archive")
        self.file_name = file_name
        self.iterations = int(iterations)
        self._lock = threading.RLock()
        self._error: str | None = None
        self._data = self._read()

    # ---------- состояние ----------

    @property
    def path(self) -> str:
        return os.path.join(self.root_folder, self.file_name)

    @property
    def error(self) -> str | None:
        """Ошибка чтения файла: HMI показывает её вместо формы первого входа."""
        return self._error

    def has_users(self) -> bool:
        with self._lock:
            return bool(self._data["users"])

    def logins(self) -> list[str]:
        """ФИО всех операторов; последний вошедший — первым.

        Порядок задаёт подсказку на экране входа: оператор выбирает себя
        из списка, и первым в нём стоит тот, кто работал последним.
        """
        with self._lock:
            names = [user["login"] for user in self._data["users"]]
        last = self.last_login()
        if last in names:
            names.remove(last)
            names.insert(0, last)
        return names

    def last_login(self) -> str:
        with self._lock:
            return str(self._data["last_login"] or "")

    def can_add_user(self) -> bool:
        """Добавлять операторов можно, только если файл читается."""
        return self._error is None

    # ---------- вход и регистрация ----------

    def authenticate(self, login: str, password: str) -> str:
        """Проверить ФИО и пароль; вернуть ФИО в нормальном виде.

        Неверная пара поднимает ``ValueError`` без подсказки, что именно
        не совпало: и лишние догадки, и разные тексты тут не нужны.
        """
        value = normalise_login(login)
        if not value:
            raise ValueError("Укажите ФИО оператора")
        stored = self._find(value)
        if stored is None:
            raise ValueError("Оператор не найден")
        if not self._password_matches(stored, password):
            raise ValueError("Неверный пароль")
        with self._lock:
            self._touch(stored["login"])
        return str(stored["login"])

    def add_user(self, login: str, password: str) -> str:
        """Зарегистрировать оператора и вернуть его ФИО в нормальном виде."""
        value = validate_login(login)
        secret = validate_password(password)
        if not self.can_add_user():
            raise RuntimeError(
                f"Файл операторов недоступен: {self._error}"
            )
        with self._lock:
            if self._find(value) is not None:
                raise ValueError("Оператор с таким ФИО уже есть")
            salt_hex, hash_hex = hash_password(
                secret, iterations=self.iterations
            )
            self._data["users"].append({
                "login": value,
                "salt": salt_hex,
                "password_hash": hash_hex,
                "iterations": self.iterations,
                "created_at": self._now(),
            })
            self._data["last_login"] = value
            self._write()
        return value

    def remove_user(self, login: str) -> bool:
        """Удалить оператора (служебная операция для тестов и сервиса)."""
        with self._lock:
            stored = self._find(login)
            if stored is None:
                return False
            self._data["users"] = [
                user for user in self._data["users"]
                if user is not stored
            ]
            if self._data["last_login"] == stored["login"]:
                self._data["last_login"] = ""
            self._write()
            return True

    # ---------- внутреннее ----------

    def _find(self, login: str) -> dict | None:
        key = _login_key(login)
        if not key:
            return None
        with self._lock:
            for user in self._data["users"]:
                if _login_key(user.get("login", "")) == key:
                    return user
        return None

    def _password_matches(self, user: dict, password: str) -> bool:
        try:
            salt = bytes.fromhex(str(user.get("salt") or ""))
            expected = str(user.get("password_hash") or "")
            iterations = int(user.get("iterations") or self.iterations)
        except (TypeError, ValueError):
            return False
        if not salt or not expected:
            return False
        _, actual = hash_password(
            str(password or ""), salt, iterations=iterations
        )
        return hmac.compare_digest(actual, expected)

    def _touch(self, login: str) -> None:
        """Запомнить последнего вошедшего: его ФИО HMI подсказывает первой."""
        users = self._data["users"]
        for index, user in enumerate(users):
            if user.get("login") == login:
                users.insert(0, users.pop(index))
                break
        self._data["last_login"] = login
        self._write()

    def _read(self) -> dict:
        data = {
            "schema_version": SCHEMA_VERSION,
            "last_login": "",
            "users": [],
        }
        try:
            with open(self.path, encoding="utf-8") as stream:
                raw = json.load(stream)
        except FileNotFoundError:
            return data
        except (OSError, json.JSONDecodeError) as exc:
            self._error = f"{type(exc).__name__}: {exc}"
            print(f"[OPERATORS] Ошибка чтения {self.path}: {exc}")
            return data

        users = []
        for item in (raw.get("users") if isinstance(raw, dict) else None) or []:
            if not isinstance(item, dict):
                continue
            login = normalise_login(item.get("login") or "")
            salt = str(item.get("salt") or "")
            password_hash = str(item.get("password_hash") or "")
            if not login or not salt or not password_hash:
                continue
            users.append({
                "login": login,
                "salt": salt,
                "password_hash": password_hash,
                "iterations": int(item.get("iterations") or ITERATIONS),
                "created_at": str(item.get("created_at") or ""),
            })
        data["users"] = users
        last_login = normalise_login(raw.get("last_login") or "")
        keys = {_login_key(user["login"]) for user in users}
        data["last_login"] = last_login if _login_key(last_login) in keys else ""
        return data

    def _write(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "last_login": self._data["last_login"],
            "users": list(self._data["users"]),
        }
        folder = os.path.dirname(self.path) or "."
        os.makedirs(folder, exist_ok=True)
        # Атомарная замена: файл операторов не должен остаться обрезанным
        # при выключении питания посреди записи.
        handle, temp_path = tempfile.mkstemp(
            dir=folder, prefix=f".{self.file_name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temp_path, self.path)
        except OSError:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
