// batch.js — менеджер партий: номер партии и учёт корпусов.
//
// Сначала оператор входит в программу по ФИО и паролю (operator.js), и
// только после этого доступна вкладка «ПАРТИЯ» — она открыта по умолчанию:
// карточка держит номер партии и пуск учёта, а ФИО оператора показано
// плашкой над вкладками и в карточке не повторяется. Пока партия не открыта,
// пуск линии заблокирован (controls.start приходит с backend). Второе лицо
// сервисной зоны — пороги (по нажатию вкладки).
'use strict';

const BATCH_FINISH_CONFIRM_MS = 5000;

let batchData = null;
let batchSignature = null;
let batchFetchBusy = false;
let batchBusy = false;
let batchFinishArmed = false;
let batchFinishTimer = null;
let batchLabelTouched = false;
// Выбор вкладки оператором и фактически показанное лицо зоны. По умолчанию
// открыта «ПАРТИЯ» — вход в программу ведёт к работе с партией; «ПОРОГИ» —
// только по явному нажатию. Опрос статуса выбор не перетирает.
let deckFace = 'batch';
let deckFaceShown = 'batch';

// ─── Доступность ─────────────────────────────────────────────

function batchManagerAvailable() {
    return !!(batchData && batchData.available === true);
}

function batchActive() {
    return !!(batchData && batchData.active === true && batchData.batch);
}

// Вкладка «ПАРТИЯ» — после назначения оператора: до входа партии не
// ведутся, поэтому и открывать в карточке нечего.
function batchFaceAvailable() {
    const operator = typeof operatorAssigned === 'function'
        ? operatorAssigned() : true;
    return batchManagerAvailable() && operator;
}

function batchStatusText() {
    if (!batchManagerAvailable()) return 'ПАРТИЯ НЕ ОТКРЫТА';
    if (!batchActive()) return 'ПАРТИЯ НЕ ОТКРЫТА';
    const batch = batchData.batch;
    const operator = String(batch.operator || '').trim();
    return operator
        ? `ПАРТИЯ ${batch.label || batch.batch_id} · ${operator}`
        : `ПАРТИЯ ${batch.label || batch.batch_id}`;
}

// Пуск линии доступен только в открытую партию: backend присылает
// controls.start = false, здесь добавляем только пояснение к кнопке.
function batchBlocksStart() {
    return batchManagerAvailable() && !batchActive();
}

// Оператор для партии берётся из сессии входа: карточка его только
// показывает — подменить ФИО в запросе нельзя.
function batchOperatorValue() {
    return typeof operatorName === 'function' ? operatorName() : '';
}

function batchBusyNow() {
    return (
        batchBusy
        || state.controlPending
        || state.startPending
        || state.jogBusy
    );
}

function batchEditableNow() {
    return (
        batchManagerAvailable()
        && batchData.editable === true
        && !batchBusyNow()
    );
}

// Правая колонка построена вокруг партии: карточка видна и на ходу — по
// ней оператор видит, в какую партию пишутся корпуса. Лицо «АВАРИЯ» и
// недоступные вкладки прячутся отдельно (CSS-лицо панели и disable вкладок).
function serviceDeckVisible() {
    return (
        !state.splashActive
        && !state.offline
        && !state.serverExitRequested
    );
}

// Пороги доступны только в ручном режиме на остановленной линии:
// переключаться на их вкладку имеет смысл лишь тогда, когда она рабочая.
function thresholdsFaceAvailable() {
    return (
        typeof thresholdsPanelVisible === 'function'
        && thresholdsPanelVisible()
    );
}

// ─── Колода «ПАРТИЯ» / «ПОРОГИ» ──────────────────────────────

// Лицо, которое зона может показать сейчас: выбор оператора уважается,
// но недоступную карточку не показываем (партия — только с оператором,
// пороги — только в ручном режиме на остановленной линии). По умолчанию
// зона открыта на «ПАРТИИ».
function deckFaceToShow() {
    const batchOk = batchFaceAvailable();
    const thresholdsOk = thresholdsFaceAvailable();
    if (deckFace === 'thresholds') {
        return thresholdsOk ? 'thresholds' : 'batch';
    }
    return batchOk ? 'batch' : (thresholdsOk ? 'thresholds' : 'batch');
}

function applyDeckFace() {
    const face = deckFaceToShow();
    const changed = face !== deckFaceShown;
    deckFaceShown = face;
    if (els.serviceDeck) els.serviceDeck.dataset.face = face;
    [els.deckTabBatch, els.deckTabThresholds].forEach(tab => {
        if (!tab) return;
        const isActive = tab.dataset.deckFace === face;
        tab.classList.toggle('is-active', isActive);
        tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    if (changed && typeof updateThresholdsPanel === 'function') {
        // Панель порогов сама решает, показывать ли содержимое: при
        // переключении на её вкладку данные перечитываются, при уходе —
        // только перерисовываются (без лишних запросов).
        updateThresholdsPanel(face === 'thresholds');
    }
}

function setDeckFace(face) {
    if (face !== 'batch' && face !== 'thresholds') return;
    if (face === 'thresholds' && !thresholdsFaceAvailable()) return;
    deckFace = face;
    applyDeckFace();
}

function updateServiceDeck() {
    if (!els.serviceDeck) return;
    const visible = serviceDeckVisible();
    els.serviceDeck.classList.toggle('is-hidden', !visible);
    if (els.deckTabBatch) {
        const available = batchFaceAvailable();
        els.deckTabBatch.disabled = !available;
        els.deckTabBatch.title = available
            ? 'Партия: номер и учёт корпусов'
            : 'Вкладка доступна после входа в программу';
    }
    if (els.deckTabThresholds) {
        const available = thresholdsFaceAvailable();
        els.deckTabThresholds.disabled = !available;
        els.deckTabThresholds.title = available
            ? 'Пороги правил камеры'
            : 'Пороги доступны в ручном режиме на остановленной линии';
    }
    // Лицо зоны выбирает оператор: опрос статуса вкладку не перетирает.
    // По умолчанию открыта «ПАРТИЯ» — с неё начинается смена; «ПОРОГИ»
    // показываются только после явного нажатия вкладки. Если пороги
    // перестали быть доступны (выход из ручного режима, движение линии),
    // зона сама вернёт карточку партии.
    applyDeckFace();
}

// ─── Заполнение карточки ─────────────────────────────────────

function setBatchStatus(text, kind = '') {
    setBatchPanelStatus(els.batchStatus, text, kind);
}

function setBatchActiveStatus(text, kind = '') {
    setBatchPanelStatus(els.batchActiveStatus, text, kind);
}

function setBatchPanelStatus(element, text, kind) {
    if (!element) return;
    setIfChanged(element, text || '');
    element.classList.toggle('is-error', kind === 'error');
    element.classList.toggle('is-warn', kind === 'warn');
}

function renderBatchOpenList(open) {
    const container = els.batchOpenList;
    if (!container) return;
    container.innerHTML = '';
    const items = (open || []).filter(item => item && item.batch_id);
    if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'batch-open-empty';
        empty.textContent = 'Незавершённых партий нет';
        container.appendChild(empty);
        return;
    }
    items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'batch-open-row';
        row.dataset.batchId = item.batch_id;

        const text = document.createElement('div');
        text.className = 'batch-open-text';
        const title = document.createElement('div');
        title.className = 'batch-open-label';
        title.textContent = item.label || item.batch_id;
        title.title = `${item.label || item.batch_id} · ${item.batch_id}`;
        const meta = document.createElement('div');
        meta.className = 'batch-open-meta';
        const counts = item.counts || {};
        const parts = [
            item.operator || '—',
            `корпусов ${counts.total || 0}`,
        ];
        if (item.started_at) parts.push(String(item.started_at).replace('T', ' '));
        meta.textContent = parts.join(' · ');
        text.appendChild(title);
        text.appendChild(meta);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm batch-open-continue';
        button.textContent = 'ПРОДОЛЖИТЬ';
        button.disabled = true;
        button.addEventListener('click', () => continueBatch(item));
        if (item.available === false) {
            button.textContent = 'НЕТ ПАПКИ';
            button.disabled = true;
            button.title = 'Папка партии не найдена в архиве';
        }
        row.appendChild(text);
        row.appendChild(button);
        container.appendChild(row);
    });
}

function renderBatchInfo(batch) {
    const info = els.batchActiveInfo;
    if (!info) return;
    info.innerHTML = '';
    const counts = batch.counts || {};
    // Оператора в карточке нет: он показан плашкой над вкладками (и в
    // строке партии футера) — здесь только признаки самой партии.
    const rows = [
        ['НОМЕР ПАРТИИ', batch.label || batch.batch_id],
        ['КОД ПАРТИИ', batch.batch_id || '—'],
        ['НАЧАЛАСЬ', String(batch.started_at || '—').replace('T', ' ')],
    ];
    rows.forEach(([label, value]) => {
        const row = document.createElement('div');
        row.className = 'batch-info-row';
        const name = document.createElement('span');
        name.className = 'batch-info-label';
        name.textContent = label;
        const text = document.createElement('span');
        text.className = 'batch-info-value';
        text.textContent = value;
        text.title = value;
        row.appendChild(name);
        row.appendChild(text);
        info.appendChild(row);
    });
    // Счётчики партии — компактной сеткой 2 × 2: столько же места,
    // сколько у статистики рабочего цикла, и цвет только у вердиктов.
    const grid = document.createElement('div');
    grid.className = 'batch-counts';
    [
        ['ВСЕГО', counts.total || 0, ''],
        ['ГОДНО', counts.good || 0, 'good'],
        ['БРАК', counts.bad || 0, 'bad'],
        ['ЗАЧИСТКА', counts.cleanup || 0, 'warn'],
    ].forEach(([label, value, kind]) => {
        const cell = document.createElement('div');
        cell.className = 'batch-count' + (kind ? ` ${kind}` : '');
        const name = document.createElement('span');
        name.className = 'batch-count-label';
        name.textContent = label;
        const number = document.createElement('span');
        number.className = 'batch-count-value';
        number.textContent = String(value);
        cell.appendChild(name);
        cell.appendChild(number);
        grid.appendChild(cell);
    });
    info.appendChild(grid);
}

// Строки карточки: номер партии и пуск учёта. Цветная полоса слева ведёт
// оператора к следующему действию (оператор смены — плашкой над вкладками).
function updateBatchSteps() {
    const label = els.batchLabelInput
        ? String(els.batchLabelInput.value || '').trim() : '';
    const labelDone = label.length > 0;
    if (els.batchStepLabel) {
        els.batchStepLabel.dataset.state = labelDone ? 'done' : 'active';
    }
    if (els.batchStepStart) {
        els.batchStepStart.dataset.state = labelDone ? 'active' : 'todo';
    }
}

function updateBatchPanelControls() {
    const editable = batchEditableNow();
    const active = batchActive();
    if (els.batchPanel) {
        els.batchPanel.classList.toggle('is-locked', !editable);
    }
    if (els.batchUnavailable) {
        els.batchUnavailable.classList.toggle(
            'is-hidden', batchManagerAvailable(),
        );
    }
    if (els.batchOpenFace) {
        els.batchOpenFace.classList.toggle('is-hidden', active);
    }
    if (els.batchActiveFace) {
        els.batchActiveFace.classList.toggle('is-hidden', !active);
    }
    if (els.batchStart) {
        els.batchStart.disabled = !editable || active || !batchFormFilled();
    }
    updateBatchSteps();
    if (els.batchFinish) {
        const canFinish = editable
            && active
            && batchData.can_finish === true;
        els.batchFinish.disabled = !canFinish;
        els.batchFinish.classList.toggle('is-armed', batchFinishArmed);
        els.batchFinish.textContent = batchFinishArmed
            ? 'ПОДТВЕРДИТЬ ЗАВЕРШЕНИЕ'
            : 'ЗАВЕРШИТЬ ПАРТИЮ';
    }
    if (els.batchOpenList) {
        els.batchOpenList.querySelectorAll('.batch-open-continue')
            .forEach(button => {
                if (button.textContent === 'НЕТ ПАПКИ') return;
                button.disabled = !editable || batchBusy;
            });
    }
    if (els.batchLabelInput) els.batchLabelInput.disabled = !editable || active;
    if (els.btnStart && !active && !state.offline) {
        els.btnStart.title = batchBlocksStart()
            ? 'Сначала начните партию в карточке «ПАРТИЯ»'
            : '';
    }
    updateBatchHint();
}

function updateBatchHint() {
    if (!els.batchActiveHint) return;
    let hint = 'Учёт корпусов ведётся в этой партии';
    if (batchActive() && batchData.can_finish !== true) {
        if (state.lineState !== 'IDLE' && state.lineState !== 'STOPPED') {
            hint = 'Завершение — после полной остановки линии';
        } else {
            hint = 'На линии остались корпуса: завершение после их выхода';
        }
    }
    setIfChanged(els.batchActiveHint, hint);
}

function batchFormFilled() {
    const label = els.batchLabelInput
        ? String(els.batchLabelInput.value || '').trim() : '';
    return batchOperatorValue().length >= 3 && label.length > 0;
}

function renderBatchFooter() {
    if (!els.footerBatch) return;
    const active = batchActive();
    setIfChanged(els.footerBatch, active
        ? batchStatusText()
        : 'ПАРТИЯ НЕ ОТКРЫТА');
    els.footerBatch.classList.toggle('is-active', active);
    els.footerBatch.title = active
        ? batchStatusText()
        : 'Учёт корпусов ведётся в открытой партии';
}

function renderBatchPanel() {
    if (!els.batchPanel) return;
    if (els.batchLabelInput && !batchLabelTouched) {
        els.batchLabelInput.value = String(batchData.suggestion || '');
        batchLabelTouched = !!els.batchLabelInput.value;
    }
    if (batchActive()) {
        renderBatchInfo(batchData.batch);
        setBatchStatus('');
    } else {
        renderBatchOpenList(batchData.open);
    }
    updateBatchPanelControls();
    updateServiceDeck();
}

// Подпись состояния: перерисовка только при реальных изменениях, иначе
// поллинг статуса ломал бы ввод ФИО и нажатия кнопок.
function batchDataSignature(data) {
    if (!data || data.available !== true) {
        return `unavailable:${!!data}`;
    }
    const batch = data.batch || {};
    const open = (data.open || []).map(item => [
        item.batch_id, item.status, item.available,
        (item.counts || {}).total,
    ].join(':'));
    return [
        data.active,
        data.editable,
        data.can_finish,
        batch.batch_id,
        batch.label,
        (batch.counts || {}).total,
        (batch.counts || {}).good,
        (batch.counts || {}).bad,
        (batch.counts || {}).cleanup,
        open.join('|'),
    ].join('~');
}

function applyBatchPayload(data) {
    batchData = data || null;
    if (!batchManagerAvailable()) {
        setBatchStatus('');
        renderBatchFooter();
        updateBatchPanelControls();
        updateServiceDeck();
        return;
    }
    const signature = batchDataSignature(batchData);
    if (signature !== batchSignature) {
        batchSignature = signature;
        renderBatchPanel();
    } else {
        updateBatchPanelControls();
        updateServiceDeck();
    }
    renderBatchFooter();
}

// Вызывается из status.js на каждом опросе /api/status.
function updateBatchStatus(data) {
    if (!data) return;
    applyBatchPayload(data);
}

async function fetchBatch() {
    if (batchFetchBusy) return;
    batchFetchBusy = true;
    const data = await apiGet('/api/batch');
    batchFetchBusy = false;
    if (data) applyBatchPayload(data);
}

// ─── Действия оператора ──────────────────────────────────────

async function submitBatchOpen(payload, message) {
    batchBusy = true;
    updateBatchPanelControls();
    setBatchStatus(message);
    try {
        const result = await apiPostJson('/api/batch/open', payload, true);
        if (!result || result.ok !== true || !result.batch) {
            setBatchStatus('Не удалось открыть партию', 'error');
            return null;
        }
        setBatchStatus('');
        applyBatchPayload(result.batch);
        return result.batch;
    } finally {
        batchBusy = false;
        updateBatchPanelControls();
        updateServiceDeck();
    }
}

async function startBatch() {
    if (batchBusy) return null;
    if (batchActive()) return null;
    if (!operatorAssigned()) {
        setBatchStatus('Сначала войдите в программу', 'error');
        return null;
    }
    if (!batchFormFilled()) {
        setBatchStatus('Укажите номер партии', 'error');
        if (els.batchLabelInput) els.batchLabelInput.focus();
        return null;
    }
    if (!batchEditableNow()) {
        setBatchStatus('Партия открывается на остановленной линии', 'warn');
        return null;
    }
    return submitBatchOpen({
        label: String(els.batchLabelInput.value || '').trim(),
    }, 'Открытие партии…');
}

async function continueBatch(item) {
    if (batchBusy) return null;
    if (!operatorAssigned()) {
        setBatchStatus('Сначала войдите в программу', 'error');
        return null;
    }
    if (!batchEditableNow()) {
        setBatchStatus('Продолжить партию можно на остановленной линии', 'warn');
        return null;
    }
    return submitBatchOpen({
        label: item.label || item.batch_id,
        batch_id: item.batch_id,
    }, 'Продолжение партии…');
}

function disarmBatchFinish() {
    batchFinishArmed = false;
    if (batchFinishTimer) {
        clearTimeout(batchFinishTimer);
        batchFinishTimer = null;
    }
    updateBatchPanelControls();
}

async function finishBatch() {
    if (batchBusy || !batchActive()) return null;
    if (!batchEditableNow() || batchData.can_finish !== true) {
        setBatchActiveStatus('Завершение доступно после полной остановки', 'warn');
        return null;
    }
    // Завершение партии необратимо (манифест CLOSED, отправка, ZIP),
    // поэтому второе нажатие подтверждает действие.
    if (!batchFinishArmed) {
        batchFinishArmed = true;
        setBatchActiveStatus('Нажмите «ПОДТВЕРДИТЬ ЗАВЕРШЕНИЕ»', 'warn');
        updateBatchPanelControls();
        if (batchFinishTimer) clearTimeout(batchFinishTimer);
        batchFinishTimer = setTimeout(disarmBatchFinish, BATCH_FINISH_CONFIRM_MS);
        return null;
    }
    disarmBatchFinish();
    batchBusy = true;
    updateBatchPanelControls();
    setBatchActiveStatus('Завершение партии: манифест и ZIP…');
    try {
        const result = await apiPostJson('/api/batch/finish', {}, true);
        if (!result || result.ok !== true || !result.batch) {
            setBatchActiveStatus('Не удалось завершить партию', 'error');
            return null;
        }
        batchLabelTouched = false;
        applyBatchPayload(result.batch);
        setBatchStatus('Партия завершена и отправлена в архив');
        return result.batch;
    } finally {
        batchBusy = false;
        updateBatchPanelControls();
        updateServiceDeck();
    }
}

// ─── Инициализация ───────────────────────────────────────────

function setupBatchControls() {
    if (els.batchStart) {
        els.batchStart.addEventListener('click', () => { startBatch(); });
    }
    if (els.batchFinish) {
        els.batchFinish.addEventListener('click', () => { finishBatch(); });
    }
    if (els.batchLabelInput) {
        els.batchLabelInput.addEventListener('input', () => {
            batchLabelTouched = true;
            updateBatchPanelControls();
        });
        els.batchLabelInput.addEventListener('keydown', event => {
            if (event.key === 'Enter') startBatch();
        });
    }
    [els.deckTabBatch, els.deckTabThresholds].forEach(tab => {
        if (!tab) return;
        tab.addEventListener('click', () => {
            if (tab.disabled) return;
            if (tab.dataset.deckFace === 'thresholds'
                && !thresholdsFaceAvailable()) {
                return;
            }
            setDeckFace(tab.dataset.deckFace);
        });
    });
    fetchBatch();
    updateServiceDeck();
}

if (typeof window !== 'undefined') {
    window.updateBatchStatus = updateBatchStatus;
    window.setupBatchControls = setupBatchControls;
    window.setDeckFace = setDeckFace;
}
