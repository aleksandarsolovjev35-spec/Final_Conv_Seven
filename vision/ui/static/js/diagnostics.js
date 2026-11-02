// diagnostics.js — стабилизированный модуль диагностики и анализа кадра
'use strict';

function disableSelectedAnalysisButton() {
    if (els.analyzeSelectedFrame) els.analyzeSelectedFrame.disabled = true;
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
// меняются под ней одним кадром, а не по очереди. Шторка падает вниз,
// а после переключения поднимается вверх.
const PANEL_SHUTTER_FALL = 420;        // падение, как transition в CSS
const PANEL_SHUTTER_MIN_DOWN = 820;   // падение + показ результата
const PANEL_SHUTTER_TAIL = 300;       // даём блокам доиграть переход
const PANEL_SHUTTER_FALLBACK = 5000;  // страховка, если статус не придёт
let _panelShutterTimer = null;
let _panelShutterShownAt = 0;
let _panelShutterDown = false;

// Опустить шторку и дождаться, пока она закроет панель. Интерфейс меняем
// только под ней: резкая смена блоков не должна быть видна.
function showPanelShutter(targetActive) {
    const shutter = document.getElementById('panel-shutter');
    if (!shutter) return Promise.resolve();
    state.panelShutterTarget = targetActive;
    state.panelShutterPending = true;
    _panelShutterShownAt = Date.now();
    clearTimeout(_panelShutterTimer);
    shutter.classList.add('is-down');
    _panelShutterTimer = setTimeout(hidePanelShutter, PANEL_SHUTTER_FALLBACK);
    if (_panelShutterDown) return Promise.resolve();
    return new Promise(resolve => {
        setTimeout(() => {
            _panelShutterDown = true;
            resolve();
        }, PANEL_SHUTTER_FALL);
    });
}

function hidePanelShutter() {
    if (!state.panelShutterPending) return;
    state.panelShutterPending = false;
    clearTimeout(_panelShutterTimer);
    // Не дёргаем шторку обратно, пока она не дошла до низа и блоки не
    // доиграли переход.
    const elapsed = Date.now() - _panelShutterShownAt;
    const hold = Math.max(PANEL_SHUTTER_TAIL, PANEL_SHUTTER_MIN_DOWN - elapsed);
    _panelShutterTimer = setTimeout(() => {
        _panelShutterTimer = null;
        _panelShutterDown = false;
        const shutter = document.getElementById('panel-shutter');
        if (shutter) shutter.classList.remove('is-down');
    }, hold);
}

function setupSelectedFrameAnalysis() {
    if (!els.analyzeSelectedFrame) return;
    els.analyzeSelectedFrame.addEventListener('click', async () => {
        if (els.analyzeSelectedFrame.disabled || state.selectedAnalysisPending) return;
        const releasing = state.selectedAnalysisActive;
        const role = state.currentCamera;
        if (!releasing && !role) return;
        state.selectedAnalysisPending = true;
        els.analyzeSelectedFrame.disabled = true;
        clearControlError();
        // 1. Сначала шторка падает и закрывает правую панель.
        await showPanelShutter(!releasing);
        // 2. И только под ней перестраивается интерфейс.
        // Скрываем редактирование порогов: анализируемый стоп-кадр должен
        // оставаться привязанным к уже применённым значениям.
        if (typeof updateThresholdsPanel === 'function') updateThresholdsPanel();
        updateViewModeControls();
        state.backendControls = {
            ...state.backendControls,
            start: false, jog_hold: false, distributor_diagnostic: false,
            camera_diagnostic: false, vision_rule_diagnostic: false, selected_model_analysis: false,
        };
        applyButtonsForState(state.lineState, state.serverExitRequested, state.backendControls);
        if (els.jogPanel) {
            els.jogPanel.classList.add('is-collapsed');
            els.jogPanel.querySelectorAll('.jog-hold-btn').forEach(b => { b.disabled = true; });
        }
        try {
            if (releasing) {
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
