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
