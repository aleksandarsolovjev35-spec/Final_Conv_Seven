/**
 * @file render.js
 * @description Рендеринг элементов DOM: позиции, ноды холста, каталоги, поповер порогов.
 */

'use strict';

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

/**
 * Отрисовка каталогов моделей и правил в боковой панели
 */
function renderAssets() {
    const renderList = (boxId, items, isRule, query, countId, countPrefix) => {
        const box = $(boxId);
        if (!box) return;
        box.textContent = '';

        const list = query ? items.filter(x => x.name.toLowerCase().includes(query)) : items;

        list.forEach(item => {
            const used = isRule
                ? ruleOnCameras(item).length
                : RULES.filter(r => r.models.includes(item.id)).length;

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

            box.appendChild(wrapper);
        });

        const cnt = $(countId);
        if (cnt) {
            const inUse = isRule
                ? items.filter(r => ruleOnCameras(r).length > 0).length
                : items.filter(m => RULES.some(r => r.models.includes(m.id))).length;
            cnt.textContent = `${countPrefix}: ${inUse} / ${items.length}`;
        }
    };

    renderList('asset-models', MODELS, false, modelQuery, 'model-count', 'в правилах');
    renderList('asset-rules', RULES, true, ruleQuery, 'rule-count', 'на камерах');
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

/**
 * Нода камеры на холсте сборки
 * @param {string} camId ID камеры
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
        if (owner >= 0) {
            belt.positions[owner].inspection.cameras.splice(belt.positions[owner].inspection.cameras.indexOf(camId), 1);
            toast(`${camName(camId)} — снята с П${owner}.`);
        } else {
            delete belt.places[key];
            toast(`${camName(camId)} — возвращена на стену.`);
        }
        render();
    };

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

/**
 * Нода-поповер параметров порогов детекции камеры
 * @param {Object} dev Камера из inventory
 * @returns {HTMLElement}
 */
function renderThrPop(dev) {
    const pop = el('div', 'thr-node');
    pop.onclick = ev => ev.stopPropagation();

    dev.rules.forEach(rid => {
        const rule = RULES.find(r => r.id === rid);
        if (!rule) return;
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

        pop.appendChild(blk);
    });

    return pop;
}
