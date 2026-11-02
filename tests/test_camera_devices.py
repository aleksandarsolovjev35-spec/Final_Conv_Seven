"""Перечисление физических камер для мастера назначения ролей."""

import unittest

import numpy as np

from vision.camera_devices import (
    ERROR_NO_FRAME,
    ERROR_NOT_OPENED,
    grab_snapshot,
    probe_device,
    probe_devices,
)


class FakeCapture:
    def __init__(self, opened=True, frame=None):
        self._opened = opened
        self._frame = frame
        self.released = False

    def isOpened(self):
        return self._opened

    def read(self):
        if self._frame is None:
            return False, None
        return True, self._frame

    def release(self):
        self.released = True


class ProbeDeviceTest(unittest.TestCase):
    def test_open_device_reports_resolution(self):
        frame = np.full((720, 1280, 3), 40, dtype=np.uint8)
        capture = FakeCapture(frame=frame)
        result = probe_device(3, factory=lambda index: capture)
        self.assertTrue(result["ok"])
        self.assertEqual(result["index"], 3)
        self.assertEqual((result["width"], result["height"]), (1280, 720))
        self.assertTrue(capture.released)

    def test_closed_device(self):
        capture = FakeCapture(opened=False)
        result = probe_device(1, factory=lambda index: capture)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_NOT_OPENED)
        self.assertTrue(capture.released)

    def test_device_without_frame(self):
        result = probe_device(0, factory=lambda index: FakeCapture(frame=None))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], ERROR_NO_FRAME)

    def test_factory_error_is_reported(self):
        def factory(index):
            raise OSError("busy")

        result = probe_device(2, factory=factory)
        self.assertFalse(result["ok"])
        self.assertIn("busy", result["error"])

    def test_probe_devices_covers_requested_range(self):
        results = probe_devices(3, factory=lambda index: FakeCapture(frame=None))
        self.assertEqual([item["index"] for item in results], [0, 1, 2])


class GrabSnapshotTest(unittest.TestCase):
    def test_returns_jpeg(self):
        frame = np.full((120, 160, 3), 90, dtype=np.uint8)
        jpeg = grab_snapshot(
            0, factory=lambda index: FakeCapture(frame=frame),
        )
        self.assertIsNotNone(jpeg)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

    def test_unavailable_device_returns_none(self):
        self.assertIsNone(
            grab_snapshot(0, factory=lambda index: FakeCapture(opened=False)),
        )


if __name__ == "__main__":
    unittest.main()
