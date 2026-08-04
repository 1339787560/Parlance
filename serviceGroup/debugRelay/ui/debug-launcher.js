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
let launcherIframes = [];   // [{ idx, url, userId, wrapEl, iframeEl, labelEl, loadTimer, started, startedAt }]
let launcherCurrency = 'points';  // 默认积分 tab
let launcherMessageBound = false;
let launcherLabelTicker = null;   // 每窗加载计时器 (UX 进度反馈)
let launcherPrewarmIframe = null; // 预热隐藏 iframe (V8 code cache 暖机, 见 launcherPrewarm)

// ===== Stagger 启动配置 =====
// 两种启动模式 (checkbox "🔀 多源拆进程" 切换):
//
// **单源 (默认 OFF → 走串行 onload 链)**:
//   同源 iframe 共享父进程 V8 (Site Isolation 不切同源), 且 cocos preview server 不发
//   Cache-Control → 4 个 iframe 同时启动会各自下载完整 bundle (MB 级) → 网络拥塞 + CPU 卡死.
//   链式: iframe[0] onload (bundle 完整加载完) → iframe[1].src → onload → ...
//   浏览器 HTTP 缓存同 top-level+frame origin 共享分区, 第 2 个起命中缓存瞬载.
//   效果: bundle 只下载 1 次, 后续 N-1 个走缓存; 首窗口最快可见.
//
// **多源 (toggle ON → 走并行)**:
//   同源是 V8 单进程瓶颈根因 — 4 个 cocos 引擎 init + login 在同一 main thread 串行执行,
//   实测每窗口 login 12-30s, 第 4 个累积最慢 (+13.8s).
//   修法: iframe i 用不同 hostname (localhost / 127.0.0.1 / 127.0.0.2 / 127.0.0.3 ...),
//   Chrome Site Isolation 按源拆 renderer 进程 → 真 4 进程并行 init + login.
//   代价: 不同源 → 不同 HTTP cache 分区 → bundle 每 origin 各下载一份. 但 localhost 带宽
//   几百 MB/s, MB 级 bundle × 4 < 1s, 远小于 CPU 并行的收益.
//
// Loopback 整个 127.0.0.0/8 路由本机, 但 **Chrome 145 实测** iframe 导航用 IP 字面量仅 localhost + 127.0.0.1
// 能完整加载 bundle (curl/bash 全 200, 但浏览器对 127.0.0.2+ 静默挂起 — 推测 Private Network Access 或
// Cocos preview Host 校验).
//
// *.localhost 扩池实验 (2026-08-04 实测, 已证伪收益): Chrome 内建 DNS 把 *.localhost 解析到 127.0.0.1 (免改
// hosts), a.localhost / b.localhost 等不同主机名 = 不同 origin → 真 N 进程并行, 技术可行. **但实测 4 origin 并行
// cold 总 59.8s / warm 46.4s, 远劣于单源串行链 27.6s**: 4 份 18MB engine bundle 同时 V8 parse → CPU/内存争抢,
// 单窗耗时从 17s 膨胀到 ~46s. 结论: 瓶颈是「每窗固定 ~18s 的 parse+init+login」而非进程数, 多源拆进程反引入
// 4× 冷下载+parse 争抢. 故池保持 2 origin (多源 toggle 仅作 2 进程实验位, 实测亦无收益 ≈ 串行), 串行链为默认最优.
const LAUNCHER_MULTI_ORIGIN_POOL = ['localhost', '127.0.0.1'];
const LAUNCHER_ONLOAD_TIMEOUT_MS = 20000;  // 单窗口 onload 等待上限 (单源链模式用)

/** 多源 URL 重写: 替换 urlBase 的 hostname 为 pool[i % pool.length], 保留 port + path. */
function launcherMultiOriginUrl(urlBase, i) {
    try {
        const u = new URL(urlBase);
        u.hostname = LAUNCHER_MULTI_ORIGIN_POOL[i % LAUNCHER_MULTI_ORIGIN_POOL.length];
        return u.toString();
    } catch {
        // urlBase 不合法 (无协议等), 退化原样
        return urlBase;
    }
}

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

// 每窗加载计时器: 给 started 但未收到 userId 的窗口显示实时秒数, 让用户看到"在动"而非黑窗卡死.
// userId 到达后由 launcherBindMessage 改写 label, 本 ticker 自动跳过 (userId !== null); 全部就绪后自停.
function launcherStartLabelTicker() {
    if (launcherLabelTicker) clearInterval(launcherLabelTicker);
    launcherLabelTicker = setInterval(() => {
        let anyLoading = false;
        for (const x of launcherIframes) {
            if (x.userId === null && x.started && x.startedAt) {
                anyLoading = true;
                const secs = Math.floor((performance.now() - x.startedAt) / 1000);
                x.labelEl.textContent = `#${x.idx} ⏱${secs}s 加载中…`;
            }
        }
        if (!anyLoading) {
            clearInterval(launcherLabelTicker);
            launcherLabelTicker = null;
        }
    }, 500);
}

// ===== 预热隐藏 iframe (V8 code cache 暖机) =====
// launcher 页加载即挂个隐藏 iframe 跑 preview: 让 V8 先 parse 18MB dev 引擎 bundle, 编译字节码写磁盘
// code cache. 用户点启动时 launcherDisposePrewarm 销毁预热 iframe (code cache 磁盘级, context 销毁不丢) →
// 真 iframe 同源同进程加载同一引擎脚本, 命中 V8 code cache 跳过 ~5s 冷 parse.
// 串行链 #0 17s→~12s, 链总 ~27s→~22s. 多源拆进程 code cache 不跨进程, 收益递减但不亏.
// 副作用: prewarm iframe 用默认账号登录, 其 launcher_uid 上报被 launcherBindMessage 显式忽略 (不计入收集).
function launcherPrewarm() {
    if (launcherPrewarmIframe) return;  // 已在预热
    const urlEl = document.getElementById('launcher-preview-url');
    if (!urlEl) return;
    const url = (urlEl.value || 'http://localhost:7456').trim();
    if (!url) return;
    try {
        const f = document.createElement('iframe');
        f.allow = 'autoplay; fullscreen';
        f.style.cssText = 'position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;border:0;';
        f.title = 'prewarm (engine code cache warmup)';
        f.src = url;  // 无 suffix, 仅 parse 引擎填 code cache
        document.body.appendChild(f);
        launcherPrewarmIframe = f;
        console.log('[launcher] prewarm hidden iframe started (V8 code cache warmup)');
    } catch (e) {
        console.warn('[launcher] prewarm start failed:', e);
    }
}

function launcherDisposePrewarm() {
    if (!launcherPrewarmIframe) return;
    try { launcherPrewarmIframe.src = 'about:blank'; } catch { /* cross-origin 可能抛 */ }
    try { launcherPrewarmIframe.remove(); } catch {}
    launcherPrewarmIframe = null;
    console.log('[launcher] prewarm iframe disposed (V8 code cache persisted on disk)');
}

// ===== Start N windows =====
function launcherStart() {
    const urlBase = (document.getElementById('launcher-preview-url').value || 'http://localhost:7456').trim();
    const n = Math.max(1, Math.min(10, parseInt(document.getElementById('launcher-window-count').value) || 1));
    const useSuffix = document.getElementById('launcher-suffix').checked;
    const useMultiOrigin = document.getElementById('launcher-multi-origin')?.checked === true;

    launcherCloseAll();
    launcherDisposePrewarm();  // 销毁预热 iframe (code cache 已落盘, 让位真窗口 + 避免默认账号与 #0 登录冲突)
    const grid = document.getElementById('launcher-iframe-grid');

    // 2D 布局: 列数 = ceil(sqrt(N)) → 4=2x2 / 6=3x2 / 9=3x3 / 10=4x3
    // (非"从左到右一行"; 按上下左右 2D 网格排)
    const cols = Math.ceil(Math.sqrt(n));
    grid.style.gridTemplateColumns = `repeat(${cols}, minmax(280px, 1fr))`;

    launcherSetStatus(`启动 ${n} 个窗口 (${cols}列 × ${Math.ceil(n / cols)}行, ${useMultiOrigin ? '多源并行' : '单源串行链'})...`);

    // 创建所有 DOM 占位 (含 close btn + label), src 暂不设
    for (let i = 0; i < n; i++) {
        // 注意: 不能加 &_t cache-bust — cocos preview 把整个 query string 当账号索引解析,
        // ?0&_t=xxx 会解析成 NaN → debugconfig[NaN] undefined → setNickName 读 .length 崩.
        // 改用工具栏 "🔄 同时刷新" 按钮显式刷 (src 重写 about:blank → 原 URL).
        // 多源模式: 替换 hostname 为 127.0.0.X 轮询 → Chrome Site Isolation 拆 renderer 进程, 真 4 进程并行.
        let baseUrl = urlBase;
        if (useMultiOrigin) baseUrl = launcherMultiOriginUrl(urlBase, i);
        const finalUrl = useSuffix ? `${baseUrl}?${i}` : baseUrl;

        const wrap = document.createElement('div');
        wrap.className = 'launcher-iframe-wrap';
        wrap.dataset.idx = String(i);

        const label = document.createElement('div');
        label.className = 'launcher-iframe-label';
        // 多源并行模式: 全部立即起, 都显示"加载中"; 单源链模式: 后续显示"排队中"
        label.textContent = (i === 0 || useMultiOrigin) ? `#${i} 加载中...` : `#${i} 排队中`;
        wrap.appendChild(label);

        const iframe = document.createElement('iframe');
        iframe.allow = 'autoplay; fullscreen';
        // src 暂不设, 等链触发 (见下方 startChain)
        wrap.appendChild(iframe);

        const closeBtn = document.createElement('button');
        closeBtn.className = 'launcher-iframe-close';
        closeBtn.textContent = '✕';
        closeBtn.title = `关闭 #${i}`;
        closeBtn.onclick = () => launcherCloseOne(i);
        wrap.appendChild(closeBtn);

        grid.appendChild(wrap);
        launcherIframes.push({
            idx: i, url: finalUrl, userId: null,
            wrapEl: wrap, iframeEl: iframe, labelEl: label,
            loadTimer: null, started: false,
        });
    }

    if (useMultiOrigin) {
        // 并行模式: 每窗口独立 origin → 独立 renderer 进程, 无 V8 竞争, 全部立即注入 src 并行启动.
        // 代价: 不同源 HTTP cache 分区, bundle 每窗口各下 1 份 (localhost 带宽足够, MB 级 < 1s).
        const poolUsed = LAUNCHER_MULTI_ORIGIN_POOL.slice(0, n).join(' / ');
        for (const e of launcherIframes) {
            e.started = true; e.startedAt = performance.now();
            e.iframeEl.onload = () => { e.labelEl.textContent = `#${e.idx} uid: ...`; };
            e.iframeEl.src = e.url;
        }
        launcherSetStatus(`已并行启动 ${n} 窗口 (多源: ${poolUsed}), 等待 userId 上报 (HallReady 后 DebugPlugin postMessage)`);
    } else {
        // 串行链模式: iframe[0] onload (bundle 完整加载) → iframe[1].src → onload → ...
        // 浏览器 HTTP 缓存 (top-level=localhost:5003, frame=localhost:7456) 同源共享, 第 2 个起命中缓存瞬载.
        // 启动链: 递归注入 src, 每窗口 onload (或超时) 后启动下一个
        const startChain = (k) => {
            if (k >= launcherIframes.length) {
                launcherSetStatus(`所有 ${launcherIframes.length} 窗口已加载, 等待 userId 上报 (HallReady 后 DebugPlugin postMessage)`);
                return;
            }
            const e = launcherIframes[k];
            if (e.started) return;  // 防重复触发 (close 早返时)
            e.started = true; e.startedAt = performance.now();
            e.labelEl.textContent = `#${e.idx} 加载中...`;
            launcherSetStatus(`#${e.idx}/${launcherIframes.length} 加载中 (bundle ${k === 0 ? '冷下载' : '走缓存'})...`);

            // onload: cross-origin iframe 的 load 事件仍可触发 (浏览器少数允许的跨域信号)
            e.iframeEl.onload = () => {
                if (e.loadTimer) { clearTimeout(e.loadTimer); e.loadTimer = null; }
                e.labelEl.textContent = `#${e.idx} uid: ...`;
                // bundle 已完整下载并进缓存, 启动下一个 (缓存命中瞬载)
                startChain(k + 1);
            };
            // Fallback: onload 超时未触发 → 不阻塞链, 强制下一个
            e.loadTimer = setTimeout(() => {
                console.warn(`[launcher] #${e.idx} onload 超时 ${LAUNCHER_ONLOAD_TIMEOUT_MS}ms, 强制链下一步`);
                e.iframeEl.onload = null;
                e.labelEl.textContent = `#${e.idx} uid: ...`;
                startChain(k + 1);
            }, LAUNCHER_ONLOAD_TIMEOUT_MS);

            e.iframeEl.src = e.url;  // 触发加载
        };
        startChain(0);
    }
    launcherStartLabelTicker();
    launcherBindMessage();
    renderAccounts();
}

function launcherCloseOne(idx) {
    const pos = launcherIframes.findIndex(x => x.idx === idx);
    if (pos < 0) return;
    // 清掉未触发的 stagger timer, 避免 close 后孤儿 src 注入到已移除 iframe
    if (launcherIframes[pos].loadTimer) {
        clearTimeout(launcherIframes[pos].loadTimer);
        launcherIframes[pos].loadTimer = null;
    }
    launcherIframes[pos].wrapEl.remove();
    launcherIframes.splice(pos, 1);
    renderAccounts();
}

function launcherCloseAll() {
    // 清所有 stagger timer
    for (const x of launcherIframes) {
        if (x.loadTimer) { clearTimeout(x.loadTimer); x.loadTimer = null; }
    }
    if (launcherLabelTicker) { clearInterval(launcherLabelTicker); launcherLabelTicker = null; }
    const grid = document.getElementById('launcher-iframe-grid');
    if (grid) grid.innerHTML = '';
    launcherIframes = [];
    renderAccounts();
    launcherSetStatus('');
}

/** 同时刷新所有 iframe (与 stagger 启动不同: 刷新走并行).
 *  前提: bundle 已在浏览器 HTTP 缓存 (前次启动预热过), 不再下载, 仅重跑 engine init/login.
 *
 *  ⚠️ 跨域限制 (2026-08-02 实测踩坑): parent=(:5003), iframe=(:7456) 不同源,
 *  Chrome 拒绝 `iframe.contentWindow.location.reload()` (SecurityError:
 *  "Failed to read a named property 'reload' from 'Location'"). 原作者误判 spec 允许,
 *  实测被拦 → count=0 全失败.
 *  改走 **src 重写**: 先 about:blank 清空, 微任务后还原 src → 触发完整导航 (走缓存).
 *  浏览器 HTTP 缓存按 URL 分区 (非 iframe 实例), 还原 src 命中前次预热的 bundle 缓存, 不重下载. */
function launcherReloadAll() {
    if (launcherIframes.length === 0) {
        launcherSetStatus('无窗口可刷新');
        return;
    }
    let count = 0;
    for (const x of launcherIframes) {
        const u = x.iframeEl.src;
        // 1) 先清空 → 解除旧 cocos 实例, 释放引擎资源
        x.iframeEl.src = 'about:blank';
        // 2) 微任务后还原 src → 触发导航 (about:blank→原 URL 必导航, 不被去重)
        //    50ms 延迟确保 about:blank 已提交, 否则部分浏览器合并两次 src 写入只生效一次
        setTimeout(((fr, url) => () => { fr.src = url; })(x.iframeEl, u), 50);
        count++;
        // 重置 userId, 等待重新上报
        x.userId = null;
        x.labelEl.textContent = `#${x.idx} uid: ...`;
    }
    renderAccounts();
    launcherSetStatus(`🔄 同时刷新 ${count} 窗口 (并行 src 重写, 等待 userId 重新上报...)`);
}

// ===== postMessage: 接收 iframe 上报 userId =====
function launcherBindMessage() {
    if (launcherMessageBound) return;
    launcherMessageBound = true;
    window.addEventListener('message', (ev) => {
        const data = ev.data;
        if (!data || data.type !== 'launcher_uid' || !data.userId) return;
        // 忽略预热 iframe 的上报 (它用默认账号登录, 不计入收集)
        if (launcherPrewarmIframe) {
            try { if (ev.source === launcherPrewarmIframe.contentWindow) return; } catch { /* cross-origin */ }
        }
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

// 页面加载即预热 (用户点启动前先 parse 18MB 引擎填 V8 code cache, 真 #0 窗命中跳冷 parse)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', launcherPrewarm);
} else {
    launcherPrewarm();
}
