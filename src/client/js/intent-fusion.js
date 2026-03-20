/**
 * Intent Fusion Engine — Multimodal signal merging and intent resolution.
 *
 * Architecture:
 *   Each modality emits typed signals into a shared temporal buffer.
 *   The fusion engine matches signals within a time window, resolves
 *   compound intents, and dispatches unified actions.
 *
 * Signal types:
 *   spatial  — where (from gaze/gesture cursor position)
 *   action   — what  (from expression/gesture/voice command)
 *   modifier — how   (from expression hold / voice qualifier)
 *   semantic — full intent with entities (from voice/AI)
 *
 * Fusion strategy:
 *   1. FAST PATH: Single high-confidence signal → immediate dispatch
 *   2. COMPOUND: action + spatial within window → fused dispatch
 *   3. DEFERRED: Low-confidence or ambiguous → queue for AI resolution
 */

import { bus } from './event-bus.js';

// ── Signal types ──

const SIGNAL_TYPE = {
  SPATIAL:  'spatial',
  ACTION:   'action',
  MODIFIER: 'modifier',
  SEMANTIC: 'semantic',
};

const FUSION_WINDOW_MS = 2000;
const FAST_WINDOW_MS = 500;

// Actions that need a spatial target to be useful
const SPATIAL_ACTIONS = new Set([
  'click', 'right_click', 'double_click', 'drag_to', 'type_at', 'hover',
]);

// Actions that are complete on their own (no spatial needed)
const STANDALONE_ACTIONS = new Set([
  'scroll_up', 'scroll_down', 'screenshot', 'undo', 'redo', 'enter',
  'confirm', 'cancel', 'stop', 'start_voice', 'copy', 'paste', 'cut',
  'switch_app', 'close_window', 'minimize', 'show_desktop',
]);

// Voice intent → action mapping for common phrases
const VOICE_INTENT_MAP = {
  '点击': 'click', '点一下': 'click', '按一下': 'click', '选择': 'click',
  '右键': 'right_click', '右击': 'right_click',
  '双击': 'double_click', '双点': 'double_click',
  '滚动': 'scroll_down', '往下': 'scroll_down', '下翻': 'scroll_down',
  '往上': 'scroll_up', '上翻': 'scroll_up',
  '确认': 'confirm', '确定': 'confirm', '好的': 'confirm', '是的': 'confirm',
  '取消': 'cancel', '不要': 'cancel', '算了': 'cancel',
  '截图': 'screenshot', '截屏': 'screenshot',
  '撤销': 'undo', '回退': 'undo',
  '重做': 'redo',
  '回车': 'enter', '换行': 'enter',
  '复制': 'copy', '拷贝': 'copy',
  '粘贴': 'paste',
  '剪切': 'cut',
  '切换': 'switch_app', '切换窗口': 'switch_app',
  '关闭': 'close_window',
};


class Signal {
  constructor(type, source, data, confidence = 1.0) {
    this.type = type;
    this.source = source; // 'gesture', 'expression', 'gaze', 'voice'
    this.data = data;
    this.confidence = confidence;
    this.timestamp = performance.now();
    this.consumed = false;
  }
}


class FusedIntent {
  constructor(action, params = {}, signals = []) {
    this.action = action;
    this.params = params;
    this.signals = signals;
    this.confidence = this._computeConfidence();
    this.timestamp = performance.now();
    this.source = signals.map(s => s.source).join('+');
  }

  _computeConfidence() {
    if (this.signals.length === 0) return 0;
    // Multi-modal confirmation boosts confidence
    const base = Math.max(...this.signals.map(s => s.confidence));
    const modalityBonus = Math.min((this.signals.length - 1) * 0.1, 0.2);
    return Math.min(base + modalityBonus, 1.0);
  }
}


/**
 * The main fusion engine.
 */
export class IntentFusionEngine {
  constructor() {
    this.enabled = true;
    this._buffer = [];        // Signal[]
    this._cooldownUntil = 0;  // prevent rapid re-fire
    this._cooldownMs = 300;
    this._lastDispatch = null;
    this._pendingTimeout = null;

    // Workflow recording
    this.recording = false;
    this._recordedActions = [];

    this._setupListeners();
  }

  // ── Signal intake ──

  _setupListeners() {
    // Gaze → spatial signals
    bus.on('gaze:update', ({ x, y, zone, confidence }) => {
      if (!this.enabled) return;
      this._pushSignal(new Signal(SIGNAL_TYPE.SPATIAL, 'gaze', {
        x, y, zone, method: 'gaze',
      }, confidence));
    });

    bus.on('gaze:dwell', ({ zone, x, y }) => {
      if (!this.enabled) return;
      // Dwell is a strong spatial + implicit action (selection)
      this._pushSignal(new Signal(SIGNAL_TYPE.SPATIAL, 'gaze', {
        x, y, zone, method: 'gaze_dwell', isDwell: true,
      }, 0.9));
    });

    // Expression → action signals
    bus.on('expression:action', ({ name, action, confidence, label }) => {
      if (!this.enabled) return;
      this._pushSignal(new Signal(SIGNAL_TYPE.ACTION, 'expression', {
        action, name, label,
      }, confidence));
    });

    // Gesture → action signals (injected from app.html)
    bus.on('fusion:gesture', ({ gesture, action, confidence, position }) => {
      if (!this.enabled) return;
      if (position) {
        this._pushSignal(new Signal(SIGNAL_TYPE.SPATIAL, 'gesture', {
          x: position.x, y: position.y, zone: null, method: 'gesture_point',
        }, confidence));
      }
      if (action) {
        this._pushSignal(new Signal(SIGNAL_TYPE.ACTION, 'gesture', {
          action, gesture,
        }, confidence));
      }
    });

    // Voice → semantic signals (injected from voice pipeline)
    bus.on('fusion:voice', ({ transcript, action, entities, confidence }) => {
      if (!this.enabled) return;
      // Try to extract action from transcript
      const resolved = action || this._resolveVoiceAction(transcript);
      if (resolved) {
        this._pushSignal(new Signal(SIGNAL_TYPE.ACTION, 'voice', {
          action: resolved, transcript,
        }, confidence || 0.85));
      }
      if (entities) {
        this._pushSignal(new Signal(SIGNAL_TYPE.SEMANTIC, 'voice', {
          transcript, action: resolved, entities,
        }, confidence || 0.8));
      }
    });
  }

  _resolveVoiceAction(transcript) {
    if (!transcript) return null;
    const text = transcript.trim();
    // Direct match
    if (VOICE_INTENT_MAP[text]) return VOICE_INTENT_MAP[text];
    // Substring match
    for (const [keyword, action] of Object.entries(VOICE_INTENT_MAP)) {
      if (text.includes(keyword)) return action;
    }
    return null;
  }

  // ── Signal buffer management ──

  _pushSignal(signal) {
    const now = performance.now();

    // Remove expired signals
    this._buffer = this._buffer.filter(
      s => (now - s.timestamp) < FUSION_WINDOW_MS && !s.consumed
    );

    this._buffer.push(signal);
    this._tryFuse(now);
  }

  // ── Core fusion logic ──

  _tryFuse(now) {
    if (now < this._cooldownUntil) return;

    // Collect unconsumed signals within the fast window
    const recent = this._buffer.filter(
      s => !s.consumed && (now - s.timestamp) < FAST_WINDOW_MS
    );

    const actions = recent.filter(s => s.type === SIGNAL_TYPE.ACTION);
    const spatials = recent.filter(s => s.type === SIGNAL_TYPE.SPATIAL);
    const semantics = recent.filter(s => s.type === SIGNAL_TYPE.SEMANTIC);

    // Strategy 1: Standalone action (high confidence, no spatial needed)
    for (const actionSig of actions) {
      if (STANDALONE_ACTIONS.has(actionSig.data.action) && actionSig.confidence >= 0.7) {
        this._dispatch(new FusedIntent(
          actionSig.data.action,
          { ...actionSig.data },
          [actionSig]
        ));
        actionSig.consumed = true;
        return;
      }
    }

    // Strategy 2: Action + spatial fusion (e.g., "click" + gaze position)
    for (const actionSig of actions) {
      if (SPATIAL_ACTIONS.has(actionSig.data.action)) {
        // Find the best spatial signal (prefer gesture point > gaze dwell > gaze)
        const bestSpatial = this._bestSpatial(spatials);
        if (bestSpatial) {
          this._dispatch(new FusedIntent(
            actionSig.data.action,
            {
              ...actionSig.data,
              x: bestSpatial.data.x,
              y: bestSpatial.data.y,
              zone: bestSpatial.data.zone,
              spatialMethod: bestSpatial.data.method,
            },
            [actionSig, bestSpatial]
          ));
          actionSig.consumed = true;
          bestSpatial.consumed = true;
          return;
        }

        // No spatial yet — defer briefly to wait for spatial signal
        if (!this._pendingTimeout) {
          this._pendingTimeout = setTimeout(() => {
            this._pendingTimeout = null;
            this._tryDeferredFuse();
          }, FAST_WINDOW_MS);
        }
        return;
      }
    }

    // Strategy 3: Gaze dwell as implicit click (no explicit action needed)
    for (const sp of spatials) {
      if (sp.data.isDwell && sp.confidence >= 0.85) {
        this._dispatch(new FusedIntent(
          'click',
          { x: sp.data.x, y: sp.data.y, zone: sp.data.zone, spatialMethod: 'gaze_dwell' },
          [sp]
        ));
        sp.consumed = true;
        return;
      }
    }

    // Strategy 4: Semantic signal with entities → AI routing
    for (const sem of semantics) {
      if (sem.data.entities && Object.keys(sem.data.entities).length > 0) {
        this._dispatch(new FusedIntent(
          'ai_route',
          { ...sem.data },
          [sem]
        ));
        sem.consumed = true;
        return;
      }
    }
  }

  _tryDeferredFuse() {
    const now = performance.now();
    const actions = this._buffer.filter(
      s => !s.consumed && s.type === SIGNAL_TYPE.ACTION && (now - s.timestamp) < FUSION_WINDOW_MS
    );
    const spatials = this._buffer.filter(
      s => !s.consumed && s.type === SIGNAL_TYPE.SPATIAL && (now - s.timestamp) < FUSION_WINDOW_MS
    );

    for (const actionSig of actions) {
      if (SPATIAL_ACTIONS.has(actionSig.data.action)) {
        const bestSpatial = this._bestSpatial(spatials);
        if (bestSpatial) {
          this._dispatch(new FusedIntent(
            actionSig.data.action,
            {
              ...actionSig.data,
              x: bestSpatial.data.x,
              y: bestSpatial.data.y,
              zone: bestSpatial.data.zone,
              spatialMethod: bestSpatial.data.method,
            },
            [actionSig, bestSpatial]
          ));
          actionSig.consumed = true;
          bestSpatial.consumed = true;
          return;
        }

        // Still no spatial — dispatch action-only (let desktop figure out where)
        this._dispatch(new FusedIntent(
          actionSig.data.action,
          { ...actionSig.data },
          [actionSig]
        ));
        actionSig.consumed = true;
        return;
      }
    }
  }

  _bestSpatial(spatials) {
    if (spatials.length === 0) return null;
    // Priority: gesture_point > gaze_dwell > gaze
    const priority = { gesture_point: 3, gaze_dwell: 2, gaze: 1 };
    return spatials.sort((a, b) => {
      const pa = priority[a.data.method] || 0;
      const pb = priority[b.data.method] || 0;
      if (pa !== pb) return pb - pa;
      return b.confidence - a.confidence;
    })[0];
  }

  // ── Dispatch ──

  _dispatch(intent) {
    this._cooldownUntil = performance.now() + this._cooldownMs;
    this._lastDispatch = intent;

    // Record if recording
    if (this.recording) {
      this._recordedActions.push({
        action: intent.action,
        params: intent.params,
        source: intent.source,
        confidence: intent.confidence,
        timestamp: Date.now(),
      });
    }

    bus.emit('intent:fused', {
      action: intent.action,
      params: intent.params,
      source: intent.source,
      confidence: intent.confidence,
    });
  }

  // ── Workflow Recording API ──

  startRecording() {
    this.recording = true;
    this._recordedActions = [];
    bus.emit('workflow:recording', { active: true });
  }

  stopRecording() {
    this.recording = false;
    const actions = [...this._recordedActions];
    bus.emit('workflow:recording', { active: false });
    return actions;
  }

  getRecordedActions() {
    return [...this._recordedActions];
  }

  // ── Config ──

  setFusionWindow(ms) {
    // Can't change const, but we can override via instance
    this._fusionWindowMs = ms;
  }

  setCooldown(ms) {
    this._cooldownMs = ms;
  }

  getStatus() {
    return {
      enabled: this.enabled,
      bufferSize: this._buffer.filter(s => !s.consumed).length,
      recording: this.recording,
      recordedCount: this._recordedActions.length,
      lastDispatch: this._lastDispatch ? {
        action: this._lastDispatch.action,
        source: this._lastDispatch.source,
        confidence: this._lastDispatch.confidence,
      } : null,
    };
  }

  reset() {
    this._buffer = [];
    this._lastDispatch = null;
    if (this._pendingTimeout) {
      clearTimeout(this._pendingTimeout);
      this._pendingTimeout = null;
    }
  }
}

export { SIGNAL_TYPE, VOICE_INTENT_MAP, SPATIAL_ACTIONS, STANDALONE_ACTIONS };
