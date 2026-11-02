// diagnostics.js — стабилизированный модуль диагностики и анализа кадра
'use strict';

function disableSelectedAnalysisButton() {
    if (els.analyzeSelectedFrame) els.analyzeSelectedFrame.disabled = true;
}

function updateDistributorDiagnosticControls(ls) {
    if (!els.distributorDiagnostics) return;
    const allowed = ls.diagnostic_allowed === true && (!ls.controls || ls.controls.distributor_diagnostic === true) && !state.offline;
    state.distributorDiagnosticBackendBusy = ls.diagnostic_busy === true;
    const busy = state.distributorDiagnosticBackendBusy || state.distributorDiagnosticPending;
    els.distributorDiagnostics.querySelectorAll('button').forEach(button => {
        button.disabled = !allowed || busy;
        button.classList.toggle('pending', busy);
    });
}

function setupDistributorDiagnostics() {
    if (!els.distributorDiagnostics) return;
    els.distributorDiagnostics.querySelectorAll('button').forEach(button => {
        button.addEventListener('click', async () => {
            if (button.disabled || state.distributorDiagnosticPending) return;
            const command = button.dataset.distributorCommand;
            if (!command) return;
            state.distributorDiagnosticPending = true;
            startStatusPolling();
            updateViewModeControls();
            state.backendControls = {
                ...state.backendControls,
                start: false, exit: false, jog_hold: false,
                distributor_diagnostic: false, camera_diagnostic: false, vision_rule_diagnostic: false,
            };
            applyButtonsForState(state.lineState, state.serverExitRequested, state.backendControls);
            if (els.jogPanel) els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(b => { b.disabled = true; });
            disableSelectedAnalysisButton();
            updateDistributorDiagnosticControls({diagnostic_allowed: false, diagnostic_busy: true});
            try {
                clearControlError();
                await apiPost(`/api/distributor/diagnostic/${command}`, true);
            } finally {
                state.distributorDiagnosticPending = false;
                startStatusPolling();
                updateViewModeControls();
                requestImmediateStatus();
            }
        });
    });
}

function updateSelectedAnalysisStatus(ls) {
    if (!els.analyzeSelectedFrame) return;
    const selected = ls.selected_analysis || {};
    const wasActive = state.selectedAnalysisActive;
    const wasLiveStreaming = state.liveStreaming;
    // Пока бэкенд завершает выход из анализа (он переснимает кадры всех
    // камер), интерфейс уже в live: не возвращаем стоп-кадр обратно.
    state.selectedAnalysisActive = (
        selected.active === true && !state.analysisReleasePending
    );
    state.selectedAnalysisRole = selected.role || null;
    if (wasActive !== state.selectedAnalysisActive && typeof updateThresholdsPanel === 'function') {
        updateThresholdsPanel();
    }

    // Во время анализа кадра параметры линии не нужны: они уже применены
    // к показанному результату.
    if (els.statsPanel) {
        els.statsPanel.classList.toggle('analysis-active', state.selectedAnalysisActive);
    }
    const selectedActive = state.selectedAnalysisActive && JOG_ALLOWED_STATES.includes(state.lineState);
    if (els.statsSummary) els.statsSummary.classList.toggle('is-collapsed', selectedActive);
    if (els.distributorDiagnostics) els.distributorDiagnostics.classList.toggle('is-collapsed', selectedActive);

    const live = ls.live || {};
    state.liveFps = Number(live.fps || (ls.jog || {}).live_fps || 0);
    const staticRoles = Array.isArray(live.static_roles) ? live.static_roles : [];
    const process = ls.process || {};
    const inspectionRoles = Array.isArray(process.inspection_roles) ? process.inspection_roles : [];
    const phase = String(process.phase || '').toUpperCase();
    const inspectionDisplay = inspectionRoles.includes(state.currentCamera)
        && isInspectionDisplayPhase(phase);
    const selectedRoleStatic = live.all_roles_static === true
        || staticRoles.includes(state.currentCamera)
        || inspectionDisplay
        // Совместимость со статусом backend до ролевых пауз.
        || (live.static === true && live.streaming === false && staticRoles.length === 0);
    // Источник главной камеры зависит от её собственной роли, а не от
    // inspection другой группы камер.
    state.liveStreaming = live.running === true && !selectedRoleStatic;

    if (wasLiveStreaming !== state.liveStreaming && typeof applyMainCameraSource === 'function') {
        applyMainCameraSource();
    }

    const controls = ls.controls || {};
    const allowed = state.selectedAnalysisActive ? controls.selected_model_release === true : controls.selected_model_analysis === true;
    const lineState = state.lineState;
    const showAnalysis = (lineState === 'IDLE' || lineState === 'STOPPED') || state.selectedAnalysisActive;
    els.analyzeSelectedFrame.classList.toggle('is-hidden', !showAnalysis);
    els.analyzeSelectedFrame.disabled = !allowed || state.selectedAnalysisPending || state.analysisReleasePending || state.offline || !state.currentCamera;
    els.analyzeSelectedFrame.textContent = state.selectedAnalysisActive ? 'ВЕРНУТЬ ПОТОК' : 'АНАЛИЗ КАДРА';
    els.analyzeSelectedFrame.classList.toggle('analysis-active', state.selectedAnalysisActive);

    if (typeof applyLiveBadge === 'function') applyLiveBadge(state.jogActive);
    updateViewModeControls();

    // Шторка правой панели: поднимаем, когда целевое состояние анализа уже
    // в интерфейсе — блоки успели перестроиться под ней.
    if (state.panelShutterPending && state.selectedAnalysisActive === state.panelShutterTarget) {
        hidePanelShutter();
    }

    if (state.selectedAnalysisActive) {
        showSelectedAnalysisFrame(state.selectedAnalysisRole);
    } else if (wasActive) {
        returnSelectedCameraToLive();
    }
}

// ——— выбранный кадр: кнопки ———

// Шторка правой панели на время переключения анализа кадра: блоки
// меняются под ней одним кадром, а не по очереди.
const PANEL_SHUTTER_TAIL = 240;      // переходы блоков .ui-collapse
const PANEL_SHUTTER_FALLBACK = 5000;  // страховка, если статус не пришёл
let _panelShutterTimer = null;

function showPanelShutter(targetActive) {
    const shutter = document.getElementById('panel-shutter');
    if (!shutter) return;
    state.panelShutterTarget = targetActive;
    state.panelShutterPending = true;
    shutter.classList.remove('is-hidden');
    clearTimeout(_panelShutterTimer);
    _panelShutterTimer = setTimeout(hidePanelShutter, PANEL_SHUTTER_FALLBACK);
}

function hidePanelShutter() {
    if (!state.panelShutterPending || _panelShutterTimer === null) return;
    state.panelShutterPending = false;
    clearTimeout(_panelShutterTimer);
    // Даём блокам доиграть переход, и только потом поднимаем шторку.
    _panelShutterTimer = setTimeout(() => {
        _panelShutterTimer = null;
        const shutter = document.getElementById('panel-shutter');
        if (shutter) shutter.classList.add('is-hidden');
    }, PANEL_SHUTTER_TAIL);
}

function setupSelectedFrameAnalysis() {
    if (!els.analyzeSelectedFrame) return;
    els.analyzeSelectedFrame.addEventListener('click', async () => {
        if (els.analyzeSelectedFrame.disabled || state.selectedAnalysisPending) return;
        state.selectedAnalysisPending = true;
        // Скрываем редактирование порогов сразу: анализируемый стоп-кадр
        // должен оставаться привязанным к уже применённым значениям.
        if (typeof updateThresholdsPanel === 'function') updateThresholdsPanel();
        updateViewModeControls();
        els.analyzeSelectedFrame.disabled = true;
        state.backendControls = {
            ...state.backendControls,
            start: false, jog_hold: false, distributor_diagnostic: false,
            camera_diagnostic: false, vision_rule_diagnostic: false, selected_model_analysis: false,
        };
        applyButtonsForState(state.lineState, state.serverExitRequested, state.backendControls);
        if (els.distributorDiagnostics) els.distributorDiagnostics.querySelectorAll('button').forEach(b => { b.disabled = true; });
        if (els.jogPanel) {
            els.jogPanel.classList.add('is-collapsed');
            els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(b => { b.disabled = true; });
        }
        clearControlError();
        try {
            if (state.selectedAnalysisActive) {
                showPanelShutter(false);
                // Не ждём ответа: бэкенд возвращает поток, последовательно
                // переснимая кадры всех камер, а интерфейс должен ожить сразу.
                state.analysisReleasePending = true;
                state.selectedAnalysisActive = false;
                state.selectedAnalysisPending = false;
                state.selectedAnalysisRole = null;
                returnSelectedCameraToLive();
                // Блоки правой панели вернёт ближайший статус — все вместе,
                // а не по одному (пороги успевали появиться раньше остальных).
                requestImmediateStatus();
                await apiPost('/api/diagnostics/selected/release', true);
            } else {
                const role = state.currentCamera;
                if (!role) return;
                showPanelShutter(true);
                await apiPost(`/api/diagnostics/selected/${encodeURIComponent(role)}`, true);
            }
        } finally {
            state.selectedAnalysisPending = false;
            state.analysisReleasePending = false;
            updateViewModeControls();
            requestImmediateStatus();
        }
    });
}

// Совместимость с тестами — минимальный экспорт
if (typeof window !== 'undefined') {
    window.updateSelectedAnalysisStatus = updateSelectedAnalysisStatus;
}
