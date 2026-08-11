from __future__ import annotations

import unittest

from conveyor_compact.domain.state import LineState, StateMachine
from conveyor_compact.production.stages import (
    StageSequence,
    StageSequenceError,
    StepStage,
)


class StateMachineTests(unittest.TestCase):
    def test_normal_stop_flow(self):
        machine = StateMachine()
        self.assertTrue(machine.request_start())
        self.assertEqual(LineState.RUNNING, machine.state)
        self.assertTrue(machine.request_stop())
        self.assertEqual(LineState.STOPPING, machine.state)
        self.assertTrue(machine.notify_line_empty())
        self.assertEqual(LineState.STOPPED, machine.state)

    def test_pause_and_resume(self):
        machine = StateMachine()
        machine.request_start()
        self.assertTrue(machine.request_pause())
        self.assertEqual(LineState.PAUSED, machine.state)
        self.assertTrue(machine.request_resume())
        self.assertEqual(LineState.RUNNING, machine.state)

    def test_invalid_transition_does_not_change_state(self):
        machine = StateMachine()
        self.assertFalse(machine.request_pause())
        self.assertEqual(LineState.IDLE, machine.state)


class StageSequenceTests(unittest.TestCase):
    def test_full_step_and_next_motion(self):
        sequence = StageSequence()
        for stage in (
            StepStage.MOTION,
            StepStage.SETTLE,
            StepStage.CAPTURE,
            StepStage.ANALYSIS,
            StepStage.PUBLISH,
            StepStage.MOTION,
        ):
            sequence.move_to(stage)
        self.assertEqual(StepStage.MOTION, sequence.stage)

    def test_out_of_order_stage_fails_closed(self):
        sequence = StageSequence()
        with self.assertRaises(StageSequenceError):
            sequence.move_to(StepStage.CAPTURE)
        self.assertEqual(StepStage.IDLE, sequence.stage)


if __name__ == "__main__":
    unittest.main()
