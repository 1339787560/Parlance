/**
 * Performance 面板
 * - 显示 FPS / DrawCall / FrameTime / 内存 / 三角面-顶点
 * - 历史折线图
 */

const PERF_HISTORY_MAX = 300;   // 最多保留 300 条 = 5 分钟 @ 1Hz
const perfHistory = [];         // [{ fps, drawCall, frameTime, memBytes, ts }]

function handlePerfSnapshot(snap) {
    perfHistory.push(snap);
    if (perfHistory.length > PERF_HISTORY_MAX) {
        perfHistory.shift();
    }
    if (window.__perfDbg === undefined) {
        window.__perfDbg = 0;
    }
    if (window.__perfDbg < 3) {
        console.log('[perf] raw snapshot:', JSON.stringify(snap));
        window.__perfDbg++;
    }
    renderPerfCards(snap);
    renderPerfCharts();
}

function handlePerfHistory(snapshots) {
    perfHistory.length = 0;
    for (const s of snapshots) perfHistory.push(s);
    if (perfHistory.length > PERF_HISTORY_MAX) {
        perfHistory.splice(0, perfHistory.length - PERF_HISTORY_MAX);
    }
    if (perfHistory.length > 0) {
        renderPerfCards(perfHistory[perfHistory.length - 1]);
        renderPerfCharts();
    }
}

function renderPerfCards(snap) {
    const f1 = (v) => (typeof v === 'number' && isFinite(v)) ? v.toFixed(1) : v;
    setText('perf-fps', f1(snap.fps), snap.fps >= 50 ? 'good' : snap.fps >= 30 ? 'warn' : 'bad');
    setText('perf-frame', `frameTime ${f1(snap.frameTime)}ms · max ${f1(snap.frameTimeMax)}ms`);
    setText('perf-dc', snap.drawCall >= 0 ? String(snap.drawCall) : 'N/A',
        snap.drawCall < 0 ? '' : snap.drawCall <= 100 ? 'good' : snap.drawCall <= 200 ? 'warn' : 'bad');
    setText('perf-dc-max', `峰值 ${snap.drawCallMax}`);

    setText('perf-ft', snap.frameTime > 0 ? f1(snap.frameTime) : 'N/A',
        snap.frameTime <= 0 ? '' : snap.frameTime <= 20 ? 'good' : snap.frameTime <= 33 ? 'warn' : 'bad');
    setText('perf-ft-max', `峰值 ${f1(snap.frameTimeMax)}ms`);

    if (snap.memBytes > 0) {
        const mb = (snap.memBytes / 1024 / 1024).toFixed(1);
        setText('perf-mem', mb, parseFloat(mb) < 80 ? 'good' : parseFloat(mb) < 150 ? 'warn' : 'bad');
        setText('perf-mem-sub', 'JS Heap');
    } else {
        setText('perf-mem', 'N/A');
        setText('perf-mem-sub', '不可用');
    }

    setText('perf-tris', snap.tris >= 0 ? formatNumber(snap.tris) : 'N/A');
    setText('perf-verts', snap.verts >= 0 ? formatNumber(snap.verts) : 'N/A');
}

function setText(id, text, klass) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'perf-value' + (klass ? ' ' + klass : '');
}

function formatNumber(n) {
    if (n >= 10000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
}

// 折线图颜色: 用固定 hex 字面量, 不用 CSS 变量。
// 关键: Canvas 2D 不解析 var(--x), 直接赋值会被当成非法颜色退回黑色
// (实测 strokeStyle='var(--accent,#4ec9b0)' 实际生效 '#000000'), 黑线画在深色
// canvas 背景 (var(--bg)=#0d1117) 上对比度极低 → 折线不可见 (狼尊 LV999 下复现)。
// 决策: 只要可见、不跟主题变。这些色在深背景上高对比稳定, 且 --bg 不随主题变。
const CHART_COLORS = { fps: '#4ec9b0', dc: '#58a6ff', ft: '#d29922' };

function renderPerfCharts() {
    drawLineChart('perf-fps-canvas', perfHistory.map(s => s.fps), { color: CHART_COLORS.fps, fill: true, min: 0 });
    drawLineChart('perf-dc-canvas', perfHistory.map(s => s.drawCall >= 0 ? s.drawCall : null), { color: CHART_COLORS.dc });
    drawLineChart('perf-ft-canvas', perfHistory.map(s => s.frameTime), { color: CHART_COLORS.ft });
}

function drawLineChart(canvasId, values, opts) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 800;
    const cssH = canvas.clientHeight || 80;
    if (canvas.width !== cssW * dpr) {
        canvas.width = cssW * dpr;
        canvas.height = cssH * dpr;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, cssW, cssH);

    // 过滤 null
    const pts = [];
    values.forEach((v, i) => {
        if (v === null || v === undefined) return;
        pts.push({ i, v });
    });
    if (pts.length < 2) return;

    // 计算 min/max
    let min = opts.min !== undefined ? opts.min : Infinity;
    let max = -Infinity;
    for (const p of pts) {
        if (p.v < min) min = p.v;
        if (p.v > max) max = p.v;
    }
    if (max - min < 1) { min -= 1; max += 1; }

    const color = opts.color || '#4ec9b0';
    const padX = 2;
    const padY = 4;
    const w = cssW - padX * 2;
    const h = cssH - padY * 2;
    const xStep = w / Math.max(1, values.length - 1);

    // 填充
    if (opts.fill) {
        ctx.beginPath();
        pts.forEach((p, idx) => {
            const x = padX + p.i * xStep;
            const y = padY + h - (p.v - min) / (max - min) * h;
            if (idx === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        const lastX = padX + pts[pts.length - 1].i * xStep;
        const firstX = padX + pts[0].i * xStep;
        ctx.lineTo(lastX, padY + h);
        ctx.lineTo(firstX, padY + h);
        ctx.closePath();
        ctx.fillStyle = withAlpha(color, 0.15);
        ctx.fill();
    }

    // 折线
    ctx.beginPath();
    pts.forEach((p, idx) => {
        const x = padX + p.i * xStep;
        const y = padY + h - (p.v - min) / (max - min) * h;
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // 最新点
    const last = pts[pts.length - 1];
    const lx = padX + last.i * xStep;
    const ly = padY + h - (last.v - min) / (max - min) * h;
    ctx.beginPath();
    ctx.arc(lx, ly, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
}

function withAlpha(color, alpha) {
    if (color.startsWith('#')) {
        const r = parseInt(color.slice(1, 3), 16);
        const g = parseInt(color.slice(3, 5), 16);
        const b = parseInt(color.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
    return color;
}

// 暴露给 debug-console.js 调用
window.handlePerfSnapshot = handlePerfSnapshot;
window.handlePerfHistory = handlePerfHistory;
window.renderPerfCharts = renderPerfCharts;
