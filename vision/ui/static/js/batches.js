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
        const main = document.createElement('div');
        main.className = 'batch-card-main';
        const titleRow = document.createElement('div');
        titleRow.className = 'batch-card-title';
        const title = document.createElement('span');
        title.className = 'batch-card-id';
        title.textContent = item.batch_id;
        titleRow.append(title);
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
            const tileLabel = document.createElement('span');
            tileLabel.className = 'batch-card-stat-label';
            tileLabel.textContent = label;
            const tileValue = document.createElement('span');
            tileValue.className = 'batch-card-stat-value';
            tileValue.textContent = value || 0;
            tile.append(tileLabel, tileValue);
            statsGrid.appendChild(tile);
        });
        statsSection.append(statsHead, statsGrid);
        main.append(titleRow, statsSection);
        const opRows = batchOperatorStats(item);
        if (opRows.length) {
            const ops = document.createElement('div');
            ops.className = 'batch-card-section';
            const opsHead = document.createElement('div');
            opsHead.className = 'batch-card-heading';
            opsHead.textContent = 'УЧАСТНИКИ';
            ops.appendChild(opsHead);
            opRows.forEach(entry => {
                const row = document.createElement('div');
                row.className = 'batch-card-op';
                const name = document.createElement('div');
                name.className = 'batch-card-op-name';
                const dot = document.createElement('span');
                dot.className = 'batch-card-op-dot';
                const nameText = document.createElement('span');
                nameText.className = 'batch-card-op-name-text';
                nameText.textContent = entry.operator || '—';
                nameText.title = entry.operator || '';
                name.append(dot, nameText);
                const count = document.createElement('div');
                count.className = 'batch-card-op-count';
                const countLabel = document.createElement('span');
                countLabel.textContent = 'всего деталей: ';
                const countValue = document.createElement('span');
                countValue.className = 'batch-card-op-count-value';
                countValue.textContent = entry.parts || 0;
                count.append(countLabel, countValue);
                row.append(name, count);
                ops.appendChild(row);
            });
            main.append(ops);
        }
        const actions = document.createElement('div');
        actions.className = 'batch-card-actions';
        if (item.status === 'OPEN' && !item.zipped) {
            const resume = document.createElement('button');
            resume.type = 'button';
            resume.className = 'btn btn-sm btn-ok';
            resume.textContent = item.batch_id === activeId ? 'ВЫБРАНА' : 'ПРОДОЛЖИТЬ';
            resume.disabled = batchActionPending || item.batch_id === activeId;
            resume.addEventListener('click', () => batchRequest(
                '/api/batches/resume', {batch_id: item.batch_id},
            ));
            actions.appendChild(resume);
        } else {
            const closed = document.createElement('span');
            closed.className = 'batch-card-meta';
            closed.textContent = 'ЗАКРЫТА';
            actions.appendChild(closed);
        }
        card.append(main, actions);
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
    ['batch-open', 'active-batch-detach', 'active-batch-close'].forEach(id => {
        const button = document.getElementById(id);
        if (button) button.disabled = !canManage;
    });
    if (typeof applyButtonsForState === 'function') {
        applyButtonsForState(state.lineState, state.serverExitRequested, state.backendControls);
    }
}

async function batchRequest(path, payload) {
    if (batchActionPending || state.offline) return;
    batchActionPending = true;
    ['batch-open', 'active-batch-detach', 'active-batch-close', 'batch-list'].forEach(id => {
        const node = document.getElementById(id);
        if (node) node.disabled = true;
    });
    const result = await apiPostJson(path, payload, true);
    batchActionPending = false;
    if (result && result.batch) updateBatchStatus(result.batch);
    await refreshBatches();
}

async function refreshBatches() {
    const payload = await apiGet('/api/batches');
    if (payload) updateBatchStatus(payload);
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
    bind('active-batch-close', () => {
        if (window.confirm('Закрыть партию? После закрытия продолжить её будет нельзя.')) batchRequest('/api/batches/close');
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setupBatchManagement();
    refreshBatches();
});
