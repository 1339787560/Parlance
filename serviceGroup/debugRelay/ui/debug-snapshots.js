/**
 * Snapshots 面板逻辑
 * - 立即快照: POST /api/snapshot 切片当前选中客户端的 console_buffer + perf_buffer 落档
 *   → 单文件 JSON + summary.md, 给 AI agent 一次性 Read 推断性能瓶颈
 * - 列表: GET /api/snapshots 查所有快照 (倒序)
 * - 详情: GET /api/snapshot/{id}?format=summary 取 markdown 摘要弹窗显示
 * - 复制路径: 一键复制 JSON 路径给 AI
 *
 * selectedClient / switchTab 由 debug-console.js 提供 (本脚本在其后加载)。
 */

let snapshotsCache = [];

function snapshotsSetStatus(text, isError) {
    const el = document.getElementById('snapshots-status');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = isError ? 'var(--red)' : 'var(--dim)';
}

/** 立即快照: 对当前选中客户端切片 console+perf 落档 */
async function snapCapture() {
    if (!selectedClient) {
        snapshotsSetStatus('未选中客户端', true);
        alert('请先在工具栏选择一个客户端再打快照');
        return;
    }
    const noteInput = document.getElementById('snapshots-note');
    const note = (noteInput && noteInput.value || '').trim();
    const btn = document.getElementById('snapshot-btn');
    const btnLabel = btn ? btn.textContent : '📸 快照';
    if (btn) { btn.disabled = true; btn.textContent = '📸 ...'; }

    snapshotsSetStatus('落档中...');
    try {
        const resp = await fetch('/api/snapshot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                client_id: selectedClient,
                note: note,
                console_tail: 500,
                perf_tail: 300,
            }),
        });
        const data = await resp.json();
        if (!resp.ok || !data.ok) {
            snapshotsSetStatus('落档失败: ' + (data.error || resp.status), true);
            return;
        }
        const ps = data.perf_summary || {};
        const fpsAvg = (ps.fps || {}).avg;
        const hot = ps.hot_frames_count;
        const jsonPath = String(data.json_path || '').replace(/\\/g, '/');

        // 自动复制 JSON 路径到剪贴板, 方便贴给 AI
        let copied = false;
        try {
            await navigator.clipboard.writeText(jsonPath);
            copied = true;
        } catch { /* 剪贴板权限拒绝, 不阻断 */ }
        snapshotsSetStatus(
            `已落档: fps_avg=${fpsAvg} hot=${hot} (${data.perf_tail_count}s)` +
            (copied ? '  ✋路径已复制' : '')
        );
        console.log('[snap] persisted:', data.snapshot_id, jsonPath);
        if (noteInput) noteInput.value = '';
        await snapRefresh();
    } catch (e) {
        snapshotsSetStatus('落档失败: ' + e.message, true);
        console.error('[snap] capture failed:', e);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = btnLabel; }
    }
}

/** 刷新快照列表 */
async function snapRefresh() {
    snapshotsSetStatus('加载列表...');
    try {
        const resp = await fetch('/api/snapshots?limit=50');
        const data = await resp.json();
        snapshotsCache = data.snapshots || [];
        snapRender(snapshotsCache);
        snapshotsSetStatus('');
    } catch (e) {
        snapshotsSetStatus('加载失败: ' + e.message, true);
        console.error('[snap] refresh failed:', e);
    }
}

/** 查看 AI 摘要 markdown (新窗口) */
async function snapViewSummary(id) {
    try {
        const resp = await fetch(`/api/snapshot/${encodeURIComponent(id)}?format=summary`);
        const data = await resp.json();
        if (!data.ok) { alert('读取失败: ' + (data.error || '')); return; }
        const w = window.open('', '_blank');
        if (!w) { alert('弹窗被拦截, 请允许'); return; }
        w.document.write(
            '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Snapshot ' +
            snapEscHtml(id) + '</title>' +
            '<style>body{margin:0;padding:16px;font-family:Consolas,"Microsoft YaHei",monospace;' +
            'background:#1e1e1e;color:#d4d4d4;}pre{white-space:pre-wrap;word-wrap:break-word;' +
            'font-family:inherit;}</style></head><body><pre>' +
            snapEscHtml(data.summary_md || '(无摘要)') + '</pre></body></html>'
        );
        w.document.close();
    } catch (e) {
        alert('读取失败: ' + e.message);
    }
}

/** 复制 JSON 路径到剪贴板 */
async function snapCopyPath(path) {
    const p = String(path).replace(/\\/g, '/');
    try {
        await navigator.clipboard.writeText(p);
        snapshotsSetStatus('路径已复制: ' + p);
    } catch {
        snapshotsSetStatus('剪贴板失败, 手动复制: ' + p);
    }
}

/** 复制完整 JSON 内容到剪贴板 (AI 直接吃) */
async function snapCopyJson(id) {
    try {
        const resp = await fetch(`/api/snapshot/${encodeURIComponent(id)}?format=full`);
        const data = await resp.json();
        if (!data.ok) { snapshotsSetStatus('读取失败: ' + (data.error || ''), true); return; }
        const text = JSON.stringify(data.data);
        try {
            await navigator.clipboard.writeText(text);
            snapshotsSetStatus(`JSON 已复制 (${(text.length / 1024).toFixed(1)} KB)`);
        } catch {
            snapshotsSetStatus('剪贴板失败, JSON 太大请直接 Read 文件', true);
        }
    } catch (e) {
        snapshotsSetStatus('读取失败: ' + e.message, true);
    }
}

// ---- Render ----

function snapRender(snapshots) {
    const output = document.getElementById('snapshots-output');
    const countEl = document.getElementById('snapshots-count');
    if (!snapshots || snapshots.length === 0) {
        output.innerHTML =
            '<div class="events-empty">暂无快照。点工具栏 "📸 快照" 对当前选中客户端打一份 Console+Perf 快照 ' +
            '(落档后给 AI Read 推断瓶颈)。</div>';
        countEl.textContent = '';
        return;
    }
    countEl.textContent = `${snapshots.length} 份`;
    let html = '<table class="events-table"><thead><tr>' +
        '<th>快照时间</th><th>客户端</th><th>备注</th><th>fps_avg</th>' +
        '<th>hot</th><th>window</th><th>动作</th>' +
        '</tr></thead><tbody>';
    snapshots.forEach(s => {
        const ts = s.click_ts ? s.click_ts.replace('T', ' ').slice(0, 19) : '-';
        const id = s.snapshot_id || '';
        const path = s.json_path || '';
        const fpsAvg = (s.fps_avg !== null && s.fps_avg !== undefined) ? s.fps_avg : '-';
        html += `<tr>
            <td class="events-ts">${snapEscHtml(ts)}</td>
            <td>${snapEscHtml(s.client_label || s.client_id || '-')}</td>
            <td>${snapEscHtml(s.note || '')}</td>
            <td>${fpsAvg}</td>
            <td>${s.hot_frames_count || 0}</td>
            <td>${s.perf_tail_count || 0}s</td>
            <td class="events-action" style="white-space:nowrap;">
                <button class="events-del-btn" onclick="snapViewSummary('${snapEscAttr(id)}')" title="查看 AI 摘要 (markdown)">📄</button>
                <button class="events-del-btn" onclick="snapCopyPath('${snapEscAttr(path)}')" title="复制 JSON 文件路径给 AI Read">📋路径</button>
                <button class="events-del-btn" onclick="snapCopyJson('${snapEscAttr(id)}')" title="复制完整 JSON 内容 (大文件慎用)">📋JSON</button>
            </td>
        </tr>`;
    });
    html += '</tbody></table>';
    html += '<div class="events-empty" style="margin-top:12px;">' +
        '<b>给 AI 用法</b>: 点 📋路径 复制 JSON 路径 → 在 Claude/agent 里说 "Read 这个文件分析性能瓶颈" 即可。' +
        '文件含 console_tail (500) + perf_tail (300) + perf_summary + hot_frames + AI hints。' +
        '</div>';
    output.innerHTML = html;
}

function snapEscHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function snapEscAttr(s) {
    return String(s).replace(/'/g, "\\'").replace(/\\/g, '\\\\');
}

// 页面加载后自动拉一次列表 (无依赖 selectedClient)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(snapRefresh, 200));
} else {
    setTimeout(snapRefresh, 200);
}
