"""UI-сервер: публикация кадров/статуса, пороги, архив, HTTP-маршруты.

``UIServer`` тестируется напрямую (методы) и через FastAPI TestClient
(маршруты /api/*, /frame/*, /stream/*). Сервер не поднимает uvicorn —
только приложение FastAPI.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient

from domain.threshold_loader import ThresholdLoader
from inspection.batch_manager import NO_BATCH_MESSAGE, BatchManager
from inspection.part_archive import safe_component
from inspection.operator_store import NO_OPERATOR_MESSAGE, OperatorStore
from vision.ui.server.server import UIServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLDS_PATH = os.path.join(REPO_ROOT, "thresholds.json")

OPERATOR = "Иванов Иван Иванович"
RESUME_OPERATOR = "Петров Пётр Петрович"
PASSWORD = "1234"


def make_frame(value=100):
    return np.full((64, 96, 3), value, dtype=np.uint8)


class UIServerTest(unittest.TestCase):
    def setUp(self):
        self.server = UIServer()
        self.client = TestClient(self.server.app)

    # ---------- update / кадры ----------

    def test_update_publishes_frames_and_increments_version(self):
        version_before = self.server._cache_version
        frame = make_frame()
        self.server.update(frames={"TOP": frame})
        self.assertIs(self.server.frames["TOP"], frame)
        self.assertEqual(self.server._cache_version, version_before + 1)
        self.assertEqual(self.server.get_frame_version("TOP"), 1)

    def test_update_same_frame_object_no_invalidate(self):
        frame = make_frame()
        self.server.update(frames={"TOP": frame})
        version = self.server._cache_version
        self.server.update(frames={"TOP": frame})
        self.assertEqual(self.server._cache_version, version)

    def test_mutated_vision_results_invalidate_cache(self):
        # Регрессия: ProductionCycle дополняет один и тот же dict
        # (_last_vision_results.update(...)) по стадиям шага. Сравнение по
        # identity считало такую публикацию «без изменений», и RAW-разметка
        # не попадала в кэш JPEG — в UI отображался кадр без детекций.
        frame = make_frame()
        vision = {}
        self.server.update(frames={"TOP": frame}, vision_results=vision)
        before = self.server._get_or_render("TOP", "RAW", "main")
        version = self.server._cache_version

        vision["TOP"] = [{
            "class": "glass", "confidence": 0.9,
            "bbox": [1.0, 1.0, 50.0, 50.0], "mask": None,
        }]
        self.server.update(frames={"TOP": frame}, vision_results=vision)

        self.assertGreater(self.server._cache_version, version)
        self.assertNotEqual(
            before, self.server._get_or_render("TOP", "RAW", "main"),
        )

    def test_unchanged_vision_results_do_not_invalidate(self):
        # Обратная сторона: повторная публикация того же содержимого не
        # должна дёргать кэш, иначе фронтенд перезапрашивает кадры зря.
        vision = {"TOP": [{"class": "glass", "confidence": 0.5}]}
        self.server.update(frames={"TOP": make_frame()}, vision_results=vision)
        version = self.server._cache_version
        self.server.update(vision_results=dict(vision))
        self.assertEqual(self.server._cache_version, version)

    def test_vision_comparison_is_cheap_under_lock(self):
        # Сравнение выполняется под общим self.lock, который держат и
        # /api/status, и рендер кадров. Полный рекурсивный обход масок
        # (тысячи точек) занимал десятки миллисекунд и подтормаживал UI.
        detections = {
            role: [{
                "class": "platform", "confidence": 0.83,
                "bbox": [1.0, 2.0, 3.0, 4.0],
                "mask": [[float(i), float(i)] for i in range(400)],
            } for _ in range(12)]
            for role in ("INPUT_LEFT", "SPIDER_LEFT", "TOP")
        }
        started = time.monotonic()
        for _ in range(10):
            UIServer._vision_signature(detections)
        elapsed = (time.monotonic() - started) / 10

        self.assertLess(elapsed, 0.005)

    def test_vision_results_snapshot_is_isolated(self):
        # Опубликованное состояние не должно меняться «задним числом»
        # вместе с исходным dict вызывающей стороны.
        vision = {"TOP": [{"class": "glass", "confidence": 0.5}]}
        self.server.update(vision_results=vision)
        vision["TOP"].append({"class": "pin", "confidence": 0.7})
        self.assertEqual(len(self.server.vision_results["TOP"]), 1)

    def test_update_rule_results_invalidate(self):
        from domain.defect_rules import RuleResult
        self.server.update(rule_results=[RuleResult("a", False)])
        version = self.server._cache_version
        self.server.update(rule_results=[RuleResult("a", False)])
        self.assertEqual(self.server._cache_version, version)
        self.server.update(rule_results=[RuleResult("a", True)])
        self.assertGreater(self.server._cache_version, version)

    def test_update_line_status_and_recent_parts(self):
        self.server.update(line_status={"state": "IDLE"},
                           recent_parts=[1, 2])
        self.assertEqual(self.server.line_status["state"], "IDLE")
        self.assertEqual(self.server.recent_parts, [1, 2])

    def test_frame_update_invalidates_only_that_role_cache(self):
        # Обновление кадра одной камеры не должно сбрасывать готовые
        # превью остальных (иначе вторичные камеры не успевают грузиться).
        self.server.update(frames={
            "TOP": make_frame(10), "INPUT_LEFT": make_frame(20),
        })
        for role in ("TOP", "INPUT_LEFT"):
            response = self.client.get(f"/frame/{role}?preview=1")
            self.assertEqual(response.status_code, 200)
        mode = self.server.mode
        self.assertIn(("TOP", mode, "preview"), self.server._jpeg_cache)
        self.assertIn(("INPUT_LEFT", mode, "preview"), self.server._jpeg_cache)
        # Меняется только кадр TOP.
        self.server.update(frames={"TOP": make_frame(99)})
        self.assertNotIn(("TOP", mode, "preview"), self.server._jpeg_cache)
        self.assertIn(("INPUT_LEFT", mode, "preview"), self.server._jpeg_cache)

    def test_rules_equal_with_numpy(self):
        self.assertTrue(UIServer._rules_equal(
            [{"mask": np.zeros((2, 2))}], [{"mask": np.zeros((2, 2))}],
        ))
        self.assertFalse(UIServer._rules_equal(
            [{"mask": np.zeros((2, 2))}], [{"mask": np.ones((2, 2))}],
        ))

    # ---------- камеры ----------

    def test_set_camera_roles(self):
        self.server.set_camera_roles({
            "TOP": 2, "INPUT_LEFT": 0,
        })
        self.assertEqual(self.server.camera_roles, ["TOP", "INPUT_LEFT"])
        self.assertEqual(self.server.camera_mapping, {"TOP": 2, "INPUT_LEFT": 0})
        self.assertEqual(self.server.active_camera_role, "TOP")

    def test_set_active_camera_role(self):
        self.server.set_camera_roles({"TOP": 2, "INPUT_LEFT": 0})
        self.assertTrue(self.server.set_active_camera_role("INPUT_LEFT"))
        self.assertEqual(self.server.active_camera_role, "INPUT_LEFT")
        self.assertFalse(self.server.set_active_camera_role("NOPE"))

    def test_set_active_camera_callback(self):
        self.server.set_camera_roles({"TOP": 2, "INPUT_LEFT": 0})
        calls = []
        self.server.on_active_camera_changed = lambda role: calls.append(role)
        self.server.set_active_camera_role("INPUT_LEFT")
        self.assertEqual(calls, ["INPUT_LEFT"])

    # ---------- пороги ----------

    def test_thresholds_editable(self):
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE"}
        self.assertTrue(self.server.thresholds_editable())
        self.server.line_status = {"state": "RUNNING"}
        self.assertFalse(self.server.thresholds_editable())
        self.server.splash_active = True
        self.assertFalse(self.server.thresholds_editable())

    def test_thresholds_payload_without_data(self):
        payload = self.server.build_thresholds_payload()
        self.assertFalse(payload["available"])

    def test_thresholds_payload_with_data(self):
        thresholds = ThresholdLoader(THRESHOLDS_PATH).get_all()
        self.server.thresholds = thresholds
        payload = self.server.build_thresholds_payload("TOP")
        self.assertTrue(payload["available"])
        self.assertIn("rules", payload)
        self.assertIn("top_contacts", {
            group["rule"] for group in payload["rules"]
        })

    def test_thresholds_payload_all_roles(self):
        thresholds = ThresholdLoader(THRESHOLDS_PATH).get_all()
        self.server.thresholds = thresholds
        payload = self.server.build_thresholds_payload()
        self.assertIn("TOP", payload["roles"])

    def test_apply_thresholds_requires_callback(self):
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE"}
        with self.assertRaisesRegex(RuntimeError, "не подключено"):
            self.server.apply_thresholds("TOP", {})

    def test_apply_thresholds_calls_callback(self):
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE"}
        self.server.thresholds = {
            "TOP.top_contacts_min_confidence": 0.3,
        }
        self.server.on_thresholds_apply = mock.Mock(return_value={
            "TOP.top_contacts_min_confidence": 0.5,
        })
        result = self.server.apply_thresholds(
            "TOP", {"top_contacts_min_confidence": 0.5},
        )
        self.assertTrue(result["available"])
        self.assertEqual(
            self.server.thresholds["TOP.top_contacts_min_confidence"], 0.5,
        )
        self.assertEqual(self.server.thresholds_revision, 1)
        self.server.on_thresholds_apply.assert_called_once_with(
            "TOP", {"top_contacts_min_confidence": 0.5}, {},
        )

    def test_reload_thresholds_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            ThresholdLoader.save_file(
                path, ThresholdLoader(THRESHOLDS_PATH).get_all(),
            )
            self.server.thresholds_path = path
            self.server.thresholds_file_mtime = None
            self.server.splash_active = False
            self.server.line_status = {"state": "IDLE"}
            self.assertTrue(self.server.reload_thresholds_from_file())
            self.assertEqual(self.server.thresholds_revision, 1)
            # Повторный вызов без изменения файла — False.
            self.assertFalse(self.server.reload_thresholds_from_file())

    def test_reload_thresholds_not_editable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            ThresholdLoader.save_file(
                path, ThresholdLoader(THRESHOLDS_PATH).get_all(),
            )
            self.server.thresholds_path = path
            self.server.splash_active = False
            self.server.line_status = {"state": "RUNNING"}
            self.assertFalse(self.server.reload_thresholds_from_file())

    def test_reload_thresholds_missing_path(self):
        self.assertFalse(self.server.reload_thresholds_from_file())

    def test_reload_thresholds_broken_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{broken")
            self.server.thresholds_path = path
            self.assertFalse(self.server.reload_thresholds_from_file())

    def test_thresholds_file_mtime_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thresholds.json")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{}")
            self.server.thresholds_path = path
            self.assertTrue(self.server.thresholds_file_mtime_changed())
            self.server.thresholds_file_mtime = os.path.getmtime(path)
            self.assertFalse(self.server.thresholds_file_mtime_changed())

    # ---------- boot ----------

    def test_boot_steps(self):
        self.server.boot_step_start("cameras", "Камеры")
        self.assertEqual(self.server.boot_steps["cameras"], "running")
        self.server.boot_step_done("cameras")
        self.assertEqual(self.server.boot_steps["cameras"], "done")
        self.server.boot_step_error("serial", "boom")
        self.assertEqual(self.server.boot_steps["serial"], "error")
        self.assertEqual(self.server.boot_error, "boom")
        self.server.boot_complete()
        self.assertFalse(self.server.splash_active)

    def test_splash_log_capped(self):
        for i in range(40):
            self.server._append_log(f"line {i}")
        self.assertEqual(len(self.server.splash_log), 30)

    def test_set_splash_status(self):
        self.server.set_splash_status("текст")
        self.assertEqual(self.server.boot_message, "текст")

    # ---------- архив ----------

    def test_archive_payload_without_archive(self):
        payload = self.server.build_archive_payload()
        self.assertFalse(payload.get("available", False))

    def test_archive_ready_for_start(self):
        self.server.archive = mock.Mock(root_folder="/archive")
        ok, message = self.server.archive_ready_for_start()
        self.assertTrue(ok)
        self.assertIsNone(message)
        self.server.archive.validate_root.assert_called_once_with("/archive")

    def test_archive_is_required_for_start(self):
        ok, message = self.server.archive_ready_for_start()
        self.assertFalse(ok)
        self.assertIn("не инициализирован", message)

    def test_apply_archive_settings_requires_archive(self):
        with self.assertRaisesRegex(RuntimeError, "не инициализирован"):
            self.server.apply_archive_settings({})

    def test_apply_archive_settings(self):
        archive = mock.Mock()
        archive.can_reconfigure.return_value = True
        archive.reconfigure.return_value = {"root_path": "/tmp/new"}
        archive.get_settings.return_value = {"root_path": "/tmp/x"}
        self.server.archive = archive
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE"}
        with mock.patch(
            "config.archive_config.save_archive_config",
        ) as save:
            result = self.server.apply_archive_settings({
                "root_path": "/tmp/new",
                "enabled": False,
                "jpeg_quality": 70,
            })
        self.assertEqual(result["root_path"], "/tmp/new")
        archive.reconfigure.assert_called_once_with(root_folder="/tmp/new")
        save.assert_called_once()

    # ---------- stream / frame ----------

    def test_get_stream_jpeg_no_frame(self):
        jpeg, version = self.server.get_stream_jpeg("TOP")
        self.assertIsNone(jpeg)
        self.assertEqual(version, 0)

    def test_get_stream_jpeg_with_frame(self):
        self.server.update(frames={"TOP": make_frame()})
        jpeg, version = self.server.get_stream_jpeg("TOP", "RAW")
        self.assertIsNotNone(jpeg)
        self.assertGreater(version, 0)
        self.assertEqual(jpeg[:2], b"\xff\xd8")  # JPEG magic

    def test_get_stream_jpeg_rules_mode(self):
        self.server.update(frames={"TOP": make_frame()})
        jpeg, _ = self.server.get_stream_jpeg("TOP", "RULES")
        self.assertIsNotNone(jpeg)

    def test_render_and_encode(self):
        rendered = self.server._render(
            make_frame(), "TOP", "RAW", [], [],
        )
        self.assertEqual(rendered.shape, (64, 96, 3))
        jpeg = self.server._encode_jpeg(make_frame())
        self.assertEqual(jpeg[:2], b"\xff\xd8")

    def test_resize_for_preview(self):
        resized = UIServer._resize_for_preview(np.zeros((720, 1280, 3), dtype=np.uint8))
        self.assertEqual(resized.shape[1], UIServer.PREVIEW_MAX_WIDTH)

    def test_sort_by_order(self):
        self.assertEqual(
            UIServer._sort_by_order(["TOP", "INPUT_LEFT", "X"]),
            ["INPUT_LEFT", "TOP", "X"],
        )

    # ---------- HTTP ----------

    def test_api_cameras(self):
        self.server.set_camera_roles({"TOP": 2})
        response = self.client.get("/api/cameras")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["camera_ids"], {"TOP": 2})

    def test_api_boot(self):
        self.server.boot_step_start("cameras")
        response = self.client.get("/api/boot")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["steps"][0]["status"], "running")

    def test_api_status(self):
        self.server.update(frames={"TOP": make_frame()},
                           line_status={"state": "IDLE"})
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["line_status"]["state"], "IDLE")

    def test_api_mode(self):
        self.assertEqual(self.client.get("/api/mode").json()["mode"], "RULES")
        response = self.client.post("/api/mode/RAW")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.server.mode, "RAW")

    def test_api_active_camera(self):
        self.server.set_camera_roles({"TOP": 2})
        response = self.client.post("/api/active_camera/TOP")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.server.active_camera_role, "TOP")

    def test_api_thresholds_get(self):
        self.server.thresholds = ThresholdLoader(THRESHOLDS_PATH).get_all()
        response = self.client.get("/api/thresholds?role=TOP")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

    def test_api_thresholds_post_without_callback(self):
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE"}
        response = self.client.post("/api/thresholds", json={
            "role": "TOP", "values": {"top_contacts_min_confidence": 0.5},
        })
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])

    def test_api_thresholds_post_empty_values_400(self):
        response = self.client.post("/api/thresholds", json={
            "role": "TOP", "values": {},
        })
        self.assertEqual(response.status_code, 400)

    def test_api_start_503_without_callback(self):
        self.server.archive = mock.Mock(root_folder="/archive")
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["ok"])

    def test_api_start_callback_false_409(self):
        self.server.archive = mock.Mock(root_folder="/archive")
        self.server.on_start = lambda: False
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 409)

    def test_api_start_callback_exception_500(self):
        self.server.archive = mock.Mock(root_folder="/archive")

        def boom():
            raise RuntimeError("cycle broken")

        self.server.on_start = boom
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 500)
        self.assertIn("cycle broken", response.json()["error"])

    def test_api_start_callback_ok(self):
        self.server.archive = mock.Mock(root_folder="/archive")
        self.server.on_start = mock.Mock(return_value=True)
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 200)
        self.server.on_start.assert_called_once()

    def test_api_diagnostics_endpoints(self):
        self.server.on_camera_diagnostic = mock.Mock(return_value=True)
        response = self.client.post("/api/diagnostics/cameras")
        self.assertEqual(response.status_code, 200)
        self.server.on_vision_rule_diagnostic = mock.Mock(return_value=True)
        self.assertEqual(
            self.client.post("/api/diagnostics/vision-rules").status_code, 200,
        )

    def test_api_jog(self):
        self.server.on_jog_enter = mock.Mock(return_value=True)
        self.assertEqual(self.client.post("/api/jog/enter").status_code, 200)
        self.server.on_jog_exit = mock.Mock(return_value=True)
        self.assertEqual(self.client.post("/api/jog/exit").status_code, 200)

    def test_frame_route_404_without_frames(self):
        response = self.client.get("/frame/TOP")
        self.assertEqual(response.status_code, 404)

    def test_frame_route_with_frame(self):
        self.server.update(frames={"TOP": make_frame()})
        response = self.client.get("/frame/TOP")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.content[:2], b"\xff\xd8")

    def test_frame_route_preview(self):
        self.server.update(frames={"TOP": make_frame()})
        response = self.client.get("/frame/TOP?preview=1")
        self.assertEqual(response.status_code, 200)

    def test_mjpeg_generator_disconnected(self):
        import asyncio
        from vision.ui.server.routes_frames import _mjpeg_generator

        class FakeRequest:
            async def is_disconnected(self):
                return True

        async def run():
            chunks = []
            async for chunk in _mjpeg_generator(
                self.server, "TOP", FakeRequest(), "RAW",
            ):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(run())
        self.assertEqual(chunks, [])

    def test_mjpeg_generator_sends_first_frame_then_disconnects(self):
        import asyncio
        from vision.ui.server.routes_frames import _mjpeg_generator

        self.server.update(frames={"TOP": make_frame()})
        calls = {"n": 0}

        class FakeRequest:
            async def is_disconnected(self):
                calls["n"] += 1
                return calls["n"] >= 3

        async def run():
            chunks = []
            async for chunk in _mjpeg_generator(
                self.server, "TOP", FakeRequest(), "RAW",
            ):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(run())
        self.assertEqual(len(chunks), 1)
        self.assertIn(b"--frame", chunks[0])
        self.assertIn(b"\xff\xd8", chunks[0])

    def test_archive_part_route_without_archive(self):
        response = self.client.get("/api/archive/part/1")
        self.assertEqual(response.status_code, 404)

    def test_archive_part_route_with_archive(self):
        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory() as tmp:
            meta_path = os.path.join(tmp, "meta.json")
            with open(meta_path, "w", encoding="utf-8") as stream:
                json.dump({"part_id": 3, "category": "GOOD"}, stream)
            archive = mock.Mock()
            archive.get_part_info.return_value = {"folder": tmp}
            archive.get_part_images.return_value = {
                "TOP": {
                    "raw": os.path.join(tmp, "TOP.jpg"),
                    "debug": os.path.join(tmp, "TOP_debug.jpg"),
                },
            }
            self.server.archive = archive
            response = self.client.get("/api/archive/part/3")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["meta"]["category"], "GOOD")
            self.assertEqual(data["roles"][0]["role"], "TOP")
            self.assertIn("raw_url", data["roles"][0])

    def test_archive_part_route_not_found(self):
        archive = mock.Mock()
        archive.get_part_info.return_value = None
        self.server.archive = archive
        response = self.client.get("/api/archive/part/99")
        self.assertEqual(response.status_code, 404)

    def test_archive_image_route(self):
        import tempfile as _tempfile

        with _tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "TOP.jpg")
            with open(image_path, "wb") as stream:
                stream.write(b"jpeg-data")
            archive = mock.Mock()
            archive.get_part_images.return_value = {
                "TOP": {"raw": image_path},
            }
            self.server.archive = archive
            response = self.client.get(
                "/api/archive/image/1/TOP/raw",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"jpeg-data")
            self.assertEqual(response.headers["content-type"], "image/jpeg")
            # part_id начинается с единицы в каждой партии, поэтому WebView
            # не должен переиспользовать снимок с тем же URL после перезапуска.
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertEqual(response.headers["pragma"], "no-cache")
            self.assertEqual(response.headers["expires"], "0")

    def test_archive_image_route_bad_kind(self):
        self.server.archive = mock.Mock()
        response = self.client.get("/api/archive/image/1/TOP/other")
        self.assertEqual(response.status_code, 400)

    def test_archive_image_route_missing_image(self):
        archive = mock.Mock()
        archive.get_part_images.return_value = {}
        self.server.archive = archive
        response = self.client.get("/api/archive/image/1/TOP/raw")
        self.assertEqual(response.status_code, 404)

    def test_index_route(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_static_css(self):
        response = self.client.get("/static/css/base.css")
        self.assertEqual(response.status_code, 200)

    # ---------- uvicorn thread ----------

    def test_start_server_with_fake_uvicorn(self):
        import threading as _threading

        class FakeUvicornServer:
            def __init__(self, config):
                self.config = config
                self.should_exit = False
                self.started = _threading.Event()

            def run(self):
                self.started.set()
                while not self.should_exit:
                    time.sleep(0.01)

        with mock.patch(
            "vision.ui.server.server.uvicorn.Server", FakeUvicornServer,
        ), mock.patch(
            "vision.ui.server.server.uvicorn.Config",
        ):
            self.server.start_server("127.0.0.1", 8000)
            self.assertIsNotNone(self.server.get_server_thread())
            self.server.stop_server(timeout=2.0)
            self.assertIsNone(self.server.get_server_thread())

    def test_configure_windows_event_loop_policy_on_linux(self):
        self.assertFalse(UIServer._configure_windows_event_loop_policy())


class OperatorSessionMixin:
    """Общая часть: сервер с хранилищем операторов и вход по ФИО."""

    def start_operator_store(self, root_folder):
        self.server.operator_store = OperatorStore(root_folder)
        self.server.operator_store.add_user(OPERATOR, PASSWORD)

    def login(self, login=OPERATOR, password=PASSWORD):
        return self.client.post(
            "/api/operator/login",
            json={"login": login, "password": password},
        )

    def logout(self):
        return self.client.post("/api/operator/logout")

    def register(self, login, password):
        return self.client.post(
            "/api/operator/register",
            json={"login": login, "password": password},
        )


class BatchUiServerTest(OperatorSessionMixin, unittest.TestCase):
    """Менеджер партий в UIServer: маршруты, гейт пуска и статус."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = UIServer()
        # Отправка аналитику заглушена: тест не пишет в очередь json_sender.
        self.manager = BatchManager(
            root_folder=os.path.join(self.tmp.name, "archive"),
            batch_sender=lambda folder: True,
        )
        self.server.batch_manager = self.manager
        self.server.archive = self.manager
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE", "in_line": 0}
        self.client = TestClient(self.server.app)
        self.start_operator_store(self.manager.root_folder)
        self.login()

    def tearDown(self):
        self.tmp.cleanup()

    def open_batch(self, **payload):
        body = {"label": "П-1"}
        body.update(payload)
        return self.client.post("/api/batch/open", json=body)

    # ---------- состояние ----------

    def test_batch_payload_without_manager(self):
        self.server.batch_manager = None
        payload = self.server.batch_status_payload()
        self.assertFalse(payload["available"])
        self.assertFalse(payload["active"])

    def test_get_batch_route(self):
        response = self.client.get("/api/batch")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["available"])
        self.assertFalse(payload["active"])
        self.assertTrue(payload["editable"])
        self.assertTrue(payload["suggestion"])

    def test_status_route_includes_batch(self):
        payload = self.client.get("/api/status").json()
        self.assertIn("batch", payload)
        self.assertFalse(payload["batch"]["active"])

    # ---------- открытие и продолжение ----------

    def test_open_batch_route(self):
        response = self.open_batch()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["batch"]["active"])
        # Оператор берётся из сессии входа, а не из тела запроса.
        self.assertEqual(
            payload["batch"]["batch"]["operator"], OPERATOR,
        )
        self.assertTrue(payload["batch"]["can_finish"])

    def test_open_batch_validation_400(self):
        response = self.open_batch(label="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("номер", response.json()["error"])

    def test_open_batch_ignores_operator_in_body(self):
        """ФИО в запросе больше не подменяет оператора смены."""
        response = self.open_batch(operator="Петров Пётр Петрович")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["batch"]["batch"]["operator"], OPERATOR,
        )

    def test_open_batch_switches_without_finishing(self):
        """Второй запрос открытия переключает учёт, партию не закрывая."""
        self.assertEqual(self.open_batch().status_code, 200)
        first_id = self.manager.batch_id
        response = self.open_batch(label="П-2")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["batch"]
        self.assertEqual(payload["batch"]["label"], "П-2")
        self.assertNotEqual(self.manager.batch_id, first_id)
        self.assertEqual(
            sorted(item["label"] for item in payload["open"]),
            ["П-1", "П-2"],
        )
        self.assertEqual(
            len([item for item in payload["open"] if item["status"] == "OPEN"]),
            2,
        )

    def test_open_batch_same_batch_changes_nothing(self):
        self.assertEqual(self.open_batch().status_code, 200)
        batch_id = self.manager.batch_id
        response = self.open_batch(label="П-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.batch_id, batch_id)
        self.assertEqual(len(response.json()["batch"]["open"]), 1)

    def test_open_batch_on_running_line_409(self):
        self.server.line_status = {"state": "RUNNING", "in_line": 1}
        self.assertEqual(self.open_batch().status_code, 409)

    def test_open_batch_with_parts_in_line_409(self):
        """Корпуса прежней партии на линии не переходят в новый учёт."""
        self.server.line_status = {"state": "STOPPED", "in_line": 2}
        response = self.open_batch()
        self.assertEqual(response.status_code, 409)
        self.assertIn("корпуса", response.json()["error"])
        self.assertFalse(self.manager.active)

    def test_continue_open_batch_route(self):
        self.assertEqual(self.open_batch().status_code, 200)
        batch_id = self.manager.batch_id
        self.manager.prepare_shutdown()
        self.manager = BatchManager(
            root_folder=self.manager.root_folder,
            batch_sender=lambda folder: True,
        )
        self.server.batch_manager = self.manager
        self.server.archive = self.manager
        response = self.open_batch(batch_id=batch_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["batch"]["batch"]["operator"], OPERATOR,
        )

    def test_continue_open_batch_after_operator_change(self):
        """Партию продолжает тот, кто вошёл сейчас; начавший — в истории."""
        self.assertEqual(self.open_batch().status_code, 200)
        batch_id = self.manager.batch_id
        self.manager.prepare_shutdown()
        self.manager = BatchManager(
            root_folder=self.manager.root_folder,
            batch_sender=lambda folder: True,
        )
        self.server.batch_manager = self.manager
        self.server.archive = self.manager
        self.server.operator_store.add_user(RESUME_OPERATOR, PASSWORD)
        self.assertEqual(self.logout().status_code, 200)
        self.assertEqual(self.login(RESUME_OPERATOR).status_code, 200)
        response = self.open_batch(batch_id=batch_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["batch"]["batch"]["operator"], RESUME_OPERATOR,
        )

    # ---------- завершение ----------

    def test_finish_batch_route(self):
        self.open_batch()
        response = self.client.post("/api/batch/finish")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["batch"]["active"])

    def test_finish_without_batch_409(self):
        response = self.client.post("/api/batch/finish")
        self.assertEqual(response.status_code, 409)
        self.assertIn("не открыта", response.json()["error"])

    def test_finish_with_parts_in_line_409(self):
        self.open_batch()
        self.server.line_status = {"state": "STOPPED", "in_line": 2}
        response = self.client.post("/api/batch/finish")
        self.assertEqual(response.status_code, 409)
        self.assertIn("остались корпуса", response.json()["error"])

    # ---------- гейт пуска ----------

    def test_start_without_label_409(self):
        """Пуск без номера партии: открывать нечего."""
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], NO_BATCH_MESSAGE)
        self.assertFalse(self.manager.active)

    def test_start_opens_batch_from_card(self):
        """Партию открывает ПУСК по номеру и пути из карточки."""
        self.server.on_start = mock.Mock(return_value=True)
        folder = os.path.join(self.tmp.name, "orders", "П-7")
        response = self.client.post(
            "/api/start", json={"label": "П-7", "path": folder},
        )
        self.assertEqual(response.status_code, 200)
        self.server.on_start.assert_called_once()
        self.assertTrue(self.manager.active)
        self.assertEqual(self.manager.batch_folder, os.path.abspath(folder))
        info = self.manager.batch_info()
        self.assertEqual(info["label"], "П-7")
        self.assertEqual(info["operator"], OPERATOR)

    def test_start_continues_selected_batch(self):
        """Выбранная незавершённая партия продолжается тем же ПУСКОМ."""
        self.server.on_start = mock.Mock(return_value=True)
        self.open_batch(label="П-1")
        batch_id = self.manager.batch_id
        # Перезапуск программы: партия осталась открытой на диске.
        self.manager.prepare_shutdown()
        self.manager._current = None

        response = self.client.post(
            "/api/start", json={"batch_id": batch_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.batch_id, batch_id)

    def test_start_switches_to_selected_batch(self):
        """Выбранная в списке партия переключает учёт тем же ПУСКОМ."""
        self.server.on_start = mock.Mock(return_value=True)
        self.assertEqual(self.open_batch().status_code, 200)
        first_id = self.manager.batch_id
        folder = os.path.join(self.tmp.name, "orders", "П-5")
        self.assertEqual(
            self.open_batch(label="П-5", path=folder).status_code, 200,
        )
        switched_id = self.manager.batch_id
        self.assertNotEqual(switched_id, first_id)

        # Переключение назад по выбранной партии из списка.
        response = self.client.post(
            "/api/start", json={"label": "П-1", "batch_id": first_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.batch_id, first_id)
        self.assertEqual(len(self.manager.status_payload()["open"]), 2)

    def test_start_switches_by_label_from_card(self):
        """Номер другой партии в поле — ПУСК переключает учёт на неё."""
        self.server.on_start = mock.Mock(return_value=True)
        self.assertEqual(self.open_batch().status_code, 200)
        first_id = self.manager.batch_id
        response = self.client.post(
            "/api/start", json={"label": "П-8"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.manager.batch_id, first_id)
        self.assertEqual(self.manager.status_payload()["batch"]["label"], "П-8")
        self.assertEqual(
            sorted(
                item["label"]
                for item in self.manager.status_payload()["open"]
            ),
            ["П-1", "П-8"],
        )
        self.assertEqual(first_id, "batch_" + safe_component("П-1"))

    def test_start_with_card_of_open_batch_does_not_switch(self):
        """Поля карточки повторяют открытую партию — переключения нет."""
        self.server.on_start = mock.Mock(return_value=True)
        self.open_batch()
        batch_id = self.manager.batch_id
        folder = self.manager.batch_folder
        response = self.client.post(
            "/api/start", json={"label": "П-1", "path": folder},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.batch_id, batch_id)
        self.assertEqual(len(self.manager.status_payload()["open"]), 1)

    def test_start_switch_needs_stopped_line(self):
        self.open_batch()
        self.server.line_status = {"state": "RUNNING", "in_line": 1}
        response = self.client.post("/api/start", json={"label": "П-2"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("остановленной", response.json()["error"])
        self.assertEqual(self.manager.batch_id, "batch_" + safe_component("П-1"))

    def test_start_switch_with_parts_in_line_409(self):
        self.open_batch()
        self.server.line_status = {"state": "STOPPED", "in_line": 2}
        response = self.client.post("/api/start", json={"label": "П-2"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("корпуса", response.json()["error"])
        self.assertEqual(self.manager.batch_id, "batch_" + safe_component("П-1"))

    def test_start_allowed_with_open_batch(self):
        self.server.on_start = mock.Mock(return_value=True)
        self.open_batch()
        ok, message = self.server.archive_ready_for_start()
        self.assertTrue(ok)
        self.assertIsNone(message)
        self.assertEqual(self.client.post("/api/start").status_code, 200)

    def test_batch_changed_hook_is_called(self):
        hook = mock.Mock()
        self.server.on_batch_changed = hook
        self.open_batch()
        hook.assert_called_once()
        self.client.post("/api/batch/finish")
        self.assertEqual(hook.call_count, 2)


class OperatorUiServerTest(OperatorSessionMixin, unittest.TestCase):
    """Вход в программу: ФИО и пароль, гейт вкладки «ПАРТИЯ»."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = UIServer()
        self.root = os.path.join(self.tmp.name, "archive")
        self.manager = BatchManager(
            root_folder=self.root,
            batch_sender=lambda folder: True,
        )
        self.server.batch_manager = self.manager
        self.server.archive = self.manager
        self.server.splash_active = False
        self.server.line_status = {"state": "IDLE", "in_line": 0}
        self.client = TestClient(self.server.app)
        self.start_operator_store(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    # ---------- состояние ----------

    def test_status_without_store(self):
        self.server.operator_store = None
        payload = self.server.operator_status_payload()
        self.assertFalse(payload["available"])
        self.assertFalse(payload["assigned"])
        self.assertIsNone(payload["operator"])
        self.assertEqual(payload["since"], "")

    def test_get_operator_route(self):
        payload = self.client.get("/api/operator").json()
        self.assertTrue(payload["available"])
        self.assertFalse(payload["assigned"])
        self.assertEqual(payload["users"], [OPERATOR])
        self.assertFalse(payload["can_register"])
        self.assertTrue(payload["can_add_user"])

    def test_status_route_includes_operator(self):
        payload = self.client.get("/api/status").json()
        self.assertIn("operator", payload)
        self.assertFalse(payload["operator"]["assigned"])

    # ---------- вход ----------

    def test_login_route(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["operator"]["assigned"])
        self.assertEqual(payload["operator"]["operator"], OPERATOR)
        # Плашка над вкладками показывает, с какого времени оператор в смене.
        self.assertRegex(payload["operator"]["since"], r"^\d{2}:\d{2}$")

    def test_login_accepts_case_and_spaces(self):
        response = self.login("  иванов иван иванович  ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["operator"]["operator"], OPERATOR,
        )

    def test_login_wrong_password_400(self):
        response = self.login(password="0000")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Неверный пароль")
        self.assertIsNone(self.server.operator)

    def test_login_unknown_operator_400(self):
        response = self.login("Сидоров Сидор Сидорович")
        self.assertEqual(response.status_code, 400)
        self.assertIn("не найден", response.json()["error"])

    def test_login_twice_409(self):
        self.assertEqual(self.login().status_code, 200)
        response = self.login()
        self.assertEqual(response.status_code, 409)
        self.assertIn("уже назначен", response.json()["error"])

    def test_login_bad_payload_400(self):
        response = self.client.post("/api/operator/login", json={})
        self.assertEqual(response.status_code, 400)

    # ---------- регистрация и смена ----------

    def test_register_first_operator(self):
        store = self.server.operator_store
        store.remove_user(OPERATOR)
        response = self.register("Смирнов Илья Петрович", "1234")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["operator"]["assigned"])
        self.assertEqual(
            payload["operator"]["operator"], "Смирнов Илья Петрович",
        )

    def test_register_existing_list_409(self):
        response = self.register("Смирнов Илья Петрович", "1234")
        self.assertEqual(response.status_code, 409)
        self.assertIn("войдите", response.json()["error"])

    def test_logged_operator_adds_colleague(self):
        """Вошедший оператор заводит коллегу, не меняя свою сессию."""
        self.assertEqual(self.login().status_code, 200)
        response = self.register("Смирнов Илья Петрович", "1234")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["operator"]
        self.assertEqual(payload["operator"], OPERATOR)
        self.assertEqual(len(payload["users"]), 2)
        self.assertEqual(self.server.operator, OPERATOR)

    def test_register_short_password_400(self):
        store = self.server.operator_store
        store.remove_user(OPERATOR)
        response = self.register("Смирнов Илья Петрович", "12")
        self.assertEqual(response.status_code, 400)

    def test_logout_route(self):
        self.login()
        response = self.logout()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["operator"]["assigned"])
        self.assertEqual(response.json()["operator"]["since"], "")
        self.assertIsNone(self.server.operator)
        self.assertEqual(self.server.operator_since, "")

    def test_logout_without_operator_409(self):
        response = self.logout()
        self.assertEqual(response.status_code, 409)
        self.assertIn("не назначен", response.json()["error"])

    def test_logout_blocked_by_open_batch(self):
        self.login()
        self.client.post("/api/batch/open", json={"label": "П-1"})
        response = self.logout()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.server.operator, OPERATOR)
        self.assertFalse(self.server.operator_status_payload()["editable"])

    def test_logout_blocked_on_running_line(self):
        self.login()
        self.server.line_status = {"state": "RUNNING", "in_line": 1}
        response = self.logout()
        self.assertEqual(response.status_code, 409)

    def test_switch_operator(self):
        self.login()
        self.server.operator_store.add_user(RESUME_OPERATOR, PASSWORD)
        self.assertEqual(self.logout().status_code, 200)
        response = self.login(RESUME_OPERATOR)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.server.operator, RESUME_OPERATOR)

    # ---------- гейты ----------

    def test_batch_open_requires_operator(self):
        response = self.client.post("/api/batch/open", json={"label": "П-1"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], NO_OPERATOR_MESSAGE)
        self.assertFalse(self.manager.active)

    def test_start_requires_operator(self):
        ok, message = self.server.archive_ready_for_start()
        self.assertFalse(ok)
        self.assertEqual(message, NO_OPERATOR_MESSAGE)
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], NO_OPERATOR_MESSAGE)

    def test_start_needs_operator_then_label(self):
        """Сначала оператор, затем номер партии: пуск открывает партию."""
        self.assertEqual(self.login().status_code, 200)
        self.server.on_start = mock.Mock(return_value=True)
        # Номер не указан: пуск отклонён, партия не открыта.
        response = self.client.post("/api/start")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], NO_BATCH_MESSAGE)
        # Номер указан: пуск открывает партию и запускает линию.
        response = self.client.post("/api/start", json={"label": "П-2"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.server.batch_manager.active)
        self.assertEqual(
            self.server.batch_manager.batch_info()["label"], "П-2",
        )
        ok, message = self.server.archive_ready_for_start()
        self.assertTrue(ok)
        self.assertIsNone(message)

    def test_persistent_login_after_restart(self):
        """Учётки переживают перезапуск программы."""
        self.assertEqual(self.login().status_code, 200)
        self.server.operator = None
        self.server.operator_store = OperatorStore(self.root)
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["operator"]["operator"], OPERATOR,
        )


if __name__ == "__main__":
    unittest.main()
