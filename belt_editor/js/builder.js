/* belt_editor/js/builder.js — сборка ленты перетаскиванием элементов.
 *
 * Две области: палитра элементов (data-kind) и лента. Правила домена:
 *   - первая позиция ленты — вход: она СРАЗУ становится местом инспекции
 *     и основным: по входному наличию детали считается движение
 *     (part_presence), поэтому это место неснимаемо;
 *   - место инспекции навешивается и на другие позиции; повторный бросок
 *     снимает его (кроме входа);
 *   - камеры приходят из блока «Обнаруженные камеры» (js/cameras.js):
 *     плита тянется на позицию и привязывается к её месту инспекции;
 *     один прибор — в одном месте, перенос = ребинд, повторный бросок
 *     на ту же позицию отвязывает;
 *   - точка сброса одна: бросок на новую позицию переносит её, повторный
 *     бросок на занятую позицию снимает;
 *   - максимум 64 позиции.
 */
'use strict';

(function () {

const MAX_POSITIONS = 64;
const CAM_NAME_MAX = 24;

/* Симуляция обнаружения: список устройств, который сообщает слой
 * захвата (video0..video7). id — стабильный ключ привязки, name —
 * роль-метка (переименовывается), dev — путь устройства. */
/* Симулированные каталоги (имена — из vision/model_config.py и
 * thresholds.json, укорочены). Присоединяются перетаскиванием
 * плитки на фишку камеры; повторное — снимает. Привязка к прибору. */
let ruleQuery = '';
let modelQuery = '';

const MODELS = [
    { id: 'm0', name: 'uneven-heights' },
    { id: 'm1', name: 'window-sinks' },
    { id: 'm2', name: 'omission-long' },
    { id: 'm3', name: 'contacts-long' },
    { id: 'm4', name: 'bracket-90' },
    { id: 'm5', name: 'flange-low' },
    { id: 'm6', name: 'gear-set' },
    { id: 'm7', name: 'hinge-side' },
    { id: 'm8', name: 'plate-thin' },
    { id: 'm9', name: 'roller-mid' },
    { id: 'm10', name: 'shaft-long' },
    { id: 'm11', name: 'yoke-drop' },
];
const RULES = [
    { id: 'r0', name: 'геометрия', color: '#d9a441', models: [] },
    { id: 'r1', name: 'наличие', color: '#58b79a', models: [] },
    { id: 'r2', name: 'пропуск', color: '#cf7aa6', models: [] },
    { id: 'r3', name: 'контакты', color: '#a58ad9', models: [] },
];

function ruleColor(id) {
    const r = RULES.find(function (x) { return x.id === id; });
    return r ? r.color : 'var(--text-dim)';
}

const inventory = [];
(function discover() {
    for (let i = 0; i < 8; i += 1) {
        inventory.push({
            id: 'cam' + i, name: 'CAM_' + (i + 1), dev: 'video' + i,
            rules: [],
        });
    }
})();

function invCam(id) {
    for (let i = 0; i < inventory.length; i += 1) {
        if (inventory[i].id === id) { return inventory[i]; }
    }
    return null;
}

function camName(id) {
    const cam = invCam(id);
    return cam ? cam.name : id;
}

/* positions: [{label, inspection: null|{cameras:[], primary:bool}, reset}]
 * — форма совпадает с belt.path.v1, чтобы лента позже ушла в runtime
 * без переработки модели. */
const belt = { positions: [] };

let marker = null;      // индикатор вставки позиции
let dragKind = null;    // что сейчас тащим
let dragFrom = -1;      // индекс карточки при переносе
let dragCamId = null;   // id камеры при переносе из стены
let dragAsset = null;   // id модели/правила при переносе из каталога


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
        /* инспекция и сброс на одной позиции невозможны; вход
         * неснимаем, поэтому при конфликте всегда проигрывает сброс */
        if (pos.reset && pos.inspection) { pos.reset = false; }
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
    const resetIdx = findIndex(function (p) { return p.reset; });
    if (resetIdx >= 0 && gap > resetIdx) {
        toast('После точки сброса позиции не ставятся — она всегда'
            + ' последняя. Сначала снимите сброс.', 'err');
        return;
    }
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
    const r = findIndex(function (p) { return p.reset; });
    if (r >= 0) {
        const r1 = from < r ? r - 1 : r;
        const after = from === r ? to : (to <= r1 ? r1 + 1 : r1);
        if (after !== belt.positions.length - 1) {
            toast('Перенос нарушил бы «сброс — последняя».', 'err');
            return;
        }
    }
    const pos = belt.positions.splice(from, 1)[0];
    belt.positions.splice(to, 0, pos);
    applyInvariants();
    render();
}

function removePosition(i) {
    belt.positions.splice(i, 1);
    const hadReset = belt.positions.some(function (p) {
        return p.reset;
    });
    applyInvariants();
    if (hadReset && !belt.positions.some(function (p) { return p.reset; })
        && belt.positions.length > 0) {
        toast('Сброс снят: позиция стала входом — инспекция'
            + ' обязательна.', 'err');
    }
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
        if (pos.reset) {
            toast('П' + i + ' — точка сброса: инспекция и сброс'
                + ' на одной позиции невозможны.', 'err');
            return;
        }
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
        const last = belt.positions.length - 1;
        if (i !== last) {
            toast('Точка сброса — только на последней позиции (П'
                + last + ').', 'err');
            return;
        }
        if (pos.inspection) {
            toast('П' + i + ' — место инспекции: инспекция и сброс'
                + ' на одной позиции невозможны.', 'err');
            return;
        }
        belt.positions.forEach(function (p) { p.reset = false; });
        pos.reset = true;
        toast('П' + i + ' — точка сброса');
    }
    applyInvariants();
    render();
}

function bindCamera(i, camId) {
    const pos = belt.positions[i];
    if (!pos || !camId) { return; }
    if (!pos.inspection) {
        toast('П' + i + ' — не место инспекции: камеры ставятся только'
            + ' на места инспекции («Место инспекции» из палитры).');
        return;
    }
    const owner = findIndex(function (p) {
        return p.inspection && p.inspection.cameras.indexOf(camId) !== -1;
    });
    if (owner === i) {
        pos.inspection.cameras.splice(
            pos.inspection.cameras.indexOf(camId), 1);
        toast(camName(camId) + ' — снята с П' + i + '.');
        render();
        return;
    }
    if (owner >= 0) {
        belt.positions[owner].inspection.cameras.splice(
            belt.positions[owner].inspection.cameras.indexOf(camId), 1);
        toast(camName(camId) + ': П' + owner + ' → П' + i);
    } else {
        toast(camName(camId) + ' → П' + i);
    }
    pos.inspection.cameras.push(camId);
    applyInvariants();
    render();
}

function removeCamera(i, j) {
    const pos = belt.positions[i];
    if (!pos || !pos.inspection) { return; }
    const id = pos.inspection.cameras.splice(j, 1)[0];
    toast(camName(id) + ' — снята с П' + i + '.');
    render();
}

function renameCamera(i, j) {
    const card = $('belt-row').querySelector('.pos-card[data-index="' + i + '"]');
    const chip = card ? card.querySelectorAll('.chip')[j] : null;
    if (!chip) { return; }
    const pos = belt.positions[i];
    if (!pos || !pos.inspection) { return; }
    const cam = invCam(pos.inspection.cameras[j]);
    if (!cam) { return; }
    startInlineEdit(chip, function (text) {
        const name = String(text).trim().toUpperCase()
            .replace(/[^A-Z0-9_]/g, '').slice(0, CAM_NAME_MAX);
        if (!/^[A-Z][A-Z0-9_]{1,23}$/.test(name)) {
            toast('Роль некорректна: буквы/цифры/_ , 2–24, с буквы.', 'err');
            return;
        }
        const taken = inventory.some(function (other) {
            return other !== cam && other.name === name;
        });
        if (taken) {
            toast('Роль «' + name + '» уже занята.', 'err');
            return;
        }
        cam.name = name;
        render();
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

    if (window.Cameras) {
        window.Cameras.sync(cameraViews());
    }
    renderAssets();
    const zn = $('belt-zone');
    if (zn) { zn.dispatchEvent(new CustomEvent('belt:render')); }
}

function ruleOnCameras(rule) {
    return inventory.filter(function (d) {
        return d.rules.indexOf(rule.id) !== -1;
    });
}

/* модель — компонент правила: бросок на плитку правила, повторный — снять;
 * у правила «на камерах» последняя модель не снимается */
function togglePart(ruleId, modelId) {
    const rule = RULES.find(function (r) { return r.id === ruleId; });
    const mod = MODELS.find(function (m) { return m.id === modelId; });
    if (!rule || !mod) { return; }
    const at = rule.models.indexOf(modelId);
    if (at >= 0) {
        if (rule.models.length === 1 && ruleOnCameras(rule).length > 0) {
            toast('Правило «' + rule.name + '» стоит на камерах —'
                + ' последнюю модель не снять.', 'err');
            return;
        }
        rule.models.splice(at, 1);
        toast('«' + mod.name + '» убрана из «' + rule.name + '».');
    } else {
        rule.models.push(modelId);
        toast('«' + rule.name + '» ← ' + mod.name + '.');
    }
    render();
}

/* правило — на камеру; модели подгружаются составом правила */
function toggleRuleOnCam(camId, ruleId) {
    const dev = inventory.find(function (d) { return d.id === camId; });
    const rule = RULES.find(function (r) { return r.id === ruleId; });
    if (!dev || !rule) { return; }
    const at = dev.rules.indexOf(ruleId);
    if (at >= 0) {
        dev.rules.splice(at, 1);
        toast(dev.name + ': «' + rule.name + '» снято.');
    } else {
        if (!rule.models.length) {
            toast('Правило «' + rule.name + '» без моделей — не ставится.', 'err');
            return;
        }
        dev.rules.push(ruleId);
        toast(dev.name + ': «' + rule.name + '» подключено, модели подгружены.');
    }
    render();
}

function loadedModels(dev) {
    const set = Object.create(null);
    dev.rules.forEach(function (id) {
        const rule = RULES.find(function (r) { return r.id === id; });
        if (rule) {
            rule.models.forEach(function (m) { set[m] = true; });
        }
    });
    return Object.keys(set);
}

function renderAssets() {
    /* МОДЕЛИ — drag-источник: бросок на плашку правила назначает */
    const mbox = $('asset-models');
    if (mbox) {
        mbox.textContent = '';
        const mUsed = MODELS.filter(function (mod) {
            return RULES.some(function (r) {
                return r.models.indexOf(mod.id) !== -1;
            });
        }).length;
        const mlist = modelQuery ? MODELS.filter(function (mod) {
            return mod.name.toLowerCase().indexOf(modelQuery) !== -1;
        }) : MODELS;
        mlist.forEach(function (mod) {
            const byRules = RULES.filter(function (r) {
                return r.models.indexOf(mod.id) !== -1;
            });
            const tile = el('div', 'asset'
                + (byRules.length ? ' asset-used' : ''));
            tile.draggable = true;
            tile.appendChild(el('b', '', mod.name));
            if (byRules.length) {
                tile.appendChild(el('span', 'asset-use',
                    'правил: ' + byRules.length));
            }
            tile.addEventListener('dragstart', function (ev) {
                dragKind = 'model-part';
                dragAsset = mod.id;
                ev.dataTransfer.setData('text/plain',
                    'model:' + mod.id);
                ev.dataTransfer.effectAllowed = 'copy';
                tile.classList.add('dragging');
            });
            tile.addEventListener('dragend', function () {
                dragKind = null;
                dragAsset = null;
                cleanVisuals();
            });
            mbox.appendChild(tile);
        });
        const mcnt = $('model-count');
        if (mcnt) {
            mcnt.textContent = 'в правилах: ' + mUsed + ' / '
                + MODELS.length;
        }
    }

    /* ПРАВИЛА — одна строка: имя, счётчики, чипы состава.
     * Бросок модели добавляет, клик по чипу снимает. */
    const rbox = $('asset-rules');
    if (rbox) {
        rbox.textContent = '';
        const rUsed = RULES.filter(function (r) {
            return ruleOnCameras(r).length > 0;
        }).length;
        const rlist = ruleQuery ? RULES.filter(function (r) {
            return r.name.toLowerCase().indexOf(ruleQuery) !== -1;
        }) : RULES;
        rlist.forEach(function (rule) {
            const cams = ruleOnCameras(rule);
            const entry = el('div', 'rule-entry');
            const tile = el('div', 'rule-tile'
                + (cams.length ? ' asset-used' : '')
                + (rule.models.length ? '' : ' rule-empty'));
            tile.draggable = rule.models.length > 0;
            tile.dataset.ruleId = rule.id;
            const sw = el('span', 'rule-swatch');
            sw.style.background = rule.color;
            tile.appendChild(sw);
            const nm = el('b', '', rule.name);
            nm.style.color = rule.color;
            tile.appendChild(nm);
            if (rule.models.length) {
                tile.appendChild(el('span', 'rule-parts-count',
                    rule.models.length + 'м'));
            }
            if (cams.length) {
                tile.appendChild(el('span', 'asset-use',
                    'кам: ' + cams.length));
            }
            const drawer = el('div', 'rule-drawer'
                + (rule.models.length ? '' : ' rule-drawer-empty'));
            if (!rule.models.length) {
                drawer.style.borderColor = rule.color + '66';
            }
            rule.models.forEach(function (mid) {
                const mod = MODELS.find(function (m) {
                    return m.id === mid;
                });
                const chip = el('span', 'rule-chip',
                    mod ? mod.name : mid);
                chip.style.color = rule.color;
                chip.style.borderColor = rule.color + '66';
                chip.style.background = rule.color + '1f';
                chip.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    togglePart(rule.id, mid);
                });
                drawer.appendChild(chip);
            });
            entry.appendChild(tile);
            entry.appendChild(drawer);
            entry.addEventListener('dragover', function (ev) {
                if (dragKind !== 'model-part') { return; }
                ev.preventDefault();
                ev.stopPropagation();
                entry.classList.add('drop-target');
            });
            entry.addEventListener('dragleave', function () {
                entry.classList.remove('drop-target');
            });
            entry.addEventListener('drop', function (ev) {
                if (dragKind !== 'model-part') { return; }
                ev.preventDefault();
                ev.stopPropagation();
                const mid = dragAsset;
                dragKind = null;
                dragAsset = null;
                cleanVisuals();
                togglePart(rule.id, mid);
            });
            tile.addEventListener('dragstart', function (ev) {
                if (!rule.models.length) { return; }
                dragKind = 'rule';
                dragAsset = rule.id;
                ev.dataTransfer.setData('text/plain',
                    'rule:' + rule.id);
                ev.dataTransfer.effectAllowed = 'copy';
                entry.classList.add('dragging');
                const zn = $('belt-zone');
                if (zn && belt.positions.some(function (p) {
                    return p.inspection && p.inspection.cameras.length;
                })) {
                    zn.classList.add('drop-ready');
                }
            });
            tile.addEventListener('dragend', function () {
                dragKind = null;
                dragAsset = null;
                cleanVisuals();
            });
            rbox.appendChild(entry);
        });
        const rcnt = $('rule-count');
        if (rcnt) {
            rcnt.textContent = 'на камерах: ' + rUsed + ' / '
                + RULES.length;
        }
    }
}

/* Обнаруженные камеры: роли мест инспекции по порядку ленты;
 * основная — входное (П0) место. */
function cameraViews() {
    const bound = Object.create(null);
    belt.positions.forEach(function (pos, i) {
        if (!pos.inspection) { return; }
        pos.inspection.cameras.forEach(function (id) {
            bound[id] = { position: i, primary: !!pos.inspection.primary };
        });
    });
    return inventory.map(function (cam) {
        const b = bound[cam.id];
        return {
            id: cam.id,
            name: cam.name,
            dev: cam.dev,
            position: b ? b.position : -1,
            primary: b ? b.primary : false,
            rules: cam.rules.length,
            ruleColors: cam.rules.map(ruleColor),
            mods: loadedModels(cam).length,
        };
    });
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
        badges.appendChild(el('span', 'badge badge-insp', 'инспекция'));
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
        pos.inspection.cameras.forEach(function (id, j) {
            const chip = el('span', 'chip');
            chip.draggable = false;
            chip.appendChild(el('span', 'chip-name', camName(id)));
            const dev = inventory.find(function (d) { return d.id === id; });
            if (dev && dev.rules.length) {
                chip.appendChild(el('span', 'chip-assets',
                    'п:' + dev.rules.length
                    + ' · м:' + loadedModels(dev).length));
                const tabs = el('span', 'rule-tabs');
                dev.rules.forEach(function (rid) {
                    const t = el('i');
                    t.style.background = ruleColor(rid);
                    tabs.appendChild(t);
                });
                chip.appendChild(tabs);
            }
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

/* Мост для стены камер: dragstart/dragend плиты ленты-редактор
 * обрабатывает как обычный drop-объект. */
window.BeltBridge = {
    camDragStart: function (id, dt) {
        dragKind = 'camera';
        dragCamId = id;
        if (dt) {
            dt.setData('text/plain', 'camera:' + id);
            dt.effectAllowed = 'copy';
        }
        const zn = $('belt-zone');
        if (zn && belt.positions.some(function (p) {
            return p.inspection;
        })) {
            zn.classList.add('drop-ready');
        }
    },
    camDragEnd: function () {
        dragKind = null;
        dragCamId = null;
        cleanVisuals();
    },
    /* правило можно бросить и на плитку камеры в стене (настроить
     * прибор, даже не стоящий на ленте) — тот же тумбл, что и на фишке */
    ruleActive: function () { return dragKind === 'rule'; },
    ruleDrop: function (camId) {
        const rid = dragAsset;
        dragKind = null;
        dragAsset = null;
        cleanVisuals();
        toggleRuleOnCam(camId, rid);
    },
};

function cleanVisuals() {
    if (marker && marker.parentNode) { marker.remove(); }
    document.querySelectorAll('.drop-target')
        .forEach(function (n) { n.classList.remove('drop-target'); });
    $('belt-zone').classList.remove('drop-ready');
    document.querySelectorAll('.tool.dragging, .asset.dragging,'
        + '.pos-card.dragging-src,.rule-entry.dragging,'
        + '.rule-entry.drop-target')
        .forEach(function (n) {
            n.classList.remove('dragging', 'dragging-src', 'drop-target');
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
/* куда данный перетаскиваемый элемент реально «сядет» — подсветка
 * показывается только на принимающих целях (камера: только место
 * инспекции; не-позиционный сброс и т.п. отказа не подсвечиваем) */
function acceptsAt(kind, idx) {
    const pos = belt.positions[idx];
    if (!pos) { return false; }
    if (kind === 'camera') { return !!pos.inspection; }
    if (kind === 'inspect') { return !pos.reset || !!pos.inspection; }
    if (kind === 'reset') {
        return pos.reset
            || (idx === belt.positions.length - 1 && !pos.inspection);
    }
    return true;
}

function gapFromX(clientX) {
    const cards = $('belt-row').querySelectorAll('.pos-card');
    let gap = cards.length;
    for (let i = 0; i < cards.length; i += 1) {
        const r = cards[i].getBoundingClientRect();
        if (clientX < r.left + r.width / 2) { gap = i; break; }
    }
    /* раньше входной позиции слота нет: левее П0 — вставка сразу
     * после входа (маркер и drop считают один и тот же зажим) */
    if (cards.length > 0 && gap === 0) { gap = 1; }
    /* и слота за точкой сброса нет: дальше сброса цепь не растёт —
     * встанет перед ним */
    const rr = findIndex(function (p) { return p.reset; });
    if (rr >= 0 && gap > rr) { gap = rr; }
    return gap;
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
        } else if (dragKind === 'rule') {
            if (marker && marker.parentNode) { marker.remove(); }
            document.querySelectorAll('.drop-target').forEach(
                function (n) { n.classList.remove('drop-target'); });
            const chipEl = ev.target && ev.target.closest
                ? ev.target.closest('.chip') : null;
            if (chipEl) { chipEl.classList.add('drop-target'); }
        } else {
            if (marker && marker.parentNode) { marker.remove(); }
            const idx = cardFromEvent(ev);
            document.querySelectorAll('.pos-card.drop-target').forEach(
                function (n) { n.classList.remove('drop-target'); });
            if (idx >= 0 && acceptsAt(dragKind, idx)) {
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
        if (kind === 'model-part') {
            toast('Модель ставится на плитку правила в каталоге.', 'err');
            dragAsset = null;
            return;
        }
        if (cardIdx < 0) {
            toast(kind === 'rule'
                ? 'Опустите на фишку камеры.' : 'Не на позицию.', 'err');
            return;
        }
        if (kind === 'rule') {
            const chipEl = ev.target && ev.target.closest
                ? ev.target.closest('.chip') : null;
            const chips = chipEl && chipEl.parentNode
                ? chipEl.parentNode.querySelectorAll('.chip') : [];
            let j = -1;
            for (let k = 0; k < chips.length; k += 1) {
                if (chips[k] === chipEl) { j = k; }
            }
            const pos = belt.positions[cardIdx];
            if (j < 0 || !chipEl.closest('.pos-card')
                || Number(chipEl.closest('.pos-card').dataset.index) !== cardIdx
                || !pos || !pos.inspection) {
                toast('Опустите на фишку камеры.', 'err');
                dragAsset = null;
                return;
            }
            toggleRuleOnCam(pos.inspection.cameras[j], dragAsset);
            dragAsset = null;
            return;
        }
        if (kind === 'inspect') { toggleInspection(cardIdx); }
        else if (kind === 'reset') { toggleReset(cardIdx); }
        else if (kind === 'camera') {
            bindCamera(cardIdx, dragCamId);
            dragCamId = null;
        }
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
        /* сброс — хвост: его карточка не переносится */
        const moving = belt.positions[Number(card.dataset.index)];
        if (moving && moving.reset) {
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

/** листание списка ровно на плашку: шаг = высота первой строки + gap;
 * при перетаскивании ползунка список докликовывает scroll-snap */
function wireSteppedScroll(list) {
    if (!list) { return; }
    function step() {
        const row = list.firstElementChild;
        const h = row ? row.offsetHeight : 0;
        return h > 0 ? h + 6 : 40;
    }
    list.addEventListener('wheel', function (e) {
        if (list.scrollHeight <= list.clientHeight) { return; }
        e.preventDefault();
        const d = (e.deltaY > 0 ? 1 : -1) * step();
        if (list.scrollTo) {
            list.scrollTo({ top: list.scrollTop + d, behavior: 'smooth' });
        } else {
            list.scrollTop += d;
        }
    }, { passive: false });
}

function wireScrollSnap() {
    wireSteppedScroll($('asset-models'));
    wireSteppedScroll($('asset-rules'));
}

function wireSearch() {
    [['rule-search', function (v) { ruleQuery = v; }],
     ['model-search', function (v) { modelQuery = v; }]]
        .forEach(function (pair) {
            const inp = $(pair[0]);
            if (!inp) { return; }
            inp.addEventListener('input', function () {
                pair[1](inp.value.trim().toLowerCase());
                render();
            });
        });
}

document.addEventListener('DOMContentLoaded', function () {
    wirePalette();
    wireBelt();
    wireSearch();
    wireScrollSnap();
    render();
});

})();
