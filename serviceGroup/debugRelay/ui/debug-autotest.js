/**
 * AutoTest 面板逻辑 (SDD 客户端对局自动化测试)
 *
 * - 状态 + scenario 列表: GET /api/autotest
 * - 开关: POST /api/autotest {enabled, scenario}
 * - 四家 arm 全景: GET /api/autotest/arm
 *
 * 开启 → relay 广播 AUTOTEST_STATE → 各客户端 DebugPlugin fetch scenario +
 * 动态挂载 AutotestPlayer → update(dt) 自驱跑局 → arm 回执上报聚合到 /api/autotest/arm。
 *
 * switchTab 由 debug-console.js 提供。poll 每 2s 刷新（REST 轻，n≤4 客户端）。
 */

let autotestPollTimer = null;
let autotestLastState = null;

function autotestSetStatus(text, isError) {
    const el = document.getElementById('autotest-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--dim)';
}

/** 拉状态 + scenario 列表 + arm 全景，渲染 */
async function autotestRefresh() {
    try {
        const [stateResp, armResp] = await Promise.all([
            fetch('/api/autotest').then(r => r.json()),
            fetch('/api/autotest/arm').then(r => r.json()),
        ]);
        autotestLastState = stateResp;
        autotestRenderState(stateResp);
        autotestRenderScenarioSelect(stateResp);
        autotestRenderArm(armResp);
        autotestRenderToggleButton(stateResp);
        autotestSetStatus('');
    } catch (e) {
        autotestSetStatus('拉取失败: ' + e.message, true);
    }
}

function autotestRenderState(state) {
    const el = document.getElementById('autotest-state');
    if (!el) return;
    const enabled = !!state.enabled;
    const scenario = state.scenario || '(无)';
    const scnCount = (state.scenarios || []).length;
    el.innerHTML = `
        <div class="autotest-row"><span class="autotest-k">开关</span><span class="autotest-v ${enabled ? 'autotest-on' : 'autotest-off'}">${enabled ? '● 已开启' : '○ 已关闭'}</span></div>
        <div class="autotest-row"><span class="autotest-k">当前 scenario</span><span class="autotest-v">${scenario}</span></div>
        <div class="autotest-row"><span class="autotest-k">可用 scenario</span><span class="autotest-v">${scnCount} 个（${(state.scenarios || []).join(', ') || '空'}）</span></div>
    `;
}

function autotestRenderScenarioSelect(state) {
    const sel = document.getElementById('autotest-scenario');
    if (!sel) return;
    const scenarios = state.scenarios || [];
    const cur = state.scenario || '';
    const existing = sel.dataset.populated === String(scenarios.join(',')) && sel.value === cur;
    if (existing) return;
    sel.innerHTML = scenarios.map(s => `<option value="${s}" ${s === cur ? 'selected' : ''}>${s}</option>`).join('');
    sel.dataset.populated = String(scenarios.join(','));
}

function autotestRenderToggleButton(state) {
    const btn = document.getElementById('autotest-toggle-btn');
    if (!btn) return;
    const enabled = !!state.enabled;
    btn.textContent = enabled ? '⏻ 关闭' : '⏻ 开启';
    btn.classList.toggle('autotest-btn-on', enabled);
}

function autotestRenderArm(arm) {
    const el = document.getElementById('autotest-arm');
    const cnt = document.getElementById('autotest-arm-count');
    if (!el) return;
    if (cnt) cnt.textContent = `${arm.arm_count}/${arm.client_count} 已上报`;
    const arms = arm.arms || [];
    if (arms.length === 0) {
        el.innerHTML = '<div class="events-empty">无 arm 回执（开启后客户端上报）</div>';
        return;
    }
    el.innerHTML = `
        <table class="autotest-table">
            <thead><tr><th>client_id</th><th>chair</th><th>ok</th><th>rules</th><th>scenario</th><th>error</th><th>ts</th></tr></thead>
            <tbody>
            ${arms.map(a => `
                <tr>
                    <td>${a.client_id}</td>
                    <td>${a.chair}</td>
                    <td class="${a.ok ? 'autotest-on' : 'autotest-off'}">${a.ok ? '✓' : '✗'}</td>
                    <td>${a.rules_count}</td>
                    <td>${a.scenario}</td>
                    <td>${a.error || ''}</td>
                    <td>${(a.ts || '').slice(11, 19)}</td>
                </tr>
            `).join('')}
            </tbody>
        </table>
    `;
}

/** 开关按钮：切换 enabled，scenario 用下拉选中值 */
async function autotestToggle() {
    const state = autotestLastState;
    const nextEnabled = !(state && state.enabled);
    const sel = document.getElementById('autotest-scenario');
    const scenario = (sel && sel.value) || '';
    if (nextEnabled && !scenario) {
        autotestSetStatus('开启需先选 scenario', true);
        return;
    }
    autotestSetStatus(nextEnabled ? '广播开启中...' : '广播关闭中...');
    try {
        const resp = await fetch('/api/autotest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: nextEnabled, scenario: nextEnabled ? scenario : '' }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            autotestSetStatus(data.error || ('HTTP ' + resp.status), true);
            return;
        }
        autotestSetStatus(`已广播给 ${data.broadcast_to} 客户端`);
        await autotestRefresh();
    } catch (e) {
        autotestSetStatus('切换失败: ' + e.message, true);
    }
}

/** tab 切到 autotest 时触发（debug-console.js switchTab 调，若存在） */
function autotestOnTabShow() {
    autotestRefresh();
    if (!autotestPollTimer) autotestPollTimer = setInterval(autotestRefresh, 2000);
}

// 初始拉一次 + 启 poll（轻量，tab 隐藏时 CSS 不显示但数据新鲜）
autotestRefresh();
autotestPollTimer = setInterval(autotestRefresh, 2000);

// ── 复盘回放（做牌激活 + 剧本 scenario 一键启动, servicesvr 联动）──
// 服务源 → servicesvr /api/record/makecards 列 ; Rec= 关联做牌;
// 启动 = POST /api/autotest/replay (激活 test.ini + 生成 replay_* scenario + 广播/单发)。

const REPLAY_SVRS = {
    'local-xzms': 'http://127.0.0.1:5000',
    'local-xzmo': 'http://127.0.0.1:5000',
    'local-xzmo2': 'http://127.0.0.1:5000',
    'bastion-53-xzmo': 'http://127.0.0.1:5000',
    'bastion-53-xzmo2': 'http://127.0.0.1:5000',
};

function replayStatus(text, isError) {
    const el = document.getElementById('replay-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--green)';
}

/** 拉做牌记录列表 + 当前 test.ini 关联 + 连接列表, 渲染回放区 */
async function replayRefresh() {
    const srcSel = document.getElementById('replay-source');
    const mkSel = document.getElementById('replay-makecard');
    const cliSel = document.getElementById('replay-client');
    if (!srcSel || !mkSel) return;
    const source = srcSel.value;
    // 做牌记录列表 (servicesvr 直连; CORS 已放开)
    try {
        const r = await fetch(`${REPLAY_SVRS[source]}/api/record/makecards?source=${encodeURIComponent(source)}`).then(r => r.json());
        const items = (r.items || []);
        const prev = mkSel.value;
        mkSel.innerHTML = items.length
            ? items.map(it => `<option value="${it.name}">${it.name} · ${it.record_id} 局${it.round + 1}</option>`).join('')
            : '<option value="">(无关联做牌记录)</option>';
        if (items.some(it => it.name === prev)) mkSel.value = prev;
    } catch (e) {
        mkSel.innerHTML = `<option value="">(拉取失败: ${e.message})</option>`;
    }
    // 当前 test.ini 关联 (仅 local 源)
    const recEl = document.getElementById('replay-current-rec');
    if (recEl) {
        if (!source.startsWith('local-')) {
            recEl.textContent = '当前 test.ini 关联: bastion 源暂不支持远读, 启动时由激活步骤自动校验';
        } else {
            try {
                const c = await fetch(`/api/autotest/current_rec?source=${source}`).then(r => r.json());
                if (c.rec) {
                    recEl.innerHTML = `当前 test.ini 已关联: <b>${c.rec.record_id} 局${c.rec.round + 1}</b> ` +
                        `(${c.has_total ? '做牌生效中' : '⚠ 无 Total'}) <button class="toolbar-btn" style="padding:2px 8px" onclick="replayLaunchRec(${JSON.stringify(c.rec).replace(/"/g, '&quot;')})">▶ 按此关联启动</button>`;
                } else {
                    recEl.textContent = '当前 test.ini 无 ; Rec= 关联' + (c.has_total ? '（做牌生效中, 来源非复盘器直存）' : '');
                }
            } catch (e) { recEl.textContent = ''; }
        }
    }
    // 连接列表 (单发启动目标)
    if (cliSel) {
        try {
            const cs = await fetch('/api/clients').then(r => r.json());
            const list = Array.isArray(cs) ? cs : (cs.clients || []);
            const prev = cliSel.value;
            cliSel.innerHTML = list.length
                ? list.map(c => `<option value="${c.client_id || c.id}">${c.client_id || c.id}${c.chair != null ? ' · 椅' + c.chair : ''}</option>`).join('')
                : '<option value="">(无连接)</option>';
            if (list.some(c => (c.client_id || c.id) === prev)) cliSel.value = prev;
        } catch (e) { /* 忽略, 列表空态 */ }
    }
}

/** 启动回放: clientId=null 广播全部; 指定 = 单连接 */
async function replayLaunch(clientId) {
    const mkSel = document.getElementById('replay-makecard');
    const name = mkSel && mkSel.value;
    const source = document.getElementById('replay-source').value;
    if (!name) { replayStatus('先选择做牌记录', true); return; }
    replayStatus('启动中 (激活做牌+生成剧本)...');
    try {
        const body = { source, name, enabled: true };
        if (clientId) body.client_id = clientId;
        const resp = await fetch('/api/autotest/replay', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        replayStatus(`✓ ${data.scenario} (${data.actions} 步, 已发 ${data.broadcast_to} 连接)`);
        await autotestRefresh();
    } catch (e) {
        replayStatus('启动失败: ' + e.message, true);
    }
}

function replayLaunchClient() {
    const cid = document.getElementById('replay-client').value;
    if (!cid) { replayStatus('无连接可选', true); return; }
    replayLaunch(cid);
}

/** 当前 test.ini 已有关联 → direct_rec 路径启动 (做牌已生效, 跳过激活直接加载剧本) */
async function replayLaunchRec(rec, clientId) {
    replayStatus('按当前关联启动中...');
    try {
        const source = document.getElementById('replay-source').value;
        const body = { source, enabled: true, direct_rec: rec };
        if (clientId) body.client_id = clientId;
        const resp = await fetch('/api/autotest/replay', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.error || ('HTTP ' + resp.status));
        replayStatus(`✓ ${data.scenario} (${data.actions} 步, 已发 ${data.broadcast_to} 连接)`);
        await autotestRefresh();
    } catch (e) {
        replayStatus('启动失败: ' + e.message, true);
    }
}

document.getElementById('replay-source').addEventListener('change', replayRefresh);
if (document.getElementById('replay-makecard')) replayRefresh();
// 连接列表随 arm 刷新 (2s poll 里做牌列表不重复拉 — servicesvr 压力考虑, 手动换源才刷新)
setInterval(async () => {
    const cliSel = document.getElementById('replay-client');
    if (!cliSel) return;
    try {
        const cs = await fetch('/api/clients').then(r => r.json());
        const list = Array.isArray(cs) ? cs : (cs.clients || []);
        const ids = list.map(c => c.client_id || c.id);
        if (ids.join(',') !== [...cliSel.options].map(o => o.value).join(',')) {
            const prev = cliSel.value;
            cliSel.innerHTML = ids.length ? ids.map(id => `<option value="${id}">${id}</option>`).join('') : '<option value="">(无连接)</option>';
            if (ids.includes(prev)) cliSel.value = prev;
        }
    } catch (e) { /* ignore */ }
}, 5000);

// 注入极简样式（避免改 debug-ui.css）
(function injectAutotestStyle() {
    if (document.getElementById('autotest-style')) return;
    const style = document.createElement('style');
    style.id = 'autotest-style';
    style.textContent = `
        #panel-autotest { flex-direction: column; }   /* 覆盖 .panel 默认 row, toolbar 上 body 下 */
        #autotest-toolbar { display:flex; gap:8px; align-items:center; padding:6px 8px; border-bottom:1px solid var(--border); flex-wrap:wrap; }
        #autotest-body { padding:8px; overflow:auto; }
        .autotest-section { margin-bottom:12px; }
        .autotest-section-title { font-weight:bold; margin-bottom:4px; color:var(--dim); font-size:12px; text-transform:uppercase; }
        .autotest-row { display:flex; gap:8px; padding:2px 0; }
        .autotest-k { min-width:120px; color:var(--dim); }
        .autotest-v { color:var(--fg); }
        .autotest-on { color:#2ed573; }
        .autotest-off { color:#ff4757; }
        .autotest-btn-on { background:#2ed573 !important; color:#000 !important; }
        .autotest-table { width:100%; border-collapse:collapse; font-size:12px; }
        .autotest-table th, .autotest-table td { border:1px solid var(--border); padding:3px 6px; text-align:left; }
        .autotest-table th { background:var(--bg-alt, rgba(255,255,255,0.04)); color:var(--dim); }
        .autotest-legend { color:var(--dim); font-size:11px; padding:6px 0; border-top:1px solid var(--border); margin-top:8px; }
    `;
    document.head.appendChild(style);
})();
