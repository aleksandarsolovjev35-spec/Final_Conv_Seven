"""Проверки независимого мастера сбора датасета и YOLO segmentation."""

from __future__ import annotations

import json
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
from training.motion import VirtualBeltStep
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


class FakeBelt:
    """Шаг ленты без железа: считает вызовы advance()."""

    def __init__(self):
        self.calls = 0

    def advance(self):
        self.calls += 1
        return {
            "available": True,
            "moved": True,
            "steps": self.calls,
            "message": f"step {self.calls}",
        }


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

    def test_capture_and_annotation_persist_all_files_and_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            collector, _ = self.make_collector(root)
            collector.start_session("persistence")
            collector.begin_part(label="operator-check")

            pending = collector.capture_next()
            session = Path(collector.store.session_folder)
            original_path = session / pending.original
            detail_folder = session / "details" / "part_0001"
            self.assertTrue(original_path.exists())
            self.assertTrue(
                (detail_folder / "CAM_A_original.jpg").exists()
            )
            self.assertIsNone(pending.annotated)
            self.assertIsNone(pending.label)
            original_bytes = original_path.read_bytes()
            manifest_pending = [
                json.loads(line)
                for line in (session / "manifest.jsonl").read_text().splitlines()
            ]
            self.assertEqual(manifest_pending[0]["status"], "pending")

            saved = collector.annotate_current(
                annotations=[
                    {
                        "class_name": "scratch",
                        "points": [[10, 10], [45, 12], [35, 35]],
                    },
                    {
                        "class_name": "glass",
                        "points": [[60, 30], [90, 30], [85, 55]],
                    },
                ]
            )
            self.assertEqual(original_path.read_bytes(), original_bytes)
            for relative in (
                saved.annotated,
                saved.label,
                saved.detail_annotated,
                saved.detail_label,
            ):
                self.assertIsNotNone(relative)
                self.assertTrue((session / relative).exists())
            self.assertEqual(saved.status, "annotated")
            self.assertEqual(
                [item.class_name for item in saved.annotations],
                ["scratch", "glass"],
            )
            self.assertTrue(
                (detail_folder / "CAM_A_annotated.jpg").stat().st_size > 0
            )
            self.assertTrue(
                (detail_folder / "CAM_A.txt").read_text().strip()
            )

            second = collector.capture_next()
            collector.skip_current()
            collector.finish_part()
            result = collector.finish_session()
            self.assertTrue(result["finished_at"])

            manifest = [
                json.loads(line)
                for line in (session / "manifest.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["status"] for row in manifest], ["annotated", "annotated"])
            self.assertEqual(
                [item["class"] for item in manifest[0]["annotations"]],
                ["scratch", "glass"],
            )
            self.assertEqual(manifest[1]["image_id"], second.image_id)
            self.assertEqual(
                json.loads((session / "session.json").read_text())["finished_at"],
                result["finished_at"],
            )
            classes = json.loads((session / "classes.json").read_text())
            self.assertEqual(classes["yolo_task"], "segment")
            self.assertEqual(classes["classes"], ["scratch", "glass"])
            self.assertEqual(
                json.loads((session / "session.json").read_text())["parts"][0]["status"],
                "finished",
            )
            self.assertEqual(len(list((session / "yolo/images/train").glob("*.jpg"))), 2)
            self.assertEqual(len(list((session / "yolo/labels/train").glob("*.txt"))), 2)
            self.assertTrue((session / "yolo/dataset.yaml").exists())
            self.assertTrue((session / "yolo/split.json").exists())

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


class TrainingBeltAndNextPartTest(unittest.TestCase):
    """Шаг ленты и переход «ДАЛЕЕ» к следующей детали."""

    def make_collector(self, root, *, belt=None):
        source = FakeFrameSource()
        collector = TrainingCollector(
            TrainingConfig(
                root_folder=root,
                camera_roles=("CAM_A", "CAM_B"),
                defect_classes=("scratch",),
                validation_ratio=0.5,
            ),
            frame_source=source,
            belt=belt,
        )
        return collector, source

    @staticmethod
    def annotate_all_cameras(collector):
        for _ in collector.config.camera_roles:
            collector.capture_next()
            collector.skip_current()

    def test_next_part_moves_belt_and_opens_new_part(self):
        with tempfile.TemporaryDirectory() as root:
            belt = FakeBelt()
            collector, source = self.make_collector(root, belt=belt)
            collector.start_session("belt")
            collector.begin_part()
            self.annotate_all_cameras(collector)

            result = collector.next_part()
            self.assertEqual(belt.calls, 1)
            self.assertTrue(result["belt"]["moved"])
            self.assertEqual(result["belt"]["steps"], 1)
            self.assertEqual(result["finished_part"]["part_id"], 1)
            self.assertEqual(result["part"]["part_id"], 2)
            self.assertEqual(result["frame"]["part_id"], 2)
            self.assertEqual(result["frame"]["camera_role"], "CAM_A")
            self.assertEqual(result["current_frame"]["image_id"], 3)
            # Новая деталь сразу получила новый кадр первой камеры.
            self.assertEqual(source.roles, ["CAM_A", "CAM_B", "CAM_A"])

    def test_next_part_requires_saved_annotation_of_current_frame(self):
        with tempfile.TemporaryDirectory() as root:
            belt = FakeBelt()
            collector, _ = self.make_collector(root, belt=belt)
            collector.start_session("guard")
            collector.begin_part()
            collector.capture_next()
            with self.assertRaises(CollectorError):
                collector.next_part()
            self.assertEqual(belt.calls, 0)

    def test_next_part_rejects_incomplete_part_but_keeps_belt(self):
        with tempfile.TemporaryDirectory() as root:
            belt = FakeBelt()
            collector, _ = self.make_collector(root, belt=belt)
            collector.start_session("incomplete")
            collector.begin_part()
            collector.capture_next()
            collector.skip_current()
            # Вторая камера ещё не снята — деталь не завершена.
            with self.assertRaises(CollectorError):
                collector.next_part()
            self.assertEqual(belt.calls, 0)

    def test_next_part_without_belt_still_advances_part(self):
        with tempfile.TemporaryDirectory() as root:
            collector, _ = self.make_collector(root, belt=None)
            collector.start_session("no-belt")
            collector.begin_part()
            self.annotate_all_cameras(collector)
            result = collector.next_part()
            self.assertFalse(result["belt"]["available"])
            self.assertFalse(result["belt"]["moved"])
            self.assertEqual(result["part"]["part_id"], 2)

    def test_advance_belt_counts_steps_without_session(self):
        with tempfile.TemporaryDirectory() as root:
            belt = VirtualBeltStep()
            collector, _ = self.make_collector(root, belt=belt)
            first = collector.advance_belt()
            second = collector.advance_belt()
            self.assertTrue(first["moved"])
            self.assertEqual(second["steps"], 2)

    def test_next_part_can_skip_belt_explicitly(self):
        with tempfile.TemporaryDirectory() as root:
            belt = FakeBelt()
            collector, _ = self.make_collector(root, belt=belt)
            collector.start_session("skip-step")
            collector.begin_part()
            self.annotate_all_cameras(collector)
            result = collector.next_part(move_belt=False)
            self.assertEqual(belt.calls, 0)
            self.assertFalse(result["belt"]["moved"])
            self.assertEqual(result["part"]["part_id"], 2)


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
            # Экраны мастера и шаг ленты между деталями.
            self.assertIn("id=\"next-part\"", page.text)
            self.assertIn("id=\"belt-step\"", page.text)
            self.assertIn("id=\"motion-overlay\"", page.text)
            self.assertIn("step-chip", page.text)
            # Работа с выделенными областями без полной очистки.
            self.assertIn("id=\"delete-region\"", page.text)
            self.assertIn("id=\"reclass-region\"", page.text)
            self.assertEqual(config.status_code, 200)
            self.assertEqual(config.json()["yolo_task"], "segment")
            self.assertEqual(script.status_code, 200)
            self.assertIn("draftPoints", script.text)
            self.assertIn("showScreen", script.text)
            self.assertIn("selectedRegion", script.text)
            openapi = client.get("/openapi.json").text
            self.assertIn("/api/training/parts/next", openapi)
            self.assertIn("/api/training/belt/step", openapi)
            self.assertEqual(stylesheet.status_code, 200)
            self.assertIn("motion-overlay", stylesheet.text)

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

    def test_parts_next_api_moves_belt_and_returns_new_frame(self):
        with tempfile.TemporaryDirectory() as root:
            belt = FakeBelt()
            collector = TrainingCollector(
                TrainingConfig(
                    root_folder=root,
                    camera_roles=("CAM_A", "CAM_B"),
                    defect_classes=("contact",),
                    validation_ratio=0.0,
                ),
                frame_source=FakeFrameSource(),
                belt=belt,
            )
            client = TestClient(create_app(collector))
            client.post("/api/training/session", json={"dataset_name": "flow"})
            client.post("/api/training/parts", json={})
            for _ in range(2):
                frame = client.post("/api/training/capture").json()["frame"]
                response = client.post(
                    "/api/training/annotations",
                    json={"image_id": frame["image_id"], "annotations": []},
                )
                self.assertEqual(response.status_code, 200)

            response = client.post("/api/training/parts/next", json={})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["belt"]["moved"])
            self.assertEqual(payload["belt"]["steps"], 1)
            self.assertEqual(payload["finished_part"]["part_id"], 1)
            self.assertEqual(payload["part"]["part_id"], 2)
            self.assertEqual(payload["frame"]["camera_role"], "CAM_A")
            self.assertEqual(belt.calls, 1)
            # У нового кадра есть ссылки на изображение.
            self.assertTrue(payload["frame"]["original_url"].endswith("/original"))
            self.assertEqual(client.get(payload["frame"]["original_url"]).status_code, 200)
            self.assertIn("belt", client.get("/api/training/state").json())

    def test_parts_next_api_requires_saved_frame(self):
        with tempfile.TemporaryDirectory() as root:
            belt = FakeBelt()
            collector = TrainingCollector(
                TrainingConfig(
                    root_folder=root,
                    camera_roles=("CAM_A",),
                    defect_classes=("contact",),
                ),
                frame_source=FakeFrameSource(),
                belt=belt,
            )
            client = TestClient(create_app(collector))
            client.post("/api/training/session", json={"dataset_name": "guard"})
            client.post("/api/training/parts", json={})
            client.post("/api/training/capture")
            response = client.post("/api/training/parts/next", json={})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(belt.calls, 0)

    def test_belt_step_api_reports_availability(self):
        with tempfile.TemporaryDirectory() as root:
            belt = FakeBelt()
            collector = TrainingCollector(
                TrainingConfig(
                    root_folder=root,
                    camera_roles=("CAM_A",),
                    defect_classes=("contact",),
                ),
                frame_source=FakeFrameSource(),
                belt=belt,
            )
            client = TestClient(create_app(collector))
            response = client.post("/api/training/belt/step")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["belt"]["moved"])
            self.assertEqual(payload["belt"]["steps"], 1)

            # Без подключённой ленты шаг пропускается, но не ломает мастер.
            bare = TrainingCollector(
                TrainingConfig(root_folder=root, camera_roles=("CAM_A",)),
                frame_source=FakeFrameSource(),
            )
            bare_client = TestClient(create_app(bare))
            skip = bare_client.post("/api/training/belt/step").json()
            self.assertFalse(skip["belt"]["available"])
            self.assertFalse(skip["belt"]["moved"])


if __name__ == "__main__":
    unittest.main()
