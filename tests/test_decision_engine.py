"""DecisionEngine и базовые классы правил.

Проверяются: состав активных правил, фильтрация по ``disabled_rules``,
выбор правил по ролям стадии и контракт ``RuleResult`` / ``BaseRule``.
"""

from __future__ import annotations

import os
import unittest

from core.decision_engine import DecisionEngine
from domain.defect_rules import (
    BaseRule,
    InputPartPresenceRule,
    RuleResult,
)
from domain.threshold_loader import ThresholdLoader

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLDS_PATH = os.path.join(REPO_ROOT, "thresholds.json")


class RuleResultTest(unittest.TestCase):
    def test_defect_none_when_not_triggered(self):
        result = RuleResult("rule_a", False)
        self.assertIsNone(result.defect)

    def test_defect_is_rule_name_when_triggered(self):
        result = RuleResult("rule_a", True)
        self.assertEqual(result.defect, "rule_a")

    def test_repr_fail(self):
        self.assertIn("FAIL", repr(RuleResult("rule_a", True)))

    def test_repr_ok(self):
        self.assertIn("OK", repr(RuleResult("rule_a", False)))

    def test_default_details_and_drawings(self):
        result = RuleResult("rule_a", False)
        self.assertEqual(result.details, {})
        self.assertEqual(result.drawings, [])


class BaseRuleTest(unittest.TestCase):
    class StubRule(BaseRule):
        name = "stub_rule"

        def check(self, vision_results, **kwargs):
            return RuleResult(self.name, True)

    def test_enabled_by_default(self):
        rule = self.StubRule({})
        self.assertTrue(rule.enabled)

    def test_disabled_via_thresholds(self):
        rule = self.StubRule({"disabled_rules": ["stub_rule"]})
        self.assertFalse(rule.enabled)

    def test_check_raises_not_implemented(self):
        class BareRule(BaseRule):
            name = "bare"

        with self.assertRaises(NotImplementedError):
            BareRule({}).check({})

    def test_get_falls_back_to_default(self):
        rule = self.StubRule({})
        self.assertEqual(rule._get("missing", 42), 42)

    def test_get_common_threshold(self):
        rule = self.StubRule({"key": 10})
        self.assertEqual(rule._get("key", 0), 10)

    def test_get_per_role_wins(self):
        rule = self.StubRule({
            "key": 10,
            "ROLE.key": 5,
        })
        self.assertEqual(rule._get("key", 0, role="ROLE"), 5)

    def test_get_per_role_missing_uses_common(self):
        rule = self.StubRule({"key": 10})
        self.assertEqual(rule._get("key", 0, role="ROLE"), 10)

    def test_make_skip(self):
        result = self.StubRule._make_skip("some_rule")
        self.assertEqual(result.rule_name, "some_rule")
        self.assertFalse(result.triggered)
        self.assertEqual(result.details, {"skipped": "rule disabled"})


class DecisionEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.thresholds = ThresholdLoader(THRESHOLDS_PATH).get_all()

    def test_constructs_with_real_thresholds(self):
        engine = DecisionEngine(thresholds=self.thresholds)
        names = {rule.name for rule in engine.rules}
        self.assertIn("top_contacts", names)
        self.assertIn("contacts_long", names)
        self.assertIn("window_geometry", names)

    def test_constructs_without_thresholds(self):
        engine = DecisionEngine()
        self.assertGreater(len(engine.rules), 0)

    def test_disabled_rules_are_filtered(self):
        thresholds = dict(self.thresholds)
        thresholds["disabled_rules"] = ["top_glass", "sinks"]
        engine = DecisionEngine(thresholds=thresholds)
        names = {rule.name for rule in engine.rules}
        self.assertNotIn("top_glass", names)
        self.assertNotIn("sinks", names)
        self.assertIn("top_contacts", names)

    def test_no_active_rules_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["disabled_rules"] = [
            "window_geometry", "window_sinks",
            "contacts_long", "long_omission", "contacts_short",
            "short_omission", "top_contacts", "top_platform", "sinks",
            "glass", "glass_on_contacts",
            "platform_contacts_overlap",
        ]
        with self.assertRaisesRegex(RuntimeError, "No active defect rules"):
            DecisionEngine(thresholds=thresholds)

    def test_rules_for_roles(self):
        engine = DecisionEngine(thresholds=self.thresholds)
        spider = engine.rules_for_roles(("SPIDER_LEFT",))
        names = {rule.name for rule in spider}
        self.assertIn("contacts_long", names)
        self.assertNotIn("top_contacts", names)
        self.assertNotIn("window_geometry", names)

    def test_rules_for_role_single(self):
        engine = DecisionEngine(thresholds=self.thresholds)
        top = engine.rules_for_role("TOP")
        self.assertEqual({rule.name for rule in top}, {
            "top_contacts", "top_platform", "sinks", "glass",
            "glass_on_contacts", "platform_contacts_overlap",
        })

    def test_rules_for_roles_empty(self):
        engine = DecisionEngine(thresholds=self.thresholds)
        self.assertEqual(engine.rules_for_roles(()), [])
        self.assertEqual(engine.rules_for_roles(None), [])

    def test_evaluate_empty_results(self):
        engine = DecisionEngine(thresholds=self.thresholds)
        self.assertEqual(engine.evaluate_rules_detailed(engine.rules, {}), [])

    def test_evaluate_detailed_returns_rule_results(self):
        engine = DecisionEngine(thresholds=self.thresholds)
        results = engine.evaluate_all_detailed({"TOP": []})
        self.assertIsInstance(results, list)
        self.assertTrue(all(isinstance(r, RuleResult) for r in results))

    def test_evaluate_passes_frames_kwarg(self):
        engine = DecisionEngine(thresholds=self.thresholds)

        class ProbeRule(BaseRule):
            name = "probe"

            def check(self, vision_results, **kwargs):
                return RuleResult("probe", kwargs.get("frames") is not None)

        result = engine.evaluate_rules_detailed(
            [ProbeRule(self.thresholds)], {"TOP": []}, frames={"TOP": object()},
        )[0]
        self.assertTrue(result.triggered)


class InputPartPresenceRuleTest(unittest.TestCase):
    def setUp(self):
        self.thresholds = ThresholdLoader(THRESHOLDS_PATH).get_all()

    def flatness(self, confidence=0.9):
        return {"class": "flatness", "confidence": confidence}

    def make_rule(self, thresholds=None):
        return InputPartPresenceRule(thresholds or self.thresholds)

    def test_empty_vision_is_empty_tray(self):
        result = self.make_rule().check({
            "INPUT_LEFT": [],
            "INPUT_RIGHT": [],
        })
        self.assertFalse(result.triggered)
        self.assertTrue(result.details["empty_tray"])

    def test_present_on_both_roles(self):
        result = self.make_rule().check({
            "INPUT_LEFT": [self.flatness(), self.flatness(), self.flatness()],
            "INPUT_RIGHT": [self.flatness(), self.flatness(), self.flatness()],
        })
        self.assertFalse(result.triggered)
        self.assertFalse(result.details["empty_tray"])
        self.assertEqual(result.details["flatness_left"], 3)
        self.assertEqual(result.details["flatness_right"], 3)

    def test_low_confidence_detections_ignored(self):
        result = self.make_rule().check({
            "INPUT_LEFT": [self.flatness(0.1)],
            "INPUT_RIGHT": [self.flatness(0.9), self.flatness(0.9)],
        })
        self.assertTrue(result.details["empty_tray"])
        self.assertEqual(result.details["flatness_left"], 0)

    def test_false_positive_budget(self):
        result = self.make_rule().check({
            "INPUT_LEFT": [self.flatness(), self.flatness()],
            "INPUT_RIGHT": [self.flatness(), self.flatness()],
        })
        self.assertTrue(result.details["empty_tray"])
        self.assertEqual(result.details["false_positive_ignored_left"], 2)
        self.assertEqual(result.details["effective_flatness_left"], 0)

    def test_other_classes_ignored(self):
        result = self.make_rule().check({
            "INPUT_LEFT": [{"class": "objects", "confidence": 0.9}],
            "INPUT_RIGHT": [self.flatness()],
        })
        self.assertTrue(result.details["empty_tray"])

    def test_single_role_in_results(self):
        result = self.make_rule().check({
            "INPUT_LEFT": [self.flatness(), self.flatness(), self.flatness()],
        })
        self.assertFalse(result.details["empty_tray"])
        self.assertEqual(result.details["flatness_left"], 3)

    def test_disabled_rule_skipped(self):
        thresholds = dict(self.thresholds)
        thresholds["disabled_rules"] = ["part_presence"]
        result = self.make_rule(thresholds).check({"INPUT_LEFT": []})
        self.assertEqual(result.details, {"skipped": "rule disabled"})

    def test_invalid_confidence_threshold_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["INPUT_LEFT.input_window_geometry_min_confidence"] = 5.0
        with self.assertRaisesRegex(ValueError, "0..1"):
            self.make_rule(thresholds).check({
                "INPUT_LEFT": [],
                "INPUT_RIGHT": [],
            })

    def test_invalid_false_positive_count_raises(self):
        thresholds = dict(self.thresholds)
        thresholds["INPUT_LEFT.input_part_presence_false_positive_max_count"] = -1
        with self.assertRaisesRegex(ValueError, ">= 0"):
            self.make_rule(thresholds).check({
                "INPUT_LEFT": [],
                "INPUT_RIGHT": [],
            })

    def test_drawings_empty(self):
        result = self.make_rule().check({"INPUT_LEFT": [], "INPUT_RIGHT": []})
        self.assertEqual(result.drawings, [])


if __name__ == "__main__":
    unittest.main()
