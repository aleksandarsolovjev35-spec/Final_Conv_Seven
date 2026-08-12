from domain.defect_rules import InputPartPresenceRule

from vision.overlay.raw_overlay import RawOverlay

from inspection.result import InspectionResult
from inspection.run_report import (
    prepare_presence_result,
    prepare_rule_results,
)


class Inspector:
    """Выполняет инспекцию по одному свежему кадру."""

    INPUT_ROLES = ("INPUT_LEFT", "INPUT_RIGHT")
    SPIDER_ROLES = (
        "SPIDER_LEFT", "SPIDER_RIGHT",
        "SPIDER_IN", "SPIDER_OUT",
        "TOP",
    )

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

    def inspect_input(
        self,
        part_id: int,
        step: int,
        frames,
    ) -> InspectionResult:
        # Строгий порядок одной стадии: кадры -> модели -> проверка
        # наличия (gate) -> геометрия/defect rules -> разметка -> результат.
        frames = self._stage_frames(frames, self.INPUT_ROLES, "input")
        self._notify_progress(
            "INPUT_MODELS",
            "INPUT: запуск моделей по свежему кадру",
            part_id=part_id,
            roles=self.INPUT_ROLES,
        )
        vision_results = self._run_vision(frames, self.INPUT_ROLES)

        self._notify_progress(
            "INPUT_PRESENCE",
            "INPUT: проверка наличия корпуса",
            part_id=part_id,
            roles=self.INPUT_ROLES,
        )
        presence_result = prepare_presence_result(
            self._evaluate_part_presence(vision_results)
        )

        if bool(presence_result.details.get("empty_tray")):
            self._notify_progress(
                "INPUT_DECISION",
                "INPUT: лоток пуст, решение наличия принято",
                part_id=part_id,
                roles=self.INPUT_ROLES,
            )
            return InspectionResult(
                stage="input",
                defects=[],
                vision_results=vision_results,
                rule_results=[presence_result],
                annotated={},
                raw_frames=frames,
                raw_overlay_frames={},
                is_empty_tray=True,
            )

        self._notify_progress(
            "INPUT_GEOMETRY",
            "INPUT: построение геометрии и измерений",
            part_id=part_id,
            roles=self.INPUT_ROLES,
        )
        defect_results = prepare_rule_results(
            self.decision.evaluate_rules_detailed(
                self.decision.rules_for_roles(self.INPUT_ROLES),
                vision_results,
                frames=frames,
            )
        )
        self._notify_progress(
            "INPUT_DECISION",
            "INPUT: решение правил сформировано",
            part_id=part_id,
            roles=self.INPUT_ROLES,
        )
        return self._build_result(
            stage="input",
            part_id=part_id,
            step=step,
            frames=frames,
            vision_results=vision_results,
            rule_results=[presence_result] + defect_results,
            markup_rule_results=defect_results,
        )

    def inspect_spider(
        self,
        part_id: int,
        step: int,
        frames,
    ) -> InspectionResult:
        frames = self._stage_frames(frames, self.SPIDER_ROLES, "spider")
        self._notify_progress(
            "SPIDER_MODELS",
            "SPIDER/TOP: запуск моделей по свежему кадру",
            part_id=part_id,
            roles=self.SPIDER_ROLES,
        )
        vision_results = self._run_vision(frames, self.SPIDER_ROLES)

        self._notify_progress(
            "SPIDER_GEOMETRY",
            "SPIDER/TOP: построение геометрии и измерений",
            part_id=part_id,
            roles=self.SPIDER_ROLES,
        )
        rule_results = prepare_rule_results(
            self.decision.evaluate_rules_detailed(
                self.decision.rules_for_roles(self.SPIDER_ROLES),
                vision_results,
                frames=frames,
            )
        )
        self._notify_progress(
            "SPIDER_DECISION",
            "SPIDER/TOP: окончательное решение правил сформировано",
            part_id=part_id,
            roles=self.SPIDER_ROLES,
        )
        return self._build_result(
            stage="spider",
            part_id=part_id,
            step=step,
            frames=frames,
            vision_results=vision_results,
            rule_results=rule_results,
            markup_rule_results=rule_results,
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
        progress_prefix = "INPUT" if stage == "input" else "SPIDER"
        self._notify_progress(
            f"{progress_prefix}_FRAME_RECORD",
            f"{progress_prefix}: запись кадра и геометрической разметки",
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
            f"{progress_prefix}_FRAME_RECORDED",
            f"{progress_prefix}: кадр и разметка подготовлены",
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
        rule = InputPartPresenceRule(thresholds=self.decision.thresholds)
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
