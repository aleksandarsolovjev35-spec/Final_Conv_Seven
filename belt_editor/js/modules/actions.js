/**
 * @file actions.js
 * @description Бизнес-действия ленты: добавление, удаление, привязка камер, редактирование меток.
 */

'use strict';

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
 * Снятие камеры с позиции
 * @param {number} i Индекс позиции
 * @param {number} j Индекс камеры в массиве cameras
 */
function removeCamera(i, j) {
    const pos = belt.positions[i];
    if (!pos?.inspection) return;
    toast(`${camName(pos.inspection.cameras.splice(j, 1)[0])} — снята с П${i}.`);
    render();
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

