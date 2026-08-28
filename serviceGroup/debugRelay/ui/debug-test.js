/**
 * Test 面板逻辑 — creator xzmp 测试接口统一入口（单列 + 展开参数表单 + Toast）
 *
 * - GET  /api/debug-index  拉取当前客户端已注入的调试接口目录
 * - POST /api/test-call    调用 window.<name>(...args) 模拟测试行为
 *
 * 界面逻辑：
 * - 单列展示，点击接口展开参数引导区
 * - 分类过滤：Agent（agent.*）与用户测试接口（game.test/hall.test/common.test/action_*）分开
 * - 执行结果以 Toast 提示
 */

// 常见 agent.* 接口的参数含义/可选范围（未收录的接口回退到函数签名参数名 + “未标注”）
const TEST_PARAM_HINTS = {
    'agent.meta.list': [{ name: 'env', desc: '过滤环境', range: 'hall / game / both，空=全部' }],
    'agent.meta.registry': [{ name: 'env', desc: '过滤环境', range: 'hall / game / both，空=全部' }],
    'agent.hall.areas': [],
    'agent.hall.openArea': [{ name: 'areaId', desc: '大区 ID', range: '数字，来自 areas()' }],
    'agent.hall.rooms': [{ name: 'areaId', desc: '大区 ID（可选）', range: '数字，空=全部房间' }],
    'agent.hall.findRoom': [{ name: 'filters', desc: '筛选条件', range: '{areaId?, roomId?, name?, baseScore?, minDeposit?, maxDeposit?, userCount?}' }],
    'agent.hall.getRoomInfo': [{ name: 'roomId', desc: '房间 ID', range: '数字' }],
    'agent.hall.currentArea': [],
    'agent.hall.selectTab': [{ name: 'index', desc: 'Tab 索引', range: '数字，从 0 开始' }],
    'agent.hall.enterRoom': [{ name: 'roomId', desc: '房间 ID', range: '数字，来自 findRoom()' }],
    'agent.hall.quickStart': [],
    'agent.hall.enterRoomByIndex': [{ name: 'areaId', desc: '大区 ID（可选）', range: '数字，空=当前大区' }, { name: 'index', desc: '房间列表索引', range: '数字，默认 0' }],
    'agent.hall.viewState': [],
    'agent.hall.closeAllViews': [],
    'agent.hall.openView': [{ name: 'view', desc: '视图名', range: '字符串' }, { name: 'args', desc: '打开参数', range: '对象，可空' }],
    'agent.game.state': [],
    'agent.game.actions': [],
    'agent.game.doAction': [{ name: 'action', desc: '真实协议动作', range: 'hu / peng / gang / chi / guo / throw / dingque' }, { name: 'opts', desc: '动作参数', range: 'throw 传 {card}；gang/throw 可传 {cardIdx}' }],
    'agent.game.hand': [],
    'agent.game.cpg': [],
    'agent.game.discard': [],
    'agent.game.setHands': [{ name: 'seatsCards', desc: '四家手牌', range: '{1:[...],2:[...],3:[...],4:[...]}' }],
    'agent.game.info': [],
    'agent.game.find': [{ name: 'path', desc: '节点路径/关键字', range: '字符串' }],
    'agent.device.resolution': [],
    'agent.device.sim': [{ name: 'cfg', desc: '模拟配置', range: '{w,h,inset,top,notch}，notch=none|notch|waterdrop|hole' }],
    'agent.device.capture': [],
    'agent.device.diag': [{ name: 'deep', desc: '是否深度诊断', range: 'true / false' }],
    'agent.device.setDesignWidth': [{ name: 'width', desc: '设计宽度', range: '数字' }],
    'agent.device.bizDesignWidth': [],
    'agent.plugins.huInfoTouch': [{ name: 'chair', desc: '座位', range: '数字' }, { name: 'show', desc: '显示/隐藏', range: 'true / false' }],
    'agent.plugins.dingQueFly': [],
    'common.test.ct.startGame': [{ name: 'roomId', desc: '房间 ID', range: '数字' }],
    'game.test.handCards': [{ name: 'cards', desc: '手牌配置', range: '数组，如 [1,2,3] 或 4 家对象' }],
    'game.test.changePlayerHead': [{ name: 'prop', desc: '头像装扮 propid', range: '1..9，空=循环切换' }, { name: 'drawIndex', desc: '座位 drawIndex', range: '默认自己=1' }],
    'game.test.changeCardBack': [{ name: 'skinIndex', desc: '牌背皮肤索引', range: '0..5，空=循环切换' }],
    'game.test.changeTable': [{ name: 'uuid', desc: '桌布 UUID', range: '字符串' }],
    'game.test.doAction': [{ name: 'action', desc: '动作', range: 'hu / peng / gang / chi / guo / throw / dingque' }, { name: 'opts', desc: '参数', range: '{card? / cardIdx?}' }],
    'game.test.setHands': [{ name: 'seatsCards', desc: '四家手牌', range: '{1:[...],2:[...],3:[...],4:[...]}' }],
};

let testCatalog = null;
let testExpanded = {};  // name -> true/false

function testSetStatus(text, isError) {
    const el = document.getElementById('test-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--dim)';
}

function testOnTabShow() {
    testRefresh();
}

function testResetPanel() {
    testCatalog = null;
    testExpanded = {};
    const list = document.getElementById('test-list');
    if (list) list.innerHTML = '<div class="events-empty">选择客户端后点击刷新查看测试接口</div>';
}

async function testRefresh() {
    if (!selectedClient) {
        testSetStatus('请先选择客户端', true);
        return;
    }
    testSetStatus('拉取测试接口目录...');
    const env = document.getElementById('test-env').value || '';
    const params = new URLSearchParams();
    if (selectedClient) params.set('client', selectedClient);
    if (env) params.set('env', env);
    try {
        const resp = await fetch('/api/debug-index?' + params.toString());
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        testCatalog = data;
        testRender();
        testSetStatus(`已加载 ${data.count || 0} 个测试接口`);
    } catch (e) {
        testCatalog = null;
        const list = document.getElementById('test-list');
        if (list) list.innerHTML = `<div class="events-empty">加载失败: ${escapeHtml(e.message)}</div>`;
        testSetStatus('加载失败', true);
    }
}

function testCategoryOf(ns) {
    return ns === 'agent' || ns.startsWith('agent.') ? 'agent' : 'user';
}

function testFlattenCatalog(catalog) {
    const fns = (catalog && catalog.namespaces) || {};
    const out = [];
    for (const ns of Object.keys(fns)) {
        const members = fns[ns] || {};
        for (const fn of Object.keys(members)) {
            const meta = members[fn] || {};
            const name = `${ns}.${fn}`;
            out.push({
                name,
                ns,
                fn,
                arity: meta.arity != null ? meta.arity : 0,
                desc: meta.desc || '',
                env: meta.env || '',
                category: testCategoryOf(ns),
                params: Array.isArray(meta.params) ? meta.params : [],
                origName: meta.origName || '',
            });
        }
    }
    out.sort((a, b) => a.name.localeCompare(b.name));
    return out;
}

function testParamHints(name, fallbackParams, arity) {
    const hints = TEST_PARAM_HINTS[name] || [];
    const names = fallbackParams.length ? fallbackParams : Array.from({ length: hints.length || 0 }, (_, i) => `arg${i + 1}`);
    const count = Math.max(names.length, hints.length, arity || 0);
    return Array.from({ length: count }, (_, i) => {
        const h = hints[i] || {};
        return {
            name: h.name || names[i] || `arg${i + 1}`,
            desc: h.desc || '未标注',
            range: h.range || '未标注',
        };
    });
}

function testRender() {
    const list = document.getElementById('test-list');
    if (!list) return;
    if (!testCatalog) return;
    const all = testFlattenCatalog(testCatalog);
    const q = (document.getElementById('test-search').value || '').trim().toLowerCase();
    const category = document.getElementById('test-category').value || 'all';
    let filtered = all;
    if (category !== 'all') filtered = filtered.filter(x => x.category === category);
    if (q) filtered = filtered.filter(x =>
        x.name.toLowerCase().includes(q) ||
        (x.desc || '').toLowerCase().includes(q) ||
        (x.origName || '').toLowerCase().includes(q)
    );
    if (filtered.length === 0) {
        list.innerHTML = '<div class="events-empty">没有匹配的测试接口</div>';
        return;
    }
    const sections = [];
    if (category === 'all' || category === 'agent') {
        const agentItems = filtered.filter(x => x.category === 'agent');
        if (agentItems.length) sections.push({ title: 'Agent 接口', items: agentItems });
    }
    if (category === 'all' || category === 'user') {
        const userItems = filtered.filter(x => x.category === 'user');
        if (userItems.length) sections.push({ title: '用户测试接口', items: userItems });
    }
    list.innerHTML = sections.map(sec => `
        <div class="test-group">
            <div class="test-group-title">${escapeHtml(sec.title)} (${sec.items.length})</div>
            ${sec.items.map(testRenderItem).join('')}
        </div>
    `).join('');
}

function testRenderItem(item) {
    const expanded = !!testExpanded[item.name];
    const hints = testParamHints(item.name, item.params, item.arity);
    const paramsHtml = item.arity > 0 ? hints.map((p, i) => `
        <div class="test-param">
            <div class="test-param-label">参数 ${i + 1} · <b>${escapeHtml(p.name)}</b></div>
            <div class="test-param-meta">含义：${escapeHtml(p.desc)} · 范围：${escapeHtml(p.range)}</div>
            <input class="test-param-input" data-param-index="${i}" placeholder="输入值（JSON / 数字 / 字符串）" />
        </div>
    `).join('') : '<div class="test-param-empty">无需参数，直接运行</div>';
    const aliasHtml = item.origName && item.origName !== item.fn
        ? `<span class="test-item-alias" title="原函数名">${escapeHtml(item.origName)}</span>`
        : '';
    const paramBadge = item.arity > 0
        ? `<span class="test-item-params-badge">⚙ 有参数 ${item.arity}</span>`
        : '<span class="test-item-params-badge no-params">无参数</span>';
    return `
        <div class="test-item ${expanded ? 'test-item-open' : ''}" data-name="${escapeHtml(item.name)}">
            <div class="test-item-head" onclick="testToggleItem('${escapeHtml(item.name).replace(/'/g, "\\'")}')">
                <span class="test-item-arrow">${expanded ? '▼' : '▶'}</span>
                <span class="test-item-name">${escapeHtml(item.name)}</span>
                ${aliasHtml}
                <span class="test-item-cat ${item.category === 'agent' ? 'cat-agent' : 'cat-user'}">${item.category === 'agent' ? 'Agent' : '用户'}</span>
                <span class="test-item-env">${escapeHtml(item.env)}</span>
                ${paramBadge}
                <button class="test-item-run" onclick="event.stopPropagation();testRunItem('${escapeHtml(item.name).replace(/'/g, "\\'")}', ${item.arity})">🚀 运行</button>
            </div>
            <div class="test-item-detail ${expanded ? '' : 'hidden'}">
                <div class="test-item-desc">${escapeHtml(item.desc || '暂无描述')}</div>
                ${paramsHtml}
            </div>
        </div>
    `;
}

function testToggleItem(name) {
    testExpanded[name] = !testExpanded[name];
    const items = document.querySelectorAll('.test-item');
    const item = Array.from(items).find(x => x.dataset.name === name);
    if (!item) return;
    item.classList.toggle('test-item-open', testExpanded[name]);
    const detail = item.querySelector('.test-item-detail');
    const arrow = item.querySelector('.test-item-arrow');
    if (detail) detail.classList.toggle('hidden', !testExpanded[name]);
    if (arrow) arrow.textContent = testExpanded[name] ? '▼' : '▶';
}

function testCollectArgs(name, arity) {
    const items = document.querySelectorAll('.test-item');
    const container = Array.from(items).find(x => x.dataset.name === name) || document;
    const inputs = container.querySelectorAll('.test-param-input');
    const args = [];
    for (const input of inputs) {
        const raw = input.value.trim();
        if (raw === '') {
            args.push(undefined);
            continue;
        }
        try {
            args.push(JSON.parse(raw));
        } catch (_) {
            args.push(raw);
        }
    }
    // arity 之外多余参数裁剪；undefined 补足到 arity（保持位置语义）
    while (args.length < arity) args.push(undefined);
    return args.slice(0, arity);
}

async function testRunItem(name, arity) {
    if (arity > 0) {
        const items = document.querySelectorAll('.test-item');
        const item = Array.from(items).find(x => x.dataset.name === name);
        const detail = item && item.querySelector('.test-item-detail');
        if (!detail || detail.classList.contains('hidden')) {
            if (!testExpanded[name]) testToggleItem(name);
            testToast(`${name} 有 ${arity} 个参数，请展开填写后再次运行`, true);
            return;
        }
    }
    const args = testCollectArgs(name, arity);
    testToast(`正在调用 ${name} ...`, false, true);
    try {
        const resp = await fetch('/api/test-call', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, args, client: selectedClient }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        if (data.eval_error) throw new Error(data.eval_result || 'eval error');
        let text = String(data.eval_result ?? 'undefined');
        try {
            const parsed = JSON.parse(text);
            text = JSON.stringify(parsed, null, 2);
        } catch (_) { /* 原样展示 */ }
        testToast(`✓ ${name} 执行成功\n${text.length > 400 ? text.slice(0, 400) + ' …' : text}`);
    } catch (e) {
        testToast(`✗ ${name} 调用失败：${e.message}`, true);
    }
}

// ---- Toast ----

let testToastTimer = null;

function testToast(message, isError, keep) {
    let el = document.getElementById('test-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'test-toast';
        document.body.appendChild(el);
    }
    el.textContent = message;
    el.className = 'test-toast ' + (isError ? 'test-toast-error' : 'test-toast-ok');
    el.style.display = 'block';
    if (testToastTimer) clearTimeout(testToastTimer);
    if (!keep) {
        testToastTimer = setTimeout(() => {
            el.style.display = 'none';
        }, 3500);
    }
}

// 注入极简样式（避免改 debug-ui.css, 同 device/autotest 模式）
(function injectTestStyle() {
    if (document.getElementById('test-style')) return;
    const style = document.createElement('style');
    style.id = 'test-style';
    style.textContent = `
        #panel-test { flex-direction: column; }
        #test-toolbar { display:flex; gap:8px; align-items:center; padding:6px 8px; border-bottom:1px solid var(--border); flex-wrap:wrap; }
        #test-body { padding:8px; overflow:auto; }
        #test-list { width:100%; }
        .test-group { margin-bottom:14px; }
        .test-group-title { font-weight:bold; color:var(--dim); font-size:12px; text-transform:uppercase; margin:8px 0 6px; }
        .test-item { border:1px solid var(--border); border-radius:6px; margin-bottom:6px; overflow:hidden; }
        .test-item-open { border-color:var(--accent, #4a9eff); }
        .test-item-head { display:flex; align-items:center; gap:8px; padding:6px 10px; cursor:pointer; user-select:none; justify-content:flex-start; text-align:left; }
        .test-item-head:hover { background:var(--bg-alt, rgba(255,255,255,0.04)); }
        .test-item-arrow { width:16px; text-align:center; color:var(--dim); }
        .test-item-name { font-family:monospace; font-size:12px; flex:1; min-width:0; word-break:break-all; text-align:left; }
        .test-item-cat { border-radius:3px; padding:0 5px; font-size:10px; }
        .cat-agent { background:rgba(46,213,115,.15); color:#2ed573; }
        .cat-user { background:rgba(74,158,255,.15); color:var(--accent, #4a9eff); }
        .test-item-env { background:rgba(255,255,255,.08); color:var(--dim); border-radius:3px; padding:0 4px; font-size:10px; }
        .test-item-arity { color:var(--dim); font-size:10px; }
        .test-item-alias { background:rgba(255,193,7,.12); color:#ffc107; border-radius:3px; padding:0 4px; font-size:10px; }
        .test-item-params-badge { border-radius:3px; padding:0 5px; font-size:10px; background:rgba(255,165,0,.12); color:#ffa502; white-space:nowrap; }
        .test-item-params-badge.no-params { background:rgba(255,255,255,.06); color:var(--dim); }
        .test-item-detail { padding:8px 12px 10px; border-top:1px solid var(--border); text-align:left; }
        .test-item-detail.hidden { display:none; }
        .test-item-desc { color:var(--dim); font-size:12px; margin-bottom:8px; }
        .test-param { margin-bottom:8px; }
        .test-param-label { font-size:12px; margin-bottom:2px; }
        .test-param-label b { font-family:monospace; }
        .test-param-meta { color:var(--dim); font-size:11px; margin-bottom:2px; }
        .test-param-input { width:100%; box-sizing:border-box; padding:4px 8px; background:var(--bg, #1e1e1e); color:var(--fg); border:1px solid var(--border); border-radius:4px; }
        .test-param-empty { color:var(--dim); font-size:12px; margin-bottom:8px; }
        .test-item-run { margin-left:auto; background:var(--bg-alt, rgba(255,255,255,0.06)); border:1px solid var(--border); color:var(--fg); border-radius:4px; padding:3px 12px; cursor:pointer; }
        .test-item-run:hover { border-color:#2ed573; color:#2ed573; }
        .test-legend { color:var(--dim); font-size:11px; padding:6px 0; border-top:1px solid var(--border); margin-top:8px; }
        .test-legend code { background:var(--bg-alt, rgba(255,255,255,0.04)); padding:0 3px; border-radius:3px; }
        .test-toast { position:fixed; left:50%; bottom:36px; transform:translateX(-50%); max-width:70vw; max-height:50vh; overflow:auto; white-space:pre-wrap; word-break:break-all; background:#1e1e1e; color:#fff; border:1px solid var(--border, #444); border-left:4px solid #2ed573; border-radius:6px; padding:10px 16px; font-size:12px; z-index:99999; box-shadow:0 4px 20px rgba(0,0,0,.4); display:none; }
        .test-toast-error { border-left-color:#ff4757; }
    `;
    document.head.appendChild(style);
})();
