from domain.defect_rules import PartPresenceRule

from vision.overlay.raw_overlay import RawOverlay

from inspection.result import InspectionResult
from inspection.rule_log import log_rule_results


class Inspector:
    """Выполняет инспекцию по одному свежему кадру (трёхкамерная линия).

    Одна стадия: все три камеры смотрят в зону инспекции (+0):
    LEFT/RIGHT — разновысотность и раковины окон, MIDDLE — стекло и сварка.
    """

    INSPECT_ROLES = ("LEFT", "MIDDLE", "RIGHT")
    # Камеры-маркеры наличия детали (окна видят только боковые камеры).
    PRESENCE_ROLES = ("LEFT", "RIGHT")

    def __init__(self, vision, decision, recorder, on_progress=None):
        self.vision = vision
        self.decision = decision
        self.recorder = recorder
        # Наблюдатель не участвует в принятии решения: его исключения не
        # должны ломать инспекцию. ProductionCycle использует callback для
        # отображения внутренних этапов в HMI.
        self.on_progress = on_progress

    def set_progress_callback(self, callback):
        self.on_progress = callback

    # Публичный API для диагностики без движения линии.
    #
    # ProductionCycle прогоняет те же модели и правила, что и рабочий шаг,
    # но не создаёт Part и не пишет архив. Чтобы предстартовая проверка и
    # production не разошлись в трактовке результатов, порядок «наличие
    # корпуса -> defect rules» и проверка контракта результата живут здесь,
    # а не в вызывающем коде.

    def evaluate_presence(self, vision_results: dict, stage: str = "presence"):
        """Проверить наличие детали и залогировать результат в консоль."""
        result = self._evaluate_part_presence(vision_results)
        log_rule_results(stage, [result])
        return result

    def evaluate_rules(
        self,
        vision_results: dict,
        frames=None,
        roles=None,
        stage: str = "rules",
    ):
        """Выполнить defect rules и залогировать результаты в консоль.

        ``roles`` ограничивает набор правил камерами стадии; без него
        берутся все активные правила.
        """
        rules = (
            self.decision.rules_for_roles(roles)
            if roles is not None
            else self.decision.rules
        )
        results = self.decision.evaluate_rules_detailed(
            rules, vision_results, frames=frames,
        )
        log_rule_results(stage, results)
        return results

    def evaluate_all(self, frames: dict):
        """Полный прогон диагностики по готовым кадрам.

        Возвращает ``(vision_results, rule_results, model_rows)``. Пустая
        ячейка обрывает цепочку на наличии детали — ровно как в рабочем
        шаге, где defect rules по пустой ячейке не считаются.
        """
        vision_results = self.vision.process_all(frames)
        presence_result = self.evaluate_presence(vision_results, "diagnostic")
        rule_results = [presence_result]
        if not presence_result.details.get("empty_tray"):
            rule_results.extend(
                self.evaluate_rules(
                    vision_results, frames=frames, stage="diagnostic",
                )
            )
        return vision_results, rule_results, self.model_health()

    def model_health(self) -> list:
        """Строки состояния моделей последнего прогона для HMI."""
        summary = []
        for row in self.vision.last_health or []:
            if not isinstance(row, dict):
                continue
            summary.append({
                "role": row.get("role"),
                "model": row.get("model"),
                "ok": bool(row.get("ok")),
                "elapsed_ms": float(row.get("elapsed_ms") or 0.0),
                "detections": int(row.get("detections") or 0),
                "error": row.get("error"),
            })
        return summary

    def _notify_progress(self, phase, label, *, part_id=None, roles=()):
        callback = self.on_progress
        if not callable(callback):
            return
        try:
            callback(
                phase,
                label,
                part_id=part_id,
                roles=tuple(roles or ()),
            )
        except Exception as exc:
            print(f"[INSPECTION] Ошибка отображения этапа {phase}: {exc}")

    def inspect(
        self,
        part_id: int,
        step: int,
        frames,
    ) -> InspectionResult:
        # Строгий порядок единственной стадии: кадры -> модели ->
        # проверка наличия (gate) -> геометрия/defect rules -> разметка ->
        # результат.
        frames = self._stage_frames(frames, self.INSPECT_ROLES, "inspect")
        self._notify_progress(
            "INSPECT_MODELS",
            "ИНСПЕКЦИЯ: запуск моделей по свежему кадру",
            part_id=part_id,
            roles=self.INSPECT_ROLES,
        )
        vision_results = self._run_vision(frames, self.INSPECT_ROLES)

        self._notify_progress(
            "INSPECT_PRESENCE",
            "ИНСПЕКЦИЯ: проверка наличия детали",
            part_id=part_id,
            roles=self.PRESENCE_ROLES,
        )
        presence_result = self.evaluate_presence(
            vision_results, f"INSPECT part={part_id}",
        )

        if bool(presence_result.details.get("empty_tray")):
            self._notify_progress(
                "INSPECT_DECISION",
                "ИНСПЕКЦИЯ: ячейка пуста, решение наличия принято",
                part_id=part_id,
                roles=self.INSPECT_ROLES,
            )
            return InspectionResult(
                stage="inspect",
                defects=[],
                vision_results=vision_results,
                rule_results=[presence_result],
                annotated={},
                raw_frames=frames,
                raw_overlay_frames={},
                is_empty_tray=True,
            )

        # Наличие подтверждено: теперь корпус можно показывать в линии.
        # Пустой лоток до этой точки «призрака» не создаёт.
        self._notify_progress(
            "INSPECT_PRESENT",
            "ИНСПЕКЦИЯ: наличие детали подтверждено",
            part_id=part_id,
            roles=self.INSPECT_ROLES,
        )
        self._notify_progress(
            "INSPECT_GEOMETRY",
            "ИНСПЕКЦИЯ: построение геометрии и измерений",
            part_id=part_id,
            roles=self.INSPECT_ROLES,
        )
        defect_results = self.evaluate_rules(
            vision_results,
            frames=frames,
            roles=self.INSPECT_ROLES,
            stage=f"INSPECT part={part_id}",
        )
        self._notify_progress(
            "INSPECT_DECISION",
            "ИНСПЕКЦИЯ: решение правил сформировано",
            part_id=part_id,
            roles=self.INSPECT_ROLES,
        )
        return self._build_result(
            stage="inspect",
            part_id=part_id,
            step=step,
            frames=frames,
            vision_results=vision_results,
            rule_results=[presence_result] + defect_results,
            markup_rule_results=defect_results,
        )

    @staticmethod
    def _stage_frames(frames, roles, stage: str) -> dict:
        if not isinstance(frames, dict):
            raise RuntimeError(f"{stage}: кадры должны быть словарём")
        missing = set(roles) - set(frames)
        if missing:
            raise RuntimeError(
                f"Missing {stage} camera frames: {sorted(missing)}"
            )
        return {role: frames[role] for role in roles}

    def _run_vision(self, frames: dict, roles: tuple):
        vision_results = self.vision.process_all(frames)
        missing = set(roles) - set(vision_results)
        if missing:
            raise RuntimeError(f"Missing vision results: {sorted(missing)}")
        return vision_results

    def _build_result(
        self,
        *,
        stage: str,
        part_id: int,
        step: int,
        frames: dict,
        vision_results: dict,
        rule_results: list,
        markup_rule_results: list | None = None,
    ) -> InspectionResult:
        defects = [result.defect for result in rule_results if result.triggered]

        markup = (
            markup_rule_results
            if markup_rule_results is not None
            else rule_results
        )
        self._notify_progress(
            "INSPECT_FRAME_RECORD",
            "ИНСПЕКЦИЯ: запись кадра и геометрической разметки",
            part_id=part_id,
            roles=frames.keys(),
        )
        annotated = self.recorder.process(
            part_id=part_id,
            step=step,
            frames=frames,
            rule_results=markup,
        )
        raw_overlay_frames = self._raw_overlays(frames, vision_results)
        self._notify_progress(
            "INSPECT_FRAME_RECORDED",
            "ИНСПЕКЦИЯ: кадр и разметка подготовлены",
            part_id=part_id,
            roles=frames.keys(),
        )
        return InspectionResult(
            stage=stage,
            defects=defects,
            vision_results=vision_results,
            rule_results=rule_results,
            annotated=annotated,
            raw_frames=frames,
            raw_overlay_frames=raw_overlay_frames,
            is_empty_tray=False,
        )

    def _evaluate_part_presence(self, vision_results: dict):
        rule = PartPresenceRule(thresholds=self.decision.thresholds)
        if not rule.enabled:
            raise RuntimeError("part_presence rule is disabled")
        return rule.check(vision_results)

    @staticmethod
    def _raw_overlays(stage_frames: dict, vision_results: dict) -> dict:
        raw_overlay_frames = {}
        for role, frame in stage_frames.items():
            detections = vision_results.get(role, [])
            raw_overlay_frames[role] = (
                RawOverlay.render(frame, detections)
                if detections
                else frame.copy()
            )
        return raw_overlay_frames
