"""Тесты отметки пропущенных дефектов на камере и выгрузки ZIP для YOLO."""

from __future__ import annotations

import io
import json
import os
import tempfile
import types
import unittest
import zipfile
from unittest import mock

import cv2
import numpy as np
from fastapi.testclient import TestClient

from inspection.part_archive import PartArchive
from inspection.yolo_feedback import YoloFeedbackStore, get_role_classes
from vision.model_config import ROLE_TO_GROUP
from vision.ui.live_monitor import LiveMonitor
from vision.ui.server.server import UIServer


def make_clean_frame(width: int = 1280, height: int = 720, fill: int = 40):
    return np.full((height, width, 3), fill, dtype=np.uint8)


class YoloFeedbackCatalogTest(unittest.TestCase):
    def test_all_three_roles_have_russian_class_buttons(self):
        expected_roles = {"LEFT", "MIDDLE", "RIGHT"}
        self.assertEqual(set(ROLE_TO_GROUP.keys()), expected_roles)

        for role in expected_roles:
            classes = get_role_classes(role)
            self.assertGreaterEqual(len(classes), 2, role)
            self.assertEqual(classes[-1]["yolo_class"], "other")
            for item in classes:
                self.assertTrue(item["label"])
                self.assertTrue(str(item["color"]).startswith("#"))

    def test_side_roles_map_exact_models_and_class_ids(self):
        # Боковые камеры: окна и раковины.
        by_cls = {c["yolo_class"]: c for c in get_role_classes("LEFT")}
        self.assertEqual(
            by_cls["uneven_heights"]["model_path"], "weights/windows_4.pt",
        )
        self.assertEqual(by_cls["uneven_heights"]["class_id"], 0)
        self.assertEqual(
            by_cls["window_sinks"]["model_path"], "weights/shells.pt",
        )
        self.assertEqual(by_cls["window_sinks"]["class_id"], 0)

    def test_middle_role_maps_glass_and_welding_models(self):
        by_cls = {c["yolo_class"]: c for c in get_role_classes("MIDDLE")}
        self.assertEqual(
            by_cls["bottom_glass"]["model_path"],
            "weights/bottom_glass_new_v3.pt",
        )
        self.assertEqual(by_cls["bottom_glass"]["class_id"], 0)
        self.assertEqual(
            by_cls["welding"]["model_path"], "weights/welding_new_2.pt",
        )
        self.assertEqual(by_cls["welding"]["class_id"], 0)


class YoloFeedbackStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = YoloFeedbackStore(root_folder=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_frame_stays_pure_and_hint_has_annotations(self):
        frame = make_clean_frame(fill=32)
        saved = self.store.save_task(
            role="MIDDLE",
            clean_frame=frame,
            marks=[
                {
                    "shape": "polygon",
                    "yolo_class": "bottom_glass",
                    "points": [
                        [0.25, 0.25], [0.45, 0.25],
                        [0.45, 0.50], [0.25, 0.50],
                    ],
                },
                {
                    "shape": "bbox",
                    "yolo_class": "glass",
                    "points": [[0.60, 0.30], [0.80, 0.60]],
                },
            ],
            comment="Пропущена мелкая раковина и стекло",
            existing_detections=[
                {
                    "class": "contacts",
                    "confidence": 0.91,
                    "bbox": [10.0, 10.0, 80.0, 80.0],
                    "model_path": "weights/4/contacts.pt",
                },
            ],
            source_kind="inspected",
            part_id=7,
            step=12,
        )

        task_id = saved["task_id"]
        clean_path = self.store.get_item_image_path(task_id, "clean")
        hint_path = self.store.get_item_image_path(task_id, "hint")
        self.assertIsNotNone(clean_path)
        self.assertIsNotNone(hint_path)

        clean_decoded = cv2.imread(clean_path, cv2.IMREAD_COLOR)
        hint_decoded = cv2.imread(hint_path, cv2.IMREAD_COLOR)
        self.assertEqual(clean_decoded.shape, (720, 1280, 3))
        self.assertEqual(hint_decoded.shape, (720, 1280, 3))

        # Чистый кадр не должен содержать ни одного пикселя обводки!
        max_diff = int(np.max(np.abs(
            clean_decoded.astype(np.int16) - frame.astype(np.int16)
        )))
        self.assertLessEqual(max_diff, 2)
        # На шпаргалке разметка гарантированно присутствует.
        hint_diff = int(np.max(np.abs(
            hint_decoded.astype(np.int16) - frame.astype(np.int16)
        )))
        self.assertGreater(hint_diff, 80)

    def test_single_line_stroke_and_zero_height_bbox_get_valid_nonzero_area(self):
        frame = make_clean_frame(fill=48)
        saved = self.store.save_task(
            role="RIGHT",
            clean_frame=frame,
            marks=[
                {
                    "shape": "polygon",
                    "yolo_class": "omission-long",
                    # Оператор провёл одну прямую линию вдоль полосы пропуска
                    "points": [[0.20, 0.50], [0.40, 0.50], [0.60, 0.50]],
                },
                {
                    "shape": "bbox",
                    "yolo_class": "contacts-long",
                    # Строго горизонтальная протяжка без высоты
                    "points": [[0.25, 0.30], [0.55, 0.30]],
                },
            ],
        )
        self.assertEqual(saved["marks_count"], 2)
        meta_path = os.path.join(
            self.store.items_dir, saved["task_id"], "meta.json",
        )
        with open(meta_path, encoding="utf-8") as stream:
            meta = json.load(stream)
        for mark in meta["marks"]:
            _cx, _cy, bw, bh = mark["yolo_bbox_cxcywh"]
            self.assertGreater(bw, 0.0)
            self.assertGreater(bh, 0.0)
            self.assertGreaterEqual(len(mark["points_norm"]), 4)

    def test_summary_separates_shared_model_classes_and_roles(self):
        frame = make_clean_frame()
        self.store.save_task(
            role="LEFT",
            clean_frame=frame,
            marks=[{
                "shape": "bbox",
                "yolo_class": "window_sinks",
                "points": [[0.1, 0.1], [0.3, 0.3]],
            }],
        )
        self.store.save_task(
            role="MIDDLE",
            clean_frame=frame,
            marks=[{
                "shape": "bbox",
                "yolo_class": "welding",
                "points": [[0.2, 0.2], [0.5, 0.4]],
            }],
        )
        summary = self.store.get_summary()
        pairs = {
            (entry["camera_role"], entry["yolo_class"])
            for entry in summary["by_model"]
        }
        self.assertEqual(
            pairs,
            {("LEFT", "window_sinks"), ("MIDDLE", "welding")},
        )

    def test_failed_disk_write_does_not_mark_tasks_exported(self):
        frame = make_clean_frame()
        self.store.save_task(
            role="MIDDLE",
            clean_frame=frame,
            marks=[{
                "shape": "bbox",
                "yolo_class": "bottom_glass",
                "points": [[0.2, 0.2], [0.4, 0.4]],
            }],
        )
        bad_dest = os.path.join(self.tmp.name, "fail.zip")
        with mock.patch.object(
            YoloFeedbackStore, "_build_zip_unlocked",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaises(OSError):
                self.store.export_zip_to_path(bad_dest, only_pending=True)

        # Очередь новых обязана сохраниться при сбое записи на флешку/диск!
        self.assertEqual(self.store.status_counts()["pending"], 1)
        self.assertFalse(os.path.exists(bad_dest))
        leftovers = [
            name for name in os.listdir(self.tmp.name)
            if name.endswith(".zip.tmp")
        ]
        self.assertEqual(leftovers, [])

    def test_export_zip_groups_by_target_model_and_marks_exported(self):
        frame = make_clean_frame(fill=50)
        self.store.save_task(
            role="MIDDLE",
            clean_frame=frame,
            marks=[
                {
                    "shape": "polygon",
                    "yolo_class": "bottom_glass",
                    "points": [[0.2, 0.2], [0.3, 0.2], [0.3, 0.35]],
                },
                {
                    "shape": "bbox",
                    "yolo_class": "welding",
                    "points": [[0.4, 0.4], [0.6, 0.65]],
                },
            ],
            comment="Два класса в разных моделях",
        )
        self.assertEqual(self.store.status_counts()["pending"], 1)

        zip_bytes, count, filename = self.store.build_export_zip(
            only_pending=True, mark_exported=True,
        )
        self.assertEqual(count, 1)
        self.assertTrue(filename.endswith(".zip"))
        self.assertEqual(self.store.status_counts()["pending"], 0)
        self.assertEqual(self.store.status_counts()["total"], 1)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
            self.assertIn("README_YOLO.txt", names)
            self.assertIn("manifest.json", names)
            self.assertFalse(
                any(
                    n.endswith("classes.txt") or n.endswith("frames.txt")
                    for n in names
                ),
                names,
            )

            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            self.assertEqual(manifest["exported_count"], 1)

            # Кадр и шпаргалка — в одной папке модели, номер кадра в
            # имени файла. Ни классы, ни индекс, ни draft/meta нет.
            self.assertIn("datasets/MIDDLE__bottom_glass_new_v3/001_image.jpg", names)
            self.assertIn("datasets/MIDDLE__bottom_glass_new_v3/001_hint.jpg", names)
            self.assertFalse(
                any("draft_label" in n or "meta.json" in n for n in names),
                names,
            )

        with self.assertRaises(ValueError):
            self.store.build_export_zip(only_pending=True)

        _all_bytes, all_count, _ = self.store.build_export_zip(
            only_pending=False, mark_exported=False,
        )
        self.assertEqual(all_count, 1)

    def test_export_numbers_frames_per_model(self):
        frame = make_clean_frame(fill=30)
        for index in range(1, 4):
            self.store.save_task(
                role="MIDDLE",
                clean_frame=frame,
                marks=[{
                    "shape": "bbox",
                    "yolo_class": "bottom_glass",
                    "points": [[0.2, 0.2], [0.4, 0.4]],
                }],
                comment=f"Кадр {index}",
                part_id=100 + index,
            )

        zip_bytes, count, _filename = self.store.build_export_zip(
            only_pending=True, mark_exported=False,
        )
        self.assertEqual(count, 3)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = set(zf.namelist())
            for index in (1, 2, 3):
                prefix = f"datasets/MIDDLE__bottom_glass_new_v3/{index:03d}_"
                self.assertIn(f"{prefix}image.jpg", names)
                self.assertIn(f"{prefix}hint.jpg", names)
            self.assertFalse(
                any(
                    n.endswith("frames.txt") or n.endswith("classes.txt")
                    for n in names
                ),
                names,
            )

    def test_part_archive_compress_preserves_yolo_tasks(self):
        archive = PartArchive(root_folder=self.tmp.name, batch_id="batch_1")
        frame = make_clean_frame()
        archive.store_frames(1, {"MIDDLE": frame}, {"MIDDLE": frame})
        archive.finalize(1, "GOOD", "ok", [], step=1)

        store = YoloFeedbackStore(root_folder=self.tmp.name)
        saved = store.save_task(
            role="MIDDLE",
            clean_frame=frame,
            marks=[{
                "shape": "bbox",
                "yolo_class": "bottom_glass",
                "points": [[0.1, 0.1], [0.3, 0.3]],
            }],
        )
        zip_batch = archive.compress()
        self.assertIsNotNone(zip_batch)
        self.assertTrue(os.path.isfile(
            store.get_item_image_path(saved["task_id"], "clean")
        ))


class YoloServerRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cyrillic_root = os.path.join(self.tmp.name, "Архив_Цех_7")
        self.server = UIServer()
        self.server.archive = PartArchive(
            root_folder=cyrillic_root, batch_id="batch_ui",
        )
        self.client = TestClient(self.server.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_yolo_snapshot_rejected_outside_jog_and_while_jog_busy(self):
        frame = make_clean_frame(fill=65)
        # 1) RUNNING — строго запрещено (409)
        self.server.update(
            frames={"MIDDLE": frame},
            line_status={
                "state": "RUNNING",
                "step": 4,
                "jog": {"active": False, "busy": False},
            },
        )
        resp_running = self.client.post(
            "/api/yolo-tasks/snapshot", json={"role": "MIDDLE"},
        )
        self.assertEqual(resp_running.status_code, 409)

        # 2) IDLE, но JOG ещё не активирован — запрещено (409)
        self.server.update(
            line_status={
                "state": "IDLE",
                "step": 4,
                "jog": {"active": False, "busy": False},
            },
        )
        resp_no_jog = self.client.post(
            "/api/yolo-tasks/snapshot", json={"role": "MIDDLE"},
        )
        self.assertEqual(resp_no_jog.status_code, 409)

        # 3) JOG активен, но лента движется (busy=True) — запрещено (409)
        self.server.update(
            line_status={
                "state": "IDLE",
                "step": 4,
                "jog": {"active": True, "busy": True},
            },
        )
        resp_busy = self.client.post(
            "/api/yolo-tasks/snapshot", json={"role": "MIDDLE"},
        )
        self.assertEqual(resp_busy.status_code, 409)

    def test_jog_snapshot_save_export_and_delete_cycle(self):
        jog_frame = make_clean_frame(fill=90)
        self.server.update(
            frames={"MIDDLE": jog_frame, "LEFT": jog_frame},
            vision_results={
                "MIDDLE": [{
                    "class": "contacts",
                    "confidence": 0.88,
                    "bbox": [20.0, 20.0, 120.0, 120.0],
                    "mask": None,
                }],
            },
            line_status={
                "state": "PAUSED",
                "step": 4,
                # Трёхкамерная линия: все камеры смотрят в зону +0,
                # поэтому оба снимка берут корпус именно с этой позиции.
                "line_parts": [
                    {"id": 2, "position": 0, "category": "GOOD"},
                    {"id": 6, "position": 4, "category": "UNKNOWN"},
                ],
                "jog": {"active": True, "busy": False},
                "selected_analysis": {"active": True, "role": "MIDDLE"},
                "process": {"phase": "PAUSED", "step": 4, "part_id": None},
            },
        )

        in_resp = self.client.post(
            "/api/yolo-tasks/snapshot",
            json={"role": "LEFT"},
        )
        self.assertEqual(in_resp.status_code, 200)
        self.assertEqual(in_resp.json()["snapshot"]["part_id"], 2)
        self.assertEqual(in_resp.json()["snapshot"]["source_kind"], "jog")

        resp = self.client.post(
            "/api/yolo-tasks/snapshot",
            json={"role": "MIDDLE"},
        )
        self.assertEqual(resp.status_code, 200)
        snap = resp.json()["snapshot"]
        self.assertEqual(snap["source_kind"], "analysis")
        self.assertEqual(snap["part_id"], 2)
        self.assertEqual(snap["step"], 4)
        self.assertTrue(snap["has_detections"])

        save_resp = self.client.post(
            "/api/yolo-tasks/save",
            json={
                "snapshot_id": snap["snapshot_id"],
                "comment": "В режиме JOG на камере TOP",
                "marks": [{
                    "shape": "polygon",
                    "yolo_class": "bottom_glass",
                    "points": [[0.2, 0.2], [0.4, 0.2], [0.3, 0.4]],
                }],
            },
        )
        self.assertEqual(save_resp.status_code, 200)
        task_id = save_resp.json()["task"]["task_id"]

        clean_path = self.server.get_yolo_store().get_item_image_path(
            task_id, "clean",
        )
        saved_img = cv2.imdecode(
            np.fromfile(clean_path, dtype=np.uint8), cv2.IMREAD_COLOR,
        )
        self.assertAlmostEqual(float(saved_img.mean()), 90.0, delta=2.0)

        # Если линия перешла в RUNNING, повторное сохранение снимка запрещено
        self.server.update(
            line_status={"state": "RUNNING", "jog": {"active": False, "busy": False}},
        )
        blocked_save = self.client.post(
            "/api/yolo-tasks/save",
            json={
                "snapshot_id": snap["snapshot_id"],
                "marks": [{
                    "shape": "bbox",
                    "yolo_class": "bottom_glass",
                    "points": [[0.2, 0.2], [0.4, 0.4]],
                }],
            },
        )
        self.assertEqual(blocked_save.status_code, 409)

        st = self.client.get("/api/status").json()
        self.assertEqual(st["yolo_tasks"]["pending"], 1)

        zip_resp = self.client.get("/api/yolo-tasks/export?scope=pending")
        self.assertEqual(zip_resp.status_code, 200)
        self.assertEqual(zip_resp.headers["content-type"], "application/zip")
        self.assertEqual(zip_resp.headers["x-exported-count"], "1")

        st_after = self.client.get("/api/status").json()
        self.assertEqual(st_after["yolo_tasks"]["pending"], 0)
        self.assertEqual(st_after["yolo_tasks"]["total"], 1)

        del_resp = self.client.post(f"/api/yolo-tasks/item/{task_id}/delete")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json()["summary"]["total_count"], 0)

    def test_jog_step_api_endpoint_and_webview_save_dialog(self):
        step_calls = []
        self.server.on_jog_step = lambda direction: (
            step_calls.append(direction) or True
        )
        bad_dir = self.client.post("/api/jog/step", json={"direction": "up"})
        self.assertEqual(bad_dir.status_code, 400)

        ok_step = self.client.post("/api/jog/step", json={"direction": "+"})
        self.assertEqual(ok_step.status_code, 200)
        self.assertEqual(step_calls, ["+"])

        frame = make_clean_frame(fill=77)
        self.server.update(
            frames={"LEFT": frame},
            line_status={
                "state": "IDLE",
                "step": 0,
                "jog": {"active": True, "busy": False},
            },
        )
        snap = self.client.post(
            "/api/yolo-tasks/snapshot",
            json={"role": "LEFT"},
        ).json()["snapshot"]

        monitor = LiveMonitor()
        monitor.server.archive = self.server.archive
        fake_window = mock.Mock()
        monitor._webview_window = fake_window
        fake_webview = types.SimpleNamespace(SAVE_DIALOG=20, FOLDER_DIALOG=10)

        # Пустая очередь должна отклоняться ДО вызова системного диалога
        with mock.patch.dict("sys.modules", {"webview": fake_webview}):
            empty_res = monitor.webview_api.export_yolo_tasks_zip("pending")
        self.assertFalse(empty_res["ok"])
        fake_window.create_file_dialog.assert_not_called()

        # Сохраняем задачу и проверяем возврат обычной строки (поведение SAVE_DIALOG в Windows)
        self.client.post(
            "/api/yolo-tasks/save",
            json={
                "snapshot_id": snap["snapshot_id"],
                "marks": [{
                    "shape": "bbox",
                    "yolo_class": "window_sinks",
                    "points": [[0.3, 0.3], [0.5, 0.5]],
                }],
            },
        )
        target_zip = os.path.join(self.tmp.name, "exported_dialog.zip")
        fake_window.create_file_dialog.return_value = target_zip

        with mock.patch.dict("sys.modules", {"webview": fake_webview}):
            res = monitor.webview_api.export_yolo_tasks_zip("pending")

        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 1)
        self.assertTrue(os.path.isfile(target_zip))
        with zipfile.ZipFile(target_zip, "r") as zf:
            self.assertIn(
                "datasets/LEFT__shells/001_image.jpg",
                zf.namelist(),
            )


if __name__ == "__main__":
    unittest.main()
