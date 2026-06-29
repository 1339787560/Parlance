/**
 * Performance 面板
 * - 显示 FPS / DrawCall / FrameTime / CPU耗时分解 / 显存 / 内存 / 三角面
 * - 历史折线图
 *
 * 字段兼容：同时支持旧字段名(frameTime/drawCall/tris/verts)和新字段名(frame/draws/tricount)
 * 新字段来自 profiler.stats（策略对齐），旧字段来自 PerfBridge fallback
 */

const PERF_HISTORY_MAX = 300;   // 最多保留 300 条 = 5 分钟 @ 1Hz
const perfHistory = [];         // [{ fps, draws, frame, logic, render, textureMemory, ... }]

/** 兼容读取：优先新字段名，fallback 旧字段名 */
function getField(snap, newName, oldName, defaultVal = -1) {
    if (snap[newName] !== undefined && snap[newName] !== null) return snap[newName];
    if (snap[oldName] !== undefined && snap[oldName] !== null) return snap[oldName];
    return defaultVal;
}

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

    // FPS
    setText('perf-fps', f1(snap.fps), snap.fps >= 50 ? 'good' : snap.fps >= 30 ? 'warn' : 'bad');

    // FrameTime — 新字段 frame, 旧字段 frameTime
    const frameTime = getField(snap, 'frame', 'frameTime', 0);
    const frameTimeMax = snap.frameTimeMax ?? 0;
    setText('perf-frame', `frameTime ${f1(frameTime)}ms · max ${f1(frameTimeMax)}ms`);

    // DrawCall — 新字段 draws, 旧字段 drawCall
    const draws = getField(snap, 'draws', 'drawCall', -1);
    const drawCallMax = snap.drawCallMax ?? -1;
    setText('perf-dc', draws >= 0 ? String(draws) : 'N/A',
        draws < 0 ? '' : draws <= 100 ? 'good' : draws <= 200 ? 'warn' : 'bad');
    setText('perf-dc-max', `峰值 ${drawCallMax >= 0 ? drawCallMax : '-'}`);

    setText('perf-ft', frameTime > 0 ? f1(frameTime) : 'N/A',
        frameTime <= 0 ? '' : frameTime <= 20 ? 'good' : frameTime <= 33 ? 'warn' : 'bad');
    setText('perf-ft-max', `峰值 ${f1(frameTimeMax)}ms`);

    // 内存
    if (snap.memBytes > 0) {
        const mb = (snap.memBytes / 1024 / 1024).toFixed(1);
        setText('perf-mem', mb, parseFloat(mb) < 80 ? 'good' : parseFloat(mb) < 150 ? 'warn' : 'bad');
        setText('perf-mem-sub', 'JS Heap');
    } else {
        setText('perf-mem', 'N/A');
        setText('perf-mem-sub', '不可用');
    }

    // 三角面 — 新字段 tricount, 旧字段 tris
    const tricount = getField(snap, 'tricount', 'tris', -1);
    const verts = snap.verts ?? -1;
    setText('perf-tris', tricount >= 0 ? formatNumber(tricount) : 'N/A');
    setText('perf-verts', verts >= 0 ? formatNumber(verts) : 'N/A');
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

// 保存每个 canvas 的绘制参数，供 hover 时查最近数据点
const _chartMeta = {};  // { canvasId: { pts, min, max, xStep, padX, padY, w, h, color, unit, decimals } }

function renderPerfCharts() {
    drawLineChart('perf-fps-canvas', perfHistory.map(s => s.fps), { color: CHART_COLORS.fps, fill: true, min: 0, unit: '', decimals: 0 });
    drawLineChart('perf-dc-canvas', perfHistory.map(s => getField(s, 'draws', 'drawCall', -1)), { color: CHART_COLORS.dc, unit: '', decimals: 0 });
    drawLineChart('perf-ft-canvas', perfHistory.map(s => getField(s, 'frame', 'frameTime', 0)), { color: CHART_COLORS.ft, unit: 'ms', decimals: 1 });
    bindPerfHover();
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

    // 过滤 null / 负值（-1 表示不可用）
    const pts = [];
    values.forEach((v, i) => {
        if (v === null || v === undefined || v < 0) return;
        pts.push({ i, v });
    });
    if (pts.length < 2) {
        _chartMeta[canvasId] = null;
        return;
    }

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

    // 保存绘制参数，供 hover 查最近点
    _chartMeta[canvasId] = { pts, min, max, xStep, padX, padY, w, h, color, cssW, cssH, unit: opts.unit || '', decimals: opts.decimals ?? 1 };

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

    // 悬停标记（hover 时由事件回调追加绘制）
    if (canvas._hoverX !== undefined) {
        drawHoverIndicator(canvasId, ctx, canvas._hoverX);
    }
}

// ---- Hover tooltip ----

function drawHoverIndicator(canvasId, ctx, mouseX) {
    const meta = _chartMeta[canvasId];
    if (!meta) return;

    const { pts, min, max, xStep, padX, padY, w, h, color, cssW, cssH, unit, decimals } = meta;

    // 二分找最近的数据点（按 x 坐标）
    let nearest = null;
    let nearestDist = Infinity;
    for (const p of pts) {
        const x = padX + p.i * xStep;
        const dist = Math.abs(x - mouseX);
        if (dist < nearestDist) {
            nearestDist = dist;
            nearest = p;
        }
    }
    if (!nearest) return;

    const hx = padX + nearest.i * xStep;
    const hy = padY + h - (nearest.v - min) / (max - min) * h;

    // 竖线
    ctx.strokeStyle = withAlpha(color, 0.5);
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(hx, 0);
    ctx.lineTo(hx, cssH);
    ctx.stroke();
    ctx.setLineDash([]);

    // 数据点高亮
    ctx.beginPath();
    ctx.arc(hx, hy, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1;
    ctx.stroke();

    // 数值标签
    const valStr = nearest.v.toFixed(decimals) + unit;
    ctx.font = '11px monospace';
    const tw = ctx.measureText(valStr).width;
    const tx = Math.min(Math.max(hx - tw / 2 - 4, 1), cssW - tw - 9);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
    ctx.fillRect(tx, 2, tw + 8, 16);
    ctx.fillStyle = color;
    ctx.fillText(valStr, tx + 4, 13);
}

// 给所有 perf canvas 绑定 hover 事件（只需绑定一次）
let _hoverBound = false;
function bindPerfHover() {
    if (_hoverBound) return;
    _hoverBound = true;

    ['perf-fps-canvas', 'perf-dc-canvas', 'perf-ft-canvas'].forEach(id => {
        const canvas = document.getElementById(id);
        if (!canvas) return;

        canvas.addEventListener('mousemove', (e) => {
            const rect = canvas.getBoundingClientRect();
            canvas._hoverX = e.clientX - rect.left;
            renderPerfCharts();
        });

        canvas.addEventListener('mouseleave', () => {
            canvas._hoverX = undefined;
            renderPerfCharts();
        });
    });
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

// ---- 段打点 (perf_mark) ----

const perfMarks = [];         // 最近的 mark 记录 [{name, dur, ts}]
const PERF_MARKS_MAX = 200;

function handlePerfMark(msg) {
    perfMarks.push(msg);
    if (perfMarks.length > PERF_MARKS_MAX) {
        perfMarks.shift();
    }
    renderPerfMarks();
}

function renderPerfMarks() {
    const el = document.getElementById('perf-marks-list');
    if (!el) return;

    // 只显示最近 20 条
    const recent = perfMarks.slice(-20).reverse();
    el.innerHTML = recent.map(m => {
        const f1 = (v) => (typeof v === 'number' && isFinite(v)) ? v.toFixed(1) : v;
        const durMs = f1(m.dur);
        const cls = m.dur <= 16 ? 'good' : m.dur <= 33 ? 'warn' : 'bad';
        return `<div class="perf-mark-item"><span class="perf-mark-name">${escapePerfHtml(m.name)}</span><span class="perf-value ${cls}">${durMs}ms</span><span class="perf-mark-ts">${m.ts ? m.ts.split('T')[1]?.split('.')?.[0] || '' : ''}</span></div>`;
    }).join('');
}

function escapePerfHtml(text) {
    const d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
}

// 暴露给 debug-console.js 调用
window.handlePerfSnapshot = handlePerfSnapshot;
window.handlePerfHistory = handlePerfHistory;
window.handlePerfCharts = renderPerfCharts;
window.handlePerfMark = handlePerfMark;
