/**
 * BELT BUILDER — Редактор сборки ленты конвейера
 * Модульная структура: State, Geometry, Actions, Render, Wires, DnD, Dock, Init
 */
(() => {
'use strict';


/* ─── МОДУЛЬ: state.js ─── */
/**
 * @file state.js
 * @description Центральное состояние редактора ленты, константы и базовые структуры данных.
 */


const MAX_POSITIONS = 64;
const CAM_NAME_MAX = 24;
const THR_DEFAULT = 0.5;
const CANVAS_W = 5000;
const CANVAS_H = 3000;

let ruleQuery = '';
let modelQuery = '';
let nextModelId = 12;
let nextRuleId = 4;
let uidSeq = 0;

let dragKind = null;
let dragFrom = -1;
let dragCamId = null;
let dragAsset = null;
let openThrCam = null;
let movingG = null;

/** Список доступных моделей машинного зрения */
const MODELS = [
    'uneven-heights', 'window-sinks', 'omission-long', 'contacts-long',
    'bracket-90', 'flange-low', 'gear-set', 'hinge-side',
    'plate-thin', 'roller-mid', 'shaft-long', 'yoke-drop'
].map((name, i) => ({ id: 'm' + i, name }));

/** Список детекционных правил и инспекций */
const RULES = [
    { id: 'r0', name: 'геометрия', color: '#d9a441', thr: ['площадь', 'перекос', 'высота'], models: [] },
    { id: 'r1', name: 'наличие', color: '#58b79a', thr: ['контраст'], models: [] },
    { id: 'r2', name: 'пропуск', color: '#cf7aa6', thr: ['окно'], models: [] },
    { id: 'r3', name: 'контакты', color: '#a58ad9', thr: ['нажим', 'смещение'], models: [] }
];

/** Цветовая палитра правил */
const RULE_COLORS = [
    '#4fa3d1', '#d9a441', '#58b79a', '#cf7aa6', '#a58ad9', '#e06c75', '#98c379',
    '#d19a66', '#61afef', '#c678dd', '#56b6c2', '#e5c07b', '#e27d60', '#85dcba', '#e8a87c'
];

/** Список обнаруженных камер захвата */
const inventory = Array.from({ length: 8 }, (_, i) => ({
    id: 'cam' + i,
    name: 'CAM_' + (i + 1),
    dev: 'video' + i,
    rules: []
}));

/** Состояние позиций и свободных нод на холсте */
const belt = {
    positions: [],
    places: Object.create(null)
};

/** Быстрый доступ к DOM-элементу по ID */
const $ = id => document.getElementById(id);

/** Поиск камеры в инвентаре по ID */
const invCam = id => inventory.find(c => c.id === id) || null;

/** Получение имени камеры по ID */
const camName = id => (invCam(id) || {}).name || id;

/** Получение акцентного цвета правила по ID */
const ruleColor = id => RULES.find(x => x.id === id)?.color || 'var(--text-dim)';

/**
 * Всплывающее уведомление пользователю
 * @param {string} text Текст сообщения
 * @param {string} [kind] Тип ('err' для ошибок)
 */
function toast(text, kind) {
    const box = $('toasts');
    if (!box) return;
    const t = el('div', 'toast' + (kind ? ' toast-' + kind : ''), text);
    box.appendChild(t);
    setTimeout(() => {
        t.classList.add('toast-out');
        setTimeout(() => t.remove(), 300);
    }, 2800);
}

/**
 * Проверка и соблюдение инвариантов цепи позиций ленты
 */
function applyInvariants() {
    let resetKept = false;
    belt.positions.forEach((pos, i) => {
        if (pos.uid == null) pos.uid = ++uidSeq;
        if (pos.reset && pos.nextUid) pos.nextUid = null;
        if (pos.reset) {
            if (resetKept) pos.reset = false;
            resetKept = true;
        }
        if (i === 0) {
            if (!pos.inspection) pos.inspection = { cameras: [], primary: true };
            else pos.inspection.primary = true;
        } else if (pos.inspection) {
            pos.inspection.primary = false;
        }
        if (pos.reset && pos.inspection) {
            pos.reset = false;
        }
    });
}


/* ─── МОДУЛЬ: geometry.js ─── */
/**
 * @file geometry.js
 * @description Геометрия холста, позиционирование узлов и предотвращение наложений (коллизий).
 */


/** Ограничение числового диапазона [lo, hi] */
const clampN = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/**
 * Расчет стартовой резервной координаты для позиции ленты
 * @param {number} i Индекс позиции
 * @returns {{x: number, y: number}}
 */
function layoutSlot(i) {
    const row = $('belt-row');
    const maxW = Math.max(row?.offsetWidth || 0, CANVAS_W);
    const maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);
    return {
        x: clampN(Math.round(maxW / 2) - 260 + i * 206, 2, maxW - 190),
        y: clampN(Math.round(maxH / 2) - 60 + (i % 3) * 40, 2, maxH - 124)
    };
}

/**
 * Определение физических габаритов ноды по типу или DOM-элементу
 * @param {string} keyOrType Ключ или тип ноды
 * @param {HTMLElement} [domNode] Опциональный DOM-элемент
 * @returns {{w: number, h: number}}
 */
function getNodeDimensions(keyOrType, domNode) {
    if (domNode?.offsetWidth && domNode?.offsetHeight) {
        return { w: domNode.offsetWidth, h: domNode.offsetHeight };
    }
    const k = String(keyOrType || '');
    if (k.startsWith('pos') || k === 'position') return { w: 176, h: 96 };
    if (k.startsWith('cam')) return { w: 148, h: 54 };
    if (k.startsWith('rule')) return { w: 128, h: 50 };
    if (k.startsWith('model')) return { w: 128, h: 34 };
    return { w: 128, h: 44 };
}

/**
 * Сбор всех активных ограничивающих прямоугольников (AABB) на холсте
 * @param {string} [excludeKey] Исключаемый из расчета ключ
 * @returns {Array<{key: string, x: number, y: number, w: number, h: number}>}
 */
function getCanvasBoxes(excludeKey) {
    const boxes = [];
    const row = $('belt-row');

    belt.positions.forEach((pos, i) => {
        const key = 'pos:' + i;
        if (key === excludeKey) return;
        const at = pos.at || layoutSlot(i);
        const dom = row?.querySelector(`.pos-card[data-index="${i}"]`);
        boxes.push({ key, x: at.x, y: at.y, ...getNodeDimensions('pos', dom) });
    });

    Object.keys(belt.places).forEach(key => {
        if (key === excludeKey || !belt.places[key]) return;
        const at = belt.places[key];
        const dom = row?.querySelector(`.gnode[data-gk="${key}"]`);
        boxes.push({ key, x: at.x, y: at.y, ...getNodeDimensions(key, dom) });
    });

    return boxes;
}

/**
 * Проверка наличия коллизии (пересечения) прямоугольника с существующими блоками
 * @param {number} x
 * @param {number} y
 * @param {number} w
 * @param {number} h
 * @param {string} [excludeKey]
 * @param {number} [gap]
 * @returns {boolean}
 */
function hasCollision(x, y, w, h, excludeKey, gap = 4) {
    return getCanvasBoxes(excludeKey).some(b =>
        x < b.x + b.w + gap &&
        x + w + gap > b.x &&
        y < b.y + b.h + gap &&
        y + h + gap > b.y
    );
}

/**
 * Преобразование координат курсора события в координаты плоскости холста сборки
 * @param {MouseEvent|DragEvent} ev
 * @param {number} w Ширина размещаемого объекта
 * @param {number} h Высота размещаемого объекта
 * @returns {{x: number, y: number}}
 */
function canvasPoint(ev, w, h) {
    const row = $('belt-row');
    const r = row?.getBoundingClientRect() || { left: 0, top: 0, width: 0, height: 0 };
    const z = window.BeltView?.state().z || 1;
    const maxW = Math.max(row?.offsetWidth || 0, CANVAS_W);
    const maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);

    const x = r.width ? (ev.clientX - r.left) / z - w / 2 : Math.round(maxW / 2 - w / 2);
    const y = r.width ? (ev.clientY - r.top) / z - h / 2 : Math.round(maxH / 2 - h / 2);

    return {
        x: clampN(x, 2, Math.max(2, maxW - w - 2)),
        y: clampN(y, 2, Math.max(2, maxH - h - 2))
    };
}

/**
 * Поиск свободной точки на холсте без коллизий для автоматического выставления ноды
 * @param {string} [forType] Тип ноды ('cam', 'rule', 'model')
 * @returns {{x: number, y: number}}
 */
function freePoint(forType) {
    const row = $('belt-row');
    const maxW = Math.max(row?.offsetWidth || 0, CANVAS_W);
    const maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);
    const dims = getNodeDimensions(forType || 'cam');

    let x = Math.round(maxW / 2 - dims.w / 2);
    let y = Math.round(maxH / 2 - 160);
    let attempts = 0;

    while (hasCollision(x, y, dims.w, dims.h, null, 8) && attempts++ < 100) {
        y += dims.h + 16;
        if (y + dims.h > maxH - 20) {
            y = Math.round(maxH / 2 - 160);
            x += dims.w + 24;
        }
    }
    return { x, y };
}


/* ─── МОДУЛЬ: actions.js ─── */
/**
 * @file actions.js
 * @description Бизнес-действия ленты: добавление, удаление, привязка камер, редактирование меток.
 */


/**
 * Вставка новой позиции на ленту
 * @param {{x: number, y: number}} [at] Координаты точки размещения
 * @returns {boolean}
 */
function insertPosition(at) {
    if (belt.positions.length >= MAX_POSITIONS) {
        toast(`Максимум ${MAX_POSITIONS} позиций на ленте.`, 'err');
        return false;
    }
    const targetAt = at || layoutSlot(belt.positions.length);
    const dims = getNodeDimensions('pos');
    if (at && hasCollision(targetAt.x, targetAt.y, dims.w, dims.h, null, 4)) {
        toast('Наложение блоков запрещено.', 'err');
        return false;
    }
    const wasEmpty = !belt.positions.length;
    belt.positions.push({
        label: '',
        inspection: null,
        reset: false,
        uid: ++uidSeq,
        nextUid: null,
        at: targetAt
    });
    applyInvariants();
    render();
    toast(wasEmpty ? 'П0 — вход: место инспекции, определяет наличие детали.' : 'Позиция добавлена — соедините её коннекторами.');
    return true;
}

/**
 * Удаление позиции по индексу
 * @param {number} i Индекс удаляемой позиции
 */
function removePosition(i) {
    const gone = belt.positions[i];
    if (gone) {
        belt.positions.forEach(p => {
            if (String(p.nextUid) === String(gone.uid)) p.nextUid = null;
        });
    }
    belt.positions.splice(i, 1);
    const hadReset = belt.positions.some(p => p.reset);
    applyInvariants();
    if (hadReset && !belt.positions.some(p => p.reset) && belt.positions.length > 0) {
        toast('Сброс снят: позиция стала входом — инспекция обязательна.', 'err');
    }
    render();
}

/**
 * Переключение режима инспекции на позиции
 * @param {number} i Индекс позиции
 */
function toggleInspection(i) {
    const pos = belt.positions[i];
    if (!pos) return;
    if (i === 0) return toast('П0 — входное место инспекции, оно не снимается.');
    if (pos.inspection) {
        pos.inspection = null;
        toast(`П${i}: инспекция снята.`);
    } else {
        if (pos.reset) return toast(`П${i} — точка сброса: инспекция и сброс на одной позиции невозможны.`, 'err');
        pos.inspection = { cameras: [], primary: false };
        toast(`П${i} — место инспекции.`);
    }
    applyInvariants();
    render();
}

/**
 * Переключение признака точки сброса
 * @param {number} i Индекс позиции
 */
function toggleReset(i) {
    const pos = belt.positions[i];
    if (!pos) return;
    if (pos.reset) {
        pos.reset = false;
        toast(`П${i}: точка сброса снята.`);
    } else {
        if (pos.nextUid) return toast(`У П${i} есть связь дальше по ленте — сначала разорвите её (повторная линка снимает).`, 'err');
        if (pos.inspection && i === 0) return toast('П0 — вход, сбросом быть не может.', 'err');
        if (pos.inspection) return toast(`П${i} — место инспекции: инспекция и сброс на одной позиции невозможны.`, 'err');
        belt.positions.forEach(p => { p.reset = false; });
        pos.nextUid = null;
        pos.reset = true;
        toast(`П${i} — точка сброса`);
    }
    applyInvariants();
    render();
}

/**
 * Привязка камеры к позиции инспекции
 * @param {number} i Индекс позиции
 * @param {string} camId ID камеры
 */
function bindCamera(i, camId) {
    const pos = belt.positions[i];
    if (!pos || !camId) return;
    if (!pos.inspection) {
        return toast(`П${i} — не место инспекции: камеры ставятся только на места инспекции («Место инспекции» из палитры).`);
    }
    const owner = belt.positions.findIndex(p => p.inspection?.cameras.includes(camId));
    if (owner === i) {
        pos.inspection.cameras.splice(pos.inspection.cameras.indexOf(camId), 1);
        toast(`${camName(camId)} — снята с П${i}.`);
        return render();
    }
    if (owner >= 0) {
        belt.positions[owner].inspection.cameras.splice(belt.positions[owner].inspection.cameras.indexOf(camId), 1);
        toast(`${camName(camId)}: П${owner} → П${i}`);
    } else {
        toast(`${camName(camId)} → П${i}`);
    }
    if (!belt.places['cam:' + camId]) {
        belt.places['cam:' + camId] = freePoint();
    }
    pos.inspection.cameras.push(camId);
    applyInvariants();
    render();
}

/**
 * Снятие камеры с позиции инспекции
 * @param {number} i Индекс позиции
 * @param {string} camId
 */
function unbindCamera(i, camId) {
    const pos = belt.positions[i];
    if (!pos?.inspection) return;
    const idx = pos.inspection.cameras.indexOf(camId);
    if (idx >= 0) {
        pos.inspection.cameras.splice(idx, 1);
        toast(`${camName(camId)} — снята с П${i}.`);
        render();
    }
}

/** Индекс позиции, на которой сейчас размещена камера (или -1) */
const camOwner = camId => belt.positions.findIndex(p => p.inspection?.cameras.includes(camId));

/**
 * Переименование роли камеры
 * @param {string} camId
 */
function renameCamera(camId) {
    const chip = $('belt-row')?.querySelector(`.cam-node[data-cam="${camId}"] .chip`);
    const cam = invCam(camId);
    if (!chip || !cam) return;
    startInlineEdit(chip, text => {
        const name = String(text).trim().toUpperCase().replace(/[^A-Z0-9_]/g, '').slice(0, CAM_NAME_MAX);
        if (!/^[A-Z][A-Z0-9_]{1,23}$/.test(name)) {
            return toast('Роль некорректна: буквы/цифры/_ , 2–24, с буквы.', 'err');
        }
        if (inventory.some(o => o !== cam && o.name === name)) {
            return toast(`Роль «${name}» уже занята.`, 'err');
        }
        cam.name = name;
        render();
    });
}

/**
 * Переименование метки позиции
 * @param {number} i Индекс позиции
 */
function renamePosition(i) {
    const label = $('belt-row')?.querySelector(`.pos-card[data-index="${i}"] .pos-label`);
    if (label) {
        startInlineEdit(label, text => {
            if (belt.positions[i]) belt.positions[i].label = String(text).trim().slice(0, 40);
        });
    }
}

/**
 * Редактирование текста прямо в узле карточки по месту (contenteditable)
 * @param {HTMLElement} node Редактируемый элемент
 * @param {Function} onCommit Callback применения результата
 */
function startInlineEdit(node, onCommit) {
    node.dataset.editing = '1';
    node.setAttribute('contenteditable', 'true');
    node.classList.add('editing');

    const range = document.createRange();
    const sel = window.getSelection();
    range.selectNodeContents(node);
    sel.removeAllRanges();
    sel.addRange(range);

    const finish = commit => {
        if (!node.dataset.editing) return;
        delete node.dataset.editing;
        node.removeAttribute('contenteditable');
        node.classList.remove('editing');
        if (commit) onCommit(node.textContent);
        render();
    };

    node.onkeydown = ev => {
        if (ev.key === 'Enter') { ev.preventDefault(); finish(true); }
        if (ev.key === 'Escape') { ev.preventDefault(); finish(false); }
    };
    node.onblur = () => finish(true);
}

/**
 * Размещение свободной ноды (правило, модель, камера) на холсте сборки ленты
 * @param {string} key Идентификатор ноды ('rule:r1', 'model:m1', 'cam:cam1')
 * @param {DragEvent|MouseEvent} ev Событие для вычисления координат броска
 * @returns {boolean}
 */
function placeNode(key, ev) {
    const dims = getNodeDimensions(key);
    const pt = canvasPoint(ev, dims.w, dims.h);
    if (hasCollision(pt.x, pt.y, dims.w, dims.h, key, 4)) {
        toast('Наложение блоков запрещено.', 'err');
        return false;
    }
    belt.places[key] = pt;
    toast('Связь — линкой сокета на холсте ленты.');
    render();
    return true;
}


/* ─── МОДУЛЬ: render.js ─── */
/**
 * @file render.js
 * @description Рендеринг элементов DOM: позиции, ноды холста, каталоги, поповер порогов.
 */


/**
 * Вспомогательная фабрика для декларативного создания элементов DOM
 * @param {string} tag Имя HTML-тега
 * @param {string} [cls] CSS-классы
 * @param {string} [text] Текстовое содержимое
 * @param {Array<HTMLElement|null>} [children] Дочерние узлы
 * @returns {HTMLElement}
 */
function el(tag, cls, text, children) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    if (children) children.forEach(c => c && node.appendChild(c));
    return node;
}

/**
 * Основной цикл рендеринга редактора ленты
 */
function render() {
    const row = $('belt-row');
    if (!row) return;
    row.textContent = '';

    belt.positions.forEach((pos, i) => row.appendChild(renderCard(pos, i)));

    Object.keys(belt.places).forEach(key => {
        const [type, id] = key.split(':');
        const at = belt.places[key];
        if (type === 'cam') row.appendChild(renderCamNode(id, at));
        else if (type === 'rule') row.appendChild(renderRuleNode(id, at));
        else if (type === 'model') row.appendChild(renderModelNode(id, at));
    });

    const meta = $('belt-meta');
    if (meta) meta.textContent = `позиций: ${belt.positions.length} / ${MAX_POSITIONS}`;

    if (window.Cameras) window.Cameras.sync(cameraViews());
    renderAssets();
    renderWires();
    $('belt-zone')?.dispatchEvent(new CustomEvent('belt:render'));
}

/** Список камер, использующих указанное правило */
const ruleOnCameras = rule => inventory.filter(d => d.rules.includes(rule.id));

/**
 * Привязка или снятие модели с правила
 * @param {string} ruleId
 * @param {string} modelId
 */
function togglePart(ruleId, modelId) {
    const rule = RULES.find(r => r.id === ruleId);
    const mod = MODELS.find(m => m.id === modelId);
    if (!rule || !mod) return;

    const at = rule.models.indexOf(modelId);
    if (at >= 0) {
        if (rule.models.length === 1 && ruleOnCameras(rule).length > 0) {
            return toast(`Правило «${rule.name}» стоит на камерах — последнюю модель не снять.`, 'err');
        }
        rule.models.splice(at, 1);
        toast(`«${mod.name}» убрана из «${rule.name}».`);
    } else {
        rule.models.push(modelId);
        toast(`«${rule.name}» ← ${mod.name}.`);
    }
    render();
}

/** Поиск позиции по ее уникальному сквозному uid */
const findPosByUid = uid => belt.positions.find(p => String(p.uid) === String(uid)) || null;

/**
 * Создание или разрыв связи между двумя позициями ленты
 * @param {number|string} fromUid
 * @param {number|string} toUid
 */
function linkPos(fromUid, toUid) {
    const from = findPosByUid(fromUid);
    const to = findPosByUid(toUid);
    if (!from || !to) return;
    if (from === to) return toast('Позиция не связывается сама с собой.', 'err');

    if (String(from.nextUid) === String(toUid)) {
        from.nextUid = null;
        toast('Связь разорвана.');
        return render();
    }

    let cur = to;
    let guard = 0;
    while (cur && guard++ <= belt.positions.length) {
        if (cur === from) return toast('Лента не делает цикл.', 'err');
        cur = cur.nextUid ? findPosByUid(cur.nextUid) : null;
    }

    belt.positions.forEach(pp => {
        if (String(pp.nextUid) === String(toUid)) pp.nextUid = null;
    });

    from.nextUid = String(toUid);
    toast(`П${belt.positions.indexOf(from)} → П${belt.positions.indexOf(to)}`);
    render();
}

/**
 * Привязка или снятие правила с камеры
 * @param {string} camId
 * @param {string} ruleId
 */
function toggleRuleOnCam(camId, ruleId) {
    const dev = inventory.find(d => d.id === camId);
    const rule = RULES.find(r => r.id === ruleId);
    if (!dev || !rule) return;

    const at = dev.rules.indexOf(ruleId);
    if (at >= 0) {
        dev.rules.splice(at, 1);
        if (dev.thr) delete dev.thr[ruleId];
        toast(`${dev.name}: «${rule.name}» снято.`);
    } else {
        if (!rule.models.length) return toast(`Правило «${rule.name}» без моделей — не ставится.`, 'err');
        dev.rules.push(ruleId);
        if (!dev.thr) dev.thr = Object.create(null);
        dev.thr[ruleId] = rule.thr.map(() => THR_DEFAULT);
        toast(`${dev.name}: «${rule.name}» подключено, ${rule.thr.length} порог(а) = ${THR_DEFAULT.toFixed(2)}.`);
    }
    render();
}

/** Список уникальных ID моделей, загруженных на камеру через правила */
const loadedModels = dev => [...new Set(dev.rules.flatMap(id => RULES.find(r => r.id === id)?.models || []))];

/** Создание плитки ассета для каталога */
function createAssetTile(item, isRule, used) {
    const tile = el('div', (isRule ? 'rule-tile' : 'asset') + (used ? ' asset-used' : ''));
    tile.draggable = true;

    if (isRule) {
        tile.dataset.ruleId = item.id;
        const sw = el('span', 'rule-swatch');
        sw.style.background = item.color;
        const nm = el('b', '', item.name);
        nm.style.color = item.color;
        tile.appendChild(sw);
        tile.appendChild(nm);
        if (item.models.length) tile.appendChild(el('span', 'rule-parts-count', `${item.models.length}м`));
        if (used) tile.appendChild(el('span', 'asset-use', `кам: ${used}`));
    } else {
        tile.appendChild(el('b', '', item.name));
        if (used) tile.appendChild(el('span', 'asset-use', `правил: ${used}`));
    }

    const wrapper = isRule ? el('div', 'rule-entry', null, [tile]) : tile;

    tile.ondragstart = ev => {
        dragKind = isRule ? 'rule' : 'model-part';
        dragAsset = item.id;
        ev.dataTransfer.setData('text/plain', (isRule ? 'rule:' : 'model:') + item.id);
        ev.dataTransfer.effectAllowed = 'copy';
        (isRule ? wrapper : tile).classList.add('dragging');
        setupDragImage(ev, dragKind, item.id);
        $('belt-zone')?.classList.add('drop-ready');
    };

    tile.ondragend = () => {
        dragKind = dragAsset = null;
        cleanVisuals();
    };

    return wrapper;
}

/** Отрисовка списка каталога и обновление счетчиков */
function renderCatalogList(boxId, items, isRule, query, countId, countPrefix) {
    const box = $(boxId);
    if (!box) return;
    box.textContent = '';

    const list = query ? items.filter(x => x.name.toLowerCase().includes(query)) : items;
    list.forEach(item => {
        const used = isRule ? ruleOnCameras(item).length : RULES.filter(r => r.models.includes(item.id)).length;
        box.appendChild(createAssetTile(item, isRule, used));
    });

    const cnt = $(countId);
    if (cnt) {
        const inUse = isRule
            ? items.filter(r => ruleOnCameras(r).length > 0).length
            : items.filter(m => RULES.some(r => r.models.includes(m.id))).length;
        cnt.textContent = `${countPrefix}: ${inUse} / ${items.length}`;
    }
}

/**
 * Отрисовка каталогов моделей и правил в боковой панели
 */
function renderAssets() {
    renderCatalogList('asset-models', MODELS, false, modelQuery, 'model-count', 'в правилах');
    renderCatalogList('asset-rules', RULES, true, ruleQuery, 'rule-count', 'на камерах');
}

/**
 * Подготовка данных состояния камер для видеостены
 * @returns {Array<Object>}
 */
function cameraViews() {
    const bound = Object.create(null);
    belt.positions.forEach((pos, i) => {
        if (!pos.inspection) return;
        pos.inspection.cameras.forEach(id => {
            bound[id] = { position: i, primary: !!pos.inspection.primary };
        });
    });

    return inventory.map(cam => ({
        id: cam.id,
        name: cam.name,
        dev: cam.dev,
        position: bound[cam.id]?.position ?? -1,
        primary: !!bound[cam.id]?.primary,
        rules: cam.rules.length,
        ruleColors: cam.rules.map(ruleColor),
        mods: loadedModels(cam).length,
    }));
}

/**
 * Рендеринг карточки позиции ленты на холсте
 * @param {Object} pos
 * @param {number} i
 * @returns {HTMLElement}
 */
function renderCard(pos, i) {
    if (!pos.at) pos.at = layoutSlot(i);

    const del = el('button', 'pos-del', '×');
    del.type = 'button';
    del.draggable = false;

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

    card.dataset.gk = 'pos:' + i;
    card.dataset.index = String(i);
    card.style.left = Math.round(pos.at.x) + 'px';
    card.style.top = Math.round(pos.at.y) + 'px';

    const sNode = card.querySelector('.sock-node');
    if (sNode) sNode.dataset.idx = String(i);
    const sLineIn = card.querySelector('.sock-line-in');
    if (sLineIn) sLineIn.dataset.uid = String(pos.uid);

    return card;
}

/**
 * Базовая рамка для свободных нод графа на холсте
 * @param {string} cls CSS-класс
 * @param {string} key Ключ в belt.places
 * @param {{x: number, y: number}} at Координаты
 * @param {string} title Заголовок ноды
 * @returns {HTMLElement}
 */
function gnodeFrame(cls, key, at, title) {
    const del = el('button', 'pos-del', '×');
    del.type = 'button';
    del.draggable = false;

    const node = el('div', 'gnode ' + cls, null, [
        el('div', 'node-head', null, [el('span', 'pos-label', title), del])
    ]);
    node.dataset.gk = key;
    node.style.left = Math.round(at.x) + 'px';
    node.style.top = Math.round(at.y) + 'px';
    return node;
}

/**
 * Фабрика элементов сокетов
 * @param {string} cls
 * @param {string} [link]
 * @param {string} [drop]
 * @param {string} [rid]
 * @returns {HTMLElement}
 */
function gsock(cls, link, drop, rid) {
    const n = el('span', 'sock ' + cls);
    if (link) n.dataset.link = link;
    if (drop) n.dataset.drop = drop;
    if (rid) n.dataset.rid = rid;
    return n;
}

/**
 * Нода модели на холсте сборки
 * @param {string} mid ID модели
 * @param {{x: number, y: number}} at
 * @returns {HTMLElement}
 */
function renderModelNode(mid, at) {
    const mod = MODELS.find(m => m.id === mid);
    if (!mod) return el('div', 'gnode');

    const key = 'model:' + mid;
    const node = gnodeFrame('g-model', key, at, mod.name);
    node.dataset.model = mid;
    node.querySelector('.pos-del').onclick = ev => {
        ev.stopPropagation();
        delete belt.places[key];
        render();
    };
    node.appendChild(gsock('sock-out', key));

    const rules = RULES.filter(r => r.models.includes(mid));
    if (rules.length) node.appendChild(el('div', 'g-meta', `правил: ${rules.length}`));
    return node;
}

/**
 * Нода детекционного правила на холсте сборки
 * @param {string} rid ID правила
 * @param {{x: number, y: number}} at
 * @returns {HTMLElement}
 */
function renderRuleNode(rid, at) {
    const rule = RULES.find(r => r.id === rid);
    if (!rule) return el('div', 'gnode');

    const key = 'rule:' + rid;
    const node = gnodeFrame('g-rule', key, at, rule.name);
    node.dataset.rule = rid;
    node.querySelector('.pos-del').onclick = ev => {
        ev.stopPropagation();
        delete belt.places[key];
        render();
    };

    const head = node.querySelector('.node-head');
    const sw = el('i', 'g-swatch');
    sw.style.background = rule.color;
    head.insertBefore(sw, head.firstChild);
    node.querySelector('.pos-label').style.color = rule.color;

    node.appendChild(gsock('sock-in', null, 'rule', rid));
    node.appendChild(gsock('sock-out', key));

    const list = el('div', 'g-models', null, rule.models.map(mid => {
        const mod = MODELS.find(m => m.id === mid);
        const chip = el('span', 'g-chip', mod ? mod.name : mid);
        chip.title = 'снять модель';
        chip.onclick = ev => {
            ev.stopPropagation();
            togglePart(rid, mid);
        };
        return chip;
    }));

    if (!rule.models.length) list.appendChild(el('span', 'g-empty', '→ тяни модель сюда'));
    node.appendChild(list);

    const cams = ruleOnCameras(rule);
    if (cams.length) node.appendChild(el('div', 'g-meta', `кам: ${cams.length}`));
    return node;
}

/** Чип камеры со списком правил и кликом открытия поповера */
function createCamChip(camId, dev, node) {
    const chip = el('span', 'chip', null, [el('span', 'chip-name', camName(camId))]);
    chip.dataset.cam = camId;

    if (dev.rules.length) {
        chip.appendChild(el('span', 'chip-assets', `п:${dev.rules.length} · м:${loadedModels(dev).length}`));
        chip.appendChild(el('span', 'rule-tabs', null, dev.rules.map(rid => {
            const t = el('i');
            t.style.background = ruleColor(rid);
            return t;
        })));
        if (openThrCam === camId) {
            node.classList.add('chip-open');
            chip.classList.add('chip-open');
        }
        chip.onclick = ev => {
            ev.stopPropagation();
            openThrCam = openThrCam === camId ? null : camId;
            render();
        };
    }

    chip.ondblclick = ev => {
        ev.stopPropagation();
        renameCamera(camId);
    };

    return chip;
}

/**
 * Отрисовка ноды камеры на сборке ленты
 * @param {string} camId
 * @param {{x: number, y: number}} at
 * @returns {HTMLElement}
 */
function renderCamNode(camId, at) {
    const dev = invCam(camId);
    if (!dev) return el('div', 'gnode');

    const key = 'cam:' + camId;
    const owner = camOwner(camId);
    const node = gnodeFrame('cam-node g-cam' + (owner < 0 ? ' free' : ''), key, at, '');
    node.dataset.cam = camId;
    if (owner >= 0) node.dataset.pos = String(owner);

    const head = node.querySelector('.node-head');
    const cin = gsock('sock-in', null, 'cam');
    cin.dataset.cam = camId;
    head.insertBefore(cin, head.firstChild);

    node.querySelector('.pos-del').onclick = ev => {
        ev.stopPropagation();
        if (owner >= 0) unbindCamera(owner, camId);
        else {
            delete belt.places[key];
            toast(`${camName(camId)} — возвращена на стену.`);
            render();
        }
    };

    const chip = createCamChip(camId, dev, node);
    node.appendChild(el('div', 'node-body', null, [chip]));
    head.insertBefore(el('span', 'g-title', 'камера'), head.children[1]);
    node.appendChild(gsock('sock-out', 'camera:' + camId));

    if (openThrCam === camId && dev.rules.length) {
        node.appendChild(renderThrPop(dev));
    }
    return node;
}

/** Форматирование числового порога (0.00 – 1.00) */
const fmtThr = v => (typeof v === 'number' && isFinite(v) ? Math.max(0, Math.min(1, v)) : THR_DEFAULT).toFixed(2);

/** Блок порогов одного правила внутри поповера */
function renderThrRuleBlock(dev, rid) {
    const rule = RULES.find(r => r.id === rid);
    if (!rule) return null;
    if (!dev.thr) dev.thr = Object.create(null);
    if (!dev.thr[rid]) dev.thr[rid] = rule.thr.map(() => THR_DEFAULT);

    const arr = dev.thr[rid];
    const head = el('div', 'thr-head', null, [
        el('b', '', rule.name),
        el('span', 'thr-cams', `кам: ${ruleOnCameras(rule).length}`)
    ]);
    head.style.background = rule.color;

    const blk = el('div', 'thr-blk', null, [head]);

    rule.thr.forEach((pname, k) => {
        const inp = el('input', 'thr-input');
        inp.type = 'text';
        inp.value = fmtThr(arr[k]);

        inp.oninput = () => {
            const v = parseFloat(inp.value.replace(',', '.'));
            if (isFinite(v)) arr[k] = Math.max(0, Math.min(1, v));
        };

        inp.onchange = () => {
            inp.value = fmtThr(arr[k]);
            render();
        };

        blk.appendChild(el('div', 'thr-row', null, [
            el('span', 'thr-name', pname),
            el('span', 'thr-gt', '≥'),
            inp
        ]));
    });

    return blk;
}

/**
 * Нода-поповер параметров порогов детекции камеры
 * @param {Object} dev Камера из inventory
 * @returns {HTMLElement}
 */
function renderThrPop(dev) {
    const pop = el('div', 'thr-node');
    pop.onclick = ev => ev.stopPropagation();

    dev.rules.forEach(rid => {
        const blk = renderThrRuleBlock(dev, rid);
        if (blk) pop.appendChild(blk);
    });

    return pop;
}


/* ─── МОДУЛЬ: wires.js ─── */
/**
 * @file wires.js
 * @description Blender-style движок связей: кривые Безье, сокеты, магнитный доводчик, клик удаления.
 */


/** Допустимые прямые направления связей (Out → In) */
const LINK_WANT = {
    rule: 'cam',
    model: 'rule',
    camera: 'pos',
    posline: 'poslink'
};

/** Допустимые обратные направления связей (In → Out) */
const LINK_REV = {
    cam: 'rule',
    rule: 'model',
    pos: 'camera',
    poslink: 'posline'
};

let linkDrag = null;
let wiresScheduled = false;

/**
 * Магнитный поиск ближайшего подходящего сокета в радиусе захвата (32px)
 * @param {number} x
 * @param {number} y
 * @param {Object} [drag]
 * @returns {HTMLElement|null}
 */
function findSnapTarget(x, y, drag) {
    const d = drag || linkDrag;
    if (!d) return null;

    const sel = d.dir === 'out' ? '.sock[data-drop].sock-ok' : '.sock[data-link].sock-ok';
    let best = null;
    let minD = 32;

    document.querySelectorAll(sel).forEach(n => {
        if (n === d.from) return;
        const r = n.getBoundingClientRect();
        if (!r.width && !r.height) return;
        const dist = Math.hypot(x - (r.left + r.width / 2), y - (r.top + r.height / 2));
        if (dist < minD) {
            minD = dist;
            best = n;
        }
    });

    return best;
}

/**
 * Получение экранных координат центра сокета относительно #belt-zone
 * @param {HTMLElement} node
 * @returns {[number, number]|null}
 */
function sockXY(node) {
    if (!node) return null;
    const r = node.getBoundingClientRect();
    const z = $('belt-zone')?.getBoundingClientRect() || { left: 0, top: 0 };
    return (r.width || r.height)
        ? [r.left - z.left + r.width / 2, r.top - z.top + r.height / 2]
        : null;
}

/**
 * Построение плавной кривой Безье между двумя точками без паразитных петель
 * @param {[number, number]} a Начальная точка
 * @param {[number, number]} b Конечная точка
 * @returns {string} SVG path d
 */
function bez(a, b) {
    const z = window.BeltView?.state().z || 1;
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const dist = Math.hypot(dx, dy);

    if (dist < 2) return `M${a[0]} ${a[1]}L${b[0]} ${b[1]}`;

    const h = dx > 0
        ? Math.min(dx * 0.5, Math.max(4 * z, dist * 0.35))
        : Math.min(50 * z, Math.max(6 * z, dist * 0.35));

    return `M${a[0].toFixed(1)} ${a[1].toFixed(1)}C${(a[0] + h).toFixed(1)} ${a[1].toFixed(1)},${(b[0] - h).toFixed(1)} ${b[1].toFixed(1)},${b[0].toFixed(1)} ${b[1].toFixed(1)}`;
}

/**
 * Создание SVG path элемента с динамической шириной обводки
 * @param {string} d
 * @param {string} cls
 * @param {string} [color]
 * @returns {SVGPathElement}
 */
function svgPath(d, cls, color) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', d);
    p.setAttribute('class', cls);
    const z = window.BeltView?.state().z || 1;
    const w = (cls.includes('wire-chain') ? 2.5 : 2.0) * Math.min(1.2, Math.sqrt(z));
    p.style.strokeWidth = Math.max(0.75, w).toFixed(2) + 'px';
    if (color) p.style.stroke = color;
    return p;
}

/**
 * Отложенное обновление связей через requestAnimationFrame
 */
function scheduleWires() {
    if (wiresScheduled) return;
    wiresScheduled = true;
    (window.requestAnimationFrame || (f => f()))(() => {
        wiresScheduled = false;
        renderWires();
    });
}

/**
 * Отрисовка отдельной связи и интерактивного хитбокса удаления
 */
function drawConnection(svg, fromSock, toSock, color, cls, onRemove) {
    const a = sockXY(fromSock);
    const b = sockXY(toSock);
    if (!a || !b) return;

    const d = bez(a, b);
    const wire = svgPath(d, cls || 'wire', color);
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
            ev.stopPropagation();
            onRemove();
        };

        svg.appendChild(hit);
    }
}

/** Отрисовка связей модель → правило */
function renderModelWires(svg) {
    RULES.forEach(r => {
        r.models.forEach(m => {
            drawConnection(
                svg,
                document.querySelector(`.sock[data-link="model:${m}"]`),
                document.querySelector(`.sock[data-drop="rule"][data-rid="${r.id}"]`),
                null,
                null,
                () => togglePart(r.id, m)
            );
        });
    });
}

/** Отрисовка связей правило → камера */
function renderRuleWires(svg) {
    inventory.forEach(dev => {
        dev.rules.forEach(rid => {
            const r = RULES.find(x => x.id === rid);
            drawConnection(
                svg,
                document.querySelector(`.sock[data-link="rule:${rid}"]`),
                document.querySelector(`.sock[data-drop="cam"][data-cam="${dev.id}"]`),
                r?.color,
                null,
                () => toggleRuleOnCam(dev.id, rid)
            );
        });
    });
}

/** Отрисовка связей камера → позиция и позиция → позиция */
function renderPosWires(svg) {
    belt.positions.forEach((pos, i) => {
        if (pos.inspection) {
            pos.inspection.cameras.forEach(cid => {
                drawConnection(
                    svg,
                    document.querySelector(`.cam-node[data-cam="${cid}"] .sock[data-link="camera:${cid}"]`),
                    document.querySelector(`.pos-card[data-index="${i}"] .sock-node`),
                    null,
                    null,
                    () => unbindCamera(i, cid)
                );
            });
        }

        if (pos.nextUid) {
            const tgt = findPosByUid(pos.nextUid);
            if (tgt) {
                drawConnection(
                    svg,
                    document.querySelector(`.pos-card[data-index="${i}"] .sock-line-out`),
                    document.querySelector(`.pos-card[data-index="${belt.positions.indexOf(tgt)}"] .sock-line-in`),
                    null,
                    'wire wire-chain',
                    () => {
                        pos.nextUid = null;
                        toast('Связь разорвана.');
                        render();
                    }
                );
            }
        }
    });
}

/** Отрисовка интерактивного вытягиваемого провода */
function renderLiveWire(svg) {
    if (!linkDrag) return;
    const fromPt = sockXY(linkDrag.from);
    const toPt = linkDrag.snapPt || [linkDrag.x, linkDrag.y];
    if (fromPt && toPt) {
        const [start, end] = linkDrag.dir === 'out' ? [fromPt, toPt] : [toPt, fromPt];
        svg.appendChild(svgPath(bez(start, end), 'wire wire-live' + (linkDrag.hot ? ' wire-ok' : '')));
    }
}

/**
 * Отрисовка всех активных соединений и интерактивных хитбоксов удаления
 */
function renderWires() {
    const svg = $('wires');
    if (!svg) return;
    svg.textContent = '';
    renderModelWires(svg);
    renderRuleWires(svg);
    renderPosWires(svg);
    renderLiveWire(svg);
}

/**
 * Подсветка допустимых сокетов-приемников во время протягивания провода
 * @param {boolean} on
 */
function markTargets(on) {
    document.querySelectorAll('.sock-ok, .sock-hot').forEach(n => n.classList.remove('sock-ok', 'sock-hot'));
    if (!linkDrag || !on) return;

    const isOut = linkDrag.dir === 'out';
    const want = isOut ? LINK_WANT[linkDrag.kind] : LINK_REV[linkDrag.kind];

    document.querySelectorAll(isOut ? '.sock[data-drop]' : '.sock[data-link]').forEach(n => {
        if (n.closest?.('.cam-node')?.dataset.cam === linkDrag.id) return;
        const key = isOut ? n.dataset.drop : (n.dataset.link || '').split(':')[0];
        let ok = key === want;
        if (ok && isOut && want === 'pos' && !belt.positions[Number(n.dataset.idx)]?.inspection) ok = false;
        n.classList.toggle('sock-ok', ok);
    });
}

/**
 * Применение созданной связи
 * @param {Object} d Исходный объект drag
 * @param {HTMLElement} t Целевой сокет
 */
function commitLink(d, t) {
    if (d.kind === 'model') togglePart(t.dataset.rid || t.dataset.link.split(':')[1], d.id);
    else if (d.kind === 'rule') toggleRuleOnCam(t.dataset.cam, d.id);
    else if (d.kind === 'camera') bindCamera(Number(t.dataset.idx), d.id);
    else if (d.kind === 'posline') linkPos(d.id, t.dataset.uid);
    render();
}

/**
 * Инициализация обработчиков мыши и клавиатуры для вытягивания связей
 */
/** Начало вытягивания связи от сокета */
function startLinkDrag(ev) {
    if (ev.button !== 0) return;
    const sock = ev.target.closest?.('.sock');
    if (!sock) return;

    const isOut = sock.classList.contains('sock-out');
    const kind = isOut ? (sock.dataset.link || '').split(':')[0] : sock.dataset.drop;
    if (!LINK_WANT[kind] && !LINK_REV[kind]) return;

    ev.preventDefault();
    ev.stopPropagation();

    const zr = $('belt-zone')?.getBoundingClientRect() || { left: 0, top: 0 };
    const id = isOut
        ? sock.dataset.link.split(':')[1]
        : (sock.dataset.cam || sock.dataset.rid || sock.dataset.uid || sock.dataset.idx);

    linkDrag = {
        from: sock,
        dir: isOut ? 'out' : 'in',
        kind,
        id,
        x: ev.clientX - zr.left,
        y: ev.clientY - zr.top,
        hot: null,
        snapPt: null
    };

    document.body.classList.add('linking');
    markTargets(true);
    renderWires();
}

/** Перемещение курсора при протягивании связи */
function moveLinkDrag(ev) {
    if (!linkDrag) return;

    const zr = $('belt-zone')?.getBoundingClientRect() || { left: 0, top: 0 };
    linkDrag.x = ev.clientX - zr.left;
    linkDrag.y = ev.clientY - zr.top;

    const target = findSnapTarget(ev.clientX, ev.clientY)
        || (document.elementFromPoint
            ? document.elementFromPoint(ev.clientX, ev.clientY)?.closest(linkDrag.dir === 'out' ? '[data-drop].sock-ok' : '[data-link].sock-ok')
            : null);

    if (linkDrag.hot && linkDrag.hot !== target) linkDrag.hot.classList.remove('sock-hot');
    linkDrag.hot = target;
    linkDrag.snapPt = target ? (target.classList.add('sock-hot'), sockXY(target)) : null;

    renderWires();
}

/** Определение целевого сокета для завершения связи */
function resolveLinkTarget(ev, d) {
    if (ev.target?.closest) {
        const cand = ev.target.closest(d.dir === 'out' ? '[data-drop]' : '[data-link]');
        if (cand && cand !== d.from) {
            const want = d.dir === 'out' ? LINK_WANT[d.kind] : LINK_REV[d.kind];
            const key = d.dir === 'out' ? cand.dataset.drop : (cand.dataset.link || '').split(':')[0];
            if (key === want && !(d.dir === 'out' && want === 'pos' && !belt.positions[Number(cand.dataset.idx)]?.inspection)) {
                return cand;
            }
        }
    }
    return d.hot;
}

/** Завершение протягивания связи (отпускание ЛКМ) */
function finishLinkDrag(ev) {
    if (!linkDrag) return;
    const d = linkDrag;
    const t = resolveLinkTarget(ev, d);

    markTargets(false);
    if (d.hot) d.hot.classList.remove('sock-hot');
    document.body.classList.remove('linking');
    linkDrag = null;

    if (t) {
        if (d.dir === 'out') commitLink(d, t);
        else commitLink({ kind: (t.dataset.link || '').split(':')[0], id: (t.dataset.link || '').split(':')[1] }, d.from);
    } else {
        render();
    }
}

/** Отмена протягивания связи (Escape) */
function cancelLinkDrag() {
    if (!linkDrag) return;
    markTargets(false);
    if (linkDrag.hot) linkDrag.hot.classList.remove('sock-hot');
    document.body.classList.remove('linking');
    linkDrag = null;
    render();
}

/** Инициализация обработчиков связывания сокетов */
function wireLinkEngine() {
    document.addEventListener('mousedown', startLinkDrag);
    window.addEventListener('mousemove', moveLinkDrag);
    window.addEventListener('mouseup', finishLinkDrag);
    document.addEventListener('keydown', ev => { if (ev.key === 'Escape') cancelLinkDrag(); });

    ['resize', 'scroll', 'transitionend'].forEach(e =>
        (e === 'scroll' ? document : window).addEventListener(e, scheduleWires, true)
    );
    $('belt-zone')?.addEventListener('belt:view', renderWires);
    ['wheel', 'mousemove', 'dblclick'].forEach(t => $('belt-zone')?.addEventListener(t, scheduleWires));

    if (typeof ResizeObserver !== 'undefined' && $('belt-zone')) {
        try { new ResizeObserver(scheduleWires).observe($('belt-zone')); } catch (e) {}
    }
}


/* ─── МОДУЛЬ: dnd.js ─── */
/**
 * @file dnd.js
 * @description Drag & Drop: захват из палитры/каталогов, свободное перемещение нод по холсту, превью призрака.
 */


/** Построение превью перетаскиваемого объекта */
function buildGhostPreview(kind, id) {
    let preview = null, ox = 64, oy = 18;

    if (kind === 'position') {
        const i = belt.positions.length;
        preview = el('div', 'pos-card gnode g-pos ghost-preview', null, [
            el('div', 'node-head', null, [
                el('span', 'pos-index', 'П' + i),
                el('span', 'pos-label', 'Позиция ' + i)
            ]),
            el('div', 'node-body', null, [
                el('div', 'pos-badges', null, [
                    el('span', 'badge badge-insp', i === 0 ? 'вход' : 'позиция')
                ])
            ])
        ]);
        ox = 88;
        oy = 22;
    } else if (kind === 'rule') {
        const r = RULES.find(x => x.id === id) || { name: id, color: '#c1a66a' };
        const sw = el('i', 'g-swatch');
        sw.style.background = r.color;
        const lbl = el('span', 'pos-label', r.name);
        lbl.style.color = r.color;
        preview = el('div', 'gnode g-rule ghost-preview', null, [
            el('div', 'node-head', null, [sw, lbl])
        ]);
    } else if (kind === 'model-part') {
        const m = MODELS.find(x => x.id === id) || { name: id };
        preview = el('div', 'gnode g-model ghost-preview', null, [
            el('div', 'node-head', null, [el('span', 'pos-label', m.name)])
        ]);
        oy = 16;
    } else if (kind === 'camera') {
        const c = invCam(id) || { name: id };
        preview = el('div', 'gnode cam-node g-cam ghost-preview free', null, [
            el('div', 'node-head', null, [el('span', 'pos-label', c.name || id)])
        ]);
        ox = 74;
    }

    return { preview, ox, oy };
}

/**
 * Подготовка нативного полупрозрачного превью перетаскиваемого объекта
 * @param {DragEvent} ev
 * @param {string} kind
 * @param {string|null} id
 */
function setupDragImage(ev, kind, id) {
    if (!ev?.dataTransfer?.setDragImage) return;

    let ghost = $('drag-ghost-native') || el('div', 'drag-ghost-native');
    ghost.id = 'drag-ghost-native';
    if (!ghost.parentNode) document.body.appendChild(ghost);
    ghost.textContent = '';

    const { preview, ox, oy } = buildGhostPreview(kind, id);
    if (preview) {
        ghost.appendChild(preview);
        try {
            ev.dataTransfer.setDragImage(preview, ox, oy);
        } catch (e) {}
    }
}

/** Удаление временного призрака перетаскивания */
function removeCanvasGhost() {
    $('canvas-drag-ghost')?.remove();
}

/** Внешний мост взаимодействия со стеной камер */
window.BeltBridge = {
    camDragStart(id, dt, ev) {
        dragKind = 'camera';
        dragCamId = dragAsset = id;
        if (dt) {
            dt.setData('text/plain', 'camera:' + id);
            dt.effectAllowed = 'copy';
        }
        if (ev) setupDragImage(ev, 'camera', id);
        $('belt-zone')?.classList.add('drop-ready');
    },
    camDragEnd() {
        dragKind = dragCamId = dragAsset = null;
        cleanVisuals();
    },
    addModelFromFile: (fileName, path) => addModelFromFile(fileName, path),
    addRuleFromFile: (fileName, path) => addRuleFromFile(fileName, path),
};

/** Очистка визуальных эффектов перетаскивания и подсветки целей */
function cleanVisuals() {
    removeCanvasGhost();
    document.querySelectorAll('.drop-target, .collision-warning, .tool.dragging, .asset.dragging, .pos-card.dragging-src, .rule-entry.dragging, .rule-entry.drop-target')
        .forEach(n => n.classList.remove('drop-target', 'collision-warning', 'dragging', 'dragging-src'));
    $('belt-zone')?.classList.remove('drop-ready');
}

/**
 * Проверка возможности приема броска инструментом
 * @param {string} kind
 * @param {number} idx
 * @returns {boolean}
 */
const acceptsAt = (kind, idx) => {
    const pos = belt.positions[idx];
    if (!pos || ['position', 'camera', 'rule', 'model-part'].includes(kind)) return false;
    return kind === 'inspect'
        ? (!pos.reset || !!pos.inspection)
        : (pos.reset || (idx === belt.positions.length - 1 && !pos.inspection));
};

/** Получение индекса позиции из события */
const cardFromEvent = ev => Number(ev.target?.closest?.('.pos-card')?.dataset.index ?? -1);

/**
 * Подключение событий перетаскивания из верхней палитры инструментов
 */
function wirePalette() {
    document.querySelectorAll('.tool').forEach(tool => {
        tool.ondragstart = ev => {
            dragKind = tool.dataset.kind;
            dragFrom = -1;
            ev.dataTransfer.setData('text/plain', dragKind);
            ev.dataTransfer.effectAllowed = 'copy';
            tool.classList.add('dragging');
            if (dragKind === 'position') setupDragImage(ev, 'position', null);
            $('belt-zone')?.classList.add('drop-ready');
        };
        tool.ondragend = () => {
            dragKind = null;
            dragFrom = -1;
            cleanVisuals();
        };
    });
}

/** Обработка наведения при перетаскивании на холст */
function handleBeltDragOver(ev) {
    if (!dragKind) return;
    ev.preventDefault();

    document.querySelectorAll('.drop-target, .collision-warning').forEach(n =>
        n.classList.remove('drop-target', 'collision-warning')
    );

    if (['model-part', 'rule', 'position', 'camera'].includes(dragKind)) {
        const key = dragKind === 'position' ? 'pos' : (dragKind === 'model-part' ? 'model' : (dragKind === 'rule' ? 'rule' : 'cam'));
        const dims = getNodeDimensions(key);
        const pt = canvasPoint(ev, dims.w, dims.h);
        const coll = hasCollision(pt.x, pt.y, dims.w, dims.h, null, 4);

        ev.dataTransfer.dropEffect = coll ? 'none' : 'copy';
        if (coll) ev.target?.closest?.('.gnode')?.classList.add('collision-warning');
    } else {
        const idx = cardFromEvent(ev);
        if (idx >= 0 && acceptsAt(dragKind, idx)) {
            $('belt-zone')?.querySelector(`.pos-card[data-index="${idx}"]`)?.classList.add('drop-target');
            ev.dataTransfer.dropEffect = 'copy';
        } else {
            ev.dataTransfer.dropEffect = 'none';
        }
    }
}

/** Обработка броска элемента на холст */
function handleBeltDrop(ev) {
    removeCanvasGhost();
    if (!dragKind) return;
    ev.preventDefault();

    const kind = dragKind;
    const cardIdx = cardFromEvent(ev);
    cleanVisuals();
    dragKind = null;
    dragFrom = -1;

    if (kind === 'position') {
        if (cardIdx >= 0) return toast('Наложение блоков запрещено.', 'err');
        return insertPosition(canvasPoint(ev, 176, 100));
    }

    if (['model-part', 'rule', 'camera'].includes(kind)) {
        if (cardIdx >= 0) {
            toast('Наложение блоков запрещено.', 'err');
            dragAsset = dragCamId = null;
            return;
        }
        const id = kind === 'camera' ? (dragCamId || dragAsset) : dragAsset;
        if (id) {
            placeNode((kind === 'model-part' ? 'model:' : (kind === 'rule' ? 'rule:' : 'cam:')) + id, ev);
        }
        dragAsset = dragCamId = null;
        return;
    }

    if (!belt.positions.length) return toast('Нет ни одной позиции.', 'err');
    if (cardIdx < 0) return toast('Не на позицию.', 'err');
    if (kind === 'inspect') return toggleInspection(cardIdx);
    if (kind === 'reset') return toggleReset(cardIdx);
}

/**
 * Подключение событий холста для приема бросков элементов
 */
function wireBelt() {
    const zone = $('belt-zone');
    if (!zone) return;

    zone.ondragenter = ev => { if (dragKind) ev.preventDefault(); };
    zone.ondragover = handleBeltDragOver;
    zone.ondragleave = ev => {
        if (ev.relatedTarget && zone.contains(ev.relatedTarget)) return;
        document.querySelectorAll('.pos-card.drop-target, .collision-warning').forEach(n =>
            n.classList.remove('drop-target', 'collision-warning')
        );
    };
    zone.ondrop = handleBeltDrop;

    $('belt-row')?.addEventListener('click', ev => {
        if (ev.target.closest('.chip')) return;
        if (ev.target.closest('.pos-del')) {
            const i = cardFromEvent(ev);
            if (i >= 0) {
                removePosition(i);
                toast(`Позиция П${i} удалена.`);
            }
        }
    });

    $('belt-row')?.addEventListener('dblclick', ev => {
        if (ev.target.closest('.chip, .pos-del')) return;
        const i = cardFromEvent(ev);
        if (i >= 0) renamePosition(i);
    });
}

/**
 * Получение ссылки на координаты ноды
 * @param {HTMLElement} node
 * @returns {{x: number, y: number}|null}
 */
function nodeAt(node) {
    const key = node.dataset.gk || '';
    if (key.startsWith('pos:')) {
        const idx = Number(key.slice(4));
        const pos = belt.positions[idx];
        if (pos) {
            if (!pos.at) pos.at = layoutSlot(idx);
            return pos.at;
        }
        return null;
    }
    return belt.places[key] || null;
}

/** Захват ноды за шапку для перемещения */
function startNodeDrag(ev) {
    if (ev.button !== 0 || linkDrag) return;
    const head = ev.target.closest?.('.gnode .node-head');
    if (!head || ev.target.closest('button, .sock')) return;

    const node = head.closest('.gnode');
    const p = nodeAt(node);
    if (!p) return;

    const key = node.dataset.gk || '';
    const dims = getNodeDimensions(key, node);

    movingG = {
        node,
        key,
        dims,
        at: p,
        x0: ev.clientX,
        y0: ev.clientY,
        px: p.x,
        py: p.y,
        hasCollided: false
    };

    ev.preventDefault();
    node.classList.add('node-dragging');
    node.parentNode?.appendChild(node);
    document.body.classList.add('node-moving');
}

/** Перемещение ноды по холсту курсором */
function moveNodeDrag(ev) {
    if (!movingG) return;

    const z = window.BeltView?.state().z || 1;
    const row = $('belt-row');
    const tall = movingG.node.classList.contains('g-pos');
    const maxW = Math.max(row?.offsetWidth || 0, CANVAS_W);
    const maxH = Math.max(row?.offsetHeight || 0, CANVAS_H);

    const x = clampN(movingG.px + (ev.clientX - movingG.x0) / z, 2, Math.max(2, maxW - (tall ? 180 : 110)));
    const y = clampN(movingG.py + (ev.clientY - movingG.y0) / z, 2, Math.max(2, maxH - (tall ? 124 : 30)));

    movingG.at.x = x;
    movingG.at.y = y;
    movingG.node.style.left = Math.round(x) + 'px';
    movingG.node.style.top = Math.round(y) + 'px';

    const coll = hasCollision(x, y, movingG.dims.w, movingG.dims.h, movingG.key, 4);
    movingG.hasCollided = coll;
    movingG.node.classList.toggle('collision-warning', coll);

    renderWires();
}

/** Завершение перемещения ноды с откатом при коллизии */
function finishNodeDrag() {
    if (!movingG) return;
    const target = movingG;
    movingG = null;

    document.body.classList.remove('node-moving');
    target.node.classList.remove('node-dragging', 'collision-warning');

    if (target.hasCollided) {
        target.at.x = target.px;
        target.at.y = target.py;
        toast('Наложение блоков запрещено.', 'err');
        render();

        const reNode = $('belt-row')?.querySelector('.gnode[data-gk="' + target.key + '"]');
        if (reNode) {
            reNode.classList.add('collision-shake');
            setTimeout(() => reNode.classList.remove('collision-shake'), 350);
        }
    } else {
        render();
    }
}

/**
 * Свободное перемещение нод по холсту за шапку с откатом при коллизиях
 */
function dragGNodes() {
    document.addEventListener('mousedown', startNodeDrag);
    window.addEventListener('mousemove', moveNodeDrag);
    window.addEventListener('mouseup', finishNodeDrag);
}


/* ─── МОДУЛЬ: dock.js ─── */
/**
 * @file dock.js
 * @description Боковая панель (Photoshop dock), вкладки правил и моделей, фильтрация/поиск, выбор локальных папок.
 */


/** Плавный скролл списков каталога колесом мыши */
function wireScrollSnap() {
    [$('asset-models'), $('asset-rules')].forEach(list => {
        if (!list) return;
        list.addEventListener('wheel', e => {
            if (list.scrollHeight <= list.clientHeight) return;
            e.preventDefault();
            const h = (list.firstElementChild?.offsetHeight || 0) > 0 ? list.firstElementChild.offsetHeight + 6 : 40;
            const d = (e.deltaY > 0 ? 1 : -1) * h;
            if (list.scrollTo) {
                list.scrollTo({ top: list.scrollTop + d, behavior: 'smooth' });
            } else {
                list.scrollTop += d;
            }
        }, { passive: false });
    });
}

/** Закрытие всплывающего поповера порогов по клику вовне или Escape */
function wireThrClose() {
    const close = () => {
        if (openThrCam !== null) {
            openThrCam = null;
            render();
        }
    };
    document.addEventListener('click', close);
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') close();
    });
}

/** Фильтрация элементов каталога правил и моделей через строку поиска */
function wireSearch() {
    [
        ['rule-search', v => { ruleQuery = v; }],
        ['model-search', v => { modelQuery = v; }]
    ].forEach(([id, fn]) => {
        $(id)?.addEventListener('input', e => {
            fn(e.target.value.trim().toLowerCase());
            render();
        });
    });
}

/**
 * Правая боковая стенка в стиле Photoshop (вкладки правил и моделей, сворачивание)
 */
/** Навешивание обработчиков событий элементов боковой панели */
function bindDockListeners(dock, setTab, setCollapsed) {
    $('tab-btn-rules')?.addEventListener('click', e => {
        e.stopPropagation();
        setTab('rules', true);
        $('rule-search')?.focus();
    });

    $('tab-btn-models')?.addEventListener('click', e => {
        e.stopPropagation();
        setTab('models', true);
        $('model-search')?.focus();
    });

    ['transitionend', 'transitioncancel'].forEach(evt =>
        dock.addEventListener(evt, () => {
            renderWires();
            window.dispatchEvent(new Event('resize'));
        })
    );

    $('btn-side-collapse')?.addEventListener('click', e => {
        e.stopPropagation();
        setCollapsed(true, true);
    });

    $('btn-side-expand')?.addEventListener('click', e => {
        e.stopPropagation();
        setCollapsed(false, true);
    });

    $('side-dock-collapsed-bar')?.addEventListener('click', ev => {
        const panel = ev.target?.closest?.('.side-dock-tab')?.dataset.panel;
        if (panel === 'models' || panel === 'rules') {
            setTab(panel, true);
            setCollapsed(false, true);
            setTimeout(() => $(`${panel === 'models' ? 'model' : 'rule'}-search`)?.focus(), 100);
        } else {
            setCollapsed(false, true);
        }
    });
}

/**
 * Правая боковая стенка в стиле Photoshop (вкладки правил и моделей, сворачивание)
 */
function wireSideDock() {
    const dock = $('side-dock');
    if (!dock) return;

    const KEY_COL = 'belt_side_dock_collapsed';
    const KEY_TAB = 'belt_side_dock_tab';
    let currentTab = 'rules';

    function setTab(tab, save) {
        currentTab = tab === 'models' ? 'models' : 'rules';
        dock.classList.toggle('show-rules', currentTab === 'rules');
        dock.classList.toggle('show-models', currentTab === 'models');

        ['rules', 'models'].forEach(t => {
            const active = currentTab === t;
            const btn = $(`tab-btn-${t}`);
            btn?.classList.toggle('active', active);
            btn?.setAttribute('aria-selected', active ? 'true' : 'false');
            dock.querySelector(`.side-dock-tab[data-panel="${t}"]`)?.classList.toggle('active', active);
        });

        if (save) {
            try { localStorage.setItem(KEY_TAB, currentTab); } catch (e) {}
        }
        renderWires();
    }

    function setCollapsed(col, save) {
        dock.classList.toggle('collapsed', col);
        if (save) {
            try { localStorage.setItem(KEY_COL, col ? '1' : '0'); } catch (e) {}
        }
        window.dispatchEvent(new Event('resize'));
        renderWires();
        (window.requestAnimationFrame || (f => f()))(() => {
            renderWires();
            setTimeout(renderWires, 40);
        });
    }

    try {
        if (localStorage.getItem(KEY_COL) === '1') setCollapsed(true, false);
    } catch (e) {}

    try {
        setTab(localStorage.getItem(KEY_TAB) === 'models' ? 'models' : 'rules', false);
    } catch (e) {
        setTab('rules', false);
    }

    bindDockListeners(dock, setTab, setCollapsed);
    window.SideDock = { setTab, setCollapsed, currentTab: () => currentTab };
}

/**
 * Регистрация модели нейросети из файла весов
 * @param {string} fileName
 * @param {string} path
 */
function addModelFromFile(fileName, path) {
    const name = fileName.replace(/\.[^/.]+$/, '').trim();
    if (!name) return null;
    const exist = MODELS.find(m => m.name.toLowerCase() === name.toLowerCase());
    if (exist) return exist;
    const mod = { id: 'm' + (nextModelId++), name, path: path || name };
    MODELS.push(mod);
    render();
    return mod;
}

/**
 * Регистрация правила дефектоскопии из файла скрипта/конфига
 * @param {string} fileName
 * @param {string} path
 */
function addRuleFromFile(fileName, path) {
    const name = fileName.replace(/\.[^/.]+$/, '').replace(/^rule_/, '').replace(/_/g, ' ').trim();
    if (!name) return null;
    const exist = RULES.find(r => r.name.toLowerCase() === name.toLowerCase());
    if (exist) return exist;
    const rule = {
        id: 'r' + (nextRuleId++),
        name,
        color: RULE_COLORS[RULES.length % RULE_COLORS.length],
        thr: ['порог'],
        models: [],
        path: path || name
    };
    RULES.push(rule);
    render();
    return rule;
}

/**
 * Настройка инпута выбора локальной папки и импорта файлов
 */
function bindFolderPicker(pathId, btnId, fileId, key, title, defFolder, unit, filter, add) {
    const pathInp = $(pathId);
    const fileInp = $(fileId);

    try {
        const s = localStorage.getItem(key);
        if (s && pathInp) pathInp.value = s;
    } catch (e) {}

    $(btnId)?.addEventListener('click', e => {
        e.stopPropagation();
        fileInp?.click();
    });

    fileInp?.addEventListener('change', function () {
        if (!this.files?.length) return;
        let folder = '';
        let count = 0;

        Array.from(this.files).forEach(f => {
            const rel = f.webkitRelativePath || f.name;
            if (!folder && rel.includes('/')) folder = rel.split('/')[0];
            if (filter(f.name.toLowerCase(), rel) && add(f.name, rel)) count++;
        });

        folder = folder || defFolder;
        if (pathInp) {
            pathInp.value = folder + '/';
            try { localStorage.setItem(key, folder + '/'); } catch (e) {}
        }

        toast(`${title}: ${folder}${count ? ` (+ ${count} ${unit})` : ''}`);
        render();
        this.value = '';
    });

    pathInp?.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            const val = pathInp.value.trim();
            if (val) {
                try { localStorage.setItem(key, val); } catch (e) {}
                toast(`${title}: ${val}`);
            }
        }
    });
}

/**
 * Настройка полей выбора локальных директорий правил и моделей
 */
function wireFolderPickers() {
    bindFolderPicker(
        'rule-folder-path',
        'btn-rule-folder',
        'rule-folder-input',
        'belt_rule_folder',
        'Папка правил',
        'папка правил',
        'правил',
        n => (n.endsWith('.py') || n.endsWith('.json') || n.endsWith('.rule')) && n !== '__init__.py' && n !== 'base.py',
        addRuleFromFile
    );

    bindFolderPicker(
        'model-folder-path',
        'btn-model-folder',
        'model-folder-input',
        'belt_model_folder',
        'Папка весов',
        'папка весов',
        'моделей',
        n => ['.pt', '.onnx', '.engine', '.tflite', '.weights', '.bin'].some(ext => n.endsWith(ext)),
        addModelFromFile
    );
}


/* ─── МОДУЛЬ: init.js ─── */
/**
 * @file init.js
 * @description Точка входа: сборка обработчиков и первичная отрисовка рабочей области редактора ленты.
 */


/**
 * Инициализация всех подсистем редактора
 */
function initBeltEditor() {
    wirePalette();
    wireBelt();
    wireSearch();
    wireThrClose();
    wireLinkEngine();
    dragGNodes();
    wireScrollSnap();
    wireSideDock();
    wireFolderPickers();
    render();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBeltEditor);
} else {
    initBeltEditor();
}


})();
