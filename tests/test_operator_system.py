"""Тесты системы пользователей (операторов): вход по ФИО, метаданные партии, UI."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient

from config.operator_store import (
    MAX_OPERATOR_LENGTH,
    OperatorStore,
    normalise_operator_fio,
)
from inspection.part_archive import PartArchive
from json_sender import TARGET_JSON_NAME, scan_and_send_all_batches
from ui_simulation import LineSimulation
from vision.ui.server.server import UIServer


ROOT = Path(__file__).resolve().parents[1]


def make_frame(width=64, height=48, value=120):
    return np.full((height, width, 3), value, dtype=np.uint8)


class OperatorStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalise_operator_fio(self):
        self.assertEqual(
            normalise_operator_fio("  Иванов   Иван\tИванович \n"),
            "Иванов Иван Иванович",
        )
        for invalid in (None, 123, "", "   ", "А", "Я" * (MAX_OPERATOR_LENGTH + 1)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalise_operator_fio(invalid)

    def test_in_memory_store_mru_and_dedup(self):
        store = OperatorStore(root_folder=None)
        self.assertIsNone(store.storage_path)
        store.register_operator("Иванов И.И.")
        store.register_operator("Петров П.П.")
        store.register_operator("иванов и.и.")
        self.assertEqual(
            store.list_operators(),
            ["иванов и.и.", "Петров П.П."],
        )
        store.remove_operator("ПЕТРОВ П.П.")
        self.assertEqual(store.list_operators(), ["иванов и.и."])

    def test_persistent_store_saves_and_reloads(self):
        store = OperatorStore(root_folder=self.tmp.name)
        store.register_operator("Сидоров Сергей Петрович")
        store.register_operator("Кузнецова Анна Викторовна")

        reloaded = OperatorStore(root_folder=self.tmp.name)
        self.assertEqual(
            reloaded.list_operators(),
            ["Кузнецова Анна Викторовна", "Сидоров Сергей Петрович"],
        )

        reloaded.remove_operator("Сидоров Сергей Петрович")
        reloaded_again = OperatorStore(root_folder=self.tmp.name)
        self.assertEqual(
            reloaded_again.list_operators(),
            ["Кузнецова Анна Викторовна"],
        )

    def test_corrupted_file_tolerated(self):
        bad_path = os.path.join(self.tmp.name, "operators.json")
        with open(bad_path, "w", encoding="utf-8") as stream:
            stream.write("{broken json")
        store = OperatorStore(root_folder=self.tmp.name)
        self.assertEqual(store.list_operators(), [])
        store.register_operator("Смирнов А.А.")
        self.assertEqual(store.list_operators(), ["Смирнов А.А."])

    def test_set_root_folder_merges_existing_operators(self):
        dir1 = os.path.join(self.tmp.name, "a")
        dir2 = os.path.join(self.tmp.name, "b")
        other = OperatorStore(root_folder=dir2)
        other.register_operator("Орлов О.О.")

        store = OperatorStore(root_folder=dir1)
        store.register_operator("Волков В.В.")
        store.set_root_folder(dir2)
        self.assertEqual(
            store.list_operators(),
            ["Волков В.В.", "Орлов О.О."],
        )


class ArchiveOperatorMetadataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "archive")

    def tearDown(self):
        self.tmp.cleanup()

    def store_part(self, archive: PartArchive, part_id: int = 1):
        archive.store_frames(
            part_id,
            raw_frames={"TOP": make_frame()},
            annotated_frames={"TOP": make_frame(value=140)},
            raw_overlay_frames={"TOP": make_frame(value=160)},
        )
        return archive.finalize(
            part_id, "GOOD", decision="none", defects=[], step=1,
        )

    def test_operator_written_to_part_meta_batch_manifest_and_zip(self):
        archive = PartArchive(root_folder=self.root, batch_id="batch_op")
        self.assertEqual(archive.operator, "")
        archive.set_operator("  Соловьёв   Александр  ")
        self.assertEqual(archive.operator, "Соловьёв Александр")
        self.assertEqual(
            archive.get_settings(validate=False)["operator"],
            "Соловьёв Александр",
        )

        folder = self.store_part(archive, part_id=1)
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
            part_meta = json.load(f)
        self.assertEqual(part_meta["operator"], "Соловьёв Александр")

        manifest_path = os.path.join(archive.batch_folder, "batch.json")
        with open(manifest_path, encoding="utf-8") as f:
            open_manifest = json.load(f)
        self.assertEqual(open_manifest["operator"], "Соловьёв Александр")
        self.assertEqual(open_manifest["status"], "OPEN")

        # После начала записи деталей смена оператора в активной партии запрещена.
        with self.assertRaisesRegex(RuntimeError, "до начала текущей партии"):
            archive.set_operator("Другой Оператор")

        archive.close_manifest()
        queue_dir = Path(self.tmp.name) / "queue"
        remote_dir = Path(self.tmp.name) / "remote"
        remote_dir.mkdir()
        delivered = scan_and_send_all_batches(
            archive.root_folder,
            queue_dir=queue_dir,
            remote_root=remote_dir,
        )
        self.assertEqual(delivered, 1)
        sent_manifest = json.loads(
            (remote_dir / "batch_op" / TARGET_JSON_NAME).read_text(encoding="utf-8")
        )
        self.assertEqual(sent_manifest["status"], "CLOSED")
        self.assertEqual(sent_manifest["operator"], "Соловьёв Александр")

        zip_path = archive.compress()
        self.assertIsNotNone(zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zipped_manifest = json.loads(zf.read("batch.json").decode("utf-8"))
            zipped_part = json.loads(
                zf.read("GOOD/part_0001/meta.json").decode("utf-8")
            )
        self.assertEqual(zipped_manifest["operator"], "Соловьёв Александр")
        self.assertEqual(zipped_part["operator"], "Соловьёв Александр")


class UIServerOperatorApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.archive_root = os.path.join(self.tmp.name, "archive")
        self.server = UIServer()
        self.server.archive = PartArchive(
            root_folder=self.archive_root, batch_id="batch_api",
        )
        self.server.configure_operator_store(self.archive_root)
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE"}
        self.client = TestClient(self.server.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_login_flow_and_start_guard(self):
        status = self.client.get("/api/status").json()
        self.assertEqual(status["operator"]["name"], "")
        self.assertFalse(status["operator"]["logged_in"])
        self.assertTrue(status["operator"]["editable"])

        self.server.on_start = mock.Mock(return_value=True)
        blocked = self.client.post("/api/start")
        self.assertEqual(blocked.status_code, 409)
        self.server.on_start.assert_not_called()

        bad = self.client.post("/api/operator", json={"name": " "})
        self.assertEqual(bad.status_code, 400)

        ok = self.client.post(
            "/api/operator", json={"name": "Иванов Иван Иванович"},
        )
        self.assertEqual(ok.status_code, 200)
        data = ok.json()["operator"]
        self.assertEqual(data["name"], "Иванов Иван Иванович")
        self.assertTrue(data["logged_in"])
        self.assertIn("Иванов Иван Иванович", data["operators"])
        self.assertEqual(self.server.archive.operator, "Иванов Иван Иванович")
        self.server.open_batch("batch_api")

        started = self.client.post("/api/start")
        self.assertEqual(started.status_code, 200)
        self.server.on_start.assert_called_once()

    def test_switch_blocked_while_running_or_after_batch_started(self):
        self.client.post("/api/operator", json={"name": "Первый Оператор"})

        # До начала партии в IDLE сменить оператора можно.
        switched = self.client.post(
            "/api/operator", json={"name": "Второй Оператор"},
        )
        self.assertEqual(switched.status_code, 200)
        self.assertEqual(self.server.operator_name, "Второй Оператор")
        self.assertEqual(self.server.archive.operator, "Второй Оператор")

        # В движении смена запрещена.
        self.server.line_status = {"state": "RUNNING"}
        denied_running = self.client.post(
            "/api/operator", json={"name": "Третий Оператор"},
        )
        self.assertEqual(denied_running.status_code, 409)
        self.assertEqual(self.server.operator_name, "Второй Оператор")

        # После записи детали смена запрещена даже в STOPPED.
        self.server.line_status = {"state": "STOPPED"}
        self.server.archive.store_frames(
            1, raw_frames={"TOP": make_frame()}, annotated_frames={},
        )
        self.server.archive.finalize(1, "GOOD", "none", [], 1)
        denied_locked = self.client.post(
            "/api/operator", json={"name": "Третий Оператор"},
        )
        self.assertEqual(denied_locked.status_code, 409)
        self.assertEqual(self.server.archive.operator, "Второй Оператор")

    def test_remove_saved_operator_endpoint(self):
        self.client.post("/api/operator", json={"name": "Оператор Один"})
        self.client.post("/api/operator", json={"name": "Оператор Два"})
        res = self.client.post(
            "/api/operator/remove", json={"name": "Оператор Один"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["operator"]["operators"], ["Оператор Два"])

        bad = self.client.post("/api/operator/remove", json={"name": ""})
        self.assertEqual(bad.status_code, 400)


class SimulationOperatorBatchRolloverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "sim_archive")
        self.server = UIServer()
        self.server.splash_active = False
        self.server.archive = PartArchive(
            root_folder=self.root, batch_id="batch_sim_1",
        )
        self.server.configure_operator_store(self.root)
        self.sim = LineSimulation(self.server)
        self.server.can_switch_operator = self.sim.can_switch_operator
        self.server.on_operator_changed = self.sim.on_operator_changed

    def tearDown(self):
        self.sim.close()
        self.tmp.cleanup()

    def test_operator_carried_into_next_batch_and_switchable_after_compress(self):
        self.server.login_operator("Морозов Павел Игоревич")
        self.server.archive.store_frames(
            1, raw_frames={"TOP": make_frame()}, annotated_frames={},
        )
        self.server.archive.finalize(1, "GOOD", "none", [], 1)
        self.sim._finalize_archive_batch()
        self.assertTrue(self.sim.archive_compressed)
        self.sim.state = "STOPPED"
        self.server.line_status = {"state": "STOPPED"}

        # После финализации партии в симуляторе можно сменить оператора для новой партии.
        self.assertTrue(self.server.operator_editable())
        self.server.login_operator("Новикова Елена Сергеевна")
        self.assertFalse(self.sim.archive_compressed)
        self.assertEqual(
            self.server.archive.operator, "Новикова Елена Сергеевна",
        )


class OperatorHmiStaticContractTest(unittest.TestCase):
    def test_hmi_markup_and_static_assets_present(self):
        index_html = (
            ROOT / "vision" / "ui" / "templates" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn('data-ui-block="operator-login"', index_html)
        self.assertIn('data-ui-block="footer-operator"', index_html)
        self.assertIn('id="operator-current-name"', index_html)
        self.assertIn('id="archive-batch-operator"', index_html)
        self.assertIn('id="gallery-operator"', index_html)

        server = UIServer()
        client = TestClient(server.app)
        self.assertEqual(client.get("/static/css/operator.css").status_code, 200)
        self.assertEqual(client.get("/static/js/operator.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
