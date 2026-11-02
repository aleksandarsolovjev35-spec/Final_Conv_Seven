"""Снимок линии для HMI.

Часть ``ProductionCycle``: статус, анализ кадра и публикация в монитор.
"""


class CycleStatusMixin:
    """Телеметрия и публикация кадров/статуса в UI."""

    # Живой просмотр камер

    def _get_active_camera_role(self):
        server = getattr(self.monitor, "server", None)
        if server is None:
            return None
        return getattr(server, "active_camera_role", None)

    def _current_live_fps(self) -> float:
        return self.live.fps

    def _line_parts(self, parts_snapshot: list, step_snapshot: int) -> list:
        """Позиции корпусов на ленте для мнемосхемы HMI.

        Показывает только корпуса, чьё наличие подтверждено правилом
        part_presence: новый корпус входит в учёт до анализа, но пустой
        лоток не должен рисовать «призрак» в зоне входа.
        """
        line_parts = []
        for part in parts_snapshot:
            if not part.present:
                continue
            position = step_snapshot - part.step_created
            position = max(0, min(position, self.OFFSET_REJECT))
            # На шаге передачи маршрут уже выставлен: GOOD проходит через
            # DIST1=0, BAD/CLEANUP — через DIST1=340 и DIST2.
            line_parts.append({
                "id": part.id,
                "position": position,
                "category": part.route_category,
                "dropping": self._pending_drop is part,
            })
        return line_parts

    def _build_controls(self, snapshot: dict) -> tuple:
        """Доступность кнопок HMI по одному снимку состояния.

        Возвращает ``(controls, diagnostic_allowed)``. Все предикаты
        считаются от одного снимка, поэтому кнопки не могут описывать
        разные моменты времени.
        """
        state_name = snapshot["state"]
        operation_busy = snapshot["operation_busy"]
        jog_busy = snapshot["jog_busy"]
        jog_error = snapshot["jog_error"]
        exit_requested = snapshot["exit_requested"]
        has_parts = snapshot["has_parts"]

        idle = state_name in ("IDLE", "STOPPED")
        # Общее условие «линия стоит пустой и ничем не занята»: от него
        # зависят и пуск, и все предстартовые проверки.
        line_ready = (
            idle
            and not has_parts
            and not jog_busy
            and not jog_error
            and not operation_busy
            and not self._selected_analysis_active
            and not exit_requested
        )
        diagnostic_allowed = (
            line_ready and not self._cancel_motion.is_set()
        )

        controls = {
            "start": line_ready,
            "stop": state_name in ("RUNNING", "PAUSED") and not operation_busy,
            "pause": (
                state_name == "RUNNING"
                and not operation_busy
                and not exit_requested
            ),
            "resume": (
                state_name == "PAUSED"
                and not operation_busy
                and not jog_busy
                and not jog_error
                and not exit_requested
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
                and not exit_requested
            ),
            "selected_model_analysis": diagnostic_allowed,
            "selected_model_release": (
                self._selected_analysis_active
                and idle
                and not operation_busy
            ),
            "distributor_diagnostic": diagnostic_allowed,
            "camera_diagnostic": diagnostic_allowed,
            "vision_rule_diagnostic": diagnostic_allowed,
        }
        return controls, diagnostic_allowed

    def _build_jog_status(self, state_name: str) -> dict:
        if self.jog is None:
            return {"active": False, "can_enter": False, "busy": False}
        return {
            "active": bool(
                self.jog_active and state_name in self.JOG_ALLOWED_STATES
            ),
            "can_enter": self.can_enter_jog(),
            "busy": self.jog.status["busy"],
            "live_fps": self._current_live_fps(),
        }

    def _build_live_status(self) -> dict:
        # Inspection забирает все камеры на exclusive-блок
        # CAPTURE…PUBLISH. Live возобновляется только на MOTION.
        static = self.stages.static
        return {
            "running": self.live.running,
            "streaming": self.live.running,
            "static": static,
            "static_roles": list(self.stages.static_roles or ()),
            "all_roles_static": static,
            "fps": self._current_live_fps(),
        }

    def _build_status(self) -> dict:
        sm_snap = self.sm.get_snapshot()

        # Статус собирается из потоков UI, пока цикл меняет линию. Снимок
        # списка и шага берётся один раз, иначе in_line и line_parts могли
        # бы описывать разные моменты времени.
        parts_snapshot = list(self.parts)
        step_snapshot = self.current_step
        # В линию для HMI попадают только корпуса с подтверждённым
        # наличием: новый корпус появляется в схеме после проверки
        # наличия, а не до неё (иначе пустой лоток даёт «призрак»).
        visible_parts = [p for p in parts_snapshot if p.present]
        state_name = sm_snap["state"]
        jog_snapshot = self.jog.status if self.jog is not None else {}

        operation_busy = self._operation_lock.locked()
        speed_allowed = (
            state_name in ("IDLE", "STOPPED")
            and not sm_snap["exit_requested"] and not self._shutdown
            and not operation_busy and not jog_snapshot.get("busy", False)
            and not self._selected_analysis_active
        )
        # Проценты на ползунке HMI считаются от максимальной скорости
        # конкретной ленты. Для production это 20000 шаг/с (25 % = 5000).
        speed_min = int(getattr(self.conveyor, "MIN_SPEED", 5000))
        speed_max = int(getattr(self.conveyor, "MAX_SPEED", 20000))
        conveyor_speed = int(self.conveyor.speed)
        speed_percent = (
            max(0, min(100, round(conveyor_speed / speed_max * 100)))
            if speed_max > 0 else 0
        )
        controls, diagnostic_allowed = self._build_controls({
            "state": state_name,
            "exit_requested": sm_snap["exit_requested"],
            "operation_busy": operation_busy,
            "jog_busy": bool(jog_snapshot.get("busy", False)),
            "jog_error": jog_snapshot.get("error") or self.live.error,
            "has_parts": bool(parts_snapshot),
        })

        return {
            "state": state_name,
            "exit_requested": sm_snap["exit_requested"],
            "fault_reason": self._fault_reason,
            "step": step_snapshot,
            "in_line": len(visible_parts),
            "line_parts": self._line_parts(visible_parts, step_snapshot),
            "total": self.part_counter,
            "good": self.good_count,
            "rejected": self.bad_count,
            "cleanup": self.cleanup_count,
            "empty": self.empty_count,
            **self.distributor.status,
            "conveyor_speed": conveyor_speed,
            "conveyor_speed_percent": speed_percent,
            "conveyor_speed_min": speed_min,
            "conveyor_speed_max": speed_max,
            "speed_allowed": speed_allowed,
            "inspection_timings": {
                "settle_time": round(
                    float(self.stages.settle_seconds), 2,
                ),
                "review_time": round(
                    float(self.review_seconds), 2,
                ),
                "settle_max": 5.0,
                "review_max": 30.0,
            },
            "timings_allowed": speed_allowed,
            "process": dict(self._process),
            "diagnostic_allowed": diagnostic_allowed,
            "diagnostic_busy": operation_busy,
            "controls": controls,
            "selected_analysis": {
                "active": self._selected_analysis_active,
                "role": self._selected_analysis_role,
            },
            "live": self._build_live_status(),
            "jog": self._build_jog_status(state_name),
        }

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
