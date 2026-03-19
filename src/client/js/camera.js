import { S, fn, dom, t, getBaseUrl, bus, expressionSystem, gazeTracker, intentFusion, EXPR_PRESETS } from '/js/state.js';

// ═══════════════════════════════════════════════════
// CAMERA & MEDIAPIPE
// ═══════════════════════════════════════════════════

async function toggleCamera() {
  if (S.isCameraOn) {
    closeCamera();
  } else {
    openCamera();
  }
}

async function openCamera() {
  dom.cameraPanel.classList.remove('hidden');
  dom.gestureTags.innerHTML = `<span class="gesture-tag">${t('camera.requesting')}</span>`;

  try {
    S.cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    dom.cameraVideo.srcObject = new MediaStream(S.cameraStream.getVideoTracks());
    await dom.cameraVideo.play().catch(() => {});
    if (S.mediaStream) { S.mediaStream.getTracks().forEach(t => t.stop()); }
    S.mediaStream = new MediaStream(S.cameraStream.getAudioTracks());
    console.log('Unified stream: audio+video in one session ✅');
    S.isCameraOn = true;
    setTimeout(() => fn.startSnapDetect(), 500);

    let waitCount = 0;
    const waitForVideo = () => {
      if (dom.cameraVideo.videoWidth > 0 && dom.cameraVideo.videoHeight > 0) {
        dom.gestureTags.innerHTML = `<span class="gesture-tag" style="color:var(--success)">${t('camera.ok', {size: dom.cameraVideo.videoWidth+'x'+dom.cameraVideo.videoHeight})}</span>`;
        initMediaPipe();
      } else if (waitCount < 30) {
        waitCount++;
        dom.gestureTags.innerHTML = `<span class="gesture-tag">${t('camera.starting', {count: waitCount})}</span>`;
        setTimeout(waitForVideo, 200);
      } else {
        dom.gestureTags.innerHTML = `<span class="gesture-tag" style="color:var(--warning)">${t('camera.black')}</span>`;
      }
    };
    setTimeout(waitForVideo, 300);

  } catch (e) {
    console.error('Camera error:', e);
    S.isCameraOn = false;
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const isHTTPS = location.protocol === 'https:';
    let hint = '';

    if (e.name === 'NotAllowedError') {
      hint = isIOS ? t('camera.deniedIOS') : t('camera.deniedOther');
    } else if (e.name === 'NotFoundError') {
      hint = t('camera.notFound');
    } else if (isIOS && isHTTPS) {
      hint = t('camera.blockedIOS');
    } else if (!isHTTPS) {
      hint = t('camera.needsHttps');
    } else {
      hint = t('camera.error', {error: `${e.name} — ${e.message}`});
    }

    dom.gestureTags.innerHTML = `<span class="gesture-tag" style="color:var(--error);white-space:normal;line-height:1.6">${hint}</span>`;
  }
}

function closeCamera() {
  S.isCameraOn = false;
  dom.cameraPanel.classList.add('hidden');
  if (S.gestureAnimFrame) { cancelAnimationFrame(S.gestureAnimFrame); S.gestureAnimFrame = null; }
  if (S.cameraStream) { S.cameraStream.getTracks().forEach(t => t.stop()); S.cameraStream = null; }
  dom.cameraVideo.srcObject = null;
  if (S.mediaStream) { S.mediaStream.getTracks().forEach(t => t.stop()); S.mediaStream = null; }
  fn.stopWakeWordMonitor();
  fn.stopSnapDetect();
}

function capturePhoto() {
  const video = dom.cameraVideo;
  if (!video.videoWidth) return;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(video, 0, 0);
  canvas.toBlob(blob => {
    if (!blob) return;
    const file = new File([blob], `capture_${Date.now()}.jpg`, { type: 'image/jpeg' });
    fn.addAttachment(file);
  }, 'image/jpeg', 0.85);
}

let mediaPipeLoading = false;
let mediaPipeReady = false;

async function initMediaPipe() {
  if (mediaPipeReady || mediaPipeLoading) {
    if (mediaPipeReady) startGestureLoop();
    return;
  }
  mediaPipeLoading = true;
  dom.gestureTags.innerHTML = `<span class="gesture-tag">${t('camera.loadingMP')}</span>`;

  try {
    const vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest');
    const { GestureRecognizer, FaceLandmarker, FilesetResolver, DrawingUtils } = vision;

    const filesetResolver = await FilesetResolver.forVisionTasks(
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm'
    );

    S.gestureRecognizer = await GestureRecognizer.createFromOptions(filesetResolver, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task',
        delegate: 'GPU',
      },
      runningMode: 'VIDEO',
      numHands: 2,
    });

    S.faceLandmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task',
        delegate: 'GPU',
      },
      runningMode: 'VIDEO',
      outputFaceBlendshapes: true,
      numFaces: 1,
    });

    const canvas = dom.gestureCanvas;
    const ctx = canvas.getContext('2d');
    S.drawingUtils = new DrawingUtils(ctx);

    mediaPipeReady = true;
    mediaPipeLoading = false;
    dom.gestureTags.innerHTML = `<span class="gesture-tag">${t('camera.ready')}</span>`;
    startGestureLoop();
  } catch (e) {
    mediaPipeLoading = false;
    console.warn('MediaPipe init failed:', e);
    dom.gestureTags.innerHTML = `<span class="gesture-tag">${t('camera.mpUnavailable')}</span>`;
  }
}

// ═══════════════════════════════════════════════════
// GESTURE COMMAND SYSTEM
// ═══════════════════════════════════════════════════

let GESTURE_COMMANDS = {};
function rebuildGestureCommands() {
  GESTURE_COMMANDS = {
    'Thumb_Up': {
      icon: '👍', label: t('gesture.confirm'), color: '#4ade80',
      action: 'ai', aiMsg: t('gesture.confirmMsg'),
    },
    'Thumb_Down': {
      icon: '👎', label: t('gesture.reject'), color: '#f87171',
      action: 'ai', aiMsg: t('gesture.rejectMsg'),
    },
    'Open_Palm': {
      icon: '✋', label: t('gesture.stop'), color: '#fbbf24',
      action: 'stop',
    },
    'Closed_Fist': {
      icon: '✊', label: t('gesture.desktop'), color: '#7c6aef',
      action: 'desktop',
    },
    'Pointing_Up': {
      icon: '☝️', label: t('gesture.voice'), color: '#38bdf8',
      action: 'voice',
    },
    'Victory': {
      icon: '✌️', label: t('gesture.screenshot'), color: '#c084fc',
      action: 'screenshot',
    },
    'ILoveYou': {
      icon: '🤟', label: t('gesture.hello'), color: '#fb7185',
      action: 'ai', aiMsg: t('gesture.helloMsg'),
    },
  };
  if (mediaPipeReady) initGestureHud();
}

// ═══════════════════════════════════════════════════
// GESTURE COMBO SYSTEM
// ═══════════════════════════════════════════════════
const COMBO_WINDOW_MS = 2500;
const COMBO_TABLE = [
  { seq: ['Victory', 'Thumb_Up'],   icon: '✌️👍', labelKey: 'combo.screenshotAI',  action: 'screenshot_ai' },
  { seq: ['Open_Palm', 'Pointing_Up'], icon: '✋☝️', labelKey: 'combo.langSwitch', action: 'lang_switch' },
  { seq: ['ILoveYou', 'Closed_Fist'], icon: '🤟✊', labelKey: 'combo.desktopAgent', action: 'desktop_agent' },
  { seq: ['Thumb_Up', 'Thumb_Up'],  icon: '👍👍', labelKey: 'combo.maxVol',       action: 'max_vol' },
  { seq: ['Thumb_Down', 'Thumb_Down'], icon: '👎👎', labelKey: 'combo.minVol',    action: 'min_vol' },
];
let comboHistory = [];

function recordGestureForCombo(gestureName) {
  const now = Date.now();
  comboHistory = comboHistory.filter(e => now - e.time < COMBO_WINDOW_MS);
  comboHistory.push({ name: gestureName, time: now });
  for (const combo of COMBO_TABLE) {
    const n = combo.seq.length;
    if (comboHistory.length >= n) {
      const tail = comboHistory.slice(-n);
      if (tail.every((e, i) => e.name === combo.seq[i])) {
        comboHistory = [];
        setTimeout(() => fireCombo(combo), 50);
        return true;
      }
    }
  }
  return false;
}

function fireCombo(combo) {
  const label = t(combo.labelKey) || combo.icon;
  showGestureToast({ icon: combo.icon, label: `⚡ ${label}`, color: '#f59e0b' });
  playGestureSound('#f59e0b');
  showComboFlash(combo.icon, label);
  switch (combo.action) {
    case 'screenshot_ai':
      fn.captureCameraFrame(0.75).then(frame => {
        if (frame) fn.sendTextMessageWithImage('请分析一下摄像头画面，告诉我你看到了什么', frame);
        else desktopRemote.requestScreenshot();
      });
      break;
    case 'lang_switch':
      S.lang = S.lang === 'zh' ? 'en' : 'zh';
      fn.applyLang();
      break;
    case 'desktop_agent':
      if (!desktopRemote.active) toggleDesktopMode();
      setTimeout(() => fn.startVoiceRecording(), 300);
      break;
    case 'max_vol':
      fn.setAppVolume(1.0);
      break;
    case 'min_vol':
      fn.setAppVolume(0.05);
      break;
  }
}

let _comboFlashTimer = null;
function showComboFlash(icon, label) {
  const el = document.getElementById('combo-flash');
  const iconEl = document.getElementById('combo-flash-icon');
  const labelEl = document.getElementById('combo-flash-label');
  if (!el) return;
  iconEl.textContent = icon;
  labelEl.textContent = `⚡ ${label}`;
  el.classList.add('show');
  clearTimeout(_comboFlashTimer);
  _comboFlashTimer = setTimeout(() => el.classList.remove('show'), 1200);
}

// ═══════════════════════════════════════════════════
// PINCH GESTURE
// ═══════════════════════════════════════════════════
const PINCH_NORM_THRESHOLD = 0.13;
const PINCH_HOLD_MS = 700;
const PINCH_COOLDOWN_MS = 3000;
let _pinchState = null, _pinchLastFired = 0;

function checkPinchGesture(lm) {
  const thumb = lm[4], index = lm[8], wrist = lm[0], mid = lm[9];
  const handSize = Math.hypot(wrist.x - mid.x, wrist.y - mid.y);
  const pinchDist = Math.hypot(thumb.x - index.x, thumb.y - index.y);
  const norm = handSize > 0.01 ? pinchDist / handSize : 1;
  const isPinching = norm < PINCH_NORM_THRESHOLD;
  const now = Date.now();

  const pinchEl = document.getElementById('pinch-indicator');

  if (isPinching) {
    if (!_pinchState) {
      _pinchState = { start: now, fired: false };
    }
    const elapsed = now - _pinchState.start;
    const progress = Math.min(elapsed / PINCH_HOLD_MS, 1);
    if (pinchEl) {
      pinchEl.classList.add('active');
      pinchEl.style.boxShadow = `0 0 ${Math.round(16 + progress * 24)}px rgba(251,191,36,${0.4 + progress * 0.5})`;
      pinchEl.style.transform = `translate(-50%,-50%) scale(${0.8 + progress * 0.4})`;
    }
    if (progress >= 1 && !_pinchState.fired && now - _pinchLastFired > PINCH_COOLDOWN_MS) {
      _pinchState.fired = true;
      _pinchLastFired = now;
      firePinchCommand();
    }
  } else {
    _pinchState = null;
    if (pinchEl) pinchEl.classList.remove('active');
  }
}

async function firePinchCommand() {
  showGestureToast({ icon: '🤌', label: t('gesture.pinch'), color: '#fbbf24' });
  playGestureSound('#fbbf24');
  const frame = await fn.captureCameraFrame(0.75);
  if (frame) {
    showGestureToast({ icon: '📷', label: t('gesture.pinchSending'), color: '#fbbf24' });
    fn.sendTextMessageWithImage('请详细描述摄像头画面中你看到的内容，包括物体、文字、场景等', frame);
  }
}

// ═══════════════════════════════════════════════════
// FINGER COUNT → VOLUME CONTROL
// ═══════════════════════════════════════════════════
const VOL_HOLD_FRAMES = 8;
let _fingerCountHistory = [];
let _lastVolFingers = -1;

function checkFingerCountVolume(lm) {
  let count = 0;
  if (lm[8].y < lm[6].y) count++;
  if (lm[12].y < lm[10].y) count++;
  if (lm[16].y < lm[14].y) count++;
  if (lm[20].y < lm[18].y) count++;
  if (Math.abs(lm[4].x - lm[2].x) > 0.06) count++;

  _fingerCountHistory.push(count);
  if (_fingerCountHistory.length > VOL_HOLD_FRAMES) _fingerCountHistory.shift();

  if (_fingerCountHistory.length === VOL_HOLD_FRAMES &&
      _fingerCountHistory.every(c => c === count) &&
      count > 0 && count !== _lastVolFingers) {
    _lastVolFingers = count;
    fn.setAppVolume(count / 5);
  }
}

// ═══════════════════════════════════════════════════
// GESTURE HOLD / FIRE
// ═══════════════════════════════════════════════════
const GESTURE_HOLD_MS = 700;
const GESTURE_COOLDOWN_MS = 2500;
let gestureHoldState = {};
let gestureLastFired = {};
let gestureToastTimer = null;

function initGestureHud() {
  const hud = document.getElementById('gesture-hud');
  hud.innerHTML = Object.entries(GESTURE_COMMANDS).map(([key, cmd]) =>
    `<div class="gesture-hud-item" data-g="${key}">
      <span class="gesture-hud-icon">${cmd.icon}</span>
      <span class="gesture-hud-label">${cmd.label}</span>
      <span class="gesture-hud-bar"><span class="gesture-hud-fill"></span></span>
    </div>`
  ).join('');
}

function checkGestureCommand(gestureName, confidence) {
  const now = Date.now();
  const cmd = GESTURE_COMMANDS[gestureName];
  if (!cmd || confidence < 0.7) return;
  if (gestureLastFired[gestureName] && now - gestureLastFired[gestureName] < GESTURE_COOLDOWN_MS) return;

  if (!gestureHoldState[gestureName]) {
    gestureHoldState[gestureName] = { start: now, fired: false };
  }

  const elapsed = now - gestureHoldState[gestureName].start;
  const progress = Math.min(elapsed / GESTURE_HOLD_MS, 1);

  showGestureCharge(cmd, progress);
  updateHudItem(gestureName, progress);

  if (progress >= 1 && !gestureHoldState[gestureName].fired) {
    gestureHoldState[gestureName].fired = true;
    gestureLastFired[gestureName] = now;
    fireGestureCommand(gestureName, cmd);
  }
}

function clearGestureHold(gestureName) {
  if (gestureHoldState[gestureName] && !gestureHoldState[gestureName].fired) {
    hideGestureCharge();
  }
  delete gestureHoldState[gestureName];
  updateHudItem(gestureName, 0);
}

function showGestureCharge(cmd, progress) {
  const el = document.getElementById('gesture-charge');
  const icon = document.getElementById('gcharge-icon');
  el.classList.add('active');
  el.style.setProperty('--gc-color', cmd.color);
  el.style.setProperty('--gc-progress', `${progress * 100}%`);
  icon.textContent = cmd.icon;
}

function hideGestureCharge() {
  document.getElementById('gesture-charge').classList.remove('active');
}

function updateHudItem(gestureName, progress) {
  const item = document.querySelector(`.gesture-hud-item[data-g="${gestureName}"]`);
  if (!item) return;
  item.classList.toggle('active', progress > 0);
  item.querySelector('.gesture-hud-fill').style.width = `${progress * 100}%`;
}

function fireGestureCommand(gestureName, cmd) {
  hideGestureCharge();
  showFireEffect(cmd);
  showGestureToast(cmd);
  playGestureSound(cmd.color);

  switch (cmd.action) {
    case 'ai':
      fn.sendTextMessage(cmd.aiMsg);
      break;
    case 'stop':
      fn.stopSpeaking();
      fn.closeVoiceOverlay();
      break;
    case 'desktop':
      toggleDesktopMode();
      break;
    case 'voice':
      if (dom.voiceOverlay.classList.contains('hidden')) fn.startVoiceRecording();
      else fn.closeVoiceOverlay();
      break;
    case 'screenshot':
      desktopRemote.requestScreenshot();
      break;
  }
}

// ═══════════════════════════════════════════════════
// LOCAL COMMAND EXECUTION
// ═══════════════════════════════════════════════════

function executeLocalCommand(msg) {
  const { action, params, phrase, confidence } = msg;
  showGestureToast({ icon: '🎤', label: `✅ ${phrase}`, color: '#4ade80' });

  switch (action) {
    case 'hotkey':
      if (desktopRemote.active && params.keys) {
        desktopRemote.send({ type: 'hotkey', keys: params.keys });
      }
      break;
    case 'skill':
      if (params.skill_id) {
        fetch(getBaseUrl() + '/api/desktop-skill/' + params.skill_id, { method: 'POST' })
          .catch(e => console.warn('Skill exec error:', e));
      }
      break;
    case 'scroll':
      if (desktopRemote.active && params.dy !== undefined) {
        desktopRemote.send({ type: 'mouse_scroll', dy: params.dy });
      }
      break;
    case 'screenshot':
      desktopRemote.requestScreenshot();
      break;
    case 'volume':
      if (params.level !== undefined) {
        fn.setAppVolume(params.level / 100);
      }
      break;
    case 'stop_all':
      fn.stopSpeaking();
      break;
    case 'pause_ai':
      fn.stopSpeaking();
      break;
    case 'resume_ai':
      break;
    case 'cancel':
      fn.stopSpeaking();
      fn.closeVoiceOverlay();
      break;
    case 'confirm':
      fn.sendTextMessage('好的，请继续');
      break;
  }
}

// ═══════════════════════════════════════════════════
// GESTURE TOAST / EFFECTS
// ═══════════════════════════════════════════════════

function showGestureToast(cmd) {
  const toast = document.getElementById('gesture-toast');
  document.getElementById('gtoast-icon').textContent = cmd.icon;
  document.getElementById('gtoast-text').textContent = cmd.label;
  toast.style.borderColor = cmd.color;
  toast.classList.add('show');
  clearTimeout(gestureToastTimer);
  gestureToastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
}

function showFireEffect(cmd) {
  const container = document.createElement('div');
  container.className = 'gesture-fire';
  container.innerHTML = `<div class="gesture-fire-ring" style="border-color:${cmd.color}"></div><div class="gesture-fire-particles"></div>`;
  const particles = container.querySelector('.gesture-fire-particles');
  for (let i = 0; i < 12; i++) {
    const angle = (i / 12) * Math.PI * 2;
    const dist = 60 + Math.random() * 40;
    const p = document.createElement('div');
    p.className = 'gesture-particle';
    p.style.setProperty('--px', `${Math.cos(angle) * dist}px`);
    p.style.setProperty('--py', `${Math.sin(angle) * dist}px`);
    p.style.background = cmd.color;
    particles.appendChild(p);
  }
  document.body.appendChild(container);
  setTimeout(() => container.remove(), 800);
}

function playGestureSound(color) {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(600, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1200, ctx.currentTime + 0.08);
    osc.frequency.exponentialRampToValueAtTime(800, ctx.currentTime + 0.15);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
    setTimeout(() => ctx.close(), 300);
  } catch {}
}

// ═══════════════════════════════════════════════════
// DESKTOP REMOTE
// ═══════════════════════════════════════════════════
const desktopRemote = {
  ws: null,
  canvas: null,
  ctx: null,
  active: false,
  gestureControl: false,
  img: new Image(),
  screenW: 1920,
  screenH: 1080,
  lastFingerPos: null,

  connect() {
    if (this.ws && this.ws.readyState <= 1) return;
    const pageProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = new URL(getBaseUrl()).host;
    this.ws = new WebSocket(`${pageProtocol}//${host}/ws/desktop`);
    this.canvas = document.getElementById('desktop-canvas');
    this.ctx = this.canvas.getContext('2d');

    this.ws.onopen = () => {
      console.log('Desktop WS connected');
      document.getElementById('desktop-hint').textContent = t('desktop.connecting');
    };
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'frame') {
          this.screenW = msg.sw;
          this.screenH = msg.sh;
          this.img.onload = () => {
            this.canvas.width = msg.w;
            this.canvas.height = msg.h;
            this.ctx.drawImage(this.img, 0, 0);
            document.getElementById('desktop-hint').style.display = 'none';
          };
          this.img.src = 'data:image/jpeg;base64,' + msg.data;
        }
      } catch (err) {
        console.error('Desktop frame error:', err);
      }
    };
    this.ws.onclose = () => {
      console.log('Desktop WS closed');
      this.ws = null;
      if (this.active) {
        document.getElementById('desktop-hint').textContent = t('desktop.reconnecting');
        document.getElementById('desktop-hint').style.display = '';
        setTimeout(() => { if (this.active) this.connect(); }, 1500);
      }
    };
    this.ws.onerror = (err) => {
      console.error('Desktop WS error:', err);
      this.ws = null;
    };
  },

  disconnect() {
    if (this.ws) { this.ws.close(); this.ws = null; }
  },

  send(msg) {
    if (this.ws?.readyState === 1) this.ws.send(JSON.stringify(msg));
  },

  canvasToNorm(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const x = (clientX - rect.left) / rect.width;
    const y = (clientY - rect.top) / rect.height;
    return { x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) };
  },

  // ── Gesture control state ──
  _gSmX: 0.5, _gSmY: 0.5, _gInited: false,
  _scrollPrevY: null, _scrollLastSent: 0,
  _fistStartX: null, _fistStartY: null,
  _fistStartTime: 0, _isDragging: false,
  _lastFistTime: 0,
  _prevGestures: new Set(),
  _posHistory: [],
  _swipeCooldown: 0,
  _gestureHintTimer: null,

  _DESK_SHORTCUTS: {
    'ILoveYou':   { keys: ['ctrl','c'],      icon:'🤟', label:'复制 Ctrl+C' },
    'Open_Palm':  { keys: ['ctrl','v'],      icon:'✋', label:'粘贴 Ctrl+V' },
    'Pointing_Up':{ keys: ['ctrl','z'],      icon:'☝️', label:'撤销 Ctrl+Z' },
    'Thumb_Up':   { scroll: 5,              icon:'👍', label:'向上滚动' },
    'Thumb_Down': { scroll: -5,             icon:'👎', label:'向下滚动' },
    'Victory':    { rightClick: true,        icon:'✌️', label:'右键菜单' },
  },

  showGestureHint(icon, label, color='#7c6aef') {
    showGestureToast({ icon, label, color });
  },

  handleGestureFrame(result, gestureNames) {
    if (!this.active || !this.gestureControl || !result?.landmarks?.length) return;
    const hand = result.landmarks[0];
    const now = Date.now();

    // ── 1. Detect two-finger scroll ──
    const indexUp  = hand[8].y  < hand[6].y;
    const middleUp = hand[12].y < hand[10].y;
    const ringDown  = hand[16].y >= hand[14].y;
    const pinkyDown = hand[20].y >= hand[18].y;
    const isTwoFinger = indexUp && middleUp && ringDown && pinkyDown;

    if (isTwoFinger) {
      const midY = (hand[8].y + hand[12].y) / 2;
      if (this._scrollPrevY !== null && now - this._scrollLastSent > 80) {
        const dy = midY - this._scrollPrevY;
        if (Math.abs(dy) > 0.004) {
          this.send({ type: 'mouse_scroll', dy: dy > 0 ? -4 : 4 });
          this._scrollLastSent = now;
        }
      }
      this._scrollPrevY = midY;
      this._prevGestures = gestureNames;
      return;
    }
    this._scrollPrevY = null;

    // ── 2. Detect swipe (Open_Palm moving fast) ──
    const isOpenPalm = gestureNames.has('Open_Palm');
    const palmX = hand[9].x, palmY = hand[9].y;
    this._posHistory.push({ x: 1 - palmX, y: palmY, t: now, palm: isOpenPalm });
    if (this._posHistory.length > 25) this._posHistory.shift();

    if (isOpenPalm && now > this._swipeCooldown) {
      const recent = this._posHistory.filter(p => p.palm && now - p.t < 500);
      if (recent.length >= 5) {
        const dx = recent[recent.length-1].x - recent[0].x;
        const dy = recent[recent.length-1].y - recent[0].y;
        const dist = Math.hypot(dx, dy);
        if (dist > 0.22) {
          const angle = Math.atan2(dy, dx) * 180 / Math.PI;
          let swipeDir = null;
          if (angle > -45 && angle < 45)   swipeDir = 'right';
          else if (angle > 135 || angle < -135) swipeDir = 'left';
          else if (angle > 45 && angle < 135)   swipeDir = 'down';
          else swipeDir = 'up';

          this._swipeCooldown = now + 1000;
          this._posHistory = [];
          this._fireSwipe(swipeDir);
          this._prevGestures = gestureNames;
          return;
        }
      }
    }

    // ── 3. Cursor movement (single index finger pointing) ──
    const isFist = gestureNames.has('Closed_Fist');
    const isPointing = !isFist && !isOpenPalm;
    const tip = hand[8];

    if (isPointing) {
      const ALPHA = 0.18;
      if (!this._gInited) {
        this._gSmX = tip.x; this._gSmY = tip.y; this._gInited = true;
      } else {
        this._gSmX = ALPHA * tip.x + (1 - ALPHA) * this._gSmX;
        this._gSmY = ALPHA * tip.y + (1 - ALPHA) * this._gSmY;
      }
      const nx = 1 - this._gSmX, ny = this._gSmY;
      this.lastNx = nx; this.lastNy = ny;
      this.send({ type: 'mouse_move', x: nx, y: ny });

      const cursor = document.getElementById('desktop-cursor');
      const rect = this.canvas.getBoundingClientRect();
      cursor.style.display = 'block';
      cursor.style.left = `${rect.left + nx * rect.width}px`;
      cursor.style.top = `${rect.top + ny * rect.height}px`;

      if (this._isDragging) {
        this.send({ type: 'mouse_up' });
        this._isDragging = false;
        this.showGestureHint('🖱️', '拖拽结束', '#4ade80');
      }
    }

    // ── 4. Drag (fist held + moving) ──
    if (isFist) {
      const cx = 1 - hand[9].x, cy = hand[9].y;
      if (this._fistStartX === null) {
        this._fistStartX = cx; this._fistStartY = cy;
        this._fistStartTime = now;
      } else {
        const moved = Math.hypot(cx - this._fistStartX, cy - this._fistStartY);
        if (!this._isDragging && moved > 0.04 && now - this._fistStartTime > 150) {
          this._isDragging = true;
          this.send({ type: 'mouse_down', x: this.lastNx ?? 0.5, y: this.lastNy ?? 0.5 });
          this.showGestureHint('✊', '开始拖拽', '#fbbf24');
        }
        if (this._isDragging) {
          const nx = 1 - this._gSmX * 0.3 - cx * 0.7;
          const ny = this._gSmY * 0.3 + cy * 0.7;
          this.send({ type: 'mouse_move', x: 1 - cx, y: cy });
        }
      }
    } else if (this._fistStartX !== null) {
      if (this._isDragging) {
        this.send({ type: 'mouse_up' });
        this._isDragging = false;
        this.showGestureHint('✊', '拖拽完成', '#4ade80');
      } else {
        const held = now - this._fistStartTime;
        const cx = this.lastNx ?? 0.5, cy = this.lastNy ?? 0.5;
        if (now - this._lastFistTime < 380) {
          this.send({ type: 'mouse_dblclick', x: cx, y: cy });
          this._lastFistTime = 0;
        } else {
          this.send({ type: 'mouse_click', x: cx, y: cy, button: 'left' });
          this._lastFistTime = now;
        }
      }
      this._fistStartX = null; this._fistStartY = null;
    }

    // ── 5. Gesture shortcuts (only on NEW gesture, not held) ──
    for (const g of gestureNames) {
      if (this._prevGestures.has(g)) continue;
      const shortcut = this._DESK_SHORTCUTS[g];
      if (!shortcut) continue;
      if (shortcut.keys) {
        this.send({ type: 'hotkey', keys: shortcut.keys });
        this.showGestureHint(shortcut.icon, shortcut.label, '#c084fc');
      } else if (shortcut.scroll) {
        this.send({ type: 'mouse_scroll', dy: shortcut.scroll });
      } else if (shortcut.rightClick) {
        this.send({ type: 'mouse_click', x: this.lastNx ?? 0.5, y: this.lastNy ?? 0.5, button: 'right' });
        this.showGestureHint(shortcut.icon, shortcut.label, '#fb7185');
      }
    }

    this._prevGestures = new Set(gestureNames);
  },

  _fireSwipe(dir) {
    const SWIPE_MAP = {
      left:  { keys: ['alt','left'],  icon:'👈', label:'后退 Alt+←' },
      right: { keys: ['alt','right'], icon:'👉', label:'前进 Alt+→' },
      up:    { keys: ['win','up'],    icon:'👆', label:'最大化 Win+↑' },
      down:  { keys: ['win','d'],     icon:'👇', label:'显示桌面 Win+D' },
    };
    const cmd = SWIPE_MAP[dir];
    if (!cmd) return;
    this.send({ type: 'hotkey', keys: cmd.keys });
    this.showGestureHint(cmd.icon, `手掌快滑: ${cmd.label}`, '#f59e0b');
    playGestureSound('#f59e0b');
  },

  handleGestureCursor(landmarks) {},
  handleGestureClick(gestureName) { return false; },

  requestScreenshot() {
    if (!this.ws || this.ws.readyState !== 1) {
      showGestureToast({ icon: '📸', label: t('gesture.openDesktopFirst'), color: '#fbbf24' });
      return;
    }
    const link = document.createElement('a');
    link.download = `desktop_${Date.now()}.jpg`;
    link.href = this.canvas.toDataURL('image/jpeg', 0.9);
    link.click();
    showGestureToast({ icon: '📸', label: t('gesture.screenshotSaved'), color: '#4ade80' });
  },

  setupTouch() {
    const body = document.getElementById('desktop-body');
    let touchStart = null;

    body.addEventListener('touchstart', (e) => {
      e.preventDefault();
      const t = e.touches[0];
      touchStart = { x: t.clientX, y: t.clientY, time: Date.now() };
    }, { passive: false });

    body.addEventListener('touchend', (e) => {
      if (!touchStart) return;
      const elapsed = Date.now() - touchStart.time;
      if (elapsed < 300) {
        const pos = this.canvasToNorm(touchStart.x, touchStart.y);
        this.send({ type: 'mouse_click', x: pos.x, y: pos.y, button: 'left' });
      }
      touchStart = null;
    });

    body.addEventListener('touchmove', (e) => {
      e.preventDefault();
      const t = e.touches[0];
      const pos = this.canvasToNorm(t.clientX, t.clientY);
      this.send({ type: 'mouse_move', x: pos.x, y: pos.y });
      const cursor = document.getElementById('desktop-cursor');
      cursor.style.display = 'block';
      cursor.style.left = `${t.clientX}px`;
      cursor.style.top = `${t.clientY}px`;
    }, { passive: false });

    let lastPinchDist = 0;
    body.addEventListener('touchmove', (e) => {
      if (e.touches.length === 2) {
        e.preventDefault();
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        const dist = Math.hypot(dx, dy);
        if (lastPinchDist > 0) {
          const delta = dist - lastPinchDist;
          if (Math.abs(delta) > 5) {
            this.send({ type: 'mouse_scroll', dy: delta > 0 ? 3 : -3 });
          }
        }
        lastPinchDist = dist;
      }
    }, { passive: false });

    body.addEventListener('touchend', () => { lastPinchDist = 0; });
  },
};

function toggleDesktopMode() {
  const panel = document.getElementById('desktop-panel');
  if (desktopRemote.active) {
    closeDesktopMode();
  } else {
    openDesktopMode();
  }
}

function openDesktopMode() {
  desktopRemote.active = true;
  desktopRemote.connect();
  document.getElementById('desktop-panel').classList.remove('hidden');
  dom.msgInput.placeholder = t('desktop.ai.placeholder');
  if (S.isCameraOn) minimizeCameraToPip();
  loadSkills();
}

function closeDesktopMode() {
  desktopRemote.active = false;
  desktopRemote.disconnect();
  document.getElementById('desktop-panel').classList.add('hidden');
  document.getElementById('desktop-cursor').style.display = 'none';
  dom.msgInput.placeholder = t('input.placeholder');
  if (S.isCameraOn) restoreCameraFromPip();
  document.getElementById('skill-bar').classList.add('hidden');
}

// ═══════════════════════════════════════════════════
// DESKTOP SKILLS
// ═══════════════════════════════════════════════════

let _skills = [];

async function loadSkills() {
  try {
    const resp = await fetch(`${getBaseUrl()}/api/desktop-skills`);
    if (!resp.ok) return;
    const data = await resp.json();
    _skills = data.skills || [];
    renderSkillBar();
  } catch (e) {
    console.warn('Failed to load skills:', e);
  }
}

function renderSkillBar() {
  const bar = document.getElementById('skill-bar');
  if (!_skills.length) { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');
  const lang = S.lang || 'zh';
  bar.innerHTML = _skills.map(s =>
    `<button class="skill-btn" data-skill="${s.id}" title="${lang === 'zh' ? s.desc_zh : s.desc_en}">` +
    `<span class="skill-icon">${s.icon}</span>` +
    `<span>${lang === 'zh' ? s.name_zh : s.name_en}</span>` +
    `</button>`
  ).join('');

  bar.querySelectorAll('.skill-btn').forEach(btn => {
    btn.addEventListener('click', () => executeSkill(btn.dataset.skill));
  });
}

async function executeSkill(skillId) {
  const skill = _skills.find(s => s.id === skillId);
  if (!skill) return;

  const bar = document.getElementById('skill-bar');
  const btn = bar.querySelector(`[data-skill="${skillId}"]`);
  if (btn) btn.classList.add('running');

  const toast = document.getElementById('skill-toast');
  const toastTitle = document.getElementById('skill-toast-title');
  const toastSteps = document.getElementById('skill-toast-steps');
  const toastMsg = document.getElementById('skill-toast-msg');
  const lang = S.lang || 'zh';

  toastTitle.textContent = `${skill.icon} ${lang === 'zh' ? skill.name_zh : skill.name_en}`;
  toastSteps.innerHTML = '';
  toastMsg.classList.add('hidden');
  toastMsg.textContent = '';
  toast.classList.remove('hidden');

  const stepStatusIcon = (status) => {
    switch (status) {
      case 'success': return '✅';
      case 'failed': return '❌';
      case 'running': return '⏳';
      case 'skipped': return '⏭️';
      default: return '⬜';
    }
  };

  try {
    const resp = await fetch(`${getBaseUrl()}/api/desktop-skill/${skillId}`, { method: 'POST' });
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

          if (msg.type === 'skill_start') {
            // already showing
          } else if (msg.type === 'skill_step') {
            const li = document.createElement('li');
            li.innerHTML = `<span class="step-icon">${stepStatusIcon(msg.status)}</span>` +
              `<span>${msg.desc}${msg.detail ? ' — ' + msg.detail : ''}</span>`;
            toastSteps.appendChild(li);
            toast.scrollTop = toast.scrollHeight;
          } else if (msg.type === 'skill_done') {
            toastMsg.textContent = msg.message;
            toastMsg.classList.remove('hidden');
            if (msg.screenshot) {
              const img = document.createElement('img');
              img.src = 'data:image/jpeg;base64,' + msg.screenshot;
              img.className = 'skill-toast-img';
              img.onclick = () => fn.openLightbox(img.src);
              toastMsg.after(img);
            }
            const aiMsg = { role: 'assistant', content: `${skill.icon} **${lang === 'zh' ? skill.name_zh : skill.name_en}**: ${msg.message}`, desktop: true };
            S.messages.push(aiMsg);
            const el = fn.appendMessage(aiMsg);
            fn.finalizeStreamingEl(el, aiMsg.content);
          } else if (msg.type === 'skill_error') {
            toastMsg.textContent = `${t('error.prefix', {msg: msg.message})}`;
            toastMsg.classList.remove('hidden');
          }
        } catch {}
      }
    }
  } catch (e) {
    toastMsg.textContent = `${t('error.prefix', {msg: e.message})}`;
    toastMsg.classList.remove('hidden');
  }

  if (btn) btn.classList.remove('running');
  setTimeout(() => { if (!toast.matches(':hover')) toast.classList.add('hidden'); }, 5000);
}

// ═══════════════════════════════════════════════════
// PIP CAMERA
// ═══════════════════════════════════════════════════

function minimizeCameraToPip() {
  dom.cameraPanel.classList.add('hidden');
  const pip = document.getElementById('camera-pip');
  const pipVideo = document.getElementById('pip-video');
  pipVideo.srcObject = S.cameraStream;
  pip.classList.remove('hidden');
}

function restoreCameraFromPip() {
  const pip = document.getElementById('camera-pip');
  pip.classList.add('hidden');
  if (S.isCameraOn) {
    dom.cameraPanel.classList.remove('hidden');
    dom.cameraVideo.srcObject = S.cameraStream;
  }
}

// ═══════════════════════════════════════════════════
// ENHANCED GESTURE LOOP
// ═══════════════════════════════════════════════════

function startGestureLoop() {
  if (!S.isCameraOn || !mediaPipeReady) return;
  initGestureHud();
  document.getElementById('gesture-hud').style.display = 'flex';

  const video = dom.cameraVideo;
  const canvas = dom.gestureCanvas;
  let prevGestures = new Set();

  function processFrame() {
    if (!S.isCameraOn) {
      document.getElementById('gesture-hud').style.display = 'none';
      return;
    }

    if (video.readyState >= 2) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const now = performance.now();
      const tags = [];
      const currentGestures = new Set();

      if (S.gestureRecognizer) {
        try {
          const result = S.gestureRecognizer.recognizeForVideo(video, now);
          if (result?.gestures?.length) {
            for (let i = 0; i < result.gestures.length; i++) {
              const g = result.gestures[i][0];
              if (g.score > 0.6) {
                const cmd = GESTURE_COMMANDS[g.categoryName];
                const label = cmd ? `${cmd.icon} ${cmd.label}` : g.categoryName;
                tags.push(label);
                currentGestures.add(g.categoryName);

                if (!desktopRemote.active || !desktopRemote.gestureControl) {
                  checkGestureCommand(g.categoryName, g.score);
                }
              }
            }

            if (result.landmarks && desktopRemote.active && desktopRemote.gestureControl) {
              desktopRemote.handleGestureFrame(result, currentGestures);
            }

            if (result.landmarks) {
              for (const hand of result.landmarks) {
                drawHandLandmarks(ctx, hand, canvas.width, canvas.height);
                checkPinchGesture(hand);
                checkFingerCountVolume(hand);
              }
            }
          }
        } catch {}
      }

      if (currentGestures.size === 0) {
        _fingerCountHistory = [];
        _lastVolFingers = -1;
        _pinchState = null;
        const pinchEl = document.getElementById('pinch-indicator');
        if (pinchEl) pinchEl.classList.remove('active');
      }

      for (const g of prevGestures) {
        if (!currentGestures.has(g)) clearGestureHold(g);
      }
      prevGestures = currentGestures;

      if (S.faceLandmarker && (S._faceFrameCount = (S._faceFrameCount || 0) + 1) % 2 === 0) {
        try {
          const faceResult = S.faceLandmarker.detectForVideo(video, now);
          if (faceResult?.faceBlendshapes?.length) {
            const bs = faceResult.faceBlendshapes[0].categories;
            const landmarks = faceResult.faceLandmarks?.[0] || null;
            const get = (name) => bs.find(b => b.categoryName === name)?.score || 0;

            if (get('mouthSmileLeft') > 0.5 || get('mouthSmileRight') > 0.5) tags.push(t('face.smile'));
            if (get('browInnerUp') > 0.5) tags.push(t('face.surprised'));
            if (get('eyeBlinkLeft') > 0.6 && get('eyeBlinkRight') < 0.3) tags.push(t('face.wink'));
            if (get('jawOpen') > 0.5) tags.push(t('face.speaking'));

            const exprTags = expressionSystem.processBlendshapes(bs, landmarks, now);
            for (const et of exprTags) {
              if (et.active && !tags.some(tt => tt.includes(et.label))) {
                tags.push(et.label);
              }
            }

            if (landmarks) {
              gazeTracker.processLandmarks(landmarks, now);
            }
          }
        } catch {}
      }

      const tagHtml = tags.length
        ? tags.map(t => `<span class="gesture-tag">${t}</span>`).join('')
        : `<span class="gesture-tag" style="opacity:.4">${t('camera.noGestures')}</span>`;
      dom.gestureTags.innerHTML = tagHtml;
      const pipBadge = document.getElementById('pip-badge');
      if (pipBadge) pipBadge.textContent = tags[0] || '';
    }

    S.gestureAnimFrame = requestAnimationFrame(processFrame);
  }

  processFrame();
}

// ═══════════════════════════════════════════════════
// GAZE CALIBRATION FLOW
// ═══════════════════════════════════════════════════

async function startGazeCalibration() {
  const points = gazeTracker.startCalibration();
  const overlay = document.createElement('div');
  overlay.id = 'gaze-calib-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;flex-direction:column;color:#fff;font-family:inherit';

  for (let i = 0; i < points.length; i++) {
    const pt = points[i];
    overlay.innerHTML = `
      <div style="position:absolute;left:${pt.x * 100}%;top:${pt.y * 100}%;transform:translate(-50%,-50%)">
        <div style="width:24px;height:24px;border-radius:50%;background:#38bdf8;animation:pulse-dot 1s infinite;box-shadow:0 0 20px rgba(56,189,248,0.5)"></div>
      </div>
      <div style="position:fixed;bottom:40px;text-align:center">
        <div style="font-size:18px;margin-bottom:8px">请注视 ${pt.label} 的蓝色圆点</div>
        <div style="font-size:14px;opacity:.6">第 ${i + 1}/${points.length} 步 — 3秒后自动记录</div>
      </div>
      <style>@keyframes pulse-dot{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.3);opacity:.7}}</style>
    `;
    document.body.appendChild(overlay);

    await new Promise(r => setTimeout(r, 3000));

    if (S.faceLandmarker) {
      try {
        const video = document.getElementById('camera-video');
        const faceResult = S.faceLandmarker.detectForVideo(video, performance.now());
        const lm = faceResult?.faceLandmarks?.[0];
        if (lm) {
          gazeTracker.recordCalibrationPoint(pt.x, pt.y, lm);
        }
      } catch (e) {
        console.warn('Calibration point failed:', e);
      }
    }

    if (overlay.parentNode) overlay.remove();
  }

  const ok = gazeTracker.finishCalibration();
  const statusEl = document.getElementById('gaze-status');
  if (statusEl) {
    statusEl.textContent = ok ? '✅ 校准完成！精度已提升至15宫格' : '❌ 校准失败，请重试';
    statusEl.style.color = ok ? 'var(--success)' : 'var(--error)';
  }
}

// ═══════════════════════════════════════════════════
// ACCESSIBILITY CALIBRATION WIZARD
// ═══════════════════════════════════════════════════
const CalibWizard = {
  steps: [
    { id: 'welcome', title: '🎯 无障碍控制校准', desc: '这个向导会帮你校准表情、手势和眼神控制。\n整个过程大约3分钟。请确保摄像头已开启且光线充足。' },
    { id: 'face_neutral', title: '😐 自然表情基准', desc: '请保持自然表情，面向摄像头，不要做任何表情。\n我们会记录你的基准值（10秒）。' },
    { id: 'face_smile', title: '😊 微笑校准', desc: '请保持微笑3秒，我来记录你的微笑幅度。' },
    { id: 'face_brow', title: '🤨 挑眉校准', desc: '请挑起眉毛3秒，我来记录你的挑眉幅度。' },
    { id: 'face_wink', title: '😉 眨眼校准', desc: '请分别眨左眼和右眼各3次。' },
    { id: 'preset', title: '🎮 选择控制方案', desc: '选择最适合你的控制方式。你随时可以在设置中更改。' },
    { id: 'done', title: '✅ 校准完成！', desc: '所有控制已就绪。你可以开始使用了！\n随时可以在设置 → 表情控制中重新校准。' },
  ],
  currentStep: 0,
  calibData: {},

  open() {
    this.currentStep = 0;
    const el = document.getElementById('calib-wizard');
    el.classList.remove('hidden');
    this.renderStep();
  },

  close() {
    document.getElementById('calib-wizard').classList.add('hidden');
    localStorage.setItem('oc-calib-done', '1');
  },

  renderStep() {
    const step = this.steps[this.currentStep];
    const indicator = document.getElementById('calib-step-indicator');
    const content = document.getElementById('calib-content');
    const nextBtn = document.getElementById('calib-next');

    indicator.innerHTML = this.steps.map((s, i) => {
      const state = i < this.currentStep ? 'done' : (i === this.currentStep ? 'active' : '');
      const color = state === 'done' ? 'var(--success)' : (state === 'active' ? 'var(--accent)' : 'var(--bg-surface)');
      return `<div style="width:${100/this.steps.length}%;height:4px;border-radius:2px;background:${color};transition:background .3s"></div>`;
    }).join('');

    if (step.id === 'preset') {
      content.innerHTML = `
        <h2 style="font-size:22px;margin-bottom:6px">${step.title}</h2>
        <p style="color:var(--text-secondary);margin-bottom:20px;white-space:pre-line">${step.desc}</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;width:100%">
          ${Object.entries(EXPR_PRESETS).map(([key, p]) =>
            `<button class="btn calib-preset-btn" data-preset="${key}" style="background:var(--bg-surface);color:var(--text-primary);padding:14px;text-align:left;border:2px solid var(--border);border-radius:var(--radius-md)" aria-label="${p.label} ${p.description}">
              <div style="font-size:15px;font-weight:600;margin-bottom:4px">${p.label}</div>
              <div style="font-size:11px;color:var(--text-secondary);line-height:1.4">${p.description}</div>
            </button>`
          ).join('')}
        </div>
      `;
      content.querySelectorAll('.calib-preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          content.querySelectorAll('.calib-preset-btn').forEach(b => b.style.borderColor = 'var(--border)');
          btn.style.borderColor = 'var(--accent)';
          this.calibData.preset = btn.dataset.preset;
        });
      });
      nextBtn.textContent = '应用并完成';
    } else if (step.id === 'done') {
      content.innerHTML = `
        <div style="font-size:64px;margin-bottom:16px">🎉</div>
        <h2 style="font-size:22px;margin-bottom:6px">${step.title}</h2>
        <p style="color:var(--text-secondary);white-space:pre-line">${step.desc}</p>
      `;
      nextBtn.textContent = '开始使用';
    } else if (step.id.startsWith('face_')) {
      const countdown = step.id === 'face_neutral' ? 10 : 3;
      content.innerHTML = `
        <h2 style="font-size:22px;margin-bottom:6px">${step.title}</h2>
        <p style="color:var(--text-secondary);margin-bottom:16px;white-space:pre-line">${step.desc}</p>
        <div style="width:120px;height:120px;border-radius:50%;border:3px solid var(--accent);display:flex;align-items:center;justify-content:center;margin:0 auto">
          <span id="calib-countdown" style="font-size:32px;font-weight:700;color:var(--accent)">${countdown}</span>
        </div>
        <div id="calib-face-status" style="margin-top:12px;font-size:13px;color:var(--text-muted)">等待开始...</div>
      `;
      nextBtn.textContent = '开始记录';
    } else {
      content.innerHTML = `
        <h2 style="font-size:22px;margin-bottom:6px">${step.title}</h2>
        <p style="color:var(--text-secondary);white-space:pre-line">${step.desc}</p>
      `;
      nextBtn.textContent = this.currentStep === 0 ? '开始校准' : '下一步';
    }
  },

  async next() {
    const step = this.steps[this.currentStep];

    if (step.id.startsWith('face_') && !this.calibData[step.id]) {
      await this.runFaceCalib(step);
      return;
    }

    if (step.id === 'preset' && this.calibData.preset) {
      expressionSystem.applyPreset(this.calibData.preset);
      try {
        await fetch(getBaseUrl() + '/api/access/preset/' + this.calibData.preset, { method: 'POST' });
      } catch (_) {}
    }

    if (step.id === 'done') {
      this.close();
      return;
    }

    this.currentStep++;
    if (this.currentStep < this.steps.length) {
      this.renderStep();
    }
  },

  async runFaceCalib(step) {
    const countdownEl = document.getElementById('calib-countdown');
    const statusEl = document.getElementById('calib-face-status');
    const duration = step.id === 'face_neutral' ? 10 : 3;

    statusEl.textContent = '正在记录...';
    for (let i = duration; i > 0; i--) {
      if (countdownEl) countdownEl.textContent = i;
      await new Promise(r => setTimeout(r, 1000));
    }
    if (countdownEl) countdownEl.textContent = '✓';
    statusEl.textContent = '记录完成！';
    this.calibData[step.id] = true;

    await new Promise(r => setTimeout(r, 500));
    this.currentStep++;
    this.renderStep();
  },
};

function maybeShowCalibWizard() {
  if (!localStorage.getItem('oc-calib-done')) {
    CalibWizard.open();
  }
}

// ═══════════════════════════════════════════════════
// EXPRESSION CONFIG
// ═══════════════════════════════════════════════════

async function loadExpressionConfig() {
  try {
    const resp = await fetch(getBaseUrl() + '/api/access/config');
    if (resp.ok) {
      const config = await resp.json();
      expressionSystem.applyConfig({
        enabled: config.expression_enabled || false,
        sensitivity: config.sensitivity || 1.0,
        expressions: _expandExprConfig(config.expressions || {}),
        headMovements: _expandHeadConfig(config.head_movements || {}),
      });
    }
  } catch (e) {
    console.warn('Failed to load expression config:', e);
  }
}

function _expandExprConfig(map) {
  const result = {};
  for (const [name, val] of Object.entries(map)) {
    if (typeof val === 'boolean') {
      result[name] = { enabled: val };
    } else if (typeof val === 'object') {
      result[name] = val;
    }
  }
  return result;
}
function _expandHeadConfig(map) {
  const result = {};
  for (const [name, val] of Object.entries(map)) {
    if (typeof val === 'boolean') {
      result[name] = { enabled: val };
    } else if (typeof val === 'object') {
      result[name] = val;
    }
  }
  return result;
}

function drawHandLandmarks(ctx, landmarks, w, h) {
  ctx.fillStyle = 'rgba(124,106,239,0.8)';
  for (const lm of landmarks) {
    ctx.beginPath();
    ctx.arc(lm.x * w, lm.y * h, 3, 0, 2 * Math.PI);
    ctx.fill();
  }
  const connections = [
    [0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],
    [9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]
  ];
  ctx.strokeStyle = 'rgba(124,106,239,0.5)';
  ctx.lineWidth = 1.5;
  for (const [a, b] of connections) {
    ctx.beginPath();
    ctx.moveTo(landmarks[a].x * w, landmarks[a].y * h);
    ctx.lineTo(landmarks[b].x * w, landmarks[b].y * h);
    ctx.stroke();
  }
}

// ═══════════════════════════════════════════════════
// GAZE CALIBRATION LOAD
// ═══════════════════════════════════════════════════

function loadGazeCalibration() {
  try {
    const saved = localStorage.getItem('oc-gaze-calibration');
    if (saved) {
      gazeTracker.loadCalibration(JSON.parse(saved));
    }
  } catch (_) {}
}

// ═══════════════════════════════════════════════════
// EXPRESSION ACTION HANDLER (set up in init)
// ═══════════════════════════════════════════════════

function setupExpressionActionHandler() {
  bus.on('expression:action', ({ name, action, confidence, label }) => {
    showGestureToast({ icon: label.charAt(0), label: label, color: '#c084fc' });
    playGestureSound('#c084fc');

    switch (action) {
      case 'confirm':
        fn.sendTextMessage('好的，请继续');
        break;
      case 'cancel':
        fn.stopSpeaking();
        break;
      case 'start_voice':
        if (!S.isRecording) fn.startVoiceRecording();
        break;
      case 'click':
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'mouse_click', button: 'left' });
        }
        break;
      case 'right_click':
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'mouse_click', button: 'right' });
        }
        break;
      case 'scroll_up':
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'mouse_scroll', dy: 5 });
        }
        break;
      case 'scroll_down':
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'mouse_scroll', dy: -5 });
        }
        break;
      case 'screenshot':
        desktopRemote.requestScreenshot();
        break;
      case 'enter':
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'key_press', key: 'enter' });
        }
        break;
      case 'undo':
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'hotkey', keys: ['ctrl', 'z'] });
        }
        break;
      case 'redo':
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'hotkey', keys: ['ctrl', 'y'] });
        }
        break;
      case 'stop':
        fn.stopSpeaking();
        if (desktopRemote.active) {
          desktopRemote.send({ type: 'emergency_stop' });
        }
        break;
    }
  });

  bus.on('expression:charging', ({ name, progress, label }) => {
    const chargeEl = document.getElementById('gesture-charge');
    const iconEl = document.getElementById('gcharge-icon');
    if (chargeEl && iconEl) {
      chargeEl.classList.add('active');
      chargeEl.style.setProperty('--gc-color', '#c084fc');
      chargeEl.style.setProperty('--gc-progress', `${progress * 100}%`);
      iconEl.textContent = label.charAt(0);
    }
  });

  bus.on('expression:idle', () => {
    hideGestureCharge();
  });
}

// ═══════════════════════════════════════════════════
// GAZE CURSOR HANDLER (set up in init)
// ═══════════════════════════════════════════════════

function setupGazeCursorHandler() {
  bus.on('gaze:update', ({ x, y, zone, confidence, dwellMs, calibrated }) => {
    const cursor = document.getElementById('gaze-cursor');
    if (!cursor) return;

    if (confidence < 0.3) {
      cursor.style.opacity = '0';
      return;
    }

    cursor.style.display = 'block';
    cursor.style.opacity = String(Math.min(confidence, 0.8));
    cursor.style.left = `${x * 100}vw`;
    cursor.style.top = `${y * 100}vh`;

    if (dwellMs > 500) {
      const progress = Math.min(dwellMs / gazeTracker.dwellThresholdMs, 1);
      const borderWidth = 2 + progress * 3;
      cursor.style.borderWidth = `${borderWidth}px`;
      cursor.style.borderColor = `rgba(56,189,248,${0.3 + progress * 0.5})`;
    } else {
      cursor.style.borderWidth = '2px';
      cursor.style.borderColor = 'rgba(56,189,248,0.3)';
    }

    const label = document.getElementById('gaze-zone-label');
    if (label) label.textContent = zone;
  });

  bus.on('gaze:dwell', ({ zone, x, y }) => {
    const cursor = document.getElementById('gaze-cursor');
    if (cursor) {
      cursor.style.borderColor = 'rgba(74,222,128,0.6)';
      cursor.style.boxShadow = '0 0 30px rgba(74,222,128,0.3)';
      setTimeout(() => {
        cursor.style.borderColor = 'rgba(56,189,248,0.3)';
        cursor.style.boxShadow = '0 0 20px rgba(56,189,248,0.15)';
      }, 500);
    }
  });

  bus.on('gaze:lost', () => {
    const cursor = document.getElementById('gaze-cursor');
    if (cursor) cursor.style.opacity = '0';
  });

  bus.on('gaze:calibrated', (data) => {
    try {
      localStorage.setItem('oc-gaze-calibration', JSON.stringify(data));
    } catch (_) {}
  });
}

// ═══════════════════════════════════════════════════
// INTENT FUSION HANDLER (set up in init)
// ═══════════════════════════════════════════════════

function setupIntentFusionHandler() {
  bus.on('intent:fused', async ({ action, params, source, confidence }) => {
    const sourceEmoji = source.includes('voice') ? '🎤' :
                        source.includes('gaze') ? '👁️' :
                        source.includes('expression') ? '🎭' :
                        source.includes('gesture') ? '✋' : '🔮';
    const label = `${sourceEmoji} ${action}`;
    showGestureToast({ icon: sourceEmoji, label, color: '#a78bfa' });
    playGestureSound?.('#a78bfa');

    if (action === 'ai_route' || confidence < 0.5) {
      try {
        const resp = await fetch(getBaseUrl() + '/api/intent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, params, source, confidence }),
        });
        const result = await resp.json();
        if (result.category === 'desktop_direct' && result.params?.executed) {
          showGestureToast({ icon: '✅', label: `AI→${action}`, color: '#4ade80' });
        }
      } catch (e) {
        console.warn('Intent routing failed:', e);
      }
      return;
    }

    if (desktopRemote?.active) {
      switch (action) {
        case 'click':
          if (params.x != null && params.y != null) {
            desktopRemote.send({ type: 'mouse_click', x: params.x, y: params.y, button: params.button || 'left' });
          } else {
            desktopRemote.send({ type: 'mouse_click', button: 'left' });
          }
          break;
        case 'right_click':
          desktopRemote.send({ type: 'mouse_click', button: 'right', x: params.x, y: params.y });
          break;
        case 'double_click':
          desktopRemote.send({ type: 'mouse_dblclick', x: params.x, y: params.y });
          break;
        case 'scroll_up':
          desktopRemote.send({ type: 'mouse_scroll', dy: 5 });
          break;
        case 'scroll_down':
          desktopRemote.send({ type: 'mouse_scroll', dy: -5 });
          break;
        case 'screenshot':
          desktopRemote.send({ type: 'screenshot' });
          break;
        case 'enter':
          desktopRemote.send({ type: 'hotkey', keys: ['enter'] });
          break;
        case 'undo':
          desktopRemote.send({ type: 'hotkey', keys: ['ctrl', 'z'] });
          break;
        case 'redo':
          desktopRemote.send({ type: 'hotkey', keys: ['ctrl', 'y'] });
          break;
        case 'copy':
          desktopRemote.send({ type: 'hotkey', keys: ['ctrl', 'c'] });
          break;
        case 'paste':
          desktopRemote.send({ type: 'hotkey', keys: ['ctrl', 'v'] });
          break;
        case 'cut':
          desktopRemote.send({ type: 'hotkey', keys: ['ctrl', 'x'] });
          break;
        case 'switch_app':
          desktopRemote.send({ type: 'hotkey', keys: ['alt', 'tab'] });
          break;
        case 'close_window':
          desktopRemote.send({ type: 'hotkey', keys: ['alt', 'F4'] });
          break;
        case 'show_desktop':
        case 'minimize':
          desktopRemote.send({ type: 'hotkey', keys: ['win', 'd'] });
          break;
        case 'confirm':
          desktopRemote.send({ type: 'hotkey', keys: ['enter'] });
          break;
        case 'cancel':
        case 'stop':
          desktopRemote.send({ type: 'hotkey', keys: ['escape'] });
          break;
        default:
          fetch(getBaseUrl() + '/api/intent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, params, source, confidence }),
          }).catch(() => {});
      }
    }
  });

  // ── Workflow recording UI feedback ──
  bus.on('workflow:recording', ({ active }) => {
    const badge = document.getElementById('workflow-rec-badge');
    if (badge) {
      badge.style.display = active ? 'flex' : 'none';
    }
  });
}

// ═══════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════

export function init() {
  // 1. Register fn.* functions
  fn.toggleCamera = toggleCamera;
  fn.openCamera = openCamera;
  fn.closeCamera = closeCamera;
  fn.capturePhoto = capturePhoto;
  fn.rebuildGestureCommands = rebuildGestureCommands;
  fn.startGestureLoop = startGestureLoop;
  fn.executeLocalCommand = executeLocalCommand;
  fn.showGestureToast = showGestureToast;
  fn.fireGestureCommand = fireGestureCommand;
  fn.isDesktopActive = () => desktopRemote.active;
  fn.toggleDesktopMode = toggleDesktopMode;
  fn.openDesktopMode = openDesktopMode;
  fn.closeDesktopMode = closeDesktopMode;
  fn.minimizeCameraToPip = minimizeCameraToPip;
  fn.restoreCameraFromPip = restoreCameraFromPip;
  fn.showEmotionBadge = () => {};

  // 2. Initialize gesture commands
  rebuildGestureCommands();

  // 3. Set up bus.on event listeners
  setupExpressionActionHandler();
  setupGazeCursorHandler();
  setupIntentFusionHandler();

  // 4. Calibration wizard button bindings
  document.getElementById('calib-next')?.addEventListener('click', () => CalibWizard.next());
  document.getElementById('calib-skip')?.addEventListener('click', () => CalibWizard.close());

  // 5. Load gaze calibration from localStorage
  loadGazeCalibration();

  // 6. Maybe show calibration wizard
  maybeShowCalibWizard();

  // 7. Load expression config from server
  loadExpressionConfig();
}
