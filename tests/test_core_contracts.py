"""Контракты пакета ``core``: границы слоёв, gate камер и снимок статуса.

Эти проверки закрепляют свойства, которые легко потерять при рефакторинге:
``core`` не должен зависеть от прикладных пакетов, камеры не должны
читаться во время инспекции, а форма статуса HMI не должна меняться
незаметно для frontend.
"""

from __future__ import annotations

import ast
import os
import threading
import unittest

# Импорты ``core`` намеренно ленивые: проверка границ слоёв разбирает
# исходники через AST и обязана выдавать понятный список нарушителей,
# даже когда импорт самого пакета сломан лишней зависимостью.

CORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core",
)

# Пакеты приложения, от которых ядро не должно зависеть: ``core`` живёт
# ниже них по слоям и обязан оставаться импортируемым без камер и UI.
FORBIDDEN_IMPORTS = ("vision", "hardware", "application", "config", "inspection")


def _core_modules():
    for root, dirs, files in os.walk(CORE_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


class CoreLayeringTest(unittest.TestCase):
    """Ядро зависит только от ``domain`` и стандартной библиотеки."""

    def test_core_does_not_import_application_packages(self):
        offenders = []
        for path in _core_modules():
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    root = name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS:
                        offenders.append(
                            f"{os.path.relpath(path)}:{node.lineno} -> {name}"
                        )
        self.assertEqual(offenders, [], "core импортирует прикладные пакеты")

    def test_rule_report_exports_resolve(self):
        import core.rule_report as rule_report

        missing = [
            name for name in rule_report.__all__
            if not hasattr(rule_report, name)
        ]
        self.assertEqual(missing, [])


class LiveCaptureGateTest(unittest.TestCase):
    """Инспекция забирает камеры целиком и дожидается активных чтений."""

    def setUp(self):
        from core.live_preview import LiveCaptureGate

        self.gate_factory = LiveCaptureGate

    def test_pause_blocks_new_reads(self):
        gate = self.gate_factory()
        self.assertTrue(gate.pause())
        with gate.live_read("TOP") as allowed:
            self.assertFalse(allowed)
        with gate.live_reads(("TOP", "INPUT_LEFT")) as roles:
            self.assertEqual(roles, ())
        gate.resume()
        with gate.live_read("TOP") as allowed:
            self.assertTrue(allowed)

    def test_pause_is_reentrant(self):
        gate = self.gate_factory()
        gate.pause()
        gate.pause()
        gate.resume()
        with gate.live_read("TOP") as allowed:
            self.assertFalse(allowed, "одного resume не хватает для двух пауз")
        gate.resume()
        with gate.live_read("TOP") as allowed:
            self.assertTrue(allowed)

    def test_pause_waits_for_active_read(self):
        gate = self.gate_factory()
        started = threading.Event()
        release = threading.Event()

        def reader():
            with gate.live_read("TOP") as allowed:
                if allowed:
                    started.set()
                    release.wait(2.0)

        thread = threading.Thread(target=reader)
        thread.start()
        self.assertTrue(started.wait(2.0))

        # Чтение ещё идёт: пауза не должна успеть за короткий таймаут.
        self.assertFalse(gate.pause(timeout=0.05))
        release.set()
        thread.join(2.0)
        self.assertTrue(gate.pause(timeout=1.0))

    def test_failed_pause_does_not_leave_live_blocked(self):
        gate = self.gate_factory()
        started = threading.Event()
        release = threading.Event()

        def reader():
            with gate.live_read("TOP") as allowed:
                if allowed:
                    started.set()
                    release.wait(2.0)

        thread = threading.Thread(target=reader)
        thread.start()
        self.assertTrue(started.wait(2.0))
        self.assertFalse(gate.pause(timeout=0.05))
        release.set()
        thread.join(2.0)

        # Неудавшаяся пауза снимает свой счётчик, иначе live остался бы
        # навсегда замороженным после одного таймаута.
        with gate.live_read("TOP") as allowed:
            self.assertTrue(allowed)

    def test_reset_clears_pauses(self):
        gate = self.gate_factory()
        gate.pause()
        gate.pause()
        gate.reset()
        with gate.live_read("TOP") as allowed:
            self.assertTrue(allowed)


class RecordingLive:
    """Минимальный live-просмотр: пишет порядок передачи камер."""

    def __init__(self, pause_ok=True):
        self.events = []
        self.error = None
        self._pause_ok = pause_ok

    def pause(self, timeout=5.0):
        self.events.append("pause")
        return self._pause_ok

    def resume(self):
        self.events.append("resume")


class StepSequencerHandoverTest(unittest.TestCase):
    """Камеры переходят к инспекции ровно один раз за шаг."""

    def _sequencer(self, live):
        from core.step_stages import StepSequencer

        return StepSequencer(live, settle_seconds=0, trace_seconds=0)

    @property
    def sequence_error(self):
        from core.step_stages import StageSequenceError

        return StageSequenceError

    def test_capture_takes_all_cameras_once_per_step(self):
        live = RecordingLive()
        stages = self._sequencer(live)
        stages.enter_motion()
        stages.enter_settle()
        stages.enter_capture(("INPUT_LEFT",))
        stages.enter_analysis()
        stages.enter_capture(("TOP",))
        stages.enter_analysis()
        stages.enter_publish()

        self.assertEqual(live.events, ["pause"])
        self.assertTrue(stages.static)
        # Инспекция забирает камеры целиком: частичного владения нет.
        self.assertIsNone(stages.static_roles)

        stages.enter_motion()
        self.assertEqual(live.events, ["pause", "resume"])
        self.assertFalse(stages.static)

    def test_failed_handover_raises_and_keeps_live(self):
        live = RecordingLive(pause_ok=False)
        stages = self._sequencer(live)
        stages.enter_motion()
        stages.enter_settle()
        with self.assertRaises(self.sequence_error):
            stages.enter_capture(("TOP",))
        self.assertFalse(stages.static)

    def test_reset_during_handover_is_detected(self):
        class ResettingLive(RecordingLive):
            def __init__(self, stages_ref):
                super().__init__()
                self.stages_ref = stages_ref

            def pause(self, timeout=5.0):
                self.events.append("pause")
                # Сброс шага приходит, пока live отдаёт камеры.
                self.stages_ref[0].reset()
                return True

        holder = []
        live = ResettingLive(holder)
        stages = self._sequencer(live)
        holder.append(stages)
        stages.enter_motion()
        stages.enter_settle()
        with self.assertRaises(self.sequence_error):
            stages.enter_capture(("TOP",))
        # Камеры возвращены live, а не удержаны отменённым шагом.
        self.assertEqual(live.events, ["pause", "resume"])
        self.assertFalse(stages.static)

    def test_empty_capture_keeps_live_running(self):
        live = RecordingLive()
        stages = self._sequencer(live)
        stages.enter_motion()
        stages.enter_settle()
        stages.enter_capture(())
        self.assertEqual(live.events, [])
        self.assertFalse(stages.static)


class DiagnosticsFactoryTest(unittest.TestCase):
    """Форма отчёта диагностики задаётся в одном месте."""

    REQUIRED = (
        "status", "kind", "message", "cameras", "models", "rules", "updated_at",
    )

    @staticmethod
    def _make(*args, **kwargs):
        from core.cycle.diagnostics import make_diagnostics

        return make_diagnostics(*args, **kwargs)

    def test_defaults_are_complete(self):
        report = self._make()
        for key in self.REQUIRED:
            self.assertIn(key, report)
        self.assertEqual(report["status"], "NOT_RUN")
        self.assertIsNone(report["kind"])
        self.assertEqual(report["cameras"], [])
        self.assertEqual(report["models"], [])
        self.assertEqual(report["rules"], [])

    def test_extra_fields_are_passed_through(self):
        report = self._make(
            "PASSED", "SELECTED_MODEL", "готово", selected_role="TOP",
        )
        self.assertEqual(report["selected_role"], "TOP")
        for key in self.REQUIRED:
            self.assertIn(key, report)

    def test_sequences_are_copied(self):
        cameras = [{"role": "TOP"}]
        report = self._make(cameras=cameras)
        cameras.append({"role": "INPUT_LEFT"})
        self.assertEqual(len(report["cameras"]), 1)


class StateMachineSnapshotTest(unittest.TestCase):
    """Снимок автомата атомарен и не зависит от порядка чтения полей."""

    def test_snapshot_matches_properties(self):
        from core.state_machine import State, StateMachine

        machine = StateMachine()
        machine.request_start()
        snapshot = machine.get_snapshot()
        self.assertEqual(snapshot["state"], State.RUNNING.value)
        self.assertFalse(snapshot["exit_requested"])
        self.assertFalse(snapshot["force_exit"])

        machine.request_exit()
        snapshot = machine.get_snapshot()
        self.assertTrue(snapshot["exit_requested"])
        # STOP применяется сразу, чтобы линия начала опустошаться.
        self.assertEqual(snapshot["state"], State.STOPPING.value)


class WindowGeometryMetricsTest(unittest.TestCase):
    """Замеры окон: разбор телеметрии и границы допуска.

    Правило может прислать значения списком, внутри ``items`` или вовсе
    строкой от сбойного детектора — карточка замера обязана пережить всё
    это без исключения.
    """

    @staticmethod
    def _metrics(details):
        from core.rule_report.details.window_geometry import (
            window_geometry_metrics,
        )

        return window_geometry_metrics(details)

    def _by_key(self, details):
        return {item["key"]: item for item in self._metrics(details)}

    def test_empty_details_produce_no_metrics(self):
        self.assertEqual(self._metrics({}), [])

    def test_min_max_checked_against_limits(self):
        metrics = self._by_key({
            "top_limits_px": [10, 20],
            "top_values_px": [12, 25, 9],
        })
        self.assertEqual(metrics["top_px_min"]["value"], "9 px")
        self.assertFalse(metrics["top_px_min"]["ok"])
        self.assertEqual(metrics["top_px_max"]["value"], "25 px")
        self.assertFalse(metrics["top_px_max"]["ok"])

    def test_values_fall_back_to_items(self):
        metrics = self._by_key({
            "top_limits_px": [10, 20],
            "items": [
                {"index": 2, "top_px": 15, "valid": True},
                {"index": 1, "top_px": 11, "valid": True},
            ],
        })
        # Порядок берётся по index, а не по позиции в списке.
        self.assertEqual(metrics["window_1_top_px"]["value"], "11 px")
        self.assertEqual(metrics["window_2_top_px"]["value"], "15 px")

    def test_window_metric_reports_full_range(self):
        metrics = self._by_key({
            "top_limits_px": [10, 20],
            "top_values_px": [12],
        })
        self.assertEqual(metrics["window_1_top_px"]["limit"], "10-20 px")
        self.assertTrue(metrics["window_1_top_px"]["ok"])

    def test_out_of_range_window_is_marked(self):
        metrics = self._by_key({
            "bottom_limits_px": [5, 15],
            "bottom_values_px": [2],
        })
        self.assertFalse(metrics["window_1_bottom_px"]["ok"])

    def test_non_numeric_values_are_skipped(self):
        metrics = self._by_key({
            "top_limits_px": [10, 20],
            "top_values_px": ["мусор", None, 15],
        })
        self.assertNotIn("window_1_top_px", metrics)
        self.assertNotIn("window_2_top_px", metrics)
        self.assertEqual(metrics["window_3_top_px"]["value"], "15 px")

    def test_window_count_is_capped(self):
        from core.rule_report.details.window_geometry import MAX_WINDOWS

        details = {
            "top_limits_px": [1, 40],
            "items": [
                {"index": i, "top_px": i, "valid": True}
                for i in range(1, MAX_WINDOWS + 5)
            ],
        }
        metrics = self._by_key(details)
        self.assertIn(f"window_{MAX_WINDOWS}_top_px", metrics)
        self.assertNotIn(f"window_{MAX_WINDOWS + 1}_top_px", metrics)

    def test_out_of_tolerance_windows_are_counted(self):
        metrics = self._by_key({
            "items": [
                {"index": 1, "top_px": 1, "valid": True},
                {"index": 2, "top_px": 2, "valid": True, "top_fail": True},
                {"index": 3, "valid": False},
            ],
        })
        self.assertEqual(metrics["windows_out_of_tolerance"]["value"], "2")
        self.assertFalse(metrics["windows_out_of_tolerance"]["ok"])

    def test_missing_limits_do_not_crash(self):
        metrics = self._by_key({
            "top_limits_px": [],
            "top_values_px": [12],
            "bottom_limits_px": [None, "x"],
            "bottom_values_px": [7],
        })
        self.assertIsNone(metrics["window_1_top_px"]["ok"])
        self.assertIsNone(metrics["window_1_bottom_px"]["ok"])


if __name__ == "__main__":
    unittest.main()
