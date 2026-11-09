"""Правая панель HMI статична: никаких «лиц», шторки и сворачивания.

Guard-тесты фиксируют удаление колоды альтернативных версий правой
панели (panel-deck): состав блоков не меняется при переходах между
состояниями линии, доступность ручного управления выражается только
disabled кнопок и стражами команд, а причина аварии показывается
отдельным постоянным баннером (#fault-banner).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "vision" / "ui"
INDEX_HTML = (UI / "templates" / "index.html").read_text(encoding="utf-8")
JOG_JS = (UI / "static" / "js" / "jog.js").read_text(encoding="utf-8")
STATUS_JS = (UI / "static" / "js" / "status.js").read_text(encoding="utf-8")
CONTROLS_JS = (UI / "static" / "js" / "controls.js").read_text(encoding="utf-8")
DIAGNOSTICS_JS = (UI / "static" / "js" / "diagnostics.js").read_text(encoding="utf-8")
THRESHOLDS_JS = (UI / "static" / "js" / "thresholds.js").read_text(encoding="utf-8")
PROCESS_CSS = (UI / "static" / "css" / "process.css").read_text(encoding="utf-8")
MOTION_CSS = (UI / "static" / "css" / "motion.css").read_text(encoding="utf-8")


def test_panel_deck_files_removed():
    assert not (UI / "static" / "js" / "panel-deck.js").exists()
    assert not (UI / "static" / "css" / "panel-deck.css").exists()


def test_index_has_no_panel_deck_markup():
    tokens = ("panel-deck", "data-face", "fault-face", "jog-deck", "jog-shutter")
    for token in tokens:
        assert token not in INDEX_HTML, token


def test_no_face_rules_in_any_css():
    for css in sorted((UI / "static" / "css").glob("*.css")):
        text = css.read_text(encoding="utf-8")
        for token in ("data-face", "jog-shutter", "jog-locked"):
            assert token not in text, f"{css.name}: {token}"


def test_jog_panel_is_never_hidden_or_dimmed_by_state():
    tokens = (
        "showJogPanel",
        "jog-inactive",
        "jog-pause-handoff",
        "jog-locked",
        "is-collapsed",
    )
    for token in tokens:
        assert token not in JOG_JS, token
    for token in ("jog-inactive", "jog-pause-handoff"):
        assert token not in PROCESS_CSS, token
    assert "jogUiAvailable" in JOG_JS


def test_no_right_panel_block_is_ever_hidden():
    """Статистика, пороги правил и JOG не скрываются и не сворачиваются:
    ни при переходах состояний, ни во время анализа кадра, ни оффлайн."""
    assert "is-collapsed" not in CONTROLS_JS
    assert "is-collapsed" not in DIAGNOSTICS_JS
    assert "is-collapsed" not in STATUS_JS
    assert "is-collapsed" not in INDEX_HTML
    assert "is-hidden" not in THRESHOLDS_JS
    assert "thresholdsPanelVisible" not in THRESHOLDS_JS
    assert 'class="thresholds-panel"' in INDEX_HTML
    assert "#jog-panel.ui-collapse" not in MOTION_CSS


def test_fault_banner_present_and_announced():
    assert 'id="fault-banner"' in INDEX_HTML
    banner_tag = INDEX_HTML.split('id="fault-banner"', 1)[1].split(">", 1)[0]
    assert 'role="alert"' in banner_tag
    assert 'aria-live="assertive"' in banner_tag
    assert "updateFaultBanner" in STATUS_JS
    assert ".fault-banner" in PROCESS_CSS
