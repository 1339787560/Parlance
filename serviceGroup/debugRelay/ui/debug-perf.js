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

// 会话级峰值 (从首次收到 perf_snapshot 到当前, 持续累 max)。
// 切换客户端时由 resetPerfPanel() 重置。与后端 ClientCtx.perf_peaks 对齐
// (后端从 client 连接算, 前端从 browser 订阅算 — 后端更准, 用于快照持久化)。
const perfPeaks = {
    fps_min: -1,                  // fps min (跌帧谷值, 比 max 更有意义)
    memBytes: -1, tricount: -1, verts: -1,
    draws: -1, frameTimeMax: -1,
    logicMs: -1, physicsMs: -1, renderMs: -1, presentMs: -1,
    cpuTotalPct: -1,              // (logic+physics+render+present)/16.67ms 峰值
};

const FRAME_BUDGET_MS_60 = 1000 / 60;  // 60Hz 帧预算

function updatePerfPeaks(snap) {
    const up = (val, key) => {
        if (typeof val === 'number' && isFinite(val) && val >= 0 && val > perfPeaks[key]) {
            perfPeaks[key] = val;
        }
    };
    up(snap.memBytes, 'memBytes');
    up(getField(snap, 'tricount', 'tris', -1), 'tricount');
    up(snap.verts, 'verts');
    up(getField(snap, 'draws', 'drawCall', -1), 'draws');
    up(snap.frameTimeMax, 'frameTimeMax');
    up(snap.logic, 'logicMs');
    up(snap.physics, 'physicsMs');
    up(snap.render, 'renderMs');
    up(snap.present, 'presentMs');
    // fps min (双向, min 是坏信号)
    if (typeof snap.fps === 'number' && isFinite(snap.fps) && snap.fps >= 0) {
        if (perfPeaks.fps_min < 0 || snap.fps < perfPeaks.fps_min) perfPeaks.fps_min = snap.fps;
    }
    // CPU 总和峰值 (%)
    const parts = [snap.logic, snap.physics, snap.render, snap.present]
        .filter(v => typeof v === 'number' && v >= 0);
    if (parts.length > 0) {
        const totalPct = parts.reduce((a, b) => a + b, 0) / FRAME_BUDGET_MS_60 * 100;
        if (totalPct > perfPeaks.cpuTotalPct) perfPeaks.cpuTotalPct = totalPct;
    }
}

function resetPerfPeaks() {
    Object.keys(perfPeaks).forEach(k => { perfPeaks[k] = -1; });
}

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
    updateScenePerfBadges(snap);
    updatePerfPeaks(snap);
    // 泄漏探针: leak 字段嵌在 perf_snapshot 内, 同 1Hz 频率
    if (window.handleLeakSample) window.handleLeakSample(snap);
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
        updateScenePerfBadges(perfHistory[perfHistory.length - 1]);
    }
}

/** Scene 工具栏右侧实时 FPS / DrawCall 徽标 */
function updateScenePerfBadges(snap) {
    const fpsEl = document.getElementById('scene-fps');
    const dcEl = document.getElementById('scene-dc');
    if (fpsEl && typeof snap.fps === 'number' && snap.fps >= 0) {
        fpsEl.textContent = snap.fps.toFixed(0);
    } else if (fpsEl) {
        fpsEl.textContent = '-';
    }
    const draws = getField(snap, 'draws', 'drawCall', -1);
    if (dcEl) {
        dcEl.textContent = draws >= 0 ? String(draws) : '-';
    }
}

function renderPerfCards(snap) {
    const f1 = (v) => (typeof v === 'number' && isFinite(v)) ? v.toFixed(1) : v;

    // FPS
    setText('perf-fps', f1(snap.fps), snap.fps >= 50 ? 'good' : snap.fps >= 30 ? 'warn' : 'bad');

    // FrameTime — 新字段 frame, 旧字段 frameTime
    const frameTime = getField(snap, 'frame', 'frameTime', 0);
    const frameTimeMax = snap.frameTimeMax ?? 0;
    setText('perf-frame', `frameTime ${f1(frameTime)}ms`);
    // FPS 卡会话峰值: fps 谷值 + frameTimeMax 峰值
    const fpsMinPk = perfPeaks.fps_min >= 0 ? perfPeaks.fps_min.toFixed(1) : '-';
    const ftMaxPk = perfPeaks.frameTimeMax >= 0 ? f1(perfPeaks.frameTimeMax) : '-';
    setPeakText('perf-fps-peak', `会话峰值: fps谷 ${fpsMinPk} · ftMax ${ftMaxPk}ms`);

    // DrawCall — 新字段 draws, 旧字段 drawCall。峰值用会话级 perfPeaks.draws
    const draws = getField(snap, 'draws', 'drawCall', -1);
    const drawCallMax = snap.drawCallMax ?? -1;
    setText('perf-dc', draws >= 0 ? String(draws) : 'N/A',
        draws < 0 ? '' : draws <= 100 ? 'good' : draws <= 200 ? 'warn' : 'bad');
    const dcPeak = perfPeaks.draws >= 0 ? perfPeaks.draws : drawCallMax;
    setPeakText('perf-dc-max', `会话峰值 ${dcPeak >= 0 ? dcPeak : '-'}`);

    setText('perf-ft', frameTime > 0 ? f1(frameTime) : 'N/A',
        frameTime <= 0 ? '' : frameTime <= 20 ? 'good' : frameTime <= 33 ? 'warn' : 'bad');
    // FT 峰值: 会话级 frameTimeMax (真实帧间峰值, 含 vsync/阻塞等待)
    const ftPeak = perfPeaks.frameTimeMax >= 0 ? perfPeaks.frameTimeMax : frameTimeMax;
    setPeakText('perf-ft-max', `会话峰值 ${f1(ftPeak)}ms`);

    // 内存 + 会话峰值 (sub=JS Heap, peak=会话峰值, 拆行)
    if (snap.memBytes > 0) {
        const mb = (snap.memBytes / 1024 / 1024).toFixed(1);
        setText('perf-mem', mb, parseFloat(mb) < 80 ? 'good' : parseFloat(mb) < 150 ? 'warn' : 'bad');
        setText('perf-mem-sub', 'JS Heap');
        const peakMb = perfPeaks.memBytes > 0 ? (perfPeaks.memBytes / 1024 / 1024).toFixed(1) : '-';
        setPeakText('perf-mem-peak', `会话峰值 ${peakMb} MB`);
    } else {
        setText('perf-mem', 'N/A');
        setText('perf-mem-sub', '不可用');
        setPeakText('perf-mem-peak', '-');
    }

    // 三角面 / 顶点 + 会话峰值 (sub=verts, peak=tri/v 峰值, 拆行)
    const tricount = getField(snap, 'tricount', 'tris', -1);
    const verts = snap.verts ?? -1;
    setText('perf-tris', tricount >= 0 ? formatNumber(tricount) : 'N/A');
    setText('perf-verts', `verts ${verts >= 0 ? formatNumber(verts) : '-'}`);
    const triPk = perfPeaks.tricount >= 0 ? formatNumber(perfPeaks.tricount) : '-';
    const vertPk = perfPeaks.verts >= 0 ? formatNumber(perfPeaks.verts) : '-';
    setPeakText('perf-tris-peak', `峰值 tri ${triPk} / v ${vertPk}`);

    // CPU 阶段（占 60Hz 帧预算 16.67ms 的百分比，近似 CPU 占用率）
    // profiler.stats 给的是 ms，转 % 更直观。基准 16.67ms = 100%。
    const FRAME_BUDGET_MS = 1000 / 60;
    const logic = snap.logic ?? -1;
    const physics = snap.physics ?? -1;
    const render = snap.render ?? -1;
    const present = snap.present ?? -1;
    const cpuParts = [logic, physics, render, present];
    const validParts = cpuParts.filter(v => typeof v === 'number' && v >= 0);
    if (validParts.length > 0) {
        const totalMs = validParts.reduce((a, b) => a + b, 0);
        const totalPct = totalMs / FRAME_BUDGET_MS * 100;
        setText('perf-cpu-total', totalPct.toFixed(0) + '%',
            totalPct <= 60 ? 'good' : totalPct <= 90 ? 'warn' : 'bad');
        const pct = (v) => (typeof v === 'number' && v >= 0)
            ? (v / FRAME_BUDGET_MS * 100).toFixed(0) + '%'
            : '-';
        const cpuPeak = perfPeaks.cpuTotalPct >= 0 ? perfPeaks.cpuTotalPct.toFixed(0) + '%' : '-';
        setText('perf-cpu-detail',
            `logic ${pct(logic)} · phys ${pct(physics)} · render ${pct(render)} · present ${pct(present)}`);
        setPeakText('perf-cpu-peak', `会话峰值 ${cpuPeak}`, true);  // dense=长文本缩字号
    } else {
        setText('perf-cpu-total', 'N/A');
        setText('perf-cpu-detail', '不可用');
    }
}

function setText(id, text, klass) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'perf-value' + (klass ? ' ' + klass : '');
}

/** 写会话峰值元素: 强制 perf-peak class (琥珀色贴底), dense=长文本缩字号 */
function setPeakText(id, text, dense) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = 'perf-peak' + (dense ? ' dense' : '');
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
const CHART_COLORS = { fps: '#4ec9b0', dc: '#58a6ff', ft: '#d29922', cpu: '#f85149' };

// 保存每个 canvas 的绘制参数，供 hover 时查最近数据点
const _chartMeta = {};  // { canvasId: { pts, min, max, xStep, padX, padY, w, h, color, unit, decimals } }

function renderPerfCharts() {
    drawLineChart('perf-fps-canvas', perfHistory.map(s => s.fps), { color: CHART_COLORS.fps, fill: true, min: 0, unit: '', decimals: 0 });
    drawLineChart('perf-dc-canvas', perfHistory.map(s => getField(s, 'draws', 'drawCall', -1)), { color: CHART_COLORS.dc, unit: '', decimals: 0 });
    drawLineChart('perf-ft-canvas', perfHistory.map(s => getField(s, 'frame', 'frameTime', 0)), { color: CHART_COLORS.ft, unit: 'ms', decimals: 1 });
    // CPU 占用率（% = 阶段 ms 之和 / 60Hz 帧预算 16.67ms * 100）
    const FRAME_BUDGET_MS_CHART = 1000 / 60;
    drawLineChart('perf-cpu-canvas', perfHistory.map(s => {
        const parts = [s.logic, s.physics, s.render, s.present]
            .filter(v => typeof v === 'number' && v >= 0);
        if (parts.length === 0) return -1;
        return parts.reduce((a, b) => a + b, 0) / FRAME_BUDGET_MS_CHART * 100;
    }), { color: CHART_COLORS.cpu, min: 0, unit: '%', decimals: 0 });
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

    ['perf-fps-canvas', 'perf-dc-canvas', 'perf-ft-canvas', 'perf-cpu-canvas'].forEach(id => {
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

// ---- 切换客户端时重置面板 ----

function resetPerfPanel() {
    perfHistory.length = 0;
    perfMarks.length = 0;
    resetPerfPeaks();
    // 卡片复位
    ['perf-fps', 'perf-dc', 'perf-ft', 'perf-mem', 'perf-tris', 'perf-cpu-total']
        .forEach(id => setText(id, '-'));
    ['perf-frame', 'perf-mem-sub', 'perf-verts', 'perf-cpu-detail']
        .forEach(id => { const e = document.getElementById(id); if (e) e.textContent = '-'; });
    // peak 元素用 setPeakText 复位 (保留 perf-peak class, 不被 setText 覆盖成 perf-value)
    setPeakText('perf-fps-peak', '-');
    setPeakText('perf-dc-max', '-');
    setPeakText('perf-ft-max', '-');
    setPeakText('perf-mem-peak', '-');
    setPeakText('perf-tris-peak', '-');
    setPeakText('perf-cpu-peak', '-', true);
    renderPerfCharts();
    const ml = document.getElementById('perf-marks-list');
    if (ml) ml.innerHTML = '';
    // Scene 工具栏徽标
    const f = document.getElementById('scene-fps'), d = document.getElementById('scene-dc');
    if (f) f.textContent = '-';
    if (d) d.textContent = '-';
}

// 暴露给 debug-console.js 调用
window.handlePerfSnapshot = handlePerfSnapshot;
window.handlePerfHistory = handlePerfHistory;
window.handlePerfCharts = renderPerfCharts;
window.handlePerfMark = handlePerfMark;
window.resetPerfPanel = resetPerfPanel;
