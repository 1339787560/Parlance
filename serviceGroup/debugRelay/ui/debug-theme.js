// debug-theme.js — 主题系统接入 (同 statisticServer 模式, 见 docs/theme-integration.md)
//
// 调色板: debug-ui.css 内嵌 html[data-theme="xxx"] 块 (与 parlanceChat 调色板同源)
// 状态同步: infoServer (:5001) /api/theme — 同 IP 跨子服务共享使用状态
// 背景图: infoServer /style/<theme>/ — 不引全量 style.css 避免布局污染 (np-reader 范本)
// localStorage key 用 debugrel_ 前缀, 避免与其他子服务冲突

const DEBUG_THEMES = ['red', 'default', 'kokomi', 'firefly', 'furina', 'hysilens', 'geniusclub', 'silverwolf'];

function cfThemeValue(t) { return DEBUG_THEMES.includes(t) ? t : (t === 'dark' ? 'hysilens' : 'default'); }

const DEBUG_THEME_WALLPAPERS = {
  kokomi:     { img: '/style/kokomi/kokomi.png',         overlay: 'linear-gradient(135deg, rgba(225,240,255,.55), rgba(252,232,240,.55))' },
  firefly:    { img: '/style/firefly/firefly.png',        overlay: 'linear-gradient(135deg, rgba(229,243,241,.55), rgba(236,233,242,.55), rgba(245,235,240,.55))' },
  furina:     { img: '/style/furina/furina.png',          overlay: 'radial-gradient(circle 900px at top center, rgba(255,235,190,.15) 0%, rgba(255,250,230,.03) 50%, rgba(18,11,11,.7) 100%), linear-gradient(135deg, rgba(18,11,11,.45), rgba(18,11,11,.25))' },
  hysilens:   { img: '/style/Hysilens/Hysilens.jpg',      overlay: 'radial-gradient(ellipse 80% 35% at 50% 0%, rgba(112,195,252,.12) 0%, transparent 70%), radial-gradient(ellipse 40% 30% at 10% 100%, rgba(209,46,107,.10) 0%, transparent 70%), linear-gradient(135deg, rgba(14,24,38,.4), rgba(45,15,63,.3), rgba(21,42,66,.4))' },
  geniusclub: { img: '/style/geniusclub/geniusclub.png',  overlay: 'radial-gradient(ellipse 70% 40% at 50% 0%, rgba(138,79,255,.08) 0%, transparent 70%), radial-gradient(ellipse 40% 25% at 80% 100%, rgba(229,193,123,.06) 0%, transparent 60%), linear-gradient(135deg, rgba(15,18,31,.5), rgba(34,18,48,.4))' },
  silverwolf: { img: '/style/silverwolf/silverwolf.png',  overlay: 'linear-gradient(#070312, rgba(7,3,18,.4))' },
};

const SERVICE_NAME = 'debugRelay';
let _sharedMode = null;

async function getSharedMode() {
  // 查 infoServer 共享开关; enabled=false 或本服务在 exclude → 纯本地主题 (localStorage)
  if (_sharedMode !== null) return _sharedMode;
  try {
    const r = await fetch(getInfoServerUrl() + '/api/theme/config');
    const cfg = await r.json();
    _sharedMode = cfg.enabled !== false && !(cfg.exclude || []).includes(SERVICE_NAME);
  } catch (_) { _sharedMode = false; }  // infoServer 离线 = 纯本地
  return _sharedMode;
}

function getInfoServerUrl() {
  return 'http://' + (window.location.hostname || '127.0.0.1') + ':5001';
}

function applyTheme(theme) {
  const sel = document.getElementById('themeSelect');
  if (!theme) {
    // 空值 = 深色默认 (debug-ui.css :root 兜底); 清 data-theme + 背景图露底色
    document.documentElement.removeAttribute('data-theme');
    document.body.style.backgroundImage = 'none';
    document.body.style.backgroundSize = '';
    document.body.style.backgroundAttachment = '';
    if (sel) sel.value = '';
    return;
  }
  document.documentElement.setAttribute('data-theme', theme);
  if (sel) sel.value = theme;

  // 背景图交给 body::before 伪元素渲染，透明度由 --theme-bg-opacity 控制
  const wp = DEBUG_THEME_WALLPAPERS[theme];
  if (wp) {
    const url = `${getInfoServerUrl()}${wp.img}`;
    document.documentElement.style.setProperty('--theme-bg-image', `${wp.overlay}, url(${url})`);
    document.body.style.background = 'transparent'; // 让 body::before 背景图透出
  } else {
    document.documentElement.style.setProperty('--theme-bg-image', 'none');
    document.body.style.background = ''; // 恢复 CSS 纯色背景
  }
  document.body.style.backgroundImage = 'none';
  document.body.style.backgroundSize = '';
  document.body.style.backgroundAttachment = '';
}

async function syncThemeToServer(theme) {
  try {
    await fetch(getInfoServerUrl() + '/api/theme', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: theme || '' })
    });
  } catch (_) { /* infoServer offline, local-only */ }
}

async function setTheme(theme) {
  applyTheme(theme);
  localStorage.setItem('debugrel_theme', theme || '');
  if (await getSharedMode()) await syncThemeToServer(theme);
}

async function restoreTheme() {
  // Castflow embed：直接采用宿主主题，不走本地/服务端历史覆盖
  if (new URLSearchParams(location.search).has('embed')) {
    const q = new URLSearchParams(location.search).get('theme');
    if (q) {
      await setTheme(cfThemeValue(q));
      return;
    }
  }
  if (await getSharedMode()) {
    // 共享: 优先 infoServer (同 IP 跨子服务同步)
    try {
      const r = await fetch(getInfoServerUrl() + '/api/theme');
      const data = await r.json();
      const t = data.theme;
      if (t && DEBUG_THEMES.includes(t)) {
        applyTheme(t);
        localStorage.setItem('debugrel_theme', t);
        return;
      }
    } catch (_) { /* infoServer unreachable */ }
  }
  // 纯本地 (共享关 / 本服务 excluded / 无记录) → 缓存 → 深色默认
  const saved = localStorage.getItem('debugrel_theme');
  if (saved && DEBUG_THEMES.includes(saved)) {
    applyTheme(saved);
  } else {
    applyTheme('');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const sel = document.getElementById('themeSelect');
  if (sel) {
    sel.addEventListener('change', () => setTheme(sel.value));
  }
  restoreTheme();
});

// Castflow embed mode：隐藏主题选择器，跟随宿主整体样式
// debug-theme.js 在 body 末尾加载，DOM 已就绪，直接执行（不依赖 DOMContentLoaded）
const debugEmbed = new URLSearchParams(location.search).has('embed');
if (debugEmbed) {
  const sel = document.getElementById('themeSelect');
  if (sel) sel.style.display = 'none';
  const q = new URLSearchParams(location.search).get('theme');
  if (q) setTheme(cfThemeValue(q));
}
window.addEventListener('message', (ev) => {
  if (ev.data && ev.data.type === 'cf-theme') {
    setTheme(cfThemeValue(ev.data.value));
  } else if (ev.data && ev.data.type === 'cf-bg-opacity') {
    const op = Math.max(0, Math.min(1, Number(ev.data.value) || 0));
    document.documentElement.style.setProperty('--theme-bg-opacity', String(op));
  }
});
