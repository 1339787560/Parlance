/**
 * Device 面板逻辑 — preview 模拟真机（deposit 式数值配置 + 模板管理）
 *
 * 驱动游戏端 __xzmp_simDevice（biz Init.ts）:
 * - 对象参数 {w,h,inset,top,notch} — 本面板数值配置直驱
 * - 字符串 profile — 内置档案
 * - null — 还原
 *
 * 交互（同 deposit 页模式）:
 * - 切到 Device tab 自动应用当前编辑器配置
 * - 数值配置: w/h/inset/top + notch 形状（none/notch刘海/waterdrop水滴/hole挖孔）
 * - 模板: localStorage 持久化；点击模板 = 应用 + 载入编辑模式；保存/删除
 */

// 内置档案（种子模板, 只读; 用户模板存 localStorage）
const DEVICE_BUILTIN = {
    iPhoneX:   { w: 1558, h: 720, inset: 91, top: 0,  notch: 'notch',     builtin: true },
    waterdrop: { w: 1440, h: 720, inset: 55, top: 0,  notch: 'waterdrop', builtin: true },
    plain169:  { w: 1280, h: 720, inset: 0,  top: 0,  notch: 'none',      builtin: true },
    iPad43:    { w: 960,  h: 720, inset: 0,  top: 0,  notch: 'none',      builtin: true },
    foldInner: { w: 1068, h: 720, inset: 0,  top: 0,  notch: 'none',      builtin: true },
    notchTop:  { w: 1440, h: 720, inset: 24, top: 48, notch: 'hole',      builtin: true },
};
const DEVICE_LS_KEY = 'device_sim_templates';

const NOTCH_OPTIONS = [
    { value: 'none',       label: '无' },
    { value: 'notch',      label: '刘海屏' },
    { value: 'waterdrop',  label: '水滴' },
    { value: 'hole',       label: '挖孔' },
];

let deviceCurrent = { w: 1558, h: 720, inset: 91, top: 0, notch: 'notch' };  // 编辑器当前值
let deviceActiveName = 'iPhoneX';  // 当前应用中的模板名（'custom' = 未存模板）

function deviceSetStatus(text, isError) {
    const el = document.getElementById('device-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--dim)';
}

/** POST /api/device 给当前选中客户端（代码通道, 非 eval — 真机无 eval 也可用） */
async function deviceCall(action, payload) {
    const url = '/api/device' + (selectedClient ? '?client=' + encodeURIComponent(selectedClient) : '');
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, payload }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.status);
    if (data.result && data.result.error) throw new Error(data.result.error);
    return data.result;
}

// ---- 配置读写 ----

function deviceReadEditor() {
    const num = (id) => parseInt(document.getElementById(id).value, 10) || 0;
    return { w: num('device-w'), h: num('device-h'), inset: num('device-inset'), top: num('device-top'), notch: document.getElementById('device-notch').value };
}

function deviceWriteEditor(cfg) {
    document.getElementById('device-w').value = cfg.w;
    document.getElementById('device-h').value = cfg.h;
    document.getElementById('device-inset').value = cfg.inset;
    document.getElementById('device-top').value = cfg.top;
    document.getElementById('device-notch').value = cfg.notch || 'none';
}

// ---- 应用 ----

async function deviceApply() {
    try {
        deviceCurrent = deviceReadEditor();
        deviceSetStatus('应用中...');
        const result = await deviceCall('apply', deviceCurrent);
        deviceRenderSnapshot(result);
        deviceSetStatus(`已应用 ${deviceActiveName === 'custom' ? '自定义' : deviceActiveName}`);
        setTimeout(deviceSnapshot, 1000);  // windowSize 异步收敛后二次快照
    } catch (e) {
        deviceSetStatus('失败: ' + e.message, true);
    }
}

async function deviceRestore() {
    try {
        deviceSetStatus('还原中...');
        const result = await deviceCall('restore');
        deviceRenderSnapshot(result);
        deviceActiveName = null;
        deviceRenderTemplates();
        deviceSetStatus('已还原真实值');
    } catch (e) {
        deviceSetStatus('失败: ' + e.message, true);
    }
}

async function deviceSnapshot() {
    try {
        const result = await deviceCall('diag', { deep: false });
        deviceRenderSnapshot(result);
    } catch (e) {
        deviceSetStatus('快照失败: ' + e.message, true);
    }
}

/** 从选中客户端抓取真机参数 → 存模板 → 应用（复现真机分辨率/安全区/异形形状） */
async function deviceCapture() {
    deviceSetStatus('抓取真机参数中...');
    try {
        const result = await deviceCall('capture');
        if (!result || result.error) throw new Error((result && result.error) || 'capture 失败（客户端可能未加载 Init.ts）');
        const c = result.simConfig || {};
        deviceCurrent = { w: c.w || 1280, h: c.h || 720, inset: c.inset || 0, top: c.top || 0, notch: c.notch || 'none' };
        deviceWriteEditor(deviceCurrent);
        // 自动存为模板（real_<platform>[_N], 不覆盖已有）
        const base = 'real_' + (result.platform !== undefined && result.platform !== null ? result.platform : 'device');
        let name = base;
        let n = 2;
        const user = deviceLoadTemplates();
        while (user[name]) { name = base + '_' + n++; }
        user[name] = Object.assign({}, deviceCurrent, { captured: true });
        deviceSaveTemplates(user);
        deviceActiveName = name;
        deviceRenderTemplates();
        deviceRenderCapture(result);
        deviceApply();
        deviceSetStatus(`已从真机抓取并保存模板 "${name}"`);
    } catch (e) {
        deviceSetStatus('抓取失败: ' + e.message, true);
    }
}

/** 渲染真机抓取详情（frame/drs/vs/safeArea/insets/platform/notch） */
function deviceRenderCapture(r) {
    const el = document.getElementById('device-snapshot');
    if (!el) return;
    const f = r.frame || {}, d = r.drs || {}, v = r.vs || {}, sa = r.safeArea || {}, ins = r.insets || {};
    const notchLabel = ({ notch: '刘海', waterdrop: '水滴', hole: '挖孔' })[r.notch] || '无';
    el.innerHTML = `
        <div class="device-row"><span class="device-k">平台</span><span class="device-v">${r.platform} / os=${r.os} ${r.isMiniGame ? '(小程序)' : r.isNative ? '(原生)' : r.isBrowser ? '(浏览器)' : ''}</span></div>
        <div class="device-row"><span class="device-k">frame</span><span class="device-v">${f.w}x${f.h}</span></div>
        <div class="device-row"><span class="device-k">designResolution</span><span class="device-v">${d.w}x${d.h}</span></div>
        <div class="device-row"><span class="device-k">visibleSize</span><span class="device-v">${v.w}x${v.h}</span></div>
        <div class="device-row"><span class="device-k">safeArea</span><span class="device-v">x:${sa.x ?? '-'} y:${sa.y ?? '-'} w:${sa.width ?? '-'} h:${sa.height ?? '-'}</span></div>
        <div class="device-row"><span class="device-k">insets</span><span class="device-v">L${ins.l} T${ins.t} R${ins.r} B${ins.b}</span></div>
        <div class="device-row"><span class="device-k">policy / notch</span><span class="device-v">${r.policy || '-'} / ${notchLabel}</span></div>
    `;
}

/** 打包彻查诊断（__xzmp_diagReport(true): Init.ts 执行/拦截器/DRS/safeArea/Canvas 布局） */
async function deviceDiag() {
    deviceSetStatus('诊断中...');
    try {
        const r = await deviceCall('diag', { deep: true });
        if (!r || r.err) throw new Error((r && (r.err || r.error)) || 'diag 失败（客户端未加载 Init.ts — 这本身就是结论: 拦截器没跑）');
        const el = document.getElementById('device-snapshot');
        const canvases = (r.canvases || []).map(c => `
            <div class="device-row device-mono"><span class="device-k">${c.name}</span><span class="device-v">pos(${c.pos ? c.pos.x + ',' + c.pos.y : '-'}) size(${c.size ? c.size.w + 'x' + c.size.h : '-'}) w[${c.widget ? 'L' + c.widget.l + ' R' + c.widget.r + ' T' + c.widget.t + ' B' + c.widget.b : '-'}] ${c.safeAreaFix ? '🛡SafeAreaFix' : ''} ${c.active ? '' : '(inactive)'}</span></div>`).join('');
        el.innerHTML = `
            <div class="device-row device-mono"><span class="device-k">initLoaded</span><span class="device-v">${r.initLoaded ? '✅ Init.ts 已执行' : '❌ 未执行(拦截器缺失)'}</span></div>
            <div class="device-row device-mono"><span class="device-k">interceptor</span><span class="device-v">${r.interceptorArmed ? '✅ 武装' : '❌ 未武装'} · bizW=${r.bizDesignWidth} · updatet=${r.updatetFn ? '✓' : '✗'}</span></div>
            <div class="device-row device-mono"><span class="device-k">平台</span><span class="device-v">${r.platform} / ${r.os} ${r.isMiniGame ? '(小程序)' : ''} · orient=${r.orientation}</span></div>
            <div class="device-row device-mono"><span class="device-k">windowSize</span><span class="device-v">${r.windowSize ? r.windowSize.width + 'x' + r.windowSize.height : '-'}</span></div>
            <div class="device-row device-mono"><span class="device-k">drs / vs</span><span class="device-v">${r.drs ? r.drs.width + 'x' + r.drs.height : '-'} / ${r.vs ? r.vs.width.toFixed(0) + 'x' + r.vs.height.toFixed(0) : '-'}</span></div>
            <div class="device-row device-mono"><span class="device-k">safeArea</span><span class="device-v">x:${r.safeArea ? r.safeArea.x : '-'} y:${r.safeArea ? r.safeArea.y : '-'} w:${r.safeArea ? r.safeArea.width : '-'}</span></div>
            <div class="device-row device-mono"><span class="device-k">policy</span><span class="device-v">${r.policy}</span></div>
            <div class="device-row device-mono"><span class="device-k">nativeEdge</span><span class="device-v">${r.nativeEdge ? JSON.stringify(r.nativeEdge) : '-'}</span></div>
            <div class="device-row device-mono device-section-title" style="margin-top:8px">Canvas 节点</div>
            ${canvases || '<div class="device-row"><span class="device-v">场景未起或无 Canvas</span></div>'}
        `;
        deviceSetStatus('诊断完成');
    } catch (e) {
        deviceSetStatus('诊断失败: ' + e.message, true);
    }
}

// ---- 模板管理（localStorage） ----

function deviceLoadTemplates() {
    try { return JSON.parse(localStorage.getItem(DEVICE_LS_KEY) || '{}'); } catch (e) { return {}; }
}

function deviceSaveTemplates(tpls) {
    localStorage.setItem(DEVICE_LS_KEY, JSON.stringify(tpls));
}

function deviceRenderTemplates() {
    const el = document.getElementById('device-templates');
    if (!el) return;
    const user = deviceLoadTemplates();
    const all = Object.assign({}, DEVICE_BUILTIN, user);
    const names = [...Object.keys(DEVICE_BUILTIN), ...Object.keys(user)];
    el.innerHTML = names.map(n => {
        const t = all[n];
        const active = deviceActiveName === n;
        const isBuiltin = !!t.builtin;
        return `<div class="device-tpl ${active ? 'device-tpl-active' : ''}" onclick="deviceUseTemplate('${n}')" title="点击应用并进入编辑">
            <span class="device-tpl-name">${n}${isBuiltin ? '' : ' *'}</span>
            <span class="device-tpl-desc">${t.w}x${t.h} · inset${t.inset}${t.top ? ' · top' + t.top : ''} · ${({ notch: '刘海', waterdrop: '水滴', hole: '挖孔' })[t.notch] || '无'}</span>
            ${isBuiltin ? '' : `<button class="device-tpl-del" onclick="event.stopPropagation();deviceDeleteTemplate('${n}')" title="删除模板">✕</button>`}
        </div>`;
    }).join('');
}

function deviceUseTemplate(name) {
    const user = deviceLoadTemplates();
    const t = DEVICE_BUILTIN[name] || user[name];
    if (!t) return;
    deviceActiveName = name;
    deviceWriteEditor(t);
    deviceCurrent = { w: t.w, h: t.h, inset: t.inset, top: t.top, notch: t.notch };
    deviceRenderTemplates();
    deviceApply();
}

function deviceSaveTemplate() {
    const cfg = deviceReadEditor();
    const name = prompt('模板名称:', deviceActiveName && deviceActiveName !== 'custom' ? deviceActiveName + '_v' : '');
    if (!name) return;
    if (DEVICE_BUILTIN[name]) { alert('与内置档案重名, 请换名'); return; }
    const user = deviceLoadTemplates();
    user[name] = cfg;
    deviceSaveTemplates(user);
    deviceActiveName = name;
    deviceRenderTemplates();
    deviceSetStatus(`模板 "${name}" 已保存`);
}

function deviceDeleteTemplate(name) {
    if (!confirm(`删除模板 "${name}"?`)) return;
    const user = deviceLoadTemplates();
    delete user[name];
    deviceSaveTemplates(user);
    if (deviceActiveName === name) deviceActiveName = null;
    deviceRenderTemplates();
}

// ---- 渲染 ----

function deviceRenderSnapshot(result) {
    const el = document.getElementById('device-snapshot');
    if (!el) return;
    if (result && result.restored) {
        el.innerHTML = '<div class="device-row"><span class="device-k">状态</span><span class="device-v device-on">● 已还原真实值</span></div>';
        return;
    }
    // DebugPlugin 内联 fallback 形状（真机无 Init.ts）
    if (result && result.ok) {
        const sa = result.safeArea || {};
        el.innerHTML = `
            <div class="device-row"><span class="device-k">状态</span><span class="device-v device-on">✅ 已应用（内联通道）</span></div>
            <div class="device-row"><span class="device-k">frame</span><span class="device-v">${result.frame || '-'}</span></div>
            <div class="device-row"><span class="device-k">inset/top</span><span class="device-v">${result.inset ?? '-'} / ${result.top ?? '-'}</span></div>
            <div class="device-row"><span class="device-k">safeArea</span><span class="device-v">x:${sa.x ?? '-'} w:${sa.width ?? '-'}</span></div>
        `;
        return;
    }
    if (result && result.drs && !result.profile) {
        el.innerHTML = `
            <div class="device-row"><span class="device-k">designResolution</span><span class="device-v">${result.drs.width ? result.drs.width + 'x' + result.drs.height : result.drs}</span></div>
            <div class="device-row"><span class="device-k">visibleSize</span><span class="device-v">${result.vs.width ? result.vs.width.toFixed(0) + 'x' + result.vs.height.toFixed(0) : result.vs}</span></div>
            <div class="device-row"><span class="device-k">safeArea</span><span class="device-v">x:${result.safeArea ? result.safeArea.x : '-'} w:${result.safeArea ? result.safeArea.width : '-'}</span></div>
            <div class="device-row"><span class="device-k">policy</span><span class="device-v">${result.policy || '-'}</span></div>
        `;
        return;
    }
    if (result && result.drs) {
        const safe = result.safeArea || {};
        const notchLabel = ({ notch: '刘海', waterdrop: '水滴', hole: '挖孔' })[result.notch] || '无';
        el.innerHTML = `
            <div class="device-row"><span class="device-k">档案</span><span class="device-v">${result.profile}</span></div>
            <div class="device-row"><span class="device-k">frame</span><span class="device-v">${result.frame || '-'}</span></div>
            <div class="device-row"><span class="device-k">designResolution</span><span class="device-v">${result.drs || '-'}</span></div>
            <div class="device-row"><span class="device-k">visibleSize</span><span class="device-v">${result.vs || '-'}</span></div>
            <div class="device-row"><span class="device-k">policy</span><span class="device-v">${result.policy || '-'}</span></div>
            <div class="device-row"><span class="device-k">safeArea</span><span class="device-v">x:${safe.x ?? '-'} w:${safe.width ?? '-'}</span></div>
            <div class="device-row"><span class="device-k">notch</span><span class="device-v">${notchLabel}</span></div>
            <div class="device-row"><span class="device-k">gdm 联动</span><span class="device-v">${result.gdmApplied ? '✅ updateArea 已触发' : '○ 不在对局场景（预期）'}</span></div>
        `;
        return;
    }
    el.textContent = JSON.stringify(result);
}

/** 编辑器 input 变化 → 未存模板态 + 实时应用（数值配置直驱） */
function deviceOnEditorInput() {
    deviceActiveName = 'custom';
    deviceRenderTemplates();
    deviceApply();
}

/** tab 切到 device: 初始化 + 直接应用当前配置 */
function deviceOnTabShow() {
    if (!document.getElementById('device-templates').dataset.populated) {
        document.getElementById('device-templates').dataset.populated = '1';
        const sel = document.getElementById('device-notch');
        sel.innerHTML = NOTCH_OPTIONS.map(o => `<option value="${o.value}">${o.label}</option>`).join('');
        deviceWriteEditor(deviceCurrent);
    }
    deviceRenderTemplates();
    deviceApply();
}

// 注入极简样式（避免改 debug-ui.css, 同 autotest 模式）
(function injectDeviceStyle() {
    if (document.getElementById('device-style')) return;
    const style = document.createElement('style');
    style.id = 'device-style';
    style.textContent = `
        #panel-device { flex-direction: column; }
        #device-toolbar { display:flex; gap:8px; align-items:center; padding:6px 8px; border-bottom:1px solid var(--border); flex-wrap:wrap; }
        #device-body { padding:8px; overflow:auto; display:flex; gap:12px; align-items:flex-start; flex-wrap:wrap; }
        .device-section { margin-bottom:12px; min-width:300px; }
        .device-section-title { font-weight:bold; margin-bottom:4px; color:var(--dim); font-size:12px; text-transform:uppercase; }
        .device-config-grid { display:grid; grid-template-columns: auto 1fr; gap:4px 8px; align-items:center; }
        .device-config-grid label { color:var(--dim); font-size:12px; }
        .device-config-grid input, .device-config-grid select { width:100%; padding:2px 6px; background:var(--bg, #1e1e1e); color:var(--fg); border:1px solid var(--border); border-radius:3px; }
        .device-btn-row { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
        .device-row { display:flex; gap:8px; padding:2px 0; }
        .device-k { min-width:130px; color:var(--dim); }
        .device-v { color:var(--fg); }
        .device-mono .device-k, .device-mono .device-v { font-family:monospace; font-size:11px; }
        .device-on { color:#2ed573; }
        .device-tpl { display:flex; align-items:center; gap:8px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; margin-bottom:4px; cursor:pointer; }
        .device-tpl:hover { border-color:var(--accent, #4a9eff); }
        .device-tpl-active { border-color:#2ed573; background:rgba(46,213,115,0.08); }
        .device-tpl-name { font-weight:bold; min-width:90px; }
        .device-tpl-desc { color:var(--dim); font-size:11px; flex:1; }
        .device-tpl-del { background:none; border:none; color:var(--red, #ff4757); cursor:pointer; padding:0 4px; }
        .device-legend { color:var(--dim); font-size:11px; padding:6px 0; border-top:1px solid var(--border); margin-top:8px; width:100%; }
    `;
    document.head.appendChild(style);
})();
