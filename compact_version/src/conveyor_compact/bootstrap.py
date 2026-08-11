"""Composition root: только здесь будут создаваться конкретные адаптеры."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from conveyor_compact.compatibility import CompatibilityManifest, MANIFEST
from conveyor_compact.config import ConfigBundle, load_config_bundle
from conveyor_compact.lifecycle import Lifecycle


MIGRATION_STATUS = {
    "compatibility_contract": "ready",
    "configuration": "ready",
    "domain": "ready",
    "lifecycle": "ready",
    "hardware_adapters": "planned",
    "vision_and_rules": "planned",
    "production_cycle": "planned",
    "api_and_hmi": "planned",
}


@dataclass(slots=True)
class ApplicationContext:
    root: Path
    config: ConfigBundle
    compatibility: CompatibilityManifest
    lifecycle: Lifecycle

    @property
    def production_ready(self) -> bool:
        return all(value == "ready" for value in MIGRATION_STATUS.values())


def build_context(root: str | Path) -> ApplicationContext:
    project_root = Path(root).expanduser().resolve()
    return ApplicationContext(
        root=project_root,
        config=load_config_bundle(project_root),
        compatibility=MANIFEST,
        # Конкретные компоненты добавляются по мере миграции адаптеров.
        lifecycle=Lifecycle(),
    )
