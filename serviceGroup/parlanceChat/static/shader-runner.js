/**
 * ShaderRunner — 全息背景着色器引擎
 *
 * 职责:
 *   1. 创建全屏 canvas (z-index 底层, pointer-events:none)
 *   2. 按当前主题加载对应的 GLSL 片元着色器
 *   3. requestAnimationFrame 驱动 (传入 u_time / u_resolution)
 *   4. 主题切换时热替换着色器
 *
 * 使用:
 *   const runner = new ShaderRunner();
 *   runner.setTheme('silverwolf'); // fetch → compile → animate
 *   runner.setTheme('default');    // → 隐藏 canvas
 *
 * GLSL 约定:
 *   - precision highp float;
 *   - uniform float u_time;
 *   - uniform vec2  u_resolution;
 *   - void main() { gl_FragColor = vec4(...); }
 */

(function () {
  'use strict';

  // ── 简单顶点着色器 (全屏 quad) ─────────────────────────────
  const VS_SRC = [
    'attribute vec2 a_position;',
    'void main() {',
    '  gl_Position = vec4(a_position, 0.0, 1.0);',
    '}',
  ].join('\n');

  // ── 默认"无效果"着色器 (纯透明黑) ──────────────────────────
  const NULL_FS_SRC = [
    'precision highp float;',
    'void main() {',
    '  gl_FragColor = vec4(0.0, 0.0, 0.0, 0.0);',
    '}',
  ].join('\n');

  // ── 着色器缓存 ─────────────────────────────────────────────
  const shaderCache = {};

  // ── 工具: 编译着色器 ───────────────────────────────────────
  function compileShader(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(s);
      gl.deleteShader(s);
      throw new Error('Shader compile error: ' + log);
    }
    return s;
  }

  function createProgram(gl, vsSrc, fsSrc) {
    const vs = compileShader(gl, gl.VERTEX_SHADER, vsSrc);
    const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSrc);
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      const log = gl.getProgramInfoLog(prog);
      gl.deleteProgram(prog);
      throw new Error('Program link error: ' + log);
    }
    return prog;
  }

  // ── 工具: 提取 uniform 位置 ────────────────────────────────
  function getLocations(gl, prog) {
    return {
      u_time: gl.getUniformLocation(prog, 'u_time'),
      u_resolution: gl.getUniformLocation(prog, 'u_resolution'),
      a_position: gl.getAttribLocation(prog, 'a_position'),
    };
  }

  // ── GLSL 文件 URL (按主题) ─────────────────────────────────
  function shaderUrl(theme) {
    // 无对应着色器的主题 → null
    const themed = ['silverwolf'];
    if (!themed.includes(theme)) return null;
    return '/static/shaders/' + theme + '.glsl';
  }

  // ── 主类 ───────────────────────────────────────────────────
  window.ShaderRunner = function () {
    // 状态
    const self = this;
    let canvas = null;
    let gl = null;
    let program = null;
    let loc = null;
    let animId = null;
    let active = false;
    let currentTheme = 'default';

    // DOM 准备就绪后初始化 canvas
    function ensureCanvas() {
      if (canvas) return;
      canvas = document.createElement('canvas');
      canvas.id = 'shaderCanvas';
      canvas.style.cssText =
        'position:fixed;top:0;left:0;width:100%;height:100%;' +
        'z-index:-1;pointer-events:none;display:block;';
      document.body.insertBefore(canvas, document.body.firstChild);

      // WebGL 2 → WebGL 1 回退
      const opts = { alpha: true, antialias: false, premultipliedAlpha: false };
      gl =
        canvas.getContext('webgl2', opts) ||
        canvas.getContext('webgl', opts) ||
        canvas.getContext('experimental-webgl', opts);
      if (!gl) {
        console.warn('[ShaderRunner] WebGL not available');
        canvas.style.display = 'none';
        canvas = null;
        return false;
      }
      return true;
    }

    // 调整 canvas 尺寸
    function resize() {
      if (!canvas || !gl) return;
      const dpr = 1; // 保持 1x 省电
      const w = window.innerWidth;
      const h = window.innerHeight;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        gl.viewport(0, 0, canvas.width, canvas.height);
      }
    }

    // 加载并编译着色器
    function loadShader(theme) {
      const url = shaderUrl(theme);
      if (!url) {
        // 无对应着色器 → 隐藏 canvas
        if (canvas) canvas.style.display = 'none';
        stop();
        return Promise.resolve();
      }

      // 缓存命中
      if (shaderCache[url]) {
        applyShader(shaderCache[url]);
        return Promise.resolve();
      }

      return fetch(url)
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.text();
        })
        .then(function (src) {
          shaderCache[url] = src;
          applyShader(src);
        })
        .catch(function (err) {
          console.warn('[ShaderRunner] Failed to load ' + url, err);
          stop();
        });
    }

    // 编译并应用着色器源码
    function applyShader(fsSrc) {
      if (!gl) return;
      try {
        if (program) {
          gl.deleteProgram(program);
          program = null;
        }
        program = createProgram(gl, VS_SRC, fsSrc);
        loc = getLocations(gl, program);

        // 全屏 quad (两个三角形)
        const positions = new Float32Array([
          -1, -1,
          1, -1,
          -1, 1,
          -1, 1,
          1, -1,
          1, 1,
        ]);
        const buf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
        gl.enableVertexAttribArray(loc.a_position);
        gl.vertexAttribPointer(loc.a_position, 2, gl.FLOAT, false, 0, 0);

        canvas.style.display = 'block';
        resize();
        start();
      } catch (e) {
        console.warn('[ShaderRunner] Shader error:', e);
        stop();
      }
    }

    // 渲染循环
    function render(now) {
      if (!active || !gl || !program || !loc) return;
      resize();

      gl.useProgram(program);
      gl.uniform1f(loc.u_time, now / 1000);
      gl.uniform2f(
        loc.u_resolution,
        canvas ? canvas.width : 1,
        canvas ? canvas.height : 1
      );

      gl.drawArrays(gl.TRIANGLES, 0, 6);

      animId = requestAnimationFrame(render);
    }

    function start() {
      if (active) return;
      active = true;
      animId = requestAnimationFrame(render);
    }

    function stop() {
      active = false;
      if (animId !== null) {
        cancelAnimationFrame(animId);
        animId = null;
      }
    }

    // ── 公开 API ─────────────────────────────────────────────
    self.setTheme = function (theme) {
      if (theme === currentTheme) return;
      currentTheme = theme || 'default';

      if (!ensureCanvas()) return;

      // 清理旧着色器输出
      if (gl) {
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT);
      }

      loadShader(currentTheme);
    };

    // 清理
    self.dispose = function () {
      stop();
      if (gl && program) gl.deleteProgram(program);
      if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
      canvas = gl = program = loc = null;
    };

    // 页面可见性 → 暂停/恢复
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        stop();
      } else if (currentTheme && shaderUrl(currentTheme)) {
        start();
      }
    });

    // 延迟初始化: 等 body 存在
    if (document.body) {
      ensureCanvas();
    } else {
      document.addEventListener('DOMContentLoaded', ensureCanvas);
    }
  };
})();
