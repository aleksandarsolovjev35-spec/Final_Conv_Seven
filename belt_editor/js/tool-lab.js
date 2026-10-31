/* belt_editor/js/tool-lab.js — Лаборатория: визуально чистый и понятный стенд */
'use strict';

(function () {
    const labState = {
        open: false,
        figW: 72,
        figH: 58,
        figD1: 30,
        figD2: 28,
        tolX: 42,
        tolY: 34,
        lineMode: 'none',
        lineTolMin1: 20,
        lineTolMax1: 35,
        lineTolMin2: 20,
        lineTolMax2: 35
    };

    function $id(id) { return document.getElementById(id); }

    function drawCanvasGrid(ctx, w, h) {
        ctx.fillStyle = '#0c1216';
        ctx.fillRect(0, 0, w, h);
        ctx.strokeStyle = 'rgba(120, 153, 165, 0.08)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let x = 0; x <= w; x += 20) { ctx.moveTo(x, 0); ctx.lineTo(x, h); }
        for (let y = 0; y <= h; y += 20) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
        ctx.stroke();
    }

    function drawCenteredAxes(ctx, xc, yc) {
        ctx.strokeStyle = '#334155';
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(50, yc); ctx.lineTo(550, yc);
        ctx.moveTo(550, yc); ctx.lineTo(543, yc - 3);
        ctx.moveTo(550, yc); ctx.lineTo(543, yc + 3);
        ctx.moveTo(xc, 305); ctx.lineTo(xc, 30);
        ctx.moveTo(xc, 30); ctx.lineTo(xc - 3, 37);
        ctx.moveTo(xc, 30); ctx.lineTo(xc + 3, 37);
        ctx.stroke();

        ctx.font = '11px monospace';
        ctx.fillStyle = '#64748b';
        ctx.fillText('X', 554, yc + 4);
        ctx.fillText('Y', xc + 6, 32);
        ctx.fillText('0', xc + 5, yc + 13);
    }

    function drawLineTolZone(ctx, xc, yc, scale) {
        ctx.strokeStyle = 'rgba(34, 197, 94, 0.85)';
        ctx.lineWidth = 1.8;
        ctx.setLineDash([5, 4]);

        if (labState.lineMode === 'horiz') {
            const dx = (labState.figW / 2) * scale;
            const yTopTol = yc - labState.lineTolMax1 * scale;
            const yBotTol = yc + labState.lineTolMax2 * scale;
            ctx.strokeRect(xc - dx, yTopTol, dx * 2, yBotTol - yTopTol);
            ctx.fillStyle = 'rgba(34, 197, 94, 0.05)';
            ctx.fillRect(xc - dx, yTopTol, dx * 2, yBotTol - yTopTol);
        } else if (labState.lineMode === 'vert') {
            const dy = (labState.figH / 2) * scale;
            const xLeftTol = xc - labState.lineTolMax1 * scale;
            const xRightTol = xc + labState.lineTolMax2 * scale;
            ctx.strokeRect(xLeftTol, yc - dy, xRightTol - xLeftTol, dy * 2);
            ctx.fillStyle = 'rgba(34, 197, 94, 0.05)';
            ctx.fillRect(xLeftTol, yc - dy, xRightTol - xLeftTol, dy * 2);
        }
        ctx.setLineDash([]);
    }

    function drawToleranceZone(ctx, xc, yc, scale) {
        if (labState.lineMode !== 'none') {
            drawLineTolZone(ctx, xc, yc, scale);
            return;
        }
        const tx = labState.tolX * scale, ty = labState.tolY * scale;
        ctx.strokeStyle = 'rgba(34, 197, 94, 0.85)';
        ctx.lineWidth = 1.8;
        ctx.setLineDash([5, 4]);
        ctx.strokeRect(xc - tx, yc - ty, tx * 2, ty * 2);
        ctx.fillStyle = 'rgba(34, 197, 94, 0.05)';
        ctx.fillRect(xc - tx, yc - ty, tx * 2, ty * 2);
        ctx.setLineDash([]);
    }

    function drawArrowV(ctx, x, y1, y2, color, text) {
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(x, y1); ctx.lineTo(x, y2);
        ctx.moveTo(x - 3, y1 + 5); ctx.lineTo(x, y1); ctx.lineTo(x + 3, y1 + 5);
        ctx.moveTo(x - 3, y2 - 5); ctx.lineTo(x, y2); ctx.lineTo(x + 3, y2 - 5);
        ctx.stroke();
        ctx.font = 'bold 12.5px monospace';
        ctx.fillText(text, x + 8, (y1 + y2) / 2 + 4);
    }

    function drawArrowH(ctx, y, x1, x2, color, text) {
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(x1, y); ctx.lineTo(x2, y);
        ctx.moveTo(x1 + 5, y - 3); ctx.lineTo(x1, y); ctx.lineTo(x1 + 5, y + 3);
        ctx.moveTo(x2 - 5, y - 3); ctx.lineTo(x2, y); ctx.lineTo(x2 - 5, y + 3);
        ctx.stroke();
        ctx.font = 'bold 12.5px monospace';
        const tw = ctx.measureText(text).width;
        ctx.fillText(text, (x1 + x2) / 2 - tw / 2, y - 7);
    }

    function drawHorizLineMeasures(ctx, xc, yc, scale, dx) {
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 1.8;
        ctx.setLineDash([5, 3]);
        ctx.beginPath();
        ctx.moveTo(xc - dx - 12, yc); ctx.lineTo(xc + dx + 12, yc);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 11px monospace';
        ctx.fillText('L', xc + dx + 14, yc + 4);

        const d1 = labState.figD1, d2 = labState.figD2;
        const d1Ok = d1 >= labState.lineTolMin1 && d1 <= labState.lineTolMax1;
        const d2Ok = d2 >= labState.lineTolMin2 && d2 <= labState.lineTolMax2;

        const yTop = yc - d1 * scale, yBot = yc + d2 * scale;
        const xDim = xc + dx + 22;
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xc + dx, yTop); ctx.lineTo(xDim + 6, yTop);
        ctx.moveTo(xc + dx, yc); ctx.lineTo(xDim + 6, yc);
        ctx.moveTo(xc + dx, yBot); ctx.lineTo(xDim + 6, yBot);
        ctx.stroke();

        drawArrowV(ctx, xDim, yTop, yc, d1Ok ? '#22c55e' : '#ef4444', `${d1} px`);
        drawArrowV(ctx, xDim, yc, yBot, d2Ok ? '#22c55e' : '#ef4444', `${d2} px`);

        return { ok: d1Ok && d2Ok, d1Ok, d2Ok, yTop, yBot };
    }

    function drawVertLineMeasures(ctx, xc, yc, scale, dy) {
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 1.8;
        ctx.setLineDash([5, 3]);
        ctx.beginPath();
        ctx.moveTo(xc, yc - dy - 12); ctx.lineTo(xc, yc + dy + 12);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 11px monospace';
        ctx.fillText('L', xc - 4, yc - dy - 14);

        const d1 = labState.figD1, d2 = labState.figD2;
        const d1Ok = d1 >= labState.lineTolMin1 && d1 <= labState.lineTolMax1;
        const d2Ok = d2 >= labState.lineTolMin2 && d2 <= labState.lineTolMax2;

        const xLeft = xc - d1 * scale, xRight = xc + d2 * scale;
        const yDim = yc - dy - 18;
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xLeft, yc - dy); ctx.lineTo(xLeft, yDim - 6);
        ctx.moveTo(xc, yc - dy); ctx.lineTo(xc, yDim - 6);
        ctx.moveTo(xRight, yc - dy); ctx.lineTo(xRight, yDim - 6);
        ctx.stroke();

        drawArrowH(ctx, yDim, xLeft, xc, d1Ok ? '#22c55e' : '#ef4444', `${d1} px`);
        drawArrowH(ctx, yDim, xc, xRight, d2Ok ? '#22c55e' : '#ef4444', `${d2} px`);

        return { ok: d1Ok && d2Ok, d1Ok, d2Ok, xLeft, xRight };
    }

    function evaluateVerdictAndFigure(ctx, xc, yc, scale) {
        let allOk = false, verdict = '', fx = 0, fy = 0, fw = 0, fh = 0;
        if (labState.lineMode === 'horiz') {
            const dx = (labState.figW / 2) * scale;
            const r = drawHorizLineMeasures(ctx, xc, yc, scale, dx);
            allOk = r.ok;
            verdict = allOk ? '✓ ГОДНАЯ' : (!r.d1Ok ? '✗ ВЫЛЕТ ДО' : '✗ ВЫЛЕТ ОТ');
            fx = xc - dx; fy = r.yTop; fw = dx * 2; fh = r.yBot - r.yTop;
        } else if (labState.lineMode === 'vert') {
            const dy = (labState.figH / 2) * scale;
            const r = drawVertLineMeasures(ctx, xc, yc, scale, dy);
            allOk = r.ok;
            verdict = allOk ? '✓ ГОДНАЯ' : (!r.d1Ok ? '✗ ВЫЛЕТ ДО' : '✗ ВЫЛЕТ ОТ');
            fx = r.xLeft; fy = yc - dy; fw = r.xRight - r.xLeft; fh = dy * 2;
        } else {
            const dx = (labState.figW / 2) * scale, dy = (labState.figH / 2) * scale;
            const xOk = (labState.figW / 2) <= labState.tolX, yOk = (labState.figH / 2) <= labState.tolY;
            allOk = xOk && yOk;
            verdict = allOk ? '✓ ГОДНАЯ' : (!xOk ? '✗ ВЫЛЕТ X' : '✗ ВЫЛЕТ Y');
            fx = xc - dx; fy = yc - dy; fw = dx * 2; fh = dy * 2;
        }

        ctx.fillStyle = allOk ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.16)';
        ctx.fillRect(fx, fy, fw, fh);
        ctx.strokeStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 2.4;
        ctx.strokeRect(fx, fy, fw, fh);

        ctx.fillStyle = allOk ? 'rgba(34, 197, 94, 0.18)' : 'rgba(239, 68, 68, 0.22)';
        ctx.fillRect(450, 16, 130, 26);
        ctx.strokeStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 1.2;
        ctx.strokeRect(450, 16, 130, 26);
        ctx.fillStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.font = 'bold 12px monospace';
        ctx.fillText(verdict, 462, 33);

        return { fx, fy, fw, fh };
    }

    function drawCenteredFigure(ctx, xc, yc, scale) {
        const f = evaluateVerdictAndFigure(ctx, xc, yc, scale);
        ctx.font = 'bold 12px monospace';
        ctx.fillStyle = '#94a3b8';
        if (labState.lineMode === 'none') {
            const txt = `${labState.figW} × ${labState.figH} px`;
            const tw = ctx.measureText(txt).width;
            ctx.fillText(txt, xc - tw / 2, yc + 4);
        } else if (labState.lineMode === 'horiz') {
            const txt = `W = ${labState.figW} px`;
            const tw = ctx.measureText(txt).width;
            ctx.fillText(txt, xc - tw / 2, f.fy + f.fh + 18);
        } else {
            const txt = `H = ${labState.figH} px`;
            const tw = ctx.measureText(txt).width;
            ctx.fillText(txt, xc - tw / 2, f.fy + f.fh + 18);
        }
    }

    function paintLabCanvas() {
        const cv = $id('lab-canvas');
        if (!cv || !cv.getContext) return;
        const ctx = cv.getContext('2d');
        if (!ctx) return;
        const w = cv.width, h = cv.height;
        const xc = 300, yc = 170, scale = 2.4;

        drawCanvasGrid(ctx, w, h);
        drawCenteredAxes(ctx, xc, yc);
        drawToleranceZone(ctx, xc, yc, scale);
        drawCenteredFigure(ctx, xc, yc, scale);
    }

    function updateUiValues() {
        const isLine = labState.lineMode !== 'none';
        const isHoriz = labState.lineMode === 'horiz';
        const isVert = labState.lineMode === 'vert';

        $id('fig-row-w') && ($id('fig-row-w').style.display = isVert ? 'none' : 'flex');
        $id('fig-row-h') && ($id('fig-row-h').style.display = isHoriz ? 'none' : (isVert ? 'flex' : 'flex'));
        $id('fig-row-d1') && ($id('fig-row-d1').style.display = isLine ? 'flex' : 'none');
        $id('fig-row-d2') && ($id('fig-row-d2').style.display = isLine ? 'flex' : 'none');

        $id('fig-val-w') && ($id('fig-val-w').textContent = `${labState.figW} px (±${(labState.figW / 2).toFixed(0)} px)`);
        $id('fig-val-h') && ($id('fig-val-h').textContent = `${labState.figH} px (±${(labState.figH / 2).toFixed(0)} px)`);
        $id('fig-val-d1') && ($id('fig-val-d1').textContent = `${labState.figD1} px`);
        $id('fig-val-d2') && ($id('fig-val-d2').textContent = `${labState.figD2} px`);

        const lbl1 = $id('lab-lbl-tol-1'), lbl2 = $id('lab-lbl-tol-2'), hint = $id('lab-hint-text');
        if (lbl1) lbl1.textContent = isLine ? 'Параметр 1 — Допуск ДО линии:' : 'Параметр 1 — Допуск X (от центра 0):';
        if (lbl2) lbl2.textContent = isLine ? 'Параметр 2 — Допуск ОТ линии:' : 'Параметр 2 — Допуск Y (от центра 0):';
        if (hint) hint.textContent = isLine ? 'Замеры проводятся строго ДО опорной линии и ОТ неё. На чертеже видны размерные стрелки.' : 'Центр области зафиксирован в точке (0, 0). Контролируется симметричное отклонение краев ±X и ±Y от центра.';

        const val1 = isLine ? `${labState.lineTolMin1}–${labState.lineTolMax1} px` : `±${labState.tolX} px (W ≤ ${labState.tolX * 2} px)`;
        const val2 = isLine ? `${labState.lineTolMin2}–${labState.lineTolMax2} px` : `±${labState.tolY} px (H ≤ ${labState.tolY * 2} px)`;
        $id('lab-val-tol-x') && ($id('lab-val-tol-x').textContent = val1);
        $id('lab-val-tol-y') && ($id('lab-val-tol-y').textContent = val2);

        document.querySelectorAll('.btn-line-mode').forEach(b => b.classList.toggle('active', b.dataset.mode === labState.lineMode));
        paintLabCanvas();
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

        document.querySelectorAll('.btn-line-mode').forEach(b => {
            b.addEventListener('click', () => { labState.lineMode = b.dataset.mode; updateUiValues(); });
        });

        $id('fig-slider-w')?.addEventListener('input', e => { labState.figW = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-h')?.addEventListener('input', e => { labState.figH = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-d1')?.addEventListener('input', e => { labState.figD1 = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-d2')?.addEventListener('input', e => { labState.figD2 = parseInt(e.target.value, 10); updateUiValues(); });

        $id('lab-tol-x-dec')?.addEventListener('click', () => {
            if (labState.lineMode !== 'none') { labState.lineTolMin1 = Math.max(5, labState.lineTolMin1 - 1); labState.lineTolMax1 = Math.max(labState.lineTolMin1 + 5, labState.lineTolMax1 - 1); }
            else { labState.tolX = Math.max(15, labState.tolX - 2); }
            updateUiValues();
        });
        $id('lab-tol-x-inc')?.addEventListener('click', () => {
            if (labState.lineMode !== 'none') { labState.lineTolMin1 = Math.min(30, labState.lineTolMin1 + 1); labState.lineTolMax1 = Math.min(55, labState.lineTolMax1 + 1); }
            else { labState.tolX = Math.min(70, labState.tolX + 2); }
            updateUiValues();
        });

        $id('lab-tol-y-dec')?.addEventListener('click', () => {
            if (labState.lineMode !== 'none') { labState.lineTolMin2 = Math.max(5, labState.lineTolMin2 - 1); labState.lineTolMax2 = Math.max(labState.lineTolMin2 + 5, labState.lineTolMax2 - 1); }
            else { labState.tolY = Math.max(10, labState.tolY - 2); }
            updateUiValues();
        });
        $id('lab-tol-y-inc')?.addEventListener('click', () => {
            if (labState.lineMode !== 'none') { labState.lineTolMin2 = Math.min(30, labState.lineTolMin2 + 1); labState.lineTolMax2 = Math.min(55, labState.lineTolMax2 + 1); }
            else { labState.tolY = Math.min(50, labState.tolY + 2); }
            updateUiValues();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', wireLabEvents);
    } else {
        wireLabEvents();
    }

    window.ToolLab = { open: openLab, close: closeLab, state: () => labState };
})();
