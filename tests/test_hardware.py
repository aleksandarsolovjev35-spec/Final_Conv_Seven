"""Слой оборудования: SerialTransport, Axis, Conveyor, Distributor, JogController.

Физический COM-порт заменяется фейковым транспортом; проверяются команды,
парсинг ответов контроллера, ограничения движения и последовательности
маршрутизации распределителя.
"""

from __future__ import annotations

import unittest
from unittest import mock

from hardware.axis import Axis
from hardware.conveyor import Conveyor
from hardware.distributor import Distributor
from hardware.jog_controller import JogController
from hardware.port_discovery import (
    find_controller,
    is_controller_response,
    list_available_ports,
    try_port,
)
from hardware.serial_transport import SerialTransport


class FakeSerial:
    """Минимальная имитация pyserial."""

    def __init__(self, responses=None, write_error=None):
        self.is_open = True
        self.closed = False
        self.writes = []
        self.responses = list(responses or [])
        self.write_error = write_error
        self._buffer = b""

    def write(self, data):
        if self.write_error:
            raise self.write_error
        self.writes.append(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        self._buffer = b""

    def read_all(self):
        if self.responses:
            return self.responses.pop(0)
        return b""

    def close(self):
        self.closed = True
        self.is_open = False


class RecordingTransport:
    """Транспорт-дублёр: записывает команды, отвечает по шаблону."""

    def __init__(self, responses=None):
        self.commands = []
        self.responses = responses or {}

    def send(self, command):
        self.commands.append(command)

    def query(self, command, delay=0.15):
        self.commands.append(command)
        return self.responses.get(command, "")


class SerialTransportTest(unittest.TestCase):
    @mock.patch("hardware.serial_transport.serial.Serial")
    def test_open_sends_nothing_and_sleeps(self, serial_cls):
        fake = FakeSerial()
        serial_cls.return_value = fake
        with mock.patch("hardware.serial_transport.time.sleep"):
            transport = SerialTransport("COM4", 115200)
        serial_cls.assert_called_once_with(
            "COM4", 115200, timeout=0.5, write_timeout=2.0,
        )
        transport.close()
        self.assertTrue(fake.closed)

    @mock.patch("hardware.serial_transport.serial.Serial")
    def test_send_appends_newline(self, serial_cls):
        fake = FakeSerial()
        serial_cls.return_value = fake
        with mock.patch("hardware.serial_transport.time.sleep"):
            transport = SerialTransport("COM4")
        transport.send("G3")
        self.assertEqual(fake.writes, [b"G3\n"])

    @mock.patch("hardware.serial_transport.serial.Serial")
    def test_query_returns_trimmed_response(self, serial_cls):
        fake = FakeSerial(responses=[b"MOV=0 WAIT=0 lastErr=0\r\n"])
        serial_cls.return_value = fake
        with mock.patch("hardware.serial_transport.time.sleep"):
            transport = SerialTransport("COM4")
        self.assertEqual(
            transport.query("I2"), "MOV=0 WAIT=0 lastErr=0",
        )

    @mock.patch("hardware.serial_transport.serial.Serial")
    def test_close_tolerates_missing_serial(self, serial_cls):
        fake = FakeSerial()
        serial_cls.return_value = fake
        with mock.patch("hardware.serial_transport.time.sleep"):
            transport = SerialTransport("COM4")
        transport.close()
        self.assertTrue(fake.closed)

    @mock.patch("hardware.serial_transport.serial.Serial")
    def test_close_after_open_failure_not_needed(self, serial_cls):
        serial_cls.side_effect = RuntimeError("no port")
        with mock.patch("hardware.serial_transport.time.sleep"):
            with self.assertRaises(RuntimeError):
                SerialTransport("COM4")


class FakeAxisTransport(RecordingTransport):
    """Транспорт с ответами firmware для осей."""

    def __init__(self, status_line, config_line=None):
        super().__init__()
        self.status_line = status_line
        self.config_line = config_line or (
            "AXIS0 speed=300 accel=100 limMin=0 limMax=1000"
        )

    def query(self, command, delay=0.15):
        self.commands.append(command)
        if command == "I10":
            return self.status_line
        if command == "I11":
            return self.config_line
        return ""


class AxisTest(unittest.TestCase):
    def make_axis(self, transport=None, maximum=1000):
        transport = transport or FakeAxisTransport(
            "AXIS0 POS=0 TGT=0 MOV=0 EN=1 HOME=0 HOMED=1 LIM=1 ES=0",
        )
        with mock.patch("time.sleep"):
            return Axis(transport, 0, maximum, 0, speed=300, accel=100), transport

    def test_invalid_axis_id(self):
        with self.assertRaisesRegex(ValueError, "0 или 1"):
            Axis(RecordingTransport(), 2, 1000)

    def test_invalid_limits(self):
        with self.assertRaisesRegex(ValueError, "0 <= minimum < maximum"):
            Axis(RecordingTransport(), 0, 1000, minimum=-5)
        with self.assertRaisesRegex(ValueError, "0 <= minimum < maximum"):
            Axis(RecordingTransport(), 0, maximum=0)

    def test_constructor_sends_params_and_limits(self):
        transport = FakeAxisTransport("")
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000, speed=300, accel=100)
        self.assertEqual(transport.commands, [
            "G21 S300 P0", "G22 S100 P0",
            "G31 S0 P0", "G32 S1000 P0", "G33 S1 P0", "I11",
        ])
        self.assertEqual(axis.minimum, 0)
        self.assertEqual(axis.maximum, 1000)

    def test_verify_limit_config_mismatch_raises(self):
        transport = FakeAxisTransport(
            "", config_line="AXIS0 speed=300 accel=100 limMin=10 limMax=1000",
        )
        with mock.patch("time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "limMin"):
                Axis(transport, 0, 1000)

    def test_move_absolute(self):
        transport = FakeAxisTransport("")
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        with mock.patch("time.sleep"):
            axis.move_absolute(500)
        self.assertEqual(transport.commands[-1], "G27 S500 P0")

    def test_move_absolute_out_of_range(self):
        with mock.patch("time.sleep"):
            axis = Axis(FakeAxisTransport(""), 0, 1000)
        with self.assertRaisesRegex(ValueError, "absolute position"):
            axis.move_absolute(5000)
        with self.assertRaisesRegex(ValueError, "absolute position"):
            axis.move_absolute(5.5)

    def test_home(self):
        transport = FakeAxisTransport("")
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        with mock.patch("time.sleep"):
            axis.home()
        self.assertIn("G28 P0", transport.commands)

    def test_read_status_parses_fields(self):
        transport = FakeAxisTransport(
            "AXIS0 POS=100 TGT=100 MOV=1 EN=1 HOME=2 HOMED=1 LIM=1 ES=0",
        )
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        status = axis.read_status()
        self.assertEqual(status["position"], 100)
        self.assertEqual(status["moving"], 1)
        self.assertEqual(status["homed"], 1)
        self.assertEqual(status["raw"], transport.status_line)

    def test_read_status_unparseable(self):
        transport = FakeAxisTransport("GARBAGE")
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        status = axis.read_status()
        self.assertIsNone(status["position"])

    def test_verify_homed_failures(self):
        transport = FakeAxisTransport(
            "AXIS0 POS=50 TGT=50 MOV=0 EN=1 HOME=0 HOMED=0 LIM=1 ES=0",
        )
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        with self.assertRaisesRegex(RuntimeError, "invalid homing"):
            axis.verify_homed()

    def test_position_property(self):
        transport = FakeAxisTransport(
            "AXIS0 POS=42 TGT=42 MOV=0 EN=1 HOME=0 HOMED=1 LIM=1 ES=0",
        )
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        self.assertEqual(axis.position, 42)

    def test_position_missing_raises(self):
        transport = FakeAxisTransport("AXIS0 TGT=0")
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        with self.assertRaisesRegex(RuntimeError, "no position"):
            _ = axis.position

    def test_wait_stop(self):
        transport = FakeAxisTransport(
            "AXIS0 POS=0 TGT=0 MOV=0 EN=1 HOME=0 HOMED=1 LIM=1 ES=0",
        )
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        with mock.patch("time.sleep"):
            axis.wait_stop(timeout=1.0)

    def test_wait_stop_timeout(self):
        transport = FakeAxisTransport(
            "AXIS0 POS=0 TGT=0 MOV=1 EN=1 HOME=0 HOMED=1 LIM=1 ES=0",
        )
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        with mock.patch("time.sleep"):
            with self.assertRaises(TimeoutError):
                axis.wait_stop(timeout=0.01)

    def test_wait_stop_progress_callback(self):
        transport = FakeAxisTransport(
            "AXIS0 POS=0 TGT=0 MOV=0 EN=1 HOME=0 HOMED=1 LIM=1 ES=0",
        )
        with mock.patch("time.sleep"):
            axis = Axis(transport, 0, 1000)
        seen = []
        with mock.patch("time.sleep"):
            axis.wait_stop(timeout=1.0, progress_callback=lambda p, m: seen.append(p))
        self.assertEqual(seen, [0])


class ConveyorTest(unittest.TestCase):
    def make_conveyor(self, transport=None, **kwargs):
        transport = transport or RecordingTransport()
        with mock.patch("time.sleep"):
            conveyor = Conveyor(
                transport,
                speed=20000,
                accel=6000,
                steps_per_division=19048,
                divisions_per_movement=2,
                **kwargs,
            )
        return conveyor, transport

    def test_constructor_sets_parameters(self):
        conveyor, transport = self.make_conveyor()
        self.assertEqual(transport.commands, [
            "G5 S20000", "G4 S6000", "G7 S19048", "G6 S2",
        ])
        self.assertEqual(conveyor.speed, 20000)
        self.assertEqual(conveyor.steps_per_division, 19048)

    def test_invalid_geometry(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            Conveyor(RecordingTransport(), steps_per_division=0)

    def test_move_step(self):
        conveyor, transport = self.make_conveyor()
        with mock.patch("time.sleep"):
            conveyor.move_step()
        self.assertEqual(transport.commands[-1], "G3")

    def test_emergency_stop(self):
        conveyor, transport = self.make_conveyor()
        conveyor.emergency_stop()
        self.assertEqual(transport.commands[-1], "G1")

    def test_wait_stop_confirmed(self):
        transport = RecordingTransport({
            "I1": "0",
            "I2": "MOV=0 WAIT=0 lastErr=0",
        })
        conveyor, _ = self.make_conveyor(transport)
        with mock.patch("time.sleep"):
            conveyor.wait_stop(timeout=1.0)

    def test_wait_stop_timeout(self):
        transport = RecordingTransport({
            "I1": "1",
            "I2": "MOV=1 WAIT=0 lastErr=0",
        })
        conveyor, _ = self.make_conveyor(transport)
        with mock.patch("time.sleep"):
            with self.assertRaises(TimeoutError):
                conveyor.wait_stop(timeout=0.01)

    def test_parse_motion_reply(self):
        self.assertIsNone(Conveyor._parse_motion_reply(""))
        self.assertIsNone(Conveyor._parse_motion_reply("garbage"))
        self.assertTrue(Conveyor._parse_motion_reply("0"))
        self.assertFalse(Conveyor._parse_motion_reply("1"))
        self.assertTrue(Conveyor._parse_motion_reply("noise\n0\n"))
        self.assertFalse(Conveyor._parse_motion_reply("noise\n1\n"))

    def test_parse_status(self):
        status = Conveyor._parse_status("MOV=0 WAIT=1 POS=5 TGT=5 lastErr=-3")
        self.assertEqual(status["mov"], 0)
        self.assertEqual(status["wait"], 1)
        self.assertEqual(status["pos"], 5)
        self.assertEqual(status["lasterr"], -3)
        empty = Conveyor._parse_status("")
        self.assertIsNone(empty["mov"])

    def test_strict_stop_confirmed(self):
        self.assertTrue(Conveyor._strict_stop_confirmed(
            "MOV=0 WAIT=0 lastErr=0",
        ))
        self.assertFalse(Conveyor._strict_stop_confirmed("MOV=0 WAIT=0 lastErr=1"))
        self.assertFalse(Conveyor._strict_stop_confirmed(""))
        self.assertFalse(Conveyor._strict_stop_confirmed("MOV=1 WAIT=0 lastErr=0"))


class FakeAxisForDistributor:
    def __init__(self, transport, max_position=1000):
        self.transport = transport
        self.position = 0
        self.max_position = max_position

    def home(self):
        self.transport.send("G28")

    def verify_homed(self):
        return {"position": 0, "moving": 0, "homed": 1}

    def move_absolute(self, position):
        self.position = position
        self.transport.send(f"G27 S{position}")

    def wait_stop(self, timeout=12.0, progress_callback=None):
        if progress_callback is not None:
            progress_callback(self.position, 0)

    def read_status(self):
        return {"position": self.position, "moving": 0}


class DistributorTest(unittest.TestCase):
    def make_distributor(self, dist1_open=340, dist2_bad=0, dist2_cleanup=340):
        transport = RecordingTransport()
        dist1 = FakeAxisForDistributor(transport)
        dist2 = FakeAxisForDistributor(transport)
        distributor = Distributor(
            dist1, dist2,
            dist1_open_position=dist1_open,
            dist2_bad_position=dist2_bad,
            dist2_cleanup_position=dist2_cleanup,
        )
        return distributor, transport

    def test_invalid_positions(self):
        with self.assertRaisesRegex(ValueError, "dist1_open_position"):
            Distributor(None, None, 0, 1, 2)
        with self.assertRaisesRegex(ValueError, "dist2_bad_position"):
            Distributor(None, None, 10, -1, 2)
        with self.assertRaisesRegex(ValueError, "различаться"):
            Distributor(None, None, 10, 5, 5)

    def test_status_shape(self):
        distributor, _ = self.make_distributor()
        status = distributor.status
        for key in (
            "dist1_position", "dist1_max", "dist1_state",
            "dist2_position", "dist2_max", "dist2_state",
            "dist2_target", "last_distributor_action",
        ):
            self.assertIn(key, status)

    def test_initialize_homes_both_axes(self):
        distributor, transport = self.make_distributor()
        distributor.initialize()
        self.assertEqual(distributor.dist1_state, "GOOD")
        self.assertEqual(distributor.dist2_state, "IDLE")
        self.assertEqual(distributor.dist2_target, "BAD")

    def test_park_production(self):
        distributor, _ = self.make_distributor()
        distributor.park_production()
        self.assertEqual(distributor.dist1_state, "GOOD")
        self.assertEqual(distributor.last_action, "PRODUCTION READY")

    def test_prepare_route_good(self):
        distributor, _ = self.make_distributor()
        distributor.prepare_route("GOOD", part_id=7)
        self.assertEqual(distributor.dist1_state, "GOOD")
        self.assertIn("PART #7 -> GOOD", distributor.last_action)

    def test_prepare_route_bad(self):
        distributor, transport = self.make_distributor()
        distributor.prepare_route("BAD", part_id=3)
        self.assertEqual(distributor.dist2_target, "BAD")
        self.assertEqual(distributor.dist2.position, 0)
        self.assertIn("PART #3 -> BAD READY", distributor.last_action)

    def test_prepare_route_cleanup(self):
        distributor, transport = self.make_distributor()
        distributor.prepare_route("CLEANUP", part_id=3)
        self.assertEqual(distributor.dist2_target, "CLEANUP")
        self.assertEqual(distributor.dist2.position, 340)
        self.assertIn("PART #3 -> CLEANUP READY", distributor.last_action)

    def test_prepare_route_invalid_category(self):
        distributor, _ = self.make_distributor()
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            distributor.prepare_route("MAYBE")

    def test_confirm_transfer(self):
        distributor, _ = self.make_distributor()
        distributor.confirm_transfer(5, "GOOD")
        self.assertIn("PART #5 -> GOOD DONE", distributor.last_action)

    def test_diagnostic_gate(self):
        distributor, _ = self.make_distributor()
        distributor.diagnostic_gate("HOME")
        self.assertEqual(distributor.dist1_state, "GOOD")
        distributor.diagnostic_gate("OPEN")
        self.assertEqual(distributor.dist1_state, "TO_DIST2")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            distributor.diagnostic_gate("SIDE")

    def test_diagnostic_route(self):
        distributor, _ = self.make_distributor()
        distributor.diagnostic_route("BAD")
        self.assertEqual(distributor.dist2_target, "BAD")
        distributor.diagnostic_route("CLEANUP")
        self.assertEqual(distributor.dist2_target, "CLEANUP")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            distributor.diagnostic_route("GOOD")

    def test_emergency_stop(self):
        distributor, transport = self.make_distributor()
        distributor.emergency_stop()
        self.assertEqual(transport.commands[-1], "G25")
        self.assertEqual(distributor.dist1_state, "FAULT")
        self.assertEqual(distributor.dist2_state, "FAULT")

    def test_state_changed_callback(self):
        distributor, _ = self.make_distributor()
        events = []
        distributor.on_state_changed = lambda: events.append(1)
        distributor.initialize()
        self.assertGreater(len(events), 0)


def _calibration():
    return {
        "jog_hold_steps": 1_000_000,
        "normal_steps": 19048,
    }


class JogControllerTest(unittest.TestCase):
    def make_jog(self, transport=None, calibration=None, timeout=0.15):
        transport = transport or RecordingTransport()
        with mock.patch("time.sleep"):
            jog = JogController(
                transport,
                calibration or _calibration(),
                heartbeat_timeout=timeout,
            )
        return jog, transport

    def test_invalid_hold_steps(self):
        with self.assertRaisesRegex(ValueError, "jog_hold_steps"):
            JogController(RecordingTransport(), {"jog_hold_steps": 5, "normal_steps": 1})

    def test_invalid_normal_steps(self):
        with self.assertRaisesRegex(ValueError, "normal_steps"):
            JogController(RecordingTransport(), {"jog_hold_steps": 100000, "normal_steps": 0})

    def test_invalid_heartbeat_timeout(self):
        with self.assertRaisesRegex(ValueError, "heartbeat_timeout"):
            JogController(RecordingTransport(), _calibration(), heartbeat_timeout=5.0)

    def test_status_shape(self):
        jog, _ = self.make_jog()
        status = jog.status
        self.assertEqual(status["hold_steps"], 1_000_000)
        self.assertFalse(status["busy"])
        self.assertIn("heartbeat_timeout_ms", status)

    def test_start_hold_invalid_direction(self):
        jog, _ = self.make_jog()
        with self.assertRaisesRegex(ValueError, "'\\+' или '-'"):
            jog.start_hold("x")

    def test_start_hold_and_release(self):
        transport = RecordingTransport({
            "I1": "0",
            "I2": "MOV=0 WAIT=0 lastErr=0",
        })
        jog, _ = self.make_jog(transport)
        self.assertTrue(jog.start_hold("+"))
        self.assertTrue(jog.busy)
        self.assertEqual(jog.last_action, "HOLD RIGHT")
        self.assertTrue(jog.heartbeat("+"))
        self.assertTrue(jog.release("test"))
        self.assertFalse(jog.busy)
        self.assertIn("STOP: test", jog.last_action)
        self.assertIn("G1", transport.commands)

    def test_start_hold_left_direction(self):
        jog, _ = self.make_jog()
        self.assertTrue(jog.start_hold("-"))
        self.assertEqual(jog.last_action, "HOLD LEFT")
        jog.release()

    def test_heartbeat_wrong_direction(self):
        jog, _ = self.make_jog()
        jog.start_hold("+")
        self.assertFalse(jog.heartbeat("-"))
        jog.release()

    def test_heartbeat_when_idle(self):
        jog, _ = self.make_jog()
        self.assertFalse(jog.heartbeat("+"))

    def test_release_without_start(self):
        jog, _ = self.make_jog()
        self.assertTrue(jog.release("nothing"))

    def test_repeated_hold_same_direction(self):
        jog, _ = self.make_jog()
        jog.start_hold("+")
        self.assertTrue(jog.start_hold("+"))
        jog.release()

    def test_hold_other_direction_while_busy(self):
        jog, _ = self.make_jog()
        jog.start_hold("+")
        self.assertFalse(jog.start_hold("-"))
        jog.release()


class PortDiscoveryTest(unittest.TestCase):
    def test_is_controller_response(self):
        self.assertTrue(is_controller_response("MOV=0 WAIT=0 lastErr=0"))
        self.assertFalse(is_controller_response(""))
        self.assertFalse(is_controller_response("hello"))

    def test_list_available_ports(self):
        class Info:
            device = "COM4"
            description = "USB-SERIAL"
            hwid = "USB VID:PID"
            manufacturer = "FTDI"

        with mock.patch(
            "hardware.port_discovery.serial.tools.list_ports.comports",
            return_value=[Info()],
        ):
            ports = list_available_ports()
        self.assertEqual(ports, [{
            "port": "COM4", "description": "USB-SERIAL",
            "hwid": "USB VID:PID", "manufacturer": "FTDI",
        }])

    def test_try_port_success(self):
        fake = FakeSerial(responses=[b"MOV=0 WAIT=0 lastErr=0"])
        with mock.patch("hardware.port_discovery.serial.Serial",
                        return_value=fake), \
             mock.patch("hardware.port_discovery.time.sleep"):
            ok, response = try_port("COM4")
        self.assertTrue(ok)
        self.assertIn("MOV=", response)

    def test_try_port_no_response(self):
        fake = FakeSerial(responses=[b""])
        with mock.patch("hardware.port_discovery.serial.Serial",
                        return_value=fake), \
             mock.patch("hardware.port_discovery.time.sleep"):
            ok, response = try_port("COM4")
        self.assertFalse(ok)
        self.assertEqual(response, "no response")

    def test_try_port_unexpected_response(self):
        fake = FakeSerial(responses=[b"hello"])
        with mock.patch("hardware.port_discovery.serial.Serial",
                        return_value=fake), \
             mock.patch("hardware.port_discovery.time.sleep"):
            ok, response = try_port("COM4")
        self.assertFalse(ok)
        self.assertIn("unexpected controller response", response)

    def test_try_port_serial_exception(self):
        with mock.patch(
            "hardware.port_discovery.serial.Serial",
            side_effect=Exception("boom"),
        ), mock.patch("hardware.port_discovery.time.sleep"):
            ok, response = try_port("COM4")
        self.assertFalse(ok)
        self.assertIn("error", response)

    def test_try_port_closes_serial(self):
        fake = FakeSerial(responses=[b""])
        with mock.patch("hardware.port_discovery.serial.Serial",
                        return_value=fake), \
             mock.patch("hardware.port_discovery.time.sleep"):
            try_port("COM4")
        self.assertTrue(fake.closed)

    def test_find_controller_no_ports(self):
        with mock.patch(
            "hardware.port_discovery.list_available_ports", return_value=[],
        ):
            port, message = find_controller()
        self.assertIsNone(port)
        self.assertIn("No COM ports", message)

    def test_find_controller_found(self):
        with mock.patch(
            "hardware.port_discovery.list_available_ports",
            return_value=[{"port": "COM4", "description": "USB"}],
        ), mock.patch(
            "hardware.port_discovery.try_port",
            return_value=(True, "MOV=0 WAIT=0 lastErr=0"),
        ):
            port, message = find_controller()
        self.assertEqual(port, "COM4")
        self.assertIn("Found on COM4", message)

    def test_find_controller_preferred_first(self):
        calls = []

        def fake_try_port(port, baudrate):
            calls.append(port)
            return (port == "COM3", "MOV=0 WAIT=0 lastErr=0")

        with mock.patch(
            "hardware.port_discovery.list_available_ports",
            return_value=[
                {"port": "COM4", "description": "USB"},
                {"port": "COM3", "description": "USB"},
            ],
        ), mock.patch("hardware.port_discovery.try_port",
                      side_effect=fake_try_port):
            port, _ = find_controller(preferred_port="COM3")
        self.assertEqual(port, "COM3")
        self.assertEqual(calls, ["COM3"])

    def test_find_controller_not_found(self):
        with mock.patch(
            "hardware.port_discovery.list_available_ports",
            return_value=[{"port": "COM4", "description": "USB"}],
        ), mock.patch(
            "hardware.port_discovery.try_port", return_value=(False, "no response"),
        ):
            port, message = find_controller()
        self.assertIsNone(port)
        self.assertIn("Controller not found", message)


if __name__ == "__main__":
    unittest.main()
