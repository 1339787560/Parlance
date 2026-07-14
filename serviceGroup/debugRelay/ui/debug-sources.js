/**
 * Sources 面板逻辑
 * - 递归嵌套文件树（可折叠）
 * - Ctrl+P 快速打开文件（VSCode 风格）
 * - Ctrl+Shift+F 全局搜索（区分大小写 / 全字匹配）
 * - 断点点击标记（register / remove）
 * - 暂停高亮
 */

// ---- State ----

let currentFile = null;
let currentContent = null;
let allFiles = [];              // 文件列表缓存
const breakpoints = new Set();  // "file:line"
let pausedFile = null;
let pausedLine = null;

// Quick Open / Search 状态
let quickOpenActive = 0;        // 0=关闭, 1=quick-open, 2=search
let paletteActiveIndex = -1;

// ---- File Tree ----

function loadFileTree() {
    fetch('/api/sources')
        .then(r => r.json())
        .then(data => {
            allFiles = data.files || [];
            renderFileTree(allFiles);
        })
        .catch(err => {
            console.error('Failed to load sources:', err);
        });
}

function renderFileTree(files) {
    const tree = document.getElementById('file-tree');
    tree.innerHTML = '';

    // 构建嵌套树结构
    const root = {};
    for (const f of files) {
        const parts = f.split('/');
        let node = root;
        for (let i = 0; i < parts.length - 1; i++) {
            if (!node[parts[i]]) node[parts[i]] = {};
            node = node[parts[i]];
        }
        node[parts[parts.length - 1]] = null;
    }

    renderTreeNode(root, tree, '', '');
}

function renderTreeNode(node, parentEl, prefix, indent) {
    const dirs = Object.keys(node).filter(k => node[k] !== null).sort();
    const files = Object.keys(node).filter(k => node[k] === null).sort();
    const total = dirs.length + files.length;
    let idx = 0;

    for (const dirName of dirs) {
        idx++;
        const isLast = idx === total;
        const connector = isLast ? '└── ' : '├── ';
        const childIndent = indent + (isLast ? '    ' : '│   ');

        const folderDiv = document.createElement('div');
        folderDiv.className = 'tree-folder';

        const header = document.createElement('div');
        header.className = 'tree-folder-header';
        header.innerHTML = `<span class="tree-line">${escapeHtml(indent + connector)}</span><span class="tree-arrow">▶</span> <span class="tree-name">${escapeHtml(dirName)}/</span>`;
        header.onclick = () => {
            const collapsed = folderDiv.classList.toggle('collapsed');
            header.querySelector('.tree-arrow').textContent = collapsed ? '▶' : '▼';
        };

        const children = document.createElement('div');
        children.className = 'tree-folder-children';

        const childPath = prefix ? prefix + '/' + dirName : dirName;
        renderTreeNode(node[dirName], children, childPath, childIndent);

        folderDiv.appendChild(header);
        folderDiv.appendChild(children);
        parentEl.appendChild(folderDiv);
    }

    for (const fileName of files) {
        idx++;
        const isLast = idx === total;
        const connector = isLast ? '└── ' : '├── ';

        const fullPath = prefix ? prefix + '/' + fileName : fileName;
        const fileDiv = document.createElement('div');
        fileDiv.className = 'tree-file';
        fileDiv.innerHTML = `<span class="tree-line">${escapeHtml(indent + connector)}</span><span class="tree-name">${escapeHtml(fileName)}</span>`;
        fileDiv.onclick = () => {
            document.querySelectorAll('.tree-file.selected').forEach(el => el.classList.remove('selected'));
            fileDiv.classList.add('selected');
            loadSourceFile(fullPath);
        };
        parentEl.appendChild(fileDiv);
    }
}

// ---- Source Viewer ----

function loadSourceFile(path) {
    currentFile = path;
    fetch('/api/source?path=' + encodeURIComponent(path))
        .then(r => {
            if (!r.ok) return r.json().then(d => { throw new Error(d.error || `HTTP ${r.status}`); });
            return r.json();
        })
        .then(data => {
            if (data.error) {
                showSourceError(data.error);
                return;
            }
            currentContent = data.content;
            renderSourceCode(path, data.content);
        })
        .catch(err => {
            showSourceError(err.message);
        });
}

function showSourceError(msg) {
    const header = document.getElementById('source-filename');
    header.textContent = '错误';
    const codeContainer = document.getElementById('source-content');
    codeContainer.innerHTML = `<div style="color:var(--red);padding:8px;">加载失败: ${escapeHtml(msg)}</div>`;
}

function renderSourceCode(path, content) {
    const header = document.getElementById('source-filename');
    header.textContent = path;

    const codeContainer = document.getElementById('source-content');
    codeContainer.innerHTML = '';

    // 是否启用语法高亮（仅 TS / JS 文件）
    const ext = path.split('.').pop().toLowerCase();
    const useHighlight = ext === 'ts' || ext === 'js';

    // 多行注释状态：跨行追踪
    let inBlockComment = false;

    const lines = content.split('\n');
    for (let i = 0; i < lines.length; i++) {
        const lineNum = i + 1;
        const lineDiv = document.createElement('div');
        lineDiv.className = 'source-line';

        const bpKey = `${path}:${lineNum}`;
        if (breakpoints.has(bpKey)) {
            lineDiv.classList.add('breakpoint');
        }

        if (pausedFile === path && pausedLine === lineNum) {
            lineDiv.classList.add('paused');
        }

        let highlighted;
        if (useHighlight) {
            const result = highlightTSLine(lines[i], inBlockComment);
            highlighted = result.html;
            inBlockComment = result.inBlockComment;
        } else {
            highlighted = escapeHtml(lines[i]);
        }

        lineDiv.innerHTML = `<span class="line-num">${lineNum}</span><span class="line-content">${highlighted}</span>`;

        const lineNumSpan = lineDiv.querySelector('.line-num');
        lineNumSpan.onclick = () => toggleBreakpoint(path, lineNum);

        codeContainer.appendChild(lineDiv);
    }
}

// ---- 语法高亮（轻量 TS/JS） ──────────────────────────────────

const TS_KEYWORDS = new Set([
    'abstract','as','async','await','break','case','catch','class','const','continue',
    'debugger','default','delete','do','else','enum','export','extends','finally','for',
    'from','function','get','if','implements','import','in','instanceof','interface','is',
    'keyof','let','module','namespace','new','null','of','package','private','protected',
    'public','readonly','return','set','static','super','switch','this','throw','try',
    'type','typeof','undefined','var','void','while','with','yield','true','false'
]);

const TS_BUILTIN_TYPES = new Set([
    'string','number','boolean','any','unknown','never','object','symbol','bigint','Array','Promise','Map','Set','Date','RegExp','Error','Function'
]);

function highlightTSLine(line, inBlockComment) {
    let html = '';
    let i = 0;
    const n = line.length;

    // 续接的多行注释
    if (inBlockComment) {
        const endIdx = line.indexOf('*/');
        if (endIdx === -1) {
            return { html: `<span class="tok-comment">${escapeHtml(line)}</span>`, inBlockComment: true };
        }
        html += `<span class="tok-comment">${escapeHtml(line.substring(0, endIdx + 2))}</span>`;
        i = endIdx + 2;
        inBlockComment = false;
    }

    while (i < n) {
        const c = line[i];
        const next = line[i + 1];

        // 单行注释
        if (c === '/' && next === '/') {
            html += `<span class="tok-comment">${escapeHtml(line.substring(i))}</span>`;
            return { html, inBlockComment: false };
        }

        // 多行注释开始
        if (c === '/' && next === '*') {
            const endIdx = line.indexOf('*/', i + 2);
            if (endIdx === -1) {
                html += `<span class="tok-comment">${escapeHtml(line.substring(i))}</span>`;
                return { html, inBlockComment: true };
            }
            html += `<span class="tok-comment">${escapeHtml(line.substring(i, endIdx + 2))}</span>`;
            i = endIdx + 2;
            continue;
        }

        // 字符串（", ', `）
        if (c === '"' || c === "'" || c === '`') {
            const quote = c;
            let j = i + 1;
            while (j < n) {
                if (line[j] === '\\') { j += 2; continue; }
                if (line[j] === quote) { j++; break; }
                j++;
            }
            html += `<span class="tok-string">${escapeHtml(line.substring(i, j))}</span>`;
            i = j;
            continue;
        }

        // 数字
        if (/[0-9]/.test(c)) {
            let j = i;
            while (j < n && /[0-9_.xXa-fA-F]/.test(line[j])) j++;
            html += `<span class="tok-number">${escapeHtml(line.substring(i, j))}</span>`;
            i = j;
            continue;
        }

        // 标识符 / 关键字
        if (/[a-zA-Z_$]/.test(c)) {
            let j = i;
            while (j < n && /[a-zA-Z0-9_$]/.test(line[j])) j++;
            const word = line.substring(i, j);

            // 判断后续是否为函数调用 / 方法属性
            const k = j;
            let nextNonSpace = '';
            for (let m = k; m < n; m++) {
                if (line[m] !== ' ' && line[m] !== '\t') { nextNonSpace = line[m]; break; }
            }
            const prevChar = i > 0 ? line[i - 1] : '';

            if (TS_KEYWORDS.has(word)) {
                html += `<span class="tok-keyword">${escapeHtml(word)}</span>`;
            } else if (TS_BUILTIN_TYPES.has(word)) {
                html += `<span class="tok-type">${escapeHtml(word)}</span>`;
            } else if (nextNonSpace === '(') {
                html += `<span class="tok-func">${escapeHtml(word)}</span>`;
            } else if (prevChar === '.') {
                html += `<span class="tok-prop">${escapeHtml(word)}</span>`;
            } else {
                html += escapeHtml(word);
            }
            i = j;
            continue;
        }

        // 标点
        if (/[{}()\[\];,.<>=+\-*/%!&|^~?:]/.test(c)) {
            html += `<span class="tok-punct">${escapeHtml(c)}</span>`;
            i++;
            continue;
        }

        // 其他字符
        html += escapeHtml(c);
        i++;
    }

    return { html, inBlockComment };
}

// ---- 字号调节 ──────────────────────────────────────────────────

const FONT_SIZE_KEY = 'debug_code_font_size';
const MIN_FONT_SIZE = 10;
const MAX_FONT_SIZE = 28;

function getCodeFontSize() {
    const saved = parseInt(localStorage.getItem(FONT_SIZE_KEY), 10);
    return (saved >= MIN_FONT_SIZE && saved <= MAX_FONT_SIZE) ? saved : 13;
}

function applyCodeFontSize(size) {
    document.documentElement.style.setProperty('--code-font-size', size + 'px');
    const label = document.getElementById('font-size-label');
    if (label) label.textContent = size + 'px';
    localStorage.setItem(FONT_SIZE_KEY, String(size));
}

function changeCodeFontSize(delta) {
    let size = getCodeFontSize() + delta;
    if (size < MIN_FONT_SIZE) size = MIN_FONT_SIZE;
    if (size > MAX_FONT_SIZE) size = MAX_FONT_SIZE;
    applyCodeFontSize(size);
}

// 启动时应用保存的字号
applyCodeFontSize(getCodeFontSize());

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ---- Breakpoints ----

function toggleBreakpoint(path, line) {
    const bpKey = `${path}:${line}`;
    if (breakpoints.has(bpKey)) {
        breakpoints.delete(bpKey);
        wsSend({ type: 'remove_breakpoint', file: path, line: line });
    } else {
        breakpoints.add(bpKey);
        wsSend({ type: 'register_breakpoint', file: path, line: line });
    }

    if (currentFile === path) {
        renderSourceCode(path, currentContent);
    }
}

// ---- Pause / Resume ----

function highlightPausedLine(file, lineOrFunc) {
    pausedFile = file;
    pausedLine = typeof lineOrFunc === 'number' ? lineOrFunc : null;

    if (currentFile === file) {
        renderSourceCode(file, currentContent);
    }
}

function handlePauseState(msg) {
    if (!msg.paused) {
        pausedFile = null;
        pausedLine = null;
        if (currentFile) {
            renderSourceCode(currentFile, currentContent);
        }
    }
}

// ---- Source List/Content from WebSocket ----

function handleSourceList(msg) {
    if (msg.files) {
        allFiles = msg.files;
        renderFileTree(allFiles);
    }
}

function handleSourceContent(msg) {
    if (msg.file && msg.content) {
        currentFile = msg.file;
        currentContent = msg.content;
        renderSourceCode(msg.file, msg.content);
    }
}

// ---- Ctrl+P Quick Open ──────────────────────────────────────────

function showQuickOpen() {
    quickOpenActive = 1;
    paletteActiveIndex = -1;
    const panel = document.getElementById('quick-open');
    panel.classList.remove('hidden');
    const input = document.getElementById('quick-open-input');
    input.value = '';
    input.focus();
    renderQuickOpenResults('');
}

function hideQuickOpen() {
    quickOpenActive = 0;
    paletteActiveIndex = -1;
    document.getElementById('quick-open').classList.add('hidden');
}

function renderQuickOpenResults(query) {
    const resultsEl = document.getElementById('quick-open-results');
    resultsEl.innerHTML = '';
    paletteActiveIndex = -1;

    if (!query) {
        // 显示最近文件 + 所有文件
        const items = allFiles.slice(0, 50);
        items.forEach((f, i) => {
            const div = document.createElement('div');
            div.className = 'palette-item';
            div.dataset.index = i;
            div.dataset.path = f;
            div.innerHTML = `<span class="item-icon">📄</span><span class="item-path">${f}</span>`;
            div.onclick = () => {
                loadSourceFile(f);
                hideQuickOpen();
            };
            resultsEl.appendChild(div);
        });
        return;
    }

    // 按文件名匹配排序
    const qLower = query.toLowerCase();
    const matches = allFiles.filter(f => f.toLowerCase().includes(qLower));
    matches.slice(0, 30).forEach((f, i) => {
        const div = document.createElement('div');
        div.className = 'palette-item';
        div.dataset.index = i;
        div.dataset.path = f;
        // 高亮匹配部分
        const idx = f.toLowerCase().indexOf(qLower);
        const before = f.substring(0, idx);
        const match = f.substring(idx, idx + query.length);
        const after = f.substring(idx + query.length);
        div.innerHTML = `<span class="item-icon">📄</span><span class="item-path">${escapeHtml(before)}<strong>${escapeHtml(match)}</strong>${escapeHtml(after)}</span>`;
        div.onclick = () => {
            loadSourceFile(f);
            hideQuickOpen();
        };
        resultsEl.appendChild(div);
    });
}

// ---- Ctrl+Shift+F Global Search ────────────────────────────────

function showSearchPanel() {
    quickOpenActive = 2;
    paletteActiveIndex = -1;
    const panel = document.getElementById('search-panel');
    panel.classList.remove('hidden');
    const input = document.getElementById('search-input');
    input.value = '';
    input.focus();
    document.getElementById('search-results').innerHTML = '';
}

function hideSearchPanel() {
    quickOpenActive = 0;
    paletteActiveIndex = -1;
    document.getElementById('search-panel').classList.add('hidden');
}

function executeSearch() {
    const query = document.getElementById('search-input').value.trim();
    const caseSensitive = document.getElementById('search-case').checked;
    const wholeWord = document.getElementById('search-whole').checked;
    const resultsEl = document.getElementById('search-results');
    resultsEl.innerHTML = '';

    if (!query || !allFiles.length) return;

    // 构建搜索参数
    let regex;
    try {
        const wordPattern = wholeWord ? `\\b${query}\\b` : query;
        regex = new RegExp(wordPattern, caseSensitive ? 'g' : 'gi');
    } catch (e) {
        resultsEl.innerHTML = `<div style="color:var(--red);padding:8px;">正则错误: ${escapeHtml(e.message)}</div>`;
        return;
    }

    // 对每个文件发起搜索请求
    let fileCount = 0;
    let matchCount = 0;

    allFiles.slice(0, 100).forEach(f => {
        fetch('/api/source?path=' + encodeURIComponent(f))
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (!data || !data.content) return;

                const content = data.content;
                const lines = content.split('\n');
                const matches = [];

                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i];
                    // 重置 regex lastIndex
                    regex.lastIndex = 0;
                    if (regex.test(line)) {
                        matches.push({ lineNum: i + 1, line: line });
                    }
                }

                if (matches.length === 0) return;

                matchCount += matches.length;
                fileCount++;

                // 渲染文件头
                const fileHeader = document.createElement('div');
                fileHeader.className = 'search-result-file';
                fileHeader.textContent = `${f} (${matches.length} 处匹配)`;
                resultsEl.appendChild(fileHeader);

                // 渲染匹配行（最多 5 行 / 文件）
                matches.slice(0, 5).forEach(m => {
                    const lineDiv = document.createElement('div');
                    lineDiv.className = 'search-result-line';
                    lineDiv.onclick = () => {
                        loadSourceFile(f);
                        hideSearchPanel();
                        // 滚动到对应行
                        setTimeout(() => {
                            const sourceCode = document.getElementById('source-code');
                            const lineEl = sourceCode.querySelector(`.source-line:nth-child(${m.lineNum})`);
                            if (lineEl) lineEl.scrollIntoView({ block: 'center' });
                        }, 100);
                    };

                    // 高亮匹配词
                    const escapedLine = escapeHtml(m.line);
                    const escapedQuery = escapeHtml(query);
                    const highlighted = escapedLine.replace(
                        new RegExp(escapedQuery, caseSensitive ? 'g' : 'gi'),
                        `<span class="match-highlight">${escapedQuery}</span>`
                    );
                    lineDiv.innerHTML = `<span style="color:var(--dim);min-width:30px;display:inline-block">${m.lineNum}</span>${highlighted}`;
                    resultsEl.appendChild(lineDiv);
                });

                if (matches.length > 5) {
                    const moreDiv = document.createElement('div');
                    moreDiv.className = 'search-result-line';
                    moreDiv.textContent = `... 还有 ${matches.length - 5} 处`;
                    resultsEl.appendChild(moreDiv);
                }
            })
            .catch(() => {});
    });
}

// ---- Keyboard Shortcuts ─────────────────────────────────────────

document.addEventListener('keydown', (e) => {
    // Ctrl+P → Quick Open
    if (e.ctrlKey && !e.shiftKey && e.key === 'p') {
        e.preventDefault();
        if (quickOpenActive === 1) {
            hideQuickOpen();
        } else {
            hideSearchPanel();
            showQuickOpen();
        }
        return;
    }

    // Ctrl+Shift+F → Global Search
    if (e.ctrlKey && e.shiftKey && e.key === 'F') {
        e.preventDefault();
        if (quickOpenActive === 2) {
            hideSearchPanel();
        } else {
            hideQuickOpen();
            showSearchPanel();
        }
        return;
    }

    // Escape → 关闭面板
    if (e.key === 'Escape') {
        if (quickOpenActive === 1) hideQuickOpen();
        if (quickOpenActive === 2) hideSearchPanel();
        return;
    }

    // Enter → 选择当前 palette 项
    if (e.key === 'Enter' && quickOpenActive === 1) {
        const items = document.querySelectorAll('#quick-open-results .palette-item');
        if (paletteActiveIndex >= 0 && items[paletteActiveIndex]) {
            const path = items[paletteActiveIndex].dataset.path;
            loadSourceFile(path);
            hideQuickOpen();
        }
        return;
    }

    if (e.key === 'Enter' && quickOpenActive === 2) {
        e.preventDefault();
        executeSearch();
        return;
    }

    // Arrow navigation in palette
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && quickOpenActive === 1) {
        e.preventDefault();
        const items = document.querySelectorAll('#quick-open-results .palette-item');
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            paletteActiveIndex = Math.min(paletteActiveIndex + 1, items.length - 1);
        } else {
            paletteActiveIndex = Math.max(paletteActiveIndex - 1, 0);
        }

        items.forEach(el => el.classList.remove('active'));
        items[paletteActiveIndex].classList.add('active');
        items[paletteActiveIndex].scrollIntoView({ block: 'nearest' });
        return;
    }
});

// Quick Open 输入框事件
document.addEventListener('DOMContentLoaded', () => {
    const quickOpenInput = document.getElementById('quick-open-input');
    if (quickOpenInput) {
        quickOpenInput.addEventListener('input', () => {
            renderQuickOpenResults(quickOpenInput.value);
        });
    }

    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                executeSearch();
            }
        });
    }

    // 搜索选项变更时自动重新搜索
    const searchCase = document.getElementById('search-case');
    const searchWhole = document.getElementById('search-whole');
    if (searchCase) searchCase.addEventListener('change', () => {
        if (document.getElementById('search-input').value.trim()) executeSearch();
    });
    if (searchWhole) searchWhole.addEventListener('change', () => {
        if (document.getElementById('search-input').value.trim()) executeSearch();
    });
});

// ---- 多客户端：切换/订阅时重置 + 断点状态 replay ----

function resetSourcesPanel() {
    currentFile = null;
    currentContent = null;
    breakpoints.clear();
    pausedFile = null;
    pausedLine = null;
    const header = document.getElementById('source-filename');
    if (header) header.textContent = '未选择文件';
    const code = document.getElementById('source-content');
    if (code) code.innerHTML = '选择左侧文件浏览源码';
    const pauseInd = document.getElementById('pause-indicator');
    const resumeBtn = document.getElementById('resume-btn');
    if (pauseInd) pauseInd.classList.add('hidden');
    if (resumeBtn) resumeBtn.classList.add('hidden');
}

function applyBreakpointsState(bps) {
    breakpoints.clear();
    for (const bp of bps) {
        if (bp && bp.file != null && bp.line != null) {
            breakpoints.add(`${bp.file}:${bp.line}`);
        }
    }
    if (currentFile && currentContent) {
        renderSourceCode(currentFile, currentContent);
    }
}

window.resetSourcesPanel = resetSourcesPanel;
window.applyBreakpointsState = applyBreakpointsState;

// ---- Init ----

loadFileTree();
