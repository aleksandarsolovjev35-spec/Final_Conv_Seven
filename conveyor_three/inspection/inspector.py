from domain.defect_rules import PartPresenceRule

from vision.overlay.raw_overlay import RawOverlay

from inspection.consensus import (
    combine_presence_results,
    combine_rule_results,
    describe_picture_run,
    summarize_model_health,
)
from inspection.result import InspectionResult


class Inspector:
    """Выполняет инспекцию по одному свежему кадру (трёхкамерная линия).

    Одна стадия: все три камеры смотрят в одну зону инспекции (+0):
    NEAR/FAR — разновысотность и раковины окон, MIDDLE — стекло и сварка.
    """

    INSPECT_ROLES = ("NEAR", "MIDDLE", "FAR")
    # Камеры-маркеры наличия детали (окна видят только боковые камеры).
    PRESENCE_ROLES = ("NEAR", "FAR")

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

    # ProductionCycle передаёт один набор кадров как [frames]. Инспектор
    # проверяет этот контракт и обрабатывает единственный элемент.

    def inspect_consensus(
        self,
        part_id: int,
        step: int,
        frame_runs,
        force_bad: bool = False,
    ) -> InspectionResult:
        # Строгий порядок стадии: кадры -> модели -> проверка наличия
        # (gate) -> замеры/defect rules -> разметка -> результат.
        # Все последующие шаги используют ровно этот ``frames`` snapshot.
        frames = self._single_stage_frames(frame_runs)
        self._notify_progress(
            "INSPECT_MODELS",
            "ИНСПЕКЦИЯ: запуск моделей по свежему кадру",
            part_id=part_id,
            roles=self.INSPECT_ROLES,
        )
        vision_results, model_health = self._run_vision(frames)

        self._notify_progress(
            "INSPECT_PRESENCE",
            "ИНСПЕКЦИЯ: проверка наличия детали",
            part_id=part_id,
            roles=self.PRESENCE_ROLES,
        )
        presence_result = self._evaluate_part_presence(vision_results)
        presence_result, presence_vote, _ = combine_presence_results(
            [presence_result]
        )

        if bool(presence_result.details.get("empty_tray")):
            self._notify_progress(
                "INSPECT_DECISION",
                "ИНСПЕКЦИЯ: ячейка пуста, решение наличия принято",
                part_id=part_id,
                roles=self.INSPECT_ROLES,
            )
            consensus = {
                "runs": 1,
                "required_votes": 1,
                "evidence_run": 1,
                "part_presence": presence_vote,
                "rules": {},
                "picture_run": 1,
                "picture_reason": describe_picture_run(
                    [presence_result], 0,
                ),
            }
            return InspectionResult(
                stage="inspect",
                defects=[],
                vision_results=vision_results,
                rule_results=[presence_result],
                annotated={},
                raw_frames=frames,
                raw_overlay_frames={},
                is_empty_tray=True,
                consensus=consensus,
                model_health=model_health,
                run_frames=[frames],
                run_rule_results=[[]],
            )

        self._notify_progress(
            "INSPECT_GEOMETRY",
            "ИНСПЕКЦИЯ: построение геометрии и измерений",
            part_id=part_id,
            roles=self.INSPECT_ROLES,
        )
        defect_results, consensus, _evidence = combine_rule_results(
            [self.decision.evaluate_all_detailed(vision_results, frames=frames)]
        )
        self._notify_progress(
            "INSPECT_DECISION",
            "ИНСПЕКЦИЯ: решение правил сформировано",
            part_id=part_id,
            roles=self.INSPECT_ROLES,
        )
        consensus["part_presence"] = presence_vote

        final_results = [presence_result] + defect_results
        consensus["picture_run"] = 1
        consensus["picture_reason"] = describe_picture_run(final_results, 0)

        return self._build_result(
            part_id=part_id,
            step=step,
            frames=frames,
            vision_results=vision_results,
            rule_results=final_results,
            markup_rule_results=defect_results,
            force_bad=force_bad,
            consensus=consensus,
            model_health=model_health,
        )

    def _single_stage_frames(self, frame_runs) -> dict:
        runs = list(frame_runs)
        if len(runs) != 1:
            raise RuntimeError(
                f"inspect: ожидался один набор кадров, получено {len(runs)}"
            )
        frames = runs[0]
        if not isinstance(frames, dict):
            raise RuntimeError("inspect: кадры должны быть словарём")
        missing = set(self.INSPECT_ROLES) - set(frames)
        if missing:
            raise RuntimeError(
                f"Missing inspect camera frames: {sorted(missing)}"
            )
        return {role: frames[role] for role in self.INSPECT_ROLES}

    def _run_vision(self, frames: dict):
        vision_results = self.vision.process_all(frames)
        missing = set(self.INSPECT_ROLES) - set(vision_results)
        if missing:
            raise RuntimeError(f"Missing vision results: {sorted(missing)}")
        health_rows = getattr(self.vision, "last_health", None) or []
        model_health = summarize_model_health(
            [{**row, "run": 1} for row in health_rows if isinstance(row, dict)]
        )
        return vision_results, model_health

    def _build_result(
        self,
        *,
        part_id: int,
        step: int,
        frames: dict,
        vision_results: dict,
        rule_results: list,
        force_bad: bool,
        consensus: dict,
        model_health: list,
        markup_rule_results: list | None = None,
    ) -> InspectionResult:
        defects = [r.defect for r in rule_results if r.triggered]
        if force_bad:
            defects = ["forced_bad"]

        # Разметка строится последней: сначала ``rule_results`` уже
        # содержат вычисленную геометрию и решение, затем эти же drawings
        # накладываются на исходный snapshot. Служебный part_presence
        # ничего не рисует.
        markup = markup_rule_results if markup_rule_results is not None else rule_results
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
            stage="inspect",
            defects=defects,
            vision_results=vision_results,
            rule_results=rule_results,
            annotated=annotated,
            raw_frames=frames,
            raw_overlay_frames=raw_overlay_frames,
            is_empty_tray=False,
            consensus=consensus,
            model_health=model_health,
            run_frames=[frames],
            run_rule_results=[markup],
            run_vision_results=[dict(vision_results)],
        )

    # Empty tray detector

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
