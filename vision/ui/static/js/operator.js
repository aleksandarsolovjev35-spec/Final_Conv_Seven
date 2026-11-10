// operator.js — система пользователей: ввод ФИО при входе и индикация в работе
'use strict';

let operatorModalMode = 'login'; // 'login' (обязательный вход) | 'switch' (смена)
let operatorBusy = false;
let operatorSavedUsers = [];

function isOperatorModalOpen() {
    return !!(
        els.operatorModal
        && !els.operatorModal.classList.contains('is-hidden')
    );
}

function isOperatorModalMandatory() {
    return isOperatorModalOpen() && !state.operatorName;
}

function operatorSwitchVisible() {
    return (
        !state.splashActive
        && !state.offline
        && ['IDLE', 'STOPPED'].includes(state.lineState)
        && !!state.operatorName
        && state.operatorEditable === true
    );
}

function setOperatorError(message) {
    if (!els.operatorError) return;
    const text = String(message || '').trim();
    setIfChanged(els.operatorError, text);
    els.operatorError.classList.toggle('is-hidden', !text);
}

function renderOperatorFooter() {
    const nameEl = els.operatorCurrentName;
    const chipEl = els.operatorChip;
    const changeBtn = els.operatorChangeBtn;
    const hasOperator = !!state.operatorName;

    if (nameEl) {
        setIfChanged(nameEl, hasOperator ? state.operatorName : 'НЕ ВЫБРАН');
        nameEl.classList.toggle('is-empty', !hasOperator);
        nameEl.title = hasOperator
            ? `Оператор партии: ${state.operatorName}`
            : 'Необходимо указать ФИО оператора';
    }
    if (chipEl) {
        chipEl.title = hasOperator
            ? `Оператор партии: ${state.operatorName}`
            : 'Необходимо указать ФИО оператора';
    }
    if (changeBtn) {
        const visible = operatorSwitchVisible();
        changeBtn.classList.toggle('is-hidden', !visible);
        changeBtn.disabled = !visible || operatorBusy;
    }
}

function renderSavedOperatorsList() {
    const section = els.operatorSavedSection;
    const list = els.operatorSavedList;
    if (!section || !list) return;

    if (!Array.isArray(operatorSavedUsers) || operatorSavedUsers.length === 0) {
        section.classList.add('is-hidden');
        list.innerHTML = '';
        return;
    }

    section.classList.remove('is-hidden');
    const currentInput = String(
        (els.operatorFioInput && els.operatorFioInput.value) || ''
    ).trim().toLowerCase();

    list.innerHTML = '';
    operatorSavedUsers.forEach((fio) => {
        const row = document.createElement('div');
        row.className = 'operator-saved-item';

        const pickBtn = document.createElement('button');
        pickBtn.type = 'button';
        pickBtn.className = 'btn operator-saved-pick';
        if (currentInput && fio.toLowerCase() === currentInput) {
            pickBtn.classList.add('is-selected');
        }
        pickBtn.title = `Выбрать: ${fio} (двойной клик — быстрый вход)`;
        const label = document.createElement('span');
        label.textContent = fio;
        pickBtn.appendChild(label);

        pickBtn.addEventListener('click', () => {
            if (operatorBusy) return;
            if (els.operatorFioInput) {
                els.operatorFioInput.value = fio;
            }
            setOperatorError('');
            renderSavedOperatorsList();
            if (els.operatorSubmitBtn) {
                els.operatorSubmitBtn.focus();
            }
        });

        pickBtn.addEventListener('dblclick', () => {
            if (operatorBusy) return;
            if (els.operatorFioInput) {
                els.operatorFioInput.value = fio;
            }
            submitOperatorLogin();
        });

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-icon operator-saved-remove';
        removeBtn.title = `Удалить «${fio}» из сохранённых`;
        removeBtn.setAttribute('aria-label', `Удалить ${fio}`);
        removeBtn.textContent = '\u00d7';
        removeBtn.disabled = operatorBusy;
        removeBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            removeSavedOperator(fio);
        });

        row.appendChild(pickBtn);
        row.appendChild(removeBtn);
        list.appendChild(row);
    });
}

function applyOperatorModalMode(mode) {
    operatorModalMode = mode;
    const mandatory = (mode === 'login' || !state.operatorName);
    if (els.operatorModalTitle) {
        setIfChanged(
            els.operatorModalTitle,
            mandatory ? 'ВХОД В СИСТЕМУ' : 'СМЕНА ОПЕРАТОРА',
        );
    }
    if (els.operatorModalSubtitle) {
        setIfChanged(
            els.operatorModalSubtitle,
            mandatory
                ? 'Введите своё ФИО или выберите пользователя для текущей партии'
                : 'Укажите ФИО оператора (доступно до начала текущей партии)',
        );
    }
    if (els.operatorModalClose) {
        els.operatorModalClose.classList.toggle('is-hidden', mandatory);
    }
    if (els.operatorCancelBtn) {
        els.operatorCancelBtn.classList.toggle('is-hidden', mandatory);
    }
    if (els.operatorExitBtn) {
        els.operatorExitBtn.classList.toggle('is-hidden', !mandatory);
    }
    if (els.operatorSubmitBtn) {
        setIfChanged(els.operatorSubmitBtn, mandatory ? 'ВОЙТИ' : 'СОХРАНИТЬ');
    }
}

function focusOperatorInputIfOpen() {
    if (!isOperatorModalOpen() || !els.operatorFioInput) return;
    requestAnimationFrame(() => {
        if (!isOperatorModalOpen() || !els.operatorFioInput) return;
        els.operatorFioInput.focus();
        if (operatorModalMode === 'switch' && els.operatorFioInput.value) {
            els.operatorFioInput.select();
        }
    });
}

async function fetchOperatorDetails() {
    const data = await apiGet('/api/operator');
    if (!data) return;
    if (Array.isArray(data.operators)) {
        operatorSavedUsers = data.operators;
    }
    if (typeof data.name === 'string') {
        state.operatorName = data.name;
    }
    if (typeof data.editable === 'boolean') {
        state.operatorEditable = data.editable;
    }
    renderSavedOperatorsList();
    renderOperatorFooter();
}

function openOperatorModal(mode = 'login') {
    if (!els.operatorModal) return;
    applyOperatorModalMode(mode);
    setOperatorError('');
    if (els.operatorFioInput) {
        els.operatorFioInput.value = mode === 'switch'
            ? (state.operatorName || '')
            : '';
    }
    renderSavedOperatorsList();
    els.operatorModal.classList.remove('is-hidden');
    fetchOperatorDetails();
    if (!state.splashActive) {
        focusOperatorInputIfOpen();
    }
}

function closeOperatorModal(force = false) {
    if (!els.operatorModal) return;
    if (!force && !state.operatorName) return;
    els.operatorModal.classList.add('is-hidden');
    setOperatorError('');
}

function ensureOperatorLoginBeforeWork() {
    if (!state.operatorName) {
        openOperatorModal('login');
    }
}

function updateOperatorStatus(data) {
    if (!data || typeof data !== 'object') {
        renderOperatorFooter();
        return;
    }
    const incomingName = typeof data.name === 'string' ? data.name : '';
    const editable = data.editable === true;
    const prevName = state.operatorName;
    state.operatorName = incomingName;
    state.operatorEditable = editable;

    renderOperatorFooter();

    if (prevName !== incomingName && typeof applyButtonsForState === 'function') {
        applyButtonsForState(
            state.lineState,
            state.serverExitRequested,
            state.backendControls,
        );
    }

    if (incomingName && isOperatorModalOpen() && operatorModalMode === 'login') {
        closeOperatorModal(true);
    } else if (!incomingName && state.uiRevealed && !isOperatorModalOpen()) {
        openOperatorModal('login');
    } else if (
        incomingName
        && !editable
        && isOperatorModalOpen()
        && operatorModalMode === 'switch'
    ) {
        closeOperatorModal(true);
    }
}

async function submitOperatorLogin(event) {
    if (event) event.preventDefault();
    if (operatorBusy) return;

    const raw = String(
        (els.operatorFioInput && els.operatorFioInput.value) || ''
    ).trim();
    if (!raw) {
        setOperatorError('Укажите ФИО оператора');
        if (els.operatorFioInput) els.operatorFioInput.focus();
        return;
    }

    operatorBusy = true;
    setOperatorError('');
    if (els.operatorSubmitBtn) els.operatorSubmitBtn.disabled = true;
    if (els.operatorFioInput) els.operatorFioInput.disabled = true;

    try {
        const res = await fetch('/api/operator', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: raw}),
        });
        const payload = await res.json().catch(() => null);
        if (!res.ok || !payload || payload.ok !== true) {
            const err = (payload && payload.error)
                || 'Не удалось выполнить вход оператора';
            setOperatorError(err);
            return;
        }
        const info = payload.operator || {};
        const previousName = state.operatorName;
        state.operatorName = info.name || raw;
        state.operatorEditable = info.editable === true;
        if (Array.isArray(info.operators)) {
            operatorSavedUsers = info.operators;
        }
        renderOperatorFooter();
        closeOperatorModal(true);
        if (previousName !== state.operatorName) {
            if (typeof updateBatchStatus === 'function') {
                updateBatchStatus({selected: false, batches: []});
            }
            if (typeof refreshBatches === 'function') refreshBatches();
        }
        if (typeof applyButtonsForState === 'function') {
            applyButtonsForState(
                state.lineState,
                state.serverExitRequested,
                state.backendControls,
            );
        }
        requestImmediateStatus();
    } catch (err) {
        setOperatorError(err.message || 'Нет связи с сервером');
    } finally {
        operatorBusy = false;
        if (els.operatorSubmitBtn) els.operatorSubmitBtn.disabled = false;
        if (els.operatorFioInput) {
            els.operatorFioInput.disabled = false;
            if (isOperatorModalOpen()) els.operatorFioInput.focus();
        }
        renderSavedOperatorsList();
        renderOperatorFooter();
    }
}

async function removeSavedOperator(fio) {
    if (operatorBusy || !fio) return;
    operatorBusy = true;
    renderSavedOperatorsList();
    try {
        const result = await apiPostJson(
            '/api/operator/remove', {name: fio}, false,
        );
        if (result && result.ok && result.operator) {
            operatorSavedUsers = result.operator.operators || [];
        }
    } finally {
        operatorBusy = false;
        renderSavedOperatorsList();
    }
}

function setupOperatorControls() {
    if (els.operatorForm) {
        els.operatorForm.addEventListener('submit', submitOperatorLogin);
    }
    if (els.operatorFioInput) {
        els.operatorFioInput.addEventListener('input', () => {
            setOperatorError('');
            renderSavedOperatorsList();
        });
    }
    if (els.operatorChangeBtn) {
        els.operatorChangeBtn.addEventListener('click', () => {
            if (!operatorSwitchVisible() || operatorBusy) return;
            openOperatorModal('switch');
        });
    }
    if (els.operatorModalClose) {
        els.operatorModalClose.addEventListener('click', () => {
            closeOperatorModal(false);
        });
    }
    if (els.operatorCancelBtn) {
        els.operatorCancelBtn.addEventListener('click', () => {
            closeOperatorModal(false);
        });
    }
    if (els.operatorModalBackdrop) {
        els.operatorModalBackdrop.addEventListener('click', () => {
            if (!isOperatorModalMandatory()) {
                closeOperatorModal(false);
            }
        });
    }
    if (els.operatorExitBtn) {
        els.operatorExitBtn.addEventListener('click', async () => {
            if (operatorBusy) return;
            els.operatorExitBtn.disabled = true;
            const result = await apiPost('/api/exit', false);
            if (!result) {
                els.operatorExitBtn.disabled = false;
                setOperatorError('Не удалось отправить команду выхода');
            }
        });
    }
    renderOperatorFooter();
}

if (typeof window !== 'undefined') {
    window.setupOperatorControls = setupOperatorControls;
    window.updateOperatorStatus = updateOperatorStatus;
    window.ensureOperatorLoginBeforeWork = ensureOperatorLoginBeforeWork;
    window.focusOperatorInputIfOpen = focusOperatorInputIfOpen;
    window.isOperatorModalOpen = isOperatorModalOpen;
    window.isOperatorModalMandatory = isOperatorModalMandatory;
    window.closeOperatorModal = closeOperatorModal;
}
