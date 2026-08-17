"""Загрузка и валидация конфигурации трёхкамерной линии."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from config.archive_config import (
    DEFAULTS,
    load_archive_config,
    normalise_archive_config,
    save_archive_config,
)
from config.calibration_loader import (
    load_calibration,
)
from config.camera_mapping import (
    REQUIRED_ROLES,
    load_camera_mapping,
    validate_camera_mapping,
)

VALID_CALIB = {
    "micro_steps": 500,
    "jog_hold_steps": 1_000_000,
    "normal_steps": 19048,
    "conveyor_speed": 20000,
    "conveyor_accel": 6000,
    "dist1_open_position": 340,
    "dist2_bad_position": 0,
    "dist2_cleanup_position": 340,
    "drop_time": 0.8,
    "axis_speed": 300,
    "axis_accel": 100,
}


class ArchiveConfigTest(unittest.TestCase):
    def test_defaults_complete(self):
        result = normalise_archive_config(None)
        self.assertEqual(set(result), set(DEFAULTS))
        self.assertTrue(result["enabled"])
        self.assertEqual(result["jpeg_quality"], 92)

    def test_clamps_jpeg_quality(self):
        result = normalise_archive_config({"jpeg_quality": 10})
        self.assertEqual(result["jpeg_quality"], 70)
        result = normalise_archive_config({"jpeg_quality": 200})
        self.assertEqual(result["jpeg_quality"], 98)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "archive_config.json")
            save_archive_config(path, {"root_path": "parts", "jpeg_quality": 80})
            loaded = load_archive_config(path)
            self.assertEqual(loaded["root_path"], "parts")
            self.assertEqual(loaded["jpeg_quality"], 80)


class CalibrationTest(unittest.TestCase):
    def _write(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        self.addCleanup(os.remove, path)
        return path

    def test_loads_valid_calibration(self):
        path = self._write(VALID_CALIB)
        result = load_calibration(path)
        self.assertEqual(result["normal_steps"], 19048)
        self.assertEqual(result["drop_time"], 0.8)
        # Опциональные тайминги подставлены.
        self.assertIn("settle_time", result)
        self.assertIn("review_time", result)

    def test_missing_field_raises(self):
        data = dict(VALID_CALIB)
        del data["drop_time"]
        path = self._write(data)
        with self.assertRaises(RuntimeError):
            load_calibration(path)

    def test_extra_field_raises(self):
        data = dict(VALID_CALIB)
        data["unknown"] = 1
        path = self._write(data)
        with self.assertRaises(RuntimeError):
            load_calibration(path)

    def test_bad_and_cleanup_must_differ(self):
        data = dict(VALID_CALIB)
        data["dist2_bad_position"] = 340
        data["dist2_cleanup_position"] = 340
        path = self._write(data)
        with self.assertRaises(RuntimeError):
            load_calibration(path)


class CameraMappingTest(unittest.TestCase):
    def test_required_roles(self):
        self.assertEqual(REQUIRED_ROLES, {"NEAR", "MIDDLE", "FAR"})

    def test_valid_mapping(self):
        mapping = {"NEAR": 0, "MIDDLE": 1, "FAR": 2}
        self.assertEqual(validate_camera_mapping(mapping), mapping)

    def test_missing_role(self):
        with self.assertRaises(ValueError):
            validate_camera_mapping({"NEAR": 0, "MIDDLE": 1})

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            validate_camera_mapping({"NEAR": 0, "MIDDLE": 0, "FAR": 2})

    def test_loads_from_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"NEAR": 2, "MIDDLE": 0, "FAR": 1}, stream)
        self.addCleanup(os.remove, path)
        self.assertEqual(
            load_camera_mapping(path),
            {"NEAR": 2, "MIDDLE": 0, "FAR": 1},
        )


if __name__ == "__main__":
    unittest.main()
