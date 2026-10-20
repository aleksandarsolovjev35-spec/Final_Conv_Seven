/* belt_editor/js/builder.js — сборка ленты перетаскиванием элементов.
 * Сверхкомпактная архитектура: свободное размещение, двусторонние связи,
 * сокеты, предотвращение наложений, боковой док правил и моделей. */
'use strict';

(function () {

const MAX_POSITIONS = 64, CAM_NAME_MAX = 24, THR_DEFAULT = 0.5, CANVAS_W = 5000, CANVAS_H = 3000;
let ruleQuery = '', modelQuery = '', nextModelId = 12, nextRuleId = 4, uidSeq = 0;
let dragKind = null, dragFrom = -1, dragCamId = null, dragAsset = null, openThrCam = null, movingG = null;

const MODELS = ['uneven-heights', 'window-sinks', 'omission-long', 'contacts-long',
    'bracket-90', 'flange-low', 'gear-set', 'hinge-side', 'plate-thin', 'roller-mid',
    'shaft-long', 'yoke-drop'].map((name, i) => ({ id: 'm' + i, name }));

const RULES = [
    { id: 'r0', name: 'геометрия', color: '#d9a441', thr: ['площадь', 'перекос', 'высота'], models: [] },
    { id: 'r1', name: 'наличие', color: '#58b79a', thr: ['контраст'], models: [] },
    { id: 'r2', name: 'пропуск', color: '#cf7aa6', thr: ['окно'], models: [] },
    { id: 'r3', name: 'контакты', color: '#a58ad9', thr: ['нажим', 'смещение'], models: [] }
];

const RULE_COLORS = ['#4fa3d1', '#d9a441', '#58b79a', '#cf7aa6', '#a58ad9', '#e06c75', '#98c379',
    '#d19a66', '#61afef', '#c678dd', '#56b6c2', '#e5c07b', '#e27d60', '#85dcba', '#e8a87c'];

const inventory = Array.from({ length: 8 }, (_, i) => ({ id: 'cam' + i, name: 'CAM_' + (i + 1), dev: 'video' + i, rules: [] }));
const invCam = id => inventory.find(c => c.id === id) || null;
const camName = id => (invCam(id) || {}).name || id;
const ruleColor = id => RULES.find(x => x.id === id)?.color || 'var(--text-dim)';
const belt = { positions: [], places: Object.create(null) };
const $ = id => document.getElementById(id);

function toast(text, kind) {
    const box = $('toasts');
    if (!box) return;
    const t = el('div', 'toast' + (kind ? ' toast-' + kind : ''), text);
    box.appendChild(t);
    setTimeout(() => { t.classList.add('toast-out'); setTimeout(() => t.remove(), 300); }, 2800);
}

/* ─── Инварианты ─────────────────────────────────────────────────── */
function applyInvariants() {
    let resetKept = false;
    belt.positions.forEach((pos, i) => {
        if (pos.uid == null) pos.uid = ++uidSeq;
        if (pos.reset && pos.nextUid) pos.nextUid = null;
        if (pos.reset) { if (resetKept) pos.reset = false; resetKept = true; }
        if (i === 0) { if (!pos.inspection) pos.inspection = { cameras: [], primary: true }; else pos.inspection.primary = true; }
        else if (pos.inspection) pos.inspection.primary = false;
        if (pos.reset && pos.inspection) pos.reset = false;
    });
}

/* ─── Геометрия холста и предотвращение наложения блоков ─────────── */
const clampN = (v, lo, hi) => v < lo ? lo : (v > hi ? hi : v);

function layoutSlot(i) {
    const row = $('belt-row'), maxW = Math.max(row?.offsetWidth || 0, CANVAS_W), maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);
    return {
        x: clampN(Math.round(maxW / 2) - 260 + i * 206, 2, maxW - 190),
        y: clampN(Math.round(maxH / 2) - 60 + (i % 3) * 40, 2, maxH - 124)
    };
}

function getNodeDimensions(keyOrType, domNode) {
    if (domNode?.offsetWidth && domNode?.offsetHeight) return { w: domNode.offsetWidth, h: domNode.offsetHeight };
    const k = String(keyOrType || '');
    if (k.startsWith('pos') || k === 'position') return { w: 176, h: 96 };
    if (k.startsWith('cam')) return { w: 148, h: 54 };
    if (k.startsWith('rule')) return { w: 128, h: 50 };
    if (k.startsWith('model')) return { w: 128, h: 34 };
    return { w: 128, h: 44 };
}

function getCanvasBoxes(excludeKey) {
    const boxes = [], row = $('belt-row');
    belt.positions.forEach((pos, i) => {
        const key = 'pos:' + i;
        if (key === excludeKey) return;
        const at = pos.at || layoutSlot(i), dom = row?.querySelector(`.pos-card[data-index="${i}"]`);
        boxes.push({ key, x: at.x, y: at.y, ...getNodeDimensions('pos', dom) });
    });
    Object.keys(belt.places).forEach(key => {
        if (key === excludeKey || !belt.places[key]) return;
        const at = belt.places[key], dom = row?.querySelector(`.gnode[data-gk="${key}"]`);
        boxes.push({ key, x: at.x, y: at.y, ...getNodeDimensions(key, dom) });
    });
    return boxes;
}

const hasCollision = (x, y, w, h, excludeKey, gap = 4) =>
    getCanvasBoxes(excludeKey).some(b => x < b.x + b.w + gap && x + w + gap > b.x && y < b.y + b.h + gap && y + h + gap > b.y);

/* ─── Действия ───────────────────────────────────────────────────── */
function insertPosition(at) {
    if (belt.positions.length >= MAX_POSITIONS) return toast(`Максимум ${MAX_POSITIONS} позиций на ленте.`, 'err'), false;
    const targetAt = at || layoutSlot(belt.positions.length), dims = getNodeDimensions('pos');
    if (at && hasCollision(targetAt.x, targetAt.y, dims.w, dims.h, null, 4)) return toast('Наложение блоков запрещено.', 'err'), false;
    const wasEmpty = !belt.positions.length;
    belt.positions.push({ label: '', inspection: null, reset: false, uid: ++uidSeq, nextUid: null, at: targetAt });
    applyInvariants(); render();
    toast(wasEmpty ? 'П0 — вход: место инспекции, определяет наличие детали.' : 'Позиция добавлена — соедините её коннекторами.');
    return true;
}

function removePosition(i) {
    const gone = belt.positions[i];
    if (gone) belt.positions.forEach(p => { if (String(p.nextUid) === String(gone.uid)) p.nextUid = null; });
    belt.positions.splice(i, 1);
    const hadReset = belt.positions.some(p => p.reset);
    applyInvariants();
    if (hadReset && !belt.positions.some(p => p.reset) && belt.positions.length > 0) toast('Сброс снят: позиция стала входом — инспекция обязательна.', 'err');
    render();
}

function toggleInspection(i) {
    const pos = belt.positions[i];
    if (!pos) return;
    if (i === 0) return toast('П0 — входное место инспекции, оно не снимается.');
    if (pos.inspection) { pos.inspection = null; toast(`П${i}: инспекция снята.`); }
    else {
        if (pos.reset) return toast(`П${i} — точка сброса: инспекция и сброс на одной позиции невозможны.`, 'err');
        pos.inspection = { cameras: [], primary: false }; toast(`П${i} — место инспекции.`);
    }
    applyInvariants(); render();
}

function toggleReset(i) {
    const pos = belt.positions[i];
    if (!pos) return;
    if (pos.reset) { pos.reset = false; toast(`П${i}: точка сброса снята.`); }
    else {
        if (pos.nextUid) return toast(`У П${i} есть связь дальше по ленте — сначала разорвите её (повторная линка снимает).`, 'err');
        if (pos.inspection && i === 0) return toast('П0 — вход, сбросом быть не может.', 'err');
        if (pos.inspection) return toast(`П${i} — место инспекции: инспекция и сброс на одной позиции невозможны.`, 'err');
        belt.positions.forEach(p => { p.reset = false; });
        pos.nextUid = null; pos.reset = true; toast(`П${i} — точка сброса`);
    }
    applyInvariants(); render();
}

function unbindCamera(camId) {
    let unpinned = false;
    belt.positions.forEach((pos, i) => {
        if (!pos.inspection) return;
        const idx = pos.inspection.cameras.indexOf(camId);
        if (idx >= 0) {
            pos.inspection.cameras.splice(idx, 1);
            toast(`${camName(camId)} — снята с П${i}.`);
            unpinned = true;
        }
    });
    return unpinned;
}

function bindCamera(i, camId) {
    const pos = belt.positions[i];
    if (!pos || !camId) return;
    if (!pos.inspection) return toast(`П${i} — не место инспекции: камеры ставятся только на места инспекции («Место инспекции» из палитры).`);
    const owner = belt.positions.findIndex(p => p.inspection?.cameras.includes(camId));
    if (owner === i) {
        pos.inspection.cameras.splice(pos.inspection.cameras.indexOf(camId), 1);
        toast(`${camName(camId)} — снята с П${i}.`);
        return render();
    }
    if (owner >= 0) {
        belt.positions[owner].inspection.cameras.splice(belt.positions[owner].inspection.cameras.indexOf(camId), 1);
        toast(`${camName(camId)}: П${owner} → П${i}`);
    } else toast(`${camName(camId)} → П${i}`);
    if (!belt.places['cam:' + camId]) belt.places['cam:' + camId] = freePoint();
    pos.inspection.cameras.push(camId);
    applyInvariants(); render();
}

function removeCamera(i, j) {
    const pos = belt.positions[i];
    if (!pos?.inspection) return;
    toast(`${camName(pos.inspection.cameras.splice(j, 1)[0])} — снята с П${i}.`);
    render();
}

const camOwner = camId => belt.positions.findIndex(p => p.inspection?.cameras.includes(camId));

function renameCamera(camId) {
    const chip = $('belt-row')?.querySelector(`.cam-node[data-cam="${camId}"] .chip`), cam = invCam(camId);
    if (!chip || !cam) return;
    startInlineEdit(chip, text => {
        const name = String(text).trim().toUpperCase().replace(/[^A-Z0-9_]/g, '').slice(0, CAM_NAME_MAX);
        if (!/^[A-Z][A-Z0-9_]{1,23}$/.test(name)) return toast('Роль некорректна: буквы/цифры/_ , 2–24, с буквы.', 'err');
        if (inventory.some(o => o !== cam && o.name === name)) return toast(`Роль «${name}» уже занята.`, 'err');
        cam.name = name; render();
    });
}

function renamePosition(i) {
    const label = $('belt-row')?.querySelector(`.pos-card[data-index="${i}"] .pos-label`);
    if (label) startInlineEdit(label, text => { if (belt.positions[i]) belt.positions[i].label = String(text).trim().slice(0, 40); });
}

function startInlineEdit(node, onCommit) {
    node.dataset.editing = '1'; node.setAttribute('contenteditable', 'true'); node.classList.add('editing');
    const range = document.createRange(), sel = window.getSelection();
    range.selectNodeContents(node); sel.removeAllRanges(); sel.addRange(range);
    const finish = commit => {
        if (!node.dataset.editing) return;
        delete node.dataset.editing; node.removeAttribute('contenteditable'); node.classList.remove('editing');
        if (commit) onCommit(node.textContent);
        render();
    };
    node.onkeydown = ev => { if (ev.key === 'Enter') { ev.preventDefault(); finish(true); } if (ev.key === 'Escape') { ev.preventDefault(); finish(false); } };
    node.onblur = () => finish(true);
}

/* ─── Рендер ─────────────────────────────────────────────────────── */
function el(tag, cls, text, children) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    if (children) children.forEach(c => c && node.appendChild(c));
    return node;
}

function render() {
    const row = $('belt-row');
    if (!row) return;
    row.textContent = '';
    belt.positions.forEach((pos, i) => row.appendChild(renderCard(pos, i)));
    Object.keys(belt.places).forEach(key => {
        const [type, id] = key.split(':'), at = belt.places[key];
        if (type === 'cam') row.appendChild(renderCamNode(id, at));
        else if (type === 'rule') row.appendChild(renderRuleNode(id, at));
        else if (type === 'model') row.appendChild(renderModelNode(id, at));
    });
    const meta = $('belt-meta');
    if (meta) meta.textContent = `позиций: ${belt.positions.length} / ${MAX_POSITIONS}`;
    if (window.Cameras) window.Cameras.sync(cameraViews());
    renderAssets(); renderWires();
    $('belt-zone')?.dispatchEvent(new CustomEvent('belt:render'));
}

const ruleOnCameras = rule => inventory.filter(d => d.rules.includes(rule.id));

function togglePart(ruleId, modelId) {
    const rule = RULES.find(r => r.id === ruleId), mod = MODELS.find(m => m.id === modelId);
    if (!rule || !mod) return;
    const at = rule.models.indexOf(modelId);
    if (at >= 0) {
        if (rule.models.length === 1 && ruleOnCameras(rule).length > 0) return toast(`Правило «${rule.name}» стоит на камерах — последнюю модель не снять.`, 'err');
        rule.models.splice(at, 1); toast(`«${mod.name}» убрана из «${rule.name}».`);
    } else { rule.models.push(modelId); toast(`«${rule.name}» ← ${mod.name}.`); }
    render();
}

const findPosByUid = uid => belt.positions.find(p => String(p.uid) === String(uid)) || null;

function linkPos(fromUid, toUid) {
    const from = findPosByUid(fromUid), to = findPosByUid(toUid);
    if (!from || !to) return;
    if (from === to) return toast('Позиция не связывается сама с собой.', 'err');
    if (String(from.nextUid) === String(toUid)) { from.nextUid = null; toast('Связь разорвана.'); return render(); }
    let cur = to, guard = 0;
    while (cur && guard++ <= belt.positions.length) { if (cur === from) return toast('Лента не делает цикл.', 'err'); cur = cur.nextUid ? findPosByUid(cur.nextUid) : null; }
    belt.positions.forEach(pp => { if (String(pp.nextUid) === String(toUid)) pp.nextUid = null; });
    from.nextUid = String(toUid); toast(`П${belt.positions.indexOf(from)} → П${belt.positions.indexOf(to)}`);
    render();
}

function toggleRuleOnCam(camId, ruleId) {
    const dev = inventory.find(d => d.id === camId), rule = RULES.find(r => r.id === ruleId);
    if (!dev || !rule) return;
    const at = dev.rules.indexOf(ruleId);
    if (at >= 0) {
        dev.rules.splice(at, 1); if (dev.thr) delete dev.thr[ruleId]; toast(`${dev.name}: «${rule.name}» снято.`);
    } else {
        if (!rule.models.length) return toast(`Правило «${rule.name}» без моделей — не ставится.`, 'err');
        dev.rules.push(ruleId);
        if (!dev.thr) dev.thr = Object.create(null);
        dev.thr[ruleId] = rule.thr.map(() => THR_DEFAULT);
        toast(`${dev.name}: «${rule.name}» подключено, ${rule.thr.length} порог(а) = ${THR_DEFAULT.toFixed(2)}.`);
    }
    render();
}

const loadedModels = dev => [...new Set(dev.rules.flatMap(id => RULES.find(r => r.id === id)?.models || []))];

function renderAssets() {
    const renderList = (boxId, items, isRule, query, countId, countPrefix) => {
        const box = $(boxId);
        if (!box) return;
        box.textContent = '';
        const list = query ? items.filter(x => x.name.toLowerCase().includes(query)) : items;
        list.forEach(item => {
            const used = isRule ? ruleOnCameras(item).length : RULES.filter(r => r.models.includes(item.id)).length;
            const tile = el('div', (isRule ? 'rule-tile' : 'asset') + (used ? ' asset-used' : ''));
            tile.draggable = true;
            if (isRule) {
                tile.dataset.ruleId = item.id;
                const sw = el('span', 'rule-swatch'); sw.style.background = item.color;
                const nm = el('b', '', item.name); nm.style.color = item.color;
                tile.appendChild(sw); tile.appendChild(nm);
                if (item.models.length) tile.appendChild(el('span', 'rule-parts-count', `${item.models.length}м`));
                if (used) tile.appendChild(el('span', 'asset-use', `кам: ${used}`));
            } else {
                tile.appendChild(el('b', '', item.name));
                if (used) tile.appendChild(el('span', 'asset-use', `правил: ${used}`));
            }
            const wrapper = isRule ? el('div', 'rule-entry', null, [tile]) : tile;
            tile.ondragstart = ev => {
                dragKind = isRule ? 'rule' : 'model-part'; dragAsset = item.id;
                ev.dataTransfer.setData('text/plain', (isRule ? 'rule:' : 'model:') + item.id);
                ev.dataTransfer.effectAllowed = 'copy';
                (isRule ? wrapper : tile).classList.add('dragging');
                setupDragImage(ev, dragKind, item.id);
                $('belt-zone')?.classList.add('drop-ready');
            };
            tile.ondragend = () => { dragKind = dragAsset = null; cleanVisuals(); };
            box.appendChild(wrapper);
        });
        const cnt = $(countId);
        if (cnt) {
            const inUse = isRule ? items.filter(r => ruleOnCameras(r).length > 0).length : items.filter(m => RULES.some(r => r.models.includes(m.id))).length;
            cnt.textContent = `${countPrefix}: ${inUse} / ${items.length}`;
        }
    };
    renderList('asset-models', MODELS, false, modelQuery, 'model-count', 'в правилах');
    renderList('asset-rules', RULES, true, ruleQuery, 'rule-count', 'на камерах');
}

function cameraViews() {
    const bound = Object.create(null);
    belt.positions.forEach((pos, i) => { if (pos.inspection) pos.inspection.cameras.forEach(id => { bound[id] = { position: i, primary: !!pos.inspection.primary }; }); });
    return inventory.map(cam => ({
        id: cam.id, name: cam.name, dev: cam.dev,
        position: bound[cam.id]?.position ?? -1, primary: !!bound[cam.id]?.primary,
        rules: cam.rules.length, ruleColors: cam.rules.map(ruleColor),
        mods: loadedModels(cam).length,
    }));
}

function renderCard(pos, i) {
    if (!pos.at) pos.at = layoutSlot(i);
    const del = el('button', 'pos-del', '×'); del.type = 'button'; del.draggable = false;
    const badges = el('div', 'pos-badges', null, [
        pos.inspection ? el('span', 'badge badge-insp', 'инспекция') : null,
        pos.inspection ? el('span', 'badge badge-cam', pos.inspection.cameras.length ? `камер: ${pos.inspection.cameras.length}` : 'без камер') : null,
        pos.reset ? el('span', 'badge badge-reset', 'сброс') : null
    ]);
    const card = el('div', `pos-card gnode g-pos${pos.inspection ? ' inspect' : ''}${pos.reset ? ' reset-pt' : ''}`, null, [
        el('div', 'node-head', null, [el('span', 'pos-index', 'П' + i), el('span', 'pos-label', pos.label || 'Позиция ' + i), del]),
        gsock('sock-in sock-node', null, 'pos'),
        i > 0 ? gsock('sock-in sock-line-in', null, 'poslink') : null,
        !pos.reset ? gsock('sock-out sock-line-out', 'posline:' + pos.uid) : null,
        el('div', 'node-body', null, [badges])
    ]);
    card.dataset.gk = 'pos:' + i; card.dataset.index = String(i);
    card.style.left = Math.round(pos.at.x) + 'px'; card.style.top = Math.round(pos.at.y) + 'px';
    const sNode = card.querySelector('.sock-node'); if (sNode) sNode.dataset.idx = String(i);
    const sLineIn = card.querySelector('.sock-line-in'); if (sLineIn) sLineIn.dataset.uid = String(pos.uid);
    return card;
}

/* ─── Холст сборки: свободные ноды моделей/правил/камер ──────────── */
function canvasPoint(ev, w, h) {
    const row = $('belt-row'), r = row?.getBoundingClientRect() || { left: 0, top: 0, width: 0, height: 0 };
    const z = window.BeltView?.state().z || 1, maxW = Math.max(row?.offsetWidth || 0, CANVAS_W), maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);
    const x = r.width ? (ev.clientX - r.left) / z - w / 2 : Math.round(maxW / 2 - w / 2);
    const y = r.width ? (ev.clientY - r.top) / z - h / 2 : Math.round(maxH / 2 - h / 2);
    return { x: clampN(x, 2, Math.max(2, maxW - w - 2)), y: clampN(y, 2, Math.max(2, maxH - h - 2)) };
}

function freePoint(forType) {
    const row = $('belt-row'), maxW = Math.max(row?.offsetWidth || 0, CANVAS_W), maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);
    const dims = getNodeDimensions(forType || 'cam');
    let x = Math.round(maxW / 2 - dims.w / 2), y = Math.round(maxH / 2 - 160), attempts = 0;
    while (hasCollision(x, y, dims.w, dims.h, null, 8) && attempts++ < 100) {
        y += dims.h + 16;
        if (y + dims.h > maxH - 20) { y = Math.round(maxH / 2 - 160); x += dims.w + 24; }
    }
    return { x, y };
}

function placeNode(key, ev) {
    const dims = getNodeDimensions(key), pt = canvasPoint(ev, dims.w, dims.h);
    if (hasCollision(pt.x, pt.y, dims.w, dims.h, key, 4)) return toast('Наложение блоков запрещено.', 'err'), false;
    belt.places[key] = pt; toast('Связь — линкой сокета на холсте ленты.'); render(); return true;
}

function gnodeFrame(cls, key, at, title) {
    const del = el('button', 'pos-del', '×'); del.type = 'button'; del.draggable = false;
    const node = el('div', 'gnode ' + cls, null, [el('div', 'node-head', null, [el('span', 'pos-label', title), del])]);
    node.dataset.gk = key; node.style.left = Math.round(at.x) + 'px'; node.style.top = Math.round(at.y) + 'px';
    return node;
}

function gsock(cls, link, drop, rid) {
    const n = el('span', 'sock ' + cls);
    if (link) n.dataset.link = link; if (drop) n.dataset.drop = drop; if (rid) n.dataset.rid = rid;
    return n;
}

function renderModelNode(mid, at) {
    const mod = MODELS.find(m => m.id === mid);
    if (!mod) return el('div', 'gnode');
    const key = 'model:' + mid, node = gnodeFrame('g-model', key, at, mod.name);
    node.dataset.model = mid;
    node.querySelector('.pos-del').onclick = ev => { ev.stopPropagation(); delete belt.places[key]; render(); };
    node.appendChild(gsock('sock-out', key));
    const rules = RULES.filter(r => r.models.includes(mid));
    if (rules.length) node.appendChild(el('div', 'g-meta', `правил: ${rules.length}`));
    return node;
}

function renderRuleNode(rid, at) {
    const rule = RULES.find(r => r.id === rid);
    if (!rule) return el('div', 'gnode');
    const key = 'rule:' + rid, node = gnodeFrame('g-rule', key, at, rule.name);
    node.dataset.rule = rid;
    node.querySelector('.pos-del').onclick = ev => { ev.stopPropagation(); delete belt.places[key]; render(); };
    const head = node.querySelector('.node-head'), sw = el('i', 'g-swatch');
    sw.style.background = rule.color; head.insertBefore(sw, head.firstChild);
    node.querySelector('.pos-label').style.color = rule.color;
    node.appendChild(gsock('sock-in', null, 'rule', rid));
    node.appendChild(gsock('sock-out', key));
    const list = el('div', 'g-models', null, rule.models.map(mid => {
        const mod = MODELS.find(m => m.id === mid), chip = el('span', 'g-chip', mod ? mod.name : mid);
        chip.title = 'снять модель'; chip.onclick = ev => { ev.stopPropagation(); togglePart(rid, mid); };
        return chip;
    }));
    if (!rule.models.length) list.appendChild(el('span', 'g-empty', '→ тяни модель сюда'));
    node.appendChild(list);
    const cams = ruleOnCameras(rule);
    if (cams.length) node.appendChild(el('div', 'g-meta', `кам: ${cams.length}`));
    return node;
}

function renderCamNode(camId, at) {
    const dev = invCam(camId);
    if (!dev) return el('div', 'gnode');
    const key = 'cam:' + camId, owner = camOwner(camId);
    const node = gnodeFrame('cam-node g-cam' + (owner < 0 ? ' free' : ''), key, at, '');
    node.dataset.cam = camId; if (owner >= 0) node.dataset.pos = String(owner);
    const head = node.querySelector('.node-head'), cin = gsock('sock-in', null, 'cam');
    cin.dataset.cam = camId; head.insertBefore(cin, head.firstChild);
    node.querySelector('.pos-del').onclick = ev => {
        ev.stopPropagation();
        if (owner >= 0) {
            belt.positions[owner].inspection.cameras.splice(belt.positions[owner].inspection.cameras.indexOf(camId), 1);
            toast(`${camName(camId)} — снята с П${owner}.`);
        } else { delete belt.places[key]; toast(`${camName(camId)} — возвращена на стену.`); }
        render();
    };
    const chip = el('span', 'chip', null, [el('span', 'chip-name', camName(camId))]);
    chip.dataset.cam = camId;
    if (dev.rules.length) {
        chip.appendChild(el('span', 'chip-assets', `п:${dev.rules.length} · м:${loadedModels(dev).length}`));
        chip.appendChild(el('span', 'rule-tabs', null, dev.rules.map(rid => {
            const t = el('i'); t.style.background = ruleColor(rid); return t;
        })));
        if (openThrCam === camId) node.classList.add('chip-open'), chip.classList.add('chip-open');
        chip.onclick = ev => { ev.stopPropagation(); openThrCam = openThrCam === camId ? null : camId; render(); };
    }
    chip.ondblclick = ev => { ev.stopPropagation(); renameCamera(camId); };
    node.appendChild(el('div', 'node-body', null, [chip]));
    head.insertBefore(el('span', 'g-title', 'камера'), head.children[1]);
    node.appendChild(gsock('sock-out', 'camera:' + camId));
    if (openThrCam === camId && dev.rules.length) node.appendChild(renderThrPop(dev));
    return node;
}

const fmtThr = v => (typeof v === 'number' && isFinite(v) ? Math.max(0, Math.min(1, v)) : THR_DEFAULT).toFixed(2);

function renderThrRuleBlock(dev, rule, rid) {
    if (!dev.thr) dev.thr = Object.create(null);
    if (!dev.thr[rid]) dev.thr[rid] = rule.thr.map(() => THR_DEFAULT);
    const arr = dev.thr[rid], head = el('div', 'thr-head', null, [el('b', '', rule.name), el('span', 'thr-cams', `кам: ${ruleOnCameras(rule).length}`)]);
    head.style.background = rule.color;
    const blk = el('div', 'thr-blk', null, [head]);
    rule.thr.forEach((pname, k) => {
        const inp = el('input', 'thr-input'); inp.type = 'text'; inp.value = fmtThr(arr[k]);
        inp.oninput = () => { const v = parseFloat(inp.value.replace(',', '.')); if (isFinite(v)) arr[k] = Math.max(0, Math.min(1, v)); };
        inp.onchange = () => { inp.value = fmtThr(arr[k]); render(); };
        blk.appendChild(el('div', 'thr-row', null, [el('span', 'thr-name', pname), el('span', 'thr-gt', '≥'), inp]));
    });
    return blk;
}

function renderThrPop(dev) {
    const pop = el('div', 'thr-node');
    pop.onclick = ev => ev.stopPropagation();
    dev.rules.forEach(rid => {
        const rule = RULES.find(r => r.id === rid);
        if (rule) pop.appendChild(renderThrRuleBlock(dev, rule, rid));
    });
    return pop;
}

/* ─── Связи-провода (Blender-style) ────────────────────────────── */
const LINK_WANT = { rule: 'cam', model: 'rule', camera: 'pos', posline: 'poslink' };
const LINK_REV = { cam: 'rule', rule: 'model', pos: 'camera', poslink: 'posline' };
let linkDrag = null, wiresScheduled = false;

function findSnapTarget(x, y, drag) {
    const d = drag || linkDrag;
    if (!d) return null;
    const sel = d.dir === 'out' ? '.sock[data-drop].sock-ok' : '.sock[data-link].sock-ok';
    let best = null, minD = 32;
    document.querySelectorAll(sel).forEach(n => {
        if (n === d.from) return;
        const r = n.getBoundingClientRect();
        if (!r.width && !r.height) return;
        const dist = Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2));
        if (dist < minD) { minD = dist; best = n; }
    });
    return best;
}

function sockXY(node) {
    if (!node) return null;
    const r = node.getBoundingClientRect(), z = $('belt-zone')?.getBoundingClientRect() || { left: 0, top: 0 };
    return (r.width || r.height) ? [r.left - z.left + r.width / 2, r.top - z.top + r.height / 2] : null;
}

function bez(a, b) {
    const z = window.BeltView?.state().z || 1, dx = b[0] - a[0], dy = b[1] - a[1], dist = Math.hypot(dx, dy);
    if (dist < 2) return `M${a[0]} ${a[1]}L${b[0]} ${b[1]}`;
    const h = dx > 0 ? Math.min(dx * 0.5, Math.max(4 * z, dist * 0.35)) : Math.min(50 * z, Math.max(6 * z, dist * 0.35));
    return `M${a[0].toFixed(1)} ${a[1].toFixed(1)}C${(a[0] + h).toFixed(1)} ${a[1].toFixed(1)},${(b[0] - h).toFixed(1)} ${b[1].toFixed(1)},${b[0].toFixed(1)} ${b[1].toFixed(1)}`;
}

function svgPath(d, cls, color) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', d); p.setAttribute('class', cls);
    const z = window.BeltView?.state().z || 1, w = (cls.includes('wire-chain') ? 2.5 : 2.0) * Math.min(1.2, Math.sqrt(z));
    p.style.strokeWidth = Math.max(0.75, w).toFixed(2) + 'px';
    if (color) p.style.stroke = color;
    return p;
}

function scheduleWires() {
    if (wiresScheduled) return;
    wiresScheduled = true;
    (window.requestAnimationFrame || (f => f()))(() => { wiresScheduled = false; renderWires(); });
}

function createWireLink(svg, from, to, color, cls, onRemove) {
    const a = sockXY(from), b = sockXY(to);
    if (!a || !b) return;
    const d = bez(a, b), wire = svgPath(d, cls || 'wire', color);
    svg.appendChild(wire);

    if (onRemove) {
        const hit = svgPath(d, 'wire-hitbox');
        hit.style.cssText = 'stroke:rgba(0,0,0,0.001);stroke-width:16px;pointer-events:stroke;cursor:pointer;';
        hit.setAttribute('title', 'Нажмите, чтобы удалить соединение');
        wire.setAttribute('title', 'Нажмите, чтобы удалить соединение');
        hit.onmouseenter = wire.onmouseenter = () => wire.classList.add('wire-hover-delete');
        hit.onmouseleave = wire.onmouseleave = () => wire.classList.remove('wire-hover-delete');
        hit.onclick = wire.onclick = ev => {
            if (ev.button !== 0 || linkDrag || movingG || document.querySelector('.panning')) return;
            ev.stopPropagation(); onRemove();
        };
        svg.appendChild(hit);
    }
}

function renderModelWires(svg, q) {
    RULES.forEach(r => r.models.forEach(m =>
        createWireLink(svg, q(`.sock[data-link="model:${m}"]`), q(`.sock[data-drop="rule"][data-rid="${r.id}"]`), null, null, () => togglePart(r.id, m))
    ));
}

function renderRuleWires(svg, q) {
    inventory.forEach(dev => dev.rules.forEach(rid => {
        const r = RULES.find(x => x.id === rid);
        createWireLink(svg, q(`.sock[data-link="rule:${rid}"]`), q(`.sock[data-drop="cam"][data-cam="${dev.id}"]`), r?.color, null, () => toggleRuleOnCam(dev.id, rid));
    }));
}

function renderPosWires(svg, q) {
    belt.positions.forEach((pos, i) => {
        if (pos.inspection) {
            pos.inspection.cameras.forEach(cid =>
                createWireLink(svg, q(`.cam-node[data-cam="${cid}"] .sock[data-link="camera:${cid}"]`), q(`.pos-card[data-index="${i}"] .sock-node`), null, null, () => {
                    const idx = pos.inspection.cameras.indexOf(cid);
                    if (idx >= 0) { pos.inspection.cameras.splice(idx, 1); toast(camName(cid) + ' — снята с П' + i + '.'); render(); }
                })
            );
        }
        if (pos.nextUid) {
            const tgt = findPosByUid(pos.nextUid);
            if (tgt) createWireLink(svg, q(`.pos-card[data-index="${i}"] .sock-line-out`), q(`.pos-card[data-index="${belt.positions.indexOf(tgt)}"] .sock-line-in`), null, 'wire wire-chain', () => {
                pos.nextUid = null; toast('Связь разорвана.'); render();
            });
        }
    });
}

function renderLiveWire(svg) {
    if (!linkDrag) return;
    const fromPt = sockXY(linkDrag.from), toPt = linkDrag.snapPt || [linkDrag.x, linkDrag.y];
    if (fromPt && toPt) {
        const [start, end] = linkDrag.dir === 'out' ? [fromPt, toPt] : [toPt, fromPt];
        svg.appendChild(svgPath(bez(start, end), 'wire wire-live' + (linkDrag.hot ? ' wire-ok' : '')));
    }
}

function renderWires() {
    const svg = $('wires');
    if (!svg) return;
    svg.textContent = '';
    const q = sel => document.querySelector(sel);
    renderModelWires(svg, q);
    renderRuleWires(svg, q);
    renderPosWires(svg, q);
    renderLiveWire(svg);
}

function markTargets(on) {
    document.querySelectorAll('.sock-ok, .sock-hot').forEach(n => n.classList.remove('sock-ok', 'sock-hot'));
    if (!linkDrag || !on) return;
    const isOut = linkDrag.dir === 'out', want = isOut ? LINK_WANT[linkDrag.kind] : LINK_REV[linkDrag.kind];
    document.querySelectorAll(isOut ? '.sock[data-drop]' : '.sock[data-link]').forEach(n => {
        if (n.closest?.('.cam-node')?.dataset.cam === linkDrag.id) return;
        const key = isOut ? n.dataset.drop : (n.dataset.link || '').split(':')[0];
        let ok = key === want;
        if (ok && isOut && want === 'pos' && !belt.positions[Number(n.dataset.idx)]?.inspection) ok = false;
        n.classList.toggle('sock-ok', ok);
    });
}

function commitLink(d, t) {
    if (d.kind === 'model') togglePart(t.dataset.rid || t.dataset.link.split(':')[1], d.id);
    else if (d.kind === 'rule') toggleRuleOnCam(t.dataset.cam, d.id);
    else if (d.kind === 'camera') bindCamera(Number(t.dataset.idx), d.id);
    else if (d.kind === 'posline') linkPos(d.id, t.dataset.uid);
    render();
}

function startLinkDrag(sock, isOut, kind, ev) {
    const zr = $('belt-zone')?.getBoundingClientRect() || { left: 0, top: 0 };
    const id = isOut ? sock.dataset.link.split(':')[1] : (sock.dataset.cam || sock.dataset.rid || sock.dataset.uid || sock.dataset.idx);
    linkDrag = { from: sock, dir: isOut ? 'out' : 'in', kind, id, x: ev.clientX - zr.left, y: ev.clientY - zr.top, hot: null, snapPt: null };
    document.body.classList.add('linking');
    markTargets(true);
    renderWires();
}

function moveLinkDrag(ev) {
    if (!linkDrag) return;
    const zr = $('belt-zone')?.getBoundingClientRect() || { left: 0, top: 0 };
    linkDrag.x = ev.clientX - zr.left; linkDrag.y = ev.clientY - zr.top;
    const target = findSnapTarget(ev.clientX, ev.clientY)
        || (document.elementFromPoint ? document.elementFromPoint(ev.clientX, ev.clientY)?.closest(linkDrag.dir === 'out' ? '[data-drop].sock-ok' : '[data-link].sock-ok') : null);
    if (linkDrag.hot && linkDrag.hot !== target) linkDrag.hot.classList.remove('sock-hot');
    linkDrag.hot = target;
    linkDrag.snapPt = target ? (target.classList.add('sock-hot'), sockXY(target)) : null;
    renderWires();
}

function finishLinkDrag(ev) {
    if (!linkDrag) return;
    const d = linkDrag;
    let t = null;
    if (ev.target?.closest) {
        const cand = ev.target.closest(d.dir === 'out' ? '[data-drop]' : '[data-link]');
        if (cand && cand !== d.from) {
            const want = d.dir === 'out' ? LINK_WANT[d.kind] : LINK_REV[d.kind];
            const key = d.dir === 'out' ? cand.dataset.drop : (cand.dataset.link || '').split(':')[0];
            if (key === want && !(d.dir === 'out' && want === 'pos' && !belt.positions[Number(cand.dataset.idx)]?.inspection)) t = cand;
        }
    }
    if (!t) t = d.hot;
    markTargets(false);
    if (d.hot) d.hot.classList.remove('sock-hot');
    document.body.classList.remove('linking');
    linkDrag = null;
    if (t) {
        if (d.dir === 'out') commitLink(d, t);
        else commitLink({ kind: (t.dataset.link || '').split(':')[0], id: (t.dataset.link || '').split(':')[1] }, d.from);
    } else render();
}

function cancelLinkDrag() {
    if (!linkDrag) return;
    markTargets(false);
    if (linkDrag.hot) linkDrag.hot.classList.remove('sock-hot');
    document.body.classList.remove('linking');
    linkDrag = null;
    render();
}

function wireLinkEngine() {
    document.addEventListener('mousedown', ev => {
        if (ev.button !== 0) return;
        const sock = ev.target.closest?.('.sock');
        if (!sock) return;
        const isOut = sock.classList.contains('sock-out'), kind = isOut ? (sock.dataset.link || '').split(':')[0] : sock.dataset.drop;
        if (!LINK_WANT[kind] && !LINK_REV[kind]) return;
        ev.preventDefault(); ev.stopPropagation();
        startLinkDrag(sock, isOut, kind, ev);
    });

    window.addEventListener('mousemove', moveLinkDrag);
    window.addEventListener('mouseup', finishLinkDrag);
    document.addEventListener('keydown', ev => { if (ev.key === 'Escape') cancelLinkDrag(); });

    ['resize', 'scroll', 'transitionend'].forEach(e => (e === 'scroll' ? document : window).addEventListener(e, scheduleWires, true));
    $('belt-zone')?.addEventListener('belt:view', renderWires);
    ['wheel', 'mousemove', 'dblclick'].forEach(t => $('belt-zone')?.addEventListener(t, scheduleWires));
    if (typeof ResizeObserver !== 'undefined' && $('belt-zone')) {
        try { new ResizeObserver(scheduleWires).observe($('belt-zone')); } catch (e) {}
    }
}

function nodeAt(node) {
    const key = node.dataset.gk || '';
    if (key.startsWith('pos:')) {
        const idx = Number(key.slice(4)), pos = belt.positions[idx];
        if (pos) { if (!pos.at) pos.at = layoutSlot(idx); return pos.at; }
        return null;
    }
    return belt.places[key] || null;
}

function startNodeDrag(node, p, ev) {
    const key = node.dataset.gk || '', dims = getNodeDimensions(key, node);
    movingG = { node, key, dims, at: p, x0: ev.clientX, y0: ev.clientY, px: p.x, py: p.y, hasCollided: false };
    ev.preventDefault();
    node.classList.add('node-dragging');
    node.parentNode?.appendChild(node);
    document.body.classList.add('node-moving');
}

function moveNodeDrag(ev) {
    if (!movingG) return;
    const z = window.BeltView?.state().z || 1, row = $('belt-row'), tall = movingG.node.classList.contains('g-pos');
    const maxW = Math.max(row?.offsetWidth || 0, CANVAS_W), maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);
    const x = clampN(movingG.px + (ev.clientX - movingG.x0) / z, 2, Math.max(2, maxW - (tall ? 180 : 110)));
    const y = clampN(movingG.py + (ev.clientY - movingG.y0) / z, 2, Math.max(2, maxH - (tall ? 124 : 30)));
    movingG.at.x = x; movingG.at.y = y;
    movingG.node.style.left = Math.round(x) + 'px'; movingG.node.style.top = Math.round(y) + 'px';
    const coll = hasCollision(x, y, movingG.dims.w, movingG.dims.h, movingG.key, 4);
    movingG.hasCollided = coll;
    movingG.node.classList.toggle('collision-warning', coll);
    renderWires();
}

function finishNodeDrag() {
    if (!movingG) return;
    const target = movingG; movingG = null;
    document.body.classList.remove('node-moving');
    target.node.classList.remove('node-dragging', 'collision-warning');
    if (target.hasCollided) {
        target.at.x = target.px; target.at.y = target.py;
        toast('Наложение блоков запрещено.', 'err'); render();
        const reNode = $('belt-row')?.querySelector('.gnode[data-gk="' + target.key + '"]');
        if (reNode) { reNode.classList.add('collision-shake'); setTimeout(() => reNode.classList.remove('collision-shake'), 350); }
    } else render();
}

function dragGNodes() {
    document.addEventListener('mousedown', ev => {
        if (ev.button !== 0 || linkDrag) return;
        const head = ev.target.closest?.('.gnode .node-head');
        if (!head || ev.target.closest('button, .sock')) return;
        const node = head.closest('.gnode'), p = nodeAt(node);
        if (p) startNodeDrag(node, p, ev);
    });

    window.addEventListener('mousemove', moveNodeDrag);
    window.addEventListener('mouseup', finishNodeDrag);
}

/* ─── Drag & drop ─────────────────────────────────────────────────── */
function buildGhostPreview(kind, id) {
    if (kind === 'position') {
        const i = belt.positions.length;
        return {
            preview: el('div', 'pos-card gnode g-pos ghost-preview', null, [
                el('div', 'node-head', null, [el('span', 'pos-index', 'П' + i), el('span', 'pos-label', 'Позиция ' + i)]),
                el('div', 'node-body', null, [el('div', 'pos-badges', null, [el('span', 'badge badge-insp', i === 0 ? 'вход' : 'позиция')])])
            ]),
            ox: 88, oy: 22
        };
    }
    if (kind === 'rule') {
        const r = RULES.find(x => x.id === id) || { name: id, color: '#c1a66a' }, sw = el('i', 'g-swatch'), lbl = el('span', 'pos-label', r.name);
        sw.style.background = r.color; lbl.style.color = r.color;
        return { preview: el('div', 'gnode g-rule ghost-preview', null, [el('div', 'node-head', null, [sw, lbl])]), ox: 64, oy: 18 };
    }
    if (kind === 'model-part') {
        const m = MODELS.find(x => x.id === id) || { name: id };
        return { preview: el('div', 'gnode g-model ghost-preview', null, [el('div', 'node-head', null, [el('span', 'pos-label', m.name)])]), ox: 64, oy: 16 };
    }
    if (kind === 'camera') {
        const c = invCam(id) || { name: id };
        return { preview: el('div', 'gnode cam-node g-cam ghost-preview free', null, [el('div', 'node-head', null, [el('span', 'pos-label', c.name || id)])]), ox: 74, oy: 18 };
    }
    return null;
}

function setupDragImage(ev, kind, id) {
    if (!ev?.dataTransfer?.setDragImage) return;
    let ghost = $('drag-ghost-native') || el('div', 'drag-ghost-native');
    ghost.id = 'drag-ghost-native';
    if (!ghost.parentNode) document.body.appendChild(ghost);
    ghost.textContent = '';
    const res = buildGhostPreview(kind, id);
    if (res?.preview) {
        ghost.appendChild(res.preview);
        try { ev.dataTransfer.setDragImage(res.preview, res.ox, res.oy); } catch (e) {}
    }
}

function removeCanvasGhost() { $('canvas-drag-ghost')?.remove(); }

window.BeltBridge = {
    syncCameras: () => { if (window.Cameras) window.Cameras.sync(cameraViews()); },
    camDragStart(id, dt, ev) {
        dragKind = 'camera'; dragCamId = dragAsset = id;
        if (dt) { dt.setData('text/plain', 'camera:' + id); dt.effectAllowed = 'copy'; }
        if (ev) setupDragImage(ev, 'camera', id);
        $('belt-zone')?.classList.add('drop-ready');
    },
    camDragEnd() { dragKind = dragCamId = dragAsset = null; cleanVisuals(); },
    addModelFromFile: (fileName, path) => addModelFromFile(fileName, path),
    addRuleFromFile: (fileName, path) => addRuleFromFile(fileName, path),
};

function cleanVisuals() {
    removeCanvasGhost();
    document.querySelectorAll('.drop-target, .collision-warning, .tool.dragging, .asset.dragging, .pos-card.dragging-src, .rule-entry.dragging, .rule-entry.drop-target')
        .forEach(n => n.classList.remove('drop-target', 'collision-warning', 'dragging', 'dragging-src'));
    $('belt-zone')?.classList.remove('drop-ready');
}

const acceptsAt = (kind, idx) => {
    const pos = belt.positions[idx];
    if (!pos || ['position', 'camera', 'rule', 'model-part'].includes(kind)) return false;
    return kind === 'inspect' ? (!pos.reset || !!pos.inspection) : (pos.reset || (idx === belt.positions.length - 1 && !pos.inspection));
};

const cardFromEvent = ev => Number(ev.target?.closest?.('.pos-card')?.dataset.index ?? -1);

function wirePalette() {
    document.querySelectorAll('.tool').forEach(tool => {
        tool.ondragstart = ev => {
            dragKind = tool.dataset.kind; dragFrom = -1;
            ev.dataTransfer.setData('text/plain', dragKind);
            ev.dataTransfer.effectAllowed = 'copy';
            tool.classList.add('dragging');
            if (dragKind === 'position') setupDragImage(ev, 'position', null);
            $('belt-zone')?.classList.add('drop-ready');
        };
        tool.ondragend = () => { dragKind = null; dragFrom = -1; cleanVisuals(); };
    });
}

function handleBeltDragOver(ev, zone) {
    if (!dragKind) return;
    ev.preventDefault();
    document.querySelectorAll('.drop-target, .collision-warning').forEach(n => n.classList.remove('drop-target', 'collision-warning'));
    if (['model-part', 'rule', 'position', 'camera'].includes(dragKind)) {
        const key = dragKind === 'position' ? 'pos' : (dragKind === 'model-part' ? 'model' : (dragKind === 'rule' ? 'rule' : 'cam'));
        const dims = getNodeDimensions(key), pt = canvasPoint(ev, dims.w, dims.h);
        const coll = hasCollision(pt.x, pt.y, dims.w, dims.h, null, 4);
        ev.dataTransfer.dropEffect = coll ? 'none' : 'copy';
        if (coll) ev.target?.closest?.('.gnode')?.classList.add('collision-warning');
    } else {
        const idx = cardFromEvent(ev);
        if (idx >= 0 && acceptsAt(dragKind, idx)) {
            zone.querySelector(`.pos-card[data-index="${idx}"]`)?.classList.add('drop-target');
            ev.dataTransfer.dropEffect = 'copy';
        } else ev.dataTransfer.dropEffect = 'none';
    }
}

function handleBeltDrop(ev) {
    removeCanvasGhost();
    if (!dragKind) return;
    ev.preventDefault();
    const kind = dragKind, cardIdx = cardFromEvent(ev);
    cleanVisuals();
    dragKind = null; dragFrom = -1;

    if (kind === 'position') {
        if (cardIdx >= 0) return toast('Наложение блоков запрещено.', 'err');
        return insertPosition(canvasPoint(ev, 176, 100));
    }
    if (['model-part', 'rule', 'camera'].includes(kind)) {
        if (cardIdx >= 0) { toast('Наложение блоков запрещено.', 'err'); dragAsset = dragCamId = null; return; }
        const id = kind === 'camera' ? (dragCamId || dragAsset) : dragAsset;
        if (id) placeNode((kind === 'model-part' ? 'model:' : (kind === 'rule' ? 'rule:' : 'cam:')) + id, ev);
        dragAsset = dragCamId = null;
        return;
    }
    if (!belt.positions.length) return toast('Нет ни одной позиции.', 'err');
    if (cardIdx < 0) return toast('Не на позицию.', 'err');
    if (kind === 'inspect') return toggleInspection(cardIdx);
    if (kind === 'reset') return toggleReset(cardIdx);
}

function wireBelt() {
    const zone = $('belt-zone');
    zone.ondragenter = ev => { if (dragKind) ev.preventDefault(); };
    zone.ondragover = ev => handleBeltDragOver(ev, zone);
    zone.ondragleave = ev => {
        if (ev.relatedTarget && zone.contains(ev.relatedTarget)) return;
        document.querySelectorAll('.pos-card.drop-target, .collision-warning').forEach(n => n.classList.remove('drop-target', 'collision-warning'));
    };
    zone.ondrop = handleBeltDrop;

    $('belt-row')?.addEventListener('click', ev => {
        if (ev.target.closest('.chip')) return;
        if (ev.target.closest('.pos-del')) {
            const i = cardFromEvent(ev);
            if (i >= 0) { removePosition(i); toast(`Позиция П${i} удалена.`); }
        }
    });

    $('belt-row')?.addEventListener('dblclick', ev => {
        if (ev.target.closest('.chip, .pos-del')) return;
        const i = cardFromEvent(ev);
        if (i >= 0) renamePosition(i);
    });
}

/* ─── Старт ───────────────────────────────────────────────────────── */
function wireScrollSnap() {
    [$('asset-models'), $('asset-rules')].forEach(list => {
        if (!list) return;
        list.addEventListener('wheel', e => {
            if (list.scrollHeight <= list.clientHeight) return;
            e.preventDefault();
            const h = (list.firstElementChild?.offsetHeight || 0) > 0 ? list.firstElementChild.offsetHeight + 6 : 40;
            const d = (e.deltaY > 0 ? 1 : -1) * h;
            if (list.scrollTo) list.scrollTo({ top: list.scrollTop + d, behavior: 'smooth' }); else list.scrollTop += d;
        }, { passive: false });
    });
}

function wireThrClose() {
    const close = () => { if (openThrCam !== null) { openThrCam = null; render(); } };
    document.addEventListener('click', close);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
}

function wireSearch() {
    [['rule-search', v => { ruleQuery = v; }], ['model-search', v => { modelQuery = v; }]].forEach(([id, fn]) => {
        $(id)?.addEventListener('input', e => { fn(e.target.value.trim().toLowerCase()); render(); });
    });
}

/* ─── Правая боковая стенка в стиле Photoshop (меню правил и моделей) ── */
function wireSideDock() {
    const dock = $('side-dock');
    if (!dock) return;
    const KEY_COL = 'belt_side_dock_collapsed', KEY_TAB = 'belt_side_dock_tab';
    let currentTab = 'rules';

    function setTab(tab, save) {
        currentTab = tab === 'models' ? 'models' : 'rules';
        dock.classList.toggle('show-rules', currentTab === 'rules');
        dock.classList.toggle('show-models', currentTab === 'models');
        ['rules', 'models'].forEach(t => {
            const active = currentTab === t, btn = $(`tab-btn-${t}`);
            btn?.classList.toggle('active', active);
            btn?.setAttribute('aria-selected', active ? 'true' : 'false');
            dock.querySelector(`.side-dock-tab[data-panel="${t}"]`)?.classList.toggle('active', active);
        });
        if (save) try { localStorage.setItem(KEY_TAB, currentTab); } catch (e) {}
        renderWires();
    }

    function setCollapsed(col, save) {
        dock.classList.toggle('collapsed', col);
        if (save) try { localStorage.setItem(KEY_COL, col ? '1' : '0'); } catch (e) {}
        window.dispatchEvent(new Event('resize'));
        renderWires();
        (window.requestAnimationFrame || (f => f()))(() => { renderWires(); setTimeout(renderWires, 40); });
    }

    try { if (localStorage.getItem(KEY_COL) === '1') setCollapsed(true, false); } catch (e) {}
    try { setTab(localStorage.getItem(KEY_TAB) === 'models' ? 'models' : 'rules', false); } catch (e) { setTab('rules', false); }

    $('tab-btn-rules')?.addEventListener('click', e => { e.stopPropagation(); setTab('rules', true); $('rule-search')?.focus(); });
    $('tab-btn-models')?.addEventListener('click', e => { e.stopPropagation(); setTab('models', true); $('model-search')?.focus(); });
    ['transitionend', 'transitioncancel'].forEach(evt => dock.addEventListener(evt, () => { renderWires(); window.dispatchEvent(new Event('resize')); }));
    $('btn-side-collapse')?.addEventListener('click', e => { e.stopPropagation(); setCollapsed(true, true); });
    $('btn-side-expand')?.addEventListener('click', e => { e.stopPropagation(); setCollapsed(false, true); });

    $('side-dock-collapsed-bar')?.addEventListener('click', ev => {
        const panel = ev.target?.closest?.('.side-dock-tab')?.dataset.panel;
        if (panel === 'models' || panel === 'rules') {
            setTab(panel, true); setCollapsed(false, true);
            setTimeout(() => $(`${panel === 'models' ? 'model' : 'rule'}-search`)?.focus(), 100);
        } else setCollapsed(false, true);
    });

    window.SideDock = { setTab, setCollapsed, currentTab: () => currentTab };
}

/* ─── Выбор папок с правилами (.py) и весами моделей ───────────────── */
function addModelFromFile(fileName, path) {
    const name = fileName.replace(/\.[^/.]+$/, '').trim();
    if (!name) return null;
    const exist = MODELS.find(m => m.name.toLowerCase() === name.toLowerCase());
    if (exist) return exist;
    const mod = { id: 'm' + (nextModelId++), name, path: path || name };
    MODELS.push(mod); render(); return mod;
}

function addRuleFromFile(fileName, path) {
    const name = fileName.replace(/\.[^/.]+$/, '').replace(/^rule_/, '').replace(/_/g, ' ').trim();
    if (!name) return null;
    const exist = RULES.find(r => r.name.toLowerCase() === name.toLowerCase());
    if (exist) return exist;
    const rule = {
        id: 'r' + (nextRuleId++), name, color: RULE_COLORS[RULES.length % RULE_COLORS.length],
        thr: ['порог'], models: [], path: path || name
    };
    RULES.push(rule); render(); return rule;
}

function wireFolderPickers() {
    const setup = (pathId, btnId, fileId, key, title, defFolder, unit, filter, add) => {
        const pathInp = $(pathId), fileInp = $(fileId);
        try { const s = localStorage.getItem(key); if (s && pathInp) pathInp.value = s; } catch (e) {}
        $(btnId)?.addEventListener('click', e => { e.stopPropagation(); fileInp?.click(); });
        fileInp?.addEventListener('change', function () {
            if (!this.files?.length) return;
            let folder = '', count = 0;
            Array.from(this.files).forEach(f => {
                const rel = f.webkitRelativePath || f.name;
                if (!folder && rel.includes('/')) folder = rel.split('/')[0];
                if (filter(f.name.toLowerCase(), rel) && add(f.name, rel)) count++;
            });
            folder = folder || defFolder;
            if (pathInp) { pathInp.value = folder + '/'; try { localStorage.setItem(key, folder + '/'); } catch (e) {} }
            toast(`${title}: ${folder}${count ? ` (+ ${count} ${unit})` : ''}`);
            render(); this.value = '';
        });
        pathInp?.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                const val = pathInp.value.trim();
                if (val) { try { localStorage.setItem(key, val); } catch (e) {} toast(`${title}: ${val}`); }
            }
        });
    };

    setup('rule-folder-path', 'btn-rule-folder', 'rule-folder-input', 'belt_rule_folder', 'Папка правил', 'папка правил', 'правил',
        n => (n.endsWith('.py') || n.endsWith('.json') || n.endsWith('.rule')) && n !== '__init__.py' && n !== 'base.py', addRuleFromFile);
    setup('model-folder-path', 'btn-model-folder', 'model-folder-input', 'belt_model_folder', 'Папка весов', 'папка весов', 'моделей',
        n => ['.pt', '.onnx', '.engine', '.tflite', '.weights', '.bin'].some(ext => n.endsWith(ext)), addModelFromFile);
}

function boot() {
    wirePalette(); wireBelt(); wireSearch(); wireThrClose(); wireLinkEngine();
    dragGNodes(); wireScrollSnap(); wireSideDock(); wireFolderPickers(); render();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
} else {
    boot();
}

})();
