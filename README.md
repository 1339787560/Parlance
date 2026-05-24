# LAN InfoShare · 兰亭信传

局域网群聊式文件共享服务器，支持多设备实时聊天、文件传输、自定义主题、外部服务托管。

## 功能

- **实时聊天** — 基于 SSE 的实时消息推送，文本、文件、打包发送
- **文件传输** — 拖拽/粘贴发送文件，多文件自动打包 ZIP，支持断点续传下载（HTTP Range）
- **自定义昵称** — 每个 IP 可设置昵称，点击 IP/昵称切换显示
- **消息管理** — 撤回自己的消息，一键清空全部（含二次确认弹窗）
- **用户筛选** — 按下拉筛选特定用户的发言和文件
- **多主题切换** — 内置 5 套视觉主题，下拉即切，按 IP 持久化
- **手机适配** — 响应式布局，支持触摸操作
- **外部服务托管** — 通过子进程管理启动/停止附属服务（如 HttpPhotoServer）

## 快速开始

### 安装依赖

```bash
pip install fastapi uvicorn pyyaml python-multipart aiofiles
```

### 启动服务

```bash
python main.py
```

默认地址 `http://192.168.10.28:5000`（可在 `config.yaml` 中修改）。

### 局域网访问

同局域网设备浏览器打开 `http://<你的IP>:5000` 即可。

## 配置

编辑 `config.yaml`：

```yaml
server:
  host: 0.0.0.0       # 监听地址
  port: 5000           # 端口
  upload_dir: ./uploads # 上传文件存储路径
  max_upload_size: 1073741824  # 单文件上限（默认 1GB）

database:
  path: ./data/chat.db

# 托管的外部服务（子进程），随主服务启停
services:
  - name: http-photo-server
    command: python
    args: ["C:\\codelib\\HttpPhotoServer\\src\\main.py"]
    cwd: C:\codelib\HttpPhotoServer\src
    auto_restart: false
    tags: [media, gallery]
    enabled: true
```

### 托管服务字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 服务名称，用作标识 |
| `command` | 是 | 可执行文件路径 |
| `args` | 否 | 命令行参数列表 |
| `cwd` | 否 | 工作目录 |
| `env` | 否 | 额外环境变量键值对 |
| `auto_restart` | 否 | 崩溃后自动重启（默认 false） |
| `tags` | 否 | 标签分类 |
| `enabled` | 否 | 是否启用（默认 true） |
| `health_check` | 否 | 健康检查配置 `{url, timeout}` |

## 项目结构

```
main.py              # 入口：app 创建、lifespan、中间件
routes.py            # 所有 API 路由
state.py             # 共享应用状态（db/fh/chat/svc_mgr）
chat_manager.py      # 聊天逻辑 + SSE 事件管理器
database.py          # SQLite 封装（消息/主题/昵称）
file_handler.py      # 文件存储、ZIP 打包、流式下载
service_manager.py   # 外部服务子进程管理
config.yaml          # 配置文件
static/              # 前端资源（index.html / script.js / style.css）
style/               # 主题背景图片
```

## 主题系统

### 内置主题

| 主题 | 设计灵感 | 关键词 |
|------|---------|--------|
| 兰亭信传 | 中国传统风格 | 宣纸黄、朱砂红、檀木色 |
| 简约配色 | 现代极简 | 蓝白、清爽 |
| 珊瑚宫心海 | 原神·珊瑚宫心海 | 深海蓝、珊瑚粉、毛玻璃、气泡动画 |
| 流萤·萨姆 | 崩铁·流萤装甲 | 萤火绿、装甲灰、红黄火焰、脉动光效 |
| 芙宁娜·歌剧院 | 原神·芙宁娜 | 暗色舞台、聚光灯、白芙/黑芙双气泡 |

### 自定义主题

在 `static/style.css` 中添加 `html[data-theme="你的主题名"]` 变量块即可。变量清单：

```css
html[data-theme="your_theme"] {
  --cn-paper:       #...;  /* 页面背景色 */
  --cn-bubble:      #...;  /* 消息气泡背景 */
  --cn-ink:         #...;  /* 主文字色 */
  --cn-ink-light:   #...;  /* 次要文字 */
  --cn-ink-faint:   #...;  /* 淡化文字/边框 */
  --cn-red:         #...;  /* 主强调色 */
  --cn-red-hover:   #...;  /* 强调色悬停 */
  --cn-red-light:   #...;  /* 强调色浅淡 */
  --cn-gold:        #...;  /* 次要强调色 */
  --cn-wood:        #...;  /* 边框色 */
  --cn-overlay:     #...;  /* 遮罩层 */
}
```

然后在 `static/script.js` 的 `THEMES` 和 `THEME_NAMES` 数组中添加名称。

如需背景图片，放入 `style/主题名/` 目录，参照已有主题的 CSS 写法添加 `background-image`。

## 壁纸资源

珊瑚宫心海、流萤·萨姆、芙宁娜·歌剧院 的背景图片下载：

<https://pan.baidu.com/s/5JXkz0LTTf2X13pVF2ij5_A>

下载后将图片放入对应目录：
- `style/kokomi/kokomi.png`
- `style/firefly/firefly.png`
- `style/furina/furina.png`

## API 接口

### 聊天相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 页面 |
| GET | `/api/messages` | 获取消息列表（支持 `before_id`、`sender_ip` 参数） |
| POST | `/api/messages/text` | 发送文本消息 |
| POST | `/api/messages/file` | 上传文件 |
| POST | `/api/messages/zip` | 上传多文件打包为 ZIP |
| POST | `/api/messages/files` | 批量上传多文件 |
| DELETE | `/api/messages/{id}` | 撤回自己的消息 |
| DELETE | `/api/messages` | 清空所有消息（需 `?confirm=true`） |

### 文件相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/download/{id}` | 下载文件（支持断点续传） |
| GET | `/api/download-batch/{id}` | 下载批量文件夹为 ZIP |

### 实时通信

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events` | SSE 实时事件推送 |

### 用户与主题

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/theme` | 获取当前 IP 的主题偏好 |
| POST | `/api/theme` | 保存主题偏好 |
| GET | `/api/profile` | 获取当前 IP 的昵称 |
| POST | `/api/profile` | 设置昵称 |
| GET | `/api/users` | 获取活跃用户列表 |
| GET | `/api/whoami` | 获取当前 IP |

### 服务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/services` | 列出所有托管服务状态 |
| POST | `/api/services/{name}/start` | 启动服务 |
| POST | `/api/services/{name}/stop` | 停止服务 |
| POST | `/api/services/{name}/restart` | 重启服务 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |

## 技术栈

- **后端**：Python + FastAPI + uvicorn
- **前端**：纯 HTML/CSS/JS，无框架无依赖
- **存储**：SQLite（消息、主题偏好、用户昵称）
- **实时**：Server-Sent Events（SSE）
- **文件流**：aiofiles 异步流式传输，支持 HTTP Range
- **服务管理**：subprocess 子进程管理，支持进程树清理
