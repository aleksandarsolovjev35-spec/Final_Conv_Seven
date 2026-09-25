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
let dropTileSeq = 0;
function dragTileToBelt(tile, x) {
    const dt = mkDT();
    const cx = x !== undefined ? x : (1200 + (dropTileSeq++) * 180);
    fire(tile, 'dragstart', dt);
    fire(zone(), 'dragover', dt, cx);
    fire(zone(), 'drop', dt, cx);
    fire(tile, 'dragend', dt);
}
function sockLink(srcSel, dstSel) {
    const a = doc.querySelector(srcSel);
    const b = doc.querySelector(dstSel);
    a.dispatchEvent(new window.MouseEvent('mousedown',
        { bubbles: true, cancelable: true, button: 0,
          clientX: 10, clientY: 10 }));
    b.dispatchEvent(new window.MouseEvent('mouseup',
        { bubbles: true, cancelable: true }));
}

check('старт: цепь пуста (первый бросок станет входом)', cards().length === 0);
dropTool('position', 300);
check('первая позиция = П0 вход с обязательной инспекцией',
    cards().length === 1 && cards()[0].classList.contains('inspect')
    && /инспекция/.test(cards()[0].textContent));
dropTool('position', 500);
check('бросок позиции добавляет свободную ноду (2 пластины)',
    cards().length === 2);
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
check('свободное добавление: нода встаёт в точку броска, а не в ряд',
    cards().length === nBefore + 1
    && cards()[cards().length - 1].classList.contains('g-pos')
    && cards()[cards().length - 1].style.left !== '');
check('инспекция и сброс не пересекаются',
    !Array.prototype.some.call(cards(),
        (c) => c.classList.contains('inspect') && c.classList.contains('reset-pt')));
let dropCamSeq = 0;
function dragWallToBelt(nth, x) {
    const dt = mkDT();
    const tile = thumbs()[nth];
    fire(tile, 'dragstart', dt);
    const cx = x !== undefined ? x : (3200 + (dropCamSeq++) * 200);
    fire(zone(), 'dragover', dt, cx);
    fire(zone(), 'drop', dt, cx);
    fire(tile, 'dragend', dt);
}
dragWall(0, 0);
check('перенос камеры на позицию не соединяет её напрямую', chips(0).length === 0);
dragWallToBelt(0);
check('выставление камеры на поле создает свободную ноду камеры', doc.querySelector('.cam-node[data-cam="cam0"]') !== null);
sockLink('.cam-node[data-cam="cam0"] .sock-out', '.pos-card[data-index="0"] .sock-node');
check('камера с поля подключена к П0 линией сокетов', chips(0).length === 1 && /CAM/.test(chips(0)[0].textContent));
check('детект: плиток стены ≥ 3', thumbs().length >= 3);
check('камера на не-инспекцию отклоняется',
    (function () {
        dragWall(1, 2);
        return !cards()[2].classList.contains('inspect') && chips(2).length === 0;
    })());
dragTileToBelt(modelTiles()[0]);
dragTileToBelt(ruleTiles()[0]);
check('бросок модели и правила на холст — свободные ноды',
    doc.querySelector('.gnode.g-model[data-model="m0"]') !== null
    && doc.querySelector('.gnode.g-rule[data-rule="r0"]') !== null);
sockLink('.g-model[data-model="m0"] .sock-out',
    '.g-rule[data-rule="r0"] .sock-in');
check('линка модель→правило: чип модели внутри ноды правила на холсте',
    doc.querySelectorAll('.gnode.g-rule[data-rule="r0"] .g-chip').length === 1
    && /1м/.test(ruleTiles()[0].textContent)
    && doc.querySelectorAll('.rule-drawer').length === 0);
check('плитки правил draggable всегда (размещение на холст)',
    ruleTiles()[1].draggable === true);
dragTileToBelt(modelTiles()[2]);
sockLink('.g-model[data-model="m2"] .sock-out',
    '.g-rule[data-rule="r0"] .sock-in');
check('вторая линка модели: счётчик «2м»', /2м/.test(ruleTiles()[0].textContent)
    && doc.querySelectorAll('.gnode.g-rule[data-rule="r0"] .g-chip').length === 2);
sockLink('.g-model[data-model="m2"] .sock-out',
    '.g-rule[data-rule="r0"] .sock-in');
check('повторная линка той же модели снимает её',
    doc.querySelectorAll('.gnode.g-rule[data-rule="r0"] .g-chip').length === 1
    && /1м/.test(ruleTiles()[0].textContent));
sockLink('.g-rule[data-rule="r0"] .sock-out',
    '.cam-node[data-cam="cam0"] .sock-in');
check('линка правило→камера: п:1, плашка «в деле»',
    /п:1/.test(chips(0)[0].textContent)
    && ruleTiles()[0].classList.contains('asset-used')
    && /кам: 1/.test(ruleTiles()[0].textContent));
check('закладка цвета правила у камеры',
    (function () {
        const tab = chips(0)[0].querySelector('.rule-tabs i');
        return tab !== null && /217, 164, 65/.test(tab.getAttribute('style') || '')
            && doc.querySelectorAll('.thumb .rule-tabs i').length >= 1
            && doc.querySelector('.g-rule .g-swatch') !== null;
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
check('запрет наложения: вторую позицию нельзя поместить поверх существующей',
    (function () {
        const row = doc.getElementById('belt-row');
        Object.defineProperty(row, 'offsetWidth',
            { value: 900, configurable: true });
        Object.defineProperty(row, 'offsetHeight',
            { value: 400, configurable: true });
        const n = cards().length;
        dropTool('position', 700);
        const countAfterFirst = cards().length;
        dropTool('position', 700);
        const countAfterSecond = cards().length;
        return countAfterFirst === n + 1 && countAfterSecond === n + 1
            && /Наложение/.test(doc.getElementById('toasts').textContent);
    })());
check('запрет наложения при перемещении: перетаскивание ноды на другую возвращает её назад',
    (function () {
        const c0 = cards()[0];
        const c1 = cards()[1];
        const x0 = parseFloat(c1.style.left);
        const y0 = parseFloat(c1.style.top);
        const head1 = c1.querySelector('.node-head');
        head1.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0, clientX: 10, clientY: 10 }));
        const targetX = parseFloat(c0.style.left);
        const targetY = parseFloat(c0.style.top);
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 10 + (targetX - x0), clientY: 10 + (targetY - y0) }));
        const warned = c1.classList.contains('collision-warning');
        window.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true }));
        const c1After = cards()[1];
        return warned
            && parseFloat(c1After.style.left) === x0
            && parseFloat(c1After.style.top) === y0
            && /Наложение/.test(doc.getElementById('toasts').textContent);
    })());
check('поле 2D: позицию можно поднять/опустить — вертикаль свободна',
    (function () {
        const last = cards()[cards().length - 1];
        const y0 = Number(last.style.top.replace('px', ''));
        const head = last.querySelector('.node-head');
        head.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 40, clientY: 40 }));
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 40, clientY: 200 }));
        window.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true }));
        const again = cards()[cards().length - 1];
        const y1 = Number(again.style.top.replace('px', ''));
        Object.defineProperty(doc.getElementById('belt-row'), 'offsetHeight',
            { value: 210, configurable: true });
        return y1 === y0 + 160;
    })());
check('расширенное поле: движение не зажато 210px — можно увести далеко по X и Y',
    (function () {
        const last = cards()[cards().length - 1];
        const y0 = Number(last.style.top.replace('px', ''));
        const head = last.querySelector('.node-head');
        head.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 40, clientY: 40 }));
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 700, clientY: 640 }));
        window.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true }));
        const again = cards()[cards().length - 1];
        const y1 = Number(again.style.top.replace('px', ''));
        return y1 === y0 + 600 && y1 > 500;
    })());
check('css: карточка позиции — absolute (иначе left/top не работают и ноды падают стопкой)',
    (function () {
        const css = fs.readFileSync(ROOT + '/css/belt-editor.css', 'utf8');
        const m = css.match(/\.pos-card\s*\{[^}]*\}/);
        return !!m && /position:\s*absolute/.test(m[0]);
    })());
check('роли цепи: П0 — только выход, середина — вход+выход, сброс — только вход',
    (function () {
        const c = cards();
        return c[0].querySelectorAll('.sock-line-out').length === 1
            && c[0].querySelectorAll('.sock-line-in').length === 0
            && c[2].querySelectorAll('.sock-line-in').length === 1
            && c[2].querySelectorAll('.sock-line-out').length === 1
            && c[1].querySelectorAll('.sock-line-in').length === 1
            && c[1].querySelectorAll('.sock-line-out').length === 0;
    })());
check('цепь линками: сборка, перелинковка входа, разрыв',
    (function () {
        const d = (a, b) => {
            a.dispatchEvent(new window.MouseEvent('mousedown',
                { bubbles: true, cancelable: true, button: 0,
                  clientX: 10, clientY: 10 }));
            b.dispatchEvent(new window.MouseEvent('mouseup',
                { bubbles: true, cancelable: true }));
        };
        const cnt = () => doc.querySelectorAll('#wires .wire-chain').length;
        d(cards()[0].querySelector('.sock-line-out'),
            cards()[2].querySelector('.sock-line-in'));
        if (cnt() !== 1) { return false; }
        d(cards()[2].querySelector('.sock-line-out'),
            cards()[1].querySelector('.sock-line-in'));
        if (cnt() !== 2) { return false; }
        d(cards()[0].querySelector('.sock-line-out'),
            cards()[1].querySelector('.sock-line-in'));
        const rewired = cnt() === 1;
        d(cards()[0].querySelector('.sock-line-out'),
            cards()[1].querySelector('.sock-line-in'));
        return rewired && cnt() === 0;
    })());
check('цикл на ленте невозможен, а П1 без связи дальше = валидный хвост',
    (function () {
        const d = (a, b) => {
            a.dispatchEvent(new window.MouseEvent('mousedown',
                { bubbles: true, cancelable: true, button: 0,
                  clientX: 10, clientY: 10 }));
            b.dispatchEvent(new window.MouseEvent('mouseup',
                { bubbles: true, cancelable: true }));
        };
        const cnt = () => doc.querySelectorAll('#wires .wire-chain').length;
        d(cards()[0].querySelector('.sock-line-out'),
            cards()[2].querySelector('.sock-line-in'));
        d(cards()[2].querySelector('.sock-line-out'),
            cards()[0].querySelector('.sock-line-in')
            || doc.createElement('i'));
        return cnt() === 1;
    })());
check('сокеты только на холсте: каталог/стена чисты, ноды — с сокетаки',
    (function () {
        return doc.querySelector('#asset-models .sock') === null
            && doc.querySelector('#asset-rules .sock') === null
            && doc.querySelector('.thumb .sock') === null
            && doc.querySelector('.g-model .sock-out') !== null
            && doc.querySelector('.g-rule .sock-in[data-drop="rule"]') !== null
            && doc.querySelector('.cam-node .sock-in[data-drop="cam"]') !== null
            && doc.querySelector('.cam-node .sock-out[data-link^="camera:"]') !== null
            && doc.querySelectorAll('.pos-card .sock-node[data-drop="pos"]').length
                === cards().length;
    })());
check('камера мимо позиции — свободная нода; линка сокета к входу привязывает',
    (function () {
        const dt = mkDT();
        fire(thumbs()[2], 'dragstart', dt);
        fire(zone(), 'dragover', dt, 2500);
        fire(zone(), 'drop', dt, 2500);
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
        const click = { bubbles: true };
        doc.querySelector('.cam-node[data-cam="cam2"] .pos-del')
            .dispatchEvent(new window.MouseEvent('click', click));
        const unbound = doc.querySelectorAll('.cam-node[data-pos="0"]')
            .length === 1
            && doc.querySelector('.cam-node.free[data-cam="cam2"]') !== null;
        doc.querySelector('.cam-node.free[data-cam="cam2"] .pos-del')
            .dispatchEvent(new window.MouseEvent('click', click));
        return unbound
            && doc.querySelector('.cam-node[data-cam="cam2"]') === null;
    })());
check('ссылка: тянем r1 (с моделью) на чип cam1 — связь создана, провод нарисован',
    (function () {
        dragTileToBelt(modelTiles()[1]);  /* m1 → нода */
        dragTileToBelt(ruleTiles()[1]);   /* r1 → нода */
        sockLink('.g-model[data-model="m1"] .sock-out',
            '.g-rule[data-rule="r1"] .sock-in');
        dragWallToBelt(1);                   /* cam1 → нода на холсте */
        sockLink('.cam-node[data-cam="cam1"] .sock-out',
            '.pos-card[data-index="0"] .sock-node'); /* линка к П0 */
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
        const to = doc.querySelector('.cam-node[data-cam="cam1"] .sock-in');
        from.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 10, clientY: 10 }));
        to.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true, cancelable: true }));
        const chip = doc.querySelector('.chip[data-cam="cam1"]');
        const clean = chip.querySelector('.chip-assets') === null;
        doc.querySelector('.cam-node[data-cam="cam1"] .pos-del')
            .dispatchEvent(new window.MouseEvent('click',
                { bubbles: true }));
        return clean && chips(0).length === 1
            && doc.querySelector('.cam-node.free[data-cam="cam1"]') !== null;
    })());
check('Esc обрывает незавершённую линку без изменений',
    (function () {
        const before = doc.querySelectorAll('#wires .wire').length;
        const from = doc.querySelector('.g-rule[data-rule="r1"] .sock-out');
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
        const chip = doc.querySelector('.gnode.g-rule[data-rule="r0"] .g-chip');
        if (!chip) { return false; }
        chip.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        return doc.querySelectorAll('.gnode.g-rule[data-rule="r0"] .g-chip').length === 1;
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
check('бросок модели на холст — нода, связей не создаёт',
    (function () {
        const chipsBefore = chips(0).length;
        dragTileToBelt(modelTiles()[3]);
        const n = doc.querySelector('.g-model[data-model="m3"]');
        return n !== null && chips(0).length === chipsBefore
            && /1м/.test(ruleTiles()[0].textContent);
    })());
check('ЛКМ за шапку двигает ноду по холсту',
    (function () {
        const head = doc.querySelector('.g-rule[data-rule="r0"] .node-head');
        head.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 30, clientY: 30 }));
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 110, clientY: 80 }));
        window.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true }));
        const st = doc.querySelector('.g-rule[data-rule="r0"]');
        return st.style.left !== '' && st.style.top !== '';
    })());
check('позиция — свободная нода: ЛКМ за шапку двигает карточку',
    (function () {
        const n0 = cards().length;
        const c1 = cards()[1];
        const head = c1.querySelector('.node-head');
        head.dispatchEvent(new window.MouseEvent('mousedown',
            { bubbles: true, cancelable: true, button: 0,
              clientX: 40, clientY: 40 }));
        window.dispatchEvent(new window.MouseEvent('mousemove',
            { bubbles: true, clientX: 150, clientY: 120 }));
        window.dispatchEvent(new window.MouseEvent('mouseup',
            { bubbles: true }));
        const c1b = cards()[1];
        return c1b.classList.contains('g-pos') && c1b.style.left !== ''
            && c1b.style.top !== '' && c1b.dataset.index === '1'
            && cards().length === n0;
    })());
check('перенос карточек drag-ом удалён (порядок = места вставки)',
    (function () {
        const c = cards()[0];
        if (c.draggable) { return false; }
        const dt = mkDT();
        fire(c, 'dragstart', dt);
        const clean = !c.classList.contains('dragging-src');
        fire(c, 'dragend', dt);
        return clean;
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
check('разделитель высоты сборки удалён, размер сборки зафиксирован на половине экрана',
    doc.getElementById('app-splitter') === null && doc.getElementById('btn-expand-build') === null);
check('сборка ленты: высота зафиксирована на 50%',
    (function () {
        const css = fs.readFileSync(ROOT + '/css/belt-editor.css', 'utf8');
        return /\.app\s*\{[^}]*50%/.test(css) && /\.cameras\s*\{[^}]*50%/.test(css);
    })());
check('панель правил и моделей #side-dock перенесена внутрь сборки ленты .build',
    doc.querySelector('.build').contains(doc.getElementById('side-dock')));
check('панель правил и моделей находится в правой части сборки ленты',
    doc.querySelector('.build-body').lastElementChild === doc.getElementById('side-dock'));
check('svg wires: строго внутри #belt-zone (провода не выходят за пределы поля на камеры)',
    doc.getElementById('belt-zone').contains(doc.getElementById('wires')));
check('боковая панель: отдельный док #side-dock внутри сборки ленты',
    doc.getElementById('side-dock') !== null);
check('боковая панель: правила и модели внутри #side-dock',
    doc.getElementById('side-dock').contains(doc.getElementById('asset-rules'))
    && doc.getElementById('side-dock').contains(doc.getElementById('asset-models')));
check('видеостена разгружена: в .cam-wall-wrap больше нет правил и моделей',
    !doc.querySelector('.cam-wall-wrap').contains(doc.getElementById('asset-rules'))
    && !doc.querySelector('.cam-wall-wrap').contains(doc.getElementById('asset-models')));
check('боковая панель Photoshop: сворачивание/разворачивание по кнопке',
    (function () {
        const dock = doc.getElementById('side-dock');
        const btnCol = doc.getElementById('btn-side-collapse');
        const btnExp = doc.getElementById('btn-side-expand');
        if (!dock || !btnCol || !btnExp) { return false; }
        btnCol.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        const isCol = dock.classList.contains('collapsed');
        btnExp.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        const isExp = !dock.classList.contains('collapsed');
        return isCol && isExp;
    })());
check('выбор папки: поля выбора папки в нижней части блоков правил и моделей',
    doc.getElementById('rule-folder-path') !== null
    && doc.getElementById('model-folder-path') !== null
    && doc.getElementById('btn-rule-folder') !== null
    && doc.getElementById('btn-model-folder') !== null);
check('выбор папки: поле правил внутри #ps-panel-rules, поле моделей внутри #ps-panel-models',
    doc.getElementById('ps-panel-rules').contains(doc.getElementById('rule-folder-path'))
    && doc.getElementById('ps-panel-models').contains(doc.getElementById('model-folder-path')));
check('выбор папки: загрузка файлов из папки добавляет модели и правила в каталог',
    (function () {
        const mBefore = doc.querySelectorAll('#asset-models .asset').length;
        window.BeltBridge.addModelFromFile('defect_weight_test.pt', 'weights/defect_weight_test.pt');
        const mAfter = doc.querySelectorAll('#asset-models .asset').length;

        const rBefore = doc.querySelectorAll('#asset-rules .rule-entry').length;
        window.BeltBridge.addRuleFromFile('rule_crack_test.py', 'domain/defect_rules/rule_crack_test.py');
        const rAfter = doc.querySelectorAll('#asset-rules .rule-entry').length;

        return mAfter === mBefore + 1 && rAfter === rBefore + 1;
    })());
check('синхронизация связей: мгновенное обновление проводов при переключении дока без задержки и рассинхрона',
    (function () {
        const js = fs.readFileSync(ROOT + '/js/builder.js', 'utf8');
        const css = fs.readFileSync(ROOT + '/css/belt-editor.css', 'utf8');
        const hasDirectWiresUpdate = js.includes('renderWires()') && js.includes('window.dispatchEvent(new Event(\'resize\'))');
        const noWidthTransition = !/\.side-dock\s*\{[^}]*transition:[^}]*width/.test(css);
        return hasDirectWiresUpdate && noWidthTransition;
    })());
check('переключение вкладок меню: за раз отображаются только правила либо только модели',
    (function () {
        const dock = doc.getElementById('side-dock');
        const tabRules = doc.getElementById('tab-btn-rules');
        const tabModels = doc.getElementById('tab-btn-models');
        if (!dock || !tabRules || !tabModels) { return false; }

        tabRules.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        const isRules = dock.classList.contains('show-rules')
            && !dock.classList.contains('show-models')
            && tabRules.classList.contains('active');

        tabModels.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        const isModels = dock.classList.contains('show-models')
            && !dock.classList.contains('show-rules')
            && tabModels.classList.contains('active');

        // Возвращаем в состояние rules
        tabRules.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
        return isRules && isModels;
    })());
check('видеостена камер не принимает правила: сборка только на сборке ленты',
    (function () {
        const br = window.BeltBridge;
        const noRuleDrop = typeof br.ruleDrop === 'undefined';
        const noRuleActive = typeof br.ruleActive === 'undefined';
        const camJs = fs.readFileSync(ROOT + '/js/cameras.js', 'utf8');
        const noWallDropRule = !camJs.includes('ruleDrop');
        return noRuleDrop && noRuleActive && noWallDropRule;
    })());
check('каталог правил чист от ящиков сборки: сборка только на холсте ленты',
    (function () {
        const drawers = doc.querySelectorAll('.rule-drawer');
        const ruleChipsInCatalog = doc.querySelectorAll('#asset-rules .rule-chip');
        return drawers.length === 0 && ruleChipsInCatalog.length === 0;
    })());
check('плитки правил не блокированы: нет класса rule-empty, курсор grab (перетаскивание доступно)',
    (function () {
        const tiles = doc.querySelectorAll('#asset-rules .rule-tile');
        const hasRuleEmpty = Array.from(tiles).some(t => t.classList.contains('rule-empty'));
        const css = fs.readFileSync(ROOT + '/css/belt-editor.css', 'utf8');
        const noNotAllowed = !/\.rule-tile[^{]*\{[^}]*cursor:\s*not-allowed/i.test(css);
        return tiles.length > 0 && !hasRuleEmpty && noNotAllowed;
    })());
check('запрет наложения графа: нельзя поместить ноду правила поверх ноды модели',
    (function () {
        const m = doc.querySelector('.gnode.g-model');
        const r = doc.querySelector('.gnode.g-rule');
        if (!m || !r) { return false; }
        const rX0 = parseFloat(r.style.left);
        const rY0 = parseFloat(r.style.top);
        const mX = parseFloat(m.style.left);
        const mY = parseFloat(m.style.top);
        const head = r.querySelector('.node-head');
        head.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0, clientX: 10, clientY: 10 }));
        window.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true, clientX: 10 + (mX - rX0), clientY: 10 + (mY - rY0) }));
        const warning = r.classList.contains('collision-warning');
        window.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true }));
        const rAfter = doc.querySelector('.gnode.g-rule');
        return warning
            && parseFloat(rAfter.style.left) === rX0
            && parseFloat(rAfter.style.top) === rY0
            && /Наложение/.test(doc.getElementById('toasts').textContent);
    })());
check('размерность при удержании: dragstart позиции формирует превью 176×96',
    (function () {
        const tool = doc.querySelector('.tool[data-kind="position"]');
        let setDragImageCalled = false;
        let dragEl = null;
        let ox = 0, oy = 0;
        const dt = {
            setData: function () {},
            setDragImage: function (el, x, y) {
                setDragImageCalled = true;
                dragEl = el;
                ox = x;
                oy = y;
            }
        };
        const ev = new window.Event('dragstart', { bubbles: true, cancelable: true });
        ev.dataTransfer = dt;
        tool.dispatchEvent(ev);
        const hasPreview = !!dragEl && dragEl.classList.contains('pos-card') && dragEl.classList.contains('ghost-preview');
        const endEv = new window.Event('dragend', { bubbles: true });
        tool.dispatchEvent(endEv);
        return setDragImageCalled && hasPreview && ox === 88 && oy === 22;
    })());
check('размерность при удержании: dragstart правила и модели задает превью 128px',
    (function () {
        const rTile = doc.querySelector('#asset-rules .rule-tile');
        let rCalled = false, rEl = null;
        const dtR = {
            setData: function () {},
            setDragImage: function (el) { rCalled = true; rEl = el; }
        };
        const evR = new window.Event('dragstart', { bubbles: true, cancelable: true });
        evR.dataTransfer = dtR;
        rTile.dispatchEvent(evR);
        const rOk = rCalled && rEl && rEl.classList.contains('g-rule');
        rTile.dispatchEvent(new window.Event('dragend', { bubbles: true }));

        const mTile = doc.querySelector('#asset-models .asset');
        let mCalled = false, mEl = null;
        const dtM = {
            setData: function () {},
            setDragImage: function (el) { mCalled = true; mEl = el; }
        };
        const evM = new window.Event('dragstart', { bubbles: true, cancelable: true });
        evM.dataTransfer = dtM;
        mTile.dispatchEvent(evM);
        const mOk = mCalled && mEl && mEl.classList.contains('g-model');
        mTile.dispatchEvent(new window.Event('dragend', { bubbles: true }));

        return rOk && mOk;
    })());
check('нет дублирования при первой установке: на холсте не создается второй элемент-призрак',
    (function () {
        const zone = doc.getElementById('belt-zone');
        const tool = doc.querySelector('.tool[data-kind="position"]');
        const dt = { setData: function () {}, setDragImage: function () {} };
        const evStart = new window.Event('dragstart', { bubbles: true, cancelable: true });
        evStart.dataTransfer = dt;
        tool.dispatchEvent(evStart);

        const evOver = new window.Event('dragover', { bubbles: true, cancelable: true });
        evOver.clientX = 500;
        evOver.clientY = 150;
        evOver.dataTransfer = { dropEffect: 'none' };
        zone.dispatchEvent(evOver);

        const ghost = doc.getElementById('canvas-drag-ghost');
        const noDuplicate = ghost === null;

        const evEnd = new window.Event('dragend', { bubbles: true });
        tool.dispatchEvent(evEnd);

        return noDuplicate;
    })());
check('перетаскиваемый объект: сплошная обводка без пунктира',
    (function () {
        const css = fs.readFileSync(ROOT + '/css/belt-editor.css', 'utf8');
        const previewBlock = css.match(/\.ghost-preview\s*\{[^}]*\}/);
        const hasSolid = previewBlock && /border-style:\s*solid\s*!important/i.test(previewBlock[0]);
        const noDashed = previewBlock && !/border-style:\s*dashed/i.test(previewBlock[0]);
        return !!(hasSolid && noDashed);
    })());
check('перетаскиваемый блок поверх цели: z-index 100 и верхушка DOM при наведении на другой блок',
    (function () {
        const m = doc.querySelector('.gnode.g-model');
        const r = doc.querySelector('.gnode.g-rule');
        if (!m || !r) { return false; }
        const rX0 = parseFloat(r.style.left);
        const rY0 = parseFloat(r.style.top);
        const mX = parseFloat(m.style.left);
        const mY = parseFloat(m.style.top);
        const head = r.querySelector('.node-head');
        head.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0, clientX: 10, clientY: 10 }));
        window.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true, clientX: 10 + (mX - rX0), clientY: 10 + (mY - rY0) }));
        const isDragging = r.classList.contains('node-dragging');
        const isLastChild = r.parentNode && r.parentNode.lastElementChild === r;
        window.dispatchEvent(new window.MouseEvent('mouseup', { bubbles: true }));

        const css = fs.readFileSync(ROOT + '/css/belt-editor.css', 'utf8');
        const hasHighZ = /\.node-dragging[^{]*\{[^}]*z-index:\s*100\s*!important/i.test(css);

        return isDragging && isLastChild && hasHighZ;
    })());
check('камера подключается к позиции только линией сокетов после выставления на поле',
    (function () {
        const c0 = cards()[0];
        const camCountBefore = doc.querySelectorAll('.cam-node').length;
        const dt = mkDT();
        fire(thumbs()[3], 'dragstart', dt);
        fire(zone(), 'dragover', dt, 50);
        fire(c0, 'drop', dt, 50);
        fire(thumbs()[3], 'dragend', dt);
        const notConnected = !c0.querySelector('.chip[data-cam="cam3"]')
            && doc.querySelectorAll('.cam-node').length === camCountBefore;

        dragWallToBelt(3);
        const cam3Free = doc.querySelector('.cam-node[data-cam="cam3"]');
        const onField = cam3Free !== null && cam3Free.classList.contains('free');

        sockLink('.cam-node[data-cam="cam3"] .sock-out', '.pos-card[data-index="0"] .sock-node');
        const cam3Bound = doc.querySelector('.cam-node[data-cam="cam3"]');
        const connectedByLine = cam3Bound !== null
            && !cam3Bound.classList.contains('free')
            && cam3Bound.dataset.pos === '0';

        return notConnected && onField && connectedByLine;
    })());
check('логика переноса камеры унифицирована с правилами и моделями: отказ с запретом наложения',
    (function () {
        const c0 = cards()[0];
        const dt = mkDT();
        fire(thumbs()[4], 'dragstart', dt);
        fire(zone(), 'dragover', dt, 50);
        fire(c0, 'drop', dt, 50);
        fire(thumbs()[4], 'dragend', dt);
        const hasOverlayToast = /Наложение/.test(doc.getElementById('toasts').textContent);
        const noChip = !c0.querySelector('.chip[data-cam="cam4"]');
        return hasOverlayToast && noChip;
    })());
check('после dragend визуал чист',
    doc.querySelectorAll('.dragging, .drop-target, .dragging-src').length === 0);

console.log(failures === 0 ? 'SMOKE_PASS' : 'SMOKE_FAIL(' + failures + ')');
process.exit(failures === 0 ? 0 : 1);
