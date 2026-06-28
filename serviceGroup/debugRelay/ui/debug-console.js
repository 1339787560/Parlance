/**
 * Console 面板逻辑
 * - WebSocket 连接管理
 * - 全量同步（新连接获取历史）
 * - 增量追加（实时消息）
 * - 过滤（log/warn/error/info）
 */

// ---- Filter State ----
const filters = { log: true, warn: true, error: true, info: true };

function toggleFilter(name) {
    filters[name] = !filters[name];
    const btn = document.getElementById(`filter-${name}`);
    btn.classList.toggle('active', filters[name]);
    btn.classList.toggle('inactive', !filters[name]);
    refreshConsoleDisplay();
}

function clearConsole() {
    const output = document.getElementById('console-output');
    output.innerHTML = '';
}

function scrollToBottom() {
    const output = document.getElementById('console-output');
    output.scrollTop = output.scrollHeight;
}

// ---- Console Display ----

const allEntries = [];  // 全量消息列表

/** 是否用户正在"跟踪底部"（滚动条在最下方附近） */
function isAtBottom() {
    const output = document.getElementById('console-output');
    // 距底部 <= 2 行高度即视为"在底部"
    return output.scrollHeight - output.scrollTop - output.clientHeight <= 24;
}

function addConsoleEntry(entry) {
    allEntries.push(entry);
    if (shouldShow(entry)) {
        renderEntry(entry, true);
    }
}

function addConsoleBatch(entries) {
    // 批量追加时暂挂自动滚动，最后统一处理
    for (const entry of entries) {
        allEntries.push(entry);
        if (shouldShow(entry)) {
            renderEntry(entry, false);
        }
    }
    const output = document.getElementById('console-output');
    output.scrollTop = output.scrollHeight;
}

function shouldShow(entry) {
    const typeMap = {
        console_log: 'log',
        console_warn: 'warn',
        console_error: 'error',
        console_info: 'info',
    };
    const filterName = typeMap[entry.type] || 'log';
    return filters[filterName];
}

function refreshConsoleDisplay() {
    const wasAtBottom = isAtBottom();
    const output = document.getElementById('console-output');
    output.innerHTML = '';
    for (const entry of allEntries) {
        if (shouldShow(entry)) {
            renderEntry(entry, false);
        }
    }
    if (wasAtBottom) {
        requestAnimationFrame(() => {
            output.scrollTop = output.scrollHeight;
        });
    }
}

function renderEntry(entry, autoScroll) {
    const output = document.getElementById('console-output');
    const div = document.createElement('div');

    const typeClass = entry.type.replace('console_', '');
    div.className = `console-entry console-${typeClass}`;

    // 前缀图标替代行号
    const iconMap = { log: '›', warn: '⚠', error: '✕', info: 'ℹ' };
    const icon = iconMap[typeClass] || '›';
    div.innerHTML = `<span class="log-icon">${icon}</span>${escapeHtml(entry.content)}`;

    output.appendChild(div);

    // 自动滚动：仅当 autoScroll=true 且用户在底部时
    if (autoScroll && isAtBottom()) {
        requestAnimationFrame(() => {
            output.scrollTop = output.scrollHeight;
        });
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---- Eval ----

function evalExpr() {
    const input = document.getElementById('eval-input');
    const expr = input.value.trim();
    if (!expr) return;

    // 发送 eval 请求给游戏端
    wsSend({ type: 'eval', expr: expr });

    // 在控制台显示正在执行的表达式
    const output = document.getElementById('console-output');
    const div = document.createElement('div');
    div.className = 'console-entry console-info';
    div.innerHTML = `<span class="log-icon">▸</span>${escapeHtml(expr)}`;
    output.appendChild(div);

    // 滚动到底部让用户看到输入的表达式
    output.scrollTop = output.scrollHeight;

    input.value = '';
}

// ---- Tab Switching ----

function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));

    document.getElementById(`tab-${tab}`).classList.add('active');
    document.getElementById(`panel-${tab}`).classList.add('active');

    // 持久化 tab 选择，刷新后恢复
    try { localStorage.setItem('debug_active_tab', tab); } catch(e) {}

    if (tab === 'perf' && window.renderPerfCharts) {
        setTimeout(window.renderPerfCharts, 50);
    }
    // 首次切换到 events 面板时自动加载分类列表
    if (tab === 'events' && typeof eventsLoadCategories === 'function') {
        eventsLoadCategories();
    }
}

function restoreActiveTab() {
    let saved = null;
    try { saved = localStorage.getItem('debug_active_tab'); } catch(e) {}
    if (saved && document.getElementById(`tab-${saved}`)) {
        switchTab(saved);
    }
}

// ---- WebSocket ----

let ws = null;
let reconnectTimer = null;

function wsConnect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${location.host}/ws/browser`;

    ws = new WebSocket(url);

    ws.onopen = () => {
        updateStatus('connected');
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleBrowserMessage(msg);
    };

    ws.onclose = () => {
        updateStatus('disconnected');
        // 自动重连
        reconnectTimer = setTimeout(wsConnect, 3000);
    };

    ws.onerror = () => {
        ws.close();
    };
}

function wsSend(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg));
    }
}

function handleBrowserMessage(msg) {
    switch (msg.type) {
        case 'console_batch':
            // 全量历史消息
            addConsoleBatch(msg.messages);
            break;

        case 'console_log':
        case 'console_warn':
        case 'console_error':
        case 'console_info':
            // 实时消息
            addConsoleEntry(msg);
            break;

        case 'game_connected':
            // 游戏端连接：若带有 clear_console 标记则清空并重新同步
            if (msg.clear_console) {
                allEntries.length = 0;     // 清空本地缓冲
                const output = document.getElementById('console-output');
                output.innerHTML = '';     // 清空显示
            }
            updateGameStatus(true, msg.ts);
            break;

        case 'game_disconnected':
            updateGameStatus(false, msg.ts);
            break;

        case 'breakpoint_hit':
            handleBreakpointHit(msg);
            break;

        case 'pause_state':
            handlePauseState(msg);
            break;

        case 'source_list':
            handleSourceList(msg);
            break;

        case 'source_content':
            handleSourceContent(msg);
            break;

        case 'perf_snapshot':
            if (window.handlePerfSnapshot) window.handlePerfSnapshot(msg);
            break;

        case 'perf_history':
            if (window.handlePerfHistory) window.handlePerfHistory(msg.snapshots || []);
            break;

        case 'important_event':
            if (typeof onRealtimeEvent === 'function') onRealtimeEvent(msg);
            break;

        // eval 结果也在控制台显示
        default:
            if (msg.eval_result !== undefined) {
                try {
                    const output = document.getElementById('console-output');
                    const div = document.createElement('div');
                    div.className = msg.eval_error ? 'eval-error' : 'eval-result';

                    const icon = msg.eval_error ? '✕' : (msg.eval_is_object ? '⊕' : '←');
                    const iconSpan = document.createElement('span');
                    iconSpan.className = 'log-icon';
                    iconSpan.textContent = icon;
                    div.appendChild(iconSpan);

                    const raw = String(msg.eval_result);
                    if (msg.eval_is_object) {
                        // Object：用折叠树展示
                        const tree = buildFoldableTree(raw);
                        div.appendChild(tree);
                    } else {
                        // 原始值：单行
                        const text = document.createElement('span');
                        text.textContent = raw;
                        div.appendChild(text);
                    }

                    output.appendChild(div);
                    requestAnimationFrame(() => { output.scrollTop = output.scrollHeight; });
                } catch (e) {
                    console.error('[eval] render failed:', e);
                }
            }
            break;
    }
}

// ---- 折叠树（浏览器 DevTools 风格） -----------------------------

/**
 * 解析 JSON 字符串为折叠树
 * 节点类型：object / array / leaf（string/number/bool/null）
 */
function buildFoldableTree(jsonText) {
    const container = document.createElement('div');
    container.className = 'eval-tree';

    let parsed;
    try {
        parsed = JSON.parse(jsonText);
    } catch (e) {
        // 解析失败：回退到纯文本
        const pre = document.createElement('pre');
        pre.className = 'eval-object';
        pre.textContent = jsonText;
        container.appendChild(pre);
        return container;
    }

    if (parsed === null) {
        container.textContent = 'null';
        return container;
    }
    if (typeof parsed !== 'object') {
        container.textContent = String(parsed);
        return container;
    }

    const root = document.createElement('div');
    root.className = 'tree-root';
    if (Array.isArray(parsed)) {
        appendArrayNode(root, parsed, 0, true);
    } else {
        appendObjectNode(root, parsed, 0, true);
    }
    container.appendChild(root);
    return container;
}

function appendObjectNode(parent, obj, depth, isRoot) {
    const keys = Object.keys(obj);
    const header = document.createElement('div');
    header.className = 'tree-node-header';
    header.style.paddingLeft = (depth * 16) + 'px';

    const arrow = document.createElement('span');
    arrow.className = 'tree-arrow-toggle';
    arrow.textContent = isRoot ? '▼' : '▶';
    header.appendChild(arrow);

    if (isRoot) {
        const brace = document.createElement('span');
        brace.className = 'tree-brace';
        brace.textContent = '{';
        header.appendChild(brace);

        const summary = document.createElement('span');
        summary.className = 'tree-summary';
        summary.textContent = ` ${keys.length} keys `;
        header.appendChild(summary);

        parent.appendChild(header);
    } else {
        parent.appendChild(header);
    }

    const children = document.createElement('div');
    children.className = 'tree-children';
    if (!isRoot) children.style.display = 'none';

    for (let i = 0; i < keys.length; i++) {
        const k = keys[i];
        const v = obj[k];
        const isLast = i === keys.length - 1;

        const item = document.createElement('div');
        item.className = 'tree-item';

        if (v !== null && typeof v === 'object') {
            appendObjectNode(item, v, depth + 1, false);
            // 改 header 的缩进与前缀
            item.querySelector('.tree-node-header').style.paddingLeft = ((depth + 1) * 16) + 'px';
        } else if (Array.isArray(v)) {
            appendArrayNode(item, v, depth + 1, false);
            item.querySelector('.tree-node-header').style.paddingLeft = ((depth + 1) * 16) + 'px';
        } else {
            const line = document.createElement('div');
            line.className = 'tree-leaf';
            line.style.paddingLeft = ((depth + 1) * 16) + 'px';
            const keySpan = document.createElement('span');
            keySpan.className = 'json-key';
            keySpan.textContent = JSON.stringify(k);
            line.appendChild(keySpan);
            line.appendChild(document.createTextNode(': '));
            line.appendChild(formatLeafNode(v));
            if (!isLast) line.appendChild(document.createTextNode(','));
            item.appendChild(line);
        }

        children.appendChild(item);
    }
    parent.appendChild(children);

    if (isRoot) {
        const close = document.createElement('div');
        close.className = 'tree-close';
        close.style.paddingLeft = (depth * 16) + 'px';
        const cb = document.createElement('span');
        cb.className = 'tree-brace';
        cb.textContent = '}';
        close.appendChild(cb);
        parent.appendChild(close);
    }

    // 折叠/展开
    header.addEventListener('click', (e) => {
        e.stopPropagation();
        const collapsed = children.style.display === 'none';
        children.style.display = collapsed ? 'block' : 'none';
        arrow.textContent = collapsed ? '▼' : '▶';
    });
}

function appendArrayNode(parent, arr, depth, isRoot) {
    const header = document.createElement('div');
    header.className = 'tree-node-header';
    header.style.paddingLeft = (depth * 16) + 'px';

    const arrow = document.createElement('span');
    arrow.className = 'tree-arrow-toggle';
    arrow.textContent = '▼';
    header.appendChild(arrow);

    if (isRoot) {
        const brace = document.createElement('span');
        brace.className = 'tree-brace';
        brace.textContent = '[';
        header.appendChild(brace);
        const summary = document.createElement('span');
        summary.className = 'tree-summary';
        summary.textContent = ` ${arr.length} items `;
        header.appendChild(summary);
        parent.appendChild(header);
    } else {
        parent.appendChild(header);
    }

    const children = document.createElement('div');
    children.className = 'tree-children';
    if (!isRoot) children.style.display = 'none';

    for (let i = 0; i < arr.length; i++) {
        const v = arr[i];
        const isLast = i === arr.length - 1;
        const item = document.createElement('div');
        item.className = 'tree-item';

        if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
            appendObjectNode(item, v, depth + 1, false);
            item.querySelector('.tree-node-header').style.paddingLeft = ((depth + 1) * 16) + 'px';
        } else if (Array.isArray(v)) {
            appendArrayNode(item, v, depth + 1, false);
            item.querySelector('.tree-node-header').style.paddingLeft = ((depth + 1) * 16) + 'px';
        } else {
            const line = document.createElement('div');
            line.className = 'tree-leaf';
            line.style.paddingLeft = ((depth + 1) * 16) + 'px';
            const idx = document.createElement('span');
            idx.className = 'json-key';
            idx.textContent = String(i);
            line.appendChild(idx);
            line.appendChild(document.createTextNode(': '));
            line.appendChild(formatLeafNode(v));
            if (!isLast) line.appendChild(document.createTextNode(','));
            item.appendChild(line);
        }
        children.appendChild(item);
    }
    parent.appendChild(children);

    if (isRoot) {
        const close = document.createElement('div');
        close.className = 'tree-close';
        close.style.paddingLeft = (depth * 16) + 'px';
        const cb = document.createElement('span');
        cb.className = 'tree-brace';
        cb.textContent = ']';
        close.appendChild(cb);
        parent.appendChild(close);
    }

    header.addEventListener('click', (e) => {
        e.stopPropagation();
        const collapsed = children.style.display === 'none';
        children.style.display = collapsed ? 'block' : 'none';
        arrow.textContent = collapsed ? '▼' : '▶';
    });
}

function formatLeafNode(v) {
    const span = document.createElement('span');
    if (v === null) {
        span.className = 'json-bool';
        span.textContent = 'null';
    } else if (typeof v === 'string') {
        span.className = 'json-string';
        span.textContent = JSON.stringify(v);
    } else if (typeof v === 'number') {
        span.className = 'json-number';
        span.textContent = String(v);
    } else if (typeof v === 'boolean') {
        span.className = 'json-bool';
        span.textContent = String(v);
    } else {
        span.textContent = String(v);
    }
    return span;
}

// ---- Status Display ----

function updateStatus(state) {
    const indicator = document.getElementById('status-indicator');
    indicator.className = state;
    indicator.textContent = state === 'connected' ? '● 已连接' : '● 未连接';
}

function updateGameStatus(connected, ts) {
    const status = document.getElementById('game-status');
    status.className = connected ? 'connected' : 'disconnected';
    status.textContent = connected ? `游戏: 已连接 (${ts})` : '游戏: 未连接';
}

// ---- Breakpoint / Pause handling (shared with sources) ----

function handleBreakpointHit(msg) {
    const pauseIndicator = document.getElementById('pause-indicator');
    const resumeBtn = document.getElementById('resume-btn');
    pauseIndicator.classList.remove('hidden');
    resumeBtn.classList.remove('hidden');

    // 在控制台显示暂停信息
    const output = document.getElementById('console-output');
    const div = document.createElement('div');
    div.className = 'console-entry console-warn';
    div.innerHTML = `<span class="log-icon">⏸</span>断点命中: ${msg.file}:${msg.line || msg.func} — ${msg.reason || ''}`;
    output.appendChild(div);
    output.scrollTop = output.scrollHeight;

    // 如果当前打开的是命中文件，高亮行
    highlightPausedLine(msg.file, msg.line || msg.func);
}

function handlePauseState(msg) {
    if (!msg.paused) {
        const pauseIndicator = document.getElementById('pause-indicator');
        const resumeBtn = document.getElementById('resume-btn');
        pauseIndicator.classList.add('hidden');
        resumeBtn.classList.add('hidden');
    }
}

function resumeExecution() {
    wsSend({ type: 'resume' });
    const pauseIndicator = document.getElementById('pause-indicator');
    const resumeBtn = document.getElementById('resume-btn');
    pauseIndicator.classList.add('hidden');
    resumeBtn.classList.add('hidden');
}

// ---- Theme system (synced with statisticServer) ----

const THEMES = ['red', 'default', 'kokomi', 'firefly', 'furina', 'hysilens', 'geniusclub', 'silverwolf'];
const THEME_NAMES = ['朱砂红', '简约配色', '珊瑚宫心海', '流萤·萨姆', '芙宁娜·歌剧院', '海瑟音·深境', '天才俱乐部', '狼尊 LV.999'];

const THEME_WALLPAPERS = {
    kokomi:     { img: '/style/kokomi/kokomi.png',       overlay: 'linear-gradient(135deg, rgba(225,240,255,.55), rgba(252,232,240,.55))' },
    firefly:    { img: '/style/firefly/firefly.png',      overlay: 'linear-gradient(135deg, rgba(229,243,241,.55), rgba(236,233,242,.55), rgba(245,235,240,.55))' },
    furina:     { img: '/style/furina/furina.png',        overlay: 'radial-gradient(circle 900px at top center, rgba(255,235,190,.15) 0%, rgba(255,250,230,.03) 50%, rgba(18,11,11,.7) 100%), linear-gradient(135deg, rgba(18,11,11,.45), rgba(18,11,11,.25))' },
    hysilens:   { img: '/style/Hysilens/Hysilens.jpg',    overlay: 'radial-gradient(ellipse 80% 35% at 50% 0%, rgba(112,195,252,.12) 0%, transparent 70%), radial-gradient(ellipse 40% 30% at 10% 100%, rgba(209,46,107,.10) 0%, transparent 70%), linear-gradient(135deg, rgba(14,24,38,.4), rgba(45,15,63,.3), rgba(21,42,66,.4))' },
    geniusclub: { img: '/style/geniusclub/geniusclub.png', overlay: 'radial-gradient(ellipse 70% 40% at 50% 0%, rgba(138,79,255,.08) 0%, transparent 70%), radial-gradient(ellipse 40% 25% at 80% 100%, rgba(229,193,123,.06) 0%, transparent 60%), linear-gradient(135deg, rgba(15,18,31,.5), rgba(34,18,48,.4))' },
    silverwolf: { img: '/style/silverwolf/silverwolf.png', overlay: 'linear-gradient(#070312, rgba(7,3,18,.4))' },
};

function getInfoServerUrl() {
    return 'http://' + (window.location.hostname || '127.0.0.1') + ':5001';
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme || '');
    const sel = document.getElementById('themeSelect');
    if (sel) sel.value = theme || '';

    // Set background image from infoServer (only for themed pages with wallpaper)
    const wp = THEME_WALLPAPERS[theme];
    if (wp) {
        const url = getInfoServerUrl() + wp.img;
        document.body.style.backgroundImage = wp.overlay + ', url(' + url + ')';
        document.body.style.backgroundSize = 'cover';
        document.body.style.backgroundAttachment = 'fixed';
    } else {
        document.body.style.backgroundImage = 'none';
        document.body.style.backgroundSize = '';
        document.body.style.backgroundAttachment = '';
    }
}

async function syncThemeToServer(theme) {
    try {
        await fetch(getInfoServerUrl() + '/api/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: theme || '' })
        });
    } catch (_) { /* infoServer offline, local-only */ }
}

async function setTheme(theme) {
    applyTheme(theme);
    localStorage.setItem('debug_theme', theme || '');
    await syncThemeToServer(theme);
}

async function restoreTheme() {
    // Try infoServer first
    try {
        const r = await fetch(getInfoServerUrl() + '/api/theme');
        const data = await r.json();
        if (data.theme && THEMES.includes(data.theme)) {
            applyTheme(data.theme);
            localStorage.setItem('debug_theme', data.theme);
            return;
        }
    } catch (_) { /* infoServer unreachable, use local */ }

    // Fallback to localStorage
    const saved = localStorage.getItem('debug_theme');
    if (saved && THEMES.includes(saved)) {
        applyTheme(saved);
    } else {
        applyTheme('');  // default dark theme
    }
}

// Theme selector event
document.addEventListener('DOMContentLoaded', () => {
    const sel = document.getElementById('themeSelect');
    if (sel) {
        sel.addEventListener('change', () => setTheme(sel.value));
    }
    restoreTheme();
    restoreActiveTab();
});

// ---- Init ----

wsConnect();