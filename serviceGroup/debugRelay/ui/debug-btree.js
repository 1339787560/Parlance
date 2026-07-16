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
// 弹窗 popupType 配色（popup 配置卡片用）
const POPUP_TYPE_COLOR = { 0:'#6b7280', 1:'#3b82f6', 2:'#22c55e', 3:'#a855f7', 4:'#f59e0b', 5:'#ec4899', 6:'#14b8a6', 7:'#eab308' };

const NODE_W = 172, NODE_H = 72;
const COMP_W = 58, COMP_H = 30;   // Composite 紧凑 pill 尺寸
// Composite 节点符号（&&=Sequence, ||=Priority, M=Memory 前缀）
const COMPOSITE_SYMBOL = {
    Sequence:'&&', Priority:'||', MemSequence:'M&&', MemPriority:'M||',
    Parallel:'Par', ForEach:'Each', MemPriorityRandom:'Mr||', PriorityRandom:'r||'
};
function isCompositeName(name) { return !!COMPOSITE_SYMBOL[name] || COMPOSITES.has(name); }
function compositeSymbol(name) { return COMPOSITE_SYMBOL[name] || (name || '?').slice(0, 3); }
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
    diff: null,              // {added:Set, removed:[node], baseNames:Set} | null
    layerState: {},          // layer -> 上次打开的 tree name（切换层还原）
    collapsed: new Set(),
    runtimeTrees: [],        // [{name, tree}]
    runtimeUserid: null,
    runtimeDate: null,
    exec: null,              // {versions, curVer, curStep, nodeStates, playing, timer}
    layout: {},              // id -> {x,y}
    editing: false,          // 编辑模式（仅覆写层）
    selectedNodeId: null,
    dirty: false,            // 有未保存改动
    catalog: null,           // 节点 palette（分类）
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

// btree 状态持久化（层 + 各层上次树），刷新不重置
function saveBtreePersist() {
    try {
        localStorage.setItem('btree_curLayer', state.curLayer);
        localStorage.setItem('btree_layerState', JSON.stringify(state.layerState));
    } catch (e) {}
}
function loadBtreePersist() {
    try {
        const l = localStorage.getItem('btree_curLayer');
        if (l) state.curLayer = l;
        const ls = localStorage.getItem('btree_layerState');
        if (ls) state.layerState = JSON.parse(ls) || {};
    } catch (e) {}
}

function btreeCategory(node) {
    const name = node.name || '';
    if (COMPOSITES.has(name)) return 'composite';
    if (DECORATORS.has(name)) return 'decorator';
    if (name.indexOf('Con_') === 0) return 'condition';
    if (Array.isArray(node.children) && node.children.length) return 'composite';
    if (node.child) return 'decorator';
    return 'action';
}

function formatProps(props, limit) {
    if (!props) return [];
    if (limit == null) limit = 2;
    const out = [];
    for (const k in props) {
        if (!Object.prototype.hasOwnProperty.call(props, k)) continue;
        let v = props[k];
        if (v === '' || v == null) continue;   // 跳空值，优先显有意义字段
        if (typeof v === 'object') v = JSON.stringify(v);
        out.push(k + ': ' + v);
        if (out.length >= limit) break;
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
    loadBtreePersist();   // 还原上次层 + 各层树（刷新不重置）
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
    saveBtreePersist();   // 记住层
    state.curTree = null;
    state.treeData = null;
    state.diff = null;
    state.editing = false;
    state.selectedNodeId = null;
    state.dirty = false;
    showEditPanel(false);
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
        const span = document.createElement('span');
        span.className = 'btree-tree-name';
        span.textContent = name;
        span.onclick = () => btreeSelectTree(name);
        d.appendChild(span);
        const isBase = layer.indexOf('base_') === 0;
        const btn = document.createElement('button');
        btn.className = 'btree-tree-act';
        btn.title = isBase ? '拷贝到覆写层' : '版本历史(git)';
        btn.textContent = isBase ? '⎘' : '🕓';
        btn.onclick = (e) => { e.stopPropagation(); if (isBase) btreeCopyTree(layer, name); else btreeShowVersions(name); };
        d.appendChild(btn);
        list.appendChild(d);
    });
    setStatus('层: ' + layer + ' (' + info.trees.length + ' 棵树)');
    // 还原该层上次打开的树（配置浏览 tab 状态记忆）
    const last = state.layerState[layer];
    if (last && info.trees.indexOf(last) >= 0) {
        btreeSelectTree(last);
    } else {
        btreeClearCanvas();
    }
}
window.btreeSelectLayer = btreeSelectLayer;

async function btreeSelectTree(name) {
    state.curTree = name;
    state.layerState[state.curLayer] = name;   // 记住该层上次打开的树
    saveBtreePersist();   // 持久化（刷新不重置）
    document.querySelectorAll('.btree-tree-item').forEach(d => d.classList.toggle('active', d.textContent.startsWith(name)));
    setStatus('加载 ' + state.curLayer + '/' + name + ' ...');
    try {
        const r = await fetch('/api/bt/tree?layer=' + encodeURIComponent(state.curLayer) + '&file=' + encodeURIComponent(name));
        if (!r.ok) { const e = await r.json().catch(()=>({})); setStatus('加载失败: ' + (e.error || r.status)); return; }
        const data = await r.json();
        state.treeData = data.tree;
        state.collapsed.clear();
        state.pan = { x: 0, y: 0 }; state.zoom = 1;
        if ($('btree-diff') && $('btree-diff').checked) await btreeLoadDiff(name);
        else state.diff = null;
        btreeRender();
        navRecordBtree(state.curLayer, name, 'config');
    } catch (e) { setStatus('加载失败: ' + e.message); }
}

// ---- 浏览历史（全局 navHistory 在 debug-console.js）+ btree 视图桥接 ----
// 供全局历史记录/恢复时读取与加载 btree 视图
window.btreeNavState = function () { return { layer: state.curLayer, tree: state.curTree, mode: state.mode }; };
window.btreeNavLoad = async function (layer, tree, mode) {
    const wantMode = mode === 'runtime' ? 'runtime' : 'config';
    const m = $('btree-mode');
    if (m) m.value = wantMode;
    btreeSwitchMode();   // 对齐 UI（层 tab 显隐）+ state.mode
    if (wantMode === 'runtime') {
        if (state.runtimeTrees.find(x => x.name === tree)) await btreeSelectRuntimeTree(tree);
    } else {
        if (state.curLayer !== layer) btreeSelectLayer(layer);
        await btreeSelectTree(tree);
    }
};
// RunTree 节点跳转：找目标树（config 搜四层，runtime 搜 runtimeTrees）并加载
async function jumpToTree(target) {
    if (!target) return false;
    if (state.mode === 'runtime') {
        if (state.runtimeTrees.find(x => x.name === target)) { btreeSelectRuntimeTree(target); return true; }
        setStatus('RunTree → ' + target + ' 运行时未找到'); return false;
    }
    const order = [state.curLayer, 'override_btree', 'base_btree', 'override_popup', 'base_popup'];
    const seen = new Set();
    for (const layer of order) {
        if (seen.has(layer)) continue; seen.add(layer);
        const info = state.layers[layer];
        if (info && info.trees && info.trees.indexOf(target) >= 0) {
            if (state.curLayer !== layer) btreeSelectLayer(layer);
            btreeSelectTree(target);
            return true;
        }
    }
    setStatus('RunTree → ' + target + ' 未找到'); return false;
}
// 节点点击跳转目标提取: RunTree->actionName, Action_Popup/Con_CheckPopup->name(popup 配置)
function nodeJumpTarget(node) {
    const nm = (node.name || '').toLowerCase();
    const p = node.properties || {};
    if (nm === 'runtree') return p.actionName || '';
    if (nm === 'action_popup' || nm === 'con_checkpopup') return p.name || '';
    return '';
}
function btreeNodeClick(node) {
    if (state.editing) { btreeSelectNode(node.id); return; }   // 编辑模式：选中节点
    const target = nodeJumpTarget(node);
    if (target) { jumpToTree(target); return; }
    btreeResolveNode(node.name);
}
function btreeSelectNode(id) {
    state.selectedNodeId = id;
    btreeRender();
    renderEditPanel();
}
async function btreeLoadDiff(name) {
    const baseLayer = state.curLayer.replace('override_', 'base_');
    if (baseLayer === state.curLayer) { state.diff = null; return; }
    try {
        const r = await fetch('/api/bt/tree?layer=' + encodeURIComponent(baseLayer) + '&file=' + encodeURIComponent(name));
        if (!r.ok) { state.diff = null; return; }
        const data = await r.json();
        const baseNodes = (data.tree && data.tree.nodes) || {};
        const curNodes = (state.treeData && state.treeData.nodes) || {};
        const baseNames = new Set();
        for (const id in baseNodes) baseNames.add((baseNodes[id].name || '').toLowerCase());
        const curNames = new Set();
        for (const id in curNodes) curNames.add((curNodes[id].name || '').toLowerCase());
        const added = new Set();
        curNames.forEach(n => { if (!baseNames.has(n)) added.add(n); });
        const removed = [];
        const seen = new Set();
        for (const id in baseNodes) {
            const n = baseNodes[id];
            const ln = (n.name || '').toLowerCase();
            if (!curNames.has(ln) && !seen.has(ln)) { seen.add(ln); removed.push(n); }
        }
        state.diff = { added, removed, baseNames, curNames };
    } catch (e) { state.diff = null; }
}

async function btreeToggleDiff() {
    if (!$('btree-diff').checked) { state.diff = null; btreeRender(); return; }
    if (state.curTree && state.mode === 'config') await btreeLoadDiff(state.curTree);
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
    // 覆写对比: 移除节点簇（右侧 ghost 区）
    let removedLayout = {};
    if (state.diff && state.diff.removed.length) {
        const clusterX = maxX + LEVEL_W * 1.3;
        state.diff.removed.forEach((node, i) => {
            removedLayout[node.id] = { x: clusterX, y: minY + (i + 1) * (NODE_H + V_GAP) };
        });
        maxX = clusterX + NODE_W;
        maxY = Math.max(maxY, minY + (state.diff.removed.length + 1) * (NODE_H + V_GAP));
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
        childIds.forEach(cid => { if (visible.has(cid)) drawEdge(edgesG, n, state.layout[id], state.layout[cid], offX, offY); });
    }
    for (const id of visible) drawNode(nodesG, nodes[id], state.layout[id], offX, offY);
    // 覆写对比: 渲染移除节点簇（ghost，右侧）+ 簇头
    if (state.diff && state.diff.removed.length) {
        const clusterX = (removedLayout[state.diff.removed[0].id] || {x:0}).x + offX;
        const hdr = svgEl('text', { x: clusterX, y: minY + offY - 6, class: 'btree-diff-header btree-diff-removed' });
        hdr.textContent = '— 移除 ' + state.diff.removed.length + ' —';
        nodesG.appendChild(hdr);
        state.diff.removed.forEach(node => {
            const pos = removedLayout[node.id];
            if (pos) drawNode(nodesG, node, pos, offX, offY, 'removed');
        });
    }

    let added = 0;
    if (state.diff && state.diff.added) for (const id of visible) if (state.diff.added.has((nodes[id].name || '').toLowerCase())) added++;
    const removedCount = (state.diff && state.diff.removed.length) || 0;
    const diffMsg = state.diff ? ' · 🟢新增 ' + added + ' 🔴移除 ' + removedCount : '';
    const src = state.mode === 'runtime' ? '运行时' : state.curLayer;
    setStatus(src + '/' + (state.curTree||'?') + ' · ' + visible.size + ' 节点' + diffMsg);
    bindPanZoom(svg, vp);
}
window.btreeRender = btreeRender;

function vpTransform() { return 'translate(' + state.pan.x + ',' + state.pan.y + ') scale(' + state.zoom + ')'; }

// 边: 父右边中心 -> 子左边中心（右出左入）
function drawEdge(g, parentNode, pp, cp, offX, offY) {
    const pw = (parentNode && isCompositeName(parentNode.name)) ? COMP_W : NODE_W;
    const px = pp.x + offX + pw;
    const py = pp.y + offY + NODE_H / 2;   // 节点垂直居中于 NODE_H 槽
    const cx = cp.x + offX;
    const cy = cp.y + offY + NODE_H / 2;
    const mx = (px + cx) / 2;
    g.appendChild(svgEl('path', {
        d: 'M ' + px + ' ' + py + ' C ' + mx + ' ' + py + ' ' + mx + ' ' + cy + ' ' + cx + ' ' + cy,
        class: 'btree-edge', fill: 'none',
    }));
}

function drawNode(g, node, pos, offX, offY, forceStyle) {
    const x = pos.x + offX, y = pos.y + offY;
    const cat = btreeCategory(node);
    const color = CATEGORY_COLOR[cat];
    let cls = 'btree-node cat-' + cat;
    if (state.editing && state.selectedNodeId === node.id) cls += ' btree-selected';

    // 覆写对比 diff 样式：新增(绿) / 移除(红 ghost)
    let diffKind = forceStyle || null;
    if (!diffKind && state.diff && state.diff.added && state.diff.added.has((node.name || '').toLowerCase())) diffKind = 'added';

    // 运行时调试着色：未播放=实色清晰；播放过=蒙雾 + 状态色边框
    const inDebug = !!state.exec;
    const execState = (inDebug && state.exec.nodeStates && state.exec.nodeStates[node.id] !== undefined) ? state.exec.nodeStates[node.id] : null;

    let bodyFill = color, bodyOp = inDebug ? 0.60 : 0.18, stroke = color, sw = 1.4;
    let fog = false, ghost = false, dash = null, badgeText = null, badgeColor = null;
    if (diffKind === 'added') {
        bodyFill = '#22c55e'; bodyOp = 0.22; stroke = '#22c55e'; sw = 2.2; dash = '5 3';
        cls += ' btree-diff-added'; badgeText = '+新增'; badgeColor = '#22c55e';
    } else if (diffKind === 'removed') {
        bodyFill = '#ef4444'; bodyOp = 0.14; stroke = '#ef4444'; sw = 2.2; dash = '5 3'; ghost = true;
        cls += ' btree-diff-removed'; badgeText = '✕移除'; badgeColor = '#ef4444';
    } else if (execState !== null) {
        // 已执行: 蒙雾感（淡底 + 暗雾叠加 + 状态色边框）
        const sc = STATE_COLOR[execState] || color;
        bodyFill = sc; bodyOp = 0.12; stroke = sc; sw = 2.6; fog = true;
        cls += ' exec-state-' + execState; badgeText = STATE_LABEL[execState]; badgeColor = sc;
    }

    // Composite: 紧凑 pill + 符号（M&& / M|| / && / || ...），垂直居中于 NODE_H 槽
    if (isCompositeName(node.name)) {
        const cy = (NODE_H - COMP_H) / 2;
        const grp = svgEl('g', { class: cls + ' btree-composite', 'data-id': node.id, transform: 'translate(' + x + ',' + (y + cy) + ')' });
        if (ghost) grp.setAttribute('opacity', '0.5');
        const rAttrs = { x:0, y:0, width:COMP_W, height:COMP_H, rx:COMP_H/2, fill: bodyFill, 'fill-opacity':bodyOp, stroke: stroke, 'stroke-width':sw };
        if (dash) rAttrs['stroke-dasharray'] = dash;
        grp.appendChild(svgEl('rect', rAttrs));
        if (fog) grp.appendChild(svgEl('rect', { x:0, y:0, width:COMP_W, height:COMP_H, rx:COMP_H/2, fill:'#000', 'fill-opacity':0.48 }));
        const sym = svgEl('text', { x:COMP_W/2, y:COMP_H/2 + 4, class:'btree-comp-sym', 'text-anchor':'middle' });
        sym.textContent = compositeSymbol(node.name);
        if (badgeColor) sym.setAttribute('fill', badgeColor);
        grp.appendChild(sym);
        if ((Array.isArray(node.children) && node.children.length) || node.child) {
            const tog = svgEl('text', { x:COMP_W + 4, y:COMP_H - 1, class:'btree-collapse-toggle', 'font-size':10 });
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
            btreeNodeClick(node);
        });
        const tip = svgEl('title');
        let tipText = node.name + ' (' + compositeSymbol(node.name) + ')' + (node.title ? '\n' + node.title : '');
        if (execState !== null) tipText += '\n[运行时] ' + (STATE_LABEL[execState] || '?');
        tip.textContent = tipText;
        grp.appendChild(tip);
        g.appendChild(grp);
        return;
    }

    const rectAttrs = { x:0, y:0, width:NODE_W, height:NODE_H, rx:7, fill: bodyFill, 'fill-opacity':bodyOp, stroke: stroke, 'stroke-width':sw };
    if (dash) rectAttrs['stroke-dasharray'] = dash;
    const grp = svgEl('g', { class: cls, 'data-id': node.id, transform: 'translate(' + x + ',' + y + ')' });
    if (ghost) grp.setAttribute('opacity', '0.5');
    grp.appendChild(svgEl('rect', rectAttrs));
    grp.appendChild(svgEl('rect', { x:0, y:0, width:6, height:NODE_H, rx:3, fill: color }));   // 左条保留分类色
    if (fog) {
        grp.appendChild(svgEl('rect', { x:6, y:0, width:NODE_W-6, height:NODE_H, fill:'#000', 'fill-opacity':0.48 }));  // 蒙雾叠加
    }

    const nameTxt = svgEl('text', { x:14, y:21, class:'btree-node-name' });
    nameTxt.textContent = node.name || '(?)';
    grp.appendChild(nameTxt);

    const badge = svgEl('text', { x:NODE_W-8, y:21, class:'btree-node-cat', 'text-anchor':'end' });
    if (badgeText) { badge.textContent = badgeText; badge.setAttribute('fill', badgeColor); }
    else badge.textContent = CATEGORY_LABEL[cat];
    grp.appendChild(badge);

    formatProps(node.properties, 3).forEach((p, i) => {
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
        btreeNodeClick(node);
    });

    const tip = svgEl('title');
    let tipText = node.name + '\n' + (node.title || '');
    if (formatProps(node.properties, 999).length) tipText += '\n[配置] ' + formatProps(node.properties, 999).join(' | ');
    const jt = nodeJumpTarget(node);
    if (jt) tipText += '\n→ 点击跳转: ' + jt;
    if (state.exec && state.exec.nodeStates && state.exec.nodeStates[node.id] !== undefined) {
        tipText += '\n[运行时] ' + (STATE_LABEL[state.exec.nodeStates[node.id]] || '?');
        const ip = state.exec.nodeInProps && state.exec.nodeInProps[node.id];
        if (ip) tipText += '  inProps=' + ip;
    }
    tip.textContent = tipText;
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
    const flags = flagKeys.filter(k => k in data && data[k] !== '' && data[k] != null)
        .map(k => k + ': ' + JSON.stringify(data[k]));
    let html = '<div class="btree-cfg-header"><span class="btree-cfg-name">' + escapeText(data.popupName || state.curTree) + '</span>';
    html += '<span class="btree-cfg-sub">弹窗配置 · ' + items.length + ' 个变体</span></div>';
    if (flags.length) {
        html += '<div class="btree-cfg-flags">' + flags.map(f => '<span class="btree-cfg-flag">' + escapeText(f) + '</span>').join('') + '</div>';
    }
    html += '<div class="btree-cfg-note">⚠ 弹窗配置（非行为树）。行为树中 <code>Action_Popup</code> / <code>Con_CheckPopup</code> 通过 <code>name</code> 引用此配置。</div>';
    if (items.length) {
        html += '<div class="btree-cfg-cards">';
        items.forEach(it => {
            const pt = (it && it.popupType != null) ? it.popupType : '?';
            const color = POPUP_TYPE_COLOR[pt] || '#6b7280';
            const meta = [];
            if (it && it.dailyTimes != null) meta.push('daily ' + it.dailyTimes);
            if (it && it.abbr) meta.push('abbr ' + it.abbr);
            if (it && it.interruptOnCancel) meta.push('interruptOnCancel');
            if (it && it.id != null) meta.push('id ' + it.id);
            html += '<div class="btree-cfg-card" style="border-left-color:' + color + '">';
            html += '<span class="btree-cfg-card-pt" style="background:' + color + '">type ' + escapeText(pt) + '</span>';
            html += '<div class="btree-cfg-card-view">' + escapeText((it && it.viewName) || '(无 view)') + '</div>';
            html += '<div class="btree-cfg-card-plugin">' + escapeText((it && it.pluginName) || '') + '</div>';
            html += '<div class="btree-cfg-card-meta">' + escapeText(meta.join(' · ')) + '</div>';
            html += '</div>';
        });
        html += '</div>';
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
    const end = () => { state.dragging = false; svg.style.cursor = 'default'; };
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
    stopPlay();   // 切模式前停播放，隔离 timer
    state.mode = $('btree-mode').value;
    const rt = $('btree-runtime-panel');
    const layerTabs = $('btree-layer-tabs');
    const diffToggle = document.querySelector('.btree-diff-toggle');
    // 运行时: 隐藏层 tab + 覆写对比（不适用）；配置浏览: 展开
    const showConfigUi = state.mode !== 'runtime';
    if (layerTabs) layerTabs.style.display = showConfigUi ? '' : 'none';
    if (diffToggle) diffToggle.style.display = showConfigUi ? '' : 'none';
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
    state.diff = null;
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
    // exec 内联（session 已整目录拉取）—— 先停旧树播放再换，隔离 timer
    stopPlay();
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
    navRecordBtree(state.curLayer, name, 'runtime');
}

// ---- 编辑模式（仅覆写层，自动布局无需连线）----
function _canEdit() { return state.mode === 'config' && (state.curLayer === 'override_btree' || state.curLayer === 'override_popup') && !!state.treeData; }
function markDirty() { state.dirty = true; updateEditPanelHead(); }
function showEditPanel(show) { const p = $('btree-edit-panel'); if (p) p.classList.toggle('hidden', !show); }
function updateEditPanelHead() { const h = $('btree-edit-dirty'); if (h) h.textContent = state.dirty ? '● 未保存' : ''; }

async function btreeToggleEdit() {
    if (!_canEdit()) { setStatus('仅覆写层(override_btree/popup) 可编辑，且需选中树'); return; }
    state.editing = !state.editing;
    if (!state.editing) state.selectedNodeId = null;
    showEditPanel(state.editing);
    if (state.editing && !state.catalog) {
        try { const r = await fetch('/api/btree/nodes_catalog'); state.catalog = (await r.json()).catalog; } catch (e) {}
    }
    btreeRender();
    if (state.editing) renderEditPanel();
    setStatus(state.editing ? '编辑模式：点节点选中，右下面板编辑/加子/删除/保存' : '');
}
window.btreeToggleEdit = btreeToggleEdit;

function renderEditPanel() {
    const body = $('btree-edit-body');
    if (!body) return;
    const node = state.selectedNodeId && state.treeData && state.treeData.nodes ? state.treeData.nodes[state.selectedNodeId] : null;
    if (!node) { body.innerHTML = '<div class="btree-edit-empty">点选一个节点编辑</div>'; return; }
    const cat = btreeCategory(node);
    const props = node.properties || {};
    let html = '<div class="btree-edit-node"><b>' + escapeText(node.name) + '</b> <span class="btree-edit-cat">' + cat + '</span></div>';
    html += '<div class="btree-edit-row"><label>title</label><input id="btree-edit-title" value="' + escapeText(node.title || '') + '"></div>';
    html += '<div class="btree-edit-sec">属性</div><div id="btree-edit-props">';
    Object.keys(props).forEach(k => {
        const v = typeof props[k] === 'object' ? JSON.stringify(props[k]) : props[k];
        html += '<div class="btree-edit-prop"><input class="btree-edit-pk" data-oldk="' + escapeText(k) + '" value="' + escapeText(k) + '"><input class="btree-edit-pv" value="' + escapeText(v) + '"><button class="btree-edit-pdel" data-k="' + escapeText(k) + '">×</button></div>';
    });
    html += '</div>';
    html += '<button class="btree-edit-addprop">+ 加属性</button>';
    body.innerHTML = html;
    const ti = $('btree-edit-title');
    if (ti) ti.oninput = () => { node.title = ti.value; markDirty(); btreeRender(); };
    body.querySelectorAll('.btree-edit-pk').forEach(pk => {
        const pv = pk.parentElement.querySelector('.btree-edit-pv');
        const oldk = pk.getAttribute('data-oldk');
        pk.onchange = () => { const nk = pk.value.trim(); const v = node.properties[oldk]; delete node.properties[oldk]; node.properties[nk] = v; pk.setAttribute('data-oldk', nk); markDirty(); btreeRender(); };
        if (pv) pv.oninput = () => { node.properties[pk.getAttribute('data-oldk')] = pv.value; markDirty(); btreeRender(); };
    });
    body.querySelectorAll('.btree-edit-pdel').forEach(b => b.onclick = () => btreeDelProp(b.getAttribute('data-k')));
    const ap = body.querySelector('.btree-edit-addprop');
    if (ap) ap.onclick = btreeAddProp;
}

function btreeAddProp() {
    const node = state.selectedNodeId && state.treeData.nodes[state.selectedNodeId];
    if (!node) return;
    node.properties = node.properties || {};
    let k = 'newProp', i = 1;
    while (node.properties[k] !== undefined) k = 'newProp' + (++i);
    node.properties[k] = '';
    markDirty(); renderEditPanel(); btreeRender();
}
window.btreeAddProp = btreeAddProp;
function btreeDelProp(k) {
    const node = state.selectedNodeId && state.treeData.nodes[state.selectedNodeId];
    if (!node || !node.properties) return;
    delete node.properties[k];
    markDirty(); renderEditPanel(); btreeRender();
}
window.btreeDelProp = btreeDelProp;

function btreeShowPalette() {
    if (!state.selectedNodeId) { setStatus('先选中一个父节点'); return; }
    const ov = $('btree-palette-overlay');
    if (!ov) return;
    ov.classList.remove('hidden');
    const body = $('btree-palette-body');
    const cat = state.catalog || { composite: [], decorator: [], condition: [], action: [] };
    const labels = { composite: '组合', decorator: '装饰', condition: '条件', action: '动作' };
    body.innerHTML = '';
    ['composite', 'decorator', 'condition', 'action'].forEach(c => {
        const names = cat[c] || [];
        if (!names.length) return;
        const sec = document.createElement('div');
        sec.innerHTML = '<div class="btree-pal-sec">' + labels[c] + '</div>';
        const grid = document.createElement('div');
        grid.className = 'btree-pal-grid';
        names.forEach(n => {
            const b = document.createElement('button');
            b.className = 'btree-pal-node';
            b.textContent = n;
            b.onclick = () => { btreeAddChild(state.selectedNodeId, n); btreeClosePalette(); };
            grid.appendChild(b);
        });
        sec.appendChild(grid);
        body.appendChild(sec);
    });
}
window.btreeShowPalette = btreeShowPalette;
function btreeClosePalette() { const ov = $('btree-palette-overlay'); if (ov) ov.classList.add('hidden'); }
window.btreeClosePalette = btreeClosePalette;

function btreeAddChild(parentId, nodeName) {
    const nodes = state.treeData.nodes;
    const parent = nodes[parentId];
    if (!parent) return;
    const id = (crypto.randomUUID ? crypto.randomUUID() : 'n' + Date.now() + Math.random().toString(36).slice(2));
    nodes[id] = { id, name: nodeName, title: '', properties: {}, display: { x: 0, y: 0 } };
    parent.children = Array.isArray(parent.children) ? parent.children : [];
    parent.children.push(id);
    state.selectedNodeId = id;
    state.dirty = true;
    btreeRender();
    renderEditPanel();
    setStatus('已加 ' + nodeName + ' 为子节点（未保存）');
}

function btreeDeleteNode() {
    const id = state.selectedNodeId;
    if (!id || !state.treeData) return;
    if (id === state.treeData.root) { setStatus('不能删除根节点'); return; }
    const nodes = state.treeData.nodes;
    const toDel = new Set();
    (function walk(nid) { if (!nodes[nid] || toDel.has(nid)) return; toDel.add(nid); const n = nodes[nid]; if (Array.isArray(n.children)) n.children.forEach(walk); if (n.child) walk(n.child); })(id);
    for (const pid in nodes) {
        const p = nodes[pid];
        if (Array.isArray(p.children)) p.children = p.children.filter(c => c !== id);
        if (p.child === id) p.child = undefined;
    }
    toDel.forEach(d => delete nodes[d]);
    state.selectedNodeId = null;
    state.dirty = true;
    btreeRender();
    renderEditPanel();
    setStatus('已删除节点（未保存）');
}
window.btreeDeleteNode = btreeDeleteNode;

async function btreeSaveEdit() {
    if (!state.treeData || state.curLayer.indexOf('override_') !== 0) { setStatus('仅覆写层可保存'); return; }
    setStatus('保存 + git commit ...');
    try {
        const r = await fetch('/api/btree/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ layer: state.curLayer, name: state.curTree, tree: state.treeData }) });
        const d = await r.json();
        if (!r.ok) { setStatus('✗ ' + (d.detail || r.status)); return; }
        state.dirty = false;
        updateEditPanelHead();
        setStatus('✓ 已保存 ' + state.curTree + ' (git: ' + d.git + ')');
    } catch (e) { setStatus('✗ ' + e.message); }
}
window.btreeSaveEdit = btreeSaveEdit;

// ---- 拷贝基础→覆写 + 版本历史(git) ----
async function btreeCopyTree(baseLayer, name) {
    setStatus('拷贝 ' + baseLayer + '/' + name + ' → 覆写层 ...');
    try {
        const r = await fetch('/api/btree/copy', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_layer: baseLayer, name }) });
        const d = await r.json();
        if (!r.ok) { setStatus('✗ ' + (d.detail || d.error || r.status)); return; }
        setStatus(d.copied ? ('✓ 已拷贝 ' + name + ' 到覆写层') : ('⊙ ' + name + ' 覆写层已存在，跳过'));
        if (d.copied) {   // 刷新层列表（覆写层多了一棵）
            const lr = await fetch('/api/bt/layers'); const ld = await lr.json(); state.layers = ld.layers || {};
        }
    } catch (e) { setStatus('✗ ' + e.message); }
}
window.btreeCopyTree = btreeCopyTree;

async function btreeShowVersions(name) {
    const ov = $('btree-versions-overlay');
    if (!ov) return;
    ov.classList.remove('hidden');
    const list = $('btree-versions-list');
    const title = $('btree-versions-title');
    if (title) title.textContent = state.curLayer + '/' + name + ' 版本历史';
    list.innerHTML = '<div class="btree-tree-empty">加载版本...</div>';
    try {
        const r = await fetch('/api/btree/versions?layer=' + encodeURIComponent(state.curLayer) + '&name=' + encodeURIComponent(name));
        const d = await r.json();
        if (!d.git || !d.versions.length) { list.innerHTML = '<div class="btree-tree-empty">无 git 历史</div>'; return; }
        list.innerHTML = '';
        d.versions.forEach(v => {
            const row = document.createElement('div');
            row.className = 'btree-ver-row';
            const info = document.createElement('div');
            info.className = 'btree-ver-info';
            info.innerHTML = '<span class="btree-ver-hash">' + escapeText(v.hash) + '</span>'
                + '<span class="btree-ver-date">' + escapeText(v.date) + '</span>'
                + '<span class="btree-ver-sub">' + escapeText(v.subject) + '</span>';
            row.appendChild(info);
            const rb = document.createElement('button');
            rb.className = 'btree-ver-restore';
            rb.textContent = '回滚';
            rb.onclick = () => btreeRestoreVersion(name, v.hash);
            row.appendChild(rb);
            list.appendChild(row);
        });
    } catch (e) { list.innerHTML = '<div class="btree-tree-empty">加载失败: ' + e.message + '</div>'; }
}
window.btreeShowVersions = btreeShowVersions;

async function btreeRestoreVersion(name, hash) {
    if (!confirm('回滚 ' + name + ' 到 ' + hash + '？')) return;
    try {
        const r = await fetch('/api/btree/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ layer: state.curLayer, name, hash }) });
        const d = await r.json();
        if (!r.ok) { setStatus('✗ ' + (d.detail || r.status)); return; }
        setStatus('✓ 已回滚 ' + name + ' → ' + hash);
        btreeCloseVersions();
        if (state.curTree === name) btreeSelectTree(name);   // 重载
    } catch (e) { setStatus('✗ ' + e.message); }
}
window.btreeRestoreVersion = btreeRestoreVersion;

function btreeCloseVersions() { const ov = $('btree-versions-overlay'); if (ov) ov.classList.add('hidden'); }
window.btreeCloseVersions = btreeCloseVersions;

// ---- 运行时调试: 时间线 + 状态应用 ----
function applyExecStep(k) {
    if (!state.exec) return;
    const ver = state.exec.versions[state.exec.curVer];
    if (!ver) return;
    const evs = ver.events;
    k = Math.max(0, Math.min(k, evs.length));
    const ns = {}, np = {};   // 末次状态 / 末次 inProps 胜出
    for (let i = 0; i < k; i++) {
        ns[evs[i].nodeId] = evs[i].state;
        if (evs[i].inProps) np[evs[i].nodeId] = evs[i].inProps;
    }
    state.exec.nodeStates = ns;
    state.exec.nodeInProps = np;
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
    const ex = state.exec;
    const ver = ex.versions[ex.curVer];
    if (!ver || !ver.events.length) return;
    if (ex.playing) { stopPlay(); return; }
    if (ex.curStep >= ver.events.length) applyExecStep(0);
    ex.playing = true;
    setPlayBtn(true);
    // 捕获本次 exec 引用: 若已切树/切模式(state.exec 不再是 ex)则自杀, 隔离播放
    ex.timer = setInterval(() => {
        if (state.exec !== ex) { clearInterval(ex.timer); return; }
        const v = ex.versions[ex.curVer];
        const next = ex.curStep + 1;
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

// 键盘单步调试（行为树面板激活 + 运行时 exec 存在时）：←/→ 单步，空格 播放/暂停
document.addEventListener('keydown', (e) => {
    if (!state.exec) return;
    const panel = document.getElementById('panel-btree');
    if (!panel || !panel.classList.contains('active')) return;
    const tag = (e.target && e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); btreeStep(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); btreeStep(1); }
    else if (e.key === ' ') { e.preventDefault(); btreePlay(); }
});

})();
