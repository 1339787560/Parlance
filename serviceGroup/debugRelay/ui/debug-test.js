/**
 * Test 面板逻辑 — creator xzmp 测试接口统一入口
 *
 * - GET  /api/debug-index  拉取当前客户端已注入的调试接口目录
 * - POST /api/test-call    调用 window.<name>(...args) 模拟测试行为
 *
 * 目录来自 creator xzmp 的 window.__debugIndex / agent.meta.registry()；
 * Agent 可用同一组 REST 完成相同操作。
 */

let testCatalog = null;      // {namespaces, refs, count, namespace_count}

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
    const list = document.getElementById('test-list');
    const result = document.getElementById('test-result');
    if (list) list.innerHTML = '<div class="events-empty">选择客户端后点击刷新查看测试接口</div>';
    if (result) {
        result.textContent = '尚未执行测试接口';
        result.className = 'test-result-empty';
    }
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

function testFlattenCatalog(catalog) {
    const fns = (catalog && catalog.namespaces) || {};
    const out = [];
    for (const ns of Object.keys(fns)) {
        const members = fns[ns] || {};
        for (const fn of Object.keys(members)) {
            const meta = members[fn] || {};
            out.push({
                name: `${ns}.${fn}`,
                ns,
                fn,
                arity: meta.arity != null ? meta.arity : 0,
                desc: meta.desc || '',
                env: meta.env || '',
            });
        }
    }
    out.sort((a, b) => a.name.localeCompare(b.name));
    return out;
}

function testRender() {
    const list = document.getElementById('test-list');
    if (!list) return;
    if (!testCatalog) return;
    const all = testFlattenCatalog(testCatalog);
    const q = (document.getElementById('test-search').value || '').trim().toLowerCase();
    const filtered = q ? all.filter(x =>
        x.name.toLowerCase().includes(q) ||
        (x.desc || '').toLowerCase().includes(q)
    ) : all;
    if (filtered.length === 0) {
        list.innerHTML = '<div class="events-empty">没有匹配的测试接口</div>';
        return;
    }
    // 按命名空间分组渲染
    const groups = {};
    for (const item of filtered) {
        (groups[item.ns] = groups[item.ns] || []).push(item);
    }
    list.innerHTML = Object.keys(groups).sort().map(ns => {
        const items = groups[ns].map(item => `
            <div class="test-item">
                <div class="test-item-info">
                    <span class="test-item-name">${escapeHtml(item.name)}</span>
                    ${item.env ? `<span class="test-item-env">${escapeHtml(item.env)}</span>` : ''}
                    <span class="test-item-arity">arity ${item.arity}</span>
                    ${item.desc ? `<span class="test-item-desc">${escapeHtml(item.desc)}</span>` : ''}
                </div>
                <button class="test-item-run" onclick="testCall('${escapeHtml(item.name).replace(/'/g, "\\'")}', ${item.arity})">▶ 执行</button>
            </div>
        `).join('');
        return `<div class="test-group">
            <div class="test-group-title">${escapeHtml(ns)} (${items.length})</div>
            ${items}
        </div>`;
    }).join('');
}

async function testCall(name, arity) {
    let args = [];
    if (arity > 0) {
        const raw = prompt(`${name} 参数（JSON 数组）:`, '[]');
        if (raw === null) return;
        try {
            args = JSON.parse(raw || '[]');
            if (!Array.isArray(args)) throw new Error('必须是数组');
        } catch (e) {
            alert('参数格式错误: ' + e.message);
            return;
        }
    }
    const resultEl = document.getElementById('test-result');
    if (resultEl) {
        resultEl.textContent = `正在调用 ${name} ...`;
        resultEl.className = 'test-result-pending';
    }
    testSetStatus(`调用 ${name}...`);
    try {
        const resp = await fetch('/api/test-call', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, args, client: selectedClient }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        testRenderResult(data);
        testSetStatus(`${name} 执行完成`);
    } catch (e) {
        if (resultEl) {
            resultEl.textContent = '调用失败: ' + e.message;
            resultEl.className = 'test-result-error';
        }
        testSetStatus('调用失败', true);
    }
}

function testRenderResult(data) {
    const el = document.getElementById('test-result');
    if (!el) return;
    if (data.eval_error) {
        el.textContent = `错误: ${data.eval_result || 'eval error'}`;
        el.className = 'test-result-error';
        return;
    }
    // eval_result 已是游戏端序列化字符串；尝试 JSON.parse 后美化展示，失败则原样
    let text = String(data.eval_result ?? 'undefined');
    try {
        const parsed = JSON.parse(text);
        text = JSON.stringify(parsed, null, 2);
    } catch (_) { /* 原始值/非 JSON 文本，原样展示 */ }
    el.textContent = text;
    el.className = 'test-result-ok';
}

// 注入极简样式（避免改 debug-ui.css, 同 device/autotest 模式）
(function injectTestStyle() {
    if (document.getElementById('test-style')) return;
    const style = document.createElement('style');
    style.id = 'test-style';
    style.textContent = `
        #panel-test { flex-direction: column; }
        #test-toolbar { display:flex; gap:8px; align-items:center; padding:6px 8px; border-bottom:1px solid var(--border); flex-wrap:wrap; }
        #test-body { padding:8px; overflow:auto; display:flex; gap:12px; align-items:flex-start; flex-wrap:wrap; }
        #test-list { flex:1 1 480px; min-width:320px; }
        #test-result-wrap { flex:1 1 320px; min-width:260px; }
        .test-group { margin-bottom:10px; }
        .test-group-title { font-weight:bold; color:var(--dim); font-size:12px; text-transform:uppercase; margin:8px 0 4px; }
        .test-item { display:flex; align-items:center; gap:8px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; margin-bottom:4px; }
        .test-item:hover { border-color:var(--accent, #4a9eff); }
        .test-item-info { flex:1; min-width:0; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
        .test-item-name { font-family:monospace; font-size:12px; }
        .test-item-env { background:rgba(74,158,255,.15); color:var(--accent, #4a9eff); border-radius:3px; padding:0 4px; font-size:10px; }
        .test-item-arity { color:var(--dim); font-size:10px; }
        .test-item-desc { color:var(--dim); font-size:11px; width:100%; }
        .test-item-run { background:var(--bg-alt, rgba(255,255,255,0.06)); border:1px solid var(--border); color:var(--fg); border-radius:3px; padding:2px 8px; cursor:pointer; }
        .test-item-run:hover { border-color:#2ed573; color:#2ed573; }
        .test-section-title { font-weight:bold; margin-bottom:4px; color:var(--dim); font-size:12px; text-transform:uppercase; }
        #test-result { white-space:pre-wrap; word-break:break-all; background:var(--bg-alt, rgba(255,255,255,0.04)); border:1px solid var(--border); border-radius:4px; padding:8px; min-height:80px; max-height:480px; overflow:auto; font-family:monospace; font-size:12px; }
        .test-result-empty { color:var(--dim); }
        .test-result-pending { color:var(--accent, #4a9eff); }
        .test-result-ok { color:var(--fg); }
        .test-result-error { color:var(--red, #ff4757); }
        .test-legend { color:var(--dim); font-size:11px; padding:6px 0; border-top:1px solid var(--border); margin-top:8px; width:100%; }
        .test-legend code { background:var(--bg-alt, rgba(255,255,255,0.04)); padding:0 3px; border-radius:3px; }
    `;
    document.head.appendChild(style);
})();
