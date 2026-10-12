"""Проверки независимого мастера сбора датасета."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from training.collector import (
    CollectorError,
    TrainingCollector,
    TrainingConfig,
    ValidationError,
)


class FakeFrameSource:
    def __init__(self):
        self.roles = []

    def capture_single(self, role):
        self.roles.append(role)
        frame = np.zeros((80, 120, 3), dtype=np.uint8)
        frame[:, :] = (20, 30, 40)
        return frame


class TrainingCollectorTest(unittest.TestCase):
    def make_collector(self, root):
        source = FakeFrameSource()
        collector = TrainingCollector(
            TrainingConfig(
                root_folder=root,
                camera_roles=("CAM_A", "CAM_B"),
                defect_classes=("scratch", "glass"),
                validation_ratio=0.5,
            ),
            frame_source=source,
        )
        return collector, source

    def test_each_camera_gets_unique_original_and_yolo_files(self):
        with tempfile.TemporaryDirectory() as root:
            collector, source = self.make_collector(root)
            collector.start_session("case")
            collector.begin_part()

            first = collector.capture_next()
            self.assertEqual(first.image_id, 1)
            collector.annotate_current(
                defect_class="scratch",
                boxes=[{"x": 10, "y": 20, "width": 30, "height": 25}],
            )
            second = collector.capture_next()
            self.assertEqual(second.image_id, 2)
            collector.skip_current()
            collector.finish_part()
            result = collector.finish_session()

            self.assertEqual(source.roles, ["CAM_A", "CAM_B"])
            session = Path(result["session_folder"])
            originals = sorted((session / "images").glob("*.jpg"))
            marked = sorted((session / "annotated").glob("*.jpg"))
            labels = sorted((session / "labels").glob("*.txt"))
            self.assertEqual(len(originals), 2)
            self.assertEqual(len(marked), 2)
            self.assertEqual(len(labels), 2)
            self.assertEqual(
                (session / "labels/frame_000001_CAM_A.txt").read_text().split(),
                ["0", "0.208333", "0.406250", "0.250000", "0.312500"],
            )
            self.assertEqual(
                (session / "labels/frame_000002_CAM_B.txt").read_text(),
                "",
            )
            self.assertTrue((session / "yolo/dataset.yaml").exists())
            self.assertEqual(result["yolo"]["train_count"], 2)
            self.assertEqual(result["yolo"]["validation_count"], 0)

    def test_state_machine_requires_annotation_before_next_camera(self):
        with tempfile.TemporaryDirectory() as root:
            collector, _ = self.make_collector(root)
            collector.start_session("case")
            collector.begin_part()
            collector.capture_next()
            with self.assertRaises(CollectorError):
                collector.capture_next()
            with self.assertRaises(ValidationError):
                collector.annotate_current(
                    defect_class="unknown",
                    boxes=[{"x": 1, "y": 1, "width": 4, "height": 4}],
                )
            collector.skip_current()
            with self.assertRaises(CollectorError):
                collector.finish_part()

    def test_no_defect_keeps_empty_yolo_label(self):
        with tempfile.TemporaryDirectory() as root:
            collector, _ = self.make_collector(root)
            collector.start_session("negative")
            collector.begin_part()
            for _ in range(2):
                collector.capture_next()
                collector.skip_current()
            collector.finish_part()
            result = collector.finish_session()
            session = Path(result["session_folder"])
            self.assertTrue(
                all(
                    not path.read_text()
                    for path in (session / "labels").glob("*.txt")
                )
            )


if __name__ == "__main__":
    unittest.main()
