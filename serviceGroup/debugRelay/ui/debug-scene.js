/**
 * Scene Panel — left hierarchy + right inspector.
 *
 * UX target:
 * - Left: every node is one row/tab, first level visible by default.
 * - Row arrow expands/collapses children.
 * - Row click selects node, right inspector edits runtime properties.
 */

let sceneTreeData = null;
let sceneSelectedPath = null;
let sceneSelectedInfo = null;
const sceneExpanded = new Set();

// ─────────────────────────────────────────────────────────────
// Requests / WS handlers
// ─────────────────────────────────────────────────────────────

function sceneRefreshTree() {
    sceneSend({ type: 'scene_get_tree' });
    const treeEl = document.getElementById('scene-tree');
    if (treeEl) treeEl.innerHTML = '<div class="scene-loading">Loading scene tree...</div>';
}

function handleSceneTree(msg) {
    if (msg.error) {
        const treeEl = document.getElementById('scene-tree');
        if (treeEl) treeEl.innerHTML = `<div class="scene-error">${sceneEsc(msg.error)}</div>`;
        return;
    }

    sceneTreeData = msg.tree;
    if (sceneTreeData && sceneExpanded.size === 0) {
        // Default: root expanded, first-level nodes visible.
        sceneExpanded.add(sceneTreeData.path);
    }
    sceneRenderTree();
}

function handleSceneNodeInfo(msg) {
    sceneSelectedInfo = msg;
    sceneRenderInspector(msg);
}

function sceneSend(msg) {
    if (typeof wsSend === 'function') {
        wsSend(msg);
    } else {
        console.warn('[scene] wsSend not available');
    }
}

// ─────────────────────────────────────────────────────────────
// Tree rendering
// ─────────────────────────────────────────────────────────────

function sceneRenderTree() {
    const treeEl = document.getElementById('scene-tree');
    if (!treeEl) return;
    treeEl.innerHTML = '';

    if (!sceneTreeData) {
        treeEl.innerHTML = '<div class="scene-empty">No scene tree</div>';
        return;
    }

    const frag = document.createDocumentFragment();
    sceneRenderTreeRows(sceneTreeData, 0, frag);
    treeEl.appendChild(frag);
}

function sceneRenderTreeRows(node, depth, parentEl) {
    const row = document.createElement('div');
    row.className = 'scene-node-tab';
    if (!node.active) row.classList.add('inactive');
    if (node.path === sceneSelectedPath) row.classList.add('selected');
    row.dataset.path = node.path;
    row.style.setProperty('--depth', String(depth));

    const children = node.children || [];
    const hasChildren = children.length > 0;
    const expanded = sceneExpanded.has(node.path);

    const arrow = document.createElement('button');
    arrow.className = 'scene-node-arrow' + (hasChildren ? '' : ' leaf');
    arrow.textContent = hasChildren ? (expanded ? '▾' : '▸') : '';
    arrow.title = expanded ? '折叠' : '展开';
    arrow.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!hasChildren) return;
        if (sceneExpanded.has(node.path)) sceneExpanded.delete(node.path);
        else sceneExpanded.add(node.path);
        sceneRenderTree();
    });
    row.appendChild(arrow);

    const state = document.createElement('span');
    state.className = 'scene-node-state ' + (node.activeInHierarchy ? 'on' : 'off');
    state.title = node.activeInHierarchy ? 'activeInHierarchy=true' : 'activeInHierarchy=false';
    row.appendChild(state);

    const name = document.createElement('span');
    name.className = 'scene-node-title';
    name.textContent = node.name;
    row.appendChild(name);

    if (node.components && node.components.length > 0) {
        const badge = document.createElement('span');
        badge.className = 'scene-node-badge';
        badge.textContent = node.components.length;
        badge.title = node.components.join(', ');
        row.appendChild(badge);
    }

    row.addEventListener('click', () => sceneSelectNode(node.path));
    parentEl.appendChild(row);

    if (hasChildren && expanded) {
        for (const child of children) {
            sceneRenderTreeRows(child, depth + 1, parentEl);
        }
    }
}

function sceneSelectNode(path) {
    sceneSelectedPath = path;
    sceneRenderTree();
    sceneRenderInspectorLoading(path);
    // 点节点前先刷新场景树，避免缓存的 path 已过期
    sceneSend({ type: 'scene_get_tree' });
    sceneSend({ type: 'scene_get_node_info', path });
}

function sceneRenderInspectorLoading(path) {
    const el = document.getElementById('scene-detail');
    if (!el) return;
    el.innerHTML = `<div class="inspector-empty">Loading ${sceneEsc(path)}...</div>`;
}

// ─────────────────────────────────────────────────────────────
// Inspector rendering
// ─────────────────────────────────────────────────────────────

function sceneRenderInspector(info) {
    const el = document.getElementById('scene-detail');
    if (!el) return;

    if (!info) {
        el.innerHTML = '<div class="inspector-empty">Select a node</div>';
        return;
    }

    if (info.error) {
        el.innerHTML = `<div class="scene-error">${sceneEsc(info.error)}</div>`;
        return;
    }

    const path = info.path;
    let html = '';

    html += `<div class="inspector-head">`;
    html += `<div class="inspector-title">${sceneEsc(info.name)}</div>`;
    html += `<div class="inspector-path">${sceneEsc(path)}</div>`;
    html += `</div>`;

    html += `<div class="inspector-section open">`;
    html += `<div class="inspector-section-head">Node</div>`;
    html += `<div class="inspector-section-body">`;
    html += inspectorRow('Visible', sceneBool(path, '__node__', 'active', info.active));
    html += inspectorRow('In Hierarchy', `<span class="scene-readonly ${info.activeInHierarchy ? 'ok' : 'bad'}">${info.activeInHierarchy}</span>`);
    html += inspectorRow('Position', sceneVec3(path, '__node__', 'position', info.position || { x: 0, y: 0, z: 0 }));
    html += inspectorRow('Scale', sceneVec3(path, '__node__', 'scale', info.scale || { x: 1, y: 1, z: 1 }, 0.01));
    html += inspectorRow('Rotation', sceneVec3(path, '__node__', 'eulerAngles', info.eulerAngles || { x: 0, y: 0, z: 0 }));
    html += inspectorRow('Layer', sceneNumber(path, '__node__', 'layer', info.layer ?? 0, 1));
    html += `</div></div>`;

    const components = info.components || [];
    html += renderPreferredComponent(path, components, 'UITransform', 'UITransform');
    html += renderPreferredComponent(path, components, 'Widget', 'Widget');
    html += renderPreferredComponent(path, components, 'Layout', 'Layout');

    const shown = new Set(['UITransform', 'Widget', 'Layout']);
    for (const comp of components) {
        if (shown.has(comp.name)) continue;
        html += renderGenericComponent(path, comp);
    }

    el.innerHTML = html;
    sceneBindInspectorInputs(el);
}

function renderPreferredComponent(path, components, compName, title) {
    const comp = components.find(c => c.name === compName);
    if (!comp) return '';
    return renderGenericComponent(path, comp, title, true);
}

function renderGenericComponent(path, comp, title, open = false) {
    const props = comp.properties || {};
    const keys = Object.keys(props);
    let html = '';
    html += `<div class="inspector-section ${open ? 'open' : ''}" data-comp="${sceneEsc(comp.name)}">`;
    html += `<div class="inspector-section-head" onclick="this.parentElement.classList.toggle('open')">`;
    html += `<span class="section-caret">▸</span>${sceneEsc(title || comp.name)}`;
    html += `<span class="component-state ${comp.enabled && comp.enabledInHierarchy ? 'ok' : 'bad'}">${comp.enabled ? 'enabled' : 'disabled'}</span>`;
    html += `</div>`;
    html += `<div class="inspector-section-body">`;
    html += inspectorRow('Enabled', sceneBool(path, comp.name, 'enabled', comp.enabled));

    for (const key of keys) {
        html += inspectorRow(labelForProp(key), sceneEditor(path, comp.name, key, props[key]));
    }

    if (keys.length === 0) {
        html += `<div class="inspector-empty small">No editable props</div>`;
    }

    html += `</div></div>`;
    return html;
}

function inspectorRow(label, control) {
    return `<div class="inspector-row"><div class="inspector-key">${sceneEsc(label)}</div><div class="inspector-control">${control}</div></div>`;
}

function sceneEditor(path, comp, prop, value) {
    if (typeof value === 'boolean') return sceneBool(path, comp, prop, value);
    if (typeof value === 'number') return sceneNumber(path, comp, prop, value);
    if (typeof value === 'string') return sceneString(path, comp, prop, value);
    if (value && typeof value === 'object') {
        if ('width' in value && 'height' in value) return sceneSize(path, comp, prop, value);
        if ('x' in value && 'y' in value) return sceneVec2or3(path, comp, prop, value);
        if ('r' in value && 'g' in value && 'b' in value) return sceneColor(path, comp, prop, value);
        return `<span class="scene-readonly">${sceneEsc(JSON.stringify(value))}</span>`;
    }
    return `<span class="scene-readonly">${sceneEsc(String(value))}</span>`;
}

function sceneBool(path, comp, prop, value) {
    return `<label class="scene-switch"><input type="checkbox" data-scene-edit="1" data-type="bool" data-path="${sceneEsc(path)}" data-comp="${sceneEsc(comp)}" data-prop="${sceneEsc(prop)}" ${value ? 'checked' : ''}><span></span></label>`;
}

function sceneNumber(path, comp, prop, value, step = 0.1) {
    return `<input class="scene-input number" type="number" step="${step}" value="${value}" data-scene-edit="1" data-type="number" data-path="${sceneEsc(path)}" data-comp="${sceneEsc(comp)}" data-prop="${sceneEsc(prop)}">`;
}

function sceneString(path, comp, prop, value) {
    return `<input class="scene-input text" type="text" value="${sceneEsc(value)}" data-scene-edit="1" data-type="string" data-path="${sceneEsc(path)}" data-comp="${sceneEsc(comp)}" data-prop="${sceneEsc(prop)}">`;
}

function sceneVec2or3(path, comp, prop, value) {
    if ('z' in value) return sceneVec3(path, comp, prop, value);
    return sceneVec2(path, comp, prop, value);
}

function sceneVec2(path, comp, prop, value, step = 0.1) {
    return `<div class="scene-vec">${sceneAxis(path, comp, prop, 'x', value.x, step)}${sceneAxis(path, comp, prop, 'y', value.y, step)}</div>`;
}

function sceneVec3(path, comp, prop, value, step = 0.1) {
    return `<div class="scene-vec">${sceneAxis(path, comp, prop, 'x', value.x, step)}${sceneAxis(path, comp, prop, 'y', value.y, step)}${sceneAxis(path, comp, prop, 'z', value.z, step)}</div>`;
}

function sceneSize(path, comp, prop, value) {
    return `<div class="scene-vec">${sceneAxis(path, comp, prop, 'width', value.width, 1, 'W')}${sceneAxis(path, comp, prop, 'height', value.height, 1, 'H')}</div>`;
}

function sceneAxis(path, comp, prop, axis, value, step, label) {
    return `<label class="scene-axis"><span>${label || axis.toUpperCase()}</span><input type="number" step="${step}" value="${value}" data-scene-edit="1" data-type="axis" data-axis="${axis}" data-path="${sceneEsc(path)}" data-comp="${sceneEsc(comp)}" data-prop="${sceneEsc(prop)}"></label>`;
}

function sceneColor(path, comp, prop, value) {
    const hex = sceneRgbToHex(value.r, value.g, value.b);
    return `<input class="scene-color" type="color" value="${hex}" data-scene-edit="1" data-type="color" data-path="${sceneEsc(path)}" data-comp="${sceneEsc(comp)}" data-prop="${sceneEsc(prop)}"><span class="scene-readonly">rgba(${value.r}, ${value.g}, ${value.b}, ${value.a ?? 255})</span>`;
}

function sceneBindInspectorInputs(root) {
    root.querySelectorAll('[data-scene-edit]').forEach(input => {
        input.addEventListener('change', sceneOnInputChange);
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') sceneOnInputChange(e);
        });
    });
}

function sceneOnInputChange(e) {
    const input = e.target;
    const path = input.dataset.path;
    const compName = input.dataset.comp;
    const propName = input.dataset.prop;
    const type = input.dataset.type;
    let value;

    if (type === 'bool') value = input.checked;
    else if (type === 'number') value = Number(input.value);
    else if (type === 'string') value = input.value;
    else if (type === 'axis') value = sceneCollectAxis(path, compName, propName);
    else if (type === 'color') value = sceneHexToRgb(input.value);
    else value = input.value;

    sceneSend({ type: 'scene_set_property', path, compName, propName, value });
}

function sceneCollectAxis(path, compName, propName) {
    const q = `[data-scene-edit][data-type="axis"][data-path="${cssEscape(path)}"][data-comp="${cssEscape(compName)}"][data-prop="${cssEscape(propName)}"]`;
    const obj = {};
    document.querySelectorAll(q).forEach(input => {
        obj[input.dataset.axis] = Number(input.value);
    });
    return obj;
}

function labelForProp(prop) {
    const map = {
        contentSize: 'Content Size',
        anchorPoint: 'Anchor Point',
        priority: 'Priority',
        isAlignTop: 'Align Top',
        isAlignBottom: 'Align Bottom',
        isAlignLeft: 'Align Left',
        isAlignRight: 'Align Right',
        isAlignHorizontalCenter: 'H Center',
        isAlignVerticalCenter: 'V Center',
        spacingX: 'Spacing X',
        spacingY: 'Spacing Y',
        paddingLeft: 'Padding Left',
        paddingRight: 'Padding Right',
        paddingTop: 'Padding Top',
        paddingBottom: 'Padding Bottom',
        resizeMode: 'Resize Mode',
    };
    return map[prop] || prop;
}

function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/"/g, '\\"');
}

function sceneEsc(value) {
    const d = document.createElement('div');
    d.textContent = String(value);
    return d.innerHTML;
}

function sceneRgbToHex(r, g, b) {
    return '#' + [r, g, b].map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
}

function sceneHexToRgb(hex) {
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return m ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16), a: 255 } : { r: 255, g: 255, b: 255, a: 255 };
}

// ---- 多客户端：切换时重置 ----

function resetScenePanel() {
    sceneTreeData = null;
    sceneSelectedPath = null;
    sceneSelectedInfo = null;
    sceneExpanded.clear();
    const tree = document.getElementById('scene-tree');
    if (tree) tree.innerHTML = '<div class="scene-empty">切换客户端后点刷新加载场景树</div>';
    const detail = document.getElementById('scene-detail');
    if (detail) detail.innerHTML = '<div class="scene-empty">点击节点查看详情</div>';
    const fps = document.getElementById('scene-fps');
    const dc = document.getElementById('scene-dc');
    if (fps) fps.textContent = '-';
    if (dc) dc.textContent = '-';
    const st = document.getElementById('scene-status');
    if (st) st.textContent = '';
}

window.handleSceneTree = handleSceneTree;
window.handleSceneNodeInfo = handleSceneNodeInfo;
window.sceneRefreshTree = sceneRefreshTree;
window.sceneSelectNode = sceneSelectNode;
window.resetScenePanel = resetScenePanel;
