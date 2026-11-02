"""Консольное логирование результатов правил дефектов."""

import unittest

from domain.defect_rules import RuleResult
from inspection.rule_log import format_rule_result, log_rule_results


class FormatRuleResultTest(unittest.TestCase):
    def test_ok_rule(self):
        result = RuleResult("top_glass", False, details={"per_role": {
            "TOP": {"triggered": False},
        }})
        self.assertEqual(
            format_rule_result("SPIDER", result),
            "[RULES] SPIDER top_glass: OK TOP=ok",
        )

    def test_fail_rule_with_reason(self):
        result = RuleResult("top_platform", True, details={"per_role": {
            "TOP": {"triggered": True, "reason": "no_valid_platform"},
        }})
        self.assertEqual(
            format_rule_result("SPIDER", result),
            "[RULES] SPIDER top_platform: FAIL TOP=fail(no_valid_platform)",
        )

    def test_skipped_rule(self):
        result = RuleResult("sinks", False, details={"skipped": "rule disabled"})
        self.assertEqual(
            format_rule_result("SPIDER", result),
            "[RULES] SPIDER sinks: SKIP",
        )

    def test_presence_rule(self):
        result = RuleResult("part_presence", False, details={"empty_tray": True})
        self.assertEqual(
            format_rule_result("INPUT part=7", result),
            "[RULES] INPUT part=7 part_presence: OK empty_tray=True",
        )

    def test_rule_without_details(self):
        self.assertEqual(
            format_rule_result("rules", RuleResult("window_geometry", True)),
            "[RULES] rules window_geometry: FAIL",
        )

    def test_log_rule_results_prints_each_rule(self):
        import contextlib
        import io

        results = [RuleResult("a", False), RuleResult("b", True)]
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            log_rule_results("diag", results)
        lines = stream.getvalue().splitlines()
        self.assertEqual(lines, ["[RULES] diag a: OK", "[RULES] diag b: FAIL"])


if __name__ == "__main__":
    unittest.main()
