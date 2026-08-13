"""CameraManager: открытие, захват, drain, ошибки и блокировка после сбоя.

Реальные USB-камеры заменяются фабрикой фейковых ``VideoCapture``,
конфигурация пишется во временный ``camera_mapping.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

import numpy as np

from vision.camera_manager import CameraManager

ROLES = (
    "INPUT_LEFT", "INPUT_RIGHT", "SPIDER_LEFT", "SPIDER_RIGHT",
    "SPIDER_IN", "SPIDER_OUT", "TOP",
)


def mapping():
    return {role: index for index, role in enumerate(ROLES)}


def good_frame():
    return np.full((720, 1280, 3), 128, dtype=np.uint8)


class FakeCapture:
    def __init__(self, camera_id, frame=None, opened=True, reads=None,
                 fail_reads=()):
        self.camera_id = camera_id
        self.frame = frame if frame is not None else good_frame()
        self.opened = opened
        self.reads = reads if reads is not None else []
        self.fail_reads = set(fail_reads)
        self.released = False
        self.settings = []

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.settings.append((prop, value))

    def read(self):
        self.reads.append(self.camera_id)
        if self.camera_id in self.fail_reads:
            return False, None
        return True, self.frame.copy()

    def release(self):
        self.released = True


class FakeCaptureFactory:
    def __init__(self, captures):
        self.captures = dict(captures)

    def __call__(self, camera_id):
        return self.captures[camera_id]


class CameraManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.tmp.name, "camera_mapping.json")
        with open(self.config, "w", encoding="utf-8") as stream:
            json.dump(mapping(), stream)

    def tearDown(self):
        self.tmp.cleanup()

    def make_manager(self, captures=None):
        if captures is None:
            captures = {
                index: FakeCapture(index) for index in range(7)
            }
        factory = FakeCaptureFactory(captures)
        manager = CameraManager(
            config_file=self.config,
            capture_factory=factory,
        )
        return manager, factory

    def test_opens_all_cameras(self):
        manager, factory = self.make_manager()
        self.assertEqual(set(manager.cameras), set(ROLES))
        self.assertEqual(manager.mapping, mapping())

    def test_capture_all_returns_all_roles(self):
        manager, _ = self.make_manager()
        frames = manager.capture_all()
        self.assertEqual(set(frames), set(ROLES))
        self.assertEqual(frames["TOP"].shape, (720, 1280, 3))

    def test_capture_roles_order_and_single(self):
        manager, factory = self.make_manager()
        frames = manager.capture_roles(("TOP", "INPUT_LEFT"))
        self.assertEqual(list(frames), ["TOP", "INPUT_LEFT"])
        frame = manager.capture_single("TOP")
        self.assertEqual(frame.shape, (720, 1280, 3))

    def test_capture_roles_empty(self):
        manager, _ = self.make_manager()
        self.assertEqual(manager.capture_roles(()), {})

    def test_capture_unknown_role(self):
        manager, _ = self.make_manager()
        with self.assertRaisesRegex(RuntimeError, "Неизвестные камеры"):
            manager.capture_roles(("NOPE",))

    def test_drain_buffers(self):
        captures = {index: FakeCapture(index) for index in range(7)}
        manager, _ = self.make_manager(captures)
        manager.drain_buffers(("TOP",))
        self.assertGreaterEqual(len(captures[6].reads), 3)
        manager.drain_buffers()
        self.assertGreaterEqual(len(captures[0].reads), 3)

    def test_read_failure_latches_and_blocks(self):
        captures = {index: FakeCapture(index) for index in range(7)}
        captures[2].fail_reads.add(2)
        manager, _ = self.make_manager(captures)
        with self.assertRaisesRegex(RuntimeError, "read returned no frame"):
            manager.capture_all()
        with self.assertRaisesRegex(RuntimeError, "заблокирован"):
            manager.capture_single("TOP")

    def test_invalid_resolution_rejected(self):
        captures = {index: FakeCapture(index) for index in range(7)}
        captures[1].frame = np.zeros((100, 100, 3), dtype=np.uint8)
        manager, _ = self.make_manager(captures)
        with self.assertRaisesRegex(RuntimeError, "invalid resolution"):
            manager.capture_single("INPUT_RIGHT")

    def test_near_black_frame_rejected(self):
        captures = {index: FakeCapture(index) for index in range(7)}
        captures[1].frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        manager, _ = self.make_manager(captures)
        with self.assertRaisesRegex(RuntimeError, "near-black"):
            manager.capture_single("INPUT_RIGHT")

    def test_release_closes_cameras(self):
        captures = {index: FakeCapture(index) for index in range(7)}
        manager, _ = self.make_manager(captures)
        manager.release()
        self.assertTrue(all(captures[index].released for index in range(7)))
        self.assertEqual(manager.cameras, {})
        with self.assertRaises(RuntimeError):
            manager.capture_all()

    def test_open_failure_releases_opened(self):
        captures = {index: FakeCapture(index) for index in range(7)}
        captures[3].opened = False
        factory = FakeCaptureFactory(captures)
        with self.assertRaisesRegex(RuntimeError, "Ошибка открытия"):
            CameraManager(config_file=self.config, capture_factory=factory)
        self.assertTrue(captures[0].released)
        self.assertTrue(captures[2].released)

    def test_config_missing_file(self):
        with self.assertRaisesRegex(RuntimeError, "не найден"):
            CameraManager(config_file=os.path.join(self.tmp.name, "nope.json"))

    def test_config_invalid_json(self):
        path = os.path.join(self.tmp.name, "bad.json")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("{bad")
        with self.assertRaisesRegex(RuntimeError, "Ошибка чтения"):
            CameraManager(config_file=path)

    def test_config_bad_roles(self):
        path = os.path.join(self.tmp.name, "bad_roles.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"TOP": 0}, stream)
        with self.assertRaisesRegex(RuntimeError, "Неверный набор камер"):
            CameraManager(config_file=path)

    def test_config_duplicate_ids(self):
        data = mapping()
        data["TOP"] = 0
        path = os.path.join(self.tmp.name, "dup.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        with self.assertRaisesRegex(RuntimeError, "уникальными"):
            CameraManager(config_file=path)

    def test_config_non_int_id(self):
        data = mapping()
        data["TOP"] = "2"
        path = os.path.join(self.tmp.name, "str.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        with self.assertRaisesRegex(RuntimeError, "неотрицательными int"):
            CameraManager(config_file=path)

    def test_configure_capture_called(self):
        captures = {index: FakeCapture(index) for index in range(7)}
        manager, _ = self.make_manager(captures)
        self.assertTrue(captures[0].settings)

    def test_frame_error_validation(self):
        self.assertIsNone(CameraManager._frame_error(good_frame()))
        error = CameraManager._frame_error(np.zeros((10, 10), dtype=np.uint8))
        self.assertIn("invalid frame shape", error)


if __name__ == "__main__":
    unittest.main()
