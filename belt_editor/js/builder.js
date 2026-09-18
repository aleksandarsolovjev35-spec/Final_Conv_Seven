/* belt_editor/js/builder.js — сборка ленты перетаскиванием элементов.
 *
 * Две области: палитра элементов (data-kind) и лента. Правила домена:
 *   - первая позиция ленты — вход: она СРАЗУ становится местом инспекции
 *     и основным: по входному наличию детали считается движение
 *     (part_presence), поэтому это место неснимаемо;
 *   - место инспекции навешивается и на другие позиции; повторный бросок
 *     снимает его (кроме входа);
 *   - точка сброса одна: бросок на новую позицию переносит её, повторный
 *     бросок на занятую позицию снимает;
 *   - максимум 64 позиции.
 */
'use strict';

(function () {

const MAX_POSITIONS = 64;
const CAM_NAME_MAX = 24;

/* positions: [{label, inspection: null|{cameras:[], primary:bool}, reset}]
 * — форма совпадает с belt.path.v1, чтобы лента позже ушла в runtime
 * без переработки модели. */
const belt = { positions: [] };

let marker = null;      // индикатор вставки позиции
let dragKind = null;    // что сейчас тащим
let dragFrom = -1;      // индекс карточки при переносе

/* ─── Инварианты ─────────────────────────────────────────────────── */

function applyInvariants() {
    let resetKept = false;
    belt.positions.forEach(function (pos, i) {
        if (pos.reset) {
            if (resetKept) { pos.reset = false; }
            resetKept = true;
        }
        if (i === 0) {
            if (!pos.inspection) { pos.inspection = { cameras: [], primary: true }; }
            else { pos.inspection.primary = true; }
        } else if (pos.inspection) {
            pos.inspection.primary = false;
        }
    });
}

function findIndex(pred) {
    for (let i = 0; i < belt.positions.length; i += 1) {
        if (pred(belt.positions[i], i)) { return i; }
    }
    return -1;
}

/* ─── Действия ───────────────────────────────────────────────────── */

function insertPosition(gap) {
    if (belt.positions.length >= MAX_POSITIONS) {
        toast('Максимум ' + MAX_POSITIONS + ' позиций на ленте.', 'err');
        return;
    }
    const wasEmpty = belt.positions.length === 0;
    belt.positions.splice(gap, 0, {
        label: '', inspection: null, reset: false,
    });
    applyInvariants();
    render();
    if (gap === 0) {
        toast('П0 — вход: место инспекции, определяет наличие детали.');
    } else if (wasEmpty) {
        toast('Позиция добавлена.');
    }
}

function movePosition(from, gap) {
    const to = gap > from ? gap - 1 : gap;
    if (to === from) { return; }
    const pos = belt.positions.splice(from, 1)[0];
    belt.positions.splice(to, 0, pos);
    applyInvariants();
    render();
}

function removePosition(i) {
    belt.positions.splice(i, 1);
    applyInvariants();
    render();
}

function toggleInspection(i) {
    const pos = belt.positions[i];
    if (!pos) { return; }
    if (i === 0) {
        toast('П0 — входное место инспекции, оно не снимается.');
        return;
    }
    if (pos.inspection) {
        pos.inspection = null;
        toast('П' + i + ': инспекция снята.');
    } else {
        pos.inspection = { cameras: [], primary: false };
        toast('П' + i + ' — место инспекции.');
    }
    applyInvariants();
    render();
}

function toggleReset(i) {
    const pos = belt.positions[i];
    if (!pos) { return; }
    if (pos.reset) {
        pos.reset = false;
        toast('П' + i + ': точка сброса снята.');
    } else {
        const prev = findIndex(function (p) { return p.reset; });
        belt.positions.forEach(function (p) { p.reset = false; });
        pos.reset = true;
        toast(prev >= 0 ? 'сброс: П' + prev + ' → П' + i
            : 'П' + i + ' — точка сброса');
    }
    applyInvariants();
    render();
}

function addCamera(i) {
    const pos = belt.positions[i];
    if (!pos) { return; }
    if (!pos.inspection) {
        pos.inspection = { cameras: [], primary: false };
        applyInvariants();
        toast('П' + i + ' — место инспекции');
    }
    const used = Object.create(null);
    belt.positions.forEach(function (other) {
        if (other.inspection) {
            other.inspection.cameras.forEach(function (c) { used[c] = true; });
        }
    });
    let k = 1;
    while (used['CAM_' + k]) { k += 1; }
    pos.inspection.cameras.push('CAM_' + k);
    render();
}

function removeCamera(i, j) {
    const pos = belt.positions[i];
    if (!pos || !pos.inspection) { return; }
    const name = pos.inspection.cameras.splice(j, 1)[0];
    toast('Камера ' + name + ' убрана с П' + i + '.');
    render();
}

function renameCamera(i, j) {
    const card = $('belt-row').querySelector('.pos-card[data-index="' + i + '"]');
    const chip = card ? card.querySelectorAll('.chip')[j] : null;
    if (!chip) { return; }
    startInlineEdit(chip, function (text) {
        const pos = belt.positions[i];
        if (!pos || !pos.inspection) { return; }
        const name = String(text).trim().toUpperCase()
            .replace(/[^A-Z0-9_]/g, '').slice(0, CAM_NAME_MAX);
        if (!/^[A-Z][A-Z0-9_]{1,23}$/.test(name)) {
            toast('Роль «' + name + '» некорректна: буквы/цифры/_ , 2–24, с буквы.',
                'err');
            return;
        }
        pos.inspection.cameras[j] = name;
    });
}

function renamePosition(i) {
    const card = $('belt-row').querySelector('.pos-card[data-index="' + i + '"]');
    const label = card ? card.querySelector('.pos-label') : null;
    if (!label) { return; }
    startInlineEdit(label, function (text) {
        const pos = belt.positions[i];
        if (pos) { pos.label = String(text).trim().slice(0, 40); }
    });
}

/* contenteditable-редактирование прямо в карточке: Enter — применить,
 * Esc — отменить, потеря фокуса — применить. */
function startInlineEdit(node, onCommit) {
    node.dataset.editing = '1';
    node.setAttribute('contenteditable', 'plaintext-only');
    if (!node.isContentEditable) { node.setAttribute('contenteditable', 'true'); }
    node.classList.add('editing');
    const range = document.createRange();
    range.selectNodeContents(node);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const finish = function (commit) {
        if (!node.dataset.editing) { return; }
        delete node.dataset.editing;
        node.removeAttribute('contenteditable');
        node.classList.remove('editing');
        const text = node.textContent;
        node.removeEventListener('keydown', onKey);
        if (commit) { onCommit(text); }
        render();
    };
    const onKey = function (ev) {
        if (ev.key === 'Enter') { ev.preventDefault(); finish(true); }
        else if (ev.key === 'Escape') { ev.preventDefault(); finish(false); }
    };
    node.addEventListener('keydown', onKey);
    node.addEventListener('blur', function () { finish(true); }, { once: true });
}

/* ─── Рендер ─────────────────────────────────────────────────────── */

function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined) { node.textContent = text; }
    return node;
}

function render() {
    const row = $('belt-row');
    row.textContent = '';

    belt.positions.forEach(function (pos, i) {
        if (i > 0) { row.appendChild(el('span', 'lane-arrow', '→')); }
        row.appendChild(renderCard(pos, i));
    });

    $('belt-meta').textContent = 'позиций: ' + belt.positions.length +
        ' / ' + MAX_POSITIONS;
}

function renderCard(pos, i) {
    const card = el('div', 'pos-card');
    if (pos.inspection) { card.classList.add('inspect'); }
    if (pos.reset) { card.classList.add('reset-pt'); }
    card.dataset.index = String(i);

    const top = el('div', 'pos-top');
    top.appendChild(el('span', 'pos-index', 'П' + i));
    const del = el('button', 'pos-del', '×');
    del.type = 'button';
    del.draggable = false;
    top.appendChild(del);
    card.appendChild(top);

    card.appendChild(el('div', 'pos-label', pos.label || 'Позиция ' + i));

    const badges = el('div', 'pos-badges');
    if (pos.inspection) {
        if (pos.inspection.primary) {
            badges.appendChild(el('span', 'badge badge-primary', 'основное'));
        } else {
            badges.appendChild(el('span', 'badge badge-insp', 'инспекция'));
        }
        const n = pos.inspection.cameras.length;
        badges.appendChild(el('span', 'badge badge-cam',
            n ? 'камер: ' + n : 'без камер'));
    }
    if (pos.reset) {
        badges.appendChild(el('span', 'badge badge-reset', 'сброс'));
    }
    card.appendChild(badges);

    if (pos.inspection && pos.inspection.cameras.length) {
        const cams = el('div', 'cam-chips');
        pos.inspection.cameras.forEach(function (name, j) {
            const chip = el('span', 'chip');
            chip.draggable = false;
            chip.appendChild(el('span', 'chip-name', name));
            const chipX = el('button', 'chip-x', '×');
            chipX.type = 'button';
            chipX.draggable = false;
            chipX.addEventListener('click', function (ev) {
                ev.stopPropagation();
                removeCamera(i, j);
            });
            chip.appendChild(chipX);
            chip.addEventListener('dblclick', function (ev) {
                ev.stopPropagation();
                renameCamera(i, j);
            });
            cams.appendChild(chip);
        });
        card.appendChild(cams);
    }
    return card;
}

function $(id) { return document.getElementById(id); }

let toastTimer = null;

function toast(text, kind) {
    const box = $('toasts');
    box.textContent = '';
    const node = el('div', 'toast' + (kind ? ' ' + kind : ''), text);
    box.appendChild(node);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.textContent = ''; }, 3200);
}

/* ─── Drag & drop ─────────────────────────────────────────────────── */

function cleanVisuals() {
    if (marker && marker.parentNode) { marker.remove(); }
    document.querySelectorAll('.pos-card.drop-target')
        .forEach(function (n) { n.classList.remove('drop-target'); });
    $('belt-zone').classList.remove('drop-ready');
    document.querySelectorAll('.tool.dragging, .pos-card.dragging-src')
        .forEach(function (n) {
            n.classList.remove('dragging', 'dragging-src');
        });
}

function ensureMarker() {
    if (!marker) {
        marker = el('div', 'insert-marker');
    }
    return marker;
}

/* индекс щели (0..n), куда встанет позиция по X курсора; карточки и
 * стрелки лежат в ряду по очереди, поэтому шаг 2 */
function gapFromX(clientX) {
    const cards = $('belt-row').querySelectorAll('.pos-card');
    for (let i = 0; i < cards.length; i += 1) {
        const r = cards[i].getBoundingClientRect();
        if (clientX < r.left + r.width / 2) { return i; }
    }
    return cards.length;
}

function showMarkerAt(gap) {
    const row = $('belt-row');
    const m = ensureMarker();
    const cards = row.querySelectorAll('.pos-card');
    const before = cards[gap] || null;
    if (m.parentNode !== row || (before ? m.nextSibling !== before
        : before === null && row.lastChild !== m)) {
        row.insertBefore(m, before);
    }
}

function cardFromEvent(ev) {
    const node = ev.target && ev.target.closest
        ? ev.target.closest('.pos-card') : null;
    if (node) { return Number(node.dataset.index); }
    return -1;
}

function wirePalette() {
    document.querySelectorAll('.tool').forEach(function (tool) {
        tool.addEventListener('dragstart', function (ev) {
            dragKind = tool.dataset.kind;
            dragFrom = -1;
            ev.dataTransfer.setData('text/plain', dragKind);
            ev.dataTransfer.effectAllowed = 'copy';
            tool.classList.add('dragging');
            $('belt-zone').classList.add('drop-ready');
        });
        tool.addEventListener('dragend', function () {
            dragKind = null;
            dragFrom = -1;
            cleanVisuals();
        });
    });
}

function wireBelt() {
    const zone = $('belt-zone');

    /* Firefox: пока не снят default у dragenter, до dragover/drop дело
     * может не дойти */
    zone.addEventListener('dragenter', function (ev) {
        if (dragKind) { ev.preventDefault(); }
    });

    zone.addEventListener('dragover', function (ev) {
        if (!dragKind) { return; }
        ev.preventDefault();
        const wantsSlot = dragKind === 'position' || dragKind === 'move';
        if (dragKind === 'move') {
            ev.dataTransfer.dropEffect = 'move';
        } else {
            ev.dataTransfer.dropEffect = 'copy';
        }
        if (wantsSlot) {
            showMarkerAt(gapFromX(ev.clientX));
            document.querySelectorAll('.pos-card.drop-target').forEach(
                function (n) { n.classList.remove('drop-target'); });
        } else {
            if (marker && marker.parentNode) { marker.remove(); }
            const idx = cardFromEvent(ev);
            document.querySelectorAll('.pos-card.drop-target').forEach(
                function (n) { n.classList.remove('drop-target'); });
            if (idx >= 0) {
                const card = zone.querySelector(
                    '.pos-card[data-index="' + idx + '"]');
                if (card) { card.classList.add('drop-target'); }
            }
        }
    });

    zone.addEventListener('dragleave', function (ev) {
        if (ev.relatedTarget && zone.contains(ev.relatedTarget)) { return; }
        if (marker && marker.parentNode) { marker.remove(); }
        document.querySelectorAll('.pos-card.drop-target').forEach(
            function (n) { n.classList.remove('drop-target'); });
    });

    zone.addEventListener('drop', function (ev) {
        if (!dragKind) { return; }
        ev.preventDefault();
        const kind = dragKind;
        const from = dragFrom;
        const cardIdx = cardFromEvent(ev);
        const gap = gapFromX(ev.clientX);
        cleanVisuals();
        dragKind = null;
        dragFrom = -1;

        const emptyZone = belt.positions.length === 0;
        if (kind === 'position') {
            insertPosition(gap);
            return;
        }
        if (kind === 'move') {
            if (from >= 0) { movePosition(from, gap); }
            return;
        }
        if (emptyZone) {
            toast('Нет ни одной позиции.', 'err');
            return;
        }
        if (cardIdx < 0) {
            toast('Не на позицию.', 'err');
            return;
        }
        if (kind === 'inspect') { toggleInspection(cardIdx); }
        else if (kind === 'reset') { toggleReset(cardIdx); }
        else if (kind === 'camera') { addCamera(cardIdx); }
    });

    /* клик по карточке: делёжка и значки */
    $('belt-row').addEventListener('click', function (ev) {
        if (ev.target.closest('.chip')) { return; }
        const del = ev.target.closest('.pos-del');
        if (del) {
            const i = cardFromEvent(ev);
            if (i >= 0) {
                removePosition(i);
                toast('Позиция П' + i + ' удалена.');
            }
            return;
        }
    });

    $('belt-row').addEventListener('dblclick', function (ev) {
        if (ev.target.closest('.chip') || ev.target.closest('.pos-del')) {
            return;
        }
        const i = cardFromEvent(ev);
        if (i >= 0) { renamePosition(i); }
    });

    /* перенос карточек по ленте */
    $('belt-row').addEventListener('dragstart', function (ev) {
        const card = ev.target.closest('.pos-card');
        if (!card || ev.target.closest('.chip, .pos-del, .editing')) {
            ev.preventDefault();
            return;
        }
        dragKind = 'move';
        dragFrom = Number(card.dataset.index);
        ev.dataTransfer.setData('text/plain', 'move:' + dragFrom);
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.dropEffect = 'move';
        card.classList.add('dragging-src');
        $('belt-zone').classList.add('drop-ready');
    });

    $('belt-row').addEventListener('dragend', function () {
        dragKind = null;
        dragFrom = -1;
        cleanVisuals();
    });

    /* карточки draggable только за «ручку»-тело: чипы и кнопки — нет */
    const observer = new MutationObserver(function () {
        $('belt-row').querySelectorAll('.pos-card')
            .forEach(function (n) { n.draggable = true; });
    });
    observer.observe($('belt-row'), { childList: true, subtree: true });
}

/* ─── Старт ───────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', function () {
    wirePalette();
    wireBelt();
    render();
});

})();
