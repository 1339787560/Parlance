/**
 * Leak 面板 - 泄漏探针可视化 (川麻 3 局发烫根因度量, 2026-07-20)
 *
 * 数据来源: perf_snapshot.leak (PerfBridge 1Hz 推, 客户端 LeakProbe 采样).
 * 由 debug-perf.js handlePerfSnapshot → window.handleLeakSample(snap) 调用,
 * 复用 perf 1Hz 频率, 不另起 WS 通道.
 *
 * 8 个字段对应调查报告 5 嫌疑点 + 通用场景节点数:
 *   #1 result_ani_listeners_{win,fail}  局末应归 0 (ResultManager.ts:163,181)
 *   #2 socket_{send,recv}_pipe_handlers 重连应不涨 (GamePlugin.ts:500,524,702,705)
 *   #3 res_cache_total_refs             一次性常量 ~40+ (GameResCache.ts)
 *   #4 trigger_map_size                 局末归 0 (GameInfo._curTriggerFunc)
 *   #4 third_info_map_size              离桌归 0 (GameInfo._userID2ThirdInfo)
 *   通用 total_scene_node_count         局间稳定
 *
 * 颜色: 红=超警戒 / 黄=非零应归 0 / 灰=正常; 峰值=本次订阅会话最高.
 */

// 字段配置: warn=警戒阈值 (9999 表示无警戒, 仅显示)
const LEAK_FIELDS = [
    { key: 'result_ani_listeners_win',  label: 'Result Ani · Win',    expect: '局末归 0',  warn: 4 },
    { key: 'result_ani_listeners_fail', label: 'Result Ani · Fail',   expect: '局末归 0',  warn: 4 },
    { key: 'socket_send_pipe_handlers', label: 'Socket Send Pipe',    expect: '重连不涨',  warn: 2 },
    { key: 'socket_recv_pipe_handlers', label: 'Socket Recv Pipe',    expect: '重连不涨',  warn: 2 },
    { key: 'res_cache_total_refs',      label: 'ResCache addRefs',    expect: '常量 ~40+', warn: 100 },
    { key: 'trigger_map_size',          label: 'Trigger Map',         expect: '局末归 0',  warn: 10 },
    { key: 'third_info_map_size',       label: 'Third Info Map',      expect: '离桌归 0',  warn: 16 },
    { key: 'total_scene_node_count',    label: 'Scene Nodes',         expect: '局间稳定',  warn: 9999 },
];

// 会话级峰值 (首次采到当前, 切客户端 resetLeakPanel 重置)
const leakPeaks = {};
LEAK_FIELDS.forEach(f => leakPeaks[f.key] = -1);

/** 初始化卡片 DOM (幂等, 重复调用安全) */
function initLeakPanel() {
    const cards = document.getElementById('leak-cards');
    if (!cards || cards.childElementCount > 0) return;
    for (const f of LEAK_FIELDS) {
        const card = document.createElement('div');
        card.className = 'perf-card leak-card';
        card.innerHTML = `
            <div class="perf-label">${f.label}</div>
            <div class="perf-value" id="leak-${f.key}">-</div>
            <div class="perf-sub">${f.expect}</div>
            <div class="perf-peak" id="leak-${f.key}-peak">峰值 -</div>
        `;
        cards.appendChild(card);
    }
}

/** 处理 perf_snapshot.leak, 更新卡片 + 峰值. 由 debug-perf.js handlePerfSnapshot 调用 */
function handleLeakSample(snap) {
    const leak = snap && snap.leak;
    if (!leak) return;
    initLeakPanel();
    for (const f of LEAK_FIELDS) {
        const v = leak[f.key];
        if (typeof v !== 'number' || v < 0) continue;

        // 峰值
        if (v > leakPeaks[f.key]) leakPeaks[f.key] = v;

        // 当前值 + 颜色
        const el = document.getElementById(`leak-${f.key}`);
        if (el) {
            el.textContent = v;
            if (f.warn < 9999 && v > f.warn) el.style.color = '#ff4757';        // 红: 超警戒
            else if (f.warn < 9999 && v > 0) el.style.color = '#ffa502';       // 黄: 非零应归 0
            else el.style.color = '';                                          // 灰: 正常
        }

        // 峰值显示
        const peakEl = document.getElementById(`leak-${f.key}-peak`);
        if (peakEl && leakPeaks[f.key] >= 0) {
            peakEl.textContent = `峰值 ${leakPeaks[f.key]}`;
        }
    }
}

/** 切换客户端时重置 (与 resetPerfPanel/resetScenePanel 同模式, 由 resetAllPanels 调用) */
function resetLeakPanel() {
    LEAK_FIELDS.forEach(f => leakPeaks[f.key] = -1);
    initLeakPanel();
    for (const f of LEAK_FIELDS) {
        const el = document.getElementById(`leak-${f.key}`);
        const peakEl = document.getElementById(`leak-${f.key}-peak`);
        if (el) { el.textContent = '-'; el.style.color = ''; }
        if (peakEl) peakEl.textContent = '峰值 -';
    }
}

window.handleLeakSample = handleLeakSample;
window.resetLeakPanel = resetLeakPanel;

document.addEventListener('DOMContentLoaded', initLeakPanel);
