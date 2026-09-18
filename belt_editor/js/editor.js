/* belt_editor/js/editor.js — экран сборки ленты.
 *
 * Рендер: любое изменение модели перерисовывает ленту, инспектор,
 * панель проверок и JSON. Текстовые поля коммитятся на «input» и
 * «change» без перериски инспектора, чтобы не терять фокус.
 */
'use strict';

(function () {

const DRAFT_KEY = 'beltEditor.draft.v1';
const WALK_STEP_MS = 520;

const model = new BeltModel(null);
const ui = {
    selected: 0,
    walkTimer: null,
    walkDone: [],
    jsonDirty: false,
};

/* ─── DOM-хелперы ─────────────────────────────────────────────────── */

function $(id) { return document.getElementById(id); }

function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined) { node.textContent = text; }
    return node;
}

function btn(label, cls, handler, attrs) {
    const node = el('button', cls || 'btn', label);
    node.type = 'button';
    node.addEventListener('click', handler);
    (attrs || []).forEach(function (pair) {
        if (pair[1] === true) { node.setAttribute(pair[0], ''); }
        else { node.setAttribute(pair[0], pair[1]); }
    });
    return node;
}

function on(node, ev, fn) { node.addEventListener(ev, fn); }

function toast(text, kind) {
    const box = $('toasts');
    const node = el('div', 'toast' + (kind ? ' ' + kind : ''), text);
    box.appendChild(node);
    setTimeout(function () {
        node.style.opacity = '0';
        setTimeout(function () { node.remove(); }, 250);
    }, 2800);
}

function clockNow() {
    const d = new Date();
    return [d.getHours(), d.getMinutes(), d.getSeconds()]
        .map(function (n) { return String(n).padStart(2, '0'); }).join(':');
}

/* ─── Лента ───────────────────────────────────────────────────────── */

function renderStrip() {
    const strip = $('belt-strip');
    strip.textContent = '';
    const belt = model.belt;
    if (belt.positions.length === 0) {
        const empty = el('div', 'belt-empty');
        empty.appendChild(document.createTextNode(
            'Позиций нет. Добавьте первую: '));
        empty.appendChild(btn('＋ Позиция', 'btn btn-sm', function () {
            model.addPosition();
            ui.selected = 0;
            renderAll();
        }));
        strip.appendChild(empty);
        return;
    }
    belt.positions.forEach(function (pos, i) {
        strip.appendChild(renderCard(pos, i));
        if (i < belt.positions.length - 1) {
            strip.appendChild(el('div', 'pos-arrow', '→'));
        }
    });
    if (belt.path_type === 'loop') {
        const back = el('div', 'pos-arrow loop-back', '↻');
        back.title = 'Циклический путь: лента возвращается на вход';
        strip.appendChild(back);
    }
    if (ui.walkTimer === null) { syncWalkClasses(); }
}

function renderCard(pos, i) {
    const card = el('div', 'pos-card');
    if (ui.selected === i) { card.classList.add('selected'); }
    if (pos.inspection) { card.classList.add('inspect'); }
    if (pos.reset) { card.classList.add('reset-pt'); }
    card.dataset.index = String(i);

    card.appendChild(el('div', 'pos-index', 'ПОЗИЦИЯ ' + i));
    card.appendChild(el('div', 'pos-label', pos.label || ('П' + i)));

    const badges = el('div', 'pos-badges');
    if (pos.inspection) {
        const n = pos.inspection.cameras.length;
        badges.appendChild(el('span', 'badge badge-cam',
            n === 0 ? 'без камер' : '🎥 ' + n));
        if (pos.inspection.primary) {
            badges.appendChild(el('span', 'badge badge-primary', '★ основное'));
        }
    }
    if (pos.reset) { badges.appendChild(el('span', 'badge badge-reset', '⏏ сброс')); }
    card.appendChild(badges);

    const tools = el('div', 'pos-tools');
    tools.appendChild(btn('＋', 'mini-btn', function (ev) {
        ev.stopPropagation();
        ui.selected = model.insertPosition(i);
        renderAll();
    }, [['title', 'Вставить позицию после']]));
    tools.appendChild(btn('✕', 'mini-btn del', function (ev) {
        ev.stopPropagation();
        model.removePosition(i);
        if (ui.selected >= model.positionCount()) {
            ui.selected = model.positionCount() - 1;
        }
        renderAll();
    }, [['title', 'Удалить позицию']]));
    card.appendChild(tools);

    on(card, 'click', function () {
        ui.selected = i;
        renderAll();
    });
    return card;
}

function renderCaps() {
    const belt = model.belt;
    const inCap = $('cap-in');
    const outCap = $('cap-out');
    const loop = belt.path_type === 'loop';
    const resetIdx = model.resetIndex();
    inCap.textContent = loop ? '◀ РЕТУР' : 'ВХОД ▶';
    inCap.style.visibility = 'visible';
    if (loop) {
        outCap.textContent = resetIdx >= 0
            ? '⏏ сброс на П' + resetIdx + ' · дальше по кругу'
            : '↻ путь по кругу';
    } else {
        outCap.textContent = '▶ СБРОС';
    }
}

function renderPathCaption() {
    const box = $('path-caption');
    box.textContent = '';
    const steps = model.casePath();
    if (!steps) {
        box.appendChild(el('span', 'hint',
            'Путь корпуса не определён: задайте позиции и точку сброса.'));
        return;
    }
    const line = el('span');
    line.appendChild(document.createTextNode('Путь корпуса: '));
    line.appendChild(el('b', null, 'ВХОД'));
    steps.forEach(function (st) {
        line.appendChild(document.createTextNode(' → '));
        const part = el('b', null, 'П' + st.index +
            (st.primary ? ' ★' : '') + (st.cameras ? ' 🎥' : '') +
            (st.reset ? ' ⏏' : ''));
        line.appendChild(part);
    });
    const tail = model.belt.path_type === 'linear' ? ' → выход' : ' → ретур';
    line.appendChild(document.createTextNode(tail));
    box.appendChild(line);
}

/* ─── Инспектор ───────────────────────────────────────────────────── */

function renderInspector() {
    const body = $('inspector-body');
    body.textContent = '';
    const i = ui.selected;
    const pos = model.position(i);
    if (!pos) {
        body.appendChild(el('div', 'insp-empty',
            'Позиция не выбрана — кликните карточку на ленте.'));
        return;
    }

    const wrap = el('div', 'inspector');

    const head = el('div', 'insp-head');
    head.appendChild(el('span', 'pos-no', 'Позиция ' + i));
    head.appendChild(el('span', 'hint',
        (model.belt.path_type === 'linear' ? 'линейный путь' : 'циклический путь')));
    wrap.appendChild(head);

    const nav = el('div', 'insp-grid-actions');
    nav.appendChild(btn('◀ сдвинуть', 'btn', function () {
        model.movePosition(i, -1);
        ui.selected = i - 1;
        renderAll();
    }, [['title', 'Сдвинуть позицию влево']]));
    nav.appendChild(btn('сдвинуть ▶', 'btn', function () {
        model.movePosition(i, 1);
        ui.selected = i + 1;
        renderAll();
    }, [['title', 'Сдвинуть позицию вправо']]));
    nav.appendChild(btn('＋ после', 'btn', function () {
        ui.selected = model.insertPosition(i);
        renderAll();
    }, [['title', 'Вставить позицию после текущей']]));
    nav.appendChild(btn('✕ удалить', 'btn btn-danger', function () {
        model.removePosition(i);
        if (ui.selected >= model.positionCount()) {
            ui.selected = model.positionCount() - 1;
        }
        renderAll();
    }, [['title', 'Удалить позицию']]));
    wrap.appendChild(nav);

    const label = el('label', 'field');
    label.appendChild(el('span', null, 'Название позиции'));
    const input = el('input', 'insp-label-input');
    input.type = 'text';
    input.maxLength = 40;
    input.value = pos.label;
    on(input, 'input', function () {
        model.setPositionLabel(i, input.value);
        renderStrip();
        renderPathCaption();
        renderJson(false);
        scheduleDraft();
    });
    label.appendChild(input);
    wrap.appendChild(label);

    wrap.appendChild(renderInspectionSection(i, pos));
    wrap.appendChild(renderResetSection(i, pos));
    body.appendChild(wrap);
}

function renderInspectionSection(i, pos) {
    const sect = el('div', 'insp-section');
    const head = el('div', 'insp-row');
    head.appendChild(el('h3', null,
        pos.inspection ? 'МЕСТО ИНСПЕКЦИИ' : 'МЕСТО ИНСПЕКЦИИ НЕТ'));
    head.style.marginBottom = '0';
    if (pos.inspection) {
        head.appendChild(btn('✕ убрать место', 'btn btn-sm btn-danger', function () {
            model.removeInspection(i);
            renderAll();
        }));
    }
    sect.appendChild(head);

    if (!pos.inspection) {
        sect.appendChild(el('div', 'insp-note',
            'Добавьте место инспекции на позицию — она станет инспекционной. ' +
            'Если место инспекции на ленте одно, оно автоматически ' +
            'становится основным: определяет наличие детали.'));
        sect.appendChild(btn('＋ Сделать местом инспекции', 'btn btn-primary', function () {
            model.addInspection(i);
            renderAll();
        }));
        return sect;
    }

    const list = el('div');
    pos.inspection.cameras.forEach(function (cam, j) {
        const row = el('div', 'cam-row');
        const camInput = el('input');
        camInput.type = 'text';
        camInput.value = cam;
        camInput.maxLength = 24;
        camInput.placeholder = 'ROLE_NAME';
        on(camInput, 'input', function () {
            model.renameCamera(i, j, camInput.value);
            renderStrip();
            renderIssues();
            renderJson(false);
            scheduleDraft();
        });
        row.appendChild(camInput);
        row.appendChild(btn('✕', 'mini-btn del', function (ev) {
            ev.stopPropagation();
            model.removeCamera(i, j);
            renderAll();
        }));
        list.appendChild(row);
    });
    sect.appendChild(list);
    sect.appendChild(btn('＋ Камера', 'btn btn-sm', function () {
        model.addCamera(i);
        renderAll();
    }));

    const prim = el('div', 'primary-star');
    const single = model.inspectionCount() === 1;
    if (pos.inspection.primary) {
        prim.appendChild(el('span', 'lock-pill', '★ ОСНОВНОЕ'));
        prim.appendChild(el('span', 'insp-note', single
            ? 'Единственное место инспекции — основное автоматически.'
            : 'Определяет наличие детали (part_presence).'));
    } else {
        prim.appendChild(btn('★ Сделать основным', 'btn btn-sm', function () {
            model.setPrimary(i);
            renderAll();
            toast('Позиция ' + i + ' — основное место инспекции.');
        }));
    }
    sect.appendChild(prim);
    return sect;
}

function renderResetSection(i, pos) {
    const sect = el('div', 'insp-section');
    sect.appendChild(el('h3', null,
        pos.reset ? 'ТОЧКА СБРОСА' : 'СБРОС КОРПУСА'));
    sect.appendChild(el('div', 'insp-note',
        'Точка сброса — позиция, где корпус покидает ленту. ' +
        'На всей ленте она ровно одна; установка на новую позицию ' +
        'переносит сброс сюда.'));
    if (pos.reset) {
        sect.appendChild(btn('⏏ Снять точку сброса', 'btn', function () {
            model.setReset(i, false);
            renderAll();
        }));
    } else {
        sect.appendChild(btn('⏏ Сделать точкой сброса', 'btn btn-primary', function () {
            const note = model.setReset(i, true);
            renderAll();
            if (note) { toast(note); }
        }));
    }
    return sect;
}

/* ─── Проверки ────────────────────────────────────────────────────── */

function renderIssues() {
    const list = $('issues-list');
    list.textContent = '';
    const issues = model.validate();
    const errors = issues.filter(function (x) { return x.level === 'error'; });
    const warns = issues.filter(function (x) { return x.level === 'warn'; });
    const badge = $('issues-badge');
    if (issues.length === 0) {
        badge.textContent = '✓ конфигурация допустима';
        badge.className = 'issues-badge ok';
        list.appendChild(elRow('ok', null, 'Все проверки пройдены. ' +
            'Конфигурацию можно сохранять.'));
    } else {
        badge.textContent = '✕ ошибок: ' + errors.length + ' · предупреждений: ' + warns.length;
        badge.className = 'issues-badge' + (errors.length ? ' err' : ' ok');
        issues.forEach(function (issue) {
            list.appendChild(elRow(issue.level, issue.code, issue.text, issue.position));
        });
    }
}

function elRow(level, code, text, position) {
    const li = el('li', 'issue ' + level);
    if (code) { li.appendChild(el('span', 'issue-code', code)); }
    li.appendChild(el('span', 'issue-text', text));
    if (typeof position === 'number') {
        on(li, 'click', function () {
            ui.selected = position;
            renderAll();
            const card = $('belt-strip').querySelector(
                '.pos-card[data-index="' + position + '"]');
            if (card) { card.scrollIntoView({ block: 'nearest', inline: 'center' }); }
        });
    }
    return li;
}

/* ─── JSON-панель ─────────────────────────────────────────────────── */

function renderJson(force) {
    const area = $('json-area');
    if (ui.jsonDirty && !force) { return; }
    area.value = JSON.stringify(model.exportBelt(), null, 2);
    ui.jsonDirty = false;
}

function applyJson() {
    const area = $('json-area');
    let raw;
    try {
        raw = JSON.parse(area.value);
    } catch (err) {
        toast('JSON не разобран: ' + err.message, 'err');
        return;
    }
    try {
        model.loadBelt(raw);
    } catch (err) {
        toast('JSON не проходит формат belt.path.v1: ' + err.message, 'err');
        return;
    }
    ui.selected = Math.min(ui.selected, model.positionCount() - 1);
    ui.jsonDirty = false;
    renderAll();
    toast('Конфигурация применена из поля JSON.', 'ok');
}

/* ─── Сохранение / загрузка через сервер ──────────────────────────── */

async function saveToServer() {
    const issues = model.validate();
    const errors = issues.filter(function (x) { return x.level === 'error'; });
    if (errors.length > 0) {
        toast('Сначала исправьте ошибки конфигурации (' + errors.length + ').', 'err');
        return;
    }
    try {
        const res = await fetch('api/belt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(model.exportBelt()),
        });
        const data = await res.json();
        if (res.ok) {
            $('save-status').textContent =
                'сохранено в ' + (data.file || 'belt_path.json') + ' · ' + clockNow();
            toast('Конфигурация сохранена на сервер.', 'ok');
        } else if (res.status === 422) {
            const first = (data.issues || [])[0];
            toast('Сервер отклонил конфигурацию: ' +
                (first ? first.text : 'см. belt_path.json'), 'err');
        } else {
            toast('Сервер вернул HTTP ' + res.status, 'err');
        }
    } catch (err) {
        toast('Сервер недоступен (' + err.message +
            '). Используйте «Скачать» и «Загрузить».', 'err');
    }
}

async function loadFromServer() {
    try {
        const res = await fetch('api/belt');
        if (res.status === 404) {
            toast('На сервере нет сохранённой конфигурации.', 'err');
            return;
        }
        const data = await res.json();
        model.loadBelt(data);
        ui.selected = 0;
        renderAll();
        toast('Конфигурация загружена с сервера.', 'ok');
    } catch (err) {
        toast('Сервер недоступен — загрузите файл вручную.', 'err');
        $('file-input').click();
    }
}

function downloadJson() {
    const blob = new Blob([JSON.stringify(model.exportBelt(), null, 2) + '\n'],
        { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'belt_path.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
}

function openFile(file) {
    const reader = new FileReader();
    reader.onload = function () {
        try {
            model.loadBelt(JSON.parse(String(reader.result)));
        } catch (err) {
            toast('Файл не читается: ' + err.message, 'err');
            return;
        }
        ui.selected = 0;
        renderAll();
        toast('Файл загружен.', 'ok');
    };
    reader.readAsText(file, 'utf-8');
}

/* ─── Черновик в localStorage ─────────────────────────────────────── */

let draftTimer = null;

function scheduleDraft() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(saveDraft, 500);
}

function saveDraft() {
    try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(model.exportBelt()));
        $('draft-status').textContent = 'черновик сохранён · ' + clockNow();
    } catch (err) { /* приватный режим — молча */ }
}

function restoreDraft() {
    try {
        const raw = localStorage.getItem(DRAFT_KEY);
        if (!raw) { return false; }
        model.loadBelt(JSON.parse(raw));
        return true;
    } catch (err) {
        return false;
    }
}

/* ─── Обход пути (прогулка корпуса по ленте) ──────────────────────── */

function stopWalk() {
    if (ui.walkTimer !== null) {
        clearInterval(ui.walkTimer);
        ui.walkTimer = null;
    }
    ui.walkDone = [];
    syncWalkClasses();
    $('walk-log').textContent = '';
    $('btn-walk').textContent = '▶ Пройти путь';
}

function startWalk() {
    const steps = model.casePath();
    if (!steps) {
        toast('Нельзя пройти путь: не хватает позиций или точки сброса.', 'err');
        return;
    }
    ui.walkDone = [];
    let k = -1;
    $('btn-walk').textContent = '■ Остановить';
    const log = $('walk-log');
    ui.walkTimer = setInterval(function () {
        k += 1;
        if (k >= steps.length) {
            stopWalk();
            log.textContent = 'Корпус покинул ленту — путь пройден.';
            return;
        }
        ui.walkDone.push(steps[k].index);
        const st = steps[k];
        const bits = [];
        if (st.cameras) {
            bits.push('место инспекции (' + st.cameras.length + ' кам.)');
            if (st.primary) { bits.push('основное — наличие детали'); }
        }
        if (st.reset) { bits.push('сброс корпуса'); }
        log.textContent = 'Шаг ' + (k + 1) + '/' + steps.length +
            ': позиция ' + st.index + ' «' + st.label + '»' +
            (bits.length ? ' — ' + bits.join(', ') : ' — транспорт');
        syncWalkClasses();
        const card = $('belt-strip').querySelector(
            '.pos-card[data-index="' + st.index + '"]');
        if (card) { card.scrollIntoView({ block: 'nearest', inline: 'center' }); }
    }, WALK_STEP_MS);
}

function syncWalkClasses() {
    document.querySelectorAll('.pos-card').forEach(function (card) {
        const idx = Number(card.dataset.index);
        card.classList.remove('walk-current', 'walk-done');
        if (ui.walkTimer !== null && idx === ui.walkDone[ui.walkDone.length - 1]) {
            card.classList.add('walk-current');
        } else if (ui.walkDone.indexOf(idx) !== -1) {
            card.classList.add('walk-done');
        }
    });
}

/* ─── Глобальная панель ────────────────────────────────────────────── */

function renderTopbar() {
    const belt = model.belt;
    const name = $('belt-name');
    if (document.activeElement !== name) { name.value = belt.name; }
    document.querySelectorAll('#path-type .seg-btn').forEach(function (b) {
        b.setAttribute('aria-checked',
            String(b.dataset.type === belt.path_type));
    });
    $('positions-count').textContent =
        'позиций: ' + belt.positions.length + ' · мест инспекции: ' +
        model.inspectionCount() + ' · сброс: ' +
        (model.resetIndex() >= 0 ? 'П' + model.resetIndex() : 'нет');
}

/* ─── Главный рендер и инициализация ──────────────────────────────── */

function renderAll() {
    stopWalkSilent();
    renderTopbar();
    renderStrip();
    renderCaps();
    renderPathCaption();
    renderInspector();
    renderIssues();
    renderJson();
}

function stopWalkSilent() {
    if (ui.walkTimer !== null) {
        clearInterval(ui.walkTimer);
        ui.walkTimer = null;
        $('btn-walk').textContent = '▶ Пройти путь';
    }
    if (ui.walkDone.length) {
        ui.walkDone = [];
        $('walk-log').textContent = '';
        syncWalkClasses();
    }
}

function wireTopbar() {
    on($('belt-name'), 'input', function () {
        model.setName($('belt-name').value);
        scheduleDraft();
    });
    document.querySelectorAll('#path-type .seg-btn').forEach(function (b) {
        on(b, 'click', function () {
            model.setPathType(b.dataset.type);
            renderAll();
            scheduleDraft();
        });
    });
    on($('btn-add-position'), 'click', function () {
        ui.selected = model.addPosition();
        renderAll();
        scheduleDraft();
    });
    on($('btn-walk'), 'click', function () {
        if (ui.walkTimer !== null) { stopWalk(); } else { startWalk(); }
    });
    on($('btn-save'), 'click', saveToServer);
    on($('btn-load'), 'click', loadFromServer);
    on($('file-input'), 'change', function () {
        const f = $('file-input').files[0];
        if (f) { openFile(f); }
        $('file-input').value = '';
    });
    on($('btn-copy-json'), 'click', async function () {
        const text = JSON.stringify(model.exportBelt(), null, 2);
        try {
            await navigator.clipboard.writeText(text);
            toast('JSON скопирован.', 'ok');
        } catch (err) {
            const area = $('json-area');
            area.select();
            document.execCommand('copy');
            toast('JSON скопирован через выделение.', 'ok');
        }
    });
    on($('btn-apply-json'), 'click', applyJson);
    on($('btn-download-json'), 'click', downloadJson);
    on($('btn-reset-to-default'), 'click', function () {
        model.applyPreset('current7');
        ui.selected = 0;
        renderAll();
        scheduleDraft();
        toast('Загружена текущая линия (7 камер).');
    });

    const sel = $('preset-select');
    Object.keys(BeltModel.PRESETS).forEach(function (key) {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = BeltModel.PRESETS[key].caption;
        sel.appendChild(opt);
    });
    on(sel, 'change', function () {
        if (!sel.value) { return; }
        model.applyPreset(sel.value);
        ui.selected = 0;
        renderAll();
        scheduleDraft();
        sel.value = '';
    });
}

model.subscribe(function () {
    renderTopbar();
    renderStrip();
    renderPathCaption();
    renderIssues();
    renderJson();
    scheduleDraft();
});

async function boot() {
    wireTopbar();
    on($('json-area'), 'input', function () { ui.jsonDirty = true; });

    let loaded = false;
    try {
        const res = await fetch('api/belt');
        if (res.ok) {
            model.loadBelt(await res.json());
            $('save-status').textContent = 'конфигурация с сервера';
            loaded = true;
        }
    } catch (err) { /* файл / server не запущен — ниже черновик или пресет */ }
    if (loaded) {
        ui.selected = 0;
    } else if (restoreDraft()) {
        $('save-status').textContent = 'черновик из браузера';
    }
    renderAll();
}

document.addEventListener('DOMContentLoaded', boot);

})();
