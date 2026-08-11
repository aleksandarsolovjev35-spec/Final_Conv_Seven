from __future__ import annotations

import unittest
from pathlib import Path

from conveyor_compact.config import (
    ConfigError,
    load_config_bundle,
    normalize_archive,
    validate_camera_mapping,
)


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_production_config_snapshot_is_valid(self):
        bundle = load_config_bundle(ROOT)
        self.assertEqual(7, len(bundle.camera_mapping))
        self.assertEqual(96, bundle.threshold_count)
        self.assertEqual(340, bundle.calibration["dist1_open_position"])
        self.assertEqual("archive", bundle.archive["root_path"])

    def test_camera_ids_must_be_unique(self):
        mapping = {
            "INPUT_LEFT": 0,
            "INPUT_RIGHT": 0,
            "SPIDER_LEFT": 1,
            "SPIDER_RIGHT": 2,
            "SPIDER_IN": 3,
            "SPIDER_OUT": 4,
            "TOP": 5,
        }
        with self.assertRaisesRegex(ConfigError, "уникальными"):
            validate_camera_mapping(mapping)

    def test_archive_quality_uses_compatible_clamp(self):
        normalized = normalize_archive({"jpeg_quality": 200, "root_path": ""})
        self.assertEqual(98, normalized["jpeg_quality"])
        self.assertEqual("archive", normalized["root_path"])


if __name__ == "__main__":
    unittest.main()
