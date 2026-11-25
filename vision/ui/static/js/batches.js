'use strict';

let batchActionPending = false;

function batchOperatorStats(item = {}) {
    return Array.isArray(item.operator_stats) ? item.operator_stats : [];
}

function setBatchSlot(selected) {
    const panel = document.getElementById('thresholds-panel');
    if (!panel) return;
    panel.dataset.slotMode = selected ? 'thresholds' : 'batches';
    state.batchSelected = Boolean(selected);
}

function renderBatchList(items = [], activeId = null) {
    const list = document.getElementById('batch-list');
    if (!list) return;
    list.replaceChildren();
    if (!items.length) {
        const empty = document.createElement('div');
        empty.className = 'batch-card-meta';
        empty.textContent = 'Архив партий пока пуст';
        list.appendChild(empty);
        return;
    }
    items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'batch-card';

        // Шапка: название партии и крестик закрытия для открытой партии.
        const head = document.createElement('div');
        head.className = 'batch-card-head';
        const title = document.createElement('span');
        title.className = 'batch-card-id';
        title.textContent = item.batch_id;
        const isOpen = item.status === 'OPEN' && !item.zipped;
        head.append(title);
        if (isOpen) {
            card.classList.add('is-open-card');
            if (item.batch_id === activeId) {
                card.classList.add('is-active-card');
            } else {
                card.title = 'Нажмите, чтобы продолжить партию';
                card.addEventListener('click', () => {
                    if (!batchActionPending) {
                        batchRequest('/api/batches/resume', {batch_id: item.batch_id});
                    }
                });
            }
            const close = document.createElement('button');
            close.type = 'button';
            close.className = 'batch-card-close';
            close.textContent = '✕';
            close.title = 'Закрыть партию';
            close.setAttribute('aria-label', 'Закрыть партию');
            close.disabled = batchActionPending;
            close.addEventListener('click', (e) => {
                e.stopPropagation();
                if (window.confirm('Закрыть партию? После закрытия продолжить её будет нельзя.')) {
                    batchRequest('/api/batches/close', {batch_id: item.batch_id});
                }
            });
            head.append(close);
        }

        // Блок «СТАТИСТИКА»: плитки счётчиков.
        const statsSection = document.createElement('div');
        statsSection.className = 'batch-card-section';
        const statsHead = document.createElement('div');
        statsHead.className = 'batch-card-heading';
        statsHead.textContent = 'СТАТИСТИКА';
        const statsGrid = document.createElement('div');
        statsGrid.className = 'batch-card-stats';
        const counts = item.counts || {};
        [
            ['годных', counts.good, 'is-good'],
            ['брак', counts.bad, 'is-bad'],
            ['зачистка', counts.cleanup, 'is-cleanup'],
        ].forEach(([label, value, cls]) => {
            const tile = document.createElement('div');
            tile.className = `batch-card-stat ${cls}`;
            tile.title = label;
            const tileValue = document.createElement('span');
            tileValue.className = 'batch-card-stat-value';
            tileValue.textContent = value || 0;
            tile.append(tileValue);
            statsGrid.appendChild(tile);
        });
        statsSection.append(statsHead, statsGrid);
        card.append(head, statsSection);

        // Блок «УЧАСТНИКИ»: имя слева, личный итог справа.
        const opRows = batchOperatorStats(item);
        if (opRows.length) {
            const ops = document.createElement('div');
            ops.className = 'batch-card-section batch-card-ops';
            const opsHead = document.createElement('div');
            opsHead.className = 'batch-card-heading';
            opsHead.textContent = 'УЧАСТНИКИ';
            ops.appendChild(opsHead);
            opRows.forEach(entry => {
                const row = document.createElement('div');
                row.className = 'batch-card-op';
                const name = document.createElement('div');
                name.className = 'batch-card-op-name';
                const nameText = document.createElement('span');
                nameText.className = 'batch-card-op-name-text';
                nameText.textContent = entry.operator || '—';
                nameText.title = entry.operator || '';
                name.append(nameText);
                const count = document.createElement('div');
                count.className = 'batch-card-stat is-accent batch-card-op-stat';
                count.title = 'всего деталей';
                const countValue = document.createElement('span');
                countValue.className = 'batch-card-stat-value';
                countValue.textContent = entry.parts || 0;
                count.append(countValue);
                row.append(name, count);
                ops.appendChild(row);
            });
            card.appendChild(ops);
        }
        list.appendChild(card);
    });
}

function updateBatchStatus(batch) {
    if (!batch) return;
    const selected = batch.selected === true;
    setBatchSlot(selected);
    const cycleStats = document.getElementById('stats-summary');
    if (cycleStats) cycleStats.classList.toggle('is-hidden', !selected);
    const activeToolbar = document.getElementById('active-batch-toolbar');
    const create = document.getElementById('batch-create');
    const list = document.getElementById('batch-list');
    const activeName = batch.batch_id || '—';
    if (activeToolbar) activeToolbar.hidden = !selected;
    if (create) create.hidden = selected;
    if (list) list.hidden = selected;
    ['active-batch-name'].forEach(id => {
        const node = document.getElementById(id);
        if (node) node.textContent = activeName;
    });
    if (Array.isArray(batch.batches)) {
        renderBatchList(batch.batches, selected ? batch.batch_id : null);
    }
    const canManage = ['IDLE', 'STOPPED'].includes(state.lineState)
        && !batchActionPending && !state.offline;
    ['batch-open', 'active-batch-detach'].forEach(id => {
        const button = document.getElementById(id);
        if (button) button.disabled = !canManage;
    });
    if (typeof applyButtonsForState === 'function') {
        applyButtonsForState(state.lineState, state.serverExitRequested, state.backendControls);
    }
}

function setBatchLoading(loading) {
    const panel = document.getElementById('thresholds-panel');
    if (!panel) return;
    if (loading) {
        panel.dataset.batchLoading = 'true';
    } else {
        delete panel.dataset.batchLoading;
    }
}

async function batchRequest(path, payload) {
    if (batchActionPending || state.offline) return;
    batchActionPending = true;
    setBatchLoading(true);
    ['batch-open', 'active-batch-detach'].forEach(id => {
        const node = document.getElementById(id);
        if (node) node.disabled = true;
    });
    document.querySelectorAll('#batch-list .batch-card-close').forEach(btn => {
        btn.disabled = true;
    });
    try {
        const result = await apiPostJson(path, payload, true);
        const tasks = [apiGet('/api/batches')];
        if (typeof fetchStatus === 'function') {
            tasks.push(fetchStatus());
        }
        const [batchesPayload] = await Promise.all(tasks);
        batchActionPending = false;
        const finalBatch = batchesPayload || (result && result.batch) || null;
        if (finalBatch) updateBatchStatus(finalBatch);
    } finally {
        batchActionPending = false;
        setBatchLoading(false);
    }
}

async function refreshBatches() {
    setBatchLoading(true);
    try {
        const payload = await apiGet('/api/batches');
        if (payload) updateBatchStatus(payload);
    } finally {
        setBatchLoading(false);
    }
}

function setupBatchManagement() {
    const bind = (id, callback) => {
        const node = document.getElementById(id);
        if (node) node.addEventListener('click', callback);
    };
    bind('batch-open', () => {
        const input = document.getElementById('batch-id-input');
        batchRequest('/api/batches/open', {batch_id: input ? input.value.trim() : ''});
    });
    bind('active-batch-detach', () => batchRequest('/api/batches/detach'));
}

document.addEventListener('DOMContentLoaded', () => {
    setupBatchManagement();
    refreshBatches();
});
