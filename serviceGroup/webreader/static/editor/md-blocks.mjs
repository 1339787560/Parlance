// 编辑态装饰层的纯逻辑: 只读扫描 md 源码 → 范围数组。
//
// 保真红线地基 (原文保真 = 三条红线之一):
//   本模块**永不返回文本、永不改写 doc**。所有 from/to 都是原文档坐标,
//   切片回 doc 即原始片段 (不发明字符, 不重排)。装饰只作投影, 不参与持久化。
//   拿不准的结构一律不返范围 —— 宁可不装饰, 不可猜 (宁可不所见即所得, 不可糟蹋原文)。
//
// 无依赖, 浏览器与 Node 同源 (app.js 与单测都直接 import 本文件)。

// ============== 行索引 ==============

// 切行 → [{ text, from, to, end }]
//   from/to = 行文本范围 (不含换行); end = 行尾之后 (含换行)
function splitLines(doc) {
  const lines = [];
  let pos = 0;
  while (pos <= doc.length) {
    let nl = doc.indexOf('\n', pos);
    if (nl < 0) nl = doc.length;
    lines.push({ text: doc.slice(pos, nl), from: pos, to: nl, end: Math.min(nl + 1, doc.length) });
    if (nl >= doc.length) break;
    pos = nl + 1;
  }
  return lines;
}

// 显式行尾 CR 规范化判断: 只用于文本匹配, 不改动 doc
function stripCR(text) {
  return text.endsWith('\r') ? text.slice(0, -1) : text;
}

function insideAny(ranges, pos) {
  for (const r of ranges) {
    if (pos >= r.from && pos <= r.to) return true;
  }
  return false;
}

// ============== 围栏扫描 ==============

const FENCE_OPEN_RE = /^( {0,3})(`{3,}|~{3,})(.*)$/;

function fenceOpen(line) {
  const m = FENCE_OPEN_RE.exec(stripCR(line));
  if (!m) return null;
  const marker = m[2][0];
  const len = m[2].length;
  const info = m[3].trim();
  // CommonMark: 反引号围栏的信息串不得含反引号 (含则不是围栏, 是普通行)
  if (marker === '`' && info.includes('`')) return null;
  return { marker, len, info, lang: (info.split(/\s+/)[0] || '').toLowerCase() };
}

function isFenceClose(line, marker, len) {
  const text = stripCR(line);
  const re = marker === '`'
    ? new RegExp('^ {0,3}`{' + len + ',}\\s*$')
    : new RegExp('^ {0,3}~{' + len + ',}\\s*$');
  return re.test(text);
}

/**
 * 扫描围栏代码块 (``` / ~~~)。
 * @param {string} doc
 * @param {string|null} wantLang 只返回该语言的围栏 (小写); null = 全部
 * @returns {{from:number,to:number,bodyFrom:number,bodyTo:number,lang:string,info:string,src:string}[]}
 *   未闭合围栏不返回 (保守: 无法界定的内容不装饰)。
 */
export function scanFencedBlocks(doc, wantLang = null) {
  if (!doc) return [];
  const lines = splitLines(doc);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const open = fenceOpen(lines[i].text);
    if (!open) continue;
    // 找闭合行: 同字符且长度 >= 开启长度
    let closeIdx = -1;
    for (let j = i + 1; j < lines.length; j++) {
      if (isFenceClose(lines[j].text, open.marker, open.len)) { closeIdx = j; break; }
    }
    if (closeIdx < 0) {
      // 未闭合: 跳过开启行, 继续按普通行扫描 (后面可能还有真正的成对围栏)
      continue;
    }
    const bodyLines = lines.slice(i + 1, closeIdx);
    const from = lines[i].from;
    const to = lines[closeIdx].to;
    const bodyFrom = bodyLines.length ? bodyLines[0].from : lines[i].end;
    const bodyTo = bodyLines.length ? bodyLines[bodyLines.length - 1].to : bodyFrom;
    // src 用 doc 切片, 保证与 bodyFrom/bodyTo 完全一致 (不另造字符串)
    const src = doc.slice(bodyFrom, bodyTo);
    if (wantLang == null || open.lang === wantLang) {
      out.push({ from, to, bodyFrom, bodyTo, lang: open.lang, info: open.info, src });
    }
    i = closeIdx;   // 跳过整块 (嵌套围栏是内容, 不是新块)
  }
  return out;
}

/** 只扫 mermaid 围栏 (装饰层用)。 */
export function scanMermaidBlocks(doc) {
  return scanFencedBlocks(doc, 'mermaid');
}

// ============== 表格扫描 ==============

// 行形状: 允许最多 3 空格缩进, 首尾都是未转义管道
const TABLE_ROW_RE = /^ {0,3}\|.*\|\s*$/;
// 分隔行: 每个单元形如 :?-+:?
const TABLE_DELIM_RE = /^ {0,3}\|[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|\s*$/;

/** 按未转义管道切出单元格文本范围 (去首尾空白)。 */
function splitCells(text, base) {
  const cuts = [];
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '\\') { i++; continue; }   // 跳过被转义的字符
    if (text[i] === '|') cuts.push(i);
  }
  const cells = [];
  for (let k = 0; k + 1 < cuts.length; k++) {
    const segFrom = cuts[k] + 1;
    const segTo = cuts[k + 1];
    let a = segFrom, b = segTo;
    while (a < b && /\s/.test(text[a])) a++;
    while (b > a && /\s/.test(text[b - 1])) b--;
    if (a >= b) { cells.push({ from: base + segFrom, to: base + segFrom }); continue; }
    cells.push({ from: base + a, to: base + b });
  }
  return cells;
}

/**
 * 扫描 md 表格块 (表头行 + 分隔行 + 数据行)。
 * 围栏内的表格不算表 (代码块内容不装饰)。
 * @returns {{from:number,to:number,rows:{from:number,to:number,isDelimiter:boolean,cells:{from:number,to:number}[]}[]}[]}
 */
export function scanTableBlocks(doc) {
  if (!doc) return [];
  const lines = splitLines(doc);
  const fences = scanFencedBlocks(doc, null);
  const out = [];
  for (let i = 0; i + 1 < lines.length; i++) {
    const head = stripCR(lines[i].text);
    const delim = stripCR(lines[i + 1].text);
    if (!TABLE_ROW_RE.test(head)) continue;
    if (!TABLE_DELIM_RE.test(delim)) continue;
    if (insideAny(fences, lines[i].from)) continue;   // 代码块内的表格不装饰
    // 表头行与分隔行的列数必须一致 (不一致 = 不是表, 保守不碰)
    const headCells = splitCells(head, lines[i].from);
    const delimCells = splitCells(delim, lines[i + 1].from);
    if (headCells.length === 0 || headCells.length !== delimCells.length) continue;

    const rows = [];
    let last = i + 1;
    for (let j = i + 2; j < lines.length; j++) {
      const text = stripCR(lines[j].text);
      if (!TABLE_ROW_RE.test(text)) break;
      last = j;
    }
    const bodyFrom = lines[i].from;
    const bodyTo = lines[last].to;
    if (insideAny(fences, bodyFrom)) continue;

    rows.push({ from: lines[i].from, to: lines[i].to, isDelimiter: false, cells: headCells });
    rows.push({ from: lines[i + 1].from, to: lines[i + 1].to, isDelimiter: true, cells: delimCells });
    for (let j = i + 2; j <= last; j++) {
      const text = stripCR(lines[j].text);
      rows.push({ from: lines[j].from, to: lines[j].to, isDelimiter: false, cells: splitCells(text, lines[j].from) });
    }
    out.push({ from: bodyFrom, to: bodyTo, rows });
    i = last;
  }
  return out;
}

// ============== wikilink ==============

// 行内代码段 (反引号 run 配对): 返回该行的 code 范围 (行内相对坐标)
function inlineCodeSpans(lineText) {
  const spans = [];
  let i = 0;
  while (i < lineText.length) {
    if (lineText[i] !== '`') { i++; continue; }
    let runEnd = i;
    while (runEnd < lineText.length && lineText[runEnd] === '`') runEnd++;
    const runLen = runEnd - i;
    // 找下一个等长 run
    let j = runEnd;
    let closeEnd = -1;
    while (j < lineText.length) {
      if (lineText[j] === '`') {
        let k = j;
        while (k < lineText.length && lineText[k] === '`') k++;
        if (k - j === runLen) { closeEnd = k; break; }
        j = k;
      } else j++;
    }
    if (closeEnd < 0) break;   // 未配对: 不当作代码段
    spans.push([i, closeEnd]);
    i = closeEnd;
  }
  return spans;
}

/**
 * 扫描 [[target]] / [[target|label]]。围栏内与行内代码内不识别。
 * 返回的 from/to 覆盖整个 [[...]]; innerFrom/innerTo 覆盖 inner 文本 (含 |label 部分)。
 */
export function scanWikilinks(doc) {
  if (!doc) return [];
  const lines = splitLines(doc);
  const fences = scanFencedBlocks(doc, null);
  const out = [];
  const re = /\[\[([^\]\n[|]*?)(?:\|([^\]\n]*?))?\]\]/g;
  for (const line of lines) {
    if (insideAny(fences, line.from)) continue;
    const codeSpans = inlineCodeSpans(line.text);
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(line.text)) !== null) {
      const relFrom = m.index;
      const relTo = m.index + m[0].length;
      // 转义: 前面奇数个反斜杠
      let bs = 0;
      for (let k = relFrom - 1; k >= 0 && line.text[k] === '\\'; k--) bs++;
      if (bs % 2 === 1) continue;
      // 行内代码内跳过
      if (codeSpans.some(([a, b]) => relFrom >= a && relTo <= b)) continue;
      const target = (m[1] || '').trim();
      if (!target) continue;
      const label = m[2] != null ? m[2].trim() : target;
      const innerFrom = line.from + relFrom + 2;
      const innerTo = line.from + relTo - 2;
      out.push({
        from: line.from + relFrom,
        to: line.from + relTo,
        innerFrom,
        innerTo,
        target,
        label,
      });
    }
  }
  return out;
}

// ============== 单元格定位 (阶段三之二) ==============

/**
 * 给定文档位置, 返回所在单元格 { row, col, from, to }。
 * 在表内但落在管道/空白上时, 归到该行最近的单元格; 表外返 null。
 */
export function tableCellAt(doc, pos) {
  if (!doc || pos == null) return null;
  const tables = scanTableBlocks(doc);
  const table = tables.find(t => pos >= t.from && pos <= t.to);
  if (!table) return null;
  const row = table.rows.find(r => pos >= r.from && pos <= r.to) || table.rows[0];
  if (!row || row.cells.length === 0) return null;
  const rowIdx = table.rows.indexOf(row);
  let col = row.cells.findIndex(c => pos >= c.from && pos <= c.to);
  if (col < 0) {
    // 落在管道上: 取最近的单元格
    let best = 0, bestDist = Infinity;
    row.cells.forEach((c, idx) => {
      const d = pos < c.from ? c.from - pos : pos - c.to;
      if (d < bestDist) { bestDist = d; best = idx; }
    });
    col = best;
  }
  const cell = row.cells[col];
  return { row: rowIdx, col, from: cell.from, to: cell.to };
}

// ============== 原子范围 ==============

/**
 * 判断 pos 处是不是"紧贴某个原子块"的删除动作。
 * dir = -1 (退格, 光标在块首) / +1 (删除, 光标在块尾)。
 * 命中 → 调用方应先"揭示源码", 再次删除才真删 (防一按退格整块消失)。
 */
export function nearestAtomicEdge(blocks, pos, dir) {
  for (const b of blocks || []) {
    if (dir < 0 && b.from === pos) return { block: b, edge: 'from' };
    if (dir > 0 && b.to === pos) return { block: b, edge: 'to' };
  }
  return null;
}
