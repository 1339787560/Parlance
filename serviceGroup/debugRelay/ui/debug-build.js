// debug-build.js — Build/编译状态 tab
// 轮询 /api/build/progress，展示 packer-driver 产物进度 + 编译日志关键行。
// 提供 增量 Reload / 全量 Rebuild / Restart Preview 操作按钮（异步触发）。
(function () {
    let prevPreviewFiles = null;
    let timer = null;

    function $(id) { return document.getElementById(id); }

    function setText(id, text) {
        const el = $(id);
        if (el) el.textContent = text;
    }

    function render(data) {
        if (!data || !data.ok) {
            setText('build-state', '不可用');
            setText('build-log', (data && data.error) || '未获取到状态');
            return;
        }
        const t = data.targets || {};
        setText('build-editor-files', String(t.editor_files ?? '-'));
        setText('build-editor-import', t.editor_import_map ? '✅' : '❌');
        setText('build-preview-files', String(t.preview_files ?? '-'));
        setText('build-preview-import', t.preview_import_map ? '✅' : '❌');

        const previewFiles = t.preview_files || 0;
        let stateText;
        const stateEl = $('build-state');
        stateEl.className = 'build-stat-value';
        if (data.building) {
            stateText = '🔄 重建中';
            stateEl.classList.add('state-building');
        } else if (t.preview_import_map) {
            stateText = '✅ 就绪';
            stateEl.classList.add('state-ok');
        } else {
            stateText = '⏳ 等待构建';
            stateEl.classList.add('state-wait');
        }
        if (prevPreviewFiles !== null && previewFiles !== prevPreviewFiles) {
            const delta = previewFiles - prevPreviewFiles;
            stateText += ` (preview 文件 ${delta > 0 ? '+' : ''}${delta})`;
        }
        prevPreviewFiles = previewFiles;
        setText('build-state', stateText);

        const log = (data.log_tail || []).join('\n') || '(无关键编译日志)';
        setText('build-log', log);
        setText('build-status', `项目: ${data.project}`);
    }

    async function refresh() {
        try {
            const resp = await fetch('/api/build/progress');
            const data = await resp.json();
            render(data);
        } catch (e) {
            setText('build-state', '请求失败');
            setText('build-log', String(e));
        }
    }

    async function buildAction(action) {
        const btn = $('build-' + (action === 'incremental' ? 'incremental' : action === 'full' ? 'full' : 'restart'));
        if (btn) btn.disabled = true;
        setText('build-action-result', '⏳ 已触发，等待执行...');
        try {
            const resp = await fetch('/api/build/action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action })
            });
            const data = await resp.json();
            if (data.ok) {
                setText('build-action-result', `✅ 已启动 ${action}`);
            } else {
                setText('build-action-result', `❌ ${data.error || '启动失败'}`);
            }
        } catch (e) {
            setText('build-action-result', `❌ ${e}`);
        } finally {
            if (btn) btn.disabled = false;
            // 触发后立刻刷新一次，稍后轮询会持续跟进
            setTimeout(refresh, 500);
        }
    }

    window.buildRefresh = refresh;
    window.buildAction = buildAction;

    if (!timer) {
        timer = setInterval(refresh, 2000);
        refresh();
    }
})();
