"""Операторы HMI: учётные записи в JSON и вход по ФИО и паролю.

``OperatorStore`` тестируется напрямую (без сервера): хранение, проверка
пары ФИО/пароль, нормализация ФИО, перечитывание файла и права доступа.
Итерации PBKDF2 в тестах уменьшены — стойкость проверяет не тест.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest

from inspection.operator_store import (
    FILE_NAME,
    OperatorStore,
    hash_password,
    normalise_login,
    validate_login,
    validate_password,
)

ITERATIONS = 1000
OPERATOR = "Иванов Иван Иванович"
SECOND = "Петров Пётр Петрович"
PASSWORD = "1234"


class OperatorStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "archive")
        self.store = OperatorStore(self.root, iterations=ITERATIONS)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, login=OPERATOR, password=PASSWORD):
        return self.store.add_user(login, password)

    def raw(self):
        with open(self.store.path, encoding="utf-8") as stream:
            return json.load(stream)

    # ---------- пустое хранилище ----------

    def test_empty_store(self):
        self.assertFalse(self.store.has_users())
        self.assertEqual(self.store.logins(), [])
        self.assertEqual(self.store.last_login(), "")
        self.assertIsNone(self.store.error)
        self.assertTrue(self.store.can_add_user())
        self.assertFalse(os.path.exists(self.store.path))

    def test_file_path_is_next_to_batches(self):
        self.assertEqual(
            self.store.path, os.path.join(self.root, FILE_NAME),
        )

    # ---------- регистрация ----------

    def test_add_user_and_login(self):
        self.assertEqual(self.add(), OPERATOR)
        self.assertTrue(self.store.has_users())
        self.assertEqual(self.store.logins(), [OPERATOR])
        self.assertEqual(self.store.last_login(), OPERATOR)
        self.assertTrue(os.path.exists(self.store.path))
        self.assertEqual(self.store.authenticate(OPERATOR, PASSWORD), OPERATOR)

    def test_login_ignores_case_and_extra_spaces(self):
        self.add()
        entered = "  иванов   иван иванович  "
        self.assertEqual(self.store.authenticate(entered, PASSWORD), OPERATOR)

    def test_password_is_not_stored_in_plain_text(self):
        self.add()
        with open(self.store.path, encoding="utf-8") as stream:
            text = stream.read()
        self.assertNotIn(PASSWORD, text)
        user = self.raw()["users"][0]
        self.assertEqual(user["iterations"], ITERATIONS)
        self.assertTrue(user["salt"])
        self.assertTrue(user["password_hash"])

    def test_file_is_private(self):
        self.add()
        mode = stat.S_IMODE(os.stat(self.store.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_add_user_normalises_full_name(self):
        self.assertEqual(
            self.add("  Иванов  Иван   Иванович "), OPERATOR,
        )

    def test_add_user_rejects_duplicate_in_other_case(self):
        self.add()
        with self.assertRaises(ValueError) as ctx:
            self.add("иванов иван иванович")
        self.assertIn("уже есть", str(ctx.exception))
        self.assertEqual(len(self.store.logins()), 1)

    def test_add_user_validates_full_name_and_password(self):
        with self.assertRaises(ValueError):
            self.add("Ив")
        with self.assertRaises(ValueError):
            self.add("12345")
        with self.assertRaises(ValueError):
            self.add(OPERATOR, "12")
        self.assertFalse(self.store.has_users())

    def test_second_operator_is_added(self):
        self.add()
        self.add(SECOND, PASSWORD)
        self.assertEqual(len(self.store.logins()), 2)
        # Последний заведённый — первым в подсказке.
        self.assertEqual(self.store.logins()[0], SECOND)

    # ---------- вход ----------

    def test_wrong_password(self):
        self.add()
        with self.assertRaises(ValueError) as ctx:
            self.store.authenticate(OPERATOR, "0000")
        self.assertEqual(str(ctx.exception), "Неверный пароль")

    def test_unknown_operator(self):
        self.add()
        with self.assertRaises(ValueError) as ctx:
            self.store.authenticate("Сидоров Сидор Сидорович", PASSWORD)
        self.assertEqual(str(ctx.exception), "Оператор не найден")

    def test_empty_login(self):
        self.add()
        with self.assertRaises(ValueError) as ctx:
            self.store.authenticate("   ", PASSWORD)
        self.assertEqual(str(ctx.exception), "Укажите ФИО оператора")

    def test_login_moves_operator_to_top(self):
        self.add()
        self.add(SECOND, PASSWORD)
        self.assertEqual(self.store.logins()[0], SECOND)
        self.store.authenticate(OPERATOR, PASSWORD)
        self.assertEqual(self.store.logins(), [OPERATOR, SECOND])
        self.assertEqual(self.store.last_login(), OPERATOR)

    def test_password_of_one_operator_does_not_fit_another(self):
        self.add()
        self.add(SECOND, "4321")
        with self.assertRaises(ValueError):
            self.store.authenticate(SECOND, PASSWORD)

    # ---------- перечитывание ----------

    def test_store_survives_restart(self):
        self.add()
        restarted = OperatorStore(self.root, iterations=ITERATIONS)
        self.assertTrue(restarted.has_users())
        self.assertEqual(restarted.logins(), [OPERATOR])
        self.assertEqual(restarted.last_login(), OPERATOR)
        self.assertEqual(
            restarted.authenticate(OPERATOR, PASSWORD), OPERATOR,
        )

    def test_alien_iterations_are_respected(self):
        """Хранилище с другим числом итераций всё равно пускает оператора."""
        self.add()
        heavy = OperatorStore(self.root, iterations=ITERATIONS * 2)
        self.assertEqual(heavy.authenticate(OPERATOR, PASSWORD), OPERATOR)

    def test_corrupted_file_is_reported(self):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, FILE_NAME), "w",
                  encoding="utf-8") as stream:
            stream.write("{не json")
        store = OperatorStore(self.root)
        self.assertIsNotNone(store.error)
        self.assertFalse(store.can_add_user())
        self.assertFalse(store.has_users())
        self.assertFalse(store.logins())
        with self.assertRaises(RuntimeError):
            store.add_user(OPERATOR, PASSWORD)
        with self.assertRaises(ValueError):
            store.authenticate(OPERATOR, PASSWORD)

    def test_broken_records_are_skipped(self):
        os.makedirs(self.root, exist_ok=True)
        payload = {
            "schema_version": 1,
            "last_login": "Петров Пётр Петрович",
            "users": [
                {"login": "", "salt": "aa", "password_hash": "bb"},
                "мусор",
                {"login": OPERATOR, "salt": "", "password_hash": ""},
                {
                    "login": "  Петров   Пётр Петрович ",
                    "salt": "aa",
                    "password_hash": "bb",
                    "iterations": ITERATIONS,
                },
            ],
        }
        with open(os.path.join(self.root, FILE_NAME), "w",
                  encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        store = OperatorStore(self.root, iterations=ITERATIONS)
        self.assertIsNone(store.error)
        self.assertEqual(store.logins(), [SECOND])
        self.assertEqual(store.last_login(), SECOND)

    def test_last_login_unknown_is_dropped(self):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, FILE_NAME), "w",
                  encoding="utf-8") as stream:
            json.dump(
                {"schema_version": 1, "last_login": "Никого Нет",
                 "users": []},
                stream, ensure_ascii=False,
            )
        store = OperatorStore(self.root)
        self.assertEqual(store.last_login(), "")

    # ---------- удаление ----------

    def test_remove_user(self):
        self.add()
        self.add(SECOND, PASSWORD)
        self.assertTrue(self.store.remove_user(OPERATOR))
        self.assertEqual(self.store.logins(), [SECOND])
        self.assertFalse(self.store.remove_user(OPERATOR))
        with self.assertRaises(ValueError):
            self.store.authenticate(OPERATOR, PASSWORD)

    def test_remove_last_operator_clears_hint(self):
        self.add()
        self.assertTrue(self.store.remove_user("иванов иван иванович"))
        self.assertFalse(self.store.has_users())
        self.assertEqual(self.store.last_login(), "")


class OperatorHelpersTest(unittest.TestCase):
    """Нормализация и проверки живут отдельно от хранилища."""

    def test_normalise_login(self):
        self.assertEqual(normalise_login("  Иван   Иванов "), "Иван Иванов")
        self.assertEqual(normalise_login(None), "")

    def test_validate_login(self):
        self.assertEqual(validate_login(" Иван  Иванов "), "Иван Иванов")
        with self.assertRaises(ValueError):
            validate_login("Ив")
        with self.assertRaises(ValueError):
            validate_login("123456")

    def test_validate_password(self):
        self.assertEqual(validate_password("1234"), "1234")
        with self.assertRaises(ValueError):
            validate_password("123")
        with self.assertRaises(ValueError):
            validate_password(None)

    def test_hash_password_is_salted(self):
        first = hash_password("1234")
        second = hash_password("1234")
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(
            hash_password("1234", bytes.fromhex(first[0]))[1], first[1],
        )


if __name__ == "__main__":
    unittest.main()
