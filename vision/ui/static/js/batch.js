// batch.js — менеджер партий: номер партии и учёт корпусов.
//
// Сначала оператор входит в программу по ФИО и паролю (operator.js), и
// только после этого доступна вкладка «ПАРТИЯ» — она открыта по умолчанию.
// Карточка держит список партий: номер и путь сверху, незавершённые партии
// ниже. Партию открывает, продолжает и переключает сама кнопка ПУСК, а
// открытая партия при переключении остаётся открытой и ждёт оператора:
// завершают партию только явной кнопкой. ФИО оператора показано плашкой над
// вкладками и в карточке не повторяется. Второе лицо сервисной зоны — пороги
// (по нажатию вкладки).
'use strict';

const BATCH_FINISH_CONFIRM_MS = 5000;

let batchData = null;
let batchSignature = null;
let batchFetchBusy = false;
let batchBusy = false;
let batchFinishArmed = false;
let batchFinishTimer = null;
let batchLabelTouched = false;
// Путь правил сам оператор: до этого путь ведётся автоматически — от
// открытой или выбранной партии, иначе по умолчанию от корня хранения.
let batchPathDirty = false;
// Выбранная незавершённая партия: нажатие на строку списка подставляет её
// номер и путь, а ПУСК открывает, продолжает или переключает её.
let selectedBatchId = null;
// Партия, номер и путь которой сейчас показаны в полях карточки.
let batchFieldsBatchId = null;
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

function activeBatchId() {
    return batchActive() ? String(batchData.batch.batch_id || '') : '';
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

        // Строка списка — сам выбор: нажатие подставляет номер и путь
        // партии в поля карточки, а ПУСК продолжает её.
        const missing = item.available === false;
        const isOpen = item.batch_id === activeBatchId();
        const mark = document.createElement('span');
        mark.className = 'batch-open-mark';
        mark.textContent = missing
            ? 'НЕТ ПАПКИ'
            : (isOpen
                ? 'ОТКРЫТА'
                : (item.batch_id === selectedBatchId ? '●' : '○'));
        if (missing) {
            row.classList.add('is-missing');
            row.title = 'Папка партии не найдена: продолжить нечем';
        } else {
            row.classList.toggle('is-selected', item.batch_id === selectedBatchId);
            row.classList.toggle('is-open', isOpen);
            row.tabIndex = 0;
            row.setAttribute('role', 'button');
            row.title = isOpen
                ? 'Эта партия открыта: ПУСК просто продолжит её'
                : 'Нажмите, чтобы выбрать партию, затем ПУСК';
            row.addEventListener('click', () => selectBatch(item));
            row.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    selectBatch(item);
                }
            });
        }
        row.appendChild(text);
        row.appendChild(mark);
        container.appendChild(row);
    });
}

// Выбор незавершённой партии: номер и путь берутся из реестра партий, а
// ПУСК уходит с batch_id — так продолжается именно выбранная партия.
function selectBatch(item) {
    if (!item || item.available === false) return;
    selectedBatchId = item.batch_id;
    batchLabelTouched = true;
    batchPathDirty = false;
    if (els.batchLabelInput) {
        els.batchLabelInput.value = item.label || item.batch_id;
    }
    if (els.batchPathInput) {
        els.batchPathInput.value = item.folder || '';
    }
    setBatchStatus('');
    renderBatchOpenList(batchData && batchData.open);
    updateBatchPanelControls();
}

// Правка номера или пути означает новую партию: выбор снимается.
function clearBatchSelection() {
    if (!selectedBatchId) return;
    selectedBatchId = null;
    if (batchData) renderBatchOpenList(batchData.open);
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
        ['ПАПКА', batch.folder || 'по умолчанию'],
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

// Строки карточки: номер партии и путь партии. Цветная полоса слева ведёт
// оператора к следующему действию (оператор смены — плашкой над вкладками).
function updateBatchSteps() {
    const label = batchLabelValue();
    const path = String(els.batchPathInput && els.batchPathInput.value || '').trim();
    if (els.batchStepLabel) {
        els.batchStepLabel.dataset.state = label ? 'done' : 'active';
    }
    if (els.batchStepPath) {
        els.batchStepPath.dataset.state = label ? (path ? 'done' : 'active') : 'todo';
    }
}

function batchLabelValue() {
    return els.batchLabelInput
        ? String(els.batchLabelInput.value || '').trim() : '';
}

function batchPathValue() {
    return els.batchPathInput
        ? String(els.batchPathInput.value || '').trim() : '';
}

// Копия серверного safe_component: путь по умолчанию в поле совпадает с
// папкой, которую менеджер партий создал бы сам.
function batchSafeComponent(text) {
    return String(text || '').trim()
        .replace(/[^0-9A-Za-zА-Яа-яЁё._-]+/g, '_')
        .replace(/_{2,}/g, '_')
        .replace(/^[._]+/, '')
        .replace(/[._]+$/, '')
        .slice(0, 36);
}

function batchDefaultFolder(label) {
    const root = String((batchData && batchData.root_path) || '').replace(/[\\/]+$/, '');
    const date = String((batchData && batchData.date) || '');
    const name = batchSafeComponent(label) || 'partiya';
    if (!root || !date) return String((batchData && batchData.default_folder) || '');
    return `${root}/${date}/${name}`;
}

// Путь подставляется сам, пока оператор его не правил: у открытой партии
// это её папка, у выбранной — папка из реестра, иначе путь по умолчанию от
// корня хранения. Так номер и путь не расходятся: сменив номер, оператор
// получает папку нового номера, а не папку прежней партии.
function syncBatchPath() {
    if (batchPathDirty || !els.batchPathInput) return;
    const label = batchLabelValue();
    if (batchActive()) {
        const active = batchData.batch;
        if (label === String(active.label || active.batch_id || '')) {
            els.batchPathInput.value = active.folder
                || batchDefaultFolder(label);
            return;
        }
    }
    if (selectedBatchId) {
        const item = (batchData.open || []).find(
            row => row.batch_id === selectedBatchId,
        );
        if (item) {
            els.batchPathInput.value = item.folder || '';
            return;
        }
    }
    const folder = batchDefaultFolder(label);
    if (folder) els.batchPathInput.value = folder;
}

// Поля карточки показывают открытую партию: её номер и путь попадают туда,
// как только партия открылась или учёт переключился. Дальше оператор правит
// их сам — так выбирают другую партию, не закрывая текущую.
function syncBatchFieldsToActive() {
    const id = activeBatchId();
    if (id === batchFieldsBatchId) return;
    batchFieldsBatchId = id;
    if (!id) return;
    const active = batchData.batch || {};
    batchLabelTouched = true;
    batchPathDirty = false;
    selectedBatchId = null;
    if (els.batchLabelInput) {
        els.batchLabelInput.value = active.label || active.batch_id || '';
    }
    if (els.batchPathInput) {
        els.batchPathInput.value = active.folder
            || batchDefaultFolder(active.label || '');
    }
}

// Что именно сделает ПУСК с учётом: открытие, продолжение или переключение
// на другую партию. Пусто — ПУСК просто продолжает открытую партию.
function batchSwitchIntent() {
    if (!batchActive()) return null;
    const active = batchData.batch || {};
    const activeId = String(active.batch_id || '');
    const activeLabel = String(active.label || active.batch_id || '');
    const activeFolder = String(active.folder || '');
    const label = batchLabelValue();
    const path = batchPathValue();
    if (selectedBatchId && selectedBatchId !== activeId) {
        const item = (batchData.open || []).find(
            row => row.batch_id === selectedBatchId,
        );
        return {
            kind: 'batch',
            label: (item && (item.label || item.batch_id))
                || label || selectedBatchId,
            path: (item && item.folder) || path,
        };
    }
    if (!label || label === activeLabel) {
        if (label && path && path !== activeFolder) {
            return {kind: 'folder', label, path};
        }
        return null;
    }
    return {kind: 'label', label, path};
}

// Причина, по которой ПУСК сейчас не может открыть или переключить партию.
// Пусто — можно пускать (партия открыта или номер введён/выбран).
function batchStartBlockedReason() {
    if (!batchManagerAvailable()) return '';
    if (!operatorAssigned()) return 'Сначала войдите в программу';
    const intent = batchSwitchIntent();
    if (!batchActive() && !selectedBatchId && !batchLabelValue()) {
        return 'Укажите номер партии: ПУСК начнёт учёт';
    }
    if ((!batchActive() || intent) && !batchEditableNow()) {
        return 'Партия открывается на остановленной линии';
    }
    return '';
}

// Тело запроса ПУСКА: номер, путь и выбранная незавершённая партия. По нему
// backend открывает партию, продолжает её или переключает учёт.
function batchStartPayload() {
    if (!batchManagerAvailable()) return null;
    const payload = {label: batchLabelValue(), path: batchPathValue()};
    if (selectedBatchId) payload.batch_id = selectedBatchId;
    return payload;
}

// Подсказка под полями: что именно сделает ПУСК.
function updateBatchOpenHint() {
    if (!els.batchStatus) return;
    if (!batchManagerAvailable()) return;
    if (!operatorAssigned()) return;
    const intent = batchSwitchIntent();
    if (intent) {
        const tail = 'прежняя партия останется открытой';
        if (intent.kind === 'folder') {
            setBatchStatus(
                `ПУСК начнёт партию ${intent.label} в папке ${intent.path}`,
                'warn',
            );
        } else if (intent.kind === 'batch') {
            setBatchStatus(
                `Выбрана партия ${intent.label}: ПУСК переключит учёт на неё, `
                + tail,
                'warn',
            );
        } else {
            setBatchStatus(
                `ПУСК переключит учёт на партию ${intent.label}: ${tail}`,
                'warn',
            );
        }
        return;
    }
    if (batchActive()) {
        setBatchStatus('');
        return;
    }
    const label = batchLabelValue();
    const path = batchPathValue();
    if (selectedBatchId) {
        setBatchStatus(
            `Выбрана партия ${label || selectedBatchId}: ПУСК продолжит её`,
            'warn',
        );
        return;
    }
    if (!label) {
        setBatchStatus('Укажите номер партии: ПУСК начнёт учёт в новой партии');
        return;
    }
    setBatchStatus(
        path
            ? `ПУСК начнёт партию ${label} в папке ${path}`
            : `ПУСК начнёт партию ${label} в папке по умолчанию`,
    );
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
    // Список партий виден всегда: партию можно выбрать и переключить, не
    // закрывая текущую — её блок просто добавляется снизу.
    if (els.batchActiveFace) {
        els.batchActiveFace.classList.toggle('is-hidden', !active);
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
        els.batchOpenList.querySelectorAll('.batch-open-row').forEach(row => {
            const missing = row.classList.contains('is-missing');
            row.classList.toggle(
                'is-locked', missing || !editable || batchBusy,
            );
        });
    }
    if (els.batchLabelInput) els.batchLabelInput.disabled = !editable;
    if (els.batchPathInput) els.batchPathInput.disabled = !editable;
    updateBatchOpenHint();
    updateBatchHint();
}

function updateBatchHint() {
    if (!els.batchActiveHint) return;
    let hint = 'Учёт корпусов ведётся в этой партии';
    if (batchActive() && batchData.can_finish === true) {
        hint = 'Партия закрывается кнопкой «ЗАВЕРШИТЬ ПАРТИЮ» '
            + 'на остановленной линии; другую партию можно выбрать списком';
    } else if (batchActive() && batchData.can_finish !== true) {
        if (state.lineState !== 'IDLE' && state.lineState !== 'STOPPED') {
            hint = 'Завершение — после полной остановки линии';
        } else {
            hint = 'На линии остались корпуса: завершение после их выхода';
        }
    }
    setIfChanged(els.batchActiveHint, hint);
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
    syncBatchFieldsToActive();
    syncBatchPath();
    renderBatchOpenList(batchData.open);
    if (batchActive()) renderBatchInfo(batchData.batch);
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
        item.batch_id, item.status, item.available, item.folder,
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

// Ошибка запроса ПУСКА: backend объясняет, чего не хватает (номер партии,
// партия не открыта, линия занята) — текст показывается в карточке.
function showBatchRequestError(result) {
    const error = (result && result.error) || 'Не удалось открыть партию';
    setBatchStatus(error, 'error');
    if (els.batchLabelInput && /номер партии/i.test(error)) {
        els.batchLabelInput.focus();
    }
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
        batchPathDirty = false;
        batchFieldsBatchId = null;
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
    if (els.batchFinish) {
        els.batchFinish.addEventListener('click', () => { finishBatch(); });
    }
    if (els.batchLabelInput) {
        els.batchLabelInput.addEventListener('input', () => {
            batchLabelTouched = true;
            // Номер сменился — путь снова ведётся автоматически: у другой
            // партии своя папка, прежняя здесь была бы ошибкой.
            batchPathDirty = false;
            clearBatchSelection();
            syncBatchPath();
            updateBatchPanelControls();
        });
        els.batchLabelInput.addEventListener('keydown', event => {
            if (event.key === 'Enter') requestImmediateStatus();
        });
    }
    if (els.batchPathInput) {
        els.batchPathInput.addEventListener('input', () => {
            batchPathDirty = true;
            clearBatchSelection();
            updateBatchPanelControls();
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
    window.batchSwitchIntent = batchSwitchIntent;
}
