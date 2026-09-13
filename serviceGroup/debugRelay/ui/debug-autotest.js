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
        autotestRenderCtl(stateResp);
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
    const localN = state.local_client_count ?? 0;
    const remoteN = (state.remote_client_ids || []).length;
    el.innerHTML = `
        <div class="autotest-row"><span class="autotest-k">开关</span><span class="autotest-v ${enabled ? 'autotest-on' : 'autotest-off'}">${enabled ? '● 已开启' : '○ 已关闭'}</span></div>
        <div class="autotest-row"><span class="autotest-k">当前 scenario</span><span class="autotest-v">${scenario}</span></div>
        <div class="autotest-row"><span class="autotest-k">可用 scenario</span><span class="autotest-v">${scnCount} 个（${(state.scenarios || []).join(', ') || '空'}）</span></div>
        <div class="autotest-row"><span class="autotest-k">本机连接（可 arm）</span><span class="autotest-v autotest-on">${localN} 个${localN ? '（' + (state.local_client_ids || []).join(', ') + '）' : ''}</span></div>
        <div class="autotest-row"><span class="autotest-k">远端连接（隔离）</span><span class="autotest-v ${remoteN ? 'autotest-off' : ''}">${remoteN} 个${remoteN ? '（' + (state.remote_client_ids || []).join(', ') + '）' : ''}</span></div>
    `;
}

/** 节拍控制态渲染（间隔/暂停 + 各客户端实际生效回执） */
function autotestRenderCtl(state) {
    const el = document.getElementById('autotest-ctl');
    if (!el) return;
    const ctl = state.ctl || {};
    const ack = state.ctl_ack || [];
    // 输入框 = 用户设定值（本地缓存优先；无缓存才用服务端值种子），编辑中不覆盖
    const cached = autotestGetCachedInterval();
    const input = document.getElementById('autotest-interval');
    if (input && document.activeElement !== input) {
        if (cached !== null) input.value = String(cached);
        else if (ctl.interval_ms != null) input.value = String(ctl.interval_ms);
    }
    // 缓存值 ≠ 服务端生效值 → 提示需点「应用」
    const pending = cached !== null && ctl.interval_ms != null && cached !== ctl.interval_ms;
    const btn = document.getElementById('autotest-pause-btn');
    if (btn) {
        btn.textContent = ctl.paused ? '▶ 继续' : '⏸ 暂停';
        btn.classList.toggle('autotest-btn-on', !!ctl.paused);
    }
    // 节奏模式回填（缓存优先；服务端 ctl 为权威）
    const paceSel = document.getElementById('autotest-pacing');
    if (paceSel && document.activeElement !== paceSel) {
        const cachedPace = autotestLsGet(AUTOTEST_LS_KEYS.pacing);
        paceSel.value = ctl.pacing || cachedPace || 'fixed';
    }
    const stepN = ctl.step || 0;
    el.innerHTML = `
        <div class="autotest-row"><span class="autotest-k">节奏模式</span><span class="autotest-v">${ctl.pacing === 'record' ? '按原时间（record 相邻动作时间差）' : '固定间隔'}</span></div>
        <div class="autotest-row"><span class="autotest-k">就位时间</span><span class="autotest-v">${ctl.settle_ms != null ? ctl.settle_ms + ' ms' : '(客户端默认 800)'} <span class="autotest-off" style="font-size:11px">阶段刚开/窗口刚亮时不抢拍</span></span></div>
        <div class="autotest-row"><span class="autotest-k">播放间隔</span><span class="autotest-v">${ctl.interval_ms != null ? ctl.interval_ms + ' ms' : '(客户端默认 1350/2250)'}${ctl.interval_ms === 0 ? ' · 最快' : ''}${pending ? ` <span class="autotest-off">(已缓存 ${cached} 未应用)</span>` : ''}</span></div>
        <div class="autotest-row"><span class="autotest-k">播放状态</span><span class="autotest-v ${ctl.paused ? 'autotest-off' : 'autotest-on'}">${ctl.paused ? '⏸ 已暂停（单步模式）' : '▶ 自动播放'}</span></div>
        <div class="autotest-row"><span class="autotest-k">单步计数</span><span class="autotest-v">${stepN} 次「立即执行」</span></div>
        <div class="autotest-row"><span class="autotest-k">客户端实际生效</span><span class="autotest-v">${
            ack.length
                ? ack.map(a => `${a.client_id}: ${a.interval_ms}ms${a.pacing === 'record' ? '(原时)' : ''}${a.paused ? ' ⏸' : ''}`).join(' · ')
                : '(无回执 — 需 AutotestPlayer 已挂载)'
        }</span></div>
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
    // 全局步数: 取各椅已触发动作的 record 全局序最大值 (面板顶部计数处显示)
    const gStep = arm.global_step || 0;
    const gTotal = arm.global_total || 0;
    if (cnt) {
        cnt.textContent = `${arm.arm_count}/${arm.client_count} 已上报`
            + (gTotal ? ` · 全局步 ${gStep}/${gTotal}` : '');
    }
    const prog = arm.progress || [];
    const arms = arm.arms || [];
    if (arms.length === 0 && prog.length === 0) {
        el.innerHTML = '<div class="events-empty">无 arm 回执（开启后客户端上报）</div>';
        return;
    }
    el.innerHTML = `
        <table class="autotest-table">
            <thead><tr><th>client_id</th><th>范围</th><th>chair</th><th>ok</th><th>rules</th><th>进度</th><th>scenario</th><th>error</th><th>ts</th></tr></thead>
            <tbody>
            ${arms.map(a => {
                const p = prog.find(x => x.client_id === a.client_id);
                const stepTxt = p ? `${p.idx}/${p.total}${p.done ? ' ✓' : ''}${p.kind ? ' · ' + p.kind : ''}` : '—';
                return `
                <tr>
                    <td>${a.client_id}</td>
                    <td class="${a.is_local ? 'autotest-on' : 'autotest-off'}">${a.is_local ? '本机' : '远端·隔离'}</td>
                    <td>${a.chair}</td>
                    <td class="${a.ok ? 'autotest-on' : 'autotest-off'}">${a.ok ? '✓' : '✗'}</td>
                    <td>${a.rules_count}</td>
                    <td class="${p && p.done ? 'autotest-on' : ''}">${stepTxt}</td>
                    <td>${a.scenario}</td>
                    <td>${a.error || ''}</td>
                    <td>${(a.ts || '').slice(11, 19)}</td>
                </tr>`;
            }).join('')}
            </tbody>
        </table>
        ${arm.scenario ? `<div class="autotest-legend">播放进度：全局 ${gStep}/${gTotal} 步（各椅取 record 全局序最大值）；本椅列为该椅自己的 idx/总动作数</div>` : ''}
    `;
}

// ── 节拍控制（可视化回放）: 间隔 / 暂停 / 立即执行 ──────────────────────
// 仅本机连接可被控制（relay 侧强制；远端连接被隔离）。

// ── 面板本地缓存（localStorage）──────────────────────────────────────
// 刷新页面 / 重开浏览器后回填上次设定：节拍间隔 + 复盘回放三个下拉。
// 均为「本浏览器偏好」，非权威态（服务端 ctl / 生效 test.ini 才是权威）。

const AUTOTEST_LS_KEYS = {
    interval: 'autotest_interval_ms',
    pacing: 'autotest_pacing',
    settle: 'autotest_settle_ms',
    replaySource: 'autotest_replay_source',
    replayMakecard: 'autotest_replay_makecard',
    replayClient: 'autotest_replay_client',
};

function autotestLsGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }   // 隐私模式/禁用 storage → 无缓存
}

function autotestLsSet(key, val) {
    try {
        if (val === null || val === undefined || val === '') localStorage.removeItem(key);
        else localStorage.setItem(key, String(val));
    } catch (e) { /* 忽略 */ }
}

function autotestGetCachedInterval() {
    const v = autotestLsGet(AUTOTEST_LS_KEYS.interval);
    if (v === null) return null;
    const n = parseInt(v, 10);
    return isNaN(n) ? null : n;
}

function autotestSetCachedInterval(ms) {
    autotestLsSet(AUTOTEST_LS_KEYS.interval, ms);
}

/** 页面加载回填输入框（缓存优先；无缓存则等 renderCtl 用服务端值种子） */
function autotestInitIntervalInput() {
    const input = document.getElementById('autotest-interval');
    if (input) {
        const cached = autotestGetCachedInterval();
        if (cached !== null) input.value = String(cached);
    }
    const paceSel = document.getElementById('autotest-pacing');
    if (paceSel) {
        const cachedPace = autotestLsGet(AUTOTEST_LS_KEYS.pacing);
        if (cachedPace) paceSel.value = cachedPace;   // 缓存只回填显示；生效以服务端 ctl 为准
    }
    const settleInput = document.getElementById('autotest-settle');
    if (settleInput) {
        const cachedSettle = autotestLsGet(AUTOTEST_LS_KEYS.settle);
        if (cachedSettle !== null) settleInput.value = cachedSettle;
    }
}

/** 节拍控制统一入口。action: set_interval | pause | resume | step */
async function autotestCtl(action, payload) {
    try {
        const resp = await fetch('/api/autotest/ctl', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(Object.assign({ action }, payload || {})),
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
            autotestSetStatus(data.error || ('HTTP ' + resp.status), true);
            return null;
        }
        const iso = data.isolated_remotes ? `（${data.isolated_remotes} 个远端连接已隔离）` : '';
        const labels = { set_interval: '间隔已应用', pause: '已暂停', resume: '已继续', step: '已立即执行' };
        autotestSetStatus(`${labels[action] || action} → ${data.sent_to} 个本机客户端${iso}`);
        await autotestRefresh();
        return data;
    } catch (e) {
        autotestSetStatus(action + ' 失败: ' + e.message, true);
        return null;
    }
}

function autotestApplyInterval() {
    const input = document.getElementById('autotest-interval');
    const ms = parseInt((input && input.value) || '', 10);
    if (isNaN(ms) || ms < 0) { autotestSetStatus('间隔需为非负整数 (ms)', true); return; }
    autotestSetCachedInterval(ms);   // 缓存设定值，刷新后回填
    autotestCtl('set_interval', { interval_ms: ms });
}

/** 节奏模式: fixed=固定间隔 / record=按原时间(record 相邻动作时间差) */
function autotestApplyPacing() {
    const sel = document.getElementById('autotest-pacing');
    const pacing = (sel && sel.value) || 'fixed';
    autotestLsSet(AUTOTEST_LS_KEYS.pacing, pacing);
    autotestCtl('set_pacing', { pacing });
}

/** 就位时间 (ms): 阶段刚开/窗口刚亮时至少等这么久才动作 */
function autotestApplySettle() {
    const input = document.getElementById('autotest-settle');
    const ms = parseInt((input && input.value) || '', 10);
    if (isNaN(ms) || ms < 0) { autotestSetStatus('就位时间需为非负整数 (ms)', true); return; }
    autotestLsSet(AUTOTEST_LS_KEYS.settle, ms);
    autotestCtl('set_settle', { settle_ms: ms });
}

function autotestTogglePause() {
    const ctl = (autotestLastState && autotestLastState.ctl) || {};
    autotestCtl(ctl.paused ? 'resume' : 'pause');
}

/** 立即执行一次动作（暂停态 = 单步推进；播放态 = 不等间隔抢一拍） */
function autotestStep() {
    autotestCtl('step');
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
autotestInitIntervalInput();   // 间隔缓存回填（localStorage；刷新/重开浏览器保留）
autotestRefresh();
autotestPollTimer = setInterval(autotestRefresh, 2000);

// ── 复盘回放（做牌激活 + 剧本 scenario 一键启动, servicesvr 联动）──
// 服务源 → servicesvr /api/record/makecards 列 ; Rec= 关联做牌;
// 启动 = POST /api/autotest/replay (激活 test.ini + 生成 replay_* scenario + 广播/单发)。

// 做牌生效目标 = debugRelay 同机服务 (客户端永远本机, 2026-09-09 定);
// 列表含从任何来源(53/OSS/本机)导出的做牌 — 复盘器直存恒写本机服务目录。
// 2026-09-09: makecards 改走 debugRelay 同源代理 /api/autotest/makecards
// (原直连 :5000 servicesvr 跨源 — 其无 CORS → 浏览器拦 → 下拉恒「拉取失败」)。

function replayStatus(text, isError) {
    const el = document.getElementById('replay-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--green)';
}

/** 当前生效 test.ini 的 Rec (replayRefresh 缓存; '__current__' 项 direct_rec 启动用) */
let replayCurrentRec = null;
/** 最近一次列表项缓存 (列表行渲染用) */
let replayItems = [];

/** 拉做牌记录列表 + 当前 test.ini 关联 + 连接列表, 渲染回放区 */
async function replayRefresh() {
    const srcSel = document.getElementById('replay-source');
    const mkSel = document.getElementById('replay-makecard');
    const cliSel = document.getElementById('replay-client');
    if (!srcSel || !mkSel) return;
    const source = srcSel.value;
    // 当前生效 test.ini 的 Rec (仅 local 源; 供下拉「当前生效」项 direct_rec 启动)
    const isLocal = source.startsWith('local-');
    replayCurrentRec = null;
    if (isLocal) {
        try {
            const c = await fetch(`/api/autotest/current_rec?source=${source}`).then(r => r.json());
            replayCurrentRec = c.rec || null;
        } catch (e) { replayCurrentRec = null; }
    }
    // 做牌下拉: 当前生效 test.ini (direct_rec) 首项 + test_*.ini 存档 (同源代理)
    try {
        const r = await fetch(`/api/autotest/makecards?source=${encodeURIComponent(source)}`).then(r => r.json());
        const items = (r.items || []);
        replayItems = items;
        // 选中值优先用当前 DOM（同页切换），其次用本地缓存（刷新/重开后回填）
        const prev = mkSel.value || autotestLsGet(AUTOTEST_LS_KEYS.replayMakecard) || '';
        const curOpt = replayCurrentRec
            ? `<option value="__current__">当前生效 · ${replayCurrentRec.record_id} 局${replayCurrentRec.round + 1}</option>`
            : '';
        const archOpts = items.map(it => `<option value="${it.name}">${it.name} · ${it.record_id} 局${it.round + 1}</option>`).join('');
        mkSel.innerHTML = (curOpt + archOpts) || '<option value="">(无关联做牌记录)</option>';
        if (items.some(it => it.name === prev) || prev === '__current__') mkSel.value = prev;
        replayRenderMakecardList();
    } catch (e) {
        replayItems = [];
        mkSel.innerHTML = `<option value="">(拉取失败: ${e.message})</option>`;
        replayRenderMakecardList();
    }
    // 连接列表 (单发启动目标) — 仅本机连接可选（远端连接被 autotest 隔离）
    if (cliSel) {
        try {
            const cs = await fetch('/api/clients').then(r => r.json());
            const list = (Array.isArray(cs) ? cs : (cs.clients || [])).filter(c => c.is_local !== false);
            const prev = cliSel.value || autotestLsGet(AUTOTEST_LS_KEYS.replayClient) || '';
            cliSel.innerHTML = list.length
                ? list.map(c => `<option value="${c.client_id || c.id}">${c.client_id || c.id}${c.chair != null ? ' · 椅' + c.chair : ''}</option>`).join('')
                : '<option value="">(无本机连接)</option>';
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
        let body;
        if (name === '__current__') {
            // 当前生效 test.ini 已关联 → direct_rec 启动 (不重复 activate; test.ini 已含 Rec)
            if (!replayCurrentRec) { replayStatus('当前 test.ini 无关联', true); return; }
            body = { source, enabled: true, direct_rec: replayCurrentRec };
        } else {
            body = { source, name, enabled: true };
        }
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

/** 做牌存档逐行列表: 点行=选中到下拉, 点 🗑 = 删该条（不必先去下拉里选中）。
 *  「当前生效」行不可删（那是 test.ini 本身, 非存档）。 */
function replayRenderMakecardList() {
    const el = document.getElementById('replay-makecard-list');
    if (!el) return;
    const mkSel = document.getElementById('replay-makecard');
    const cur = (mkSel && mkSel.value) || '';
    const rows = [];
    if (replayCurrentRec) {
        rows.push(`<div class="autotest-mk-row is-current" title="生效中的 test.ini（不是存档, 不可删）">
            <span class="autotest-mk-name">当前生效 · ${replayCurrentRec.record_id} 局${replayCurrentRec.round + 1}</span>
            <span class="autotest-mk-tag">test.ini</span>
        </div>`);
    }
    for (const it of replayItems) {
        const sel = it.name === cur ? ' is-sel' : '';
        rows.push(`<div class="autotest-mk-row${sel}" data-name="${it.name}">
            <span class="autotest-mk-name" title="点行选中">${it.name}</span>
            <span class="autotest-mk-meta">${it.record_id} 局${it.round + 1}</span>
            <button class="autotest-mk-del" title="删除 test_${it.name}.ini" onclick="replayDeleteByName('${it.name}')">🗑</button>
        </div>`);
    }
    el.innerHTML = rows.length ? rows.join('') : '<div class="events-empty">无做牌存档</div>';
    // 点行 = 选中（供「全部启动 / 当前连接启动」用）
    el.querySelectorAll('.autotest-mk-row[data-name]').forEach(row => {
        row.addEventListener('click', (ev) => {
            if (ev.target && ev.target.classList.contains('autotest-mk-del')) return;   // 删除按钮不触发选中
            const name = row.getAttribute('data-name');
            if (mkSel) mkSel.value = name;
            autotestLsSet(AUTOTEST_LS_KEYS.replayMakecard, name);
            replayRenderMakecardList();
        });
    });
}

/** 删除指定做牌存档（行内 🗑 直接调, 无需先选中） */
async function replayDeleteByName(name) {
    if (!name) return;
    if (!confirm(`删除做牌存档 test_${name}.ini ?\n(不会影响生效中的 test.ini)`)) return;
    replayStatus('删除中...');
    try {
        const source = document.getElementById('replay-source').value;
        const resp = await fetch(`/api/autotest/makecards?source=${encodeURIComponent(source)}&name=${encodeURIComponent(name)}`, {
            method: 'DELETE',
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) throw new Error(data.error || ('HTTP ' + resp.status));
        const mkSel = document.getElementById('replay-makecard');
        if (mkSel && mkSel.value === name) mkSel.value = '';
        autotestLsSet(AUTOTEST_LS_KEYS.replayMakecard, '');
        replayStatus(`✓ 已删除 test_${name}.ini`);
        await replayRefresh();
    } catch (e) {
        replayStatus('删除失败: ' + e.message, true);
    }
}

/** 删除下拉中选中项（工具栏按钮入口） */
async function replayDelete() {
    const mkSel = document.getElementById('replay-makecard');
    const name = mkSel && mkSel.value;
    if (!name) { replayStatus('先选择做牌记录', true); return; }
    if (name === '__current__') { replayStatus('「当前生效」不是存档, 需先在服务端另存为再做删除', true); return; }
    await replayDeleteByName(name);
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

/** 复盘区下拉缓存回填 + 变更即写缓存（source 需在首次 replayRefresh 前回填，否则拉错源列表） */
function autotestInitReplayCaches() {
    const srcSel = document.getElementById('replay-source');
    const mkSel = document.getElementById('replay-makecard');
    const cliSel = document.getElementById('replay-client');
    if (srcSel) {
        const cachedSrc = autotestLsGet(AUTOTEST_LS_KEYS.replaySource);
        if (cachedSrc && [...srcSel.options].some(o => o.value === cachedSrc)) srcSel.value = cachedSrc;
        // 换源 → 存缓存 + 重拉该源的做牌列表/Rec 关联（原行为）
        srcSel.addEventListener('change', () => {
            autotestLsSet(AUTOTEST_LS_KEYS.replaySource, srcSel.value);
            replayRefresh();
        });
    }
    // 做牌/连接下拉是动态重建的（replayRefresh / 5s poll），选中值在重建时用缓存回填（见 replayRefresh）
    if (mkSel) mkSel.addEventListener('change', () => autotestLsSet(AUTOTEST_LS_KEYS.replayMakecard, mkSel.value));
    if (cliSel) cliSel.addEventListener('change', () => autotestLsSet(AUTOTEST_LS_KEYS.replayClient, cliSel.value));
    if (mkSel) replayRefresh();
}
autotestInitReplayCaches();
// 连接列表随 arm 刷新 (2s poll 里做牌列表不重复拉 — servicesvr 压力考虑, 手动换源才刷新)
setInterval(async () => {
    const cliSel = document.getElementById('replay-client');
    if (!cliSel) return;
    try {
        const cs = await fetch('/api/clients').then(r => r.json());
        const list = (Array.isArray(cs) ? cs : (cs.clients || [])).filter(c => c.is_local !== false);
        const ids = list.map(c => c.client_id || c.id);
        if (ids.join(',') !== [...cliSel.options].map(o => o.value).join(',')) {
            const prev = cliSel.value || autotestLsGet(AUTOTEST_LS_KEYS.replayClient) || '';
            cliSel.innerHTML = ids.length ? ids.map(id => `<option value="${id}">${id}</option>`).join('') : '<option value="">(无本机连接)</option>';
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
        .autotest-ctl-group { display:inline-flex; gap:6px; align-items:center; padding-left:8px; border-left:1px solid var(--border); }
        .autotest-ctl-group input[type=number] { background:var(--bg-alt, rgba(255,255,255,0.04)); color:var(--fg); border:1px solid var(--border); border-radius:3px; padding:2px 4px; }
        .autotest-makecard-list { max-height:132px; overflow:auto; border:1px solid var(--border); border-radius:3px; font-size:12px; }
        .autotest-mk-row { display:flex; gap:8px; align-items:center; padding:2px 6px; cursor:pointer; border-bottom:1px solid var(--border); }
        .autotest-mk-row:last-child { border-bottom:none; }
        .autotest-mk-row:hover { background:var(--bg-alt, rgba(255,255,255,0.06)); }
        .autotest-mk-row.is-sel { background:rgba(46,213,115,0.14); }
        .autotest-mk-row.is-current { cursor:default; color:var(--dim); }
        .autotest-mk-name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .autotest-mk-meta { color:var(--dim); }
        .autotest-mk-tag { color:var(--dim); font-size:11px; }
        .autotest-mk-del { background:transparent; border:none; color:#ff4757; cursor:pointer; padding:0 4px; font-size:12px; }
        .autotest-mk-del:hover { background:rgba(255,71,87,0.15); border-radius:3px; }
    `;
    document.head.appendChild(style);
})();
