/**
 * Sources 面板逻辑
 * - 递归嵌套文件树（可折叠）
 * - 代码展示 + 行号
 * - 断点标记点击
 * - 暂停高亮
 */

// ---- State ----

let currentFile = null;
let currentContent = null;
const breakpoints = new Set();  // "file:line"
let pausedFile = null;
let pausedLine = null;

// ---- File Tree ----

function loadFileTree() {
    fetch('/api/sources')
        .then(r => r.json())
        .then(data => {
            renderFileTree(data.files || []);
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
        node[parts[parts.length - 1]] = null;  // null = 文件叶节点
    }

    // 递归渲染
    renderTreeNode(root, tree, '');
}

function renderTreeNode(node, parentEl, prefix) {
    // 先渲染文件夹（排序）
    const dirs = Object.keys(node).filter(k => node[k] !== null).sort();
    // 再渲染文件（排序）
    const files = Object.keys(node).filter(k => node[k] === null).sort();

    for (const dirName of dirs) {
        const folderDiv = document.createElement('div');
        folderDiv.className = 'tree-folder';

        const header = document.createElement('div');
        header.className = 'tree-folder-header';
        header.innerHTML = `<span class="tree-arrow">▶</span><span class="tree-icon">📁</span><span class="tree-name">${dirName}</span>`;
        header.onclick = () => {
            const collapsed = folderDiv.classList.toggle('collapsed');
            header.querySelector('.tree-arrow').textContent = collapsed ? '▶' : '▼';
        };

        const children = document.createElement('div');
        children.className = 'tree-folder-children';

        const childPath = prefix ? prefix + '/' + dirName : dirName;
        renderTreeNode(node[dirName], children, childPath);

        folderDiv.appendChild(header);
        folderDiv.appendChild(children);
        parentEl.appendChild(folderDiv);
    }

    for (const fileName of files) {
        const fullPath = prefix ? prefix + '/' + fileName : fileName;
        const fileDiv = document.createElement('div');
        fileDiv.className = 'tree-file';
        fileDiv.innerHTML = `<span class="tree-icon">📄</span><span class="tree-name">${fileName}</span>`;
        fileDiv.onclick = () => {
            // 选中高亮
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
    codeContainer.innerHTML = `<div style="color:#f44747;padding:8px;">加载失败: ${escapeHtml(msg)}</div>`;
}

function renderSourceCode(path, content) {
    const header = document.getElementById('source-filename');
    header.textContent = path;

    const codeContainer = document.getElementById('source-content');
    codeContainer.innerHTML = '';

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

        lineDiv.innerHTML = `
            <span class="line-num">${lineNum}</span>
            <span class="line-content">${escapeHtml(lines[i])}</span>
        `;

        const lineNumSpan = lineDiv.querySelector('.line-num');
        lineNumSpan.onclick = () => toggleBreakpoint(path, lineNum);

        codeContainer.appendChild(lineDiv);
    }
}

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
        renderFileTree(msg.files);
    }
}

function handleSourceContent(msg) {
    if (msg.file && msg.content) {
        currentFile = msg.file;
        currentContent = msg.content;
        renderSourceCode(msg.file, msg.content);
    }
}

// ---- Init ----

loadFileTree();
