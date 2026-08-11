from __future__ import annotations

import unittest

from conveyor_compact.domain.part import (
    CATEGORY_BAD,
    CATEGORY_CLEANUP,
    CATEGORY_GOOD,
    CATEGORY_UNKNOWN,
    Part,
)


class PartTests(unittest.TestCase):
    def test_good_requires_both_stages(self):
        part = Part(1, 0)
        part.mark_input_done()
        self.assertEqual(CATEGORY_UNKNOWN, part.route_category)
        part.mark_spider_done()
        self.assertEqual(CATEGORY_GOOD, part.route_category)

    def test_cleanup_only_defects_use_cleanup_route(self):
        part = Part(2, 0)
        part.add_input_defect("glass")
        part.add_spider_defect("glass_glare")
        part.mark_input_done()
        part.mark_spider_done()
        self.assertEqual(CATEGORY_CLEANUP, part.route_category)
        self.assertEqual("glass_glare", part.final_decision)

    def test_regular_defect_has_priority_over_cleanup(self):
        part = Part(3, 0)
        part.add_input_defect("glass")
        part.add_spider_defect("contacts_long")
        part.mark_input_done()
        part.mark_spider_done()
        self.assertEqual(CATEGORY_BAD, part.route_category)
        self.assertEqual("contacts_long", part.final_decision)


if __name__ == "__main__":
    unittest.main()
