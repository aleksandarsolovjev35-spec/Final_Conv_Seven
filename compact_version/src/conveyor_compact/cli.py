"""Безопасные команды каркаса: проверка конфигурации и контрактов."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from conveyor_compact.bootstrap import MIGRATION_STATUS, build_context
from conveyor_compact.compatibility import MANIFEST
from conveyor_compact.config import ConfigError


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="conveyor-compact")
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", help="проверить каркас и JSON-конфиги")
    doctor.add_argument("--root", type=Path, default=_default_root())
    doctor.add_argument("--json", action="store_true", dest="as_json")

    manifest = subparsers.add_parser("manifest", help="показать контракт совместимости")
    manifest.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "doctor"
    if command == "manifest":
        return _show_manifest(args.as_json)
    return _doctor(getattr(args, "root", _default_root()), getattr(args, "as_json", False))


def _doctor(root: Path, as_json: bool) -> int:
    try:
        context = build_context(root)
    except ConfigError as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"[ERROR] {exc}")
        return 1

    report = {
        "ok": True,
        "root": str(context.root),
        "production_ready": context.production_ready,
        "configuration": {
            "cameras": len(context.config.camera_mapping),
            "thresholds": context.config.threshold_count,
            "archive_enabled": context.config.archive["enabled"],
        },
        "compatibility": {
            "categories": len(context.compatibility.categories),
            "rules": len(context.compatibility.production_rules),
            "api_routes": len(context.compatibility.api_routes),
        },
        "migration": MIGRATION_STATUS,
    }
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("Compact version · проверка каркаса")
    print(f"[OK] Корень: {context.root}")
    print(f"[OK] Камеры: {report['configuration']['cameras']} ролей")
    print(f"[OK] Пороги: {report['configuration']['thresholds']} значений")
    print(
        "[OK] Контракт: "
        f"{report['compatibility']['rules']} правил, "
        f"{report['compatibility']['api_routes']} API-маршрутов"
    )
    print("[INFO] Миграция:")
    for module, status in MIGRATION_STATUS.items():
        marker = "OK" if status == "ready" else "--"
        print(f"  [{marker}] {module}: {status}")
    print("[SAFE] Production-запуск и движение оборудования пока отключены.")
    return 0


def _show_manifest(as_json: bool) -> int:
    payload = MANIFEST.as_dict()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print("Контракт совместимости compact_version")
    print(f"Камеры: {', '.join(MANIFEST.camera_roles)}")
    print(f"Категории: {', '.join(MANIFEST.categories)}")
    print(f"Правила: {', '.join(MANIFEST.production_rules)}")
    print(f"Фазы: {', '.join(MANIFEST.step_stages)}")
    print(f"API-маршруты: {len(MANIFEST.api_routes)}")
    return 0
