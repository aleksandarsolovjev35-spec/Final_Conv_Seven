/**
 * @file dnd.js
 * @description Drag & Drop: захват из палитры/каталогов, свободное перемещение нод по холсту, превью призрака.
 */

'use strict';

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

    let preview = null;
    let ox = 64;
    let oy = 18;

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

/**
 * Подключение событий холста для приема бросков элементов
 */
function wireBelt() {
    const zone = $('belt-zone');

    zone.ondragenter = ev => {
        if (dragKind) ev.preventDefault();
    };

    zone.ondragover = ev => {
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
                zone.querySelector(`.pos-card[data-index="${idx}"]`)?.classList.add('drop-target');
                ev.dataTransfer.dropEffect = 'copy';
            } else {
                ev.dataTransfer.dropEffect = 'none';
            }
        }
    };

    zone.ondragleave = ev => {
        if (ev.relatedTarget && zone.contains(ev.relatedTarget)) return;
        document.querySelectorAll('.pos-card.drop-target, .collision-warning').forEach(n =>
            n.classList.remove('drop-target', 'collision-warning')
        );
    };

    zone.ondrop = ev => {
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
    };

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

/**
 * Свободное перемещение нод по холсту за шапку с откатом при коллизиях
 */
function dragGNodes() {
    document.addEventListener('mousedown', ev => {
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
    });

    window.addEventListener('mousemove', ev => {
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
    });

    window.addEventListener('mouseup', () => {
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
    });
}
