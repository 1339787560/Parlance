/**
 * Events 面板逻辑
 * - 从 /api/events 查询按日归档的重要事件
 * - 实时接收 WS 推送的 important_event 消息（由 debug-console.js handleBrowserMessage 路由）
 * - 按分类/日期筛选
 */

// ---- State ----
let eventsCache = [];       // 当前显示的事件列表
let eventsCategories = [];  // 可用分类列表
let eventsDateList = [];    // 当前分类的可用日期列表

function eventsSetStatus(text, isError) {
    const el = document.getElementById('events-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--dim)';
}

// ---- API Calls ----

async function eventsLoadCategories() {
    eventsSetStatus('加载分类...');
    try {
        const resp = await fetch('/api/events/dates');
        if (!resp.ok) {
            eventsSetStatus('API错误: ' + resp.status, true);
            console.error('[events] API error:', resp.status, resp.statusText);
            return;
        }
        const data = await resp.json();
        eventsCategories = data.categories || [];
        console.log('[events] categories loaded:', eventsCategories);

        const sel = document.getElementById('events-category');
        sel.innerHTML = '<option value="">全部分类</option>';
        eventsCategories.forEach(cat => {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            sel.appendChild(opt);
        });

        // 默认选中第一个分类并手动触发加载
        if (eventsCategories.length > 0) {
            sel.value = eventsCategories[0];
            await eventsLoadDates();
        } else {
            eventsSetStatus('暂无分类');
        }
    } catch(e) {
        eventsSetStatus('加载失败: ' + e.message, true);
        console.error('[events] load categories failed:', e);
    }
}

async function eventsLoadDates() {
    const category = document.getElementById('events-category').value;
    eventsSetStatus('加载日期...');
    try {
        const url = category
            ? `/api/events/dates?category=${encodeURIComponent(category)}`
            : '/api/events/dates';
        const resp = await fetch(url);
        const data = await resp.json();

        eventsDateList = data.dates || [];
        console.log('[events] dates loaded:', eventsDateList.length);

        const sel = document.getElementById('events-date');
        sel.innerHTML = '';
        eventsDateList.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.date;
            opt.textContent = `${d.date} (${d.category})`;
            sel.appendChild(opt);
        });

        // 默认选最近一天并手动触发加载
        if (eventsDateList.length > 0) {
            sel.value = eventsDateList[0].date;
            await eventsLoadData();
        } else {
            eventsRender([]);
            eventsSetStatus('该分类暂无日期');
        }
    } catch(e) {
        eventsSetStatus('加载失败: ' + e.message, true);
        console.error('[events] load dates failed:', e);
    }
}

async function eventsLoadData() {
    const category = document.getElementById('events-category').value;
    const date = document.getElementById('events-date').value;
    if (!date) { eventsRender([]); return; }

    eventsSetStatus('加载数据...');
    try {
        let url = `/api/events?date=${encodeURIComponent(date)}&limit=200`;
        if (category) url += `&category=${encodeURIComponent(category)}`;
        console.log('[events] fetching:', url);
        const resp = await fetch(url);
        if (!resp.ok) {
            eventsSetStatus('API错误: ' + resp.status, true);
            console.error('[events] API error:', resp.status);
            return;
        }
        const data = await resp.json();
        console.log('[events] loaded:', data.count, 'events');
        eventsCache = data.events || [];
        eventsRender(eventsCache);
    } catch(e) {
        eventsSetStatus('加载失败: ' + e.message, true);
        console.error('[events] load data failed:', e);
    }
}

function eventsRefresh() {
    eventsLoadData();
}

function eventsPrevDay() {
    const sel = document.getElementById('events-date');
    const idx = Array.from(sel.options).findIndex(o => o.value === sel.value);
    if (idx < sel.options.length - 1) {
        sel.value = sel.options[idx + 1].value;
        eventsLoadData();
    }
}

function eventsNextDay() {
    const sel = document.getElementById('events-date');
    const idx = Array.from(sel.options).findIndex(o => o.value === sel.value);
    if (idx > 0) {
        sel.value = sel.options[idx - 1].value;
        eventsLoadData();
    }
}

// ---- Realtime Event ----

function onRealtimeEvent(msg) {
    // 多客户端：仅显示当前订阅客户端的实时事件（历史归档全局共享，不受此限）
    if (msg.client_id !== undefined && msg.client_id !== null && msg.client_id !== selectedClient) {
        return;
    }
    // 如果当前查看的是今天的日期，实时追加
    const selDate = document.getElementById('events-date').value;
    const today = new Date().toISOString().slice(0, 10);

    if (!selDate || selDate === today) {
        eventsCache.push(msg);
        eventsRender(eventsCache);
    }
}

// ---- Render ----

function eventsRender(events) {
    const output = document.getElementById('events-output');
    const countEl = document.getElementById('events-count');

    if (!events || events.length === 0) {
        output.innerHTML = '<div class="events-empty">暂无事件数据</div>';
        countEl.textContent = '';
        return;
    }

    countEl.textContent = `${events.length} 条`;
    eventsSetStatus('');

    // 按时间倒序
    const sorted = [...events].reverse();

    let html = '<table class="events-table"><thead><tr>' +
        '<th>时间</th><th>分类</th><th>事件</th><th>数据</th><th></th>' +
        '</tr></thead><tbody>';

    sorted.forEach(ev => {
        const ts = ev.ts ? ev.ts.replace('T', ' ').slice(0, 19) : '-';
        const category = ev.category || '-';
        const name = ev.name || '-';
        let dataStr = '-';
        if (ev.data) {
            try {
                dataStr = JSON.stringify(ev.data, null, 2);
            } catch(e) {
                dataStr = String(ev.data);
            }
        }
        const idx = ev._idx;
        const cat = ev._category || category;
        const delBtn = (idx !== undefined)
            ? `<button class="events-del-btn" onclick="eventsDelete('${escAttr(cat)}','${escAttr(ev._date || document.getElementById('events-date').value)}',${idx},this)">✕</button>`
            : '';

        html += `<tr>
            <td class="events-ts">${escHtml(ts)}</td>
            <td class="events-cat">${escHtml(category)}</td>
            <td class="events-name">${escHtml(name)}</td>
            <td class="events-data"><pre>${escHtml(dataStr)}</pre></td>
            <td class="events-action">${delBtn}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    output.innerHTML = html;
}

async function eventsDelete(category, date, index, btn) {
    if (!confirm(`确定删除第 ${index + 1} 条记录？`)) return;

    if (btn) { btn.disabled = true; btn.textContent = '...'; }
    eventsSetStatus('删除中...');

    try {
        const resp = await fetch(
            `/api/events?category=${encodeURIComponent(category)}&date=${encodeURIComponent(date)}&index=${index}`,
            { method: 'DELETE' }
        );
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            eventsSetStatus('删除失败: ' + (err.error || resp.status), true);
            if (btn) { btn.disabled = false; btn.textContent = '✕'; }
            return;
        }
        const data = await resp.json();
        console.log('[events] deleted, remaining:', data.remaining);
        eventsSetStatus('已删除');
        await eventsLoadData();
    } catch(e) {
        eventsSetStatus('删除失败: ' + e.message, true);
        if (btn) { btn.disabled = false; btn.textContent = '✕'; }
    }
}

function escAttr(s) {
    return String(s).replace(/'/g, "\\'");
}

function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
