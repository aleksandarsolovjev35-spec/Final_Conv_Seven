// panel-deck.js — лица правой панели и смена лица сдвигом листа
// 'use strict';
//
// Правая панель — «колода лиц»: ready / production / fault. Лицо
// выбирается автоматически по состоянию линии. Смена лица — сдвиг
// листа в сторону движения по порядку лиц:
//   1. панель коротко уходит по горизонтали и притухает (deck-out);
//   2. на этом кадре подменяется data-face;
//   3. новое лицо въезжает с противоположной стороны (deck-settle).
// Никакого 3D-переворота: только сдвиг и прозрачность. Прежний rotateY
// крутил панель вокруг вертикальной оси и полсекунды держал её
// нечитаемой, хотя по содержанию ready и production совпадают — крутить
// было нечего. Теперь вся анимация на композиторе и занимает 240 мс.

const PANEL_FACE_ORDER = ['ready', 'production', 'fault'];

const PANEL_FACE_BY_STATE = {
    IDLE: 'ready',
    STOPPED: 'ready',
    RUNNING: 'production',
    PAUSED: 'production',
    STOPPING: 'production',
    FAULT: 'fault',
};

const PANEL_SHIFT_OUT_MS = 90;
const PANEL_SHIFT_IN_MS = 150;
const PANEL_SHIFT_TOTAL_MS = PANEL_SHIFT_OUT_MS + PANEL_SHIFT_IN_MS;
const PANEL_SHIFT_SETTLE_GRACE_MS = 30;

let _panelFace = 'ready';
let _panelShifting = false;
let _panelQueuedFace = null;
let _lastLineStatus = null;

function panelFaceForState(lineState) {
    return PANEL_FACE_BY_STATE[String(lineState || '').toUpperCase()] || 'ready';
}

function applyPanelFace(face) {
    if (!els.statsPanel) return;
    els.statsPanel.dataset.face = face;
}

// Ручное управление (JOG) заблокировано только тогда, когда линия реально
// едет или доезжает: RUNNING / STOPPING. На паузе JOG разрешён — это и есть
// назначение паузы (коррекция ленты), поэтому шторка поднята.
function panelJogLocked(ls) {
    const s = String((ls && ls.state) || '').toUpperCase();
    return s === 'RUNNING' || s === 'STOPPING';
}

function applyJogLock() {
    if (!els.statsPanel) return;
    const locked = panelJogLocked(_lastLineStatus);
    els.statsPanel.classList.toggle('jog-locked', locked);
}

// Карточка «АВАРИЯ» заполняется всегда (дёшево): при входе в лицо fault
// текст причины и число корпусов уже актуальны.
function fillFaultFace(ls) {
    const reason = document.getElementById('fault-reason');
    const inline = document.getElementById('fault-inline');
    if (reason) setIfChanged(reason, (ls && ls.fault_reason) || 'Неизвестная причина');
    if (inline) setIfChanged(inline, (ls && ls.in_line) || 0);
}

function shiftPanelTo(face) {
    if (!els.statsPanel) return;
    if (face === _panelFace) {
        // Лицо не меняется (например, ПАУЗА ↔ РАБОТА): сдвига нет,
        // но доступность ручного управления могла измениться — применяем
        // сразу, чтобы шторка поднялась/опустилась синхронно.
        applyJogLock();
        return;
    }

    // Смена уже идёт: запоминаем последний запрошенный вариант и
    // доигрываем до него после текущей. Быстрая смена состояний не ломает
    // анимацию и не оставляет панель в стороне от места.
    if (_panelShifting) {
        _panelQueuedFace = face;
        return;
    }

    const panel = els.statsPanel;
    const fromIndex = PANEL_FACE_ORDER.indexOf(_panelFace);
    const toIndex = PANEL_FACE_ORDER.indexOf(face);
    // Направление: вперёд по порядку лиц (готовность → работа → авария) или
    // назад. Панель уходит в сторону движения и возвращается с другой.
    const dir = toIndex >= fromIndex ? 1 : -1;

    _panelShifting = true;
    _panelFace = face;
    _panelQueuedFace = null;
    panel.style.setProperty('--panel-deck-duration', `${PANEL_SHIFT_TOTAL_MS}ms`);
    panel.style.setProperty('--deck-shift-dir', String(dir));
    panel.classList.add('panel-shifting', 'deck-out');

    // Шторка ручного управления проходит свой путь ровно за время смены
    // лица (CSS берёт длительность из --panel-deck-duration), поэтому обе
    // механики начинаются и заканчиваются вместе.
    setTimeout(() => {
        // На «отвернувшемся» листе меняем только лицо: шторка уже движется
        // синхронно и не получает повторного переключения в середине.
        applyPanelFace(face);
        panel.classList.remove('deck-out');
        panel.classList.add('deck-in');
        // Перечитываем раскладку, чтобы сброс transition применился
        // до старта въезда нового лица.
        void panel.offsetWidth;
        panel.classList.remove('deck-in');
        panel.classList.add('deck-settle');
    }, PANEL_SHIFT_OUT_MS);

    setTimeout(() => {
        panel.classList.remove('deck-settle', 'panel-shifting');
        panel.style.removeProperty('--panel-deck-duration');
        panel.style.removeProperty('--deck-shift-dir');
        _panelShifting = false;

        const queued = _panelQueuedFace;
        _panelQueuedFace = null;
        if (queued && queued !== _panelFace) shiftPanelTo(queued);
    }, PANEL_SHIFT_TOTAL_MS + PANEL_SHIFT_SETTLE_GRACE_MS);
}

// Вызывается из status.js.updateLineStatus после обновления состояния.
function updatePanelFace(ls) {
    _lastLineStatus = ls || null;
    fillFaultFace(ls);
    // Целевое положение шторки задаём до запуска сдвига. Если лицо
    // меняется, браузер запускает оба движения в одном кадре; если лицо то
    // же (RUNNING ↔ PAUSED), работает только обычная короткая анимация шторки.
    applyJogLock();
    shiftPanelTo(panelFaceForState(ls && ls.state));
}

if (typeof window !== 'undefined') {
    window.updatePanelFace = updatePanelFace;
    window.shiftPanelTo = shiftPanelTo;
    window.panelFaceForState = panelFaceForState;
}
