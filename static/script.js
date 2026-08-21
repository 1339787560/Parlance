(function() {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────
  const MSG_API = '/api/messages';
  const UPLOAD_API = '/api/upload';
  const EVT_API = '/api/events';
  const DL_API = '/api/download';
  let selectedFiles = [];
  let loadingHistory = false;
  let allLoaded = false;

  // ── DOM refs ────────────────────────────────────────────────────────────
  const msgArea = document.getElementById('msgArea');
  const msgInput = document.getElementById('msgInput');
  const btnSend = document.getElementById('btnSend');
  const btnZip = document.getElementById('btnZip');
  const themeSelect = document.getElementById('themeSelect');
  const pageTitle = document.getElementById('pageTitle');
  const nameInput = document.getElementById('nameInput');
  const btnSetName = document.getElementById('btnSetName');
  const btnClear = document.getElementById('btnClear');
  const filterSelect = document.getElementById('filterSelect');
  let currentFilter = '';
  const messageCache = {};  // id -> original msg data for rerender
  const zipModal = document.getElementById('zipModal');
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
    // Large single file -> chunked parallel path (resumable); no progress UI here
    if (file.size > CHUNK_SIZE) {
      try {
        const id = await uploadFileChunked(file, () => {});
        await fetchJSON(UPLOAD_API + '/complete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ upload_ids: [id], sender: '' })
        });
      } catch (e) {
        showToast('上传失败(进度已保留, 重发将续传): ' + e.message);
      }
      return;
    }
    const fd = new FormData();
    fd.set('file', file);
    fd.set('sender', '');
    try {
      await fetchJSON(MSG_API + '/file', { method: 'POST', body: fd });
    } catch (e) {
      showToast('上传失败: ' + e.message);
    }
  }

  // ── Upload progress helpers ──────────────────────────────────────────
  const progressFill = document.getElementById('progressFill');
  const progressInfo = document.getElementById('progressInfo');
  const progressSection = document.getElementById('progressSection');

  function resetProgress() {
    progressFill.style.width = '0%';
    progressInfo.textContent = '';
    uploadSpeed = 0;
    uploadLastBytes = 0;
    uploadLastTime = 0;
    uploadXHR = null;
  }

  function showProgress(show) {
    progressSection.style.display = show ? 'block' : 'none';
  }

  function updateProgress(loaded, total) {
    const now = Date.now();
    if (uploadLastTime > 0) {
      const dt = (now - uploadLastTime) / 1000;
      if (dt > 0) {
        const dBytes = loaded - uploadLastBytes;
        const instantaneous = dBytes / dt;
        if (instantaneous > 0) {
          uploadSpeed = uploadSpeed > 0
            ? (0.3 * instantaneous + 0.7 * uploadSpeed)
            : instantaneous;
        }
      }
    }
    uploadLastBytes = loaded;
    uploadLastTime = now;

    const pct = Math.min(100, Math.round((loaded / total) * 100));
    progressFill.style.width = pct + '%';

    const speedStr = formatSize(Math.round(uploadSpeed));
    let remaining = '';
    if (uploadSpeed > 0 && pct < 100) {
      const secs = Math.ceil((total - loaded) / uploadSpeed);
      remaining = secs < 60 ? ' · 剩余 ' + secs + '秒'
        : ' · 剩余 ' + Math.ceil(secs / 60) + '分钟';
    }

    progressInfo.textContent = pct + '% · ' + formatSize(loaded) + ' / ' + formatSize(total)
      + (speedStr ? ' · ' + speedStr + '/s' : '')
      + remaining;
  }

  // ── Chunked parallel + resumable upload ────────────────────────────────
  const CHUNK_SIZE = 8 * 1024 * 1024;   // must match server UPLOAD_CHUNK_SIZE
  const CHUNK_CONCURRENCY = 4;          // parallel TCP streams
  const CHUNK_RETRY = 3;
  let uploadXHRs = [];                  // in-flight chunk XHRs (for cancel)

  function fileFingerprint(file) {
    return file.name + '|' + file.size + '|' + file.lastModified;
  }

  function uploadChunkXHR(uploadId, index, blob, onLoaded) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      uploadXHRs.push(xhr);
      xhr.open('POST', UPLOAD_API + '/chunk?upload_id=' +
               encodeURIComponent(uploadId) + '&index=' + index);
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onLoaded(e.loaded);
      };
      xhr.onload = () => {
        uploadXHRs = uploadXHRs.filter(x => x !== xhr);
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else reject(new Error('分块 ' + index + ' HTTP ' + xhr.status));
      };
      xhr.onerror = () => { uploadXHRs = uploadXHRs.filter(x => x !== xhr); reject(new Error('网络错误')); };
      xhr.ontimeout = () => { uploadXHRs = uploadXHRs.filter(x => x !== xhr); reject(new Error('分块超时')); };
      xhr.onabort = () => { uploadXHRs = uploadXHRs.filter(x => x !== xhr); reject(new Error('上传已取消')); };
      xhr.timeout = 300000;
      xhr.send(blob);
    });
  }

  async function uploadChunkWithRetry(uploadId, index, blob, onLoaded) {
    let lastErr = null;
    for (let attempt = 0; attempt <= CHUNK_RETRY; attempt++) {
      try {
        await uploadChunkXHR(uploadId, index, blob, onLoaded);
        return;
      } catch (e) {
        lastErr = e;
        if (e.message === '上传已取消') throw e;  // user cancel: no retry
      }
    }
    throw lastErr;
  }

  async function uploadFileChunked(file, onProgress) {
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
    const chunkSize = init.chunk_size;
    const totalChunks = init.total_chunks;
    const doneSet = new Set(init.received);
    const expectedLen = (i) => Math.min(chunkSize, file.size - i * chunkSize);

    // progress bookkeeping: base = bytes already on server, live = in-flight chunk loads
    let base = 0;
    for (const i of doneSet) base += expectedLen(i);
    const live = {};
    const report = () => {
      let loaded = base;
      for (const k in live) loaded += live[k];
      onProgress(Math.min(loaded, file.size), file.size);
    };
    report();

    const pending = [];
    for (let i = 0; i < totalChunks; i++) {
      if (!doneSet.has(i)) pending.push(i);
    }
    let cursor = 0;
    const worker = async () => {
      while (cursor < pending.length) {
        const i = pending[cursor++];
        const blob = file.slice(i * chunkSize, Math.min((i + 1) * chunkSize, file.size));
        live[i] = 0;
        await uploadChunkWithRetry(uploadId, i, blob, (l) => { live[i] = l; report(); });
        base += expectedLen(i);
        delete live[i];
        report();
      }
    };
    const n = Math.min(CHUNK_CONCURRENCY, Math.max(1, pending.length));
    await Promise.all(Array.from({ length: n }, worker));
    return uploadId;
  }

  async function sendDirectUpload(files) {
    const totalAll = files.reduce((s, f) => s + f.size, 0);

    // All small files: single multipart request (lowest latency)
    if (files.length && files.every(f => f.size <= CHUNK_SIZE)) {
      const fd = new FormData();
      fd.set('sender', '');
      for (const f of files) {
        fd.append('files', f);
      }

      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        uploadXHR = xhr;
        xhr.open('POST', MSG_API + '/files');

        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            updateProgress(e.loaded, e.total);
          }
        };

        xhr.onload = () => {
          uploadXHR = null;
          if (xhr.status >= 200 && xhr.status < 300) {
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
            reject(new Error(errMsg));
          }
        };

        xhr.onerror = () => { uploadXHR = null; reject(new Error('网络错误')); };
        xhr.ontimeout = () => { uploadXHR = null; reject(new Error('上传超时')); };
        xhr.onabort = () => { uploadXHR = null; reject(new Error('上传已取消')); };
        xhr.timeout = 300000;
        xhr.send(fd);
      });
    }

    // Large file(s): chunked parallel + resumable path
    const ids = [];
    let cumDone = 0;
    for (const f of files) {
      const id = await uploadFileChunked(f, (loaded) => {
        updateProgress(cumDone + loaded, totalAll);
      });
      cumDone += f.size;
      ids.push(id);
    }
    return await fetchJSON(UPLOAD_API + '/complete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ upload_ids: ids, sender: '' })
    });
  }

  async function sendZip(files, name) {
    const fd = new FormData();
    fd.set('zip_name', name || 'files');
    fd.set('sender', '');
    for (const f of files) {
      fd.append('files', f);
    }
    try {
      await fetchJSON(MSG_API + '/zip', { method: 'POST', body: fd });
      showToast(`共 ${files.length} 个文件，打包发送成功`);
    } catch (e) {
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

  // ── ZIP modal ──────────────────────────────────────────────────────────
  let zipFiles = [];

  // Upload progress state
  let uploadSpeed = 0;
  let uploadLastBytes = 0;
  let uploadLastTime = 0;
  let uploadXHR = null;

  btnZip.addEventListener('click', () => {
    zipFiles = [];
    zipName.value = '';
    resetProgress();
    showProgress(false);
    updateZipFileList();
    zipModal.classList.add('open');
  });

  function closeZipModal() {
    // Abort any in-flight upload (multipart single-stream + parallel chunks).
    // Aborted chunk sessions stay 'active' server-side -> same file re-send resumes.
    if (uploadXHR) {
      try { uploadXHR.abort(); } catch (_) {}
      uploadXHR = null;
    }
    for (const x of uploadXHRs) {
      try { x.abort(); } catch (_) {}
    }
    uploadXHRs = [];
    zipModal.classList.remove('open');
    zipFiles = [];
    resetProgress();
    showProgress(false);
    updateZipFileList();
    btnZipCancel.textContent = '取消';
  }

  btnZipCancel.addEventListener('click', closeZipModal);

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

  // File input for zip modal
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
    btnZipUpload.disabled = zipFiles.length === 0;
    btnDirectUpload.disabled = zipFiles.length === 0;
  }

  btnZipUpload.addEventListener('click', async () => {
    if (zipFiles.length === 0) return;
    btnZipUpload.disabled = true;
    btnZipUpload.textContent = '打包中...';
    try {
      const name = zipName.value.trim() || 'files';
      await sendZip(zipFiles, name);
      closeZipModal();
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
    btnZipCancel.textContent = '取消上传';

    // Show progress
    resetProgress();
    showProgress(true);
    updateProgress(0, totalSize);

    try {
      await sendDirectUpload(zipFiles);
      showToast('共 ' + zipFiles.length + ' 个文件，直接发送成功');
      closeZipModal();
    } catch (e) {
      showProgress(false);
      showToast('上传失败: ' + e.message);
      updateButtonState();
      btnZipCancel.textContent = '取消';
    }
  });

  // Close modal on overlay click
  zipModal.addEventListener('click', (e) => {
    if (e.target === zipModal) closeZipModal();
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
      // Multiple files → open ZIP modal
      zipFiles = Array.from(files);
      zipName.value = 'files';
      zipModal.classList.add('open');
      updateZipFileList();
    }
  });

  // ── Theme switching ───────────────────────────────────────────────────
  const THEMES = ['red', 'default', 'kokomi', 'firefly', 'furina', 'hysilens', 'geniusclub', 'silverwolf'];
  const THEME_NAMES = ['兰亭信传', '简约配色', '珊瑚宫心海', '流萤·萨姆', '芙宁娜·歌剧院', '海瑟音·深境', '天才俱乐部', '狼尊 LV.999'];

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