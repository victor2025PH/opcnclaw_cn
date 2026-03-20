import { S, fn, dom, t, getBaseUrl } from '/js/state.js';

// ── Voice WebSocket state ──
let _wsReconnectTimer = null;
let _pendingVoiceStart = false;
let _wsRetryCount = 0;
let _disconnectedByUser = false;

function connectVoiceWs() {
  if (_disconnectedByUser) return;
  if (S.voiceWs && S.voiceWs.readyState <= 1) return;
  if (_wsReconnectTimer) { clearTimeout(_wsReconnectTimer); _wsReconnectTimer = null; }

  const pageProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = new URL(getBaseUrl()).host;
  const wsUrl = `${pageProtocol}//${host}/ws`;
  console.log(`Voice WS connecting to ${wsUrl} (attempt ${_wsRetryCount + 1})`);

  try {
    S.voiceWs = new WebSocket(wsUrl);
  } catch (e) {
    console.error('WebSocket create failed:', e);
    _wsRetryCount++;
    _wsReconnectTimer = setTimeout(connectVoiceWs, Math.min(2000 * _wsRetryCount, 10000));
    return;
  }

  S.voiceWs.onopen = () => {
    console.log('Voice WS connected');
    _wsRetryCount = 0;
    S._wsHighLatencyStreak = 0;
    dom.statusDot.className = 'status-dot';
    const rbar = document.getElementById('ws-reconnect-bar');
    if (rbar) rbar.classList.remove('visible');
    if (S._reconnectCountdown) { clearInterval(S._reconnectCountdown); S._reconnectCountdown = null; }
    if (S._wsPingInterval) clearInterval(S._wsPingInterval);
    S._wsPingInterval = setInterval(() => {
      if (S.voiceWs?.readyState === 1) {
        S._pingTs = performance.now();
        try { S.voiceWs.send(JSON.stringify({type: 'ping', ts: Date.now()})); } catch {}
      }
    }, 5000);
    if (_pendingVoiceStart) {
      _pendingVoiceStart = false;
      setTimeout(() => fn.startVoiceRecording(), 300);
    }
    if (S.wakeWordActive && !S.isRecording) {
      setTimeout(() => fn.startWakeWord(), 500);
    }
  };

  S.voiceWs.onclose = (ev) => {
    console.log('Voice WS closed, code:', ev.code, 'reason:', ev.reason);
    S.voiceWs = null;
    if (S._wsPingInterval) { clearInterval(S._wsPingInterval); S._wsPingInterval = null; }
    const badge = document.getElementById('ws-latency-badge');
    if (badge) { badge.textContent = '—'; badge.className = 'ws-latency-badge'; }
    if (_disconnectedByUser) return;
    _wsRetryCount++;
    if (_wsRetryCount <= 8) {
      dom.statusDot.className = 'status-dot disconnected';
      const delay = Math.min(1000 * Math.pow(1.5, _wsRetryCount - 1), 15000);
      console.log(`WS reconnect in ${Math.round(delay)}ms (attempt ${_wsRetryCount})`);
      const rbar = document.getElementById('ws-reconnect-bar');
      if (rbar) {
        let remaining = Math.ceil(delay / 1000);
        rbar.textContent = t('ws.reconnecting').replace('{s}', remaining);
        rbar.classList.add('visible');
        if (S._reconnectCountdown) clearInterval(S._reconnectCountdown);
        S._reconnectCountdown = setInterval(() => {
          remaining--;
          if (remaining <= 0) { clearInterval(S._reconnectCountdown); S._reconnectCountdown = null; rbar.classList.remove('visible'); }
          else rbar.textContent = t('ws.reconnecting').replace('{s}', remaining);
        }, 1000);
      }
      _wsReconnectTimer = setTimeout(connectVoiceWs, delay);
    } else {
      console.log('WS failed 8 times, switching to HTTP voice mode');
      dom.statusDot.className = 'status-dot http-mode';
      dom.statusDot.title = 'HTTP voice mode';
    }
  };

  S.voiceWs.onerror = (e) => {
    console.warn('Voice WS error:', e);
  };

  S.voiceWs.onmessage = (e) => handleVoiceMessage(JSON.parse(e.data));
}

// ── Voice message handling state ──
let voiceStreamText = '';
let voiceAiMsgEl = null;
let voiceSpeechDetected = false;
let voiceLastSpeechTime = 0;
let voiceSilenceTimer = null;
let voiceResponseComplete = false;

function handleVoiceMessage(msg) {
  if (msg.type === 'pong' && S._pingTs) {
    const latency = Math.round(performance.now() - S._pingTs);
    S._pingTs = null;
    if (typeof window.ocPerf !== 'undefined') window.ocPerf.setWsLatency(latency);
    const badge = document.getElementById('ws-latency-badge');
    if (badge) {
      badge.textContent = latency + 'ms';
      const q = latency < 100 ? 'excellent' : latency < 300 ? 'good' : latency < 1000 ? 'fair' : 'poor';
      badge.className = 'ws-latency-badge q-' + q;
    }
    if (!S._wsHighLatencyStreak) S._wsHighLatencyStreak = 0;
    if (latency >= 1000) { S._wsHighLatencyStreak++; } else { S._wsHighLatencyStreak = 0; }
    if (S._wsHighLatencyStreak === 3) {
      if (typeof window.ocToast !== 'undefined') window.ocToast.warning(t('ws.degraded'));
    }
    return;
  }
  if (typeof window.ocPerf !== 'undefined') {
    if (msg.type === 'listening_stopped') window.ocPerf.mark('stt_start');
    if (msg.type === 'transcript' && !msg.partial) { window.ocPerf.mark('stt_end'); window.ocPerf.mark('ai_start'); }
    if (msg.type === 'response_chunk' && !window.ocPerf._aiMarked) { window.ocPerf.mark('ai_end'); window.ocPerf._aiMarked = true; window.ocPerf.mark('tts_start'); }
    if (msg.type === 'audio_chunk' && !window.ocPerf._ttsMarked) { window.ocPerf.mark('tts_end'); window.ocPerf._ttsMarked = true; }
    if (msg.type === 'response_complete') {
      const stt = window.ocPerf.measure('stt_start', 'stt_end');
      const ai = window.ocPerf.measure('ai_start', 'ai_end');
      const tts = window.ocPerf.measure('tts_start', 'tts_end');
      window.ocPerf.recordCycle(stt, ai, tts);
      window.ocPerf._aiMarked = false; window.ocPerf._ttsMarked = false;
    }
  }
  switch (msg.type) {
    case 'listening_started':
      fn.setVoiceStatus(t('voice.listening'));
      if (window.ocLiveSubtitle) window.ocLiveSubtitle.show('');
      break;
    case 'listening_stopped':
      fn.setVoiceStatus(t('voice.processing'));
      break;
    case 'transcript':
      if (msg.partial && !msg.final) {
        const accum = msg.accumulated || msg.text;
        fn.setVoiceTranscript(accum);
        fn.setVoiceStatus('🎤 ' + (accum?.slice(0, 40) || '...'));
        if (window.ocLiveSubtitle) window.ocLiveSubtitle.typeText(accum);
        if (!window._partialUserEl) {
          fn.hideWelcome();
          window._partialUserEl = fn.appendMessage({ role: 'user', content: accum, voice: true }, false);
          if (window._partialUserEl) window._partialUserEl.classList.add('partial-msg');
        } else {
          const textEl = window._partialUserEl.querySelector('.msg-text');
          if (textEl) textEl.textContent = accum;
        }
      } else {
        const finalText = msg.accumulated || msg.text;
        window._partialUserEl = null;
        if (window.ocLiveSubtitle) window.ocLiveSubtitle.hide();
        fn.setVoiceTranscript(finalText);
        if (finalText?.trim()) {
          fn.hideWelcome();
          S.messages.push({ role: 'user', content: finalText, voice: true });
          document.querySelectorAll('.partial-msg').forEach(el => el.remove());
          fn.appendMessage({ role: 'user', content: finalText, voice: true });
          voiceStreamText = '';
          const aiMsg = { role: 'assistant', content: '' };
          S.messages.push(aiMsg);
          voiceAiMsgEl = fn.appendMessage(aiMsg, true);
          fn.setVoiceStatus(t('voice.thinking'));
        }
      }
      break;
    case 'local_command':
      fn.executeLocalCommand(msg);
      break;
    case 'response_chunk':
      voiceStreamText += msg.text;
      if (voiceAiMsgEl) fn.updateStreamingEl(voiceAiMsgEl, voiceStreamText);
      fn.setVoiceStatus(t('voice.speaking'));
      break;
    case 'audio_chunk':
      queueVoiceAudio(msg.data, msg.sample_rate, msg.format || 'pcm');
      break;
    case 'response_complete':
      voiceResponseComplete = true;
      if (msg.empty_transcript) {
        fn.setVoiceStatus(t('voice.noSpeech'));
        if (S.continuousMode && !dom.voiceOverlay.classList.contains('hidden')) {
          setTimeout(() => {
            if (S.continuousMode && !dom.voiceOverlay.classList.contains('hidden')) {
              fn.startVoiceRecording();
            }
          }, 800);
        }
        break;
      }
      if (voiceAiMsgEl) fn.finalizeStreamingEl(voiceAiMsgEl, msg.text);
      const lastAi = S.messages.findLast(m => m.role === 'assistant');
      if (lastAi) lastAi.content = msg.text;
      if (!S.isPlayingAudio && S.audioQueue.length === 0) fn.onVoiceAudioDone();
      break;
    case 'emotion':
      fn.showEmotionBadge(msg.emotion, msg.dominant);
      break;
    case 'vad_status':
      dom.voiceLevel.classList.toggle('active', msg.speech_detected);
      if (msg.speech_detected) {
        voiceSpeechDetected = true;
        voiceLastSpeechTime = Date.now();
        fn.setVoiceStatus(t('voice.listening'));
        if (voiceSilenceTimer) { clearTimeout(voiceSilenceTimer); voiceSilenceTimer = null; }
      } else if (voiceSpeechDetected && S.isRecording) {
        if (!voiceSilenceTimer) {
          voiceSilenceTimer = setTimeout(() => {
            voiceSilenceTimer = null;
            if (S.isRecording && voiceSpeechDetected && Date.now() - voiceLastSpeechTime >= 1200) {
              fn.stopVoiceRecording();
            }
          }, 1500);
        }
      }
      break;
    case 'pong':
      break;
    case 'monitor_transcript':
      if (msg.has_wake_word && S.wakeWordActive && !S.isRecording) {
        fn._triggerWakeWord(msg.text || '');
      } else if (msg.text) {
        document.getElementById('wake-label').textContent =
          t('wake.heard', {text: msg.text.trim().slice(0, 30)});
      }
      break;
    case 'vision_used':
      fn.showGestureToast({ icon: '📷', label: t('vision.analyzing'), color: '#06b6d4' });
      break;
  }
}

function queueVoiceAudio(base64, sampleRate, format) {
  S.audioQueue.push({ data: base64, sampleRate, format });
  if (!S.isPlayingAudio) fn.playNextAudio();
}

// ── PWA state ──
let _deferredInstall = null;

function _showUpdateBanner(reg) {
  if (document.getElementById('pwa-update-banner')) return;
  const banner = document.createElement('div');
  banner.id = 'pwa-update-banner';
  banner.style.cssText = 'position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:99999;' +
    'background:linear-gradient(135deg,#10b981,#34d399);color:#fff;padding:12px 20px;border-radius:14px;' +
    'display:flex;align-items:center;gap:12px;box-shadow:0 6px 24px rgba(16,185,129,.4);font-family:Inter,system-ui,sans-serif;' +
    'animation:slideDown .4s ease-out;max-width:380px;width:calc(100% - 40px)';
  banner.innerHTML = '<span style="font-size:22px">🔄</span>' +
    '<div style="flex:1;font-size:13px;font-weight:500">新版本已就绪</div>' +
    '<button onclick="this.parentElement.remove();location.reload()" style="padding:6px 16px;background:rgba(255,255,255,.2);' +
    'color:#fff;border:1px solid rgba(255,255,255,.3);border-radius:8px;font-size:12px;cursor:pointer;font-weight:600">刷新</button>';
  const style = document.createElement('style');
  style.textContent = '@keyframes slideDown{from{opacity:0;transform:translateX(-50%) translateY(-20px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}';
  document.head.appendChild(style);
  document.body.appendChild(banner);
}

function disconnectPermanently() {
  _disconnectedByUser = true;
  if (_wsReconnectTimer) { clearTimeout(_wsReconnectTimer); _wsReconnectTimer = null; }
  if (S._wsPingInterval) { clearInterval(S._wsPingInterval); S._wsPingInterval = null; }
  if (S._reconnectCountdown) { clearInterval(S._reconnectCountdown); S._reconnectCountdown = null; }
  if (S.voiceWs) {
    try { S.voiceWs.close(); } catch (_) {}
    S.voiceWs = null;
  }
}

export function init() {
  // Register public functions on fn
  fn.connectVoiceWs = connectVoiceWs;
  fn.disconnectPermanently = disconnectPermanently;
  fn.handleVoiceMessage = handleVoiceMessage;
  fn.queueVoiceAudio = queueVoiceAudio;

  // Expose _wsRetryCount via getter/setter for cross-module access
  Object.defineProperty(fn, '_wsRetryCount', {
    get() { return _wsRetryCount; },
    set(v) { _wsRetryCount = v; },
    configurable: true,
  });
  Object.defineProperty(fn, '_pendingVoiceStart', {
    get() { return _pendingVoiceStart; },
    set(v) { _pendingVoiceStart = v; },
    configurable: true,
  });

  // ── Visibility change reconnection ──
  document.addEventListener('visibilitychange', () => {
    if (_disconnectedByUser) return;
    if (document.visibilityState === 'visible') {
      if (!S.voiceWs || S.voiceWs.readyState > 1) {
        console.log('Page visible again, reconnecting WS...');
        _wsRetryCount = 0;
        connectVoiceWs();
      }
    }
  });

  // ── Offline / Online detection ──
  const _offlineBanner = document.getElementById('offline-banner');
  window.addEventListener('offline', () => {
    if (_offlineBanner) _offlineBanner.classList.add('show');
  });
  window.addEventListener('online', () => {
    if (_offlineBanner) _offlineBanner.classList.remove('show');
    if (!_disconnectedByUser && (!S.voiceWs || S.voiceWs.readyState > 1)) {
      _wsRetryCount = 0;
      connectVoiceWs();
    }
    if (typeof window.ocToast !== 'undefined') window.ocToast.success('网络已恢复');
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_API_CACHE' });
    }
  });
  if (!navigator.onLine && _offlineBanner) _offlineBanner.classList.add('show');

  // ── PWA Install ──
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    _deferredInstall = e;
    const dismissed = localStorage.getItem('pwa_dismissed');
    if (!dismissed) {
      setTimeout(() => {
        const bar = document.getElementById('pwa-install-bar');
        if (bar && !localStorage.getItem('pwa_dismissed')) bar.classList.add('show');
      }, 60000);
    }
  });

  const _pwaInstallBtn = document.getElementById('pwa-install-btn');
  const _pwaDismissBtn = document.getElementById('pwa-dismiss-btn');
  if (_pwaInstallBtn) {
    _pwaInstallBtn.onclick = async () => {
      if (_deferredInstall) {
        _deferredInstall.prompt();
        const result = await _deferredInstall.userChoice;
        if (result.outcome === 'accepted') console.log('PWA installed');
        _deferredInstall = null;
      }
      const bar = document.getElementById('pwa-install-bar');
      if (bar) bar.classList.remove('show');
    };
  }
  if (_pwaDismissBtn) {
    _pwaDismissBtn.onclick = () => {
      const bar = document.getElementById('pwa-install-bar');
      if (bar) bar.classList.remove('show');
      localStorage.setItem('pwa_dismissed', '1');
    };
  }

  window.addEventListener('appinstalled', () => {
    _deferredInstall = null;
    const bar = document.getElementById('pwa-install-bar');
    if (bar) bar.classList.remove('show');
    fn.showGestureToast({ icon: '✅', label: '应用已安装', color: '#10b981' });
  });

  // ── Service Worker registration + update detection ──
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js?v=4')
        .then((reg) => {
          console.log('SW registered:', reg.scope);
          reg.update();
          reg.addEventListener('updatefound', () => {
            const newSW = reg.installing;
            if (!newSW) return;
            newSW.addEventListener('statechange', () => {
              if (newSW.state === 'installed' && navigator.serviceWorker.controller) {
                _showUpdateBanner(reg);
              }
            });
          });
        })
        .catch((e) => console.warn('SW registration failed:', e));
    });
  }
}
