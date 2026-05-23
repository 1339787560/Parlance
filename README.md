# LAN InfoShare · 兰亭信传

局域网群聊式文件共享服务器，支持多设备实时聊天、文件传输、自定义主题。

## 功能

- **实时聊天** — 基于 SSE 的实时消息推送，文本、文件、打包发送
- **文件传输** — 拖拽/粘贴发送文件，多文件自动打包 ZIP，支持断点续传下载（HTTP Range）
- **自定义昵称** — 每个 IP 可设置昵称，点击 IP/昵称切换显示
- **消息管理** — 撤回自己的消息，一键清空全部（含二次确认弹窗）
- **用户筛选** — 按下拉筛选特定用户的发言和文件
- **多主题切换** — 内置 5 套视觉主题，下拉即切，按 IP 持久化
- **手机适配** — 响应式布局，支持触摸操作

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

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 页面 |
| GET | `/api/messages` | 获取消息列表（支持 `before_id`、`sender_ip` 参数） |
| POST | `/api/messages/text` | 发送文本消息 |
| POST | `/api/messages/file` | 上传文件 |
| POST | `/api/messages/zip` | 上传多文件打包为 ZIP |
| DELETE | `/api/messages/{id}` | 撤回自己的消息 |
| DELETE | `/api/messages` | 清空所有消息（需 `?confirm=true`） |
| GET | `/api/download/{id}` | 下载文件（支持断点续传） |
| GET | `/api/events` | SSE 实时事件推送 |
| GET | `/api/theme` | 获取当前 IP 的主题偏好 |
| POST | `/api/theme` | 保存主题偏好 |
| GET | `/api/profile` | 获取当前 IP 的昵称 |
| POST | `/api/profile` | 设置昵称 |
| GET | `/api/users` | 获取活跃用户列表 |
| GET | `/api/health` | 健康检查 |

## 技术栈

- **后端**：Python + FastAPI + uvicorn
- **前端**：纯 HTML/CSS/JS，无框架无依赖
- **存储**：SQLite（消息、主题偏好、用户昵称）
- **实时**：Server-Sent Events（SSE）
- **文件流**：aiofiles 异步流式传输，支持 HTTP Range
