// controls.js — Line Monitor UI module
'use strict';

// ─── Buttons ─────────────────────────────────────────────────

function applyButtonsForState(lineState, exitRequested, controls = {}) {
    const offline = state.offline || lineState === 'OFFLINE';
    const pending = state.controlPending;
    const lockSettings = offline || pending || !['IDLE', 'STOPPED'].includes(lineState);
    // Спидометр скорости и степперы пауз: блокировку ведут их render-функции.
    conveyorSpeedLockedByState = lockSettings;
    renderConveyorSpeed();
    inspectionTimingsLockedByState = lockSettings;
    renderInspectionTimings();
    const startVisible = (
        (lineState === 'IDLE' || lineState === 'STOPPED')
        && !exitRequested
    );
    const stopVisible = (lineState === 'RUNNING' || lineState === 'PAUSED');
    const pauseVisible = lineState === 'RUNNING' && !exitRequested;
    const resumeVisible = lineState === 'PAUSED' && !exitRequested;
    const exitText = (
        lineState === 'FAULT'
        || (exitRequested && lineState === 'STOPPING')
    ) ? 'ПРИНУДИТЕЛЬНЫЙ ВЫХОД' : 'ВЫХОД';

    if (els.btnStart) {
        els.btnStart.classList.toggle('is-hidden', !startVisible);
        els.btnStart.disabled = (
            !startVisible
            || controls.start !== true
            || pending
            || offline
            || !state.camerasReady
        );
    }

    if (els.btnPause) {
        els.btnPause.classList.toggle('is-hidden', !pauseVisible);
        els.btnPause.disabled = (
            !pauseVisible
            || controls.pause !== true
            || pending
            || offline
        );
    }

    if (els.btnResume) {
        els.btnResume.classList.toggle('is-hidden', !resumeVisible);
        els.btnResume.disabled = (
            !resumeVisible
            || controls.resume !== true
            || pending
            || offline
        );
    }

    if (els.btnStop) {
        els.btnStop.classList.toggle('is-hidden', !stopVisible);
        els.btnStop.disabled = (
            !stopVisible
            || controls.stop !== true
            || pending
            || offline
        );
    }

    if (els.btnExit) {
        els.btnExit.classList.remove('is-hidden');
        els.btnExit.textContent = exitText;
        els.btnExit.className = 'btn btn-exit';
        els.btnExit.disabled = (
            controls.exit !== true
            || pending
            || offline
        );
    }
}

function flashButton(btn) {
    if (!btn) return;
    btn.classList.add('btn-flash');
    setTimeout(() => btn.classList.remove('btn-flash'), 250);
}

async function submitControl(path) {
    if (state.controlPending || state.offline) return null;
    const isStart = path === '/api/start';
    let result = null;
    state.controlPending = true;
    if (isStart) {
        state.startPending = true;
        updateStateOverlay({state: state.lineState, in_line: 0});
    }
    startStatusPolling();
    updateViewModeControls();
    applyButtonsForState(
        state.lineState,
        state.serverExitRequested,
        state.backendControls,
    );
    disableSelectedAnalysisButton();
    if (els.jogPanel) {
        if (path === '/api/start') {
            els.jogPanel.classList.add('is-collapsed');
        }
        els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(
            button => { button.disabled = true; }
        );
    }
    try {
        clearControlError();
        result = await apiPost(path, true);
        return result;
    } finally {
        state.controlPending = false;
        if (isStart && !result) {
            state.startPending = false;
        }
        startStatusPolling();
        updateViewModeControls();
        requestImmediateStatus();
    }
}

// ─── Скорость ленты: один ползунок ───────────────────────────
// Аппаратные пределы совпадают с hardware.conveyor.Conveyor: шкала в
// процентах от максимальной скорости (25 % = 5000 шаг/с). Шаг — 5 %,
// на сервер значение уходит после отпускания ползунка.

const CONVEYOR_SPEED_MIN = 5000;
const CONVEYOR_SPEED_MAX = 20000;
const CONVEYOR_SPEED_STEP = 5;

const conveyorSpeed = {percent: 90, percentMin: 25, allowed: false};
let conveyorSpeedPending = false;
let conveyorSpeedEditing = false;
let conveyorSpeedLockedByState = false;

function conveyorPercentToSpeed(percent) {
    return Math.round(CONVEYOR_SPEED_MAX * Number(percent) / 100);
}

function conveyorSpeedToPercent(speed) {
    const value = Math.round(Number(speed) / CONVEYOR_SPEED_MAX * 100);
    return Math.max(0, Math.min(100, value));
}

function formatConveyorSpeed(percent) {
    return `${Math.round(percent)} %`;
}

function conveyorSpeedTitle(speed) {
    return `${Math.round(speed).toLocaleString('ru-RU')} шаг/с`;
}

function conveyorSpeedLocked() {
    return conveyorSpeedLockedByState
        || !conveyorSpeed.allowed
        || conveyorSpeedPending
        || state.offline;
}

// Ползунок гасим только по состоянию линии, но не на время запроса:
// иначе он дёргался бы под рукой оператора.
function conveyorSpeedUnavailable() {
    return conveyorSpeedLockedByState || !conveyorSpeed.allowed || state.offline;
}

function conveyorSpeedSlider() {
    return document.getElementById('conveyor-speed-slider');
}

function conveyorSpeedFraction() {
    const span = Math.max(1, 100 - conveyorSpeed.percentMin);
    const raw = (conveyorSpeed.percent - conveyorSpeed.percentMin) / span;
    return Math.max(0, Math.min(1, raw));
}

function renderConveyorSpeed() {
    const slider = conveyorSpeedSlider();
    const output = document.getElementById('conveyor-speed-value');
    const percent = Math.round(conveyorSpeed.percent);
    const steps = conveyorSpeedTitle(conveyorPercentToSpeed(percent));
    if (slider) {
        // Значение ползунка не трогаем, пока оно уже верное: иначе
        // перетаскивание сбрасывалось бы на каждом кадре.
        if (slider.value !== String(percent)) slider.value = String(percent);
        slider.min = String(conveyorSpeed.percentMin);
        slider.style.setProperty(
            '--fill', `${(conveyorSpeedFraction() * 100).toFixed(2)}%`,
        );
        slider.disabled = conveyorSpeedUnavailable();
        slider.setAttribute('aria-valuetext',
            `${formatConveyorSpeed(percent)} · ${steps}`);
    }
    if (output) {
        output.textContent = formatConveyorSpeed(percent);
        output.title = steps;
    }
}

function updateConveyorSpeed(ls) {
    const maxSpeed = Number.isFinite(ls.conveyor_speed_max)
        ? Number(ls.conveyor_speed_max) : CONVEYOR_SPEED_MAX;
    const minSpeed = Number.isFinite(ls.conveyor_speed_min)
        ? Number(ls.conveyor_speed_min) : CONVEYOR_SPEED_MIN;
    conveyorSpeed.percentMin = Math.max(1, Math.round(minSpeed / maxSpeed * 100));
    conveyorSpeed.allowed = ls.speed_allowed === true;
    const idle = !conveyorSpeedEditing && !conveyorSpeedPending;
    if (idle && Number.isFinite(ls.conveyor_speed)) {
        conveyorSpeed.percent = Number.isFinite(ls.conveyor_speed_percent)
            ? Number(ls.conveyor_speed_percent)
            : conveyorSpeedToPercent(ls.conveyor_speed);
    }
    renderConveyorSpeed();
}

function applyConveyorPercent(percent) {
    const snapped = Math.round(Number(percent) / CONVEYOR_SPEED_STEP) * CONVEYOR_SPEED_STEP;
    conveyorSpeed.percent = Math.max(
        conveyorSpeed.percentMin,
        Math.min(100, snapped),
    );
    conveyorSpeedEditing = true;
    renderConveyorSpeed();
}

async function commitConveyorSpeed() {
    if (conveyorSpeedPending || conveyorSpeedLocked()) {
        conveyorSpeedEditing = false;
        return;
    }
    conveyorSpeedPending = true;
    renderConveyorSpeed();
    try {
        await apiPostJson('/api/conveyor/speed', {
            speed: conveyorPercentToSpeed(conveyorSpeed.percent),
            percent: conveyorSpeed.percent,
        }, true);
    } finally {
        conveyorSpeedPending = false;
        conveyorSpeedEditing = false;
        requestImmediateStatus();
    }
}

function setupConveyorSpeedSlider() {
    const slider = conveyorSpeedSlider();
    if (!slider) return;
    slider.addEventListener('input', () => {
        if (conveyorSpeedLocked()) return;
        applyConveyorPercent(slider.value);
    });
    // change приходит на отпускание, Enter и стрелки — один запрос.
    slider.addEventListener('change', () => {
        if (conveyorSpeedLocked()) return;
        commitConveyorSpeed();
    });
}

// ─── Паузы инспекции: два числовых поля ──────────────────────
// Значения в секундах: 0…5 с до инспекции (шаг 0.1) и 0…30 с после
// (шаг 0.5). Набор копится локально и уходит одним запросом.

const INSPECTION_TIMING_FIELDS = [
    {key: 'settle_time', id: 'settle-time', step: 0.1, min: 0, max: 5},
    {key: 'review_time', id: 'review-time', step: 0.5, min: 0, max: 30},
];

const inspectionTimingValues = {settle_time: 0.2, review_time: 0.5};
let inspectionTimingsPending = false;
let inspectionTimingsLockedByState = false;
let inspectionTimingsAllowed = false;
let inspectionTimingCommitTimer = null;

function inspectionTimingField(key) {
    return INSPECTION_TIMING_FIELDS.find(field => field.key === key) || null;
}

function inspectionTimingLocked() {
    return inspectionTimingsLockedByState
        || !inspectionTimingsAllowed
        || inspectionTimingsPending
        || state.offline;
}

function inspectionTimingsUnavailable() {
    return inspectionTimingsLockedByState
        || !inspectionTimingsAllowed
        || state.offline;
}

function inspectionTimingInput(field) {
    return document.getElementById(`${field.id}-input`);
}

function renderInspectionTimings() {
    const locked = inspectionTimingsUnavailable();
    INSPECTION_TIMING_FIELDS.forEach(field => {
        const input = inspectionTimingInput(field);
        if (!input) return;
        // Поле, в котором печатают, не переписываем под курсором.
        if (document.activeElement !== input) {
            input.value = Number(inspectionTimingValues[field.key]).toFixed(1);
        }
        input.disabled = locked;
    });
}

function updateInspectionTimings(ls) {
    inspectionTimingsAllowed = ls.timings_allowed === true
        && !state.controlPending;
    const timings = ls.inspection_timings || {};
    // Пока оператор набирает значение, ответ сервера его не перебивает.
    if (!inspectionTimingsPending && !inspectionTimingCommitTimer) {
        INSPECTION_TIMING_FIELDS.forEach(field => {
            const value = Number(timings[field.key]);
            if (Number.isFinite(value)) inspectionTimingValues[field.key] = value;
        });
    }
    renderInspectionTimings();
}

function scheduleInspectionTimingsCommit() {
    clearTimeout(inspectionTimingCommitTimer);
    inspectionTimingCommitTimer = setTimeout(commitInspectionTimings, 400);
}

async function commitInspectionTimings() {
    inspectionTimingCommitTimer = null;
    if (inspectionTimingsPending || inspectionTimingLocked()) return;
    inspectionTimingsPending = true;
    renderInspectionTimings();
    try {
        await apiPostJson(
            '/api/inspection/timings',
            {...inspectionTimingValues},
            true,
        );
    } finally {
        inspectionTimingsPending = false;
        requestImmediateStatus();
    }
}

function applyInspectionTimingInput(field, commit) {
    const input = inspectionTimingInput(field);
    if (!input) return;
    const previous = Number(inspectionTimingValues[field.key]);
    const parsed = Number.parseFloat(String(input.value).replace(',', '.'));
    if (!Number.isFinite(parsed)) {
        // Пустое или мусорное поле возвращаем к последнему значению.
        if (commit) input.value = previous.toFixed(1);
        return;
    }
    const clamped = Math.min(field.max, Math.max(field.min, parsed));
    const value = commit
        ? Math.round(clamped / field.step) * field.step
        : clamped;
    inspectionTimingValues[field.key] = Number(value.toFixed(2));
    if (commit) input.value = Number(value.toFixed(2)).toFixed(1);
    if (!inspectionTimingLocked() || commit) scheduleInspectionTimingsCommit();
}

function setupInspectionTimingInputs() {
    INSPECTION_TIMING_FIELDS.forEach(field => {
        const input = inspectionTimingInput(field);
        if (!input) return;
        input.addEventListener('input', () => applyInspectionTimingInput(field, false));
        // change — это Enter, уход из поля или стрелки счётчика.
        input.addEventListener('change', () => applyInspectionTimingInput(field, true));
    });
}

function setupButtons() {
    setupConveyorSpeedSlider();
    setupInspectionTimingInputs();

    if (els.splashExit) {
        els.splashExit.addEventListener('click', async () => {
            els.splashExit.disabled = true;
            clearControlError();
            const result = await apiPost('/api/exit', true);
            if (!result) els.splashExit.disabled = false;
        });
    }

    els.btnStart.addEventListener('click', async () => {
        if (els.btnStart.classList.contains('is-hidden')
            || els.btnStart.disabled) return;
        flashButton(els.btnStart);
        await submitControl('/api/start');
    });

    if (els.btnPause) {
        els.btnPause.addEventListener('click', async () => {
            if (els.btnPause.classList.contains('is-hidden')
                || els.btnPause.disabled) return;
            flashButton(els.btnPause);
            await submitControl('/api/pause');
        });
    }

    if (els.btnResume) {
        els.btnResume.addEventListener('click', async () => {
            if (els.btnResume.classList.contains('is-hidden')
                || els.btnResume.disabled) return;
            flashButton(els.btnResume);
            await submitControl('/api/resume');
        });
    }

    els.btnStop.addEventListener('click', async () => {
        if (els.btnStop.classList.contains('is-hidden')
            || els.btnStop.disabled) return;
        flashButton(els.btnStop);
        await submitControl('/api/stop');
    });

    els.btnExit.addEventListener('click', async () => {
        if (els.btnExit.classList.contains('is-hidden')
            || els.btnExit.disabled) return;
        flashButton(els.btnExit);
        await submitControl('/api/exit');
    });

}

// ─── State overlay ───────────────────────────────────────────

function updateStateOverlay(ls) {
    const lineState     = ls.state || 'IDLE';
    const exitRequested = ls.exit_requested;

    let mainCode = '';
    let mainText = '';
    let subText  = '';
    let peekable = false;

    if (lineState === 'OFFLINE' || state.offline) {
        mainCode = 'OFFLINE';
        mainText = 'НЕТ СВЯЗИ';
        subText = 'Нет связи с системой управления. Команды заблокированы.';
        peekable = false;
    } else if (state.startPending) {
        mainCode = 'STARTING';
        mainText = 'ПОДГОТОВКА К ПУСКУ';
        subText = 'Распределитель устанавливается в рабочее положение';
        peekable = false;
    } else if (lineState === 'FAULT') {
        mainCode = 'FAULT';
        mainText = 'АВАРИЯ';
        const remaining = ls.in_line || 0;
        const reason = ls.fault_reason || 'Произошла ошибка';
        subText = remaining > 0
            ? `${reason}. Корпусов на линии: ${remaining}.`
            : reason;
        peekable = false;
    } else if (exitRequested && lineState === 'STOPPING') {
        mainCode = 'DRAINING';
        mainText = 'ОСТАНОВКА ЛИНИИ';
        const remaining = ls.in_line || 0;
        subText = remaining > 0
            ? `На линии осталось корпусов: ${remaining}`
            : 'Завершение работы...';
        peekable = true;
    } else if (state.selectedAnalysisActive) {
        // Оператор запросил стоп-кадр выбранной камеры: не закрываем его
        // большим состоянием IDLE/STOPPED поверх изображения.
        mainText = '';
    } else if (lineState === 'PAUSED') {
        if (state.jogActive) {
            mainText = '';
        } else {
            mainCode = 'PAUSED';
            mainText = 'ПАУЗА В ЦИКЛЕ';
            subText = 'Доступна ручная коррекция ленты. Нажмите ПРОДОЛЖИТЬ';
            peekable = true;
        }
    } else if (lineState === 'STOPPED') {
        if (state.jogActive) {
            mainText = '';
        } else {
            mainCode = 'STOPPED';
            mainText = 'ЛИНИЯ ОСТАНОВЛЕНА';
            subText  = 'Нажмите ПУСК для продолжения';
            peekable = false;
        }
    } else if (lineState === 'STOPPING') {
        mainCode = 'STOPPING';
        mainText = 'ОСТАНОВКА ЛИНИИ';
        subText  = `На линии осталось корпусов: ${ls.in_line || 0}`;
        peekable = true;
    } else if (lineState === 'IDLE') {
        if (state.jogActive) {
            mainText = '';
        } else {
            mainCode = 'IDLE';
            mainText = 'ГОТОВА К ПУСКУ';
            subText  = 'Нажмите ПУСК для начала работы';
            peekable = false;
        }
    }

    if (mainText) {
        els.cameraOverlay.dataset.mainText = mainCode;
        els.cameraOverlay.dataset.peekable = peekable ? '1' : '0';

        if (els.cameraOverlay.dataset.renderedMain !== mainText
            || els.cameraOverlay.dataset.renderedSub !== subText) {
            els.cameraOverlay.innerHTML = `
                <div class="camera-overlay-main"></div>
                <div class="camera-overlay-sub"></div>
            `;
            els.cameraOverlay.dataset.renderedMain = mainText;
            els.cameraOverlay.dataset.renderedSub  = subText;
        }

        const mainEl = els.cameraOverlay.querySelector('.camera-overlay-main');
        const subEl  = els.cameraOverlay.querySelector('.camera-overlay-sub');
        if (mainEl) setIfChanged(mainEl, mainText);
        if (subEl)  setIfChanged(subEl, subText);

        els.cameraOverlay.classList.remove('is-hidden');

        if (peekable && state.cameraHovered) {
            els.cameraOverlay.classList.add('overlay-peek');
        } else {
            els.cameraOverlay.classList.remove('overlay-peek');
        }
    } else {
        els.cameraOverlay.classList.add('is-hidden');
        els.cameraOverlay.dataset.mainText    = '';
        els.cameraOverlay.dataset.peekable    = '0';
        els.cameraOverlay.dataset.renderedMain = '';
        els.cameraOverlay.dataset.renderedSub  = '';
    }
}

