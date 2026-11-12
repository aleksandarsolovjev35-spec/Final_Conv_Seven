import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from inspection.part_archive import PartArchive
from json_sender import scan_and_send_all_batches
from vision.ui.server.server import UIServer

ROOT = Path(__file__).resolve().parents[1]


class PartArchiveBatchManagementTest(unittest.TestCase):
    def test_open_manifest_listing_and_resume_restores_part_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = PartArchive(
                tmp, "Lot-2026-A", "Иванов Иван Иванович",
                create_manifest=True,
            )
            self.assertTrue(os.path.isfile(os.path.join(archive.batch_folder, "batch.json")))
            listed = PartArchive.list_batches(tmp)
            self.assertEqual(listed[0]["batch_id"], "Lot-2026-A")
            self.assertEqual(listed[0]["status"], "OPEN")

            archive.finalize(1, "GOOD", "accepted", [], 1)
            resumed = PartArchive.resume(tmp, "Lot-2026-A")
            self.assertEqual(resumed.next_part_id, 2)
            self.assertEqual(resumed._batch_stats["total"], 1)
            self.assertEqual(resumed._batch_stats["good"], 1)
            self.assertEqual(resumed._batch_parts[0]["part_id"], 1)

    def test_generated_id_contains_only_sequence_and_date_and_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = PartArchive.generate_batch_id(tmp)
            archive = PartArchive(tmp, first, "Оператор", create_manifest=True)
            second = PartArchive.generate_batch_id(tmp)
            self.assertRegex(first, r"^\d{4}_\d{4}_\d{2}_\d{2}$")
            self.assertEqual(int(second.split("_", 1)[0]),
                             int(first.split("_", 1)[0]) + 1)
            self.assertNotIn("batch", first.lower())
            self.assertNotEqual(archive.batch_id, second)

    def test_invalid_batch_id_cannot_escape_archive_root(self):
        for value in ("../outside", "CON", "lot."):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PartArchive.validate_batch_id(value)
        self.assertEqual(PartArchive.validate_batch_id("Партия-7"), "Партия-7")

    def test_closed_zip_is_discoverable_and_empty_batch_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = PartArchive(tmp, "CloseMe", create_manifest=True)
            archive.finalize(1, "BAD", "rejected", [], 1)
            zip_path = archive.close_batch()
            self.assertTrue(os.path.isfile(zip_path))
            listed = PartArchive.list_batches(tmp)
            self.assertEqual(listed[0]["status"], "CLOSED")
            self.assertTrue(listed[0]["zipped"])

            empty = PartArchive(tmp, "Empty", create_manifest=True)
            empty.close_batch()
            self.assertFalse(os.path.exists(empty.batch_folder))

    def test_sender_finds_custom_closed_ids_but_skips_open_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "archive")
            queue = os.path.join(tmp, "queue")
            remote = os.path.join(tmp, "remote")
            os.makedirs(remote)
            closed = PartArchive(root, "Партия-А", create_manifest=True)
            closed.finalize(1, "GOOD", "accepted", [], 1)
            closed.close_manifest()
            open_batch = PartArchive(root, "StillOpen", create_manifest=True)
            open_batch.finalize(1, "BAD", "pending", [], 1)

            delivered = scan_and_send_all_batches(
                root, queue_dir=queue, remote_root=remote,
            )
            self.assertEqual(delivered, 1)
            self.assertTrue(os.path.isfile(os.path.join(
                remote, "Партия-А", "batch.json",
            )))
            self.assertFalse(os.path.exists(os.path.join(
                remote, "StillOpen", "batch.json",
            )))


class BatchManagementApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = UIServer()
        self.server.archive = PartArchive(self.tmp.name, "bootstrap")
        self.server.batch_root_folder = self.tmp.name
        self.server.operator_name = "Оператор Тестовый"
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE"}
        self.server.on_start = lambda: True
        self.client = TestClient(self.server.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_requires_batch_created_in_management_panel(self):
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 409)
        self.assertIn("создайте партию", response.json()["error"])
        self.assertFalse(self.server.batch_selected)

        opened = self.client.post("/api/batches/open", json={})
        self.assertEqual(opened.status_code, 200)
        self.assertTrue(self.server.batch_selected)
        self.assertRegex(
            self.server.archive.batch_id, r"^\d{4}_\d{4}_\d{2}_\d{2}$",
        )
        self.assertEqual(self.client.post("/api/start").status_code, 200)

    def test_selected_batch_is_the_one_started(self):
        self.client.post("/api/batches/open", json={"batch_id": "Line-7"})
        self.assertEqual(self.client.post("/api/start").status_code, 200)
        self.assertEqual(self.server.archive.batch_id, "Line-7")

    def test_batch_list_is_shared_between_operators(self):
        self.server.open_batch("Mine")
        self.client.post("/api/batches/detach")
        PartArchive(
            self.tmp.name, "OtherOperatorBatch", "Другой Оператор",
            create_manifest=True,
        )

        payload = self.client.get("/api/batches").json()
        listed = {
            item["batch_id"]: item for item in payload["batches"]
        }
        self.assertEqual(set(listed), {"Mine", "OtherOperatorBatch"})
        self.assertEqual(listed["Mine"]["owner"], "Оператор Тестовый")
        self.assertEqual(
            listed["OtherOperatorBatch"]["owner"], "Другой Оператор",
        )
        # Партии просто общие: разделения на «мои» и «чужие» нет.
        for item in listed.values():
            self.assertNotIn("owned", item)
            self.assertNotIn("shared", item)
            self.assertIn("operator_stats", item)

        # Список виден тому же оператору и другому пользователю.
        self.server.operator_name = "Другой Оператор"
        other_payload = self.client.get("/api/batches").json()
        other_listed = {
            item["batch_id"]: item for item in other_payload["batches"]
        }
        self.assertEqual(set(other_listed), {"Mine", "OtherOperatorBatch"})
        self.assertEqual(other_listed["Mine"]["owner"], "Оператор Тестовый")
        self.assertEqual(
            other_listed["OtherOperatorBatch"]["owner"], "Другой Оператор",
        )

    def test_foreign_open_batch_can_be_resumed_and_keeps_its_creator(self):
        PartArchive(
            self.tmp.name, "OtherOperatorBatch", "Другой Оператор",
            create_manifest=True,
        )
        resumed = self.client.post(
            "/api/batches/resume", json={"batch_id": "OtherOperatorBatch"},
        )
        self.assertEqual(resumed.status_code, 200)
        archive = self.server.archive
        self.assertEqual(archive.batch_id, "OtherOperatorBatch")
        self.assertEqual(archive.operator, "Оператор Тестовый")
        self.assertEqual(archive.created_by, "Другой Оператор")
        self.assertIn("Другой Оператор", archive.operators)
        self.assertIn("Оператор Тестовый", archive.operators)

        with open(
            os.path.join(archive.batch_folder, "batch.json"), encoding="utf-8",
        ) as stream:
            manifest = json.load(stream)
        self.assertEqual(manifest["created_by"], "Другой Оператор")
        self.assertIn("Оператор Тестовый", manifest["operators"])

        payload = self.client.get("/api/batches").json()
        self.assertEqual(payload["owner"], "Другой Оператор")
        shared = [
            item for item in payload["batches"]
            if item["batch_id"] == "OtherOperatorBatch"
        ][0]
        # Оба оператора показаны во вкладе партии (деталей пока нет).
        stats = {
            entry["operator"]: entry for entry in shared["operator_stats"]
        }
        self.assertEqual(
            set(stats), {"Другой Оператор", "Оператор Тестовый"},
        )
        self.assertEqual(stats["Оператор Тестовый"]["parts"], 0)

    def test_batch_reports_parts_processed_per_operator(self):
        archive = PartArchive(
            self.tmp.name, "SharedLot", "Иванов Иван Иванович",
            create_manifest=True,
        )
        archive.finalize(1, "GOOD", "accepted", [], 1)
        archive.finalize(2, "BAD", "rejected", [], 2)

        self.server.operator_name = "Сидоров Сидор Сидорович"
        resumed = self.client.post(
            "/api/batches/resume", json={"batch_id": "SharedLot"},
        )
        self.assertEqual(resumed.status_code, 200)
        self.server.archive.finalize(3, "GOOD", "accepted", [], 3)

        payload = self.client.get("/api/batches").json()
        listed = [
            item for item in payload["batches"]
            if item["batch_id"] == "SharedLot"
        ][0]
        stats = {
            entry["operator"]: entry for entry in listed["operator_stats"]
        }
        self.assertEqual(stats["Иванов Иван Иванович"]["parts"], 2)
        self.assertEqual(stats["Иванов Иван Иванович"]["good"], 1)
        self.assertEqual(stats["Иванов Иван Иванович"]["bad"], 1)
        self.assertEqual(stats["Сидоров Сидор Сидорович"]["parts"], 1)
        self.assertEqual(stats["Сидоров Сидор Сидорович"]["good"], 1)

        # В активной партии вклад показан тем же списком.
        active = {
            entry["operator"]: entry for entry in payload["operator_stats"]
        }
        self.assertEqual(active["Иванов Иван Иванович"]["parts"], 2)
        self.assertEqual(active["Сидоров Сидор Сидорович"]["parts"], 1)

        # В манифесте каждая деталь закреплена за своим оператором.
        with open(
            os.path.join(self.server.archive.batch_folder, "batch.json"),
            encoding="utf-8",
        ) as stream:
            manifest = json.load(stream)
        by_part = {part["part_id"]: part for part in manifest["parts"]}
        self.assertEqual(by_part[1]["operator"], "Иванов Иван Иванович")
        self.assertEqual(by_part[3]["operator"], "Сидоров Сидор Сидорович")

    def test_closed_batch_cannot_be_resumed_by_another_operator(self):
        archive = PartArchive(
            self.tmp.name, "ClosedForeign", "Другой Оператор",
            create_manifest=True,
        )
        archive.finalize(1, "GOOD", "accepted", [], 1)
        archive.close_batch()
        denied = self.client.post(
            "/api/batches/resume", json={"batch_id": "ClosedForeign"},
        )
        self.assertEqual(denied.status_code, 409)

    def test_resume_and_detach_preserve_open_batch(self):
        archive = PartArchive(
            self.tmp.name, "ContinueMe", self.server.operator_name,
            create_manifest=True,
        )
        archive.finalize(2, "CLEANUP", "review", [], 1)
        resumed = self.client.post(
            "/api/batches/resume", json={"batch_id": "ContinueMe"},
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(self.server.archive.next_part_id, 3)
        self.assertEqual(self.server.archive.operator, "Оператор Тестовый")

        detached = self.client.post("/api/batches/detach")
        self.assertEqual(detached.status_code, 200)
        self.assertFalse(self.server.batch_selected)
        self.assertTrue(os.path.isfile(os.path.join(archive.batch_folder, "batch.json")))

    def test_close_queues_nonempty_batch_and_removes_active_selection(self):
        self.client.post("/api/batches/open", json={"batch_id": "ToClose"})
        archive = self.server.archive
        expected_zip = archive.batch_folder + ".zip"
        archive.finalize(1, "GOOD", "accepted", [], 1)
        with mock.patch("json_sender.send_batch_json", return_value=False) as sender:
            result = self.client.post("/api/batches/close")
        self.assertEqual(result.status_code, 200)
        sender.assert_called_once()
        self.assertFalse(self.server.batch_selected)
        self.assertTrue(os.path.isfile(expected_zip))

    def test_custom_batch_id_validation_returns_400(self):
        response = self.client.post(
            "/api/batches/open", json={"batch_id": "../bad"},
        )
        self.assertEqual(response.status_code, 400)

    def test_open_and_resume_require_idle_line(self):
        self.server.line_status = {"state": "RUNNING"}
        response = self.client.post("/api/batches/open", json={})
        self.assertEqual(response.status_code, 409)


class BatchPanelStaticContractTest(unittest.TestCase):
    """Карточка партии разделена на блоки с заголовками: статистика и
    участники с личными итогами; панель активной партии — только имя."""

    def test_panel_markup_and_static_assets_present(self):
        index_html = (
            ROOT / "vision" / "ui" / "templates" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn('id="batch-list"', index_html)
        self.assertIn('id="active-batch-name"', index_html)
        # В панели активной партии — только имя: без создателя и вклада.
        self.assertNotIn('id="active-batch-owner"', index_html)
        self.assertNotIn('id="active-batch-operators"', index_html)

        batches_js = (
            ROOT / "vision" / "ui" / "static" / "js" / "batches.js"
        ).read_text(encoding="utf-8")
        # Карточка разбита на блоки с заголовками.
        self.assertIn("batch-card-section", batches_js)
        self.assertIn("batch-card-heading", batches_js)
        self.assertIn("СТАТИСТИКА", batches_js)
        self.assertIn("УЧАСТНИКИ", batches_js)
        self.assertIn("batch-card-stat", batches_js)
        self.assertIn("всего деталей", batches_js)
        # Ни разделения «мои/чужие», ни лишних сведений в карточке.
        self.assertNotIn("МОЯ", batches_js)
        self.assertNotIn("ОБЩАЯ", batches_js)
        self.assertNotIn("создал:", batches_js)
        self.assertNotIn("batchOwnerName", batches_js)

    def test_static_assets_are_served(self):
        server = UIServer()
        client = TestClient(server.app)
        self.assertEqual(client.get("/static/css/batches.css").status_code, 200)
        self.assertEqual(client.get("/static/js/batches.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
