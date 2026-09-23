// 编辑态装饰决策的纯逻辑单测 (node --test)
// edit-decorations.mjs = (结构范围 + 编辑状态) → 装饰计划 / 删除决策。
// 纯函数, 无 DOM 无 CM6 → 可在 Node 直测; app.js 只做薄适配 (ViewPlugin / Widget / keymap)。
//
// 契约来源: 测试用例文档「操作稳定」组 + tech_discuss「原子范围坑点」
//   - 退格误删: 默认退格整体删除原子范围, 首次进源码态, 再次才删
//   - 跨块选区: 有选区时不拦 (交给默认删除, 选区连续)

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { scanMermaidBlocks } from '../static/editor/md-blocks.mjs';
import {
  planMermaidProjection,
  decideAtomicDelete,
  pruneRevealed,
} from '../static/editor/edit-decorations.mjs';

const DOC2 = [
  '前文',
  '',
  '```mermaid',
  'graph TD; A-->B;',
  '```',
  '',
  '中间',
  '',
  '```mermaid',
  'graph LR; C-->D;',
  '```',
  '',
  '后文',
  '',
].join('\n');

// ============== 投影计划 ==============

test('planMermaidProjection: 未揭示时全部投影, 位置与源码与扫描一致', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const plan = planMermaidProjection(blocks, new Set());
  assert.equal(plan.length, 2);
  assert.equal(plan[0].from, blocks[0].from);
  assert.equal(plan[0].to, blocks[0].to);
  assert.equal(plan[0].src, blocks[0].src);
  assert.equal(plan[1].src, 'graph LR; C-->D;');
});

test('planMermaidProjection: 已揭示的块不投影, 其余仍投影', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const plan = planMermaidProjection(blocks, new Set([blocks[0].from]));
  assert.equal(plan.length, 1);
  assert.equal(plan[0].from, blocks[1].from);
});

test('planMermaidProjection: 全部揭示 → 空计划 (等价源码编辑器)', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const all = new Set(blocks.map(b => b.from));
  assert.deepEqual(planMermaidProjection(blocks, all), []);
});

test('planMermaidProjection: 无块 / 入参缺失都返空, 不抛', () => {
  assert.deepEqual(planMermaidProjection([], new Set()), []);
  assert.deepEqual(planMermaidProjection(null, new Set()), []);
  const blocks = scanMermaidBlocks(DOC2);
  assert.equal(planMermaidProjection(blocks).length, 2);      // revealed 缺省 = 全投影
  assert.equal(planMermaidProjection(blocks, null).length, 2);
});

test('planMermaidProjection: 投影区间互不重叠 (CM6 重叠 replace 会抛)', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const plan = planMermaidProjection(blocks, new Set());
  for (let i = 1; i < plan.length; i++) {
    assert.ok(plan[i - 1].to <= plan[i].from, '投影区间重叠');
  }
});

// ============== 原子范围删除决策 ==============

test('decideAtomicDelete: 块首退格未揭示 → 先揭示源码, 不删', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const r = decideAtomicDelete(blocks, blocks[0].from, -1, new Set());
  assert.equal(r.action, 'reveal');
  assert.equal(r.block.from, blocks[0].from);
});

test('decideAtomicDelete: 块首退格但已揭示 → 放行真删', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const revealed = new Set([blocks[0].from]);
  const r = decideAtomicDelete(blocks, blocks[0].from, -1, revealed);
  assert.equal(r.action, 'delete');
});

test('decideAtomicDelete: 块尾按删除键未揭示 → 先揭示, 不误删整图', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const r = decideAtomicDelete(blocks, blocks[0].to, 1, new Set());
  assert.equal(r.action, 'reveal');
  assert.equal(r.block.from, blocks[0].from);
});

test('decideAtomicDelete: 块尾按删除键且已揭示 → 放行真删', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const revealed = new Set([blocks[0].from]);
  assert.equal(decideAtomicDelete(blocks, blocks[0].to, 1, revealed).action, 'delete');
});

test('decideAtomicDelete: 不贴块边 → pass (走默认删除)', () => {
  const blocks = scanMermaidBlocks(DOC2);
  assert.equal(decideAtomicDelete(blocks, 0, -1, new Set()).action, 'pass');
  assert.equal(decideAtomicDelete(blocks, blocks[0].from + 3, -1, new Set()).action, 'pass');
  // 方向与边不匹配: 块首按删除键 / 块尾按退格 都不该命中
  assert.equal(decideAtomicDelete(blocks, blocks[0].from, 1, new Set()).action, 'pass');
  assert.equal(decideAtomicDelete(blocks, blocks[0].to, -1, new Set()).action, 'pass');
});

test('decideAtomicDelete: 空块表 / 方向非法 → pass', () => {
  assert.equal(decideAtomicDelete([], 0, -1, new Set()).action, 'pass');
  const blocks = scanMermaidBlocks(DOC2);
  assert.equal(decideAtomicDelete(blocks, blocks[0].from, 0, new Set()).action, 'pass');
});

test('decideAtomicDelete: 只认最近的边 (两块相邻时命中各自)', () => {
  const blocks = scanMermaidBlocks(DOC2);
  assert.equal(decideAtomicDelete(blocks, blocks[1].from, -1, new Set()).block.from, blocks[1].from);
  assert.equal(decideAtomicDelete(blocks, blocks[1].to, 1, new Set()).block.from, blocks[1].from);
});

// ============== 揭示态收束 ==============

test('pruneRevealed: 光标仍在块内 → 保留揭示', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const revealed = new Set([blocks[0].from]);
  const pos = blocks[0].from + 5;
  const next = pruneRevealed(blocks, revealed, pos);
  assert.ok(next.has(blocks[0].from));
});

test('pruneRevealed: 光标移出块 → 合上投影 (揭示态清除)', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const revealed = new Set([blocks[0].from]);
  const next = pruneRevealed(blocks, revealed, blocks[1].from);
  assert.equal(next.has(blocks[0].from), false, '移开的块应合上投影');
  // 只做减法: 光标移进一个未揭示的块, 不该凭空把它揭示 (否则点一下就让图变成源码)
  assert.equal(next.size, 0);
});

test('pruneRevealed: 只留光标所在块, 其余合上', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const revealed = new Set(blocks.map(b => b.from));
  const next = pruneRevealed(blocks, revealed, blocks[1].to);
  assert.deepEqual([...next], [blocks[1].from]);
});

test('pruneRevealed: 空集 / 失焦 (pos 非数字) → 空集', () => {
  const blocks = scanMermaidBlocks(DOC2);
  assert.equal(pruneRevealed(blocks, new Set(), 0).size, 0);
  assert.equal(pruneRevealed(blocks, new Set([blocks[0].from]), null).size, 0);
  assert.equal(pruneRevealed(blocks, new Set([blocks[0].from]), undefined).size, 0);
});

test('pruneRevealed: 返回新集合, 不改入参 (纯函数)', () => {
  const blocks = scanMermaidBlocks(DOC2);
  const revealed = new Set([blocks[0].from]);
  pruneRevealed(blocks, revealed, null);
  assert.equal(revealed.size, 1, '入参被就地修改了');
});
