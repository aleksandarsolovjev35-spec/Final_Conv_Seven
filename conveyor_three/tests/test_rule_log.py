"""Консольное логирование результатов правил дефектов."""

import unittest

from domain.defect_rules import RuleResult
from inspection.rule_log import format_rule_result, log_rule_results


class FormatRuleResultTest(unittest.TestCase):
    def test_ok_rule(self):
        result = RuleResult("window_sinks", False, details={"per_role": {
            "LEFT": {"triggered": False},
        }})
        self.assertEqual(
            format_rule_result("INSPECT part=3", result),
            "[RULES] INSPECT part=3 window_sinks: OK LEFT=ok",
        )

    def test_fail_rule_with_reason(self):
        result = RuleResult("bottom_glass", True, details={"per_role": {
            "MIDDLE": {"triggered": True, "reason": "glass_found"},
        }})
        self.assertEqual(
            format_rule_result("INSPECT part=3", result),
            "[RULES] INSPECT part=3 bottom_glass: FAIL MIDDLE=fail(glass_found)",
        )

    def test_skipped_rule(self):
        result = RuleResult("welding", False, details={"skipped": "rule disabled"})
        self.assertEqual(
            format_rule_result("rules", result),
            "[RULES] rules welding: SKIP",
        )

    def test_presence_rule(self):
        result = RuleResult("part_presence", False, details={"empty_tray": True})
        self.assertEqual(
            format_rule_result("presence part=7", result),
            "[RULES] presence part=7 part_presence: OK empty_tray=True",
        )

    def test_rule_without_details(self):
        self.assertEqual(
            format_rule_result("rules", RuleResult("uneven_heights", True)),
            "[RULES] rules uneven_heights: FAIL",
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
