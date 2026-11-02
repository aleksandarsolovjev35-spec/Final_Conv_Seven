from __future__ import annotations

from domain.defect_rules.result import RuleResult


def detections_of_kind(vision_results: dict, role: str, kind: str,
                       min_confidence: float = 0.0) -> list:
    """Детекции нужного типа модели на роли с фильтром по уверенности.

    ``kind`` проставляется VisionCluster'ом из model_config и повторяет
    семантику трёхкамерника: модель привязана к камере, а не к имени
    класса внутри весов.
    """
    out = []
    for det in vision_results.get(role, []) or []:
        if not isinstance(det, dict):
            continue
        if kind and det.get("kind") != kind:
            continue
        if float(det.get("confidence", 0.0)) < float(min_confidence):
            continue
        out.append(det)
    return out


class WindowSinksRule:
    """Раковины окон по камерам LEFT и RIGHT.

    Перенос трёхкамерника (kind=window_sinks, модель shells): любая
    детекция с уверенностью выше порога — брак (код состояния 3,
    наивысший приоритет 100).
    """

    name = "window_sinks"
    ROLES = ("LEFT", "RIGHT")
    TARGET_KIND = "window_sinks"

    def __init__(self, thresholds: dict):
        self.thresholds = thresholds
        self._enabled = self.name not in thresholds.get(
            "disabled_rules", []
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _get(self, key, default=None, role=None):
        """Порог этого правила: сначала ROLE.key, затем key, затем default."""
        if role:
            role_key = f"{role}.{key}"
            if role_key in self.thresholds:
                return self.thresholds[role_key]
        return self.thresholds.get(key, default)

    def _make_skip(self, rule_name):
        """Результат для отключённого правила."""
        return RuleResult(
            rule_name, False,
            details={"skipped": "rule disabled"},
        )

    def check(self, vision_results: dict, **kwargs) -> RuleResult:
        if not self.enabled:
            return self._make_skip(self.name)

        roles_to_check = [r for r in self.ROLES if r in vision_results]
        if not roles_to_check:
            roles_to_check = list(self.ROLES)

        per_role = {}
        drawings = []
        any_triggered = False

        for role in roles_to_check:
            min_confidence = float(self._get(
                "window_sinks_min_confidence", 0.8, role=role,
            ))
            detections = detections_of_kind(
                vision_results, role, self.TARGET_KIND, min_confidence,
            )
            triggered = len(detections) > 0

            per_role[role] = {
                "valid": True,
                "skipped": False,
                "triggered": triggered,
                "reason": "sinks_found" if triggered else None,
                "found": len(detections),
                "min_confidence": min_confidence,
            }

            for det in detections:
                drawings.append({
                    "type": "rule_bbox",
                    "role": role,
                    "rule": self.name,
                    "bbox": det.get("bbox"),
                    "mask": det.get("mask"),
                    "triggered": True,
                    "confidence": det.get("confidence"),
                })

            any_triggered = any_triggered or triggered

        return RuleResult(
            self.name,
            triggered=any_triggered,
            details={"per_role": per_role},
            drawings=drawings,
        )
