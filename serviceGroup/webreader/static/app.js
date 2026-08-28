// roleManager Web Reader — 主前端逻辑
// - 文件树懒加载、md 渲染、代码高亮、CodeMirror 6 编辑、每秒自动回写
// - 快捷键: Cmd/Ctrl + F 当前查找 / Shift+F 全局搜索 / P 快速打开 / B 折叠侧栏 / S 强制保存
// - 字号 A+/A-, 侧栏宽度可拖拽, mac/win 通用

import { EditorView, lineNumbers, highlightActiveLine, highlightActiveLineGutter,
         keymap, drawSelection, gutter, GutterMarker } from '@codemirror/view';
import { EditorState, Compartment, Text } from '@codemirror/state';
import { history, defaultKeymap, historyKeymap, indentWithTab } from '@codemirror/commands';
import { HighlightStyle, syntaxHighlighting, defaultHighlightStyle, indentOnInput,
         bracketMatching, foldGutter, foldKeymap } from '@codemirror/language';
import { search, openSearchPanel, searchKeymap, closeSearchPanel } from '@codemirror/search';
import { markdown } from '@codemirror/lang-markdown';
import { python } from '@codemirror/lang-python';
import { cpp } from '@codemirror/lang-cpp';
import { rust } from '@codemirror/lang-rust';
import { javascript } from '@codemirror/lang-javascript';
import { json } from '@codemirror/lang-json';
import { html } from '@codemirror/lang-html';
import { css } from '@codemirror/lang-css';
import { yaml } from '@codemirror/lang-yaml';
import { oneDark } from '@codemirror/theme-one-dark';

// ============== 状态 ==============
const state = {
  currentFile: null,         // { path, encoding, language, extension, content }
  fontSize: 14,                 // Mac 默认 14; Win 在 loadPrefs 中改为 16
  sidebarWidth: 280,
  sidebarCollapsed: false,
  allFiles: [],              // 用于 cmd+P 模糊匹配
  allFilesLoaded: false,     // 快速打开索引是否已加载（懒加载）
  treeCache: new Map(),      // path -> [items]
  expanded: new Set(),       // 已展开的目录
  editor: null,              // CodeMirror EditorView
  editorLangCompartment: new Compartment(),
  editorThemeCompartment: new Compartment(),
  vditor: null,              // Vditor IR 编辑器实例 (.md 用)
  saveTimer: null,
  lastSavedContent: '',
  isDirty: false,
  // tab 系统
  tabs: [],                  // [{ path, name, pinned, dirty, scrollTop, editMode }]
  activeTabPath: null,
  // 文件复制/剪切/粘贴 + 拖拽
  clipboard: null,          // { path, type, cut }
  selectedPath: null,
  selectedType: null,
  // 批注
  comments: [],             // 当前文件批注列表
  commentFilter: 'all',     // all | open | resolved
  commentPendingContext: null, // 添加批注时临时保存的选区上下文 { snippet, contextBefore, contextAfter }
  // 根目录可见性筛选：visibleFolders 为空 = 全部文件夹；showRootFiles 控制根目录文件是否显示
  visibleFolders: new Set(),
  showRootFiles: true,
};

const $ = (sel) => document.querySelector(sel);
const $all = (sel) => document.querySelectorAll(sel);
const els = {
  topbar: $('#topbar'),
  layout: $('#layout'),
  splitter: $('#splitter'),
  sidebar: $('#sidebar'),
  tree: $('#tree'),
  treeFilter: $('#tree-filter'),
  currentPath: $('#current-path'),
  fontSizeLabel: $('#font-size-label'),
  saveStatus: $('#save-status'),
  editToggle: $('#btn-edit-toggle'),
  welcome: $('#welcome'),
  viewer: $('#viewer'),
  vditorHost: $('#vditor-host'),
  editorHost: $('#editor-host'),
  contentBody: $('#content-body'),
  contentWrap: $('#content-wrap'),
  tabBar: $('#tab-bar'),
  outlinePanel: $('#outline-panel'),
  outlineBody: $('#outline-body'),
  historyPanel: $('#history-panel'),
  historyBody: $('#history-body'),
  btnOutlineToggle: $('#btn-outline-toggle'),
  btnHistory: $('#btn-history'),
  btnShare: $('#btn-share'),
  btnDownload: $('#btn-download'),
  btnArchive: $('#btn-archive'),
  btnTrash: $('#btn-trash'),
  btnTreeFilterConfig: $('#btn-tree-filter-config'),
  treeFilterModal: $('#tree-filter-modal'),
  treeFilterList: $('#tree-filter-list'),
  treeFilterClose: $('#tree-filter-close'),
  treeFilterCancel: $('#tree-filter-cancel'),
  treeFilterSave: $('#tree-filter-save'),
  trashPanel: $('#trash-panel'),
  trashBody: $('#trash-body'),
  trashSelectAll: $('#trash-select-all'),
  btnTrashRestore: $('#btn-trash-restore'),
  btnTrashPurge: $('#btn-trash-purge'),
  // 批注
  btnComments: $('#btn-comments'),
  btnCommentsBadge: $('#btn-comments-badge'),
  commentPanel: $('#comment-panel'),
  commentBody: $('#comment-body'),
  commentFilter: $('#comment-filter'),
  btnCommentRefresh: $('#btn-comment-refresh'),
  commentMenu: $('#comment-menu'),
  commentEditorPanel: $('#comment-editor-panel'),
  commentEditorSnippet: $('#comment-editor-snippet'),
  commentEditorText: $('#comment-editor-text'),
  commentEditorCancel: $('#comment-editor-cancel'),
  commentEditorSubmit: $('#comment-editor-submit'),
  sbEncoding: $('#sb-encoding'),
  sbInfo: $('#sb-info'),
  searchModal: $('#search-modal'),
  searchInput: $('#search-input'),
  searchExt: $('#search-ext'),
  searchResults: $('#search-results'),
  quickopenModal: $('#quickopen-modal'),
  quickopenInput: $('#quickopen-input'),
  quickopenResults: $('#quickopen-results'),
  findBar: $('#find-bar'),
  findInput: $('#find-input'),
  findCount: $('#find-count'),
  findNext: $('#find-next'),
  findPrev: $('#find-prev'),
  btnIncFont: $('#btn-increase-font'),
  btnDecFont: $('#btn-decrease-font'),
  btnToggleSidebar: $('#btn-toggle-sidebar'),
  btnRefreshTree: $('#btn-refresh-tree'),
  tabMenu: $('#tab-menu'),
  treeMenu: $('#tree-menu'),
};

// 右缘面板浮层化: 同步 class, 让 #content-body 的滚动条始终贴页面最右
const rightPanels = [els.historyPanel, els.trashPanel, els.commentPanel];
function syncRightPanelLayout() {
  els.contentWrap.classList.toggle('right-panel-open', rightPanels.some(p => !p.hidden));
  els.contentWrap.classList.toggle('right-panel-history', !els.historyPanel.hidden);
  els.contentWrap.classList.toggle('right-panel-wide', !els.trashPanel.hidden || !els.commentPanel.hidden);
}
const rightPanelObserver = new MutationObserver(syncRightPanelLayout);
rightPanels.forEach(p => rightPanelObserver.observe(p, { attributes: true, attributeFilter: ['hidden'] }));
syncRightPanelLayout();

// ============== 持久化 ==============
const IS_WIN = navigator.userAgent.includes('Windows');

function loadPrefs() {
  const defaultSize = IS_WIN ? 16 : 14;
  const fs = parseInt(localStorage.getItem('reader.fontSize') || String(defaultSize), 10);
  if (fs >= 10 && fs <= 24) state.fontSize = fs;
  const sw = parseInt(localStorage.getItem('reader.sidebarWidth') || '280', 10);
  if (sw >= 180 && sw <= 600) state.sidebarWidth = sw;
  const sc = localStorage.getItem('reader.sidebarCollapsed') === '1';
  state.sidebarCollapsed = sc;
  try {
    const v = JSON.parse(localStorage.getItem('reader.visibleRoots') || 'null');
    if (v) {
      if (Array.isArray(v.folders)) state.visibleFolders = new Set(v.folders);
      if (typeof v.showFiles === 'boolean') state.showRootFiles = v.showFiles;
    }
  } catch (e) {}
  applyFontSize();
  applySidebarWidth();
  if (sc) els.layout.classList.add('collapsed');
}

function savePref(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) {}
}

function saveVisibleRoots() {
  savePref('reader.visibleRoots', JSON.stringify({
    folders: [...state.visibleFolders],
    showFiles: state.showRootFiles,
  }));
}

// 根目录可见性过滤：文件夹按勾选集合过滤；根文件由 showRootFiles 控制
function filterRootItems(items) {
  return (items || []).filter((it) => {
    if (it.type === 'folder') {
      return state.visibleFolders.size === 0 || state.visibleFolders.has(it.name);
    }
    return state.showRootFiles;
  });
}

function applyFontSize() {
  document.documentElement.style.setProperty('--reader-font-size', state.fontSize + 'px');
  els.fontSizeLabel.textContent = String(state.fontSize);
  savePref('reader.fontSize', state.fontSize);
}

function applySidebarWidth() {
  document.documentElement.style.setProperty('--sidebar-width', state.sidebarWidth + 'px');
  savePref('reader.sidebarWidth', state.sidebarWidth);
}

// ============== 嵌入桥 (Castflow iframe) + 展示缩放 ==============
// WebReader 可独立浏览器使用, 也可被 Castflow 以 iframe 嵌入。嵌入时:
//   - 展示缩放: 父窗口 postMessage {type:'cf-zoom', value} 驱动整页 zoom (布局重排不裁剪)
//   - 状态同步: 本页把当前打开状态上报父窗口 {type:'cf-state'}, 父窗口持久化后跨重启还原
const EMBEDDED = window.parent !== window;
let currentZoom = 1;

function clampZoom(z) {
  const v = parseFloat(z);
  if (!isFinite(v)) return 1;
  return Math.min(2, Math.max(0.5, v));
}

// 整页展示缩放 (类浏览器 zoom): CSS zoom 布局重排 + 视觉放大。
// 坑: CSS zoom 不缩放 vh/vw 单位 → 若只设 zoom, body 固定高度(100vh) 视觉溢出出现整页滚动条;
//     显式把 body width/height 设为 视口/zoom, 使缩放后正好填满视口, 无溢出无裁剪。
function applyZoom(z) {
  currentZoom = clampZoom(z);
  const b = document.body;
  if (currentZoom !== 1) {
    b.style.zoom = String(currentZoom);
    b.style.width = (window.innerWidth / currentZoom) + 'px';
    b.style.height = (window.innerHeight / currentZoom) + 'px';
  } else {
    b.style.zoom = '';
    b.style.width = '';
    b.style.height = '';
  }
  savePref('reader.zoom', currentZoom);
  notifyParent({ type: 'cf-zoom-state', value: currentZoom });
}

function notifyParent(msg) {
  if (EMBEDDED && window.parent) {
    try { window.parent.postMessage(msg, '*'); } catch (e) {}
  }
}

function buildReaderState() {
  return {
    tabs: state.tabs.filter(t => !t.isHistory).map(t => ({
      path: t.path, name: t.name, pinned: t.pinned,
      scrollTop: t.scrollTop, editMode: t.editMode,
    })),
    activeTabPath: getTab(state.activeTabPath)?.isHistory ? null : state.activeTabPath,
  };
}

// 父窗口命令: zoom 驱动 / 状态还原 / 主动拉取状态 / 主题跟随
window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || typeof d !== 'object' || typeof d.type !== 'string') return;
  if (d.type === 'cf-zoom') {
    applyZoom(d.value);
  } else if (d.type === 'cf-restore') {
    if (d.state && d.state.activeTabPath) {
      openFile(d.state.activeTabPath).catch(() => {});
    }
  } else if (d.type === 'cf-theme') {
    applyTheme(d.value);
  } else if (d.type === 'cf-config') {
    if (d.config) {
      state.localIps = d.config.localIps || [];
      state.downloadDir = d.config.downloadDir || '';
      const raw = Number(d.config.bgOpacity);
      const op = Math.max(0, Math.min(100, Number.isFinite(raw) ? raw : 85)) / 100;
      document.documentElement.style.setProperty('--theme-bg-opacity', String(op));
      document.documentElement.style.setProperty('--reader-bg-opacity', String(op));
    }
  } else if (d.type === 'cf-bg-opacity') {
    const raw = Number(d.value);
    const op = Math.max(0, Math.min(1, Number.isFinite(raw) ? raw : 1));
    document.documentElement.style.setProperty('--theme-bg-opacity', String(op));
    document.documentElement.style.setProperty('--reader-bg-opacity', String(op));
  } else if (d.type === 'cf-get-state') {
    notifyParent({ type: 'cf-state', state: buildReaderState() });
  }
});

// 显式主题（父窗口 Castflow 设置跟随）：html[data-theme] 覆盖 prefers-color-scheme。
// 未设置（无 reader.theme）→ 跟随系统。
const READER_DARK_THEMES = new Set(['dark', 'furina', 'hysilens', 'geniusclub', 'silverwolf', 'odette']);
function isDarkReaderTheme(t) {
  const theme = t || document.documentElement.dataset.theme || 'dark';
  return READER_DARK_THEMES.has(theme);
}
function editorThemeForCurrent() {
  return isDarkReaderTheme() ? oneDark : [];
}
function applyTheme(t) {
  const valid = ['dark', 'light', 'red', 'default', 'kokomi', 'firefly', 'furina', 'hysilens', 'geniusclub', 'silverwolf', 'odette'];
  if (valid.includes(t)) {
    document.documentElement.dataset.theme = t;
    savePref('reader.theme', t);
    // CodeMirror 跟随当前主题：深色主题用 oneDark，浅色主题用默认浅色编辑器
    if (state.editor) {
      try {
        state.editor.dispatch({
          effects: state.editorThemeCompartment.reconfigure(isDarkReaderTheme(t) ? oneDark : []),
        });
      } catch (e) {}
    }
  }
}

// 窗口缩放 → 重算 zoom 补偿 (vh 不随 zoom 缩放)
window.addEventListener('resize', () => {
  if (currentZoom !== 1) applyZoom(currentZoom);
});

// ============== API ==============
async function apiTree(path = '', recursive = false) {
  if (canLocalReader()) {
    return localReaderRequest('tree', { path, recursive });
  }
  const url = '/api/reader/tree?path=' + encodeURIComponent(path) + (recursive ? '&recursive=1' : '');
  const r = await fetch(url);
  if (!r.ok) throw new Error('tree ' + r.status);
  return r.json();
}

// Castflow 本地化 IO 桥：iframe 内通过 postMessage 让父窗口（Tauri）直接读写磁盘，
// 减少 HTTP 往返。仅当嵌入且 URL 带 local=1 时启用。
function canLocalReader() {
  return window.parent !== window && new URLSearchParams(location.search).has('local');
}

function localReaderRequest(op, payload) {
  return new Promise((resolve, reject) => {
    const id = 'lr' + Math.random().toString(36).slice(2);
    const timer = setTimeout(() => {
      window.removeEventListener('message', handler);
      reject(new Error('local reader timeout'));
    }, 10000);
    function handler(e) {
      const d = e.data;
      if (!d || d.type !== 'cf-reader-response' || d.id !== id) return;
      clearTimeout(timer);
      window.removeEventListener('message', handler);
      if (d.ok) resolve(d.data);
      else reject(new Error(d.error || 'local reader failed'));
    }
    window.addEventListener('message', handler);
    window.parent.postMessage({ type: 'cf-reader-request', id, op, payload }, '*');
  });
}

async function apiFile(path) {
  if (canLocalReader()) {
    return localReaderRequest('read', { path });
  }
  const r = await fetch('/api/reader/file?path=' + encodeURIComponent(path));
  if (!r.ok) throw new Error('file ' + r.status);
  return r.json();
}

// ISV #3 token 瘦身(2026-07-31): agent 经 fd_eval("readerGrep(...)") 调用,
// 浏览器内 fetch 全文 + grep, 只返命中行给 agent(≤5KB), 不读全文爆上下文。
// 旧 webReader 真机日志全文拉取 145-154KB/份 是 token bloat 主因之一。
//
// 三模式:
//   grep(path, pattern, {context, limit, regex}) — 命中行 ±context 行, 限 limit 条
//   tail(path, N)                                — 末尾 N 行
//   summary(path)                                — 总行数 + error 计数 + 5 sample error 行
//
// 返值结构对位 MCP 工具返值(agent 经 fd_eval 拿到这个 JSON, 不读全文):
//   { mode, path, totalLines, matchCount/returned, matches/lines/sampleErrors, truncated? }
async function readerGrep(path, pattern, options) {
  options = options || {};
  var contextLines = options.context != null ? options.context : 3;
  var limit = options.limit != null ? options.limit : 50;
  var tail = options.tail || 0;
  try {
    var fileResp = await fetch('/api/reader/file?path=' + encodeURIComponent(path));
    if (!fileResp.ok) return { error: 'file fetch ' + fileResp.status };
    var fileJson = await fileResp.json();
    var content = fileJson.content || '';
    var lines = content.split('\n');

    if (tail > 0) {
      var tailLines = lines.slice(-tail).map(function (t, i) {
        return { ln: lines.length - tail + i + 1, text: String(t).slice(0, 300) };
      });
      return { mode: 'tail', path: path, totalLines: lines.length,
               returned: tailLines.length, lines: tailLines };
    }

    if (!pattern) {
      // summary: 总行数 + error 计数 + 5 sample
      var errCount = 0;
      var sampleErrors = [];
      for (var i = 0; i < lines.length; i++) {
        if (/error|exception|fail|fatal/i.test(lines[i])) {
          errCount++;
          if (sampleErrors.length < 5) {
            sampleErrors.push({ ln: i + 1, text: String(lines[i]).slice(0, 200) });
          }
        }
      }
      return { mode: 'summary', path: path, totalLines: lines.length,
               errorCount: errCount, sampleErrors: sampleErrors };
    }

    // grep: 命中行 + context
    var regex = options.regex ? new RegExp(pattern) : null;
    var matches = [];
    for (var j = 0; j < lines.length; j++) {
      var hit = regex ? regex.test(lines[j]) : String(lines[j]).indexOf(pattern) >= 0;
      if (hit) {
        var start = Math.max(0, j - contextLines);
        var end = Math.min(lines.length - 1, j + contextLines);
        var ctx = [];
        for (var k = start; k <= end; k++) {
          ctx.push({ ln: k + 1, text: String(lines[k]).slice(0, 200) });
        }
        matches.push({ ln: j + 1, text: String(lines[j]).slice(0, 300), context: ctx });
        if (matches.length >= limit) break;
      }
    }
    return { mode: 'grep', path: path, pattern: pattern, totalLines: lines.length,
             matchCount: matches.length, truncated: matches.length >= limit,
             matches: matches };
  } catch (e) {
    return { error: String(e) };
  }
}
// 暴露到 window 供 fd_eval 调用
window.readerGrep = readerGrep;

async function apiSave(path, content, encoding) {
  if (canLocalReader()) {
    return localReaderRequest('save', { path, content, encoding });
  }
  const r = await fetch('/api/reader/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ path, content, encoding }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('save ' + r.status));
  }
  return r.json();
}

// 上传图片到 repo 根 assets/ (后端 sha1 内容寻址去重), 返回 { ok, path }。
// FileReader.readAsDataURL 无 secure-context 限制 (局域网 IP 也可用, crypto.subtle 不行)。
async function apiUploadImage(file) {
  const b64 = await new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => { const s = String(r.result || ''); const i = s.indexOf(','); res(i >= 0 ? s.slice(i + 1) : s); };
    r.onerror = () => rej(r.error);
    r.readAsDataURL(file);
  });
  const extMap = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp', 'image/bmp': 'bmp', 'image/svg+xml': 'svg' };
  const ext = extMap[file.type] || 'png';
  const r = await fetch('/api/reader/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ ext, content: b64 }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('upload ' + r.status));
  }
  return r.json();
}

async function apiStatus(path) {
  const r = await fetch('/api/reader/status?path=' + encodeURIComponent(path));
  if (!r.ok) throw new Error('status ' + r.status);
  return r.json();
}

async function apiCommit(path, message) {
  const r = await fetch('/api/reader/commit?path=' + encodeURIComponent(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ message: message || '' }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ('commit ' + r.status));
  return j;
}

// 自动历史快照: 后端 git add -A 提交所有改动 (md 编辑 + 新粘贴图等), 返 {committed, files}。
// 与单文件 /commit 区别: snapshot 提交整个工作区 (含新 untracked 资产), 用作 autosave 兜底。
async function apiSnapshot(message) {
  const r = await fetch('/api/reader/snapshot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ message: message || '' }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('snapshot ' + r.status));
  }
  return r.json();
}

// 刷新归档按钮: 有未提交改动 -> 亮起; 否则置灰
async function refreshArchiveBtn() {
  const p = state.currentFile && !state.currentFile.isHistory ? state.currentFile.path : null;
  if (!p) { els.btnArchive.disabled = true; return; }
  try {
    const s = await apiStatus(p);
    els.btnArchive.disabled = !s.dirty;
  } catch {
    els.btnArchive.disabled = true;
  }
}

async function apiSearch(q, ext) {
  if (canLocalReader()) {
    const r = await localReaderRequest('search', { q, ext: ext || null });
    return (r && r.results) || [];
  }
  const url = '/api/reader/search?q=' + encodeURIComponent(q) +
              (ext ? '&ext=' + encodeURIComponent(ext) : '');
  const r = await fetch(url);
  if (!r.ok) throw new Error('search ' + r.status);
  const j = await r.json();
  return j.results || [];
}

async function apiAllFiles() {
  return apiTree('', true);
}

async function apiCreate(path, type) {
  if (canLocalReader()) {
    return localReaderRequest('create', { path, type });
  }
  const r = await fetch('/api/reader/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ path, type }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('create ' + r.status));
  }
  return r.json();
}

async function apiDelete(path) {
  if (canLocalReader()) {
    return localReaderRequest('delete', { path });
  }
  const r = await fetch('/api/reader/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ path }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('delete ' + r.status));
  }
  return r.json();
}

async function apiRename(from, to) {
  if (canLocalReader()) {
    return localReaderRequest('rename', { from, to });
  }
  const r = await fetch('/api/reader/rename', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ from, to }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('rename ' + r.status));
  }
  return r.json();
}

// 改名被引用资源 (图片/drawio): 后端扫所有 md 重写引用 + 移文件 + git 提交 (可还原)。
// 返回 { ok, from, to, rewritten:[mdPath...], committed, message }。
async function apiRenameRef(from, to) {
  const r = await fetch('/api/reader/rename-ref', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ from, to }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('rename-ref ' + r.status));
  }
  return r.json();
}

async function apiCopy(from, to) {
  const r = await fetch('/api/reader/copy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ from, to }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('copy ' + r.status));
  }
  return r.json();
}

async function apiDownload(paths) {
  if (canLocalReader()) {
    // 本地模式：直接复制到配置的下载目录，返回目录路径
    return localReaderRequest('download', { paths, download_dir: state.downloadDir || '' });
  }
  const r = await fetch('/api/reader/download', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ paths }),
  });
  if (!r.ok) throw new Error('download ' + r.status);
  return r.blob();
}

// 扫 md 笔记内嵌的本地图片引用, 返回去重后的相对路径列表 (供下载打包)。
// 外链 / data-URI / mailto 不打包 (浏览器直连, 非本地资产)。
// 活动编辑中的 md 取 Vditor 最新值, 其余走 apiFile 取已回写内容。
async function collectImageDeps(mdPaths) {
  const deps = new Set();
  const re = /!\[[^\]]*\]\(([^)]+)\)|<img\s[^>]*src=["']([^"']+)["']/gi;
  for (const mdPath of mdPaths) {
    let content = '';
    if (state.currentFile && state.currentFile.path === mdPath && state.vditor) {
      content = state.vditor.getValue();
    } else {
      try { const f = await apiFile(mdPath); content = f.content || ''; } catch (e) { continue; }
    }
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(content)) !== null) {
      // ![alt](path "title") → 取首 token (path); <img src="path"> → m[2]
      const ref = (m[1] || m[2] || '').trim().split(/\s+/)[0];
      if (!ref) continue;
      if (/^(https?:)?\/\//i.test(ref) || ref.startsWith('data:') || ref.startsWith('mailto:')) continue;
      const resolved = resolveRelative(mdPath, ref);
      if (resolved) deps.add(resolved);
    }
  }
  return [...deps];
}

async function apiHistory(path) {
  const r = await fetch('/api/reader/history?path=' + encodeURIComponent(path));
  if (!r.ok) throw new Error('history ' + r.status);
  const j = await r.json();
  return j.results || [];
}

async function apiVersion(path, hash) {
  const r = await fetch('/api/reader/version?path=' + encodeURIComponent(path) + '&hash=' + encodeURIComponent(hash));
  if (!r.ok) throw new Error('version ' + r.status);
  return r.json();
}

async function apiRestore(path, hash) {
  const r = await fetch('/api/reader/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ path, hash }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('restore ' + r.status));
  }
  return r.json();
}

async function apiTrashList() {
  const r = await fetch('/api/reader/trash/list');
  if (!r.ok) throw new Error('trash list ' + r.status);
  const j = await r.json();
  return j.items || [];
}

async function apiTrashRestore(paths) {
  const r = await fetch('/api/reader/trash/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ paths }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('trash restore ' + r.status));
  }
  return r.json();
}

async function apiTrashPurge(paths) {
  const r = await fetch('/api/reader/trash/purge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ paths }),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || ('trash purge ' + r.status));
  }
  return r.json();
}

// ============== 批注 API ==============
// Castflow 嵌入时，非 roles/ 路径的批注走本地 localStorage 兜底，避免 5090 返回 400。
function isLocalCommentPath(path) {
  return EMBEDDED && path && !path.startsWith('roles/');
}
function localCommentKey(path) {
  return 'reader.comments.local.' + path;
}
function localCommentsGet(path) {
  try {
    const v = JSON.parse(localStorage.getItem(localCommentKey(path)) || 'null');
    return v && Array.isArray(v.comments) ? v : { version: 1, comments: [] };
  } catch (e) { return { version: 1, comments: [] }; }
}
function localCommentsSave(path, data) {
  try { localStorage.setItem(localCommentKey(path), JSON.stringify(data)); } catch (e) {}
}
function localCommentId() {
  return 'local-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
}

async function apiGetComments(path) {
  if (isLocalCommentPath(path)) return localCommentsGet(path);
  const r = await fetch('/api/reader/comments?path=' + encodeURIComponent(path));
  if (!r.ok) throw new Error('comments GET ' + r.status);
  return r.json(); // { version, comments: [...] }
}
async function apiCreateComment(payload) {
  if (isLocalCommentPath(payload.path)) {
    const data = localCommentsGet(payload.path);
    const now = new Date().toISOString();
    const comment = {
      id: localCommentId(),
      path: payload.path,
      anchor: {
        snippet: payload.snippet || '',
        contextBefore: payload.contextBefore || '',
        contextAfter: payload.contextAfter || '',
      },
      author: payload.author || { kind: 'human' },
      body: payload.body || '',
      createdAt: now,
      updatedAt: now,
      status: 'open',
      replies: [],
    };
    data.comments.push(comment);
    localCommentsSave(payload.path, data);
    return comment;
  }
  const r = await fetch('/api/reader/comments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error('comments POST ' + r.status);
  return r.json();
}
async function apiReplyComment(id, payload) {
  const path = payload.path || (state.currentFile && state.currentFile.path);
  if (isLocalCommentPath(path)) {
    const data = localCommentsGet(path);
    const parent = data.comments.find((c) => c.id === id);
    if (!parent) throw new Error('comment not found');
    parent.replies = parent.replies || [];
    parent.replies.push({
      id: localCommentId(),
      author: payload.author || { kind: 'human' },
      body: payload.body || '',
      createdAt: new Date().toISOString(),
    });
    parent.updatedAt = new Date().toISOString();
    localCommentsSave(path, data);
    return parent;
  }
  const r = await fetch('/api/reader/comments/' + encodeURIComponent(id) + '/reply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error('comments reply ' + r.status);
  return r.json();
}
async function apiUpdateComment(id, payload) {
  const path = payload.path || (state.currentFile && state.currentFile.path);
  if (isLocalCommentPath(path)) {
    const data = localCommentsGet(path);
    const c = data.comments.find((x) => x.id === id);
    if (!c) throw new Error('comment not found');
    if (typeof payload.body === 'string') c.body = payload.body;
    if (typeof payload.status === 'string') c.status = payload.status;
    c.updatedAt = new Date().toISOString();
    localCommentsSave(path, data);
    return c;
  }
  // PATCH 优先; 后端不支持 PATCH 时 fallback POST /update
  let r = await fetch('/api/reader/comments/' + encodeURIComponent(id), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (r.status === 404 || r.status === 405) {
    r = await fetch('/api/reader/comments/' + encodeURIComponent(id) + '/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }
  if (!r.ok) throw new Error('comments update ' + r.status);
  return r.json();
}
async function apiDeleteComment(id, path) {
  if (isLocalCommentPath(path)) {
    const data = localCommentsGet(path);
    data.comments = data.comments.filter((c) => c.id !== id);
    localCommentsSave(path, data);
    return { ok: true };
  }
  const qs = path ? '?path=' + encodeURIComponent(path) : '';
  const r = await fetch('/api/reader/comments/' + encodeURIComponent(id) + qs, { method: 'DELETE' });
  if (!r.ok) throw new Error('comments delete ' + r.status);
  return r.json();
}

// ============== 目录大纲 ==============
function buildOutline(content) {
  els.outlineBody.innerHTML = '';
  const lines = content.split('\n');
  // 解析标题: # ~ ######, 忽略代码块内的
  const headings = [];
  let inCode = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) { inCode = !inCode; continue; }
    if (inCode) continue;
    const m = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (m) {
      headings.push({ level: m[1].length, text: m[2], line: i });
    }
  }
  if (headings.length === 0) {
    els.outlineBody.innerHTML = '<div class="outline-empty">无标题</div>';
    return;
  }
  // 构建树
  const root = { children: [], level: 0 };
  const stack = [root];
  for (const h of headings) {
    const node = { ...h, children: [] };
    while (stack.length > 1 && stack[stack.length - 1].level >= h.level) stack.pop();
    stack[stack.length - 1].children.push(node);
    stack.push(node);
  }
  for (const child of root.children) {
    els.outlineBody.appendChild(renderOutlineNode(child));
  }
}

function renderOutlineNode(node) {
  const wrap = document.createElement('div');
  const row = document.createElement('div');
  row.className = 'outline-item';
  row.style.paddingLeft = ((node.level - 1) * 12 + 10) + 'px';

  const hasChildren = node.children.length > 0;
  const twisty = document.createElement('span');
  twisty.className = 'twisty';
  twisty.textContent = hasChildren ? '▼' : '';
  row.appendChild(twisty);

  const text = document.createElement('span');
  text.textContent = node.text;
  row.appendChild(text);

  row.addEventListener('click', (e) => {
    if (e.target === twisty && hasChildren) {
      // 折叠/展开
      const childWrap = wrap.querySelector('.outline-children');
      if (childWrap) {
        const open = childWrap.classList.toggle('open');
        twisty.textContent = open ? '▼' : '▶';
      }
      return;
    }
    jumpToHeading(node.line);
  });
  wrap.appendChild(row);

  if (hasChildren) {
    const childWrap = document.createElement('div');
    childWrap.className = 'outline-children open';
    for (const child of node.children) {
      childWrap.appendChild(renderOutlineNode(child));
    }
    wrap.appendChild(childWrap);
  }
  return wrap;
}

function jumpToHeading(lineIndex) {
  // 给 viewer 内对应行加 id 并滚动
  // marked 渲染后的标题没有行号映射, 改为按标题文本查找
  const container = state.vditor ? els.vditorHost : els.viewer;
  const headings = container.querySelectorAll('h1, h2, h3, h4, h5, h6');
  // 重新解析原始标题顺序与渲染后顺序对应
  // 注意: 必须用去 frontmatter 的 body (与 buildOutline 一致), 否则行号不一致导致跳转失败
  const raw = (state.currentFile && state.currentFile.content || '');
  const { body } = splitFrontmatter(raw);
  const srcLines = body.split('\n');
  let inCode = false;
  const srcHeadings = [];
  for (let i = 0; i < srcLines.length; i++) {
    if (/^\s*```/.test(srcLines[i])) { inCode = !inCode; continue; }
    if (inCode) continue;
    const m = srcLines[i].match(/^#{1,6}\s+(.+?)\s*#*\s*$/);
    if (m) srcHeadings.push(i);
  }
  const targetIdx = srcHeadings.indexOf(lineIndex);
  if (targetIdx >= 0 && headings[targetIdx]) {
    const heading = headings[targetIdx];
    // 跳转前展开所有包裹该标题的折叠 section (否则隐藏无法定位)
    let p = heading.parentElement;
    while (p && p !== container) {
      if (p.classList && p.classList.contains('md-section') && p.dataset.collapsed === 'true') {
        p.dataset.collapsed = 'false';
        // 同步持久化状态 (只清 heading key, 子标题 key 保留以便下次手动维持)
        const key = headingKey(p.querySelector('h1,h2,h3,h4,h5,h6'));
        const s = loadCollapsed(state.currentFile ? state.currentFile.path : '');
        s.delete(key); saveCollapsed(state.currentFile ? state.currentFile.path : '', s);
      }
      p = p.parentElement;
    }
    // 手动计算 content-body 内的滚动位置, 避免 scrollIntoView 触发 body 滚动顶走顶栏
    const scroller = els.contentBody;
    if (scroller) {
      const scrollerRect = scroller.getBoundingClientRect();
      const headingRect = heading.getBoundingClientRect();
      const offset = headingRect.top - scrollerRect.top + scroller.scrollTop;
      scroller.scrollTop = Math.max(0, offset - 8);
    }
    heading.style.transition = 'background 0.5s';
    const oldBg = heading.style.background;
    heading.style.background = 'rgba(255, 213, 79, 0.4)';
    setTimeout(() => { heading.style.background = oldBg; }, 800);
    // 手机端: 跳转后关闭 outline 浮层
    if (isMobile()) closeMobileOutline();
  }
}

// ============== 文件树 ==============
function renderTreeNode(item, depth) {
  const wrap = document.createElement('div');
  wrap.className = 'tree-wrap';
  const row = document.createElement('div');
  row.className = 'tree-node';
  row.style.paddingLeft = (depth * 14 + 6) + 'px';
  row.dataset.path = item.path;
  row.dataset.type = item.type;

  const twisty = document.createElement('span');
  twisty.className = 'twisty';
  twisty.textContent = item.type === 'folder' ? '▶' : '';
  row.appendChild(twisty);

  const icon = document.createElement('span');
  icon.className = 'icon';
  icon.textContent = item.type === 'folder' ? '📁' : fileIcon(item.extension);
  row.appendChild(icon);

  const name = document.createElement('span');
  name.className = 'name';
  name.textContent = item.name;
  row.appendChild(name);

  wrap.appendChild(row);

  // 拖拽: 所有行都可拖
  row.draggable = true;
  row.addEventListener('dragstart', (e) => {
    e.stopPropagation();
    e.dataTransfer.setData('text/plain', item.path);
    e.dataTransfer.effectAllowed = 'move';
    row.classList.add('dragging');
  });
  row.addEventListener('dragend', () => row.classList.remove('dragging'));

  // 文件夹行 = 拖拽放置区
  if (item.type === 'folder') {
    row.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'move';
      row.classList.add('drag-over');
    });
    row.addEventListener('dragleave', () => row.classList.remove('drag-over'));
    row.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      row.classList.remove('drag-over');
      const src = e.dataTransfer.getData('text/plain');
      if (src) handleDropMove(src, item.path);
    });
  }

  // 右键菜单
  row.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    e.stopPropagation();
    state.selectedPath = item.path;
    state.selectedType = item.type;
    showTreeMenu(e.clientX, e.clientY, item);
  });

  if (item.type === 'folder') {
    const childWrap = document.createElement('div');
    childWrap.className = 'tree-children';
    wrap.appendChild(childWrap);
    row.addEventListener('click', async () => {
      const isOpen = childWrap.classList.contains('open');
      if (isOpen) {
        childWrap.classList.remove('open');
        twisty.textContent = '▶';
        state.expanded.delete(item.path);
      } else {
        twisty.textContent = '▼';
        childWrap.classList.add('open');
        state.expanded.add(item.path);
        if (!state.treeCache.has(item.path)) {
          try {
            const items = await apiTree(item.path);
            state.treeCache.set(item.path, items);
          } catch (e) {
            childWrap.innerHTML = '<div class="muted" style="padding:4px 12px;font-size:11px">加载失败</div>';
            return;
          }
        }
        const items = state.treeCache.get(item.path) || [];
        // 大目录分页：首屏最多渲染 300 项，超出显示“显示更多”
        const MAX_TREE_CHILDREN = 300;
        childWrap.querySelectorAll('.tree-more').forEach(el => el.remove());
        const existingCount = childWrap.children.length;
        const frag = document.createDocumentFragment();
        let added = 0;
        for (const child of items) {
          if (existingCount + added >= MAX_TREE_CHILDREN) break;
          if (childWrap.querySelector(`[data-path="${cssEsc(child.path)}"]`)) continue;
          frag.appendChild(renderTreeNode(child, depth + 1));
          added++;
        }
        childWrap.appendChild(frag);
        const currentTotal = childWrap.children.length;
        if (items.length > currentTotal) {
          const more = document.createElement('div');
          more.className = 'tree-more';
          more.textContent = `显示更多 ${items.length - currentTotal} 项`;
          more.addEventListener('click', () => {
            more.remove();
            const frag2 = document.createDocumentFragment();
            for (const child of items) {
              if (childWrap.querySelector(`[data-path="${cssEsc(child.path)}"]`)) continue;
              frag2.appendChild(renderTreeNode(child, depth + 1));
            }
            childWrap.appendChild(frag2);
          });
          childWrap.appendChild(more);
        }
      }
    });
  } else {
    row.addEventListener('click', () => openFile(item.path, { fromTree: true }));
  }

  // 自动展开已展开过的目录
  if (item.type === 'folder' && state.expanded.has(item.path)) {
    queueMicrotask(async () => {
      row.click();
    });
  }
  return wrap;
}

function cssEsc(s) {
  return String(s).replace(/["\\]/g, '\\$&');
}

function fileIcon(ext) {
  if (!ext) return '·';
  const e = ext.toLowerCase();
  if (['.md', '.markdown'].includes(e)) return '📝';
  if (['.json', '.yaml', '.yml', '.toml'].includes(e)) return '⚙️';
  if (['.py'].includes(e)) return '🐍';
  if (['.rs'].includes(e)) return '🦀';
  if (['.ts', '.tsx', '.js', '.jsx'].includes(e)) return '📜';
  if (['.cpp', '.c', '.cc', '.cxx', '.h', '.hpp', '.hh'].includes(e)) return '⚡';
  if (['.lua'].includes(e)) return '🌙';
  if (['.sh', '.bash', '.zsh', '.bat', '.ps1'].includes(e)) return '🐚';
  if (['.html', '.htm', '.css'].includes(e)) return '🎨';
  if (['.drawio', '.dio'].includes(e)) return '📐';
  if (['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'].includes(e)) return '🖼️';
  return '📄';
}

function highlightActiveTreeNode(path, flash = true) {
  document.querySelectorAll('.tree-node.active').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.tree-node.selected').forEach(n => n.classList.remove('selected'));
  const sel = `.tree-node[data-path="${cssEsc(path)}"]`;
  const node = document.querySelector(sel);
  if (!node) return;
  node.classList.add('active');
  node.classList.add('selected');  // 蓝色边框跟随 active (同步 Ctrl+C/X/V 基准)
  state.selectedPath = path;
  state.selectedType = node.dataset.type;
  if (!flash) return;  // 文件树点击: 仅更新 active/selected 标记, 不播放呼吸动画/不滚动
  // 示踪: 橙黄色单次呼吸高亮 + 滚动文件树定位
  document.querySelectorAll('.tree-node.flash').forEach(n => n.classList.remove('flash'));
  void node.offsetWidth;  // 强制 reflow 确保重复触发时动画重启
  node.classList.add('flash');
  const tree = els.tree;
  const tRect = tree.getBoundingClientRect();
  const nRect = node.getBoundingClientRect();
  const margin = 8;
  let delta = 0;
  if (nRect.top < tRect.top + margin) delta = nRect.top - tRect.top - margin;
  else if (nRect.bottom > tRect.bottom - margin) delta = nRect.bottom - tRect.bottom + margin;
  if (delta) tree.scrollBy({ top: delta, behavior: 'smooth' });
  setTimeout(() => node.classList.remove('flash'), 1300);
}

// 逐级展开文件所在的所有父目录, 使其节点进入 DOM (文件树懒加载, 折叠目录的子节点不在 DOM)
async function expandToPath(filePath) {
  if (!filePath) return;
  const parts = filePath.split('/');
  // 祖先目录链: 根'' -> 直接父目录 (不含文件自身). 例 'a/b/c.md' -> ['', 'a', 'a/b']
  const ancestors = [''];
  let cur = '';
  for (let i = 0; i < parts.length - 1; i++) {
    cur = cur ? cur + '/' + parts[i] : parts[i];
    ancestors.push(cur);
  }
  for (const dir of ancestors) {
    await expandFolder(dir);
  }
}

// 展开单个目录节点 (直接加载+渲染, 不走 row.click, 确保子节点入 DOM 后才 resolve)
async function expandFolder(dirPath) {
  if (dirPath === '' || state.expanded.has(dirPath)) return;  // 根已渲染 / 已展开
  const row = document.querySelector(`.tree-node[data-path="${cssEsc(dirPath)}"]`);
  if (!row) return;  // 父未展开致 row 不在 DOM, 安全跳过
  const wrap = row.parentElement;  // .tree-wrap
  const childWrap = wrap ? wrap.querySelector(':scope > .tree-children') : null;
  if (!childWrap) return;
  if (childWrap.classList.contains('open')) {  // DOM 已展开但 state 未同步 -> 补同步
    state.expanded.add(dirPath);
    return;
  }
  // 加载子项 (若未缓存)
  if (!state.treeCache.has(dirPath)) {
    try {
      state.treeCache.set(dirPath, await apiTree(dirPath));
    } catch (e) {
      return;  // 加载失败, 放弃展开
    }
  }
  const items = state.treeCache.get(dirPath) || [];
  // 子项 depth = 目录路径层数 ('a' 子项 depth 1, 'a/b' 子项 depth 2)
  const depth = dirPath.split('/').length;
  for (const child of items) {
    if (childWrap.querySelector(`[data-path="${cssEsc(child.path)}"]`)) continue;
    childWrap.appendChild(renderTreeNode(child, depth));
  }
  childWrap.classList.add('open');
  const twisty = row.querySelector('.twisty');
  if (twisty) twisty.textContent = '▼';
  state.expanded.add(dirPath);
}

function applyTreeFilter() {
  const q = els.treeFilter.value.trim().toLowerCase();
  document.querySelectorAll('.tree-node').forEach(n => {
    const name = n.querySelector('.name').textContent.toLowerCase();
    n.style.display = (q && !name.includes(q)) ? 'none' : '';
  });
}

async function loadAllFilesIndex() {
  try {
    state.allFiles = await apiAllFiles();
    state.allFilesLoaded = true;
  } catch (e) {
    state.allFiles = [];
  }
}

async function loadTree() {
  state.treeCache.clear();
  state.expanded.clear();
  els.tree.innerHTML = '';
  const items = await apiTree('');
  state.treeCache.set('', items);
  for (const item of filterRootItems(items)) {
    els.tree.appendChild(renderTreeNode(item, 0));
  }
  // cmd+P 索引改为懒加载：首次打开快速打开时再构建，避免启动时全仓扫描
}

// ============== 打开文件 ==============
function isMarkdown(ext) {
  const e = (ext || '').toLowerCase().replace(/^\./, '');
  return e === 'md' || e === 'markdown';
}

function isDrawio(ext) {
  const e = (ext || '').toLowerCase().replace(/^\./, '');
  return e === 'drawio' || e === 'dio';
}

function isImageFile(ext) {
  const e = (ext || '').toLowerCase().replace(/^\./, '');
  return ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'ico'].includes(e);
}

// <center>![](xxx)</center> 预处理: Vditor IR / marked 把 <center> 当 HTML 代码块,
// 不解析内部 ![]() markdown 图片语法 (整段当代码字面显示) -> 预处理提取为 <img> 标签,
// 让 applyImageRewrite 能改写 src 为 /api/reader/raw。
function preprocessCenterImages(content) {
  if (!content) return content;
  return content.replace(/<center>\s*!\[[^\]]*\]\(([^)]+)\)\s*<\/center>/gi,
    '<img src="$1" style="display:block;margin:0 auto;max-width:100%">');
}

// 把 md 内嵌 <img> 相对路径重写到 /api/reader/raw (浏览器直拉二进制图)。
// 外链 / data-URI / mailto 跳过 (浏览器直连, 非本地资产); drawio 内联图跳过
// (applyDrawioInline 处理, 且该步已把 drawio img replaceWith 出 DOM)。
function applyImageRewrite(root, basePath) {
  if (!root) return;
  root.querySelectorAll('img').forEach(img => {
    const src = img.getAttribute('src') || '';
    if (!src) return;
    if (/^(https?:)?\/\//i.test(src) || src.startsWith('data:') || src.startsWith('mailto:')) return;
    if (/\.(drawio|dio)$/i.test(src)) return;
    const resolved = resolveRelative(basePath, src);
    if (!resolved) return;
    img.setAttribute('src', '/api/reader/raw?path=' + encodeURIComponent(resolved));
  });
}

// drawio 图形化渲染: 与内联一致, 直接在主页面用 GraphViewer 渲染
// 无 iframe (直接展示), 无提示文本, 自然高度无内部滚动条 (由内容区滚动控制)
// viewer-static.min.js 懒加载 (ensureDrawioViewer); 加载失败显示错误占位
function renderDrawio(file) {
  exitEditMode();
  els.welcome.hidden = true;
  els.viewer.hidden = false;
  els.editorHost.hidden = true;

  const xml = file.content || '';
  els.viewer.innerHTML = '<div class="drawio-standalone"></div>';
  const host = els.viewer.querySelector('.drawio-standalone');

  if (!xml.trim()) {
    host.innerHTML = '<div class="md-drawio-error">📐 文件为空</div>';
    els.outlineBody.innerHTML = '<div class="outline-empty">drawio 图形无目录大纲</div>';
    return;
  }

  const node = document.createElement('div');
  node.className = 'mxgraph';
  node.style.cssText = 'background:#fff;max-width:100%';
  node.dataset.mxgraph = JSON.stringify({
    highlight: '#0000ff',
    nav: true,
    resize: true,
    xml: xml
  });
  host.appendChild(node);

  ensureDrawioViewer().then(() => {
    if (!host.isConnected) return; // 文件已切换, 旧节点脱离 DOM
    if (window.GraphViewer) {
      try { window.GraphViewer.processElements(); } catch (e) {}
    }
  }).catch(err => {
    if (host.isConnected) {
      host.innerHTML = '<div class="md-drawio-error">📐 ' + escHtml(err.message) + '</div>';
    }
  });

  // 代码文件无大纲
  els.outlineBody.innerHTML = '<div class="outline-empty">drawio 图形无目录大纲</div>';
}

// 图片文件独立查看 (png/jpg/gif/webp/bmp/svg/ico): 单图居中, 只读。
// 字节经 /api/reader/raw 加载 (绕过 detect_and_read 文本解码)。
function renderImage(file) {
  exitEditMode();
  els.welcome.hidden = true;
  els.viewer.hidden = false;
  els.editorHost.hidden = true;

  els.viewer.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'image-standalone';
  wrap.style.cssText = 'padding:16px;text-align:center';
  const img = document.createElement('img');
  img.className = 'image-standalone-img';
  img.alt = file.path;
  img.style.cssText = 'display:inline-block;max-width:100%;height:auto;background:#fff;border-radius:4px;box-shadow:0 1px 6px rgba(0,0,0,.15)';
  img.src = '/api/reader/raw?path=' + encodeURIComponent(file.path);
  wrap.appendChild(img);
  els.viewer.appendChild(wrap);

  els.outlineBody.innerHTML = '<div class="outline-empty">图片无目录大纲</div>';
}

function languageForFile(ext) {
  const e = (ext || '').toLowerCase().replace(/^\./, '');
  if (isMarkdown(e)) return markdown();
  if (e === 'py') return python();
  if (['cpp', 'c', 'cc', 'cxx', 'h', 'hpp', 'hh'].includes(e)) return cpp();
  if (e === 'rs') return rust();
  if (['ts', 'tsx', 'js', 'jsx', 'mjs'].includes(e)) return javascript();
  if (e === 'json') return json();
  if (['html', 'htm', 'xml', 'drawio', 'dio'].includes(e)) return html();
  if (e === 'css') return css();
  if (['yaml', 'yml'].includes(e)) return yaml();
  return [];
}

function highlightLangForFile(ext) {
  const e = (ext || '').toLowerCase().replace(/^\./, '');
  if (isMarkdown(e)) return 'markdown';
  if (e === 'py') return 'python';
  if (['cpp', 'c', 'cc', 'cxx', 'h', 'hpp', 'hh'].includes(e)) return 'cpp';
  if (e === 'rs') return 'rust';
  if (['ts', 'tsx'].includes(e)) return 'typescript';
  if (['js', 'jsx', 'mjs'].includes(e)) return 'javascript';
  if (e === 'json') return 'json';
  if (['html', 'htm', 'xml', 'drawio', 'dio'].includes(e)) return 'xml';
  if (e === 'css') return 'css';
  if (['yaml', 'yml'].includes(e)) return 'yaml';
  if (e === 'sh' || e === 'bash' || e === 'zsh') return 'bash';
  if (e === 'lua') return 'lua';
  if (e === 'sql') return 'sql';
  return '';
}

async function openFile(path, opts = {}) {
  try {
    // 切换前保存当前 tab 的滚动位置 (初始加载时跳过，避免覆盖恢复的 scrollTop)
    if (state.currentFile) saveCurrentTabState();

    const file = await apiFile(path);
    state.currentFile = file;
    state.lastSavedContent = file.content;
    state.isDirty = false;

    // 注册/激活 tab
    ensureTab(path, opts.edit);

    els.currentPath.textContent = file.path;
    els.sbEncoding.textContent = '编码: ' + file.encoding;
    els.sbInfo.textContent = file.extension + ' · ' + file.content.length + ' 字符';
    setSaveStatus('已加载', 'saved');
    els.editToggle.disabled = false;
    els.editToggle.classList.remove('edit-active');  // 非 .md 不绿; .md 分支 setMdToggleState 会加回
    // .drawio / 图片强制只读: 禁用编辑按钮 (仅可查看)
    if (isDrawio(file.extension) || isImageFile(file.extension)) {
      els.editToggle.disabled = true;
    }
    els.editToggle.textContent = (opts.edit || getTab(path)?.editMode) ? '预览' : '编辑';
    els.btnShare.disabled = state.tabs.length === 0;
    els.btnDownload.disabled = state.tabs.filter(t => !t.isHistory).length === 0;
    els.btnHistory.disabled = false;
    // 打开新文件时关闭历史面板(避免显示旧文件历史)
    if (!els.historyPanel.hidden) {
      els.historyPanel.hidden = true;
    }
    // 大纲面板: md 文件按偏好显示, 非 md 文件隐藏
    if (isMarkdown(file.extension)) {
      els.outlinePanel.hidden = localStorage.getItem('reader.outlineShown') === '0';
    } else {
      els.outlinePanel.hidden = true;
    }

    const wantEdit = opts.edit || getTab(path)?.editMode;
    // .drawio 强制只读 + 图形化渲染 (viewer.draw.io embed)
    if (isDrawio(file.extension)) {
      renderDrawio(file);
    } else if (isImageFile(file.extension)) {
      renderImage(file);
    } else if (isMarkdown(file.extension)) {
      // .md 编辑模式选择:
      //   - 含 ```mermaid 块 → CM6 纯文本编辑 (renderCode). Vditor IR 对 mermaid 代码块在真实
      //     流程下 getValue 会丢码/错乱/重复 (4+ 次客诉, 最小复现未抓到确切路径), CM6 不 mutate
      //     内容, 数据安全. 代价: 失 Vditor IR 所见即所得, 改为源码编辑.
      //   - 无 mermaid → Vditor IR 编辑 (getMdEditMode) 或 renderMarkdown 只读
      const hasMermaid = /```mermaid\b/.test(file.content || '');
      if (getMdEditMode() && hasMermaid) {
        enterEditMode();   // CM6 纯文本编辑器 (state.editor = new EditorView), 不 mutate 内容, mermaid 安全
        setMdToggleState(true);
      } else if (getMdEditMode()) {
        renderMarkdownVditor(file);
      } else {
        renderMarkdown(file);
        setMdToggleState(false);
      }
    } else {
      renderCode(file);
    }
    if (wantEdit && !isDrawio(file.extension) && !isImageFile(file.extension) && !isMarkdown(file.extension)) enterEditMode();
    // 先逐级展开父目录链 (懒加载下折叠目录的文件节点不在 DOM), 再高亮定位
    // fromTree (文件树点击): 仅更新 active 不 flash; 其他入口 (tab/quickopen/搜索): flash 示踪
    await expandToPath(path);
    highlightActiveTreeNode(path, !opts.fromTree);

    // 手机端: 选中文件后自动折叠侧栏 (用户可自行再展开)
    if (isMobile() && !state.sidebarCollapsed) {
      state.sidebarCollapsed = true;
      els.layout.classList.add('collapsed');
      savePref('reader.sidebarCollapsed', 1);
    }

    // 恢复该 tab 之前保存的滚动位置 (新文档 scrollTop=0 即最上层)
    const tab = getTab(path);
    renderTabs();
    persistSession();
    refreshArchiveBtn();
    setTimeout(() => {
      const scroller = els.contentBody;
      if (scroller) scroller.scrollTop = (tab && tab.scrollTop) ? tab.scrollTop : 0;
    }, 0);

    // 批注: 加载当前文件批注 + 渲染面板 (面板未开也预取, 开启即可见)
    els.btnComments.disabled = false;
    loadComments(path).catch((err) => {
      console.warn('[comments] loadComments failed:', err);
    });
  } catch (e) {
    setSaveStatus('打开失败: ' + e.message, 'error');
  }
}

// ============== Tab 系统 ==============
function ensureTab(path, editMode) {
  let tab = state.tabs.find(t => t.path === path);
  if (!tab) {
    tab = {
      path,
      name: path.split('/').pop(),
      pinned: false,
      dirty: false,
      scrollTop: 0,
      editMode: !!editMode,
    };
    state.tabs.push(tab);
  } else if (editMode) {
    tab.editMode = true;
  }
  state.activeTabPath = path;
}

function getTab(path) {
  return state.tabs.find(t => t.path === path);
}

function saveCurrentTabState() {
  if (!state.activeTabPath) return;
  const tab = getTab(state.activeTabPath);
  if (!tab) return;
  tab.editMode = state.vditor ? true : !els.editorHost.hidden;
  tab.dirty = state.isDirty;
  if (els.contentBody) tab.scrollTop = els.contentBody.scrollTop;
}

function switchTab(path) {
  if (path === state.activeTabPath) {
    // 已选中 tab: 不重新加载内容, 仅触发文件树示踪定位
    expandToPath(path).then(() => highlightActiveTreeNode(path, true));
    return;
  }
  // 保存当前 tab 编辑内容到内存 (不落盘)
  if (state.editor && state.currentFile) {
    state.currentFile.content = state.editor.state.doc.toString();
  }
  saveCurrentTabState();
  // 历史版本 tab 直接重新渲染 (不重新请求 API, 用已存内容)
  const tab = getTab(path);
  if (tab && tab.isHistory && state.currentFile && tab.sourcePath === state.currentFile.path) {
    // 切回历史 tab: 重新展示
    state.activeTabPath = path;
    renderTabs();
    persistSession();
    return;
  }
  if (tab && tab.isHistory) {
    // 切到历史 tab: 重新加载该版本内容
    state.activeTabPath = path;
    renderTabs();
    openHistoryVersion(tab.sourcePath, tab.commit);
    return;
  }
  // 普通 tab: 如果当前是历史 tab, 切回时重新打开真实文件
  openFile(path);
}

function closeTab(path) {
  const idx = state.tabs.findIndex(t => t.path === path);
  if (idx === -1) return;
  const tab = state.tabs[idx];
  // 历史版本 tab 直接关闭, 不提示未保存
  if (!tab.isHistory && tab.dirty && !confirm(`"${tab.name}" 有未保存改动,确认关闭?`)) return;

  state.tabs.splice(idx, 1);

  if (state.activeTabPath === path) {
    // 切到相邻 tab
    const next = state.tabs[idx] || state.tabs[idx - 1];
    if (next) {
      openFile(next.path);
    } else {
      // 无 tab, 显示欢迎页
      state.activeTabPath = null;
      state.currentFile = null;
      els.welcome.hidden = false;
      els.viewer.hidden = true;
      els.editorHost.hidden = true;
      els.currentPath.textContent = '未打开文件';
      els.editToggle.disabled = true;
      els.btnHistory.disabled = true;
      els.btnShare.disabled = true;
      els.btnDownload.disabled = true;
      els.btnArchive.disabled = true;
      els.outlinePanel.hidden = true;
      els.historyPanel.hidden = true;
      setSaveStatus('就绪', 'muted');
      if (state.editor) { state.editor.destroy(); state.editor = null; }
    }
  }
  renderTabs();
  persistSession();
}

function togglePinTab(path) {
  const tab = getTab(path);
  if (!tab || tab.isHistory) return;  // 历史 tab 不可固定
  tab.pinned = !tab.pinned;
  state.tabs.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
  renderTabs();
  persistSession();
}

function renderTabs() {
  els.tabBar.innerHTML = '';
  for (const tab of state.tabs) {
    const el = document.createElement('div');
    el.className = 'tab' + (tab.path === state.activeTabPath ? ' active' : '') +
                   (tab.pinned ? ' pinned' : '') + (tab.dirty ? ' dirty' : '') +
                   (tab.isHistory ? ' history' : '');
    el.dataset.path = tab.path;

    // 历史 tab 用 📜 标记, 不可固定
    if (!tab.isHistory) {
      const pin = document.createElement('span');
      pin.className = 'tab-pin';
      pin.textContent = '📌';
      pin.title = tab.pinned ? '取消固定' : '固定';
      pin.addEventListener('click', (e) => { e.stopPropagation(); togglePinTab(tab.path); });
      el.appendChild(pin);
    } else {
      const mark = document.createElement('span');
      mark.className = 'tab-pin';
      mark.textContent = '📜';
      mark.title = '历史版本 (只读)';
      el.appendChild(mark);
    }

    const name = document.createElement('span');
    name.className = 'tab-name';
    name.textContent = tab.name;
    name.title = tab.path;
    el.appendChild(name);

    const close = document.createElement('span');
    close.className = 'tab-close';
    close.textContent = '×';
    close.title = '关闭';
    close.addEventListener('click', (e) => { e.stopPropagation(); closeTab(tab.path); });
    el.appendChild(close);

    el.addEventListener('click', () => switchTab(tab.path));
    el.addEventListener('auxclick', (e) => {
      if (e.button === 1) { e.preventDefault(); closeTab(tab.path); }
    });
    el.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      showTabMenu(e.clientX, e.clientY, tab.path);
    });
    els.tabBar.appendChild(el);
  }
}

// ============== Tab 右键菜单 ==============
function showTabMenu(x, y, path) {
  els.tabMenu.dataset.path = path;
  els.tabMenu.style.left = x + 'px';
  els.tabMenu.style.top = y + 'px';
  els.tabMenu.hidden = false;
}

function hideTabMenu() {
  els.tabMenu.hidden = true;
}

function closeAllTabs() {
  const dirtyTabs = state.tabs.filter(t => t.dirty && !t.pinned);
  if (dirtyTabs.length > 0) {
    if (!confirm(`有 ${dirtyTabs.length} 个未保存的 tab,确认全部关闭?`)) return;
  }
  state.tabs = state.tabs.filter(t => t.pinned);
  if (!state.tabs.find(t => t.path === state.activeTabPath)) {
    state.activeTabPath = state.tabs[0]?.path || null;
  }
  if (state.activeTabPath) {
    openFile(state.activeTabPath);
  } else {
    state.currentFile = null;
    els.welcome.hidden = false;
    els.viewer.hidden = true;
    els.editorHost.hidden = true;
    els.currentPath.textContent = '未打开文件';
    els.editToggle.disabled = true;
    els.btnHistory.disabled = true;
    els.btnShare.disabled = true;
    els.btnDownload.disabled = true;
    els.btnArchive.disabled = true;
    els.outlinePanel.hidden = true;
    els.historyPanel.hidden = true;
    els.commentPanel.hidden = true;
    els.btnComments.disabled = true;
    state.comments = [];
    renderComments();
    updateCommentBadge();
    setSaveStatus('就绪', 'muted');
    if (state.editor) { state.editor.destroy(); state.editor = null; }
  }
  renderTabs();
  persistSession();
}

function closeOthers(keepPath) {
  const dirtyTabs = state.tabs.filter(t => t.dirty && t.path !== keepPath && !t.pinned);
  if (dirtyTabs.length > 0) {
    if (!confirm(`有 ${dirtyTabs.length} 个未保存的 tab,确认关闭其他?`)) return;
  }
  state.tabs = state.tabs.filter(t => t.pinned || t.path === keepPath);
  state.activeTabPath = keepPath;
  openFile(keepPath);
}

function closeSide(keepPath, side) {
  // side: 'left' | 'right'
  const idx = state.tabs.findIndex(t => t.path === keepPath);
  if (idx === -1) return;
  const toClose = side === 'left'
    ? state.tabs.slice(0, idx)
    : state.tabs.slice(idx + 1);
  const dirtyTabs = toClose.filter(t => t.dirty && !t.pinned);
  if (dirtyTabs.length > 0) {
    if (!confirm(`有 ${dirtyTabs.length} 个未保存的 tab,确认关闭${side === 'left' ? '左侧' : '右侧'}?`)) return;
  }
  if (side === 'left') {
    state.tabs = state.tabs.filter((t, i) => t.pinned || i >= idx);
  } else {
    state.tabs = state.tabs.filter((t, i) => t.pinned || i <= idx);
  }
  renderTabs();
  persistSession();
}

els.tabMenu.addEventListener('click', (e) => {
  const item = e.target.closest('.tab-menu-item');
  if (!item) return;
  const action = item.dataset.action;
  const path = els.tabMenu.dataset.path;
  hideTabMenu();
  switch (action) {
    case 'pin': togglePinTab(path); break;
    case 'close': closeTab(path); break;
    case 'close-others': closeOthers(path); break;
    case 'close-left': closeSide(path, 'left'); break;
    case 'close-right': closeSide(path, 'right'); break;
    case 'close-all': closeAllTabs(); break;
  }
});

// 点击其他地方关闭菜单
document.addEventListener('click', (e) => {
  if (!els.tabMenu.hidden && !els.tabMenu.contains(e.target)) hideTabMenu();
  if (!els.treeMenu.hidden && !els.treeMenu.contains(e.target)) hideTreeMenu();
  if (!els.commentMenu.hidden && !els.commentMenu.contains(e.target)) hideCommentMenu();
});
document.addEventListener('contextmenu', (e) => {
  // 非 tab/tree-node 上的右键, 关闭菜单
  if (!e.target.closest('.tab')) hideTabMenu();
  if (!e.target.closest('.tree-node')) hideTreeMenu();
  // 批注右键: 在 #viewer 或 #vditor-host 内有文本选区 → 显示"添加批注"
  if (!els.commentMenu.hidden && !els.commentMenu.contains(e.target)) hideCommentMenu();
  const inViewer = e.target.closest('#viewer');
  const inVditor = e.target.closest('#vditor-host');
  if ((inViewer || inVditor) && state.currentFile) {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    if (text.length > 0) {
      e.preventDefault();
      showCommentMenu(e.clientX, e.clientY);
    }
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (!els.tabMenu.hidden) hideTabMenu();
    if (!els.treeMenu.hidden) hideTreeMenu();
    if (!els.commentMenu.hidden) hideCommentMenu();
    if (!els.commentEditorPanel.hidden) hideCommentEditor();
  }
});

// ============== 文件树右键菜单 (创建/删除/重命名) ==============
function showTreeMenu(x, y, item) {
  // item: null 表示在空白处右键 (根目录)
  els.treeMenu.dataset.path = item ? item.path : '';
  els.treeMenu.dataset.type = item ? item.type : 'root';
  // 文件类型禁用"新建"项
  const isFolder = !item || item.type === 'folder';
  els.treeMenu.querySelector('[data-action="new-file"]').style.display = isFolder ? '' : 'none';
  els.treeMenu.querySelector('[data-action="new-folder"]').style.display = isFolder ? '' : 'none';
  // 根目录空白处禁用重命名/删除
  const hasTarget = !!item;
  els.treeMenu.querySelector('[data-action="rename"]').style.display = hasTarget ? '' : 'none';
  els.treeMenu.querySelector('[data-action="delete"]').style.display = hasTarget ? '' : 'none';
  const seps = els.treeMenu.querySelectorAll('.tab-menu-sep');
  if (seps[0]) seps[0].style.display = hasTarget ? '' : 'none';
  // 复制/剪切需要目标; 粘贴需要剪贴板非空
  els.treeMenu.querySelector('[data-action="copy"]').style.display = hasTarget ? '' : 'none';
  els.treeMenu.querySelector('[data-action="cut"]').style.display = hasTarget ? '' : 'none';
  els.treeMenu.querySelector('[data-action="paste"]').style.display = state.clipboard ? '' : 'none';
  if (seps[1]) seps[1].style.display = (hasTarget || state.clipboard) ? '' : 'none';

  els.treeMenu.style.left = x + 'px';
  els.treeMenu.style.top = y + 'px';
  els.treeMenu.hidden = false;
}

function hideTreeMenu() {
  els.treeMenu.hidden = true;
}

// 侧栏空白处右键 → 根目录新建 (整个 sidebar 区域, 不止 #tree)
els.sidebar.addEventListener('contextmenu', (e) => {
  if (e.target.closest('.tree-node')) return; // 节点上已有自己的 handler
  e.preventDefault();
  e.stopPropagation(); // 阻止冒泡到 document, 避免立即 hideTreeMenu
  showTreeMenu(e.clientX, e.clientY, null);
});

// 树点击 capture: 跟踪当前选中节点 (供 Ctrl+C/X/V)
els.tree.addEventListener('click', (e) => {
  const row = e.target.closest('.tree-node');
  if (!row) return;
  els.tree.querySelectorAll('.tree-node.selected').forEach(n => n.classList.remove('selected'));
  row.classList.add('selected');
  state.selectedPath = row.dataset.path;
  state.selectedType = row.dataset.type;
}, true);

// 树空白区 = 根目录放置区 (拖到非文件夹行或空白)
els.tree.addEventListener('dragover', (e) => {
  if (e.target.closest('.tree-node[data-type="folder"]')) return; // 文件夹自己处理
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  els.tree.classList.add('drag-over');
});
els.tree.addEventListener('dragleave', (e) => {
  if (!els.tree.contains(e.relatedTarget)) els.tree.classList.remove('drag-over');
});
els.tree.addEventListener('drop', (e) => {
  if (e.target.closest('.tree-node[data-type="folder"]')) return;
  e.preventDefault();
  els.tree.classList.remove('drag-over');
  const src = e.dataTransfer.getData('text/plain');
  if (src) handleDropMove(src, '');
});

// dragend (drop 后必触发) 兜底清理: 文件夹行 drop 因 stopPropagation 不冒泡,
// 根 #tree 上由 hover 残留的 drag-over 不会被自身 drop 清除 -> 蓝虚线不消失
document.addEventListener('dragend', () => {
  els.tree.classList.remove('drag-over');
  els.tree.querySelectorAll('.drag-over').forEach((n) => n.classList.remove('drag-over'));
});

els.treeMenu.addEventListener('click', (e) => {
  const item = e.target.closest('.tab-menu-item');
  if (!item) return;
  const action = item.dataset.action;
  const path = els.treeMenu.dataset.path;
  const type = els.treeMenu.dataset.type;
  hideTreeMenu();
  handleTreeAction(action, path, type);
});

async function handleTreeAction(action, path, type) {
  if (action === 'new-file') {
    const name = prompt('输入新文件名 (含后缀, 如 note.md):');
    if (!name) return;
    const dir = type === 'root' ? '' : path;
    const newPath = dir ? dir + '/' + name.trim() : name.trim();
    try {
      await apiCreate(newPath, 'file');
      await refreshTreePath(dir);
      // 创建后直接打开进入编辑
      await openFile(newPath);
      enterEditMode();
    } catch (e) { alert('创建失败: ' + e.message); }
  } else if (action === 'new-folder') {
    const name = prompt('输入新文件夹名:');
    if (!name) return;
    const dir = type === 'root' ? '' : path;
    const newPath = dir ? dir + '/' + name.trim() : name.trim();
    try {
      await apiCreate(newPath, 'folder');
      await refreshTreePath(dir);
    } catch (e) { alert('创建失败: ' + e.message); }
  } else if (action === 'rename') {
    const oldName = path.split('/').pop();
    const newName = prompt('重命名为:', oldName);
    if (!newName || newName === oldName) return;
    const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
    const newPath = dir ? dir + '/' + newName.trim() : newName.trim();
    try {
      // 被引用资源 (图片/drawio) 走 rename-ref: 重写所有 md 引用 + git 备份 (历史面板可还原)
      const ext = '.' + (path.split('.').pop() || '').toLowerCase();
      let refCount = -1;
      if (isImageFile(ext) || isDrawio(ext)) {
        const resp = await apiRenameRef(path, newPath);
        refCount = (resp.rewritten || []).length;
      } else {
        await apiRename(path, newPath);
      }
      // 更新 tab 引用
      const tab = getTab(path);
      if (tab) {
        tab.path = newPath;
        tab.name = newName.trim();
      }
      await refreshTreePath(dir);
      renderTabs();
      persistSession();
      if (state.activeTabPath === newPath) {
        // 当前 tab 被重命名, 重新打开
        openFile(newPath);
      } else if (refCount >= 0) {
        setSaveStatus(`改名 + 更新 ${refCount} 处引用 (已 git 备份)`, 'saved');
      }
    } catch (e) { alert('重命名失败: ' + e.message); }
  } else if (action === 'delete') {
    if (!confirm(`确认将 "${path}" 移到回收站?` + (type === 'folder' ? '\n(文件夹整体移入)' : ''))) return;
    try {
      await apiDelete(path);
      // 关闭相关 tab
      const toClose = state.tabs.filter(t => t.path === path || t.path.startsWith(path + '/'));
      for (const t of toClose) {
        const idx = state.tabs.findIndex(x => x.path === t.path);
        if (idx >= 0) state.tabs.splice(idx, 1);
      }
      if (!state.tabs.find(t => t.path === state.activeTabPath)) {
        state.activeTabPath = state.tabs[0]?.path || null;
      }
      const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
      await refreshTreePath(dir);
      if (!els.trashPanel.hidden) loadTrash();
      renderTabs();
      persistSession();
      if (state.activeTabPath) openFile(state.activeTabPath);
      else {
        state.currentFile = null;
        els.welcome.hidden = false;
        els.viewer.hidden = true;
        els.editorHost.hidden = true;
      }
    } catch (e) { alert('删除失败: ' + e.message); }
  } else if (action === 'copy') {
    state.clipboard = { path, type, cut: false };
    setSaveStatus('已复制', 'ok');
  } else if (action === 'cut') {
    state.clipboard = { path, type, cut: true };
    setSaveStatus('已剪切', 'ok');
  } else if (action === 'paste') {
    const targetDir = !path || type === 'root' ? '' : (type === 'folder' ? path : (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''));
    await pasteInto(targetDir);
  }
}

/**
 * 将 srcPath 移动到 targetDir (根目录 targetDir='')
 * 拖拽放下的通用处理。
 */
async function handleDropMove(srcPath, targetDir) {
  const name = srcPath.split('/').pop();
  const newPath = targetDir ? targetDir + '/' + name : name;
  if (newPath === srcPath) return;
  if (targetDir === srcPath || targetDir.startsWith(srcPath + '/')) {
    alert('不能移动到自身或子目录内');
    return;
  }
  try {
    await apiRename(srcPath, newPath);
    relocateTabs(srcPath, newPath);
    // 刷新全部树 (清理缓存后重绘)
    state.treeCache.clear();
    await refreshTreePath('');
    renderTabs();
    persistSession();
  } catch (e) {
    alert('移动失败: ' + e.message);
  }
}

/**
 * 将剪贴板内容粘贴到 targetDir (根目录 targetDir='')。
 * 复制: 若文件名冲突自动追加 " 副本" / " 副本2"...
 * 剪切: 使用 rename (移动), 冲突时 alert。
 */
async function pasteInto(targetDir) {
  const cb = state.clipboard;
  if (!cb) { alert('剪贴板为空'); return; }
  const srcPath = cb.path;
  const name = srcPath.split('/').pop();
  if (targetDir === srcPath || targetDir.startsWith(srcPath + '/')) {
    alert('不能粘贴到自身或子目录内');
    return;
  }
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')) : '';
  const stem = ext ? name.slice(0, name.lastIndexOf('.')) : name;
  let newPath = targetDir ? targetDir + '/' + name : name;
  if (cb.cut) {
    if (newPath === srcPath) { state.clipboard = null; return; }
    try {
      await apiRename(srcPath, newPath);
      state.clipboard = null;
      relocateTabs(srcPath, newPath);
      state.treeCache.clear();
      await refreshTreePath(targetDir);
      renderTabs();
      persistSession();
    } catch (e) { alert('剪切失败: ' + e.message); }
  } else {
    let candidate = newPath;
    let attempt = 0;
    while (true) {
      try {
        await apiCopy(srcPath, candidate);
        break;
      } catch (e) {
        if (String(e.message).includes('target exists') || String(e.message).includes('409')) {
          attempt++;
          const sfx = attempt === 1 ? ' 副本' : ' 副本' + attempt;
          const candName = stem + sfx + ext;
          candidate = targetDir ? targetDir + '/' + candName : candName;
        } else {
          alert('复制失败: ' + e.message);
          return;
        }
      }
    }
    state.treeCache.clear();
    await refreshTreePath(targetDir);
  }
}

/**
 * 文件/夹移动后更新所有引用该路径的 tab 和 activeTabPath。
 */
function relocateTabs(oldPath, newPath) {
  for (const t of state.tabs) {
    if (t.path === oldPath) {
      t.path = newPath;
      t.name = newPath.split('/').pop();
    } else if (t.path.startsWith(oldPath + '/')) {
      t.path = newPath + t.path.slice(oldPath.length);
    }
  }
  if (state.activeTabPath === oldPath) {
    state.activeTabPath = newPath;
  } else if (state.activeTabPath && state.activeTabPath.startsWith(oldPath + '/')) {
    state.activeTabPath = newPath + state.activeTabPath.slice(oldPath.length);
  }
  if (state.currentFile && (state.currentFile.path === oldPath || state.currentFile.path.startsWith(oldPath + '/'))) {
    state.currentFile.path = state.activeTabPath;
    // content 不变, path 更新后下次保存会写入新位置
  }
}

// 刷新树: 清缓存重新渲染, 保留已展开目录状态 (renderTreeNode 会自动重新展开)
async function refreshTreePath(dir) {
  state.treeCache.delete(dir);
  state.treeCache.delete('');
  // 文件树已变化：下次 cmd+P 时重建索引，避免 stale
  state.allFilesLoaded = false;
  const expanded = new Set(state.expanded);
  // 加载根（cmd+P 索引保持懒加载，不随树刷新全量重建）
  const items = await apiTree('');
  state.treeCache.set('', items);
  // 重新渲染根 (保留 expanded, renderTreeNode 内 queueMicrotask 会自动展开)
  els.tree.innerHTML = '';
  for (const item of filterRootItems(items)) {
    els.tree.appendChild(renderTreeNode(item, 0));
  }
}

// ============== 版本历史 ==============
async function loadHistory(path) {
  els.historyBody.innerHTML = '<div class="outline-empty">加载中...</div>';
  try {
    const commits = await apiHistory(path);
    if (commits.length === 0) {
      els.historyBody.innerHTML = '<div class="outline-empty">无提交历史</div>';
      return;
    }
    els.historyBody.innerHTML = '';
    commits.forEach((c) => {
      const item = document.createElement('div');
      item.className = 'history-item';
      item.innerHTML = '<div class="history-info">' +
        '<div class="history-hash">' + escHtml(c.short) + '</div>' +
        '<div class="history-date">' + escHtml(c.date) + '</div>' +
        '<div class="history-msg">' + escHtml(c.message) + '</div>' +
        '</div>' +
        '<button class="history-restore-btn" title="恢复到此版本">↩</button>';
      // 点击条目 (除按钮外) → 只读查看该版本
      item.addEventListener('click', (e) => {
        if (e.target.closest('.history-restore-btn')) return;
        openHistoryVersion(path, c);
      });
      // 恢复按钮: 用该版本内容覆盖当前文件 + git commit
      item.querySelector('.history-restore-btn').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('恢复 ' + path + ' 到版本 ' + c.short + '?\n当前内容将被覆盖 (可再次从历史恢复)。')) return;
        try {
          setSaveStatus('恢复中...', 'saving');
          await apiRestore(path, c.hash);
          els.historyPanel.hidden = true;
          await openFile(path);
          setSaveStatus('已恢复到 ' + c.short, 'saved');
        } catch (err) {
          alert('恢复失败: ' + err.message);
          setSaveStatus('恢复失败', 'error');
        }
      });
      els.historyBody.appendChild(item);
    });
  } catch (e) {
    els.historyBody.innerHTML = '<div class="outline-empty">加载失败: ' + escHtml(e.message) + '</div>';
  }
}

// 历史版本作为只读 tab 打开
async function openHistoryVersion(path, commit) {
  // tab 标识: 历史版本用特殊 path 区分
  const tabPath = path + '@' + commit.short;
  const tabName = (path.split('/').pop()) + '@' + commit.short;

  // 已存在则切换
  let tab = state.tabs.find(t => t.path === tabPath);
  if (tab) {
    switchTab(tabPath);
    return;
  }

  // 先保存当前 tab 状态
  saveCurrentTabState();

  // 注册历史 tab (标记为只读历史, 不可编辑)
  tab = {
    path: tabPath,
    name: tabName,
    pinned: false,
    dirty: false,
    scrollTop: 0,
    editMode: false,
    isHistory: true,
    sourcePath: path,
    hash: commit.hash,
    commit: commit,
  };
  state.tabs.push(tab);
  state.activeTabPath = tabPath;

  // 渲染 tab
  renderTabs();
  els.currentPath.textContent = path + ' @ ' + commit.short;
  els.sbEncoding.textContent = '历史版本 (只读)';
  els.sbInfo.textContent = commit.date + ' · ' + commit.author;
  setSaveStatus('历史版本', 'muted');
  els.editToggle.disabled = true;  // 历史版本不可编辑
  els.btnArchive.disabled = true;  // 历史版本不可归档
  els.welcome.hidden = true;
  els.editorHost.hidden = true;
  els.viewer.hidden = false;
  els.outlinePanel.hidden = true;

  // 占位
  els.viewer.innerHTML = '<pre class="code-view">加载历史版本...</pre>';

  try {
    const v = await apiVersion(path, commit.hash);
    // 按源文件扩展名渲染
    const ext = '.' + (path.split('.').pop() || '');
    const fakeFile = {
      path: path, content: v.content, encoding: 'utf-8',
      language: '', extension: ext,
    };
    state.currentFile = fakeFile;
    if (isMarkdown(ext)) {
      renderMarkdown(fakeFile);
    } else {
      renderCode(fakeFile);
    }
    // 在内容顶部加历史版本信息条
    const banner = document.createElement('div');
    banner.className = 'history-banner';
    banner.innerHTML = '📜 历史版本 · <b>' + escHtml(commit.short) + '</b> · ' +
                       escHtml(commit.date) + ' · ' + escHtml(commit.message);
    els.viewer.insertBefore(banner, els.viewer.firstChild);
  } catch (e) {
    els.viewer.innerHTML = '<pre class="code-view">加载失败: ' + escHtml(e.message) + '</pre>';
  }
  persistSession();
}

els.btnHistory.addEventListener('click', () => {
  if (!state.currentFile) return;
  const hidden = els.historyPanel.hidden;
  els.trashPanel.hidden = true;
  els.historyPanel.hidden = !hidden;
  if (hidden) loadHistory(state.currentFile.path);
});

// ============== 回收站 ==============
let trashSelection = new Set();

async function loadTrash() {
  els.trashBody.innerHTML = '<div class="outline-empty">加载中...</div>';
  trashSelection = new Set();
  els.trashSelectAll.checked = false;
  updateTrashToolbar();
  try {
    const items = await apiTrashList();
    if (items.length === 0) {
      els.trashBody.innerHTML = '<div class="outline-empty">回收站为空</div>';
      return;
    }
    els.trashBody.innerHTML = '';
    items.forEach((it) => {
      const item = document.createElement('div');
      item.className = 'trash-item';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'trash-cb';
      cb.dataset.path = it.path;
      cb.addEventListener('change', () => {
        if (cb.checked) trashSelection.add(it.path);
        else trashSelection.delete(it.path);
        const allCbs = els.trashBody.querySelectorAll('.trash-cb');
        els.trashSelectAll.checked = allCbs.length > 0 && [...allCbs].every(c => c.checked);
        updateTrashToolbar();
      });
      const info = document.createElement('div');
      info.className = 'trash-info';
      const date = new Date(it.deleted_at * 1000);
      const dateStr = isNaN(date.getTime()) ? '' : date.toLocaleString();
      info.innerHTML = '<div class="trash-path">' + escHtml(it.path) + '</div>' +
        '<div class="trash-meta">' + escHtml(dateStr) + ' · ' + escHtml(formatSize(it.size)) + '</div>';
      item.append(cb, info);
      els.trashBody.appendChild(item);
    });
  } catch (e) {
    els.trashBody.innerHTML = '<div class="outline-empty">加载失败: ' + escHtml(e.message) + '</div>';
  }
}

function formatSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

function updateTrashToolbar() {
  const count = trashSelection.size;
  els.btnTrashRestore.disabled = count === 0;
  els.btnTrashPurge.disabled = count === 0;
  els.btnTrashRestore.textContent = count > 0 ? '↩ 还原 (' + count + ')' : '↩ 还原';
  els.btnTrashPurge.textContent = count > 0 ? '🗑 删除 (' + count + ')' : '🗑 删除';
}

els.btnTrash.addEventListener('click', () => {
  const hidden = els.trashPanel.hidden;
  els.historyPanel.hidden = true;
  els.trashPanel.hidden = !hidden;
  if (hidden) loadTrash();
});

// ============== 根目录显示配置 ==============
async function openTreeFilterModal() {
  els.treeFilterModal.hidden = false;
  try {
    const items = await apiTree('');
    const folders = items.filter((it) => it.type === 'folder');
    const showFilesHtml = `<label><input type="checkbox" data-root-file ${state.showRootFiles ? 'checked' : ''} /> 根目录下文件</label>`;
    const folderHtml = folders.map((f) => {
      const checked = state.visibleFolders.size === 0 || state.visibleFolders.has(f.name);
      return `<label><input type="checkbox" data-root-folder="${escHtml(f.name)}" ${checked ? 'checked' : ''} /> ${escHtml(f.name)}</label>`;
    }).join('');
    els.treeFilterList.innerHTML = showFilesHtml + folderHtml;
  } catch (e) {
    els.treeFilterList.innerHTML = '<div class="tree-filter-tip">加载根目录失败</div>';
  }
}

function closeTreeFilterModal() {
  els.treeFilterModal.hidden = true;
}

function saveTreeFilter() {
  const folders = [];
  els.treeFilterList.querySelectorAll('[data-root-folder]:checked').forEach((cb) => {
    folders.push(cb.dataset.rootFolder);
  });
  const fileCb = els.treeFilterList.querySelector('[data-root-file]');
  state.visibleFolders = new Set(folders);
  state.showRootFiles = fileCb ? fileCb.checked : true;
  saveVisibleRoots();
  closeTreeFilterModal();
  loadTree();
}

els.btnTreeFilterConfig.addEventListener('click', openTreeFilterModal);
els.treeFilterClose.addEventListener('click', closeTreeFilterModal);
els.treeFilterCancel.addEventListener('click', closeTreeFilterModal);
els.treeFilterSave.addEventListener('click', saveTreeFilter);

els.trashSelectAll.addEventListener('change', () => {
  const cbs = els.trashBody.querySelectorAll('.trash-cb');
  const checked = els.trashSelectAll.checked;
  cbs.forEach(cb => {
    cb.checked = checked;
    if (checked) trashSelection.add(cb.dataset.path);
    else trashSelection.delete(cb.dataset.path);
  });
  updateTrashToolbar();
});

els.btnTrashRestore.addEventListener('click', async () => {
  const paths = [...trashSelection];
  if (paths.length === 0) return;
  if (!confirm('还原 ' + paths.length + ' 个文件到原位?')) return;
  try {
    setSaveStatus('还原中...', 'saving');
    const r = await apiTrashRestore(paths);
    const failCount = r.failed ? r.failed.length : 0;
    setSaveStatus('已还原 ' + r.restored.length + ' 个' + (failCount ? ' (失败 ' + failCount + ')' : ''), failCount ? 'error' : 'saved');
    state.treeCache.clear();
    await refreshTreePath('');
    await loadTrash();
    if (state.currentFile && r.restored.includes(state.currentFile.path)) {
      await openFile(state.currentFile.path);
    }
  } catch (e) {
    alert('还原失败: ' + e.message);
    setSaveStatus('还原失败', 'error');
  }
});

els.btnTrashPurge.addEventListener('click', async () => {
  const paths = [...trashSelection];
  if (paths.length === 0) return;
  if (!confirm('彻底删除 ' + paths.length + ' 个文件? 此操作不可撤销!')) return;
  try {
    setSaveStatus('删除中...', 'saving');
    const r = await apiTrashPurge(paths);
    const failCount = r.failed ? r.failed.length : 0;
    setSaveStatus('已彻底删除 ' + r.purged.length + ' 个' + (failCount ? ' (失败 ' + failCount + ')' : ''), failCount ? 'error' : 'saved');
    await loadTrash();
  } catch (e) {
    alert('彻底删除失败: ' + e.message);
    setSaveStatus('删除失败', 'error');
  }
});

// ============== 复制分享 ==============
async function copyToClipboard(text) {
  // 1. 优先用 Clipboard API (需 secure context: https 或 localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      console.warn('[reader] clipboard API failed:', e);
    }
  }
  // 2. 降级: 临时 textarea + execCommand (兼容非 secure context 如局域网 IP)
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.top = '-9999px';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if (ok) return true;
    console.warn('[reader] execCommand copy returned false');
  } catch (e) {
    console.warn('[reader] execCommand copy failed:', e);
  }
  return false;
}

els.btnShare.addEventListener('click', async () => {
  if (!state.currentFile && state.tabs.length === 0) return;
  saveCurrentTabState();
  persistSession();
  const sessionData = {
    tabs: state.tabs.filter(t => !t.isHistory).map(t => ({
      path: t.path, name: t.name, pinned: t.pinned, editMode: t.editMode,
    })),
    activeTabPath: getTab(state.activeTabPath)?.isHistory ? null : state.activeTabPath,
  };
  const json = JSON.stringify(sessionData);
  // UTF-8 → base64 → URL 安全 (- _ 替代 + /, 去掉 =)
  const bytes = new TextEncoder().encode(json);
  let binStr = '';
  for (const b of bytes) binStr += String.fromCharCode(b);
  const encoded = btoa(binStr).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const url = location.origin + location.pathname + '#session=' + encoded;

  const ok = await copyToClipboard(url);
  if (ok) {
    const lanIps = (state.localIps || []).filter(ip => ip !== '127.0.0.1');
    if (lanIps.length) {
      const lan = lanIps.map(ip => `http://${ip}:5090${location.pathname}${location.hash}`).join('  ');
      setSaveStatus(`链接已复制；局域网访问: ${lan}`, 'saved');
    } else {
      setSaveStatus('链接已复制到剪贴板', 'saved');
    }
    setTimeout(() => {
      if (state.isDirty) setSaveStatus('编辑中...', 'dirty');
      else setSaveStatus('已保存', 'saved');
    }, 4000);
  } else {
    // 兜底: 写入地址栏提示手动复制
    try { window.history.replaceState(null, '', url); } catch (_) {}
    setSaveStatus('复制失败,请手动复制地址栏', 'error');
    console.log('[reader] share url (manual copy):', url);
  }
});

// ============== 打包下载 ==============
els.btnDownload.addEventListener('click', async () => {
  // 收集非历史 tab 的路径 (历史 tab 是只读快照, 不下载)
  const tabPaths = state.tabs.filter(t => !t.isHistory).map(t => t.path);
  if (tabPaths.length === 0) {
    alert('没有可下载的 tab');
    return;
  }
  setSaveStatus('打包中...', 'saving');
  // 笔记 + 依赖图片: 扫 md 内嵌本地图引用, 合并进打包列表 (失败退化为仅 tab 列表)
  let paths = tabPaths;
  try {
    const mdPaths = tabPaths.filter(p => isMarkdown(p.includes('.') ? '.' + p.split('.').pop().toLowerCase() : ''));
    const deps = await collectImageDeps(mdPaths);
    if (deps.length) {
      const set = new Set(tabPaths);
      deps.forEach(d => set.add(d));
      paths = [...set];
    }
  } catch (e) { /* 依赖收集失败, 退化 */ }
  try {
    const dl = await apiDownload(paths);
    if (canLocalReader() && dl && dl.path) {
      setSaveStatus(`已下载到 ${dl.path}（${dl.count || 0} 个文件）`, 'saved');
    } else {
      const blob = dl;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'reader-tabs.zip';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setSaveStatus('已下载 reader-tabs.zip', 'saved');
    }
    setTimeout(() => {
      if (state.isDirty) setSaveStatus('编辑中...', 'dirty');
      else setSaveStatus('已保存', 'saved');
    }, 2500);
  } catch (e) {
    setSaveStatus('下载失败: ' + e.message, 'error');
  }
});

// 从 URL 恢复分享的 session
function restoreSharedSession() {
  const hash = location.hash;
  console.log('[reader] restoreSharedSession: hash=', hash ? hash.slice(0, 50) + '...' : '(empty)');
  if (!hash.startsWith('#session=')) return false;
  try {
    let encoded = hash.slice('#session='.length);
    // URL 安全 base64 还原为标准 base64
    encoded = encoded.replace(/-/g, '+').replace(/_/g, '/');
    while (encoded.length % 4) encoded += '=';
    const binStr = atob(encoded);
    const bytes = Uint8Array.from(binStr, c => c.charCodeAt(0));
    const json = new TextDecoder('utf-8').decode(bytes);
    const data = JSON.parse(json);
    if (!data.tabs || data.tabs.length === 0) {
      console.warn('[reader] shared session has no tabs');
      return false;
    }
    state.tabs = data.tabs.map(t => ({
      path: t.path, name: t.name || t.path.split('/').pop(),
      pinned: !!t.pinned, dirty: false, scrollTop: 0, editMode: !!t.editMode,
    }));
    // 固定 tab 排到前面 (与正常 togglePinTab 行为一致)
    state.tabs.sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0));
    state.activeTabPath = data.activeTabPath || state.tabs[0].path;
    console.log('[reader] shared session restored:', state.tabs.length, 'tabs, active:', state.activeTabPath);
    // 用 window.history 显式引用, 避免 RTK hook 劫持全局 history
    try { window.history.replaceState(null, '', window.location.pathname); } catch (e) {}
    return true;
  } catch (e) {
    console.error('[reader] restore shared session failed:', e, 'hash:', hash.slice(0, 80));
    return false;
  }
}

// ============== 大纲面板开关 (眼睛按钮) ==============
// hidden=true: 文字+标题树隐藏, 悬停浮出; hidden=false: 永久显示
function toggleOutline() {
  const isShown = !els.outlinePanel.hidden;
  els.outlinePanel.hidden = isShown;
  savePref('reader.outlineShown', isShown ? 0 : 1);
  // 切换眼睛按钮图标
  if (els.btnOutlineToggle) {
    els.btnOutlineToggle.textContent = isShown ? '👁‍🗨' : '👁';
  }
}
els.btnOutlineToggle.addEventListener('click', (e) => {
  e.stopPropagation();
  toggleOutline();
});
// 初始化眼睛图标
function refreshOutlineEye() {
  if (els.btnOutlineToggle) {
    els.btnOutlineToggle.textContent = els.outlinePanel.hidden ? '👁' : '👁‍🗨';
  }
}

// 面板关闭按钮
document.querySelectorAll('.panel-close').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = document.getElementById(btn.dataset.target);
    if (target) target.hidden = true;
  });
});

// ============== 批注 (comments) ==============
// 右键菜单: 显示/隐藏
function showCommentMenu(x, y) {
  els.commentMenu.style.left = x + 'px';
  els.commentMenu.style.top = y + 'px';
  els.commentMenu.hidden = false;
}
function hideCommentMenu() {
  els.commentMenu.hidden = true;
}

// 从当前选区抽取批注锚信息 (snippet + 前后 40 字符上下文)
//   - #viewer 只读态: textContent 取上下文
//   - #vditor-host 编辑态: state.vditor.getValue() 原始 markdown
function captureSelectionContext() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const snippet = sel.toString().trim();
  if (!snippet) return null;

  const inVditor = state.vditor && !els.vditorHost.hidden;
  let fullText = '';
  if (inVditor) {
    try { fullText = state.vditor.getValue() || ''; }
    catch (_) { fullText = ''; }
  } else if (!els.viewer.hidden) {
    fullText = els.viewer.textContent || '';
  }
  const idx = fullText.indexOf(snippet);
  if (idx >= 0) {
    return {
      snippet,
      contextBefore: fullText.slice(Math.max(0, idx - 40), idx),
      contextAfter: fullText.slice(idx + snippet.length, idx + snippet.length + 40),
    };
  }
  // 多处匹配或未找到: 只带 snippet
  return { snippet, contextBefore: '', contextAfter: '' };
}

// 打开批注编辑器
function openCommentEditor() {
  const ctx = captureSelectionContext();
  if (!ctx) {
    setSaveStatus('未选中文本, 无法添加批注', 'error');
    return;
  }
  state.commentPendingContext = ctx;
  els.commentEditorSnippet.textContent =
    (ctx.contextBefore ? '… ' + ctx.contextBefore + ' ' : '') +
    '[ ' + ctx.snippet + ' ]' +
    (ctx.contextAfter ? ' ' + ctx.contextAfter + ' …' : '');
  els.commentEditorText.value = '';
  els.commentEditorPanel.hidden = false;
  setTimeout(() => els.commentEditorText.focus(), 0);
}

function hideCommentEditor() {
  els.commentEditorPanel.hidden = true;
  els.commentEditorText.value = '';
  state.commentPendingContext = null;
}

els.commentMenu.addEventListener('click', (e) => {
  const item = e.target.closest('.tab-menu-item');
  if (!item) return;
  const action = item.dataset.action;
  hideCommentMenu();
  if (action === 'add-comment') openCommentEditor();
});

els.commentEditorCancel.addEventListener('click', hideCommentEditor);
els.commentEditorSubmit.addEventListener('click', submitComment);
els.commentEditorText.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    submitComment();
  }
});

async function submitComment() {
  if (!state.currentFile || !state.commentPendingContext) return;
  const body = els.commentEditorText.value.trim();
  if (!body) { els.commentEditorText.focus(); return; }
  const ctx = state.commentPendingContext;
  hideCommentEditor();
  try {
    setSaveStatus('提交批注...', 'saving');
    await apiCreateComment({
      path: state.currentFile.path,
      snippet: ctx.snippet,
      contextBefore: ctx.contextBefore,
      contextAfter: ctx.contextAfter,
      author: { kind: 'human' },
      body,
    });
    setSaveStatus('批注已添加', 'saved');
    await loadComments(state.currentFile.path);
    // 提交后自动打开面板
    els.commentPanel.hidden = false;
  } catch (err) {
    setSaveStatus('批注失败: ' + err.message, 'error');
  }
}

// 顶栏按钮: 切换批注面板
els.btnComments.addEventListener('click', () => {
  const hidden = els.commentPanel.hidden;
  els.historyPanel.hidden = true;
  els.trashPanel.hidden = true;
  els.commentPanel.hidden = !hidden;
  if (hidden && state.currentFile) {
    loadComments(state.currentFile.path).catch(() => {});
  }
});

// 切换其他面板时关闭批注面板 (history/trash 互斥)
els.btnHistory.addEventListener('click', () => { if (!els.commentPanel.hidden) els.commentPanel.hidden = true; });
els.btnTrash.addEventListener('click', () => { if (!els.commentPanel.hidden) els.commentPanel.hidden = true; }, true);

els.commentFilter.addEventListener('change', () => {
  state.commentFilter = els.commentFilter.value;
  renderComments();
});

els.btnCommentRefresh.addEventListener('click', () => {
  if (state.currentFile) loadComments(state.currentFile.path).catch(() => {});
});

// 更新顶栏批注 badge: 数字 = 批注总数 + 评论总数, 便于快捷唤起批注面板
function updateCommentBadge() {
  const list = state.comments || [];
  let comments = 0, replies = 0;
  for (const c of list) {
    comments++;
    replies += Array.isArray(c.replies) ? c.replies.length : 0;
  }
  const total = comments + replies;
  if (els.btnCommentsBadge) {
    els.btnCommentsBadge.textContent = String(total);
    els.btnCommentsBadge.hidden = total === 0;
  }
  if (els.btnComments) {
    els.btnComments.title = total > 0
      ? `批注: 切换批注面板 (${comments} 批注 · ${replies} 评论)`
      : '批注: 切换批注面板';
  }
}

// 后端将 snippet/context 存在 comment.anchor.* (顶层 snippet 为兼容旧数据兜底)
function commentSnippet(c) { return (c && (c.snippet || (c.anchor && c.anchor.snippet))) || ''; }
function commentContextBefore(c) { return (c && (c.contextBefore || (c.anchor && c.anchor.contextBefore))) || ''; }

// 加载批注: fetch + 存储 + 渲染面板 + 应用锚标
async function loadComments(path) {
  if (!path) return;
  try {
    const data = await apiGetComments(path);
    state.comments = Array.isArray(data.comments) ? data.comments : [];
  } catch (err) {
    console.warn('[comments] GET failed:', err);
    state.comments = [];
  }
  renderComments();
  updateCommentBadge();
  // 锚标: 当前可见的容器
  const container = state.vditor && !els.vditorHost.hidden
    ? els.vditorHost
    : (!els.viewer.hidden ? els.viewer : null);
  if (container) requestAnimationFrame(() => applyCommentAnchors(container));
}

// 渲染批注面板
function renderComments() {
  const filter = state.commentFilter;
  const list = state.comments.filter(c => {
    if (filter === 'open') return c.status !== 'resolved';
    if (filter === 'resolved') return c.status === 'resolved';
    return true;
  });
  els.commentBody.innerHTML = '';
  if (!state.comments.length) {
    els.commentBody.innerHTML = '<div class="comment-empty">本文档暂无批注<br><span style="font-size:11px">右键选中文字 → 添加批注</span></div>';
    return;
  }
  if (!list.length) {
    els.commentBody.innerHTML = '<div class="comment-empty">' + escapeHtml(filter) + ' 下无批注</div>';
    return;
  }
  for (const c of list) {
    els.commentBody.appendChild(buildCommentCard(c));
  }
}

function buildCommentCard(c) {
  const card = document.createElement('div');
  card.className = 'comment-card';
  card.dataset.commentId = c.id;
  card.dataset.status = c.status || 'open';

  // 片段
  const snippetEl = document.createElement('div');
  snippetEl.className = 'comment-snippet';
  const snip = commentSnippet(c).slice(0, 60);
  snippetEl.textContent = snip + (commentSnippet(c).length > 60 ? '…' : '');
  snippetEl.title = '点击定位到原文';
  snippetEl.addEventListener('click', () => scrollAnchorIntoView(c.id));
  // stale 判定: 应用锚标后若没找到该 id 的 mark, 加 stale 标
  if (!document.querySelector('mark.comment-anchor[data-comment-id="' + CSS.escape(c.id) + '"]')) {
    snippetEl.classList.add('stale');
    snippetEl.title = '⚠ 锚文本未找到 (文档已修改?) — 点击尝试定位';
  }
  card.appendChild(snippetEl);

  // body
  const bodyEl = document.createElement('div');
  bodyEl.className = 'comment-body';
  bodyEl.innerHTML = window.marked
    ? window.marked.parse(c.body || '')
    : escapeHtml(c.body || '');
  card.appendChild(bodyEl);

  // meta
  const metaEl = document.createElement('div');
  metaEl.className = 'comment-meta';
  const kind = (c.author && c.author.kind) || 'human';
  metaEl.innerHTML =
    '<span class="comment-tag ' + escapeHtml(kind) + '">' + escapeHtml(kind === 'ai' ? '🤖 AI' : '👤 human') + '</span>' +
    '<span class="comment-status ' + escapeHtml(c.status || 'open') + '">' + escapeHtml(c.status === 'resolved' ? '已解决' : '未解决') + '</span>' +
    (c.createdAt ? '<span>' + escapeHtml(formatCommentTime(c.createdAt)) + '</span>' : '');
  card.appendChild(metaEl);

  // 回复列表
  if (Array.isArray(c.replies) && c.replies.length) {
    for (const r of c.replies) {
      const replyWrap = document.createElement('div');
      replyWrap.className = 'comment-reply';
      const rBody = document.createElement('div');
      rBody.className = 'comment-reply-body';
      rBody.innerHTML = window.marked ? window.marked.parse(r.body || '') : escapeHtml(r.body || '');
      const rMeta = document.createElement('div');
      rMeta.className = 'comment-reply-meta';
      const rKind = (r.author && r.author.kind) || 'human';
      rMeta.innerHTML = '<span class="comment-tag ' + escapeHtml(rKind) + '">' + escapeHtml(rKind === 'ai' ? '🤖' : '👤') + '</span>' +
        (r.createdAt ? '<span>' + escapeHtml(formatCommentTime(r.createdAt)) + '</span>' : '');
      replyWrap.appendChild(rMeta);
      replyWrap.appendChild(rBody);
      card.appendChild(replyWrap);
    }
  }

  // 回复输入
  const replyInput = document.createElement('div');
  replyInput.className = 'comment-reply-input';
  const input = document.createElement('input');
  input.type = 'text';
  input.placeholder = '回复...';
  const replyBtn = document.createElement('button');
  replyBtn.textContent = '回复';
  replyBtn.addEventListener('click', async () => {
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    try {
      setSaveStatus('提交回复...', 'saving');
      await apiReplyComment(c.id, { author: { kind: 'human' }, body: text });
      input.value = '';
      setSaveStatus('回复已添加', 'saved');
      await loadComments(state.currentFile.path);
    } catch (err) {
      setSaveStatus('回复失败: ' + err.message, 'error');
    }
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); replyBtn.click(); }
  });
  replyInput.appendChild(input);
  replyInput.appendChild(replyBtn);
  card.appendChild(replyInput);

  // actions: 解决/重开 / 删除
  const actions = document.createElement('div');
  actions.className = 'comment-actions';
  const toggleBtn = document.createElement('button');
  toggleBtn.textContent = c.status === 'resolved' ? '↩ 重开' : '✓ 解决';
  toggleBtn.addEventListener('click', async () => {
    try {
      setSaveStatus('更新批注...', 'saving');
      await apiUpdateComment(c.id, { status: c.status === 'resolved' ? 'open' : 'resolved' });
      setSaveStatus('已更新', 'saved');
      await loadComments(state.currentFile.path);
      applyCommentAnchors(state.vditor && !els.vditorHost.hidden ? els.vditorHost : (!els.viewer.hidden ? els.viewer : null));
    } catch (err) {
      setSaveStatus('更新失败: ' + err.message, 'error');
    }
  });
  actions.appendChild(toggleBtn);

  const delBtn = document.createElement('button');
  delBtn.className = 'danger';
  delBtn.textContent = '🗑 删除';
  // 删除: author.kind === 'human' 才允许 (按 spec)
  delBtn.disabled = (c.author && c.author.kind) !== 'human';
  delBtn.addEventListener('click', async () => {
    if (!confirm('确认删除该批注?')) return;
    try {
      setSaveStatus('删除批注...', 'saving');
      await apiDeleteComment(c.id, state.currentFile && state.currentFile.path);
      setSaveStatus('已删除', 'saved');
      await loadComments(state.currentFile.path);
    } catch (err) {
      setSaveStatus('删除失败: ' + err.message, 'error');
    }
  });
  actions.appendChild(delBtn);
  card.appendChild(actions);

  return card;
}

function formatCommentTime(ts) {
  if (!ts) return '';
  // 兼容 ISO 字符串 / unix 秒 / unix 毫秒
  let d;
  if (typeof ts === 'number') {
    d = new Date(ts < 1e12 ? ts * 1000 : ts);
  } else {
    d = new Date(ts);
  }
  if (isNaN(d.getTime())) return String(ts);
  const now = new Date();
  const diff = (now - d) / 1000; // 秒
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' 天前';
  const pad = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

// 锚标: TreeWalker 遍历 text 节点, 找 snippet 首次出现, 包裹 <mark>
function applyCommentAnchors(container) {
  if (!container) return;
  // 清旧
  container.querySelectorAll('mark.comment-anchor').forEach((m) => {
    const parent = m.parentNode;
    if (!parent) return;
    // 还原文本: mark 替换为文本节点, 合并相邻
    const text = document.createTextNode(m.textContent);
    parent.replaceChild(text, m);
    parent.normalize();
  });
  // 清旧编号圆圈
  container.querySelectorAll('.comment-anchor-badge').forEach((b) => b.remove());

  state.comments.forEach((c, idx) => {
    const snippet = commentSnippet(c);
    if (!snippet || snippet.length < 2) return;
    const match = findFirstTextNodeMatch(container, snippet, commentContextBefore(c));
    if (!match) return;
    const { node, offset, length } = match;
    try {
      const range = document.createRange();
      range.setStart(node, offset);
      range.setEnd(node, offset + length);
      const mark = document.createElement('mark');
      mark.className = 'comment-anchor';
      mark.dataset.commentId = c.id;
      mark.dataset.status = c.status || 'open';
      mark.addEventListener('click', (e) => {
        e.stopPropagation();
        scrollCommentIntoView(c.id);
      });
      range.surroundContents(mark);

      // 段落旁黄色数字圆圈: 点击 → 打开批注面板并定位到该批注
      const badge = document.createElement('span');
      badge.className = 'comment-anchor-badge';
      badge.textContent = String(idx + 1);
      badge.dataset.commentId = c.id;
      badge.title = '打开批注 #' + (idx + 1);
      badge.addEventListener('click', (e) => {
        e.stopPropagation();
        scrollCommentIntoView(c.id);
      });
      // 插入到 mark 所在块级元素末尾 (段落旁)
      const block = mark.closest('p, li, h1, h2, h3, h4, h5, h6, td, th, blockquote, pre, div') || mark.parentNode;
      block.appendChild(badge);
    } catch (_) {
      // 跨节点: 跳过 (简化处理, 多处匹配由 contextBefore 兜底)
    }
  });
}

// TreeWalker 找 snippet 在 container 内的首个 text-node 命中; contextBefore 做兜底筛选
function findFirstTextNodeMatch(container, snippet, contextBefore) {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return node.nodeValue && node.nodeValue.length >= snippet.length
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT;
    },
  });
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);
  // 单节点直接命中
  const candidates = [];
  for (const node of nodes) {
    const text = node.nodeValue;
    let idx = text.indexOf(snippet);
    while (idx >= 0) {
      candidates.push({ node, offset: idx, length: snippet.length });
      idx = text.indexOf(snippet, idx + 1);
    }
  }
  if (!candidates.length) return null;
  if (candidates.length === 1) return candidates[0];
  // 多候选: 用 contextBefore 比对命中节点之前的累积文本末尾
  if (contextBefore) {
    let acc = '';
    for (const cand of candidates) {
      // 在 cand 之前累积文本 (粗略: 全文 indexOf cand 段)
      const beforeText = acc + cand.node.nodeValue.slice(0, cand.offset);
      if (beforeText.endsWith(contextBefore)) return cand;
      // 更新 acc: 简单累加节点值, 不精确但够用
    }
    // 再用全局 textContent 定位
    const fullText = container.textContent || '';
    const wantCtx = contextBefore + snippet;
    const ctxIdx = fullText.indexOf(wantCtx);
    if (ctxIdx >= 0) {
      // 映射回 text 节点: 累加偏移
      let consumed = 0;
      for (const node of nodes) {
        const len = node.nodeValue.length;
        const candGlobalStart = ctxIdx + contextBefore.length;
        if (consumed + len > candGlobalStart && candGlobalStart >= consumed) {
          const localOffset = candGlobalStart - consumed;
          if (node.nodeValue.slice(localOffset, localOffset + snippet.length) === snippet) {
            return { node, offset: localOffset, length: snippet.length };
          }
        }
        consumed += len;
      }
    }
  }
  return candidates[0];
}

// 点击锚标 → 滚动到批注卡片 + flash
function scrollCommentIntoView(commentId) {
  els.commentPanel.hidden = false;
  const card = els.commentBody.querySelector('.comment-card[data-comment-id="' + CSS.escape(commentId) + '"]');
  if (!card) return;
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  card.classList.remove('flash');
  void card.offsetWidth;
  card.classList.add('flash');
}

// 点击卡片片段 → 滚动到锚标 + flash
function scrollAnchorIntoView(commentId) {
  const mark = document.querySelector('mark.comment-anchor[data-comment-id="' + CSS.escape(commentId) + '"]');
  if (!mark) {
    setSaveStatus('⚠ 锚文本未找到, 文档可能已修改', 'error');
    return;
  }
  mark.scrollIntoView({ behavior: 'auto', block: 'center' });
  mark.classList.remove('flash');
  void mark.offsetWidth;
  mark.classList.add('flash');
}

// ============== 会话持久化 ==============
function persistSession() {
  try {
    const data = state.tabs.filter(t => !t.isHistory).map(t => ({
      path: t.path, name: t.name, pinned: t.pinned,
      dirty: t.dirty, scrollTop: t.scrollTop, editMode: t.editMode,
    }));
    const activePath = getTab(state.activeTabPath)?.isHistory ? null : state.activeTabPath;
    const payload = JSON.stringify({ tabs: data, activeTabPath: activePath });
    localStorage.setItem('reader.session', payload);
    // 嵌入场景: 把当前状态上报父窗口 (Castflow 持久化, 跨重启还原)
    notifyParent({ type: 'cf-state', state: buildReaderState() });
  } catch (e) {}
}

function restoreSession() {
  try {
    const raw = localStorage.getItem('reader.session');
    if (!raw) return false;
    const data = JSON.parse(raw);
    if (!data.tabs || data.tabs.length === 0) return false;
    state.tabs = data.tabs;
    state.activeTabPath = data.activeTabPath || data.tabs[0].path;
    return true;
  } catch (e) { return false; }
}

function splitFrontmatter(content) {
  const m = content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!m) return { meta: null, body: content };

  const meta = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (kv) meta[kv[1]] = kv[2];
  }

  return { meta, body: content.slice(m[0].length) };
}

function escapeHtml(s) {
  return String(s || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderFrontmatter(meta) {
  if (!meta || Object.keys(meta).length === 0) return '';
  const rows = Object.entries(meta).map(([k, v]) =>
    `<div class="frontmatter-row">
      <div class="frontmatter-key">${escapeHtml(k)}</div>
      <div class="frontmatter-value">${escapeHtml(v)}</div>
    </div>`
  ).join('');
  return `<section class="frontmatter-card">
    <div class="frontmatter-title">文档元信息</div>
    ${rows}
  </section>`;
}

// ============== 标题 slug (内文锚链接 + URL hash 跳转) ==============
function slugify(text) {
  return String(text || '')
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, '')   // 保留字母数字空格- (unicode 兼容中文)
    .replace(/\s+/g, '-');
}

// 给 marked 渲染后的标题批量加 id (slug), 支持同文多标题去重
function applyHeadingIds(root) {
  const seen = new Set();
  root.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach((h) => {
    let id = slugify(h.textContent);
    if (!id) id = 'heading';
    let base = id, i = 2;
    while (seen.has(id)) { id = base + '-' + (i++); }
    seen.add(id);
    h.id = id;
  });
}

// ============== Vditor IR 编辑器 (PoC) ==============
// .md 以 Vditor 即时渲染(IR, Typora 式) 呈现+编辑, 替代 renderMarkdown + CodeMirror 编辑态。
// Lute 引擎原生保留 frontmatter / [[wikilink]] / ![](x.drawio), 无需剥离/回填。
function destroyVditor() {
  disconnectVditorFoldObserver();
  if (state.vditor) {
    state.vditor.destroy();
    state.vditor = null;
  }
  if (els.vditorHost) {
    els.vditorHost.innerHTML = '';
    els.vditorHost.hidden = true;
  }
}

// .md 编辑/只读 全局偏好 (对所有 .md 文档生效, localStorage 持久化, 刷新保留)
// true=编辑(Vditor IR), false=只读(renderMarkdown 渲染); 默认 false (只读, 2026-08-23 改: 原默认编辑)
function getMdEditMode() {
  return localStorage.getItem('reader.mdEditMode') === 'true';
}
function setMdEditMode(editMode) {
  localStorage.setItem('reader.mdEditMode', editMode ? 'true' : 'false');
}

// .md 编辑/只读 toggle 状态: editMode=true 编辑(Vditor IR), false 只读(renderMarkdown 渲染)
// 绿色常驻 (编辑/只读两态都绿); 非 .md 文件由 openFile 移除 edit-active
function setMdToggleState(editMode) {
  els.editToggle.disabled = false;
  els.editToggle.textContent = editMode ? '只读' : '编辑';
  els.editToggle.classList.add('edit-active');
}

function renderMarkdownVditor(file) {
  exitEditMode();
  els.welcome.hidden = true;
  els.viewer.hidden = true;
  els.editorHost.hidden = true;
  els.vditorHost.hidden = false;

  if (!window.Vditor) {
    // Vditor 未加载, 降级到原渲染
    els.vditorHost.hidden = true;
    els.viewer.hidden = false;
    renderMarkdown(file);
    return;
  }

  const md = preprocessCenterImages(file.content || '');
  try {
    state.vditor = new window.Vditor(els.vditorHost, {
      mode: 'ir',
      value: md,
      height: 'auto',
      cache: { enable: false },
      toolbar: ['headings', 'bold', 'italic', 'strike', 'link', 'quote', 'table', 'list', 'ordered-list', 'check', 'code', 'line'],
      preview: { hljs: { enable: true, style: 'github' } },
      link: {
        isOpen: false,                // 禁用 Vditor 默认 window.open (相对路径会 404)
        click: handleVditorLinkClick, // 站内 .md → 本页开 tab; #anchor → 滚动; 外链 → 新标签
      },
      input: () => {
        state.isDirty = true;
        setSaveStatus('编辑中...', 'dirty');
        const tab = getTab(state.currentFile.path);
        if (tab) { tab.dirty = true; renderTabs(); }
        scheduleVditorOutline();
        scheduleAutosave();
        // mermaid 预览 debounce 重渲 (用户编辑 ```mermaid 块内容后)
        scheduleMermaidRender(els.vditorHost);
      },
      after: () => {
        console.log('[vditor] after callback fired');
        setSaveStatus('已加载', 'saved');
        // mermaid 快照 (load-time, 不漂移): 供 recoverMermaidBlocks 防 Vditor getValue 丢码
        state.mermaidSnapshot = captureMermaidBlocks(md);
        // 目录 (复用 buildOutline, 用去 frontmatter 的 body)
        const { body } = splitFrontmatter(md);
        buildOutline(body);
        // 编辑态标题折叠 + (切换时) 恢复文档位置 + 高亮目录
        // 全部由 applyVditorHeadingFold 在 headings 就绪后统一做 (避免 headings 未渲染 NOT FOUND)
        requestAnimationFrame(() => {
          console.log('[vditor] rAF: calling applyVditorHeadingFold');
          applyVditorHeadingFold();
          // 内嵌图片相对路径 → /api/reader/raw
          applyImageRewrite(els.vditorHost, file.path);
          // mermaid 首次渲染 (Vditor IR 把代码块渲染完才能扫到)
          renderMermaidBlocks(els.vditorHost);
          // 批注锚标: Vditor IR DOM 就绪后重新应用
          requestAnimationFrame(() => applyCommentAnchors(els.vditorHost));
        });
      },
    });
  } catch (e) {
    console.error('[vditor] init failed, fallback to renderMarkdown:', e);
    destroyVditor();
    els.vditorHost.hidden = true;
    els.viewer.hidden = false;
    renderMarkdown(file);
    return;
  }

  // .md 编辑态: toggle 启用 + 绿色 + 标签"只读" (点击切到只读渲染)
  setMdToggleState(true);

  // 图片粘贴/拖入 hook: 挂在 vditorHost 上一次 (dataset 守护防重复绑定);
  // capture 阶段拦截, 抢在 Vditor 自身 paste 之前。
  if (!els.vditorHost.dataset.imageHook) {
    els.vditorHost.dataset.imageHook = '1';
    els.vditorHost.addEventListener('paste', onVditorPaste, true);
    els.vditorHost.addEventListener('drop', onVditorDrop, true);
  }

  if (isMarkdown(file.extension)) {
    els.outlinePanel.hidden = localStorage.getItem('reader.outlineShown') === '0';
  }
}

// Vditor 链接点击回调 (通过 options.link.click 接管, 替代 Vditor 默认 window.open)
// Vditor IR 把链接渲染成 <span data-type="a">, URL 在 .vditor-ir__marker--link;
// 回调入参即该 marker 元素, textContent 为 URL。
function handleVditorLinkClick(linkMarkerEl) {
  const href = (linkMarkerEl && linkMarkerEl.textContent) || '';
  if (!href) return;
  if (/^https?:\/\//i.test(href) || href.startsWith('mailto:')) {
    window.open(href, '_blank');  // 外链: 新标签打开
    return;
  }
  if (href.startsWith('#')) {
    const id = href.slice(1);
    if (!id) return;
    let target = null;
    try { target = els.vditorHost.querySelector('#' + CSS.escape(id)); } catch (_) {}
    if (!target) {
      target = [...els.vditorHost.querySelectorAll('h1,h2,h3,h4,h5,h6')]
        .find(h => h.id === id || slugify(h.textContent) === id);
    }
    if (target) {
      const scroller = els.contentBody;
      const rect = target.getBoundingClientRect();
      const scrollerRect = scroller.getBoundingClientRect();
      scroller.scrollTop = rect.top - scrollerRect.top + scroller.scrollTop - 8;
    }
    return;
  }
  if (!state.currentFile) return;
  const anchorIdx = href.indexOf('#');
  const anchor = anchorIdx >= 0 ? href.slice(anchorIdx + 1) : '';
  const filePart = anchorIdx >= 0 ? href.slice(0, anchorIdx) : href;
  const resolved = filePart ? resolveRelative(state.currentFile.path, filePart) : state.currentFile.path;
  if (!resolved) return;
  openFile(resolved).then(() => {
    if (anchor) {
      requestAnimationFrame(() => {
        let target = null;
        try { target = els.vditorHost.querySelector('#' + CSS.escape(anchor)); } catch (_) {}
        if (target) {
          const scroller = els.contentBody;
          const rect = target.getBoundingClientRect();
          const scrollerRect = scroller.getBoundingClientRect();
          scroller.scrollTop = rect.top - scrollerRect.top + scroller.scrollTop - 8;
        }
      });
    }
  });
}

// ============== Vditor 图片粘贴/拖入 → 上传到根 assets/ ==============
// 粘贴 (剪贴板截图) 或拖入图片文件 → 上传 → 插入根相对引用 ![](/assets/x.png)。
// 根相对 (/ 前缀) 使任意目录 md 都指向 repo 根同一图, 跨文档复用; resolveRelative
// 切掉前导 / → assets/x.png, 与 applyImageRewrite / collectImageDeps 自洽。
async function handleVditorImageInsert(files) {
  const vd = state.vditor;
  if (!vd) return;
  const imgs = [...files].filter(f => f.type && f.type.startsWith('image/'));
  if (!imgs.length) return;
  for (const f of imgs) {
    try {
      setSaveStatus('上传图片...', 'saving');
      const { path } = await apiUploadImage(f);
      vd.insertMD('\n\n![](/' + path + ')\n\n');
      setSaveStatus('图片已插入', 'saved');
    } catch (e) {
      alert('图片上传失败: ' + e.message);
      setSaveStatus('上传失败', 'error');
      return;
    }
  }
  // insertMD 触发 input → scheduleMermaidRender 内 applyImageRewrite 把新 img 改到 raw 路由
}
// paste: 仅当剪贴板含图片文件时拦截 (preventDefault 阻断 Vditor 默认 base64 fallback);
// 纯文本/代码片段放行给 Vditor 正常处理。
function onVditorPaste(e) {
  const items = e.clipboardData && e.clipboardData.items;
  if (!items) return;
  const imgs = [...items]
    .filter(it => it.kind === 'file' && it.type && it.type.startsWith('image/'))
    .map(it => it.getAsFile())
    .filter(Boolean);
  if (!imgs.length) return;
  e.preventDefault();
  e.stopPropagation();
  handleVditorImageInsert(imgs);
}
// drop: 拖入图片文件 → 上传; 拖入非图文件放行 (避免干扰 Vditor 自身行为)。
function onVditorDrop(e) {
  const files = e.dataTransfer && e.dataTransfer.files;
  if (!files || !files.length) return;
  const imgs = [...files].filter(f => f.type && f.type.startsWith('image/'));
  if (!imgs.length) return;
  e.preventDefault();
  e.stopPropagation();
  handleVditorImageInsert(imgs);
}

// ============== 文档内右键样式面板 (Vditor IR 编辑态) ==============
// 菜单项: action 对应 Vditor 工具栏项 (DOM click 触发); 下划线/链接走 insertMD
const STYLE_MENU_ITEMS = [
  { group: '标题' },
  { action: 'h1', label: '标题 1', mac: '⌥⌘1', win: 'Alt+Ctrl+1' },
  { action: 'h2', label: '标题 2', mac: '⌥⌘2', win: 'Alt+Ctrl+2' },
  { action: 'h3', label: '标题 3', mac: '⌥⌘3', win: 'Alt+Ctrl+3' },
  { action: 'h4', label: '标题 4', mac: '⌥⌘4', win: 'Alt+Ctrl+4' },
  { action: 'h5', label: '标题 5', mac: '⌥⌘5', win: 'Alt+Ctrl+5' },
  { action: 'h6', label: '标题 6', mac: '⌥⌘6', win: 'Alt+Ctrl+6' },
  { group: '列表' },
  { action: 'list', label: '无序列表', mac: '⌘L', win: 'Ctrl+L' },
  { action: 'ordered-list', label: '有序列表', mac: '⌘O', win: 'Ctrl+O' },
  { action: 'check', label: '代办列表', mac: '⌘J', win: 'Ctrl+J' },
  { group: '块' },
  { action: 'quote', label: '引用', mac: '', win: '' },
  { action: 'table', label: '表格', mac: '', win: '' },
  { action: 'code', label: '代码块', mac: '⌘U', win: 'Ctrl+U' },
  { action: 'line', label: '分割线', mac: '⇧⌘H', win: 'Ctrl+Shift+H' },
  { action: 'blank-line', label: '空行', mac: '', win: '' },
  { group: '内联' },
  { action: 'bold', label: '粗体', mac: '⌘B', win: 'Ctrl+B' },
  { action: 'italic', label: '斜体', mac: '⌘I', win: 'Ctrl+I' },
  { action: 'strike', label: '删除线', mac: '⌘D', win: 'Ctrl+D' },
  { action: 'underline', label: '下划线', mac: '', win: '' },
  { action: 'link', label: '链接', mac: '⌘K', win: 'Ctrl+K' },
];

let styleMenuEl = null;
function getStyleMenu() {
  if (styleMenuEl) return styleMenuEl;
  styleMenuEl = document.createElement('div');
  styleMenuEl.id = 'vditor-style-menu';
  styleMenuEl.hidden = true;
  for (const item of STYLE_MENU_ITEMS) {
    if (item.group) {
      const sep = document.createElement('div');
      sep.className = 'style-menu-sep';
      sep.textContent = item.group;
      styleMenuEl.appendChild(sep);
    } else {
      const row = document.createElement('div');
      row.className = 'style-menu-item';
      const sc = IS_WIN ? (item.win || '') : (item.mac || '');
      row.innerHTML = '<span class="style-menu-label">' + item.label + '</span>'
        + (sc ? '<span class="style-menu-sc">' + sc + '</span>' : '');
      // mousedown preventDefault 保持编辑器选区 (否则点击菜单会丢选区)
      row.addEventListener('mousedown', (e) => e.preventDefault());
      row.addEventListener('click', () => { applyStyleAction(item.action); hideStyleMenu(); });
      styleMenuEl.appendChild(row);
    }
  }
  document.body.appendChild(styleMenuEl);
  return styleMenuEl;
}

function showStyleMenu(x, y) {
  const m = getStyleMenu();
  // 边界处理: 避免超出视口
  m.hidden = false;
  const rect = m.getBoundingClientRect();
  const maxX = window.innerWidth - rect.width - 8;
  const maxY = window.innerHeight - rect.height - 8;
  m.style.left = Math.min(x, maxX) + 'px';
  m.style.top = Math.min(y, maxY) + 'px';
}
function hideStyleMenu() {
  if (styleMenuEl) styleMenuEl.hidden = true;
}

// 选区是否在指定 data-type 的内联标记内 (用于 toggle 判断)
function vdSelInType(dataType) {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return false;
  let node = sel.getRangeAt(0).startContainer;
  if (node.nodeType === 3) node = node.parentElement;
  while (node && node !== els.vditorHost) {
    if (node.dataset && node.dataset.type === dataType) return true;
    node = node.parentElement;
  }
  return false;
}
// 选区所在标题级别 (0=非标题)
function vdHeadingLevel() {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return 0;
  let node = sel.getRangeAt(0).startContainer;
  if (node.nodeType === 3) node = node.parentElement;
  while (node && node !== els.vditorHost) {
    const m = node.tagName && node.tagName.match(/^H([1-6])$/);
    if (m) return parseInt(m[1], 10);
    node = node.parentElement;
  }
  return 0;
}
// 选区所在列表类型 ('list'|'ordered-list'|'check'|'')
function vdListType() {
  const sel = window.getSelection();
  if (!sel || !sel.rangeCount) return '';
  let node = sel.getRangeAt(0).startContainer;
  if (node.nodeType === 3) node = node.parentElement;
  while (node && node !== els.vditorHost) {
    if (node.tagName === 'LI') {
      if (node.classList.contains('vditor-task')) return 'check';
      if (node.parentElement && node.parentElement.tagName === 'OL') return 'ordered-list';
      return 'list';
    }
    node = node.parentElement;
  }
  return '';
}

function applyStyleAction(action) {
  const vd = state.vditor;
  if (!vd) return;
  vd.focus();
  const host = els.vditorHost;

  // 内联标记 toggle: bold/italic/strike
  // 右键(contextmenu)不触发 Vditor 的 highlightToolbar, vditor-menu--current 类是旧的,
  // 故按当前选区手动设对 class, 让 processToolbar 走"添加"或"移除"分支
  const inlineMap = { bold: 'strong', italic: 'em', strike: 's' };
  if (inlineMap[action]) {
    const btn = host.querySelector('[data-type="' + action + '"]');
    if (!btn) return;
    btn.classList.toggle('vditor-menu--current', vdSelInType(inlineMap[action]));
    btn.click();
    return;
  }

  // 链接 toggle: 在链接内 -> 移除(保留文字); 否则 prompt URL 添加
  if (action === 'link') {
    if (vdSelInType('a')) {
      const btn = host.querySelector('[data-type="link"]');
      if (btn) { btn.classList.add('vditor-menu--current'); btn.click(); }
    } else {
      const sel = vd.getSelection();
      const url = prompt('链接 URL:', 'https://');
      if (url === null) return;
      const text = sel || '链接文字';
      if (sel) vd.deleteValue();
      vd.insertMD('[' + text + '](' + url + ')');
    }
    return;
  }

  // 标题 toggle: 当前块已是同级标题 -> 移除(actionBtn current 分支); 否则 -> 转换(panel 按钮)
  if (/^h[1-6]$/.test(action)) {
    const level = parseInt(action[1], 10);
    if (vdHeadingLevel() === level) {
      const actionBtn = host.querySelector('[data-type="headings"]');
      if (actionBtn) { actionBtn.classList.add('vditor-menu--current'); actionBtn.click(); }
    } else {
      const btn = host.querySelector('[data-tag="' + action + '"]');
      if (btn) btn.click();
    }
    return;
  }

  // 列表 toggle: 同类型 -> 移除(listToggle); 否则 -> 转换/添加
  if (action === 'list' || action === 'ordered-list' || action === 'check') {
    const btn = host.querySelector('[data-type="' + action + '"]');
    if (!btn) return;
    btn.classList.toggle('vditor-menu--current', vdListType() === action);
    btn.click();
    return;
  }

  // 下划线: markdown 无原生, <u> 在 IR 为 html-inline 难以稳定 toggle, 仅添加
  if (action === 'underline') {
    const sel = vd.getSelection();
    if (sel) { vd.deleteValue(); vd.insertMD('<u>' + sel + '</u>'); }
    else vd.insertMD('<u>下划线</u>');
    return;
  }

  // 空行: 插入 &nbsp; 段落 (有内容不被 markdown 折叠; margin:0 下恰为一行行高; 字符不抢光标)
  // 编辑态: 一行含 nbsp (淡); 只读态: <p>&nbsp;</p> 渲染为一行行高空白
  if (action === 'blank-line') {
    vd.insertMD('\n\n&nbsp;\n\n');
    return;
  }

  // 表格: 1 行 1 列 (header "列1" + 1 数据行; 用户可用表格右键菜单加行加列)
  if (action === 'table') {
    vd.insertMD('\n\n| 列1 |\n| --- |\n|  |\n\n');
    return;
  }

  // 代码块/分割线: 插入, 无 toggle 语义
  const btn = host.querySelector('[data-type="' + action + '"]');
  if (btn) btn.click();
}

// ============== 表格右键菜单 (Vditor IR) ==============
// 表格内右键 → 表格菜单 (加行/加列/调整); 空白处右键 → 样式面板。
// 视觉与样式面板统一 (复用 .style-menu-sep / .style-menu-item); 右键单元格置灰高亮暗示选中。
// 表格操作: 从渲染 DOM 重建表格 markdown, 变换后整体替换表格块 (Vditor IR 自动重渲染)。
const TABLE_MENU_ITEMS = [
  { group: '表格' },
  { action: 'table-add-row', label: '下方插入行' },
  { action: 'table-add-col', label: '右侧插入列' },
  { action: 'table-del-row', label: '删除当前行' },
  { action: 'table-del-col', label: '删除当前列' },
  { action: 'table-resize', label: '调整行列数…' },
];
let tableMenuEl = null;
let tableMenuCellEl = null;  // 右键所在单元格, 供 action 定位行列 + 高亮

function getTableMenu() {
  if (tableMenuEl) return tableMenuEl;
  tableMenuEl = document.createElement('div');
  tableMenuEl.id = 'vditor-table-menu';
  tableMenuEl.hidden = true;
  for (const item of TABLE_MENU_ITEMS) {
    if (item.group) {
      const sep = document.createElement('div');
      sep.className = 'style-menu-sep';
      sep.textContent = item.group;
      tableMenuEl.appendChild(sep);
    } else {
      const row = document.createElement('div');
      row.className = 'style-menu-item';  // 复用样式面板项样式
      row.innerHTML = '<span class="style-menu-label">' + item.label + '</span>';
      row.addEventListener('mousedown', (e) => e.preventDefault());  // 保选区
      row.addEventListener('click', () => { applyTableAction(item.action); hideTableMenu(); });
      tableMenuEl.appendChild(row);
    }
  }
  document.body.appendChild(tableMenuEl);
  return tableMenuEl;
}
function clearCellHighlight() {
  document.querySelectorAll('.vditor-cell-selected').forEach(el => el.classList.remove('vditor-cell-selected'));
}
function showTableMenu(x, y, cellEl) {
  const m = getTableMenu();
  clearCellHighlight();
  tableSel = null;  // 右键转单格操作, 清拖选
  tableMenuCellEl = cellEl;
  cellEl.classList.add('vditor-cell-selected');  // 置灰高亮: 暗示操作基准格
  m.hidden = false;
  const rect = m.getBoundingClientRect();
  m.style.left = Math.min(x, window.innerWidth - rect.width - 8) + 'px';
  m.style.top = Math.min(y, window.innerHeight - rect.height - 8) + 'px';
}
function hideTableMenu() {
  if (tableMenuEl) tableMenuEl.hidden = true;
  tableMenuCellEl = null;
  clearCellHighlight();
}

// 表格 DOM -> markdown 重建 (IR 表格 <table> 含 thead/tbody 或纯 tr, 统一取所有 tr)
function tableElToMD(table) {
  const trs = [...table.querySelectorAll('tr')];
  if (!trs.length) return '';
  const cellCount = tr => [...tr.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH').length;
  const colCount = Math.max(1, ...trs.map(cellCount));
  const cellText = (tr, i) => {
    const cells = [...tr.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH');
    const c = cells[i];
    if (!c) return ' ';
    const t = c.textContent.replace(/\|/g, '\\|').replace(/\n/g, ' ').trim();
    return t || ' ';
  };
  const lineFor = tr => '| ' + [...Array(colCount)].map((_, i) => cellText(tr, i)).join(' | ') + ' |';
  const header = lineFor(trs[0]);
  const sep = '| ' + [...Array(colCount)].map(() => '---').join(' | ') + ' |';
  const data = trs.slice(1).map(lineFor);
  return [header, sep, ...data].join('\n');
}

// 定位表格在 markdown 源码中的行范围 [startLine, endLine)
// 先按内容 (规范化后) 精确匹配 DOM 表格 ↔ 源码表格; 失败再退回 DOM 索引对应
function findTableSourceRange(tableEl, doc) {
  const lines = doc.split('\n');
  const isSep = line => /^\s*\|?[\s:|\-]+\|?\s*$/.test(line) && line.includes('-') && line.includes('|');
  // 扫出所有源码表格块
  const sourceTables = [];
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*\|.*\|/.test(lines[i]) && i + 1 < lines.length && isSep(lines[i + 1])) {
      let j = i + 2;
      while (j < lines.length && /^\s*\|.*\|/.test(lines[j])) j++;
      sourceTables.push([i, j]);
      i = j - 1;
    }
  }
  // 规范化: 折叠空白 + 分隔行对齐冒号样式 (:---:→---), 忽略对齐差异
  const norm = s => s.replace(/\s+/g, ' ').replace(/:?-+:?/g, '---').trim();
  const wantNorm = norm(tableElToMD(tableEl));
  for (const [s, e] of sourceTables) {
    if (norm(lines.slice(s, e).join('\n')) === wantNorm) return [s, e];
  }
  // 兜底: DOM 表格索引 ↔ 源码表格索引
  const root = vditorFoldRoot();
  const allTables = root ? [...root.querySelectorAll('table')] : [];
  const idx = allTables.indexOf(tableEl);
  if (idx >= 0 && idx < sourceTables.length) return sourceTables[idx];
  return null;
}

// 替换表格: 定位源码行范围 → 替换 → setValue 重渲染
// (避开 insertMD 的 focus 重置 / 块边界留空段落问题; setValue 会重置滚动+DOM, 手动恢复)
function replaceTableBlock(tableEl, newMD) {
  const vd = state.vditor;
  if (!vd) return;
  const doc = vd.getValue();
  const range = findTableSourceRange(tableEl, doc);
  if (!range) {
    console.warn('[table] 无法在源码中定位表格, 操作中止');
    return;
  }
  const lines = doc.split('\n');
  const newLines = [...lines.slice(0, range[0]), ...newMD.split('\n'), ...lines.slice(range[1])];
  const newDoc = newLines.join('\n');
  const scroller = els.contentBody;
  const savedScroll = scroller.scrollTop;
  vd.setValue(newDoc);
  // setValue 重渲染: 下一帧恢复滚动 + 重新应用标题折叠态 (DOM 重建, data-folded 丢失)
  requestAnimationFrame(() => {
    scroller.scrollTop = savedScroll;
    disconnectVditorFoldObserver();
    applyVditorHeadingFold();
  });
}

function applyTableAction(action) {
  const cellEl = tableMenuCellEl;
  if (!cellEl) return;
  const table = cellEl.closest('table');
  const tr = cellEl.closest('tr');
  if (!table || !tr) return;
  const trs = [...table.querySelectorAll('tr')];
  const rowIndex = trs.indexOf(tr);
  const trCells = [...tr.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH');
  const colIndex = trCells.indexOf(cellEl);
  const colCount = Math.max(1, ...trs.map(t => [...t.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH').length));

  if (action === 'table-add-row') {
    const md = tableElToMD(table);
    const lines = md.split('\n');
    // markdown 行: [0]=header [1]=sep [2+]=data; DOM tr0=header, trk(k≥1)=data→lines[k+1]
    // tr0 下方 → 插 lines[2] (sep 后首数据行); trk(k≥1) 下方 → 插 lines[k+2]
    const insertAt = rowIndex === 0 ? 2 : rowIndex + 2;
    const emptyRow = '| ' + [...Array(colCount)].map(() => ' ').join(' | ') + ' |';
    lines.splice(insertAt, 0, emptyRow);
    replaceTableBlock(table, lines.join('\n'));
    return;
  }
  if (action === 'table-add-col') {
    const md = tableElToMD(table);
    const lines = md.split('\n').map(line => {
      const m = line.match(/^\|([\s\S]*)\|$/);
      if (!m) return line;
      const cells = m[1].split('|').map(c => c.trim());
      cells.splice(colIndex + 1, 0, line.includes('---') ? '---' : ' ');
      return '| ' + cells.join(' | ') + ' |';
    });
    replaceTableBlock(table, lines.join('\n'));
    return;
  }
  if (action === 'table-del-row') {
    if (rowIndex === 0) { alert('表头行不能删除 (用「调整行列数」重建)'); return; }
    const md = tableElToMD(table);
    const lines = md.split('\n');
    // trk (k≥1) → lines[k+1]; 删该行
    const lineIdx = rowIndex + 1;
    if (lineIdx >= lines.length) return;
    lines.splice(lineIdx, 1);
    // 删光数据行 (只剩 header+sep) → 补一个空数据行保表格有效
    if (lines.length <= 2) {
      lines.push('| ' + [...Array(colCount)].map(() => ' ').join(' | ') + ' |');
    }
    replaceTableBlock(table, lines.join('\n'));
    return;
  }
  if (action === 'table-del-col') {
    if (colCount <= 1) { alert('至少保留一列'); return; }
    const md = tableElToMD(table);
    const lines = md.split('\n').map(line => {
      const m = line.match(/^\|([\s\S]*)\|$/);
      if (!m) return line;
      const cells = m[1].split('|').map(c => c.trim());
      if (colIndex < cells.length) cells.splice(colIndex, 1);
      return '| ' + cells.join(' | ') + ' |';
    });
    replaceTableBlock(table, lines.join('\n'));
    return;
  }
  if (action === 'table-resize') {
    const curRows = trs.length;
    const input = prompt('调整行列数 (行数 列数, 含表头; 以左上为基准裁剪/补足, 改动发生在右下):', curRows + ' ' + colCount);
    if (!input) return;
    const m = input.trim().match(/^(\d+)\s+(\d+)$/);
    if (!m) { alert('格式: 行数 列数, 如 3 2'); return; }
    const tR = parseInt(m[1], 10), tC = parseInt(m[2], 10);
    if (tR < 1 || tC < 1) { alert('行列数 >= 1'); return; }
    const cellsOf = r => [...(trs[r] ? trs[r].children : [])].filter(c => c.tagName === 'TD' || c.tagName === 'TH');
    const getCell = (r, c) => {
      const cell = cellsOf(r)[c];
      if (!cell) return ' ';
      const t = cell.textContent.replace(/\|/g, '\\|').replace(/\n/g, ' ').trim();
      return t || ' ';
    };
    const out = [];
    out.push('| ' + [...Array(tC)].map((_, c) => getCell(0, c)).join(' | ') + ' |');
    out.push('| ' + [...Array(tC)].map(() => '---').join(' | ') + ' |');
    for (let r = 1; r < tR; r++) {
      out.push('| ' + [...Array(tC)].map((_, c) => getCell(r, c)).join(' | ') + ' |');
    }
    replaceTableBlock(table, out.join('\n'));
    return;
  }
}

// ============== 表格拖选 + Delete (Vditor IR) ==============
// mousedown 单元格 + 拖动 → 矩形选区高亮; 松开保留选区。
// Delete/Backspace: 选区横跨所有列 → 删整行; 纵跨所有行 → 删整列; 否则清空内容。
// 点别处/单击单元格 → 清选区交 Vditor 编辑。
let tableDragStart = null;
let tableSel = null;

function tableCellPos(cell) {
  const table = cell.closest('table');
  const tr = cell.closest('tr');
  if (!table || !tr) return null;
  const trs = [...table.querySelectorAll('tr')];
  const cells = [...tr.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH');
  return { table, row: trs.indexOf(tr), col: cells.indexOf(cell) };
}
function tableDims(table) {
  const trs = [...table.querySelectorAll('tr')];
  const cols = Math.max(1, ...trs.map(tr => [...tr.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH').length));
  return { rows: trs.length, cols };
}
function highlightTableRegion(table, r1, r2, c1, c2) {
  clearCellHighlight();
  const trs = [...table.querySelectorAll('tr')];
  for (let r = r1; r <= r2; r++) {
    const cells = trs[r] ? [...trs[r].children].filter(c => c.tagName === 'TD' || c.tagName === 'TH') : [];
    for (let c = c1; c <= c2; c++) if (cells[c]) cells[c].classList.add('vditor-cell-selected');
  }
}
function clearTableSel() { clearCellHighlight(); tableSel = null; }

// mousedown (capture): 表格单元格记录拖拽起点 (仅左键; 不 preventDefault, 允许单击编辑)
els.vditorHost.addEventListener('mousedown', (e) => {
  if (!state.vditor || e.button !== 0) return;
  const cell = e.target.closest && e.target.closest('td,th');
  if (!cell || !cell.closest('table')) return;
  const pos = tableCellPos(cell);
  if (!pos) return;
  tableDragStart = { table: pos.table, row: pos.row, col: pos.col, x: e.clientX, y: e.clientY, moved: false };
}, true);

document.addEventListener('mousemove', (e) => {
  if (!tableDragStart) return;
  const dx = e.clientX - tableDragStart.x, dy = e.clientY - tableDragStart.y;
  if (!tableDragStart.moved && Math.hypot(dx, dy) > 6) {
    tableDragStart.moved = true;
    clearCellHighlight();
  }
  if (!tableDragStart.moved) return;
  e.preventDefault();  // 抑制 Vditor 文本选区
  const el = document.elementFromPoint(e.clientX, e.clientY);
  const cell = el && el.closest ? el.closest('td,th') : null;
  if (!cell || cell.closest('table') !== tableDragStart.table) return;
  const pos = tableCellPos(cell);
  if (!pos) return;
  const r1 = Math.min(tableDragStart.row, pos.row), r2 = Math.max(tableDragStart.row, pos.row);
  const c1 = Math.min(tableDragStart.col, pos.col), c2 = Math.max(tableDragStart.col, pos.col);
  highlightTableRegion(tableDragStart.table, r1, r2, c1, c2);
  tableSel = { table: tableDragStart.table, start: { row: tableDragStart.row, col: tableDragStart.col }, end: { row: pos.row, col: pos.col } };
});

document.addEventListener('mouseup', (e) => {
  if (!tableDragStart) return;
  if (!tableDragStart.moved) clearTableSel();  // 单击: 清旧选区, 交 Vditor 编辑
  else e.preventDefault();
  tableDragStart = null;
});

// Delete/Backspace: 有选区时按形状删行/列或清空 (capture, 抢在 Vditor 编辑前)
els.vditorHost.addEventListener('keydown', (e) => {
  if (!tableSel || (e.key !== 'Delete' && e.key !== 'Backspace')) return;
  e.preventDefault();
  e.stopPropagation();
  const { table, start, end } = tableSel;
  const dims = tableDims(table);
  const r1 = Math.min(start.row, end.row), r2 = Math.max(start.row, end.row);
  const c1 = Math.min(start.col, end.col), c2 = Math.max(start.col, end.col);
  const fullRows = c1 === 0 && c2 === dims.cols - 1;
  const fullCols = r1 === 0 && r2 === dims.rows - 1;
  if (fullRows && fullCols) clearTableRegion(table, 0, dims.rows - 1, 0, dims.cols - 1);
  else if (fullRows) deleteTableRows(table, r1, r2);
  else if (fullCols) deleteTableCols(table, c1, c2);
  else clearTableRegion(table, r1, r2, c1, c2);
  clearTableSel();
});

function deleteTableRows(table, r1, r2) {
  const md = tableElToMD(table);
  const lines = md.split('\n');
  const toDelete = new Set();
  for (let r = r1; r <= r2; r++) toDelete.add(r === 0 ? 0 : r + 1);  // tr0→line0, trk→line[k+1]
  const delHeader = toDelete.has(0);
  if (delHeader) toDelete.add(1);  // 连 sep 一起删
  let newLines = lines.filter((_, i) => !toDelete.has(i));
  const colCount = Math.max(1, (newLines[0] ? (newLines[0].match(/\|/g) || []).length - 1 : 1));
  if (delHeader && newLines.length >= 1) {
    // 第一保留行升为新 header, 其后补 sep
    const sep = '| ' + [...Array(colCount)].map(() => '---').join(' | ') + ' |';
    newLines = [newLines[0], sep, ...newLines.slice(1)];
  }
  if (newLines.length <= 1) {  // 只剩 header 或空 → 补 sep + 空数据行
    const sep = '| ' + [...Array(colCount)].map(() => '---').join(' | ') + ' |';
    const empty = '| ' + [...Array(colCount)].map(() => ' ').join(' | ') + ' |';
    if (newLines.length === 1) newLines.push(sep);
    newLines.push(empty);
  }
  replaceTableBlock(table, newLines.join('\n'));
}
function deleteTableCols(table, c1, c2) {
  const md = tableElToMD(table);
  const lines = md.split('\n').map(line => {
    const m = line.match(/^\|([\s\S]*)\|$/);
    if (!m) return line;
    const cells = m[1].split('|').map(c => c.trim());
    cells.splice(c1, c2 - c1 + 1);
    return '| ' + cells.join(' | ') + ' |';
  });
  replaceTableBlock(table, lines.join('\n'));
}
function clearTableRegion(table, r1, r2, c1, c2) {
  const trs = [...table.querySelectorAll('tr')];
  const colCount = tableDims(table).cols;
  const cellText = (tr, i) => {
    const cells = [...tr.children].filter(c => c.tagName === 'TD' || c.tagName === 'TH');
    return cells[i] ? cells[i].textContent.replace(/\|/g, '\\|').replace(/\n/g, ' ').trim() || ' ' : ' ';
  };
  const lineFor = (tr, rowIdx) => '| ' + [...Array(colCount)].map((_, c) => {
    if (rowIdx >= r1 && rowIdx <= r2 && c >= c1 && c <= c2) return ' ';
    return cellText(tr, c);
  }).join(' | ') + ' |';
  const out = [lineFor(trs[0], 0), '| ' + [...Array(colCount)].map(() => '---').join(' | ') + ' |'];
  for (let r = 1; r < trs.length; r++) out.push(lineFor(trs[r], r));
  replaceTableBlock(table, out.join('\n'));
}

// 右键唤出: 表格内 → 表格菜单; 否则样式面板 (仅 Vditor 编辑态)
els.vditorHost.addEventListener('contextmenu', (e) => {
  if (!state.vditor) return;
  e.preventDefault();
  e.stopPropagation();
  const cell = e.target.closest('td,th');
  if (cell && cell.closest('table')) {
    hideStyleMenu();
    showTableMenu(e.clientX, e.clientY, cell);
  } else {
    hideTableMenu();
    showStyleMenu(e.clientX, e.clientY);
  }
});
// 点击别处 / Escape 关闭 (两菜单都关)
document.addEventListener('click', (e) => {
  if (styleMenuEl && !styleMenuEl.hidden && !styleMenuEl.contains(e.target)) hideStyleMenu();
  if (tableMenuEl && !tableMenuEl.hidden && !tableMenuEl.contains(e.target)) hideTableMenu();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (styleMenuEl && !styleMenuEl.hidden) hideStyleMenu();
    if (tableMenuEl && !tableMenuEl.hidden) hideTableMenu();
  }
});

function renderMarkdown(file) {
  exitEditMode();
  els.welcome.hidden = true;
  els.viewer.hidden = false;
  els.editorHost.hidden = true;

  const { meta, body } = splitFrontmatter(file.content);
  let html = window.marked.parse(preprocessCenterImages(body));
  if (window.DOMPurify) {
    html = window.DOMPurify.sanitize(html, { ADD_ATTR: ['target'] });
  }
  els.viewer.innerHTML = renderFrontmatter(meta) + html;

  // 给所有标题加 slug id (支持内文 [链接](#heading) + URL hash 跳转)
  applyHeadingIds(els.viewer);

  // 若 URL 含 #hash, 跳转到对应标题 (首次渲染该文件时)
  if (location.hash && location.hash.length > 1) {
    const id = location.hash.slice(1);
    const target = els.viewer.querySelector('#' + CSS.escape(id));
    if (target) {
      requestAnimationFrame(() => {
        const scroller = els.contentBody;
        const rect = target.getBoundingClientRect();
        const scrollerRect = scroller.getBoundingClientRect();
        scroller.scrollTop = rect.top - scrollerRect.top + scroller.scrollTop - 8;
      });
      // 用完即清, 避免切换文件后误跳
      try { window.history.replaceState(null, '', window.location.pathname); } catch (_) {}
    }
  }

  // 后处理: 对 code 块运行 highlight.js
  els.viewer.querySelectorAll('pre code').forEach(block => {
    const cls = block.className || '';
    const langMatch = cls.match(/language-(\w+)/);
    const lang = langMatch ? langMatch[1] : '';
    if (lang && window.hljs.getLanguage(lang)) {
      try { window.hljs.highlightElement(block); } catch (e) {}
    } else if (window.hljs) {
      try { window.hljs.highlightElement(block); } catch (e) {}
    }
  });

  // 折叠功能: 标题 + 代码块
  applyHeadingCollapse(els.viewer, file.path);
  applyCodeCollapse(els.viewer, file.path);

  // drawio 内联渲染: ![alt](xxx.drawio) → GraphViewer 内联图 (无 iframe, 可折叠)
  applyDrawioInline(els.viewer, file.path);
  // 内嵌图片: 相对路径 → /api/reader/raw (drawio img 已在上步 replaceWith 出 DOM)
  applyImageRewrite(els.viewer, file.path);

  // mermaid 渲染: ```mermaid 代码块 → SVG
  renderMermaidBlocks(els.viewer);

  // 拦截 md 内 a 链接 (相对路径 .md → 站内打开)
  els.viewer.addEventListener('click', onViewerClick);

  // 生成目录大纲
  buildOutline(body);
  // 初始高亮当前目录项 (只读态)
  requestAnimationFrame(highlightCurrentOutline);
  // 批注锚标: 在新渲染的 viewer DOM 上重新应用
  requestAnimationFrame(() => applyCommentAnchors(els.viewer));
}

// ============== 渲染折叠 ==============
const COLLAPSE_KEY = 'webreader:collapse:';
function loadCollapsed(path) {
  try { return new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY + path) || '[]')); }
  catch { return new Set(); }
}
function saveCollapsed(path, set) {
  try { localStorage.setItem(COLLAPSE_KEY + path, JSON.stringify([...set])); } catch {}
}
function headingKey(headingEl) {
  // 用标题文本做稳定 key (跨渲染保持同一性; 编辑文档后失效可接受)
  // 兼容 Vditor IR: chevron 文本 (▼/▶) 已移至 CSS ::before 不入 DOM,
  // 但 Vditor heading textContent 含 "# " 前缀 (marker span), 规整掉以对齐 viewer key
  return 'h:' + (headingEl.textContent || '')
    .replace(/^\s*[▼▶]\s*/, '')
    .replace(/^#+\s*/, '')
    .trim();
}

// 把 viewer 顶层扁平的标题/内容流重组为嵌套 .md-section
function applyHeadingCollapse(root, path) {
  const collapsed = loadCollapsed(path);
  const kids = [...root.childNodes];
  const stack = []; // { section, level, body }
  for (const node of kids) {
    if (node.nodeType === 1 && /^H[1-6]$/.test(node.tagName)) {
      const level = parseInt(node.tagName[1], 10);
      while (stack.length && stack[stack.length - 1].level >= level) stack.pop();

      const section = document.createElement('div');
      section.className = 'md-section';
      section.dataset.level = level;

      const chev = document.createElement('span');
      chev.className = 'md-collapse-chevron';
      chev.textContent = '▼';
      node.insertBefore(chev, node.firstChild);

      const lvl = document.createElement('span');
      lvl.className = 'md-level-badge';
      lvl.textContent = 'H' + level;
      node.appendChild(lvl);

      const body = document.createElement('div');
      body.className = 'md-section-body';
      section.appendChild(node);   // 标题作为 section 头 (始终可见)
      section.appendChild(body);    // 其后内容进 body (可隐藏)

      const key = headingKey(node);
      const isCollapsed = collapsed.has(key);
      section.dataset.collapsed = isCollapsed ? 'true' : 'false';
      chev.addEventListener('click', (e) => {
        e.stopPropagation();
        const now = section.dataset.collapsed === 'true';
        section.dataset.collapsed = now ? 'false' : 'true';
        const s = loadCollapsed(path);
        if (now) s.delete(key); else s.add(key);
        saveCollapsed(path, s);
      });

      if (stack.length) stack[stack.length - 1].body.appendChild(section);
      else root.appendChild(section);
      stack.push({ section, level, body });
    } else if (stack.length) {
      // 非标题内容归入当前最深 section body; 第一个标题前的内容保留在 root
      stack[stack.length - 1].body.appendChild(node);
    }
  }
}

// ============== Vditor IR 标题折叠 + 编辑态目录同步 ==============
// Vditor IR 把 md 渲染在 pre.vditor-reset (或多级 fallback 的 contenteditable 区),
// h1~h6 与后续段落/列表/代码块为扁平兄弟节点, 模型同 viewer:
// 点击标题前缘 chevron 即隐藏其后到下一同级/更高级标题之间的所有兄弟。
// 不向 contenteditable DOM 注入节点 (避免污染 Lute getValue 序列化):
// chevron 用 CSS ::before 呈现, 点击靠 left 缘位置判定 + 委托 listener (跨 Vditor 重渲染存活)。
let vditorFoldObserver = null;
let vditorFoldClickAttached = false;
let vditorFoldInitRetries = 0;

function vditorFoldRoot() {
  // 此版 Vditor IR: 标题在 .vditor-ir 内 (非 pre.vditor-reset), 故优先取 .vditor-ir
  // 兜底 pre.vditor-reset / contenteditable, 防其它版本结构差异
  return els.vditorHost.querySelector('.vditor-ir')
      || els.vditorHost.querySelector('.vditor-ir [contenteditable="true"]')
      || els.vditorHost.querySelector('pre.vditor-reset');
}

// 根据持久化态设置 heading data-folded + 隐藏/显示后续同级兄弟
function applyVditorFoldState(heading) {
  const level = parseInt(heading.tagName[1], 10);
  if (!level || level < 1 || level > 6) return;
  const path = state.currentFile ? state.currentFile.path : '';
  const isColl = loadCollapsed(path).has(headingKey(heading));
  heading.dataset.folded = isColl ? '1' : '0';
  let sib = heading.nextElementSibling;
  while (sib) {
    const tag = sib.tagName;
    if (/^H[1-6]$/.test(tag) && parseInt(tag[1], 10) <= level) break;
    // 仅由折叠驱动的隐藏: 用 hidden 属性, 不改 display (避免覆盖 Vditor 自身逻辑)
    sib.hidden = isColl;
    sib = sib.nextElementSibling;
  }
}

// 清除标题内的 ## markdown 标记 (结构无关: 任何文本只含 # 的 span/元素都隐藏)
// Vditor IR 对标题不套 .vditor-ir__node, 默认 width:0 隐藏不生效 → CSS 按类名隐藏不可靠, 用 JS 兜底
function cleanHeadingMarkers(heading) {
  heading.querySelectorAll('*').forEach(el => {
    if (el === heading) return;
    // 直接子文本只含 # + 空白 → 隐藏该元素
    const direct = [...el.childNodes].filter(n => n.nodeType === 1 || n.nodeType === 3);
    if (direct.length && direct.every(n => n.nodeType === 3 ? /^\s*#+\s*$/.test(n.textContent) : false)) {
      if (/^\s*#+\s*$/.test(el.textContent)) el.style.display = 'none';
    }
  });
  // 也处理 heading 直接文本节点前导 ##
  heading.childNodes.forEach(n => {
    if (n.nodeType === 3 && /^\s*#+\s+/.test(n.textContent)) {
      n.textContent = n.textContent.replace(/^\s*#+\s+/, '');
    }
  });
}

// 委托监听挂到稳定的 els.vditorHost (不挂 pre, 防 Vditor 重建 pre 失效)。
// 用 mousedown + capture: 在 Vditor 的 bubble 阶段 cursor-placement 之前截获,
// 命中 chevron 区即 preventDefault (阻止落光标) + stopPropagation (阻断 Vditor)。
function ensureVditorFoldClickHandler() {
  if (vditorFoldClickAttached) return;
  vditorFoldClickAttached = true;
  els.vditorHost.addEventListener('mousedown', (e) => {
    if (!state.vditor) return;
    const heading = e.target.closest && e.target.closest('h1,h2,h3,h4,h5,h6');
    if (!heading || !els.vditorHost.contains(heading)) return;
    // 仅 Vditor IR 内 (viewer 有自己的 applyHeadingCollapse 折叠, 不抢)
    if (!heading.closest('.vditor-ir')) return;
    const rect = heading.getBoundingClientRect();
    const padL = parseFloat(getComputedStyle(heading).paddingLeft) || 0;
    const zone = padL;  // 命中区 = 左 gutter (三角形所在), gutter 外是标题文本交给 Vditor 编辑
    // debug: DevTools Console 可见命中情况
    console.log('[fold] mousedown', heading.tagName, 'dx=', Math.round(e.clientX - rect.left), 'zone=', zone);
    if (e.clientX - rect.left > zone) return;  // 非 chevron 区: 放行交 Vditor
    e.stopPropagation();
    e.preventDefault();
    const path = state.currentFile ? state.currentFile.path : '';
    const key = headingKey(heading);
    const s = loadCollapsed(path);
    if (s.has(key)) s.delete(key); else s.add(key);
    saveCollapsed(path, s);
    applyVditorFoldState(heading);
  }, true);
}

function applyVditorHeadingFold() {
  console.log('[fold] applyVditorHeadingFold called, currentFile=', !!state.currentFile, 'vditor=', !!state.vditor);
  if (!state.currentFile || !state.vditor) return;
  ensureVditorFoldClickHandler();
  const root = vditorFoldRoot();
  console.log('[fold] vditorFoldRoot() =>', root ? root.tagName + '.' + root.className : 'null');
  if (!root) {
    // Vditor IR DOM 尚未就绪 → 轮询重试 (最多 ~2s)
    if (vditorFoldInitRetries < 10) {
      vditorFoldInitRetries++;
      setTimeout(applyVditorHeadingFold, 200);
    }
    return;
  }
  vditorFoldInitRetries = 0;
  const headings = root.querySelectorAll('h1,h2,h3,h4,h5,h6');
  headings.forEach(applyVditorFoldState);
  console.log('[fold] init on', root.tagName + '.' + root.className, 'headings=', headings.length);
  if (headings[0]) console.log('[fold] heading sample HTML:', headings[0].outerHTML.slice(0, 400));
  connectVditorFoldObserver();
  // 切换编辑后: headings 就绪 → 恢复文档位置 + 高亮目录 (此前 double-rAF 时 headings 可能未渲染, NOT FOUND)
  if (state._scrollAnchor) {
    scrollToHeadingText(state._scrollAnchor);
    state._scrollAnchor = '';
  }
  requestAnimationFrame(highlightCurrentOutline);
}

function connectVditorFoldObserver() {
  const root = vditorFoldRoot();
  if (!root || vditorFoldObserver) return;
  vditorFoldObserver = new MutationObserver(() => {
    if (!state.vditor || !state.currentFile) return;
    const r = vditorFoldRoot();
    if (!r) return;
    // Vditor 结构变动后立即复核所有 heading 的 data-folded + 兄弟 hidden 态 (不 debounce, 防闪)
    r.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(applyVditorFoldState);
  });
  // subtree: Vditor 可能在子层重建节点
  vditorFoldObserver.observe(root, { childList: true, subtree: true });
}

function disconnectVditorFoldObserver() {
  if (vditorFoldObserver) {
    vditorFoldObserver.disconnect();
    vditorFoldObserver = null;
  }
  vditorFoldInitRetries = 0;
}

// 编辑时同步目录大纲 (debounced, 复用 buildOutline, 用 Vditor 当前 getValue)
let vditorOutlineSchedule = 0;
function scheduleVditorOutline() {
  if (vditorOutlineSchedule) return;
  vditorOutlineSchedule = setTimeout(() => {
    vditorOutlineSchedule = 0;
    if (!state.vditor || !state.currentFile) return;
    const md = state.vditor.getValue();
    const { body } = splitFrontmatter(md);
    buildOutline(body);
  }, 400);
}

function applyCodeCollapse(root, path) {
  const collapsed = loadCollapsed(path);
  const pres = root.querySelectorAll('pre');
  pres.forEach((pre, idx) => {
    if (pre.parentElement && pre.parentElement.classList.contains('md-codeblock')) return;
    const code = pre.querySelector('code');
    const langMatch = code && (code.className || '').match(/language-(\w+)/);
    const lang = langMatch ? langMatch[1] : 'text';
    const lineCount = code ? code.textContent.split('\n').length : 0;

    const wrap = document.createElement('div');
    wrap.className = 'md-codeblock';
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);

    const badge = document.createElement('button');
    badge.type = 'button';
    badge.className = 'md-code-badge';
    const key = 'c:' + idx;
    const render = (isColl) => {
      badge.textContent = isColl
        ? lang + ' ▶ (' + lineCount + ' lines)'
        : lang + ' ▼';
    };
    let isCollapsed = collapsed.has(key);
    wrap.dataset.collapsed = isCollapsed ? 'true' : 'false';
    render(isCollapsed);
    badge.addEventListener('click', (e) => {
      e.stopPropagation();
      isCollapsed = !isCollapsed;
      wrap.dataset.collapsed = isCollapsed ? 'true' : 'false';
      render(isCollapsed);
      const s = loadCollapsed(path);
      if (isCollapsed) s.add(key); else s.delete(key);
      saveCollapsed(path, s);
    });
    wrap.appendChild(badge);
  });
}

// ============== drawio 内联渲染 ==============
// md 里 ![alt](xxx.drawio) 被 marked 默认渲染成 <img src="xxx.drawio" alt="alt">,
// 这里 post-process (在 DOMPurify sanitize 之后, 直接 DOM 操作) 把这类 img 替换为
// GraphViewer 内联图: 无 iframe, 宽度自适应, 由 md 文档自身滚动控制, 每张可折叠.
// 路径相对当前 md 文件解析 (复用 resolveRelative). viewer-static.min.js 懒加载.

let drawioViewerPromise = null;
function ensureDrawioViewer() {
  if (window.GraphViewer) return Promise.resolve();
  if (drawioViewerPromise) return drawioViewerPromise;
  drawioViewerPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'vendor/drawio/viewer-static.min.js';
    s.onload = () => resolve();
    s.onerror = () => {
      drawioViewerPromise = null;
      reject(new Error('viewer-static.min.js 加载失败, 跑 tools/WebReader/fetch_drawio.ps1 下载'));
    };
    document.head.appendChild(s);
  });
  return drawioViewerPromise;
}

const DRAWIO_KEY = 'd:';

// 把单张内联 drawio img 替换为折叠 wrapper, 返回 { wrap, body, resolved, alt }
function buildDrawioWrap(img, basePath, collapsed, idx) {
  const rawSrc = img.getAttribute('src') || '';
  const alt = img.getAttribute('alt') || '';
  const resolved = resolveRelative(basePath, rawSrc) || rawSrc;
  // key 加 idx: 同文档多次引用同一 .drawio 时独立折叠 (跨渲染按出现顺序稳定)
  const key = DRAWIO_KEY + resolved + ':' + idx;
  const isCollapsed = collapsed.has(key);

  const wrap = document.createElement('div');
  wrap.className = 'md-drawio';
  wrap.dataset.collapsed = isCollapsed ? 'true' : 'false';

  const head = document.createElement('div');
  head.className = 'md-drawio-head';
  const chev = document.createElement('span');
  chev.className = 'md-collapse-chevron';
  chev.textContent = '▼';
  const title = document.createElement('span');
  title.className = 'md-drawio-title';
  title.textContent = alt || rawSrc;
  const tag = document.createElement('span');
  tag.className = 'md-drawio-tag';
  tag.textContent = resolved;
  head.append(chev, title, tag);

  const body = document.createElement('div');
  body.className = 'md-drawio-body';
  const placeholder = document.createElement('div');
  placeholder.className = 'md-drawio-placeholder';
  placeholder.textContent = '📐 加载中: ' + (alt || rawSrc);
  body.appendChild(placeholder);

  wrap.append(head, body);
  img.replaceWith(wrap);

  head.addEventListener('click', (e) => {
    e.stopPropagation();
    const now = wrap.dataset.collapsed === 'true';
    wrap.dataset.collapsed = now ? 'false' : 'true';
    const s = loadCollapsed(basePath);
    if (now) s.delete(key); else s.add(key);
    saveCollapsed(basePath, s);
  });

  return { wrap, body, resolved, alt };
}

// 异步 fetch drawio 文件内容, 构建 mxgraph 节点插入 body (不触发渲染, 统一在 applyDrawioInline 末尾调 processElements)
async function fetchDrawioNode({ wrap, body, resolved, alt }) {
  if (!wrap.isConnected) return; // 文件已切换, 旧节点脱离 DOM
  try {
    const file = await apiFile(resolved);
    if (!wrap.isConnected) return;
    const xml = file.content || '';
    if (!xml.trim()) throw new Error('文件为空');
    const node = document.createElement('div');
    node.className = 'mxgraph';
    node.style.cssText = 'background:#fff;max-width:100%';
    node.dataset.mxgraph = JSON.stringify({
      highlight: '#0000ff',
      nav: true,
      resize: true,
      xml: xml
    });
    body.innerHTML = '';
    body.appendChild(node);
  } catch (e) {
    if (!wrap.isConnected) return;
    body.innerHTML = '<div class="md-drawio-error">📐 加载失败: ' + escHtml(resolved) + ' (' + escHtml(e.message) + ')</div>';
  }
}

function applyDrawioInline(root, basePath) {
  const imgs = [...root.querySelectorAll('img')].filter(img =>
    /\.(drawio|dio)$/i.test(img.getAttribute('src') || '')
  );
  if (!imgs.length) return;
  const collapsed = loadCollapsed(basePath);
  const pending = imgs.map((img, i) => buildDrawioWrap(img, basePath, collapsed, i)).filter(Boolean);
  if (!pending.length) return;

  ensureDrawioViewer().then(async () => {
    // 并行 fetch + 构建 mxgraph 节点
    await Promise.all(pending.map(p => fetchDrawioNode(p)));
    // 统一触发渲染 (processElements 全局扫描未初始化的 .mxgraph)
    if (window.GraphViewer) {
      try { window.GraphViewer.processElements(); } catch (e) {}
    }
  }).catch(err => {
    pending.forEach(p => {
      if (p.wrap.isConnected) {
        p.body.innerHTML = '<div class="md-drawio-error">📐 ' + escHtml(err.message) + '</div>';
      }
    });
  });
}

// ============================================================
// Mermaid 图渲染 (```mermaid 代码块 → SVG)
// 两条渲染路径共用:
//   1. marked 只读态 (els.viewer) — <pre><code class="language-mermaid"> 直接替换为 .mermaid-block
//   2. Vditor IR 编辑态 (els.vditorHost) — 保留代码块可编辑, 在 IR 节点后插入 .mermaid-preview
// ============================================================

let __mermaidInited = false;
let __mermaidSeq = 0;            // 每次 render 分配递增 seq, 防异步竞态
let __mermaidTimer = null;

function ensureMermaidInit() {
  if (__mermaidInited || !window.mermaid) return;
  try {
    window.mermaid.initialize({
      startOnLoad: false,
      theme: 'default',
      securityLevel: 'loose',    // 允许 label 含特殊字符 + 点击事件
      fontFamily: 'inherit',
    });
    __mermaidInited = true;
  } catch (e) {
    console.warn('[mermaid] init failed:', e);
  }
}

// 收集 mermaid 渲染目标 (返回新建/复用的 div 节点数组)
function collectMermaidTargets(rootEl) {
  const targets = [];

  // 路径 A: marked 只读态 → <pre><code class="language-mermaid">
  //   applyCodeCollapse 已把每个 <pre> 包到 <div class="md-codeblock"> 里 (含 badge 按钮),
  //   因此要替换整个 .md-codeblock 而非仅 <pre>, 否则 badge 孤立。
  rootEl.querySelectorAll('code.language-mermaid').forEach(code => {
    const pre = code.parentElement;
    if (!pre || pre.tagName !== 'PRE') return;
    const wrap = pre.closest('.md-codeblock');    // applyCodeCollapse 创建的包裹层
    const src = code.textContent || '';
    if (!src.trim()) return;
    const div = document.createElement('div');
    div.className = 'mermaid mermaid-block';
    div.textContent = src;
    if (wrap && wrap.parentElement) {
      wrap.replaceWith(div);
    } else {
      pre.replaceWith(div);
    }
    targets.push(div);
  });

  // 路径 B: Vditor IR 编辑态 → 保留代码块可编辑, 在 IR 节点后插入预览
  //   Vditor IR 结构: <div class="vditor-ir__node">
  //     <span class="vditor-ir__marker vditor-ir__marker--info">language-mermaid</span>
  //     <pre class="vditor-ir__marker vditor-ir__marker--pre"><code data-type="code-block">...</code></pre>
  //     ...
  rootEl.querySelectorAll('.vditor-ir__marker--info').forEach(info => {
    const lang = (info.textContent || '').trim().toLowerCase();
    if (!lang.includes('mermaid')) return;
    const irNode = info.closest('.vditor-ir__node');
    if (!irNode) return;
    const codeEl = irNode.querySelector('pre code, code');
    if (!codeEl) return;
    const src = codeEl.textContent || '';
    if (!src.trim()) return;

    // 已存在预览则复用, 否则新建 (input 事件每次重建 src, 触发 mermaid 重渲)
    let preview = irNode.nextElementSibling;
    if (!preview || !preview.classList.contains('mermaid-preview')) {
      preview = document.createElement('div');
      preview.className = 'mermaid mermaid-preview';
      irNode.after(preview);
    }
    preview.textContent = src;
    preview.removeAttribute('data-processed');  // 让 mermaid.run 重新渲染
    preview.classList.remove('mermaid-error');
    targets.push(preview);
  });

  return targets;
}

async function renderMermaidBlocks(rootEl) {
  if (!window.mermaid || !rootEl) return;
  ensureMermaidInit();
  if (!__mermaidInited) return;

  const targets = collectMermaidTargets(rootEl);
  if (targets.length === 0) return;

  const seq = ++__mermaidSeq;
  try {
    // mermaid.run 接收带 .mermaid class 的节点数组, 读 textContent 渲染 SVG 注入
    await window.mermaid.run({ nodes: targets });
    if (seq !== __mermaidSeq) return;    // 被后续 render 覆盖, 跳过收尾
  } catch (e) {
    console.warn('[mermaid] render failed:', e);
    targets.forEach(div => {
      if (!div.querySelector('svg')) {
        div.classList.add('mermaid-error');
        div.textContent = '[mermaid 渲染失败] ' + (e && e.message || e);
      }
    });
  }
}

// Vditor IR input 回调用: debounce 重扫 (先清孤立预览, 再重渲)
// 孤立预览 = 前一个兄弟不再是 mermaid IR 节点 (用户改了语言或删了块)
function scheduleMermaidRender(rootEl) {
  if (__mermaidTimer) clearTimeout(__mermaidTimer);
  __mermaidTimer = setTimeout(() => {
    __mermaidTimer = null;
    if (!rootEl || !rootEl.isConnected) return;
    rootEl.querySelectorAll('.mermaid-preview').forEach(preview => {
      const prev = preview.previousElementSibling;
      const info = prev && prev.querySelector && prev.querySelector('.vditor-ir__marker--info');
      const stillMermaid = info && (info.textContent || '').toLowerCase().includes('mermaid');
      if (!stillMermaid) preview.remove();
    });
    // 内嵌图片重写 (Vditor IR input 重渲后 img 重建, 需重新改 src)
    applyImageRewrite(rootEl, state.currentFile ? state.currentFile.path : '');
    renderMermaidBlocks(rootEl);
  }, 500);
}

// ============================================================
// Mermaid 点击放大 (lightbox)
// 任意 .mermaid / .mermaid-preview 内 svg 点击 → 全屏 overlay 放大
// 支持: 滚轮缩放 + 工具栏按钮 (+/−/1:1/适配) + 拖动平移 + Esc/点空白关闭
// ============================================================

const mermaidZoom = (function buildMermaidZoom() {
  const overlay = document.getElementById('mermaid-zoom');
  if (!overlay) return null;
  const stage = overlay.querySelector('.mermaid-zoom-stage');
  const scaleLabel = overlay.querySelector('.mermaid-zoom-scale');
  const MIN_SCALE = 0.3;
  const MAX_SCALE = 8;
  let scale = 1;
  let currentSvg = null;

  function updateScale() {
    if (currentSvg) currentSvg.style.transform = `scale(${scale})`;
    if (scaleLabel) scaleLabel.textContent = Math.round(scale * 100) + '%';
  }
  function setScale(s) {
    scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));
    updateScale();
  }
  // SVG 自然尺寸: 优先 viewBox (mermaid 10 总是有, 最可靠); 其次非百分比 width/height 属性; 兜底 getBoundingClientRect
  function naturalSize(svg) {
    const vb = svg.getAttribute('viewBox');
    if (vb) {
      const parts = vb.split(/[\s,]+/).map(parseFloat);
      if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
        return { w: parts[2], h: parts[3] };
      }
    }
    const wAttr = svg.getAttribute('width');
    const hAttr = svg.getAttribute('height');
    const isPx = v => v && !v.endsWith('%') && !v.endsWith('em') && v !== 'auto';
    if (isPx(wAttr) && isPx(hAttr)) {
      const w = parseFloat(wAttr);
      const h = parseFloat(hAttr);
      if (w > 0 && h > 0) return { w, h };
    }
    const r = svg.getBoundingClientRect();
    return { w: r.width || 800, h: r.height || 600 };
  }
  function open(svg) {
    currentSvg = svg.cloneNode(true);
    // 清掉 CSS + 百分比 width/height, 让 viewBox + 显式 px 控制
    currentSvg.removeAttribute('style');
    ['width', 'height'].forEach(attr => {
      const v = currentSvg.getAttribute(attr);
      if (v && (v.endsWith('%') || v === 'auto')) currentSvg.removeAttribute(attr);
    });
    const ns = naturalSize(currentSvg);
    if (ns.w && ns.h) {
      currentSvg.setAttribute('width', ns.w);
      currentSvg.setAttribute('height', ns.h);
    }
    currentSvg.style.transformOrigin = 'center center';
    currentSvg.style.display = 'block';
    stage.innerHTML = '';
    stage.appendChild(currentSvg);
    scale = 1;
    // 初始缩放: 总是适配舞台 (scale 可能 < 1), 确保整图可见 + 居中
    requestAnimationFrame(() => {
      const sRect = stage.getBoundingClientRect();
      const pad = 40;
      const fit = Math.min((sRect.width - pad) / ns.w, (sRect.height - pad) / ns.h);
      setScale(fit);
      // 重置滚动到中心 (用户缩放放大后能从中心起滚)
      stage.scrollLeft = (stage.scrollWidth - stage.clientWidth) / 2;
      stage.scrollTop = (stage.scrollHeight - stage.clientHeight) / 2;
    });
    overlay.hidden = false;
  }
  function close() {
    overlay.hidden = true;
    if (stage) stage.innerHTML = '';
    currentSvg = null;
  }

  // 工具栏按钮 + 滚轮缩放
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) { close(); return; }
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'close') close();
    else if (act === 'zoom-in') setScale(scale * 1.2);
    else if (act === 'zoom-out') setScale(scale / 1.2);
    else if (act === 'reset') setScale(1);
    else if (act === 'fit') {
      if (!currentSvg) return;
      const ns = naturalSize(currentSvg);
      const sRect = stage.getBoundingClientRect();
      const pad = 40;
      setScale(Math.min((sRect.width - pad) / ns.w, (sRect.height - pad) / ns.h));
    }
  });
  stage.addEventListener('wheel', (e) => {
    // 仅 Ctrl+滚轮 缩放; 普通滚轮交给浏览器原生滚动 (平移)
    if (!e.ctrlKey) return;
    if (!currentSvg) return;
    e.preventDefault();
    setScale(scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
  }, { passive: false });

  return { open, close, isOpen: () => !overlay.hidden };
})();

// 委托: 任何 .mermaid / .mermaid-preview 内 svg 点击 → 放大
document.addEventListener('click', (e) => {
  const svg = e.target.closest('.mermaid svg, .mermaid-preview svg');
  if (!svg) return;
  if (svg.closest('.mermaid-error')) return;     // 错误占位不可点
  e.preventDefault();
  if (mermaidZoom) mermaidZoom.open(svg);
});

// ESC 关闭 (与 search/quickopen modal 同款处理)
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && mermaidZoom && mermaidZoom.isOpen()) {
    mermaidZoom.close();
    e.preventDefault();
  }
});

function renderCode(file) {
  exitEditMode();
  els.welcome.hidden = true;
  els.viewer.hidden = false;
  els.editorHost.hidden = true;

  const lang = highlightLangForFile(file.extension);
  let code = file.content;
  if (lang && window.hljs && window.hljs.getLanguage(lang)) {
    try { code = window.hljs.highlight(code, { language: lang, ignoreIllegals: true }).value; }
    catch (e) {}
  }
  const langClass = lang ? ' language-' + lang : '';
  els.viewer.innerHTML = '<pre class="code-view"><code class="hljs' + langClass + '">' + code + '</code></pre>';
  els.viewer.addEventListener('click', onViewerClick);
  // 代码文件无大纲
  els.outlineBody.innerHTML = '<div class="outline-empty">仅 Markdown 文件有目录大纲</div>';
}

function onViewerClick(e) {
  const a = e.target.closest('a');
  if (!a) return;
  // marked 渲染的 a.href 对中文/全角字符做 URL-encode (如 %EF%BC%9A)。
  // 直接用编码串作路径 → apiFile 再 encodeURIComponent → 双重编码 → 后端 404。
  // 解：先 decodeURIComponent 还原成原始 md 文本，再走 resolveRelative。
  let href;
  try { href = decodeURIComponent(a.getAttribute('href') || ''); }
  catch (_) { href = a.getAttribute('href') || ''; }
  if (!href) return;
  // 内文锚链接 (#heading-id): 滚动到同文件内对应标题
  if (href.startsWith('#')) {
    e.preventDefault();
    const id = href.slice(1);
    if (!id) return;
    let target = null;
    try { target = els.viewer.querySelector('#' + CSS.escape(id)); } catch (_) {}
    if (!target) {
      // 兜底: 按 slug 文本匹配 (标题 id 由 slugify 生成)
      target = [...els.viewer.querySelectorAll('h1,h2,h3,h4,h5,h6')]
        .find(h => h.id === id || slugify(h.textContent) === id);
    }
    if (target) {
      const scroller = els.contentBody;
      const rect = target.getBoundingClientRect();
      const scrollerRect = scroller.getBoundingClientRect();
      scroller.scrollTop = rect.top - scrollerRect.top + scroller.scrollTop - 8;
      target.style.transition = 'background 0.5s';
      const oldBg = target.style.background;
      target.style.background = 'rgba(255, 213, 79, 0.4)';
      setTimeout(() => { target.style.background = oldBg; }, 800);
    }
    return;
  }
  // 站内相对链接: 忽略外部
  if (/^https?:\/\//i.test(href) || href.startsWith('mailto:')) return;
  e.preventDefault();
  if (!state.currentFile) return;
  // 带 #anchor 的站内链接: 打开目标文件后跳转到对应标题
  const anchorIdx = href.indexOf('#');
  const anchor = anchorIdx >= 0 ? href.slice(anchorIdx + 1) : '';
  const filePart = anchorIdx >= 0 ? href.slice(0, anchorIdx) : href;
  const resolved = filePart ? resolveRelative(state.currentFile.path, filePart) : state.currentFile.path;
  if (!resolved) return;
  if (resolved === state.currentFile.path && anchor) {
    // 同文件锚跳转 (手动触发, 因 a 标签默认行为已 preventDefault)
    const fakeA = document.createElement('a');
    fakeA.setAttribute('href', '#' + anchor);
    onViewerClick({ target: fakeA, preventDefault: () => {} });
    return;
  }
  openFile(resolved).then(() => {
    if (anchor) {
      // 等渲染完成后触发 hash 跳转
      try { window.history.replaceState(null, '', '#' + anchor); } catch (_) {}
      requestAnimationFrame(() => {
        const target = els.viewer.querySelector('#' + CSS.escape(anchor));
        if (target) {
          const scroller = els.contentBody;
          const rect = target.getBoundingClientRect();
          const scrollerRect = scroller.getBoundingClientRect();
          scroller.scrollTop = rect.top - scrollerRect.top + scroller.scrollTop - 8;
        }
      });
    }
  });
}

function resolveRelative(basePath, href) {
  // basePath: "a/b/c.md", href: "./d.md" | "../d.md" | "d.md" | "/abs"
  let target = href.split('#')[0].split('?')[0];
  if (!target) return null;
  if (target.startsWith('/')) {
    target = target.slice(1);
  } else {
    const baseDir = basePath.includes('/') ? basePath.slice(0, basePath.lastIndexOf('/')) : '';
    const parts = (baseDir ? baseDir + '/' : '') + target;
    const segs = [];
    for (const p of parts.split('/')) {
      if (p === '' || p === '.') continue;
      if (p === '..') { segs.pop(); continue; }
      segs.push(p);
    }
    target = segs.join('/');
  }
  return target;
}

// ============== 编辑模式 (CodeMirror 6) ==============
// ============== Markdown 格式快捷键 ==============
// 编辑模式下对选区切换 H1..H6 / 引用块 / 粗体；相同格式再次应用 = 移除。

// 计算选区覆盖的行号范围（含两端）；若选区终点落在行首，不吞掉下一行。
function selectedLineRange(view) {
  const { from, to } = view.state.selection.main;
  const doc = view.state.doc;
  const fromLine = doc.lineAt(from).number;
  const rawToLine = doc.lineAt(to).number;
  const toLine = (to > from && to === doc.line(rawToLine).from) ? rawToLine - 1 : rawToLine;
  return [fromLine, Math.max(fromLine, toLine)];
}

function toggleHeading(view, level) {
  const [fromLine, toLine] = selectedLineRange(view);
  const changes = [];
  for (let n = fromLine; n <= toLine; n++) {
    const line = view.state.doc.line(n);
    const m = line.text.match(/^(#{1,6})\s+(.*)$/);
    const body = m ? m[2] : line.text.replace(/^#{0,6}\s*/, '');
    const insert = (m && m[1].length === level) ? body : '#'.repeat(level) + ' ' + body;
    changes.push({ from: line.from, to: line.to, insert });
  }
  view.dispatch({ changes, userEvent: 'input' });
  return true;
}

function toggleBlockquote(view) {
  const [fromLine, toLine] = selectedLineRange(view);
  const changes = [];
  for (let n = fromLine; n <= toLine; n++) {
    const line = view.state.doc.line(n);
    const m = line.text.match(/^>\s?(.*)$/);
    const insert = m ? m[1] : '> ' + line.text;
    changes.push({ from: line.from, to: line.to, insert });
  }
  view.dispatch({ changes, userEvent: 'input' });
  return true;
}

function toggleBold(view) {
  const { from, to } = view.state.selection.main;
  const doc = view.state.doc;
  if (from === to) {
    view.dispatch({
      changes: { from, insert: '****' },
      selection: { anchor: from + 2, head: from + 2 },
      userEvent: 'input',
    });
    return true;
  }
  const prefix = doc.sliceString(Math.max(0, from - 2), from);
  const suffix = doc.sliceString(to, Math.min(doc.length, to + 2));
  if (prefix === '**' && suffix === '**') {
    const inner = doc.sliceString(from, to);
    view.dispatch({
      changes: { from: from - 2, to: to + 2, insert: inner },
      selection: { anchor: from - 2, head: to - 2 },
      userEvent: 'input',
    });
  } else {
    const inner = doc.sliceString(from, to);
    view.dispatch({
      changes: { from, to, insert: '**' + inner + '**' },
      selection: { anchor: from + 2, head: to + 2 },
      userEvent: 'input',
    });
  }
  return true;
}

const mdFormatBindings = [
  { key: 'Alt-Mod-1', preventDefault: true, run: (v) => toggleHeading(v, 1) },
  { key: 'Alt-Mod-2', preventDefault: true, run: (v) => toggleHeading(v, 2) },
  { key: 'Alt-Mod-3', preventDefault: true, run: (v) => toggleHeading(v, 3) },
  { key: 'Alt-Mod-4', preventDefault: true, run: (v) => toggleHeading(v, 4) },
  { key: 'Alt-Mod-5', preventDefault: true, run: (v) => toggleHeading(v, 5) },
  { key: 'Alt-Mod-6', preventDefault: true, run: (v) => toggleHeading(v, 6) },
  { key: 'Mod-Shift-u', preventDefault: true, run: toggleBlockquote },
  { key: 'Mod-b', preventDefault: true, run: toggleBold },
];

// ============== 列表缩进 + 表格行扩展 ==============
// 列表行: "  - foo" / "1. bar" 等; 缩进档位 0/2/4 (三级)
const LIST_LINE_RE = /^(\s*)([-*+]|\d+\.)\s+/;
const TABLE_ROW_RE = /^\|.*\|\s*$/;

function listIndentAmount(text) {
  const m = text.match(LIST_LINE_RE);
  return m ? m[1].length : -1;
}

// Tab(+1)/Shift-Tab(-1); 仅作用于选区内列表行; 步长 4 空格, 级别 0/4/8 (三级)
// 4 空格兼容有序父 (1./2. 内容起始于 col 3) 与无序父 (- 内容起始于 col 2)
// marker 保持原样 (有序留 1./2., 无序留 -); 视觉父子区分交给 CSS marker 变体
function findPrevListMarkerAt(doc, fromLineNum, maxIndent) {
  for (let n = fromLineNum - 1; n >= 1; n--) {
    const line = doc.line(n);
    const m = line.text.match(LIST_LINE_RE);
    if (!m) continue;
    const ind = m[1].length;
    if (ind <= maxIndent) return m[2];
    // ind > maxIndent: 更深子项, 跳过继续往上找
  }
  return null;
}

function toggleListIndent(view, dir) {
  const { from, to } = view.state.selection.main;
  const doc = view.state.doc;
  const fromLine = doc.lineAt(from).number;
  const rawToLine = doc.lineAt(to).number;
  const toLine = (to > from && to === doc.line(rawToLine).from) ? rawToLine - 1 : rawToLine;

  const changes = [];
  const batchMarkers = {}; // newIndent -> 上次赋的 marker (多行批量 outdent 续号)
  let hasListLine = false;
  for (let n = fromLine; n <= toLine; n++) {
    const line = doc.line(n);
    const m = line.text.match(LIST_LINE_RE);
    if (!m) continue;
    hasListLine = true;
    const indent = m[1].length;
    // 吸附到 0/4/8 网格: 当前层级 = floor(indent/4), Tab/Shift-Tab 在网格上增减
    // 这样 2 空格旧内容按 Tab 会 snap 到 4 (marked 嵌套所需)
    const baseLevel = Math.floor(indent / 4);
    if (dir > 0 && baseLevel >= 2) continue; // 已三级 (8 空格), 不再加
    if (dir < 0 && baseLevel <= 0) continue;  // 已一级 (0 空格), 不再减
    const newLevel = dir > 0 ? baseLevel + 1 : baseLevel - 1;
    const newIndent = newLevel * 4;
    const isOrdered = /^\d+\.$/.test(m[2]);
    let newMarker;
    if (dir > 0) {
      // 缩进: 进入子列表, 有序 marker 重置为 1 (子列表独立编号, CSS 渲染为 a./i.)
      newMarker = isOrdered ? '1.' : m[2];
    } else {
      // 减缩进: 扫上方延续父列表 marker
      let prev = batchMarkers[newIndent] || findPrevListMarkerAt(doc, n, newIndent);
      if (prev) {
        newMarker = /^\d+\.$/.test(prev) ? (parseInt(prev, 10) + 1) + '.' : prev;
      } else {
        newMarker = isOrdered ? '1.' : m[2];
      }
      batchMarkers[newIndent] = newMarker;
    }
    const newPrefix = ' '.repeat(newIndent) + newMarker + ' ';
    changes.push({ from: line.from, to: line.from + m[0].length, insert: newPrefix });
  }
  if (!hasListLine) return false; // 非列表行: 让默认 indentWithTab 处理
  if (changes.length > 0) view.dispatch({ changes, userEvent: 'input' });
  return true; // 含列表行即拦截, 全在 cap 时 no-op 阻止默认
}

// Enter 在表格行 → 在下方插入同列数空行; 非表格行 return false 让默认换行
function insertTableRow(view) {
  const { from } = view.state.selection.main;
  const doc = view.state.doc;
  const line = doc.lineAt(from);
  if (!TABLE_ROW_RE.test(line.text)) return false;
  const parts = line.text.split('|');
  // parts[0] 与 parts[last] 为首尾 pipe 两侧空串
  const columns = parts.length - 2;
  if (columns < 1) return false;
  const newRow = Array(columns + 1).fill('|').join(' ');
  view.dispatch({
    changes: { from: line.to, insert: '\n' + newRow },
    selection: { anchor: line.to + 1 },
    userEvent: 'input',
  });
  return true;
}

// Enter 在列表行 → 续写下一项 (编号+1 或同 marker, 保缩进)
// 空列表项 Enter → 退出列表 (删 marker 行)
function continueListItem(view) {
  const { from } = view.state.selection.main;
  const doc = view.state.doc;
  const line = doc.lineAt(from);
  const m = line.text.match(LIST_LINE_RE);
  if (!m) return false;
  const indent = m[1].length;
  const marker = m[2];
  const contentAfterMarker = line.text.slice(m[0].length);
  // 空内容 (仅 marker 无正文) → 退出列表: 清空 marker, 留空行
  if (contentAfterMarker.trim() === '') {
    view.dispatch({
      changes: { from: line.from + m[1].length, to: line.to, insert: '' },
      selection: { anchor: line.from + m[1].length },
      userEvent: 'input',
    });
    return true;
  }
  // 续号: 有序 marker +1, 无序保持
  const newMarker = /^\d+\.$/.test(marker) ? (parseInt(marker, 10) + 1) + '.' : marker;
  const newPrefix = ' '.repeat(indent) + newMarker + ' ';
  const { to } = view.state.selection.main;
  view.dispatch({
    changes: { from, to, insert: '\n' + newPrefix },
    selection: { anchor: from + 1 + newPrefix.length },
    userEvent: 'input',
  });
  return true;
}

// 扫全文有序列表, 栈处理嵌套, 重排为 1,2,3...
// 触发: doc 变更时自动修正编号缺口/重复
function renumberAllLists(view) {
  const doc = view.state.doc;
  const changes = [];
  const stack = []; // [{indent, count}]
  let blankRun = 0; // 连续空行数
  for (let i = 1; i <= doc.lines; i++) {
    const line = doc.line(i);
    const m = line.text.match(LIST_LINE_RE);
    if (!m) {
      if (line.text.trim() === '') {
        // 空行: 容忍列表内软换行, 但 CommonMark 连续 >=2 空行终止列表
        if (++blankRun >= 2) stack.length = 0;
      } else {
        // 段落/标题/代码等非列表内容: 同级及以上 indent 处中断有序列表
        blankRun = 0;
        const leadWs = line.text.match(/^\s*/)[0].length;
        while (stack.length && stack[stack.length-1].indent >= leadWs) stack.pop();
      }
      continue;
    }
    blankRun = 0;
    if (!/^\d+\.$/.test(m[2])) {
      // 无序/其他 marker 行: 同级及以上处中断有序列表 (不同 marker = 新列表)
      const uIndent = m[1].length;
      while (stack.length && stack[stack.length-1].indent >= uIndent) stack.pop();
      continue;
    }
    const indent = m[1].length;
    while (stack.length && stack[stack.length-1].indent > indent) stack.pop();
    if (stack.length && stack[stack.length-1].indent === indent) {
      stack[stack.length-1].count++;
    } else {
      stack.push({ indent, count: 1 });
    }
    const expected = stack[stack.length-1].count + '.';
    if (m[2] !== expected) {
      changes.push({ from: line.from, to: line.from + m[0].length, insert: m[1] + expected + ' ' });
    }
  }
  if (changes.length > 0) {
    view.dispatch({ changes, userEvent: 'input.renumber' });
  }
}

// 必须放在主 keymap 之前, 才能先于 indentWithTab / defaultKeymap 拦截
const listTableBindings = [
  { key: 'Tab', run: (v) => toggleListIndent(v, 1) },
  { key: 'Shift-Tab', run: (v) => toggleListIndent(v, -1) },
  { key: 'Enter', run: (v) => {
    if (insertTableRow(v)) return true;       // 表格行: 插空行
    return continueListItem(v);                // 列表行: 续号; 否则 fallthrough 默认换行
  } },
];

function enterEditMode() {
  if (!state.currentFile) return;
  // 保存当前滚动位置，编辑切换后恢复
  const currentScroll = els.contentBody ? els.contentBody.scrollTop : 0;
  els.viewer.hidden = true;
  els.editorHost.hidden = false;
  els.editToggle.textContent = '预览';
  // 恢复滚动位置（编辑器内容变化不会改变位置）
  requestAnimationFrame(() => {
    if (els.contentBody) els.contentBody.scrollTop = currentScroll;
  });

  if (state.editor) {
    state.editor.dispatch({
      changes: { from: 0, to: state.editor.state.doc.length,
                 insert: state.currentFile.content },
    });
    state.editor.dispatch({
      effects: state.editorLangCompartment.reconfigure(
        languageForFile(state.currentFile.extension)
      ),
    });
    state.editor.focus();
    return;
  }

  try {
    const updateListener = EditorView.updateListener.of((vu) => {
      if (vu.docChanged) {
        state.isDirty = true;
        setSaveStatus('编辑中...', 'dirty');
        const tab = getTab(state.currentFile.path);
        if (tab) { tab.dirty = true; renderTabs(); }
        scheduleAutosave();
        // 删行后自动重编号 (renumber 自身的 userEvent 跳过, 防递归)
        const isRenumber = vu.transactions.some(t => t.isUserEvent('input.renumber'));
        if (!isRenumber) {
          try { renumberAllLists(vu.view); } catch (e) { console.error('[renumber] err', e); }
        }
      }
    });

    const saveCmd = keymap.of([{
      key: 'Mod-s',
      preventDefault: true,
      run: () => { flushSave(); return true; },
    }]);

    const ext = state.currentFile.extension;
    const langSupport = languageForFile(ext);
    const docContent = state.currentFile.content || '';

    // 诊断日志 — 打开 DevTools Console 可见
    console.log('[reader] enterEditMode:', {
      path: state.currentFile.path,
      ext: ext,
      contentLen: docContent.length,
      hostW: els.editorHost.offsetWidth,
      hostH: els.editorHost.offsetHeight,
      hostHidden: els.editorHost.hidden,
    });

    const startState = EditorState.create({
      doc: docContent,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        history(),
        foldGutter(),
        drawSelection(),
        indentOnInput(),
        bracketMatching(),
        highlightActiveLine(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        state.editorLangCompartment.of(langSupport),
        keymap.of(listTableBindings),
        keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab, ...mdFormatBindings]),
        saveCmd,
        search(),
        EditorView.lineWrapping,
        state.editorThemeCompartment.of(editorThemeForCurrent()),
        updateListener,
      ],
    });

    state.editor = new EditorView({
      state: startState,
      parent: els.editorHost,
    });
    console.log('[reader] CM6 editor created, doc length:', state.editor.state.doc.length);
  } catch (e) {
    // CodeMirror 6 加载失败,降级为 textarea
    console.error('CM6 init failed, fallback to textarea:', e);
    const ta = document.createElement('textarea');
    ta.value = state.currentFile.content || '';
    ta.style.cssText = 'width:100%;min-height:60vh;font-family:var(--font-mono);font-size:var(--reader-font-size);background:var(--bg);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:12px;resize:vertical;box-sizing:border-box;';
    ta.addEventListener('input', () => {
      state.isDirty = true;
      setSaveStatus('编辑中...', 'dirty');
      state.currentFile.content = ta.value;
      scheduleAutosave();
    });
    els.editorHost.innerHTML = '';
    els.editorHost.appendChild(ta);
    // 标记为 textarea 模式,exitEditMode 时清理
    state._textareaFallback = ta;
    ta.focus();
  }
}

function exitEditMode() {
  // Vditor (IR) 清理: 先同步当前内容到 currentFile (供 renderMarkdown 立即读最新值, 避免切换只读显示旧内容), 再落盘 + 销毁
  if (state.vditor) {
    if (state.isDirty && state.currentFile) {
      try { state.currentFile.content = recoverMermaidBlocks(state.vditor.getValue(), state.mermaidSnapshot, state.lastSavedContent); } catch (e) {}
    }
    if (state.isDirty) flushSave(true);
    destroyVditor();
  }
  if ((state.editor || state._textareaFallback) && state.isDirty) {
    flushSave(true);
  }
  // 清理 textarea 降级模式
  if (state._textareaFallback) {
    state._textareaFallback = null;
    els.editorHost.innerHTML = '';
  }
  els.editorHost.hidden = true;
  els.editToggle.textContent = '编辑';
}

function scheduleAutosave() {
  if (state.saveTimer) clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(flushSave, 1000);
}

// 防御 Vditor IR 对 mermaid 代码块的 getValue 数据丢失:
// 真实 WebReader 流程下 getValue 偶发返空 ```mermaid``` fence (最小复现未抓到确切路径,
// 非 Vditor 内置 mermaidRender — 单测 Vditor IR 保留码). 防御策略:
// load-time 抓 mermaid 快照 (state.mermaidSnapshot, 不漂移) + 兜底 lastSavedContent,
// 新内容空块 → 从快照回填.
function captureMermaidBlocks(md) {
  const map = new Map();
  if (!md) return map;
  const F = '```';
  const re = new RegExp('<!-- doc-mermaid: images/([^>]+\\.png) -->\\s*' + F + 'mermaid\\n([\\s\\S]*?)\\n' + F, 'g');
  let m;
  while ((m = re.exec(md)) !== null) {
    if (m[2] && m[2].trim()) map.set(m[1], m[2]);
  }
  return map;
}

function recoverMermaidBlocks(newContent, snapshotMap, fallbackContent) {
  if (!newContent) return newContent;
  const F = '```';
  const src = new Map(snapshotMap || []);
  if (fallbackContent) {
    const re = new RegExp('<!-- doc-mermaid: images/([^>]+\\.png) -->\\s*' + F + 'mermaid\\n([\\s\\S]*?)\\n' + F, 'g');
    let m;
    while ((m = re.exec(fallbackContent)) !== null) {
      if (m[2] && m[2].trim() && !src.has(m[1])) src.set(m[1], m[2]);
    }
  }
  if (src.size === 0) return newContent;
  const blockRe = new RegExp('(<!-- doc-mermaid: images/([^>]+\\.png) -->\\s*' + F + 'mermaid)([\\s\\S]*?)(' + F + ')', 'g');
  let recovered = 0;
  const out = newContent.replace(blockRe, (full, head, name, body, tail) => {
    if (body.trim()) return full;            // 非空保留 (用户手编过)
    const prev = src.get(name);
    if (!prev || !prev.trim()) return full;
    recovered++;
    return head + '\n' + prev + '\n' + tail;
  });
  if (recovered > 0) {
    console.warn('[mermaid-guard] getValue 丢码, 从快照回填 ' + recovered + ' 块');
    setSaveStatus('mermaid 防丢回填 ' + recovered + ' 块', 'saving');
  }
  return out;
}

async function flushSave(silent = false) {
  if (state.saveTimer) { clearTimeout(state.saveTimer); state.saveTimer = null; }
  if (!state.currentFile) return;
  // 读取编辑器内容: Vditor (IR) / CM6 / textarea 降级
  let content;
  if (state.vditor) {
    content = recoverMermaidBlocks(state.vditor.getValue(), state.mermaidSnapshot, state.lastSavedContent);
  } else if (state.editor) {
    content = state.editor.state.doc.toString();
  } else if (state._textareaFallback) {
    content = state._textareaFallback.value;
  } else {
    return;
  }
  if (content === state.lastSavedContent) {
    state.isDirty = false;
    if (!silent) setSaveStatus('已保存', 'saved');
    return;
  }
  setSaveStatus('保存中...', 'saving');
  try {
    await apiSave(state.currentFile.path, content, state.currentFile.encoding);
    state.lastSavedContent = content;
    state.isDirty = false;
    setSaveStatus('已保存 · ' + new Date().toLocaleTimeString(), 'saved');
    state.currentFile.content = content;
    const tab = getTab(state.currentFile.path);
    if (tab) { tab.dirty = false; renderTabs(); }
    refreshArchiveBtn();
    scheduleHistoryCommit();   // 真实落盘后, 安排 60s 空闲历史快照 (兜底 autosave 只落盘)
  } catch (e) {
    setSaveStatus('保存失败: ' + e.message, 'error');
  }
}

// ============== 自动历史快照 (git 备份) ==============
// autosave 每 1s 落盘 (安全) 但不入 git; 此处 60s 空闲后 git add -A 提交一次,
// 把编辑会话聚合成单个历史点, 历史面板可还原。页面隐藏/关闭用 sendBeacon 兜底。
const HISTORY_COMMIT_DELAY = 60000;
let __historyTimer = null;
function scheduleHistoryCommit() {
  if (__historyTimer) clearTimeout(__historyTimer);
  __historyTimer = setTimeout(async () => {
    __historyTimer = null;
    try {
      const r = await apiSnapshot();
      if (r.committed) {
        const n = (r.files || []).length;
        setSaveStatus(`已历史快照 (${n} 文件)`, 'saved');
        refreshArchiveBtn();
        setTimeout(() => { if (!state.isDirty) setSaveStatus('已保存', 'saved'); }, 2500);
      }
    } catch (e) { console.warn('[snapshot] auto-commit failed:', e); }
  }, HISTORY_COMMIT_DELAY);
}
// 页面隐藏/关闭: sendBeacon 兜底 (fetch 可能被浏览器中止, beacon 保证送达)
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden' && __historyTimer) {
    if (__historyTimer) { clearTimeout(__historyTimer); __historyTimer = null; }
    try {
      navigator.sendBeacon('/api/reader/snapshot', new Blob([JSON.stringify({ message: '' })], { type: 'application/json' }));
    } catch (e) {}
  }
});

function setSaveStatus(text, cls) {
  els.saveStatus.textContent = text;
  els.saveStatus.className = cls || 'muted';
}

// ============== 字号 ==============
els.btnIncFont.addEventListener('click', () => {
  if (state.fontSize < 24) { state.fontSize++; applyFontSize(); }
});
els.btnDecFont.addEventListener('click', () => {
  if (state.fontSize > 10) { state.fontSize--; applyFontSize(); }
});

els.btnArchive.addEventListener('click', async () => {
  if (els.btnArchive.disabled) return;
  const p = state.currentFile && state.currentFile.path;
  if (!p) return;
  const msg = prompt('归档提交信息 (留空用默认):', '');
  if (msg === null) return; // 用户取消
  els.btnArchive.disabled = true;
  setSaveStatus('归档中...', 'saving');
  try {
    const r = await apiCommit(p, msg.trim());
    if (r.committed) {
      setSaveStatus('已归档 · ' + (r.message || ''), 'saved');
    } else {
      setSaveStatus('无改动可归档', 'saved');
    }
  } catch (e) {
    setSaveStatus('归档失败: ' + e.message, 'error');
  }
  refreshArchiveBtn();
});

// ============== 侧栏折叠 + 分隔条 ==============
// ============== 手机端目录互斥逻辑 ==============
function isMobile() {
  return window.matchMedia('(max-width: 768px)').matches;
}

// 手机端: 关闭 outline 浮层
function closeMobileOutline() {
  els.outlinePanel.classList.remove('mobile-outline-open');
}

// 手机端: 打开 outline 浮层 (层级高于文档)
function openMobileOutline() {
  if (!state.currentFile) return;
  // 关闭 sidebar (互斥)
  state.sidebarCollapsed = true;
  els.layout.classList.add('collapsed');
  savePref('reader.sidebarCollapsed', 1);
  els.outlinePanel.classList.add('mobile-outline-open');
}

els.btnToggleSidebar.addEventListener('click', () => {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  els.layout.classList.toggle('collapsed', state.sidebarCollapsed);
  savePref('reader.sidebarCollapsed', state.sidebarCollapsed ? 1 : 0);
  // 手机端: 展开 sidebar 时关闭 outline (互斥)
  if (isMobile() && !state.sidebarCollapsed) {
    closeMobileOutline();
  }
});

// 手机端: 点击内容区左半区 → 显示文档目录; 右半区 → 隐藏
els.contentBody.addEventListener('click', (e) => {
  if (!isMobile()) return;
  if (!state.currentFile) return;
  const rect = els.contentBody.getBoundingClientRect();
  const isLeftHalf = (e.clientX - rect.left) < rect.width / 2;
  if (isLeftHalf) {
    // 已打开则关闭, 否则打开 (toggle)
    if (els.outlinePanel.classList.contains('mobile-outline-open')) {
      closeMobileOutline();
    } else {
      openMobileOutline();
    }
  } else {
    // 右半区点击: 关闭目录
    closeMobileOutline();
  }
});

els.splitter.addEventListener('mousedown', (e) => {
  e.preventDefault();
  const startX = e.clientX;
  const startW = state.sidebarWidth;
  const onMove = (ev) => {
    const dx = ev.clientX - startX;
    let w = startW + dx;
    if (w < 180) w = 180;
    if (w > 600) w = 600;
    state.sidebarWidth = w;
    applySidebarWidth();
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
});

// ============== 文件树过滤 + 刷新 ==============
els.treeFilter.addEventListener('input', applyTreeFilter);
els.btnRefreshTree.addEventListener('click', loadTree);

// ============== 编辑/预览切换 ==============
// ============== 切换编辑/只读: 保持文档位置 ==============
// 捕获当前视口顶部最近的标题文本 (编辑/只读两端都有同样标题, 可对位滚动)
function captureViewportHeading() {
  const container = state.vditor ? els.vditorHost : (els.viewer.hidden ? null : els.viewer);
  if (!container) return '';
  const headings = container.querySelectorAll('h1,h2,h3,h4,h5,h6');
  if (!headings.length) return '';
  const scrollerTop = els.contentBody.getBoundingClientRect().top;
  const clean = h => (h.textContent || '').replace(/^\s*[▼▶]\s*/, '').replace(/^#+\s*/, '').trim();
  // 优先: 视口顶部上方最近的标题 (正在阅读的区段)
  let above = null, aboveDist = -Infinity;
  let any = null, anyDist = Infinity;
  headings.forEach(h => {
    const dist = h.getBoundingClientRect().top - scrollerTop;
    if (dist <= 60 && dist > aboveDist) { aboveDist = dist; above = h; }
    if (Math.abs(dist) < anyDist) { anyDist = Math.abs(dist); any = h; }
  });
  const anchor = clean(above || any || headings[0]);
  console.log('[anchor] capture:', JSON.stringify(anchor));
  return anchor;
}
function scrollToHeadingText(text) {
  if (!text) return false;
  const container = state.vditor ? els.vditorHost : els.viewer;
  const clean = h => (h.textContent || '').replace(/^\s*[▼▶]\s*/, '').replace(/^#+\s*/, '').trim();
  for (const h of container.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
    if (clean(h) === text) {
      const scroller = els.contentBody;
      const rect = h.getBoundingClientRect();
      const sr = scroller.getBoundingClientRect();
      // 直接跳转 (scrollTop 赋值, 无 smooth 动画)
      scroller.scrollTop = rect.top - sr.top + scroller.scrollTop - 8;
      console.log('[anchor] restore:', JSON.stringify(text), 'scrollTop=', scroller.scrollTop);
      return true;
    }
  }
  console.log('[anchor] NOT FOUND:', JSON.stringify(text));
  return false;
}

els.editToggle.addEventListener('click', () => {
  if (!state.currentFile) return;
  const ext = state.currentFile.extension;
  if (isMarkdown(ext)) {
    // .md: Vditor(IR 编辑) <-> renderMarkdown(只读); 切全局偏好 (对所有 .md 生效, 刷新保留)
    // 切换前以左侧目录高亮标题为锚 (scroll-spy 维护的 state._currentHeading), 切换后跳到同一标题
    const anchor = state._currentHeading || captureViewportHeading();
    const newMode = !getMdEditMode();
    setMdEditMode(newMode);
    if (newMode) {
      state._scrollAnchor = anchor;  // Vditor after 回调里恢复
      // 含 mermaid 的 .md 走 CM6 (enterEditMode), 避免 Vditor IR 丢码/崩图; 其余 .md 仍 Vditor
      const hasMermaid = /```mermaid\b/.test(state.currentFile.content || '');
      if (hasMermaid) {
        enterEditMode();
      } else {
        renderMarkdownVditor(state.currentFile);
      }
    } else {
      if (state.isDirty) flushSave();
      renderMarkdown(state.currentFile);
      setMdToggleState(false);
      state._scrollAnchor = anchor;  // 只读同步渲染, 下一帧恢复
      requestAnimationFrame(() => {
        if (state._scrollAnchor) { scrollToHeadingText(state._scrollAnchor); state._scrollAnchor = ''; }
        highlightCurrentOutline();
      });
    }
    return;
  }
  // 非 md: CodeMirror 编辑/预览 (原逻辑)
  if (els.editorHost.hidden) {
    enterEditMode();
    const tab = getTab(state.currentFile.path);
    if (tab) { tab.editMode = true; persistSession(); }
  } else {
    if (state.isDirty) flushSave();
    renderCode(state.currentFile);
    const tab = getTab(state.currentFile.path);
    if (tab) { tab.editMode = false; persistSession(); }
  }
});

// ============== 全局搜索 ==============
function openSearchModal() {
  els.searchModal.hidden = false;
  els.searchInput.value = '';
  els.searchExt.value = '';
  els.searchResults.innerHTML = '';
  els.searchInput.focus();
  state._searchSelected = 0;
}

function closeSearchModal() {
  els.searchModal.hidden = true;
  state.editor?.focus();
}

let searchDebounce = null;
els.searchInput.addEventListener('input', () => {
  if (searchDebounce) clearTimeout(searchDebounce);
  searchDebounce = setTimeout(runSearch, 200);
});
els.searchExt.addEventListener('change', runSearch);

async function runSearch() {
  const q = els.searchInput.value.trim();
  els.searchResults.innerHTML = '';
  if (!q) return;
  const ext = els.searchExt.value || '';
  const results = await apiSearch(q, ext);
  state._searchResults = results;
  state._searchSelected = 0;
  if (results.length === 0) {
    els.searchResults.innerHTML = '<li class="muted" style="padding:8px 12px">无结果</li>';
    return;
  }
  results.forEach((r, i) => {
    const li = document.createElement('li');
    if (i === 0) li.classList.add('active');
    li.innerHTML = '<span class="search-result-path">' + escHtml(r.path) + ':' + r.line + '</span>' +
                   '<span class="search-result-line">' + escHtml(r.text.slice(0, 200)) + '</span>';
    li.addEventListener('click', () => {
      closeSearchModal();
      openFile(r.path);
    });
    els.searchResults.appendChild(li);
  });
}

els.searchInput.addEventListener('keydown', (e) => {
  const items = els.searchResults.querySelectorAll('li');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (state._searchSelected < items.length - 1) state._searchSelected++;
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (state._searchSelected > 0) state._searchSelected--;
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const r = state._searchResults && state._searchResults[state._searchSelected];
    if (r) { closeSearchModal(); openFile(r.path); }
    return;
  } else if (e.key === 'Escape') {
    closeSearchModal();
    return;
  } else return;
  items.forEach((it, i) => it.classList.toggle('active', i === state._searchSelected));
  if (items[state._searchSelected]) items[state._searchSelected].scrollIntoView({ block: 'nearest' });
});

// ============== 快速打开 (cmd+P) ==============
function openQuickOpen() {
  els.quickopenModal.hidden = false;
  els.quickopenInput.value = '';
  els.quickopenResults.innerHTML = '';
  els.quickopenInput.focus();
  state._qoSelected = 0;
  // 首次打开时懒构建 cmd+P 索引，避免 WebReader 启动/刷新时全仓扫描拖慢加载
  if (!state.allFilesLoaded && !state._allFilesLoading) {
    state._allFilesLoading = true;
    els.quickopenResults.innerHTML = '<li class="muted" style="padding:8px 12px">索引加载中…</li>';
    loadAllFilesIndex().finally(() => {
      state._allFilesLoading = false;
      runQuickOpen();
    });
    return;
  }
  runQuickOpen();
}

function closeQuickOpen() {
  els.quickopenModal.hidden = true;
  state.editor?.focus();
}

function fuzzyScore(query, str) {
  if (!query) return 1;
  const q = query.toLowerCase();
  const s = str.toLowerCase();
  if (s === q) return 1000;
  if (s.startsWith(q)) return 500 - s.length;
  if (s.includes(q)) return 200 - s.indexOf(q);
  // 顺序字符匹配
  let qi = 0, score = 0;
  for (let i = 0; i < s.length && qi < q.length; i++) {
    if (s[i] === q[qi]) { qi++; score++; }
  }
  return qi === q.length ? score : -1;
}

function runQuickOpen() {
  const q = els.quickopenInput.value.trim();
  const items = state.allFiles || [];
  let scored = items
    .map(f => ({ f, s: fuzzyScore(q, f.path) }))
    .filter(x => x.s >= 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, 50);
  state._qoResults = scored.map(x => x.f);
  state._qoSelected = 0;
  els.quickopenResults.innerHTML = '';
  if (scored.length === 0) {
    els.quickopenResults.innerHTML = '<li class="muted" style="padding:8px 12px">无匹配</li>';
    return;
  }
  scored.forEach((x, i) => {
    const li = document.createElement('li');
    if (i === 0) li.classList.add('active');
    li.innerHTML = '<span class="search-result-path">' + escHtml(x.f.path) + '</span>';
    li.addEventListener('click', () => { closeQuickOpen(); openFile(x.f.path); });
    els.quickopenResults.appendChild(li);
  });
}

els.quickopenInput.addEventListener('input', runQuickOpen);
els.quickopenInput.addEventListener('keydown', (e) => {
  const items = els.quickopenResults.querySelectorAll('li');
  if (e.key === 'ArrowDown') { e.preventDefault(); if (state._qoSelected < items.length - 1) state._qoSelected++; }
  else if (e.key === 'ArrowUp') { e.preventDefault(); if (state._qoSelected > 0) state._qoSelected--; }
  else if (e.key === 'Enter') { e.preventDefault(); const f = state._qoResults && state._qoResults[state._qoSelected]; if (f) { closeQuickOpen(); openFile(f.path); } return; }
  else if (e.key === 'Escape') { closeQuickOpen(); return; }
  else return;
  items.forEach((it, i) => it.classList.toggle('active', i === state._qoSelected));
  if (items[state._qoSelected]) items[state._qoSelected].scrollIntoView({ block: 'nearest' });
});

// 关闭弹层: 点击背景
els.searchModal.addEventListener('click', (e) => { if (e.target === els.searchModal) closeSearchModal(); });
els.quickopenModal.addEventListener('click', (e) => { if (e.target === els.quickopenModal) closeQuickOpen(); });

// ============== 页内查找（只读渲染模式，web/客户端一致） ==============
let findState = { q: '', matches: [], index: -1 };

function openFindBar() {
  els.findBar.hidden = false;
  els.findInput.focus();
  els.findInput.select();
  doFind();
}

function closeFindBar() {
  els.findBar.hidden = true;
  els.findInput.value = '';
  clearFindMarks();
  findState = { q: '', matches: [], index: -1 };
}

// 高亮 #viewer 只读渲染文本中的匹配（用自定义标签包住，不破坏原 DOM 事件）
function doFind() {
  const q = els.findInput.value;
  clearFindMarks();
  findState = { q, matches: [], index: -1 };
  if (!q || els.viewer.hidden) { updateFindCount(); return; }
  const walker = document.createTreeWalker(els.viewer, NodeFilter.SHOW_TEXT);
  const texts = [];
  let node;
  while ((node = walker.nextNode())) {
    if (!node.nodeValue || !node.nodeValue.includes(q)) continue;
    texts.push(node);
  }
  for (const t of texts) {
    const frag = document.createDocumentFragment();
    const val = t.nodeValue;
    let rest = val;
    let pos = 0;
    while (true) {
      const idx = rest.indexOf(q, pos);
      if (idx < 0) break;
      if (idx > pos) frag.appendChild(document.createTextNode(rest.slice(pos, idx)));
      const mark = document.createElement('cf-find-mark');
      mark.textContent = q;
      frag.appendChild(mark);
      findState.matches.push(mark);
      pos = idx + q.length;
    }
    if (pos < rest.length) frag.appendChild(document.createTextNode(rest.slice(pos)));
    t.parentNode.replaceChild(frag, t);
  }
  if (findState.matches.length) {
    findState.index = 0;
    markCurrent(0);
  }
  updateFindCount();
}

function clearFindMarks() {
  const marks = els.viewer.querySelectorAll('cf-find-mark');
  marks.forEach((m) => {
    const txt = document.createTextNode(m.textContent);
    m.parentNode.replaceChild(txt, m);
  });
}

function markCurrent(i) {
  els.viewer.querySelectorAll('cf-find-mark.current').forEach((m) => m.classList.remove('current'));
  const m = findState.matches[i];
  if (!m) return;
  m.classList.add('current');
  m.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function findNext(back) {
  if (!findState.matches.length) return;
  const n = findState.matches.length;
  findState.index = back
    ? (findState.index - 1 + n) % n
    : (findState.index + 1) % n;
  markCurrent(findState.index);
}

function updateFindCount() {
  els.findCount.textContent = findState.matches.length ? `${findState.index + 1}/${findState.matches.length}` : '0/0';
}

els.findInput.addEventListener('input', doFind);
els.findNext.addEventListener('click', () => findNext(false));
els.findPrev.addEventListener('click', () => findNext(true));
els.findInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); findNext(e.shiftKey); }
  if (e.key === 'Escape') { e.preventDefault(); closeFindBar(); }
});

// ============== 工具 ==============
function escHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

// ============== 快捷键 (mac/win 通吃) ==============
document.addEventListener('keydown', (e) => {
  // Escape 不需要 Cmd/Ctrl 修饰键, 必须在 mod 检查之前处理
  if (e.key === 'Escape') {
    if (!els.findBar.hidden) { closeFindBar(); e.preventDefault(); return; }
    if (!els.searchModal.hidden) { closeSearchModal(); e.preventDefault(); return; }
    if (!els.quickopenModal.hidden) { closeQuickOpen(); e.preventDefault(); return; }
    return;
  }

  // 编辑器聚焦时 Mod-b 让编辑器的粗体处理 (CM mdFormatBindings / Vditor keymap), 不触发侧栏折叠
  if ((e.key === 'b' || e.key === 'B') && (
    (state.editor && state.editor.hasFocus) ||
    (state.vditor && els.vditorHost.contains(document.activeElement))
  )) return;

  const mod = e.metaKey || e.ctrlKey;
  if (!mod) return;
  const k = e.key.toLowerCase();

  // cmd/ctrl + C/X/V → 文件复制/剪切/粘贴 (鼠标悬停侧栏 + 非编辑器/input)
  const ae = document.activeElement;
  const inEditable = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA'
    || (state.editor && state.editor.hasFocus));
  if (!e.shiftKey && !inEditable && state.selectedPath && els.sidebar.matches(':hover')) {
    if (k === 'c') {
      e.preventDefault();
      state.clipboard = { path: state.selectedPath, type: state.selectedType, cut: false };
      setSaveStatus('已复制', 'ok');
      return;
    }
    if (k === 'x') {
      e.preventDefault();
      state.clipboard = { path: state.selectedPath, type: state.selectedType, cut: true };
      setSaveStatus('已剪切', 'ok');
      return;
    }
    if (k === 'v') {
      e.preventDefault();
      const sp = state.selectedPath;
      const st = state.selectedType;
      const targetDir = !sp ? '' : (st === 'folder' ? sp : (sp.includes('/') ? sp.slice(0, sp.lastIndexOf('/')) : ''));
      pasteInto(targetDir);
      return;
    }
  }

  // cmd/ctrl + shift + F → 全局搜索 (cmd/ctrl + F 不拦截, 让浏览器默认行为生效)
  if (k === 'f' && e.shiftKey) {
    e.preventDefault();
    openSearchModal();
    return;
  }

  // cmd/ctrl + F → 页面内查找：编辑器打开时用 CM6 搜索面板；否则用只读渲染页内查找条。
  // 依赖浏览器原生 find 在 Tauri webview iframe 内不可靠（客户端版本失效），统一走显式实现。
  if (k === 'f' && !e.shiftKey) {
    if (state.editor && !inEditable) {
      e.preventDefault();
      state.editor.dispatch({ effects: openSearchPanel.of(null) });
    } else {
      e.preventDefault();
      openFindBar();
    }
    return;
  }

  // cmd/ctrl + P → 快速打开
  if (k === 'p') {
    e.preventDefault();
    openQuickOpen();
    return;
  }

  // cmd/ctrl + B → 折叠侧栏
  if (k === 'b') {
    e.preventDefault();
    els.btnToggleSidebar.click();
    return;
  }

  // cmd/ctrl + S → 强制保存
  if (k === 's') {
    e.preventDefault();
    flushSave();
    return;
  }
});

// ============== 启动 ==============
loadPrefs();
// 展示缩放: 恢复上次 zoom (独立使用与嵌入共用 reader.zoom)
applyZoom(parseFloat(localStorage.getItem('reader.zoom')) || 1);
// 显式主题: 恢复上次设置 (父窗口 Castflow 设置后记住, 重启跟随)
const savedTheme = localStorage.getItem('reader.theme');
if (savedTheme === 'light' || savedTheme === 'dark') applyTheme(savedTheme);
// 初始禁用按钮
els.btnHistory.disabled = true;
els.btnShare.disabled = true;
els.btnDownload.disabled = true;
els.btnArchive.disabled = true;
els.btnComments.disabled = true;

loadTree().catch((e) => {
  setSaveStatus('加载文件树失败: ' + e.message, 'error');
  console.error('[reader] loadTree failed:', e);
}).then(() => {
  console.log('[reader] loadTree done, restoring session...');
  // 优先恢复 URL 中的分享 session, 否则恢复本地 session
  const shared = restoreSharedSession();
  const local = !shared && restoreSession();
  if (shared || local) {
    renderTabs();
    console.log('[reader] session restored, tabs:', state.tabs.length, 'active:', state.activeTabPath);
    if (state.activeTabPath) {
      openFile(state.activeTabPath).catch(e => {
        console.error('[reader] openFile on restore failed:', e);
        setSaveStatus('恢复 tab 失败: ' + e.message, 'error');
      });
    }
  } else {
    console.log('[reader] no session to restore');
  }
  // 嵌入场景: 启动完成 → 上报当前状态 (父窗口持久化, 供下次启动还原)
  notifyParent({ type: 'cf-state', state: buildReaderState() });
});

// 滚动时: 保存位置 + 高亮当前目录项
let scrollSaveTimer = null;
els.contentBody.addEventListener('scroll', () => {
  if (scrollSaveTimer) clearTimeout(scrollSaveTimer);
  scrollSaveTimer = setTimeout(() => {
    saveCurrentTabState();
    persistSession();
    highlightCurrentOutline();
  }, 100);
});

// 根据滚动位置, 找当前可见标题 → 高亮左侧目录对应项 + 记录当前标题 (供切换编辑/只读时同步)
// 编辑态查 vditorHost, 只读态查 viewer; 目录项按标题文本 (去 ▼/## 后) 对位
function highlightCurrentOutline() {
  const container = state.vditor ? els.vditorHost : (els.viewer.hidden ? null : els.viewer);
  if (!container) return;
  const headings = [...container.querySelectorAll('h1,h2,h3,h4,h5,h6')];
  if (!headings.length) return;
  const scrollerTop = els.contentBody.getBoundingClientRect().top;
  const clean = h => (h.textContent || '').replace(/^\s*[▼▶]\s*/, '').replace(/^#+\s*/, '').trim();
  // 当前区段 = 最后一个已滚过视口顶部上方 (top <= 60) 的标题
  let current = headings[0];
  for (const h of headings) {
    if (h.getBoundingClientRect().top - scrollerTop <= 60) current = h;
  }
  const currentText = clean(current);
  state._currentHeading = currentText;
  // 高亮目录中匹配项 (按文本对位, 比 index 稳)
  let foundItem = null;
  const items = els.outlineBody.querySelectorAll('.outline-item');
  els.outlineBody.querySelectorAll('.outline-item').forEach(it => {
    const itText = (it.textContent || '').replace(/^\s*[▼▶]\s*/, '').trim();
    if (itText === currentText) { it.classList.add('active'); foundItem = it; }
    else it.classList.remove('active');
  });
  console.log('[outline] highlight:', JSON.stringify(currentText), 'items=', items.length, 'matched=', !!foundItem);
  if (!foundItem && current) console.log('[outline] unmatched heading HTML:', current.outerHTML.slice(0, 300));
  // 目录项滚入可见 (高亮项不在视口时)
  if (foundItem) {
    const pRect = els.outlineBody.getBoundingClientRect();
    const itRect = foundItem.getBoundingClientRect();
    if (itRect.top < pRect.top || itRect.bottom > pRect.bottom) {
      foundItem.scrollIntoView({ block: 'nearest' });
    }
  }
}

// 离开页面前保存会话 + flush 未保存改动
window.addEventListener('beforeunload', () => {
  saveCurrentTabState();
  persistSession();
  if (state.isDirty) flushSave(true);
});
