"""Жизненный цикл application: startup, exit, shutdown для трёх камер."""

from __future__ import annotations

import sys
import threading
import types
import unittest
from types import SimpleNamespace

# Заглушка ultralytics: application.factory тянет vision.vision_cluster.
_FAKE = types.ModuleType("ultralytics")
_FAKE.YOLO = object
sys.modules.setdefault("ultralytics", _FAKE)

from application.callbacks import ExitCoordinator  # noqa: E402
from application.runtime import RuntimeState  # noqa: E402
from application.shutdown import ShutdownManager  # noqa: E402
from application.startup import SystemInitializer  # noqa: E402


class PassiveThread:
    def __init__(self, target, daemon=True):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return False

    def join(self, timeout=None):
        return None


class ImmediateThread(PassiveThread):
    def start(self):
        self.started = True
        self.target()


class RecordingMonitor:
    def __init__(self):
        self.events = []
        self.server = SimpleNamespace(boot_current=None, archive=None)
        self.shutdown_requested = None

    def boot_step_start(self, key, label=None):
        self.events.append(("boot.start", key, label))

    def boot_step_done(self, key, message=None):
        self.events.append(("boot.done", key, message))

    def boot_step_error(self, key, message=None):
        self.events.append(("boot.error", key, message))

    def boot_complete(self):
        self.events.append(("boot.complete",))

    def set_camera_roles(self, roles):
        self.events.append(("camera.roles", dict(roles)))

    def update(self, **kwargs):
        self.events.append(("update", sorted(kwargs)))

    def stop_server(self):
        self.events.append(("server.stop",))

    def close_window(self):
        self.events.append(("window.close",))


class FakeCameras:
    def __init__(self, roles):
        self.cameras = list(roles)
        self.mapping = dict(roles)
        self.released = False

    def warmup_all(self, duration=0.0):
        return {role: {"reads": 3} for role in self.mapping}

    def warmup_roles(self, roles, duration=0.0):
        return {role: {"reads": 3} for role in roles}

    def capture_all(self):
        return {role: object() for role in self.mapping}

    def release(self):
        self.released = True


class FakeCycle:
    def __init__(self):
        self.state = "IDLE"
        self.force_exit_requested = False
        self.distributor = SimpleNamespace()
        self.live = SimpleNamespace(
            error=None,
            stop=lambda: None,
            wait_for_roles=lambda roles, timeout=2.0: (),
        )
        self.force_calls = 0
        self.exit_calls = 0
        self.jog_entered = False
        self.distributor = SimpleNamespace(
            dist1_open_position=340,
            dist2_cleanup_position=340,
        )

    def request_force_exit(self):
        self.force_calls += 1
        self.force_exit_requested = True

    def request_exit(self):
        self.exit_calls += 1

    def enter_jog(self):
        self.jog_entered = True
        return True

    # Публичный API, к которому привязываются callbacks HMI.
    def start(self):
        return None

    def request_start(self):
        return None

    def request_stop(self):
        return None

    def request_pause(self):
        return False

    def request_resume(self):
        return False

    def distributor_diagnostic(self, command):
        return False

    def diagnostic_check_cameras(self):
        return False

    def diagnostic_check_vision_rules(self):
        return False

    def diagnostic_analyze_selected_camera(self, role):
        return False

    def diagnostic_release_selected_camera(self):
        return False

    def exit_jog(self):
        return None

    def jog_hold_start(self, direction):
        return False

    def jog_hold_heartbeat(self, direction):
        return False

    def jog_hold_release(self, reason="released"):
        return False

    def _refresh_monitor(self):
        return None


class StartupHarness:
    """Минимальная фабрика для SystemInitializer без реального железа."""

    def __init__(self, monitor, roles=(("NEAR", 0), ("MIDDLE", 1), ("FAR", 2))):
        self.monitor = monitor
        self.roles = dict(roles)
        self.cameras = FakeCameras(self.roles)
        self.cycle = FakeCycle()
        self.hardware = None
        self.created = []
        self._fail = None

    def load_calibration(self):
        return {
            "settle_time": 0.0,
            "stage_trace_time": 0.0,
            "review_time": 0.0,
        }

    def create_cameras(self):
        self.created.append("cameras")
        return self.cameras

    def create_vision(self):
        self.created.append("vision")
        if self._fail == "models":
            raise RuntimeError("model load failed")
        return SimpleNamespace(models={}, warmup=lambda: None)

    def create_inspection(self, vision):
        self.created.append("inspection")
        return SimpleNamespace(
            decision=SimpleNamespace(rules=[1, 2, 3, 4, 5]),
            inspector=object(),
            archive=SimpleNamespace(),
            thresholds={},
            threshold_loader=SimpleNamespace(labels={}),
        )

    def discover_controller(self, *, baudrate, preferred_port):
        return "COM9", "found"

    def create_transport(self, *, port, baudrate):
        return SimpleNamespace(send=lambda *a: None, close=lambda: None)

    def create_hardware(self, transport, calibration, cancel_check):
        self.created.append("hardware")
        self.hardware = SimpleNamespace(
            conveyor=object(),
            distributor=SimpleNamespace(
                dist1_open_position=340,
                dist2_cleanup_position=340,
                initialize=lambda: None,
            ),
            jog=object(),
        )
        return self.hardware

    def create_cycle(self, **kwargs):
        self.created.append("cycle")
        return self.cycle


class StartupTest(unittest.TestCase):
    def _runtime(self, monitor):
        runtime = RuntimeState(monitor=monitor)
        runtime.shutdown_requested = threading.Event()
        return runtime

    def test_startup_runs_all_three_camera_stages(self):

        monitor = RecordingMonitor()
        runtime = self._runtime(monitor)
        factory = StartupHarness(monitor)
        init = SystemInitializer(
            runtime, factory, ExitCoordinator(runtime),
            thread_factory=ImmediateThread,
            sleep=lambda *_: None,
            initial_camera_frames_timeout=0.1,
        )
        init.run()

        keys = [e[1] for e in monitor.events if e[0] == "boot.start"]
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
        self.assertIn(("boot.complete",), monitor.events)
        self.assertIs(runtime.cycle, factory.cycle)
        self.assertTrue(factory.cycle.jog_entered)

    def test_model_failure_keeps_cameras_but_no_hardware(self):

        monitor = RecordingMonitor()
        runtime = self._runtime(monitor)
        factory = StartupHarness(monitor)
        factory._fail = "models"
        init = SystemInitializer(
            runtime, factory, ExitCoordinator(runtime),
            thread_factory=PassiveThread,
            sleep=lambda *_: None,
        )
        init.run()

        self.assertIsNotNone(runtime.cameras)
        self.assertIsNone(runtime.transport)
        self.assertIsNone(runtime.cycle)
        errors = [e for e in monitor.events if e[0] == "boot.error"]
        self.assertTrue(errors)
        self.assertEqual(errors[-1][1], "models_load")

    def test_cancel_during_init(self):

        monitor = RecordingMonitor()
        runtime = self._runtime(monitor)
        runtime.shutdown_requested.set()
        factory = StartupHarness(monitor)
        init = SystemInitializer(
            runtime, factory, ExitCoordinator(runtime),
            thread_factory=PassiveThread,
            sleep=lambda *_: None,
        )
        init.run()
        # До оборудования дело не дошло.
        self.assertIsNone(runtime.transport)


class ExitCoordinatorTest(unittest.TestCase):
    def test_first_exit_graceful_second_force(self):
        monitor = RecordingMonitor()
        runtime = RuntimeState(monitor=monitor)
        runtime.shutdown_requested = __import__("threading").Event()
        cycle = FakeCycle()
        runtime.cycle = cycle

        coord = ExitCoordinator(runtime, thread_factory=PassiveThread)
        coord.request_exit()
        self.assertEqual(cycle.exit_calls, 1)
        self.assertEqual(cycle.force_calls, 0)

        coord2 = ExitCoordinator(runtime, thread_factory=PassiveThread)
        coord2._press_count = 1
        coord2.request_exit()
        self.assertEqual(cycle.force_calls, 1)


class ShutdownTest(unittest.TestCase):
    def test_releases_resources_in_order(self):

        monitor = RecordingMonitor()
        runtime = RuntimeState(monitor=monitor)
        runtime.shutdown_requested = threading.Event()
        order = []
        archive = SimpleNamespace(
            enabled=True,
            compress_on_shutdown=True,
            delete_original_after_zip=True,
        )

        def compress(delete_original=True):
            order.append("compress")

        archive.compress = compress

        class Cycle:
            state = "IDLE"
            force_exit_requested = False

            def __init__(self):
                self.live = SimpleNamespace(stop=lambda: order.append("live"))

            def request_force_exit(self):
                self.force_exit_requested = True
                order.append("force_exit")

        runtime.cycle = Cycle()
        runtime.cameras = SimpleNamespace(
            release=lambda: order.append("cameras"),
        )
        runtime.transport = SimpleNamespace(
            close=lambda: order.append("transport"),
        )
        runtime.archive = archive

        mgr = ShutdownManager(runtime, thread_factory=ImmediateThread)
        mgr.shutdown()

        # live останавливается до камер; транспорт закрывается последним.
        self.assertLess(order.index("live"), order.index("cameras"))
        self.assertLess(order.index("compress"), order.index("cameras"))
        self.assertEqual(order[-1], "transport")

    def test_compress_skipped_when_disabled(self):

        monitor = RecordingMonitor()
        runtime = RuntimeState(monitor=monitor)
        runtime.shutdown_requested = threading.Event()
        calls = []
        runtime.archive = SimpleNamespace(
            enabled=False,
            compress_on_shutdown=True,
            compress=lambda **k: calls.append("compress"),
        )
        runtime.cycle = None
        runtime.cameras = None
        runtime.transport = None
        ShutdownManager(runtime, thread_factory=ImmediateThread).shutdown()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
