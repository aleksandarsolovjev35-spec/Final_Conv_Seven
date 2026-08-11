"""Публичный контракт, который новая реализация не должна менять."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ApiRoute:
    method: str
    path: str


@dataclass(frozen=True, slots=True)
class CompatibilityManifest:
    camera_roles: tuple[str, ...]
    categories: tuple[str, ...]
    production_rules: tuple[str, ...]
    step_stages: tuple[str, ...]
    config_files: tuple[str, ...]
    api_routes: tuple[ApiRoute, ...]

    def as_dict(self) -> dict:
        return asdict(self)


CAMERA_ROLES = (
    "INPUT_LEFT",
    "INPUT_RIGHT",
    "SPIDER_LEFT",
    "SPIDER_RIGHT",
    "SPIDER_IN",
    "SPIDER_OUT",
    "TOP",
)

CATEGORIES = ("GOOD", "BAD", "CLEANUP", "UNKNOWN")

# part_presence — обязательное служебное правило; остальные 12 — production.
PRODUCTION_RULES = (
    "part_presence",
    "window_geometry",
    "window_sinks",
    "contacts_long",
    "long_omission",
    "contacts_short",
    "short_omission",
    "top_contacts",
    "top_platform",
    "platform_contacts_overlap",
    "sinks",
    "glass",
    "glass_on_contacts",
)

STEP_STAGES = ("MOTION", "SETTLE", "CAPTURE", "ANALYSIS", "PUBLISH")

CONFIG_FILES = (
    "calibration.json",
    "camera_mapping.json",
    "thresholds.json",
    "archive_config.json",
)

API_ROUTES = tuple(
    ApiRoute(method, path)
    for method, path in (
        ("GET", "/frame/{role}"),
        ("GET", "/stream/{role}"),
        ("GET", "/api/archive/part/{part_id}"),
        ("GET", "/api/archive/image/{part_id}/{role}/{kind}"),
        ("GET", "/api/cameras"),
        ("GET", "/api/boot"),
        ("GET", "/api/status"),
        ("GET", "/api/mode"),
        ("POST", "/api/mode/{mode}"),
        ("POST", "/api/active_camera/{role}"),
        ("GET", "/api/thresholds"),
        ("POST", "/api/thresholds"),
        ("GET", "/api/archive/settings"),
        ("POST", "/api/archive/settings"),
        ("POST", "/api/start"),
        ("POST", "/api/stop"),
        ("POST", "/api/pause"),
        ("POST", "/api/resume"),
        ("POST", "/api/exit"),
        ("POST", "/api/diagnostics/cameras"),
        ("POST", "/api/diagnostics/vision-rules"),
        ("POST", "/api/diagnostics/selected/release"),
        ("POST", "/api/diagnostics/selected/{role}"),
        ("POST", "/api/distributor/diagnostic/{command}"),
        ("POST", "/api/jog/enter"),
        ("POST", "/api/jog/exit"),
        ("POST", "/api/jog/hold/start"),
        ("POST", "/api/jog/hold/heartbeat"),
        ("POST", "/api/jog/hold/release"),
    )
)

MANIFEST = CompatibilityManifest(
    camera_roles=CAMERA_ROLES,
    categories=CATEGORIES,
    production_rules=PRODUCTION_RULES,
    step_stages=STEP_STAGES,
    config_files=CONFIG_FILES,
    api_routes=API_ROUTES,
)
