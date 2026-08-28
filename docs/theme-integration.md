# 主题系统集成指南

infoServer 有 8 套主题（朱砂红、简约配色、珊瑚宫心海、流萤·萨姆、芙宁娜·歌剧院、海瑟音·深境、天才俱乐部、狼尊 LV.999、奥黛塔·月夜羽翼），子服务页面可共享同一套主题，同一用户在不同页面间样式一致。

## 原理

infoServer 的 `static/style.css` 用 `html[data-theme="xxx"]` 定义多组 CSS 变量（`--cn-paper`、`--cn-ink` 等）。子服务页面只需：

1. 引用该 CSS
2. 自己的颜色值写成 `var(--cn-xxx, <fallback>)` 形式
3. 设置 `data-theme` 属性
4. 同步主题选择到 infoServer 服务端

## 集成步骤

### 1. 加载 infoServer 主题 CSS

```html
<link rel="stylesheet" href="http://127.0.0.1:5001/static/style.css">
```

CSS 中 `url('/style/xxx/xxx.png')` 等资源路径会以 infoServer 为 origin 解析，背景图片正常显示。

### 2. 页面 CSS 变量使用 `--cn-*`

```css
/* ❌ 不跟随主题 */
:root {
  --bg: #0d1117;
  --text: #e6edf3;
}

/* ✅ 跟随主题（fallback 保持无主题时正常显示） */
:root {
  --bg:   var(--cn-paper, #0d1117);
  --text: var(--cn-ink, #e6edf3);
}
```

变量映射参考：

| 页面变量 | 主题变量 | 含义 |
|---------|---------|------|
| `--bg` | `--cn-paper` | 页面背景 |
| `--card` | `--cn-bubble` | 卡片/气泡背景 |
| `--border` | `--cn-wood` | 边框 |
| `--text` | `--cn-ink` | 主文字色 |
| `--dim` | `--cn-ink-light` | 次要文字 |
| `--red` | `--cn-red` | 红色强调 |
| `--blue` | `--cn-gold` | 蓝色强调（主题中映射为金色） |

### 3. 主题选择器 HTML

```html
<select id="themeSelect">
  <option value="red">朱砂红</option>
  <option value="default">简约配色</option>
  <option value="kokomi">珊瑚宫心海</option>
  <option value="firefly">流萤·萨姆</option>
  <option value="furina">芙宁娜·歌剧院</option>
  <option value="hysilens">海瑟音·深境</option>
  <option value="geniusclub">天才俱乐部</option>
  <option value="silverwolf">狼尊 LV.999</option>
  <option value="odette">奥黛塔·月夜羽翼</option>
</select>
```

### 4. JavaScript

```js
const THEMES = ['red', 'default', 'kokomi', 'firefly', 'furina', 'hysilens', 'geniusclub', 'silverwolf', 'odette'];
const INFO_PORT = 5001;

function getInfoServerUrl() {
  return 'http://' + (window.location.hostname || '127.0.0.1') + ':' + INFO_PORT;
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('themeSelect').value = theme;
}

async function setTheme(theme) {
  applyTheme(theme);
  localStorage.setItem('myapp_theme', theme);
  // 同步到 infoServer 服务端（同一 IP 的所有页面共享）
  await fetch(getInfoServerUrl() + '/api/theme', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme })
  }).catch(() => {});
}

async function restoreTheme() {
  // 优先从服务端获取（同一用户跨页面同步）
  try {
    const r = await fetch(getInfoServerUrl() + '/api/theme');
    const data = await r.json();
    if (data.theme && THEMES.includes(data.theme)) {
      applyTheme(data.theme);
      localStorage.setItem('myapp_theme', data.theme);
      return;
    }
  } catch (_) {}
  // 降级到本地缓存
  const saved = localStorage.getItem('myapp_theme');
  if (saved && THEMES.includes(saved)) {
    applyTheme(saved);
  }
}

document.getElementById('themeSelect').addEventListener('change', function() {
  setTheme(this.value);
});
restoreTheme();
```

## 完整参考实现

`serviceGroup/statisticServer/static/index.html` — 搜索 "Theme switching" 注释处。

## 皮肤三部分规范（2026-08-28 起）

每个皮肤固定拆成三部分，由 `skin-manifest.js` 统一登记：

| 部分 | 内容 | 载体 |
|---|---|---|
| 1. 背景图及资源 | 每个主题的背景图 + 叠加层 | `static/skin-manifest.js` 的 `bg` 字段；`/style/<theme>/` 图片 |
| 2. CSS 样式 | 按钮、分割线、进度条、滚动条、高亮等共享组件规则 | `static/style.css` 的 `--cn-*` 变量 + `skin-runner.js` 注入的 `skin-components-css` |
| 3. Shader | 全屏特殊效果；普通主题用 `generic.glsl`（主题色驱动），silverwolf 保留专属 shader | `static/shaders/generic.glsl` + `static/shaders/<theme>.glsl` |

### 统一应用器

- `static/skin-runner.js`：页面加载 manifest + shader-runner + skin-runner 后，自动应用三部分。
- Castflow 通过 postMessage 下发统一皮肤消息：

```js
{ type: 'cf-skin', theme: 'odette', bgOpacity: 0.85 }
```

- 兼容旧消息：`cf-theme`、`cf-bg-opacity`。
- 页面需要共享组件 CSS 时，在 `<body data-skin-components="1">` 开启。

### 接入新页面

```html
<script src="http://localhost:5001/static/skin-manifest.js"></script>
<script src="http://localhost:5001/static/shader-runner.js"></script>
<script src="http://localhost:5001/static/skin-runner.js"></script>
```

WebReader 已接入；statisticServer/debugRelay 已接入 shader/背景/透明度。

## 注意事项

- **CORS**：infoServer（端口 5001）已配置 `CORSMiddleware(allow_origins=["*"])`，不同端口的子服务页面可直接调用其 API
- **localStorage key**：各子服务用不同前缀（如 `stats_theme`），避免冲突
- **服务端 API**：`GET /api/theme` 和 `POST /api/theme` 基于请求 IP 存储主题，同一局域网的设备各自独立
- **背景图片**：如果主题定义了背景图（如 kokomi、firefly），CSS 中的 `url()` 指向 infoServer 的 `/style/` 路径，需确保 infoServer 运行中
