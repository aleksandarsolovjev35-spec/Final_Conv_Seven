/* belt_editor/js/tool-lab.js — Лаборатория: корректные замеры до и от опорной линии */
'use strict';

(function () {
    const labState = {
        open: false,
        figW: 72,
        figH: 58,
        tolX: 42,
        tolY: 34,
        lineMode: 'none',
        lineOffset: 0,
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
        for (let x = 0; x <= w; x += 16) { ctx.moveTo(x, 0); ctx.lineTo(x, h); }
        for (let y = 0; y <= h; y += 16) { ctx.moveTo(0, y); ctx.lineTo(w, y); }
        ctx.stroke();
    }

    function drawCenteredAxes(ctx, xc, yc, scale) {
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(40, yc); ctx.lineTo(560, yc);
        ctx.moveTo(560, yc); ctx.lineTo(552, yc - 4);
        ctx.moveTo(560, yc); ctx.lineTo(552, yc + 4);
        ctx.moveTo(xc, 310); ctx.lineTo(xc, 25);
        ctx.moveTo(xc, 25); ctx.lineTo(xc - 4, 33);
        ctx.moveTo(xc, 25); ctx.lineTo(xc + 4, 33);
        ctx.stroke();

        ctx.font = 'bold 11px monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText('+X →', 562, yc + 4);
        ctx.fillText('← −X', 12, yc + 4);
        ctx.fillText('↑ +Y', xc + 8, 28);
        ctx.fillText('↓ −Y', xc + 8, 320);
        ctx.fillText('0 (центр)', xc + 6, yc + 15);

        for (let px = 20; px <= 80; px += 20) {
            const dx = px * scale;
            ctx.beginPath();
            ctx.moveTo(xc + dx, yc - 3); ctx.lineTo(xc + dx, yc + 3);
            ctx.moveTo(xc - dx, yc - 3); ctx.lineTo(xc - dx, yc + 3);
            ctx.stroke();
            ctx.fillText('+' + px, xc + dx - 10, yc + 15);
            ctx.fillText('−' + px, xc - dx - 10, yc + 15);
        }
        for (let py = 20; py <= 60; py += 20) {
            const dy = py * scale;
            ctx.beginPath();
            ctx.moveTo(xc - 3, yc - dy); ctx.lineTo(xc + 3, yc - dy);
            ctx.moveTo(xc - 3, yc + dy); ctx.lineTo(xc + 3, yc + dy);
            ctx.stroke();
            ctx.fillText('+' + py, xc - 28, yc - dy + 4);
            ctx.fillText('−' + py, xc - 28, yc + dy + 4);
        }
    }

    function drawToleranceZone(ctx, xc, yc, scale) {
        if (labState.lineMode !== 'none') return;
        const tx = labState.tolX * scale, ty = labState.tolY * scale;
        ctx.strokeStyle = '#22c55e';
        ctx.lineWidth = 1.8;
        ctx.setLineDash([5, 4]);
        ctx.strokeRect(xc - tx, yc - ty, tx * 2, ty * 2);
        ctx.setLineDash([]);

        ctx.fillStyle = 'rgba(34, 197, 94, 0.15)';
        ctx.fillRect(xc - tx, yc - 4, tx * 2, 8);
        ctx.fillRect(xc - 4, yc - ty, 8, ty * 2);

        ctx.beginPath();
        ctx.moveTo(xc - tx, yc - 8); ctx.lineTo(xc - tx, yc + 8);
        ctx.moveTo(xc + tx, yc - 8); ctx.lineTo(xc + tx, yc + 8);
        ctx.moveTo(xc - 8, yc - ty); ctx.lineTo(xc + 8, yc - ty);
        ctx.moveTo(xc - 8, yc + ty); ctx.lineTo(xc + 8, yc + ty);
        ctx.stroke();

        ctx.font = 'bold 11px monospace';
        ctx.fillStyle = '#22c55e';
        ctx.fillText(`допуск X: ±${labState.tolX} px`, xc + tx - 40, yc - ty - 6);
    }

    function drawArrowV(ctx, x, y1, y2, color, text) {
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(x, y1); ctx.lineTo(x, y2);
        ctx.moveTo(x - 3, y1 + 5); ctx.lineTo(x, y1); ctx.lineTo(x + 3, y1 + 5);
        ctx.moveTo(x - 3, y2 - 5); ctx.lineTo(x, y2); ctx.lineTo(x + 3, y2 - 5);
        ctx.stroke();
        ctx.font = 'bold 11.5px monospace';
        ctx.fillText(text, x + 8, (y1 + y2) / 2 + 4);
    }

    function drawArrowH(ctx, y, x1, x2, color, text) {
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(x1, y); ctx.lineTo(x2, y);
        ctx.moveTo(x1 + 5, y - 3); ctx.lineTo(x1, y); ctx.lineTo(x1 + 5, y + 3);
        ctx.moveTo(x2 - 5, y - 3); ctx.lineTo(x2, y); ctx.lineTo(x2 - 5, y + 3);
        ctx.stroke();
        ctx.font = 'bold 11.5px monospace';
        const tw = ctx.measureText(text).width;
        ctx.fillText(text, (x1 + x2) / 2 - tw / 2, y - 7);
    }

    function drawHorizLineMeasures(ctx, xc, yc, scale, hh, dx, dy) {
        const yLine = yc - labState.lineOffset * scale;
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2.0;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(xc - dx - 16, yLine); ctx.lineTo(xc + dx + 16, yLine);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 11px monospace';
        ctx.fillText(`[ЛИНИЯ Y=${labState.lineOffset > 0 ? '+' : ''}${labState.lineOffset}]`, xc - dx - 105, yLine + 4);

        const d1 = Math.round(hh - labState.lineOffset);
        const d2 = Math.round(hh + labState.lineOffset);
        const d1Ok = d1 >= labState.lineTolMin1 && d1 <= labState.lineTolMax1;
        const d2Ok = d2 >= labState.lineTolMin2 && d2 <= labState.lineTolMax2;

        const xDim = xc + dx + 26;
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xc + dx, yc - dy); ctx.lineTo(xDim + 8, yc - dy);
        ctx.moveTo(xc + dx, yLine); ctx.lineTo(xDim + 8, yLine);
        ctx.moveTo(xc + dx, yc + dy); ctx.lineTo(xDim + 8, yc + dy);
        ctx.stroke();

        drawArrowV(ctx, xDim, yc - dy, yLine, d1Ok ? '#22c55e' : '#ef4444', `ДО: ${d1}px ${d1Ok ? '✓' : '✗'}`);
        drawArrowV(ctx, xDim, yLine, yc + dy, d2Ok ? '#22c55e' : '#ef4444', `ОТ: ${d2}px ${d2Ok ? '✓' : '✗'}`);

        return { ok: d1Ok && d2Ok, d1, d2, d1Ok, d2Ok };
    }

    function drawVertLineMeasures(ctx, xc, yc, scale, hw, dx, dy) {
        const xLine = xc + labState.lineOffset * scale;
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2.0;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(xLine, yc - dy - 16); ctx.lineTo(xLine, yc + dy + 16);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 11px monospace';
        ctx.fillText(`[ЛИНИЯ X=${labState.lineOffset > 0 ? '+' : ''}${labState.lineOffset}]`, xLine - 35, yc + dy + 22);

        const d1 = Math.round(hw + labState.lineOffset);
        const d2 = Math.round(hw - labState.lineOffset);
        const d1Ok = d1 >= labState.lineTolMin1 && d1 <= labState.lineTolMax1;
        const d2Ok = d2 >= labState.lineTolMin2 && d2 <= labState.lineTolMax2;

        const yDim = yc - dy - 22;
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(xc - dx, yc - dy); ctx.lineTo(xc - dx, yDim - 6);
        ctx.moveTo(xLine, yc - dy); ctx.lineTo(xLine, yDim - 6);
        ctx.moveTo(xc + dx, yc - dy); ctx.lineTo(xc + dx, yDim - 6);
        ctx.stroke();

        drawArrowH(ctx, yDim, xc - dx, xLine, d1Ok ? '#22c55e' : '#ef4444', `ДО: ${d1}px ${d1Ok ? '✓' : '✗'}`);
        drawArrowH(ctx, yDim, xLine, xc + dx, d2Ok ? '#22c55e' : '#ef4444', `ОТ: ${d2}px ${d2Ok ? '✓' : '✗'}`);

        return { ok: d1Ok && d2Ok, d1, d2, d1Ok, d2Ok };
    }

    function evaluateVerdictAndFigure(ctx, xc, yc, dx, dy, hw, hh) {
        let allOk = false, verdict = '';
        if (labState.lineMode === 'horiz') {
            const r = drawHorizLineMeasures(ctx, xc, yc, 2.4, hh, dx, dy);
            allOk = r.ok;
            verdict = allOk ? '✓ ГОДНАЯ (ОК)' : (!r.d1Ok && !r.d2Ok ? '✗ БРАК (ВЫЛЕТ ДО И ОТ)' : (!r.d1Ok ? `✗ ВЫЛЕТ ДО (${r.d1}px)` : `✗ ВЫЛЕТ ОТ (${r.d2}px)`));
        } else if (labState.lineMode === 'vert') {
            const r = drawVertLineMeasures(ctx, xc, yc, 2.4, hw, dx, dy);
            allOk = r.ok;
            verdict = allOk ? '✓ ГОДНАЯ (ОК)' : (!r.d1Ok && !r.d2Ok ? '✗ БРАК (ВЫЛЕТ ДО И ОТ)' : (!r.d1Ok ? `✗ ВЫЛЕТ ДО (${r.d1}px)` : `✗ ВЫЛЕТ ОТ (${r.d2}px)`));
        } else {
            const xOk = hw <= labState.tolX, yOk = hh <= labState.tolY;
            allOk = xOk && yOk;
            verdict = allOk ? '✓ ГОДНАЯ (ОК)' : (!xOk && !yOk ? '✗ БРАК (ВЫЛЕТ X И Y)' : (!xOk ? '✗ БРАК (ВЫЛЕТ X)' : '✗ БРАК (ВЫЛЕТ Y)'));
        }

        ctx.fillStyle = allOk ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.15)';
        ctx.fillRect(xc - dx, yc - dy, dx * 2, dy * 2);
        ctx.strokeStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 2.4;
        ctx.strokeRect(xc - dx, yc - dy, dx * 2, dy * 2);

        ctx.fillStyle = allOk ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.25)';
        ctx.fillRect(360, 18, 225, 30);
        ctx.strokeStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(360, 18, 225, 30);
        ctx.fillStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.font = 'bold 12px monospace';
        ctx.fillText(verdict, 370, 38);
    }

    function drawCenteredFigure(ctx, xc, yc, scale) {
        const hw = labState.figW / 2, hh = labState.figH / 2;
        const dx = hw * scale, dy = hh * scale;

        evaluateVerdictAndFigure(ctx, xc, yc, dx, dy, hw, hh);

        ctx.beginPath();
        ctx.moveTo(xc - 5, yc); ctx.lineTo(xc + 5, yc);
        ctx.moveTo(xc, yc - 5); ctx.lineTo(xc, yc + 5);
        ctx.stroke();

        ctx.font = 'bold 12.5px monospace';
        ctx.fillStyle = '#cbd5e1';
        const txt = `${labState.figW} × ${labState.figH} px (±${hw} / ±${hh})`;
        const tw = ctx.measureText(txt).width;
        ctx.fillText(txt, xc - tw / 2, yc + dy + 18);
    }

    function paintLabCanvas() {
        const cv = $id('lab-canvas');
        if (!cv || !cv.getContext) return;
        const ctx = cv.getContext('2d');
        if (!ctx) return;
        const w = cv.width, h = cv.height;
        const xc = 300, yc = 170, scale = 2.4;

        drawCanvasGrid(ctx, w, h);
        drawCenteredAxes(ctx, xc, yc, scale);
        drawToleranceZone(ctx, xc, yc, scale);
        drawCenteredFigure(ctx, xc, yc, scale);
    }

    function updateUiValues() {
        const hw = (labState.figW / 2).toFixed(0), hh = (labState.figH / 2).toFixed(0);
        $id('fig-val-w') && ($id('fig-val-w').textContent = `${labState.figW} px (±${hw} px)`);
        $id('fig-val-h') && ($id('fig-val-h').textContent = `${labState.figH} px (±${hh} px)`);
        const isLine = labState.lineMode !== 'none';
        $id('lab-row-line-pos') && ($id('lab-row-line-pos').style.display = isLine ? 'flex' : 'none');
        $id('fig-row-line-pos') && ($id('fig-row-line-pos').style.display = isLine ? 'flex' : 'none');

        const linePosTxt = `${labState.lineOffset > 0 ? '+' : ''}${labState.lineOffset} px ${labState.lineOffset === 0 ? '(по центру)' : ''}`;
        $id('lab-val-line-pos') && ($id('lab-val-line-pos').textContent = linePosTxt);
        $id('fig-val-line') && ($id('fig-val-line').textContent = linePosTxt);
        const slLine = $id('fig-slider-line');
        if (slLine && parseInt(slLine.value, 10) !== labState.lineOffset) slLine.value = labState.lineOffset;

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

        $id('lab-line-pos-dec')?.addEventListener('click', () => { labState.lineOffset = Math.max(-25, labState.lineOffset - 2); updateUiValues(); });
        $id('lab-line-pos-inc')?.addEventListener('click', () => { labState.lineOffset = Math.min(25, labState.lineOffset + 2); updateUiValues(); });
        $id('fig-slider-line')?.addEventListener('input', e => { labState.lineOffset = parseInt(e.target.value, 10); updateUiValues(); });

        $id('fig-slider-w')?.addEventListener('input', e => { labState.figW = parseInt(e.target.value, 10); updateUiValues(); });
        $id('fig-slider-h')?.addEventListener('input', e => { labState.figH = parseInt(e.target.value, 10); updateUiValues(); });

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
