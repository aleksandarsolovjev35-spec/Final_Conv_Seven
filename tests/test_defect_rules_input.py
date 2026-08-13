"""Правила входной инспекции: window_geometry и window_sinks.

Проверяются fail-closed поведения (нет детекций или масок -> срабатывание),
подсчёт окон, замер положения перекладины по синтетическим маскам и
пересечения раковин с окнами.
"""

from __future__ import annotations

import unittest

from domain.defect_rules import (
    InputWindowGeometryRule,
    InputWindowSinksRule,
)
from helpers_defects import (
    det,
    load_thresholds,
    rect_mask,
    window_mask,
)

EXPECTED = 7
TOP_RANGE = (15.0, 45.0)


def make_rule(rule_class, thresholds, disabled=None):
    thresholds = dict(thresholds)
    if disabled:
        thresholds["disabled_rules"] = list(disabled)
    return rule_class(thresholds)


def good_windows(role_prefix="INPUT_LEFT"):
    """7 окон с перекладиной: top=30px, bottom=30px — внутри допуска."""
    windows = []
    for i, x in enumerate(range(0, 7 * 60, 60)):
        windows.append(det(
            "flatness",
            [x, 0, x + 40, 59],
            0.9,
            window_mask(x, 0, 29, 40, 59),
        ))
    return windows


class WindowGeometryRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            InputWindowGeometryRule, self.thresholds,
            disabled=["window_geometry"],
        )
        result = rule.check({"INPUT_LEFT": []})
        self.assertFalse(result.triggered)
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_fail_closed(self):
        rule = InputWindowGeometryRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": [], "INPUT_RIGHT": []})
        self.assertTrue(result.triggered)
        left = result.details["per_role"]["INPUT_LEFT"]
        self.assertEqual(left["reason"], f"too_few: 0/{EXPECTED}")
        self.assertEqual(left["found"], 0)
        self.assertTrue(any(
            drawing["type"] == "construction_error"
            for drawing in result.drawings
        ))

    def test_too_few_windows_triggered(self):
        rule = InputWindowGeometryRule(self.thresholds)
        windows = good_windows()[:4]
        result = rule.check({"INPUT_LEFT": windows})
        left = result.details["per_role"]["INPUT_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(left["reason"], f"too_few: 4/{EXPECTED}")

    def test_good_row_not_triggered(self):
        rule = InputWindowGeometryRule(self.thresholds)
        result = rule.check({
            "INPUT_LEFT": good_windows("INPUT_LEFT"),
            "INPUT_RIGHT": good_windows("INPUT_RIGHT"),
        })
        self.assertFalse(result.triggered)
        for role in ("INPUT_LEFT", "INPUT_RIGHT"):
            details = result.details["per_role"][role]
            self.assertEqual(details["found"], EXPECTED)
            self.assertTrue(all(
                not item["top_fail"] and not item["bottom_fail"]
                for item in details["items"]
            ))

    def test_window_shifted_up_triggered(self):
        # Перекладина на y=10: top=10px < min 15px.
        windows = [
            det(
                "flatness", [x, 0, x + 40, 59], 0.9,
                window_mask(x, 0, 9, 40, 59),
            )
            for x in range(0, 7 * 60, 60)
        ]
        rule = InputWindowGeometryRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": windows})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertTrue(result.triggered)
        self.assertTrue(all(item["top_fail"] for item in details["items"]))
        self.assertEqual(details["failed_indices"], [1, 2, 3, 4, 5, 6, 7])

    def test_extra_detections_selected_by_evenness(self):
        # 8 детекций, ожидается 7: лишняя сбоку отбрасывается.
        windows = good_windows()
        extra = det("flatness", [420, 0, 460, 59], 0.9,
                    window_mask(420, 0, 29, 40, 59))
        rule = InputWindowGeometryRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": windows + [extra]})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["found"], EXPECTED)
        self.assertEqual(details["ignored"], 1)

    def test_missing_mask_invalid(self):
        windows = good_windows()
        windows[3] = det("flatness", [180, 0, 220, 59], 0.9)
        rule = InputWindowGeometryRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": windows})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["items"][3]["reason"], "missing_mask")

    def test_missing_threshold_key_raises(self):
        thresholds = dict(self.thresholds)
        del thresholds["INPUT_LEFT.input_window_geometry_min_confidence"]
        rule = InputWindowGeometryRule(thresholds)
        with self.assertRaisesRegex(ValueError, "Отсутствуют параметры"):
            rule.check({"INPUT_LEFT": []})

    def test_invalid_confidence_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["INPUT_LEFT.input_window_geometry_min_confidence"] = 2
        rule = InputWindowGeometryRule(thresholds)
        with self.assertRaisesRegex(ValueError, "0..1"):
            rule.check({"INPUT_LEFT": []})

    def test_inverted_range_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["INPUT_LEFT.input_window_geometry_top_px_min"] = 50
        thresholds["INPUT_LEFT.input_window_geometry_top_px_max"] = 10
        rule = InputWindowGeometryRule(thresholds)
        with self.assertRaisesRegex(ValueError, "не может превышать"):
            rule.check({"INPUT_LEFT": []})

    def test_zero_center_zone_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["INPUT_LEFT.input_window_geometry_center_zone_ratio"] = 0
        rule = InputWindowGeometryRule(thresholds)
        with self.assertRaisesRegex(ValueError, "0..1"):
            rule.check({"INPUT_LEFT": []})

    def test_low_confidence_detections_ignored(self):
        windows = [det("flatness", [0, 0, 40, 59], 0.05)]
        rule = InputWindowGeometryRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": windows})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertEqual(details["found_raw"], 0)

    def test_role_absent_is_skipped(self):
        rule = InputWindowGeometryRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": good_windows()})
        self.assertNotIn("INPUT_RIGHT", result.details["per_role"])


class WindowSinksRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            InputWindowSinksRule, self.thresholds,
            disabled=["window_sinks"],
        )
        result = rule.check({"INPUT_LEFT": []})
        self.assertFalse(result.triggered)
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_no_sinks_not_triggered(self):
        rule = InputWindowSinksRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": good_windows()})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertFalse(result.triggered)
        self.assertIsNone(details["reason"])
        self.assertEqual(details["sinks_total"], 0)

    def test_sink_without_windows_triggered(self):
        sink = det("objects", [100, 100, 120, 120], 0.9,
                   rect_mask(100, 100, 120, 120))
        rule = InputWindowSinksRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": [sink]})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertTrue(result.triggered)
        self.assertTrue(details["reason"])

    def test_sink_outside_windows_not_triggered(self):
        windows = good_windows()
        sink = det("objects", [400, 200, 420, 220], 0.9,
                   rect_mask(400, 200, 420, 220))
        rule = InputWindowSinksRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": windows + [sink]})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["confirmed_sinks"], 0)

    def test_sink_inside_window_triggered(self):
        windows = good_windows()
        # Окно 0..40 x 0..59: раковина внутри него.
        sink = det("objects", [10, 10, 30, 25], 0.9,
                   rect_mask(10, 10, 30, 25))
        rule = InputWindowSinksRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": windows + [sink]})
        details = result.details["per_role"]["INPUT_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["confirmed_sinks"], 1)
        self.assertEqual(details["hits"][0]["sink_index"], 1)

    def test_invalid_overlap_threshold_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["INPUT_LEFT.input_window_sinks_overlap_min_px"] = 0
        rule = InputWindowSinksRule(thresholds)
        with self.assertRaisesRegex(ValueError, ">= 1"):
            rule.check({"INPUT_LEFT": []})

    def test_low_confidence_sink_ignored(self):
        windows = good_windows()
        sink = det("objects", [10, 10, 30, 25], 0.05,
                   rect_mask(10, 10, 30, 25))
        rule = InputWindowSinksRule(self.thresholds)
        result = rule.check({"INPUT_LEFT": windows + [sink]})
        self.assertFalse(result.triggered)


if __name__ == "__main__":
    unittest.main()
