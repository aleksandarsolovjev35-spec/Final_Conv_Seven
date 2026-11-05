// jog.js — Line Monitor UI module
'use strict';

// ─── JOG ─────────────────────────────────────────────────────

function updateJogModeSwitchUI() {
    const isStep = state.jogControlMode === 'step';
    const disabled = (
        !state.jogActive
        || state.jogBusy
        || state.jogStepPending
        || state.offline
        || state.distributorDiagnosticBackendBusy
        || state.distributorDiagnosticPending
    );

    if (els.jogModeHold) {
        els.jogModeHold.classList.toggle('is-active', !isStep);
        els.jogModeHold.setAttribute('aria-pressed', String(!isStep));
        els.jogModeHold.disabled = disabled;
    }
    if (els.jogModeStep) {
        els.jogModeStep.classList.toggle('is-active', isStep);
        els.jogModeStep.setAttribute('aria-pressed', String(isStep));
        els.jogModeStep.disabled = disabled;
    }

    if (els.jogPanel) {
        els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(btn => {
            const forward = btn.dataset.direction === '+';
            if (isStep) {
                btn.title = forward
                    ? 'Сдвинуть ленту на 1 шаг вперёд'
                    : 'Сдвинуть ленту на 1 шаг назад';
                btn.setAttribute(
                    'aria-label',
                    forward ? 'Шаг ленты вперёд' : 'Шаг ленты назад',
                );
            } else {
                btn.title = forward
                    ? 'Удерживайте для движения вперёд'
                    : 'Удерживайте для движения назад';
                btn.setAttribute(
                    'aria-label',
                    forward ? 'Двигать ленту вперёд' : 'Двигать ленту назад',
                );
            }
        });
    }
}

function setJogControlMode(mode) {
    const normalized = mode === 'step' ? 'step' : 'hold';
    if (state.jogControlMode === normalized) return;
    if (state.jogHoldDirection || state.jogStartPromise) {
        releaseJogHold('mode switched');
    }
    state.jogControlMode = normalized;
    updateJogModeSwitchUI();
}

function triggerJogPress(direction, btn) {
    if (state.jogControlMode === 'step') {
        triggerJogStep(direction, btn);
    } else {
        beginJogHold(direction, btn);
    }
}

function updateJogState(jog) {
    if (!jog) {
        if (state.jogHoldDirection || state.jogStartPromise) {
            releaseJogHoldBestEffort('missing JOG status');
        }
        state.jogActive = false;
        state.jogBusy = false;
        state.jogStepPending = false;
        state.jogStepDirection = null;
        showJogPanel(false);
        if (els.jogPanel) {
            els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(button => {
                button.disabled = true;
                button.classList.remove('jog-active');
            });
        }
        updateJogModeSwitchUI();
        if (typeof updateYoloFeedbackButtons === 'function') {
            updateYoloFeedbackButtons();
        }
        return;
    }

    state.jogReceived = true;

    const wasActive = state.jogActive;

    state.jogActive = !!jog.active;
    state.jogBusy   = !!jog.busy;
    if (!state.jogBusy && !state.jogStepPending) {
        state.jogStepDirection = null;
    }
    updateViewModeControls();

    showJogPanel(state.jogActive);
    applyLiveBadge(state.jogActive);

    const activeDir = (
        jog.direction || state.jogHoldDirection || state.jogStepDirection
    );
    const isStepMode = state.jogControlMode === 'step';

    if (els.jogPanel) {
        els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(btn => {
            const sameDirection = btn.dataset.direction === activeDir;
            const busyBlocked = isStepMode
                ? (state.jogBusy || state.jogStepPending)
                : (state.jogBusy && !sameDirection);
            btn.disabled = (
                !state.jogActive
                || state.backendControls.jog_hold !== true
                || state.distributorDiagnosticBackendBusy
                || state.distributorDiagnosticPending
                || busyBlocked
            );
            btn.classList.toggle(
                'jog-active',
                (!!jog.busy || state.jogStepPending) && sameDirection,
            );
        });
    }

    updateJogModeSwitchUI();
    if (typeof updateYoloFeedbackButtons === 'function') {
        updateYoloFeedbackButtons();
    }

    if (
        !jog.busy
        && state.jogHoldDirection
        && !state.jogReleasePending
        && !state.jogStartPromise
    ) {
        clearJogHoldLocalState();
    }

    if (state.jogTogglePending && wasActive !== state.jogActive) {
        state.jogTogglePending = false;
    }

    if (wasActive !== state.jogActive) {
        updateViewModeControls();
        applyMainCameraSource();
    }
}

function showJogPanel(active) {
    if (!els.jogPanel || !els.statsPanel) return;
    const visible = (
        JOG_ALLOWED_STATES.includes(state.lineState)
        && !state.selectedAnalysisActive
        && !state.selectedAnalysisPending
    );
    const pauseHandoff = visible && !active && state.lineState === 'PAUSED';
    els.statsPanel.classList.remove('is-hidden');
    els.jogPanel.classList.toggle('is-collapsed', !visible);
    // При переходе RUNNING → PAUSED backend включает JOG следующим запросом.
    // Не показываем промежуточное приглушённое состояние кнопок под
    // поднимающейся шторкой — оно воспринималось как короткое мигание.
    els.jogPanel.classList.toggle(
        'jog-inactive', visible && !active && !pauseHandoff,
    );
    els.jogPanel.classList.toggle('jog-pause-handoff', pauseHandoff);
    els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(button => {
        if (!visible || !active) button.disabled = true;
    });
}

function applyLiveBadge(active) {
    if (!els.modeBadge) return;
    els.modeBadge.classList.remove(
        'is-faded', 'mode-live', 'mode-analysis', 'mode-static',
    );
    // Даже «АНАЛИЗ» появляется только когда соответствующий кадр уже
    // заменил изображение в окне: до этого остаётся бейдж предыдущего кадра.
    if (state.displayedFrameKind === 'analysis') {
        els.modeBadge.textContent = 'АНАЛИЗ';
        els.modeBadge.classList.add('mode-analysis');
        return;
    }
    // Статус линии описывает желаемый источник, но img переключается позже.
    // Не меняем надпись заранее: во время загрузки нового кадра она должна
    // описывать предыдущий, ещё действительно видимый кадр.
    if (state.displayedFrameKind === 'live') {
        els.modeBadge.textContent = `ПОТОК · ${formatFrameRate(state.liveFps)}`;
        els.modeBadge.classList.add('mode-live');
        return;
    }
    if (state.displayedFrameKind === 'static') {
        els.modeBadge.textContent = (state.mode === 'RAW'
            ? 'СТОП-КАДР · МОДЕЛИ'
            : 'СТОП-КАДР · ПРАВИЛА');
        els.modeBadge.classList.add('mode-static');
        return;
    }
    els.modeBadge.textContent = '';
    els.modeBadge.classList.add('is-faded');
}

async function handleJogAutoToggle(lineState, jog) {
    const eligible = JOG_ALLOWED_STATES.includes(lineState);
    const serverActive = !!(jog && jog.active);
    const serverCanEnter = !!(jog && jog.can_enter);

    if (state.jogTogglePending || state.offline) return;

    if (eligible && !serverActive && serverCanEnter) {
        state.jogTogglePending = true;
        const result = await apiPost('/api/jog/enter');
        if (!result) state.jogTogglePending = false;
    } else if (!eligible && serverActive) {
        state.jogTogglePending = true;
        const result = await apiPost('/api/jog/exit');
        if (!result) state.jogTogglePending = false;
    }
}

function setupJogControls() {
    if (!els.jogPanel) return;

    if (els.jogModeHold) {
        els.jogModeHold.addEventListener('click', () => setJogControlMode('hold'));
    }
    if (els.jogModeStep) {
        els.jogModeStep.addEventListener('click', () => setJogControlMode('step'));
    }
    updateJogModeSwitchUI();

    els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(btn => {
        btn.addEventListener('contextmenu', e => e.preventDefault());
        btn.addEventListener('pointerdown', e => {
            e.preventDefault();
            if (state.jogControlMode === 'step') {
                triggerJogStep(btn.dataset.direction, btn);
                return;
            }
            if (btn.setPointerCapture) {
                try { btn.setPointerCapture(e.pointerId); } catch (_) {}
            }
            beginJogHold(btn.dataset.direction, btn);
        });
        for (const eventName of ['pointerup', 'pointercancel', 'lostpointercapture']) {
            btn.addEventListener(eventName, () => {
                if (state.jogHoldDirection || state.jogStartPromise) {
                    releaseJogHold(`UI ${eventName}`);
                }
            });
        }
        btn.addEventListener('pointerleave', e => {
            if (e.buttons === 0 && (state.jogHoldDirection || state.jogStartPromise)) {
                releaseJogHold('pointer left button');
            }
        });
    });

    window.addEventListener('blur', () => releaseJogHold('window blur'));
    window.addEventListener('pagehide', () => releaseJogHoldBestEffort('page hidden'));
    window.addEventListener('beforeunload', () => {
        releaseJogHoldBestEffort('page unload');
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) releaseJogHoldBestEffort('document hidden');
    });
}

async function triggerJogStep(direction, btn) {
    if (
        !state.jogActive
        || state.jogBusy
        || state.jogStepPending
        || state.offline
        || state.backendControls.jog_hold !== true
        || state.distributorDiagnosticPending
        || state.distributorDiagnosticBackendBusy
    ) return;
    if (direction !== '+' && direction !== '-') return;

    state.jogStepPending = true;
    state.jogStepDirection = direction;
    state.backendControls = {
        ...state.backendControls,
        start: false,
        exit: false,
        jog_hold: false,
        distributor_diagnostic: false,
        camera_diagnostic: false,
        vision_rule_diagnostic: false,
    };
    applyButtonsForState(
        state.lineState,
        state.serverExitRequested,
        state.backendControls,
    );
    if (els.distributorDiagnostics) {
        els.distributorDiagnostics.querySelectorAll('button').forEach(
            diagnosticButton => { diagnosticButton.disabled = true; }
        );
    }
    disableSelectedAnalysisButton();
    updateJogModeSwitchUI();
    if (typeof updateYoloFeedbackButtons === 'function') {
        updateYoloFeedbackButtons();
    }
    if (els.jogPanel) {
        els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(b => {
            b.disabled = true;
            b.classList.toggle('jog-active', b === btn);
        });
    }
    clearControlError();

    const result = await apiPostJson('/api/jog/step', {direction}, true);
    state.jogStepPending = false;
    if (!result) {
        state.jogStepDirection = null;
        if (els.jogPanel) {
            els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(b => {
                b.classList.remove('jog-active');
            });
        }
    }
    requestImmediateStatus();
}

async function beginJogHold(direction, btn) {
    if (
        !state.jogActive
        || state.jogBusy
        || state.offline
        || state.backendControls.jog_hold !== true
        || state.distributorDiagnosticPending
        || state.distributorDiagnosticBackendBusy
    ) return;
    if (direction !== '+' && direction !== '-') return;
    if (state.jogHoldDirection) return;

    state.jogHoldDirection = direction;
    state.jogReleasePending = false;
    state.backendControls = {
        ...state.backendControls,
        start: false,
        exit: false,
        distributor_diagnostic: false,
        camera_diagnostic: false,
        vision_rule_diagnostic: false,
    };
    applyButtonsForState(
        state.lineState,
        state.serverExitRequested,
        state.backendControls,
    );
    if (els.distributorDiagnostics) {
        els.distributorDiagnostics.querySelectorAll('button').forEach(
            diagnosticButton => { diagnosticButton.disabled = true; }
        );
    }
    disableSelectedAnalysisButton();
    btn.classList.add('jog-active');
    clearControlError();

    state.jogStartPromise = apiPostJson(
        '/api/jog/hold/start',
        {direction},
        true,
    );
    const result = await state.jogStartPromise;
    state.jogStartPromise = null;

    if (!result) {
        clearJogHoldLocalState();
        requestImmediateStatus();
        return;
    }
    if (state.jogReleasePending || state.jogHoldDirection !== direction) {
        await releaseJogHold('released during start');
        return;
    }
    const heartbeat = await apiPostJson('/api/jog/hold/heartbeat', {
        direction,
    });
    if (!heartbeat) {
        await releaseJogHold('initial heartbeat rejected');
        return;
    }
    startJogHeartbeat(direction);
    requestImmediateStatus();
}

function startJogHeartbeat(direction) {
    stopJogHeartbeat();
    state.jogHeartbeatTimer = setInterval(async () => {
        if (
            state.jogHoldDirection !== direction
            || state.jogHeartbeatBusy
        ) return;
        state.jogHeartbeatBusy = true;
        const result = await apiPostJson('/api/jog/hold/heartbeat', {
            direction,
        });
        state.jogHeartbeatBusy = false;
        if (!result && state.jogHoldDirection === direction) {
            releaseJogHold('heartbeat rejected');
        }
    }, JOG_HEARTBEAT_INTERVAL);
}

function stopJogHeartbeat() {
    if (state.jogHeartbeatTimer) {
        clearInterval(state.jogHeartbeatTimer);
        state.jogHeartbeatTimer = null;
    }
}

async function releaseJogHold(reason = 'button released') {
    if (!state.jogHoldDirection && !state.jogStartPromise) return;
    if (state.jogReleasePending) return;
    state.jogReleasePending = true;
    stopJogHeartbeat();
    els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(btn => {
        btn.classList.remove('jog-active');
    });

    if (state.jogStartPromise) {
        await state.jogStartPromise;
        state.jogStartPromise = null;
    }
    await apiPostJson('/api/jog/hold/release', {reason}, true);
    clearJogHoldLocalState();
    requestImmediateStatus();
}

function releaseJogHoldBestEffort(reason) {
    if (!state.jogHoldDirection && !state.jogStartPromise) return;
    stopJogHeartbeat();
    state.jogReleasePending = true;
    fetch('/api/jog/hold/release', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
        keepalive: true,
    }).catch(() => {});
    clearJogHoldLocalState();
}

function clearJogHoldLocalState() {
    stopJogHeartbeat();
    state.jogHoldDirection = null;
    state.jogHeartbeatBusy = false;
    state.jogReleasePending = false;
    state.jogStartPromise = null;
    if (els.jogPanel) {
        els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(btn => {
            btn.classList.remove('jog-active');
            btn.disabled = (
                !state.jogActive
                || state.backendControls.jog_hold !== true
                || state.distributorDiagnosticBackendBusy
                || state.distributorDiagnosticPending
            );
        });
    }
}

