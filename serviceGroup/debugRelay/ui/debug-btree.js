// debug-btree.js - 行为树可视化（四层切换 + SVG 渲染 + 节点跳 TS + 平移缩放折叠）
// 依赖: debugRelay 后端 /api/bt/{layers,tree,resolve,search}
// 渲染约定借鉴 behavior3 editor v0.3.0（节点 display 坐标即编辑器画布坐标），逻辑自行实现。
(function () {
'use strict';

// ---- 节点分类 ----
const COMPOSITES = new Set(['MemPriority','MemPriorityRandom','MemSequence','Sequence','Priority','PriorityRandom','Parallel','ForEach']);
const DECORATORS = new Set(['Inverter','Limiter','Repeater','ReturnSuccess','ReturnFailure','MaxTime','RepeatUntilFailure','RepeatUntilSuccess','InterruptOnFinish','RecorderStatus']);

const CATEGORY_COLOR = {
    composite: '#3b82f6',   // 蓝
    decorator: '#a855f7',   // 紫
    condition: '#f59e0b',   // 橙
    action:    '#22c55e',   // 绿
};
const CATEGORY_LABEL = { composite:'组合', decorator:'装饰', condition:'条件', action:'动作' };

const NODE_W = 172, NODE_H = 60;
const PAD = 80;

// ---- 状态 ----
const state = {
    inited: false,
    layers: {},            // layer_key -> {dir, exists, trees[]}
    curLayer: 'base_btree',
    curTree: null,         // filename stem
    treeData: null,        // {root, nodes, ...}
    diffBaseNames: null,   // Set<lowercase name> 基础层节点名（覆写对比用）
    collapsed: new Set(),  // 折叠的 node id
    pan: { x: 0, y: 0 },
    zoom: 1,
    vbW: 0, vbH: 0,        // viewBox 尺寸
    dragging: false,
    dragStart: null,
};

// ---- 工具 ----
function $(id) { return document.getElementById(id); }
function svgEl(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
}
function setStatus(msg) { const e = $('btree-status'); if (e) e.textContent = msg || ''; }

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
    } catch (e) {
        setStatus('加载失败: ' + e.message);
    }
}
window.btreeInit = btreeInit;

function btreeSelectLayer(layer) {
    state.curLayer = layer;
    state.curTree = null;
    state.treeData = null;
    state.diffBaseNames = null;
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
    document.querySelectorAll('.btree-tree-item').forEach(d => {
        d.classList.toggle('active', d.textContent === name);
    });
    setStatus('加载 ' + state.curLayer + '/' + name + ' ...');
    try {
        const r = await fetch('/api/bt/tree?layer=' + encodeURIComponent(state.curLayer) + '&file=' + encodeURIComponent(name));
        if (!r.ok) { const e = await r.json().catch(()=>({})); setStatus('加载失败: ' + (e.error || r.status)); return; }
        const data = await r.json();
        state.treeData = data.tree;
        state.collapsed.clear();
        state.pan = { x: 0, y: 0 };
        state.zoom = 1;
        if ($('btree-diff') && $('btree-diff').checked) {
            await btreeLoadDiffBase(name);
        } else {
            state.diffBaseNames = null;
        }
        btreeRender();
    } catch (e) {
        setStatus('加载失败: ' + e.message);
    }
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
    } catch (e) {
        state.diffBaseNames = null;
    }
}

async function btreeToggleDiff() {
    if (!$('btree-diff').checked) {
        state.diffBaseNames = null;
        btreeRender();
        return;
    }
    if (state.curTree) await btreeLoadDiffBase(state.curTree);
    btreeRender();
}
window.btreeToggleDiff = btreeToggleDiff;

// ---- 渲染 ----
function btreeClearCanvas() {
    const svg = $('btree-canvas');
    if (svg) svg.innerHTML = '';
    const cfg = $('btree-config-view');
    if (cfg) cfg.classList.add('hidden');
    const empty = $('btree-empty');
    if (empty) empty.style.display = 'block';
}

function btreeRender() {
    const svg = $('btree-canvas');
    const empty = $('btree-empty');
    if (!state.treeData) { btreeClearCanvas(); return; }
    if (empty) empty.style.display = 'none';
    svg.innerHTML = '';

    // 弹窗配置（popup-*.json 非行为树结构，无 nodes/root）-> 配置视图
    const cfgView = $('btree-config-view');
    if (!state.treeData.nodes || !state.treeData.root) {
        if (cfgView) { cfgView.classList.remove('hidden'); renderPopupConfig(state.treeData); }
        setStatus(state.curLayer + '/' + state.curTree + ' · 弹窗配置（非行为树）');
        return;
    }
    if (cfgView) cfgView.classList.add('hidden');

    const nodes = state.treeData.nodes || {};
    const rootId = state.treeData.root;
    if (!rootId || !nodes[rootId]) { setStatus('树无 root 节点'); return; }

    // 计算 bbox（用 display 坐标）
    let minX=Infinity, minY=Infinity, maxX=-Infinity, maxY=-Infinity;
    for (const id in nodes) {
        const d = nodes[id].display || {};
        if (d.x == null || d.y == null) continue;
        if (d.x < minX) minX = d.x;
        if (d.x > maxX) maxX = d.x;
        if (d.y < minY) minY = d.y;
        if (d.y > maxY) maxY = d.y;
    }
    if (minX === Infinity) { minX=0; minY=0; maxX=400; maxY=300; }
    const offX = PAD - minX;
    const offY = PAD - minY;
    const vbW = (maxX - minX) + NODE_W + PAD * 2;
    const vbH = (maxY - minY) + NODE_H + PAD * 2;
    state.vbW = vbW; state.vbH = vbH;
    svg.setAttribute('viewBox', '0 0 ' + vbW + ' ' + vbH);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

    const vp = svgEl('g', { id: 'btree-viewport', transform: vpTransform() });
    svg.appendChild(vp);
    const edgesG = svgEl('g', { class: 'btree-edges' });
    const nodesG = svgEl('g', { class: 'btree-nodes' });
    vp.appendChild(edgesG);
    vp.appendChild(nodesG);

    // 收集可见节点（折叠裁剪子树）
    const visible = new Set();
    (function collect(id) {
        if (!id || !nodes[id] || visible.has(id)) return;
        visible.add(id);
        if (state.collapsed.has(id)) return;
        const n = nodes[id];
        if (Array.isArray(n.children)) n.children.forEach(collect);
        if (n.child) collect(n.child);
    })(rootId);

    // 边
    for (const id of visible) {
        const n = nodes[id];
        if (state.collapsed.has(id)) continue;
        const childIds = Array.isArray(n.children) ? n.children : (n.child ? [n.child] : []);
        childIds.forEach(cid => {
            if (visible.has(cid)) drawEdge(edgesG, n, nodes[cid], offX, offY);
        });
    }
    // 节点
    for (const id of visible) drawNode(nodesG, nodes[id], offX, offY);

    // 统计 + diff
    let added = 0;
    if (state.diffBaseNames) {
        for (const id of visible) {
            if (!state.diffBaseNames.has((nodes[id].name || '').toLowerCase())) added++;
        }
    }
    const diffMsg = state.diffBaseNames ? ' · 对比基础层: 新增 ' + added + '/' + visible.size : '';
    setStatus(state.curLayer + '/' + state.curTree + ' · ' + visible.size + ' 节点' + diffMsg);
    bindPanZoom(svg, vp);
}
window.btreeRender = btreeRender;

// ---- 弹窗配置视图（popup-*.json 非行为树）----
function escapeText(s) {
    return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
}

function renderPopupConfig(data) {
    const view = $('btree-config-view');
    if (!view) return;
    const items = Array.isArray(data.items) ? data.items : [];
    const flagKeys = ['id','popupName','support','maxCount','cd','defaultVersion','abbr'];
    const flags = flagKeys.filter(k => k in data).map(k => k + ': ' + JSON.stringify(data[k]));

    let html = '<div class="btree-cfg-header"><span class="btree-cfg-name">' +
        escapeText(data.popupName || state.curTree) + '</span></div>';
    if (flags.length) {
        html += '<div class="btree-cfg-flags">' +
            flags.map(f => '<span class="btree-cfg-flag">' + escapeText(f) + '</span>').join('') + '</div>';
    }
    html += '<div class="btree-cfg-note">⚠ 弹窗配置（非行为树）。行为树中 <code>Action_Popup</code> / <code>Con_CheckPopup</code> 通过 <code>name</code> 引用此配置。</div>';
    if (items.length) {
        const cols = ['id','viewName','pluginName','popupType','dailyTimes','abbr','interruptOnCancel'];
        html += '<table class="btree-cfg-table"><thead><tr>';
        cols.forEach(c => html += '<th>' + c + '</th>');
        html += '</tr></thead><tbody>';
        items.forEach(it => {
            html += '<tr>';
            cols.forEach(c => {
                const v = (it && it[c] != null) ? it[c] : '';
                html += '<td>' + escapeText(typeof v === 'object' ? JSON.stringify(v) : v) + '</td>';
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
        html += '<div class="btree-cfg-count">' + items.length + ' 个弹窗变体</div>';
    } else {
        html += '<div class="btree-cfg-empty">无 items（弹窗变体）</div>';
    }
    view.innerHTML = html;
}

function vpTransform() {
    return 'translate(' + state.pan.x + ',' + state.pan.y + ') scale(' + state.zoom + ')';
}

function drawEdge(g, parent, child, offX, offY) {
    const pd = parent.display || {x:0,y:0};
    const cd = child.display || {x:0,y:0};
    const px = pd.x + offX + NODE_W / 2;
    const py = pd.y + offY + NODE_H;
    const cx = cd.x + offX + NODE_W / 2;
    const cy = cd.y + offY;
    const my = (py + cy) / 2;
    g.appendChild(svgEl('path', {
        d: 'M ' + px + ' ' + py + ' C ' + px + ' ' + my + ' ' + cx + ' ' + my + ' ' + cx + ' ' + cy,
        class: 'btree-edge', fill: 'none',
    }));
}

function drawNode(g, node, offX, offY) {
    const d = node.display || {x:0,y:0};
    const x = d.x + offX;
    const y = d.y + offY;
    const cat = btreeCategory(node);
    const color = CATEGORY_COLOR[cat];

    let cls = 'btree-node cat-' + cat;
    if (state.diffBaseNames && !state.diffBaseNames.has((node.name || '').toLowerCase())) cls += ' btree-diff-added';

    const grp = svgEl('g', { class: cls, 'data-id': node.id, transform: 'translate(' + x + ',' + y + ')' });

    grp.appendChild(svgEl('rect', { x:0, y:0, width:NODE_W, height:NODE_H, rx:7,
        fill: color, 'fill-opacity': 0.16, stroke: color, 'stroke-width': 1.4 }));
    grp.appendChild(svgEl('rect', { x:0, y:0, width:6, height:NODE_H, rx:3, fill: color }));

    const nameTxt = svgEl('text', { x:14, y:21, class:'btree-node-name' });
    nameTxt.textContent = node.name || '(?)';
    grp.appendChild(nameTxt);

    const badge = svgEl('text', { x:NODE_W-8, y:21, class:'btree-node-cat', 'text-anchor':'end' });
    badge.textContent = CATEGORY_LABEL[cat];
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

// ---- 节点 -> TS 源码 ----
async function btreeResolveNode(name) {
    if (!name) return;
    setStatus('解析 ' + name + ' ...');
    try {
        const r = await fetch('/api/bt/resolve?name=' + encodeURIComponent(name));
        const data = await r.json();
        if (data.found) {
            setStatus('✓ ' + name + ' -> ' + data.file + ':' + data.line);
            window.open(data.vscodeUrl, '_blank');
        } else {
            setStatus('⚠ ' + name + ' 未在 Template 找到定义，兜底全代码搜索...');
            btreeFallbackSearch(name);
        }
    } catch (e) {
        setStatus('解析失败: ' + e.message);
    }
}

async function btreeFallbackSearch(name) {
    try {
        const r = await fetch('/api/bt/search?q=' + encodeURIComponent(name));
        const data = await r.json();
        if (data.results && data.results.length) {
            window.open(data.results[0].vscodeUrl, '_blank');
            setStatus('兜底命中 ' + data.results.length + ' 处，已打开第一个: ' + data.results[0].file + ':' + data.results[0].line);
        } else {
            setStatus('✗ ' + name + ' 全代码无命中（可能定义在 subgame bundle 或已移除）');
        }
    } catch (e) {
        setStatus('搜索失败: ' + e.message);
    }
}

// ---- 平移 / 缩放 ----
function clientToViewBox(svg, clientX, clientY) {
    const rect = svg.getBoundingClientRect();
    return {
        x: (clientX - rect.left) / rect.width * state.vbW,
        y: (clientY - rect.top) / rect.height * state.vbH,
    };
}

function bindPanZoom(svg, vp) {
    svg.onwheel = (e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.12 : 1/1.12;
        const z0 = state.zoom;
        const z1 = Math.max(0.2, Math.min(5, z0 * factor));
        if (z1 === z0) return;
        // 以光标为锚点缩放: screenPos = pan + zoom * vbPt 保持不变
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
    const endDrag = () => { state.dragging = false; svg.style.cursor = ''; };
    svg.onmouseup = endDrag;
    svg.onmouseleave = endDrag;
}

function btreeZoom(factor) {
    const vp = $('btree-viewport');
    if (!vp) return;
    const z0 = state.zoom;
    const z1 = Math.max(0.2, Math.min(5, z0 * factor));
    if (z1 === z0) return;
    // 以 viewBox 中心为锚点
    const cx = state.vbW / 2, cy = state.vbH / 2;
    state.pan.x = cx - (cx - state.pan.x) * (z1 / z0);
    state.pan.y = cy - (cy - state.pan.y) * (z1 / z0);
    state.zoom = z1;
    vp.setAttribute('transform', vpTransform());
}
window.btreeZoom = btreeZoom;

function btreeZoomReset() {
    state.zoom = 1; state.pan = { x:0, y:0 };
    const vp = $('btree-viewport');
    if (vp) vp.setAttribute('transform', vpTransform());
}
window.btreeZoomReset = btreeZoomReset;

// ---- 模式切换 + Phase 2 占位 ----
function btreeSwitchMode() {
    const mode = $('btree-mode').value;
    const rt = $('btree-runtime-panel');
    if (mode === 'runtime') {
        if (rt) rt.classList.remove('hidden');
        setStatus('Phase 2 运行时日志导入：功能开发中（接口已预留）');
    } else {
        if (rt) rt.classList.add('hidden');
    }
}
window.btreeSwitchMode = btreeSwitchMode;

function btreeImportLog() {
    const url = $('btree-log-url').value.trim();
    if (!url) { setStatus('请输入日志 URL'); return; }
    // Phase 2 占位：仅记录，不接逻辑
    setStatus('Phase 2 功能开发中，URL 已记录: ' + url);
}
window.btreeImportLog = btreeImportLog;

})();
