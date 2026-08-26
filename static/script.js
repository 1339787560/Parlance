(function() {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────
  const MSG_API = '/api/messages';
  const UPLOAD_API = '/api/upload';
  const EVT_API = '/api/events';
  const DL_API = '/api/download';
  const NEW_UPLOAD_ID = 'new';
  let selectedFiles = [];
  let loadingHistory = false;
  let allLoaded = false;

  // ── DOM refs ────────────────────────────────────────────────────────────
  const msgArea = document.getElementById('msgArea');
  const msgInput = document.getElementById('msgInput');
  const btnSend = document.getElementById('btnSend');
  const themeSelect = document.getElementById('themeSelect');
  const pageTitle = document.getElementById('pageTitle');
  const nameInput = document.getElementById('nameInput');
  const btnSetName = document.getElementById('btnSetName');
  const btnClear = document.getElementById('btnClear');
  const filterSelect = document.getElementById('filterSelect');
  let currentFilter = '';
  const messageCache = {};  // id -> original msg data for rerender
  const zipName = document.getElementById('zipName');
  const dropZone = document.getElementById('dropZone');
  const fileList = document.getElementById('fileList');
  const btnZipCancel = document.getElementById('btnZipCancel');
  const btnDirectUpload = document.getElementById('btnDirectUpload');
  const btnZipUpload = document.getElementById('btnZipUpload');
  const zipFileInput = document.getElementById('zipFileInput');
  const sseStatus = document.getElementById('sseStatus');
  const serverUrl = document.getElementById('serverUrl');
  const toast = document.getElementById('toast');
  const uploadPanel = document.getElementById('uploadPanel');
  const uploadListEl = document.getElementById('uploadList');
  const uploadDetailEl = document.getElementById('uploadDetail');
  const btnUploadPanel = document.getElementById('btnUploadPanel');
  const uploadBadge = document.getElementById('uploadBadge');
  const btnUploadClose = document.getElementById('btnUploadClose');
  const btnSpeedTest = document.getElementById('btnSpeedTest');
  const speedTestResult = document.getElementById('speedTestResult');
  const stressTestResult = document.getElementById('stressTestResult');
  const uploadActionPanel = document.getElementById('uploadActionPanel');
  const resumeFileInput = document.getElementById('resumeFileInput');

  serverUrl.textContent = window.location.host;

  // ── ShaderRunner instance (initialized on first set/restore) ──────────
  let shaderRunner = null;

  // ── Helpers ────────────────────────────────────────────────────────────
  function formatTime(t) {
    if (!t) return '';
    const d = new Date(t.replace(' ', 'T'));
    if (isNaN(d.getTime())) return t;
    return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
  }

  function formatSize(bytes) {
    if (!bytes || bytes === 0) return '';
    const units = ['B','KB','MB','GB','TB'];
    let i = 0; let s = bytes;
    while (s >= 1024 && i < units.length-1) { s /= 1024; i++; }
    return s.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
  }

  function getMsgClass(selfIp, msgIp) {
    if (!msgIp) return 'other';
    return selfIp === msgIp ? 'self' : 'other';
  }

  function escapeHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function scrollToBottom(smooth) {
    requestAnimationFrame(() => {
      msgArea.scrollTo({ top: msgArea.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    });
  }

  function showToast(msg, duration) {
    toast.textContent = msg;
    toast.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.remove('show'), duration || 2500);
  }

  async function fetchJSON(url, opts) {
    const r = await fetch(url, opts);
    if (!r.ok) { const t = await r.text().catch(() => ''); throw new Error(t || `HTTP ${r.status}`); }
    return r.json();
  }

  function getSelfIp() {
    // Best-effort: use the IP the server sees
    return localStorage.getItem('self_ip') || '';
  }

  function isMobile() {
    return window.matchMedia ? window.matchMedia('(max-width: 600px)').matches : window.innerWidth <= 600;
  }

  function formatDate(t) {
    if (!t) return '';
    const d = new Date(t.replace(' ', 'T'));
    if (isNaN(d.getTime())) return '';
    const today = new Date();
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    if (d.toDateString() === today.toDateString()) return '今日';
    if (d.toDateString() === yesterday.toDateString()) return '昨日';
    return `${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日`;
  }

  let lastRenderedDate = '';

  // ── Render message ─────────────────────────────────────────────────────
  function renderMsg(msg, prepend) {
    // Dedup: skip if already rendered
    if (document.querySelector('[data-id="' + msg.id + '"]')) return;
    const selfIp = getSelfIp();
    const cls = getMsgClass(selfIp, msg.device_ip);
    const div = document.createElement('div');
    div.className = `msg ${cls}`;
    div.dataset.id = msg.id;
    div.dataset.ip = msg.device_ip;

    let icon = '';
    let bodyHtml = '';

    switch (msg.message_type) {
      case 'text':
        bodyHtml = `<div class="msg-content">${escapeHtml(msg.content)}</div>`;
        break;
      case 'file':
        icon = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><rect x="4" y="3" width="16" height="18" rx="1"/><line x1="8" y1="8" x2="16" y2="8"/><line x1="8" y1="12" x2="14" y2="12"/><line x1="8" y1="16" x2="15" y2="16"/></svg>';
        let previewHtml = '';
        const _mime = (msg.file_mime || '').toLowerCase();
        if (_mime.startsWith('image/')) {
          previewHtml = `<div class="msg-preview-wrap"><img class="msg-preview" src="/api/download/${msg.id}" alt="${escapeHtml(msg.file_name)}" loading="lazy"></div>`;
        } else if (_mime.startsWith('video/')) {
          previewHtml = `<div class="msg-preview-wrap"><video class="msg-preview" src="/api/download/${msg.id}" controls preload="metadata"></video></div>`;
        }
        bodyHtml = `
          <div class="msg-file">
            <span class="msg-file-icon">${icon}</span>
            <div class="msg-file-info">
              <div class="msg-file-name">${escapeHtml(msg.file_name)}</div>
              <div class="msg-file-size">${formatSize(msg.file_size)}</div>
            </div>
            <button class="btn-download" data-id="${msg.id}">下载</button>
          </div>
          ${previewHtml}`;
        break;
      case 'zip':
        icon = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><rect x="3" y="7" width="18" height="14" rx="1"/><path d="M3 7 L5 4 L19 4 L21 7"/><line x1="12" y1="4" x2="12" y2="7"/><circle cx="12" cy="14" r="2"/></svg>';
        bodyHtml = `
          <div class="msg-file">
            <span class="msg-file-icon">${icon}</span>
            <div class="msg-file-info">
              <div class="msg-file-name">${escapeHtml(msg.file_name)}</div>
              <div class="msg-file-size">${formatSize(msg.file_size)} · ${escapeHtml(msg.content || '')}</div>
            </div>
            <button class="btn-download" data-id="${msg.id}">下载</button>
          </div>`;
        break;
      case 'batch_files':
        icon = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M2 7 L22 7"/><rect x="2" y="4" width="20" height="16" rx="1"/><path d="M9 11 L15 11"/><path d="M9 15 L13 15"/></svg>';
        bodyHtml = `
          <div class="msg-file">
            <span class="msg-file-icon">${icon}</span>
            <div class="msg-file-info">
              <div class="msg-file-name">${escapeHtml(msg.file_name)}</div>
              <div class="msg-file-size">${formatSize(msg.file_size)}</div>
            </div>
            <button class="btn-download" data-id="${msg.id}" data-batch="1">下载</button>
          </div>`;
        break;
      default:
        bodyHtml = `<div class="msg-content">${escapeHtml(msg.content)}</div>`;
    }

    messageCache[msg.id] = msg;
    const showName = localStorage.getItem('show_name') !== 'false';
    const displayName = profileCache[msg.device_ip] || '';
    const displayText = showName && displayName ? escapeHtml(displayName) : escapeHtml(msg.device_ip);
    const isSelf = selfIp === msg.device_ip;
    div.innerHTML = `
      <div class="msg-header">
        <span class="msg-ip clickable" data-ip="${escapeHtml(msg.device_ip)}" title="点击筛选此人">${displayText}</span>
        <span class="msg-time">${formatTime(msg.created_at)}</span>
      </div>
      ${isSelf ? '<button class="btn-recall" data-id="' + msg.id + '" title="撤回">\u2716</button>' : ''}
      ${bodyHtml}`;
    // Recall handler
    const recallBtn = div.querySelector('.btn-recall');
    if (recallBtn) {
      recallBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('撤回这条消息？')) return;
        try {
          await fetch('/api/messages/' + msg.id, { method: 'DELETE' });
        } catch (_) { showToast('撤回失败'); }
      });
    }
    // Click IP to toggle name/IP display
    const ipSpan = div.querySelector('.msg-ip');
    ipSpan.addEventListener('click', () => {
      const cur = localStorage.getItem('show_name');
      localStorage.setItem('show_name', cur === 'false' ? 'true' : 'false');
      showToast('已切换为: ' + (cur === 'false' ? '昵称' : 'IP地址'));
      rerenderMessages();
    });

    // Download handler (regular files + batch files, distinguished by data-batch)
    div.querySelector('.btn-download')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      if (btn.dataset.batch) {
        downloadBatch(msg.id, msg.file_name);
      } else {
        downloadFile(msg.id, msg.file_name);
      }
    });

    // Auto-scroll when image/video preview loads (appended msgs only)
    const _preview = div.querySelector('.msg-preview');
    if (_preview && !prepend) {
      const onMediaLoad = () => scrollToBottom(false);
      if (_preview.tagName === 'IMG') {
        _preview.addEventListener('load', onMediaLoad);
        if (_preview.complete) onMediaLoad();
      } else if (_preview.tagName === 'VIDEO') {
        _preview.addEventListener('loadedmetadata', onMediaLoad);
      }
    }

    if (prepend) {
      msgArea.insertBefore(div, msgArea.firstChild);
    } else {
      // Insert date separator if day changed
      const msgDate = formatDate(msg.created_at);
      if (msgDate && msgDate !== lastRenderedDate) {
        const sep = document.createElement('div');
        sep.className = 'date-sep';
        sep.innerHTML = `<span>${escapeHtml(msgDate)}</span>`;
        msgArea.appendChild(sep);
        lastRenderedDate = msgDate;
      }
      msgArea.appendChild(div);
    }
    return div;
  }

  // ── Resumable download ─────────────────────────────────────────────────
  function downloadFile(msgId, filename) {
    // Use backend streaming with Range support — browser handles resume natively
    const a = document.createElement('a');
    a.href = `${DL_API}/${msgId}`;
    a.download = filename || 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function downloadBatch(msgId, filename) {
    const a = document.createElement('a');
    a.href = '/api/download-batch/' + msgId;
    a.download = (filename || 'batch') + '.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // ── Load messages ──────────────────────────────────────────────────────
  async function loadMessages(beforeId) {
    if (loadingHistory || allLoaded) return;
    loadingHistory = true;

    try {
      const params = new URLSearchParams({ limit: '50' });
      if (beforeId) params.set('before_id', beforeId);
      const msgs = await fetchJSON(`${MSG_API}?${params}`);

      const loadingEl = document.getElementById('loadingMsg');
      if (loadingEl) loadingEl.remove();

      if (msgs.length === 0) {
        allLoaded = true;
        return;
      }

      if (beforeId) {
        // History load: iterate newest-first so prepend keeps ascending order
        for (let i = msgs.length - 1; i >= 0; i--) {
          renderMsg(msgs[i], true);
        }
        // Keep scroll position near top for history loading
        const firstNew = msgArea.querySelector('[data-id]');
        if (firstNew) firstNew.scrollIntoView({ block: 'start' });
      } else {
        // Initial load: append in ascending order (oldest → newest), no animation
        for (const msg of msgs) {
          renderMsg(msg, false);
        }
        scrollToBottom(false);
      }
    } catch (e) {
      console.error('Failed to load messages:', e);
      showToast('加载消息失败');
    } finally {
      loadingHistory = false;
    }
  }

  // ── Send message ───────────────────────────────────────────────────────
  async function sendText(text) {
    if (!text || !text.trim()) return;
    const payload = JSON.stringify({ content: text.trim(), sender: '' });
    try {
      await fetchJSON(MSG_API + '/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload
      });
      msgInput.value = '';
      msgInput.style.height = 'auto';
    } catch (e) {
      const detail = e.message;
      const match = detail.match(/"msg":"([^"]+)"/);
      showToast('发送失败: ' + (match ? match[1] : detail));
    }
  }

  async function sendFile(file) {
    // Large single file -> chunked parallel path (resumable, tracked in panel)
    if (file.size > CHUNKED_UPLOAD_THRESHOLD) {
      const task = createTask(file);
      if (uploadPanelOpen && selectedUploadId === NEW_UPLOAD_ID) {
        selectedUploadId = task.id;
        renderUploadPanel();
      }
      try {
        const id = await uploadFileChunked(file, task);
        const msg = await fetchJSON(UPLOAD_API + '/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ upload_ids: [id], sender: '' })
        });
        task.loaded = task.size;
        finishTask(task, 'done');
        return msg;
      } catch (e) {
        if (task._paused) {
          saveUploadHistory();
          updateUploadBadge();
          renderUploadPanel();
          return;
        }
        if (task.status === 'cancelled') {
          saveUploadHistory();
          updateUploadBadge();
          renderUploadPanel();
          return;
        }
        finishTask(task, e.message === '上传已取消' ? 'cancelled' : 'error', e.message);
        showToast('上传失败(进度已保留, 重发将续传): ' + e.message);
      }
      return;
    }
    // Small file: single multipart request, tracked with progress
    const task = createTask(file);
    if (uploadPanelOpen && selectedUploadId === NEW_UPLOAD_ID) {
      selectedUploadId = task.id;
      renderUploadPanel();
    }
    try {
      const msg = await uploadSmallFileXHR(task, file);
      task.loaded = task.size;
      finishTask(task, 'done');
      return msg;
    } catch (e) {
      if (task._paused) {
        saveUploadHistory();
        updateUploadBadge();
        renderUploadPanel();
        return;
      }
      if (task.status === 'cancelled') {
        saveUploadHistory();
        updateUploadBadge();
        renderUploadPanel();
        return;
      }
      finishTask(task, e.message === '上传已取消' ? 'cancelled' : 'error', e.message);
      showToast('上传失败: ' + e.message);
    }
  }

  function uploadSmallFileXHR(t, file) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.set('file', file);
      fd.set('sender', '');
      const xhr = new XMLHttpRequest();
      t.xhrs.add(xhr);
      xhr.open('POST', MSG_API + '/file');
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) { t.loaded = e.loaded; schedulePanelRender(); }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText)); } catch (_) { resolve(xhr.responseText); }
        } else {
          let errMsg = 'HTTP ' + xhr.status;
          try { errMsg = JSON.parse(xhr.responseText).detail || errMsg; } catch (_) {}
          reject(new Error(errMsg));
        }
      };
      xhr.onerror = () => reject(new Error('网络错误'));
      xhr.onabort = () => reject(new Error('上传已取消'));
      xhr.timeout = 300000;
      xhr.send(fd);
    });
  }

  // ── Upload progress helpers ──────────────────────────────────────────
  const progressFill = document.getElementById('progressFill');
  const progressInfo = document.getElementById('progressInfo');
  const progressSection = document.getElementById('progressSection');

  function resetProgress() {
    progressFill.style.width = '0%';
    progressInfo.textContent = '';
    modalOp = null;
  }

  function showProgress(show) {
    progressSection.style.display = show ? 'block' : 'none';
  }

  // Modal progress op state: overall-average speed (stable - no EMA jitter
  // from 4 parallel chunk streams each reporting its own instantaneous rate)
  let modalOp = null;  // {start, base}  base = progress counted before this op

  // updateProgress(loaded, total, sent): loaded/total = absolute progress;
  // sent = bytes actually transmitted in THIS op (excludes resume base).
  // Displayed speed = sent / elapsed since op start - an honest overall average.
  function updateProgress(loaded, total, sent) {
    if (!modalOp) modalOp = { start: Date.now(), base: 0 };
    if (sent !== undefined) modalOp.base = loaded - sent;  // resume-aware base
    const elapsed = (Date.now() - modalOp.start) / 1000;
    const speed = elapsed > 0.5 ? Math.max(0, loaded - modalOp.base) / elapsed : 0;

    const pct = total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
    progressFill.style.width = pct + '%';

    const speedStr = speed > 1 ? formatSize(Math.round(speed)) : '';
    let remaining = '';
    if (speed > 1 && pct < 100) {
      const secs = Math.ceil((total - loaded) / speed);
      remaining = secs < 60 ? ' · 剩余 ' + secs + '秒'
        : ' · 剩余 ' + Math.ceil(secs / 60) + '分钟';
    }

    progressInfo.textContent = pct + '% · ' + formatSize(loaded) + ' / ' + formatSize(total)
      + (speedStr ? ' · ' + speedStr + '/s' : '')
      + remaining;
  }

  // ── Chunked parallel + resumable upload ────────────────────────────────
  // ── Upload task registry (upload manager panel) ──────────────────────
  // Every upload (multipart / chunked / zip) creates a task. Transfers keep
  // running regardless of panel/modal visibility; history persists in
  // localStorage capped at 100 entries.
  const uploadTasks = [];
  const UPLOAD_HISTORY_KEY = 'upload_history';
  const UPLOAD_HISTORY_MAX = 100;
  let uploadSeq = 1;
  let selectedUploadId = null;
  let uploadPanelOpen = false;

  function createTask(file, nameOverride) {
    const t = {
      id: uploadSeq++,
      name: nameOverride || file.name || 'unnamed',
      size: file.size || 0,
      loaded: 0,
      sessionBase: 0,     // bytes already on server when this attempt began
      startedAt: Date.now(),
      endedAt: null,
      status: 'uploading',  // uploading | done | error | interrupted | cancelled
      error: '',
      xhrs: new Set(),
      _paused: false,
      _stoppedByUser: false,
      file: file instanceof File ? file : null,
      fingerprint: file instanceof File ? fileFingerprint(file) : null,
      lastModified: (file instanceof File && file.lastModified) || 0,
      resumable: file instanceof File,
    };
    uploadTasks.unshift(t);
    while (uploadTasks.length > UPLOAD_HISTORY_MAX) uploadTasks.pop();
    saveUploadHistory();
    updateUploadBadge();
    updateRealtimeState();
    return t;
  }

  function finishTask(t, status, err) {
    t.status = status;
    t.endedAt = Date.now();
    if (err) t.error = err;
    saveUploadHistory();
    updateUploadBadge();
    renderUploadPanel();
    updateRealtimeState();
  }

  function saveUploadHistory() {
    try {
      const hist = uploadTasks.map(t => ({
        id: t.id, name: t.name, size: t.size, loaded: t.loaded,
        status: t.status, startedAt: t.startedAt, endedAt: t.endedAt,
        fingerprint: t.fingerprint || null, lastModified: t.lastModified || 0,
        resumable: !!t.resumable, uploadId: t.uploadId || null,
      }));
      localStorage.setItem(UPLOAD_HISTORY_KEY, JSON.stringify(hist));
    } catch (_) {}
  }

  function loadUploadHistory() {
    try {
      const hist = JSON.parse(localStorage.getItem(UPLOAD_HISTORY_KEY) || '[]');
      for (const h of hist) {
        // An 'uploading' entry from a previous page died with that page
        if (h.status === 'uploading') h.status = 'interrupted';
        h.xhrs = new Set();
        h.fingerprint = h.fingerprint || null;
        h.lastModified = h.lastModified || 0;
        h.resumable = !!h.resumable;
        h.uploadId = h.uploadId || null;
        uploadTasks.push(h);
      }
      if (hist.length) uploadSeq = Math.max(...hist.map(h => h.id || 0)) + 1;
    } catch (_) {}
  }

  function updateUploadBadge() {
    const n = uploadTasks.filter(t => t.status === 'uploading').length;
    uploadBadge.style.display = n > 0 ? '' : 'none';
    uploadBadge.textContent = n > 99 ? '99+' : String(n);
  }

  function taskSpeed(t) {
    const end = t.endedAt || Date.now();
    const elapsed = (end - t.startedAt) / 1000;
    if (elapsed <= 0.3) return 0;
    return Math.max(0, t.loaded - t.sessionBase) / elapsed;
  }

  function taskStatusText(t) {
    const pct = t.size > 0 ? Math.floor(t.loaded / t.size * 100) : 0;
    switch (t.status) {
      case 'uploading': return '上传中 ' + pct + '%';
      case 'done': return '已完成';
      case 'error': return '失败';
      case 'interrupted': return '已停止';
      case 'cancelled': return '已取消';
    }
    return t.status;
  }

  // Panel rendering (throttled to ~4Hz)
  let panelRenderTimer = null;
  let lastPanelRenderTs = 0;

  function schedulePanelRender() {
    if (!uploadPanelOpen || panelRenderTimer) return;
    const wait = Math.max(0, 250 - (Date.now() - lastPanelRenderTs));
    panelRenderTimer = setTimeout(() => {
      panelRenderTimer = null;
      lastPanelRenderTs = Date.now();
      updateUploadProgress();
    }, wait);
  }

  function renderUploadPanel() {
    if (!uploadPanelOpen) return;
    uploadListEl.innerHTML = '';

    // Top action item: start a new upload (single files or packaged zip).
    const newEl = document.createElement('div');
    newEl.className = 'upload-item upload-item-new' + (selectedUploadId === NEW_UPLOAD_ID ? ' active' : '');
    newEl.innerHTML =
      '<div class="upload-item-name">＋ 上传文件</div>' +
      '<div class="upload-item-meta"><span>单文件 / 打包上传</span></div>';
    newEl.addEventListener('click', () => {
      selectedUploadId = NEW_UPLOAD_ID;
      resetProgress();
      showProgress(false);
      updateZipFileList();
      renderUploadPanel();
    });
    uploadListEl.appendChild(newEl);

    if (!uploadTasks.length) {
      const empty = document.createElement('div');
      empty.className = 'upload-empty';
      empty.textContent = '暂无上传记录';
      uploadListEl.appendChild(empty);
    }
    for (const t of uploadTasks) {
      const pct = t.size > 0 ? Math.min(100, Math.floor(t.loaded / t.size * 100)) : 0;
      const el = document.createElement('div');
      el.className = 'upload-item' + (t.id === selectedUploadId ? ' active' : '');
      el.dataset.id = t.id;
      el.innerHTML =
        '<div class="upload-item-name">' + escapeHtml(t.name) + '</div>' +
        '<div class="upload-item-meta"><span>' + formatSize(t.size) + '</span>' +
        '<span class="s-' + t.status + '">' + taskStatusText(t) + '</span></div>' +
        '<div class="upload-item-bar"><div style="width:' + pct + '%"></div></div>';
      el.addEventListener('click', () => { selectedUploadId = t.id; renderUploadPanel(); });
      uploadListEl.appendChild(el);
    }
    renderUploadDetail();
  }

  function fmtElapsed(sec) {
    sec = Math.max(0, Math.round(sec));
    if (sec < 60) return sec + ' 秒';
    if (sec < 3600) return Math.floor(sec / 60) + ' 分 ' + (sec % 60) + ' 秒';
    return Math.floor(sec / 3600) + ' 时 ' + Math.floor((sec % 3600) / 60) + ' 分';
  }

  function renderUploadDetail() {
    if (selectedUploadId === NEW_UPLOAD_ID) {
      uploadDetailEl.style.display = 'none';
      uploadActionPanel.style.display = 'block';
      btnZipCancel.textContent = '清空';
      updateZipFileList();
      updateButtonState();
      return;
    }

    uploadDetailEl.style.display = 'block';
    uploadActionPanel.style.display = 'none';

    const t = uploadTasks.find(x => x.id === selectedUploadId) || uploadTasks[0];
    if (!t) {
      uploadDetailEl.innerHTML = '<div class="upload-empty">选择左侧文件查看详情</div>';
      return;
    }
    selectedUploadId = t.id;
    const pct = t.size > 0 ? Math.min(100, t.loaded / t.size * 100) : 0;
    const speed = taskSpeed(t);
    const elapsed = ((t.endedAt || Date.now()) - t.startedAt) / 1000;
    let eta = '--';
    if (t.status === 'uploading' && speed > 1) {
      eta = fmtElapsed((t.size - t.loaded) / speed);
    }

    let html =
      '<div class="up-d-name">' + escapeHtml(t.name) + '</div>' +
      '<div class="up-d-status s-' + t.status + '" data-field="status">' + taskStatusText(t) + '</div>' +
      '<div class="up-d-bar"><div data-field="bar" style="width:' + pct + '%"></div></div>' +
      '<div class="up-d-grid">' +
      '<div><label>进度</label><span data-field="progress">' + Math.floor(pct) + '% · ' + formatSize(t.loaded) + ' / ' + formatSize(t.size) + '</span></div>' +
      '<div><label>平均速度</label><span data-field="speed">' + (speed > 1 ? formatSize(Math.round(speed)) + '/s' : '--') + '</span></div>' +
      '<div><label>已用时间</label><span data-field="elapsed">' + fmtElapsed(elapsed) + '</span></div>' +
      '<div><label>预计剩余</label><span data-field="eta">' + (t.status === 'uploading' ? eta : '--') + '</span></div>' +
      '<div><label>开始时间</label><span data-field="started">' + (t.startedAt ? new Date(t.startedAt).toLocaleTimeString() : '--') + '</span></div>' +
      '<div><label>结束时间</label><span data-field="ended">' + (t.endedAt ? new Date(t.endedAt).toLocaleTimeString() : '--') + '</span></div>' +
      '</div>';
    if (t.error) {
      html += '<div class="up-d-error">' + escapeHtml(t.error) + '</div>';
    }
    if (t.status === 'uploading') {
      html += '<div class="up-d-actions">' +
        '<button class="btn-cancel" id="btnTaskPause">停止</button>' +
        '<button class="btn-cancel" id="btnTaskCancel">取消上传</button></div>';
    } else if (['interrupted', 'error', 'cancelled'].includes(t.status) && t.resumable && t.size > 0) {
      html += '<div class="up-d-actions">' +
        '<button class="btn-upload" id="btnTaskResume">' + (t.status === 'cancelled' ? '重新上传' : '恢复上传') + '</button>';
      if (t.status !== 'cancelled') {
        html += '<button class="btn-cancel" id="btnTaskCancel">取消上传</button>';
      }
      html += '</div>';
    }
    html += '<div class="up-d-delete"><button class="btn-cancel" id="btnTaskDelete">删除记录</button></div>';
    uploadDetailEl.innerHTML = html;
    const btnPause = uploadDetailEl.querySelector('#btnTaskPause');
    if (btnPause) btnPause.addEventListener('click', () => pauseTask(t));
    const btnCancel = uploadDetailEl.querySelector('#btnTaskCancel');
    if (btnCancel) btnCancel.addEventListener('click', () => cancelTask(t));
    const btnResume = uploadDetailEl.querySelector('#btnTaskResume');
    if (btnResume) btnResume.addEventListener('click', () => resumeTask(t));
    const btnDelete = uploadDetailEl.querySelector('#btnTaskDelete');
    if (btnDelete) btnDelete.addEventListener('click', () => deleteTask(t));
  }

  function updateUploadProgress() {
    if (!uploadPanelOpen) return;

    // Update only progress-related DOM; never rebuild buttons/list.
    for (const t of uploadTasks) {
      const item = uploadListEl.querySelector('[data-id="' + t.id + '"]');
      if (!item) continue;
      const pct = t.size > 0 ? Math.min(100, Math.floor(t.loaded / t.size * 100)) : 0;
      const bar = item.querySelector('.upload-item-bar > div');
      if (bar) bar.style.width = pct + '%';
      const statusEl = item.querySelector('.upload-item-meta .s-' + t.status);
      if (statusEl) statusEl.textContent = taskStatusText(t);
    }

    if (selectedUploadId === NEW_UPLOAD_ID) return;
    const t = uploadTasks.find(x => x.id === selectedUploadId);
    if (!t) return;

    const pct = t.size > 0 ? Math.min(100, t.loaded / t.size * 100) : 0;
    const speed = taskSpeed(t);
    const elapsed = ((t.endedAt || Date.now()) - t.startedAt) / 1000;
    let eta = '--';
    if (t.status === 'uploading' && speed > 1) {
      eta = fmtElapsed((t.size - t.loaded) / speed);
    }
    const set = (field, text) => {
      const el = uploadDetailEl.querySelector('[data-field="' + field + '"]');
      if (el) el.textContent = text;
    };
    const bar = uploadDetailEl.querySelector('[data-field="bar"]');
    if (bar) bar.style.width = pct + '%';
    set('status', taskStatusText(t));
    set('progress', Math.floor(pct) + '% · ' + formatSize(t.loaded) + ' / ' + formatSize(t.size));
    set('speed', speed > 1 ? formatSize(Math.round(speed)) + '/s' : '--');
    set('elapsed', fmtElapsed(elapsed));
    set('eta', t.status === 'uploading' ? eta : '--');
  }

  async function cancelTask(t) {
    if (t.status === 'done') return;
    t._paused = false;
    t._stoppedByUser = true;
    t.status = 'cancelled';
    t.endedAt = Date.now();
    for (const x of t.xhrs) {
      try { x.abort(); } catch (_) {}
    }
    t.xhrs.clear();
    // True cancel: tell the server to discard the active resumable session.
    if (t.uploadId) {
      try { await fetch(UPLOAD_API + '/' + t.uploadId, { method: 'DELETE' }); } catch (_) {}
      t.uploadId = null;
    }
    saveUploadHistory();
    updateUploadBadge();
    renderUploadPanel();
    updateRealtimeState();
    showToast('已取消: ' + t.name);
  }

  function pauseTask(t) {
    if (t.status !== 'uploading') return;
    t._paused = true;
    t._stoppedByUser = true;
    t.status = 'interrupted';
    t.endedAt = Date.now();
    for (const x of t.xhrs) {
      try { x.abort(); } catch (_) {}
    }
    t.xhrs.clear();
    saveUploadHistory();
    updateUploadBadge();
    renderUploadPanel();
    updateRealtimeState();
    showToast('已停止: ' + t.name + ' (服务端进度保留，可随时恢复)');
  }

  function deleteTask(t) {
    // Cancel first if the task is still uploading, then remove the history entry.
    if (t.status === 'uploading') {
      t._paused = false;
      t._stoppedByUser = true;
      t.status = 'cancelled';
      t.endedAt = Date.now();
      for (const x of t.xhrs) {
        try { x.abort(); } catch (_) {}
      }
      t.xhrs.clear();
    }
    // Discard any active server-side resumable session.
    if (t.uploadId) {
      fetch(UPLOAD_API + '/' + t.uploadId, { method: 'DELETE' }).catch(() => {});
      t.uploadId = null;
    }
    const idx = uploadTasks.indexOf(t);
    if (idx >= 0) uploadTasks.splice(idx, 1);
    if (selectedUploadId === t.id) {
      selectedUploadId = uploadTasks.length ? uploadTasks[0].id : NEW_UPLOAD_ID;
    }
    saveUploadHistory();
    updateUploadBadge();
    renderUploadPanel();
    updateRealtimeState();
    showToast('已删除上传记录: ' + t.name);
  }

  async function resumeTask(t) {
    if (!t || t.status === 'uploading') return;
    if (t.file && t.file.name === t.name && t.file.size === t.size) {
      await uploadTaskWithFile(t, t.file);
      return;
    }
    resumeFileInput._taskId = t.id;
    showToast('请重新选择同名文件以续传: ' + t.name);
    resumeFileInput.click();
  }

  async function uploadTaskWithFile(t, file) {
    t.status = 'uploading';
    t.error = '';
    t.startedAt = Date.now();
    t.endedAt = null;
    t.sessionBase = 0;
    t.xhrs = new Set();
    t._paused = false;
    t._stoppedByUser = false;
    t.file = file;
    t.fingerprint = fileFingerprint(file);
    t.lastModified = file.lastModified || 0;
    t.resumable = true;
    saveUploadHistory();
    updateUploadBadge();
    renderUploadPanel();
    updateRealtimeState();
    try {
      let msg;
      if (file.size > CHUNKED_UPLOAD_THRESHOLD) {
        const id = await uploadFileChunked(file, t);
        msg = await fetchJSON(UPLOAD_API + '/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ upload_ids: [id], sender: '' })
        });
      } else {
        msg = await uploadSmallFileXHR(t, file);
      }
      t.loaded = t.size;
      finishTask(t, 'done');
      return msg;
    } catch (e) {
      if (t._paused) {
        saveUploadHistory();
        updateUploadBadge();
        renderUploadPanel();
        updateRealtimeState();
        return null;
      }
      if (t.status === 'cancelled') {
        saveUploadHistory();
        updateUploadBadge();
        renderUploadPanel();
        updateRealtimeState();
        return null;
      }
      finishTask(t, e.message === '上传已取消' ? 'cancelled' : 'error', e.message);
      showToast('续传失败(进度已保留): ' + e.message);
      return null;
    }
  }

  resumeFileInput.addEventListener('change', async () => {
    const file = resumeFileInput.files[0];
    const t = uploadTasks.find(x => x.id === resumeFileInput._taskId);
    resumeFileInput.value = '';
    if (!file || !t) return;
    const fingerprintOk = !t.fingerprint || fileFingerprint(file) === t.fingerprint;
    if (file.name !== t.name || file.size !== t.size || !fingerprintOk) {
      showToast('文件不匹配，无法续传: ' + t.name);
      return;
    }
    await uploadTaskWithFile(t, file);
  });

  function openUploadPanel(open, focusNew) {
    uploadPanelOpen = open;
    uploadPanel.classList.toggle('open', open);
    if (open) {
      if (focusNew || !uploadTasks.length) {
        selectedUploadId = NEW_UPLOAD_ID;
      } else if (!selectedUploadId || selectedUploadId === NEW_UPLOAD_ID) {
        selectedUploadId = uploadTasks[0].id;
      }
      renderUploadPanel();
    }
    updateRealtimeState();
  }

  btnUploadPanel.addEventListener('click', () => {
    if (uploadPanelOpen) closeUploadModal();
    else openUploadPanel(true, false);
  });
  btnUploadClose.addEventListener('click', closeUploadModal);

  window.addEventListener('beforeunload', saveUploadHistory);
  loadUploadHistory();
  updateUploadBadge();

  // Files larger than this use the chunked parallel/resumable path.
  // Actual transfer chunk size comes from server init.chunk_size (32MB).
  const CHUNKED_UPLOAD_THRESHOLD = 8 * 1024 * 1024;
  const CHUNK_CONCURRENCY = 6;          // parallel TCP streams (browser ~6 conns/origin)
  const CHUNK_RETRY = 3;

  function fileFingerprint(file) {
    return file.name + '|' + file.size + '|' + file.lastModified;
  }

  // CRC32 of a chunk - end-to-end integrity check.
  // 'full'   = every chunk (max reliability)
  // 'sample' = first/middle/last + every 16th chunk
  // 'fast'   = skip client CRC on trusted LAN (server still checks chunk size)
  const CRC_MODE = localStorage.getItem('upload_crc_mode') || 'fast';
  const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
      t[n] = c >>> 0;
    }
    return t;
  })();

  async function crc32HexFallback(blob) {
    const view = new Uint8Array(await blob.arrayBuffer());
    let c = 0xFFFFFFFF;
    for (let i = 0; i < view.length; i++) {
      c = CRC_TABLE[(c ^ view[i]) & 0xFF] ^ (c >>> 8);
    }
    return ((c ^ 0xFFFFFFFF) >>> 0).toString(16).padStart(8, '0');
  }

  let crcWorker = null;
  let crcWorkerSeq = 1;
  const crcWorkerPending = new Map();

  async function crc32Hex(blob) {
    if (window.Worker) {
      try {
        if (!crcWorker) {
          crcWorker = new Worker('/static/crc32-worker.js');
          crcWorker.onmessage = (e) => {
            const p = crcWorkerPending.get(e.data.id);
            if (p) {
              crcWorkerPending.delete(e.data.id);
              p.resolve(e.data.crc);
            }
          };
          crcWorker.onerror = () => {
            for (const [, p] of crcWorkerPending) p.reject(new Error('CRC worker error'));
            crcWorkerPending.clear();
            if (crcWorker) { crcWorker.terminate(); crcWorker = null; }
          };
        }
        const id = crcWorkerSeq++;
        const promise = new Promise((resolve, reject) => crcWorkerPending.set(id, { resolve, reject }));
        const buf = await blob.arrayBuffer();
        crcWorker.postMessage({ id, buffer: buf }, [buf]);
        return promise;
      } catch (_) { /* fall through to inline fallback */ }
    }
    return crc32HexFallback(blob);
  }

  function shouldCrcChunk(index, totalChunks) {
    if (CRC_MODE === 'full') return true;
    if (CRC_MODE === 'fast') return false;
    // sample mode
    if (index === 0 || index === totalChunks - 1 || index === Math.floor(totalChunks / 2)) return true;
    return index % 16 === 0;
  }

  function uploadChunkXHR(task, uploadId, index, blob, crcHex, onLoaded) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      task.xhrs.add(xhr);
      xhr.open('POST', UPLOAD_API + '/chunk?upload_id=' +
               encodeURIComponent(uploadId) + '&index=' + index);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      if (crcHex) xhr.setRequestHeader('X-Chunk-Crc32', crcHex);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onLoaded(e.loaded);
      };
      xhr.onload = () => {
        task.xhrs.delete(xhr);
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else reject(new Error('分块 ' + index + ' HTTP ' + xhr.status));
      };
      xhr.onerror = () => { task.xhrs.delete(xhr); reject(new Error('网络错误')); };
      xhr.ontimeout = () => { task.xhrs.delete(xhr); reject(new Error('分块超时')); };
      xhr.onabort = () => { task.xhrs.delete(xhr); reject(new Error('上传已取消')); };
      xhr.timeout = 300000;
      xhr.send(blob);
    });
  }

  async function uploadChunkWithRetry(task, uploadId, index, blob, onLoaded, totalChunks) {
    let lastErr = null;
    // CRC computed once per chunk; verified server-side on every attempt.
    // In fast/sample modes some chunks omit the header and server skips check.
    const crcHex = shouldCrcChunk(index, totalChunks)
      ? await crc32Hex(blob).catch(() => null)
      : null;
    for (let attempt = 0; attempt <= CHUNK_RETRY; attempt++) {
      if (task.status !== 'uploading') throw new Error('上传已取消');
      try {
        await uploadChunkXHR(task, uploadId, index, blob, crcHex, onLoaded);
        return;
      } catch (e) {
        lastErr = e;
        if (e.message === '上传已取消') throw e;  // user cancel: no retry
      }
    }
    throw lastErr;
  }

  // uploadFileChunked(file, task): updates task.loaded/sessionBase as it goes.
  // Returns upload_id. The task's XHRs are tracked for panel-side cancel.
  async function uploadFileChunked(file, task) {
    // init returns the session + already-received chunk bitmap (resume point)
    const init = await fetchJSON(UPLOAD_API + '/init', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fingerprint: fileFingerprint(file),
        filename: file.name,
        file_size: file.size
      })
    });
    const uploadId = init.upload_id;
    task.uploadId = uploadId;   // allow cancel/abort server-side before complete
    task._uploadId = uploadId;
    const chunkSize = init.chunk_size;
    const totalChunks = init.total_chunks;
    const doneSet = new Set(init.received);
    const expectedLen = (i) => Math.min(chunkSize, file.size - i * chunkSize);

    // progress bookkeeping: base = bytes already on server, live = in-flight chunk loads
    let base = 0;
    for (const i of doneSet) base += expectedLen(i);
    task.sessionBase = base;
    task.startedAt = Date.now();   // session speed counts only this attempt
    const live = {};
    const report = () => {
      let loaded = base;
      for (const k in live) loaded += live[k];
      task.loaded = Math.min(loaded, file.size);
      schedulePanelRender();
    };
    report();

    const pending = [];
    for (let i = 0; i < totalChunks; i++) {
      if (!doneSet.has(i)) pending.push(i);
    }
    let cursor = 0;
    const worker = async () => {
      while (cursor < pending.length && task.status === 'uploading') {
        const i = pending[cursor++];
        const blob = file.slice(i * chunkSize, Math.min((i + 1) * chunkSize, file.size));
        live[i] = 0;
        await uploadChunkWithRetry(task, uploadId, i, blob, (l) => { live[i] = l; report(); }, totalChunks);
        base += expectedLen(i);
        delete live[i];
        report();
      }
    };
    const n = Math.min(CHUNK_CONCURRENCY, Math.max(1, pending.length));
    await Promise.all(Array.from({ length: n }, worker));
    if (task.status !== 'uploading') throw new Error('上传已取消');
    return uploadId;
  }

  async function sendDirectUpload(files) {
    const totalAll = files.reduce((s, f) => s + f.size, 0);

    // All small files: single multipart request (lowest latency)
    if (files.length && files.every(f => f.size <= CHUNKED_UPLOAD_THRESHOLD)) {
      const fd = new FormData();
      fd.set('sender', '');
      for (const f of files) {
        fd.append('files', f);
      }
      // one task per file; the single request reports only aggregate progress,
      // split proportionally by size (small files finish in seconds anyway)
      const tasks = files.map(f => createTask(f));
      if (uploadPanelOpen && selectedUploadId === NEW_UPLOAD_ID) {
        selectedUploadId = tasks[0].id;
        renderUploadPanel();
      }

      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        for (const t of tasks) t.xhrs.add(xhr);
        xhr.open('POST', MSG_API + '/files');

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            for (const t of tasks) {
              t.loaded = Math.min(t.size, Math.round(e.loaded * t.size / Math.max(1, e.total)));
            }
            schedulePanelRender();
            updateProgress(e.loaded, e.total);
          }
        };

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            for (const t of tasks) { t.loaded = t.size; finishTask(t, 'done'); }
            try {
              resolve(JSON.parse(xhr.responseText));
            } catch (_) {
              resolve(xhr.responseText);
            }
          } else {
            let errMsg = 'HTTP ' + xhr.status;
            try {
              const body = JSON.parse(xhr.responseText);
              errMsg = body.detail || errMsg;
            } catch (_) {}
            for (const t of tasks) finishTask(t, 'error', errMsg);
            reject(new Error(errMsg));
          }
        };

        xhr.onerror = () => { for (const t of tasks) finishTask(t, 'error', '网络错误'); reject(new Error('网络错误')); };
        xhr.ontimeout = () => { for (const t of tasks) finishTask(t, 'error', '上传超时'); reject(new Error('上传超时')); };
        xhr.onabort = () => {
          for (const t of tasks) {
            if (t.status === 'uploading') finishTask(t, 'cancelled');
          }
          reject(new Error('上传已取消'));
        };
        xhr.timeout = 300000;
        xhr.send(fd);
      });
    }

    // Large file(s): chunked parallel + resumable path (one task per file)
    const tasks = [];
    // modal aggregate progress from tasks (average speed across the whole op);
    // uploadFileChunked updates task.loaded, this interval mirrors it to the bar
    const reportModal = () => {
      const loaded = tasks.reduce((s, t) => s + t.loaded, 0);
      const sent = tasks.reduce((s, t) => s + Math.max(0, t.loaded - t.sessionBase), 0);
      updateProgress(loaded, totalAll, sent);
    };
    const modalTimer = setInterval(reportModal, 250);

    try {
      for (const f of files) {
        const t = createTask(f);
        tasks.push(t);
        if (uploadPanelOpen && selectedUploadId === NEW_UPLOAD_ID) {
          selectedUploadId = t.id;
          renderUploadPanel();
        }
        t._uploadId = await uploadFileChunked(f, t);
      }

      const ids = tasks.map(t => t._uploadId);
      const msg = await fetchJSON(UPLOAD_API + '/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_ids: ids, sender: '' })
      });
      for (const t of tasks) { t.loaded = t.size; finishTask(t, 'done'); }
      return msg;
    } catch (e) {
      for (const t of tasks) {
        if (t.status === 'uploading') {
          if (t._paused) {
            saveUploadHistory();
            updateUploadBadge();
            renderUploadPanel();
          } else {
            finishTask(t, e.message === '上传已取消' ? 'cancelled' : 'error', e.message);
          }
        }
      }
      throw e;
    } finally {
      clearInterval(modalTimer);
    }
  }

  async function sendZip(files, name) {
    const fd = new FormData();
    fd.set('zip_name', name || 'files');
    fd.set('sender', '');
    for (const f of files) {
      fd.append('files', f);
    }
    // zip op = one task (single request; server-side deflate is not upload progress)
    const task = createTask(
      { name: (name || 'files') + '.zip', size: files.reduce((s, f) => s + f.size, 0) },
      (files.length > 1 ? files[0].name + ' 等 ' + files.length + ' 个文件' : undefined)
    );
    if (uploadPanelOpen && selectedUploadId === NEW_UPLOAD_ID) {
      selectedUploadId = task.id;
      renderUploadPanel();
    }
    try {
      // no per-request progress via fetch(); run XHR-less is fine for typical zips
      await fetchJSON(MSG_API + '/zip', { method: 'POST', body: fd });
      task.loaded = task.size;
      finishTask(task, 'done');
      showToast(`共 ${files.length} 个文件，打包发送成功`);
    } catch (e) {
      finishTask(task, 'error', e.message);
      showToast('打包上传失败: ' + e.message);
    }
  }

  // ── SSE ────────────────────────────────────────────────────────────────
  function connectSSE() {
    const evtSrc = new EventSource(EVT_API);
    evtSrc.onopen = () => {
      sseStatus.className = 'sse-status connected';
    };

    evtSrc.addEventListener('new_message', (e) => {
      try {
        const msg = JSON.parse(e.data);
        renderMsg(msg, false);
        scrollToBottom(false);

        // Save self IP on first message from us
        if (!getSelfIp() && msg.device_ip) {
          localStorage.setItem('self_ip', msg.device_ip);
        }
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    });

    evtSrc.addEventListener('profile_update', (e) => {
      try { refreshUsers(); } catch (_) {}
    });
    evtSrc.addEventListener('message_deleted', (e) => {
      try {
        const data = JSON.parse(e.data);
        const el = msgArea.querySelector('[data-id="' + data.id + '"]');
        if (el) el.remove();
      } catch (_) {}
    });
    evtSrc.addEventListener('messages_cleared', () => {
      msgArea.innerHTML = '';
      allLoaded = false;
      loadingHistory = false;
      lastRenderedDate = '';
      for (const k in messageCache) delete messageCache[k];
    });
    evtSrc.onerror = () => {
      sseStatus.className = 'sse-status disconnected';
      // EventSource auto-reconnects
    };
  }

  // ── History scroll (infinite scroll up) ────────────────────────────────
  msgArea.addEventListener('scroll', () => {
    if (msgArea.scrollTop < 50) {
      const firstMsg = msgArea.querySelector('[data-id]');
      if (firstMsg) {
        loadMessages(parseInt(firstMsg.dataset.id));
      }
    }
  });

  // ── Text input ─────────────────────────────────────────────────────────
  msgInput.addEventListener('input', () => {
    msgInput.style.height = 'auto';
    msgInput.style.height = Math.min(msgInput.scrollHeight, 120) + 'px';
  });

  msgInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendText(msgInput.value);
    }
  });

  btnSend.addEventListener('click', () => sendText(msgInput.value));

  // ── Clipboard paste ────────────────────────────────────────────────────
  msgInput.addEventListener('paste', async (e) => {
    const items = e.clipboardData.items;
    let hasFile = false;
    for (const item of items) {
      if (item.kind === 'file') {
        hasFile = true;
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          await sendFile(file);
          showToast(`已粘贴文件: ${file.name}`);
        }
      }
    }
  });

  // ── Upload action panel (inside upload manager modal) ─────────────────
  let zipFiles = [];

  function clearZipFiles() {
    zipFiles = [];
    zipName.value = '';
    resetProgress();
    showProgress(false);
    updateZipFileList();
  }

  function closeUploadModal() {
    // Closing the modal does NOT abort uploads - they continue in background
    // (see upload manager panel). Stop/cancel per-task from the detail panel.
    const active = uploadTasks.some(t => t.status === 'uploading');
    uploadPanelOpen = false;
    uploadPanel.classList.remove('open');
    clearZipFiles();
    btnZipCancel.textContent = '清空';
    updateRealtimeState();
    if (active) {
      showToast('上传仍在后台进行, 点击输入栏上传图标查看进度');
    }
  }

  function formatSpeed(bps) {
    return formatSize(Math.round(bps)) + '/s';
  }

  let realtimeTimer = null;
  let realtimeBusy = false;
  let stressRunning = false;

  function stopRealtimeSpeedTest() {
    if (realtimeTimer) {
      clearInterval(realtimeTimer);
      realtimeTimer = null;
    }
  }

  function updateRealtimeState() {
    const hasActive = uploadTasks.some(t => t.status === 'uploading');
    if (uploadPanelOpen && !stressRunning && !hasActive) {
      if (!realtimeTimer) {
        realtimeTimer = setInterval(runRealtimeProbe, 3000);
        runRealtimeProbe();
      }
    } else {
      stopRealtimeSpeedTest();
    }
  }

  async function runRealtimeProbe() {
    if (realtimeBusy || stressRunning || !uploadPanelOpen) return;
    realtimeBusy = true;
    try {
      const DL_SIZE = 512 * 1024;
      const UL_SIZE = 256 * 1024;
      const t0 = performance.now();
      await Promise.all([
        fetch(`/api/speedtest?bytes=${DL_SIZE}`).then(r => {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.arrayBuffer();
        }),
        fetch('/api/speedtest', {
          method: 'POST',
          body: new Uint8Array(UL_SIZE)
        }).then(r => {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.text();
        })
      ]);
      const secs = (performance.now() - t0) / 1000;
      if (!stressRunning && uploadPanelOpen && !uploadTasks.some(t => t.status === 'uploading')) {
        speedTestResult.style.display = 'block';
        speedTestResult.textContent = `实时 下载 ${formatSpeed(DL_SIZE / secs)} · 上传 ${formatSpeed(UL_SIZE / secs)}`;
      }
    } catch (_) {
      // Transient realtime probe failures are ignored.
    } finally {
      realtimeBusy = false;
    }
  }

  async function runSpeedTest() {
    if (btnSpeedTest.disabled) return;
    btnSpeedTest.disabled = true;
    stressRunning = true;
    stopRealtimeSpeedTest();
    speedTestResult.style.display = 'none';
    stressTestResult.style.display = 'block';
    stressTestResult.textContent = '压测中... 约 15 秒';

    const fetchTimeout = (url, opts, ms = 10000) => {
      if (typeof AbortController === 'undefined') return fetch(url, opts);
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), ms);
      return fetch(url, Object.assign({}, opts, { signal: ctrl.signal }))
        .finally(() => clearTimeout(timer));
    };

    const PHASE_MS = 7500;               // download + upload ≈ 15s total
    const DL_SIZE = 4 * 1024 * 1024;     // 4MB per download request
    const UL_SIZE = 1 * 1024 * 1024;     // 1MB per upload request
    const PARALLEL = 4;

    try {
      // Download phase.
      const dlStart = performance.now();
      let dlBytes = 0;
      while (performance.now() - dlStart < PHASE_MS) {
        const bufs = await Promise.all(Array.from({ length: PARALLEL }, () =>
          fetchTimeout(`/api/speedtest?bytes=${DL_SIZE}`).then(r => {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.arrayBuffer();
          })
        ));
        for (const b of bufs) dlBytes += b.byteLength;
        const elapsed = (performance.now() - dlStart) / 1000;
        stressTestResult.textContent = `压测中... 下载 ${formatSpeed(dlBytes / elapsed)}`;
      }
      const dlSecs = (performance.now() - dlStart) / 1000;
      const dlBps = dlBytes / dlSecs;

      // Upload phase.
      const ulStart = performance.now();
      let ulBytes = 0;
      while (performance.now() - ulStart < PHASE_MS) {
        await Promise.all(Array.from({ length: PARALLEL }, () =>
          fetchTimeout('/api/speedtest', {
            method: 'POST',
            body: new Uint8Array(UL_SIZE)
          }).then(r => {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.text();
          })
        ));
        ulBytes += UL_SIZE * PARALLEL;
        const elapsed = (performance.now() - ulStart) / 1000;
        stressTestResult.textContent = `压测中... 上传 ${formatSpeed(ulBytes / elapsed)}`;
      }
      const ulSecs = (performance.now() - ulStart) / 1000;
      const ulBps = ulBytes / ulSecs;

      stressTestResult.textContent = `压测结果 下载 ${formatSpeed(dlBps)} · 上传 ${formatSpeed(ulBps)}`;
    } catch (e) {
      stressTestResult.textContent = '压测失败: ' + (e.name === 'AbortError' ? '超时' : e.message);
    } finally {
      btnSpeedTest.disabled = false;
      stressRunning = false;
      updateRealtimeState();
    }
  }

  btnSpeedTest.addEventListener('click', runSpeedTest);

  btnZipCancel.addEventListener('click', clearZipFiles);

  // Drop zone — drag & drop
  dropZone.addEventListener('click', () => zipFileInput.click());

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      for (const f of files) zipFiles.push(f);
      updateZipFileList();
    }
  });

  // File input for upload action
  zipFileInput.addEventListener('change', (e) => {
    const files = (e.target || zipFileInput).files;
    if (files && files.length > 0) {
      for (const f of files) zipFiles.push(f);
      updateZipFileList();
    }
    zipFileInput.value = '';
  });

  function updateZipFileList() {
    const list = document.getElementById('fileList');
    list.innerHTML = '';
    for (let i = 0; i < zipFiles.length; i++) {
      const f = zipFiles[i];
      const item = document.createElement('div');
      item.className = 'file-item';
      item.innerHTML = `
        <span class="name">${escapeHtml(f.name)}</span>
        <span class="size">${formatSize(f.size)}</span>
        <span class="remove" data-idx="${i}">\u2715</span>`;
      item.querySelector('.remove').addEventListener('click', () => {
        zipFiles.splice(i, 1);
        updateZipFileList();
      });
      list.appendChild(item);
    }
    updateButtonState();
  }

  function updateButtonState() {
    const count = zipFiles.length;
    btnZipUpload.disabled = count === 0;
    btnDirectUpload.disabled = count === 0;

    if (isMobile() && count > 0) {
      // 手机端不展示两个上传方式，按文件数量自动选择：
      // <=10 直接上传，>10 打包上传。
      const useZip = count > 10;
      btnDirectUpload.style.display = useZip ? 'none' : '';
      btnZipUpload.style.display = useZip ? '' : 'none';
    } else {
      btnDirectUpload.style.display = '';
      btnZipUpload.style.display = '';
    }
  }

  window.addEventListener('resize', updateButtonState);

  btnZipUpload.addEventListener('click', async () => {
    if (zipFiles.length === 0) return;
    btnZipUpload.disabled = true;
    btnZipUpload.textContent = '打包中...';
    try {
      const name = zipName.value.trim() || 'files';
      await sendZip(zipFiles, name);
      // stay open: sendZip already switched to the new task detail
      zipFiles = [];
      updateZipFileList();
    } finally {
      btnZipUpload.disabled = false;
      btnZipUpload.textContent = '上传打包';
    }
  });

  btnDirectUpload.addEventListener('click', async () => {
    if (zipFiles.length === 0) return;
    const totalSize = zipFiles.reduce((s, f) => s + f.size, 0);

    // Disable all controls
    btnDirectUpload.disabled = true;
    btnZipUpload.disabled = true;
    btnZipCancel.textContent = '转入后台';

    // Show progress
    resetProgress();
    showProgress(true);
    updateProgress(0, totalSize);

    try {
      await sendDirectUpload(zipFiles);
      showToast('共 ' + zipFiles.length + ' 个文件，直接发送成功');
      zipFiles = [];
      updateZipFileList();
    } catch (e) {
      showProgress(false);
      const userStopped = uploadTasks.some(t => t._stoppedByUser) || e.message === '上传已取消';
      if (!userStopped) showToast('上传失败: ' + e.message);
      updateButtonState();
      btnZipCancel.textContent = '清空';
    }
  });

  // Close modal on overlay click
  uploadPanel.addEventListener('click', (e) => {
    if (e.target === uploadPanel) closeUploadModal();
  });

  // ── Also drag-drop files onto page for single file upload ──────────────
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', (e) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;
    if (files.length === 1) {
      sendFile(files[0]);
    } else {
      // Multiple files → open upload panel with "上传文件" action selected
      zipFiles = Array.from(files);
      zipName.value = 'files';
      openUploadPanel(true, true);
      updateZipFileList();
    }
  });

  // ── Theme switching ───────────────────────────────────────────────────
  const THEMES = ['red', 'default', 'kokomi', 'firefly', 'furina', 'hysilens', 'geniusclub', 'silverwolf', 'odette'];
  const THEME_NAMES = ['兰亭信传', '简约配色', '珊瑚宫心海', '流萤·萨姆', '芙宁娜·歌剧院', '海瑟音·深境', '天才俱乐部', '狼尊 LV.999', '奥黛塔·月夜羽翼'];

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    themeSelect.value = theme;
    const idx = THEMES.indexOf(theme);
    if (idx >= 0) pageTitle.textContent = THEME_NAMES[idx];
  }

  async function saveThemeToServer(theme) {
    try {
      await fetch('/api/theme', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme })
      });
    } catch (_) { /* offline-safe */ }
  }

  async function setTheme(theme) {
    applyTheme(theme);
    localStorage.setItem('chat_theme', theme);
    await saveThemeToServer(theme);
    if (!shaderRunner && window.ShaderRunner) shaderRunner = new window.ShaderRunner();
    if (shaderRunner) shaderRunner.setTheme(theme);
  }

  themeSelect.addEventListener('change', async () => {
    await setTheme(themeSelect.value);
    showToast('已切换为: ' + (THEME_NAMES[THEMES.indexOf(themeSelect.value)] || themeSelect.value));
  });

  // Restore saved theme — instant from local cache, then authoritative from server
  async function restoreTheme() {
    // Castflow embed：直接采用宿主主题，不走本地/服务端历史覆盖
    if (isEmbed) {
      const q = new URLSearchParams(location.search).get('theme');
      if (q) {
        await setTheme(cfThemeValue(q));
        return;
      }
    }
    const localTheme = localStorage.getItem('chat_theme');
    if (localTheme && THEMES.includes(localTheme)) {
      applyTheme(localTheme);
    } else {
      applyTheme('red');
    }
    if (!shaderRunner && window.ShaderRunner) shaderRunner = new window.ShaderRunner();
    if (shaderRunner) shaderRunner.setTheme(localTheme && THEMES.includes(localTheme) ? localTheme : 'red');
    try {
      const r = await fetchJSON('/api/theme');
      if (r.theme && THEMES.includes(r.theme)) {
        applyTheme(r.theme);
        localStorage.setItem('chat_theme', r.theme);
        if (shaderRunner) shaderRunner.setTheme(r.theme);
      }
    } catch (_) { /* offline, stay with local cache */ }
  }

  restoreTheme();

  // ── User features ──────────────────────────────────────────────────────
  let profileCache = {};

  // Load user's own profile
  async function loadProfile() {
    try {
      const r = await fetchJSON('/api/profile');
      if (r.display_name) {
        nameInput.value = r.display_name;
      }
      profileCache[r.ip] = r.display_name;
      localStorage.setItem('self_ip', r.ip);
    } catch (_) {}
  }

  btnSetName.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    if (!name) return;
    try {
      await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: name })
      });
      showToast('昵称已设置为: ' + name);
      // Refresh user list and re-render
      await refreshUsers();
      rerenderMessages();
    } catch (_) { showToast('设置失败'); }
  });
  nameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') btnSetName.click();
  });

  // Name/IP toggle: click the displayed name/IP in any message
  document.addEventListener('click', (e) => {
    const ipSpan = e.target.closest('.msg-ip');
    if (!ipSpan || e.target.closest('.btn-recall')) return;
    // Already handled by per-msg click above, but we also support global toggle
    // via Shift+click on any IP
    if (e.shiftKey) {
      const cur = localStorage.getItem('show_name');
      localStorage.setItem('show_name', cur === 'true' ? 'false' : 'true');
      showToast('已切换显示: ' + (cur === 'true' ? 'IP地址' : '昵称'));
      rerenderMessages();
    }
  });

  // Refresh user list
  async function refreshUsers() {
    try {
      const users = await fetchJSON('/api/users');
      profileCache = {};
      // Preserve current selection
      const prevVal = filterSelect.value;
      filterSelect.innerHTML = '<option value="">全部</option>';
      for (const u of users) {
        profileCache[u.device_ip] = u.display_name || '';
        const opt = document.createElement('option');
        opt.value = u.device_ip;
        opt.textContent = u.display_name || u.device_ip;
        filterSelect.appendChild(opt);
      }
      if (prevVal && [...filterSelect.options].some(o => o.value === prevVal)) {
        filterSelect.value = prevVal;
      }
    } catch (_) {}
  }

  filterSelect.addEventListener('change', () => {
    const ip = filterSelect.value;
    if (currentFilter === ip) return;
    currentFilter = ip;
    if (!ip) {
      allLoaded = false;
      msgArea.innerHTML = '';
      lastRenderedDate = '';
      loadMessages();
    } else {
      allLoaded = false;
      msgArea.innerHTML = '';
      lastRenderedDate = '';
      loadingHistory = false;
      const params = new URLSearchParams({ limit: '100', sender_ip: ip });
      fetchJSON(MSG_API + '?' + params).then(msgs => {
        for (const msg of msgs) renderMsg(msg, false);
        scrollToBottom(false);
      }).catch(() => showToast('加载失败'));
    }
  });

  function setFilter(ip) {
    currentFilter = ip;
    filterSelect.value = ip || '';
    if (ip) {
      allLoaded = false;
      msgArea.innerHTML = '';
      lastRenderedDate = '';
      loadingHistory = false;
      const params = new URLSearchParams({ limit: '100', sender_ip: ip });
      fetchJSON(MSG_API + '?' + params).then(msgs => {
        for (const msg of msgs) renderMsg(msg, false);
        scrollToBottom(false);
      }).catch(() => showToast('加载失败'));
    } else {
      allLoaded = false;
      msgArea.innerHTML = '';
      lastRenderedDate = '';
      loadMessages();
    }
  }

  function clearFilter() {
    setFilter('');
  }



  // Rerender all visible messages (for name/IP toggle)
  function rerenderMessages() {
    const ids = [];
    msgArea.querySelectorAll('[data-id]').forEach(el => {
      ids.push(parseInt(el.dataset.id));
    });
    msgArea.innerHTML = '';
    lastRenderedDate = '';
    for (const id of ids) {
      const msg = messageCache[id];
      if (msg) renderMsg(msg, false);
    }
    scrollToBottom(false);
  }

  // Clear all messages
  const clearModal = document.getElementById('clearModal');
  const clearModalCancel = document.getElementById('clearModalCancel');
  const clearModalConfirm = document.getElementById('clearModalConfirm');
  
  btnClear.addEventListener('click', () => {
    clearModal.classList.add('open');
  });
  clearModalCancel.addEventListener('click', () => {
    clearModal.classList.remove('open');
  });
  clearModal.addEventListener('click', (e) => {
    if (e.target === clearModal) clearModal.classList.remove('open');
  });
  clearModalConfirm.addEventListener('click', async () => {
    clearModal.classList.remove('open');
    try {
      await fetch('/api/messages?confirm=true', { method: 'DELETE' });
      showToast('已清空所有消息和文件');
    } catch (_) { showToast('清空失败'); }
  });

  // ── Castflow embed mode：隐藏主题选择器，跟随宿主 dark/light ──
  function cfThemeValue(t) { return THEMES.includes(t) ? t : (t === 'dark' ? 'hysilens' : 'default'); }
  const isEmbed = new URLSearchParams(location.search).has('embed');
  if (isEmbed && themeSelect) themeSelect.style.display = 'none';
  if (isEmbed) {
    const q = new URLSearchParams(location.search).get('theme');
    if (q) setTheme(cfThemeValue(q));
  }
  window.addEventListener('message', (ev) => {
    if (ev.data && ev.data.type === 'cf-theme') {
      setTheme(cfThemeValue(ev.data.value));
    }
  });

  // ── Init ───────────────────────────────────────────────────────────────
  async function init() {
    // Get self IP first so recall buttons work for messages loaded after
    try {
      const whoami = await fetchJSON('/api/whoami');
      localStorage.setItem('self_ip', whoami.ip);
    } catch (_) {}

    await loadProfile();
    await refreshUsers();
    await loadMessages();
    connectSSE();
  }

  init();
})();