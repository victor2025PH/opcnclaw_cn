/**
 * Expression Detection & Action System
 *
 * Detects facial expressions (blendshapes) and head movements (landmarks),
 * applies hold-time thresholds to avoid false triggers, and emits actions.
 *
 * Architecture:
 *   - Each expression has a state machine: idle → charging → fired → cooldown
 *   - Head movements use landmark displacement pattern matching over N frames
 *   - All actions route through the event bus for fusion engine consumption
 */

import { bus } from './event-bus.js';

// ─── Blendshape helper ───
function get(blendshapes, name) {
  const entry = blendshapes.find(b => b.categoryName === name);
  return entry ? entry.score : 0;
}

// ─── Expression Definitions ───
// Batch 1: High-reliability expressions (blendshape-based)
const DEFAULT_EXPRESSIONS = {
  smile_hold: {
    detect: (bs) => (get(bs, 'mouthSmileLeft') + get(bs, 'mouthSmileRight')) / 2,
    threshold: 0.5,
    holdMs: 2000,
    cooldownMs: 3000,
    action: 'confirm',
    label: '😊 微笑确认',
    category: 'mouth',
    enabled: true,
    batch: 1,
  },
  mouth_open: {
    detect: (bs) => get(bs, 'jawOpen'),
    threshold: 0.6,
    holdMs: 800,
    cooldownMs: 2000,
    action: 'start_voice',
    label: '🗣️ 张嘴说话',
    category: 'mouth',
    enabled: true,
    batch: 1,
  },
  brow_up: {
    detect: (bs) => get(bs, 'browInnerUp'),
    threshold: 0.5,
    holdMs: 1000,
    cooldownMs: 2500,
    action: 'scroll_up',
    label: '🤨 挑眉上翻',
    category: 'brow',
    enabled: true,
    batch: 1,
  },
  brow_down: {
    detect: (bs) => (get(bs, 'browDownLeft') + get(bs, 'browDownRight')) / 2,
    threshold: 0.4,
    holdMs: 1000,
    cooldownMs: 2500,
    action: 'scroll_down',
    label: '😤 皱眉下翻',
    category: 'brow',
    enabled: true,
    batch: 1,
  },
  wink_left: {
    detect: (bs) => {
      const left = get(bs, 'eyeBlinkLeft');
      const right = get(bs, 'eyeBlinkRight');
      return (left > 0.6 && right < 0.3) ? left : 0;
    },
    threshold: 0.6,
    holdMs: 400,
    cooldownMs: 1500,
    action: 'click',
    label: '😉 左眨=点击',
    category: 'eye',
    enabled: true,
    batch: 1,
  },
  wink_right: {
    detect: (bs) => {
      const left = get(bs, 'eyeBlinkLeft');
      const right = get(bs, 'eyeBlinkRight');
      return (right > 0.6 && left < 0.3) ? right : 0;
    },
    threshold: 0.6,
    holdMs: 400,
    cooldownMs: 1500,
    action: 'right_click',
    label: '😉 右眨=右键',
    category: 'eye',
    enabled: true,
    batch: 1,
  },

  // Batch 2: Additional expressions
  kiss: {
    detect: (bs) => get(bs, 'mouthPucker'),
    threshold: 0.6,
    holdMs: 1500,
    cooldownMs: 3000,
    action: 'screenshot',
    label: '😘 嘟嘴截图',
    category: 'mouth',
    enabled: false,
    batch: 2,
  },
  both_blink: {
    detect: (bs) => {
      const left = get(bs, 'eyeBlinkLeft');
      const right = get(bs, 'eyeBlinkRight');
      return (left > 0.7 && right > 0.7) ? (left + right) / 2 : 0;
    },
    threshold: 0.7,
    holdMs: 1200,
    cooldownMs: 2000,
    action: 'enter',
    label: '😑 双闭=回车',
    category: 'eye',
    enabled: false,
    batch: 2,
  },
};

// ─── Head Movement Definitions ───
const DEFAULT_HEAD_MOVEMENTS = {
  nod: {
    axis: 'y',
    pattern: 'down_up',
    threshold: 0.025,
    windowMs: 800,
    cooldownMs: 2000,
    action: 'confirm',
    label: '✅ 点头确认',
    enabled: false,
    batch: 2,
  },
  shake: {
    axis: 'x',
    pattern: 'left_right',
    threshold: 0.025,
    windowMs: 800,
    cooldownMs: 2000,
    action: 'cancel',
    label: '❌ 摇头取消',
    enabled: false,
    batch: 2,
  },
  tilt_left: {
    axis: 'tilt',
    threshold: 0.05,
    holdMs: 1000,
    cooldownMs: 2500,
    action: 'undo',
    label: '↩️ 左歪=撤销',
    enabled: false,
    batch: 2,
  },
  tilt_right: {
    axis: 'tilt',
    threshold: -0.05,
    holdMs: 1000,
    cooldownMs: 2500,
    action: 'redo',
    label: '↪️ 右歪=重做',
    enabled: false,
    batch: 2,
  },
};


/**
 * Expression state machine for a single expression.
 * States: idle → charging → fired → cooldown → idle
 */
class ExpressionState {
  constructor() {
    this.phase = 'idle'; // idle | charging | fired | cooldown
    this.startTime = 0;
    this.cooldownUntil = 0;
  }

  reset() {
    this.phase = 'idle';
    this.startTime = 0;
  }
}


/**
 * Head movement detector using landmark displacement history.
 * Tracks noseTip (landmark 1) and ear landmarks (234, 454) over N frames.
 */
class HeadMotionTracker {
  constructor(maxFrames = 15) {
    this.maxFrames = maxFrames;
    this.history = []; // [{x, y, tiltDelta, ts}]
    this.cooldowns = {}; // {movementName: cooldownUntil}
  }

  pushFrame(landmarks, ts) {
    if (!landmarks || landmarks.length < 468) return;

    const nose = landmarks[1];
    const leftEar = landmarks[234];
    const rightEar = landmarks[454];
    const tiltDelta = leftEar ? (leftEar.y - rightEar.y) : 0;

    this.history.push({ x: nose.x, y: nose.y, tiltDelta, ts });
    if (this.history.length > this.maxFrames) this.history.shift();
  }

  detectMovement(name, def, now) {
    if (this.cooldowns[name] && now < this.cooldowns[name]) return null;
    if (this.history.length < 5) return null;

    if (def.axis === 'tilt') {
      return this._detectTilt(name, def, now);
    }
    return this._detectOscillation(name, def, now);
  }

  _detectOscillation(name, def, now) {
    const windowStart = now - def.windowMs;
    const recent = this.history.filter(h => h.ts >= windowStart);
    if (recent.length < 4) return null;

    const axis = def.axis; // 'x' or 'y'
    const values = recent.map(h => h[axis]);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min;

    if (range < def.threshold * 2) return null;

    // Check for oscillation pattern: find at least one direction reversal
    let reversals = 0;
    let direction = 0;
    for (let i = 1; i < values.length; i++) {
      const diff = values[i] - values[i - 1];
      const newDir = diff > 0.003 ? 1 : (diff < -0.003 ? -1 : 0);
      if (newDir !== 0 && direction !== 0 && newDir !== direction) {
        reversals++;
      }
      if (newDir !== 0) direction = newDir;
    }

    if (reversals >= 1) {
      this.cooldowns[name] = now + def.cooldownMs;
      this.history = [];
      return { name, action: def.action, confidence: Math.min(range / (def.threshold * 3), 1) };
    }
    return null;
  }

  _detectTilt(name, def, now) {
    if (this.history.length < 3) return null;
    const recent = this.history.slice(-5);
    const avgTilt = recent.reduce((s, h) => s + h.tiltDelta, 0) / recent.length;

    const isPositiveThreshold = def.threshold > 0;
    const triggered = isPositiveThreshold ? (avgTilt > def.threshold) : (avgTilt < def.threshold);

    if (!triggered) return null;

    // Use holdMs-style detection via a simple "sustained" check
    const holdStart = this.history.findIndex(h => {
      return isPositiveThreshold ? (h.tiltDelta > def.threshold * 0.7) : (h.tiltDelta < def.threshold * 0.7);
    });
    if (holdStart < 0) return null;

    const holdDuration = now - this.history[holdStart].ts;
    if (holdDuration < (def.holdMs || 800)) return null;

    this.cooldowns[name] = now + def.cooldownMs;
    return { name, action: def.action, confidence: Math.min(Math.abs(avgTilt) / Math.abs(def.threshold) / 2, 1) };
  }
}


/**
 * Main Expression System controller.
 *
 * Usage:
 *   const exprSys = new ExpressionSystem();
 *   // In processFrame:
 *   exprSys.processBlendshapes(blendshapes, landmarks, timestamp);
 *
 * Events emitted on bus:
 *   'expression:action'   → { name, action, confidence, label }
 *   'expression:charging' → { name, progress, label }
 *   'expression:idle'     → { name }
 *   'expression:tags'     → [{ name, label, value, threshold }]  (for UI display)
 */
export class ExpressionSystem {
  constructor(config = {}) {
    this.enabled = false;
    this.expressions = {};
    this.headMovements = {};
    this.states = {};
    this.headTracker = new HeadMotionTracker();
    this.globalSensitivity = config.sensitivity || 1.0;
    this._lastProcessTime = 0;
    this._processIntervalMs = 50; // min ms between processing (throttle to ~20fps)

    this._initDefaults();
  }

  _initDefaults() {
    // Deep clone defaults
    for (const [name, def] of Object.entries(DEFAULT_EXPRESSIONS)) {
      this.expressions[name] = { ...def };
      this.states[name] = new ExpressionState();
    }
    for (const [name, def] of Object.entries(DEFAULT_HEAD_MOVEMENTS)) {
      this.headMovements[name] = { ...def };
    }
  }

  /**
   * Apply user configuration (from server or localStorage).
   */
  applyConfig(config) {
    if (config.enabled !== undefined) this.enabled = config.enabled;
    if (config.sensitivity !== undefined) this.globalSensitivity = config.sensitivity;

    if (config.expressions) {
      for (const [name, overrides] of Object.entries(config.expressions)) {
        if (this.expressions[name]) {
          Object.assign(this.expressions[name], overrides);
        }
      }
    }
    if (config.headMovements) {
      for (const [name, overrides] of Object.entries(config.headMovements)) {
        if (this.headMovements[name]) {
          Object.assign(this.headMovements[name], overrides);
        }
      }
    }
  }

  /**
   * Get serializable config for saving.
   */
  getConfig() {
    const exprs = {};
    for (const [name, def] of Object.entries(this.expressions)) {
      exprs[name] = {
        enabled: def.enabled,
        threshold: def.threshold,
        holdMs: def.holdMs,
        cooldownMs: def.cooldownMs,
        action: def.action,
      };
    }
    const heads = {};
    for (const [name, def] of Object.entries(this.headMovements)) {
      heads[name] = {
        enabled: def.enabled,
        threshold: def.threshold,
        windowMs: def.windowMs,
        holdMs: def.holdMs,
        cooldownMs: def.cooldownMs,
      };
    }
    return {
      enabled: this.enabled,
      sensitivity: this.globalSensitivity,
      expressions: exprs,
      headMovements: heads,
    };
  }

  /**
   * Apply a named preset configuration.
   */
  applyPreset(presetName) {
    const preset = PRESETS[presetName];
    if (!preset) return false;

    // Reset all to disabled first
    for (const def of Object.values(this.expressions)) def.enabled = false;
    for (const def of Object.values(this.headMovements)) def.enabled = false;

    // Apply preset
    if (preset.expressions) {
      for (const name of preset.expressions) {
        if (this.expressions[name]) this.expressions[name].enabled = true;
      }
    }
    if (preset.headMovements) {
      for (const name of preset.headMovements) {
        if (this.headMovements[name]) this.headMovements[name].enabled = true;
      }
    }
    if (preset.sensitivity) this.globalSensitivity = preset.sensitivity;
    if (preset.holdMultiplier) {
      for (const def of Object.values(this.expressions)) {
        def.holdMs = (DEFAULT_EXPRESSIONS[Object.keys(this.expressions).find(k => this.expressions[k] === def)]?.holdMs || 1000) * preset.holdMultiplier;
      }
    }

    this.enabled = true;
    bus.emit('expression:preset_applied', { preset: presetName });
    return true;
  }

  /**
   * Main processing entry point. Call from the camera loop.
   *
   * @param {Array} blendshapes - FaceLandmarker blendshape categories
   * @param {Array} landmarks - FaceLandmarker face landmarks (478+)
   * @param {number} now - performance.now() timestamp
   * @returns {Array} Active expression tags for UI display
   */
  processBlendshapes(blendshapes, landmarks, now) {
    if (!this.enabled || !blendshapes) return [];

    // Throttle processing
    if (now - this._lastProcessTime < this._processIntervalMs) return [];
    this._lastProcessTime = now;

    const tags = [];
    const sensitivity = this.globalSensitivity;

    // Process blendshape expressions
    for (const [name, def] of Object.entries(this.expressions)) {
      if (!def.enabled) continue;

      const rawValue = typeof def.detect === 'function' ? def.detect(blendshapes) : 0;
      const adjustedThreshold = def.threshold / sensitivity;
      const isActive = rawValue > adjustedThreshold;

      tags.push({ name, label: def.label, value: rawValue, threshold: adjustedThreshold, active: isActive });

      const state = this.states[name];

      if (state.phase === 'cooldown') {
        if (now > state.cooldownUntil) state.reset();
        else continue;
      }

      if (isActive) {
        if (state.phase === 'idle') {
          state.phase = 'charging';
          state.startTime = now;
        }

        if (state.phase === 'charging') {
          const elapsed = now - state.startTime;
          const progress = Math.min(elapsed / def.holdMs, 1);

          bus.emit('expression:charging', { name, progress, label: def.label });

          if (progress >= 1) {
            state.phase = 'fired';
            state.cooldownUntil = now + def.cooldownMs;

            bus.emit('expression:action', {
              name,
              action: def.action,
              confidence: Math.min(rawValue / def.threshold, 1),
              label: def.label,
            });

            // Transition to cooldown
            state.phase = 'cooldown';
          }
        }
      } else {
        if (state.phase === 'charging') {
          bus.emit('expression:idle', { name });
          state.reset();
        }
      }
    }

    // Process head movements
    if (landmarks) {
      this.headTracker.pushFrame(landmarks, now);
      for (const [name, def] of Object.entries(this.headMovements)) {
        if (!def.enabled) continue;
        const result = this.headTracker.detectMovement(name, def, now);
        if (result) {
          bus.emit('expression:action', {
            name,
            action: result.action,
            confidence: result.confidence,
            label: def.label,
          });
        }
      }
    }

    bus.emit('expression:tags', tags);
    return tags;
  }

  getExpressionList() {
    const list = [];
    for (const [name, def] of Object.entries(this.expressions)) {
      list.push({ name, ...def, type: 'expression' });
    }
    for (const [name, def] of Object.entries(this.headMovements)) {
      list.push({ name, ...def, type: 'head_movement' });
    }
    return list;
  }
}

// ─── Preset Configurations ───
const PRESETS = {
  hands_free: {
    label: '🙌 完全免手',
    description: '表情全开 + 头部动作 + 语音，适合无法使用双手的用户',
    expressions: ['smile_hold', 'mouth_open', 'brow_up', 'brow_down', 'wink_left', 'wink_right', 'both_blink', 'kiss'],
    headMovements: ['nod', 'shake', 'tilt_left', 'tilt_right'],
    sensitivity: 1.0,
    holdMultiplier: 1.0,
  },
  one_hand: {
    label: '🤚 单手辅助',
    description: '表情辅助 + 语音，配合单手手势使用',
    expressions: ['wink_left', 'wink_right', 'mouth_open'],
    headMovements: ['nod', 'shake'],
    sensitivity: 1.0,
    holdMultiplier: 1.0,
  },
  voice_only: {
    label: '🎤 语音为主',
    description: '张嘴自动开始录音，点头/摇头确认/取消',
    expressions: ['mouth_open'],
    headMovements: ['nod', 'shake'],
    sensitivity: 0.9,
    holdMultiplier: 1.2,
  },
  power_user: {
    label: '⚡ 效率极客',
    description: '全部开启，快速触发',
    expressions: ['smile_hold', 'mouth_open', 'brow_up', 'brow_down', 'wink_left', 'wink_right', 'both_blink', 'kiss'],
    headMovements: ['nod', 'shake', 'tilt_left', 'tilt_right'],
    sensitivity: 1.2,
    holdMultiplier: 0.7,
  },
  gentle: {
    label: '🌿 轻柔模式',
    description: '长触发时间，少量映射，适合初次使用或老年人',
    expressions: ['smile_hold', 'wink_left', 'mouth_open'],
    headMovements: ['nod'],
    sensitivity: 0.8,
    holdMultiplier: 1.5,
  },
};

export { PRESETS, DEFAULT_EXPRESSIONS, DEFAULT_HEAD_MOVEMENTS };
