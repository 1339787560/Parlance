// 编辑态装饰决策: (结构范围 + 编辑状态) → 装饰计划 / 删除决策。
//
// 纯函数, 零 DOM 零 CM6 依赖 → Node 可直测 (见 test/edit-decorations.test.mjs);
// app.js 只做薄适配 (Decoration / ViewPlugin / WidgetType / keymap), 决策逻辑全在这里。
//
// 保真红线: 本模块只产出"要装饰哪段"与"这次退格该不该拦", 永不改写文档文本。

/** 归一化 revealed (Set<number> | number[] | null) → 可直接查的 Set */
function asSet(revealed) {
  if (revealed instanceof Set) return revealed;
  if (Array.isArray(revealed)) return new Set(revealed);
  return new Set();
}

/**
 * mermaid 块投影计划: 未被"揭示为源码"的块 → 整块替换为渲染图。
 * 返回 [{ from, to, src }], 区间就是扫描器给的原文档坐标 (切片回 doc 即原始围栏)。
 * @param {{from:number,to:number,src:string}[]} blocks scanMermaidBlocks 的结果
 * @param {Set<number>|number[]} revealed 已揭示块的首偏移集合
 */
export function planMermaidProjection(blocks, revealed) {
  const open = asSet(revealed);
  const out = [];
  for (const b of blocks || []) {
    if (!b) continue;
    if (open.has(b.from)) continue;          // 已揭示: 该块保留源码, 不投影
    out.push({ from: b.from, to: b.to, src: b.src });
  }
  return out;
}

/**
 * 原子块边界的删除决策 (防"一次退格整块消失")。
 *
 * - 'reveal': 首次贴边删除 → 只把该块揭示为源码, 这次删除被吃掉 (调用方 return true)
 * - 'delete': 该块已揭示 → 放行, 走正常删除
 * - 'pass'  : 不贴边 / 方向不匹配 / 入参不对 → 交给默认行为
 *
 * 注: 有选区的情况由调用方拦截 (跨块选区要连续, 不能被这里吃掉)。
 * @param {number} pos 光标位置
 * @param {-1|1} dir -1=退格(看块首) / 1=删除键(看块尾)
 */
export function decideAtomicDelete(blocks, pos, dir, revealed) {
  const pass = { action: 'pass', block: null };
  if (dir !== -1 && dir !== 1) return pass;
  if (typeof pos !== 'number') return pass;
  const open = asSet(revealed);
  for (const b of blocks || []) {
    if (!b) continue;
    const atEdge = dir < 0 ? b.from === pos : b.to === pos;
    if (!atEdge) continue;
    return { action: open.has(b.from) ? 'delete' : 'reveal', block: b };
  }
  return pass;
}

/**
 * 揭示态收束: 只保留光标所在块, 其余合上投影 (回到渲染图)。
 * 光标不在任何块内 / 失焦 (cursorPos 非数字) → 清空 (全部合上)。
 * 返回新 Set, 不改入参。
 */
export function pruneRevealed(blocks, revealed, cursorPos) {
  const open = asSet(revealed);
  const next = new Set();
  if (typeof cursorPos !== 'number') return next;
  for (const b of blocks || []) {
    if (!b) continue;
    if (!open.has(b.from)) continue;
    if (cursorPos >= b.from && cursorPos <= b.to) next.add(b.from);
  }
  return next;
}
