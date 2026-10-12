"""Диагностика камер и правил.

Часть ``ProductionCycle``. Доступна только на пустой линии в IDLE/STOPPED.
"""

import time

from core.rule_report import build_rule_report_row


def make_diagnostics(
    status: str = "NOT_RUN",
    kind=None,
    message: str = "Проверки ещё не запускались",
    *,
    cameras=None,
    models=None,
    rules=None,
    updated_at=None,
    **extra,
) -> dict:
    """Снимок диагностики для HMI.

    Единственное место, где задаётся форма этого словаря: UI полагается на
    полный набор ключей, поэтому пустые списки подставляются всегда, а не
    по месту вызова.
    """
    report = {
        "status": status,
        "kind": kind,
        "message": message,
        "cameras": list(cameras or []),
        "models": list(models or []),
        "rules": list(rules or []),
        "updated_at": updated_at,
    }
    report.update(extra)
    return report


class CycleDiagnosticsMixin:
    """Предстартовые проверки без движения линии."""

    def diagnostic_check_cameras(self) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if not self._prestart_diagnostic_allowed():
                return False
            self._set_diagnostic_running("CAMERAS", "Проверка семи камер")
            self._set_process("CAMERA_DIAGNOSTIC", "Проверка семи камер")
            # После JOG драйвер может вернуть устаревший кадр из буфера.
            # См. комментарий в _stage_capture().
            self.cameras.drain_buffers()
            frames = self.cameras.capture_all()
            camera_rows = []
            for role, frame in frames.items():
                height, width = frame.shape[:2]
                camera_rows.append({
                    "role": role,
                    "ok": True,
                    "width": int(width),
                    "height": int(height),
                })
            self._last_vision_results = {}
            self._last_rule_results = []
            self._diagnostics = make_diagnostics(
                "PASSED", "CAMERAS",
                f"Камеры: {len(camera_rows)}/{len(camera_rows)} OK",
                cameras=camera_rows,
                updated_at=time.time(),
            )
            self._set_process("DIAGNOSTIC_DONE", "Семь камер проверены")
            self._refresh_monitor(frames)
            return True
        except Exception as exc:
            self._set_diagnostic_error("CAMERAS", exc)
            self._handle_fault(f"Ошибка проверки камер: {exc}")
            raise
        finally:
            self._operation_lock.release()

    def diagnostic_check_vision_rules(self) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            return False
        try:
            if not self._prestart_diagnostic_allowed():
                return False
            self._set_diagnostic_running(
                "VISION_RULES",
                "Камеры -> модели -> правила дефектов",
            )
            self._set_process(
                "VISION_RULE_DIAGNOSTIC",
                "Запуск всех моделей и правил дефектов без движения линии",
            )
            # После JOG драйвер может вернуть устаревший кадр из буфера.
            # См. комментарий в _stage_capture().
            self.cameras.drain_buffers()
            frames = self.cameras.capture_all()
            vision_results, rule_results, model_rows = (
                self.inspector.evaluate_all(frames)
            )
            rule_rows = [
                self._rule_report_row(result)
                for result in rule_results
            ]
            camera_rows = []
            for role, frame in frames.items():
                height, width = frame.shape[:2]
                camera_rows.append({
                    "role": role,
                    "ok": True,
                    "width": int(width),
                    "height": int(height),
                    "detections": len(vision_results.get(role, [])),
                })
            self._last_vision_results = vision_results
            self._last_rule_results = rule_results
            triggered = sum(row["triggered"] for row in rule_rows)
            self._diagnostics = make_diagnostics(
                "PASSED", "VISION_RULES",
                (
                    f"Модели: {len(model_rows)} исправны; "
                    f"правил: {len(rule_rows)}, сработало: {triggered}"
                ),
                cameras=camera_rows,
                models=model_rows,
                rules=rule_rows,
                updated_at=time.time(),
            )
            self._set_process(
                "DIAGNOSTIC_DONE",
                "Модели и правила дефектов выполнены",
            )
            self._refresh_monitor(frames)
            return True
        except Exception as exc:
            self._set_diagnostic_error("VISION_RULES", exc)
            self._handle_fault(f"Ошибка проверки моделей и правил: {exc}")
            raise
        finally:
            self._operation_lock.release()

    def _prestart_diagnostic_allowed(self) -> bool:
        return (
            self.state in ("IDLE", "STOPPED")
            and not self.parts
            and not self.exit_requested
            and not self._cancel_motion.is_set()
            and not (self.jog is not None and self.jog.busy)
        )

    def _set_diagnostic_running(self, kind: str, message: str):
        self._diagnostics = make_diagnostics(
            "RUNNING", kind, message, updated_at=time.time(),
        )
        self._refresh_monitor()

    def _set_diagnostic_error(self, kind: str, exc: Exception):
        self._diagnostics = make_diagnostics(
            "ERROR", kind, f"{type(exc).__name__}: {exc}",
            updated_at=time.time(),
        )
        self._refresh_monitor()

    @staticmethod
    def _rule_report_row(result) -> dict:
        return build_rule_report_row(result)
