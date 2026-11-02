"""Маршрутизация детали по дефектам (3 камеры)."""

from __future__ import annotations

import unittest

from domain.part import (
    CATEGORY_BAD,
    CATEGORY_CLEANUP,
    CATEGORY_GOOD,
    CLEANUP_DEFECTS,
    Part,
)


class PartRoutingTest(unittest.TestCase):
    def test_good_when_no_defects(self):
        part = Part(1, 0)
        part.mark_input_done()
        self.assertEqual(part.route_category, CATEGORY_GOOD)
        self.assertEqual(part.final_decision, "none")

    def test_cleanup_defects_route_to_cleanup(self):
        for defect in CLEANUP_DEFECTS:
            part = Part(1, 0)
            part.add_input_defect(defect)
            part.mark_input_done()
            self.assertEqual(part.route_category, CATEGORY_CLEANUP, defect)
            self.assertEqual(part.final_decision, defect)

    def test_window_sinks_routes_bad(self):
        part = Part(1, 0)
        part.add_input_defect("window_sinks")
        part.mark_input_done()
        self.assertEqual(part.route_category, CATEGORY_BAD)

    def test_priority_window_sinks_over_glass(self):
        part = Part(1, 0)
        part.add_input_defect("bottom_glass")
        part.add_input_defect("window_sinks")
        part.mark_input_done()
        # Раковины имеют больший приоритет -> BAD.
        self.assertEqual(part.route_category, CATEGORY_BAD)
        self.assertEqual(part.final_decision, "window_sinks")

    def test_input_defects_compat_property(self):
        part = Part(1, 0)
        part.add_input_defect("welding")
        self.assertEqual(part.input_defects, ["welding"])
        self.assertEqual(part.get_all_defects(), ["welding"])


if __name__ == "__main__":
    unittest.main()
