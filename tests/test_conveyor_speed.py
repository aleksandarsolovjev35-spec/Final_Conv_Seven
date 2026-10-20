"""Настройка скорости без подключения оборудования."""
import unittest
from unittest.mock import Mock
from hardware.conveyor import Conveyor


class ConveyorSpeedTest(unittest.TestCase):
    def setUp(self):
        self.conveyor = Conveyor.__new__(Conveyor)
        self.conveyor.transport = Mock()
        self.conveyor.speed = 20000
        self.conveyor._pending_step_sequence = None

    def test_confirmed_change(self):
        self.conveyor.transport.query.side_effect = [
            'MOV=0 WAIT=0 lastErr=0', 'G5: speed=12000\r\n',
        ]
        self.conveyor.set_speed(12000)
        self.assertEqual(self.conveyor.speed, 12000)
        self.conveyor.transport.query.assert_called_with('G5 S12000', delay=0.1)

    def test_invalid_values_do_not_touch_hardware(self):
        for value in (True, 4999, 20001, 12000.5, '12000', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.conveyor.set_speed(value)
        self.conveyor.transport.query.assert_not_called()

    def test_pending_step_rejected(self):
        self.conveyor._pending_step_sequence = 1
        with self.assertRaises(RuntimeError):
            self.conveyor.set_speed(12000)
        self.conveyor.transport.query.assert_not_called()

    def test_moving_or_unconfirmed_stop_rejected(self):
        for reply in ('MOV=1 WAIT=0 lastErr=0', '', 'MOV=0 WAIT=1 lastErr=0'):
            self.conveyor.transport.query.return_value = reply
            with self.assertRaises(RuntimeError):
                self.conveyor.set_speed(12000)
            self.assertEqual(self.conveyor.speed, 20000)

    def test_missing_ack_keeps_previous_speed(self):
        self.conveyor.transport.query.side_effect = ['MOV=0 WAIT=0 lastErr=0', 'Err']
        with self.assertRaises(RuntimeError):
            self.conveyor.set_speed(12000)
        self.assertEqual(self.conveyor.speed, 20000)
