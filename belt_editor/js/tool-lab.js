/* belt_editor/js/tool-lab.js — Лаборатория инструментов (координатные допуски X, Y) */
'use strict';

(function () {
    const labState = {
        open: false,
        figW: 72,
        figH: 58,
        xMin: 50,
        xMax: 90,
        yMin: 40,
        yMax: 70
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

    function drawToleranceBands(ctx, x0, y0, scX, scY) {
        const x1 = x0 + labState.xMin * scX, x2 = x0 + labState.xMax * scX;
        ctx.fillStyle = 'rgba(34, 197, 94, 0.2)';
        ctx.fillRect(x1, y0 - 4, x2 - x1, 8);
        ctx.strokeStyle = '#22c55e';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x1, y0 - 8); ctx.lineTo(x1, y0 + 8);
        ctx.moveTo(x2, y0 - 8); ctx.lineTo(x2, y0 + 8);
        ctx.stroke();

        const y1 = y0 - labState.yMin * scY, y2 = y0 - labState.yMax * scY;
        ctx.fillStyle = 'rgba(34, 197, 94, 0.2)';
        ctx.fillRect(x0 - 4, y2, 8, y1 - y2);
        ctx.beginPath();
        ctx.moveTo(x0 - 8, y1); ctx.lineTo(x0 + 8, y1);
        ctx.moveTo(x0 - 8, y2); ctx.lineTo(x0 + 8, y2);
        ctx.stroke();
    }

    function drawCoordinateAxes(ctx, x0, y0, scX, scY) {
        const xEnd = 540, yEnd = 40;
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x0 - 10, y0); ctx.lineTo(xEnd, y0);
        ctx.moveTo(xEnd, y0); ctx.lineTo(xEnd - 8, y0 - 4);
        ctx.moveTo(xEnd, y0); ctx.lineTo(xEnd - 8, y0 + 4);
        ctx.moveTo(x0, y0 + 10); ctx.lineTo(x0, yEnd);
        ctx.moveTo(x0, yEnd); ctx.lineTo(x0 - 4, yEnd + 8);
        ctx.moveTo(x0, yEnd); ctx.lineTo(x0 + 4, yEnd + 8);
        ctx.stroke();

        ctx.font = 'bold 11px monospace';
        ctx.fillStyle = '#94a3b8';
        ctx.fillText('X (горизонталь, px) →', xEnd - 150, y0 + 22);
        ctx.fillText('↑ Y (высота, px)', x0 - 15, yEnd - 12);

        for (let px = 20; px <= 140; px += 20) {
            const x = x0 + px * scX;
            ctx.beginPath(); ctx.moveTo(x, y0 - 3); ctx.lineTo(x, y0 + 3); ctx.stroke();
            ctx.fillText(String(px), x - 8, y0 + 16);
        }
        for (let py = 20; py <= 100; py += 20) {
            const y = y0 - py * scY;
            ctx.beginPath(); ctx.moveTo(x0 - 3, y); ctx.lineTo(x0 + 3, y); ctx.stroke();
            ctx.fillText(String(py), x0 - 24, y + 4);
        }
        drawToleranceBands(ctx, x0, y0, scX, scY);
    }

    function drawFigureAndProjections(ctx, x0, y0, scX, scY) {
        const wPx = labState.figW * scX, hPx = labState.figH * scY;
        const xOk = labState.figW >= labState.xMin && labState.figW <= labState.xMax;
        const yOk = labState.figH >= labState.yMin && labState.figH <= labState.yMax;
        const allOk = xOk && yOk;

        ctx.fillStyle = allOk ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.14)';
        ctx.fillRect(x0, y0 - hPx, wPx, hPx);
        ctx.strokeStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 2.4;
        ctx.strokeRect(x0, y0 - hPx, wPx, hPx);

        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = xOk ? '#22c55e' : '#ef4444';
        ctx.beginPath(); ctx.moveTo(x0 + wPx, y0 - hPx); ctx.lineTo(x0 + wPx, y0); ctx.stroke();
        ctx.strokeStyle = yOk ? '#22c55e' : '#ef4444';
        ctx.beginPath(); ctx.moveTo(x0 + wPx, y0 - hPx); ctx.lineTo(x0, y0 - hPx); ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = xOk ? '#22c55e' : '#ef4444';
        ctx.beginPath(); ctx.arc(x0 + wPx, y0, 4, 0, Math.PI * 2); ctx.fill();
        ctx.font = 'bold 12px monospace';
        ctx.fillText(`X = ${labState.figW} px ${xOk ? '✓' : '✗ вылет'}`, x0 + wPx - 20, y0 - 10);

        ctx.fillStyle = yOk ? '#22c55e' : '#ef4444';
        ctx.beginPath(); ctx.arc(x0, y0 - hPx, 4, 0, Math.PI * 2); ctx.fill();
        ctx.fillText(`Y = ${labState.figH} px ${yOk ? '✓' : '✗ вылет'}`, x0 + 10, y0 - hPx - 8);

        ctx.font = 'bold 15px monospace';
        ctx.fillStyle = allOk ? '#22c55e' : '#ef4444';
        ctx.fillText(`${labState.figW} × ${labState.figH} px`, x0 + wPx / 2 - 40, y0 - hPx / 2 + 5);

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
        const x0 = 80, y0 = 280, scX = 2.8, scY = 2.2;

        drawCanvasGrid(ctx, w, h);
        drawCoordinateAxes(ctx, x0, y0, scX, scY);
        drawFigureAndProjections(ctx, x0, y0, scX, scY);
    }

    function updateUiValues() {
        $id('fig-val-w') && ($id('fig-val-w').textContent = labState.figW + ' px');
        $id('fig-val-h') && ($id('fig-val-h').textContent = labState.figH + ' px');
        $id('lab-val-tol-x') && ($id('lab-val-tol-x').textContent = `${labState.xMin}–${labState.xMax} px`);
        $id('lab-val-tol-y') && ($id('lab-val-tol-y').textContent = `${labState.yMin}–${labState.yMax} px`);
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
            labState.xMin = Math.min(labState.xMin + 3, labState.xMax - 10);
            labState.xMax = Math.max(labState.xMax - 3, labState.xMin + 10);
            updateUiValues();
        });
        $id('lab-tol-x-inc')?.addEventListener('click', () => {
            labState.xMin = Math.max(10, labState.xMin - 3);
            labState.xMax = Math.min(140, labState.xMax + 3);
            updateUiValues();
        });

        $id('lab-tol-y-dec')?.addEventListener('click', () => {
            labState.yMin = Math.min(labState.yMin + 2, labState.yMax - 8);
            labState.yMax = Math.max(labState.yMax - 2, labState.yMin + 8);
            updateUiValues();
        });
        $id('lab-tol-y-inc')?.addEventListener('click', () => {
            labState.yMin = Math.max(10, labState.yMin - 2);
            labState.yMax = Math.min(100, labState.yMax + 2);
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
