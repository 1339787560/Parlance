// 编辑态装饰层的纯逻辑单测 (node --test)
// 契约: md-blocks.mjs 只读扫描 md 源码, 返回范围数组, 永不返回/改写文本。
// 这三条不变量是「原文保真」红线的地基:
//   I1 位置准确 — 所有 from/to 切片回原文即原始片段, 不发明字符
//   I2 不重叠   — 装饰区间互不重叠 (CM6 重叠 replace 装饰会抛错)
//   I3 保守不碰 — 未界定/拿不准的结构一律不返范围 (宁可不装饰, 不可猜)

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  scanFencedBlocks,
  scanMermaidBlocks,
  scanTableBlocks,
  scanWikilinks,
  tableCellAt,
  nearestAtomicEdge,
} from '../static/editor/md-blocks.mjs';

// ============== 黄金文档 (测试用例文档要求覆盖的危险语法) ==============
const GOLDEN = [
  '---',
  'Doc_Name: 黄金文档',
  '---',
  '',
  '# 标题',
  '',
  '正文一段, 行尾两空格硬换行  ',
  '下一行仍属同段。',
  '',
  '[[roles/InfoServer-Dev/L0_Index]]',
  '',
  '| 列A | 列B |',
  '| --- | --- |',
  '| a1  | b1  |',
  '',
  '| 左 | 右 |',
  '|:---|---:|',
  '| l   | r   |',
  '',
  '```mermaid',
  'graph TD;',
  '  A-->B;',
  '```',
  '',
  '```java',
  'int x = 1;',
  '```',
  '',
  '```',
  '未知扩展块, 含 | 与 [[不是wikilink]]',
  '```',
  '',
].join('\n');

// ============== 围栏扫描 ==============

test('scanMermaidBlocks: 识别单个 mermaid 块, 范围与正文准确', () => {
  const blocks = scanMermaidBlocks(GOLDEN);
  assert.equal(blocks.length, 1);
  const b = blocks[0];
  assert.equal(b.lang, 'mermaid');
  // 切片回原文 — 保真 I1
  assert.equal(GOLDEN.slice(b.from, b.to), '```mermaid\ngraph TD;\n  A-->B;\n```');
  assert.equal(GOLDEN.slice(b.bodyFrom, b.bodyTo), 'graph TD;\n  A-->B;');
  assert.equal(b.src, 'graph TD;\n  A-->B;');
});

test('scanMermaidBlocks: 标错语言名的围栏不算 mermaid (原样保留)', () => {
  const blocks = scanMermaidBlocks('```java\nint x = 1;\n```\n');
  assert.equal(blocks.length, 0);
});

test('scanMermaidBlocks: 无语言围栏不算 mermaid', () => {
  assert.equal(scanMermaidBlocks('```\nplain\n```\n').length, 0);
});

test('scanFencedBlocks: 支持波浪号围栏', () => {
  const doc = '~~~mermaid\ngraph TD;\n~~~\n';
  const blocks = scanFencedBlocks(doc, 'mermaid');
  assert.equal(blocks.length, 1);
  assert.equal(doc.slice(blocks[0].from, blocks[0].to), doc.trimEnd());
  assert.equal(blocks[0].src, 'graph TD;');
});

test('scanFencedBlocks: 未闭合围栏不返范围 (I3 保守不碰)', () => {
  assert.equal(scanFencedBlocks('```mermaid\ngraph TD;\n', 'mermaid').length, 0);
});

test('scanFencedBlocks: 长围栏包裹短围栏, 内层不单独成块', () => {
  const doc = '````markdown\n```mermaid\ngraph TD;\n```\n````\n';
  const blocks = scanFencedBlocks(doc, 'markdown');
  assert.equal(blocks.length, 1);
  // 内层的 ```mermaid 不得被当成独立 mermaid 块 (嵌套是内容不是块)
  assert.equal(scanMermaidBlocks(doc).length, 0);
});

test('scanFencedBlocks: 缩进 (最多3空格) 围栏也识别, 4空格不识别', () => {
  const indented = '   ```mermaid\n   graph TD;\n   ```\n';
  const b3 = scanFencedBlocks(indented, 'mermaid');
  assert.equal(b3.length, 1);
  assert.equal(b3[0].src, '   graph TD;');

  const deep = '    ```mermaid\n    graph TD;\n    ```\n';
  assert.equal(scanFencedBlocks(deep, 'mermaid').length, 0);
});

test('scanFencedBlocks: 围栏信息串带多余词仍按语言识别', () => {
  const doc = '```mermaid title="流程图"\ngraph TD;\n```\n';
  const blocks = scanFencedBlocks(doc, 'mermaid');
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].src, 'graph TD;');
});

test('scanFencedBlocks: 多个围栏按出现顺序返回, 不重叠', () => {
  const doc = [
    '```mermaid',
    'graph TD; A-->B;',
    '```',
    '',
    '正文',
    '',
    '```mermaid',
    'graph LR; C-->D;',
    '```',
    '',
  ].join('\n');
  const blocks = scanMermaidBlocks(doc);
  assert.equal(blocks.length, 2);
  assert.ok(blocks[0].to <= blocks[1].from, '装饰区间不得重叠 (I2)');
  assert.equal(blocks[1].src, 'graph LR; C-->D;');
});

test('scanFencedBlocks: 空 body 也返块 (渲染失败由装饰层兜底)', () => {
  const doc = '```mermaid\n```\n';
  const blocks = scanMermaidBlocks(doc);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].src, '');
});

// ============== 表格扫描 ==============

test('scanTableBlocks: 识别标准表, 行列与单元格范围准确', () => {
  const doc = '| 列A | 列B |\n| --- | --- |\n| a1  | b1  |\n';
  const tables = scanTableBlocks(doc);
  assert.equal(tables.length, 1);
  const t = tables[0];
  assert.equal(t.rows.length, 3);
  assert.equal(t.rows[0].cells.length, 2);
  assert.equal(t.rows[1].isDelimiter, true);
  // 单元格切片 (去空白) — I1
  assert.equal(doc.slice(t.rows[0].cells[0].from, t.rows[0].cells[0].to), '列A');
  assert.equal(doc.slice(t.rows[0].cells[1].from, t.rows[0].cells[1].to), '列B');
  assert.equal(doc.slice(t.rows[2].cells[0].from, t.rows[2].cells[0].to), 'a1');
  assert.equal(doc.slice(t.rows[2].cells[1].from, t.rows[2].cells[1].to), 'b1');
});

test('scanTableBlocks: 两种分隔行写法都识别 (含对齐冒号)', () => {
  const a = '| 左 | 右 |\n|:---|---:|\n| l   | r   |\n';
  const b = '| 左 | 右 |\n| --- | --- |\n| l   | r   |\n';
  assert.equal(scanTableBlocks(a).length, 1);
  assert.equal(scanTableBlocks(b).length, 1);
});

test('scanTableBlocks: 无分隔行的管道段落不算表', () => {
  assert.equal(scanTableBlocks('a | b | c\n只是一行普通文本\n').length, 0);
});

test('scanTableBlocks: 围栏内的表格不算表 (代码块内容不装饰)', () => {
  const doc = '```\n| a | b |\n| --- | --- |\n```\n';
  assert.equal(scanTableBlocks(doc).length, 0);
});

test('scanTableBlocks: 转义管道 \\| 不算列分隔', () => {
  const doc = '| a | b |\n| --- | --- |\n| x \\| y | z |\n';
  const t = scanTableBlocks(doc)[0];
  assert.equal(t.rows.length, 3);
  // 第三行仍为 2 列, 转义管道留在单元格文本内
  assert.equal(t.rows[2].cells.length, 2);
  assert.equal(doc.slice(t.rows[2].cells[0].from, t.rows[2].cells[0].to), 'x \\| y');
});

test('scanTableBlocks: 表格范围止于首个非表格行', () => {
  const doc = '| a | b |\n| --- | --- |\n| 1 | 2 |\n\n尾段\n';
  const t = scanTableBlocks(doc)[0];
  assert.equal(t.rows.length, 3);
  // 末行行尾之后即是边界, 不含尾段
  assert.ok(t.to <= doc.indexOf('\n\n尾段') + 1);
  assert.ok(!doc.slice(t.from, t.to).includes('尾段'));
});

test('scanTableBlocks: 表格与围栏装饰区间不重叠 (I2)', () => {
  const tables = scanTableBlocks(GOLDEN);
  const fences = scanMermaidBlocks(GOLDEN);
  for (const t of tables) {
    for (const f of fences) {
      assert.ok(t.to <= f.from || f.to <= t.from, '表格与围栏区间重叠 (I2)');
    }
  }
});

test('scanTableBlocks: 黄金文档里两张表都识别', () => {
  assert.equal(scanTableBlocks(GOLDEN).length, 2);
});

// ============== wikilink ==============

test('scanWikilinks: 识别 [[target]], 双方括号范围准确', () => {
  const doc = '见 [[roles/L0_Index]] 一节。\n';
  const links = scanWikilinks(doc);
  assert.equal(links.length, 1);
  const l = links[0];
  assert.equal(l.target, 'roles/L0_Index');
  assert.equal(doc.slice(l.from, l.to), '[[roles/L0_Index]]');
  assert.equal(doc.slice(l.innerFrom, l.innerTo), 'roles/L0_Index');
  assert.equal(doc.slice(l.from, l.innerFrom), '[[');
  assert.equal(doc.slice(l.innerTo, l.to), ']]');
});

test('scanWikilinks: [[target|显示名]] 解析出 target 与 label', () => {
  const doc = '[[roles/InfoServer-Dev/L0_Index|服务端索引]]\n';
  const l = scanWikilinks(doc)[0];
  assert.equal(l.target, 'roles/InfoServer-Dev/L0_Index');
  assert.equal(l.label, '服务端索引');
});

test('scanWikilinks: 围栏内的 [[x]] 不识别', () => {
  const doc = '```\n[[不是wikilink]]\n```\n';
  assert.equal(scanWikilinks(doc).length, 0);
});

test('scanWikilinks: 行内代码 `[[x]]` 不识别', () => {
  assert.equal(scanWikilinks('行内 `[[不是wikilink]]` 结束\n').length, 0);
});

test('scanWikilinks: 空目标 [[ ]] 不识别', () => {
  assert.equal(scanWikilinks('[[   ]]\n').length, 0);
});

test('scanWikilinks: 多个 wikilink 按序返回', () => {
  const doc = '[[a]] 与 [[b/c]] 两个\n';
  const links = scanWikilinks(doc);
  assert.equal(links.length, 2);
  assert.deepEqual(links.map(l => l.target), ['a', 'b/c']);
  assert.ok(links[0].to <= links[1].from);
});

// ============== 单元格定位 (阶段三之二) ==============

test('tableCellAt: 命中单元格返回行列与文本范围', () => {
  const doc = '| 列A | 列B |\n| --- | --- |\n| a1  | b1  |\n';
  const t = scanTableBlocks(doc)[0];
  const cell = t.rows[2].cells[1];
  const hit = tableCellAt(doc, cell.from + 1);
  assert.ok(hit);
  assert.equal(hit.row, 2);
  assert.equal(hit.col, 1);
  assert.equal(hit.from, cell.from);
  assert.equal(hit.to, cell.to);
});

test('tableCellAt: 表外位置返回 null', () => {
  const doc = '正文\n\n| a | b |\n| --- | --- |\n';
  assert.equal(tableCellAt(doc, 0), null);
});

// ============== 原子范围 (mermaid 块退格语义) ==============

test('nearestAtomicEdge: 块首退格 / 块尾删除都命中该块', () => {
  const doc = '前文\n```mermaid\ngraph TD;\n```\n后文\n';
  const blocks = scanMermaidBlocks(doc);
  const b = blocks[0];
  assert.equal(nearestAtomicEdge(blocks, b.from, -1)?.block.from, b.from);
  assert.equal(nearestAtomicEdge(blocks, b.to, 1)?.block.from, b.from);
});

test('nearestAtomicEdge: 远离块时返回 null', () => {
  const doc = '前文\n```mermaid\ngraph TD;\n```\n后文\n';
  const blocks = scanMermaidBlocks(doc);
  assert.equal(nearestAtomicEdge(blocks, 0, -1), null);
  assert.equal(nearestAtomicEdge(blocks, doc.length, 1), null);
});
