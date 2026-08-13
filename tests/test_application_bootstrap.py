"""Composition root: bootstrap, фабрика и монитор UI.

Проверяется сборка приложения из частей, создание оборудования по
калибровке и делегирование callbacks LiveMonitor в UIServer.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

# application.factory импортирует vision.vision_cluster, которому нужен
# ultralytics; в тестовом окружении его заменяет заглушка.
_FAKE_ULTRALYTICS = types.ModuleType("ultralytics")
_FAKE_ULTRALYTICS.YOLO = object
sys.modules.setdefault("ultralytics", _FAKE_ULTRALYTICS)

from application.bootstrap import (  # noqa: E402
    create_application,
    ensure_camera_mapping,
    run_application,
)
from application.factory import ProductionSystemFactory
from application.ui import OperatorUI
from vision.ui.live_monitor import LiveMonitor, LiveMonitorApi

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeWebviewModule:
    FOLDER_DIALOG = "folder"

    def __init__(self):
        self.created = []
        self.started = 0

    def create_window(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(destroy=lambda: None)

    def start(self):
        self.started += 1


class EnsureCameraMappingTest(unittest.TestCase):
    def test_existing_file_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "camera_mapping.json")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{}")
            self.assertTrue(ensure_camera_mapping(path))

    def test_missing_file_launches_calibrator(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "camera_mapping.json")
            with mock.patch(
                "application.bootstrap.launch_camera_calibrator",
                return_value=True,
            ) as launch:
                self.assertTrue(ensure_camera_mapping(path))
            launch.assert_called_once_with(path)

    def test_missing_file_calibrator_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "camera_mapping.json")
            with mock.patch(
                "application.bootstrap.launch_camera_calibrator",
                return_value=False,
            ):
                self.assertFalse(ensure_camera_mapping(path))


class CreateApplicationTest(unittest.TestCase):
    def test_create_application_wires_parts(self):
        with mock.patch(
            "application.bootstrap.ProductionSystemFactory",
        ) as factory_cls, mock.patch(
            "application.bootstrap.ExitCoordinator",
        ), mock.patch(
            "application.bootstrap.SystemInitializer",
        ) as init_cls, mock.patch(
            "application.bootstrap.OperatorUI",
        ) as ui_cls, mock.patch(
            "application.bootstrap.ShutdownManager",
        ) as shutdown_cls:
            app = create_application()
        self.assertIsNotNone(app.runtime)
        factory_cls.assert_called_once_with()
        init_cls.assert_called_once()
        ui_cls.assert_called_once()
        shutdown_cls.assert_called_once()

    def test_run_application_no_mapping(self):
        with mock.patch(
            "application.bootstrap.ensure_camera_mapping",
            return_value=False,
        ) as ensure, mock.patch(
            "application.bootstrap.create_application",
        ) as create:
            run_application()
        ensure.assert_called_once()
        create.assert_not_called()

    def test_run_application_runs(self):
        fake_app = mock.Mock()
        with mock.patch(
            "application.bootstrap.ensure_camera_mapping",
            return_value=True,
        ), mock.patch(
            "application.bootstrap.create_application",
            return_value=fake_app,
        ):
            run_application()
        fake_app.run.assert_called_once()


class OperatorUITest(unittest.TestCase):
    def test_init_without_webview_raises(self):
        monitor = mock.Mock()
        with mock.patch.dict(sys.modules, {"webview": None}):
            with mock.patch(
                "builtins.__import__",
                side_effect=ImportError("no pywebview"),
            ):
                with self.assertRaises(ImportError):
                    OperatorUI(monitor)

    def test_init_with_fake_webview(self):
        webview = FakeWebviewModule()
        ui = OperatorUI(mock.Mock(), webview_module=webview)
        self.assertIs(ui._webview, webview)

    def test_run_creates_window(self):
        webview = FakeWebviewModule()
        monitor = mock.Mock(
            window_name="HMI",
            host="127.0.0.1",
            port=8000,
            fullscreen=True,
            webview_api=object(),
        )
        monitor._webview_window = None
        ui = OperatorUI(monitor, webview_module=webview)
        ui.run()
        self.assertEqual(webview.started, 1)
        self.assertEqual(webview.created[0]["title"], "HMI")
        self.assertIsNotNone(monitor._webview_window)

    def test_print_startup_help(self):
        OperatorUI.print_startup_help()

    def test_install_signal_handler(self):
        ui = OperatorUI(mock.Mock(), webview_module=FakeWebviewModule())
        called = []
        ui.install_signal_handler(lambda: called.append(1))
        import signal
        self.assertEqual(signal.getsignal(signal.SIGINT).__name__,
                         "signal_handler")


class LiveMonitorTest(unittest.TestCase):
    def setUp(self):
        self.monitor = LiveMonitor(start_callback=None, stop_callback=None,
                                   exit_callback=None)

    def test_constructor(self):
        self.assertIsNotNone(self.monitor.server)
        self.assertIsNotNone(self.monitor.webview_api)

    def test_splash_and_boot_delegation(self):
        self.monitor.set_splash_status("текст")
        self.assertEqual(self.monitor.server.boot_message, "текст")
        self.monitor.boot_step_start("cameras")
        self.assertEqual(self.monitor.server.boot_steps["cameras"], "running")
        self.monitor.boot_step_done("cameras")
        self.assertEqual(self.monitor.server.boot_steps["cameras"], "done")
        self.monitor.boot_complete()
        self.assertFalse(self.monitor.server.splash_active)

    def test_update_delegation(self):
        self.monitor.update(frames={"TOP": "x"})
        self.assertEqual(self.monitor.server.frames["TOP"], "x")

    def test_close_window_without_window(self):
        self.monitor.close_window()  # не должно падать

    def test_close_window_destroys_once(self):
        window = mock.Mock()
        self.monitor._webview_window = window
        self.monitor.close_window()
        window.destroy.assert_called_once()
        self.monitor.close_window()
        window.destroy.assert_called_once()

    def test_stop_server_without_thread(self):
        self.monitor.stop_server()

    def test_callbacks_bind_to_server(self):
        events = []
        self.monitor.start_callback = lambda: (events.append("start"), True)[1]
        self.monitor.stop_callback = lambda: (events.append("stop"), True)[1]
        self.monitor.exit_callback = lambda: (events.append("exit"), True)[1]
        self.monitor.distributor_diagnostic_callback = (
            lambda command: (events.append(("dist", command)), True)[1]
        )
        self.monitor.active_camera_callback = (
            lambda role: (events.append(("camera", role)), True)[1]
        )
        self.monitor.jog_hold_start_callback = (
            lambda direction: (events.append(("jog", direction)), True)[1]
        )
        self.monitor.thresholds_apply_callback = (
            lambda role, values, labels: (events.append(("thr", role)), True)[1]
        )
        self.monitor._bind_server_callbacks()

        self.assertTrue(self.monitor.server.on_start())
        self.assertTrue(self.monitor.server.on_stop())
        self.assertTrue(self.monitor.server.on_exit())
        self.assertTrue(self.monitor.server.on_distributor_diagnostic(
            "DIST1_HOME",
        ))
        self.assertTrue(self.monitor.server.on_active_camera_changed("TOP"))
        self.assertTrue(self.monitor.server.on_jog_hold_start("+"))
        self.assertTrue(self.monitor.server.on_thresholds_apply(
            "TOP", {"a": 1}, {},
        ))
        self.assertEqual(events, [
            "start", "stop", "exit",
            ("dist", "DIST1_HOME"),
            ("camera", "TOP"),
            ("jog", "+"),
            ("thr", "TOP"),
        ])

    def test_unbound_callbacks_return_false(self):
        self.monitor._bind_server_callbacks()
        self.assertFalse(self.monitor.server.on_start())
        self.assertFalse(self.monitor.server.on_jog_hold_start("+"))
        self.assertFalse(self.monitor.server.on_thresholds_apply("TOP", {}, {}))

    def test_invoke_helpers(self):
        self.assertFalse(self.monitor._invoke(None))
        self.assertEqual(self.monitor._invoke(lambda: 42), 42)
        self.assertFalse(self.monitor._invoke_args(None, 1))
        self.assertEqual(
            self.monitor._invoke_args(lambda a, b: a + b, 1, 2), 3,
        )


class LiveMonitorApiTest(unittest.TestCase):
    def test_choose_archive_folder_without_window(self):
        api = LiveMonitorApi(LiveMonitor())
        result = api.choose_archive_folder()
        self.assertFalse(result["ok"])
        self.assertIn("не готово", result["error"])

    def test_choose_archive_folder_with_window(self):
        window = mock.Mock()
        window.create_file_dialog.return_value = ["C:\\archive"]
        monitor = LiveMonitor()
        monitor._webview_window = window
        api = LiveMonitorApi(monitor)
        fake_webview = SimpleNamespace(FOLDER_DIALOG="folder")
        with mock.patch.dict(sys.modules, {"webview": fake_webview}):
            result = api.choose_archive_folder()
        self.assertTrue(result["ok"])
        self.assertEqual(result["path"], "C:\\archive")

    def test_choose_archive_folder_cancelled(self):
        window = mock.Mock()
        window.create_file_dialog.return_value = None
        monitor = LiveMonitor()
        monitor._webview_window = window
        api = LiveMonitorApi(monitor)
        with mock.patch.dict(
            sys.modules,
            {"webview": SimpleNamespace(FOLDER_DIALOG="folder")},
        ):
            result = api.choose_archive_folder()
        self.assertTrue(result["cancelled"])


class FactoryTest(unittest.TestCase):
    def test_load_calibration(self):
        factory = ProductionSystemFactory()
        calibration = factory.load_calibration()
        self.assertGreater(calibration["conveyor_speed"], 0)
        self.assertGreater(calibration["normal_steps"], 0)

    def test_create_transport(self):
        class FakeSerialTransport:
            def __init__(self, *, port, baudrate):
                self.port = port
                self.baudrate = baudrate

        with mock.patch(
            "application.factory.SerialTransport", FakeSerialTransport,
        ):
            transport = ProductionSystemFactory().create_transport(
                port="COM4", baudrate=115200,
            )
        self.assertEqual(transport.port, "COM4")
        self.assertEqual(transport.baudrate, 115200)

    def test_create_hardware(self):
        transport = mock.Mock()

        def fake_query(command, delay=0.15):
            if command == "I11":
                return (
                    "AXIS0 speed=300 accel=100 limMin=0 limMax=340\n"
                    "AXIS1 speed=300 accel=100 limMin=0 limMax=340"
                )
            return "AXIS0 POS=0 TGT=0 MOV=0 EN=1 HOME=0 HOMED=1 LIM=1 ES=0"

        transport.query.side_effect = fake_query
        factory = ProductionSystemFactory()
        calibration = factory.load_calibration()
        hardware = factory.create_hardware(
            transport, calibration, cancel_check=lambda: False,
        )
        self.assertIsNotNone(hardware.conveyor)
        self.assertIsNotNone(hardware.distributor)
        self.assertIsNotNone(hardware.jog)
        self.assertEqual(hardware.distributor.dist1_open_position,
                         calibration["dist1_open_position"])

    def test_create_hardware_endpoint_mismatch(self):
        from hardware.distributor import Distributor

        calibration = ProductionSystemFactory().load_calibration()
        distributor = Distributor(
            dist1_axis=mock.Mock(),
            dist2_axis=mock.Mock(),
            dist1_open_position=calibration["dist1_open_position"],
            dist2_bad_position=calibration["dist2_bad_position"],
            dist2_cleanup_position=calibration["dist2_cleanup_position"],
        )
        mismatched = dict(calibration)
        mismatched["dist2_cleanup_position"] = (
            calibration["dist2_cleanup_position"] + 1
        )
        with self.assertRaisesRegex(RuntimeError, "do not match"):
            ProductionSystemFactory._validate_distributor_endpoints(
                distributor, mismatched,
            )

    def test_create_cycle(self):
        factory = ProductionSystemFactory()
        hardware = SimpleNamespace(
            conveyor=mock.Mock(),
            distributor=mock.Mock(),
            jog=mock.Mock(),
        )
        cameras = mock.Mock()
        cameras.mapping = {"TOP": 0}
        cameras.capture_roles.return_value = {}
        inspector = mock.Mock()
        monitor = mock.Mock()
        monitor.server = SimpleNamespace(active_camera_role="TOP")
        cycle = factory.create_cycle(
            hardware=hardware,
            cameras=cameras,
            inspector=inspector,
            monitor=monitor,
            archive=mock.Mock(),
            calibration=factory.load_calibration(),
        )
        self.assertIsNotNone(cycle)

    def test_discover_controller(self):
        factory = ProductionSystemFactory()
        with mock.patch(
            "application.factory.find_controller",
            return_value=("COM4", "ok"),
        ) as find:
            port, message = factory.discover_controller(
                baudrate=115200, preferred_port="COM4",
            )
        self.assertEqual(port, "COM4")
        find.assert_called_once_with(
            baudrate=115200, preferred_port="COM4",
        )

    def test_create_cameras_and_vision(self):
        factory = ProductionSystemFactory()
        with mock.patch("application.factory.CameraManager") as cm:
            factory.create_cameras()
            cm.assert_called_once_with()
        with mock.patch("application.factory.VisionCluster") as vc:
            factory.create_vision()
            vc.assert_called_once_with(device="cpu")


class MainEntryTest(unittest.TestCase):
    def test_main_runs_application(self):
        import main as main_module
        with mock.patch(
            "main.run_application",
        ) as run:
            main_module.main()
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
