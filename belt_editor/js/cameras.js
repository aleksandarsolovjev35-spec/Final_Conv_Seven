/* belt_editor/js/cameras.js — видеостена и источник камер.
 *
 * Справа сверху — все обнаруженные устройства: их перетаскивают на
 * позиции ленты (мост window.BeltBridge -> builder.js). Плита связана
 * с позицией подсвечена и несёт метку «Пn». Слева сверху — основной
 * крупный план: первая камера входного (основного) места; клик по
 * плите тоже выводит её на крупный план. Кадры симулированы, реальный
 * бэкенд подключится заменой drawFeed на /stream/*.
 */
'use strict';

(function () {

const PAINT_INTERVAL = 90;

let cameras = [];
let mainId = null;
let tileDragging = false;
let rafId = 0;
let lastPaint = 0;

function $id(id) { return document.getElementById(id); }

function findCam(list, id) {
    for (let i = 0; i < list.length; i += 1) {
        if (list[i].id === id) { return list[i]; }
    }
    return null;
}

/* Основная — первая камера входного места; если входа нет — первая
 * привязанная; если и таких нет — первая обнаруженная. */
function entryId(list) {
    for (let i = 0; i < list.length; i += 1) {
        if (list[i].primary && list[i].position >= 0) { return list[i].id; }
    }
    for (let i = 0; i < list.length; i += 1) {
        if (list[i].position >= 0) { return list[i].id; }
    }
    return list.length ? list[0].id : null;
}

/* ─── Синхронизация с лентой ──────────────────────────────────────── */

function sync(list) {
    cameras = list || [];
    if (!findCam(cameras, mainId)) { mainId = entryId(cameras); }
    buildMain();
    buildWall();
    schedule();
}

function pick(id) {
    mainId = id;
    buildMain();
    buildWall();
    schedule();
}

/* ─── Панели ──────────────────────────────────────────────────────── */

function buildMain() {
    const cam = findCam(cameras, mainId);
    $id('cam-main-role').textContent = cam && cam.position >= 0
        ? cam.name + ' · П' + cam.position + (cam.primary ? ' · вход' : '')
        : cam ? cam.name + ' · свободна' : 'камер нет';
}

function appendThumbBadges(tile, cam) {
    if (cam.rules) {
        const use = document.createElement('span');
        use.className = 'thumb-use';
        use.textContent = 'п:' + cam.rules + ' · м:' + cam.mods;
        tile.appendChild(use);

        if (cam.ruleColors && cam.ruleColors.length) {
            const tabs = document.createElement('span');
            tabs.className = 'rule-tabs';
            cam.ruleColors.forEach(function (c) {
                const t = document.createElement('i');
                t.style.background = c;
                tabs.appendChild(t);
            });
            tile.appendChild(tabs);
        }
    }

    if (cam.position >= 0) {
        const tag = document.createElement('span');
        tag.className = 'thumb-pos';
        tag.textContent = 'П' + cam.position;
        tile.appendChild(tag);
    }
}

function bindThumbEvents(tile, cam) {
    tile.addEventListener('dragstart', function (ev) {
        tileDragging = true;
        tile.classList.add('dragging-src');
        if (window.BeltBridge) {
            window.BeltBridge.camDragStart(cam.id, ev.dataTransfer, ev);
        }
    });

    tile.addEventListener('dragend', function () {
        tileDragging = false;
        tile.classList.remove('dragging-src');
        if (window.BeltBridge) { window.BeltBridge.camDragEnd(); }
    });

    tile.addEventListener('click', function () {
        if (!tileDragging) { pick(cam.id); }
    });
}

function createThumbTile(cam) {
    const tile = document.createElement('div');
    let cls = 'thumb';
    if (cam.id === mainId) { cls += ' main'; }
    if (cam.position >= 0) { cls += ' bound'; }
    tile.className = cls;
    tile.draggable = true;

    const canvas = document.createElement('canvas');
    canvas.dataset.cam = cam.id;
    const name = document.createElement('span');
    name.className = 'thumb-role';
    name.textContent = cam.name;
    const det = document.createElement('span');
    det.className = 'thumb-det';

    tile.appendChild(canvas);
    tile.appendChild(name);
    tile.appendChild(det);

    appendThumbBadges(tile, cam);
    bindThumbEvents(tile, cam);

    return tile;
}

function buildWall() {
    const wall = $id('cam-wall');
    wall.textContent = '';
    cameras.forEach(function (cam) {
        wall.appendChild(createThumbTile(cam));
    });
    $id('cam-count').textContent = 'камер: ' + cameras.length;
}

/* ─── Кадры ───────────────────────────────────────────────────────── */

function ctx2d(cv) {
    if (!cv || !cv.getContext) { return null; }
    try { return cv.getContext('2d'); } catch (err) { return null; }
}

function fitMain(canvas) {
    const box = $id('cam-main-box');
    const dpr = window.devicePixelRatio || 1;
    const w = box ? box.clientWidth : 0;
    const h = box ? box.clientHeight : 0;
    if (w < 2 || h < 2) { return false; }
    const bw = Math.max(2, Math.round(w * dpr));
    const bh = Math.max(2, Math.round(h * dpr));
    if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = bw;
        canvas.height = bh;
    }
    return true;
}

function fitThumb(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const bw = Math.max(2, Math.round((canvas.clientWidth || 0) * dpr));
    const bh = Math.max(2, Math.round((canvas.clientHeight || 0) * dpr));
    if (!canvas.clientWidth || !canvas.clientHeight) { return false; }
    if (canvas.width !== bw || canvas.height !== bh) {
        canvas.width = bw;
        canvas.height = bh;
    }
    return true;
}

function hash(str) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < str.length; i += 1) {
        h ^= str.charCodeAt(i);
        h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
}

/** Отрисовка направляющего рельса и шпал конвейера */
function drawConveyorTrack(ctx, w, h, railY, t) {
    ctx.strokeStyle = 'rgba(120, 153, 165, 0.28)';
    ctx.lineWidth = Math.max(1, Math.round(h / 220));
    ctx.beginPath();
    ctx.moveTo(0, railY + 0.5);
    ctx.lineTo(w, railY + 0.5);
    ctx.stroke();

    const step = Math.max(12, Math.round(w / 13));
    const shift = (t * 36) % step;
    ctx.strokeStyle = 'rgba(120, 153, 165, 0.10)';
    ctx.beginPath();
    for (let x = -step + shift; x < w + step; x += step) {
        ctx.moveTo(x, railY + 3);
        ctx.lineTo(x + step * 0.4, h);
    }
    ctx.stroke();
}

/** Отрисовка детали (корпуса) на конвейере */
function drawWorkpiece(ctx, w, h, railY, p, size) {
    const bw = Math.round(w * size);
    const bh = Math.round(h * 0.30);
    const bx = Math.round(w * p - bw / 2);
    const by = railY - bh;
    ctx.fillStyle = '#394853';
    ctx.fillRect(bx, by - Math.round(bh * 0.16), bw, Math.round(bh * 0.30));
    ctx.fillStyle = '#2c3943';
    ctx.fillRect(bx, by + Math.round(bh * 0.10), bw, bh - Math.round(bh * 0.10));
    ctx.fillStyle = '#161e25';
    const legW = Math.max(1, Math.round(bw * 0.04));
    for (let k = 0; k < 5; k += 1) {
        ctx.fillRect(bx + Math.round(bw * (0.08 + 0.20 * k)), railY, legW, Math.round(h * 0.045));
    }
}

/** Отрисовка шума матрицы и полосы сканирования */
function drawNoiseAndScanline(ctx, w, h, rand, large, t, flick) {
    for (let i = 0; i < (large ? 90 : 16); i += 1) {
        ctx.fillStyle = 'rgba(255,255,255,' + (rand() * 0.05).toFixed(3) + ')';
        ctx.fillRect(Math.round(rand() * w), Math.round(rand() * h), 1, 1);
    }
    const scanY = ((t * 0.22 + flick) % 1) * h;
    ctx.fillStyle = 'rgba(120, 153, 165, 0.055)';
    ctx.fillRect(0, scanY, w, Math.max(2, Math.round(h * 0.025)));
}

/** Отрисовка прицельной сетки и рамки захвата */
function drawReticleOverlay(ctx, w, h, inField, p, size, railY) {
    const cx = w / 2;
    const cy = h / 2;
    const m = Math.max(6, Math.round(w * 0.012));
    ctx.strokeStyle = 'rgba(224, 229, 233, 0.35)';
    ctx.beginPath();
    ctx.moveTo(cx - m, cy); ctx.lineTo(cx - m / 3, cy);
    ctx.moveTo(cx + m / 3, cy); ctx.lineTo(cx + m, cy);
    ctx.moveTo(cx, cy - m); ctx.lineTo(cx, cy - m / 3);
    ctx.moveTo(cx, cy + m / 3); ctx.lineTo(cx, cy + m);
    ctx.stroke();

    if (inField) {
        ctx.strokeStyle = 'rgba(114, 163, 126, 0.85)';
        ctx.lineWidth = Math.max(1, Math.round(w / 640));
        const bw = Math.round(w * size);
        const bh = Math.round(h * 0.30);
        const bx = Math.round(w * p - bw / 2);
        const by = railY - bh - Math.round(bh * 0.16);
        ctx.strokeRect(bx - 6, by - 6, bw + 12, railY - by + Math.round(h * 0.06) + 12);
    }
}

function drawInspectionPresence(ctx, px, py, pw, ph, rule) {
    const expected = rule.countExpected || 4, actual = expected;
    const stepX = pw / (expected + 1);
    for (let i = 1; i <= expected; i++) {
        const mx = Math.round(px + i * stepX), my = Math.round(py + ph / 2);
        ctx.fillStyle = '#58b79a';
        ctx.fillRect(mx - 3, my - 3, 6, 6);
        ctx.font = '8px monospace';
        ctx.fillText(String(i), mx - 2, my - 5);
    }
    return { isFail: actual < expected, text: `Наличие: ${actual} из ${expected} шт` };
}

function drawInspectionDefect(ctx, px, py, pw, ph, rule) {
    const allowed = rule.maxDefects ?? 0, found = 0;
    ctx.strokeStyle = 'rgba(207, 122, 166, 0.45)';
    ctx.setLineDash([2, 2]);
    ctx.strokeRect(px + 3, py + 3, pw - 6, ph - 6);
    ctx.setLineDash([]);
    ctx.fillStyle = '#cf7aa6';
    ctx.font = '7.5px monospace';
    ctx.fillText('✓ ЧИСТО', px + 6, py + Math.round(ph / 2) + 3);
    return { isFail: found > allowed, text: `Дефекты: ${found} шт (допуск: ${allowed})` };
}

function drawInspectionGeometry(ctx, px, py, pw, ph, rule) {
    const tol = rule.tolerance ?? 2, dev = 0.4;
    ctx.strokeStyle = '#d9a441';
    ctx.strokeRect(px - 2, py - 2, pw + 4, ph + 4);
    ctx.font = '7.5px monospace';
    ctx.fillStyle = '#d9a441';
    ctx.fillText(`W:${pw} H:${ph}`, px + 4, py - 5);
    return { isFail: Math.abs(dev) > tol, text: `Размер: откл. +${dev} мм (допуск ±${tol} мм)` };
}

function drawMeasureBboxAndCuts(ctx, px, py, pw, ph, rule) {
    const cutsH = rule.cutsH ?? 1, cutsV = rule.cutsV ?? 3;
    ctx.lineWidth = 1.5; ctx.strokeStyle = '#d9a441';
    ctx.strokeRect(px, py, pw, ph);

    const cLen = Math.min(6, Math.round(pw * 0.15));
    ctx.strokeStyle = '#f3ca6c';
    ctx.beginPath();
    ctx.moveTo(px, py + cLen); ctx.lineTo(px, py); ctx.lineTo(px + cLen, py);
    ctx.moveTo(px + pw - cLen, py); ctx.lineTo(px + pw); ctx.lineTo(px + pw, py + cLen);
    ctx.moveTo(px, py + ph - cLen); ctx.lineTo(px, py + ph); ctx.lineTo(px + cLen, py + ph);
    ctx.moveTo(px + pw - cLen, py + ph); ctx.lineTo(px + pw, py + ph); ctx.lineTo(px + pw, py + ph - cLen);
    ctx.stroke();

    const hStep = ph / (cutsH + 1);
    ctx.setLineDash([3, 2]); ctx.strokeStyle = 'rgba(217, 164, 65, 0.75)';
    for (let h = 1; h <= cutsH; h++) {
        const my = Math.round(py + h * hStep);
        ctx.beginPath(); ctx.moveTo(px - 3, my); ctx.lineTo(px + pw + 3, my); ctx.stroke();
    }
    const vStep = pw / (cutsV + 1);
    ctx.strokeStyle = 'rgba(243, 202, 108, 0.4)';
    for (let v = 1; v <= cutsV; v++) {
        const vx = Math.round(px + v * vStep);
        ctx.beginPath(); ctx.moveTo(vx, py - 3); ctx.lineTo(vx, py + ph + 3); ctx.stroke();
    }
    ctx.setLineDash([]);
}

function drawInspectionMeasure(ctx, px, py, pw, ph, rule) {
    drawMeasureBboxAndCuts(ctx, px, py, pw, ph, rule);
    const cutsV = rule.cutsV ?? 3, cutsH = rule.cutsH ?? 1;
    const tMin = rule.topMin ?? 15, tMax = rule.topMax ?? 45, bMin = rule.bottomMin ?? 15, bMax = rule.bottomMax ?? 45;
    const midY = Math.round(py + ph / (cutsH + 1)), vStep = pw / (cutsV + 1);
    let allOk = true;

    for (let v = 1; v <= cutsV; v++) {
        const vx = Math.round(px + v * vStep);
        const tVal = Math.round(midY - py), bVal = Math.round(py + ph - midY);
        const ok = tVal >= tMin && tVal <= tMax && bVal >= bMin && bVal <= bMax;
        if (!ok) allOk = false;
        ctx.strokeStyle = ctx.fillStyle = ok ? '#7ac48c' : '#e06c75';
        ctx.beginPath(); ctx.moveTo(vx, py); ctx.lineTo(vx, midY); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(vx, midY); ctx.lineTo(vx, py + ph); ctx.stroke();
        ctx.font = '7px monospace';
        ctx.fillText(`T${v}:${tVal}`, vx + 2, py + Math.round((midY - py) / 2));
        ctx.fillText(`B${v}:${bVal}`, vx + 2, midY + Math.round((py + ph - midY) / 2));
    }

    const hStep = ph / (cutsH + 1);
    for (let h = 1; h <= cutsH; h++) {
        const hy = Math.round(py + h * hStep);
        ctx.strokeStyle = ctx.fillStyle = '#7ac48c';
        ctx.beginPath(); ctx.moveTo(px, hy); ctx.lineTo(px + pw, hy); ctx.stroke();
        ctx.font = '7px monospace';
        ctx.fillText(`W${h}:${pw}px`, px + Math.round(pw / 2) - 12, hy - 3);
    }

    ctx.font = '7.5px monospace'; ctx.fillStyle = '#f3ca6c';
    ctx.fillText(`BBox ${pw}×${ph} | ${cutsV}V×${cutsH}H срез`, px, py + ph + 10);
    return {
        isFail: !allOk,
        text: `Замер ${cutsV}V×${cutsH}H: T=${Math.round(midY - py)} B=${Math.round(py + ph - midY)} W=${pw} px`
    };
}

function drawInspectionShift(ctx, px, py, pw, ph, rule) {
    const maxShift = rule.maxShift ?? 3, shiftVal = 1.2;
    const cx = Math.round(px + pw / 2), cy = Math.round(py + ph / 2);
    ctx.strokeStyle = 'rgba(165, 138, 217, 0.6)';
    ctx.beginPath(); ctx.moveTo(cx - 10, cy); ctx.lineTo(cx + 10, cy);
    ctx.moveTo(cx, cy - 10); ctx.lineTo(cx, cy + 10); ctx.stroke();
    ctx.fillStyle = '#a58ad9';
    ctx.fillRect(cx - 2, cy - 2, 4, 4);
    return { isFail: shiftVal > maxShift, text: `Смещение: ${shiftVal} px (допуск ≤ ${maxShift} px)` };
}

function drawLiveRuleInspection(ctx, w, h, inField, p, size, railY, t, rule) {
    if (!rule || !inField) return false;
    const bw = Math.round(w * size), bh = Math.round(h * 0.30);
    const bx = Math.round(w * p - bw / 2), by = railY - bh - Math.round(bh * 0.16);
    const pw = Math.round(bw * 0.54), ph = Math.round(bh * 0.46);
    const px = Math.round(bx + (bw - pw) / 2), py = Math.round(by + (bh - ph) / 2 + bh * 0.08);

    ctx.strokeStyle = 'rgba(79, 163, 209, 0.4)';
    ctx.strokeRect(px, py, pw, ph);

    let res = null;
    if (rule.mode === 'presence') res = drawInspectionPresence(ctx, px, py, pw, ph, rule);
    else if (rule.mode === 'shift') res = drawInspectionShift(ctx, px, py, pw, ph, rule);
    else if (rule.mode === 'measure') res = drawInspectionMeasure(ctx, px, py, pw, ph, rule);
    else if (rule.mode === 'geometry') res = drawInspectionGeometry(ctx, px, py, pw, ph, rule);
    else res = drawInspectionDefect(ctx, px, py, pw, ph, rule);

    window.Cameras.lastFail = res.isFail;

    ctx.fillStyle = 'rgba(15, 19, 23, 0.88)';
    ctx.fillRect(8, 8, Math.min(w - 16, 310), 36);
    ctx.strokeStyle = res.isFail ? '#e06c75' : '#58b79a';
    ctx.strokeRect(8, 8, Math.min(w - 16, 310), 36);
    ctx.font = '9.5px monospace';
    ctx.fillStyle = rule.color || '#fff';
    ctx.fillText(`● ИНСТРУМЕНТ: ${rule.name.toUpperCase()}`, 14, 21);
    ctx.font = '9px sans-serif';
    ctx.fillStyle = res.isFail ? '#e06c75' : '#58b79a';
    ctx.fillText(`${res.text} ➔ ${res.isFail ? 'БРАК' : 'ГОДНАЯ (ОК)'}`, 14, 34);
    return res.isFail;
}

/* Один кадр «камеры»: шум датчика, лента, идущий корпус.
 * Возвращает true, когда корпус в поле зрения. */
function drawFeed(ctx, w, h, seed, t, large) {
    let r = seed >>> 0;
    const rand = function () {
        r = (Math.imul(r, 1664525) + 1013904223) >>> 0;
        return r / 4294967296;
    };
    const speed = 0.06 + rand() * 0.10;
    const phase = rand();
    const size = 0.17 + rand() * 0.10;
    const flick = rand();
    const railY = Math.round(h * 0.74);

    ctx.fillStyle = '#11161b';
    ctx.fillRect(0, 0, w, h);

    drawConveyorTrack(ctx, w, h, railY, t);

    const p = ((t * speed + phase) % 1.6) - 0.3;
    const inField = p > 0.04 && p < 0.9;
    if (inField) drawWorkpiece(ctx, w, h, railY, p, size);

    drawNoiseAndScanline(ctx, w, h, rand, large, t, flick);

    if (large) {
        drawReticleOverlay(ctx, w, h, inField, p, size, railY);
        if (inField && window.BeltBridge && window.BeltBridge.getActiveRule) {
            drawLiveRuleInspection(ctx, w, h, inField, p, size, railY, t, window.BeltBridge.getActiveRule());
        }
    }
    return inField;
}

function paintMainView(t) {
    const main = $id('cam-main');
    if (!main) { return; }
    const on = fitMain(main);
    const ctx = on ? ctx2d(main) : null;
    const status = $id('cam-main-status');
    if (ctx) {
        const seen = drawFeed(ctx, main.width, main.height,
            hash('M|' + (mainId || '-')), t, true);
        if (mainId) {
            const rule = window.BeltBridge?.getActiveRule?.();
            const lastFail = window.Cameras?.lastFail;
            const canRun = window.BeltBridge ? window.BeltBridge.canRunBelt?.() : true;
            if (!canRun) {
                status.textContent = 'П0 без камеры (блокировка)';
                status.className = 'cam-tag cam-tag-br fail';
            } else if (seen && rule) {
                status.textContent = lastFail ? 'брак: ' + rule.name : 'годная';
                status.className = 'cam-tag cam-tag-br live ' + (lastFail ? 'fail' : 'pass');
            } else if (seen) {
                status.textContent = 'деталь';
                status.className = 'cam-tag cam-tag-br live';
            } else {
                status.textContent = 'пусто';
                status.className = 'cam-tag cam-tag-br';
            }
            $id('cam-main-time').textContent =
                new Date().toLocaleTimeString('ru-RU');
        } else if (status) {
            status.textContent = mainId ? 'кадр' : 'нет камер';
        }
    }
}

function paintWallThumbnails(t) {
    const wall = $id('cam-wall');
    if (!wall) { return; }
    const tiles = wall.children;
    for (let i = 0; i < tiles.length; i += 1) {
        const cv = tiles[i].querySelector('canvas');
        const det = tiles[i].querySelector('.thumb-det');
        if (!cv || !det) { continue; }
        const ready = fitThumb(cv);
        const ctx = ready ? ctx2d(cv) : null;
        if (!ctx) { continue; }
        const id = cv.dataset.cam;
        const seen = drawFeed(ctx, cv.width, cv.height,
            hash(id), t, false);
        det.classList.toggle('found', Boolean(seen && findCam(cameras, id)));
    }
}

function paint() {
    const t = ((window.performance && performance.now)
        ? performance.now() : Date.now()) / 1000;
    paintMainView(t);
    paintWallThumbnails(t);
}

function schedule() {
    if (!rafId && window.requestAnimationFrame) {
        rafId = window.requestAnimationFrame(loop);
    }
}

function loop(now) {
    rafId = 0;
    if (now - lastPaint >= PAINT_INTERVAL) {
        lastPaint = now;
        paint();
    }
    schedule();
}

window.Cameras = { sync: sync, pick: pick };
if (window.BeltBridge && window.BeltBridge.syncCameras) {
    window.BeltBridge.syncCameras();
}
schedule();

})();
