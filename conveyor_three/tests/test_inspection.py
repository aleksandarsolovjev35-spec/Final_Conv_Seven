"""Inspector трёхкамерной линии: контракт стадии INSPECT.

Vision подменяется фейком, правила — реальные (пороги из thresholds.json).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile

import numpy as np

from application.runtime import RuntimeState
from application.shutdown import ShutdownManager
from core.decision_engine import DecisionEngine
from domain.threshold_loader import ThresholdLoader
from inspection.debug_recorder import DebugRecorder
from inspection.inspector import Inspector
from inspection.part_archive import PartArchive
from types import SimpleNamespace


class ImmediateThread:
    """Поток для тестов: target выполняется синхронно в start()."""

    def __init__(self, target, daemon=True):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()

    def is_alive(self):
        return False

    def join(self, timeout=None):
        return None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLDS_PATH = os.path.join(REPO_ROOT, "thresholds.json")


def make_frame(seed: int = 0) -> np.ndarray:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[:] = 30 + seed
    return frame


def window_detection(confidence: float = 0.95, x1=100, y1=100, x2=160, y2=180):
    """Детекция ячейки окна (kind=uneven_heights) с прямоугольной маской."""
    return {
        "class": "windows",
        "kind": "uneven_heights",
        "confidence": confidence,
        "bbox": [x1, y1, x2, y2],
        "mask": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
    }


def sink_detection(confidence: float = 0.9):
    return {
        "class": "shells",
        "kind": "window_sinks",
        "confidence": confidence,
        "bbox": [10, 10, 40, 40],
        "mask": [[10, 10], [40, 10], [40, 40], [10, 40]],
    }


def glass_detection(confidence: float = 0.9):
    return {
        "class": "glass",
        "kind": "bottom_glass",
        "confidence": confidence,
        "bbox": [50, 50, 200, 200],
        "mask": [[50, 50], [200, 50], [200, 200], [50, 200]],
    }


class FakeVision:
    """process_all возвращает предзаданный словарь детекций."""

    def __init__(self, detections_by_role: dict):
        self.detections_by_role = detections_by_role
        self.last_health = [
            {"role": role, "model": "weights/windows_4.pt",
             "ok": True, "elapsed_ms": 1.0, "detections": len(items),
             "error": None}
            for role, items in detections_by_role.items()
        ]

    def process_all(self, frames: dict) -> dict:
        return {
            role: list(items)
            for role, items in self.detections_by_role.items()
            if role in frames
        }


def make_inspector(vision) -> Inspector:
    return Inspector(
        vision=vision,
        decision=DecisionEngine(
            thresholds=ThresholdLoader(THRESHOLDS_PATH).get_all(),
        ),
        recorder=DebugRecorder(folder="debug_frames", enabled=False),
    )


class InspectorContractTest(unittest.TestCase):
    def test_roles(self):
        inspector = make_inspector(FakeVision({}))
        self.assertEqual(
            inspector.INSPECT_ROLES, ("LEFT", "MIDDLE", "RIGHT"),
        )
        self.assertEqual(inspector.PRESENCE_ROLES, ("LEFT", "RIGHT"))

    def test_inspect_requires_dict_frames(self):
        inspector = make_inspector(FakeVision({}))
        with self.assertRaisesRegex(RuntimeError, "словарём"):
            inspector.inspect(1, 0, ["not", "a", "dict"])

    def test_inspect_requires_all_roles(self):
        inspector = make_inspector(FakeVision({}))
        with self.assertRaisesRegex(RuntimeError, "inspect camera frames"):
            inspector.inspect(1, 0, {"LEFT": make_frame()})

    def test_run_vision_missing_role(self):
        class PartialVision(FakeVision):
            def process_all(self, frames):
                return {"LEFT": []}

        inspector = make_inspector(PartialVision({}))
        with self.assertRaisesRegex(RuntimeError, "Missing vision results"):
            inspector.inspect(1, 0, {
                "LEFT": make_frame(),
                "MIDDLE": make_frame(1),
                "RIGHT": make_frame(2),
            })


class InspectStageTest(unittest.TestCase):
    def frames(self) -> dict:
        return {
            "LEFT": make_frame(0),
            "MIDDLE": make_frame(1),
            "RIGHT": make_frame(2),
        }

    def test_empty_tray_stops_before_defect_rules(self):
        vision = FakeVision({"LEFT": [], "MIDDLE": [], "RIGHT": []})
        inspector = make_inspector(vision)
        result = inspector.inspect(7, 3, self.frames())
        self.assertTrue(result.is_empty_tray)
        self.assertEqual(result.defects, [])
        # Только служебное part_presence без defect rules.
        self.assertEqual(len(result.rule_results), 1)
        self.assertEqual(result.rule_results[0].rule_name, "part_presence")
        self.assertTrue(result.rule_results[0].details["empty_tray"])

    def test_good_part_full_pipeline(self):
        vision = FakeVision({
            "LEFT": [window_detection(0.95, 100, 100, 160, 130)],
            "MIDDLE": [],
            "RIGHT": [window_detection(0.95, 300, 100, 360, 130)],
        })
        inspector = make_inspector(vision)
        result = inspector.inspect(1, 0, self.frames())
        self.assertFalse(result.is_empty_tray)
        self.assertEqual(result.defects, [])
        self.assertEqual(result.stage, "inspect")
        # part_presence + 4 defect rules трёхкамерника.
        names = [item.rule_name for item in result.rule_results]
        self.assertEqual(
            names,
            ["part_presence", "uneven_heights", "window_sinks",
             "bottom_glass", "welding"],
        )
        self.assertIn("LEFT", result.annotated)
        self.assertIn("LEFT", result.raw_overlay_frames)

    def test_triggered_rule_becomes_defect(self):
        vision = FakeVision({
            "LEFT": [window_detection(0.95, 100, 100, 160, 130)],
            "MIDDLE": [glass_detection(0.9)],
            "RIGHT": [window_detection(0.95, 300, 100, 360, 130)],
        })
        inspector = make_inspector(vision)
        result = inspector.inspect(2, 1, self.frames())
        self.assertIn("bottom_glass", result.defects)

    def test_progress_callback_roles(self):
        calls = []

        def on_progress(phase, label, *, part_id=None, roles=()):
            calls.append((phase, tuple(roles)))

        vision = FakeVision({
            "LEFT": [window_detection(0.95, 100, 100, 160, 130)],
            "MIDDLE": [],
            "RIGHT": [window_detection(0.95, 300, 100, 360, 130)],
        })
        inspector = make_inspector(vision)
        inspector.set_progress_callback(on_progress)
        inspector.inspect(1, 0, self.frames())
        self.assertTrue(calls)
        self.assertIn(("INSPECT_MODELS", ("LEFT", "MIDDLE", "RIGHT")), calls)
        self.assertIn(("INSPECT_PRESENCE", ("LEFT", "RIGHT")), calls)

    def test_progress_callback_errors_swallowed(self):
        def broken_callback(*_args, **_kwargs):
            raise RuntimeError("ui is gone")

        vision = FakeVision({
            "LEFT": [window_detection(0.95, 100, 100, 160, 130)],
            "MIDDLE": [],
            "RIGHT": [window_detection(0.95, 300, 100, 360, 130)],
        })
        inspector = make_inspector(vision)
        inspector.set_progress_callback(broken_callback)
        result = inspector.inspect(1, 0, self.frames())
        self.assertFalse(result.is_empty_tray)


class DiagnosticsApiTest(unittest.TestCase):
    def test_evaluate_all_empty_tray(self):
        vision = FakeVision({"LEFT": [], "MIDDLE": [], "RIGHT": []})
        inspector = make_inspector(vision)
        frames = {
            "LEFT": make_frame(0),
            "MIDDLE": make_frame(1),
            "RIGHT": make_frame(2),
        }
        vision_results, rule_results, model_rows = inspector.evaluate_all(
            frames,
        )
        self.assertEqual(len(rule_results), 1)
        self.assertEqual(rule_results[0].rule_name, "part_presence")
        self.assertTrue(model_rows)

    def test_evaluate_rules_limited_by_roles(self):
        vision = FakeVision({})
        inspector = make_inspector(vision)
        # Только MIDDLE: стекло и сварка, без правил окон.
        rules = inspector.decision.rules_for_roles(("MIDDLE",))
        self.assertEqual(
            sorted(rule.name for rule in rules),
            ["bottom_glass", "welding"],
        )



if __name__ == "__main__":
    unittest.main()


class PartArchiveRetentionTest(unittest.TestCase):
    """Архив трёхкамерной линии: retention, resume и закрытие партии."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "archive")

    def tearDown(self):
        self.tmp.cleanup()

    def make_archive(self, **kwargs):
        kwargs.setdefault("root_folder", self.root)
        kwargs.setdefault("batch_id", "batch_test")
        return PartArchive(**kwargs)

    def store_and_finalize(self, archive, part_id=1, category="GOOD"):
        archive.store_frames(
            part_id,
            raw_frames={"LEFT": make_frame()},
            annotated_frames={"LEFT": make_frame(1)},
            raw_overlay_frames={"LEFT": make_frame(2)},
        )
        return archive.finalize(
            part_id, category, decision="none", defects=[], step=3,
        )

    def _part_folders(self, archive):
        found = []
        for category in PartArchive.CATEGORY_DIRS.values():
            category_root = os.path.join(archive.batch_folder, category)
            if not os.path.isdir(category_root):
                continue
            for name in os.listdir(category_root):
                if name.startswith("part_"):
                    found.append(os.path.join(category_root, name))
        return sorted(found)

    def _load_manifest(self, archive):
        path = os.path.join(archive.batch_folder, "batch.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_industrial_retention_keeps_only_last_images(self):
        archive = self.make_archive()
        for part_id in range(1, 13):
            self.store_and_finalize(archive, part_id=part_id)

        # Папки и метаданные остаются для всех корпусов партии.
        self.assertEqual(len(self._part_folders(archive)), 12)
        for part_id in (1, 2, 12):
            info = archive.get_part_info(part_id)
            self.assertIsNotNone(info)
            self.assertTrue(os.path.exists(
                os.path.join(info["folder"], "meta.json"),
            ))

        # Изображения остаются только для последних десяти корпусов.
        for part_id in (1, 2):
            self.assertEqual(archive.get_part_images(part_id), {})
        images = archive.get_part_images(12)
        self.assertEqual(set(images["LEFT"]), {"raw", "raw_overlay", "debug"})

        # Статистика партии и манифест не трогаются.
        self.assertEqual(archive.stats["total"], 12)
        self.assertEqual(archive._batch_stats["total"], 12)
        manifest = self._load_manifest(archive)
        self.assertEqual(
            [item["part_id"] for item in manifest["parts"]],
            list(range(1, 13)),
        )
        self.assertEqual(manifest["counts"]["total"], 12)

    def test_retention_limit_is_configurable(self):
        archive = self.make_archive(retained_parts=3)
        for part_id in range(1, 5):
            self.store_and_finalize(archive, part_id=part_id)

        self.assertEqual(len(self._part_folders(archive)), 4)
        self.assertIsNotNone(archive.get_part_info(1))
        self.assertEqual(archive.get_part_images(1), {})
        self.assertIsNotNone(archive.get_part_info(4))
        self.assertTrue(os.path.exists(
            os.path.join(archive.get_part_info(4)["folder"], "LEFT.jpg"),
        ))

    def test_retention_applies_on_resume(self):
        archive = self.make_archive()
        for part_id in range(1, 13):
            self.store_and_finalize(archive, part_id=part_id)

        resumed = PartArchive.resume(self.root, "batch_test")
        self.assertEqual(len(self._part_folders(resumed)), 12)
        for part_id in (1, 2):
            self.assertIsNotNone(resumed.get_part_info(part_id))
            self.assertEqual(resumed.get_part_images(part_id), {})
        self.assertIsNotNone(resumed.get_part_info(12))
        self.assertTrue(os.path.exists(
            os.path.join(resumed.get_part_info(12)["folder"], "LEFT.jpg"),
        ))
        self.assertEqual(resumed._batch_stats["total"], 12)
        self.assertEqual(resumed.next_part_id, 13)

    def test_close_batch_strips_images_and_keeps_manifest(self):
        archive = self.make_archive()
        for part_id in range(1, 4):
            self.store_and_finalize(archive, part_id=part_id)

        zip_path = archive.close_batch()

        self.assertTrue(zip_path and os.path.exists(zip_path))
        with zipfile.ZipFile(zip_path) as bundle:
            names = bundle.namelist()
            self.assertIn("batch.json", names)
            self.assertIn("GOOD/part_0001/meta.json", names)
            self.assertFalse([name for name in names if name.endswith(".jpg")])
            manifest = json.loads(bundle.read("batch.json"))
        self.assertEqual(manifest["status"], "CLOSED")
        self.assertEqual(manifest["counts"]["total"], 3)


class ShutdownKeepsBatchOpenTest(unittest.TestCase):
    """Активная партия не закрывается при выходе, если так помечена."""

    def test_keep_open_on_shutdown_skips_finalization(self):
        events = []
        runtime = RuntimeState(monitor=SimpleNamespace())
        manager = ShutdownManager(
            runtime,
            thread_factory=ImmediateThread,
            batch_sender=lambda folder: events.append(("sent", folder)),
        )
        archive = SimpleNamespace(
            keep_open_on_shutdown=True,
            close_manifest=lambda: events.append(("closed", None)),
            compress=lambda: events.append(("zipped", None)),
            batch_folder="archive/batch",
            root_folder="archive",
        )

        manager._shutdown_compress(archive)

        self.assertNotIn(("closed", None), events)
        self.assertNotIn(("zipped", None), events)
