/* belt_editor/js/cameras.js — видеостена.
 *
 * Слева сверху — основная камера крупным планом: это камера входного
 * (основного) места инспекции, по ней считается наличие детали. Справа —
 * стена всех обнаруженных камер ленты; клик по плитке переключает
 * крупный план. Кадры симулированы (корпус едет по ленте, датчик шумит):
 * реальный бэкенд позже подключится заменой drawFeed на /stream/*.
 */
'use strict';

(function () {

const PAINT_INTERVAL = 90;

let cameras = [];
let mainRole = null;
let rafId = 0;
let lastPaint = 0;

function $id(id) { return document.getElementById(id); }

function findCam(list, role) {
    for (let i = 0; i < list.length; i += 1) {
        if (list[i].role === role) { return list[i]; }
    }
    return null;
}

/* Основная — первая камера входного места; если входа нет — первая из
 * обнаруженных. */
function entryRole(list) {
    for (let i = 0; i < list.length; i += 1) {
        if (list[i].primary) { return list[i].role; }
    }
    return list.length ? list[0].role : null;
}

/* ─── Синхронизация с лентой ──────────────────────────────────────── */

function sync(list) {
    cameras = list || [];
    if (!findCam(cameras, mainRole)) { mainRole = entryRole(cameras); }
    buildMain();
    buildWall();
    schedule();
}

function pick(role) {
    mainRole = role;
    buildMain();
    buildWall();
    schedule();
}

/* ─── Панели ──────────────────────────────────────────────────────── */

function buildMain() {
    const cam = findCam(cameras, mainRole);
    $id('cam-main-role').textContent = cam
        ? cam.role + ' · П' + cam.position + (cam.primary ? ' · вход' : '')
        : 'камер нет';
}

function buildWall() {
    const wall = $id('cam-wall');
    wall.textContent = '';
    cameras.forEach(function (cam) {
        const tile = document.createElement('div');
        tile.className = 'thumb' + (cam.role === mainRole ? ' main' : '');
        const canvas = document.createElement('canvas');
        canvas.dataset.role = cam.role;
        const name = document.createElement('span');
        name.className = 'thumb-role';
        name.textContent = cam.role;
        const det = document.createElement('span');
        det.className = 'thumb-det';
        tile.appendChild(canvas);
        tile.appendChild(name);
        tile.appendChild(det);
        tile.addEventListener('click', function () { pick(cam.role); });
        wall.appendChild(tile);
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

    ctx.fillStyle = '#11161b';
    ctx.fillRect(0, 0, w, h);

    const railY = Math.round(h * 0.74);
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

    const p = ((t * speed + phase) % 1.6) - 0.3;
    const inField = p > 0.04 && p < 0.9;
    if (inField) {
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
            ctx.fillRect(bx + Math.round(bw * (0.08 + 0.20 * k)),
                railY, legW, Math.round(h * 0.045));
        }
    }

    for (let i = 0; i < (large ? 90 : 16); i += 1) {
        ctx.fillStyle = 'rgba(255,255,255,' + (rand() * 0.05).toFixed(3) + ')';
        ctx.fillRect(Math.round(rand() * w), Math.round(rand() * h), 1, 1);
    }

    const scanY = ((t * 0.22 + flick) % 1) * h;
    ctx.fillStyle = 'rgba(120, 153, 165, 0.055)';
    ctx.fillRect(0, scanY, w, Math.max(2, Math.round(h * 0.025)));

    if (large) {
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
    return inField;
}

function paint() {
    const t = ((window.performance && performance.now)
        ? performance.now() : Date.now()) / 1000;

    const main = $id('cam-main');
    if (main) {
        const on = fitMain(main);
        const ctx = on ? ctx2d(main) : null;
        const status = $id('cam-main-status');
        if (ctx) {
            const seen = drawFeed(ctx, main.width, main.height,
                hash('M|' + (mainRole || '-')), t, true);
            if (mainRole) {
                status.textContent = seen ? 'деталь' : 'пусто';
                status.className = 'cam-tag cam-tag-br' + (seen ? ' live' : '');
            } else {
                status.textContent = 'нет камер';
                status.className = 'cam-tag cam-tag-br';
            }
            $id('cam-main-time').textContent =
                new Date().toLocaleTimeString('ru-RU');
        } else if (status) {
            status.textContent = mainRole ? 'кадр' : 'нет камер';
        }
    }

    const wall = $id('cam-wall');
    if (wall) {
        const tiles = wall.children;
        for (let i = 0; i < tiles.length; i += 1) {
            const cv = tiles[i].querySelector('canvas');
            const det = tiles[i].querySelector('.thumb-det');
            if (!cv || !det) { continue; }
            const ready = fitThumb(cv);
            const ctx = ready ? ctx2d(cv) : null;
            if (!ctx) { continue; }
            const role = cv.dataset.role;
            const seen = drawFeed(ctx, cv.width, cv.height,
                hash(role), t, false);
            det.classList.toggle('found',
                Boolean(seen && findCam(cameras, role)));
        }
    }
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
schedule();

})();
