# A2A 文件管理系统 - 原型文档

> **位置**: `src/A2AFile`
> **日期**: 2026-04-22

---

## 一、功能概述

A2A 文件管理系统是一个基于 Flask 的文件管理服务，提供以下核心功能：
- HTTP API 文件 CRUD 操作
- Git 版本管理集成
- Web 前端界面 (A2AManager.html)
- Python 单元测试

---

## 二、HTTP API 设计

### 2.1 文件列表接口

**路由**: `/api/a2a/list`

**方法**: `GET`

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 否 | 相对路径，默认为空（根目录） |

**响应**:
```json
{
    "success": true,
    "files": [
        {
            "name": "文件夹名或文件名",
            "type": "folder|file",
            "extension": ".md|.py|.json|null",
            "path": "相对路径",
            "size": 1024
        }
    ],
    "current_path": "当前路径"
}
```

**可展示项配置**: 文件夹、`.md`、`.py`、`.json` 文件

---

### 2.2 创建文件接口

**路由**: `/api/a2a/create`

**方法**: `POST`

**参数**:
```json
{
    "path": "相对路径/文件名.md",
    "content": "文件内容（可选，默认空）",
    "desc": "提交描述附加说明（可选）"
}
```

**响应**:
```json
{
    "success": true,
    "message": "文件创建成功",
    "git_commit": "fileName changed [desc]"
}
```

---

### 2.3 获取文件内容接口

**路由**: `/api/a2a/get`

**方法**: `GET`

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 相对路径/文件名 |
| `desc` | string | 否 | 访问记录附加说明 |

**响应**:
```json
{
    "success": true,
    "content": "文件内容",
    "extension": ".md",
    "size": 1024
}
```

---

### 2.4 修改文件接口

**路由**: `/api/a2a/update`

**方法**: `POST`

**参数**:
```json
{
    "path": "相对路径/文件名.md",
    "content": "新文件内容",
    "desc": "提交描述附加说明（可选）"
}
```

**响应**:
```json
{
    "success": true,
    "message": "文件修改成功",
    "git_commit": "fileName changed [desc]"
}
```

---

### 2.5 删除文件接口

**路由**: `/api/a2a/delete`

**方法**: `POST`

**参数**:
```json
{
    "path": "相对路径/文件名.md"
}
```

**响应**:
```json
{
    "success": true,
    "message": "文件删除成功",
    "git_commit": "fileName changed"
}
```

---

### 2.6 Git 提交历史接口

**路由**: `/api/a2a/history`

**方法**: `GET`

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 相对路径/文件名 |

**响应**:
```json
{
    "success": true,
    "commits": [
        {
            "hash": "a1b2c3d",
            "message": "fileName changed",
            "date": "2026-04-22 10:30:00",
            "author": "system"
        }
    ]
}
```

---

### 2.7 获取历史版本接口

**路由**: `/api/a2a/version`

**方法**: `GET`

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 相对路径/文件名 |
| `hash` | string | 是 | Git commit hash |

**响应**:
```json
{
    "success": true,
    "content": "历史版本文件内容",
    "commit": {
        "hash": "a1b2c3d",
        "message": "fileName changed",
        "date": "2026-04-22 10:30:00"
    }
}
```

---

## 三、版本管理设计

### 3.1 Git 独立仓库

- `src/A2AFile` 目录下使用独立的 `.git` 仓库
- 不依赖外层项目的 `.git`
- 服务启动时自动检查并初始化 Git 仓库

### 3.2 提交日志规则

| 操作 | 默认日志格式 |
|------|-------------|
| 创建 | `{fileName} changed` |
| 修改 | `{fileName} changed` |
| 删除 | `{fileName} changed` |

**附加说明**: 如果请求携带 `desc` 参数，日志格式变为 `{fileName} changed - {desc}`

### 3.3 Git 初始化流程

```python
def ensure_git_initialized():
    a2a_dir = os.path.join(os.getcwd(), 'src', 'A2AFile')
    git_dir = os.path.join(a2a_dir, '.git')

    if not os.path.exists(git_dir):
        # 初始化 Git 仓库
        subprocess.run(['git', 'init'], cwd=a2a_dir)
        # 配置用户信息（避免警告）
        subprocess.run(['git', 'config', 'user.email', 'a2a@system'], cwd=a2a_dir)
        subprocess.run(['git', 'config', 'user.name', 'A2A System'], cwd=a2a_dir)
```

---

## 四、前端页面设计 (A2AManager.html)

### 4.1 页面路由

**路由**: `/a2a-manager`

### 4.2 页面结构

```
┌─────────────────────────────────────────────────────────┐
│ 面包屑: 主页 > A2A管理 > [子文件夹路径...]              │
│ 刷新按钮                                                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  📁 folder1                                    [进入]  │
│  ─────────────────────────────────────────────────────  │
│  📁 folder2                                    [进入]  │
│  ─────────────────────────────────────────────────────  │
│  📄 file.md                          1.2 KB    [查看]  │
│  ─────────────────────────────────────────────────────  │
│  🐍 test.py                          3.5 KB    [查看]  │
│  ─────────────────────────────────────────────────────  │
│  📋 data.json                        512 B     [查看]  │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ 页面底部                                                │
└─────────────────────────────────────────────────────────┘
```

**长条列表样式说明**:
- 每个文件/文件夹占用一行，左侧图标+名称，右侧显示文件大小和操作按钮
- 文件夹显示"进入"按钮，文件显示"查看"按钮
- 使用分隔线或背景色区分每一行
- 悬停时整行高亮显示
- 点击文件夹条目直接进入该目录的递归结构，无需点击"进入"按钮
- 点击文件条目直接打开文件预览页面，无需点击"查看"按钮

### 4.3 文件预览页面结构

```
┌─────────────────────────────────────────────────┐
│ 面包屑: 主页 > A2A管理 > folder1 > file.md       │
│ 返回按钮                                         │
├─────────────────────────────────────────────────┤
│ Git 提交记录                                     │
│ ┌─────────────────────────────────────────────┐ │
│ │ ● 2026-04-22 10:30 file.md changed          │ │
│ │ ● 2026-04-21 15:00 file.md changed - 初始化 │ │
│ │   [点击查看历史版本]                          │ │
│ └─────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────┤
│                                                 │
│ 文件内容预览区（美化容器）                        │
│                                                 │
│ ┌─────────────────────────────────────────────┐ │
│ │ # Markdown 标题                              │ │
│ │                                              │ │
│ │ 内容段落...                                  │ │
│ │                                              │ │
│ │ - 列表项                                     │ │
│ │ - 列表项                                     │ │
│ └─────────────────────────────────────────────┘ │
│                                                 │
│ .py 文件: 代码语法高亮                           │
│ .json 文件: 格式化展示                           │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 4.4 交互功能

| 功能 | 实现方式 |
|------|---------|
| 点击文件夹 | 跳转到该文件夹的递归展示页面 |
| 面包屑导航 | 点击路径项跳转到对应位置 |
| 点击文件 | 打开文件预览页面 |
| 查看历史版本 | 点击提交记录，加载该版本的文件内容 |
| 刷新按钮 | 重新调用 `/api/a2a/list` 拉取最新内容 |

### 4.5 文件类型展示美化

| 文件类型 | 展示方式 |
|---------|---------|
| `.md` | Markdown 渲染（使用 marked.js，参考 AIManager.html） |
| `.py` | 代码高亮（使用 highlight.js 或 prism.js） |
| `.json` | 格式化 JSON 展示，语法高亮 |

---

## 五、单元测试设计

### 5.1 测试文件位置

`tests/test_a2a.py`

### 5.2 测试流程

```python
def test_a2a_file_operations():
    """测试 exam1.md 的完整 CRUD 流程"""

    # 1. 创建 exam1.md
    response = client.post('/api/a2a/create', json={
        'path': 'exam1.md',
        'content': '# Test File\nInitial content.',
        'desc': '单元测试创建'
    })
    assert response.json['success'] == True

    # 2. 获取 exam1.md
    response = client.get('/api/a2a/get?path=exam1.md')
    assert response.json['success'] == True
    assert '# Test File' in response.json['content']

    # 3. 修改 exam1.md
    response = client.post('/api/a2a/update', json={
        'path': 'exam1.md',
        'content': '# Modified\nUpdated content.',
        'desc': '单元测试修改'
    })
    assert response.json['success'] == True

    # 4. 验证修改
    response = client.get('/api/a2a/get?path=exam1.md')
    assert 'Modified' in response.json['content']

    # 5. 检查 Git 历史
    response = client.get('/api/a2a/history?path=exam1.md')
    assert len(response.json['commits']) >= 2

    # 6. 删除 exam1.md
    response = client.post('/api/a2a/delete', json={
        'path': 'exam1.md'
    })
    assert response.json['success'] == True
```

---

## 六、index.html 集成

### 6.1 新增按钮

在 `toolbar` 区域添加 A2A 管理按钮：

```html
<button class="a2a-btn" onclick="window.location.href='/a2a-manager'">📁 A2A管理</button>
```

### 6.2 按钮样式（参考现有风格）

```css
.a2a-btn {
    background-color: rgba(233, 69, 96, 0.7);
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    cursor: pointer;
    margin-right: 10px;
    backdrop-filter: blur(2px);
}

.a2a-btn:hover {
    background-color: rgba(200, 50, 80, 0.9);
}
```

---

## 七、文件结构规划

```
src/
├── A2AFile/                    # 文件存储目录
│   ├── .git/                   # 独立 Git 仓库
│   └── *.md/*.py/*.json        # 用户文件
│
CustomRoute/
├── ServiceRoute.py             # 新增 A2A API 路由
├── templates/
│   ├── index.html              # 新增 A2A 管理按钮
│   └── A2AManager.html         # A2A 管理页面
│
tests/
├── test_a2a.py                 # 单元测试文件
```

---

## 八、技术栈

| 类别 | 技术 |
|------|------|
| 后端框架 | Flask (现有) |
| Git 操作 | `subprocess` 调用 `git` 命令 |
| Markdown 渲染 | marked.js (参考 AIManager.html) |
| 代码高亮 | highlight.js 或 prism.js |
| 前端样式 | 参考 index.html / AIManager.html 玻璃拟态风格 |
| 单元测试 | Python `unittest` 或 `pytest` |

---

## 六、并发处理设计

### 6.1 并发场景分析

| 场景 | 风险等级 | 说明 |
|------|---------|------|
| 多 Agent 同时修改同一文件 | 🔴 高 | 后写入者覆盖先写入者，数据丢失 |
| 读写并发 | 🟡 中 | 可能读取到不完整或中间状态数据 |
| Git 操作并发 | 🔴 高 | `git add/commit` 并发执行可能导致仓库状态损坏 |
| 多 Agent 操作不同文件 | 🟢 低 | 天然隔离，无需特殊处理 |

### 6.2 并发控制方案

**方案选择**: 文件级锁 + 操作队列

```
┌─────────────────────────────────────────────────────────┐
│                    A2A 文件服务                          │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │  Agent A    │    │  Agent B    │    │  Agent C    │ │
│  │  写入 a.md  │    │  写入 a.md  │    │  读取 b.md  │ │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘ │
│         │                  │                  │        │
│         ▼                  ▼                  ▼        │
│  ┌──────────────────────────────────────────────────┐ │
│  │              文件锁管理器 (FileLockManager)        │ │
│  │                                                   │ │
│  │   a.md: 🔒 Locked by Agent A                      │ │
│  │   b.md: 🔓 Unlocked                               │ │
│  │                                                   │ │
│  │   等待队列:                                       │ │
│  │   - Agent B (写入 a.md) → 等待中...              │ │
│  └──────────────────────────────────────────────────┘ │
│                          │                            │
│                          ▼                            │
│  ┌──────────────────────────────────────────────────┐ │
│  │              Git 操作队列 (GitOperationQueue)     │ │
│  │                                                   │ │
│  │   串行执行所有 Git 操作，避免仓库损坏             │ │
│  │                                                   │ │
│  │   队列:                                           │ │
│  │   1. [执行中] commit a.md                        │ │
│  │   2. [等待] commit b.md                          │ │
│  └──────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 6.3 实现方案

#### 6.3.1 文件锁管理器

```python
import threading
from collections import defaultdict
from datetime import datetime

class FileLockManager:
    def __init__(self):
        self._locks = defaultdict(threading.Lock)  # 文件路径 -> 锁
        self._lock_info = {}  # 文件路径 -> (holder, timestamp)
        self._global_lock = threading.Lock()  # 保护 _lock_info

    def acquire(self, file_path: str, holder: str = "unknown", timeout: float = 30.0) -> bool:
        """获取文件锁，超时返回 False"""
        with self._global_lock:
            if file_path in self._lock_info:
                return False  # 已被锁定
            self._lock_info[file_path] = (holder, datetime.now())

        acquired = self._locks[file_path].acquire(timeout=timeout)
        if not acquired:
            with self._global_lock:
                self._lock_info.pop(file_path, None)
        return acquired

    def release(self, file_path: str):
        """释放文件锁"""
        with self._global_lock:
            self._lock_info.pop(file_path, None)
        if file_path in self._locks:
            self._locks[file_path].release()

    def is_locked(self, file_path: str) -> bool:
        """检查文件是否被锁定"""
        with self._global_lock:
            return file_path in self._lock_info

    def get_lock_info(self, file_path: str) -> dict:
        """获取锁信息"""
        with self._global_lock:
            if file_path in self._lock_info:
                holder, ts = self._lock_info[file_path]
                return {"locked": True, "holder": holder, "since": str(ts)}
            return {"locked": False}

# 全局实例
file_lock_manager = FileLockManager()
```

#### 6.3.2 Git 操作队列

```python
import queue
import threading
import subprocess

class GitOperationQueue:
    def __init__(self):
        self._queue = queue.Queue()
        self._worker = None
        self._running = False

    def start(self):
        """启动 Git 操作工作线程"""
        self._running = True
        self._worker = threading.Thread(target=self._process_queue, daemon=True)
        self._worker.start()

    def _process_queue(self):
        """串行处理 Git 操作"""
        while self._running:
            try:
                operation = self._queue.get(timeout=1.0)
                if operation:
                    operation()
                self._queue.task_done()
            except queue.Empty:
                continue

    def submit(self, operation: callable):
        """提交 Git 操作到队列"""
        self._queue.put(operation)

    def submit_and_wait(self, operation: callable, timeout: float = 30.0) -> bool:
        """提交并等待完成"""
        result = {"done": False, "success": False}
        event = threading.Event()

        def wrapped():
            try:
                operation()
                result["success"] = True
            except Exception as e:
                result["error"] = str(e)
            finally:
                result["done"] = True
                event.set()

        self._queue.put(wrapped)
        return event.wait(timeout=timeout) and result["success"]

# 全局实例
git_operation_queue = GitOperationQueue()
```

#### 6.3.3 API 集成示例

```python
@app.route('/api/a2a/update', methods=['POST'])
def api_a2a_update():
    data = request.json
    file_path = data.get('path')
    content = data.get('content')
    desc = data.get('desc', '')
    holder = request.remote_addr  # 或从 header 获取 Agent ID

    # 1. 获取文件锁
    if not file_lock_manager.acquire(file_path, holder, timeout=10.0):
        lock_info = file_lock_manager.get_lock_info(file_path)
        return jsonify({
            'success': False,
            'message': f'文件被锁定，当前持有者: {lock_info.get("holder")}'
        }), 423  # 423 Locked

    try:
        # 2. 写入文件
        full_path = get_full_path(file_path)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # 3. 提交 Git 操作（通过队列串行执行）
        def git_commit():
            subprocess.run(['git', 'add', file_path], cwd=A2A_DIR)
            commit_msg = f"{os.path.basename(file_path)} changed"
            if desc:
                commit_msg += f" - {desc}"
            subprocess.run(['git', 'commit', '-m', commit_msg], cwd=A2A_DIR)

        success = git_operation_queue.submit_and_wait(git_commit, timeout=30.0)

        if not success:
            return jsonify({'success': False, 'message': 'Git 操作超时'}), 500

        return jsonify({'success': True, 'message': '文件修改成功'})

    finally:
        # 4. 释放锁
        file_lock_manager.release(file_path)
```

### 6.4 锁状态查询接口

**路由**: `/api/a2a/lock-status`

**方法**: `GET`

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 相对路径/文件名 |

**响应**:
```json
{
    "success": true,
    "locked": true,
    "holder": "Agent-A",
    "since": "2026-04-22 10:30:00"
}
```

### 6.5 冲突处理策略

| 策略 | 适用场景 | 说明 |
|------|---------|------|
| **等待锁释放** | 默认策略 | 请求等待锁释放，超时返回 423 Locked |
| **立即失败** | 高并发场景 | 检测到锁立即返回，由 Agent 决定重试策略 |
| **乐观锁** | 读多写少 | 基于版本号检测冲突，冲突时要求重新获取 |

**当前实现**: 采用 **等待锁释放** 策略，超时时间 10 秒

### 6.6 性能考虑

- 文件锁是 **文件级** 而非全局锁，不同文件操作可并行
- Git 操作串行化是必要的，但通过队列异步执行减少等待
- 读操作可考虑 **读写锁** 优化（多读并行，写独占）

---

## 七、风险与注意事项

1. **路径安全**: 需防止路径穿越攻击，限制在 `src/A2AFile` 目录内
2. **Git 冲突**: 通过 Git 操作队列串行化，避免仓库损坏
3. **并发写入**: 通过文件锁机制，避免数据丢失
4. **大文件处理**: 暂不限制文件大小，后续可按需添加
5. **编码处理**: 统一使用 UTF-8 编码
6. **锁泄漏**: 使用 `try-finally` 确保锁释放，异常时自动释放

---

**请确认以上原型文档是否符合您的需求，确认后我将开始实现。**