"""Правила боковых камер: длинные/короткие контакты и полосы пропуска.

Проверяются: fail-closed при отсутствии детекций, контроль количества
контактов, вписывание эталонных прямоугольников, проверка «дымоход-
заслонка» по опорной линии omission и граница допустимой толщины полосы.
"""

from __future__ import annotations

import unittest

from domain.defect_rules import (
    SpiderContactsLongRule,
    SpiderContactsShortRule,
    SpiderLongOmissionRule,
    SpiderShortOmissionRule,
)
from helpers_defects import (
    det,
    load_thresholds,
    rect_mask,
)


def make_rule(rule_class, thresholds, disabled=None):
    thresholds = dict(thresholds)
    if disabled:
        thresholds["disabled_rules"] = list(disabled)
    return rule_class(thresholds)


def omission_strip(bbox, class_name="omission-long", confidence=0.9):
    x1, y1, x2, y2 = bbox
    return det(class_name, [x1, y1, x2, y2], confidence,
               rect_mask(x1, y1, x2, y2))


def long_contacts_row(omission_top=0):
    """5 контактов 40x20 на одной высоте под полосой omission."""
    contacts = []
    for cx in (30, 80, 130, 180, 230):
        mask = rect_mask(cx - 20, 60, cx + 20, 80)
        contacts.append(det(
            "contacts-long", [cx - 20, 60, cx + 20, 80], 0.9, mask,
        ))
    return contacts


class SpiderContactsLongRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            SpiderContactsLongRule, self.thresholds,
            disabled=["contacts_long"],
        )
        result = rule.check({"SPIDER_LEFT": []})
        self.assertFalse(result.triggered)
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_wrong_count(self):
        rule = SpiderContactsLongRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": []})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "wrong_count: 0/5")

    def test_four_contacts_wrong_count(self):
        rule = SpiderContactsLongRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": long_contacts_row()[:4]})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "wrong_count: 4/5")

    def test_invalid_contact_masks_triggered(self):
        contacts = long_contacts_row()
        contacts[2] = det("contacts-long", [110, 60, 150, 80], 0.9)
        rule = SpiderContactsLongRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": contacts})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "invalid_contact_masks")
        self.assertEqual(details["invalid_mask_indices"], [3])

    def test_good_row_with_omission_not_triggered(self):
        detections = [omission_strip((0, 0, 260, 18))]
        detections.extend(long_contacts_row())
        rule = SpiderContactsLongRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": detections})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertFalse(result.triggered, details)
        self.assertIsNone(details["reason"])
        self.assertEqual(details["found"], 5)
        self.assertFalse(details["damper_fail"])
        self.assertFalse(details["inscribe_fail"])

    def test_dropped_contact_triggered(self):
        # Один контакт опущен на 20px -> заслонка открыта.
        detections = [omission_strip((0, 0, 260, 18))]
        contacts = long_contacts_row()
        contacts[2] = det(
            "contacts-long", [110, 80, 150, 100], 0.9,
            rect_mask(110, 80, 150, 100),
        )
        detections.extend(contacts)
        rule = SpiderContactsLongRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": detections})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertTrue(details["damper_fail"])
        self.assertGreater(details["damper_open_px"], 6.0)

    def test_missing_omission_triggered(self):
        rule = SpiderContactsLongRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": long_contacts_row()})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_valid_omission_top_line")

    def test_small_contacts_inscribe_fail(self):
        detections = [omission_strip((0, 0, 260, 18))]
        contacts = [
            det(
                "contacts-long", [cx - 10, 60, cx + 10, 80], 0.9,
                rect_mask(cx - 10, 60, cx + 10, 80),
            )
            for cx in (30, 80, 130, 180, 230)
        ]
        detections.extend(contacts)
        rule = SpiderContactsLongRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": detections})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertTrue(details["inscribe_fail"])

    def test_invalid_expected_count_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["SPIDER_LEFT.spider_contacts_long_expected_count"] = 1
        rule = SpiderContactsLongRule(thresholds)
        with self.assertRaisesRegex(ValueError, ">= 2"):
            rule.check({"SPIDER_LEFT": []})

    def test_non_positive_damper_threshold_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["SPIDER_LEFT.spider_contacts_long_damper_open_max_px"] = 0
        rule = SpiderContactsLongRule(thresholds)
        with self.assertRaisesRegex(ValueError, "> 0"):
            rule.check({"SPIDER_LEFT": []})


class SpiderLongOmissionRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            SpiderLongOmissionRule, self.thresholds,
            disabled=["long_omission"],
        )
        result = rule.check({"SPIDER_LEFT": []})
        self.assertFalse(result.triggered)
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_fail_closed(self):
        rule = SpiderLongOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": []})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_detections")
        self.assertFalse(details["valid"])

    def test_invalid_mask_fail_closed(self):
        rule = SpiderLongOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": [
            det("omission-long", [0, 0, 50, 10], 0.9),
        ]})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "missing_or_invalid_mask")

    def test_thin_strip_not_triggered(self):
        # Толщина 18px <= allowed 20.5px.
        rule = SpiderLongOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": [
            omission_strip((0, 0, 200, 18)),
        ]})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertFalse(result.triggered, details)
        self.assertTrue(details["valid"])
        self.assertEqual(details["confirmed_components"], 0)

    def test_thick_strip_triggered(self):
        # Толщина 40px > allowed 20.5px.
        rule = SpiderLongOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": [
            omission_strip((0, 0, 200, 40)),
        ]})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["confirmed_components"], 1)
        self.assertGreater(details["max_excess_depth_px"], 0.0)
        self.assertGreaterEqual(details["max_consecutive_columns"], 1)

    def test_slanted_strip_with_excess_triggered(self):
        # Наклонная полоса: слева 10px, справа 60px — правый край вне допуска.
        mask = [
            [0, 0], [200, 0], [200, 60], [0, 10],
        ]
        rule = SpiderLongOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_LEFT": [
            det("omission-long", [0, 0, 200, 60], 0.9, mask),
        ]})
        details = result.details["per_role"]["SPIDER_LEFT"]
        self.assertTrue(result.triggered)
        self.assertTrue(details["valid"])

    def test_missing_config_key_raises(self):
        thresholds = dict(self.thresholds)
        del thresholds["SPIDER_LEFT.spider_long_omission_allowed_thickness_px"]
        rule = SpiderLongOmissionRule(thresholds)
        with self.assertRaisesRegex(ValueError, "Отсутствуют параметры"):
            rule.check({"SPIDER_LEFT": []})


class SpiderContactsShortRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def short_contacts(self):
        # 2 контакта 40x20, ожидается ровно 2.
        return [
            det("flatness_short", [30, 60, 70, 80], 0.9,
                rect_mask(30, 60, 70, 80)),
            det("flatness_short", [130, 60, 170, 80], 0.9,
                rect_mask(130, 60, 170, 80)),
        ]

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            SpiderContactsShortRule, self.thresholds,
            disabled=["contacts_short"],
        )
        result = rule.check({"SPIDER_IN": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_wrong_count(self):
        rule = SpiderContactsShortRule(self.thresholds)
        result = rule.check({"SPIDER_IN": []})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "wrong_count: 0/2")

    def test_single_contact_wrong_count(self):
        rule = SpiderContactsShortRule(self.thresholds)
        result = rule.check({"SPIDER_IN": self.short_contacts()[:1]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "wrong_count: 1/2")

    def test_good_pair_not_triggered(self):
        detections = [omission_strip(
            (0, 0, 200, 18), class_name="omission-short", confidence=0.9,
        )]
        detections.extend(self.short_contacts())
        rule = SpiderContactsShortRule(self.thresholds)
        result = rule.check({"SPIDER_IN": detections})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertFalse(result.triggered, details)
        self.assertEqual(details["found"], 2)

    def test_short_contact_below_area_threshold_triggered(self):
        # Площадь 20*20=400 — ровно минимальная; берём меньше.
        small = det("flatness_short", [30, 60, 50, 80], 0.9,
                    rect_mask(30, 60, 50, 80))
        rule = SpiderContactsShortRule(self.thresholds)
        result = rule.check({"SPIDER_IN": [small]})
        self.assertTrue(result.triggered)


class SpiderShortOmissionRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = load_thresholds()

    def test_disabled_rule_skipped(self):
        rule = make_rule(
            SpiderShortOmissionRule, self.thresholds,
            disabled=["short_omission"],
        )
        result = rule.check({"SPIDER_IN": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_empty_detections_fail_closed(self):
        rule = SpiderShortOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_IN": []})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_detections")

    def test_thin_strip_not_triggered(self):
        # allowed для короткой стороны 25px; полоса 15px.
        rule = SpiderShortOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 200, 15), class_name="omission-short"),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertFalse(result.triggered, details)
        self.assertTrue(details["valid"])

    def test_thick_strip_triggered(self):
        rule = SpiderShortOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 200, 50), class_name="omission-short"),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["confirmed_components"], 1)

    def test_too_small_mask_fail_closed(self):
        rule = SpiderShortOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 2, 2), class_name="omission-short"),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "mask_too_small")

    def test_top_line_not_fitted_fail_closed(self):
        rule = SpiderShortOmissionRule(self.thresholds)
        result = rule.check({"SPIDER_IN": [
            omission_strip((0, 0, 3, 3), class_name="omission-short"),
        ]})
        details = result.details["per_role"]["SPIDER_IN"]
        self.assertTrue(result.triggered)
        self.assertEqual(details["reason"], "no_valid_top_line")


if __name__ == "__main__":
    unittest.main()
