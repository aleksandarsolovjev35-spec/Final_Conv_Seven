"""Слой инспекции: Inspector, PartArchive, DebugRecorder и карточки отчёта.

Оборудование и нейросети заменяются дублёрами; кадры — синтетическими
numpy-массивами. Проверяется полный путь детали: кадры -> модели ->
правила -> разметка -> архив (meta.json, batch.json, stats, ZIP).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

import numpy as np

from domain.defect_rules import RuleResult
from inspection.debug_recorder import DebugRecorder
from inspection.inspector import Inspector
from inspection.part_archive import PartArchive
from inspection.result import InspectionResult
from inspection.run_report import (
    InspectionReportError,
    prepare_presence_result,
    prepare_rule_results,
    summarize_model_health,
)


def make_frame(width=64, height=48, value=128):
    return np.full((height, width, 3), value, dtype=np.uint8)


class FakeVision:
    last_health = []

    def __init__(self, results=None):
        self.results = results or {}

    def process_all(self, frames):
        return {role: list(self.results.get(role, [])) for role in frames}


class FakeDecision:
    def __init__(self, thresholds=None, results=None):
        self.thresholds = thresholds or {
            "INPUT_LEFT.input_window_geometry_min_confidence": 0.4,
            "INPUT_RIGHT.input_window_geometry_min_confidence": 0.4,
            "INPUT_LEFT.input_part_presence_false_positive_max_count": 2,
            "INPUT_RIGHT.input_part_presence_false_positive_max_count": 2,
        }
        self.results = results or []
        self.rules = [object()]

    def rules_for_roles(self, roles):
        return [object()]

    def evaluate_rules_detailed(self, rules, vision_results, frames=None):
        return self.results


class FakeRecorder:
    def __init__(self):
        self.calls = []

    def process(self, part_id, step, frames, rule_results):
        self.calls.append((part_id, step, rule_results))
        return {role: frame.copy() for role, frame in frames.items()}


class InspectorTest(unittest.TestCase):
    def make_inspector(self, vision_results=None, rule_results=None):
        vision = FakeVision(vision_results or {})
        decision = FakeDecision(results=rule_results or [])
        recorder = FakeRecorder()
        inspector = Inspector(vision, decision, recorder)
        return inspector, vision, decision, recorder

    def test_evaluate_presence_empty_tray(self):
        inspector, *_ = self.make_inspector()
        result = inspector.evaluate_presence({
            "INPUT_LEFT": [],
            "INPUT_RIGHT": [],
        })
        self.assertEqual(result.rule_name, "part_presence")
        self.assertTrue(result.details["empty_tray"])
        self.assertIn("measurement_cards", result.details)

    def test_evaluate_presence_present(self):
        inspector, *_ = self.make_inspector()
        result = inspector.evaluate_presence({
            "INPUT_LEFT": [
                {"class": "flatness", "confidence": 0.9},
            ] * 3,
            "INPUT_RIGHT": [
                {"class": "flatness", "confidence": 0.9},
            ] * 3,
        })
        self.assertFalse(result.details["empty_tray"])

    def test_evaluate_rules_returns_prepared(self):
        rule_result = RuleResult("window_geometry", True, details={
            "per_role": {"INPUT_LEFT": {"triggered": True, "found": 0}},
        })
        inspector, *_ = self.make_inspector(rule_results=[rule_result])
        results = inspector.evaluate_rules(
            {"INPUT_LEFT": []}, roles=("INPUT_LEFT",),
        )
        self.assertEqual(len(results), 1)
        self.assertIn("role_status", results[0].details)

    def test_evaluate_all_empty_tray_stops_chain(self):
        inspector, *_ = self.make_inspector()
        vision_results, rule_results, health = inspector.evaluate_all({
            "INPUT_LEFT": make_frame(), "INPUT_RIGHT": make_frame(),
        })
        self.assertEqual(len(rule_results), 1)
        self.assertEqual(rule_results[0].details["empty_tray"], True)

    def test_evaluate_all_full_chain(self):
        inspector, *_ = self.make_inspector(vision_results={
            "INPUT_LEFT": [{"class": "flatness", "confidence": 0.9}] * 3,
            "INPUT_RIGHT": [{"class": "flatness", "confidence": 0.9}] * 3,
        }, rule_results=[
            RuleResult("window_geometry", False, details={
                "per_role": {"INPUT_LEFT": {"triggered": False}},
            }),
        ])
        vision_results, rule_results, health = inspector.evaluate_all({
            "INPUT_LEFT": make_frame(), "INPUT_RIGHT": make_frame(),
            "SPIDER_LEFT": make_frame(), "SPIDER_RIGHT": make_frame(),
            "SPIDER_IN": make_frame(), "SPIDER_OUT": make_frame(),
            "TOP": make_frame(),
        })
        self.assertGreaterEqual(len(rule_results), 2)

    def test_model_health(self):
        inspector, _, decision, _ = self.make_inspector()
        decision.results = [RuleResult("x", False)]
        inspector.vision.last_health = [
            {"role": "TOP", "model": "m", "ok": True, "elapsed_ms": 10.0,
             "detections": 3},
        ]
        self.assertEqual(inspector.model_health()[0]["role"], "TOP")

    def test_inspect_input_empty_tray(self):
        inspector, _, _, recorder = self.make_inspector()
        result = inspector.inspect_input(1, 2, {
            "INPUT_LEFT": make_frame(), "INPUT_RIGHT": make_frame(),
        })
        self.assertIsInstance(result, InspectionResult)
        self.assertTrue(result.is_empty_tray)
        self.assertEqual(result.stage, "input")
        self.assertEqual(recorder.calls, [])

    def test_inspect_input_full(self):
        inspector, _, _, recorder = self.make_inspector(vision_results={
            "INPUT_LEFT": [{"class": "flatness", "confidence": 0.9}] * 3,
            "INPUT_RIGHT": [{"class": "flatness", "confidence": 0.9}] * 3,
        }, rule_results=[RuleResult("window_geometry", False, details={
            "per_role": {"INPUT_LEFT": {"triggered": False, "found": 7}},
        })])
        result = inspector.inspect_input(1, 2, {
            "INPUT_LEFT": make_frame(), "INPUT_RIGHT": make_frame(),
        })
        self.assertFalse(result.is_empty_tray)
        self.assertEqual(len(result.rule_results), 2)
        self.assertEqual(len(recorder.calls), 1)
        self.assertIn("INPUT_LEFT", result.annotated)
        self.assertIn("INPUT_LEFT", result.raw_overlay_frames)

    def test_inspect_input_defect_collected(self):
        inspector, _, _, _ = self.make_inspector(vision_results={
            "INPUT_LEFT": [{"class": "flatness", "confidence": 0.9}] * 3,
            "INPUT_RIGHT": [{"class": "flatness", "confidence": 0.9}] * 3,
        }, rule_results=[RuleResult("window_geometry", True, details={
            "per_role": {"INPUT_LEFT": {"triggered": True, "found": 3}},
        })])
        result = inspector.inspect_input(1, 2, {
            "INPUT_LEFT": make_frame(), "INPUT_RIGHT": make_frame(),
        })
        self.assertEqual(result.defects, ["window_geometry"])

    def test_inspect_spider(self):
        inspector, _, _, recorder = self.make_inspector(vision_results={},
                                                        rule_results=[
            RuleResult("top_contacts", False, details={
                "per_role": {"TOP": {"triggered": False, "found": 14}},
            }),
        ])
        result = inspector.inspect_spider(1, 2, {
            "SPIDER_LEFT": make_frame(), "SPIDER_RIGHT": make_frame(),
            "SPIDER_IN": make_frame(), "SPIDER_OUT": make_frame(),
            "TOP": make_frame(),
        })
        self.assertEqual(result.stage, "spider")
        self.assertEqual(len(recorder.calls), 1)

    def test_stage_frames_missing_role(self):
        inspector, *_ = self.make_inspector()
        with self.assertRaisesRegex(RuntimeError, "Missing input camera frames"):
            inspector.inspect_input(1, 2, {"INPUT_LEFT": make_frame()})

    def test_run_vision_missing_role(self):
        class SparseVision(FakeVision):
            def process_all(self, frames):
                return {"INPUT_LEFT": []}

        inspector = Inspector(
            SparseVision(), FakeDecision(), FakeRecorder(),
        )
        with self.assertRaisesRegex(RuntimeError, "Missing vision results"):
            inspector.inspect_input(1, 2, {
                "INPUT_LEFT": make_frame(),
                "INPUT_RIGHT": make_frame(),
            })

    def test_progress_callback_errors_swallowed(self):
        def boom(phase, label, **kwargs):
            raise RuntimeError("ui broke")

        inspector, _, _, _ = self.make_inspector(vision_results={
            "INPUT_LEFT": [{"class": "flatness", "confidence": 0.9}],
            "INPUT_RIGHT": [{"class": "flatness", "confidence": 0.9}],
        }, rule_results=[RuleResult("window_geometry", False, details={
            "per_role": {"INPUT_LEFT": {"triggered": False, "found": 7}},
        })])
        inspector.set_progress_callback(boom)
        inspector.inspect_input(1, 2, {
            "INPUT_LEFT": make_frame(), "INPUT_RIGHT": make_frame(),
        })  # не должно бросить исключение


class RunReportTest(unittest.TestCase):
    def test_summarize_model_health_filters_non_dicts(self):
        rows = summarize_model_health([
            {"role": "TOP", "model": "m", "ok": False, "elapsed_ms": 5.5,
             "detections": 1, "error": "x"},
            "garbage",
            None,
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["elapsed_ms"], 5.5)
        self.assertFalse(rows[0]["ok"])

    def test_prepare_presence_wrong_rule(self):
        result = RuleResult("not_presence", False)
        with self.assertRaisesRegex(InspectionReportError, "неверное правило"):
            prepare_presence_result(result)

    def test_prepare_presence_missing_empty_tray(self):
        result = RuleResult("part_presence", False, details={})
        with self.assertRaisesRegex(InspectionReportError, "empty_tray"):
            prepare_presence_result(result)

    def test_prepare_rule_results_empty(self):
        self.assertEqual(prepare_rule_results([]), [])

    def test_prepare_rule_results_duplicate_names(self):
        with self.assertRaisesRegex(InspectionReportError, "дублируются"):
            prepare_rule_results([
                RuleResult("same", False),
                RuleResult("same", False),
            ])

    def test_prepare_rule_results_missing_name(self):
        with self.assertRaisesRegex(InspectionReportError, "без имени"):
            prepare_rule_results([RuleResult("", False)])

    def test_prepare_rule_results_non_bool_triggered(self):
        result = RuleResult("a", False)
        result.triggered = "yes"
        with self.assertRaisesRegex(InspectionReportError, "не-bool"):
            prepare_rule_results([result])

    def test_prepare_rule_results_attaches_cards(self):
        result = RuleResult("window_geometry", True, details={
            "per_role": {"INPUT_LEFT": {"triggered": True, "found": 3}},
        })
        prepared = prepare_rule_results([result])[0]
        self.assertIn("measurement_cards", prepared.details)
        self.assertIn("role_status", prepared.details)
        self.assertEqual(
            prepared.details["role_status"][0]["status"], "ОТКЛОНЕНИЕ",
        )

    def test_region_missing_status(self):
        result = RuleResult("top_platform", True, details={
            "per_role": {"TOP": {
                "triggered": True, "reason": "no_valid_platform",
            }},
        })
        prepared = prepare_rule_results([result])[0]
        self.assertEqual(
            prepared.details["role_status"][0]["status"],
            "ОБЛАСТЬ НЕ ПОСТРОЕНА",
        )

    def test_skipped_status(self):
        result = RuleResult("top_glass", False, details={
            "per_role": {"TOP": {
                "triggered": False, "skipped": True,
                "reason": "reference_invalid: no_valid_platform",
            }},
        })
        prepared = prepare_rule_results([result])[0]
        self.assertEqual(
            prepared.details["role_status"][0]["status"], "НЕТ ИЗМЕРЕНИЯ",
        )

    def test_presence_status(self):
        result = RuleResult("part_presence", False, details={
            "empty_tray": False,
        })
        prepared = prepare_presence_result(result)
        self.assertEqual(
            prepared.details["role_status"][0]["status"], "КОРПУС",
        )
        empty = prepare_presence_result(RuleResult("part_presence", False,
                                                   details={"empty_tray": True}))
        self.assertEqual(
            empty.details["role_status"][0]["status"], "ПУСТО",
        )


class DebugRecorderTest(unittest.TestCase):
    def test_disabled_does_not_save(self):
        recorder = DebugRecorder(folder="/nonexistent", enabled=False)
        annotated = recorder.process(1, 1, {"TOP": make_frame()}, [])
        self.assertIn("TOP", annotated)
        self.assertEqual(recorder._step_counter, 0)

    def test_save_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = DebugRecorder(folder=tmp, enabled=True, save_interval=2)
            recorder.process(1, 1, {"TOP": make_frame()}, [])
            self.assertEqual(recorder._step_counter, 1)
            self.assertEqual(len(os.listdir(tmp)), 0)
            recorder.process(2, 2, {"TOP": make_frame()}, [])
            folders = os.listdir(tmp)
            self.assertEqual(len(folders), 1)
            self.assertTrue(os.path.exists(
                os.path.join(tmp, folders[0], "TOP.jpg"),
            ))

    def test_annotate_uses_debug_overlay(self):
        recorder = DebugRecorder(enabled=False)
        result = RuleResult("x", True, drawings=[{
            "type": "construction_error", "role": "TOP",
            "message": "NO PLATFORM", "triggered": True,
        }])
        annotated = recorder.process(1, 1, {"TOP": make_frame()}, [result])
        self.assertIn("TOP", annotated)


class PartArchiveTest(unittest.TestCase):
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
            raw_frames={"TOP": make_frame()},
            annotated_frames={"TOP": make_frame(1)},
            raw_overlay_frames={"TOP": make_frame(2)},
        )
        return archive.finalize(
            part_id, category, decision="none", defects=[], step=3,
        )

    def test_disabled_archive_no_files(self):
        archive = self.make_archive(enabled=False)
        self.assertIsNone(self.store_and_finalize(archive))
        self.assertFalse(os.path.exists(self.root))

    def test_finalize_writes_files(self):
        archive = self.make_archive()
        folder = self.store_and_finalize(archive)
        self.assertTrue(folder)
        self.assertTrue(os.path.exists(os.path.join(folder, "meta.json")))
        self.assertTrue(os.path.exists(os.path.join(folder, "TOP.jpg")))
        self.assertTrue(os.path.exists(os.path.join(folder, "TOP_raw.jpg")))
        self.assertTrue(os.path.exists(os.path.join(folder, "TOP_debug.jpg")))

    def test_meta_json_content(self):
        archive = self.make_archive()
        folder = self.store_and_finalize(archive, part_id=7, category="BAD")
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["part_id"], 7)
        self.assertEqual(meta["category"], "BAD")
        self.assertEqual(meta["category_label"], "БРАК")
        self.assertEqual(meta["defects"], [])
        self.assertEqual(meta["step"], 3)
        self.assertEqual(meta["schema_version"], 2)
        self.assertEqual(meta["requested_category"], "BAD")

    def test_stats_and_manifest(self):
        archive = self.make_archive()
        self.store_and_finalize(archive, part_id=1, category="GOOD")
        self.store_and_finalize(archive, part_id=2, category="BAD")
        with open(os.path.join(self.root, "stats.json"), encoding="utf-8") as f:
            stats = json.load(f)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["good"], 1)
        self.assertEqual(stats["bad"], 1)
        with open(os.path.join(archive.batch_folder, "batch.json"),
                  encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["status"], "OPEN")
        self.assertEqual(len(manifest["parts"]), 2)

    def test_unknown_category_normalised_to_bad(self):
        archive = self.make_archive()
        folder = self.store_and_finalize(archive, category="??")
        self.assertIn("BAD", folder)
        self.assertEqual(PartArchive.normalise_category("weird"), "BAD")
        self.assertEqual(PartArchive.normalise_category("cleanup"), "CLEANUP")

    def test_get_part_info_and_images(self):
        archive = self.make_archive()
        self.store_and_finalize(archive, part_id=5)
        info = archive.get_part_info(5)
        self.assertEqual(info["part_id"], 5)
        images = archive.get_part_images(5)
        self.assertEqual(set(images["TOP"]), {"raw", "raw_overlay", "debug"})
        self.assertIsNone(archive.get_part_info(99))
        self.assertEqual(archive.get_part_images(99), {})

    def test_can_reconfigure_before_start(self):
        archive = self.make_archive()
        self.assertTrue(archive.can_reconfigure())
        settings = archive.reconfigure(
            root_folder=os.path.join(self.tmp.name, "archive2"),
            enabled=True,
            jpeg_quality=80,
            compress_on_shutdown=False,
            delete_original_after_zip=False,
        )
        self.assertEqual(settings["jpeg_quality"], 80)
        self.assertFalse(settings["compress_on_shutdown"])
        self.assertFalse(settings["delete_original_after_zip"])
        self.assertFalse(archive.compress_on_shutdown)
        self.assertFalse(archive.delete_original_after_zip)
        self.assertIn("archive2", settings["root_path"])

    def test_reconfigure_can_disable_unavailable_archive_root(self):
        archive = self.make_archive(enabled=True)
        unavailable = os.path.join(self.tmp.name, "unavailable")
        # Обычный файл вместо каталога воспроизводит отключённый/сломанный
        # носитель: validate_root() такой путь обоснованно отклоняет.
        with open(unavailable, "w", encoding="utf-8") as stream:
            stream.write("not a directory")

        settings = archive.reconfigure(
            root_folder=unavailable,
            enabled=False,
            jpeg_quality=92,
        )

        self.assertFalse(archive.enabled)
        self.assertFalse(settings["enabled"])
        self.assertEqual(archive.root_folder, os.path.abspath(unavailable))
        self.assertIsNone(settings["validation"])

    def test_reconfigure_after_finalize_raises(self):
        archive = self.make_archive()
        self.store_and_finalize(archive)
        self.assertFalse(archive.can_reconfigure())
        with self.assertRaisesRegex(RuntimeError, "только до начала партии"):
            archive.reconfigure(root_folder=self.root, enabled=True,
                                jpeg_quality=90)

    def test_get_settings_shape(self):
        archive = self.make_archive()
        settings = archive.get_settings()
        for key in ("enabled", "root_path", "jpeg_quality", "batch_id",
                    "batch_folder", "editable", "validation"):
            self.assertIn(key, settings)
        self.assertTrue(settings["validation"]["writable"])

    def test_validate_root_unwritable(self):
        blocked = os.path.join(self.tmp.name, "blocked")
        with open(blocked, "w", encoding="utf-8") as stream:
            stream.write("file, not dir")
        with self.assertRaisesRegex(ValueError, "недоступна"):
            PartArchive.validate_root(blocked)

    def test_compress_creates_zip(self):
        archive = self.make_archive()
        self.store_and_finalize(archive)
        zip_path = archive.compress(delete_original=True)
        self.assertTrue(zip_path)
        self.assertTrue(os.path.exists(zip_path))
        self.assertFalse(os.path.exists(archive.batch_folder))
        self.assertTrue(zipfile_has(zip_path, "GOOD/part_0001/meta.json"))

    def test_compress_disabled(self):
        archive = self.make_archive(enabled=False)
        self.assertIsNone(archive.compress())

    def test_compress_empty_batch(self):
        archive = self.make_archive()
        self.assertIsNone(archive.compress())

    def test_batch_folder_uses_date_and_batch(self):
        archive = self.make_archive(batch_id="партия 1")
        self.assertIn("партия_1", archive.batch_folder)
        self.assertEqual(PartArchive._safe_name(""), "none")
        self.assertEqual(PartArchive._safe_name("a b/c:d" * 10)[:50],
                         ("a_b_c_d" * 10)[:50])

    def test_encode_image_error(self):
        archive = self.make_archive()
        with self.assertRaisesRegex(RuntimeError, "JPEG"):
            archive._encode_image(None)

    def test_stats_corrupted_file_reset(self):
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, "stats.json"), "w",
                  encoding="utf-8") as f:
            f.write("not json")
        archive = self.make_archive()
        self.assertEqual(archive.stats["total"], 0)


def zipfile_has(zip_path, member):
    import zipfile
    with zipfile.ZipFile(zip_path) as archive:
        return member in archive.namelist()


if __name__ == "__main__":
    unittest.main()
