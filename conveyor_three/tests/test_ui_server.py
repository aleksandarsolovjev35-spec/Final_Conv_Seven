"""Контракт UIServer трёхкамерной линии без запуска оборудования."""

from __future__ import annotations

import unittest

import numpy as np

from vision.ui.server.server import (
    BOOT_STEPS,
    CAMERA_ORDER,
    NO_CACHE,
    NoCacheStaticFiles,
    UIServer,
)


class UIServerContractTest(unittest.TestCase):
    def test_three_camera_order(self):
        self.assertEqual(CAMERA_ORDER, ["NEAR", "MIDDLE", "FAR"])

    def test_boot_steps_include_camera_warmup_and_preview(self):
        keys = [key for key, _ in BOOT_STEPS]
        self.assertEqual(
            keys,
            [
                "cameras",
                "camera_warmup",
                "models_load",
                "models_warm",
                "inspection",
                "serial",
                "hardware",
                "cycle",
                "preview",
                "ready",
            ],
        )

    def test_set_camera_roles_populates_mapping(self):
        server = UIServer()
        server.set_camera_roles({"NEAR": 2, "MIDDLE": 0, "FAR": 1})
        self.assertEqual(
            server.camera_mapping,
            {"NEAR": 2, "MIDDLE": 0, "FAR": 1},
        )
        self.assertEqual(server.camera_roles, ["NEAR", "MIDDLE", "FAR"])
        self.assertEqual(server.active_camera_role, "NEAR")

    def test_no_cache_constant(self):
        self.assertIn("no-store", NO_CACHE)
        self.assertTrue(issubclass(NoCacheStaticFiles, object))

    def test_work_mode_skips_overlay_rendering(self):
        server = UIServer(debug_enabled=False)
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        rendered = server._render(frame, "NEAR", "RULES", None, None)
        # В режиме РАБОТА возвращается копия чистого кадра без отрисовки.
        self.assertIsNot(rendered, frame)
        self.assertEqual(rendered.shape, frame.shape)

    def test_debug_mode_runs_render_path(self):
        server = UIServer(debug_enabled=True)
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        rendered = server._render(frame, "NEAR", "RULES", None, None)
        self.assertEqual(rendered.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
