/* Смоук-стенд belt_editor (jsdom). Запуск:
 *   cd belt_editor/tests && npm i jsdom && node smoke.js
 * Вне git только node_modules/. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const ROOT = path.resolve(__dirname, '..');

let failures = 0;
const check = (l, c) => { console.log((c ? 'ok   ' : 'FAIL ') + l); if (!c) failures++; };

const html = fs.readFileSync(ROOT + '/index.html', 'utf8')
    .replace(/<script src="[^"]*"><\/script>/g, '');
const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true });
const { window } = dom;
const doc = window.document;
window.HTMLElement.prototype.getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0 });
window.eval(fs.readFileSync(ROOT + '/js/builder.js', 'utf8'));
window.eval(fs.readFileSync(ROOT + '/js/belt-view.js', 'utf8'));
window.eval(fs.readFileSync(ROOT + '/js/cameras.js', 'utf8'));
doc.dispatchEvent(new window.Event('DOMContentLoaded', { bubbles: true }));

const mkDT = () => ({ data: {}, setData(k, v) { this.data[k] = v; },
    getData(k) { return this.data[k] || ''; }, effectAllowed: '', dropEffect: '' });
function fire(el, type, dt, x) {
    const ev = new window.MouseEvent(type, { bubbles: true, cancelable: true,
        clientX: x === undefined ? 10 : x, clientY: 80 });
    if (dt) Object.defineProperty(ev, 'dataTransfer', { value: dt });
    el.dispatchEvent(ev);
}
const zone = () => doc.getElementById('belt-zone');
const cards = () => doc.querySelectorAll('.pos-card');
const thumbs = () => doc.querySelectorAll('.thumb');
const ruleTiles = () => doc.querySelectorAll('#asset-rules .rule-tile');
const entries = () => doc.querySelectorAll('#asset-rules .rule-entry');
const modelTiles = () => doc.querySelectorAll('#asset-models .asset');
const chips = (i) => doc.querySelectorAll('.cam-node[data-pos="' + i + '"] .chip');
function dropTool(kind, x, onCard) {
    const dt = mkDT();
    fire(doc.querySelector('.tool[data-kind="' + kind + '"]'), 'dragstart', dt);
    fire(zone(), 'dragover', dt, x);
    fire((onCard === undefined) ? zone() : cards()[onCard], 'drop', dt, x);
    fire(doc.querySelector('.tool[data-kind="' + kind + '"]'), 'dragend', dt);
}
function dragWall(nth, onCard) {
    const dt = mkDT();
    const tile = thumbs()[nth];
    fire(tile, 'dragstart', dt);
    fire(zone(), 'dragover', dt, 10);
    fire(cards()[onCard], 'drop', dt, 10);
    fire(tile, 'dragend', dt);
}
function dragModelToRule(m, r) {
    const dt = mkDT();
    const tile = modelTiles()[m];
    const entry = entries()[r];
    fire(tile, 'dragstart', dt);
    fire(entry, 'dragover', dt);
    fire(entry, 'drop', dt);
    fire(tile, 'dragend', dt);
}
function dropRuleOnChip(r, cardI, chipI) {
    const dt = mkDT();
    const tile = ruleTiles()[r];
    const chip = chips(cardI)[chipI];
    fire(tile, 'dragstart', dt);
    fire(chip, 'dragover', dt);
    fire(chip, 'drop', dt);
    fire(tile, 'dragend', dt);
}

check('старт: цепь пуста (первый бросок станет входом)', cards().length === 0);
dropTool('position', 300);
check('первая позиция = П0 вход с обязательной инспекцией',
    cards().length === 1 && cards()[0].classList.contains('inspect')
    && /инспекция/.test(cards()[0].textContent));
dropTool('position', 500);
check('бросок позиции вставляет по месту (2 пластины)', cards().length === 2);
dropTool('inspect', undefined, 1);
check('бросок инспекции делает П1 инспекционной', cards()[1].classList.contains('inspect'));
dropTool('inspect', undefined, 1);
check('повторный бросок инспекции снимает её', !cards()[1].classList.contains('inspect'));
dropTool('reset', 20, 1);
check('сброс на хвостовой позиции', cards()[1].classList.contains('reset-pt'));
dropTool('reset', 20, 0);
check('сброс нельзя на П0 (вход-инспекция)', !cards()[0].classList.contains('reset-pt'));
const nBefore = cards().length;
dropTool('position', 9999);
check('вставка с хвоста встаёт перед сбросом',
    cards().length === nBefore + 1
    && cards()[cards().length - 1].classList.contains('reset-pt'));
check('инспекция и сброс не пересекаются',
    !Array.prototype.some.call(cards(),
        (c) => c.classList.contains('inspect') && c.classList.contains('reset-pt')));
dragWall(0, 0);
check('камера с стены встала на П0', chips(0).length === 1 && /CAM/.test(chips(0)[0].textContent));
check('детект: плиток стены ≥ 3', thumbs().length >= 3);
check('камера на не-инспекцию отклоняется',
    (function () {
        dragWall(1, 2);
        return !cards()[2].classList.contains('inspect') && chips(2).length === 0;
    })());
dragModelToRule(0, 0);
check('модель на правиле: чип в ящике, ящик раскрыт',
    entries()[0].querySelectorAll('.rule-chip').length === 1
    && !entries()[0].querySelector('.rule-drawer').classList.contains('rule-drawer-empty')
    && doc.querySelectorAll('.rule-drawer-empty').length === 3);
check('правило с составом стало draggable', ruleTiles()[0].draggable === true);
dragModelToRule(2, 0);
check('вторая модель: счётчик «2м»', /2м/.test(ruleTiles()[0].textContent));
dragModelToRule(0, 0);
check('повторный бросок той же модели снимает её',
    entries()[0].querySelectorAll('.rule-chip').length === 1
    && /1м/.test(ruleTiles()[0].textContent));
dragModelToRule(0, 0);
dropRuleOnChip(0, 0, 0);
check('правило на фишке камеры: п:1, плашка «в деле»',
    /п:1/.test(chips(0)[0].textContent)
    && ruleTiles()[0].classList.contains('asset-used')
    && /кам: 1/.test(ruleTiles()[0].textContent));
check('закладка цвета правила у камеры',
    (function () {
        const tab = chips(0)[0].querySelector('.rule-tabs i');
        return tab !== null && /217, 164, 65/.test(tab.getAttribute('style') || '')
            && doc.querySelectorAll('.thumb .rule-tabs i').length >= 1;
    })());
check('плитка позиции — нода: шапка с ролью, тело со строками',
    (function () {
        const c0 = cards()[0];
        const head = c0.querySelector('.node-head');
        const body = c0.querySelector('.node-body');
        return head !== null && body !== null
            && head.querySelector('.pos-label') !== null
            && head.querySelector('.pos-del') !== null
            && !c0.querySelector('.chip')
            && c0.querySelector('.sock-node') !== null
            && doc.querySelector('.cam-node[data-pos="0"]') !== null
            && !c0.querySelector('.pos-top');
    })());
check('сокеты на местах: модель/правило/стена — выходы, чип/нода — входы',
    doc.querySelector('.sock[data-link="model:m0"]') !== null
    && doc.querySelector('.sock[data-link="rule:r0"]') !== null
    && doc.querySelector('.sock[data-link^="camera:"]') !== null
    && doc.querySelector('.sock[data-drop="cam"]') !== null
    && doc.querySelector('.sock[data-drop="pos"]') !== null);
check('камера мимо позиции — свободная нода; линка сокета к входу привязывает',
    (function () {
        const dt = mkDT();
        fire(thumbs()[2], 'dragstart', dt);
        fire(zone(), 'dragover', dt, 9999);
        fire(zone(), 'drop', dt, 9999);
        fire(thumbs()[2], 'dragend', dt);
        const free = doc.querySelector('.cam-node.free[data-cam="cam2"]');
        if (!free) { return false; }
        const out = free.querySelector('.sock-out');
        const posIn = doc.querySelector('.pos-card[data-index="0"] .sock-node');
        out.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 1, clientY: 1 }));
        posIn.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true, cancelable: true }));
        const bound = doc.querySelector(
            '.cam-node[data-pos="0"] .chip[data-cam="cam2"]');
        if (!bound || doc.querySelector('.cam-node.free')) { return false; }
        bound.querySelector('.chip-x').dispatchEvent(
            new window.MouseEvent('click', { bubbles: true }));
        return doc.querySelectorAll('.cam-node[data-pos="0"]')
            .length === 1;
    })());
check('ссылка: тянем r1 (с моделью) на чип cam1 — связь создана, провод нарисован',
    (function () {
        dragModelToRule(1, 1);            /* r1: наличие ← m1 */
        dragWall(1, 0);                   /* cam1 → П0 (2-м чипом) */
        const from = doc.querySelector('.sock[data-link="rule:r1"]');
        const to = doc.querySelector('.sock[data-drop="cam"][data-cam="cam1"]')
            || doc.querySelector('.chip[data-cam="cam1"]');
        from.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 10, clientY: 10 }));
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 60, clientY: 60 }));
        const live = doc.querySelectorAll('#wires .wire-live').length === 1;
        to.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true, cancelable: true }));
        const chip = doc.querySelector('.chip[data-cam="cam1"]');
        return live && chip !== null
            && /п:1/.test(chip.querySelector('.chip-assets').textContent)
            && doc.querySelectorAll('#wires .wire').length >= 4;
    })());
check('та же ссылка по правилу снимает его (toggle-семантика)',
    (function () {
        const from = doc.querySelector('.sock[data-link="rule:r1"]');
        const to = doc.querySelector('.chip[data-cam="cam1"] .sock-in');
        from.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 10, clientY: 10 }));
        to.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true, cancelable: true }));
        const chip = doc.querySelector('.chip[data-cam="cam1"]');
        const clean = chip.querySelector('.chip-assets') === null;
        chip.querySelector('.chip-x').dispatchEvent(
            new window.MouseEvent('click', { bubbles: true }));
        return clean && chips(0).length === 1;
    })());
check('Esc обрывает незавершённую линку без изменений',
    (function () {
        const before = doc.querySelectorAll('#wires .wire').length;
        const from = doc.querySelector('.sock[data-link="rule:r2"]');
        from.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 5, clientY: 5 }));
        doc.dispatchEvent(new window.KeyboardEvent('keydown',
            { key: 'Escape', bubbles: true }));
        return doc.querySelectorAll('#wires .wire-live').length === 0
            && doc.querySelectorAll('#wires .wire').length <= before;
    })());
check('клик по фишке — нода-карточка: блоки правил с их порогами',
    (function () {
        chips(0)[0].dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        const pop = doc.querySelector('.thr-node');
        if (!pop) { return false; }
        const inp = pop.querySelector('.thr-input');
        return pop.querySelectorAll('.thr-blk').length === 1
            && pop.querySelectorAll('.thr-row').length === 3
            && /площадь/.test(pop.textContent)
            && inp !== null && inp.value === '0.50'
            && chips(0)[0].classList.contains('chip-open');
    })());
check('правка порога сохраняется (0.83) и не удаляет камеру',
    (function () {
        const inp = doc.querySelectorAll('.thr-node .thr-input')[2];
        inp.value = '0.83';
        inp.dispatchEvent(new window.Event('input', { bubbles: true }));
        inp.dispatchEvent(new window.Event('change', { bubbles: true }));
        const pop2 = doc.querySelector('.thr-node');
        return pop2 !== null
            && pop2.querySelectorAll('.thr-input')[2].value === '0.83'
            && pop2.querySelectorAll('.thr-input')[0].value === '0.50'
            && chips(0).length === 1;
    })());
check('клик вне — закрыть; Esc — закрыть; клик по фишке — снова открыт',
    (function () {
        doc.body.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        const closed = doc.querySelector('.thr-node') === null;
        chips(0)[0].dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        const re = doc.querySelector('.thr-node') !== null;
        doc.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        return closed && re && doc.querySelector('.thr-node') === null;
    })());
check('последнюю модель стоящего правила снять нельзя',
    (function () {
        const chip = entries()[0].querySelectorAll('.rule-chip')[1]
            || entries()[0].querySelectorAll('.rule-chip')[0];
        chip.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        return entries()[0].querySelectorAll('.rule-chip').length === 1;
    })());
const ri = doc.getElementById('rule-search');
ri.value = 'геом';
ri.dispatchEvent(new window.MouseEvent('input', { bubbles: true }));
check('поиск ПРАВИЛ фильтрует по подстроке',
    ruleTiles().length === 1 && /геометрия/.test(ruleTiles()[0].textContent));
ri.value = '';
ri.dispatchEvent(new window.MouseEvent('input', { bubbles: true }));
check('очистка поиска возвращает полный список', ruleTiles().length === 4);
check('каталог моделей: 12 drag-источников',
    modelTiles().length === 12 && modelTiles()[0].draggable === true);
check('колесо над списком листает построчно',
    (function () {
        const list = doc.getElementById('asset-models');
        Object.defineProperty(list, 'scrollHeight', { value: 900, configurable: true });
        Object.defineProperty(list, 'clientHeight', { value: 100, configurable: true });
        const ev = new window.MouseEvent('wheel', { bubbles: true, cancelable: true });
        Object.defineProperty(ev, 'deltaY', { value: 120 });
        list.dispatchEvent(ev);
        return ev.defaultPrevented === true;
    })());
check('модель, брошенная на ленту, отклоняется',
    (function () {
        const before = entries()[0].querySelectorAll('.rule-chip').length;
        const dt = mkDT();
        fire(modelTiles()[1], 'dragstart', dt);
        fire(zone(), 'dragover', dt, 10);
        fire(zone(), 'drop', dt, 10);
        fire(modelTiles()[1], 'dragend', dt);
        return entries()[0].querySelectorAll('.rule-chip').length === before;
    })());
check('СКМ — свободный пан по ленте из любой точки (и по карточке)',
    (function () {
        const z = doc.getElementById('belt-zone');
        const tgt = doc.querySelector('.pos-card') || z;
        tgt.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 1,
              clientX: 50, clientY: 50 }));
        const panning = z.classList.contains('panning');
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 90, clientY: 70, buttons: 4 }));
        const st = window.BeltView.state();
        window.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true, button: 1 }));
        return panning && st.panX === 40 && st.panY === 20;
    })());
check('горизонтальное колесо — сдвиг, не зум',
    (function () {
        const z = doc.getElementById('belt-zone');
        const before = window.BeltView.state();
        const ev = new window.MouseEvent('wheel',
            { bubbles: true, cancelable: true });
        Object.defineProperty(ev, 'deltaX', { value: 30 });
        Object.defineProperty(ev, 'deltaY', { value: 5 });
        Object.defineProperty(ev, 'deltaMode', { value: 0 });
        z.dispatchEvent(ev);
        const st = window.BeltView.state();
        return st.panX === before.panX - 30 && st.z === before.z
            && ev.defaultPrevented === true;
    })());
check('ЛКМ-пан по фону жив, drag карточки не перехвачен',
    (function () {
        const z = doc.getElementById('belt-zone');
        const st0 = window.BeltView.state();
        z.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 10, clientY: 10 }));
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 35, clientY: 10, buttons: 1 }));
        const st1 = window.BeltView.state();
        window.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true }));
        return st1.panX === st0.panX + 25;
    })());
check('после dragend визуал чист',
    doc.querySelectorAll('.dragging, .drop-target, .dragging-src').length === 0);

console.log(failures === 0 ? 'SMOKE_PASS' : 'SMOKE_FAIL(' + failures + ')');
process.exit(failures === 0 ? 0 : 1);
