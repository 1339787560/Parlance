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

const TEST_CATEGORY_LABELS = {
    'hall.room': '大厅 · 房间/大区', 'hall.enter': '大厅 · 进房/快捷',
    'hall.view': '大厅 · 视图/Tab', 'hall.route': '大厅 · 路由/配置',
    'hall.tutorial': '大厅 · 新手引导',
    'game.settle': '对局 · 终局/结算', 'game.system': '对局 · 重连/系统',
    'game.hand': '对局 · 手牌/出牌', 'game.cpg': '对局 · 吃碰杠',
    'game.hu': '对局 · 听牌/胡牌', 'game.swap': '对局 · 换三张/定缺/理牌',
    'game.3d': '对局 · 3D 表现', 'game.dress': '对局 · 装扮',
    'game.ui': '对局 · UI 状态', 'game.action': '对局 · Agent 原子操作',
    'plugin.resurrect': '插件 · 复活', 'plugin.goldbank': '插件 · 金库',
    'plugin.replay': '插件 · 回放', 'plugin.loadTablePreview': '插件 · 桌布预览',
    'plugin.cardBack': '插件 · 牌背', 'plugin.promptHu': '插件 · 听牌提示',
    'plugin.exchange3': '插件 · 换三张', 'plugin.huInfoTouch': '插件 · 胡牌触摸',
    'plugin.dingQueFly': '插件 · 定缺飞', 'plugin.autotest': '插件 · 自动测试',
    'plugin.other': '插件 · 其他',
    'device': '设备模拟', 'meta': '自省/元信息', 'other': '其他',
};

const TEST_CATEGORY_ORDER = [
    'hall.room', 'hall.enter', 'hall.view', 'hall.route', 'hall.tutorial',
    'game.settle', 'game.system', 'game.hand', 'game.cpg', 'game.hu',
    'game.swap', 'game.3d', 'game.dress', 'game.ui', 'game.action',
    'plugin.resurrect', 'plugin.goldbank', 'plugin.replay', 'plugin.loadTablePreview',
    'plugin.cardBack', 'plugin.promptHu', 'plugin.exchange3', 'plugin.huInfoTouch',
    'plugin.dingQueFly', 'plugin.autotest', 'plugin.other', 'device', 'meta', 'other',
];

let testCatalog = null;     // 客户端注入的测试接口目录（/api/debug-index）
let testCatalogCp = null;   // 全局 CP schema（/api/cp/modules, relay 本地, 不依赖客户端）
let testExpanded = {};      // name -> true/false

function testSetStatus(text, isError) {
    const el = document.getElementById('test-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--dim)';
}

function testOnTabShow() {
    testInitSplitter();
    testRefresh();
}

function testResetPanel() {
    testCatalog = null;
    testCatalogCp = null;
    testExpanded = {};
    const list = document.getElementById('test-list');
    if (list) list.innerHTML = '<div class="events-empty">选择客户端后点击刷新查看测试接口</div>';
}

async function testRefresh() {
    const env = document.getElementById('test-env').value || '';
    const notes = [];

    // 1) 全局 CP schema（relay 本地, 不依赖客户端 → 没选客户端也能列目录）
    testSetStatus('拉取目录...');
    try {
        const resp = await fetch('/api/cp/modules');
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        testCatalogCp = data;
        notes.push(`CP ${data.count || 0} req`);
    } catch (e) {
        testCatalogCp = null;
        notes.push('CP 加载失败: ' + e.message);
    }

    // 2) 客户端注入的测试接口目录（需已选客户端）
    if (selectedClient) {
        const params = new URLSearchParams();
        params.set('client', selectedClient);
        if (env) params.set('env', env);
        try {
            const resp = await fetch('/api/debug-index?' + params.toString());
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
            testCatalog = data;
            notes.push(`${data.count || 0} 个测试接口`);
        } catch (e) {
            testCatalog = null;
            notes.push('接口目录: ' + e.message);
        }
    } else {
        testCatalog = null;
        notes.push('未选客户端');
    }

    testPopulateSubcategories();
    testRender();
    if (!testCatalog && !testCatalogCp) {
        const list = document.getElementById('test-list');
        if (list) list.innerHTML = '<div class="events-empty">无可用目录（CP 加载失败且未选客户端）</div>';
    }
    testSetStatus(notes.join(' · '), !testCatalog && !testCatalogCp);
}

function testCategoryOf(ns) {
    if (ns === 'cp' || ns.startsWith('cp.')) return 'cp';
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
                scope: testCategoryOf(ns),
                category: meta.category || 'other',
                params: Array.isArray(meta.params) ? meta.params : [],
                // CP: params 是 dict(命名参数 -> 样例值) → 命名表单; 客户端接口是数组 → 位置表单
                paramsObj: (meta.params && typeof meta.params === 'object' && !Array.isArray(meta.params)) ? meta.params : null,
                ro: meta.ro === false ? false : true,
                origName: meta.origName || '',
                aliases: Array.isArray(meta.aliases) ? meta.aliases : [],
            });
        }
    }
    out.sort((a, b) => a.name.localeCompare(b.name));
    return out;
}

/** 合并两个来源（客户端注入的测试接口 + 全局 CP），供渲染与子分类共用。 */
function testAllItems() {
    return [...testFlattenCatalog(testCatalog), ...testFlattenCatalog(testCatalogCp)];
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

function testCategoryLabel(cat) {
    return TEST_CATEGORY_LABELS[cat] || cat;
}

function testOnCategoryChange() {
    const sub = document.getElementById('test-subcategory');
    if (sub) sub.value = '';
    testPopulateSubcategories();
    testRender();
}

function testPopulateSubcategories() {
    const sel = document.getElementById('test-subcategory');
    if (!sel || (!testCatalog && !testCatalogCp)) return;
    const all = testAllItems();
    const scope = document.getElementById('test-category').value || 'all';
    const env = document.getElementById('test-env').value || '';
    let items = env ? all.filter(x => x.env === env || x.env === 'both') : all;
    if (scope !== 'all') items = items.filter(x => x.scope === scope);
    const cats = Array.from(new Set(items.map(x => x.category))).filter(Boolean);
    cats.sort((a, b) => {
        const ia = TEST_CATEGORY_ORDER.indexOf(a);
        const ib = TEST_CATEGORY_ORDER.indexOf(b);
        return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    });
    const current = sel.value;
    sel.innerHTML = '<option value="">全部分属</option>' + cats.map(c =>
        `<option value="${c}">${testCategoryLabel(c)}</option>`
    ).join('');
    if (current && cats.includes(current)) sel.value = current;
}

function testRender() {
    const list = document.getElementById('test-list');
    if (!list) return;
    if (!testCatalog && !testCatalogCp) return;
    const all = testAllItems();
    const q = (document.getElementById('test-search').value || '').trim().toLowerCase();
    const scope = document.getElementById('test-category').value || 'all';
    const subcategory = document.getElementById('test-subcategory').value || '';
    let filtered = all;
    if (scope !== 'all') filtered = filtered.filter(x => x.scope === scope);
    if (subcategory) filtered = filtered.filter(x => x.category === subcategory);
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
    if (scope === 'all' || scope === 'cp') {
        const cpItems = filtered.filter(x => x.scope === 'cp');
        if (cpItems.length) sections.push({ title: '全局 CP（client_request · 打到所选客户端）', items: cpItems });
    }
    if (scope === 'all' || scope === 'agent') {
        const agentItems = filtered.filter(x => x.scope === 'agent');
        if (agentItems.length) sections.push({ title: 'Agent 接口', items: agentItems });
    }
    if (scope === 'all' || scope === 'user') {
        const userItems = filtered.filter(x => x.scope === 'user');
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
    const isCp = item.scope === 'cp';
    let paramsHtml;
    if (isCp) {
        // CP: 命名参数（键 -> 样例值）, 留空 = 不传该参数
        const keys = Object.keys(item.paramsObj || {});
        paramsHtml = keys.length ? keys.map(k => {
            const sample = JSON.stringify(item.paramsObj[k]);
            return `
        <div class="test-param">
            <div class="test-param-label">参数 · <b>${escapeHtml(k)}</b></div>
            <div class="test-param-meta">样例默认值：${escapeHtml(sample)}（留空 = 不传该参数）</div>
            <input class="test-param-input" data-param-key="${escapeHtml(k)}" placeholder="${escapeHtml(sample)}" />
        </div>`;
        }).join('') : '<div class="test-param-empty">无需参数，直接运行</div>';
    } else {
        const hints = testParamHints(item.name, item.params, item.arity);
        paramsHtml = item.arity > 0 ? hints.map((p, i) => `
        <div class="test-param">
            <div class="test-param-label">参数 ${i + 1} · <b>${escapeHtml(p.name)}</b></div>
            <div class="test-param-meta">含义：${escapeHtml(p.desc)} · 范围：${escapeHtml(p.range)}</div>
            <input class="test-param-input" data-param-index="${i}" placeholder="输入值（JSON / 数字 / 字符串）" />
        </div>
    `).join('') : '<div class="test-param-empty">无需参数，直接运行</div>';
    }
    const aliasNames = [item.origName, ...(item.aliases || [])].filter(Boolean).filter(x => x !== item.fn);
    const aliasHtml = aliasNames.length
        ? aliasNames.map(a => `<span class="test-item-alias" title="原函数名/别名">${escapeHtml(a)}</span>`).join('')
        : '';
    const paramBadge = item.arity > 0
        ? `<span class="test-item-params-badge">⚙ 有参数 ${item.arity}</span>`
        : '<span class="test-item-params-badge no-params">无参数</span>';
    // CP 写操作警示（发奖/扣次数/购买 → 会真改玩家数据）
    const roBadge = (isCp && item.ro === false)
        ? '<span class="test-item-params-badge cat-cp-write" title="写操作：会真改玩家数据，只用测试账号">写</span>'
        : '';
    const scopeLabel = isCp ? 'CP' : (item.scope === 'agent' ? 'Agent' : '用户');
    const scopeCls = isCp ? 'cat-cp' : (item.scope === 'agent' ? 'cat-agent' : 'cat-user');
    return `
        <div class="test-item ${expanded ? 'test-item-open' : ''}" data-name="${escapeHtml(item.name)}">
            <div class="test-item-head" onclick="testToggleItem('${escapeHtml(item.name).replace(/'/g, "\\'")}')">
                <span class="test-item-arrow">${expanded ? '▼' : '▶'}</span>
                <span class="test-item-name">${escapeHtml(item.name)}</span>
                ${aliasHtml}
                <span class="test-item-cat ${scopeCls}">${scopeLabel}</span>
                <span class="test-item-env">${escapeHtml(item.env)}</span>
                ${roBadge}
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

/** 收集 CP 命名参数（data-param-key）; 留空 = 不传该参数（用 CP 侧默认）。 */
function testCollectParams(item) {
    const params = {};
    const inputs = item ? item.querySelectorAll('.test-param-input') : [];
    for (const input of inputs) {
        const key = input.dataset.paramKey;
        if (!key) continue;
        const raw = input.value.trim();
        if (raw === '') continue;
        try {
            params[key] = JSON.parse(raw);
        } catch (_) {
            params[key] = raw;
        }
    }
    return params;
}

/** 结果格式化: JSON 美化 + 截断（对象 / JSON 字符串都吃）。maxLen=0 → 不截断（右侧结果栏用）。 */
function testFmtJson(obj, maxLen) {
    let text;
    try {
        const parsed = typeof obj === 'string' ? JSON.parse(obj) : obj;
        text = JSON.stringify(parsed, null, 2);
    } catch (_) {
        text = String(obj);
    }
    if (text === undefined) text = String(obj);
    const cap = maxLen === 0 ? Infinity : (maxLen || 400);
    return text.length > cap ? text.slice(0, cap) + ' …' : text;
}

async function testRunItem(name, arity) {
    const item = Array.from(document.querySelectorAll('.test-item')).find(x => x.dataset.name === name);
    if (arity > 0) {
        const detail = item && item.querySelector('.test-item-detail');
        if (!detail || detail.classList.contains('hidden')) {
            if (!testExpanded[name]) testToggleItem(name);
            testToast(`${name} 有 ${arity} 个参数，请展开填写后再次运行`, true);
            return;
        }
    }

    // 全局 CP: 走代码通道（/api/cp/call → 客户端 ct.CommonCPInterFace.client_request）
    if (name.startsWith('cp.')) {
        const parts = name.split('.');
        const module = parts[1];
        const req = parts[2];
        const params = testCollectParams(item);
        const t0 = Date.now();
        testToast(`正在模拟 ${module} / ${req} ...`, false, true);
        try {
            const resp = await fetch('/api/cp/call', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ module, req, params, client: selectedClient }),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
            if (data.ok === false) throw new Error(data.error || 'CP 返回空响应');
            const meta = `请求: ${JSON.stringify(params)}`
                + `\n命中: userid=${data.userid ?? '?'} · appcode=${data.appcode ?? '?'} · client=${data.client_id ?? '?'}`
                + `\n耗时: ${Date.now() - t0}ms`;
            testToast(`✓ ${module} / ${req}`);
            testShowResult({ ok: true, title: `${module} / ${req}`, meta, body: testFmtJson(data.data, 200000) });
        } catch (e) {
            testToast(`✗ ${module} / ${req} 失败：${e.message}`, true);
            testShowResult({
                ok: false, title: `${module} / ${req}`,
                meta: `请求: ${JSON.stringify(params)}`, body: e.message,
            });
        }
        return;
    }

    const args = testCollectArgs(name, arity);
    const t0 = Date.now();
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
        const meta = `调用: window.${name}(${args.map(a => JSON.stringify(a === undefined ? null : a)).join(', ')})`
            + `\n类型: ${data.eval_type ?? '?'} · client=${data.client_id ?? '?'} · 耗时: ${Date.now() - t0}ms`;
        testToast(`✓ ${name} 执行成功`);
        testShowResult({ ok: true, title: name, meta, body: testFmtJson(data.eval_result, 200000) });
    } catch (e) {
        testToast(`✗ ${name} 调用失败：${e.message}`, true);
        testShowResult({ ok: false, title: name, meta: `调用: window.${name}`, body: e.message });
    }
}

// ---- 右侧结果栏 + 左右分割 ----

/** 渲染一次执行的返回值到右侧结果栏（无返回值也显示状态）。 */
function testShowResult(opts) {
    const title = document.getElementById('test-result-title');
    const bodyEl = document.getElementById('test-result-body');
    if (!title || !bodyEl) return;
    const ok = opts.ok !== false;
    title.textContent = (ok ? '✓ ' : '✗ ') + (opts.title || '返回结果');
    title.style.color = ok ? '#2ed573' : '#ff4757';
    const meta = opts.meta ? `<div class="test-result-meta">${escapeHtml(opts.meta)}</div>` : '';
    const text = (opts.body === undefined || opts.body === null || opts.body === '')
        ? '(无返回值)' : String(opts.body);
    bodyEl.className = 'test-result-body ' + (ok ? 'test-result-ok' : 'test-result-err');
    bodyEl.innerHTML = meta + `<div>${escapeHtml(text)}</div>`;
}

function testClearResult() {
    const title = document.getElementById('test-result-title');
    const bodyEl = document.getElementById('test-result-body');
    if (title) { title.textContent = '返回结果'; title.style.color = 'var(--dim)'; }
    if (bodyEl) {
        bodyEl.className = 'test-result-body test-result-empty';
        bodyEl.textContent = '运行测试条目后，返回值显示在这里';
    }
}

// ---- 分割占比持久化（localStorage：刷新 / 重新进入后保持） ----

const TEST_SPLIT_KEY = 'debugrelay.test.splitPct';
const TEST_SPLIT_DEFAULT = 70;   // 默认 7:3
const TEST_SPLIT_MIN = 15;
const TEST_SPLIT_MAX = 85;

function testClampSplitPct(v) {
    const n = Number(v);
    if (!isFinite(n) || n <= 0) return null;
    return Math.max(TEST_SPLIT_MIN, Math.min(TEST_SPLIT_MAX, n));
}

function testApplySplitPct(pct) {
    const left = document.getElementById('test-list-wrap');
    if (!left) return false;
    const v = testClampSplitPct(pct);
    if (v == null) return false;
    left.style.flexBasis = v.toFixed(2) + '%';
    return true;
}

function testSaveSplitPct(pct) {
    const v = testClampSplitPct(pct);
    if (v == null) return;
    try { localStorage.setItem(TEST_SPLIT_KEY, String(v)); } catch (_) { /* 隐私模式/禁用存储：忽略 */ }
}

/** 恢复上次占比；返回生效值，无存值或不可用 → null（保持 CSS 默认 70%）。 */
function testRestoreSplitPct() {
    let raw = null;
    try { raw = localStorage.getItem(TEST_SPLIT_KEY); } catch (_) { /* 忽略 */ }
    const v = testClampSplitPct(raw);
    if (v == null) return null;
    return testApplySplitPct(v) ? v : null;
}

/**
 * 左右分割条：拖拽改 #test-list-wrap 的 flex-basis（限 15%~85%），双击复位 7:3。
 * 占比写入 localStorage，刷新与重新进入后保持。
 */
function testInitSplitter() {
    const body = document.getElementById('test-body');
    const split = document.getElementById('test-splitter');
    const left = document.getElementById('test-list-wrap');
    if (!body || !split || !left || split.dataset.bound) return;
    split.dataset.bound = '1';
    testRestoreSplitPct();   // 兜底：脚本加载早于 DOM 就位时，切 tab 时再恢复一次
    let dragging = false;
    const apply = (clientX) => {
        const r = body.getBoundingClientRect();
        if (!r.width) return;
        const pct = Math.max(TEST_SPLIT_MIN, Math.min(TEST_SPLIT_MAX, ((clientX - r.left) / r.width) * 100));
        left.style.flexBasis = pct.toFixed(2) + '%';
    };
    split.addEventListener('pointerdown', (e) => {
        dragging = true;
        split.classList.add('dragging');
        try { split.setPointerCapture(e.pointerId); } catch (_) { /* 忽略 */ }
        e.preventDefault();
    });
    split.addEventListener('pointermove', (e) => { if (dragging) apply(e.clientX); });
    const stop = (e) => {
        if (!dragging) return;
        dragging = false;
        split.classList.remove('dragging');
        try { split.releasePointerCapture(e.pointerId); } catch (_) { /* 忽略 */ }
        testSaveSplitPct(parseFloat(left.style.flexBasis));   // 拖拽结束落盘
    };
    split.addEventListener('pointerup', stop);
    split.addEventListener('pointercancel', stop);
    split.addEventListener('dblclick', () => {
        left.style.flexBasis = TEST_SPLIT_DEFAULT + '%';
        testSaveSplitPct(TEST_SPLIT_DEFAULT);
    });
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
        #test-body { display:flex; flex:1 1 auto; min-height:0; overflow:hidden; }
        #test-list-wrap { flex:0 0 70%; min-width:140px; overflow:auto; padding:8px; }
        #test-list { width:100%; }
        #test-splitter { flex:0 0 6px; cursor:col-resize; background:var(--border); transition:background .12s; }
        #test-splitter:hover, #test-splitter.dragging { background:var(--accent, #4a9eff); }
        #test-result { flex:1 1 0; min-width:170px; overflow:auto; padding:8px 10px; }
        #test-result-bar { display:flex; align-items:center; gap:8px; margin-bottom:6px; position:sticky; top:0; background:var(--bg, #1e1e1e); }
        #test-result-title { font-weight:bold; font-size:12px; color:var(--dim); flex:1; }
        #test-result-bar .toolbar-btn { padding:2px 8px; font-size:11px; }
        .test-result-body { font-family:monospace; font-size:12px; white-space:pre-wrap; word-break:break-all; }
        .test-result-empty { color:var(--dim); font-family:inherit; }
        .test-result-ok { border-left:3px solid #2ed573; padding-left:8px; }
        .test-result-err { border-left:3px solid #ff4757; padding-left:8px; }
        .test-result-meta { color:var(--dim); font-size:11px; margin-bottom:6px; white-space:pre-wrap; }
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
        .cat-cp { background:rgba(255,165,0,.15); color:#ffa502; }
        .cat-cp-write { background:rgba(255,71,87,.15); color:#ff4757; }
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

// 打开页面即恢复上次的分割占比（早于切到 Test tab，避免先闪默认 7:3 再跳变）
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => testRestoreSplitPct(), { once: true });
} else {
    testRestoreSplitPct();
}
