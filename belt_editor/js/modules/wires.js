/**
 * @file wires.js
 * @description Blender-style движок связей: кривые Безье, сокеты, магнитный доводчик, клик удаления.
 */

'use strict';

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
 * Отрисовка всех активных соединений и интерактивных хитбоксов удаления
 */
function renderWires() {
    const svg = $('wires');
    if (!svg) return;
    svg.textContent = '';

    const q = sel => document.querySelector(sel);

    function link(from, to, color, cls, onRemove) {
        const a = sockXY(from);
        const b = sockXY(to);
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

    // Связи модель → правило
    RULES.forEach(r => {
        r.models.forEach(m => {
            link(
                q(`.sock[data-link="model:${m}"]`),
                q(`.sock[data-drop="rule"][data-rid="${r.id}"]`),
                null,
                null,
                () => togglePart(r.id, m)
            );
        });
    });

    // Связи правило → камера
    inventory.forEach(dev => {
        dev.rules.forEach(rid => {
            const r = RULES.find(x => x.id === rid);
            link(
                q(`.sock[data-link="rule:${rid}"]`),
                q(`.sock[data-drop="cam"][data-cam="${dev.id}"]`),
                r?.color,
                null,
                () => toggleRuleOnCam(dev.id, rid)
            );
        });
    });

    // Связи камера → позиция и позиция → позиция
    belt.positions.forEach((pos, i) => {
        if (pos.inspection) {
            pos.inspection.cameras.forEach(cid => {
                link(
                    q(`.cam-node[data-cam="${cid}"] .sock[data-link="camera:${cid}"]`),
                    q(`.pos-card[data-index="${i}"] .sock-node`),
                    null,
                    null,
                    () => {
                        const idx = pos.inspection.cameras.indexOf(cid);
                        if (idx >= 0) {
                            pos.inspection.cameras.splice(idx, 1);
                            toast(camName(cid) + ' — снята с П' + i + '.');
                            render();
                        }
                    }
                );
            });
        }

        if (pos.nextUid) {
            const tgt = findPosByUid(pos.nextUid);
            if (tgt) {
                link(
                    q(`.pos-card[data-index="${i}"] .sock-line-out`),
                    q(`.pos-card[data-index="${belt.positions.indexOf(tgt)}"] .sock-line-in`),
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

    // Живой провод во время вытягивания связи пользователем
    if (linkDrag) {
        const fromPt = sockXY(linkDrag.from);
        const toPt = linkDrag.snapPt || [linkDrag.x, linkDrag.y];
        if (fromPt && toPt) {
            const [start, end] = linkDrag.dir === 'out' ? [fromPt, toPt] : [toPt, fromPt];
            svg.appendChild(svgPath(bez(start, end), 'wire wire-live' + (linkDrag.hot ? ' wire-ok' : '')));
        }
    }
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
function wireLinkEngine() {
    document.addEventListener('mousedown', ev => {
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
    });

    window.addEventListener('mousemove', ev => {
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
    });

    window.addEventListener('mouseup', ev => {
        if (!linkDrag) return;
        const d = linkDrag;
        let t = null;

        if (ev.target?.closest) {
            const cand = ev.target.closest(d.dir === 'out' ? '[data-drop]' : '[data-link]');
            if (cand && cand !== d.from) {
                const want = d.dir === 'out' ? LINK_WANT[d.kind] : LINK_REV[d.kind];
                const key = d.dir === 'out' ? cand.dataset.drop : (cand.dataset.link || '').split(':')[0];
                if (key === want && !(d.dir === 'out' && want === 'pos' && !belt.positions[Number(cand.dataset.idx)]?.inspection)) {
                    t = cand;
                }
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
        } else {
            render();
        }
    });

    document.addEventListener('keydown', ev => {
        if (ev.key === 'Escape' && linkDrag) {
            markTargets(false);
            if (linkDrag.hot) linkDrag.hot.classList.remove('sock-hot');
            document.body.classList.remove('linking');
            linkDrag = null;
            render();
        }
    });

    ['resize', 'scroll', 'transitionend'].forEach(e =>
        (e === 'scroll' ? document : window).addEventListener(e, scheduleWires, true)
    );
    $('belt-zone')?.addEventListener('belt:view', renderWires);
    ['wheel', 'mousemove', 'dblclick'].forEach(t => $('belt-zone')?.addEventListener(t, scheduleWires));

    if (typeof ResizeObserver !== 'undefined' && $('belt-zone')) {
        try { new ResizeObserver(scheduleWires).observe($('belt-zone')); } catch (e) {}
    }
}
