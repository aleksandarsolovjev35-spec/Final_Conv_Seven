"""Снимок линии для HMI.

Часть ``ProductionCycle``: статус, анализ кадра и публикация в монитор.
"""

import time


class CycleStatusMixin:
    """Телеметрия и публикация кадров/статуса в UI."""


    # Анализ кадра по группам камер (ВХОД / КОНТРОЛЬ +4)

    def _empty_frame_analysis_entry(self) -> dict:
        return {
            "part_id": None,
            "rule_results": [],
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
        """Сохранить итог стадии в клетку её группы камер.

        Правая панель UI показывает анализ выбранной оператором камеры,
        поэтому результаты хранятся раздельно для ВХОДА и КОНТРОЛЯ +4.
        """
        self._frame_analysis_groups[group] = {
            "part_id": part_id,
            "rule_results": list(getattr(result, "rule_results", None) or []),
            "updated_at": time.time(),
        }


    def _active_frame_analysis_group(self) -> str:
        """Группа камер, чей анализ показывать: за выбранной камерой UI."""
        input_roles = set(self.inspector.INPUT_ROLES)
        try:
            role = self._get_active_camera_role()
        except Exception:
            role = None
        if role in input_roles:
            return "INPUT"
        if role is not None:
            return "SPIDER"
        # Камера ещё не выбрана: последняя обновлённая группа.
        updated = {
            name: entry.get("updated_at") or 0
            for name, entry in self._frame_analysis_groups.items()
        }
        if any(updated.values()):
            return max(updated, key=updated.get)
        return "INPUT"


    # Живой просмотр камер

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
            # Панель следует за камерой, выбранной оператором: анализ
            # меняется при каждом переключении камеры в рабочем цикле.
            # Показываются только правила и замеры этой камеры, а не
            # всей группы (INPUT / SPIDER / TOP).
            group = self._active_frame_analysis_group()
            entry = self._frame_analysis_groups.get(group) or self._empty_frame_analysis_entry()
            stage_label = "ВХОД" if group == "INPUT" else "КОНТРОЛЬ +4"
            try:
                active_role = self._get_active_camera_role()
            except Exception:
                active_role = None
            return {
                "available": True,
                "kind": "CYCLE",
                "role": active_role,
                "stage": stage_label,
                "part_id": entry["part_id"],
                "rules": self._rule_report_rows(
                    entry["rule_results"], role=active_role,
                ),
                "updated_at": entry["updated_at"],
            }

        if selected_report:
            # Ручной анализ уже снимает и считает только выбранную камеру
            # (rules_for_role + capture_single), поэтому extra-filter не нужен.
            return {
                "available": True,
                "kind": "SELECTED",
                "role": (
                    report.get("selected_role")
                    or self._selected_analysis_role
                ),
                "part_id": None,
                "rules": [dict(item) for item in report.get("rules", [])],
                "updated_at": report.get("updated_at"),
            }

        return {
            "available": False,
            "kind": None,
            "role": None,
            "part_id": None,
            "rules": [],
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
            "process": dict(self._process),
            "diagnostic_allowed": diagnostic_allowed,
            "diagnostic_busy": operation_busy,
            "controls": controls,
            "selected_analysis": {
                "active": self._selected_analysis_active,
                "role": self._selected_analysis_role,
            },
            # Inspection забирает все камеры на exclusive-блок
            # CAPTURE…PUBLISH. Live возобновляется только на MOTION.
            "live": {
                "running": self.live.running,
                "streaming": self.live.running,
                "static": self.stages.static,
                "static_roles": list(self.stages.static_roles or ()),
                "all_roles_static": self.stages.static and self.stages.static_roles is None,
                "fps": self._current_live_fps(),
            },
            "frame_analysis": self._build_frame_analysis(state_name),
        }

        if self.jog is not None:
            state_ok = (
                sm_snap["state"] in self.JOG_ALLOWED_STATES
            )
            status["jog"] = {
                "active":      bool(self.jog_active and state_ok),
                "can_enter":   self.can_enter_jog(),
                "busy":        self.jog.status["busy"],
                "live_fps":    self._current_live_fps(),
            }
        else:
            status["jog"] = {
                "active":      False,
                "can_enter":   False,
                "busy":        False,
            }

        return status


    def _refresh_monitor(self, frames: dict | None = None):
        """Публикация в HMI. Сбой UI не должен ронять физический шаг."""
        if not self.monitor:
            return
        try:
            status = self._build_status()
            if frames:
                self.monitor.update(
                    frames=frames,
                    vision_results=self._last_vision_results,
                    rule_results=self._last_rule_results,
                    line_status=status,
                    recent_parts=list(self.recent_parts),
                )
            else:
                self.monitor.update(
                    line_status=status,
                    recent_parts=list(self.recent_parts),
                )
        except Exception as exc:
            print(f"[UI] Не удалось опубликовать статус: {exc}")
