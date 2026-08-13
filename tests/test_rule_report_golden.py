"""Golden-master для :mod:`core.rule_report`.

Снапшот снят перед разрезанием ``core/rule_report.py`` на пакет
``core/rule_report/``: корпус синтетических RuleResult-ов покрывает все
правила и все ветки причин срабатывания. Любое расхождение с фикстурой —
либо намеренное изменение формата строк (тогда обнови фикстуру), либо
регрессия.

Обновление фикстуры после намеренного изменения формата:
    python -m tests.test_rule_report_golden
"""
import json
import os
import unittest
from types import SimpleNamespace

from core.rule_report import (
    build_rule_report_row,
    build_rule_report_rows,
    scope_rule_result_to_role,
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "rule_report_golden.json",
)


def res(name, triggered, details):
    return SimpleNamespace(rule_name=name, triggered=triggered,
                           details=details, drawings=[])


def role(name="TOP", **kw):
    return {name: kw}


CASES = [
    # --- part_presence ---
    res("part_presence", False, {"empty_tray": False,
                                 "flatness_left": 12, "flatness_right": 7,
                                 "false_positive_max_count_by_role":
                                     {"INPUT_LEFT": 3, "INPUT_RIGHT": 3}}),
    res("part_presence", True, {"empty_tray": True, "flatness_left": None,
                                "flatness_right": None}),
    # --- window_geometry ---
    res("window_geometry", True, {"per_role": role("INPUT_LEFT",
        found=5, expected_count=7, reason=None, top_limits_px=[10, 40],
        bottom_limits_px=[5, 30], ignored=2,
        items=[{"index": 1, "valid": True, "top_px": 22.3, "bottom_px": 14.1,
                "top_fail": True, "bottom_fail": False},
               {"index": 2, "valid": False}]),
        "measurement_cards": [{"role": "INPUT_LEFT", "ok": False,
                               "metrics": [{"label": "B", "key": "bottom_px_max",
                                            "value": 31, "limit": 30,
                                            "ok": False}]}],
        "role_status": [{"role": "INPUT_LEFT", "status": "ОТКЛОНЕНИЕ",
                         "reason": None}]}),
    res("window_geometry", True, {"per_role": role("INPUT_RIGHT",
        found=3, expected_count=7, reason="wrong_count")}),
    # --- window_sinks ---
    res("window_sinks", True, {"per_role": role("INPUT_LEFT", triggered=True,
        reason="invalid_window_reference_count", selected_windows=3)}),
    res("window_sinks", True, {"per_role": role("INPUT_LEFT", triggered=True,
        reason="invalid_window_masks", invalid_window_indices=[2, 5])}),
    res("window_sinks", True, {"per_role": role("INPUT_RIGHT", triggered=True,
        reason="invalid_sink_masks", invalid_sink_indices=[1])}),
    res("window_sinks", True, {"per_role": role("INPUT_LEFT", triggered=True,
        overlap_min_px=40,
        hits=[{"sink_index": 1, "window_index": 3, "overlap_px": 55}]),
        "measurement_cards": []}),
    # --- contacts_long ---
    res("contacts_long", True, {"per_role": role("SPIDER_LEFT",
        triggered=True, reason="wrong_count: found 4", found=4)}),
    res("contacts_long", True, {"per_role": role("SPIDER_LEFT",
        triggered=True, reason="invalid_contact_masks",
        invalid_mask_indices=[0, 4])}),
    res("contacts_long", True, {"per_role": role("SPIDER_LEFT", triggered=True,
        rect_width_px=38.0, rect_height_px=120.0, ignored=1,
        damper_open_px=12.4, damper_open_max_px=15.0,
        gap_dev_px=3.1, gap_dev_max_px=5.0, straight_dev_max_px=2.2,
        items=[{"index": 0, "omission_distance_px": 7.5,
                "gap_deviation_px": -2.5, "rect_fits": True},
               {"index": 1, "omission_distance_px": None,
                "gap_deviation_px": None, "rect_fits": False}])}),
    res("contacts_long", True, {"per_role": role("SPIDER_LEFT",
        triggered=True, reason="no_valid_omission_top_line",
        rect_width_px=38.0, rect_height_px=120.0)}),
    # --- contacts_short ---
    res("contacts_short", True, {"per_role": role("SPIDER_IN", triggered=True,
        reason="wrong_count: found 1", found=1, area_absolute_min_px2=900.0,
        invalid_mask_indices=[1])}),
    res("contacts_short", True, {"per_role": role("SPIDER_OUT", triggered=True,
        reason="invalid_contact_masks", invalid_mask_indices=[0])}),
    res("contacts_short", True, {"per_role": role("SPIDER_IN", triggered=True,
        area_absolute_min_px2=800.0, rect_width_px=30.0, rect_height_px=60.0,
        ignored=0, damper_open_px=4.2, damper_open_max_px=8.0,
        straight_delta_y_px=1.5,
        items=[{"index": 0, "omission_distance_px": 9.0, "top_y": 100.0,
                "bottom_y": 160.0, "height_px": 60.0, "rect_fits": True}])}),
    # --- omission ---
    res("long_omission", True, {"per_role": role("SPIDER_LEFT",
        triggered=True, reason="omission_reference_too_short")}),
    res("long_omission", True, {"per_role": role("SPIDER_LEFT", triggered=True,
        allowed_thickness_px=14.0, excess_component_min_px=300,
        top_line_actual_max_residual_px=4.1, top_line_max_residual_px=3.0,
        top_line_actual_inlier_ratio=0.92, top_line_min_inlier_ratio=0.95,
        largest_component_pixels=1200, excess_pixels=890,
        max_excess_depth_px=11.2)}),
    res("short_omission", False, {"per_role": role("SPIDER_IN", triggered=False,
        allowed_thickness_px=10.0, excess_component_min_px=200,
        top_line_actual_max_residual_px=2.1, top_line_max_residual_px=3.0,
        largest_component_pixels=45, excess_pixels=0,
        max_excess_depth_px=1.0)}),
    # --- top_contacts ---
    res("top_contacts", True, {"per_role": role(triggered=True,
        reason="wrong_count: found 12", found_raw=12)}),
    res("top_contacts", True, {"per_role": role(triggered=True,
        reason="insufficient_valid_contact_masks", found=9,
        invalid_mask_indices=[3, 7])}),
    res("top_contacts", True, {"per_role": role(triggered=True,
        reason="no_valid_platform")}),
    res("top_contacts", True, {"per_role": role(triggered=True,
        reason="invalid_platform_bbox")}),
    res("top_contacts", True, {"per_role": role(triggered=True,
        reason="layout_groups_failed",
        group_counts={"L": 5, "R": 4, "T": 2, "B": 2})}),
    res("top_contacts", True, {"per_role": role(triggered=True, ignored=2,
        group_checks={
            "L": {"median_distance_px": 12.0, "max_deviation_px": 1.4,
                  "allowed_deviation_px": 1.5},
            "R": {"median_distance_px": 11.0, "max_deviation_px": 3.1,
                  "allowed_deviation_px": 1.5},
            "T": {"median_distance_px": 9.0, "max_deviation_px": 0.5,
                  "allowed_deviation_px": 1.5},
            "B": {"median_distance_px": 10.0, "max_deviation_px": 0.9,
                  "allowed_deviation_px": 1.5}},
        items=[{"index": 0, "group": "L", "distance_px": 12.1,
                "deviation_px": 1.4, "allowed_deviation_px": 1.5,
                "rect_width_px": 28.0, "rect_height_px": 44.0,
                "rect_fits": True}])}),
    # --- top_platform ---
    res("top_platform", True, {"per_role": role(triggered=True,
        reason="no_valid_platform")}),
    res("top_platform", True, {"per_role": role(triggered=True,
        reason="invalid_platform_orientation")}),
    res("top_platform", True, {"per_role": role(triggered=True,
        placement="shifted", rect_width_px=210.0, rect_height_px=150.0,
        angle_deg=2.5, shift_distance_px=6.4)}),
    # --- platform_contacts_overlap ---
    res("platform_contacts_overlap", True, {"per_role": role(triggered=True,
        reason="no_valid_platform")}),
    res("platform_contacts_overlap", True, {"per_role": role(triggered=True,
        reason="contact_boundary_not_built",
        contact_groups={"L": 5, "R": 5, "T": 2, "B": 2})}),
    res("platform_contacts_overlap", True, {"per_role": role(triggered=True,
        boundary_width_px=200.0, boundary_height_px=140.0,
        excess_component_min_px=150, used_contacts=8,
        largest_component_pixels=340, excess_pixels=280)}),
    # --- sinks ---
    res("sinks", True, {"per_role": role(triggered=True,
        reason="invalid_sink_masks", invalid_sink_indices=[1])}),
    res("sinks", True, {"per_role": role(triggered=True,
        reason="invalid_case_central_reference", case_central_found=0)}),
    res("sinks", True, {"per_role": role(triggered=True,
        reason="no_valid_platform")}),
    res("sinks", True, {"per_role": role(triggered=True,
        reason="invalid_platform_bbox")}),
    res("sinks", True, {"per_role": role(triggered=True,
        reason="insufficient_valid_contacts", valid_contacts=10)}),
    res("sinks", True, {"per_role": role(triggered=True,
        reason="invalid_contact_layout",
        contact_group_counts={"L": 5, "R": 4, "T": 2, "B": 2})}),
    res("sinks", True, {"per_role": role(triggered=True,
        hits=[{"sink_index": 1, "forbidden_pixels": 120,
               "central_overlap_px": 30, "platform_overlap_px": 5,
               "contacts_overlap_px": 40}])}),
    # --- glass ---
    res("glass", True, {"per_role": role(triggered=True,
        hits=[{"glass_index": 1, "platform_overlap_px": 200,
               "pin_overlap_px": 100, "ring_overlap_px": 50,
               "cleanup_overlap_px": 350}])}),
    # --- glass_on_contacts ---
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="missing_glass_mask", invalid_glass_indices=[0])}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="no_valid_platform")}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="invalid_platform_bbox")}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="insufficient_valid_contacts", valid_contacts=11)}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="invalid_contact_layout",
        contact_group_counts={"L": 5, "R": 5, "T": 1, "B": 2})}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="wrong_pin_count: 13", pins_found=13)}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="missing_pin_mask", invalid_pin_indices=[4])}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="invalid_case_count: 0", case_found=0)}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="invalid_case_central_count: 2", case_central_found=2)}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="case_central_not_inside_case")}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        reason="empty_case_ring")}),
    res("glass_on_contacts", True, {"per_role": role(triggered=True,
        pairs=[{"glass_index": 1, "contact_index": 3, "overlap_pixels": 250},
               {"glass_index": 2, "contact_index": 7,
                "overlap_pixels": 180}])}),
    # --- skipped rule (нет измерения) ---
    res("window_sinks", False, {"per_role": {
        "INPUT_LEFT": {"skipped": True, "reason": "no_frame"},
        "INPUT_RIGHT": {"skipped": True, "reason": "camera_error"}}}),
    # --- правило без форматтера, просто reason ---
    res("unknown_rule", True, {"per_role": role(triggered=True,
        reason="some_failure")}),
]


def _golden_payload() -> dict:
    """Полный снимок поведения пакета на синтетическом корпусе."""
    out = {
        "rows": build_rule_report_rows(CASES),
        "scoped": build_rule_report_rows(CASES, role="INPUT_LEFT"),
    }
    for i, case in enumerate(CASES):
        out[f"row_{i}"] = build_rule_report_row(case)
        out[f"scope_{i}"] = scope_rule_result_to_role(case, "INPUT_LEFT")
    return out


def _serialize(payload: dict) -> str:
    return json.dumps(
        payload, ensure_ascii=False, indent=1, sort_keys=True, default=str,
    ) + "\n"


class RuleReportGoldenTest(unittest.TestCase):

    def test_output_matches_snapshot(self):
        actual = _serialize(_golden_payload())
        with open(FIXTURE, encoding="utf-8") as f:
            expected = f.read()
        if actual != expected:
            dump = os.path.join(
                os.path.dirname(FIXTURE), "rule_report_golden.actual.json",
            )
            with open(dump, "w", encoding="utf-8") as f:
                f.write(actual)
            self.fail(
                "Вывод расходится с фикстурой " + FIXTURE
                + "; актуальный вывод сохранён в " + dump
            )

    def test_every_detailed_rule_has_formatter(self):
        from core.rule_report.constants import DETAILED_RULES
        from core.rule_report.details import _DETAIL_FORMATTERS
        self.assertEqual(set(DETAILED_RULES), set(_DETAIL_FORMATTERS))

    def test_row_shape(self):
        row = build_rule_report_row(
            res("contacts_long", True, {"per_role": role(
                "SPIDER_LEFT", triggered=True, reason="wrong_count: found 4",
                found=4)})
        )
        for key in (
            "name", "triggered", "skipped", "status_label", "detail",
            "human_cause", "detail_lines", "summary_lines", "summary_cards",
            "measurement_cards", "role_status", "threshold_breaches",
            "threshold_conclusion", "part_absent", "decisive",
        ):
            self.assertIn(key, row)


if __name__ == "__main__":
    # Регенерация фикстуры при намеренном изменении формата строк.
    with open(FIXTURE, "w", encoding="utf-8") as f:
        f.write(_serialize(_golden_payload()))
    print("fixture regenerated:", FIXTURE)
