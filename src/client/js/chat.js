import { S, fn, dom, t, $, $$, getBaseUrl, escapeHtml, setLang, currentLang } from '/js/state.js';
import { petSetVisualState, petSetSubtitle } from '/js/pet-bridge.js';

// ═══════════════════════════════════════════════════
// CONNECTION & SETUP
// ═══════════════════════════════════════════════════

async function testConnection(url) {
  try {
    const r = await fetch(`${url}/api/server-info`, { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

async function connectToServer(url, token) {
  dom.connectBtn.disabled = true;
  dom.connectBtn.textContent = t('setup.connecting');

  const info = await testConnection(url);
  if (!info) {
    dom.connectBtn.disabled = false;
    dom.connectBtn.textContent = t('setup.connect');
    dom.qrStatus.textContent = t('setup.connectFailed');
    dom.qrStatus.style.color = 'var(--error)';
    return false;
  }

  S.serverUrl = url;
  S.token = token || info.token || '';
  localStorage.setItem('oc_server', S.serverUrl);
  localStorage.setItem('oc_token', S.token);

  showChat(info);
  return true;
}

function showChat(info) {
  stopQrScanner();
  dom.setupPage.classList.add('hidden');
  dom.chatPage.classList.remove('hidden');
  dom.statusDot.className = 'status-dot';
  dom.infoServer.textContent = S.serverUrl;
  dom.infoStatus.textContent = t('settings.connected');
  dom.infoStatus.style.color = 'var(--success)';
  if (info?.ips) dom.infoIps.textContent = info.ips.join(', ');
  fn.connectVoiceWs();
  generateShareQr();
}

function showSetup() {
  dom.chatPage.classList.add('hidden');
  dom.setupPage.classList.remove('hidden');
  dom.connectBtn.disabled = false;
  dom.connectBtn.textContent = t('setup.connect');
  dom.qrStatus.textContent = '';
  dom.qrStatus.style.color = '';
  if (S.serverUrl) dom.serverUrl.value = S.serverUrl;
  startQrScanner();
}

// ═══════════════════════════════════════════════════
// QR SCANNER
// ═══════════════════════════════════════════════════

let qrScanning = false;
let qrAnimFrame = null;
let qrStream = null;

async function startQrScanner() {
  try {
    qrStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 640 }, height: { ideal: 640 } }
    });
    dom.qrVideo.srcObject = qrStream;
    await dom.qrVideo.play();
    qrScanning = true;
    dom.qrStatus.textContent = t('setup.pointCamera');
    scanQrFrame();
  } catch (e) {
    dom.qrStatus.textContent = t('setup.cameraUnavailable');
    console.warn('QR camera error:', e);
  }
}

function scanQrFrame() {
  if (!qrScanning) return;
  const video = dom.qrVideo;
  const canvas = dom.qrCanvas;
  if (video.readyState === video.HAVE_ENOUGH_DATA) {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(video, 0, 0);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);

    if (typeof jsQR !== 'undefined') {
      const code = jsQR(imageData.data, canvas.width, canvas.height);
      if (code?.data) {
        handleQrResult(code.data);
        return;
      }
    }
  }
  qrAnimFrame = requestAnimationFrame(scanQrFrame);
}

function handleQrResult(data) {
  qrScanning = false;
  dom.qrStatus.textContent = t('setup.qrDetected');
  dom.qrStatus.style.color = 'var(--success)';

  try {
    const parsed = JSON.parse(data);
    const url = parsed.url || parsed.server;
    const token = parsed.token || '';
    if (url) {
      connectToServer(url, token);
      return;
    }
  } catch {}

  if (data.startsWith('http')) {
    const u = new URL(data);
    const token = u.searchParams.get('token') || '';
    const url = `${u.protocol}//${u.host}`;
    connectToServer(url, token);
    return;
  }

  dom.qrStatus.textContent = t('setup.invalidQr');
  dom.qrStatus.style.color = 'var(--error)';
  qrScanning = true;
  scanQrFrame();
}

function stopQrScanner() {
  qrScanning = false;
  if (qrAnimFrame) cancelAnimationFrame(qrAnimFrame);
  if (qrStream) { qrStream.getTracks().forEach(tr => tr.stop()); qrStream = null; }
}

// ═══════════════════════════════════════════════════
// RETRY HELPER — retries failed fetch (network / 5xx) up to N times
// ═══════════════════════════════════════════════════

async function _fetchRetry(url, opts, retries = 2, delay = 800) {
  let lastResp;
  for (let i = 0; i <= retries; i++) {
    try {
      lastResp = await fetch(url, opts);
      if (lastResp.ok || lastResp.status < 500) return lastResp;
      if (i < retries) await new Promise(r => setTimeout(r, delay * (i + 1)));
    } catch (err) {
      if (i >= retries) throw err;
      await new Promise(r => setTimeout(r, delay * (i + 1)));
    }
  }
  return lastResp;
}

// ═══════════════════════════════════════════════════
// TEXT CHAT
// ═══════════════════════════════════════════════════

function buildMessages() {
  const msgs = [{ role: 'system', content: S.SYSTEM_PROMPT }];
  const recent = S.messages.slice(-20);
  for (const m of recent) {
    if (m.role === 'user' || m.role === 'assistant') {
      if (m.imageData) {
        msgs.push({
          role: m.role,
          content: [
            ...(m.imageData.map(d => ({ type: 'image_url', image_url: { url: d } }))),
            { type: 'text', text: m.content || '(image)' },
          ]
        });
      } else {
        msgs.push({ role: m.role, content: m.content });
      }
    }
  }
  return msgs;
}

async function sendTextMessage(text) {
  if (S.isSending || (!text.trim() && S.attachments.length === 0)) return;
  if (fn.isDesktopActive?.() && text.trim() && S.attachments.length === 0) {
    return sendDesktopCommand(text);
  }
  S.isSending = true;
  dom.sendBtn.disabled = true;
  if (S.isPlayingAudio) fn.stopSpeaking();
  petSetVisualState('thinking');
  petSetSubtitle('');
  hideWelcome();

  // 隐式反馈：如果有已完成的团队，检测用户消息是否是反馈
  if (window._lastCompletedTeamId && text.trim().length > 1 && text.trim().length < 100) {
    fetch(getBaseUrl() + '/api/agents/feedback/implicit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text.trim(), team_id: window._lastCompletedTeamId }),
    }).catch(() => {});
  }

  const imageData = [];
  const fileNames = [];
  for (const att of S.attachments) {
    if (att.type.startsWith('image/')) {
      imageData.push(att.dataUrl);
    }
    fileNames.push(att.name);
  }

  const userMsg = {
    role: 'user',
    content: text.trim() || (fileNames.length ? `Sent: ${fileNames.join(', ')}` : ''),
    imageData: imageData.length ? imageData : null,
    attachments: S.attachments.map(a => ({ name: a.name, type: a.type })),
  };
  S.messages.push(userMsg);
  appendMessage(userMsg);
  clearAttachments();
  dom.msgInput.value = '';
  autoResize(dom.msgInput);

  const aiMsg = { role: 'assistant', content: '' };
  S.messages.push(aiMsg);
  const aiEl = appendMessage(aiMsg, true);

  try {
    const body = { messages: buildMessages(), model: 'deepseek-chat', stream: true };
    const resp = await _fetchRetry(`${getBaseUrl()}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      if (resp.status === 429) throw new Error('AI 正在忙，请稍等几秒再试');
      if (resp.status === 401) throw new Error('需要配置 AI，请到设置中填写 API Key');
      throw new Error('连接异常，请检查网络');
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const data = trimmed.slice(5).trim();
        if (data === '[DONE]') continue;

        try {
          const parsed = JSON.parse(data);
          const delta = parsed.choices?.[0]?.delta?.content;
          if (delta != null && delta !== '') {
            fullText += delta;
            updateStreamingEl(aiEl, fullText);
            petSetSubtitle(fullText.slice(0, 160));
          }
        } catch {}
      }
    }

    aiMsg.content = fullText;
    finalizeStreamingEl(aiEl, fullText);

    if (fullText.trim()) speakText(fullText);
    else {
      petSetVisualState('idle');
      petSetSubtitle('');
    }
  } catch (e) {
    console.error('Chat error:', e);
    aiMsg.content = '⚠️ ' + (e.message || '出了点问题，请稍后再试');
    finalizeStreamingEl(aiEl, aiMsg.content);
    petSetVisualState('error');
    petSetSubtitle('');
  }

  S.isSending = false;
  updateSendBtn();
}

async function speakText(text) {
  try {
    const resp = await fetch(`${getBaseUrl()}/api/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 500) }),
    });
    if (!resp.ok) {
      petSetVisualState('idle');
      petSetSubtitle('');
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const data = trimmed.slice(5).trim();
        if (data === '[DONE]') continue;
        try {
          const parsed = JSON.parse(data);
          if (parsed.audio) {
            fn.queueVoiceAudio(parsed.audio, 24000, parsed.format || 'pcm');
          }
        } catch {}
      }
    }
    if (!S.isPlayingAudio && (!S.audioQueue || S.audioQueue.length === 0)) {
      petSetVisualState('idle');
      petSetSubtitle('');
    }
  } catch (e) {
    console.warn('TTS error:', e);
    petSetVisualState('idle');
  }
}

// ═══════════════════════════════════════════════════
// VISION CHAT (text + camera image → AI)
// ═══════════════════════════════════════════════════

async function sendTextMessageWithImage(text, image_b64) {
  if (S.isPlayingAudio) fn.stopSpeaking();
  petSetVisualState('thinking');
  petSetSubtitle('');
  hideWelcome();
  const userMsg = { role: 'user', content: text, imageData: [`data:image/jpeg;base64,${image_b64}`] };
  S.messages.push(userMsg);
  appendMessage(userMsg);

  const aiMsg = { role: 'assistant', content: '' };
  S.messages.push(aiMsg);
  const aiEl = appendMessage(aiMsg, true);

  try {
    const resp = await _fetchRetry(`${getBaseUrl()}/api/vision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, image_b64 }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const data = trimmed.slice(5).trim();
        if (data === '[DONE]') continue;
        try {
          const parsed = JSON.parse(data);
          const chunk = parsed.choices?.[0]?.delta?.content || '';
          if (chunk) {
            fullText += chunk;
            updateStreamingEl(aiEl, fullText);
            petSetSubtitle(fullText.slice(0, 160));
          }
        } catch {}
      }
    }
    aiMsg.content = fullText;
    finalizeStreamingEl(aiEl, fullText);
    if (fullText.trim()) speakText(fullText);
    else {
      petSetVisualState('idle');
      petSetSubtitle('');
    }
  } catch (e) {
    console.error('Vision chat error:', e);
    aiMsg.content = t('error.prefix', { msg: e.message });
    finalizeStreamingEl(aiEl, aiMsg.content);
    petSetVisualState('error');
    petSetSubtitle(aiMsg.content.slice(0, 120));
  }
}

// ═══════════════════════════════════════════════════
// DESKTOP AI COMMAND
// ═══════════════════════════════════════════════════

async function sendDesktopCommand(text) {
  if (S.isSending || !text.trim()) return;
  S.isSending = true;
  dom.sendBtn.disabled = true;
  if (S.isPlayingAudio) fn.stopSpeaking();
  petSetVisualState('thinking');
  petSetSubtitle('');
  hideWelcome();

  const userMsg = { role: 'user', content: text.trim(), desktop: true };
  S.messages.push(userMsg);
  appendMessage(userMsg);
  dom.msgInput.value = '';
  autoResize(dom.msgInput);

  const aiMsg = { role: 'assistant', content: '', desktop: true };
  S.messages.push(aiMsg);
  const aiEl = appendMessage(aiMsg, true);

  let fullText = '';
  let statusEl = null;

  function showDesktopStatus(text) {
    if (!statusEl) {
      statusEl = document.createElement('div');
      statusEl.className = 'desktop-status';
      statusEl.style.cssText = 'font-size:12px;color:var(--accent);padding:4px 8px;margin-top:4px;border-left:2px solid var(--accent);opacity:.8';
      const body = aiEl.querySelector('.msg-body');
      if (body) body.appendChild(statusEl);
    }
    statusEl.textContent = text;
  }

  try {
    const history = S.messages.slice(-10).filter(m => m.desktop && m.content).map(m => ({
      role: m.role, content: m.content
    }));

    const resp = await fetch(`${getBaseUrl()}/api/desktop-cmd`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: text.trim(), history: history.slice(0, -1), max_rounds: 3 }),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith('data:')) continue;
        const data = trimmed.slice(5).trim();
        if (data === '[DONE]') continue;

        try {
          const msg = JSON.parse(data);

          if (msg.type === 'status') {
            showDesktopStatus(msg.text);
          } else if (msg.type === 'text') {
            fullText += msg.text;
            const displayText = fullText.replace(/\[ACTIONS\][\s\S]*?\[\/ACTIONS\]/g, '').trim();
            updateStreamingEl(aiEl, displayText);
            petSetSubtitle(displayText.slice(0, 160));
          } else if (msg.type === 'executing') {
            const names = msg.actions.map(a => a.action === 'find_and_click' ? `${t('desktop.ai.clicking')} "${a.text}"` :
              a.action === 'type' ? `${t('desktop.ai.typing')} "${a.text?.slice(0,20)}"` :
              a.action === 'key' ? `${t('desktop.ai.pressing')} ${a.key}` :
              a.action).join(' → ');
            showDesktopStatus(`${t('desktop.ai.executing')}: ${names}`);
          } else if (msg.type === 'exec_result') {
            const logText = msg.log?.join('\n') || '';
            showDesktopStatus(`${t('desktop.ai.done')}`);
            console.log('Desktop exec log:', logText);
          } else if (msg.type === 'screenshot') {
            const imgEl = document.createElement('img');
            imgEl.src = 'data:image/jpeg;base64,' + msg.data;
            imgEl.className = 'msg-img';
            imgEl.style.cssText = 'max-width:300px;border-radius:8px;margin-top:8px;cursor:pointer;border:1px solid var(--border)';
            imgEl.onclick = () => openLightbox(imgEl.src);
            const body = aiEl.querySelector('.msg-body');
            if (body) body.appendChild(imgEl);
          } else if (msg.type === 'error') {
            fullText += `\n${t('error.prefix', {msg: msg.text})}`;
            updateStreamingEl(aiEl, fullText);
          } else if (msg.type === 'done') {
            if (statusEl) statusEl.remove();
            statusEl = null;
          }
        } catch {}
      }
    }

    const displayText = fullText.replace(/\[ACTIONS\][\s\S]*?\[\/ACTIONS\]/g, '').trim();
    aiMsg.content = displayText;
    finalizeStreamingEl(aiEl, displayText);
    if (displayText.trim()) speakText(displayText);
    else {
      petSetVisualState('idle');
      petSetSubtitle('');
    }

  } catch (e) {
    console.error('Desktop cmd error:', e);
    aiMsg.content = '⚠️ ' + (e.message || '出了点问题，请稍后再试');
    finalizeStreamingEl(aiEl, aiMsg.content);
    petSetVisualState('error');
    petSetSubtitle('');
  }

  if (statusEl) statusEl.remove();
  S.isSending = false;
  updateSendBtn();
}

// ═══════════════════════════════════════════════════
// FILE HANDLING
// ═══════════════════════════════════════════════════

function addAttachment(file) {
  if (file.size > 20 * 1024 * 1024) {
    alert(t('file.tooLarge'));
    return;
  }

  const reader = new FileReader();
  reader.onload = () => {
    S.attachments.push({
      name: file.name,
      type: file.type,
      dataUrl: reader.result,
      size: file.size,
    });
    renderPreviews();
  };
  reader.readAsDataURL(file);
}

function removeAttachment(index) {
  S.attachments.splice(index, 1);
  renderPreviews();
}

function clearAttachments() {
  S.attachments = [];
  renderPreviews();
}

function renderPreviews() {
  dom.previewBar.innerHTML = '';
  for (let i = 0; i < S.attachments.length; i++) {
    const att = S.attachments[i];
    const el = document.createElement('div');
    el.className = 'preview-item';

    if (att.type.startsWith('image/')) {
      el.innerHTML = `<img src="${att.dataUrl}" alt="${att.name}"><button class="preview-remove" data-i="${i}">&times;</button>`;
    } else {
      const icon = att.type.includes('pdf') ? '📄' : att.type.includes('video') ? '🎬' : att.type.includes('audio') ? '🎵' : '📎';
      el.innerHTML = `<div class="file-icon">${icon}</div><button class="preview-remove" data-i="${i}">&times;</button>`;
    }
    dom.previewBar.appendChild(el);
  }
  updateSendBtn();
}

// ═══════════════════════════════════════════════════
// MARKDOWN RENDERER
// ═══════════════════════════════════════════════════

function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);

  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
    `<pre><code>${code.trim()}</code></pre>`);
  html = html.replace(/```([\s\S]*?)```/g, (_, code) =>
    `<pre><code>${code.trim()}</code></pre>`);

  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/^### (.+)$/gm, '<h4 style="margin:12px 0 4px;font-size:13px">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 style="margin:14px 0 6px;font-size:14px;color:var(--accent,#6c63ff)">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 style="margin:16px 0 8px;font-size:16px">$1</h2>');
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  html = html.replace(/\n/g, '<br>');
  html = html.replace(/<pre><code>([\s\S]*?)<\/code><\/pre>/g, (_, code) =>
    `<pre><code>${code.replace(/<br>/g, '\n')}</code></pre>`);

  return html;
}

// ═══════════════════════════════════════════════════
// UI HELPERS
// ═══════════════════════════════════════════════════

function hideWelcome() {
  if (dom.welcome) dom.welcome.style.display = 'none';
}

function _safeContent(c) {
  if (Array.isArray(c)) {
    const texts = [], imgs = [];
    c.forEach(p => {
      if (p?.type === 'text' && p.text) texts.push(p.text);
      else if (p?.type === 'image_url') imgs.push(p.image_url?.url || '');
    });
    return { text: texts.join(' ') + (imgs.length ? ` [${imgs.length > 1 ? imgs.length + '张' : ''}图片]` : ''), imgs: imgs.filter(u => u && !u.startsWith('data:')) };
  }
  if (typeof c === 'string' && c.startsWith('[{')) {
    try { return _safeContent(JSON.parse(c)); } catch(_) {}
  }
  return { text: typeof c === 'string' ? c : String(c ?? ''), imgs: [] };
}

const LONG_MSG_CHARS = 720;

function setupLongMessageCollapse(msgEl) {
  const textEl = msgEl.querySelector('.msg-text');
  if (!textEl) return;
  const plain = textEl.textContent || '';
  if (plain.length < LONG_MSG_CHARS) return;
  textEl.classList.add('msg-text--collapsed');
  const textId = 'msg-text-' + Math.random().toString(36).slice(2, 9);
  textEl.id = textId;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'msg-expand-btn';
  btn.textContent = t('ui.expand');
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', textId);
  btn.setAttribute('aria-label', t('ui.expand'));
  btn.addEventListener('click', () => {
    const collapsed = textEl.classList.toggle('msg-text--collapsed');
    btn.textContent = collapsed ? t('ui.expand') : t('ui.collapse');
    btn.setAttribute('aria-expanded', String(!collapsed));
    btn.setAttribute('aria-label', collapsed ? t('ui.expand') : t('ui.collapse'));
  });
  const body = msgEl.querySelector('.msg-body');
  if (body) body.appendChild(btn);
}

function appendMessage(msg, streaming = false) {
  // 安全检查：确保消息容器存在
  if (!dom.messages || !dom.messages.parentNode) {
    dom.messages = document.getElementById('messages');
    dom.messagesArea = document.getElementById('messages-area');
  }
  if (!dom.messages) return null;

  const div = document.createElement('div');
  div.className = `msg ${msg.role === 'user' ? 'user' : 'ai'}`;

  const safe = _safeContent(msg.content);
  const avatar = msg.role === 'user' ? '👤' : (msg.desktop ? '🖥️' : '🦞');
  let attachHtml = '';
  if (msg.imageData) {
    attachHtml = '<div class="msg-attachments">' +
      msg.imageData.map(d => `<img class="msg-img" src="${d}" onclick="openLightbox(this.src)">`).join('') +
      '</div>';
  }
  if (msg.attachments?.length) {
    const nonImages = msg.attachments.filter(a => !a.type?.startsWith('image/'));
    if (nonImages.length) {
      attachHtml += nonImages.map(a => `<div class="msg-file">📎 ${escapeHtml(a.name)}</div>`).join('');
    }
  }

  const voiceBadge = msg.voice ? ' <span style="font-size:11px;opacity:.5">🎙</span>' : '';
  const textHtml = streaming ? '<div class="typing"><span></span><span></span><span></span></div>' : renderMarkdown(safe.text);

  div.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-body">
      ${attachHtml}
      <div class="msg-text">${textHtml}${voiceBadge}</div>
    </div>`;

  dom.messages.appendChild(div);
  if (!streaming) setupLongMessageCollapse(div);
  scrollToBottom();
  return div;
}

function updateStreamingEl(el, text) {
  const textEl = el.querySelector('.msg-text');
  if (textEl) textEl.innerHTML = renderMarkdown(text) + '<span style="display:inline-block;width:6px;height:16px;background:var(--accent);margin-left:2px;animation:blink .8s infinite;vertical-align:text-bottom"></span>';
  scrollToBottom();
}

function finalizeStreamingEl(el, text) {
  const textEl = el.querySelector('.msg-text');
  if (textEl) textEl.innerHTML = renderMarkdown(text);
  setupLongMessageCollapse(el);
}

function scrollToBottom() {
  dom.messagesArea.scrollTop = dom.messagesArea.scrollHeight;
}

function updateSendBtn() {
  const hasContent = dom.msgInput.value.trim().length > 0 || S.attachments.length > 0;
  dom.sendBtn.disabled = !hasContent || S.isSending;
  dom.sendBtn.classList.toggle('active', hasContent && !S.isSending);
}

function autoResize(textarea) {
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

function openLightbox(src) {
  dom.lightboxImg.src = src;
  dom.lightbox.classList.remove('hidden');
}

async function generateShareQr() {
  try {
    const QRCode = (await import('https://cdn.jsdelivr.net/npm/qrcode@1.5.4/+esm')).default;
    const data = JSON.stringify({ url: S.serverUrl, token: S.token });
    const canvas = await QRCode.toCanvas(data, { width: 180, margin: 2, color: { dark: '#000', light: '#fff' } });
    dom.qrDisplay.innerHTML = '';
    dom.qrDisplay.appendChild(canvas);
  } catch (e) {
    dom.qrDisplay.innerHTML = `<span style="color:var(--text-muted);font-size:12px">${t('settings.qrUnavailable')}</span>`;
    console.warn('QR gen error:', e);
  }
}

// ═══════════════════════════════════════════════════
// UPLOAD TO PC
// ═══════════════════════════════════════════════════

let _uploadToastTimer = null;

function showUploadToast(icon, title, path, progress) {
  const toast = document.getElementById('upload-toast');
  document.getElementById('upload-toast-icon').textContent = icon;
  document.getElementById('upload-toast-title').textContent = title;
  document.getElementById('upload-toast-path').textContent = path || '';
  document.getElementById('upload-progress-fill').style.width = `${progress}%`;
  toast.classList.add('show');
  clearTimeout(_uploadToastTimer);
}

function hideUploadToast(delay = 3000) {
  clearTimeout(_uploadToastTimer);
  _uploadToastTimer = setTimeout(() => {
    document.getElementById('upload-toast').classList.remove('show');
  }, delay);
}

async function uploadFileToPc(file) {
  showUploadToast('⏳', t('upload.uploading') + ' ' + file.name, '', 20);
  try {
    const formData = new FormData();
    formData.append('file', file, file.name);

    showUploadToast('⏳', t('upload.uploading') + ' ' + file.name, '', 60);

    const resp = await fetch(`${getBaseUrl()}/api/upload`, {
      method: 'POST',
      body: formData,
    });
    const result = await resp.json();

    if (result.ok) {
      const sizeStr = result.size > 1024 * 1024
        ? `${(result.size / 1024 / 1024).toFixed(1)} MB`
        : `${(result.size / 1024).toFixed(1)} KB`;
      showUploadToast('✅', `${t('upload.done')} (${sizeStr})`,
        t('upload.saved').replace('{path}', result.path), 100);
      hideUploadToast(4000);
    } else {
      showUploadToast('❌', t('upload.failed').replace('{err}', result.error || 'Unknown'), '', 0);
      hideUploadToast(4000);
    }
  } catch (e) {
    showUploadToast('❌', t('upload.failed').replace('{err}', e.message), '', 0);
    hideUploadToast(4000);
  }
}

// ═══════════════════════════════════════════════════
// SESSION HELPER
// ═══════════════════════════════════════════════════

async function _getActiveSession() {
  try {
    const r = await fetch(getBaseUrl() + '/api/profiles/active');
    const d = await r.json();
    if (d.ok && d.profile) return 'profile:' + d.profile.id;
  } catch (_) {}
  return 'default';
}

// ═══════════════════════════════════════════════════
// AUDIO UNLOCK
// ═══════════════════════════════════════════════════

let audioUnlocked = false;
function unlockAudio() {
  if (audioUnlocked) return;
  const ctx = new AudioContext();
  const buf = ctx.createBuffer(1, 1, 22050);
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(ctx.destination);
  src.start(0);
  src.onended = () => ctx.close();
  audioUnlocked = true;
}

// ═══════════════════════════════════════════════════
// MIC PREWARM
// ═══════════════════════════════════════════════════

let _micPrewarmed = false;
async function prewarmMic() {
  if (_micPrewarmed) return;
  _micPrewarmed = true;
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  if (!isIOS) return;
  try {
    if (!S.mediaStream) {
      S.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
      });
      console.log('iOS mic pre-warmed ✅ (single permission prompt)');
    }
  } catch(e) {
    console.warn('iOS mic pre-warm failed:', e.message);
  }
}

// ═══════════════════════════════════════════════════
// INIT — register on fn, wire events, bootstrap
// ═══════════════════════════════════════════════════

export function init() {
  // 1. Register public functions on fn
  fn.appendMessage = appendMessage;
  fn.updateStreamingEl = updateStreamingEl;
  fn.finalizeStreamingEl = finalizeStreamingEl;
  fn.scrollToBottom = scrollToBottom;
  fn.hideWelcome = hideWelcome;
  fn.updateSendBtn = updateSendBtn;
  fn.renderMarkdown = renderMarkdown;
  fn.sendTextMessage = sendTextMessage;
  fn.sendTextMessageWithImage = sendTextMessageWithImage;
  fn.sendDesktopCommand = sendDesktopCommand;
  fn.speakText = speakText;
  fn.showChat = showChat;
  fn.showSetup = showSetup;
  fn.testConnection = testConnection;
  fn.buildMessages = buildMessages;
  fn.generateShareQr = generateShareQr;
  fn.addAttachment = addAttachment;
  fn.clearAttachments = clearAttachments;

  // 2. Expose on window for inline onclick handlers
  window.showChatPage = showChat;
  window.openLightbox = openLightbox;

  // ═══════════════════════════════════════════════════
  // EVENT LISTENERS
  // ═══════════════════════════════════════════════════

  // Setup
  dom.connectBtn.addEventListener('click', () => {
    const url = dom.serverUrl.value.trim().replace(/\/$/, '');
    const token = dom.serverToken.value.trim();
    if (!url) { dom.serverUrl.focus(); return; }
    connectToServer(url, token);
  });

  dom.skipBtn.addEventListener('click', () => {
    connectToServer(window.location.origin, '');
  });

  dom.serverUrl.addEventListener('keydown', e => { if (e.key === 'Enter') dom.connectBtn.click(); });
  dom.serverToken.addEventListener('keydown', e => { if (e.key === 'Enter') dom.connectBtn.click(); });

  // Stop Speaking
  document.getElementById('stop-speaking-btn').addEventListener('click', () => fn.stopSpeaking());

  // Chat
  dom.msgInput.addEventListener('input', () => { if (S.isPlayingAudio) fn.stopSpeaking(); autoResize(dom.msgInput); updateSendBtn(); });
  dom.msgInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTextMessage(dom.msgInput.value); }
  });
  dom.sendBtn.addEventListener('click', () => sendTextMessage(dom.msgInput.value));

  $$('.suggestion').forEach(btn => {
    btn.addEventListener('click', async () => {
      const text = btn.dataset.msg;
      if (!text) return; // onclick 按钮没有 data-msg

      // 检查 AI 是否配置
      try {
        const r = await fetch(getBaseUrl() + '/api/ai/status');
        const d = await r.json();
        if (!d.configured) {
          // 弹出配置提示
          if (confirm('⚠️ 还没有配置 AI 引擎！\n\n推荐使用智谱 GLM-4-Flash（永久免费）\n\n点击"确定"前往设置页面配置')) {
            window.open('/setup', '_blank');
          }
          return;
        }
      } catch (e) { /* 网络错误时仍尝试发送 */ }

      dom.msgInput.value = text;
      sendTextMessage(text);
    });
  });

  // Voice — click and press-and-hold support
  (function() {
    let _holdTimer = null, _isHolding = false, _holdFired = false;
    const HOLD_MS = 400;
    const hint = document.getElementById('mic-hold-hint');

    function onHoldStart(e) {
      e.preventDefault();
      _holdFired = false;
      _holdTimer = setTimeout(() => {
        _holdFired = true;
        _isHolding = true;
        if (hint) hint.classList.remove('visible');
        fn.startVoiceRecording();
      }, HOLD_MS);
    }

    function onHoldEnd(e) {
      clearTimeout(_holdTimer);
      if (_isHolding) {
        _isHolding = false;
        if (S.isRecording) fn.stopVoiceRecording();
        fn.closeVoiceOverlay();
        return;
      }
      if (_holdFired) return;
      if (!dom.voiceOverlay.classList.contains('hidden')) {
        fn.closeVoiceOverlay();
      } else {
        fn.startVoiceRecording();
      }
    }

    function onHoldCancel() { clearTimeout(_holdTimer); _isHolding = false; }

    dom.micBtn.addEventListener('touchstart', onHoldStart, { passive: false });
    dom.micBtn.addEventListener('touchend', onHoldEnd);
    dom.micBtn.addEventListener('touchcancel', onHoldCancel);
    dom.micBtn.addEventListener('mousedown', onHoldStart);
    dom.micBtn.addEventListener('mouseup', onHoldEnd);
    dom.micBtn.addEventListener('mouseleave', onHoldCancel);

    dom.micBtn.addEventListener('click', (e) => { e.preventDefault(); });

    let _hintShown = false;
    if ('ontouchstart' in window && !_hintShown) {
      dom.micBtn.addEventListener('touchstart', function showHint() {
        if (!_hintShown) { _hintShown = true; if (hint) { hint.classList.add('visible'); setTimeout(() => hint.classList.remove('visible'), 2500); } }
        dom.micBtn.removeEventListener('touchstart', showHint);
      }, { once: true });
    }
  })();

  function handleVoiceStopClick() {
    if (S.isRecording) fn.stopVoiceRecording();
    fn.closeVoiceOverlay();
  }
  dom.voiceStop.addEventListener('click', handleVoiceStopClick);
  document.getElementById('vbar-stop').addEventListener('click', handleVoiceStopClick);
  dom.voiceOverlay.addEventListener('click', (e) => {
    if (e.target === dom.voiceOverlay) {
      if (S.isRecording) fn.stopVoiceRecording();
      fn.closeVoiceOverlay();
    }
  });

  // Camera
  dom.cameraToggle.addEventListener('click', () => fn.toggleCamera());
  dom.cameraClose.addEventListener('click', () => {
    if (fn.isDesktopActive?.()) { fn.minimizeCameraToPip(); }
    else { fn.closeCamera(); }
  });
  dom.captureBtn.addEventListener('click', () => fn.capturePhoto());

  // PIP Camera — Drag, Resize, Restore
  (function() {
    const pip = document.getElementById('camera-pip');
    const resizeHandle = document.getElementById('pip-resize');
    const restoreBtn = document.getElementById('pip-restore');
    const closeBtn = document.getElementById('pip-close-btn');
    if (!pip) return;

    const DRAG_THRESHOLD = 5;
    const MIN_W = 120, MIN_H = 90, MAX_W = 640, MAX_H = 480;
    let isDragging = false, isResizing = false;
    let startX, startY, startLeft, startTop, startW, startH;
    let wasDragged = false;

    function initPosition() {
      const saved = localStorage.getItem('pip-pos');
      if (saved) {
        try {
          const p = JSON.parse(saved);
          pip.style.left = Math.min(p.x, window.innerWidth - 60) + 'px';
          pip.style.top = Math.min(p.y, window.innerHeight - 60) + 'px';
          if (p.w) pip.style.width = Math.min(p.w, MAX_W) + 'px';
          if (p.h) pip.style.height = Math.min(p.h, MAX_H) + 'px';
          pip.style.right = 'auto'; pip.style.bottom = 'auto';
          return;
        } catch(e) {}
      }
      pip.style.right = '20px'; pip.style.bottom = '100px';
      pip.style.left = 'auto'; pip.style.top = 'auto';
    }

    function savePosition() {
      const r = pip.getBoundingClientRect();
      localStorage.setItem('pip-pos', JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height }));
    }

    function clampInViewport() {
      const r = pip.getBoundingClientRect();
      let x = r.left, y = r.top;
      if (x < 0) x = 0;
      if (y < 0) y = 0;
      if (x + r.width > window.innerWidth) x = window.innerWidth - r.width;
      if (y + r.height > window.innerHeight) y = window.innerHeight - r.height;
      pip.style.left = x + 'px'; pip.style.top = y + 'px';
      pip.style.right = 'auto'; pip.style.bottom = 'auto';
    }

    function onDragStart(e) {
      if (isResizing) return;
      const pt = e.touches ? e.touches[0] : e;
      const r = pip.getBoundingClientRect();
      startX = pt.clientX; startY = pt.clientY;
      startLeft = r.left; startTop = r.top;
      wasDragged = false; isDragging = true;
      pip.classList.add('dragging');
      pip.style.left = r.left + 'px'; pip.style.top = r.top + 'px';
      pip.style.right = 'auto'; pip.style.bottom = 'auto';
      e.preventDefault();
    }

    function onDragMove(e) {
      if (!isDragging) return;
      const pt = e.touches ? e.touches[0] : e;
      const dx = pt.clientX - startX, dy = pt.clientY - startY;
      if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) wasDragged = true;
      pip.style.left = (startLeft + dx) + 'px';
      pip.style.top = (startTop + dy) + 'px';
    }

    function onDragEnd() {
      if (!isDragging) return;
      isDragging = false;
      pip.classList.remove('dragging');
      clampInViewport();
      savePosition();
    }

    function onResizeStart(e) {
      e.stopPropagation();
      const pt = e.touches ? e.touches[0] : e;
      const r = pip.getBoundingClientRect();
      startX = pt.clientX; startY = pt.clientY;
      startW = r.width; startH = r.height;
      startLeft = r.left; startTop = r.top;
      isResizing = true;
      pip.classList.add('dragging');
      pip.style.left = r.left + 'px'; pip.style.top = r.top + 'px';
      pip.style.right = 'auto'; pip.style.bottom = 'auto';
      e.preventDefault();
    }

    function onResizeMove(e) {
      if (!isResizing) return;
      const pt = e.touches ? e.touches[0] : e;
      const dx = pt.clientX - startX, dy = pt.clientY - startY;
      const nw = Math.max(MIN_W, Math.min(MAX_W, startW + dx));
      const nh = Math.max(MIN_H, Math.min(MAX_H, startH + dy));
      pip.style.width = nw + 'px';
      pip.style.height = nh + 'px';
    }

    function onResizeEnd() {
      if (!isResizing) return;
      isResizing = false;
      pip.classList.remove('dragging');
      clampInViewport();
      savePosition();
    }

    pip.addEventListener('mousedown', onDragStart);
    document.addEventListener('mousemove', (e) => { onDragMove(e); onResizeMove(e); });
    document.addEventListener('mouseup', () => { onDragEnd(); onResizeEnd(); });
    pip.addEventListener('touchstart', onDragStart, { passive: false });
    document.addEventListener('touchmove', (e) => { onDragMove(e); onResizeMove(e); }, { passive: false });
    document.addEventListener('touchend', () => { onDragEnd(); onResizeEnd(); });

    resizeHandle.addEventListener('mousedown', onResizeStart);
    resizeHandle.addEventListener('touchstart', onResizeStart, { passive: false });

    restoreBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      fn.restoreCameraFromPip();
      if (fn.isDesktopActive?.()) fn.closeDesktopMode();
    });

    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      pip.classList.add('hidden');
    });

    pip.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      fn.restoreCameraFromPip();
      if (fn.isDesktopActive?.()) fn.closeDesktopMode();
    });

    initPosition();
    window.addEventListener('resize', () => {
      if (!pip.classList.contains('hidden')) clampInViewport();
    });
  })();

  // Desktop
  document.getElementById('desktop-close').addEventListener('click', () => fn.closeDesktopMode());
  document.getElementById('skill-toast-close').addEventListener('click', () => {
    document.getElementById('skill-toast').classList.add('hidden');
  });
  document.getElementById('desktop-gesture-ctrl').addEventListener('click', (e) => {
    const gc = fn.toggleDesktopGesture?.();
    e.currentTarget.style.color = gc ? 'var(--accent)' : 'var(--text-muted)';
    document.getElementById('desktop-hint').textContent = gc
      ? t('desktop.gestureOn')
      : t('desktop.touchHint');
  });
  fn.setupDesktopTouch?.();
  document.getElementById('desktop-toggle').addEventListener('click', () => fn.toggleDesktopMode());

  // ── Attach Menu ──
  let _attachMode = 'ai';
  const attachMenu = document.getElementById('attach-menu');

  function showAttachMenu() {
    attachMenu.classList.add('show');
  }
  function hideAttachMenu() {
    attachMenu.classList.remove('show');
  }

  dom.attachBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (attachMenu.classList.contains('show')) hideAttachMenu();
    else showAttachMenu();
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#attach-menu') && !e.target.closest('#attach-btn')) {
      hideAttachMenu();
    }
  });
  document.getElementById('attach-to-ai').addEventListener('click', () => {
    _attachMode = 'ai';
    hideAttachMenu();
    dom.fileInput.click();
  });
  document.getElementById('attach-to-pc').addEventListener('click', () => {
    _attachMode = 'pc';
    hideAttachMenu();
    dom.fileInput.removeAttribute('accept');
    dom.fileInput.click();
  });

  dom.fileInput.addEventListener('change', async (e) => {
    const files = Array.from(e.target.files);
    e.target.value = '';
    dom.fileInput.setAttribute('accept', "image/*,video/*,audio/*,.pdf,.doc,.docx,.txt,.md,.json,.csv,.zip");

    if (_attachMode === 'pc') {
      for (const file of files) await uploadFileToPc(file);
    } else {
      for (const file of files) addAttachment(file);
    }
    _attachMode = 'ai';
  });

  // Preview remove
  dom.previewBar.addEventListener('click', (e) => {
    const btn = e.target.closest('.preview-remove');
    if (btn) removeAttachment(parseInt(btn.dataset.i));
  });

  // Settings（使用可选链，避免缺省节点时整段初始化失败导致「设置打不开」）
  dom.settingsToggle?.addEventListener('click', () => dom.settingsModal?.classList.remove('hidden'));
  dom.settingsClose?.addEventListener('click', () => dom.settingsModal?.classList.add('hidden'));
  document.getElementById('settings-back-btn')?.addEventListener('click', () => dom.settingsModal?.classList.add('hidden'));
  dom.settingsModal?.addEventListener('click', (e) => {
    if (e.target === dom.settingsModal) dom.settingsModal.classList.add('hidden');
  });
  dom.disconnectBtn?.addEventListener('click', () => {
    localStorage.removeItem('oc_server');
    localStorage.removeItem('oc_token');
    S.serverUrl = '';
    S.token = '';
    fn.disconnectPermanently?.();
    try { fn.closeCamera?.(); } catch (_) {}
    dom.settingsModal.classList.add('hidden');
    window.location.href = '/setup?force';
  });

  // Language toggle
  document.getElementById('lang-select').value = currentLang;
  document.getElementById('lang-select').addEventListener('change', (e) => {
    setLang(e.target.value);
  });

  // STT model selector — fetch current model on open, switch on change
  (async () => {
    try {
      const r = await fetch('/api/stt-model');
      if (r.ok) {
        const d = await r.json();
        if (d.model) {
          const sel = document.getElementById('stt-model-select');
          if (sel) sel.value = d.model;
        }
      }
    } catch (_) {}
  })();

  // Session / history count — refresh when settings opens
  document.getElementById('settings-toggle')?.addEventListener('click', async () => {
    try {
      const sess = await _getActiveSession();
      const r = await fetch(`/api/history?session=${encodeURIComponent(sess)}&limit=1000`);
      if (r.ok) {
        const d = await r.json();
        const el = document.getElementById('history-count');
        if (el) el.textContent = `${d.count} 条消息`;
      }
    } catch (_) {}
  });

  // Clear memory button
  document.getElementById('clear-memory-btn')?.addEventListener('click', async () => {
    const btn = document.getElementById('clear-memory-btn');
    const orig = btn.textContent;
    btn.textContent = '清除中...';
    btn.disabled = true;
    try {
      const sess = await _getActiveSession();
      const r = await fetch(`/api/history?session=${encodeURIComponent(sess)}`, {method: 'DELETE'});
      const d = await r.json();
      if (d.ok) {
        btn.textContent = '✅ 已清除';
        const el = document.getElementById('history-count');
        if (el) el.textContent = '0 条消息';
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
      } else {
        btn.textContent = '❌ 失败';
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
      }
    } catch (_) {
      btn.textContent = '❌ 网络错误';
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
    }
  });

  document.getElementById('stt-model-select').addEventListener('change', async (e) => {
    const model = e.target.value;
    const statusRow = document.getElementById('stt-model-status-row');
    const statusEl = document.getElementById('stt-model-status');
    statusRow.style.display = 'flex';
    statusEl.textContent = `正在加载 ${model} 模型...`;
    statusEl.style.color = 'var(--text-muted)';
    try {
      const r = await fetch('/api/stt-model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model}),
      });
      const d = await r.json();
      if (d.ok) {
        statusEl.textContent = `✅ ${model} 已加载 (${d.backend})`;
        statusEl.style.color = 'var(--success, #22c55e)';
      } else {
        statusEl.textContent = `❌ 失败: ${d.error}`;
        statusEl.style.color = 'var(--error)';
      }
    } catch (err) {
      statusEl.textContent = `❌ 网络错误`;
      statusEl.style.color = 'var(--error)';
    }
  });

  // Continuous mode toggle
  dom.continuousMode.addEventListener('change', (e) => {
    S.continuousMode = e.target.checked;
    dom.toggleKnob.style.transform = e.target.checked ? 'translateX(22px)' : 'none';
    dom.toggleKnob.parentElement.querySelector('span').style.background =
      e.target.checked ? 'var(--accent)' : 'var(--bg-surface)';
    const label = document.getElementById('voice-continuous-label');
    if (label) label.style.opacity = e.target.checked ? '1' : '0';
  });

  // Paste images
  document.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        e.preventDefault();
        const file = item.getAsFile();
        if (file) addAttachment(file);
      }
    }
  });

  // iOS: unlock audio on first user interaction
  document.addEventListener('touchstart', unlockAudio, { once: true });
  document.addEventListener('click', unlockAudio, { once: true });

  // Voice WS keepalive
  setInterval(() => {
    if (S.voiceWs?.readyState === 1) S.voiceWs.send(JSON.stringify({ type: 'ping' }));
  }, 30000);

  // Pre-warm mic on first user interaction (iOS)
  document.addEventListener('click', prewarmMic, { once: true });
  document.addEventListener('touchstart', prewarmMic, { once: true });

  // ── Main init logic ──
  (async () => {
    if (window.location.protocol === 'http:') {
      const isLocal = /^(localhost|127\.0\.0\.1)$/i.test(window.location.hostname);
      const isMobile = /iPhone|iPad|iPod|Android|Mobile/i.test(navigator.userAgent);
      if (isMobile) {
        window.location.href = '/chat';
        return;
      }
      if (!isLocal) {
        const banner = document.createElement('div');
        banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;padding:12px 20px;font-size:14px;display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;text-align:center';
        banner.innerHTML = '⚠️ 当前为 HTTP 模式，语音功能受限。'
          + '<a href="/chat" style="color:#fbbf24;font-weight:600;text-decoration:underline">文字聊天版</a>'
          + '<span style="color:#cbd5e1">|</span>'
          + '<a href="/setup" style="color:#fbbf24;font-weight:600;text-decoration:underline">安装证书启用完整版</a>'
          + '<button onclick="this.parentElement.remove()" style="background:rgba(255,255,255,.2);border:none;color:#fff;border-radius:4px;padding:2px 10px;cursor:pointer;margin-left:8px">✕</button>';
        document.body.prepend(banner);
      }
    }

    const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(window.location.origin);
    const maxRetries = isLocalhost ? 3 : 1;

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      if (attempt > 0) await new Promise(r => setTimeout(r, 2000));
      const info = await testConnection(window.location.origin);
      if (info) {
        S.serverUrl = window.location.origin;
        S.token = info.token || '';
        localStorage.setItem('oc_server', S.serverUrl);
        localStorage.setItem('oc_token', S.token);
        showChat(info);
        return;
      }
    }

    const saved = localStorage.getItem('oc_server');
    if (saved) {
      let url = saved;
      if (window.location.protocol === 'https:' && url.startsWith('http://')) {
        url = url.replace('http://', 'https://');
      }
      const savedInfo = await testConnection(url);
      if (savedInfo) {
        S.serverUrl = url;
        S.token = localStorage.getItem('oc_token') || '';
        localStorage.setItem('oc_server', url);
        showChat(savedInfo);
        return;
      }
    }

    showSetup();
  })();

  // ── 团队状态实时通知 ──
  let _teamNotifiedIds = new Set();
  let _teamProgressIds = new Set();
  setInterval(async () => {
    try {
      const r = await fetch(getBaseUrl() + '/api/agents/teams');
      const d = await r.json();
      for (const team of (d.teams || [])) {
        const tid = team.team_id;

        // 执行中：显示进度条（只显示一次）
        if ((team.status === 'executing' || team.status === 'planning') && !_teamProgressIds.has(tid)) {
          _teamProgressIds.add(tid);
          hideWelcome();
          const progressEl = document.createElement('div');
          progressEl.id = `team-progress-${tid}`;
          progressEl.className = 'msg ai';
          progressEl.innerHTML = `
            <div class="msg-avatar">🦞</div>
            <div class="msg-body">
              <div class="team-progress-card">
                <div class="tpc-header">👔 ${team.name} · ${Object.keys(team.agents||{}).length}人团队</div>
                <div class="tpc-bar"><div class="tpc-fill" style="width:0%"></div></div>
                <div style="font-size:10px;color:var(--text-muted);margin-bottom:6px">预计 1-3 分钟完成，每个成员的工作进度实时显示 ↓</div>
                <div class="tpc-detail" id="tpc-detail-${tid}">正在分配任务...</div>
              </div>
            </div>`;
          dom.messages.appendChild(progressEl);
          scrollToBottom();
        }

        // 更新进度（直播式）
        if ((team.status === 'executing') && _teamProgressIds.has(tid)) {
          const tasks = team.tasks || [];
          const done = tasks.filter(t => t.status === 'done').length;
          const pct = tasks.length ? Math.round(done / tasks.length * 100) : 0;
          const fill = document.querySelector(`#team-progress-${tid} .tpc-fill`);
          const detail = document.getElementById(`tpc-detail-${tid}`);
          if (fill) fill.style.width = pct + '%';
          if (detail) {
            const agents = Object.values(team.agents || {});
            // 直播式：显示每个 Agent 的实时工作内容
            let html = '';
            for (const a of agents) {
              const task = tasks.find(t => t.agent_id === (a.id || ''));
              const icon = a.status === 'done' ? '✅' : a.status === 'working' ? '🔄' : '⏳';
              const partial = task?.partial_result || task?.result || '';
              const preview = partial ? partial.substring(0, 60).replace(/[#*\n]/g, ' ') + '...' : '';

              html += `<div class="tpc-agent-live">
                <span class="tpc-al-head">${a.avatar} ${a.name} ${icon}</span>
                ${a.status === 'working' && preview ? `<div class="tpc-al-typing">${preview}<span class="tpc-cursor">|</span></div>` : ''}
                ${a.status === 'done' && preview ? `<div class="tpc-al-done">${preview}</div>` : ''}
              </div>`;
            }
            detail.innerHTML = html;
            scrollToBottom();
          }
        }

        // 完成：显示结果卡片
        if (team.status === 'done' && !_teamNotifiedIds.has(tid)) {
          _teamNotifiedIds.add(tid);
          window._lastCompletedTeamId = tid;  // 隐式反馈追踪
          // 移除进度条
          const progressEl = document.getElementById(`team-progress-${tid}`);
          if (progressEl) progressEl.remove();

          // 获取结果+项目文件
          const rr = await fetch(getBaseUrl() + '/api/agents/team/' + tid + '/result');
          const rd = await rr.json();
          const result = rd.result || '(无结果)';
          const files = rd.project_files || [];
          const projectId = rd.project_id || '';
          const downloadUrl = rd.download_url || '';

          // 构建文件列表 HTML
          let filesHtml = '';
          if (files.length) {
            filesHtml = '<div class="trc-files">' +
              files.slice(0, 8).map(f => `<div class="trc-file">📄 ${f.filename}</div>`).join('') +
              (files.length > 8 ? `<div class="trc-file">... 共${files.length}个文件</div>` : '') +
              '</div>';
          }

          hideWelcome();
          const card = document.createElement('div');
          card.className = 'msg ai';
          card.innerHTML = `
            <div class="msg-avatar">🦞</div>
            <div class="msg-body">
              <div class="team-result-card">
                <div class="trc-header">✅ ${team.name}完成！</div>
                <div class="trc-summary" id="trc-sum-${tid}">${renderMarkdown(result.substring(0, 600))}</div>
                ${result.length > 600 ? `<button class="trc-expand" onclick="var el=document.getElementById('trc-sum-${tid}');if(!el.classList.contains('expanded')){el.innerHTML=this.dataset.full;el.classList.add('expanded');this.textContent='收起 ↑'}else{el.innerHTML=this.dataset.short;el.classList.remove('expanded');this.textContent='展开全文 ↓'}" data-short="${renderMarkdown(result.substring(0,600)).replace(/"/g,'&quot;')}" data-full="${renderMarkdown(result).replace(/"/g,'&quot;')}">展开全文 ↓ (${result.length}字)</button>` : ''}
                ${filesHtml}
                <div class="trc-actions">
                  ${downloadUrl ? `<button onclick="window.location.href='${downloadUrl}'">📥 下载 ZIP</button>` : ''}
                  ${projectId ? `<button onclick="window.open('/report/${projectId}','_blank')">🔗 分享报告</button>` : ''}
                  <button onclick="navigator.clipboard.writeText(${JSON.stringify(result.substring(0, 2000))})">📋 复制</button>
                  ${projectId ? `<button onclick="navigator.clipboard.writeText(location.origin+'/report/${projectId}').then(()=>this.textContent='已复制链接!')">📤 复制链接</button>` : ''}
                  <button onclick="window._shareToWechat('${tid}',${JSON.stringify(result.substring(0,200))})" title="发送摘要到微信">💬 发微信</button>
                </div>
                <div class="trc-feedback" id="trc-fb-${tid}">
                  <span style="font-size:11px;color:var(--text-muted)">这次结果怎么样？</span>
                  <button class="trc-fb-btn trc-fb-good" onclick="window._submitTeamFeedback('${tid}','good',this)">👍 满意</button>
                  <button class="trc-fb-btn trc-fb-bad" onclick="window._submitTeamFeedback('${tid}','bad',this)">👎 不满意</button>
                  <button class="trc-fb-btn" onclick="window._submitTeamFeedbackDetail('${tid}',this)">💬 具体意见</button>
                </div>
              </div>
            </div>`;
          dom.messages.appendChild(card);
          scrollToBottom();
        }
      }
    } catch (e) { /* silent */ }
  }, 4000);
}

// ── 团队反馈系统 ──
window._submitTeamFeedback = async function(teamId, rating, btn) {
  const fbEl = document.getElementById('trc-fb-' + teamId);
  if (!fbEl) return;
  try {
    const r = await fetch(getBaseUrl() + '/api/agents/team/' + teamId + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, comment: '' }),
    });
    const d = await r.json();
    if (d.ok) {
      fbEl.innerHTML = rating === 'good'
        ? '<span style="color:var(--success);font-size:12px">👍 已记录！Agent 会继续保持</span>'
        : '<span style="color:var(--warning);font-size:12px">👎 已记录！Agent 下次会改进</span>';
    }
  } catch (e) { console.warn('feedback error', e); }
};

window._submitTeamFeedbackDetail = function(teamId, btn) {
  const fbEl = document.getElementById('trc-fb-' + teamId);
  if (!fbEl) return;
  fbEl.innerHTML = `
    <input type="text" id="trc-fb-input-${teamId}" placeholder="请说说哪里需要改进…" style="flex:1;padding:6px 10px;background:var(--bg-surface);color:var(--text-primary);border:1px solid var(--border);border-radius:6px;font-size:12px;font-family:inherit">
    <button class="trc-fb-btn" onclick="window._sendFeedbackComment('${teamId}')" style="white-space:nowrap">发送</button>
  `;
  fbEl.style.display = 'flex';
  fbEl.style.gap = '6px';
  const input = document.getElementById('trc-fb-input-' + teamId);
  if (input) { input.focus(); input.addEventListener('keydown', e => { if (e.key === 'Enter') window._sendFeedbackComment(teamId); }); }
};

window._sendFeedbackComment = async function(teamId) {
  const input = document.getElementById('trc-fb-input-' + teamId);
  const fbEl = document.getElementById('trc-fb-' + teamId);
  if (!input || !fbEl) return;
  const comment = input.value.trim();
  if (!comment) return;
  try {
    const r = await fetch(getBaseUrl() + '/api/agents/team/' + teamId + '/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: 'bad', comment }),
    });
    const d = await r.json();
    if (d.ok) {
      fbEl.innerHTML = '<span style="color:var(--accent);font-size:12px">💬 反馈已记录，Agent 下次会注意</span>';
    }
  } catch (e) { console.warn('feedback error', e); }
};

// ── 微信分享 ──
window._shareToWechat = async function(teamId, summary) {
  const contact = prompt('发送给谁？（输入微信联系人名称）');
  if (!contact || !contact.trim()) return;
  const text = (summary || '').substring(0, 200) + '\n\n-- 十三香小龙虾AI工作队';
  try {
    const r = await fetch(getBaseUrl() + '/api/wechat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact: contact.trim(), message: text }),
    });
    const d = await r.json();
    if (d.ok || d.success) {
      alert('已发送给 ' + contact);
    } else {
      alert('发送失败：' + (d.error || '微信未连接'));
    }
  } catch (e) {
    alert('发送失败，请检查微信连接');
  }
};
