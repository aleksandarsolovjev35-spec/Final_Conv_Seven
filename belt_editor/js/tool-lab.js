/* belt_editor/js/tool-lab.js — Лаборатория: центр области в точке 0 (допуски ±X, ±Y) */
'use strict';

(function () {
    const labState = {
        open: false,
        figW: 72,
        figH: 58,
        tolX: 42,
        tolY: 34
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

    function drawCenteredFigure(ctx, xc, yc, scale) {
        const hw = labState.figW / 2, hh = labState.figH / 2;
        const dx = hw * scale, dy = hh * scale;
        const xOk = hw <= labState.tolX, yOk = hh <= labState.tolY;
        const allOk = xOk && yOk;

        ctx.fillStyle = allOk ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.15)';
        ctx.fillRect(xc - dx, yc - dy, dx * 2, dy * 2);
        ctx.strokeStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 2.4;
        ctx.strokeRect(xc - dx, yc - dy, dx * 2, dy * 2);

        ctx.beginPath();
        ctx.moveTo(xc - 5, yc); ctx.lineTo(xc + 5, yc);
        ctx.moveTo(xc, yc - 5); ctx.lineTo(xc, yc + 5);
        ctx.stroke();

        ctx.font = 'bold 13px monospace';
        ctx.fillStyle = allOk ? '#22c55e' : '#ef4444';
        const txt = `${labState.figW} × ${labState.figH} px (±${hw} / ±${hh})`;
        const tw = ctx.measureText(txt).width;
        ctx.fillText(txt, xc - tw / 2, yc + dy + 18);

        const verdict = allOk ? '✓ ГОДНАЯ (ОК)' : (!xOk && !yOk ? '✗ БРАК (ВЫЛЕТ X И Y)' : (!xOk ? '✗ БРАК (ВЫЛЕТ X)' : '✗ БРАК (ВЫЛЕТ Y)'));
        ctx.fillStyle = allOk ? 'rgba(34, 197, 94, 0.2)' : 'rgba(239, 68, 68, 0.25)';
        ctx.fillRect(380, 18, 205, 30);
        ctx.strokeStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(380, 18, 205, 30);
        ctx.fillStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.font = 'bold 12px monospace';
        ctx.fillText(verdict, 392, 38);
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
        const hw = (labState.figW / 2).toFixed(0);
        const hh = (labState.figH / 2).toFixed(0);
        $id('fig-val-w') && ($id('fig-val-w').textContent = `${labState.figW} px (±${hw} px)`);
        $id('fig-val-h') && ($id('fig-val-h').textContent = `${labState.figH} px (±${hh} px)`);
        $id('lab-val-tol-x') && ($id('lab-val-tol-x').textContent = `±${labState.tolX} px (W ≤ ${labState.tolX * 2} px)`);
        $id('lab-val-tol-y') && ($id('lab-val-tol-y').textContent = `±${labState.tolY} px (H ≤ ${labState.tolY * 2} px)`);
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

        $id('fig-slider-w')?.addEventListener('input', e => {
            labState.figW = parseInt(e.target.value, 10);
            updateUiValues();
        });
        $id('fig-slider-h')?.addEventListener('input', e => {
            labState.figH = parseInt(e.target.value, 10);
            updateUiValues();
        });

        $id('lab-tol-x-dec')?.addEventListener('click', () => {
            labState.tolX = Math.max(15, labState.tolX - 2);
            updateUiValues();
        });
        $id('lab-tol-x-inc')?.addEventListener('click', () => {
            labState.tolX = Math.min(70, labState.tolX + 2);
            updateUiValues();
        });

        $id('lab-tol-y-dec')?.addEventListener('click', () => {
            labState.tolY = Math.max(10, labState.tolY - 2);
            updateUiValues();
        });
        $id('lab-tol-y-inc')?.addEventListener('click', () => {
            labState.tolY = Math.min(50, labState.tolY + 2);
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
