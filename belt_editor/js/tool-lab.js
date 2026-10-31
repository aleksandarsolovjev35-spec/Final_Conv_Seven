/* belt_editor/js/tool-lab.js — Лаборатория инструментов (стенд симуляции и замера фигур) */
'use strict';

(function () {
    const labState = {
        open: false,
        fig: 'window',
        topH: 30,
        botH: 28,
        w: 72,
        cutsV: 3,
        cutsH: 1,
        tolMode: 'rows',
        topMin: 15,
        topMax: 45,
        bottomMin: 15,
        bottomMax: 45,
        wMin: 50,
        wMax: 100,
        cellWMin: 15,
        cellWMax: 50,
        cellHMin: 15,
        cellHMax: 45,
        maxDelta: 4
    };

    function $id(id) { return document.getElementById(id); }

    function drawGrid(ctx, w, h) {
        ctx.fillStyle = '#0f1418';
        ctx.fillRect(0, 0, w, h);
        ctx.strokeStyle = 'rgba(120, 153, 165, 0.08)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let x = 0; x <= w; x += 16) { ctx.moveTo(x, 0); ctx.lineTo(x, h); }
        for (let y = 0; y <= h; y += 16) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
        ctx.stroke();
    }

    function drawSimulatedFigure(ctx, bx, by, bw, bh, midY) {
        ctx.fillStyle = '#222b32';
        ctx.fillRect(bx - 20, by - 16, bw + 40, bh + 32);
        ctx.fillStyle = '#0c1216';
        ctx.fillRect(bx, by, bw, bh);
        ctx.fillStyle = '#394853';
        ctx.fillRect(bx, midY - 4, bw, 8);
        ctx.strokeStyle = '#4fa3d1';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(bx, by, bw, bh);
    }

    function evaluateCellOk(cell, allCells) {
        if (labState.cutsV === 0 && labState.cutsH === 0) {
            return cell.rW >= labState.wMin && cell.rW <= labState.wMax &&
                   cell.rH >= labState.topMin && cell.rH <= (labState.topMax + labState.bottomMax);
        }
        if (labState.tolMode === 'uniform') {
            return cell.rW >= labState.cellWMin && cell.rW <= labState.cellWMax &&
                   cell.rH >= labState.cellHMin && cell.rH <= labState.cellHMax;
        }
        if (labState.tolMode === 'evenness') {
            const hs = allCells.map(c => c.rH);
            const delta = Math.max(...hs) - Math.min(...hs);
            const avg = hs.reduce((a, b) => a + b, 0) / hs.length;
            return delta <= labState.maxDelta && Math.abs(cell.rH - avg) <= (labState.maxDelta / 2 + 1);
        }
        const isTwo = (allCells.some(c => c.r === 2));
        const hOk = isTwo ? (cell.r === 1 ? (cell.rH >= labState.topMin && cell.rH <= labState.topMax) : (cell.rH >= labState.bottomMin && cell.rH <= labState.bottomMax)) : (cell.rH >= labState.topMin && cell.rH <= labState.topMax);
        const wOk = cell.rW >= Math.round(labState.wMin / (labState.cutsV + 1)) && cell.rW <= Math.round(labState.wMax / (labState.cutsV + 1));
        return hOk && wOk;
    }

    function buildGridCells(bx, by, bw, bh, midY) {
        const cutsV = labState.cutsV, cutsH = labState.cutsH;
        if (cutsV === 0 && cutsH === 0) {
            const rW = labState.w, rH = labState.topH + labState.botH;
            const cell = { r: 1, c: 1, x: bx, y: by, w: bw, h: bh, rW, rH, title: 'Область целиком' };
            cell.ok = evaluateCellOk(cell, [cell]);
            return [cell];
        }
        const cols = cutsV + 1, rows = cutsH + 1, list = [];
        const colW = bw / cols, rW = Math.round(labState.w / cols);
        for (let r = 0; r < rows; r++) {
            const isTwo = (rows === 2);
            const rowH = isTwo ? (r === 0 ? midY - by : by + bh - midY) : (bh / rows);
            const rH = isTwo ? (r === 0 ? labState.topH : labState.botH) : Math.round((labState.topH + labState.botH) / rows);
            const rowY = isTwo ? (r === 0 ? by : midY) : (by + r * (bh / rows));
            const title = isTwo ? (r === 0 ? 'Верхний ряд (T)' : 'Нижний ряд (B)') : `Клеточка [${r + 1}, c]`;
            for (let c = 0; c < cols; c++) {
                list.push({ r: r + 1, c: c + 1, x: bx + c * colW, y: rowY, w: colW, h: rowH, rW, rH, title: cols > 1 ? `${title}, кол.${c + 1}` : title });
            }
        }
        list.forEach(cell => { cell.ok = evaluateCellOk(cell, list); });
        return list;
    }

    function drawSingleCell(ctx, cell) {
        ctx.fillStyle = cell.ok ? 'rgba(122, 196, 140, 0.12)' : 'rgba(239, 68, 68, 0.16)';
        ctx.fillRect(cell.x, cell.y, cell.w, cell.h);
        ctx.strokeStyle = cell.ok ? '#7ac48c' : '#ef4444';
        ctx.lineWidth = 2.0;
        ctx.strokeRect(cell.x, cell.y, cell.w, cell.h);

        const text = `${cell.rW}×${cell.rH}px ${cell.ok ? '✓' : '✗'}`;
        ctx.font = 'bold 12.5px monospace';
        const tw = ctx.measureText(text).width;
        const xm = Math.round(cell.x + cell.w / 2), ym = Math.round(cell.y + cell.h / 2);
        ctx.fillStyle = 'rgba(8, 12, 16, 0.9)';
        ctx.fillRect(xm - Math.round(tw / 2) - 4, ym - 9, tw + 8, 18);
        ctx.fillStyle = cell.ok ? '#7ac48c' : '#ef4444';
        ctx.fillText(text, xm - Math.round(tw / 2), ym + 4);
    }

    function drawLabGridAndMeasurements(ctx, bx, by, bw, bh, midY) {
        ctx.lineWidth = 2.2; ctx.strokeStyle = '#d9a441';
        ctx.strokeRect(bx, by, bw, bh);

        const cells = buildGridCells(bx, by, bw, bh, midY);
        cells.forEach(cell => drawSingleCell(ctx, cell));

        ctx.font = 'bold 12px monospace'; ctx.fillStyle = '#f3ca6c';
        const cols = labState.cutsV + 1, rows = labState.cutsH + 1;
        const desc = (labState.cutsV === 0 && labState.cutsH === 0)
            ? `Замер области целиком (без разрезов, 1 клеточка)`
            : `Сетка: ${cols} кол. × ${rows} стр. (${cells.length} клеточек) | Режим: ${labState.tolMode.toUpperCase()}`;
        ctx.fillText(desc, bx, by + bh + 24);
        return cells;
    }

    function renderLabReport(cells) {
        const verdEl = $id('lab-verdict'), detEl = $id('lab-details');
        if (!verdEl || !detEl) return;
        const allOk = cells.every(c => c.ok);
        verdEl.className = 'lab-verdict ' + (allOk ? 'pass' : 'fail');
        verdEl.textContent = allOk ? '✓ ГОДНАЯ (ОК): ВСЕ КЛЕТОЧКИ В ДОПУСКЕ' : '✗ БРАК: ВЫЛЕТ РАЗМЕРА В КЛЕТОЧКАХ';

        detEl.innerHTML = '';
        if (labState.tolMode === 'evenness') {
            const hs = cells.map(c => c.rH);
            const delta = Math.max(...hs) - Math.min(...hs);
            const sumRow = document.createElement('div');
            sumRow.className = 'lab-report-row ' + (delta <= labState.maxDelta ? 'ok' : 'fail');
            sumRow.innerHTML = `<span>Разброс высот Δ:</span> <b style="color:${delta <= labState.maxDelta ? '#7ac48c' : '#ef4444'}">Δ = ${delta} px (норма ≤ ${labState.maxDelta} px) ${delta <= labState.maxDelta ? '✓ равномерно' : '✗ перекос'}</b>`;
            detEl.appendChild(sumRow);
        }
        cells.forEach(c => {
            const row = document.createElement('div');
            row.className = 'lab-report-row ' + (c.ok ? 'ok' : 'fail');
            row.innerHTML = `<span>${c.title}:</span> ` +
                `<b style="color:${c.ok ? '#7ac48c' : '#ef4444'}">` +
                `${c.rW} × ${c.rH} px ${c.ok ? '✓' : '✗ БРАК'}</b>`;
            detEl.appendChild(row);
        });
    }

    function computeFallbackMeasurements() {
        return buildGridCells(0, 0, 100, 100, 50);
    }

    function paintLabCanvas() {
        const cv = $id('lab-canvas');
        if (!cv || !cv.getContext) { renderLabReport(computeFallbackMeasurements()); return; }
        const ctx = cv.getContext('2d');
        if (!ctx) { renderLabReport(computeFallbackMeasurements()); return; }
        const w = cv.width, h = cv.height;

        drawGrid(ctx, w, h);

        const ZOOM = 2.4;
        const bw = Math.round(labState.w * ZOOM);
        const topH = Math.round(labState.topH * ZOOM);
        const botH = Math.round(labState.botH * ZOOM);
        const bh = topH + botH;
        const bx = Math.round((w - bw) / 2), by = Math.round((h - bh) / 2);
        const midY = by + topH;

        drawSimulatedFigure(ctx, bx, by, bw, bh, midY);
        const cells = drawLabGridAndMeasurements(ctx, bx, by, bw, bh, midY);
        renderLabReport(cells);
    }

    function updateUiValues() {
        $id('fig-val-top') && ($id('fig-val-top').textContent = labState.topH + ' px');
        $id('fig-val-bot') && ($id('fig-val-bot').textContent = labState.botH + ' px');
        $id('fig-val-w') && ($id('fig-val-w').textContent = labState.w + ' px');
        $id('lab-val-v') && ($id('lab-val-v').textContent = String(labState.cutsV));
        $id('lab-val-h') && ($id('lab-val-h').textContent = String(labState.cutsH));
        $id('lab-val-t') && ($id('lab-val-t').textContent = `${labState.topMin}–${labState.topMax} px`);
        $id('lab-val-b') && ($id('lab-val-b').textContent = `${labState.bottomMin}–${labState.bottomMax} px`);
        $id('lab-val-w') && ($id('lab-val-w').textContent = `${labState.wMin}–${labState.wMax} px`);
        $id('lab-val-cell-h') && ($id('lab-val-cell-h').textContent = `${labState.cellHMin}–${labState.cellHMax} px`);
        $id('lab-val-cell-w') && ($id('lab-val-cell-w').textContent = `${labState.cellWMin}–${labState.cellWMax} px`);
        $id('lab-val-delta') && ($id('lab-val-delta').textContent = `≤ ${labState.maxDelta} px`);

        ['rows', 'uniform', 'evenness'].forEach(m => {
            const panel = $id(`tol-panel-${m}`);
            if (panel) {
                panel.style.display = (labState.tolMode === m ? 'flex' : 'none');
                panel.classList.toggle('active', labState.tolMode === m);
            }
        });
        document.querySelectorAll('.btn-tol-mode').forEach(b => b.classList.toggle('active', b.dataset.mode === labState.tolMode));
        paintLabCanvas();
    }

    function setFigurePreset(preset) {
        labState.fig = preset;
        document.querySelectorAll('.btn-lab-fig').forEach(b => b.classList.toggle('active', b.dataset.fig === preset));
        if (preset === 'window') { labState.topH = 30; labState.botH = 28; labState.w = 72; }
        else if (preset === 'window_defect_top') { labState.topH = 52; labState.botH = 28; labState.w = 72; }
        else if (preset === 'window_defect_bot') { labState.topH = 30; labState.botH = 50; labState.w = 72; }
        else if (preset === 'rect') { labState.topH = 24; labState.botH = 24; labState.w = 88; }
        const sT = $id('fig-slider-top'), sB = $id('fig-slider-bot'), sW = $id('fig-slider-w');
        if (sT) sT.value = labState.topH;
        if (sB) sB.value = labState.botH;
        if (sW) sW.value = labState.w;
        updateUiValues();
    }

    function openLab() {
        labState.open = true;
        const ov = $id('tool-lab-overlay');
        if (ov) ov.style.display = 'flex';
        updateUiValues();
    }

    function closeLab() {
        labState.open = false;
        const ov = $id('tool-lab-overlay');
        if (ov) ov.style.display = 'none';
    }

    function wireLabEvents() {
        $id('btn-open-lab')?.addEventListener('click', openLab);
        $id('btn-open-lab-palette')?.addEventListener('click', openLab);
        $id('btn-close-lab')?.addEventListener('click', closeLab);
        $id('tool-lab-overlay')?.addEventListener('click', e => {
            if (e.target === $id('tool-lab-overlay')) closeLab();
        });

        document.querySelectorAll('.btn-lab-fig').forEach(btn => {
            btn.addEventListener('click', () => setFigurePreset(btn.dataset.fig));
        });

        $id('fig-slider-top')?.addEventListener('input', e => { labState.topH = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-bot')?.addEventListener('input', e => { labState.botH = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-w')?.addEventListener('input', e => { labState.w = parseInt(e.target.value, 10); updateUiValues(); });

        $id('lab-v-dec')?.addEventListener('click', () => { labState.cutsV = Math.max(0, labState.cutsV - 1); updateUiValues(); });
        $id('lab-v-inc')?.addEventListener('click', () => { labState.cutsV = Math.min(6, labState.cutsV + 1); updateUiValues(); });
        $id('lab-h-dec')?.addEventListener('click', () => { labState.cutsH = Math.max(0, labState.cutsH - 1); updateUiValues(); });
        $id('lab-h-inc')?.addEventListener('click', () => { labState.cutsH = Math.min(4, labState.cutsH + 1); updateUiValues(); });

        $id('lab-t-dec')?.addEventListener('click', () => { labState.topMin = Math.max(5, labState.topMin - 2); labState.topMax = Math.max(labState.topMin + 5, labState.topMax - 2); updateUiValues(); });
        $id('lab-t-inc')?.addEventListener('click', () => { labState.topMin = Math.min(30, labState.topMin + 2); labState.topMax = Math.min(60, labState.topMax + 2); updateUiValues(); });
        $id('lab-b-dec')?.addEventListener('click', () => { labState.bottomMin = Math.max(5, labState.bottomMin - 2); labState.bottomMax = Math.max(labState.bottomMin + 5, labState.bottomMax - 2); updateUiValues(); });
        $id('lab-b-inc')?.addEventListener('click', () => { labState.bottomMin = Math.min(30, labState.bottomMin + 2); labState.bottomMax = Math.min(60, labState.bottomMax + 2); updateUiValues(); });

        $id('lab-w-dec')?.addEventListener('click', () => { labState.wMin = Math.max(20, labState.wMin - 5); labState.wMax = Math.max(labState.wMin + 10, labState.wMax - 5); updateUiValues(); });
        $id('lab-w-inc')?.addEventListener('click', () => { labState.wMin = Math.min(80, labState.wMin + 5); labState.wMax = Math.min(140, labState.wMax + 5); updateUiValues(); });

        document.querySelectorAll('.btn-tol-mode').forEach(b => {
            b.addEventListener('click', () => { labState.tolMode = b.dataset.mode; updateUiValues(); });
        });
        $id('lab-cell-h-dec')?.addEventListener('click', () => { labState.cellHMin = Math.max(5, labState.cellHMin - 2); labState.cellHMax = Math.max(labState.cellHMin + 5, labState.cellHMax - 2); updateUiValues(); });
        $id('lab-cell-h-inc')?.addEventListener('click', () => { labState.cellHMin = Math.min(30, labState.cellHMin + 2); labState.cellHMax = Math.min(60, labState.cellHMax + 2); updateUiValues(); });
        $id('lab-cell-w-dec')?.addEventListener('click', () => { labState.cellWMin = Math.max(5, labState.cellWMin - 2); labState.cellWMax = Math.max(labState.cellWMin + 5, labState.cellWMax - 2); updateUiValues(); });
        $id('lab-cell-w-inc')?.addEventListener('click', () => { labState.cellWMin = Math.min(40, labState.cellWMin + 2); labState.cellWMax = Math.min(80, labState.cellWMax + 2); updateUiValues(); });
        $id('lab-delta-dec')?.addEventListener('click', () => { labState.maxDelta = Math.max(1, labState.maxDelta - 1); updateUiValues(); });
        $id('lab-delta-inc')?.addEventListener('click', () => { labState.maxDelta = Math.min(15, labState.maxDelta + 1); updateUiValues(); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireLabEvents);
    } else {
        wireLabEvents();
    }

    window.ToolLab = { open: openLab, close: closeLab, state: () => labState, setPreset: setFigurePreset };
})();
