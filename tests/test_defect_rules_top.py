"""Правила верхней камеры: контакты, платформа, раковины, стекло, заплыв.

Синтетические маски строят раскладку 5L+5R+2T+2B вокруг платформы и
проверяют как «годную» сцену, так и каждый класс дефекта.
"""

from __future__ import annotations

import unittest

from domain.defect_rules import (
    TopContactsRule,
    TopGlassOnContactsRule,
    TopGlassRule,
    TopPlatformOverlapRule,
    TopPlatformRule,
    TopSinksRule,
)
from helpers_defects import (
    contacts_layout,
    det,
    glass_context_detections,
    load_thresholds,
    rect_mask,
)

PLATFORM_BBOX = (120, 120, 280, 200)


def make_rule(rule_class, thresholds, disabled=None):
    thresholds = dict(thresholds)
    if disabled:
        thresholds["disabled_rules"] = list(disabled)
    return rule_class(thresholds)


class TopPlatformRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def platform(self, bbox=(40, 40, 360, 280), confidence=0.9):
        x1, y1, x2, y2 = bbox
        return det("platform", list(bbox), confidence,
                   rect_mask(x1, y1, x2, y2))

    def test_disabled_rule_skipped(self):
        rule = make_rule(TopPlatformRule, self.thresholds, disabled=["top_platform"])
        result = rule.check({"TOP": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_fail_closed(self):
        rule = TopPlatformRule(self.thresholds)
        result = rule.check({"TOP": []})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_valid_platform")

    def test_low_confidence_platform_ignored(self):
        rule = TopPlatformRule(self.thresholds)
        result = rule.check({"TOP": [self.platform(confidence=0.1)]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_valid_platform")

    def test_large_platform_fits(self):
        # Платформа 320x240 вмещает эталон 270x130.
        rule = TopPlatformRule(self.thresholds)
        result = rule.check({"TOP": [self.platform((40, 40, 360, 280))]})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered, details)
        self.assertIsNone(details["reason"])
        self.assertTrue(details["fits"])
        self.assertTrue(details["centered"])

    def test_small_platform_not_fitted(self):
        rule = TopPlatformRule(self.thresholds)
        result = rule.check({"TOP": [self.platform((200, 200, 240, 240))]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertFalse(details["fits"])

    def test_invalid_mask_orientation(self):
        # Тонкая маска: площадь > 0, но габарит < 1px — ориентации нет.
        degenerate = det(
            "platform", [0, 0, 20, 20], 0.9,
            [[0, 0], [10, 0], [10, 0.5]],
        )
        rule = TopPlatformRule(self.thresholds)
        result = rule.check({"TOP": [degenerate]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "invalid_platform_orientation")


class TopContactsRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def platform(self, bbox=PLATFORM_BBOX):
        x1, y1, x2, y2 = bbox
        return det("platform", list(bbox), 0.9, rect_mask(x1, y1, x2, y2))

    def test_disabled_rule_skipped(self):
        rule = make_rule(TopContactsRule, self.thresholds, disabled=["top_contacts"])
        result = rule.check({"TOP": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_wrong_count(self):
        rule = TopContactsRule(self.thresholds)
        result = rule.check({"TOP": []})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "wrong_count: 0/14")

    def test_ten_contacts_wrong_count(self):
        rule = TopContactsRule(self.thresholds)
        result = rule.check({"TOP": contacts_layout(PLATFORM_BBOX)[:10]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "wrong_count: 10/14")

    def test_contacts_without_platform(self):
        rule = TopContactsRule(self.thresholds)
        result = rule.check({"TOP": contacts_layout(PLATFORM_BBOX)})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_valid_platform")

    def test_contacts_with_invalid_masks(self):
        contacts = contacts_layout(PLATFORM_BBOX)
        contacts[0] = det("contacts", [40, 100, 80, 140], 0.9)
        detections = [self.platform()] + contacts
        rule = TopContactsRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "insufficient_valid_contact_masks")

    def test_good_layout_not_triggered(self):
        detections = [self.platform()] + contacts_layout(PLATFORM_BBOX)
        rule = TopContactsRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered, details)
        self.assertIsNone(details["reason"])
        self.assertEqual(details["selected"], 14)
        self.assertEqual(details["group_counts"], {"L": 5, "R": 5, "T": 2, "B": 2})

    def test_shifted_left_group_triggered(self):
        contacts = contacts_layout(PLATFORM_BBOX)
        # Два контакта L-группы уезжают от края — разброс отступа.
        for contact in contacts[:2]:
            x1, y1, x2, y2 = contact["bbox"]
            shift = 30
            contact["bbox"] = [x1 - shift, y1, x2 - shift, y2]
            contact["mask"] = rect_mask(
                x1 - shift, y1, x2 - shift, y2,
            )
        detections = [self.platform()] + contacts
        rule = TopContactsRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertIn("L", details["failed_groups"])

    def test_invalid_expected_count_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["TOP.top_contacts_expected_count"] = 12
        rule = TopContactsRule(thresholds)
        with self.assertRaisesRegex(ValueError, "равен 14"):
            rule.check({"TOP": []})


class TopSinksRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(TopSinksRule, self.thresholds, disabled=["sinks"])
        result = rule.check({"TOP": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_no_sinks_not_triggered(self):
        rule = TopSinksRule(self.thresholds)
        result = rule.check({"TOP": glass_context_detections()})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["sinks_total"], 0)

    def test_sink_without_context_triggered(self):
        sink = det("shells", [150, 150, 180, 180], 0.9,
                   rect_mask(150, 150, 180, 180))
        rule = TopSinksRule(self.thresholds)
        result = rule.check({"TOP": [sink]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "invalid_case_central_reference")

    def test_sink_on_platform_not_triggered(self):
        # Раковина целиком на платформе — защищённая зона.
        detections = glass_context_detections()
        detections.append(det("shells", [200, 150, 230, 180], 0.9,
                              rect_mask(200, 150, 230, 180)))
        rule = TopSinksRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered, details)
        self.assertEqual(details["defect_sinks"], 0)

    def test_sink_in_central_outside_platform_triggered(self):
        # Раковина в углу central (100..120, 100..120), вне платформы и
        # контактов — дефект.
        detections = glass_context_detections()
        detections.append(det("shells", [100, 100, 115, 115], 0.9,
                              rect_mask(100, 100, 115, 115)))
        rule = TopSinksRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["defect_sinks"], 1)
        self.assertEqual(details["hits"][0]["forbidden_pixels"] > 0, True)

    def test_invalid_sink_mask_triggered(self):
        detections = glass_context_detections()
        detections.append(det("shells", [150, 150, 180, 180], 0.9))
        rule = TopSinksRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "invalid_sink_masks")


class TopGlassRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(TopGlassRule, self.thresholds, disabled=["glass"])
        result = rule.check({"TOP": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_no_glass_not_triggered(self):
        rule = TopGlassRule(self.thresholds)
        result = rule.check({"TOP": glass_context_detections()})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["glasses_total"], 0)

    def test_glass_on_ring_triggered_cleanup(self):
        detections = glass_context_detections(glasses=[(65, 65, 90, 90)])
        rule = TopGlassRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["cleanup_hits"], 1)
        self.assertEqual(details["hits"][0]["route"], "CLEANUP")

    def test_glass_on_contact_not_cleanup(self):
        # Стекло поверх левого контакта: BAD-правило, не CLEANUP.
        detections = glass_context_detections(glasses=[(35, 130, 65, 150)])
        rule = TopGlassRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered)
        self.assertEqual(details["on_contacts_indices"], [1])

    def test_glass_without_context_skipped(self):
        rule = TopGlassRule(self.thresholds)
        result = rule.check({"TOP": [
            det("glass", [0, 0, 40, 40], 0.9, rect_mask(0, 0, 40, 40)),
        ]})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered)
        self.assertTrue(details["skipped"])
        self.assertEqual(details["reason"], "reference_invalid: no_valid_platform")


class TopGlassOnContactsRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            TopGlassOnContactsRule, self.thresholds,
            disabled=["glass_on_contacts"],
        )
        result = rule.check({"TOP": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_no_glass_not_triggered(self):
        rule = TopGlassOnContactsRule(self.thresholds)
        result = rule.check({"TOP": glass_context_detections()})
        self.assertFalse(result.triggered)

    def test_glass_overlapping_contact_triggered(self):
        detections = glass_context_detections(glasses=[(35, 130, 65, 150)])
        rule = TopGlassOnContactsRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["hits"], 1)
        self.assertEqual(details["pairs"][0]["route"], "BAD")
        self.assertGreater(details["pairs"][0]["overlap_pixels"], 0)

    def test_glass_on_ring_not_triggered(self):
        detections = glass_context_detections(glasses=[(65, 65, 90, 90)])
        rule = TopGlassOnContactsRule(self.thresholds)
        result = rule.check({"TOP": detections})
        self.assertFalse(result.triggered)

    def test_invalid_context_triggered(self):
        rule = TopGlassOnContactsRule(self.thresholds)
        result = rule.check({"TOP": [
            det("glass", [0, 0, 40, 40], 0.9, rect_mask(0, 0, 40, 40)),
        ]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertTrue(details["reference_fail"])
        self.assertEqual(details["reason"], "no_valid_platform")


class TopPlatformOverlapRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def platform(self, bbox, confidence=0.9):
        x1, y1, x2, y2 = bbox
        return det("platform", list(bbox), confidence,
                   rect_mask(x1, y1, x2, y2))

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            TopPlatformOverlapRule, self.thresholds,
            disabled=["platform_contacts_overlap"],
        )
        result = rule.check({"TOP": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_fail_closed(self):
        rule = TopPlatformOverlapRule(self.thresholds)
        result = rule.check({"TOP": []})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_valid_platform")

    def test_platform_without_contacts_triggered(self):
        rule = TopPlatformOverlapRule(self.thresholds)
        result = rule.check({"TOP": [self.platform(PLATFORM_BBOX)]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "contact_boundary_not_built")

    def test_platform_inside_contacts_not_triggered(self):
        # Платформа меньше прямоугольника контактов — заплыва нет.
        detections = [self.platform((140, 140, 260, 180))]
        detections.extend(contacts_layout(PLATFORM_BBOX))
        rule = TopPlatformOverlapRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertFalse(result.triggered, details)
        self.assertEqual(details["confirmed_components"], 0)

    def test_platform_beyond_contacts_triggered(self):
        # Платформа шире прямоугольника контактов — заплыв.
        detections = [self.platform((60, 100, 340, 220))]
        detections.extend(contacts_layout(PLATFORM_BBOX))
        rule = TopPlatformOverlapRule(self.thresholds)
        result = rule.check({"TOP": detections})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertGreater(details["confirmed_components"], 0)

    def test_degenerate_platform_orientation(self):
        degenerate = det(
            "platform", [0, 0, 20, 20], 0.9,
            [[0, 0], [10, 0], [10, 0.5]],
        )
        rule = TopPlatformOverlapRule(self.thresholds)
        result = rule.check({"TOP": [degenerate]})
        details = result.details["per_role"]["TOP"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "invalid_platform_orientation")


if __name__ == "__main__":
    unittest.main()
