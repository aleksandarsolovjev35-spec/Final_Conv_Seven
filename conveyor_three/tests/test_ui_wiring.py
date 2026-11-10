"""Связность HMI трёхкамерной линии: разметка, скрипты и обработчики.

Guard-тесты ловят ситуации, когда блок разметки перенесён, а логика к нему
нет (или наоборот): кнопка в интерфейсе есть, но обработчика нет — либо
скрипт обращается к элементу, которого в разметке не существует.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "vision" / "ui"
STATIC = UI / "static"

INDEX_HTML = (UI / "templates" / "index.html").read_text(encoding="utf-8")

JS_FILES = {
    path.stem: path.read_text(encoding="utf-8")
    for path in sorted((STATIC / "js").glob("*.js"))
}
CSS_FILES = {
    path.stem: path.read_text(encoding="utf-8")
    for path in sorted((STATIC / "css").glob("*.css"))
}

HTML_IDS = set(re.findall(r'id="([^"]+)"', INDEX_HTML))


def _defined_functions():
    names = set()
    for source in JS_FILES.values():
        names |= set(
            re.findall(r"^(?:async )?function (\w+)", source, re.M)
        )
        names |= set(
            re.findall(r"^\s*(?:const|let|var) (\w+)\s*=", source, re.M)
        )
    return names


DEFINED = _defined_functions()


def test_every_js_element_reference_exists_in_markup():
    """Каждый элемент, к которому обращается скрипт, есть в index.html."""
    missing = {}
    for name, source in JS_FILES.items():
        referenced = set(
            re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", source)
        )
        referenced |= set(re.findall(r"\$\('([^']+)'\)", source))
        absent = sorted(item for item in referenced if item not in HTML_IDS)
        if absent:
            missing[name] = absent
    assert missing == {}, f"Скрипты ссылаются на отсутствующие элементы: {missing}"


def test_deferred_module_hooks_exist():
    """Модули вызывают друг друга через typeof — имя обязано быть объявлено."""
    missing = {}
    for name, source in JS_FILES.items():
        hooks = set(re.findall(r"typeof (\w+) === ['\"]function['\"]", source))
        absent = sorted(hook for hook in hooks if hook not in DEFINED)
        if absent:
            missing[name] = absent
    assert missing == {}, f"Вызовы необъявленных функций: {missing}"


def test_batch_and_operator_markup_present():
    """Блоки партий и оператора связаны со своими скриптами."""
    for element_id in (
        "batches-view",
        "batch-list",
        "batch-id-input",
        "batch-open",
        "active-batch-toolbar",
        "operator-modal",
        "operator-fio-input",
        "operator-status-group",
    ):
        assert element_id in HTML_IDS, element_id

    for asset in ("batches.js", "operator.js", "yolo-feedback.js"):
        assert asset in INDEX_HTML, asset
    for asset in ("batches.css", "operator.css", "yolo-feedback.css"):
        assert asset in INDEX_HTML, asset


def test_jog_step_mode_has_markup_and_handlers():
    """Переключатель «1 ШАГ» не должен быть мёртвой кнопкой."""
    assert "jog-mode-step" in HTML_IDS
    jog_js = JS_FILES["jog"]
    assert "function setJogControlMode" in jog_js
    assert "async function triggerJogStep" in jog_js
    assert "/api/jog/step" in jog_js
    assert "jogModeStep.addEventListener" in jog_js
    # Режим шага обязан подменять обработчик нажатия, а не удержание.
    assert "triggerJogStep(btn.dataset.direction, btn)" in jog_js


def test_thresholds_slot_shows_batches_before_selection():
    """До выбора партии слот показывает список партий, а не прячется."""
    thresholds_js = JS_FILES["thresholds"]
    assert "state.batchSelected" in thresholds_js
    assert "data-slot-mode" in CSS_FILES["batches"] or (
        'data-slot-mode="batches"' in CSS_FILES["batches"]
    )


def test_start_button_lock_styles_exist():
    """Замок на кнопке ПУСК имеет стили, иначе он невидим."""
    controls_css = CSS_FILES["controls"]
    for token in (
        ".start-lock-icon",
        ".btn-start.is-batch-locked",
        "@keyframes startLockPress",
    ):
        assert token in controls_css, token
    assert "start-lock-icon" in HTML_IDS
    assert "start-label" in HTML_IDS


def test_three_camera_geometry_stays_own():
    """Правила, отрисовки и лента тройки не должны быть заменены семёркой."""
    rules = sorted(
        path.stem
        for path in (ROOT / "domain" / "defect_rules").glob("rule_*.py")
    )
    assert rules == [
        "rule_bottom_glass",
        "rule_part_presence",
        "rule_uneven_heights",
        "rule_welding",
        "rule_window_sinks",
    ]

    core_js = JS_FILES["core"]
    assert "const LINE_INSPECT_POS = 0;" in core_js
    assert "const LINE_SORT_POS = 3;" in core_js
    assert "const LINE_SLOT_COUNT = 4;" in core_js

    model_config = (ROOT / "vision" / "model_config.py").read_text(
        encoding="utf-8"
    )
    assert "GROUP_LEFT_RIGHT" in model_config
    assert "GROUP_MIDDLE" in model_config


def test_css_braces_balanced():
    for name, source in CSS_FILES.items():
        assert source.count("{") == source.count("}"), name


def test_all_markup_classes_have_styles():
    """Каждый класс из разметки описан в CSS — иначе блок выглядит «сырым»."""
    classes = set()
    for attr in re.findall(r'class="([^"]+)"', INDEX_HTML):
        classes |= set(attr.split())

    css = "\n".join(CSS_FILES.values())
    # Классы-переключатели состояний и служебные маркеры стилей не требуют.
    state_only = {
        "is-hidden", "is-active", "is-on", "is-collapsed", "is-open",
        "is-empty", "is-faded", "is-locked", "is-bad", "is-pending",
        "is-batch-locked", "is-lock-shake", "is-loading", "is-disabled",
        "controls-collapsed", "jog-inactive", "jog-pause-handoff",
        "pending", "active", "good", "bad", "warn", "splash-fadeout",
        "ui-collapse", "btn-sm", "btn-ok", "btn-bad", "btn-accent",
        "btn-warn", "btn-icon", "btn-icon-lg", "btn-overlay", "btn-grid",
        "jog-dpad-hold",
        # Служебные маркеры строки пути: раскладку задаёт
        # .archive-settings-row, отдельный стиль не нужен.
        "archive-settings-path-row",
    }
    missing = sorted(
        name for name in classes
        if name and name not in state_only and name not in css
    )
    assert missing == [], f"Классы без стилей: {missing}"


def test_jog_mode_switch_is_styled():
    """Переключатель режима на ленте не должен быть голым текстом."""
    jog_css = CSS_FILES["jog"]
    for token in (".jog-mode-switch", ".jog-mode-btn", ".jog-mode-btn.is-active"):
        assert token in jog_css, token


def test_every_js_api_call_has_backend_route():
    """Путь /api/..., который зовёт скрипт, обслуживается сервером."""
    server_src = "".join(
        path.read_text(encoding="utf-8")
        for path in sorted((UI / "server").glob("*.py"))
    )
    routes = {
        re.sub(r"\{[^}]+\}", "", match)
        for match in re.findall(
            r'@(?:app|router)\.(?:get|post|put|delete)\(\s*["\']([^"\']+)["\']',
            server_src,
        )
    }

    called = set()
    for source in JS_FILES.values():
        called |= set(
            re.findall(r"""['"`](/api/[A-Za-z0-9_/\-]+?)['"`]""", source)
        )

    def served(path):
        for route in routes:
            if path == route or path.rstrip("/") == route.rstrip("/"):
                return True
            if route.endswith("/") and path.startswith(route):
                return True
        return False

    missing = sorted(path for path in called if not served(path))
    assert missing == [], f"Скрипт зовёт несуществующие маршруты: {missing}"


def test_camera_roles_are_three_camera():
    """Роли камер остались трёхкамерными — перенос не притащил семь камер."""
    ui_source = INDEX_HTML + "".join(JS_FILES.values())
    assert not re.search(r"\b(TOP|SPIDER_LEFT|SPIDER_RIGHT)\b", ui_source)
    assert "LEFT" in ui_source and "MIDDLE" in ui_source and "RIGHT" in ui_source


def test_no_fault_banner_leftovers():
    """Карточку аварии рисует лицо fault, а не баннер семикамерной версии."""
    assert "fault-banner" not in INDEX_HTML
    assert "fault-face" in INDEX_HTML
    assert "faultBanner" not in "".join(JS_FILES.values())
