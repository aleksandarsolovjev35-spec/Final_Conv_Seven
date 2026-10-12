"""Менеджер партий: реестр, открытие/продолжение/завершение партии.

Логика учёта проверяется целиком: оператор и номер партии попадают в
манифест и meta.json, счётчики продолжаются после перезапуска программы,
незакрытая партия остаётся открытой, а завершение закрывает манифест,
отправляет его аналитику и упаковывает партию в ZIP.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from inspection.batch_manager import (
    REGISTRY_FILE,
    STATUS_CLOSED,
    STATUS_OPEN,
    BatchManager,
)
from inspection.part_archive import PartArchive, safe_component


def make_frame(value=120):
    return np.full((48, 64, 3), value, dtype=np.uint8)


class BatchManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "archive")
        self.sender = mock.Mock(return_value=True)
        self.manager = BatchManager(
            root_folder=self.root, batch_sender=self.sender,
        )

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- вспомогательное ----------

    def open_batch(self, label="П-1", operator="Иванов Иван Иванович"):
        return self.manager.open_batch(label=label, operator=operator)

    def store_part(self, part_id=1, category="GOOD", defects=None):
        frames = {"TOP": make_frame()}
        self.manager.store_frames(part_id, frames, frames)
        return self.manager.finalize(
            part_id=part_id,
            category=category,
            decision="ok",
            defects=defects or [],
            step=part_id,
        )

    def batch_manifest(self, batch_id=None):
        batch_id = batch_id or self.manager.batch_id
        path = os.path.join(
            self.manager.batch_folder, "batch.json",
        ) if batch_id == self.manager.batch_id else os.path.join(
            self.root, "2026-10-12", batch_id, "batch.json",
        )
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)

    # ---------- состояние до открытия партии ----------

    def test_starts_without_active_batch(self):
        self.assertFalse(self.manager.active)
        self.assertIsNone(self.manager.batch_id)
        payload = self.manager.status_payload()
        self.assertFalse(payload["active"])
        self.assertIsNone(payload["batch"])
        self.assertEqual(payload["open"], [])
        self.assertTrue(payload["suggestion"])

    def test_finalize_without_batch_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.store_part()

    # ---------- открытие партии ----------

    def test_open_batch_creates_manifest_and_registry(self):
        self.open_batch()
        self.assertTrue(self.manager.active)
        self.assertTrue(os.path.isdir(self.manager.batch_folder))
        manifest = self.batch_manifest()
        self.assertEqual(manifest["status"], STATUS_OPEN)
        self.assertEqual(manifest["operator"], "Иванов Иван Иванович")
        self.assertEqual(manifest["batch_label"], "П-1")
        self.assertTrue(os.path.exists(os.path.join(self.root, REGISTRY_FILE)))

        payload = self.manager.status_payload()
        self.assertEqual(payload["batch"]["label"], "П-1")
        self.assertEqual(payload["batch"]["operator"], "Иванов Иван Иванович")
        self.assertEqual(len(payload["open"]), 1)

    def test_batch_folder_name_is_safe_component(self):
        self.open_batch(label="Заказ 4512/3")
        self.assertEqual(
            self.manager.batch_id, "batch_" + safe_component("Заказ 4512/3"),
        )
        # Никакого выхода за корень архива через имя партии.
        self.assertNotIn("..", self.manager.batch_folder)

    def test_operator_is_normalised(self):
        self.open_batch(operator="  Петров   Пётр  Петрович ")
        self.assertEqual(
            self.manager.batch_info()["operator"], "Петров Пётр Петрович",
        )

    def test_open_validation(self):
        with self.assertRaises(ValueError):
            self.open_batch(operator="Ив")
        with self.assertRaises(ValueError):
            self.open_batch(operator="123")
        with self.assertRaises(ValueError):
            self.open_batch(label="")
        with self.assertRaises(ValueError):
            self.open_batch(label="X" * 41)
        self.assertFalse(self.manager.active)

    def test_second_batch_cannot_be_opened(self):
        self.open_batch()
        with self.assertRaises(RuntimeError):
            self.open_batch(label="П-2")

    def test_unique_batch_id_for_repeated_label(self):
        self.open_batch(label="П-1")
        first_id = self.manager.batch_id
        self.manager.prepare_shutdown()
        self.manager = BatchManager(
            root_folder=self.root, batch_sender=self.sender,
        )
        self.open_batch(label="П-1")
        self.assertNotEqual(self.manager.batch_id, first_id)

    # ---------- учёт корпусов ----------

    def test_finalize_writes_part_and_updates_registry(self):
        self.open_batch()
        folder = self.store_part(part_id=1, category="GOOD")
        self.assertTrue(os.path.exists(os.path.join(folder, "meta.json")))
        with open(
            os.path.join(folder, "meta.json"), encoding="utf-8",
        ) as stream:
            meta = json.load(stream)
        self.assertEqual(meta["operator"], "Иванов Иван Иванович")
        self.assertEqual(meta["batch_label"], "П-1")

        self.assertEqual(self.manager.counts()["total"], 1)
        manifest = self.batch_manifest()
        self.assertEqual(manifest["counts"]["total"], 1)
        payload = self.manager.status_payload()
        self.assertEqual(payload["batch"]["counts"]["good"], 1)
        self.assertEqual(payload["open"][0]["counts"]["total"], 1)

    def test_accounting_reports_open_batch_counters(self):
        """Счётчики партии — источник учёта линии; без партии их нет."""
        self.assertIsNone(self.manager.accounting())

        self.open_batch()
        self.assertEqual(self.manager.accounting(), {
            "total": 0, "good": 0, "bad": 0, "cleanup": 0, "last_part_id": 0,
        })

        self.store_part(part_id=1)
        self.store_part(part_id=2, category="BAD")
        counters = self.manager.accounting()
        self.assertEqual(counters["total"], 2)
        self.assertEqual(counters["good"], 1)
        self.assertEqual(counters["bad"], 1)
        self.assertEqual(counters["cleanup"], 0)
        self.assertEqual(counters["last_part_id"], 2)

    def test_accounting_after_resume_keeps_part_numbering(self):
        """Продолжение партии не начинает нумерацию корпусов заново."""
        self.open_batch()
        self.store_part(part_id=1)
        self.store_part(part_id=2, category="CLEANUP")
        self.manager.prepare_shutdown()

        restarted = BatchManager(
            root_folder=self.root, batch_sender=self.sender,
        )
        restarted.open_batch(
            operator="Петров Пётр Петрович",
            batch_id=self.manager.batch_id,
        )

        counters = restarted.accounting()
        self.assertEqual(counters["total"], 2)
        self.assertEqual(counters["cleanup"], 1)
        self.assertEqual(counters["last_part_id"], 2)

    def test_get_part_info_after_finalize(self):
        self.open_batch()
        self.store_part(part_id=3)
        info = self.manager.get_part_info(3)
        self.assertIsNotNone(info)
        self.assertIn("GOOD", info["relative_folder"])
        self.assertIsNone(self.manager.get_part_info(99))

    # ---------- перезаход и продолжение ----------

    def test_shutdown_keeps_batch_open_for_continuation(self):
        self.open_batch()
        self.store_part(part_id=1)
        self.manager.prepare_shutdown()

        # Партия не закрыта: папка на месте, манифест OPEN, отправки нет.
        self.assertTrue(os.path.isdir(self.manager.batch_folder))
        self.assertEqual(self.batch_manifest()["status"], STATUS_OPEN)
        self.sender.assert_not_called()
        self.assertFalse(
            os.path.exists(self.manager.batch_folder + ".zip")
        )

        # Новый запуск программы: партия видна и её можно продолжить.
        restarted = BatchManager(
            root_folder=self.root, batch_sender=self.sender,
        )
        payload = restarted.status_payload()
        self.assertFalse(payload["active"])
        self.assertEqual(len(payload["open"]), 1)
        self.assertEqual(payload["open"][0]["counts"]["total"], 1)
        self.assertTrue(payload["open"][0]["available"])

        batch = restarted.open_batch(
            operator="Петров Пётр Петрович",
            batch_id=payload["open"][0]["batch_id"],
        )
        self.assertTrue(batch["active"])
        self.assertEqual(batch["batch"]["label"], "П-1")
        self.assertEqual(batch["batch"]["operator"], "Петров Пётр Петрович")
        self.assertEqual(batch["batch"]["counts"]["total"], 1)
        self.assertEqual(batch["batch"]["started_by"], "Иванов Иван Иванович")

        # Нумерация деталей продолжается, а не начинается заново.
        restarted.store_frames(2, {"TOP": make_frame()}, {"TOP": make_frame()})
        folder = restarted.finalize(
            part_id=2, category="BAD", decision="no", defects=[], step=2,
        )
        self.assertTrue(os.path.exists(os.path.join(folder, "meta.json")))
        self.assertEqual(restarted.counts()["total"], 2)
        self.assertEqual(restarted.counts()["bad"], 1)

    def test_continue_missing_batch_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.open_batch(
                operator="Иванов Иван Иванович", batch_id="batch_нет",
            )

    def test_continue_finished_batch_is_rejected(self):
        self.open_batch()
        self.store_part(part_id=1)
        self.manager.finish_batch()
        with self.assertRaises(RuntimeError):
            self.manager.open_batch(
                operator="Иванов Иван Иванович",
                batch_id="batch_" + safe_component("П-1"),
            )

    # ---------- завершение партии ----------

    def test_finish_batch_closes_and_compresses(self):
        self.open_batch()
        self.store_part(part_id=1, category="CLEANUP")
        batch_id = self.manager.batch_id
        batch_folder = self.manager.batch_folder
        payload = self.manager.finish_batch()

        self.assertFalse(payload["active"])
        self.assertIsNone(payload["batch"])
        # Отправка манифеста аналитику до сжатия папки.
        self.sender.assert_called_once_with(batch_folder)
        zip_path = batch_folder + ".zip"
        self.assertTrue(os.path.exists(zip_path))
        self.assertFalse(os.path.isdir(batch_folder))
        self.assertEqual(payload["recent"][-1]["batch_id"], batch_id)
        self.assertEqual(payload["recent"][-1]["status"], STATUS_CLOSED)
        self.assertEqual(payload["recent"][-1]["counts"]["cleanup"], 1)
        # ZIP собирается по папке партии (её имя задаёт оператор путём).
        self.assertEqual(
            payload["recent"][-1]["zip"],
            os.path.basename(batch_folder) + ".zip",
        )

    # ---------- путь партии ----------

    def test_default_folder_is_root_date_label(self):
        """Путь по умолчанию: <корень>/<дата>/<номер партии>."""
        payload = self.manager.status_payload()
        self.assertEqual(
            payload["default_folder"],
            os.path.join(
                os.path.abspath(self.root),
                payload["date"],
                payload["suggestion"],
            ),
        )
        # Подсказка совпадает с папкой, которую менеджер создаст сам.
        self.manager.open_batch(
            label=payload["suggestion"],
            operator="Иванов Иван Иванович",
        )
        self.assertEqual(
            self.manager.batch_folder,
            os.path.join(
                os.path.abspath(self.root),
                payload["date"],
                payload["suggestion"],
            ),
        )

    def test_open_batch_uses_given_folder(self):
        """Оператор задал путь — партия пишется ровно в эту папку."""
        folder = os.path.join(self.tmp.name, "orders", "заказ-7")
        payload = self.manager.open_batch(
            label="заказ-7", operator="Иванов Иван Иванович", folder=folder,
        )

        self.assertEqual(self.manager.batch_folder, os.path.abspath(folder))
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(payload["batch"]["folder"], os.path.abspath(folder))
        self.assertEqual(payload["open"][0]["folder"], os.path.abspath(folder))
        self.store_part(part_id=1)
        self.assertTrue(os.path.isdir(os.path.join(folder, "GOOD")))

    def test_batch_folder_is_kept_after_restart(self):
        """Продолжение партии идёт в её папку, а не в корень хранения.

        Путь хранится в реестре партий, поэтому папка партии может лежать
        и вне корня хранения: после перезапуска учёт вернётся в неё.
        """
        folder = os.path.join(self.tmp.name, "orders", "заказ-7")
        self.manager.open_batch(
            label="заказ-7", operator="Иванов Иван Иванович", folder=folder,
        )
        self.store_part(part_id=1)
        batch_id = self.manager.batch_id
        self.manager.prepare_shutdown()

        restarted = BatchManager(
            root_folder=self.root, batch_sender=self.sender,
        )
        restarted.open_batch(
            operator="Петров Пётр Петрович", batch_id=batch_id,
        )

        self.assertEqual(restarted.batch_folder, os.path.abspath(folder))
        self.assertEqual(restarted.accounting()["total"], 1)

    def test_open_batch_rejects_broken_folder(self):
        """Недоступный путь партии — ошибка данных, партия не открывается."""
        broken = os.path.join(self.tmp.name, "file.txt")
        with open(broken, "w", encoding="utf-8") as stream:
            stream.write("not a folder")
        with self.assertRaises(ValueError):
            self.manager.open_batch(
                label="П-9", operator="Иванов Иван Иванович", folder=broken,
            )
        self.assertFalse(self.manager.active)

    def test_finish_without_batch_is_rejected(self):
        with self.assertRaises(RuntimeError):
            self.manager.finish_batch()

    def test_sender_failure_does_not_block_finish(self):
        self.manager = BatchManager(
            root_folder=self.root,
            batch_sender=mock.Mock(side_effect=RuntimeError("нет сети")),
        )
        self.open_batch()
        payload = self.manager.finish_batch()
        self.assertFalse(payload["active"])
        self.assertTrue(os.path.exists(
            os.path.join(self.root, REGISTRY_FILE),
        ))

    # ---------- корень архива ----------

    def test_reconfigure_only_without_batch(self):
        self.assertTrue(self.manager.reconfigure(
            root_folder=os.path.join(self.tmp.name, "other"),
        )["root_path"].endswith("other"))
        self.open_batch()
        with self.assertRaises(RuntimeError):
            self.manager.reconfigure(
                root_folder=os.path.join(self.tmp.name, "third"),
            )

    def test_get_settings_reports_batch_and_operator(self):
        self.assertIsNone(self.manager.get_settings()["batch_id"])
        self.open_batch()
        settings = self.manager.get_settings()
        self.assertEqual(settings["batch_id"], self.manager.batch_id)
        self.assertEqual(settings["batch_label"], "П-1")
        self.assertEqual(settings["operator"], "Иванов Иван Иванович")
        self.assertFalse(settings["editable"])
        self.assertTrue(settings["validation"]["writable"])


class PartArchiveResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_resume_restores_parts_and_counts(self):
        archive = PartArchive(
            self.root, batch_id="batch_1", date_folder="2026-10-12",
            operator="Иванов Иван Иванович", label="П-1",
        )
        frames = {"TOP": make_frame()}
        archive.store_frames(1, frames, frames)
        archive.finalize(1, "GOOD", "ok", [], 1)

        resumed = PartArchive.resume(
            self.root, batch_id="batch_1", date_folder="2026-10-12",
            operator="Петров Пётр Петрович",
        )
        self.assertEqual(resumed.counts["total"], 1)
        self.assertEqual(resumed.operator, "Петров Пётр Петрович")
        self.assertEqual(resumed.label, "П-1")
        self.assertIsNotNone(resumed.get_part_info(1))

        resumed.store_frames(2, frames, frames)
        resumed.finalize(2, "BAD", "no", [], 2)
        self.assertEqual(resumed.counts, {
            "total": 2, "good": 1, "bad": 1, "cleanup": 0,
        })

    def test_last_part_id_restored_after_resume(self):
        archive = PartArchive(
            self.root, batch_id="batch_1", date_folder="2026-10-12",
        )
        self.assertEqual(archive.last_part_id, 0)
        frames = {"TOP": make_frame()}
        for part_id in (1, 2, 3):
            archive.store_frames(part_id, frames, frames)
            archive.finalize(part_id, "GOOD", "ok", [], part_id)

        resumed = PartArchive.resume(
            self.root, batch_id="batch_1", date_folder="2026-10-12",
        )
        self.assertEqual(resumed.last_part_id, 3)

    def test_resume_unknown_batch_starts_from_zero(self):
        resumed = PartArchive.resume(
            self.root, batch_id="batch_none", date_folder="2026-10-12",
        )
        self.assertEqual(resumed.counts["total"], 0)

    def test_date_folder_is_sanitised(self):
        archive = PartArchive(
            self.root, batch_id="batch_1", date_folder="../../etc",
        )
        self.assertNotIn("..", archive.batch_folder)
        self.assertTrue(
            archive.batch_folder.startswith(os.path.abspath(self.root)),
        )


if __name__ == "__main__":
    unittest.main()
