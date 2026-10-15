// live_contracts.js — живые проверки против запущенного стенда: разметка,
// статика и контракты API, на которые опирается карточка «ПАРТИЯ».
// Стенд не меняется: проверки только читают.
// Запуск: node live_contracts.js (стенд — ui_simulation.py на HMI_URL).
'use strict';

const BASE = process.env.HMI_URL || 'http://localhost:8000';

async function fetchJson(path) {
    const response = await fetch(BASE + path);
    return {status: response.status, body: await response.json()};
}

async function fetchText(path) {
    const response = await fetch(BASE + path);
    return {status: response.status, body: await response.text()};
}

async function main() {
    let fails = 0;
    let total = 0;
    const check = (name, ok, extra) => {
        total += 1;
        if (ok) {
            console.log(`OK   ${name}${extra ? ' :: ' + extra : ''}`);
        } else {
            fails += 1;
            console.log(`FAIL ${name}${extra ? ' :: ' + extra : ''}`);
        }
    };

    // ─── Разметка и версии статики ─────────────────────────────
    const page = await fetchText('/');
    check('HMI отдаёт страницу', page.status === 200, `HTTP ${page.status}`);
    const assets = Array.from(
        page.body.matchAll(/(?:src|href)="(\/static\/[^"]+)"/g),
        match => match[1],
    );
    check('на странице есть версионированная статика',
        assets.length > 0 && assets.every(item => item.includes('?v=')),
        `ссылок: ${assets.length}`);
    const badAssets = [];
    for (const asset of assets) {
        const response = await fetch(BASE + asset);
        if (response.status !== 200) badAssets.push(`${asset} → ${response.status}`);
    }
    check('вся статика со страницы отдаётся', badAssets.length === 0,
        badAssets.join(', ') || 'все 200');

    // ─── Карточка партии: контракт /api/batch ──────────────────
    const batch = await fetchJson('/api/batch');
    const payload = batch.body || {};
    for (const key of [
        'available', 'active', 'batch', 'open', 'suggestion',
        'root_path', 'date', 'default_folder', 'editable', 'can_finish',
    ]) {
        check(`/api/batch отдаёт «${key}»`, key in payload);
    }
    const openRows = payload.open || [];
    check('в списке незавершённых только открытые партии',
        openRows.every(item => item.status === 'OPEN'),
        openRows.map(item => `${item.label}:${item.status}`).join(', ') || 'список пуст');
    check('у каждой строки списка есть номер, путь и счётчики',
        openRows.every(
            item => item.batch_id && item.label && item.folder
                && item.counts && typeof item.counts.total === 'number',
        ));
    check('шаблон номера и путь ведут в корень хранения',
        typeof payload.suggestion === 'string'
        && payload.suggestion.length > 0
        && String(payload.default_folder).startsWith(String(payload.root_path)),
        `${payload.suggestion} → ${payload.default_folder}`);
    check('путь по шаблону содержит дату и номер',
        String(payload.default_folder).includes(payload.date)
        && String(payload.default_folder).endsWith(payload.suggestion),
        payload.default_folder);
    if (payload.active && payload.batch) {
        check('у открытой партии есть номер, путь и счётчики',
            !!payload.batch.label && !!payload.batch.folder
            && typeof payload.batch.counts.total === 'number',
            `${payload.batch.label} · корпусов ${payload.batch.counts.total}`);
        check('открытая партия помечена в списке незавершённых',
            openRows.some(item => item.batch_id === payload.batch.batch_id));
    }

    // ─── Статус линии и оператор ───────────────────────────────
    const status = await fetchJson('/api/status');
    const line = (status.body || {}).line_status || {};
    check('/api/status отдаёт состояния линии',
        typeof line.state === 'string' && !!line.controls,
        `${line.state}, пуск: ${line.controls && line.controls.start}`);
    check('пуск связан с учётом партии',
        typeof line.batch_open === 'boolean'
        || typeof (line.controls || {}).start === 'boolean');

    const operator = await fetchJson('/api/operator');
    check('/api/operator отдаёт список и текущего оператора',
        'available' in operator.body && 'assigned' in operator.body
        && Array.isArray(operator.body.users),
        `${(operator.body.users || []).length} учёток`);

    // ─── Тексты, которых в интерфейсе быть не должно ───────────
    for (const fragment of [
        'batch-exit-modal', 'archive.js', 'archive.css',
        'НАЧАТЬ ПАРТИЮ', 'СТАТИСТИКА РАБОЧЕГО ЦИКЛА', 'ЗАМЕРЫ ОБЪЕКТОВ',
        'DIST1', 'DIST2',
    ]) {
        check(`на живом стенде нет «${fragment}»`,
            !page.body.includes(fragment));
    }

    // ─── Отданный JS: подписи и поведение карточки ─────────────
    const statusJs = await fetchText('/static/js/status.js');
    check('HMI знает фазу «ВХОД + КОНТРОЛЬ · АНАЛИЗ ПАРАЛЛЕЛЬНО»',
        statusJs.body.includes('PARALLEL_ANALYSIS')
        && statusJs.body.includes('ПАРАЛЛЕЛЬНО'));
    const batchJs = await fetchText('/static/js/batch.js');
    check('карточка партии собирает поля из цели ПУСКА',
        batchJs.body.includes('batchStartTarget')
        && batchJs.body.includes('Продолжить её — выбрать в списке'));

    console.log(`\nпроверок: ${total}, провалов: ${fails}`);
    process.exit(fails ? 1 : 0);
}

main().catch(error => {
    console.error('живой прогон упал:', error);
    process.exit(2);
});
