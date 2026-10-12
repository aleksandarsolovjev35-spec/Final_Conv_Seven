// operator.js — оператор смены: вход в программу по ФИО и паролю.
//
// Логика работы: пока оператор не назначен, HMI перекрыт экраном входа, а
// вкладка «ПАРТИЯ» заблокирована — партии открываются только после входа.
// Назначенный оператор виден всегда строкой над вкладками сервисной зоны,
// оттуда же его можно сменить (на остановленной линии без открытой партии).
// Хранение учётных записей — на стороне backend (пока operators.json).
'use strict';

let operatorData = null;
let operatorSignature = null;
let operatorFetchBusy = false;
let operatorBusy = false;
let operatorStatusTimer = null;
let loginVisible = false;

const OPERATOR_STATUS_MS = 5000;

// ─── Состояние ───────────────────────────────────────────────

function operatorAvailable() {
    return !!(operatorData && operatorData.available === true);
}

function operatorAssigned() {
    return !!(operatorData && operatorData.assigned === true);
}

function operatorName() {
    return operatorAssigned() ? String(operatorData.operator || '') : '';
}

// Экран входа нужен, когда учёт ведётся, а оператор ещё не вошёл.
function operatorRequired() {
    return operatorAvailable() && !operatorAssigned();
}

function operatorCanChange() {
    return (
        operatorAssigned()
        && operatorData.editable === true
        && !operatorBusy
        && !state.controlPending
        && !state.startPending
    );
}

function loginRegisterMode() {
    return !!(operatorData && operatorData.can_register === true);
}

// ─── Строка оператора над вкладками ──────────────────────────

function setOperatorStatus(text, kind = '') {
    const element = els.operatorStatus;
    if (!element) return;
    setIfChanged(element, text || '');
    element.classList.toggle('is-hidden', !text);
    element.classList.toggle('is-error', kind === 'error');
    element.classList.toggle('is-warn', kind === 'warn');
}

function armOperatorStatusReset() {
    if (operatorStatusTimer) clearTimeout(operatorStatusTimer);
    if (!els.operatorStatus || els.operatorStatus.classList.contains('is-hidden')) {
        return;
    }
    if (els.operatorStatus.classList.contains('is-error')) return;
    operatorStatusTimer = setTimeout(() => setOperatorStatus(''), OPERATOR_STATUS_MS);
}

function updateOperatorLine() {
    if (!els.operatorLine) return;
    const name = operatorName();
    setIfChanged(els.operatorName, name || 'НЕ НАЗНАЧЕН');
    const since = name ? String(operatorData.since || '') : '';
    if (els.operatorSince) {
        setIfChanged(els.operatorSince, since ? `с ${since}` : '');
    }
    els.operatorLine.classList.toggle('is-empty', !name);
    els.operatorLine.title = name
        ? `Оператор смены: ${name}`
        : 'Оператор не назначен: войдите в программу';
    if (els.operatorChange) {
        els.operatorChange.disabled = !operatorCanChange();
        els.operatorChange.title = operatorCanChange()
            ? 'Сменить оператора смены'
            : 'Смена оператора — на остановленной линии и после завершения партии';
    }
    if (!name) setOperatorStatus('');
}

// ─── Экран входа ─────────────────────────────────────────────

function renderLoginOperators(users, lastLogin) {
    const list = els.loginUsers;
    if (!list) return;
    list.innerHTML = '';
    (users || []).forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        list.appendChild(option);
    });
    if (!els.loginName || loginNameTouched()) return;
    const hint = String(lastLogin || users?.[0] || '');
    if (hint) els.loginName.value = hint;
}

function loginNameTouched() {
    return !!(els.loginName && String(els.loginName.value || '').trim());
}

function setLoginError(text) {
    const element = els.loginError;
    if (!element) return;
    setIfChanged(element, text || '');
    element.classList.toggle('is-hidden', !text);
}

function focusLoginField() {
    if (els.loginName && els.loginName.disabled) return;
    if (els.loginName && !String(els.loginName.value || '').trim()) {
        els.loginName.focus();
        return;
    }
    if (els.loginPassword) els.loginPassword.focus();
}

function updateLoginScreen() {
    if (!els.loginScreen) return;
    const required = operatorRequired() && !state.splashActive;
    els.loginScreen.classList.toggle('is-hidden', !required);
    if (required && !loginVisible) setTimeout(focusLoginField, 0);
    loginVisible = required;
    if (!required) return;
    const register = loginRegisterMode();
    const broken = operatorAvailable() && operatorData.can_add_user === false;
    setIfChanged(
        els.loginSubtitle,
        register
            ? 'Первый запуск: создайте оператора смены'
            : 'Оператор смены: выберите своё ФИО и введите пароль',
    );
    setIfChanged(
        els.loginHint,
        broken
            ? 'Файл операторов недоступен: проверьте папку архива'
            : (register
                ? 'ФИО — минимум 3 символа, пароль — минимум 4'
                : 'Пароль задаётся при создании учётной записи'),
    );
    if (els.loginSubmit) {
        els.loginSubmit.disabled = operatorBusy || broken;
        setIfChanged(els.loginSubmit, register ? 'СОЗДАТЬ И ВОЙТИ' : 'ВОЙТИ');
    }
    if (els.loginPasswordField) {
        els.loginPasswordField.classList.toggle('is-hidden', !register);
    }
    if (els.loginName) {
        els.loginName.disabled = operatorBusy;
        els.loginName.placeholder = register
            ? 'Иванов Иван Иванович'
            : 'Начните вводить ФИО';
    }
    if (els.loginPassword) els.loginPassword.disabled = operatorBusy;
    if (els.loginPassword2) els.loginPassword2.disabled = operatorBusy;
    renderLoginOperators(operatorData.users, operatorData.last_login);
    setOperatorErrorFromStore();
}

function setOperatorErrorFromStore() {
    if (!operatorData || !operatorData.error) return;
    setLoginError(`Файл операторов: ${operatorData.error}`);
}

function loginFilled() {
    const name = String((els.loginName && els.loginName.value) || '').trim();
    const password = String((els.loginPassword && els.loginPassword.value) || '');
    if (name.length < 3) return 'Укажите ФИО оператора';
    if (password.length < 4) return 'Пароль: минимум 4 символа';
    if (loginRegisterMode()) {
        const repeat = String((els.loginPassword2 && els.loginPassword2.value) || '');
        if (repeat !== password) return 'Пароли не совпадают';
    }
    return '';
}

async function submitOperatorAction(path, payload) {
    try {
        const response = await fetch(path, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload || {}),
        });
        const type = response.headers.get('content-type') || '';
        const body = type.includes('json') ? await response.json() : null;
        if (!response.ok) {
            return {
                ok: false,
                error: (body && body.error) || `Ошибка запроса (${response.status})`,
            };
        }
        return {ok: true, body};
    } catch (err) {
        console.warn(`[OPERATOR] ${path}:`, err.message);
        return {ok: false, error: 'Нет связи с backend'};
    }
}

async function submitLogin() {
    if (operatorBusy || !operatorRequired()) return null;
    const problem = loginFilled();
    if (problem) {
        setLoginError(problem);
        return null;
    }
    const register = loginRegisterMode();
    const payload = {
        login: String(els.loginName.value || '').trim(),
        password: String(els.loginPassword.value || ''),
    };
    operatorBusy = true;
    setLoginError('');
    updateLoginScreen();
    try {
        const result = await submitOperatorAction(
            register ? '/api/operator/register' : '/api/operator/login',
            payload,
        );
        if (!result.ok) {
            setLoginError(result.error);
            if (els.loginPassword) {
                els.loginPassword.value = '';
                els.loginPassword.focus();
            }
            return null;
        }
        const state_ = result.body && result.body.operator;
        if (els.loginPassword) els.loginPassword.value = '';
        if (els.loginPassword2) els.loginPassword2.value = '';
        setLoginError('');
        setOperatorStatus(
            register ? 'Учётная запись создана' : 'Оператор смены назначен',
        );
        applyOperatorPayload(state_ || null);
        if (typeof fetchBatch === 'function') fetchBatch();
        return state_;
    } finally {
        operatorBusy = false;
        updateLoginScreen();
    }
}

// ─── Смена оператора ─────────────────────────────────────────

async function changeOperator() {
    if (!operatorCanChange()) {
        setOperatorStatus(
            'Смена оператора — на остановленной линии и после завершения партии',
            'warn',
        );
        armOperatorStatusReset();
        return null;
    }
    operatorBusy = true;
    updateOperatorLine();
    setOperatorStatus('Смена оператора…');
    try {
        const result = await submitOperatorAction('/api/operator/logout', {});
        if (!result.ok) {
            setOperatorStatus(result.error, 'error');
            return null;
        }
        applyOperatorPayload(result.body && result.body.operator);
        if (els.loginName) els.loginName.value = '';
        if (els.loginPassword) els.loginPassword.value = '';
        if (els.loginPassword2) els.loginPassword2.value = '';
        setLoginError('');
        if (els.loginName) els.loginName.focus();
        return true;
    } finally {
        operatorBusy = false;
        updateOperatorLine();
        updateLoginScreen();
    }
}

// ─── Разбор состояния ────────────────────────────────────────

function operatorDataSignature(data) {
    if (!data || data.available !== true) {
        return `unavailable:${!!data}`;
    }
    return [
        data.assigned,
        data.operator,
        data.editable,
        data.can_register,
        data.last_login,
        (data.users || []).join('|'),
        data.error,
    ].join('~');
}

function applyOperatorPayload(data) {
    operatorData = data || null;
    const signature = operatorDataSignature(operatorData);
    const changed = signature !== operatorSignature;
    operatorSignature = signature;
    updateOperatorLine();
    updateLoginScreen();
    if (typeof updateBatchPanelControls === 'function') {
        updateBatchPanelControls();
    }
    if (typeof updateServiceDeck === 'function') updateServiceDeck();
    return changed;
}

// Вызывается из status.js на каждом опросе /api/status.
function updateOperatorStatus(data) {
    if (!data) return;
    applyOperatorPayload(data);
}

async function fetchOperator() {
    if (operatorFetchBusy) return;
    operatorFetchBusy = true;
    const data = await apiGet('/api/operator');
    operatorFetchBusy = false;
    if (data) applyOperatorPayload(data);
}

// ─── Инициализация ───────────────────────────────────────────

function setupOperatorControls() {
    if (els.loginSubmit) {
        els.loginSubmit.addEventListener('click', () => { submitLogin(); });
    }
    [els.loginName, els.loginPassword, els.loginPassword2].forEach(field => {
        if (!field) return;
        field.addEventListener('keydown', event => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            // Enter в пустом пароле переводит фокус дальше, а не ругается.
            if (field === els.loginName
                && !String(els.loginPassword?.value || '')) {
                if (els.loginPassword) els.loginPassword.focus();
                return;
            }
            submitLogin();
        });
    });
    [els.loginName, els.loginPassword, els.loginPassword2].forEach(field => {
        if (!field) return;
        field.addEventListener('input', () => setLoginError(''));
    });
    if (els.operatorChange) {
        els.operatorChange.addEventListener('click', () => { changeOperator(); });
    }
    fetchOperator();
    updateOperatorLine();
    updateLoginScreen();
}

if (typeof window !== 'undefined') {
    window.updateOperatorStatus = updateOperatorStatus;
    window.setupOperatorControls = setupOperatorControls;
    window.operatorAssigned = operatorAssigned;
    window.operatorRequired = operatorRequired;
    window.operatorName = operatorName;
}
