import { S, fn, dom, t, $, $$, getBaseUrl, escapeHtml, setLang, currentLang, isLocalOrPrivateHost } from '/js/state.js';
import { petSetVisualState, petSetSubtitle, petGetSkin } from '/js/pet-bridge.js';

/** 与桌面指令 / 桌宠皮肤一致：默认 eve 用品牌 🦞，换皮后用机器人系区分 */
function assistantAvatarEmoji(isDesktop) {
  if (isDesktop) return '🖥️';
  const skin = petGetSkin();
  if (skin === 'walle') return '🦾';
  if (skin === 'orbit') return '🛰️';
  return '🦞';
}

/** P0: 助手气泡头像 — 优先消息内 avatar / 槽位元数据 */
function resolveAssistantBubbleAvatar(msg) {
  if (msg.role === 'user') return '👤';
  if (msg.avatar) return msg.avatar;
  if (msg.slot_id && window.__slotManager?.metaFromSlot && window.__slotManager?.getSlotById) {
    const slot = window.__slotManager.getSlotById(msg.slot_id);
    if (slot) {
      const meta = window.__slotManager.metaFromSlot(slot);
      if (meta?.avatar) return meta.avatar;
    }
  }
  return assistantAvatarEmoji(!!msg.desktop);
}

// ═══════════════════════════════════════════════════
// USAGE BADGE
// ═══════════════════════════════════════════════════

/** 查询用量并更新输入框旁的用量指示器 */
async function refreshUsageBadge() {
  const badge = document.getElementById('usage-badge');
  if (!badge) return;
  try {
    const r = await fetch(getBaseUrl() + '/api/my-usage', {
      headers: { 'X-API-Token': S.token || '' },
    });
    const d = await r.json();
    // 本地模式（未连代理）不显示
    if (!d.ok || d.tier === 'local') {
      badge.style.display = 'none';
      // 解除可能的禁用状态
      if (dom.msgInput) dom.msgInput.disabled = false;
      return;
    }
    const remaining = d.daily_remaining ?? -1;
    const limit = d.daily_limit ?? -1;
    if (limit < 0 || remaining < 0) {
      // 无限制
      badge.style.display = 'none';
      return;
    }
    badge.style.display = '';
    badge.className = 'usage-badge';
    if (remaining <= 0) {
      badge.textContent = '今日额度已用完';
      badge.classList.add('danger');
      badge.title = `今日已用 ${d.daily_used || 0}/${limit} 次`;
      // 禁用输入
      if (dom.msgInput) { dom.msgInput.disabled = true; dom.msgInput.placeholder = '今日额度已用完'; }
      if (dom.sendBtn) dom.sendBtn.disabled = true;
    } else if (remaining <= 10) {
      badge.textContent = `剩余 ${remaining} 次`;
      badge.classList.add('warn');
      badge.title = `今日已用 ${d.daily_used || 0}/${limit} 次`;
      if (dom.msgInput) { dom.msgInput.disabled = false; dom.msgInput.placeholder = '有什么需要帮忙的？'; }
    } else {
      badge.textContent = `剩余 ${remaining} 次`;
      badge.title = `今日已用 ${d.daily_used || 0}/${limit} 次`;
      if (dom.msgInput) { dom.msgInput.disabled = false; dom.msgInput.placeholder = '有什么需要帮忙的？'; }
    }
  } catch (e) {
    // 查询失败不影响正常使用
    badge.style.display = 'none';
  }
}

// ═══════════════════════════════════════════════════
// CONNECTION & SETUP
// ═══════════════════════════════════════════════════

async function testConnection(url) {
  try {
    const opts = {};
    try { opts.signal = AbortSignal.timeout(8000); } catch(e) {}  // 兼容旧浏览器
    const r = await fetch(`${url}/api/server-info`, opts);
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

  // AI 后端状态检测：连接成功后检查 AI 是否可用
  fetch(S.serverUrl + '/api/ai/status', {headers: {'X-API-Token': S.token}})
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var badge = document.getElementById('ws-latency-badge');
      if (!badge) return;
      if (d.available === false || d.providers_online === 0) {
        dom.statusDot.className = 'status-dot warning';
        badge.textContent = 'AI 离线';
        badge.title = '所有 AI 平台不可用，请检查设置';
        badge.style.color = 'var(--warning, #f59e0b)';
      } else {
        badge.style.color = '';
      }
    }).catch(function() {});

  // 首次使用提示 Ctrl+K 快捷键（只显示一次）
  if (!localStorage.getItem('oc_ctrlk_tip')) {
    localStorage.setItem('oc_ctrlk_tip', '1');
    setTimeout(function() {
      if (window.ocToast) {
        window.ocToast.info('按 Ctrl+K 可随时快速搜索所有功能', 5000);
      }
    }, 3000);
  }

  // 用量查询
  refreshUsageBadge();
}

function showSetup() {
  // 局域网/本机访问不跳setup（直接留在聊天页）
  if (isLocalOrPrivateHost(location.hostname)) {
    S.serverUrl = location.origin;
    localStorage.setItem('oc_server', S.serverUrl);
    return;
  }
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
      // 503 是永久性错误（后端未配置），不重试
      if (lastResp.status === 503) return lastResp;
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

  // ── 槽位分流：非 chat 槽走专用通道 ──
  const activeSlot = window.__slotManager?.getActiveSlot?.();
  if (activeSlot && text.trim() && S.attachments.length === 0) {
    if (activeSlot.slot_type === 'agent' || activeSlot.slot_type === 'team') {
      const t = text.trim();
      dom.msgInput.value = '';
      autoResize(dom.msgInput);
      if (activeSlot.slot_type === 'agent') {
        return window.__slotManager.sendAgentMessage(t);
      }
      return window.__slotManager.sendTeamMessage(t);
    }
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

  // 显示思考状态
  _showAIStatus('thinking', 'AI 正在思考...');

  try {
    const body = {
      messages: buildMessages(),
      stream: true,
      model: window._currentModel || 'auto',  // 传给后端选择模型
      session_id: window._currentSessionId || null,
    };
    // 附带用户身份（计费+多用户隔离）
    const _chatHeaders = { 'Content-Type': 'application/json' };
    const _billingPhone = localStorage.getItem('billing_phone');
    if (_billingPhone) _chatHeaders['X-User-Phone'] = _billingPhone;

    const resp = await _fetchRetry(`${getBaseUrl()}/api/chat`, {
      method: 'POST',
      headers: _chatHeaders,
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      if (resp.status === 429) throw new Error('AI 正在忙，请稍等几秒再试');
      if (resp.status === 401) throw new Error('需要配置 AI，请到设置中填写 API Key');
      // 尝试读取服务端错误信息，映射为友好中文
      let errMsg = '连接异常，请检查网络';
      try {
        const errBody = await resp.json();
        const raw = errBody.error || errBody.detail || '';
        // 映射常见技术错误为友好提示
        if (raw.includes('API') || raw.includes('key') || raw.includes('auth'))
          errMsg = '需要配置 AI 服务，请到设置中填写';
        else if (raw.includes('timeout') || raw.includes('connect'))
          errMsg = '网络连接超时，请稍后重试';
        else if (raw.includes('繁忙') || raw.includes('busy') || raw.includes('rate'))
          errMsg = 'AI 正在忙，请稍等几秒再试';
        else if (raw.includes('启动') || raw.includes('starting'))
          errMsg = '服务正在启动，请稍后再试';
        else if (raw)
          errMsg = raw;  // 如果已是中文友好消息则保留
      } catch (_) {}
      if (resp.status === 503 && errMsg === '连接异常，请检查网络') errMsg = '服务正在启动，请稍后再试';
      throw new Error(errMsg);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let fullText = '';
    let buffer = '';
    let _firstChunk = true;
    let _desktopMode = false;
    let _toolStep = 0;

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
          // ── SSE 流中的错误消息：转为友好提示 ──
          if (parsed.error) {
            _hideAIStatus();
            const friendlyErr = '<div class="ai-error-card">'
              + '<div class="ai-error-icon">&#x26A0;&#xFE0F;</div>'
              + '<div class="ai-error-title">AI 暂时不可用</div>'
              + '<div class="ai-error-desc">请稍后重试，或检查网络连接</div>'
              + '<button class="ai-error-btn" onclick="sendQuick(window._lastUserMsg||\'你好\')">重新发送</button>'
              + '</div>';
            fullText += friendlyErr;
            updateStreamingEl(aiEl, fullText);
            continue;
          }
          const delta = parsed.choices?.[0]?.delta?.content;
          if (delta != null && delta !== '') {
            // 首个 chunk：从"思考"切换到"回复"
            if (_firstChunk) {
              _firstChunk = false;
              _hideAIStatus();
            }

            // ── 结构化错误处理：后端 __ERROR__xxx 转为友好引导卡片 ──
            if (delta.startsWith('__ERROR__')) {
              const errCode = delta.replace('__ERROR__', '').trim();
              let errHtml = '';
              if (errCode === 'no_api_key') {
                errHtml = '<div class="ai-error-card">'
                  + '<div class="ai-error-icon">&#x2699;&#xFE0F;</div>'
                  + '<div class="ai-error-title">AI 服务未配置</div>'
                  + '<div class="ai-error-desc">首次使用需要配置 AI 服务，只需 30 秒即可完成</div>'
                  + '<button class="ai-error-btn" onclick="document.querySelector(\'[data-page=settings]\')?.click();window._openSettingsTab?.(\'ai\')">打开设置</button>'
                  + '</div>';
              } else if (errCode === 'ai_unavailable') {
                errHtml = '<div class="ai-error-card">'
                  + '<div class="ai-error-icon">&#x26A0;&#xFE0F;</div>'
                  + '<div class="ai-error-title">AI 暂时不可用</div>'
                  + '<div class="ai-error-desc">所有 AI 平台暂时无法连接，请检查网络或稍后重试</div>'
                  + '<button class="ai-error-btn" onclick="location.reload()">重新连接</button>'
                  + '</div>';
              } else if (errCode === 'rate_limited') {
                errHtml = '<div class="ai-error-card">'
                  + '<div class="ai-error-icon">&#x23F3;</div>'
                  + '<div class="ai-error-title">请求过于频繁</div>'
                  + '<div class="ai-error-desc">AI 正在处理其他请求，请稍等几秒后重试</div>'
                  + '<button class="ai-error-btn" onclick="this.closest(\'.ai-error-card\').remove()">知道了</button>'
                  + '</div>';
              } else {
                errHtml = '<div class="ai-error-card">'
                  + '<div class="ai-error-icon">&#x274C;</div>'
                  + '<div class="ai-error-title">出现问题</div>'
                  + '<div class="ai-error-desc">' + errCode + '</div>'
                  + '</div>';
              }
              // 在错误卡片下方添加快捷重试入口
              errHtml += '<div class="ai-error-actions" style="display:flex;gap:8px;justify-content:center;margin-top:12px;flex-wrap:wrap">'
                + '<button class="ai-error-btn" style="background:transparent;border:1px solid var(--border);font-size:12px;padding:6px 14px" onclick="sendQuick(\'你好\')">&#x1F4AC; 试试对话</button>'
                + '<button class="ai-error-btn" style="background:transparent;border:1px solid var(--border);font-size:12px;padding:6px 14px" onclick="sendQuick(\'现在几点了\')">&#x23F0; 查时间</button>'
                + '<button class="ai-error-btn" style="background:transparent;border:1px solid var(--border);font-size:12px;padding:6px 14px" onclick="sendQuick(\'今天天气\')">&#x1F324; 查天气</button>'
                + '</div>';
              fullText += errHtml;
              updateStreamingEl(aiEl, fullText);
              _hideAIStatus();
              continue;
            }

            fullText += delta;

            // 检测工具执行状态（后端注入的提示）
            if (delta.includes('秒后操控桌面')) {
              // 3秒倒计时警告 — 醒目提示
              const sec = delta.match(/(\d)/);
              _showAIStatus('countdown', '⏳ AI 将在 ' + (sec ? sec[1] : '?') + ' 秒后操控桌面，请勿触碰鼠标键盘');
            } else if (delta.includes('正在打开') || delta.includes('正在按键') || delta.includes('正在输入') || delta.includes('正在点击') || delta.includes('正在截屏')) {
              _toolStep++;
              _showAIStatus('desktop', '⚠️ ' + delta.trim() + ' (第' + _toolStep + '步)');
            } else if (delta.includes('正在搜索') || delta.includes('正在执行 web_open')) {
              _showAIStatus('executing', '🌐 ' + delta.trim());
            } else if (delta.includes('正在查天气') || delta.includes('正在查时间')) {
              _showAIStatus('executing', delta.trim());
            } else if (delta.includes('正在组建团队')) {
              _showAIStatus('executing', '👥 ' + delta.trim());
            } else if (delta.includes('正在执行 create_excel') || delta.includes('正在执行 create_document')) {
              _showAIStatus('executing', '📄 ' + delta.trim());
            }

            updateStreamingEl(aiEl, fullText);
            petSetSubtitle(fullText.slice(0, 160));
          }
        } catch {}
      }
    }

    // 清除所有状态
    _hideAIStatus();
    _hideDesktopOverlay();

    aiMsg.content = fullText;
    finalizeStreamingEl(aiEl, fullText);

    if (fullText.trim()) speakText(fullText);
    else {
      petSetVisualState('idle');
      petSetSubtitle('');
    }
  } catch (e) {
    _hideAIStatus();
    _hideDesktopOverlay();
    console.error('Chat error:', e);
    aiMsg.content = '⚠️ ' + (e.message || '出了点问题，请稍后再试');
    finalizeStreamingEl(aiEl, aiMsg.content);
    petSetVisualState('error');
    petSetSubtitle('');
  }

  S.isSending = false;
  updateSendBtn();
  refreshUsageBadge();
}

async function speakText(text, forcePlay) {
  // 全局语音开关：关闭时不自动播报（手动点击 forcePlay=true 时仍播放）
  if (!forcePlay && localStorage.getItem('oc_tts_muted') === '1') return;
  try {
    // 前端彻底清理（v6.1：和后端 clean_for_speech 同步，白名单策略）
    let cleanText = text
      // 结构化垃圾
      .replace(/\[TOOL_CALL\][\s\S]*?\[\/TOOL_CALL\]/gi, '')
      .replace(/```[\s\S]*?```/g, '')
      .replace(/`[^`]+`/g, '')
      // URL 全部变体
      .replace(/https?:\/\/\S+/g, '')
      .replace(/\/\/\S+/g, '')
      .replace(/www\.\S+/g, '')
      .replace(/\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?/g, '')  // IP
      .replace(/\S*%[0-9A-Fa-f]{2}\S*/g, '')
      .replace(/\S+\.(com|cn|io|org|net|ai|app|html|php|asp|xyz|dev|tech)\S*/g, '')
      .replace(/\S+\/\S+\/\S+/g, '')
      // JSON / 字典
      .replace(/\{[^}]*\}/g, '')
      .replace(/\[[^\]]{15,}\]/g, '')
      // Markdown
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/[*#_~`|>]+/g, '')
      // 英文技术内容（核心！）
      .replace(/[a-zA-Z_]\w*\s*=\s*\S+/g, '')             // key=value
      .replace(/[a-zA-Z_]\w*\([^)]*\)/g, '')               // func(args)
      .replace(/[a-zA-Z_]\w*\.[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*/g, '')  // module.method
      .replace(/[a-zA-Z_][a-zA-Z0-9_]{3,}/g, '')              // 4+字母英文词（不用\b，中英交界不生效）
      .replace(/\b[a-zA-Z]{2,3}\b/g, function(m) {          // 2-3字母词白名单
        var ok = 'AI,OK,IT,VS,IP,km,mm,cm,kg,GB,MB,KB,CEO,CTO,CFO,COO,CMO,VIP,App,API,KOL,ROI,SEM,SEO,KPI,PPT,PDF,TOP,DIY,GPS,USB,LED,Pro,Max';
        return ok.indexOf(m) >= 0 || ok.indexOf(m.toUpperCase()) >= 0 ? m : '';
      })
      // 孤立符号
      .replace(/(?<![<>!])=(?!=)/g, '')
      .replace(/&\S+/g, '')
      .replace(/\(\s*\)/g, '')
      .replace(/\[\s*\]/g, '')
      // Emoji
      .replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{27BF}\u{1FA00}-\u{1FAFF}]/gu, '')
      // 单位转换
      .replace(/(\d+)\s*km\/h/g, '$1公里每小时')
      // 格式清理
      .replace(/\n+/g, '。')
      .replace(/\s{2,}/g, ' ')
      .replace(/[。，、；：]{2,}/g, '。')
      .trim();
    // 如果清理后只剩标点或极短，不读
    var meaningfulChars = cleanText.replace(/[。，、；：！？,.;:!?\s\d]+/g, '');
    if (meaningfulChars.length < 2) return;
    // AbortController: 静音按钮可中止此请求
    const _ttsAc = new AbortController();
    window.__ttsAbort = _ttsAc;
    const resp = await fetch(`${getBaseUrl()}/api/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: cleanText.slice(0, 500) }),
      signal: _ttsAc.signal,
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
            fn.queueVoiceAudio(
              parsed.audio,
              parsed.sample_rate || 24000,
              parsed.format || 'pcm',
            );
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

/** 团队完成卡片：DOM 构建，避免 innerHTML + 内联 onclick 导致脚本片段泄露到正文 */
function _mountTeamResultCard({ tid, teamName, result, files, projectId, downloadUrl }) {
  const card = document.createElement('div');
  card.className = 'msg ai';

  const av = document.createElement('div');
  av.className = 'msg-avatar';
  av.textContent = assistantAvatarEmoji(false);

  const body = document.createElement('div');
  body.className = 'msg-body';

  const trc = document.createElement('div');
  trc.className = 'team-result-card';

  const header = document.createElement('div');
  header.className = 'trc-header';
  header.textContent = `✅ ${teamName}完成！`;

  const sumEl = document.createElement('div');
  sumEl.className = 'trc-summary';
  sumEl.id = 'trc-sum-' + tid;
  const shortHtml = renderMarkdown(result.substring(0, 600));
  const fullHtml = renderMarkdown(result);
  sumEl.innerHTML = shortHtml;

  trc.appendChild(header);
  trc.appendChild(sumEl);

  if (result.length > 600) {
    const exp = document.createElement('button');
    exp.type = 'button';
    exp.className = 'trc-expand';
    let expanded = false;
    exp.textContent = `展开全文 ↓ (${result.length}字)`;
    exp.addEventListener('click', () => {
      expanded = !expanded;
      sumEl.innerHTML = expanded ? fullHtml : shortHtml;
      sumEl.classList.toggle('expanded', expanded);
      exp.textContent = expanded ? '收起 ↑' : `展开全文 ↓ (${result.length}字)`;
    });
    trc.appendChild(exp);
  }

  if (files && files.length) {
    const filesWrap = document.createElement('div');
    filesWrap.className = 'trc-files';
    files.slice(0, 8).forEach(f => {
      const row = document.createElement('div');
      row.className = 'trc-file';
      row.textContent = '📄 ' + (f.filename || '');
      filesWrap.appendChild(row);
    });
    if (files.length > 8) {
      const row = document.createElement('div');
      row.className = 'trc-file';
      row.textContent = '... 共' + files.length + '个文件';
      filesWrap.appendChild(row);
    }
    trc.appendChild(filesWrap);
  }

  const actions = document.createElement('div');
  actions.className = 'trc-actions';

  if (downloadUrl) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = '📥 下载 ZIP';
    b.addEventListener('click', () => { window.location.href = downloadUrl; });
    actions.appendChild(b);
  }
  if (projectId) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = '🔗 分享报告';
    b.addEventListener('click', () =>
      window.open('/report/' + encodeURIComponent(projectId), '_blank'));
    actions.appendChild(b);
  }

  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.textContent = '📋 复制';
  copyBtn.addEventListener('click', async () => {
    const text = result.substring(0, 2000);
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        window._fallbackCopy(text);
      }
      copyBtn.textContent = '已复制!';
    } catch (e) {
      window._fallbackCopy(text);
      copyBtn.textContent = '已复制!';
    }
  });
  actions.appendChild(copyBtn);

  if (projectId) {
    const linkBtn = document.createElement('button');
    linkBtn.type = 'button';
    linkBtn.textContent = '📤 复制链接';
    linkBtn.addEventListener('click', async () => {
      const url = location.origin + '/report/' + encodeURIComponent(projectId);
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(url);
        } else {
          window._fallbackCopy(url);
        }
        linkBtn.textContent = '已复制链接!';
      } catch (e) {
        window._fallbackCopy(url);
        linkBtn.textContent = '已复制链接!';
      }
    });
    actions.appendChild(linkBtn);
  }

  const wxBtn = document.createElement('button');
  wxBtn.type = 'button';
  wxBtn.textContent = '💬 发微信';
  wxBtn.title = '发送摘要到微信';
  const preview = result.substring(0, 200);
  wxBtn.addEventListener('click', () => window._shareToWechat(tid, preview));
  actions.appendChild(wxBtn);

  trc.appendChild(actions);

  const fb = document.createElement('div');
  fb.className = 'trc-feedback';
  fb.id = 'trc-fb-' + tid;

  const hint = document.createElement('span');
  hint.style.fontSize = '11px';
  hint.style.color = 'var(--text-muted)';
  hint.textContent = '这次结果怎么样？';

  const good = document.createElement('button');
  good.className = 'trc-fb-btn trc-fb-good';
  good.type = 'button';
  good.textContent = '👍 满意';
  good.addEventListener('click', () => window._submitTeamFeedback(tid, 'good', good));

  const bad = document.createElement('button');
  bad.className = 'trc-fb-btn trc-fb-bad';
  bad.type = 'button';
  bad.textContent = '👎 不满意';
  bad.addEventListener('click', () => window._submitTeamFeedback(tid, 'bad', bad));

  const detail = document.createElement('button');
  detail.className = 'trc-fb-btn';
  detail.type = 'button';
  detail.textContent = '💬 具体意见';
  detail.addEventListener('click', () => window._submitTeamFeedbackDetail(tid, detail));

  fb.appendChild(hint);
  fb.appendChild(good);
  fb.appendChild(bad);
  fb.appendChild(detail);

  trc.appendChild(fb);

  body.appendChild(trc);
  card.appendChild(av);
  card.appendChild(body);
  dom.messages.appendChild(card);
  // 主对话里 /api/agents/teams 轮询到的完成结果：走槽位同款分段 TTS（需已 initSlotManager 注册 fn.speakTeamTts）
  const plain = typeof result === 'string' ? result.trim() : '';
  if (plain.length >= 2 && fn.speakTeamTts) {
    fn.speakTeamTts(plain, '');
  }
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
  const avatar = msg.role === 'user' ? '👤' : resolveAssistantBubbleAvatar(msg);
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

  // 时间戳
  const now = new Date();
  const timeStr = String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0');

  div.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-body">
      ${attachHtml}
      <div class="msg-text">${textHtml}${voiceBadge}</div>
      <div class="msg-meta">
        <span class="msg-time">${timeStr}</span>
        ${msg.role === 'assistant' && !streaming ? '<button class="msg-action-btn msg-regen-btn" title="重新生成">🔄</button>' : ''}
      </div>
    </div>`;

  dom.messages.appendChild(div);

  // 重新生成按钮事件
  const regenBtn = div.querySelector('.msg-regen-btn');
  if (regenBtn) {
    regenBtn.addEventListener('click', () => {
      // 找到这条 AI 消息之前的最后一条用户消息
      const idx = S.messages.indexOf(msg);
      const prevUser = idx > 0 ? S.messages[idx - 1] : null;
      if (prevUser && prevUser.role === 'user' && prevUser.content) {
        // 删除当前 AI 回复
        S.messages.splice(idx, 1);
        div.remove();
        // 重新发送
        sendTextMessage(prevUser.content);
      }
    });
  }

  if (!streaming) setupLongMessageCollapse(div);
  scrollToBottom();
  return div;
}

/** P0/P1: 语音流式中途由服务端下发槽位头像时更新 DOM 与消息对象 */
function applyVoiceMessageIdentity(msgEl, payload, msgRef) {
  if (!msgEl || !payload) return;
  const av = payload.avatar;
  if (av) {
    const holder = msgEl.querySelector('.msg-avatar');
    if (holder) holder.textContent = av;
  }
  if (msgRef && payload.slot_id) msgRef.slot_id = payload.slot_id;
  if (msgRef && payload.avatar) msgRef.avatar = payload.avatar;
  if (msgRef && payload.display_name) msgRef.display_name = payload.display_name;
}

function updateStreamingEl(el, text) {
  const textEl = el.querySelector('.msg-text');
  if (textEl) textEl.innerHTML = renderMarkdown(text) + '<span style="display:inline-block;width:6px;height:16px;background:var(--accent);margin-left:2px;animation:blink .8s infinite;vertical-align:text-bottom"></span>';
  scrollToBottom();
}

function finalizeStreamingEl(el, text) {
  const textEl = el.querySelector('.msg-text');
  if (textEl) textEl.innerHTML = renderMarkdown(text);
  // 错误消息视觉区分：含错误卡片或错误关键词的消息添加红色边框
  if (text.includes('ai-error-card') || text.includes('__ERROR__') ||
      (text.startsWith('⚠️') && text.length < 200)) {
    el.classList.add('msg-error');
  }
  setupLongMessageCollapse(el);
  // 流式消息结束后补充 meta 区域（时间戳 + 播放 + 重新生成）
  if (el.classList.contains('ai')) {
    let meta = el.querySelector('.msg-meta');
    if (!meta) {
      meta = document.createElement('div');
      meta.className = 'msg-meta';
      const now = new Date();
      meta.innerHTML = `<span class="msg-time">${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}</span>`;
      const body = el.querySelector('.msg-body');
      if (body) body.appendChild(meta);
    }
    // 播放按钮
    if (text && text.trim().length > 5) {
      const playBtn = document.createElement('button');
      playBtn.className = 'msg-action-btn';
      playBtn.title = '朗读';
      playBtn.textContent = '🔊';
      playBtn.onclick = function() { speakText(text, true); };
      meta.appendChild(playBtn);
    }
    // 重新生成按钮
    const regenBtn = document.createElement('button');
    regenBtn.className = 'msg-action-btn msg-regen-btn';
    regenBtn.title = '重新生成';
    regenBtn.textContent = '🔄';
    regenBtn.addEventListener('click', () => {
      const msgs = S.messages;
      // 找最后一条用户消息
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'user' && msgs[i].content) {
          const userText = typeof msgs[i].content === 'string' ? msgs[i].content : '';
          if (userText) {
            // 删除当前 AI 回复
            const aiIdx = msgs.indexOf(msgs.find((m, j) => j > i && m.role === 'assistant'));
            if (aiIdx >= 0) msgs.splice(aiIdx, 1);
            el.remove();
            sendTextMessage(userText);
            break;
          }
        }
      }
    });
    meta.appendChild(regenBtn);
  }
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
  // 浏览器标签标题固定为品牌（避免地址栏/书签里 IP 抢认知）
  try {
    document.title = '52AI 工作队';
  } catch (_) {}

  // 1. Register public functions on fn
  fn.appendMessage = appendMessage;
  window.appendMessage = appendMessage;  // 暴露给 profile.js (会话切换时加载历史消息)
  fn.applyVoiceMessageIdentity = applyVoiceMessageIdentity;
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
        S.continuousMode = false;
        fn.closeVoiceOverlay();
      } else {
        S.continuousMode = true;
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
        if (el) el.textContent = t('settings.historyCount', { n: String(d.count ?? 0) });
      }
    } catch (_) {}
  });

  // Clear memory button
  document.getElementById('clear-memory-btn')?.addEventListener('click', async () => {
    const btn = document.getElementById('clear-memory-btn');
    const orig = btn.textContent;
    btn.textContent = t('settings.clearingMemory');
    btn.disabled = true;
    try {
      const sess = await _getActiveSession();
      const r = await fetch(`/api/history?session=${encodeURIComponent(sess)}`, {method: 'DELETE'});
      const d = await r.json();
      if (d.ok) {
        btn.textContent = t('settings.memoryCleared');
        const el = document.getElementById('history-count');
        if (el) el.textContent = t('settings.historyCount', { n: '0' });
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
      } else {
        btn.textContent = t('settings.clearFailed');
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
      }
    } catch (_) {
      btn.textContent = t('settings.clearNetworkErr');
      setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
    }
  });

  document.getElementById('stt-model-select').addEventListener('change', async (e) => {
    const model = e.target.value;
    const statusRow = document.getElementById('stt-model-status-row');
    const statusEl = document.getElementById('stt-model-status');
    statusRow.style.display = 'flex';
    statusEl.textContent = t('stt.statusLoading', { model });
    statusEl.style.color = 'var(--text-muted)';
    try {
      const r = await fetch('/api/stt-model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model}),
      });
      const d = await r.json();
      if (d.ok) {
        statusEl.textContent = t('stt.statusReady', { model, backend: d.backend || '' });
        statusEl.style.color = 'var(--success, #22c55e)';
      } else {
        statusEl.textContent = t('stt.statusFail', { msg: d.error || '' });
        statusEl.style.color = 'var(--error)';
      }
    } catch (err) {
      statusEl.textContent = t('stt.statusNetworkErr');
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

  // Paste images (only intercept if clipboard has NO text, otherwise let text paste through)
  document.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    // Check if clipboard contains text
    const hasText = Array.from(items).some(i => i.type === 'text/plain');
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          addAttachment(file);
          // Only prevent default if no text content (pure image paste)
          if (!hasText) e.preventDefault();
        }
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
      // 仅对公网 HTTP 尝试升级 HTTPS；局域网/VPN 扫码走 HTTP，避免自签 https 白屏
      if (!isLocalOrPrivateHost(window.location.hostname)) {
        const httpsPort = '9765';
        const httpsUrl = `https://${window.location.hostname}:${httpsPort}${window.location.pathname}`;
        try {
          const ctrl = new AbortController();
          setTimeout(() => ctrl.abort(), 3000);
          const r = await fetch(httpsUrl.replace(/\/[^/]*$/, '/api/bootstrap/status'), {
            signal: ctrl.signal, mode: 'no-cors',
          });
          window.location.href = httpsUrl;
          return;
        } catch (_) {
          console.log('HTTPS not available, staying on HTTP (voice disabled)');
        }
      }
    }

    const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(window.location.origin);
    const isLan = isLocalOrPrivateHost(window.location.hostname);
    const maxRetries = (isLocalhost || isLan) ? 8 : 2;  // 本机和局域网都多试

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      if (attempt > 0) {
        // 前3次每2秒，之后每3秒
        const delay = attempt <= 3 ? 2000 : 3000;
        // 显示等待提示
        const statusEl = document.getElementById('qr-status');
        if (statusEl) statusEl.textContent = `正在等待服务器启动... (${attempt}/${maxRetries})`;
        await new Promise(r => setTimeout(r, delay));
      }
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

    // 连接失败处理
    if (isLocalhost || isLan) {
      // 本机/局域网：直接显示聊天页（服务可能还在启动）
      dom.setupPage.classList.add('hidden');
      dom.chatPage.classList.remove('hidden');
      S.serverUrl = window.location.origin;
      localStorage.setItem('oc_server', S.serverUrl);
    } else {
      showSetup();
    }
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
            <div class="msg-avatar">${assistantAvatarEmoji(false)}</div>
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
            // 按 DAG 层分组显示
            const layers = _buildDAGLayers(tasks, agents);
            let html = '<div class="tpc-dag">';
            for (let li = 0; li < layers.length; li++) {
              const layer = layers[li];
              html += `<div class="tpc-dag-layer">`;
              if (li > 0) html += '<div class="tpc-dag-arrow">↓</div>';
              html += '<div class="tpc-dag-nodes">';
              for (const { agent: a, task } of layer) {
                const tStatus = task?.status || 'pending';
                const icon = tStatus === 'done' ? '✅' : tStatus === 'working' ? '🔄' : '⏳';
                const partial = task?.partial_result || task?.result || '';
                const preview = partial ? partial.substring(0, 50).replace(/[#*\n]/g, ' ') : '';
                const nodeClass = tStatus === 'done' ? 'done' : tStatus === 'working' ? 'working' : '';
                html += `<div class="tpc-dag-node ${nodeClass}">
                  <span class="tpc-dag-head">${a.avatar} ${a.name} ${icon}</span>
                  ${tStatus === 'working' && preview ? `<div class="tpc-dag-typing">${preview}<span class="tpc-cursor">|</span></div>` : ''}
                  ${tStatus === 'done' && preview ? `<div class="tpc-dag-done">${preview}...</div>` : ''}
                </div>`;
              }
              html += '</div></div>';
            }
            // CEO 审核指示
            if (layers.length > 1 && done > 0 && done < tasks.length) {
              html += '<div style="text-align:center;font-size:10px;color:var(--accent);margin:4px 0">💡 CEO 正在审核并协调后续任务</div>';
            }
            html += '</div>';
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

          hideWelcome();
          _mountTeamResultCard({
            tid,
            teamName: team.name || '',
            result,
            files,
            projectId,
            downloadUrl,
          });
          scrollToBottom();
        }
      }
    } catch (e) { /* silent */ }
  }, 4000);
}

// ── DAG 分层构建 ──
function _buildDAGLayers(tasks, agents) {
  if (!tasks.length) return [];
  // 构建依赖图
  const taskMap = {};
  for (const t of tasks) taskMap[t.agent_id] = t;

  const completed = new Set();
  const layers = [];
  const remaining = [...tasks];
  let maxIter = 10;

  while (remaining.length > 0 && maxIter-- > 0) {
    const layer = [];
    const nextRemaining = [];
    for (const t of remaining) {
      const deps = t.depends_on || [];
      if (deps.every(d => completed.has(d))) {
        const a = agents[t.agent_id] || Object.values(agents).find(a => a.id === t.agent_id) || { avatar: '🤖', name: t.agent_id };
        layer.push({ agent: a, task: t });
      } else {
        nextRemaining.push(t);
      }
    }
    if (layer.length === 0) {
      // deadlock — push all remaining
      for (const t of nextRemaining) {
        const a = agents[t.agent_id] || { avatar: '🤖', name: t.agent_id };
        layer.push({ agent: a, task: t });
      }
      layers.push(layer);
      break;
    }
    layers.push(layer);
    for (const { task: t } of layer) completed.add(t.agent_id);
    remaining.length = 0;
    remaining.push(...nextRemaining);
  }
  return layers;
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
// Clipboard fallback（Tauri/非 HTTPS 环境）
window._fallbackCopy = function(text) {
  try {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  } catch(e) { console.warn('Copy failed:', e); }
};

/** 移动端/WebView 常禁用 prompt()，用自定义层替代 */
window._promptWechatContact = function() {
  return new Promise((resolve) => {
    const old = document.getElementById('wechat-send-dialog');
    if (old) old.remove();
    const overlay = document.createElement('div');
    overlay.id = 'wechat-send-dialog';
    overlay.setAttribute('role', 'dialog');
    overlay.style.cssText =
      'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10050;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box';
    const box = document.createElement('div');
    box.style.cssText =
      'background:var(--bg-card,#1a1a2e);border:1px solid var(--border,#333);border-radius:12px;padding:16px;max-width:360px;width:100%;box-shadow:0 8px 32px rgba(0,0,0,.45)';
    box.innerHTML =
      '<div style="font-weight:600;margin-bottom:10px;color:var(--text-primary,#eee)">发送到微信</div>' +
      '<label style="font-size:12px;color:var(--text-muted,#888)">联系人名称</label>' +
      '<input type="text" id="wx-send-contact-inp" autocomplete="off" placeholder="输入微信联系人名称" ' +
      'style="width:100%;box-sizing:border-box;margin:6px 0 14px;padding:10px;border-radius:8px;border:1px solid var(--border,#333);background:var(--bg-surface,#252542);color:var(--text-primary,#eee);font-size:14px" />' +
      '<div style="display:flex;gap:8px;justify-content:flex-end">' +
      '<button type="button" id="wx-send-cancel" style="padding:8px 16px;border-radius:8px;border:1px solid var(--border,#333);background:transparent;color:var(--text-secondary,#aaa)">取消</button>' +
      '<button type="button" id="wx-send-ok" style="padding:8px 16px;border-radius:8px;border:none;background:var(--accent,#6c63ff);color:#fff">发送</button></div>';
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    const inp = box.querySelector('#wx-send-contact-inp');
    const done = (val) => {
      overlay.remove();
      resolve(val);
    };
    box.querySelector('#wx-send-cancel').addEventListener('click', () => done(null));
    box.querySelector('#wx-send-ok').addEventListener('click', () => {
      const v = (inp && inp.value) || '';
      done(v.trim() || null);
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const v = (inp.value || '').trim();
        done(v || null);
      }
      if (e.key === 'Escape') done(null);
    });
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) done(null);
    });
    setTimeout(() => inp && inp.focus(), 50);
  });
};

window._trcToast = function(msg, isErr) {
  const t = document.createElement('div');
  t.style.cssText =
    'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);z-index:10060;max-width:90%;padding:10px 16px;border-radius:10px;font-size:13px;color:#fff;background:' +
    (isErr ? 'rgba(220,50,50,.95)' : 'rgba(30,30,40,.95)') +
    ';box-shadow:0 4px 16px rgba(0,0,0,.3);pointer-events:none';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2800);
};

window._shareToWechat = async function(teamId, summary) {
  const contact = await window._promptWechatContact();
  if (!contact || !String(contact).trim()) return;
  const c = String(contact).trim();
  const text = (summary || '').substring(0, 200) + '\n\n-- 52AI工作队';
  try {
    const r = await fetch(getBaseUrl() + '/api/wechat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact: c, message: text }),
    });
    const d = await r.json();
    if (d.ok || d.success) {
      window._trcToast('已发送给 ' + c);
    } else {
      const err = d.error || '微信未连接';
      window._trcToast('发送失败：' + err, true);
    }
  } catch (e) {
    window._trcToast('发送失败，请检查微信连接', true);
  }
};

// ═══════════════════════════════════════════════════
// AI 状态提示 + 桌面操作遮罩
// ═══════════════════════════════════════════════════

function _showAIStatus(type, text) {
  const bar = document.getElementById('ai-status-bar');
  if (!bar) return;
  bar.className = 'ai-status-bar ' + type;
  const inner = bar.querySelector('.ai-status-spinner');
  if (type === 'desktop') {
    inner.className = 'ai-status-pulse';
  } else {
    inner.className = 'ai-status-spinner';
  }
  const txt = document.getElementById('ai-status-text');
  if (txt) txt.textContent = text;
}

function _hideAIStatus() {
  const bar = document.getElementById('ai-status-bar');
  if (bar) bar.className = 'ai-status-bar';
}

function _showDesktopOverlay(actionText) {
  // 不再显示全屏遮罩（会抢焦点导致AI操作发到聊天窗口而非目标窗口）
  // 只在底部状态条提示
  _showAIStatus('desktop', '⚠️ AI 正在操控电脑，请勿触碰鼠标键盘');
}

function _updateDesktopOverlay(actionText, stepNum) {
  _showAIStatus('desktop', '⚠️ ' + actionText.replace(/\.\.\.\n\n$/, '...') + ' (第' + stepNum + '步)');
}

function _hideDesktopOverlay() {
  const overlay = document.getElementById('desktop-overlay');
  if (overlay) overlay.classList.remove('show');
}

// 中断桌面操作
window._cancelDesktopOp = function() {
  _hideDesktopOverlay();
  _hideAIStatus();
  // 如果有正在播放的音频也停止
  if (window.__stopSpeaking) window.__stopSpeaking();
};
