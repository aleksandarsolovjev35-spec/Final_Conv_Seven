"""Поведенческая проверка ProductionCycle после разбиения на части."""

from __future__ import annotations

import threading
import time
import unittest

from core.production_cycle import ProductionCycle
from core.state_machine import State
from core.step_stages import StepSequencer
from domain.part import CATEGORY_BAD, CATEGORY_GOOD, Part
from inspection.result import InspectionResult


class FakeLive:
    def __init__(self):
        self.events = []
        self.error = None
        self._running = False

    def pause(self, timeout=5.0):
        self.events.append("pause_all")
        return True

    def resume(self):
        self.events.append("resume_all")

    def clear_overlays(self):
        self.events.append("clear")

    def start(self):
        self._running = True
        return True

    def stop(self):
        self._running = False

    def reset_pause(self):
        self.events.append("reset")

    @property
    def running(self):
        return self._running

    @property
    def fps(self):
        return 0.0


class FakeConveyor:
    speed = 20000

    def __init__(self, log):
        self.log = log

    def move_step(self):
        self.log.append("move")

    def wait_stop(self, progress_callback=None):
        self.log.append("wait_stop")

    def emergency_stop(self):
        self.log.append("e_stop")


class FakeCameras:
    mapping = {
        "INPUT_LEFT": 0, "INPUT_RIGHT": 1,
        "SPIDER_LEFT": 2, "SPIDER_RIGHT": 3,
        "SPIDER_IN": 4, "SPIDER_OUT": 5, "TOP": 6,
    }

    def __init__(self, log):
        self.log = log

    def drain_buffers(self, roles=None):
        self.log.append(("drain", tuple(roles or self.mapping)))

    def capture_roles(self, roles):
        self.log.append(("capture", tuple(roles)))
        return {role: object() for role in roles}

    def capture_single(self, role):
        return self.capture_roles((role,))[role]

    def capture_all(self):
        return self.capture_roles(tuple(self.mapping))


class FakeInspector:
    INPUT_ROLES = ("INPUT_LEFT", "INPUT_RIGHT")
    SPIDER_ROLES = (
        "SPIDER_LEFT", "SPIDER_RIGHT", "SPIDER_IN", "SPIDER_OUT", "TOP",
    )

    def __init__(self, log, empty=False, fail=False):
        self.log = log
        self.empty = empty
        self.fail = fail

    def set_progress_callback(self, callback):
        self.on_progress = callback

    def inspect_input(self, part_id, step, frames):
        self.log.append(("input", tuple(frames), part_id, step))
        if self.fail:
            raise RuntimeError("inspect failed")
        return InspectionResult(
            stage="input",
            defects=[],
            vision_results={role: [] for role in frames},
            raw_frames=frames,
            is_empty_tray=self.empty,
        )

    def inspect_spider(self, part_id, step, frames):
        self.log.append(("spider", tuple(frames), part_id, step))
        return InspectionResult(
            stage="spider",
            defects=[],
            vision_results={role: [] for role in frames},
            raw_frames=frames,
        )


class FakeDistributor:
    dist1_open_position = 340

    def __init__(self, log):
        self.log = log
        self.on_state_changed = None
        self.cancel_check = None
        self.status = {
            "dist1_position": 0, "dist1_max": 340, "dist1_state": "GOOD",
            "dist2_position": 0, "dist2_max": 340, "dist2_state": "IDLE",
            "dist2_target": "BAD", "last_distributor_action": "-",
        }

    def park_production(self):
        self.log.append("park")

    def prepare_route(self, category, part_id=None):
        self.log.append(("route", category, part_id))

    def reset_target(self):
        self.log.append("reset_target")

    def confirm_transfer(self, part_id, category):
        self.log.append(("confirm", part_id, category))

    def emergency_stop(self):
        self.log.append("dist_stop")

    def diagnostic_gate(self, position):
        self.log.append(("gate", position))

    def diagnostic_route(self, category):
        self.log.append(("dist_route", category))


class FakeJog:
    def __init__(self):
        self.status = {"busy": False, "error": None}
        self.busy = False
        self.released = []

    def start_hold(self, direction):
        self.busy = True
        self.status["busy"] = True
        return True

    def heartbeat(self, direction):
        return True

    def release(self, reason=""):
        self.busy = False
        self.status["busy"] = False
        self.released.append(reason)
        return True


class FakeMonitor:
    def __init__(self):
        self.updates = 0
        self.server = type("S", (), {"active_camera_role": "INPUT_LEFT"})()

    def update(self, **kwargs):
        self.updates += 1


class FakeArchive:
    def __init__(self):
        self.stored = []
        self.finalized = []
        self.batch_id = "test"

    def store_frames(self, **kwargs):
        self.stored.append(kwargs)

    def finalize(self, **kwargs):
        self.finalized.append(kwargs)

    def get_part_info(self, part_id):
        return {"relative_folder": f"GOOD/part_{part_id:04d}"}


def make_cycle(log=None, empty=False, fail=False, with_jog=False, with_monitor=False):
    log = log if log is not None else []
    conveyor = FakeConveyor(log)
    cameras = FakeCameras(log)
    inspector = FakeInspector(log, empty=empty, fail=fail)
    distributor = FakeDistributor(log)
    cycle = ProductionCycle(
        conveyor, cameras, inspector, distributor,
        monitor=FakeMonitor() if with_monitor else None,
        archive=FakeArchive(),
        jog=FakeJog() if with_jog else None,
        settle_seconds=0, stage_trace_seconds=0, review_seconds=0,
    )
    cycle.live = FakeLive()
    cycle.stages = StepSequencer(cycle.live, settle_seconds=0, trace_seconds=0)
    return cycle, log


class CycleBehaviorTest(unittest.TestCase):
    def test_start_parks_and_first_step_does_not_move(self):
        cycle, log = make_cycle()
        self.assertTrue(cycle.request_start())
        self.assertEqual(cycle.state, "RUNNING")
        self.assertIn("park", log)
        self.assertTrue(cycle._await_initial_inspection)
        cycle._run_once()
        self.assertNotIn("move", log)
        self.assertEqual(cycle.current_step, 0)
        self.assertEqual(cycle.part_counter, 1)
        self.assertEqual(len(cycle.parts), 1)

    def test_second_step_moves_belt(self):
        cycle, log = make_cycle()
        cycle.request_start()
        cycle._run_once()
        cycle._run_once()
        self.assertIn("move", log)
        self.assertEqual(cycle.current_step, 1)
        self.assertEqual(cycle.part_counter, 2)

    def test_empty_tray_does_not_create_part(self):
        cycle, log = make_cycle(empty=True)
        cycle.sm._state = State.RUNNING
        cycle._await_initial_inspection = True
        cycle._run_once()
        self.assertEqual(cycle.part_counter, 0)
        self.assertEqual(cycle.empty_count, 1)
        self.assertEqual(cycle.parts, [])

    def test_spider_then_drop_good(self):
        cycle, log = make_cycle()
        cycle.request_start()
        cycle._run_once()  # create part at step 0
        part = cycle.parts[0]
        part.mark_spider_done()
        self.assertEqual(part.route_category, CATEGORY_GOOD)
        # Pending drop is prepared on the step that starts at current_step=7.
        while cycle.current_step < 7:
            cycle._run_once()
        cycle._run_once()
        self.assertTrue(any(item == ("route", "GOOD", part.id) for item in log))
        self.assertTrue(any(item == ("confirm", part.id, "GOOD") for item in log))
        self.assertEqual(cycle.good_count, 1)
        self.assertFalse(any(p.id == part.id for p in cycle.parts))
        self.assertEqual(len(cycle.archive.finalized), 1)

    def test_incomplete_inspection_forced_bad(self):
        cycle, log = make_cycle()
        cycle.sm._state = State.RUNNING
        cycle._await_initial_inspection = False
        cycle.current_step = 7
        part = Part(3, 0)
        part.input_inspected = True
        cycle.parts.append(part)
        cycle._run_once()
        self.assertTrue(any(item == ("route", CATEGORY_BAD, 3) for item in log))
        self.assertEqual(cycle.bad_count, 1)

    def test_pause_blocks_before_capture(self):
        cycle, log = make_cycle(with_jog=True)
        cycle.request_start()
        self.assertTrue(cycle.request_pause())
        thread = threading.Thread(target=cycle._run_once, daemon=True)
        thread.start()
        deadline = time.time() + 2
        while cycle.state != "PAUSED" and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(cycle.state, "PAUSED")
        self.assertFalse(any(item[0] == "capture" for item in log if isinstance(item, tuple)))
        self.assertTrue(cycle.request_resume())
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(any(item[0] == "capture" for item in log if isinstance(item, tuple)))

    def test_fault_on_inspection_error(self):
        cycle, log = make_cycle(fail=True)
        cycle.sm._state = State.RUNNING
        cycle._await_initial_inspection = True
        cycle._run_once_safe()
        self.assertEqual(cycle.state, "FAULT")
        self.assertIn("e_stop", log)
        self.assertIn("dist_stop", log)

    def test_stop_rejects_new_parts_but_keeps_existing(self):
        cycle, log = make_cycle()
        cycle.request_start()
        cycle._run_once()
        self.assertEqual(len(cycle.parts), 1)
        self.assertTrue(cycle.request_stop())
        self.assertEqual(cycle.state, "STOPPING")
        before = cycle.part_counter
        cycle._run_once()
        self.assertEqual(cycle.part_counter, before)
        first_input = log.index(("input", ("INPUT_LEFT", "INPUT_RIGHT"), 1, 0))
        self.assertFalse(any(
            item[0] == "input" for item in log[first_input + 1:]
            if isinstance(item, tuple)
        ))

    def test_jog_only_in_safe_states(self):
        cycle, log = make_cycle(with_jog=True)
        self.assertTrue(cycle.enter_jog())
        self.assertTrue(cycle.jog_active)
        self.assertTrue(cycle.jog_hold_start("+"))
        self.assertTrue(cycle.jog_hold_release("up"))
        self.assertTrue(cycle.exit_jog())
        cycle.request_start()
        self.assertFalse(cycle.enter_jog())

    def test_distributor_diagnostic_only_when_idle_and_empty(self):
        cycle, log = make_cycle()
        self.assertTrue(cycle.distributor_diagnostic("DIST1_HOME"))
        cycle.request_start()
        cycle._run_once()
        self.assertFalse(cycle.distributor_diagnostic("DIST1_HOME"))

    def test_status_controls_match_state(self):
        cycle, log = make_cycle(with_jog=True, with_monitor=True)
        status = cycle._build_status()
        self.assertTrue(status["controls"]["start"])
        self.assertFalse(status["controls"]["stop"])
        cycle.request_start()
        status = cycle._build_status()
        self.assertFalse(status["controls"]["start"])
        self.assertTrue(status["controls"]["stop"])
        self.assertTrue(status["controls"]["pause"])

    def test_monitor_error_does_not_fault_step(self):
        cycle, log = make_cycle(with_monitor=True)
        cycle.monitor.update = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("ui down"))
        cycle.sm._state = State.RUNNING
        cycle._await_initial_inspection = True
        cycle._run_once_safe()
        self.assertEqual(cycle.state, "RUNNING")
        self.assertEqual(cycle.part_counter, 1)

    def test_archive_store_error_keeps_part(self):
        cycle, log = make_cycle()

        def boom(**kwargs):
            raise RuntimeError("disk full")

        cycle.archive.store_frames = boom
        cycle.sm._state = State.RUNNING
        cycle._await_initial_inspection = True
        cycle._run_once_safe()
        self.assertEqual(cycle.state, "RUNNING")
        self.assertEqual(len(cycle.parts), 1)

    def test_force_exit_cancels_motion(self):
        cycle, log = make_cycle()
        cycle.request_start()
        cycle.request_force_exit()
        self.assertTrue(cycle.force_exit_requested)
        with self.assertRaises(RuntimeError):
            cycle._run_once()


if __name__ == "__main__":
    unittest.main()
