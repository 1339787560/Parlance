// debug-btree.js - 行为树可视化
// - 四层配置浏览 + 运行时日志(userid 拉取)
// - 自动布局: 水平整齐树（子节点同 x，父居中，边右出左入）
// - 节点点击 -> Sources 面板展示 TS 源码（template_root 内）
// 依赖后端: /api/bt/{layers,tree,resolve,search,source,runtime_log}
(function () {
'use strict';

// ---- 节点分类 ----
const COMPOSITES = new Set(['MemPriority','MemPriorityRandom','MemSequence','Sequence','Priority','PriorityRandom','Parallel','ForEach']);
const DECORATORS = new Set(['Inverter','Limiter','Repeater','ReturnSuccess','ReturnFailure','MaxTime','RepeatUntilFailure','RepeatUntilSuccess','InterruptOnFinish','RecorderStatus']);
const CATEGORY_COLOR = { composite:'#3b82f6', decorator:'#a855f7', condition:'#f59e0b', action:'#22c55e' };
const CATEGORY_LABEL = { composite:'组合', decorator:'装饰', condition:'条件', action:'动作' };
// b3 执行状态（运行时调试着色）SUCCESS=1/FAILURE=2/RUNNING=3/ERROR=4/INTERRUPT=5
const STATE_COLOR = { 1:'#22c55e', 2:'#ef4444', 3:'#eab308', 4:'#6b7280', 5:'#f97316' };
const STATE_LABEL = { 1:'SUCCESS', 2:'FAILURE', 3:'RUNNING', 4:'ERROR', 5:'INTERRUPT' };

const NODE_W = 172, NODE_H = 60;
const LEVEL_W = 234;   // 水平层间距（depth -> x）
const V_GAP = 14;      // 兄弟节点垂直间距
const PAD = 40;

// ---- 状态 ----
const state = {
    inited: false,
    layers: {},
    mode: 'config',          // config | runtime
    curLayer: 'base_btree',
    curTree: null,
    treeData: null,
    diffBaseNames: null,
    collapsed: new Set(),
    runtimeTrees: [],        // [{name, tree}]
    runtimeUserid: null,
    runtimeDate: null,
    exec: null,              // {versions, curVer, curStep, nodeStates, playing, timer}
    layout: {},              // id -> {x,y}
    pan: { x: 0, y: 0 },
    zoom: 1,
    vbW: 0, vbH: 0,
    dragging: false, dragStart: null,
};

function $(id) { return document.getElementById(id); }
function svgEl(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
}
function setStatus(msg) { const e = $('btree-status'); if (e) e.textContent = msg || ''; }
function shortPath(p) { const m = /\/Template\/game\/(.+)$/.exec(p||''); return m ? m[1] : (p||''); }

function btreeCategory(node) {
    const name = node.name || '';
    if (COMPOSITES.has(name)) return 'composite';
    if (DECORATORS.has(name)) return 'decorator';
    if (name.indexOf('Con_') === 0) return 'condition';
    if (Array.isArray(node.children) && node.children.length) return 'composite';
    if (node.child) return 'decorator';
    return 'action';
}

function formatProps(props) {
    if (!props) return [];
    const out = [];
    for (const k in props) {
        if (!Object.prototype.hasOwnProperty.call(props, k)) continue;
        let v = props[k];
        if (typeof v === 'object') v = JSON.stringify(v);
        out.push(k + ': ' + v);
        if (out.length >= 2) break;
    }
    return out;
}

// ---- 自动布局: 水平整齐树（子节点同 x = depth*LEVEL_W，父 y 居中于子）----
function computeLayout(nodes, rootId) {
    const layout = {};
    let nextY = 0;
    function place(id, depth) {
        const node = nodes[id];
        if (!node) return null;
        if (state.collapsed.has(id)) {
            const y = nextY; nextY += NODE_H + V_GAP;
            layout[id] = { x: depth * LEVEL_W, y };
            return layout[id];
        }
        let childIds = Array.isArray(node.children) ? node.children.slice() : (node.child ? [node.child] : []);
        const childPos = [];
        for (const cid of childIds) {
            const p = place(cid, depth + 1);
            if (p) childPos.push(p);
        }
        if (!childPos.length) {
            const y = nextY; nextY += NODE_H + V_GAP;
            layout[id] = { x: depth * LEVEL_W, y };
            return layout[id];
        }
        const y = (childPos[0].y + childPos[childPos.length - 1].y) / 2;
        layout[id] = { x: depth * LEVEL_W, y };
        return layout[id];
    }
    place(rootId, 0);
    return layout;
}

// ---- 初始化 ----
async function btreeInit() {
    if (state.inited) { btreeRender(); return; }
    state.inited = true;
    setStatus('加载四层...');
    try {
        const r = await fetch('/api/bt/layers');
        const data = await r.json();
        state.layers = data.layers || {};
        btreeSelectLayer(state.curLayer);
    } catch (e) { setStatus('加载失败: ' + e.message); }
}
window.btreeInit = btreeInit;

function btreeSelectLayer(layer) {
    state.mode = 'config';
    state.curLayer = layer;
    state.curTree = null;
    state.treeData = null;
    state.diffBaseNames = null;
    state.runtimeTrees = [];
    state.exec = null;
    stopPlay();
    hideTimeline();
    document.querySelectorAll('.btree-layer-btn').forEach(b => {
        const m = /btreeSelectLayer\('([^']+)'\)/.exec(b.getAttribute('onclick') || '');
        b.classList.toggle('active', m && m[1] === layer);
    });
    const list = $('btree-tree-list');
    const info = state.layers[layer];
    if (!info) { list.innerHTML = '<div class="btree-tree-empty">层未配置</div>'; btreeClearCanvas(); return; }
    if (!info.exists) { list.innerHTML = '<div class="btree-tree-empty">目录不存在:<br>' + (info.dir||'') + '</div>'; btreeClearCanvas(); return; }
    if (!info.trees.length) { list.innerHTML = '<div class="btree-tree-empty">无树文件</div>'; btreeClearCanvas(); return; }
    list.innerHTML = '';
    info.trees.forEach(name => {
        const d = document.createElement('div');
        d.className = 'btree-tree-item';
        d.textContent = name;
        d.onclick = () => btreeSelectTree(name);
        list.appendChild(d);
    });
    setStatus('层: ' + layer + ' (' + info.trees.length + ' 棵树)');
    btreeClearCanvas();
}
window.btreeSelectLayer = btreeSelectLayer;

async function btreeSelectTree(name) {
    state.curTree = name;
    document.querySelectorAll('.btree-tree-item').forEach(d => d.classList.toggle('active', d.textContent === name));
    setStatus('加载 ' + state.curLayer + '/' + name + ' ...');
    try {
        const r = await fetch('/api/bt/tree?layer=' + encodeURIComponent(state.curLayer) + '&file=' + encodeURIComponent(name));
        if (!r.ok) { const e = await r.json().catch(()=>({})); setStatus('加载失败: ' + (e.error || r.status)); return; }
        const data = await r.json();
        state.treeData = data.tree;
        state.collapsed.clear();
        state.pan = { x: 0, y: 0 }; state.zoom = 1;
        if ($('btree-diff') && $('btree-diff').checked) await btreeLoadDiffBase(name);
        else state.diffBaseNames = null;
        btreeRender();
    } catch (e) { setStatus('加载失败: ' + e.message); }
}

async function btreeLoadDiffBase(name) {
    const baseLayer = state.curLayer.replace('override_', 'base_');
    if (baseLayer === state.curLayer) { state.diffBaseNames = null; return; }
    try {
        const r = await fetch('/api/bt/tree?layer=' + encodeURIComponent(baseLayer) + '&file=' + encodeURIComponent(name));
        if (!r.ok) { state.diffBaseNames = null; return; }
        const data = await r.json();
        const names = new Set();
        const nodes = (data.tree && data.tree.nodes) || {};
        for (const id in nodes) names.add((nodes[id].name || '').toLowerCase());
        state.diffBaseNames = names;
    } catch (e) { state.diffBaseNames = null; }
}

async function btreeToggleDiff() {
    if (!$('btree-diff').checked) { state.diffBaseNames = null; btreeRender(); return; }
    if (state.curTree && state.mode === 'config') await btreeLoadDiffBase(state.curTree);
    btreeRender();
}
window.btreeToggleDiff = btreeToggleDiff;

// ---- 渲染 ----
function btreeClearCanvas() {
    const svg = $('btree-canvas'); if (svg) svg.innerHTML = '';
    const cfg = $('btree-config-view'); if (cfg) cfg.classList.add('hidden');
    const empty = $('btree-empty'); if (empty) empty.style.display = 'block';
}

function btreeRender() {
    const svg = $('btree-canvas');
    const empty = $('btree-empty');
    if (!state.treeData) { btreeClearCanvas(); return; }
    if (empty) empty.style.display = 'none';
    svg.innerHTML = '';

    // 弹窗配置（popup-*.json 非行为树）
    const cfgView = $('btree-config-view');
    if (!state.treeData.nodes || !state.treeData.root) {
        svg.innerHTML = '';
        if (cfgView) { cfgView.classList.remove('hidden'); renderPopupConfig(state.treeData); }
        setStatus((state.mode === 'runtime' ? '运行时' : state.curLayer) + '/' + (state.curTree||'?') + ' · 弹窗配置（非行为树）');
        return;
    }
    if (cfgView) cfgView.classList.add('hidden');

    const nodes = state.treeData.nodes || {};
    const rootId = state.treeData.root;
    if (!nodes[rootId]) { setStatus('树无 root 节点'); return; }

    state.layout = computeLayout(nodes, rootId);
    let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
    for (const id in state.layout) {
        const p = state.layout[id];
        if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x;
        if (p.y < minY) minY = p.y; if (p.y > maxY) maxY = p.y;
    }
    const offX = PAD - minX, offY = PAD - minY;
    const vbW = (maxX - minX) + NODE_W + PAD * 2;
    const vbH = (maxY - minY) + NODE_H + PAD * 2;
    state.vbW = vbW; state.vbH = vbH;
    svg.setAttribute('viewBox', '0 0 ' + vbW + ' ' + vbH);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

    const vp = svgEl('g', { id: 'btree-viewport', transform: vpTransform() });
    svg.appendChild(vp);
    const edgesG = svgEl('g', { class: 'btree-edges' });
    const nodesG = svgEl('g', { class: 'btree-nodes' });
    vp.appendChild(edgesG); vp.appendChild(nodesG);

    const visible = new Set();
    (function collect(id) {
        if (!id || !nodes[id] || visible.has(id)) return;
        visible.add(id);
        if (state.collapsed.has(id)) return;
        const n = nodes[id];
        if (Array.isArray(n.children)) n.children.forEach(collect);
        if (n.child) collect(n.child);
    })(rootId);

    for (const id of visible) {
        const n = nodes[id];
        if (state.collapsed.has(id)) continue;
        const childIds = Array.isArray(n.children) ? n.children : (n.child ? [n.child] : []);
        childIds.forEach(cid => { if (visible.has(cid)) drawEdge(edgesG, state.layout[id], state.layout[cid], offX, offY); });
    }
    for (const id of visible) drawNode(nodesG, nodes[id], state.layout[id], offX, offY);

    let added = 0;
    if (state.diffBaseNames) for (const id of visible) if (!state.diffBaseNames.has((nodes[id].name || '').toLowerCase())) added++;
    const diffMsg = state.diffBaseNames ? ' · 对比基础层: 新增 ' + added + '/' + visible.size : '';
    const src = state.mode === 'runtime' ? '运行时' : state.curLayer;
    setStatus(src + '/' + (state.curTree||'?') + ' · ' + visible.size + ' 节点' + diffMsg);
    bindPanZoom(svg, vp);
}
window.btreeRender = btreeRender;

function vpTransform() { return 'translate(' + state.pan.x + ',' + state.pan.y + ') scale(' + state.zoom + ')'; }

// 边: 父右边中心 -> 子左边中心（右出左入）
function drawEdge(g, pp, cp, offX, offY) {
    const px = pp.x + offX + NODE_W;
    const py = pp.y + offY + NODE_H / 2;
    const cx = cp.x + offX;
    const cy = cp.y + offY + NODE_H / 2;
    const mx = (px + cx) / 2;
    g.appendChild(svgEl('path', {
        d: 'M ' + px + ' ' + py + ' C ' + mx + ' ' + py + ' ' + mx + ' ' + cy + ' ' + cx + ' ' + cy,
        class: 'btree-edge', fill: 'none',
    }));
}

function drawNode(g, node, pos, offX, offY) {
    const x = pos.x + offX, y = pos.y + offY;
    const cat = btreeCategory(node);
    const color = CATEGORY_COLOR[cat];
    let cls = 'btree-node cat-' + cat;
    if (state.diffBaseNames && !state.diffBaseNames.has((node.name || '').toLowerCase())) cls += ' btree-diff-added';

    // 运行时执行状态着色（覆盖填充/描边）
    const execState = (state.exec && state.exec.nodeStates && state.exec.nodeStates[node.id] !== undefined) ? state.exec.nodeStates[node.id] : null;
    let fill = color, fillOp = 0.16, stroke = color, sw = 1.4;
    if (execState !== null) {
        fill = STATE_COLOR[execState] || color; fillOp = 0.42; stroke = fill; sw = 2.2;
        cls += ' exec-state-' + execState;
    }

    const grp = svgEl('g', { class: cls, 'data-id': node.id, transform: 'translate(' + x + ',' + y + ')' });
    grp.appendChild(svgEl('rect', { x:0, y:0, width:NODE_W, height:NODE_H, rx:7, fill: fill, 'fill-opacity':fillOp, stroke: stroke, 'stroke-width':sw }));
    grp.appendChild(svgEl('rect', { x:0, y:0, width:6, height:NODE_H, rx:3, fill: color }));   // 左条保留分类色

    const nameTxt = svgEl('text', { x:14, y:21, class:'btree-node-name' });
    nameTxt.textContent = node.name || '(?)';
    grp.appendChild(nameTxt);

    const badge = svgEl('text', { x:NODE_W-8, y:21, class:'btree-node-cat', 'text-anchor':'end' });
    if (execState !== null) { badge.textContent = STATE_LABEL[execState]; badge.setAttribute('fill', STATE_COLOR[execState]); }
    else badge.textContent = CATEGORY_LABEL[cat];
    grp.appendChild(badge);

    formatProps(node.properties).forEach((p, i) => {
        const t = svgEl('text', { x:14, y: 39 + i*13, class:'btree-node-prop' });
        t.textContent = p.length > 30 ? p.slice(0,29) + '…' : p;
        grp.appendChild(t);
    });

    const hasKids = (Array.isArray(node.children) && node.children.length) || node.child;
    if (hasKids) {
        const tog = svgEl('text', { x:NODE_W-8, y:NODE_H-7, class:'btree-collapse-toggle', 'text-anchor':'end' });
        tog.textContent = state.collapsed.has(node.id) ? '▸' : '▾';
        tog.addEventListener('click', (e) => {
            e.stopPropagation();
            if (state.collapsed.has(node.id)) state.collapsed.delete(node.id);
            else state.collapsed.add(node.id);
            btreeRender();
        });
        grp.appendChild(tog);
    }

    grp.style.cursor = 'pointer';
    grp.addEventListener('click', (e) => {
        if (e.target.classList && e.target.classList.contains('btree-collapse-toggle')) return;
        btreeResolveNode(node.name);
    });

    const tip = svgEl('title');
    tip.textContent = node.name + '\n' + (node.title || '') + '\n' + formatProps(node.properties).join('\n');
    grp.appendChild(tip);
    g.appendChild(grp);
}

// ---- 弹窗配置视图 ----
function escapeText(s) { return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function renderPopupConfig(data) {
    const view = $('btree-config-view');
    if (!view) return;
    const items = Array.isArray(data.items) ? data.items : [];
    const flagKeys = ['id','popupName','support','maxCount','cd','defaultVersion','abbr'];
    const flags = flagKeys.filter(k => k in data).map(k => k + ': ' + JSON.stringify(data[k]));
    let html = '<div class="btree-cfg-header"><span class="btree-cfg-name">' + escapeText(data.popupName || state.curTree) + '</span></div>';
    if (flags.length) html += '<div class="btree-cfg-flags">' + flags.map(f => '<span class="btree-cfg-flag">' + escapeText(f) + '</span>').join('') + '</div>';
    html += '<div class="btree-cfg-note">⚠ 弹窗配置（非行为树）。行为树中 <code>Action_Popup</code> / <code>Con_CheckPopup</code> 通过 <code>name</code> 引用此配置。</div>';
    if (items.length) {
        const cols = ['id','viewName','pluginName','popupType','dailyTimes','abbr','interruptOnCancel'];
        html += '<table class="btree-cfg-table"><thead><tr>' + cols.map(c=>'<th>'+c+'</th>').join('') + '</tr></thead><tbody>';
        items.forEach(it => {
            html += '<tr>' + cols.map(c => {
                const v = (it && it[c] != null) ? it[c] : '';
                return '<td>' + escapeText(typeof v === 'object' ? JSON.stringify(v) : v) + '</td>';
            }).join('') + '</tr>';
        }).join('') + '</tbody></table>';
        html += '<div class="btree-cfg-count">' + items.length + ' 个弹窗变体</div>';
    } else {
        html += '<div class="btree-cfg-empty">无 items（弹窗变体）</div>';
    }
    view.innerHTML = html;
}

// ---- 节点 -> Sources 源码 ----
async function btreeResolveNode(name) {
    if (!name) return;
    setStatus('解析 ' + name + ' ...');
    try {
        const r = await fetch('/api/bt/resolve?name=' + encodeURIComponent(name));
        const data = await r.json();
        if (data.found) {
            setStatus('✓ ' + name + ' -> ' + shortPath(data.file) + ':' + data.line);
            openSource(data.file, data.line);
        } else {
            setStatus('⚠ ' + name + ' 未在 Template 找到定义，兜底全代码搜索...');
            btreeFallbackSearch(name);
        }
    } catch (e) { setStatus('解析失败: ' + e.message); }
}

function openSource(file, line) {
    if (window.openExternalSource) window.openExternalSource(file, line);
    else window.open('vscode://file/' + file + ':' + line, '_blank');
}

async function btreeFallbackSearch(name) {
    try {
        const r = await fetch('/api/bt/search?q=' + encodeURIComponent(name));
        const data = await r.json();
        if (data.results && data.results.length) {
            const first = data.results[0];
            setStatus('兜底命中 ' + data.results.length + ' 处，打开第一个: ' + shortPath(first.file) + ':' + first.line);
            openSource(first.file, first.line);
        } else {
            setStatus('✗ ' + name + ' 全代码无命中（可能定义在 subgame bundle 或已移除）');
        }
    } catch (e) { setStatus('搜索失败: ' + e.message); }
}

// ---- 平移/缩放 ----
function clientToViewBox(svg, clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    return { x: (clientX - rect.left) / rect.width * state.vbW, y: (clientY - rect.top) / rect.height * state.vbH };
}
function bindPanZoom(svg, vp) {
    svg.onwheel = (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.12 : 1/1.12;
        const z0 = state.zoom, z1 = Math.max(0.2, Math.min(5, z0 * factor));
        if (z1 === z0) return;
        const vb = clientToViewBox(svg, e.clientX, e.clientY);
        state.pan.x = vb.x - (vb.x - state.pan.x) * (z1 / z0);
        state.pan.y = vb.y - (vb.y - state.pan.y) * (z1 / z0);
        state.zoom = z1;
        vp.setAttribute('transform', vpTransform());
    };
    svg.onmousedown = (e) => {
        if (e.target.closest && e.target.closest('.btree-node')) return;
        state.dragging = true;
        const vb = clientToViewBox(svg, e.clientX, e.clientY);
        state.dragStart = { vbX: vb.x, vbY: vb.y, panX: state.pan.x, panY: state.pan.y };
        svg.style.cursor = 'grabbing';
    };
    svg.onmousemove = (e) => {
        if (!state.dragging) return;
        const vb = clientToViewBox(svg, e.clientX, e.clientY);
        state.pan.x = state.dragStart.panX + (vb.x - state.dragStart.vbX);
        state.pan.y = state.dragStart.panY + (vb.y - state.dragStart.vbY);
        vp.setAttribute('transform', vpTransform());
    };
    const end = () => { state.dragging = false; svg.style.cursor = ''; };
    svg.onmouseup = end; svg.onmouseleave = end;
}
function btreeZoom(factor) {
    const vp = $('btree-viewport'); if (!vp) return;
    const z0 = state.zoom, z1 = Math.max(0.2, Math.min(5, z0 * factor));
    if (z1 === z0) return;
    const cx = state.vbW/2, cy = state.vbH/2;
    state.pan.x = cx - (cx - state.pan.x) * (z1/z0);
    state.pan.y = cy - (cy - state.pan.y) * (z1/z0);
    state.zoom = z1; vp.setAttribute('transform', vpTransform());
}
window.btreeZoom = btreeZoom;
function btreeZoomReset() {
    state.zoom = 1; state.pan = { x:0, y:0 };
    const vp = $('btree-viewport'); if (vp) vp.setAttribute('transform', vpTransform());
}
window.btreeZoomReset = btreeZoomReset;

// ---- 模式切换 ----
function btreeSwitchMode() {
    state.mode = $('btree-mode').value;
    const rt = $('btree-runtime-panel');
    if (state.mode === 'runtime') {
        if (rt) rt.classList.remove('hidden');
        if (state.runtimeTrees.length) renderRuntimeTreeList();
        else { $('btree-tree-list').innerHTML = '<div class="btree-tree-empty">输入 userid 拉取运行时日志</div>'; btreeClearCanvas(); }
        setStatus('运行时日志模式：输入 userid + 日期拉取真机行为树');
    } else {
        if (rt) rt.classList.add('hidden');
        btreeSelectLayer(state.curLayer);
    }
}
window.btreeSwitchMode = btreeSwitchMode;

// ---- 运行时日志（userid）----
async function btreeImportLog() {
    const uid = ($('btree-userid') || {}).value || '';
    const uidT = uid.trim();
    if (!uidT) { setStatus('请输入 userid'); return; }
    const date = (($('btree-date') || {}).value || '').trim();
    setStatus('拉取整目录日志 userid=' + uidT + ' (' + (date || '今天') + ') ...');
    try {
        const url = '/api/bt/runtime_session?userid=' + encodeURIComponent(uidT) + (date ? '&date=' + encodeURIComponent(date) : '');
        const r = await fetch(url);
        const data = await r.json();
        if (!r.ok) { setStatus('✗ ' + (data.error || r.status)); return; }
        state.runtimeTrees = data.trees || [];
        state.mode = 'runtime';
        state.runtimeUserid = uidT;
        state.runtimeDate = date;
        renderRuntimeTreeList();
        const withExec = state.runtimeTrees.filter(t => t.hasExec).length;
        const withStruct = state.runtimeTrees.filter(t => t.hasStructure).length;
        setStatus('✓ ' + data.tree_count + ' 棵树 · ' + withStruct + ' runtime结构 + ' + (withExec - withStruct) + ' 缺口(config兜底)');
    } catch (e) { setStatus('✗ ' + e.message); }
}
window.btreeImportLog = btreeImportLog;

function renderRuntimeTreeList() {
    const list = $('btree-tree-list');
    document.querySelectorAll('.btree-layer-btn').forEach(b => b.classList.remove('active'));
    if (!state.runtimeTrees.length) { list.innerHTML = '<div class="btree-tree-empty">无运行时树</div>'; btreeClearCanvas(); return; }
    list.innerHTML = '';
    state.runtimeTrees.forEach(t => {
        const d = document.createElement('div');
        d.className = 'btree-tree-item' + (t.hasStructure ? '' : ' btree-tree-gap');
        d.textContent = t.name + (t.hasStructure ? '' : ' ·cfg');
        d.title = t.hasStructure ? 'runtime 结构' : '缺口树：结构用 config 兜底（nodeId 一致）';
        d.onclick = () => btreeSelectRuntimeTree(t.name);
        list.appendChild(d);
    });
    setStatus('运行时: ' + state.runtimeTrees.length + ' 棵树');
}

async function btreeSelectRuntimeTree(name) {
    const t = state.runtimeTrees.find(x => x.name === name);
    if (!t) return;
    state.curTree = name;
    state.collapsed.clear();
    state.pan = { x:0, y:0 }; state.zoom = 1;
    state.diffBaseNames = null;
    document.querySelectorAll('.btree-tree-item').forEach(d => d.classList.toggle('active', d.textContent.startsWith(name)));
    // 结构: runtime 优先；缺口树走 find_tree 用 config 兜底（nodeId 与 exec 一致）
    let structure = t.structure;
    if (!structure) {
        setStatus('缺口树 ' + name + ': config 兜底结构 ...');
        try {
            const r = await fetch('/api/bt/find_tree?name=' + encodeURIComponent(name));
            const d = await r.json();
            if (d.found) structure = d.tree;
        } catch (e) {}
    }
    if (!structure) { setStatus('✗ 未找到 ' + name + ' 的结构'); btreeClearCanvas(); return; }
    state.treeData = structure;
    // exec 内联（session 已整目录拉取）
    state.exec = null;
    hideTimeline();
    if (t.exec && t.exec.versions && t.exec.versions.length) {
        state.exec = { versions: t.exec.versions, curVer: t.exec.versions.length - 1, curStep: 0, nodeStates: {}, playing: false, timer: null };
    }
    btreeRender();
    if (state.exec) {
        showTimeline();
        applyExecStep(0);
        setStatus('运行时 ' + name + ' · ' + t.exec.version_count + ' 版本, ' + state.exec.versions[state.exec.curVer].events.length + ' 事件');
    } else {
        setStatus('运行时 ' + name + ' · 无执行轨迹');
    }
}

// ---- 运行时调试: 时间线 + 状态应用 ----
function applyExecStep(k) {
    if (!state.exec) return;
    const ver = state.exec.versions[state.exec.curVer];
    if (!ver) return;
    const evs = ver.events;
    k = Math.max(0, Math.min(k, evs.length));
    const ns = {};
    for (let i = 0; i < k; i++) ns[evs[i].nodeId] = evs[i].state;   // 末次状态胜出
    state.exec.nodeStates = ns;
    state.exec.curStep = k;
    const lbl = $('btree-step-label');
    if (lbl) lbl.textContent = k + ' / ' + evs.length;
    const scrub = $('btree-scrub');
    if (scrub) scrub.value = k;
    btreeRender();
}

function btreeStep(d) {
    if (!state.exec) return;
    stopPlay();
    applyExecStep(state.exec.curStep + d);
}
window.btreeStep = btreeStep;

function btreeScrub(v) {
    if (!state.exec) return;
    applyExecStep(parseInt(v, 10) || 0);
}
window.btreeScrub = btreeScrub;

function btreePlay() {
    if (!state.exec) return;
    const ver = state.exec.versions[state.exec.curVer];
    if (!ver || !ver.events.length) return;
    if (state.exec.playing) { stopPlay(); return; }
    if (state.exec.curStep >= ver.events.length) applyExecStep(0);
    state.exec.playing = true;
    setPlayBtn(true);
    state.exec.timer = setInterval(() => {
        const v = state.exec.versions[state.exec.curVer];
        const next = state.exec.curStep + 1;
        if (!v || next > v.events.length) { stopPlay(); return; }
        applyExecStep(next);
    }, 350);
}
window.btreePlay = btreePlay;

function stopPlay() {
    if (!state.exec) return;
    if (state.exec.timer) clearInterval(state.exec.timer);
    state.exec.timer = null;
    state.exec.playing = false;
    setPlayBtn(false);
}

function setPlayBtn(playing) {
    const b = $('btree-play-btn');
    if (b) b.textContent = playing ? '⏸' : '▶';
}

function btreeSelectVersion() {
    if (!state.exec) return;
    stopPlay();
    const sel = $('btree-version');
    state.exec.curVer = parseInt(sel.value, 10) || 0;
    const ver = state.exec.versions[state.exec.curVer];
    const scrub = $('btree-scrub');
    if (scrub && ver) scrub.max = ver.events.length;
    applyExecStep(0);
}
window.btreeSelectVersion = btreeSelectVersion;

function showTimeline() {
    if (!state.exec) return;
    const tl = $('btree-timeline');
    if (!tl) return;
    tl.classList.remove('hidden');
    const ver = state.exec.versions[state.exec.curVer];
    const scrub = $('btree-scrub');
    if (scrub && ver) { scrub.max = ver.events.length; scrub.value = 0; }
    const sel = $('btree-version');
    if (sel) {
        sel.innerHTML = '';
        state.exec.versions.forEach((v, i) => {
            const o = document.createElement('option');
            o.value = i;
            o.textContent = 'v' + v.version + ' (' + v.events.length + ')';
            sel.appendChild(o);
        });
        sel.value = state.exec.curVer;
    }
}

function hideTimeline() {
    const tl = $('btree-timeline');
    if (tl) tl.classList.add('hidden');
}

})();
