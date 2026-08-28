/**
 * skin-runner.js — 统一皮肤应用器
 *
 * 每个皮肤三部分统一在这里落地：
 *   1. bg     背景图 + 叠加层 + 透明度（--theme-bg-image / --theme-bg-opacity）
 *   2. css    共享组件样式（按钮/分割线/进度条/滚动条/高亮），页面 body 加 data-skin-components="1" 启用
 *   3. shader 全屏 GLSL 特效（ShaderRunner + skin-manifest）
 *
 * 消息协议（父窗口 Castflow 下发）：
 *   { type: 'cf-skin', theme: 'odette', bgOpacity: 0.85 }
 *
 * 兼容旧消息：
 *   { type: 'cf-theme', value: 'odette' }
 *   { type: 'cf-bg-opacity', value: 0.85 }
 *
 * 使用：页面先加载 skin-manifest.js 和 shader-runner.js，再加载本文件。
 */
(function () {
  'use strict';

  var MANIFEST = window.SKIN_MANIFEST || {};
  var BASE = (function () {
    try {
      if (window.location.port === '5001') return window.location.origin;
    } catch (e) {}
    return 'http://localhost:5001';
  })();

  var shaderRunner = null;
  var currentTheme = null;
  var currentOpacity = 1;

  function clampOp(v) {
    var n = Number(v);
    return isFinite(n) ? Math.max(0, Math.min(1, n)) : 1;
  }

  function getSkin(theme) {
    return MANIFEST[theme] || null;
  }

  function bgValue(skin) {
    if (!skin || !skin.bg || !skin.bg.image) return 'none';
    var overlay = skin.bg.overlay ? skin.bg.overlay + ', ' : '';
    return overlay + 'url("' + BASE + skin.bg.image + '")';
  }

  // 背景层基础规则
  function ensureBgStyle() {
    if (document.getElementById('skin-bg-style')) return;
    var style = document.createElement('style');
    style.id = 'skin-bg-style';
    style.textContent = [
      'html[data-theme] { background-color: var(--bg, var(--cn-paper, #1e1e1e)); }',
      'html[data-theme] body { background: transparent; }',
      'html[data-theme] body::before {',
      '  content: "";',
      '  position: fixed;',
      '  inset: 0;',
      '  z-index: -1;',
      '  background-image: var(--theme-bg-image, none);',
      '  background-size: cover;',
      '  background-attachment: fixed;',
      '  opacity: var(--theme-bg-opacity, 1);',
      '  pointer-events: none;',
      '}',
    ].join('\n');
    (document.head || document.documentElement).appendChild(style);
  }

  // 共享组件 CSS：按钮 / 分割线 / 进度条 / 滚动条 / 高亮
  function ensureComponentsCss() {
    if (!document.body || document.body.getAttribute('data-skin-components') !== '1') return;
    if (document.getElementById('skin-components-css')) return;
    var style = document.createElement('style');
    style.id = 'skin-components-css';
    style.textContent = [
      '/* 共享皮肤组件规则：由 skin-runner 注入，仅对 data-skin-components 页面生效 */',
      '[data-skin-components] button,',
      '[data-skin-components] .btn {',
      '  border: 1px solid var(--cn-wood, var(--border, rgba(128,128,128,.3)));',
      '  background: var(--cn-bubble, var(--bg-sidebar, transparent));',
      '  color: var(--cn-ink, var(--fg, inherit));',
      '  border-radius: 4px;',
      '}',
      '[data-skin-components] button:hover,',
      '[data-skin-components] .btn:hover {',
      '  background: var(--cn-red-light, var(--bg-hover, rgba(128,128,128,.15)));',
      '  border-color: var(--cn-red, var(--accent, currentColor));',
      '  color: var(--cn-ink, var(--fg-bright, inherit));',
      '}',
      '[data-skin-components] button:disabled { opacity: .4; cursor: not-allowed; }',
      '',
      '/* 分割线 */',
      '[data-skin-components] hr,',
      '[data-skin-components] .separator,',
      '[data-skin-components] .divider {',
      '  border-color: var(--cn-wood, var(--border, rgba(128,128,128,.2)));',
      '}',
      '',
      '/* 进度条 */',
      '[data-skin-components] .progress,',
      '[data-skin-components] progress,',
      '[data-skin-components] .progress-bar {',
      '  background: var(--cn-wood, rgba(128,128,128,.2));',
      '}',
      '[data-skin-components] .progress-fill,',
      '[data-skin-components] progress::-webkit-progress-value,',
      '[data-skin-components] .progress-bar > div {',
      '  background: linear-gradient(90deg, var(--cn-red, var(--accent)), var(--cn-gold, var(--accent-bright)));',
      '}',
      '',
      '/* 滚动条 */',
      '[data-skin-components] ::-webkit-scrollbar { width: 10px; height: 10px; }',
      '[data-skin-components] ::-webkit-scrollbar-track { background: transparent; }',
      '[data-skin-components] ::-webkit-scrollbar-thumb {',
      '  background: var(--cn-wood, var(--scroll-thumb, rgba(128,128,128,.5)));',
      '  border-radius: 5px;',
      '  border: 2px solid transparent;',
      '  background-clip: content-box;',
      '}',
      '[data-skin-components] ::-webkit-scrollbar-thumb:hover {',
      '  background: var(--cn-ink-faint, var(--scroll-thumb-hover, rgba(128,128,128,.8)));',
      '  background-clip: content-box;',
      '}',
      '',
      '/* 高亮 / 激活 */',
      '[data-skin-components] a { color: var(--cn-red, var(--accent)); }',
      '[data-skin-components] .active,',
      '[data-skin-components] .selected,',
      '[data-skin-components] .tree-node.active,',
      '[data-skin-components] .tab.active,',
      '[data-skin-components] .outline-item.active,',
      '[data-skin-components] .history-item.active {',
      '  background: var(--cn-red-light, var(--bg-active, rgba(0,0,0,.08)));',
      '  border-color: var(--cn-red, var(--accent));',
      '  color: var(--cn-ink, var(--fg-bright));',
      '}',
    ].join('\n');
    (document.head || document.documentElement).appendChild(style);
  }

  function applyShader(theme) {
    if (!window.ShaderRunner) return;
    if (!shaderRunner) shaderRunner = new window.ShaderRunner();
    var skin = getSkin(theme);
    shaderRunner.setTheme(theme, skin ? skin.colors : null);
  }

  function applySkin(theme, opacity) {
    if (!theme) return;
    currentTheme = theme;
    currentOpacity = clampOp(opacity);
    document.documentElement.dataset.theme = theme;

    var skin = getSkin(theme);
    document.documentElement.style.setProperty('--theme-bg-image', bgValue(skin));
    document.documentElement.style.setProperty('--theme-bg-opacity', String(currentOpacity));
    // WebReader 等页面用自己的表面透明度变量，跟随同一份 bgOpacity
    document.documentElement.style.setProperty('--reader-bg-opacity', String(currentOpacity));

    ensureBgStyle();
    ensureComponentsCss();
    applyShader(theme);
  }

  function applyOpacity(opacity) {
    currentOpacity = clampOp(opacity);
    if (currentTheme) {
      document.documentElement.style.setProperty('--theme-bg-opacity', String(currentOpacity));
      document.documentElement.style.setProperty('--reader-bg-opacity', String(currentOpacity));
    }
  }

  // 父窗口消息
  window.addEventListener('message', function (ev) {
    var d = ev.data;
    if (!d || typeof d !== 'object' || !d.type) return;
    if (d.type === 'cf-skin') {
      applySkin(d.theme, d.bgOpacity);
    } else if (d.type === 'cf-theme') {
      applySkin(d.value, currentOpacity);
    } else if (d.type === 'cf-bg-opacity') {
      applyOpacity(d.value);
    }
  });

  // 首次加载：URL 参数 / 已设置的 data-theme
  function init() {
    var params = new URLSearchParams(window.location.search);
    currentOpacity = clampOp(params.get('bg_opacity'));
    var theme = params.get('theme') || document.documentElement.dataset.theme || 'dark';
    if (getSkin(theme) || theme === 'dark' || theme === 'light') {
      applySkin(theme, currentOpacity);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
