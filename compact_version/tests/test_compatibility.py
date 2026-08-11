from __future__ import annotations

import unittest

from conveyor_compact.compatibility import MANIFEST
from conveyor_compact.production.stages import StepStage


class CompatibilityTests(unittest.TestCase):
    def test_fixed_contract_sizes(self):
        self.assertEqual(7, len(MANIFEST.camera_roles))
        self.assertEqual(13, len(MANIFEST.production_rules))
        self.assertEqual(4, len(MANIFEST.config_files))
        self.assertEqual(29, len(MANIFEST.api_routes))

    def test_safety_critical_routes_are_present(self):
        routes = {(route.method, route.path) for route in MANIFEST.api_routes}
        self.assertIn(("POST", "/api/stop"), routes)
        self.assertIn(("POST", "/api/exit"), routes)
        self.assertIn(("POST", "/api/jog/hold/release"), routes)

    def test_manifest_stages_match_runtime_enum(self):
        runtime_stages = tuple(stage.value for stage in StepStage if stage is not StepStage.IDLE)
        self.assertEqual(MANIFEST.step_stages, runtime_stages)


if __name__ == "__main__":
    unittest.main()
