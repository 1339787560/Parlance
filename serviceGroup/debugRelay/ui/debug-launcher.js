/**
 * Launcher 面板 (2026-07-21 改: 独立页 /launcher 并入主 SPA 作 "Launcher" tab;
 * legacy launcher.html 仍保留为备用入口, 共用本 JS, DOM id 双向兼容)
 *
 * 布局 (panel-launcher 内):
 *   - 左侧 sidebar (默认折叠, 点 header 展开): 顶部=货币发放控制 (积分/银两/金币),
 *     底部=启动约定项 (预览URL/窗口数/?K/启动/重载/全关)
 *   - 右侧 iframe 网格 (2D auto-fill, 手机比例)
 *
 * 功能:
 * - 启动 N 个 cocos preview 窗口 (iframe, ?K 切 debugconfig 账号)
 * - 接收每个 iframe 内 DebugPlugin 上报的 userId (postMessage {type:'launcher_uid'})
 * - 批量发放 积分/银两/金币 到收集到的 userId 数组
 *
 * Deposit API (与 servicesvr CustomRoute/templates/deposit.html 同源对接):
 *   金币 → servicesvr POST /api/set-gold        (JSON: operation/userId[s]/goldCount)
 *   积分 → servicesvr POST /api/set-points      (JSON: userIds/count/gameid/opid; 代理拆单循环)
 *   银两 → servicesvr POST /api/set-silver      (JSON: 同上)
 * 注: 积分/银两原本浏览器直连 192.168.105.62:5003, 跨网不可达 → 改由 servicesvr 代理
 * (见 servicesvr CustomRoute/ServiceRoute.py /api/set-points + /api/set-silver)
 *
 * 默认 opid: 积分=0(设置绝对值) / 银两=2(游戏里的银子) ← 用户要求"默认发放到游戏中"
 * gameid 默认 283 (川麻 xzmo; 注意非 105, deposit.html 遗留默认 105 会触发远端 500)
 *
 * 多窗口自动布局: CSS grid 2D (ceil(sqrt(N)) 列) + aspect-ratio 9/16 手机比例
 * (见 debug-ui.css .launcher-iframe-grid / .launcher-iframe-wrap)
 */

// ===== 配置 (环境变更时改这里) =====
const SERVICESVR_HOST = 'http://localhost:5000';           // servicesvr Flask (金币 / 积分 / 银两 均走此)
// 注: 积分/银两原本浏览器直连 192.168.105.62:5003, 跨网不可达 → 改由 servicesvr 代理
// (见 servicesvr CustomRoute/ServiceRoute.py /api/set-points + /api/set-silver)
const DEFAULT_GAMEID = 283;                                 // 川麻 xzmo
const OPID = {
    points: 0,   // 设置相应的值 (绝对值)
    silver: 2,   // 设置游戏里的银子 (= "发放到游戏中")
    // silver 其他 opid: 1=保险箱 / 2=游戏里 / 3=后备箱 / 4=保险柜
};

// ===== State =====
let launcherIframes = [];   // [{ idx, url, userId, wrapEl, iframeEl, labelEl }]
let launcherCurrency = 'points';  // 默认积分 tab
let launcherMessageBound = false;

// ===== Status helpers =====
function launcherSetStatus(text, isError) {
    const el = document.getElementById('launcher-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--dim)';
}

function launcherSetGrantResult(isError, text) {
    const el = document.getElementById('launcher-grant-result');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'launcher-grant-result' + (isError ? ' error' : '');
}

// ===== Start N windows =====
function launcherStart() {
    const urlBase = (document.getElementById('launcher-preview-url').value || 'http://localhost:7456').trim();
    const n = Math.max(1, Math.min(10, parseInt(document.getElementById('launcher-window-count').value) || 1));
    const useSuffix = document.getElementById('launcher-suffix').checked;

    launcherCloseAll();
    const grid = document.getElementById('launcher-iframe-grid');

    // 2D 布局: 列数 = ceil(sqrt(N)) → 4=2x2 / 6=3x2 / 9=3x3 / 10=4x3
    // (非"从左到右一行"; 按上下左右 2D 网格排)
    const cols = Math.ceil(Math.sqrt(n));
    grid.style.gridTemplateColumns = `repeat(${cols}, minmax(280px, 1fr))`;

    launcherSetStatus(`启动 ${n} 个窗口 (${cols}列 × ${Math.ceil(n / cols)}行)...`);

    for (let i = 0; i < n; i++) {
        // 注意: 不能加 &_t cache-bust — cocos preview 把整个 query string 当账号索引解析,
        // ?0&_t=xxx 会解析成 NaN → debugconfig[NaN] undefined → setNickName 读 .length 崩.
        // 改用工具栏 "🔄 重载全部" 按钮显式刷 (iframe.contentWindow.location.reload() 跨域合法).
        const finalUrl = useSuffix ? `${urlBase}?${i}` : urlBase;

        const wrap = document.createElement('div');
        wrap.className = 'launcher-iframe-wrap';
        wrap.dataset.idx = String(i);

        const label = document.createElement('div');
        label.className = 'launcher-iframe-label';
        label.textContent = `#${i} uid: ...`;
        wrap.appendChild(label);

        const iframe = document.createElement('iframe');
        iframe.src = finalUrl;
        iframe.allow = 'autoplay; fullscreen';
        wrap.appendChild(iframe);

        const closeBtn = document.createElement('button');
        closeBtn.className = 'launcher-iframe-close';
        closeBtn.textContent = '✕';
        closeBtn.title = `关闭 #${i}`;
        closeBtn.onclick = () => launcherCloseOne(i);
        wrap.appendChild(closeBtn);

        grid.appendChild(wrap);
        launcherIframes.push({ idx: i, url: finalUrl, userId: null, wrapEl: wrap, iframeEl: iframe, labelEl: label });
    }

    launcherSetStatus(`已启动 ${n} 窗口 (${cols}×${Math.ceil(n / cols)}), 等待 userId 上报 (HallReady 后 DebugPlugin postMessage)`);
    launcherBindMessage();
    renderAccounts();
}

function launcherCloseOne(idx) {
    const pos = launcherIframes.findIndex(x => x.idx === idx);
    if (pos < 0) return;
    launcherIframes[pos].wrapEl.remove();
    launcherIframes.splice(pos, 1);
    renderAccounts();
}

function launcherCloseAll() {
    const grid = document.getElementById('launcher-iframe-grid');
    if (grid) grid.innerHTML = '';
    launcherIframes = [];
    renderAccounts();
    launcherSetStatus('');
}

/** 显式重载所有 iframe (拉最新 preview bundle, 等 cocos 重编译后用).
 *  cross-origin location.reload() 是浏览器允许的少数跨域操作之一. */
function launcherReloadAll() {
    if (launcherIframes.length === 0) {
        launcherSetStatus(true ? '' : '', '无窗口可重载');
        return;
    }
    let count = 0;
    for (const x of launcherIframes) {
        try {
            x.iframeEl.contentWindow.location.reload();
            count++;
            // 重置 userId, 等待重新上报
            x.userId = null;
            x.labelEl.textContent = `#${x.idx} uid: ...`;
        } catch (e) {
            console.warn(`[launcher] reload #${x.idx} failed:`, e);
        }
    }
    renderAccounts();
    launcherSetStatus(`已重载 ${count} 窗口, 等待 userId 重新上报...`);
}

// ===== postMessage: 接收 iframe 上报 userId =====
function launcherBindMessage() {
    if (launcherMessageBound) return;
    launcherMessageBound = true;
    window.addEventListener('message', (ev) => {
        const data = ev.data;
        if (!data || data.type !== 'launcher_uid' || !data.userId) return;
        // 优先按 ev.source 匹配对应 iframe
        let target = null;
        for (const x of launcherIframes) {
            try {
                if (x.iframeEl.contentWindow === ev.source) { target = x; break; }
            } catch { /* cross-origin 比较异常忽略 */ }
        }
        // fallback: 第一个未填 userId 的空位
        if (!target) {
            target = launcherIframes.find(x => x.userId === null) || null;
        }
        if (!target) return;
        target.userId = data.userId;
        target.labelEl.textContent = `#${target.idx} uid: ${data.userId}`;
        renderAccounts();
    });
}

// ===== Render accounts in sidebar =====
function renderAccounts() {
    const el = document.getElementById('launcher-accounts');
    if (!el) return;
    if (launcherIframes.length === 0) {
        el.innerHTML = '<div class="launcher-empty">启动窗口后自动收集 userId</div>';
        return;
    }
    const items = launcherIframes.map(x => {
        const uid = x.userId !== null ? String(x.userId) : '<span class="launcher-pending">等待...</span>';
        return `<div class="launcher-account-item">#${x.idx}: ${uid}</div>`;
    }).join('');
    const collected = launcherIframes.filter(x => x.userId !== null).length;
    el.innerHTML = `<div class="launcher-account-count">${collected}/${launcherIframes.length} 已收集</div>${items}`;
}

// ===== Sidebar toggle =====
function launcherToggleSidebar() {
    const sb = document.getElementById('launcher-sidebar');
    const arrow = document.getElementById('launcher-sidebar-arrow');
    sb.classList.toggle('collapsed');
    // 箭头左右向: 展开时 ◀ (点击向左收起), 收起时 ▶ (点击向右展开)
    if (arrow) arrow.textContent = sb.classList.contains('collapsed') ? '▶' : '◀';
}

// ===== Currency tab =====
function launcherSelectCurrency(cur) {
    launcherCurrency = cur;
    document.querySelectorAll('.launcher-tab').forEach(b => {
        b.classList.toggle('active', b.dataset.currency === cur);
    });
}

// ===== Grant: 调 deposit API =====
async function launcherGrant() {
    const userIds = launcherIframes
        .filter(x => x.userId !== null)
        .map(x => Number(x.userId));
    if (userIds.length === 0) {
        launcherSetGrantResult(true, '无可发放 userId (等待窗口上报 HallReady)');
        return;
    }
    const amount = parseInt(document.getElementById('launcher-amount').value);
    if (!amount || amount <= 0) {
        launcherSetGrantResult(true, '数量无效');
        return;
    }

    const btn = document.getElementById('launcher-grant-btn');
    const oldText = btn.textContent;
    btn.disabled = true; btn.textContent = '⏳ 发放中...';
    launcherSetGrantResult(false, `发放 ${launcherCurrency} ×${amount} → ${userIds.length} 账号 [${userIds.join(',')}]`);

    try {
        let res;
        if (launcherCurrency === 'gold') {
            // servicesvr /api/set-gold (JSON, 走 RobotToolD.exe)
            res = await fetch(`${SERVICESVR_HOST}/api/set-gold`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    operation: userIds.length === 1 ? 'single' : 'multi',
                    ...(userIds.length === 1 ? { userId: userIds[0] } : { userIds }),
                    goldCount: amount,
                }),
            });
        } else {
            // 积分/银两 → servicesvr 代理 (绕开浏览器直连远程 :5003 不可达)
            const endpoint = launcherCurrency === 'points' ? '/api/set-points' : '/api/set-silver';
            const opid = OPID[launcherCurrency];
            res = await fetch(`${SERVICESVR_HOST}${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    userIds,
                    count: amount,
                    gameid: DEFAULT_GAMEID,
                    opid,
                }),
            });
        }
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
            launcherSetGrantResult(false, `✓ 已发放 ${launcherCurrency} ×${amount} → ${userIds.length} 账号`);
        } else {
            launcherSetGrantResult(true, `✗ ${res.status}: ${data.message || data.error || JSON.stringify(data)}`);
        }
    } catch (e) {
        launcherSetGrantResult(true, `✗ ${e.message} (检查 servicesvr 可达: ${SERVICESVR_HOST})`);
    } finally {
        btn.disabled = false; btn.textContent = oldText;
    }
}
