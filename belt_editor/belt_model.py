"""belt_editor/belt_model.py — конфигурация ленты `belt.path.v1` (Python-контракт).

Модуль зеркалит правила JS-модели (js/model.js): одинаковые коды нарушений,
одинаковые инварианты. Редактор сохраняет файл через сервер (serve.py), а
универсальная система позже читает его здесь, поэтому валидация обязана быть
общей и не зависит от браузера.

Элементы пути:

* позиция — слот ленты ``{"label", "inspection", "reset"}``;
* место инспекции ``{"cameras": [роль, ...], "primary": bool}`` — добавляется
  на позицию и делает позицию инспекционной;
* основное место — определяет наличие детали; если место инспекции ровно
  одно, оно основное автоматически;
* точка сброса — позиция, где корпус покидает ленту; ровно одна.

Путь корпуса: линейный (вход — позиция 0, сброс — выход) или циклический
(ретур: вход — позиция сразу за сбросом).
"""

from __future__ import annotations

import json
import os
import re

SCHEMA = "belt.path.v1"
MIN_POSITIONS = 2
MAX_POSITIONS = 64
CAM_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,23}$")

ERROR = "error"
WARN = "warn"


class BeltValidationError(RuntimeError):
    """Конфигурация ленты не проходит контракт belt.path.v1."""

    def __init__(self, issues):
        self.issues = list(issues)
        first = self.issues[0]["text"] if self.issues else "неизвестная ошибка"
        super().__init__(first)


def _issue(level, code, text, position=None):
    return {"level": level, "code": code, "text": text, "position": position}


def normalize_belt(raw):
    """Вернуть чистый belt-словарь или поднять ValueError на мусоре.

    Приводит типы, чинит инварианты: не более одной точки сброса, ровно
    одно основное место инспекции (единственное — всегда основное), пустые
    подписи получают автоимя «П{индекс}».
    """
    if not isinstance(raw, dict):
        raise ValueError("belt.path: ожидается JSON-объект")
    if not isinstance(raw.get("positions"), list):
        raise ValueError("belt.path: ожидается массив positions")
    if len(raw["positions"]) > MAX_POSITIONS:
        raise ValueError(f"belt.path: позиций не больше {MAX_POSITIONS}")

    positions = []
    for src in raw["positions"]:
        src = src if isinstance(src, dict) else {}
        label = str(src.get("label") or "").strip()[:40]
        inspection = None
        src_insp = src.get("inspection")
        if isinstance(src_insp, dict):
            cameras = src_insp.get("cameras")
            cameras = cameras if isinstance(cameras, list) else []
            inspection = {
                "cameras": [str(name or "").strip().upper() for name in cameras],
                "primary": src_insp.get("primary") is True,
            }
        positions.append({
            "label": label,
            "inspection": inspection,
            "reset": src.get("reset") is True,
        })

    belt = {
        "schema": SCHEMA,
        "name": str(raw.get("name") or "").strip()[:64],
        "path_type": "loop" if raw.get("path_type") == "loop" else "linear",
        "positions": positions,
    }
    apply_invariants(belt)
    return belt


def apply_invariants(belt):
    """Восстановить инварианты модели на месте (без копий)."""
    reset_kept = False
    points = []
    for index, pos in enumerate(belt["positions"]):
        if not pos["label"]:
            pos["label"] = f"П{index}"
        if pos["reset"]:
            if reset_kept:
                pos["reset"] = False
            reset_kept = True
        if pos["inspection"]:
            points.append(pos)

    if len(points) == 1:
        points[0]["inspection"]["primary"] = True
    elif len(points) > 1:
        primary_used = False
        for pos in points:
            if pos["inspection"]["primary"] and not primary_used:
                primary_used = True
            else:
                pos["inspection"]["primary"] = False
        if not primary_used:
            points[0]["inspection"]["primary"] = True


def find_reset_index(belt):
    for index, pos in enumerate(belt["positions"]):
        if pos["reset"]:
            return index
    return -1


def primary_index(belt):
    for index, pos in enumerate(belt["positions"]):
        insp = pos["inspection"]
        if insp and insp["primary"]:
            return index
    return -1


def validate_belt(belt):
    """Список нарушений той же грамматики, что и в JS."""
    issues = []
    positions = belt["positions"]
    n = len(positions)

    if n == 0:
        return [_issue(ERROR, "EMPTY_BELT",
                       "Лента пуста — добавьте позиции.")]
    if n < MIN_POSITIONS:
        issues.append(_issue(ERROR, "MIN_POSITIONS",
                             f"Минимум {MIN_POSITIONS} позиции на ленте.", 0))
    if n > MAX_POSITIONS:
        issues.append(_issue(ERROR, "MAX_POSITIONS",
                             f"Позиций не больше {MAX_POSITIONS}."))

    inspection_idx = [i for i, p in enumerate(positions) if p["inspection"]]
    if not inspection_idx:
        issues.append(_issue(ERROR, "NO_INSPECTIONS",
                             "Нет мест инспекции — добавьте место инспекции "
                             "на позицию."))

    reset_idx = find_reset_index(belt)
    if reset_idx < 0:
        issues.append(_issue(ERROR, "RESET_MISSING",
                             "Точка сброса не задана — укажите, где корпус "
                             "покидает ленту."))
    elif belt["path_type"] == "linear" and reset_idx < n - 1:
        issues.append(_issue(
            ERROR, "UNREACHABLE_AFTER_RESET",
            f"Линейный путь: позиции {reset_idx + 1}…{n - 1} стоят после "
            "сброса и никогда не увидят корпус. Удалите их или включите "
            "циклический путь.",
            reset_idx + 1,
        ))
    elif (belt["path_type"] == "linear" and reset_idx == 0
          and inspection_idx):
        issues.append(_issue(
            WARN, "LINEAR_RESET_AT_ENTRY",
            "Точка сброса совпадает со входом: корпус сойдёт с ленты до "
            "любой инспекции.", 0))

    seen = {}
    for index, pos in enumerate(positions):
        insp = pos["inspection"]
        if not insp:
            continue
        if not insp["cameras"]:
            issues.append(_issue(WARN, "CAMS_MISSING",
                                 f"Место инспекции «{pos['label']}» без камер.",
                                 index))
        for name in insp["cameras"]:
            if not CAM_NAME_RE.match(name):
                issues.append(_issue(
                    ERROR, "CAM_BAD_NAME",
                    f"Камера «{name}»: роль — 2–24 символа A-Z, 0-9, _ "
                    "с буквы.", index))
            if name in seen:
                issues.append(_issue(
                    ERROR, "CAM_DUP",
                    f"Камера {name} назначена дважды (позиции {seen[name]} "
                    f"и {index}) — одна камера одна роль на линии.", index))
            else:
                seen[name] = index
    return issues


def case_path(belt):
    """Последовательность позиций корпуса до сброса включительно.

    Линейный путь: вход — позиция 0. Циклический: вход — позиция сразу за
    точкой сброса, полный оборот ленты. None — путь не определён (нет
    позиций или нет точки сброса).
    """
    n = len(belt["positions"])
    reset_idx = find_reset_index(belt)
    if n == 0 or reset_idx < 0:
        return None
    loop = belt["path_type"] == "loop"
    steps = []
    i = (reset_idx + 1) % n if loop else 0
    for _ in range(n):
        pos = belt["positions"][i]
        insp = pos["inspection"]
        steps.append({
            "index": i,
            "label": pos["label"],
            "cameras": list(insp["cameras"]) if insp else None,
            "primary": bool(insp and insp["primary"]),
            "reset": pos["reset"],
        })
        if pos["reset"]:
            break
        i = (i + 1) % n
    return steps


def check_belt(raw):
    """normalize_belt + validate_belt: вернуть (belt, issues)."""
    belt = normalize_belt(raw)
    return belt, validate_belt(belt)


def load_belt_file(path):
    with open(path, encoding="utf-8") as stream:
        raw = json.load(stream)
    return normalize_belt(raw)


def save_belt_file(path, raw):
    """Нормализовать, проверить и записать. Ошибки — BeltValidationError."""
    belt, issues = check_belt(raw)
    blocking = [x for x in issues if x["level"] == ERROR]
    if blocking:
        raise BeltValidationError(blocking)
    text = json.dumps(belt, ensure_ascii=False, indent=2) + "\n"
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    os.replace(tmp, path)
    return belt, issues


def preset_current7():
    """Текущая 7-камерная линия: INPUT@0, SPIDER/TOP@4, распределитель@7,
    сброс@8 — ровно то, что редактор должен уметь собрать вручную."""
    return normalize_belt({
        "name": "7-камерная линия (текущая)",
        "path_type": "linear",
        "positions": [
            {"label": "ВХОД · НАЛИЧИЕ",
             "inspection": {"cameras": ["INPUT_LEFT", "INPUT_RIGHT"],
                            "primary": True}},
            {"label": "ТРАНСПОРТ"},
            {"label": "ТРАНСПОРТ"},
            {"label": "ТРАНСПОРТ"},
            {"label": "СПАЙДЕР / TOP",
             "inspection": {"cameras": ["SPIDER_LEFT", "SPIDER_RIGHT",
                                        "SPIDER_IN", "SPIDER_OUT", "TOP"]}},
            {"label": "ТРАНСПОРТ"},
            {"label": "ТРАНСПОРТ"},
            {"label": "РАСПРЕДЕЛИТЕЛЬ"},
            {"label": "ВЫХОД · СБРОС", "reset": True},
        ],
    })
