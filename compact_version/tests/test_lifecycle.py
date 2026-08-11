from __future__ import annotations

import unittest

from conveyor_compact.lifecycle import Lifecycle, LifecycleError, ManagedComponent


class LifecycleTests(unittest.TestCase):
    def test_components_stop_in_reverse_order(self):
        events = []
        lifecycle = Lifecycle(
            (
                ManagedComponent("camera", lambda: events.append("start camera"), lambda: events.append("stop camera")),
                ManagedComponent("ui", lambda: events.append("start ui"), lambda: events.append("stop ui")),
            )
        )
        lifecycle.start()
        lifecycle.stop()
        self.assertEqual(
            ["start camera", "start ui", "stop ui", "stop camera"],
            events,
        )

    def test_start_failure_rolls_back_started_components(self):
        events = []

        def fail():
            events.append("start vision")
            raise RuntimeError("weights missing")

        lifecycle = Lifecycle(
            (
                ManagedComponent("camera", lambda: events.append("start camera"), lambda: events.append("stop camera")),
                ManagedComponent("vision", fail, lambda: events.append("stop vision")),
            )
        )
        with self.assertRaisesRegex(LifecycleError, "weights missing"):
            lifecycle.start()
        self.assertEqual(["start camera", "start vision", "stop camera"], events)
        self.assertEqual((), lifecycle.started_names)


if __name__ == "__main__":
    unittest.main()
