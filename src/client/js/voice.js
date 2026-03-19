import { S, fn, dom, t, getBaseUrl } from '/js/state.js';

// ─── Volume Control ───
let _volHudTimer = null;
function setAppVolume(v) {
  S.appVolume = Math.max(0.05, Math.min(1.0, v));
  const pct = Math.round(S.appVolume * 100);
  const hud = document.getElementById('vol-hud');
  const fill = document.getElementById('vol-bar-fill');
  const label = document.getElementById('vol-label');
  if (fill) fill.style.height = `${pct}%`;
  if (label) label.textContent = `${pct}%`;
  const dots = document.querySelectorAll('.vol-dot');
  const fingers = Math.round(S.appVolume * 5);
  dots.forEach(d => {
    const i = parseInt(d.dataset.i);
    d.classList.toggle('active', i <= fingers);
  });
  hud.classList.add('show');
  clearTimeout(_volHudTimer);
  _volHudTimer = setTimeout(() => hud.classList.remove('show'), 2000);
  fn.showGestureToast({ icon: '🔊', label: t('gesture.vol').replace('{pct}', pct), color: '#38bdf8' });
}

// ═══════════════════════════════════════════════════
// VAD INTERRUPT MONITOR
// ═══════════════════════════════════════════════════
let _interruptCtx = null;
let _interruptAnalyser = null;
let _interruptRaf = null;
let _interruptFrames = 0;
const INTERRUPT_THRESHOLD = 30;
const INTERRUPT_MIN_FRAMES = 8;

function startInterruptMonitor() {
  if (!S.mediaStream || _interruptRaf || S.isRecording) return;
  try {
    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(S.mediaStream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.4;
    source.connect(analyser);
    _interruptCtx = ctx;
    _interruptAnalyser = analyser;
    _interruptFrames = 0;

    const buffer = new Uint8Array(analyser.frequencyBinCount);
    const check = () => {
      if (!S.isPlayingAudio) { stopInterruptMonitor(); return; }
      analyser.getByteFrequencyData(buffer);
      let energy = 0;
      for (let i = 2; i < 16; i++) energy += buffer[i];
      energy /= 14;

      if (energy > INTERRUPT_THRESHOLD) {
        _interruptFrames++;
        if (_interruptFrames >= INTERRUPT_MIN_FRAMES) {
          console.log(`🗣 Interrupt detected (energy=${energy.toFixed(0)})`);
          stopInterruptMonitor();
          stopSpeaking();
          fn.showGestureToast({ icon: '🗣️', label: t('voice.interrupted'), color: '#a855f7' });
          setTimeout(startVoiceRecording, 200);
          return;
        }
      } else {
        _interruptFrames = Math.max(0, _interruptFrames - 1);
      }
      _interruptRaf = requestAnimationFrame(check);
    };
    _interruptRaf = requestAnimationFrame(check);
    console.log('Interrupt monitor active ✅');
  } catch(e) { console.warn('Interrupt monitor failed:', e); }
}

function stopInterruptMonitor() {
  if (_interruptRaf) { cancelAnimationFrame(_interruptRaf); _interruptRaf = null; }
  if (_interruptAnalyser) { try { _interruptAnalyser.disconnect(); } catch {} _interruptAnalyser = null; }
  if (_interruptCtx) { _interruptCtx.close().catch(() => {}); _interruptCtx = null; }
  _interruptFrames = 0;
}

// ═══════════════════════════════════════════════════
// CAMERA FRAME CAPTURE (for multimodal vision)
// ═══════════════════════════════════════════════════
function captureCameraFrame(quality = 0.65) {
  if (!S.isCameraOn) return null;
  const video = dom.cameraVideo;
  if (!video.videoWidth || !video.videoHeight) return null;
  try {
    const maxW = 640, maxH = 480;
    const scale = Math.min(maxW / video.videoWidth, maxH / video.videoHeight, 1);
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(video.videoWidth * scale);
    canvas.height = Math.floor(video.videoHeight * scale);
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    const b64 = canvas.toDataURL('image/jpeg', quality).split(',')[1];
    console.log(`📷 Frame captured ${canvas.width}x${canvas.height} (~${Math.round(b64.length*0.75/1024)}KB)`);
    return b64;
  } catch(e) { console.warn('Frame capture failed:', e); return null; }
}

// ═══════════════════════════════════════════════════
// AUDIO PLAYBACK & VOICE RECORDING
// ═══════════════════════════════════════════════════
let voiceStreamText = '';
let voiceAiMsgEl = null;
let voiceSpeechDetected = false;
let voiceSilenceTimer = null;
let voiceResponseComplete = false;
let _pendingVoiceStart = false;

async function playNextAudio() {
  if (S.audioQueue.length === 0) {
    S.isPlayingAudio = false;
    S._currentAudioSrc = null;
    S._currentAudioCtx = null;
    showStopSpeaking(false);
    stopInterruptMonitor();
    if (voiceResponseComplete) onVoiceAudioDone();
    return;
  }
  S.isPlayingAudio = true;
  showStopSpeaking(true);
  if (!_interruptRaf) startInterruptMonitor();
  const { data, sampleRate, format } = S.audioQueue.shift();
  try {
    const raw = atob(data);
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

    if (format === 'mp3') {
      const ctx = new AudioContext();
      const audioBuffer = await ctx.decodeAudioData(bytes.buffer.slice(0));
      const src = ctx.createBufferSource();
      src.buffer = audioBuffer;
      const gain = ctx.createGain(); gain.gain.value = S.appVolume;
      src.connect(gain).connect(ctx.destination);
      S._currentAudioSrc = src;
      S._currentAudioCtx = ctx;
      src.onended = () => { ctx.close(); playNextAudio(); };
      src.start(0);
    } else {
      const int16 = new Int16Array(bytes.buffer);
      const float32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768.0;
      const ctx = new AudioContext({ sampleRate: sampleRate || 24000 });
      const buf = ctx.createBuffer(1, float32.length, sampleRate || 24000);
      buf.copyToChannel(float32, 0);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      const gain = ctx.createGain(); gain.gain.value = S.appVolume;
      src.connect(gain).connect(ctx.destination);
      S._currentAudioSrc = src;
      S._currentAudioCtx = ctx;
      src.onended = () => { ctx.close(); playNextAudio(); };
      src.start(0);
    }
  } catch (e) { console.error('Audio play error:', e); playNextAudio(); }
}

function setVoiceStatus(text) {
  dom.voiceStatus.textContent = text;
  dom.vbarStatus.textContent = text;
}
function setVoiceTranscript(text) {
  dom.voiceTranscript.textContent = text;
  dom.vbarTranscript.textContent = text;
}
function isVoiceUIVisible() {
  return !dom.voiceOverlay.classList.contains('hidden') ||
         !dom.voiceBar.classList.contains('hidden');
}

function stopSpeaking() {
  stopInterruptMonitor();
  S.audioQueue = [];
  if (S._currentAudioSrc) {
    try { S._currentAudioSrc.stop(); } catch {}
    S._currentAudioSrc = null;
  }
  if (S._currentAudioCtx) {
    try { S._currentAudioCtx.close(); } catch {}
    S._currentAudioCtx = null;
  }
  S.isPlayingAudio = false;
  showStopSpeaking(false);
}

function showStopSpeaking(visible) {
  const btn = document.getElementById('stop-speaking-btn');
  if (btn) btn.classList.toggle('hidden', !visible);
}

function onVoiceAudioDone() {
  const voiceVisible = isVoiceUIVisible();
  if (S.continuousMode && voiceVisible) {
    setVoiceStatus(t('voice.listening'));
    setVoiceTranscript('');
    voiceStreamText = '';
    voiceAiMsgEl = null;
    setTimeout(() => {
      if (S.continuousMode && isVoiceUIVisible()) startVoiceRecording();
    }, 400);
  } else {
    closeVoiceOverlay();
    if (wakeWordActive) setTimeout(() => startWakeWord(), 400);
  }
}

async function startVoiceRecording() {
  if (S.isRecording) return;
  if (S.isPlayingAudio) stopSpeaking();

  if (typeof pauseWakeWord === 'function') pauseWakeWord();

  const wsReady = S.voiceWs && S.voiceWs.readyState === 1;
  const useHttpFallback = !wsReady;
  if (useHttpFallback) {
    _pendingVoiceStart = false;
    console.log('Voice: using HTTP mode (WS not connected)');
  }
  if (!wsReady) fn.connectVoiceWs();

  if (S.isCameraOn) {
    dom.voiceBar.classList.remove('hidden');
    dom.vbarStatus.textContent = t('voice.startingMic');
    dom.vbarTranscript.textContent = '';
    dom.voiceOverlay.classList.add('hidden');
  } else {
    dom.voiceOverlay.classList.remove('hidden');
    setVoiceStatus(t('voice.startingMic'));
    setVoiceTranscript('');
    dom.voiceBar.classList.add('hidden');
  }
  voiceStreamText = '';
  voiceAiMsgEl = null;
  voiceSpeechDetected = false;
  voiceResponseComplete = false;
  if (voiceSilenceTimer) { clearTimeout(voiceSilenceTimer); voiceSilenceTimer = null; }
  S.audioQueue = [];

  try {
    const _isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

    const streamAlive = S.mediaStream &&
      S.mediaStream.getTracks().length > 0 &&
      S.mediaStream.getTracks().every(t => t.readyState === 'live');

    if (!streamAlive) {
      if (S.mediaStream) {
        S.mediaStream.getTracks().forEach(t => t.stop());
        S.mediaStream = null;
      }
      if (_isIOS) await new Promise(r => setTimeout(r, 600));
      S.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
      });
      console.log('New mic stream acquired');
    } else {
      console.log('Reusing existing mic stream');
    }

    const audioCtx = new AudioContext();
    if (audioCtx.state === 'suspended') await audioCtx.resume();

    const nativeRate = audioCtx.sampleRate;
    const targetRate = 16000;
    const ratio = nativeRate / targetRate;
    console.log(`Audio capture: ${nativeRate}Hz → ${targetRate}Hz (ratio ${ratio.toFixed(2)})`);

    const source = audioCtx.createMediaStreamSource(S.mediaStream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);

    if (window.ocAudioViz && window.ocAudioViz.start) {
      try { window.ocAudioViz.start(audioCtx, source); } catch(e) { console.warn('Audio viz error:', e); }
    }

    let silentChunkCount = 0;
    let totalChunkCount = 0;
    const httpAudioChunks = useHttpFallback ? [] : null;

    processor.onaudioprocess = (e) => {
      if (!S.isRecording) return;
      if (!useHttpFallback && (!S.voiceWs || S.voiceWs.readyState !== 1)) return;
      const data = e.inputBuffer.getChannelData(0);
      totalChunkCount++;

      let maxVal = 0;
      for (let i = 0; i < data.length; i += 16) {
        const abs = Math.abs(data[i]);
        if (abs > maxVal) maxVal = abs;
      }
      if (maxVal < 0.001) {
        silentChunkCount++;
        if (silentChunkCount === 8 && totalChunkCount <= 10) {
          console.warn('Audio appears silent — mic may not be capturing');
          setVoiceStatus(t('voice.silentMic'));
        }
      } else {
        silentChunkCount = 0;
      }

      let samples;
      if (ratio > 1.01) {
        const newLen = Math.floor(data.length / ratio);
        samples = new Float32Array(newLen);
        for (let i = 0; i < newLen; i++) {
          samples[i] = data[Math.floor(i * ratio)];
        }
      } else {
        samples = new Float32Array(data);
      }

      if (useHttpFallback) {
        httpAudioChunks.push(new Float32Array(samples));
      } else {
        const bytes = new Uint8Array(samples.buffer);
        let binary = '';
        for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
        S.voiceWs.send(JSON.stringify({ type: 'audio', data: btoa(binary) }));
      }
    };

    source.connect(processor);
    processor.connect(audioCtx.destination);

    S.isRecording = true;
    S._audioCtx = audioCtx;
    S._audioSource = source;
    S._audioProcessor = processor;
    S._httpAudioChunks = httpAudioChunks;
    S._useHttpVoice = useHttpFallback;

    if (!useHttpFallback) {
      S.voiceWs.send(JSON.stringify({ type: 'start_listening' }));
    }
    setVoiceStatus(t('voice.listeningHz', {rate: nativeRate}));
  } catch (e) {
    console.error('Mic error:', e);
    setVoiceStatus(t('voice.micError', {msg: e.message}));
  }
}

function stopVoiceRecording() {
  if (!S.isRecording) return;
  S.isRecording = false;
  if (voiceSilenceTimer) { clearTimeout(voiceSilenceTimer); voiceSilenceTimer = null; }

  const cameraFrame = captureCameraFrame();

  const useHttp = S._useHttpVoice;
  const httpChunks = S._httpAudioChunks;

  if (S._audioProcessor) { S._audioProcessor.disconnect(); S._audioProcessor = null; }
  if (S._audioSource) { S._audioSource.disconnect(); S._audioSource = null; }
  if (S._audioCtx) { S._audioCtx.close().catch(() => {}); S._audioCtx = null; }

  if (!S.continuousMode && !wakeWordActive) {
    if (S.mediaStream) { S.mediaStream.getTracks().forEach(t => t.stop()); S.mediaStream = null; }
  }

  if (useHttp && httpChunks && httpChunks.length > 0) {
    sendVoiceHttp(httpChunks, cameraFrame);
  } else if (S.voiceWs && S.voiceWs.readyState === 1) {
    if (cameraFrame) {
      S.voiceWs.send(JSON.stringify({ type: 'image_frame', data: cameraFrame }));
    }
    S.voiceWs.send(JSON.stringify({ type: 'stop_listening' }));
  }

  if (cameraFrame) setVoiceStatus('📷 ' + t('voice.processing'));
  else setVoiceStatus(t('voice.processing'));

  S._httpAudioChunks = null;
  S._useHttpVoice = false;
}

function closeVoiceOverlay() {
  S.isRecording = false;
  if (voiceSilenceTimer) { clearTimeout(voiceSilenceTimer); voiceSilenceTimer = null; }
  if (S._audioProcessor) { S._audioProcessor.disconnect(); S._audioProcessor = null; }
  if (S._audioSource) { S._audioSource.disconnect(); S._audioSource = null; }
  if (S._audioCtx) { S._audioCtx.close().catch(() => {}); S._audioCtx = null; }

  if (!wakeWordActive) {
    if (S.mediaStream) { S.mediaStream.getTracks().forEach(t => t.stop()); S.mediaStream = null; }
  }

  if (S.voiceWs && S.voiceWs.readyState === 1) {
    try { S.voiceWs.send(JSON.stringify({ type: 'stop_listening' })); } catch {}
  }
  dom.voiceOverlay.classList.add('hidden');
  dom.voiceBar.classList.add('hidden');

  if (wakeWordActive) {
    setTimeout(startWakeWord, 300);
  }
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

async function sendVoiceHttp(chunks, cameraFrame = null) {
  if (!chunks || chunks.length === 0) {
    console.warn('HTTP voice: no audio chunks to send');
    return;
  }
  const totalLen = chunks.reduce((s, c) => s + c.length, 0);
  if (totalLen < 1600) {
    console.warn(`HTTP voice: audio too short (${totalLen} samples), skipping`);
    return;
  }
  const merged = new Float32Array(totalLen);
  let offset = 0;
  for (const c of chunks) { merged.set(c, offset); offset += c.length; }

  const bytes = new Uint8Array(merged.buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  const audioB64 = btoa(binary);

  const durationSec = (totalLen / 16000).toFixed(1);
  console.log(`HTTP voice: sending ${totalLen} samples (${durationSec}s) to ${getBaseUrl()}/api/voice`);

  voiceStreamText = '';
  voiceAiMsgEl = null;
  voiceSpeechDetected = true;
  voiceResponseComplete = false;
  S.audioQueue = [];

  try {
    const resp = await fetch(`${getBaseUrl()}/api/voice`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audio: audioB64, ...(cameraFrame ? { image: cameraFrame } : {}) }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let lines = buf.split('\n');
      buf = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') continue;
        try {
          const msg = JSON.parse(raw);
          if (msg.type === 'transcript') {
            if (!msg.text || !msg.text.trim()) {
              setVoiceStatus(t('voice.noSpeech'));
              if (S.continuousMode) setTimeout(startVoiceRecording, 1000);
              return;
            }
            fn.appendMessage('user', msg.text);
            setVoiceStatus(t('voice.thinking'));
          } else if (msg.type === 'text') {
            voiceStreamText += msg.text;
            if (!voiceAiMsgEl) voiceAiMsgEl = fn.appendMessage('ai', voiceStreamText);
            else voiceAiMsgEl.querySelector('.msg-text').textContent = voiceStreamText;
          } else if (msg.type === 'audio') {
            S.audioQueue.push({ data: msg.data, format: msg.format || 'mp3' });
            if (!S.isPlayingAudio) playNextAudio();
          } else if (msg.type === 'done') {
            voiceResponseComplete = true;
            showStopSpeaking(false);
            if (S.continuousMode && !S.isPlayingAudio) setTimeout(startVoiceRecording, 800);
          } else if (msg.type === 'emotion') {
            fn.showEmotionBadge(msg.emotion, msg.dominant);
          } else if (msg.type === 'vision_used') {
            fn.showGestureToast({ icon: '📷', label: t('vision.analyzing'), color: '#06b6d4' });
          } else if (msg.type === 'error') {
            setVoiceStatus(msg.text || 'Error');
          }
        } catch {}
      }
    }
  } catch (e) {
    console.error('HTTP voice error:', e);
    setVoiceStatus(t('voice.micError', { msg: e.message }));
  }
}

// ═══════════════════════════════════════════════════
// WAKE WORD SYSTEM
// ═══════════════════════════════════════════════════
let wakeWordActive = false;
let wakeRecognition = null;
let _wakeWordsCache = [];
let _wakeMode = 'none';

let _monitorCtx = null;
let _monitorSource = null;
let _monitorProcessor = null;
let _monitorAccum = [];
const MONITOR_CHUNK_SECONDS = 1.0;

const _SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const _hasBrowserSTT = !!_SpeechRecognition;

async function _fetchWakeWords() {
  try {
    const proto = location.protocol === 'https:' ? 'https' : 'http';
    const resp = await fetch(`${proto}://${location.hostname}:${location.port}/api/wake-words`);
    if (resp.ok) {
      const data = await resp.json();
      _wakeWordsCache = (data.wake_words || []).map(w => w.toLowerCase());
    }
  } catch (e) {
    console.warn('Failed to fetch wake words, using defaults');
    _wakeWordsCache = ['你好', '小龙', '龙虾', '唤醒', '开始', '在吗', 'hey claw', 'hello'];
  }
}

function _matchWakeWord(text) {
  if (!text) return null;
  const lower = text.toLowerCase();
  for (const w of _wakeWordsCache) {
    if (lower.includes(w)) return w;
  }
  return null;
}

function _triggerWakeWord(matchedText) {
  const indicator = document.getElementById('wake-indicator');
  const label = document.getElementById('wake-label');
  indicator.classList.remove('listening');
  label.textContent = t('wake.matched', {text: matchedText.trim().slice(0, 20)});

  playGestureSound('#7c6aef');
  fn.showGestureToast({ icon: '🎙️', label: t('gesture.voiceActivated'), color: '#7c6aef' });

  pauseWakeWord();

  setTimeout(() => {
    S.continuousMode = true;
    document.getElementById('continuous-mode').checked = true;
    dom.toggleKnob.style.transform = 'translateX(22px)';
    dom.toggleKnob.parentElement.querySelector('span').style.background = 'var(--accent)';
    startVoiceRecording();
  }, 200);
}

function _startBrowserWakeMonitor() {
  if (wakeRecognition) return;

  const indicator = document.getElementById('wake-indicator');
  const label = document.getElementById('wake-label');
  indicator.classList.add('listening');
  label.textContent = t('wake.say');

  try {
    const recog = new _SpeechRecognition();
    recog.continuous = true;
    recog.interimResults = true;
    recog.lang = navigator.language || 'zh-CN';
    recog.maxAlternatives = 1;

    recog.onresult = (ev) => {
      if (!wakeWordActive || S.isRecording) return;
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const transcript = ev.results[i][0].transcript;
        const matched = _matchWakeWord(transcript);
        if (matched) {
          _triggerWakeWord(matched);
          return;
        }
      }
    };

    recog.onerror = (ev) => {
      if (ev.error === 'aborted' || ev.error === 'no-speech') return;
      console.warn('SpeechRecognition error:', ev.error);
      if (ev.error === 'not-allowed') {
        label.textContent = t('wake.micNeeded');
        return;
      }
      _stopBrowserWakeMonitor();
      if (wakeWordActive) {
        _wakeMode = 'server';
        console.log('Falling back to server STT wake monitor');
        _startServerWakeMonitor();
      }
    };

    recog.onend = () => {
      if (wakeWordActive && !S.isRecording && _wakeMode === 'browser') {
        try { recog.start(); } catch {}
      }
    };

    recog.start();
    wakeRecognition = recog;
    _wakeMode = 'browser';
    console.log('Wake word monitor started (browser SpeechRecognition) ✅');
  } catch (e) {
    console.warn('Browser SpeechRecognition failed, falling back:', e);
    _wakeMode = 'server';
    _startServerWakeMonitor();
  }
}

function _stopBrowserWakeMonitor() {
  if (wakeRecognition) {
    try { wakeRecognition.abort(); } catch {}
    wakeRecognition = null;
  }
}

function _startServerWakeMonitor() {
  if (!S.mediaStream || !S.voiceWs || S.voiceWs.readyState !== 1) return;
  if (_monitorProcessor) return;

  const indicator = document.getElementById('wake-indicator');
  const label = document.getElementById('wake-label');
  indicator.classList.add('listening');
  label.textContent = t('wake.say');

  try {
    const audioCtx = new AudioContext();
    const source = audioCtx.createMediaStreamSource(S.mediaStream);
    const processor = audioCtx.createScriptProcessor(4096, 1, 1);
    const nativeRate = audioCtx.sampleRate;
    const ratio = nativeRate / 16000;
    const chunkSamples = Math.floor(16000 * MONITOR_CHUNK_SECONDS);
    _monitorAccum = [];

    processor.onaudioprocess = (e) => {
      if (!wakeWordActive || S.isRecording) return;
      const data = e.inputBuffer.getChannelData(0);

      let samples;
      if (ratio > 1.01) {
        const newLen = Math.floor(data.length / ratio);
        samples = new Float32Array(newLen);
        for (let i = 0; i < newLen; i++) samples[i] = data[Math.floor(i * ratio)];
      } else {
        samples = new Float32Array(data);
      }
      _monitorAccum.push(...samples);

      if (_monitorAccum.length >= chunkSamples) {
        const chunk = new Float32Array(_monitorAccum.splice(0, chunkSamples));
        let maxVal = 0;
        for (let i = 0; i < chunk.length; i += 16) if (Math.abs(chunk[i]) > maxVal) maxVal = Math.abs(chunk[i]);
        if (maxVal > 0.008 && S.voiceWs && S.voiceWs.readyState === 1) {
          const bytes = new Uint8Array(chunk.buffer);
          let bin = '';
          for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
          S.voiceWs.send(JSON.stringify({ type: 'monitor_audio', data: btoa(bin) }));
        }
      }
    };

    source.connect(processor);
    processor.connect(audioCtx.destination);
    _monitorCtx = audioCtx;
    _monitorSource = source;
    _monitorProcessor = processor;
    _wakeMode = 'server';
    console.log('Wake word monitor started (server STT, 1.0s chunks) ✅');
  } catch(e) {
    console.warn('Wake word monitor failed:', e);
    label.textContent = t('wake.error', {error: e.message});
  }
}

function _stopServerWakeMonitor() {
  if (_monitorProcessor) { try { _monitorProcessor.disconnect(); } catch {} _monitorProcessor = null; }
  if (_monitorSource) { try { _monitorSource.disconnect(); } catch {} _monitorSource = null; }
  if (_monitorCtx) { _monitorCtx.close().catch(() => {}); _monitorCtx = null; }
  _monitorAccum = [];
}

function stopWakeWordMonitor() {
  _stopBrowserWakeMonitor();
  _stopServerWakeMonitor();
  _wakeMode = 'none';
}

async function startWakeWord() {
  wakeWordActive = true;
  const indicator = document.getElementById('wake-indicator');
  const label = document.getElementById('wake-label');
  indicator.classList.remove('hidden');
  label.textContent = t('wake.starting');

  if (!_wakeWordsCache.length) await _fetchWakeWords();

  if (_hasBrowserSTT) {
    _startBrowserWakeMonitor();
  } else if (S.mediaStream && S.mediaStream.getTracks().some(t => t.readyState === 'live')) {
    _startServerWakeMonitor();
  } else if (S.isCameraOn) {
    label.textContent = t('wake.waitingCam');
    setTimeout(startWakeWord, 500);
    wakeWordActive = false;
  } else {
    navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } })
      .then(stream => {
        S.mediaStream = stream;
        _startServerWakeMonitor();
        startSnapDetect();
      })
      .catch(e => { label.textContent = t('wake.micNeeded'); });
  }
}

function pauseWakeWord() {
  stopWakeWordMonitor();
  const indicator = document.getElementById('wake-indicator');
  indicator.classList.remove('listening');
  document.getElementById('wake-label').textContent = t('wake.paused');
}

function stopWakeWord() {
  wakeWordActive = false;
  stopWakeWordMonitor();
  stopSnapDetect();
  document.getElementById('wake-indicator').classList.add('hidden');
  if (!S.isRecording && !S.isCameraOn && S.mediaStream) {
    S.mediaStream.getTracks().forEach(t => t.stop());
    S.mediaStream = null;
  }
}

function resumeWakeWord() {
  if (wakeWordActive && !S.isRecording) {
    startWakeWord();
  }
}

// Helper: playGestureSound used by wake word trigger (delegates to fn registry)
function playGestureSound(color) {
  if (fn.playGestureSound) fn.playGestureSound(color);
}

// ═══════════════════════════════════════════════════
// GESTURE WAKE-UP (wave hand to activate)
// ═══════════════════════════════════════════════════
let gestureWakeEnabled = false;
let gestureWakeLastWave = 0;
const WAVE_COOLDOWN = 3000;

function _initGestureWake() {
  const _origFireGestureCommand = fn.fireGestureCommand;
  fn.fireGestureCommand = function(gestureName, cmd) {
    if (fn.recordGestureForCombo && fn.recordGestureForCombo(gestureName)) return;

    if (gestureWakeEnabled && gestureName === 'ILoveYou' &&
        dom.voiceOverlay.classList.contains('hidden') && !S.isRecording) {
      const now = Date.now();
      if (now - gestureWakeLastWave > WAVE_COOLDOWN) {
        gestureWakeLastWave = now;
        if (fn.hideGestureCharge) fn.hideGestureCharge();
        if (fn.showFireEffect) fn.showFireEffect(cmd);
        fn.showGestureToast({ icon: '🤟', label: t('gesture.gestureWake'), color: '#fb7185' });
        if (fn.playGestureSound) fn.playGestureSound('#fb7185');
        setTimeout(() => startVoiceRecording(), 300);
        return;
      }
    }
    _origFireGestureCommand(gestureName, cmd);
  };

  document.getElementById('gesture-wake-toggle').addEventListener('change', (e) => {
    gestureWakeEnabled = e.target.checked;
    const knob = document.getElementById('gesture-wake-knob');
    knob.style.transform = e.target.checked ? 'translateX(22px)' : 'none';
    knob.parentElement.querySelector('span').style.background =
      e.target.checked ? 'var(--accent)' : 'var(--bg-surface)';
  });
}

// ═══════════════════════════════════════════════════
// SNAP (FINGER SNAP) DETECTION — audio transient analysis
// ═══════════════════════════════════════════════════
const SNAP_THRESHOLD = 0.22;
const SNAP_RISE = 0.16;
const SNAP_WINDOW_MS = 1400;
const SNAP_MIN_INTERVAL_MS = 200;

let _snapCtx = null, _snapAnalyser = null, _snapRaf = null;
let _snapPrevRMS = 0, _snapLastTime = 0;
let _snapTimestamps = [];
let _snapFireTimer = null;
let _snapBadgeTimer = null;

function startSnapDetect() {
  if (_snapRaf || !S.mediaStream) return;
  try {
    _snapCtx = new AudioContext();
    const source = _snapCtx.createMediaStreamSource(S.mediaStream);
    _snapAnalyser = _snapCtx.createAnalyser();
    _snapAnalyser.fftSize = 512;
    source.connect(_snapAnalyser);
    const buf = new Float32Array(_snapAnalyser.fftSize);

    function loop() {
      _snapRaf = requestAnimationFrame(loop);
      _snapAnalyser.getFloatTimeDomainData(buf);
      let rms = 0;
      for (let i = 0; i < buf.length; i++) rms += buf[i] * buf[i];
      rms = Math.sqrt(rms / buf.length);

      const rise = rms - _snapPrevRMS;
      const now = Date.now();

      if (rise > SNAP_RISE && rms > SNAP_THRESHOLD &&
          now - _snapLastTime > SNAP_MIN_INTERVAL_MS &&
          !S.isRecording) {
        let hfEnergy = 0, lfEnergy = 0;
        for (let i = 0; i < buf.length; i++) {
          if (i > buf.length * 0.35) hfEnergy += buf[i] * buf[i];
          else lfEnergy += buf[i] * buf[i];
        }
        if (hfEnergy > lfEnergy * 0.7) {
          _snapLastTime = now;
          _snapTimestamps.push(now);
          showSnapBadge(_snapTimestamps.length);
          clearTimeout(_snapFireTimer);
          _snapFireTimer = setTimeout(() => {
            fireSnapCommand(_snapTimestamps.length);
            _snapTimestamps = [];
          }, SNAP_WINDOW_MS);
        }
      }
      _snapPrevRMS = rms;
    }
    loop();
    console.log('👆 Snap detect started');
  } catch (e) {
    console.warn('Snap detect failed:', e);
  }
}

function stopSnapDetect() {
  if (_snapRaf) { cancelAnimationFrame(_snapRaf); _snapRaf = null; }
  if (_snapCtx) { _snapCtx.close().catch(() => {}); _snapCtx = null; }
  _snapAnalyser = null;
  _snapTimestamps = [];
  clearTimeout(_snapFireTimer);
}

function showSnapBadge(n) {
  const badge = document.getElementById('snap-badge');
  const countEl = document.getElementById('snap-count');
  const labelEl = document.getElementById('snap-label');
  if (!badge) return;
  countEl.textContent = '👆'.repeat(n);
  labelEl.textContent = t('snap.label').replace('{n}', n);
  badge.classList.add('show');
  clearTimeout(_snapBadgeTimer);
  _snapBadgeTimer = setTimeout(() => badge.classList.remove('show'), SNAP_WINDOW_MS + 200);
}

const SNAP_CMDS = {
  1: { icon: '⏹', labelKey: 'snap.cmd1', action: () => stopSpeaking() },
  2: { icon: '🎤', labelKey: 'snap.cmd2', action: () => startVoiceRecording() },
  3: { icon: '📷', labelKey: 'snap.cmd3', action: async () => {
    const frame = await captureCameraFrame(0.75);
    if (frame) fn.sendTextMessageWithImage('请描述一下你看到的画面', frame);
    else window.desktopRemote && window.desktopRemote.requestScreenshot();
  }},
};

function fireSnapCommand(rawCount) {
  const n = Math.min(rawCount, 3);
  const cmd = SNAP_CMDS[n];
  if (!cmd) return;
  const label = t(cmd.labelKey);
  fn.showGestureToast({ icon: cmd.icon, label: `${t('snap.label').replace('{n}', n)}: ${label}`, color: '#f59e0b' });
  playSnapSound(n);
  cmd.action();
}

function playSnapSound(n) {
  try {
    const ctx = new AudioContext();
    for (let i = 0; i < n; i++) {
      const t0 = ctx.currentTime + i * 0.14;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(2200, t0);
      osc.frequency.exponentialRampToValueAtTime(800, t0 + 0.06);
      gain.gain.setValueAtTime(0.18, t0);
      gain.gain.exponentialRampToValueAtTime(0.001, t0 + 0.08);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + 0.1);
    }
    setTimeout(() => ctx.close(), 600);
  } catch {}
}

// ═══════════════════════════════════════════════════
// FULLSCREEN
// ═══════════════════════════════════════════════════
function toggleFullscreen() {
  if (!document.fullscreenElement && !document.webkitFullscreenElement) {
    const el = document.documentElement;
    if (el.requestFullscreen) el.requestFullscreen();
    else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
  } else {
    if (document.exitFullscreen) document.exitFullscreen();
    else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
  }
}

function onFsChange() {
  const isFs = !!(document.fullscreenElement || document.webkitFullscreenElement);
  document.getElementById('fullscreen-btn').innerHTML = isFs
    ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14h6v6m10-10h-6V4m0 6l7-7M3 21l7-7"/></svg>'
    : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3"/></svg>';
  document.getElementById('fullscreen-settings-btn').textContent = isFs ? t('settings.exitFs') : t('settings.enterFs');
}

// ═══════════════════════════════════════════════════
// MODULE INIT
// ═══════════════════════════════════════════════════
export function init() {
  // Register public functions on fn registry
  fn.startVoiceRecording = startVoiceRecording;
  fn.stopVoiceRecording = stopVoiceRecording;
  fn.closeVoiceOverlay = closeVoiceOverlay;
  fn.stopSpeaking = stopSpeaking;
  fn.showStopSpeaking = showStopSpeaking;
  fn.playNextAudio = playNextAudio;
  fn.onVoiceAudioDone = onVoiceAudioDone;
  fn.setVoiceStatus = setVoiceStatus;
  fn.setVoiceTranscript = setVoiceTranscript;
  fn.isVoiceUIVisible = isVoiceUIVisible;
  fn.captureCameraFrame = captureCameraFrame;
  fn.setAppVolume = setAppVolume;
  fn.startWakeWord = startWakeWord;
  fn.stopWakeWord = stopWakeWord;
  fn.pauseWakeWord = pauseWakeWord;
  fn.resumeWakeWord = resumeWakeWord;
  fn.isWakeWordActive = () => wakeWordActive;
  fn.toggleFullscreen = toggleFullscreen;
  fn.startSnapDetect = startSnapDetect;
  fn.stopSnapDetect = stopSnapDetect;
  fn.startInterruptMonitor = startInterruptMonitor;
  fn.stopInterruptMonitor = stopInterruptMonitor;

  // Fullscreen setup
  const canFullscreen = document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen;
  if (canFullscreen) {
    document.getElementById('fullscreen-btn').classList.remove('hidden');
  }
  document.getElementById('fullscreen-btn').addEventListener('click', toggleFullscreen);
  document.getElementById('fullscreen-settings-btn').addEventListener('click', () => {
    toggleFullscreen();
    dom.settingsModal.classList.add('hidden');
  });
  document.addEventListener('fullscreenchange', onFsChange);
  document.addEventListener('webkitfullscreenchange', onFsChange);

  // Wake word settings toggle
  document.getElementById('wake-word-toggle').addEventListener('change', (e) => {
    const knob = document.getElementById('wake-knob');
    knob.style.transform = e.target.checked ? 'translateX(22px)' : 'none';
    knob.parentElement.querySelector('span').style.background =
      e.target.checked ? 'var(--accent)' : 'var(--bg-surface)';
    if (e.target.checked) startWakeWord();
    else stopWakeWord();
  });

  // Gesture wake override (must run after camera.js has registered fn.fireGestureCommand)
  _initGestureWake();
}
