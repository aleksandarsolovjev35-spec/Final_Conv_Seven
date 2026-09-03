"""Правило ``black_spots_omission`` на камерах короткой omission.

Проверяются: fail-безопасное поведение при отсутствии области short omission,
подтверждение пятна только по пересечению его маски с областью short omission,
отбрасывание пятен вне области как ложных срабатываний и маршрут ``BAD``.
"""

from __future__ import annotations

import unittest

from domain.defect_rules import (
    SpiderBlackSpotsOmissionRule,
    SpiderShortOmissionRule,
)
from helpers_defects import (
    det,
    load_thresholds,
    rect_mask,
)


def black_spot(bbox, confidence=0.9):
    x1, y1, x2, y2 = bbox
    return det("black-spot", [x1, y1, x2, y2], confidence,
               rect_mask(x1, y1, x2, y2))


def omission_strip(bbox, confidence=0.9):
    x1, y1, x2, y2 = bbox
    return det("omission-short", [x1, y1, x2, y2], confidence,
               rect_mask(x1, y1, x2, y2))


class SpiderBlackSpotsOmissionRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def make_rule(self, disabled=None):
        thresholds = dict(self.thresholds)
        if disabled:
            thresholds["disabled_rules"] = list(disabled)
        return SpiderBlackSpotsOmissionRule(thresholds)

    def test_disabled_rule_skipped(self):
        rule = self.make_rule(disabled=["black_spots_omission"])
        result = rule.check({"SPIDER_IN": []})
        self.assertFalse(result.triggered)
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_no_detections_not_triggered(self):
        # Сначала ищем область omission; её нет -> брак не фиксируется.
        rule = self.make_rule()
        result = rule.check({"SPIDER_IN": []})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["reason"], "no_omission_region")

    def test_region_present_no_black_spots_good(self):
        rule = self.make_rule()
        result = rule.check({"SPIDER_IN": [omission_strip((0, 0, 260, 20))]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertFalse(result.triggered)
        self.assertIsNone(details["reason"])
        self.assertEqual(details["found"], 0)

    def test_spot_overlapping_region_is_bad(self):
        rule = self.make_rule()
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 260, 20)),
            black_spot((100, 5, 120, 15)),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["confirmed_hits"], 1)
        self.assertEqual(details["false_positives"], 0)
        self.assertGreater(details["hits"][0]["overlap_px"], 0)

    def test_spot_outside_region_is_false_positive(self):
        rule = self.make_rule()
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 260, 20)),
            black_spot((400, 400, 430, 430)),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["confirmed_hits"], 0)
        self.assertEqual(details["false_positives"], 1)

    def test_mixed_spots_only_overlap_triggered(self):
        rule = self.make_rule()
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 260, 20)),
            black_spot((100, 5, 120, 15)),
            black_spot((400, 400, 430, 430)),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["found"], 2)
        self.assertEqual(details["confirmed_hits"], 1)
        self.assertEqual(details["false_positives"], 1)

    def test_low_confidence_black_spot_ignored(self):
        # Порог black_spots_omission_min_confidence = 0.1, пятно ниже него.
        rule = self.make_rule()
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 260, 20)),
            black_spot((100, 5, 120, 15), confidence=0.05),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["found"], 0)

    def test_roles_both_cameras(self):
        # Одна камера годная, другая брак -> правило срабатывает в целом.
        rule = self.make_rule()
        result = rule.check({
            "SPIDER_IN": [
                omission_strip((0, 0, 260, 20)),
                black_spot((100, 5, 120, 15)),
            ],
            "SPIDER_OUT": [
                omission_strip((0, 0, 260, 20)),
                black_spot((400, 400, 430, 430)),
            ],
        })
        self.assertTrue(result.triggered)
        self.assertTrue(
            result.details["per_role"]["SPIDER_IN"]["triggered"]
        )
        self.assertFalse(
            result.details["per_role"]["SPIDER_OUT"]["triggered"]
        )

    def test_triggered_defect_is_bad_route(self):
        # Дефект black_spots_omission не входит в CLEANUP_DEFECTS -> BAD.
        from domain.part import CLEANUP_DEFECTS
        self.assertNotIn("black_spots_omission", CLEANUP_DEFECTS)
        # Регистрируется как дефект правила.
        rule = self.make_rule()
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 260, 20)),
            black_spot((100, 5, 120, 15)),
        ]})
        self.assertEqual(result.defect, "black_spots_omission")

    def test_is_independent_of_short_omission_trigger(self):
        # Правило работает независимо от short_omission: короткая полоса без
        # избытка (обычная) + пятно в ней -> брак black_spots_omission.
        from domain.defect_rules import SpiderBlackSpotsOmissionRule as BS
        short = SpiderShortOmissionRule(self.thresholds)
        omissions = [
            # полоса толщиной 10px, allowed_thickness для SPIDER_IN = 25px.
            omission_strip((0, 0, 260, 20)),
        ]
        short_result = short.check({"SPIDER_IN": omissions})
        self.assertFalse(short_result.triggered)
        rule = BS(self.thresholds)
        result = rule.check({"SPIDER_IN": omissions + [black_spot((100, 5, 120, 15))]})
        self.assertTrue(result.triggered)


if __name__ == "__main__":
    unittest.main()
