// controls.js — Line Monitor UI module
'use strict';

// ─── Buttons ─────────────────────────────────────────────────

function applyButtonsForState(lineState, exitRequested, controls = {}) {
    const offline = state.offline || lineState === 'OFFLINE';
    const pending = state.controlPending;
    const lockSettings = offline || pending || !['IDLE', 'STOPPED'].includes(lineState);
    ['conveyor-speed', 'settle-time', 'review-time'].forEach(id => {
        const slider = document.getElementById(id);
        if (slider && lockSettings) slider.disabled = true;
    });
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
        // Пуск невозможен без входа оператора и выбранной партии: кнопка
        // остаётся видимой, но заблокированной и с иконкой замка.
        const batchLocked = (
            !state.batchSelected && startVisible && !pending && !offline
        );
        els.btnStart.disabled = (
            !startVisible
            || controls.start !== true
            || pending
            || offline
            || !state.operatorName
            || !state.batchSelected
        );
        els.btnStart.setAttribute(
            'aria-disabled', String(els.btnStart.disabled || batchLocked),
        );
        els.btnStart.classList.toggle('is-batch-locked', batchLocked);
        const lockIcon = document.getElementById('start-lock-icon');
        if (lockIcon) lockIcon.classList.toggle('is-hidden', !batchLocked);
        const startLabel = document.getElementById('start-label');
        if (startLabel) startLabel.classList.toggle('is-hidden', batchLocked);
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
    if (els.distributorDiagnostics) {
        els.distributorDiagnostics.querySelectorAll('button').forEach(
            button => { button.disabled = true; }
        );
    }
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

// ─── Скорость ленты (в процентах) ────────────────────────────

// Аппаратные пределы совпадают с hardware.conveyor.Conveyor. Ползунок
// показывает проценты от максимальной скорости: 25 % = 5000 шаг/с.
const CONVEYOR_SPEED_MIN = 5000;
const CONVEYOR_SPEED_MAX = 20000;

let conveyorSpeedPending = false;
let conveyorSpeedEditing = false;

function conveyorPercentToSpeed(percent) {
    return Math.round(CONVEYOR_SPEED_MAX * Number(percent) / 100);
}

function conveyorSpeedToPercent(speed) {
    const value = Math.round(Number(speed) / CONVEYOR_SPEED_MAX * 100);
    return Math.max(0, Math.min(100, value));
}

function updateRangeFill(slider) {
    const min = Number(slider.min) || 0;
    const max = Number(slider.max) || 100;
    const value = Number(slider.value) || 0;
    const percent = max > min
        ? Math.max(0, Math.min(100, (value - min) / (max - min) * 100))
        : 0;
    slider.style.setProperty('--fill', `${percent.toFixed(1)}%`);
}

function formatConveyorSpeed(percent) {
    // В компактной строке показываем главное — проценты. Точная скорость
    // в шаг/с остаётся в подсказке (title) ползунка.
    return `${Math.round(percent)} %`;
}

function conveyorSpeedTitle(speed) {
    return `${Math.round(speed).toLocaleString('ru-RU')} шаг/с`;
}

function updateConveyorSpeed(ls) {
    const slider = document.getElementById('conveyor-speed');
    const output = document.getElementById('conveyor-speed-value');
    if (!slider || !output) return;
    const maxSpeed = Number.isFinite(ls.conveyor_speed_max)
        ? Number(ls.conveyor_speed_max) : CONVEYOR_SPEED_MAX;
    const minSpeed = Number.isFinite(ls.conveyor_speed_min)
        ? Number(ls.conveyor_speed_min) : CONVEYOR_SPEED_MIN;
    const percentMin = Math.max(1, Math.round(minSpeed / maxSpeed * 100));
    slider.min = String(percentMin);
    slider.max = '100';
    slider.disabled = !ls.speed_allowed || state.offline || state.controlPending || conveyorSpeedPending;
    if (conveyorSpeedEditing || conveyorSpeedPending || !Number.isFinite(ls.conveyor_speed)) return;
    const percent = Number.isFinite(ls.conveyor_speed_percent)
        ? Number(ls.conveyor_speed_percent)
        : conveyorSpeedToPercent(ls.conveyor_speed);
    slider.value = String(percent);
    updateRangeFill(slider);
    output.textContent = formatConveyorSpeed(percent);
    const speedText = conveyorSpeedTitle(ls.conveyor_speed);
    output.title = speedText;
    slider.title = speedText;
}

// ─── Паузы инспекции ─────────────────────────────────────────

const INSPECTION_TIMING_FIELDS = [
    {key: 'settle_time', sliderId: 'settle-time', outputId: 'settle-time-value'},
    {key: 'review_time', sliderId: 'review-time', outputId: 'review-time-value'},
];

let inspectionTimingsPending = false;
const inspectionTimingEditing = {settle_time: false, review_time: false};

function formatSeconds(value) {
    return `${Number(value).toFixed(1)} с`;
}

function updateInspectionTimings(ls) {
    const timings = ls.inspection_timings || {};
    const allowed = ls.timings_allowed === true
        && !state.offline && !state.controlPending && !inspectionTimingsPending;
    INSPECTION_TIMING_FIELDS.forEach(({key, sliderId, outputId}) => {
        const slider = document.getElementById(sliderId);
        const output = document.getElementById(outputId);
        if (!slider || !output) return;
        slider.disabled = !allowed;
        if (inspectionTimingEditing[key] || inspectionTimingsPending) return;
        const value = Number(timings[key]);
        if (!Number.isFinite(value)) {
            output.textContent = '—';
            return;
        }
        slider.value = String(value);
        updateRangeFill(slider);
        output.textContent = formatSeconds(value);
    });
}

function readInspectionTimings() {
    return {
        settle_time: Number(document.getElementById('settle-time').value),
        review_time: Number(document.getElementById('review-time').value),
    };
}

function setupButtons() {
    const speedSlider = document.getElementById('conveyor-speed');
    if (speedSlider) {
        speedSlider.addEventListener('input', () => {
            conveyorSpeedEditing = true;
            const percent = Number(speedSlider.value);
            const output = document.getElementById('conveyor-speed-value');
            output.textContent = formatConveyorSpeed(percent);
            const speedText = conveyorSpeedTitle(conveyorPercentToSpeed(percent));
            output.title = speedText;
            speedSlider.title = speedText;
            updateRangeFill(speedSlider);
        });
        speedSlider.addEventListener('change', async () => {
            conveyorSpeedEditing = false;
            if (speedSlider.disabled || conveyorSpeedPending || state.offline) return;
            const percent = Number(speedSlider.value);
            conveyorSpeedPending = true;
            speedSlider.disabled = true;
            try {
                await apiPostJson('/api/conveyor/speed', {
                    speed: conveyorPercentToSpeed(percent),
                    percent,
                }, true);
            } finally {
                conveyorSpeedPending = false;
                requestImmediateStatus();
            }
        });
    }

    INSPECTION_TIMING_FIELDS.forEach(({key, sliderId, outputId}) => {
        const slider = document.getElementById(sliderId);
        const output = document.getElementById(outputId);
        if (!slider || !output) return;
        slider.addEventListener('input', () => {
            inspectionTimingEditing[key] = true;
            updateRangeFill(slider);
            output.textContent = formatSeconds(slider.value);
        });
        slider.addEventListener('change', async () => {
            inspectionTimingEditing[key] = false;
            if (slider.disabled || inspectionTimingsPending || state.offline) return;
            inspectionTimingsPending = true;
            INSPECTION_TIMING_FIELDS.forEach(field => {
                const el = document.getElementById(field.sliderId);
                if (el) el.disabled = true;
            });
            try {
                await apiPostJson(
                    '/api/inspection/timings',
                    readInspectionTimings(),
                    true,
                );
            } finally {
                inspectionTimingsPending = false;
                requestImmediateStatus();
            }
        });
    });

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

