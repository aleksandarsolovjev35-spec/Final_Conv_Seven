"""Проверки независимого мастера сбора датасета и YOLO segmentation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from training.collector import (
    CollectorError,
    TrainingCollector,
    TrainingConfig,
    ValidationError,
)
from training.server import create_app
from training.yolo import PolygonAnnotation, normalise_polygon


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
                annotations=[
                    {
                        "class_name": "scratch",
                        "points": [
                            {"x": 10, "y": 20},
                            {"x": 40, "y": 20},
                            {"x": 40, "y": 45},
                            {"x": 10, "y": 45},
                        ],
                    }
                ],
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
            detail = session / "details" / "part_0001"
            self.assertEqual(
                sorted(path.name for path in detail.glob("*.jpg")),
                [
                    "CAM_A_annotated.jpg",
                    "CAM_A_original.jpg",
                    "CAM_B_annotated.jpg",
                    "CAM_B_original.jpg",
                ],
            )
            self.assertEqual(
                (session / "labels/frame_000001_CAM_A.txt").read_text().split(),
                [
                    "0",
                    "0.083333",
                    "0.250000",
                    "0.333333",
                    "0.250000",
                    "0.333333",
                    "0.562500",
                    "0.083333",
                    "0.562500",
                ],
            )
            self.assertEqual(
                (session / "labels/frame_000002_CAM_B.txt").read_text(),
                "",
            )
            self.assertTrue((session / "yolo/dataset.yaml").exists())
            self.assertIn("task: segment", (session / "yolo/dataset.yaml").read_text())
            self.assertEqual(result["yolo"]["train_count"], 2)
            self.assertEqual(result["yolo"]["validation_count"], 0)

    def test_legacy_bbox_is_exported_as_four_point_polygon(self):
        with tempfile.TemporaryDirectory() as root:
            collector, _ = self.make_collector(root)
            collector.start_session("legacy")
            collector.begin_part()
            collector.capture_next()
            collector.annotate_current(
                boxes=[
                    {
                        "class_name": "scratch",
                        "x": 10,
                        "y": 20,
                        "width": 30,
                        "height": 25,
                    }
                ]
            )
            label = Path(collector.store.session_folder / "labels/frame_000001_CAM_A.txt")
            self.assertEqual(
                label.read_text().split(),
                [
                    "0",
                    "0.083333",
                    "0.250000",
                    "0.333333",
                    "0.250000",
                    "0.333333",
                    "0.562500",
                    "0.083333",
                    "0.562500",
                ],
            )

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
                    annotations=[
                        {
                            "class_name": "scratch",
                            "points": [[1, 1], [5, 1], [5, 5]],
                        }
                    ],
                )
            collector.skip_current()
            with self.assertRaises(CollectorError):
                collector.finish_part()

    def test_one_frame_can_contain_multiple_palette_elements(self):
        with tempfile.TemporaryDirectory() as root:
            collector, _ = self.make_collector(root)
            collector.start_session("palette")
            collector.begin_part()
            collector.capture_next()
            record = collector.annotate_current(
                annotations=[
                    {
                        "class_name": "scratch",
                        "points": [[10, 10], [30, 10], [30, 30], [10, 30]],
                    },
                    {
                        "class_name": "glass",
                        "points": [[60, 30], [80, 30], [75, 50]],
                    },
                ]
            )
            self.assertEqual(
                [item.class_name for item in record.annotations],
                ["scratch", "glass"],
            )
            label = Path(collector.store.session_folder / record.label).read_text()
            self.assertEqual(len(label.strip().splitlines()), 2)
            self.assertTrue(all(len(line.split()) >= 7 for line in label.splitlines()))

    def test_polygon_is_clipped_and_closed_duplicate_is_removed(self):
        polygon = PolygonAnnotation(
            "scratch",
            ((-10, -10), (50, 0), (120, 0), (120, 80), (0, 80), (-10, -10)),
        )
        points = normalise_polygon(polygon, image_width=120, image_height=80)
        self.assertEqual(points[0], (0.0, 0.0))
        self.assertEqual(points[-1], (0.0, 80.0))
        self.assertGreater(len(points), 3)

    def test_polygon_requires_three_points_and_nonzero_area(self):
        with tempfile.TemporaryDirectory() as root:
            collector, _ = self.make_collector(root)
            collector.start_session("invalid")
            collector.begin_part()
            collector.capture_next()
            with self.assertRaises(ValidationError):
                collector.annotate_current(
                    annotations=[
                        {
                            "class_name": "scratch",
                            "points": [[1, 1], [5, 1]],
                        }
                    ]
                )
            with self.assertRaises(ValidationError):
                collector.annotate_current(
                    annotations=[
                        {
                            "class_name": "scratch",
                            "points": [[1, 1], [2, 2], [3, 3]],
                        }
                    ]
                )

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


class TrainingServerTest(unittest.TestCase):
    def test_app_serves_ui_and_static_assets_before_session(self):
        with tempfile.TemporaryDirectory() as root:
            collector = TrainingCollector(
                TrainingConfig(
                    root_folder=root,
                    camera_roles=("CAM_A",),
                    defect_classes=("contact",),
                ),
                frame_source=FakeFrameSource(),
            )
            client = TestClient(create_app(collector))

            page = client.get("/")
            config = client.get("/api/training/config")
            script = client.get("/static/training.js?v=test")
            stylesheet = client.get("/static/training.css?v=test")
            self.assertEqual(page.status_code, 200)
            self.assertIn("id=\"finish-polygon\"", page.text)
            self.assertIn(">ГОТОВО<", page.text)
            self.assertEqual(config.status_code, 200)
            self.assertEqual(config.json()["yolo_task"], "segment")
            self.assertEqual(script.status_code, 200)
            self.assertIn("draftPoints", script.text)
            self.assertEqual(stylesheet.status_code, 200)

    def test_annotations_api_rejects_invalid_polygon_then_completes_frame(self):
        with tempfile.TemporaryDirectory() as root:
            collector = TrainingCollector(
                TrainingConfig(
                    root_folder=root,
                    camera_roles=("CAM_A",),
                    defect_classes=("contact",),
                    validation_ratio=0.0,
                ),
                frame_source=FakeFrameSource(),
            )
            client = TestClient(create_app(collector))
            client.post("/api/training/session", json={"dataset_name": "api"})
            client.post("/api/training/parts", json={})
            frame = client.post("/api/training/capture").json()["frame"]

            invalid = client.post(
                "/api/training/annotations",
                json={
                    "image_id": frame["image_id"],
                    "annotations": [
                        {"class_name": "contact", "points": [[1, 1], [2, 2]]}
                    ],
                },
            )
            self.assertEqual(invalid.status_code, 400)
            self.assertIsNotNone(client.get("/api/training/state").json()["current_frame"])

            valid = client.post(
                "/api/training/annotations",
                json={
                    "image_id": frame["image_id"],
                    "annotations": [
                        {
                            "class_name": "contact",
                            "points": [[2, 2], [35, 3], [25, 25]],
                        }
                    ],
                },
            )
            self.assertEqual(valid.status_code, 200)
            saved = valid.json()["frame"]
            self.assertEqual(saved["status"], "annotated")
            self.assertEqual(client.get(saved["original_url"]).status_code, 200)
            self.assertEqual(client.get(saved["annotated_url"]).status_code, 200)

            self.assertEqual(client.post("/api/training/parts/finish").status_code, 200)
            result = client.post("/api/training/session/finish")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["yolo"]["task"], "segment")
            labels = list(Path(root).glob("api_*/labels/*.txt"))
            self.assertEqual(len(labels), 1)
            self.assertEqual(len(labels[0].read_text().split()), 7)

    def test_annotations_api_keeps_legacy_bbox_payload(self):
        with tempfile.TemporaryDirectory() as root:
            collector = TrainingCollector(
                TrainingConfig(
                    root_folder=root,
                    camera_roles=("CAM_A",),
                    defect_classes=("contact",),
                    validation_ratio=0.0,
                ),
                frame_source=FakeFrameSource(),
            )
            client = TestClient(create_app(collector))
            client.post("/api/training/session", json={"dataset_name": "legacy"})
            client.post("/api/training/parts", json={})
            frame = client.post("/api/training/capture").json()["frame"]
            response = client.post(
                "/api/training/annotations",
                json={
                    "image_id": frame["image_id"],
                    "boxes": [
                        {
                            "class_name": "contact",
                            "x": 2,
                            "y": 3,
                            "width": 20,
                            "height": 15,
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.post("/api/training/parts/finish").status_code, 200)
            self.assertEqual(client.post("/api/training/session/finish").status_code, 200)
            labels = list(Path(root).glob("legacy_*/labels/*.txt"))
            self.assertEqual(len(labels), 1)
            self.assertEqual(len(labels[0].read_text().split()), 9)

    def test_annotations_api_accepts_polygon_payload_and_exports_segmentation(self):
        with tempfile.TemporaryDirectory() as root:
            source = FakeFrameSource()
            collector = TrainingCollector(
                TrainingConfig(
                    root_folder=root,
                    camera_roles=("CAM_A",),
                    defect_classes=("contact",),
                    validation_ratio=0.0,
                ),
                frame_source=source,
            )
            client = TestClient(create_app(collector))

            self.assertEqual(client.get("/api/training/config").status_code, 200)
            self.assertEqual(
                client.post(
                    "/api/training/session",
                    json={"dataset_name": "api", "defect_classes": ["contact"]},
                ).status_code,
                200,
            )
            self.assertEqual(client.post("/api/training/parts", json={}).status_code, 200)
            frame = client.post("/api/training/capture").json()["frame"]
            response = client.post(
                "/api/training/annotations",
                json={
                    "image_id": frame["image_id"],
                    "annotations": [
                        {
                            "class_name": "contact",
                            "points": [[2, 2], [35, 3], [25, 25]],
                        }
                    ],
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["frame"]["status"], "annotated")

            # The API returns a finished frame and keeps the segmentation label.
            self.assertEqual(client.post("/api/training/parts/finish").status_code, 200)
            self.assertEqual(client.post("/api/training/session/finish").status_code, 200)
            labels = list(Path(root).glob("api_*/labels/*.txt"))
            self.assertEqual(len(labels), 1)
            self.assertGreaterEqual(len(labels[0].read_text().split()), 7)


if __name__ == "__main__":
    unittest.main()
