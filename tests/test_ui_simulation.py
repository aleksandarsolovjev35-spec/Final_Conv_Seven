"""Standalone-симулятор UI (ui_simulation.LineSimulation).

Модель линии проверяется без потоков (публичный API и внутренние шаги)
и с потоком: полный производственный шаг с нулевыми таймингами,
остановка с дренажом очереди и закрытие.
"""

from __future__ import annotations

import time
import unittest

from ui_simulation import (
    LineSimulation,
    SimPart,
    configure_simulated_thresholds,
    demo_frames,
)
from vision.ui.server.server import UIServer

ORIGINAL_TIMINGS = {
    name: getattr(LineSimulation, name)
    for name in (
        "ROUTE_PREPARE_SECONDS", "STEP_SECONDS", "SETTLE_SECONDS",
        "POST_STOP_SECONDS", "CAMERA_STAGE_SECONDS", "REVIEW_SECONDS",
    )
}


class SimulationApiTest(unittest.TestCase):
    def setUp(self):
        self.server = UIServer()
        self.sim = LineSimulation(self.server)

    def test_initial_state(self):
        self.assertEqual(self.sim.state, "IDLE")
        self.assertEqual(self.sim.step, 0)
        self.assertEqual(self.sim.counts["total"], 0)
        self.assertEqual(self.sim.last_distributor_action, "SIMULATION READY")

    def test_start_stop(self):
        self.assertTrue(self.sim.start())
        self.assertEqual(self.sim.state, "RUNNING")
        self.assertFalse(self.sim.start())
        self.assertTrue(self.sim.stop())
        self.assertEqual(self.sim.state, "STOPPING")
        # Повторный stop в STOPPING — идемпотентно.
        self.assertTrue(self.sim.stop())
        # Запуск поверх остановленного состояния снова возможен.
        with self.sim._lock:
            self.sim.state = "STOPPED"
        self.assertTrue(self.sim.start())

    def test_pause_resume(self):
        self.assertFalse(self.sim.pause())
        self.sim.start()
        self.assertTrue(self.sim.pause())
        self.assertEqual(self.sim.state, "PAUSED")
        self.assertFalse(self.sim.pause())
        self.assertTrue(self.sim.resume())
        self.assertEqual(self.sim.state, "RUNNING")
        self.sim.close()

    def test_jog_flow(self):
        self.assertFalse(self.sim.jog_hold_start("+"))
        self.assertTrue(self.sim.enter_jog())
        self.assertTrue(self.sim.jog_active)
        self.assertFalse(self.sim.enter_jog() is False)  # повторный вход
        self.assertTrue(self.sim.jog_hold_start("+"))
        self.assertEqual(self.sim.dist1_position, 5)
        self.assertTrue(self.sim.jog_hold_start("-"))
        self.assertEqual(self.sim.dist1_position, 0)
        self.assertTrue(self.sim.jog_hold_release())
        self.assertFalse(self.sim.jog_busy)
        self.assertTrue(self.sim.exit_jog())
        self.assertFalse(self.sim.jog_active)

    def test_jog_bounded_position(self):
        self.sim.enter_jog()
        for _ in range(100):
            self.sim.jog_hold_start("+")
        self.assertEqual(self.sim.dist1_position, 340)
        self.sim.exit_jog()

    def test_selected_analysis(self):
        self.assertFalse(self.sim.selected_analysis("NOPE"))
        self.assertTrue(self.sim.selected_analysis("TOP"))
        self.assertEqual(self.sim.selected_role, "TOP")
        # Другая роль в IDLE просто переназначает выбор.
        self.assertTrue(self.sim.selected_analysis("INPUT_LEFT"))
        self.assertEqual(self.sim.selected_role, "INPUT_LEFT")
        self.assertTrue(self.sim.release_selected_analysis())
        self.assertIsNone(self.sim.selected_role)

    def test_diagnostics(self):
        self.assertTrue(self.sim.distributor_diagnostic("DIST1_HOME"))
        self.assertTrue(self.sim.camera_diagnostic())
        self.assertTrue(self.sim.vision_rule_diagnostic())

    def test_close(self):
        self.assertTrue(self.sim.close())
        self.assertTrue(self.sim._stop.is_set())

    def test_new_part_empty_tray(self):
        part = self.sim._new_part()
        self.assertIsNotNone(part)
        saw_empty = False
        for _ in range(8):
            if self.sim._new_part() is None:
                saw_empty = True
        self.assertTrue(saw_empty)
        self.assertEqual(self.sim.empty_count, 1)

    def test_line_parts_with_egress(self):
        part = SimPart(1, position=7)
        self.sim.parts = [SimPart(2, position=0)]
        self.sim.egress = part
        line = self.sim._line_parts()
        self.assertEqual(len(line), 2)
        dropping = [item for item in line if item["dropping"]]
        self.assertEqual(len(dropping), 1)
        self.assertEqual(dropping[0]["position"], 7)

    def test_prepare_and_settle_distributor(self):
        part = SimPart(1, position=7, category="CLEANUP")
        self.sim.parts = [part]
        self.sim._prepare_distributor()
        self.assertEqual(self.sim._planned_route, "CLEANUP")
        self.assertEqual(self.sim.dist2_state, "MOVING")
        self.sim._settle_distributor()
        self.assertEqual(self.sim.dist1_position, 340)
        self.assertEqual(self.sim.dist2_position, 340)
        self.assertEqual(self.sim.dist2_state, "READY")

    def test_virtual_overlay_data(self):
        line = [{"id": 1, "position": 4, "category": "BAD", "dropping": False}]
        raw, rules = self.sim._virtual_overlay_data(["TOP"], line)
        self.assertEqual(raw["TOP"][0]["class"], "case")
        self.assertTrue(rules[0].drawings[0]["triggered"])
        line = [{"id": 1, "position": 4, "category": "CLEANUP", "dropping": False}]
        raw, rules = self.sim._virtual_overlay_data(["TOP"], line)
        self.assertEqual(raw["TOP"][0]["class"], "glass")

    def test_frame_analysis_payload(self):
        self.assertFalse(self.sim._frame_analysis_payload()["available"])
        self.sim.selected_role = "TOP"
        payload = self.sim._frame_analysis_payload()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["kind"], "selected")
        self.sim.parts = [SimPart(1, position=4, defects=["X"])]
        payload = self.sim._frame_analysis_payload()
        self.assertTrue(payload["rules"][1]["triggered"])

    def test_frame_analysis_follows_stage(self):
        # ВХОД: выбранная входная камера и корпус на +0.
        self.server.active_camera_role = "INPUT_LEFT"
        self.sim.parts = [SimPart(1, position=0)]
        payload = self.sim._frame_analysis_payload()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["kind"], "production")
        self.assertEqual(payload["stage"], "ВХОД")
        self.assertEqual(payload["role"], "INPUT_LEFT")
        self.assertEqual(payload["part_id"], 1)
        self.assertFalse(payload["rules"][1]["triggered"])
        # КОНТРОЛЬ +4: корпус прошёл контроль, замеры с вердиктом.
        self.server.active_camera_role = "TOP"
        inspected = SimPart(1, position=4, defects=["СИМУЛИРОВАННЫЙ ДЕФЕКТ ГЕОМЕТРИИ"], inspected=True)
        self.sim.parts = [inspected]
        payload = self.sim._frame_analysis_payload()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["stage"], "КОНТРОЛЬ +4")
        self.assertEqual(payload["role"], "TOP")
        self.assertTrue(payload["rules"][1]["triggered"])
        # Пустая линия — панель закрыта.
        self.sim.parts = []
        self.assertFalse(self.sim._frame_analysis_payload()["available"])

    def test_publish_updates_server(self):
        self.sim.start()
        self.sim._publish("MOTION")
        status = self.server.line_status
        self.assertEqual(status["state"], "RUNNING")
        self.assertEqual(status["process"]["phase"], "MOTION")
        self.assertEqual(status["controls"]["stop"], True)
        self.assertIn("TOP", self.server.frames)
        self.sim.close()

    def test_inspect_part(self):
        part = SimPart(1)
        self.sim._inspect_part(part)
        self.assertEqual(part.category, "GOOD")
        self.assertTrue(part.inspected)
        self.assertEqual(part.defects, [])
        part = SimPart(2)
        self.sim._inspect_part(part)
        self.assertEqual(part.category, "BAD")
        self.assertEqual(part.defects, ["СИМУЛИРОВАННЫЙ ДЕФЕКТ ГЕОМЕТРИИ"])

    def test_finish_egress(self):
        part = SimPart(1, category="BAD", defects=["X"])
        self.sim.egress = part
        self.sim._finish_egress()
        self.assertEqual(self.sim.counts["bad"], 1)
        self.assertIsNone(self.sim.egress)
        self.assertEqual(self.sim.recent[0]["id"], 1)

    def test_open_next_archive_batch(self):
        self.sim.server.archive = None
        self.sim._open_next_archive_batch()  # не падает
        self.sim.archive_compressed = False
        self.sim._open_next_archive_batch()

    def test_finalize_archive_batch_without_archive(self):
        self.sim.server.archive = None
        self.sim._finalize_archive_batch()
        self.assertFalse(self.sim.archive_compressed)


class DemoFramesTest(unittest.TestCase):
    def test_demo_frames_shape(self):
        frames = demo_frames(step=3, phase="MOTION")
        self.assertEqual(set(frames), {
            "INPUT_LEFT", "INPUT_RIGHT", "SPIDER_LEFT", "SPIDER_RIGHT",
            "SPIDER_IN", "SPIDER_OUT", "TOP",
        })
        for frame in frames.values():
            self.assertEqual(frame.shape, (480, 800, 3))

    def test_demo_frames_default(self):
        frames = demo_frames()
        self.assertEqual(len(frames), 7)


class ConfigureThresholdsTest(unittest.TestCase):
    def test_configure_simulated_thresholds(self):
        server = UIServer()
        configure_simulated_thresholds(server)
        self.assertIsNotNone(server.thresholds)
        self.assertGreater(server.thresholds_revision, 0)
        updated = server.on_thresholds_apply(
            "TOP", {"top_contacts_min_confidence": 0.55}, {},
        )
        self.assertEqual(
            updated["TOP.top_contacts_min_confidence"], 0.55,
        )

    def test_apply_unknown_threshold_raises(self):
        server = UIServer()
        configure_simulated_thresholds(server)
        with self.assertRaises(ValueError):
            server.on_thresholds_apply("TOP", {"nope": 1}, {})


class SimulationLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name, value in ORIGINAL_TIMINGS.items():
            setattr(LineSimulation, name, 0.005)

    @classmethod
    def tearDownClass(cls):
        for name, value in ORIGINAL_TIMINGS.items():
            setattr(LineSimulation, name, value)

    def setUp(self):
        self.server = UIServer()
        self.sim = LineSimulation(self.server)

    def tearDown(self):
        self.sim.close()

    def test_full_step_cycle(self):
        self.sim.thread.start()
        self.assertTrue(self.sim.start())
        deadline = time.monotonic() + 5.0
        while self.sim.step < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(self.sim.step, 1)
        self.assertTrue(self.sim.stop())
        deadline = time.monotonic() + 5.0
        while self.sim.state != "STOPPED" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.sim.state, "STOPPED")
        self.assertEqual(self.sim.parts, [])
        self.assertIsNone(self.sim.egress)
        self.sim.close()
        self.sim.thread.join(2.0)
        self.assertFalse(self.sim.thread.is_alive())

    def test_publish_reaches_server(self):
        self.sim.thread.start()
        self.sim.start()
        deadline = time.monotonic() + 5.0
        while not self.server.line_status and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn("state", self.server.line_status)
        self.sim.close()
        self.sim.thread.join(2.0)

    def test_start_revives_after_close(self):
        # ВЫХОД посреди цикла останавливает поток; повторный ПУСК
        # оживляет симуляцию, а не оставляет линию «замёрзшей».
        self.sim.thread.start()
        self.assertTrue(self.sim.start())
        deadline = time.monotonic() + 5.0
        while self.sim.step < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.sim.close()
        self.sim.thread.join(2.0)
        self.assertFalse(self.sim.thread.is_alive())
        self.assertTrue(self.sim.start())
        self.assertTrue(self.sim.thread.is_alive())
        self.assertEqual(self.sim.state, "RUNNING")
        deadline = time.monotonic() + 5.0
        while self.sim.step < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(self.sim.step, 2)
        self.sim.close()
        self.sim.thread.join(2.0)


if __name__ == "__main__":
    unittest.main()
