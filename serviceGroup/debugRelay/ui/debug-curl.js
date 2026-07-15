// debug-curl.js - HTTP 连通性测试工具（服务端 /api/curl 代理，绕 CORS）
(function () {
'use strict';

function $(id) { return document.getElementById(id); }
function escapeHtml(s) { return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

function parseHeaders(text) {
    const out = {};
    (text || '').split('\n').forEach(line => {
        const i = line.indexOf(':');
        if (i > 0) {
            const k = line.slice(0, i).trim();
            const v = line.slice(i + 1).trim();
            if (k) out[k] = v;
        }
    });
    return out;
}

function statusColor(code) {
    if (code >= 200 && code < 300) return '#22c55e';
    if (code >= 300 && code < 400) return '#3b82f6';
    if (code >= 400 && code < 500) return '#eab308';
    if (code >= 500) return '#ef4444';
    return '#8b949e';
}

async function curlSend() {
    const url = ($('curl-url') || {}).value || '';
    const u = url.trim();
    if (!u) { curlShow('请输入 URL', true); return; }
    const method = ($('curl-method') || {}).value || 'GET';
    const headers = parseHeaders(($('curl-headers') || {}).value || '');
    const body = ($('curl-body') || {}).value || '';
    const out = $('curl-response');
    if (out) out.innerHTML = '<div class="curl-loading">请求中...</div>';
    const btn = $('curl-send-btn'); if (btn) btn.disabled = true;
    try {
        const r = await fetch('/api/curl', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: u, method, headers, body }),
        });
        const data = await r.json();
        renderCurlResponse(data, u);
    } catch (e) {
        curlShow('请求失败: ' + e.message, true);
    } finally {
        if (btn) btn.disabled = false;
    }
}
window.curlSend = curlSend;

function curlShow(msg, isErr) {
    const out = $('curl-response');
    if (out) out.innerHTML = '<div class="curl-' + (isErr ? 'error' : 'empty') + '">' + escapeHtml(msg) + '</div>';
}

function renderCurlResponse(d, reqUrl) {
    const out = $('curl-response');
    if (!out) return;
    if (d.error) {
        out.innerHTML = '<div class="curl-error">✗ ' + escapeHtml(d.error) + (d.elapsed_ms != null ? ' (' + d.elapsed_ms + ' ms)' : '') + '</div>';
        return;
    }
    const sc = statusColor(d.status || 0);
    const hdrText = Object.entries(d.headers || {}).map(([k, v]) => escapeHtml(k) + ': ' + escapeHtml(v)).join('\n');
    const truncated = d.body_truncated ? ' <span class="curl-trunc">(截断 200KB)</span>' : '';
    const finalUrl = (d.final_url && d.final_url !== reqUrl) ? '<div class="curl-final">最终 URL: ' + escapeHtml(d.final_url) + '</div>' : '';
    out.innerHTML =
        '<div class="curl-res-meta">'
        + '<span class="curl-status" style="background:' + sc + '">' + escapeHtml(d.status || '?') + '</span>'
        + '<span class="curl-reason">' + escapeHtml(d.reason || '') + '</span>'
        + '<span class="curl-elapsed">' + (d.elapsed_ms != null ? d.elapsed_ms + ' ms' : '') + '</span>'
        + '<span class="curl-ctype">' + escapeHtml(d.content_type || '') + '</span>'
        + '</div>'
        + finalUrl
        + '<div class="curl-section">Response Headers</div><pre class="curl-headers">' + (hdrText || '(无)') + '</pre>'
        + '<div class="curl-section">Response Body' + truncated + '</div><pre class="curl-body">' + escapeHtml(d.body || '') + '</pre>';
}

})();
