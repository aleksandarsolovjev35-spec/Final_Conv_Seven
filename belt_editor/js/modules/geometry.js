/**
 * @file geometry.js
 * @description Геометрия холста, позиционирование узлов и предотвращение наложений (коллизий).
 */

'use strict';

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
