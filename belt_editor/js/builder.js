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
    { id: 'r0', name: 'геометрия', color: '#d9a441',
      thr: ['площадь', 'перекос', 'высота'], models: [] },
    { id: 'r1', name: 'наличие', color: '#58b79a',
      thr: ['контраст'], models: [] },
    { id: 'r2', name: 'пропуск', color: '#cf7aa6',
      thr: ['окно'], models: [] },
    { id: 'r3', name: 'контакты', color: '#a58ad9',
      thr: ['нажим', 'смещение'], models: [] },
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
const belt = { positions: [], places: Object.create(null) };

let uidSeq = 0;       // сквозной id позиций для связей цепи
let dragKind = null;    // что сейчас тащим
let dragFrom = -1;      // индекс карточки при переносе
let dragCamId = null;   // id камеры при переносе из стены
let dragAsset = null;   // id модели/правила при переносе из каталога
let openThrCam = null;  // id камеры, у которой открыт поповер порогов
const THR_DEFAULT = 0.5;


/* ─── Инварианты ─────────────────────────────────────────────────── */

function applyInvariants() {
    let resetKept = false;
    belt.positions.forEach(function (pos, i) {
        if (pos.uid == null) { pos.uid = ++uidSeq; }
        if (pos.reset && pos.nextUid) { pos.nextUid = null; }
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

/* Позиции ставятся буквально куда бросил; порядок ленты задают
 * линки коннекторов (П0→…→сброс), а не место в ряду */
function insertPosition(at) {
    if (belt.positions.length >= MAX_POSITIONS) {
        toast('Максимум ' + MAX_POSITIONS + ' позиций на ленте.', 'err');
        return;
    }
    const wasEmpty = belt.positions.length === 0;
    belt.positions.push({
        label: '', inspection: null, reset: false,
        uid: ++uidSeq, nextUid: null,
        at: at || layoutSlot(belt.positions.length),
    });
    applyInvariants();
    render();
    if (wasEmpty) {
        toast('П0 — вход: место инспекции, определяет наличие детали.');
    } else {
        toast('Позиция добавлена — соедините её коннекторами.');
    }
}

function removePosition(i) {
    const gone = belt.positions[i];
    if (gone) {
        belt.positions.forEach(function (p) {
            if (String(p.nextUid) === String(gone.uid)) {
                p.nextUid = null;
            }
        });
    }
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
        if (pos.nextUid) {
            toast('У П' + i + ' есть связь дальше по ленте — сначала'
                + ' разорвите её (повторная линка снимает).', 'err');
            return;
        }
        if (pos.inspection && i === 0) {
            toast('П0 — вход, сбросом быть не может.', 'err');
            return;
        }
        if (pos.inspection) {
            toast('П' + i + ' — место инспекции: инспекция и сброс'
                + ' на одной позиции невозможны.', 'err');
            return;
        }
        belt.positions.forEach(function (p) {
            p.reset = false;
        });
        pos.nextUid = null;
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
    if (!belt.places['cam:' + camId]) {
        belt.places['cam:' + camId] = freePoint();
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

function camOwner(camId) {
    for (let i = 0; i < belt.positions.length; i += 1) {
        const pos = belt.positions[i];
        if (pos.inspection
            && pos.inspection.cameras.indexOf(camId) !== -1) { return i; }
    }
    return -1;
}

function renameCamera(camId) {
    const node = $('belt-row').querySelector(
        '.cam-node[data-cam="' + camId + '"]');
    const chip = node ? node.querySelector('.chip') : null;
    const cam = invCam(camId);
    if (!chip || !cam) { return; }
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
        row.appendChild(renderCard(pos, i));
    });
    Object.keys(belt.places).forEach(function (key) {
        const parts = key.split(':');
        const at = belt.places[key];
        if (parts[0] === 'cam') {
            row.appendChild(renderCamNode(parts[1], at));
        } else if (parts[0] === 'rule') {
            row.appendChild(renderRuleNode(parts[1], at));
        } else if (parts[0] === 'model') {
            row.appendChild(renderModelNode(parts[1], at));
        }
    });

    $('belt-meta').textContent = 'позиций: ' + belt.positions.length +
        ' / ' + MAX_POSITIONS;

    if (window.Cameras) {
        window.Cameras.sync(cameraViews());
    }
    renderAssets();
    renderWires();
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

function findPosByUid(uid) {
    for (let i = 0; i < belt.positions.length; i += 1) {
        if (String(belt.positions[i].uid) === String(uid)) {
            return belt.positions[i];
        }
    }
    return null;
}

/* линка коннекторов ленты: у позиции один выход; вход приёмника
 * перетягивается на себя; повторная линка разрывает; цикл запрещён */
function linkPos(fromUid, toUid) {
    const from = findPosByUid(fromUid);
    const to = findPosByUid(toUid);
    if (!from || !to) { return; }
    if (from === to) {
        toast('Позиция не связывается сама с собой.', 'err');
        return;
    }
    if (String(from.nextUid) === String(toUid)) {
        from.nextUid = null;
        toast('Связь разорвана.');
        render();
        return;
    }
    let cur = to;
    let guard = 0;
    while (cur && guard <= belt.positions.length) {
        if (cur === from) {
            toast('Лента не делает цикл.', 'err');
            return;
        }
        cur = cur.nextUid ? findPosByUid(cur.nextUid) : null;
        guard += 1;
    }
    belt.positions.forEach(function (pp) {
        if (String(pp.nextUid) === String(toUid)) { pp.nextUid = null; }
    });
    from.nextUid = String(toUid);
    toast('П' + belt.positions.indexOf(from) + ' → П'
        + belt.positions.indexOf(to));
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
        if (dev.thr) { delete dev.thr[ruleId]; }
        toast(dev.name + ': «' + rule.name + '» снято.');
    } else {
        if (!rule.models.length) {
            toast('Правило «' + rule.name + '» без моделей — не ставится.', 'err');
            return;
        }
        dev.rules.push(ruleId);
        if (!dev.thr) { dev.thr = Object.create(null); }
        dev.thr[ruleId] = rule.thr.map(function () { return THR_DEFAULT; });
        toast(dev.name + ': «' + rule.name + '» подключено, '
            + rule.thr.length + ' порог(а) = ' + THR_DEFAULT.toFixed(2) + '.');
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
                const zn = $('belt-zone');
                if (zn) { zn.classList.add('drop-ready'); }
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
            tile.draggable = true;
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
            tile.addEventListener('dragstart', function (ev) {
                dragKind = 'rule';
                dragAsset = rule.id;
                ev.dataTransfer.setData('text/plain',
                    'rule:' + rule.id);
                ev.dataTransfer.effectAllowed = 'copy';
                entry.classList.add('dragging');
                const zn = $('belt-zone');
                if (zn) { zn.classList.add('drop-ready'); }
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
    const card = el('div', 'pos-card gnode g-pos');
    card.dataset.gk = 'pos:' + i;
    if (!pos.at) { pos.at = layoutSlot(i); }
    card.style.left = Math.round(pos.at.x) + 'px';
    card.style.top = Math.round(pos.at.y) + 'px';
    if (pos.inspection) { card.classList.add('inspect'); }
    if (pos.reset) { card.classList.add('reset-pt'); }
    card.dataset.index = String(i);

    const head = el('div', 'node-head');
    head.appendChild(el('span', 'pos-index', 'П' + i));
    head.appendChild(el('span', 'pos-label', pos.label || 'Позиция ' + i));
    const del = el('button', 'pos-del', '×');
    del.type = 'button';
    del.draggable = false;
    head.appendChild(del);
    card.appendChild(head);

    const body = el('div', 'node-body');
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
    body.appendChild(badges);

    const camIn = el('span', 'sock sock-in sock-node');
    camIn.dataset.drop = 'pos';
    camIn.dataset.idx = String(i);
    card.appendChild(camIn);
    if (i > 0) {
        const lin = el('span', 'sock sock-in sock-line-in');
        lin.dataset.drop = 'poslink';
        lin.dataset.uid = String(pos.uid);
        card.appendChild(lin);
    }
    if (!pos.reset) {
        const lout = el('span', 'sock sock-out sock-line-out');
        lout.dataset.link = 'posline:' + pos.uid;
        card.appendChild(lout);
    }

    card.appendChild(body);
    return card;
}

/* ─── Холст сборки: свободные ноды моделей/правил/камер ────────────
 * Любая нода ставится в любое место ленты (places = координаты),
 * связь — только сокет-линка: модель→правило, правило→камера,
 * камера→зона инспекции. Ноду можно двигать ЛКМ за шапку. */

function clampN(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

const CANVAS_W = 5000;
const CANVAS_H = 3000;

/* запасная точка для позиции без координат (старое сохранение):
 * ступенькой от центра поля; поле — свободное 2D */
function layoutSlot(i) {
    const row = $('belt-row');
    const maxW = Math.max(row ? (row.offsetWidth || 0) : 0, CANVAS_W);
    const maxH = Math.max(row ? (row.offsetHeight || 0) : 0, CANVAS_H);
    const cx = Math.round(maxW / 2);
    const cy = Math.round(maxH / 2);
    return {
        x: clampN(cx - 260 + i * 206, 2, maxW - 190),
        y: clampN(cy - 60 + (i % 3) * 40, 2, maxH - 124)
    };
}

/* экранные координаты дропа → координаты холста (учитывая зум) */
function canvasPoint(ev, w, h) {
    const row = $('belt-row');
    const r = row.getBoundingClientRect();
    const z = (window.BeltView && window.BeltView.state().z) || 1;
    const maxW = Math.max(row ? (row.offsetWidth || 0) : 0, CANVAS_W);
    const maxH = Math.max(row ? (row.offsetHeight || 0) : 0, CANVAS_H);
    let x = Math.round(maxW / 2 - w / 2);
    let y = Math.round(maxH / 2 - h / 2);
    if (r.width) {
        x = (ev.clientX - r.left) / z - w / 2;
        y = (ev.clientY - r.top) / z - h / 2;
    }
    return {
        x: clampN(x, 2, Math.max(2, maxW - w - 2)),
        y: clampN(y, 2, Math.max(2, maxH - h - 2)),
    };
}

function freePoint() {
    const row = $('belt-row');
    const maxW = Math.max(row ? (row.offsetWidth || 0) : 0, CANVAS_W);
    const maxH = Math.max(row ? (row.offsetHeight || 0) : 0, CANVAS_H);
    return {
        x: Math.round(maxW / 2 - 60),
        y: Math.round(maxH / 2 - 120) + Object.keys(belt.places).length * 20
    };
}

function placeNode(key, ev) {
    belt.places[key] = canvasPoint(ev, 120, 28);
    toast('Связь — линкой сокета на холсте ленты.');
    render();
}

function gnodeFrame(cls, key, at, title) {
    const node = el('div', 'gnode ' + cls);
    node.dataset.gk = key;
    node.style.left = Math.round(at.x) + 'px';
    node.style.top = Math.round(at.y) + 'px';
    const head = el('div', 'node-head');
    head.appendChild(el('span', 'pos-label', title));
    const del = el('button', 'pos-del', '×');
    del.type = 'button';
    del.draggable = false;
    head.appendChild(del);
    node.appendChild(head);
    return node;
}

function gsock(cls, link, drop, rid) {
    const n = el('span', 'sock ' + cls);
    if (link) { n.dataset.link = link; }
    if (drop) { n.dataset.drop = drop; }
    if (rid) { n.dataset.rid = rid; }
    return n;
}

function renderModelNode(mid, at) {
    const mod = MODELS.find(function (m) { return m.id === mid; });
    if (!mod) { return el('div', 'gnode'); }
    const key = 'model:' + mid;
    const node = gnodeFrame('g-model', key, at, mod.name);
    node.dataset.model = mid;
    node.querySelector('.pos-del').addEventListener('click', function (ev) {
        ev.stopPropagation();
        delete belt.places[key];
        render();
    });
    node.appendChild(gsock('sock-out', key, null));
    const rules = RULES.filter(function (r) {
        return r.models.indexOf(mid) !== -1;
    });
    if (rules.length) {
        node.appendChild(el('div', 'g-meta', 'правил: ' + rules.length));
    }
    return node;
}

function renderRuleNode(rid, at) {
    const rule = RULES.find(function (r) { return r.id === rid; });
    if (!rule) { return el('div', 'gnode'); }
    const key = 'rule:' + rid;
    const node = gnodeFrame('g-rule', key, at, rule.name);
    node.dataset.rule = rid;
    node.querySelector('.pos-del').addEventListener('click', function (ev) {
        ev.stopPropagation();
        delete belt.places[key];
        render();
    });
    const head = node.querySelector('.node-head');
    head.insertBefore(el('i', 'g-swatch'), head.firstChild);
    head.firstChild.style.background = rule.color;
    node.querySelector('.pos-label').style.color = rule.color;
    node.appendChild(gsock('sock-in', null, 'rule', rid));
    node.appendChild(gsock('sock-out', key, null));
    const list = el('div', 'g-models');
    rule.models.forEach(function (mid) {
        const mod = MODELS.find(function (m) { return m.id === mid; });
        const chip = el('span', 'g-chip', mod ? mod.name : mid);
        chip.title = 'снять модель';
        chip.addEventListener('click', function (ev) {
            ev.stopPropagation();
            togglePart(rid, mid);
        });
        list.appendChild(chip);
    });
    if (!rule.models.length) {
        list.appendChild(el('span', 'g-empty', '→ тяни модель сюда'));
    }
    node.appendChild(list);
    const cams = ruleOnCameras(rule);
    if (cams.length) {
        node.appendChild(el('div', 'g-meta', 'кам: ' + cams.length));
    }
    return node;
}

/* Нода камеры: привязка линкой ко входу позиции (или мимо — свободна),
 * × — снять привязку, а у свободной — вернуть на стену; клик — пороги */
function renderCamNode(camId, at) {
    const dev = invCam(camId);
    if (!dev) { return el('div', 'gnode'); }
    const key = 'cam:' + camId;
    const owner = camOwner(camId);
    const node = gnodeFrame('cam-node g-cam'
        + (owner < 0 ? ' free' : ''), key, at, '');
    node.dataset.cam = camId;
    if (owner >= 0) { node.dataset.pos = String(owner); }
    const head = node.querySelector('.node-head');
    const cin = gsock('sock-in', null, 'cam', null);
    cin.dataset.cam = camId;
    head.insertBefore(cin, head.firstChild);
    const del = node.querySelector('.pos-del');
    del.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if (owner >= 0) {
            const pos = belt.positions[owner];
            const j = pos.inspection.cameras.indexOf(camId);
            pos.inspection.cameras.splice(j, 1);
            toast(camName(camId) + ' — снята с П' + owner + '.');
            render();
        } else {
            delete belt.places[key];
            toast(camName(camId) + ' — возвращена на стену.');
            render();
        }
    });
    const chip = el('span', 'chip');
    chip.dataset.cam = camId;
    chip.appendChild(el('span', 'chip-name', camName(camId)));
    if (dev.rules.length) {
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
        if (openThrCam === camId) {
            node.classList.add('chip-open');
            chip.classList.add('chip-open');
        }
        chip.addEventListener('click', function (ev) {
            ev.stopPropagation();
            openThrCam = openThrCam === camId ? null : camId;
            render();
        });
    }
    chip.addEventListener('dblclick', function (ev) {
        ev.stopPropagation();
        renameCamera(camId);
    });
    const body = el('div', 'node-body');
    body.appendChild(chip);
    node.appendChild(body);
    head.insertBefore(el('span', 'g-title'), head.children[1]);
    node.querySelector('.g-title').textContent = 'камера';
    node.appendChild(gsock('sock-out', 'camera:' + camId, null));
    if (openThrCam === camId && dev.rules.length) {
        node.appendChild(renderThrPop(dev));
    }
    return node;
}

function fmtThr(v) {
    const n = typeof v === 'number' && isFinite(v) ? v : THR_DEFAULT;
    return Math.max(0, Math.min(1, n)).toFixed(2);
}

/* Нода-карточка: на камеру — блок каждого правила, шапка в цвете
 * правила, тело — фиксированный набор порогов (число на каждый) */
function renderThrPop(dev) {
    const pop = el('div', 'thr-node');
    pop.addEventListener('click', function (ev) { ev.stopPropagation(); });
    dev.rules.forEach(function (rid) {
        const rule = RULES.find(function (r) { return r.id === rid; });
        if (!rule) { return; }
        if (!dev.thr) { dev.thr = Object.create(null); }
        if (!dev.thr[rid]) {
            dev.thr[rid] = rule.thr.map(function () { return THR_DEFAULT; });
        }
        const arr = dev.thr[rid];
        const blk = el('div', 'thr-blk');
        const head = el('div', 'thr-head');
        head.style.background = rule.color;
        head.appendChild(el('b', '', rule.name));
        head.appendChild(el('span', 'thr-cams',
            'кам: ' + ruleOnCameras(rule).length));
        blk.appendChild(head);
        rule.thr.forEach(function (pname, k) {
            const row = el('div', 'thr-row');
            row.appendChild(el('span', 'thr-name', pname));
            row.appendChild(el('span', 'thr-gt', '≥'));
            const inp = el('input', 'thr-input');
            inp.type = 'text';
            inp.value = fmtThr(arr[k]);
            inp.addEventListener('input', function () {
                const v = parseFloat(inp.value.replace(',', '.'));
                if (!isFinite(v)) { return; }
                arr[k] = Math.max(0, Math.min(1, v));
            });
            inp.addEventListener('change', function () {
                inp.value = fmtThr(arr[k]);
                render();
            });
            row.appendChild(inp);
            blk.appendChild(row);
        });
        pop.appendChild(blk);
    });
    return pop;
}

/* ─── Связи-провода (Blender-style) ──────────────────────────────
 * mousedown по .sock-out — тянется bezier-линка; приёмник — .sock с
 * data-drop. Совпадение вида (model→rule, rule→cam, camera→pos).
 * Постоянные провода пересчитываются на каждый render/scroll/пан. */

const LINK_WANT = { rule: 'cam', model: 'rule', camera: 'pos',
    posline: 'poslink' };
let linkDrag = null;
let wiresScheduled = false;

function sockXY(node) {
    if (!node) { return null; }
    const r = node.getBoundingClientRect();
    if (!r.width) { return null; }
    const out = node.classList.contains('sock-out');
    return [r.left + (out ? r.width + 4 : -4), r.top + r.height / 2];
}

function bez(a, b) {
    const dx = Math.max(28, Math.abs(b[0] - a[0]) / 2);
    return 'M' + a[0].toFixed(1) + ' ' + a[1].toFixed(1)
        + 'C' + (a[0] + dx).toFixed(1) + ' ' + a[1].toFixed(1)
        + ',' + (b[0] - dx).toFixed(1) + ' ' + b[1].toFixed(1)
        + ',' + b[0].toFixed(1) + ' ' + b[1].toFixed(1);
}

function svgPath(d, cls, color) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', d);
    p.setAttribute('class', cls);
    if (color) { p.style.stroke = color; }
    return p;
}

function scheduleWires() {
    if (wiresScheduled) { return; }
    wiresScheduled = true;
    const run = function () { wiresScheduled = false; renderWires(); };
    (window.requestAnimationFrame || function (f) { f(); })(run);
}

/* Стена камер — только источник плиток: связи живут на холсте */

function renderWires() {
    const svg = $('wires');
    if (!svg) { return; }
    svg.textContent = '';
    const q = function (sel) { return document.querySelector(sel); };
    function link(from, to, color, cls) {
        const a = sockXY(from);
        const b = sockXY(to);
        if (a && b) {
            svg.appendChild(svgPath(bez(a, b), cls || 'wire', color));
        }
    }
    RULES.forEach(function (rule) {
        const to = q('.sock[data-drop="rule"][data-rid="' + rule.id + '"]');
        rule.models.forEach(function (mid) {
            link(q('.sock[data-link="model:' + mid + '"]'), to);
        });
    });
    inventory.forEach(function (dev) {
        dev.rules.forEach(function (rid) {
            const rule = RULES.find(function (r) { return r.id === rid; });
            link(q('.sock[data-link="rule:' + rid + '"]'),
                q('.sock[data-drop="cam"][data-cam="' + dev.id + '"]'),
                rule ? rule.color : null);
        });
    });
    belt.positions.forEach(function (pos, i) {
        if (!pos.inspection) { return; }
        pos.inspection.cameras.forEach(function (cid) {
            link(q('.cam-node[data-cam="' + cid + '"] .sock[data-link="camera:'
                + cid + '"]'),
                q('.pos-card[data-index="' + i + '"] .sock-node'));
        });
    });
    belt.positions.forEach(function (pos, i) {
        if (!pos.nextUid) { return; }
        const tgt = findPosByUid(pos.nextUid);
        if (!tgt) { return; }
        link(q('.pos-card[data-index="' + i + '"] .sock-line-out'),
            q('.pos-card[data-index="' + belt.positions.indexOf(tgt)
                + '"] .sock-line-in'), null, 'wire wire-chain');
    });
    if (linkDrag) {
        const a = sockXY(linkDrag.from);
        if (a) {
            svg.appendChild(svgPath(bez(a, [linkDrag.x, linkDrag.y]),
                'wire wire-live' + (linkDrag.hot ? ' wire-ok' : '')));
        }
    }
}

function markTargets(on) {
    const want = LINK_WANT[on ? linkDrag.kind : ''] || '';
    document.querySelectorAll('.sock[data-drop]').forEach(function (n) {
        const own = n.closest ? n.closest('.cam-node') : null;
        const skip = own && linkDrag && own.dataset.cam === linkDrag.id;
        n.classList.toggle('sock-ok',
            on && n.dataset.drop === want && !skip);
    });
}

function commitLink(d, t) {
    if (d.kind === 'model') {
        togglePart(t.dataset.rid || t.dataset.link.split(':')[1], d.id);
    } else if (d.kind === 'rule') {
        toggleRuleOnCam(t.dataset.cam, d.id);
    } else if (d.kind === 'camera') {
        bindCamera(Number(t.dataset.idx), d.id);
    } else if (d.kind === 'posline') {
        linkPos(d.id, t.dataset.uid);
    }
    render();
}

function wireLinkEngine() {
    document.addEventListener('mousedown', function (ev) {
        if (ev.button !== 0) { return; }
        const sock = ev.target.closest ? ev.target.closest('.sock-out') : null;
        if (!sock) { return; }
        const parts = (sock.dataset.link || '').split(':');
        if (!LINK_WANT[parts[0]]) { return; }
        ev.preventDefault();
        ev.stopPropagation();
        linkDrag = { from: sock, kind: parts[0], id: parts[1],
            x: ev.clientX, y: ev.clientY, hot: null };
        document.body.classList.add('linking');
        markTargets(true);
        renderWires();
    });
    window.addEventListener('mousemove', function (ev) {
        if (!linkDrag) { return; }
        linkDrag.x = ev.clientX;
        linkDrag.y = ev.clientY;
        const under = document.elementFromPoint
            ? document.elementFromPoint(ev.clientX, ev.clientY) : null;
        const t = under && under.closest ? under.closest('[data-drop]') : null;
        const ok = t && t.dataset.drop === LINK_WANT[linkDrag.kind];
        if (linkDrag.hot && linkDrag.hot !== (ok ? t : null)) {
            linkDrag.hot.classList.remove('sock-hot');
        }
        linkDrag.hot = ok ? t : null;
        if (linkDrag.hot) { linkDrag.hot.classList.add('sock-hot'); }
        renderWires();
    });
    window.addEventListener('mouseup', function (ev) {
        if (!linkDrag) { return; }
        const d = linkDrag;
        let t = d.hot;
        if (!t && ev.target && ev.target.closest) {
            const cand = ev.target.closest('[data-drop]');
            if (cand && cand.dataset.drop === LINK_WANT[d.kind]) { t = cand; }
        }
        markTargets(false);
        if (linkDrag && linkDrag.hot) { linkDrag.hot.classList.remove('sock-hot'); }
        document.body.classList.remove('linking');
        linkDrag = null;
        if (t) { commitLink(d, t); } else { render(); }
    });
    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && linkDrag) {
            markTargets(false);
            document.body.classList.remove('linking');
            linkDrag = null;
            render();
        }
    });
    window.addEventListener('resize', scheduleWires);
    document.addEventListener('scroll', scheduleWires, true);
    const z = $('belt-zone');
    if (z) {
        ['wheel', 'mousemove', 'dblclick'].forEach(function (t) {
            z.addEventListener(t, scheduleWires);
        });
    }
}

/* ЛКМ за шапку — свободное перемещение любой ноды по холсту */
let movingG = null;

function nodeAt(node) {
    const key = node.dataset.gk || '';
    if (key.indexOf('pos:') === 0) {
        const idx = Number(key.slice(4));
        const pos = belt.positions[idx];
        if (pos) {
            if (!pos.at) { pos.at = layoutSlot(idx); }
            return pos.at;
        }
        return null;
    }
    return belt.places[key] || null;
}

function dragGNodes() {
    document.addEventListener('mousedown', function (ev) {
        if (ev.button !== 0 || linkDrag) { return; }
        const head = ev.target.closest
            ? ev.target.closest('.gnode .node-head') : null;
        if (!head || ev.target.closest('button, .sock')) { return; }
        const node = head.closest('.gnode');
        const p = nodeAt(node);
        if (!p) { return; }
        movingG = { node: node, at: p, x0: ev.clientX,
            y0: ev.clientY, px: p.x, py: p.y };
        ev.preventDefault();
        document.body.classList.add('node-moving');
    });
    window.addEventListener('mousemove', function (ev) {
        if (!movingG) { return; }
        const z = window.BeltView
            ? (window.BeltView.state().z || 1) : 1;
        const row = $('belt-row');
        const tall = movingG.node.classList.contains('g-pos');
        const maxW = Math.max(row ? (row.offsetWidth || 0) : 0, CANVAS_W);
        const maxH = Math.max(row ? (row.offsetHeight || 0) : 0, CANVAS_H);
        const x = clampN(movingG.px + (ev.clientX - movingG.x0) / z,
            2, Math.max(2, maxW - (tall ? 180 : 110)));
        const y = clampN(movingG.py + (ev.clientY - movingG.y0) / z,
            2, Math.max(2, maxH - (tall ? 124 : 30)));
        movingG.at.x = x;
        movingG.at.y = y;
        movingG.node.style.left = Math.round(x) + 'px';
        movingG.node.style.top = Math.round(y) + 'px';
        renderWires();
    });
    window.addEventListener('mouseup', function () {
        if (!movingG) { return; }
        movingG = null;
        document.body.classList.remove('node-moving');
        render();
    });
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
        ev.dataTransfer.dropEffect = 'copy';
        document.querySelectorAll('.drop-target')
            .forEach(function (n) { n.classList.remove('drop-target'); });
        if (dragKind === 'model-part' || dragKind === 'rule'
            || dragKind === 'position') {
            /* свободное размещение: цели — весь холст */
        } else {
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
        document.querySelectorAll('.pos-card.drop-target').forEach(
            function (n) { n.classList.remove('drop-target'); });
    });

    zone.addEventListener('drop', function (ev) {
        if (!dragKind) { return; }
        ev.preventDefault();
        const kind = dragKind;
        const from = dragFrom;
        const cardIdx = cardFromEvent(ev);
        cleanVisuals();
        dragKind = null;
        dragFrom = -1;

        const emptyZone = belt.positions.length === 0;
        if (kind === 'position') {
            insertPosition(canvasPoint(ev, 176, 100));
            return;
        }
        if (kind === 'model-part' || kind === 'rule') {
            placeNode(kind === 'model-part'
                ? 'model:' + dragAsset : 'rule:' + dragAsset, ev);
            dragAsset = null;
            return;
        }
        if (kind === 'camera' && dragCamId) {
            if (cardIdx < 0) {
                placeNode('cam:' + dragCamId, ev);
                dragCamId = null;
                return;
            }
            bindCamera(cardIdx, dragCamId);
            dragCamId = null;
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

    /* цепь больше не «таскается» переносом: свободное размещение нод
     * ЛКМ за шапку делает dragGNodes (позиции — тоже ноды) */
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

function wireThrClose() {
    document.addEventListener('click', function () {
        if (openThrCam !== null) { openThrCam = null; render(); }
    });
    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && openThrCam !== null) {
            openThrCam = null;
            render();
        }
    });
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

/* ─── Изменение высоты сборки ленты вверх до 50% экрана ─────────────── */

function wireAppSplitter() {
    const splitter = $('app-splitter');
    const app = document.querySelector('.app');
    const btnExpand = $('btn-expand-build');
    if (!splitter || !app) { return; }

    const KEY = 'belt_app_height';
    const MIN_H = 196;

    function maxH() {
        return Math.max(MIN_H, Math.floor((window.innerHeight || 800) * 0.5));
    }

    function defaultH() {
        return Math.max(MIN_H, Math.floor((window.innerHeight || 800) * 0.25));
    }

    let currentH = defaultH();

    function setHeight(px, save) {
        const mx = maxH();
        const clamped = clampN(Math.round(px), MIN_H, mx);
        currentH = clamped;
        document.documentElement.style.setProperty('--app-height', clamped + 'px');
        const isNear50 = clamped >= mx - 10;
        app.classList.toggle('expanded-50', isNear50);
        if (btnExpand) {
            btnExpand.title = isNear50
                ? 'Свернуть сборку ленты (до 25%)'
                : 'Развернуть сборку ленты (до 50%)';
        }
        if (save) {
            try { localStorage.setItem(KEY, isNear50 ? '50%' : String(clamped)); } catch (e) {}
        }
        scheduleWires();
        window.dispatchEvent(new Event('resize'));
    }

    function toggle50() {
        const mx = maxH();
        if (currentH >= mx - 20) {
            setHeight(defaultH(), true);
        } else {
            setHeight(mx, true);
        }
    }

    try {
        const saved = localStorage.getItem(KEY);
        if (saved === '50%') {
            setHeight(maxH(), false);
        } else if (saved) {
            const num = Number(saved);
            if (num >= MIN_H) { setHeight(num, false); }
        }
    } catch (e) {}

    if (btnExpand) {
        btnExpand.addEventListener('click', function (ev) {
            ev.stopPropagation();
            toggle50();
        });
    }

    splitter.addEventListener('dblclick', function (ev) {
        ev.preventDefault();
        toggle50();
    });

    splitter.addEventListener('mousedown', function (ev) {
        if (ev.button !== 0) { return; }
        ev.preventDefault();
        document.body.classList.add('resizing-app');

        const startY = ev.clientY;
        const startH = currentH;

        function onMove(me) {
            const delta = startY - me.clientY;  /* движение мыши вверх увеличивает высоту */
            setHeight(startH + delta, false);
        }

        function onUp(ue) {
            document.body.classList.remove('resizing-app');
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
            const finalDelta = startY - ue.clientY;
            setHeight(startH + finalDelta, true);
        }

        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
    });

    window.addEventListener('resize', function () {
        const mx = maxH();
        if (currentH > mx) {
            setHeight(mx, false);
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    wirePalette();
    wireBelt();
    wireSearch();
    wireThrClose();
    wireLinkEngine();
    dragGNodes();
    wireScrollSnap();
    wireAppSplitter();
    render();
});

})();
