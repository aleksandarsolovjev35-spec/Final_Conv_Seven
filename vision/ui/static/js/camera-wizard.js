// camera-wizard.js — назначение физических камер ролям линии
//
// Мастер живёт внутри HMI: перед сканированием приложение освобождает
// камеры (POST /api/cameras/wizard {active:true}), показывает найденные
// устройства с живым превью и даёт разложить их по ролям. Сохранение
// проверяет mapping, пишет camera_mapping.json (.bak рядом) и заново
// открывает камеры по новому распределению.
'use strict';

const cameraWizardState = {
    open: false,
    busy: false,
    applied: false,
    devices: [],
    roles: [],
    mapping: {},
    selected: null,
    previewTimer: null,
    previewSeq: 0,
};

function cameraWizardNode(id) {
    return document.getElementById(id);
}

function cameraWizardLineStopped() {
    return ['IDLE', 'STOPPED'].includes(state.lineState);
}

function cameraWizardRoleLabel(role) {
    return typeof cameraRoleLabel === 'function' ? cameraRoleLabel(role) : role;
}

async function cameraWizardPost(url, body) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body || {}),
    });
    if (!response.ok) {
        let detail = '';
        try {
            const payload = await response.json();
            detail = typeof payload.detail === 'string' ? payload.detail : '';
        } catch (_) { /* тело не JSON */ }
        throw new Error(detail || `HTTP ${response.status}`);
    }
    return response.json();
}

function cameraWizardStatus(text, kind) {
    const node = cameraWizardNode('camera-wizard-state');
    if (!node) return;
    node.textContent = text;
    node.dataset.kind = kind || '';
}

// ─── Отрисовка ───────────────────────────────────────────────

function cameraWizardDeviceRole(index) {
    const role = Object.keys(cameraWizardState.mapping)
        .find(key => cameraWizardState.mapping[key] === index);
    return role || null;
}

function renderCameraWizardDevices() {
    const box = cameraWizardNode('camera-wizard-devices');
    if (!box) return;
    if (!cameraWizardState.devices.length) {
        box.innerHTML = '<div class="wizard-empty">КАМЕРЫ НЕ НАЙДЕНЫ</div>';
        return;
    }
    box.innerHTML = cameraWizardState.devices.map(device => {
        const role = cameraWizardDeviceRole(device.index);
        const selected = cameraWizardState.selected === device.index;
        const stateText = device.ok
            ? `${device.width}×${device.height}`
            : (device.error || 'НЕДОСТУПНА');
        return `
            <button type="button" class="wizard-device${selected ? ' is-selected' : ''}${device.ok ? '' : ' is-failed'}"
                    data-device="${device.index}">
                ${device.ok
                    ? `<img class="wizard-device-frame" data-device="${device.index}" alt="">`
                    : '<span class="wizard-device-frame is-empty">НЕТ КАДРА</span>'}
                <span class="wizard-device-line">
                    <span class="wizard-device-id">КАМЕРА ${device.index}</span>
                    <span class="wizard-device-state">${stateText}</span>
                </span>
                <span class="wizard-device-role">${role ? cameraWizardRoleLabel(role) : 'НЕ НАЗНАЧЕНА'}</span>
            </button>
        `;
    }).join('');
    box.querySelectorAll('.wizard-device').forEach(node => {
        node.addEventListener('click', () => {
            cameraWizardState.selected = Number(node.dataset.device);
            renderCameraWizard();
        });
    });
}

function renderCameraWizardRoles() {
    const box = cameraWizardNode('camera-wizard-roles');
    if (!box) return;
    const selected = cameraWizardState.selected;
    const canAssign = Number.isInteger(selected);
    box.innerHTML = cameraWizardState.roles.map(role => {
        const device = cameraWizardState.mapping[role];
        const assigned = Number.isInteger(device);
        const busy = assigned && device === selected;
        return `
            <button type="button" class="wizard-role${assigned ? ' is-assigned' : ''}${busy ? ' is-current' : ''}"
                    data-role="${role}" ${canAssign ? '' : 'data-empty="1"'}>
                <span class="wizard-role-name">${cameraWizardRoleLabel(role)}</span>
                <span class="wizard-role-value">${assigned ? `ID ${device}` : '—'}</span>
            </button>
        `;
    }).join('');
    box.querySelectorAll('.wizard-role').forEach(node => {
        node.addEventListener('click', () => assignCameraWizardRole(node.dataset.role));
        node.addEventListener('contextmenu', (event) => {
            event.preventDefault();
            clearCameraWizardRole(node.dataset.role);
        });
    });
}

function renderCameraWizard() {
    renderCameraWizardDevices();
    renderCameraWizardRoles();
    const save = cameraWizardNode('camera-wizard-save');
    if (save) {
        const complete = cameraWizardState.roles.length > 0
            && cameraWizardState.roles.every(
                role => Number.isInteger(cameraWizardState.mapping[role]),
            );
        save.disabled = !complete || cameraWizardState.busy;
    }
}

function assignCameraWizardRole(role) {
    const device = cameraWizardState.selected;
    if (!Number.isInteger(device)) {
        cameraWizardStatus('ВЫБЕРИТЕ КАМЕРУ СЛЕВА', 'warn');
        return;
    }
    // Одно устройство — одна роль: прежний владелец обменивается местом.
    Object.keys(cameraWizardState.mapping).forEach(key => {
        if (key !== role && cameraWizardState.mapping[key] === device) {
            const previous = cameraWizardState.mapping[role];
            if (Number.isInteger(previous)) {
                cameraWizardState.mapping[key] = previous;
            } else {
                delete cameraWizardState.mapping[key];
            }
        }
    });
    cameraWizardState.mapping[role] = device;
    cameraWizardStatus(`НАЗНАЧЕНО: ${cameraWizardRoleLabel(role)} → ID ${device}`, 'ok');
    renderCameraWizard();
}

function clearCameraWizardRole(role) {
    if (!Number.isInteger(cameraWizardState.mapping[role])) return;
    delete cameraWizardState.mapping[role];
    renderCameraWizard();
}

// ─── Скан и живое превью ────────────────────────────────────

async function refreshCameraWizard() {
    cameraWizardStatus('СКАНИРОВАНИЕ КАМЕР…');
    const response = await fetch('/api/cameras/devices?limit=8');
    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
    }
    const payload = await response.json();
    cameraWizardState.devices = Array.isArray(payload.devices) ? payload.devices : [];
    cameraWizardState.roles = Array.isArray(payload.roles) ? payload.roles : [];
    if (!Object.keys(cameraWizardState.mapping).length) {
        cameraWizardState.mapping = Object.assign({}, payload.mapping || {});
    }
    const found = cameraWizardState.devices.filter(device => device.ok).length;
    cameraWizardStatus(`НАЙДЕНО КАМЕР: ${found}`, found ? 'ok' : 'warn');
    renderCameraWizard();
}

function stopCameraWizardPreview() {
    if (cameraWizardState.previewTimer) {
        clearInterval(cameraWizardState.previewTimer);
        cameraWizardState.previewTimer = null;
    }
}

function refreshCameraWizardFrames() {
    if (!cameraWizardState.open) return;
    const seq = ++cameraWizardState.previewSeq;
    const images = [...document.querySelectorAll('.wizard-device-frame[data-device]')];
    images.forEach((img, order) => {
        setTimeout(() => {
            if (!cameraWizardState.open || seq !== cameraWizardState.previewSeq) return;
            img.src = `/api/cameras/devices/${img.dataset.device}/frame?t=${Date.now()}`;
        }, order * 120);
    });
}

function startCameraWizardPreview() {
    stopCameraWizardPreview();
    refreshCameraWizardFrames();
    cameraWizardState.previewTimer = setInterval(refreshCameraWizardFrames, 1600);
}

// ─── Открытие, закрытие, сохранение ─────────────────────────

async function openCameraWizard() {
    const modal = cameraWizardNode('camera-wizard');
    if (!modal || cameraWizardState.open || cameraWizardState.busy) return;
    cameraWizardState.busy = true;
    cameraWizardState.applied = false;
    modal.classList.remove('is-hidden');
    cameraWizardState.open = true;

    if (!cameraWizardLineStopped()) {
        cameraWizardStatus('ОСТАНОВИТЕ ЛИНИЮ', 'warn');
        renderCameraWizard();
        cameraWizardState.busy = false;
        return;
    }

    try {
        await cameraWizardPost('/api/cameras/wizard', {active: true});
        await refreshCameraWizard();
        startCameraWizardPreview();
    } catch (err) {
        cameraWizardStatus(String(err.message || err), 'error');
    } finally {
        cameraWizardState.busy = false;
        renderCameraWizard();
    }
}

async function closeCameraWizard() {
    const modal = cameraWizardNode('camera-wizard');
    if (!modal) return;
    stopCameraWizardPreview();
    modal.classList.add('is-hidden');
    const wasOpen = cameraWizardState.open;
    cameraWizardState.open = false;
    cameraWizardState.selected = null;
    if (wasOpen && !cameraWizardState.applied && cameraWizardLineStopped()) {
        try {
            await cameraWizardPost('/api/cameras/wizard', {active: false});
        } catch (_) { /* камеры уже открыты или линия поехала */ }
    }
    cameraWizardState.applied = false;
    if (typeof fetchCameras === 'function') fetchCameras();
}

async function rescanCameraWizard() {
    if (cameraWizardState.busy) return;
    cameraWizardState.busy = true;
    renderCameraWizard();
    try {
        await refreshCameraWizard();
        startCameraWizardPreview();
    } catch (err) {
        cameraWizardStatus(String(err.message || err), 'error');
    } finally {
        cameraWizardState.busy = false;
        renderCameraWizard();
    }
}

async function saveCameraWizard() {
    const mapping = {};
    cameraWizardState.roles.forEach(role => {
        const device = cameraWizardState.mapping[role];
        if (Number.isInteger(device)) mapping[role] = device;
    });
    if (Object.keys(mapping).length !== cameraWizardState.roles.length) return;
    if (cameraWizardState.busy) return;
    cameraWizardState.busy = true;
    cameraWizardStatus('СОХРАНЕНИЕ…');
    try {
        const result = await cameraWizardPost('/api/cameras/mapping', {mapping});
        cameraWizardState.applied = true;
        cameraWizardStatus(
            result.applied ? 'СОХРАНЕНО И ПРИМЕНЕНО' : 'СОХРАНЕНО',
            'ok',
        );
        stopCameraWizardPreview();
        setTimeout(() => { closeCameraWizard(); }, 900);
    } catch (err) {
        cameraWizardStatus(String(err.message || err), 'error');
    } finally {
        cameraWizardState.busy = false;
        renderCameraWizard();
    }
}

function setupCameraWizard() {
    const modal = cameraWizardNode('camera-wizard');
    if (!modal) return;
    const setup = cameraWizardNode('camera-setup');
    if (setup) setup.addEventListener('click', openCameraWizard);
    const close = cameraWizardNode('camera-wizard-close');
    if (close) close.addEventListener('click', closeCameraWizard);
    const rescan = cameraWizardNode('camera-wizard-scan');
    if (rescan) rescan.addEventListener('click', rescanCameraWizard);
    const save = cameraWizardNode('camera-wizard-save');
    if (save) save.addEventListener('click', saveCameraWizard);
    modal.addEventListener('click', (event) => {
        if (event.target === modal) closeCameraWizard();
    });
    window.addEventListener('beforeunload', stopCameraWizardPreview);
}
