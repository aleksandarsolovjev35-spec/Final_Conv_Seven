"""Загрузка четырёх совместимых JSON-конфигураций из одного корня."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from conveyor_compact.compatibility import CAMERA_ROLES


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    root: Path
    calibration: dict[str, int | float]
    camera_mapping: dict[str, int]
    thresholds: dict[str, Any]
    archive: dict[str, Any]

    @property
    def threshold_count(self) -> int:
        return sum(
            1
            for role in CAMERA_ROLES
            for key in self.thresholds[role]
            if not key.startswith("_")
        )


_CALIBRATION_REQUIRED = {
    "conveyor_speed",
    "conveyor_accel",
    "dist1_open_position",
    "dist2_bad_position",
    "dist2_cleanup_position",
    "drop_time",
    "axis_speed",
    "axis_accel",
    "micro_steps",
    "jog_hold_steps",
    "normal_steps",
}
_CALIBRATION_OPTIONAL = {
    "settle_time": 0.5,
    "stage_trace_time": 0.5,
    "review_time": 2.0,
}

_INPUT_PARAMETERS = (
    "input_part_presence_false_positive_max_count",
    "input_window_geometry_min_confidence",
    "input_window_geometry_expected_count",
    "input_window_geometry_top_px_min",
    "input_window_geometry_top_px_max",
    "input_window_geometry_bottom_px_min",
    "input_window_geometry_bottom_px_max",
    "input_window_geometry_center_zone_ratio",
    "input_window_sinks_min_confidence",
    "input_window_sinks_window_min_confidence",
    "input_window_sinks_overlap_min_px",
)
_LONG_PARAMETERS = (
    "spider_contacts_long_min_confidence",
    "spider_contacts_long_expected_count",
    "spider_contacts_long_damper_open_max_px",
    "spider_contacts_long_gap_dev_max_px",
    "spider_contacts_long_inscribed_rect_width_px",
    "spider_contacts_long_inscribed_rect_height_px",
    "spider_contacts_long_y_filter_ratio",
    "spider_long_omission_min_confidence",
    "spider_long_omission_allowed_thickness_px",
    "spider_long_omission_excess_component_min_px",
    "spider_long_omission_top_line_max_residual_px",
    "spider_long_omission_top_line_min_inlier_ratio",
)
_SHORT_PARAMETERS = (
    "spider_contacts_short_min_confidence",
    "spider_contacts_short_expected_count",
    "spider_contacts_short_damper_open_max_px",
    "spider_contacts_short_inscribed_rect_width_px",
    "spider_contacts_short_inscribed_rect_height_px",
    "spider_contacts_short_area_absolute_min",
    "spider_contacts_short_y_filter_ratio",
    "spider_short_omission_min_confidence",
    "spider_short_omission_allowed_thickness_px",
    "spider_short_omission_excess_component_min_px",
    "spider_short_omission_top_line_max_residual_px",
    "spider_short_omission_top_line_min_inlier_ratio",
)
_TOP_PARAMETERS = (
    "top_contacts_min_confidence",
    "top_contacts_expected_count",
    "top_contacts_platform_min_confidence",
    "top_contacts_edge_distance_deviation_ratio",
    "top_contacts_side_rect_width_px",
    "top_contacts_side_rect_height_px",
    "top_contacts_edge_rect_width_px",
    "top_contacts_edge_rect_height_px",
    "top_platform_overlap_platform_min_confidence",
    "top_platform_overlap_excess_component_min_px",
    "top_platform_overlap_contact_min_confidence",
    "top_platform_overlap_contact_inner_ratio",
    "top_platform_overlap_margin_px",
    "top_platform_overlap_expand_x_ratio",
    "top_platform_overlap_expand_y_ratio",
    "top_platform_min_confidence",
    "top_platform_inscribed_rect_width_px",
    "top_platform_inscribed_rect_height_px",
    "top_sinks_min_confidence",
    "top_sinks_platform_min_confidence",
    "top_sinks_case_central_min_confidence",
    "top_glass_min_confidence",
    "top_glass_platform_min_confidence",
    "top_glass_case_min_confidence",
    "top_glass_case_central_min_confidence",
    "top_glass_pin_min_confidence",
)
_REQUIRED_THRESHOLDS = {
    "INPUT_LEFT": _INPUT_PARAMETERS,
    "INPUT_RIGHT": _INPUT_PARAMETERS,
    "SPIDER_LEFT": _LONG_PARAMETERS,
    "SPIDER_RIGHT": _LONG_PARAMETERS,
    "SPIDER_IN": _SHORT_PARAMETERS,
    "SPIDER_OUT": _SHORT_PARAMETERS,
    "TOP": _TOP_PARAMETERS,
}


def load_config_bundle(root: str | Path) -> ConfigBundle:
    root = Path(root).expanduser().resolve()
    calibration = validate_calibration(_load_json(root / "calibration.json"))
    cameras = validate_camera_mapping(_load_json(root / "camera_mapping.json"))
    thresholds = validate_thresholds(_load_json(root / "thresholds.json"))
    archive = normalize_archive(_load_json(root / "archive_config.json"))
    return ConfigBundle(root, calibration, cameras, thresholds, archive)


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError as exc:
        raise ConfigError(f"Файл не найден: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Ошибка чтения {path}: {exc}") from exc


def validate_calibration(data: Any) -> dict[str, int | float]:
    if not isinstance(data, dict):
        raise ConfigError("calibration.json должен содержать объект")
    missing = _CALIBRATION_REQUIRED - data.keys()
    extra = data.keys() - _CALIBRATION_REQUIRED - _CALIBRATION_OPTIONAL.keys()
    if missing or extra:
        raise ConfigError(
            f"Неверные поля calibration: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    result = {**_CALIBRATION_OPTIONAL, **data}
    float_keys = {"drop_time", *_CALIBRATION_OPTIONAL}
    for key, value in result.items():
        if key in float_keys:
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise ConfigError(f"{key} должен быть конечным числом")
        elif type(value) is not int:
            raise ConfigError(f"{key} должен быть int")

    positive = _CALIBRATION_REQUIRED - {
        "dist2_bad_position",
        "dist2_cleanup_position",
        "drop_time",
    }
    if any(result[key] <= 0 for key in positive):
        raise ConfigError("Положительные calibration-параметры должны быть > 0")
    if not 1 <= result["micro_steps"] <= 5000:
        raise ConfigError("micro_steps должен быть в диапазоне 1..5000")
    if not 10_000 <= result["jog_hold_steps"] <= 10_000_000:
        raise ConfigError("jog_hold_steps должен быть в диапазоне 10000..10000000")
    if min(result["dist2_bad_position"], result["dist2_cleanup_position"]) < 0:
        raise ConfigError("Позиции DIST2 не могут быть отрицательными")
    if result["dist2_bad_position"] == result["dist2_cleanup_position"]:
        raise ConfigError("BAD и CLEANUP позиции должны различаться")
    _require_range(result, "drop_time", 0.05, 30.0)
    _require_range(result, "settle_time", 0.0, 5.0)
    _require_range(result, "stage_trace_time", 0.0, 5.0)
    _require_range(result, "review_time", 0.0, 30.0)
    return result


def _require_range(data: dict, key: str, minimum: float, maximum: float) -> None:
    if not minimum <= float(data[key]) <= maximum:
        raise ConfigError(f"{key} должен быть в диапазоне {minimum}..{maximum}")


def validate_camera_mapping(data: Any) -> dict[str, int]:
    if not isinstance(data, dict):
        raise ConfigError("camera_mapping.json должен содержать объект")
    required = set(CAMERA_ROLES)
    if set(data) != required:
        raise ConfigError(
            "camera_mapping mismatch: "
            f"missing={sorted(required - set(data))}, extra={sorted(set(data) - required)}"
        )
    ids = list(data.values())
    if any(type(camera_id) is not int or camera_id < 0 for camera_id in ids):
        raise ConfigError("Camera ID должны быть неотрицательными int")
    if len(ids) != len(set(ids)):
        raise ConfigError("Camera ID должны быть уникальными")
    return dict(data)


def validate_thresholds(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError("thresholds.json должен содержать объект")
    for role, required in _REQUIRED_THRESHOLDS.items():
        section = data.get(role)
        if not isinstance(section, dict):
            raise ConfigError(f"Секция {role} должна быть объектом")
        missing = [key for key in required if key not in section]
        if missing:
            raise ConfigError(f"{role}: отсутствуют пороги {missing}")
        for key, value in section.items():
            if key.startswith("_comment"):
                continue
            if key.startswith("_label."):
                if not isinstance(value, str) or not value.strip():
                    raise ConfigError(f"{role}.{key} должен быть непустой строкой")
                continue
            _validate_threshold_value(role, key, value)

    disabled = data.get("disabled_rules", [])
    if not isinstance(disabled, list) or any(not isinstance(item, str) for item in disabled):
        raise ConfigError("disabled_rules должен быть списком строк")
    if "part_presence" in disabled:
        raise ConfigError("part_presence нельзя отключать")

    for role in ("INPUT_LEFT", "INPUT_RIGHT"):
        section = data[role]
        for axis in ("top", "bottom"):
            minimum = section[f"input_window_geometry_{axis}_px_min"]
            maximum = section[f"input_window_geometry_{axis}_px_max"]
            if minimum > maximum:
                raise ConfigError(f"{role}: {axis}_px_min не может превышать {axis}_px_max")
    return dict(data)


def _validate_threshold_value(role: str, key: str, value: Any) -> None:
    full_key = f"{role}.{key}"
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise ConfigError(f"{full_key} должен быть конечным числом")
    number = float(value)
    if key.endswith("_min_confidence") and not 0 <= number <= 1:
        raise ConfigError(f"{full_key} должен быть 0..1")
    if key.endswith("_ratio"):
        if key.endswith(("_expand_x_ratio", "_expand_y_ratio")):
            if number <= 0:
                raise ConfigError(f"{full_key} должен быть > 0")
        elif number < 0 or (
            not key.endswith(("_y_filter_ratio", "_deviation_ratio")) and number > 1
        ):
            raise ConfigError(f"{full_key}: недопустимое отношение")
    if key.endswith("_expected_count"):
        if type(value) is not int or value <= 0:
            raise ConfigError(f"{full_key} должен быть целым > 0")
        fixed = {
            "spider_contacts_short_expected_count": 2,
            "top_contacts_expected_count": 14,
        }.get(key)
        if fixed is not None and value != fixed:
            raise ConfigError(f"{full_key} должен быть равен {fixed}")
    integer_suffixes = (
        "false_positive_max_count",
        "excess_component_min_px",
        "overlap_min_px",
        "area_absolute_min",
    )
    if key.endswith(integer_suffixes) and (type(value) is not int or value < 0):
        raise ConfigError(f"{full_key} должен быть неотрицательным целым")
    if key.endswith(("excess_component_min_px", "overlap_min_px")) and value < 1:
        raise ConfigError(f"{full_key} должен быть >= 1")
    if "inscribed_rect_" in key and number <= 0:
        raise ConfigError(f"{full_key} должен быть > 0")
    if not key.endswith("_margin_px") and number < 0:
        raise ConfigError(f"{full_key} должен быть >= 0")


def normalize_archive(data: Any) -> dict[str, Any]:
    source = data if isinstance(data, dict) else {}
    try:
        quality = int(source.get("jpeg_quality", 92))
    except (TypeError, ValueError):
        quality = 92
    root_path = str(source.get("root_path") or "archive").strip() or "archive"
    return {
        "enabled": bool(source.get("enabled", True)),
        "root_path": os.path.expandvars(os.path.expanduser(root_path)),
        "jpeg_quality": max(70, min(98, quality)),
        "compress_on_shutdown": bool(source.get("compress_on_shutdown", True)),
        "delete_original_after_zip": bool(
            source.get("delete_original_after_zip", True)
        ),
    }
