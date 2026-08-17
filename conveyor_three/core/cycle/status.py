"""Снимок линии для HMI (3 камеры).

Часть ``ProductionCycle``: телеметрия процесса, анализ кадра, статус.
"""

from __future__ import annotations

import time

from core.state_machine import State

class CycleStatusMixin:
    """Телеметрия и публикация кадров/статуса в UI."""

    def _set_process(
        self,
        phase: str,
        label: str,
        *,
        part_id=None,
        positions=None,
        conveyor_status=None,
        capture_roles=None,
    ):
        self._process_revision += 1
        self._process = {
            "phase": phase,
            "label": label,
            "step": self.current_step,
            "part_id": part_id,
            "positions": list(positions or []),
            "conveyor": dict(conveyor_status or {}),
            # Роли только что захваченных камер. UI использует это, чтобы
            # оператор видел, какая стадия Part действительно снималась.
            "capture_roles": list(capture_roles or []),
            "inspection_roles": list(self._inspection_display_roles),
            "revision": self._process_revision,
            "updated_at": time.time(),
        }
        self._refresh_monitor()

    def _on_inspection_progress(
        self,
        phase: str,
        label: str,
        *,
        part_id=None,
        roles=(),
    ):
        """Показать внутренний этап инспекции в статусе линии.

        Callback наблюдательный: решение уже выполняется Inspector'ом, а
        этот метод только публикует текущую фазу для HMI и не меняет порядок
        обработки.
        """
        self._set_process(
            str(phase or "").upper(),
            label,
            part_id=part_id,
            positions=[self.OFFSET_INSPECT],
            capture_roles=roles,
        )

    def _on_conveyor_progress(self, status: dict):
        current = self._process
        conveyor_info = dict(status or {})
        # Expose speed for frontend animation timing (higher = faster motion)
        try:
            conveyor_info["speed"] = int(getattr(self.conveyor, "speed", 20000))
            conveyor_info["normal_steps"] = int(getattr(self.conveyor, "steps_per_division", 19048))
        except Exception:
            conveyor_info["speed"] = 20000
        self._set_process(
            "CONVEYOR_MOVING",
            "Лента перемещает корпуса на следующую позицию",
            part_id=current.get("part_id"),
            positions=range(self.OFFSET_REJECT + 1),
            conveyor_status=conveyor_info,
        )

    # Public API

    def _empty_frame_analysis_entry(self) -> dict:
        return {
            "part_id": None,
            "rule_results": [],
            "models": [],
            "picture_run": None,
            "picture_reason": None,
            "updated_at": None,
        }

    def _empty_frame_analysis_groups(self) -> dict:
        return {
            group: self._empty_frame_analysis_entry()
            for group in self.FRAME_ANALYSIS_GROUPS
        }

    def _reset_frame_analysis(self):
        self._frame_analysis_groups = self._empty_frame_analysis_groups()

    def _record_frame_analysis(self, group: str, part_id, result):
        """Сохранить итог стадии в клетку анализа кадра HMI."""
        rows = getattr(result, "model_health", None)
        if not isinstance(rows, list) or not rows:
            vision = getattr(self.inspector, "vision", None)
            rows = getattr(vision, "last_health", None) or []
        consensus = getattr(result, "consensus", None) or {}

        # Подготовить модели с детальной информацией о прогоне
        model_details = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            model_details.append({
                "role": item.get("role"),
                "model": item.get("model"),
                "ok": item.get("ok"),
                "runs": item.get("runs"),
                "elapsed_ms": item.get("elapsed_ms"),
                "elapsed_total_ms": item.get("elapsed_total_ms"),
                "detections": item.get("detections"),
                "detections_by_run": item.get("detections_by_run", []),
                "error": item.get("error"),
            })

        self._frame_analysis_groups[group] = {
            "part_id": part_id,
            "rule_results": list(result.rule_results),
            "models": model_details,
            "picture_run": (
                int(consensus.get("picture_run"))
                if consensus.get("picture_run") else None
            ),
            "picture_reason": (
                str(consensus.get("picture_reason"))
                if consensus.get("picture_reason") else None
            ),
            "updated_at": time.time(),
        }

    def _on_stage_change(self, previous, current, elapsed: float):
        """Печать границы фаз шага: видно, где именно проводится время."""
        print(
            f"[STAGE] {previous.value} -> {current.value} "
            f"(предыдущая фаза {elapsed:.2f} с)"
        )

    def _on_state_change(self, old, new, action: str):
        if new == State.STOPPING:
            self._set_process("DRAINING", "Остановка")
        elif new == State.STOPPED:
            # Линия пуста: последние кадры с разметкой остаются на экране,
            # пока оператор не войдёт в JOG или не запустит цикл заново.
            self.stages.reset()
            self.live.stop()
            self._set_process("STOPPED", "Линия остановлена и пуста")
        elif new == State.FAULT:
            self._set_process("FAULT", "Цикл остановлен из-за ошибки")
        else:
            self._refresh_monitor()

    # JOG mode

    def _get_active_camera_role(self):
        server = getattr(self.monitor, "server", None)
        if server is None:
            return None
        return getattr(server, "active_camera_role", None)

    def _current_live_fps(self) -> float:
        return self.live.fps

    # Monitor

    def _build_frame_analysis(self, state_name: str) -> dict:
        report = self._diagnostics
        selected_report = report.get("kind") == "SELECTED_MODEL"

        if state_name in ("RUNNING", "STOPPING"):
            # Одна группа анализа: вся инспекция происходит на +0.
            # Показываются только правила и замеры выбранной камеры.
            entry = self._frame_analysis_groups["INPUT"]
            stage_label = "ИНСПЕКЦИЯ +0"
            try:
                active_role = self._get_active_camera_role()
            except Exception:
                active_role = None
            models = [
                dict(item) for item in entry["models"]
                if not active_role or item.get("role") == active_role
            ]
            rules = self._rule_report_rows(
                entry["rule_results"], role=active_role,
            )
            has_data = (
                entry["updated_at"] is not None
                and bool(
                    rules
                    or models
                    or entry["rule_results"]
                    or entry["models"]
                )
            )
            role_suffix = f" · {active_role}" if active_role else ""
            if has_data:
                message = (
                    f"{stage_label}{role_suffix}: итог по свежему кадру; "
                    "правила считаются по единственному замеру"
                )
            else:
                message = (
                    f"{stage_label}{role_suffix}: "
                    "результатов анализа пока нет"
                )
            return {
                "available": True,
                "kind": "CYCLE",
                "active": True,
                "title": "АНАЛИЗ ТЕКУЩЕГО КАДРА",
                "role": active_role,
                "group": "INPUT",
                "stage": stage_label,
                "part_id": entry["part_id"],
                "message": message,
                "models": models,
                "rules": rules,
                "picture_run": entry.get("picture_run"),
                "picture_reason": entry.get("picture_reason"),
                "updated_at": entry["updated_at"],
            }

        if selected_report:
            # Ручной анализ уже снимает и считает только выбранную камеру
            # (rules_for_role + capture_single), поэтому extra-filter не нужен.
            return {
                "available": True,
                "kind": "SELECTED",
                "active": self._selected_analysis_active,
                "title": "АНАЛИЗ КАДРА",
                "role": (
                    report.get("selected_role")
                    or self._selected_analysis_role
                ),
                "part_id": None,
                "message": report.get("message") or "Анализ кадра",
                "status": report.get("status"),
                "cameras": [dict(item) for item in report.get("cameras", [])],
                "models": [dict(item) for item in report.get("models", [])],
                "rules": [dict(item) for item in report.get("rules", [])],
                "picture_run": report.get("picture_run"),
                "picture_reason": report.get("picture_reason"),
                "updated_at": report.get("updated_at"),
            }

        return {
            "available": False,
            "kind": None,
            "active": False,
            "title": None,
            "role": None,
            "part_id": None,
            "message": None,
            "models": [],
            "rules": [],
            "picture_run": None,
            "picture_reason": None,
            "updated_at": None,
        }

    def _build_status(self) -> dict:
        dist = self.distributor.status

        sm_snap = self.sm.get_snapshot()

        # Статус собирается из потоков UI, пока цикл меняет линию. Снимок
        # списка и шага берётся один раз, иначе in_line и line_parts могли
        # бы описывать разные моменты времени.
        parts_snapshot = list(self.parts)
        step_snapshot = self.current_step

        line_parts = []
        for part in parts_snapshot:
            position = step_snapshot - part.step_created
            position = max(0, min(position, self.OFFSET_REJECT))
            # На шаге передачи маршрут уже выставлен: GOOD проходит через
            # DIST1=0, BAD/CLEANUP — через DIST1=340 и DIST2.
            dropping = self._pending_drop is not None and self._pending_drop is part
            line_parts.append({
                "id": part.id,
                "position": position,
                "category": part.route_category,
                # Механического удержания корпуса в этой линии нет.
                "held": False,
                "dropping": dropping,
            })

        state_name = sm_snap["state"]
        operation_busy = self._operation_lock.locked()
        jog_snapshot = self.jog.status if self.jog is not None else {}
        jog_busy = bool(jog_snapshot.get("busy", False))
        jog_error = jog_snapshot.get("error") or self.live.error
        diagnostic_allowed = (
            state_name in ("IDLE", "STOPPED")
            and not parts_snapshot
            and not jog_busy
            and not jog_error
            and not operation_busy
            and not self._cancel_motion.is_set()
            and not self._selected_analysis_active
            and not sm_snap["exit_requested"]
        )
        controls = {
            "start": (
                state_name in ("IDLE", "STOPPED")
                and not parts_snapshot
                and not jog_busy
                and not jog_error
                and not operation_busy
                and not self._selected_analysis_active
                and not sm_snap["exit_requested"]
            ),
            "stop": state_name in ("RUNNING", "PAUSED") and not operation_busy,
            "pause": (
                state_name == "RUNNING"
                and not operation_busy
                and not sm_snap["exit_requested"]
            ),
            "resume": (
                state_name == "PAUSED"
                and not operation_busy
                and not jog_busy
                and not jog_error
                and not sm_snap["exit_requested"]
            ),
            "exit": (
                not self._shutdown
                and not operation_busy
                and not jog_busy
            ),
            "jog_hold": (
                state_name in self.JOG_ALLOWED_STATES
                and self.jog_active
                and not jog_error
                and not operation_busy
                and not self._selected_analysis_active
                and not sm_snap["exit_requested"]
            ),
            "selected_model_analysis": diagnostic_allowed,
            "selected_model_release": (
                self._selected_analysis_active
                and state_name in ("IDLE", "STOPPED")
                and not operation_busy
            ),
            "distributor_diagnostic": diagnostic_allowed,
            "camera_diagnostic": diagnostic_allowed,
            "vision_rule_diagnostic": diagnostic_allowed,
        }

        status = {
            "state": state_name,
            "exit_requested": sm_snap["exit_requested"],
            "fault_reason": self._fault_reason,
            "step": step_snapshot,
            "in_line": len(parts_snapshot),
            "line_parts": line_parts,
            "total": self.part_counter,
            "good": self.good_count,
            "rejected": self.bad_count,
            "cleanup": self.cleanup_count,
            "empty": self.empty_count,
            **dist,
            "axis_position": dist["dist1_position"],
            "axis_max": dist["dist1_max"],
            "distributor_state": dist["dist1_state"],
            "process": dict(self._process),
            "diagnostic_allowed": diagnostic_allowed,
            "diagnostic_busy": operation_busy,
            "controls": controls,
            "selected_analysis": {
                "active": self._selected_analysis_active,
                "role": self._selected_analysis_role,
            },
            # Inspection блокирует live только у захватываемых ролей.
            # Остальные камеры продолжают поток даже на статической фазе.
            "live": {
                "running": self.live.running,
                "streaming": self.live.running,
                "static": self.stages.static,
                "static_roles": list(self.stages.static_roles or ()),
                "all_roles_static": self.stages.static and self.stages.static_roles is None,
                "stage": self.stages.stage.value,
                "fps": self._current_live_fps(),
                "error": self.live.error,
            },
            "frame_analysis": self._build_frame_analysis(state_name),
            "diagnostics": {
                **self._diagnostics,
                "cameras": [dict(item) for item in self._diagnostics["cameras"]],
                "models": [dict(item) for item in self._diagnostics["models"]],
                "rules": [dict(item) for item in self._diagnostics["rules"]],
            },
        }

        if self.jog is not None:
            state_ok = (
                sm_snap["state"] in self.JOG_ALLOWED_STATES
            )
            jog_status = self.jog.status
            status["jog"] = {
                "active":      bool(self.jog_active and state_ok),
                "can_enter":   self.can_enter_jog(),
                "hold_steps":  jog_status["hold_steps"],
                "last_action": jog_status["last_action"],
                "busy":        jog_status["busy"],
                "direction":   jog_status["direction"],
                "error":       jog_error,
                "live_fps":    self._current_live_fps(),
            }
        else:
            status["jog"] = {
                "active":      False,
                "can_enter":   False,
                "hold_steps":  0,
                "last_action": "-",
                "busy":        False,
                "direction":   None,
                "error":       None,
            }

        return status

    def _refresh_monitor(
        self,
        frames: dict | None = None,
        run_frames: list | None = None,
        run_rule_results: list | None = None,
    ):
        if not self.monitor:
            return
        status = self._build_status()
        if frames:
            self.monitor.update(
                frames=frames,
                vision_results=self._last_vision_results,
                rule_results=self._last_rule_results,
                line_status=status,
                recent_parts=list(self.recent_parts),
                run_frames=run_frames,
                run_rule_results=run_rule_results,
            )
        else:
            self.monitor.update(
                line_status=status,
                recent_parts=list(self.recent_parts),
                run_frames=run_frames,
                run_rule_results=run_rule_results,
            )
