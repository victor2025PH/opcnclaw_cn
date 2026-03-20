/**
 * Gaze Tracker — Webcam-based eye gaze direction estimation.
 *
 * Uses MediaPipe FaceLandmarker iris landmarks (468-477) to estimate
 * where the user is looking on screen.
 *
 * Technical approach:
 *   1. Calculate iris position relative to eye socket (normalized 0-1)
 *   2. Apply head-pose compensation using nose & forehead landmarks
 *   3. Map to screen zones via optional 5-point calibration
 *   4. Smooth output with exponential moving average
 *
 * Accuracy: ~3x3 grid (9 zones) without calibration,
 *           ~5x3 grid (15 zones) with calibration.
 *
 * Limitations:
 *   - Glasses reduce accuracy (~20% degradation)
 *   - Requires front-facing camera at approximate eye level
 *   - Not usable as a precision pointer (use with voice/gesture for precision)
 */

import { bus } from './event-bus.js';

// MediaPipe FaceLandmarker landmark indices
const IRIS = {
  LEFT_CENTER: 468,
  RIGHT_CENTER: 473,
  LEFT_INNER: 133,
  LEFT_OUTER: 33,
  LEFT_UPPER: 159,
  LEFT_LOWER: 145,
  RIGHT_INNER: 362,
  RIGHT_OUTER: 263,
  RIGHT_UPPER: 386,
  RIGHT_LOWER: 374,
  NOSE_TIP: 1,
  FOREHEAD: 10,
  CHIN: 152,
};

/**
 * Exponential moving average smoother.
 */
class EMA {
  constructor(alpha = 0.3) {
    this.alpha = alpha;
    this.value = null;
  }

  update(newVal) {
    if (this.value === null) {
      this.value = newVal;
    } else {
      this.value = this.alpha * newVal + (1 - this.alpha) * this.value;
    }
    return this.value;
  }

  reset() {
    this.value = null;
  }
}


/**
 * Calibration data: maps raw iris ratios to known screen positions.
 * Uses 5-point calibration: center, top-left, top-right, bottom-left, bottom-right.
 */
class GazeCalibration {
  constructor() {
    this.points = []; // [{screenX, screenY, irisX, irisY}]
    this.isCalibrated = false;
    this.offsetX = 0;
    this.offsetY = 0;
    this.scaleX = 1;
    this.scaleY = 1;
  }

  addPoint(screenX, screenY, irisX, irisY) {
    this.points.push({ screenX, screenY, irisX, irisY });
  }

  compute() {
    if (this.points.length < 3) return false;

    // Compute affine transform from iris space to screen space
    // Simple approach: use center point for offset, corner spread for scale
    const center = this.points.find(p => p.screenX === 0.5 && p.screenY === 0.5);
    if (center) {
      this.offsetX = 0.5 - center.irisX;
      this.offsetY = 0.5 - center.irisY;
    }

    // Compute scale from the spread of calibration points
    const irisXs = this.points.map(p => p.irisX);
    const irisYs = this.points.map(p => p.irisY);
    const screenXs = this.points.map(p => p.screenX);
    const screenYs = this.points.map(p => p.screenY);

    const irisRangeX = Math.max(...irisXs) - Math.min(...irisXs);
    const irisRangeY = Math.max(...irisYs) - Math.min(...irisYs);
    const screenRangeX = Math.max(...screenXs) - Math.min(...screenXs);
    const screenRangeY = Math.max(...screenYs) - Math.min(...screenYs);

    if (irisRangeX > 0.01) this.scaleX = screenRangeX / irisRangeX;
    if (irisRangeY > 0.01) this.scaleY = screenRangeY / irisRangeY;

    this.isCalibrated = true;
    return true;
  }

  transform(rawX, rawY) {
    if (!this.isCalibrated) return { x: rawX, y: rawY };
    const x = (rawX + this.offsetX) * this.scaleX;
    const y = (rawY + this.offsetY) * this.scaleY;
    return {
      x: Math.max(0, Math.min(1, x)),
      y: Math.max(0, Math.min(1, y)),
    };
  }

  reset() {
    this.points = [];
    this.isCalibrated = false;
    this.offsetX = 0;
    this.offsetY = 0;
    this.scaleX = 1;
    this.scaleY = 1;
  }

  toJSON() {
    return {
      points: this.points,
      isCalibrated: this.isCalibrated,
      offsetX: this.offsetX,
      offsetY: this.offsetY,
      scaleX: this.scaleX,
      scaleY: this.scaleY,
    };
  }

  fromJSON(data) {
    if (!data) return;
    this.points = data.points || [];
    this.isCalibrated = data.isCalibrated || false;
    this.offsetX = data.offsetX || 0;
    this.offsetY = data.offsetY || 0;
    this.scaleX = data.scaleX || 1;
    this.scaleY = data.scaleY || 1;
  }
}


/**
 * Zone names for the 3x3 and 5x3 grids.
 */
const ZONE_3x3 = [
  'top-left',    'top',    'top-right',
  'left',        'center', 'right',
  'bottom-left', 'bottom', 'bottom-right',
];

function getZone3x3(x, y) {
  const col = x < 0.33 ? 0 : (x < 0.67 ? 1 : 2);
  const row = y < 0.33 ? 0 : (y < 0.67 ? 1 : 2);
  return ZONE_3x3[row * 3 + col];
}

function getZone5x3(x, y) {
  const col = Math.min(4, Math.floor(x * 5));
  const row = y < 0.33 ? 0 : (y < 0.67 ? 1 : 2);
  return `r${row}c${col}`;
}


/**
 * Main Gaze Tracker class.
 *
 * Usage:
 *   const gaze = new GazeTracker();
 *   gaze.enabled = true;
 *   // In face detection loop:
 *   gaze.processLandmarks(faceLandmarks, timestamp);
 *
 * Events emitted:
 *   'gaze:update'  → { x, y, zone, confidence, dwellMs }
 *   'gaze:dwell'   → { zone, dwellMs }  (when dwelling > threshold on a zone)
 *   'gaze:lost'    → {} (face/iris not detected)
 */
export class GazeTracker {
  constructor(config = {}) {
    this.enabled = false;
    this.smoothAlpha = config.smoothAlpha || 0.25;
    this.dwellThresholdMs = config.dwellThresholdMs || 2000;
    this.useCalibration = true;

    this._smoothX = new EMA(this.smoothAlpha);
    this._smoothY = new EMA(this.smoothAlpha);
    this._currentZone = null;
    this._zoneStartTime = 0;
    this._dwellFired = false;
    this._lastUpdate = 0;
    this._processIntervalMs = 80; // ~12fps for gaze, plenty for zone detection

    this.calibration = new GazeCalibration();

    // Head pose baseline for compensation
    this._headPoseBaseline = null;
  }

  /**
   * Process face landmarks and estimate gaze direction.
   *
   * @param {Array} landmarks - MediaPipe FaceLandmarker face landmarks (478+)
   * @param {number} now - performance.now() timestamp
   */
  processLandmarks(landmarks, now) {
    if (!this.enabled || !landmarks) return;
    if (now - this._lastUpdate < this._processIntervalMs) return;
    this._lastUpdate = now;

    // Need at least iris landmarks (index 473+)
    if (landmarks.length < 474) {
      bus.emit('gaze:lost', {});
      return;
    }

    // 1. Extract iris positions relative to eye sockets
    const rawGaze = this._computeIrisRatio(landmarks);
    if (!rawGaze) {
      bus.emit('gaze:lost', {});
      return;
    }

    // 2. Head pose compensation
    const compensated = this._compensateHeadPose(rawGaze, landmarks);

    // 3. Apply calibration
    const mapped = this.useCalibration
      ? this.calibration.transform(compensated.x, compensated.y)
      : compensated;

    // 4. Smooth
    const x = this._smoothX.update(mapped.x);
    const y = this._smoothY.update(mapped.y);

    // 5. Determine zone
    const zone = this.calibration.isCalibrated
      ? getZone5x3(x, y)
      : getZone3x3(x, y);

    // 6. Dwell detection
    if (zone !== this._currentZone) {
      this._currentZone = zone;
      this._zoneStartTime = now;
      this._dwellFired = false;
    }
    const dwellMs = now - this._zoneStartTime;

    if (dwellMs >= this.dwellThresholdMs && !this._dwellFired) {
      this._dwellFired = true;
      bus.emit('gaze:dwell', { zone, dwellMs, x, y });
    }

    // 7. Emit update
    bus.emit('gaze:update', {
      x, y,
      zone,
      confidence: rawGaze.confidence,
      dwellMs,
      calibrated: this.calibration.isCalibrated,
    });
  }

  /**
   * Compute iris position as ratio within eye socket.
   * Returns {x: 0-1, y: 0-1, confidence} where 0.5,0.5 = looking straight.
   */
  _computeIrisRatio(lm) {
    try {
      const leftIris = lm[IRIS.LEFT_CENTER];
      const rightIris = lm[IRIS.RIGHT_CENTER];
      const leftInner = lm[IRIS.LEFT_INNER];
      const leftOuter = lm[IRIS.LEFT_OUTER];
      const rightInner = lm[IRIS.RIGHT_INNER];
      const rightOuter = lm[IRIS.RIGHT_OUTER];
      const leftUpper = lm[IRIS.LEFT_UPPER];
      const leftLower = lm[IRIS.LEFT_LOWER];
      const rightUpper = lm[IRIS.RIGHT_UPPER];
      const rightLower = lm[IRIS.RIGHT_LOWER];

      // Horizontal: iris position within eye socket (0 = outer, 1 = inner)
      const leftEyeWidth = Math.abs(leftInner.x - leftOuter.x);
      const rightEyeWidth = Math.abs(rightInner.x - rightOuter.x);

      if (leftEyeWidth < 0.005 || rightEyeWidth < 0.005) return null;

      const leftRatioX = (leftIris.x - leftOuter.x) / leftEyeWidth;
      const rightRatioX = (rightIris.x - rightOuter.x) / rightEyeWidth;

      // Vertical: iris position within eye height
      const leftEyeHeight = Math.abs(leftLower.y - leftUpper.y);
      const rightEyeHeight = Math.abs(rightLower.y - rightUpper.y);

      let leftRatioY = 0.5;
      let rightRatioY = 0.5;
      if (leftEyeHeight > 0.003) {
        leftRatioY = (leftIris.y - leftUpper.y) / leftEyeHeight;
      }
      if (rightEyeHeight > 0.003) {
        rightRatioY = (rightIris.y - rightUpper.y) / rightEyeHeight;
      }

      // Clamp ratios to valid range
      const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
      const avgX = clamp((leftRatioX + rightRatioX) / 2, 0, 1);
      const avgY = clamp((leftRatioY + rightRatioY) / 2, 0, 1);

      // Confidence based on eye openness (closed eyes = low confidence)
      const openness = (leftEyeHeight + rightEyeHeight) / 2;
      const confidence = Math.min(openness / 0.02, 1);

      return { x: avgX, y: avgY, confidence };
    } catch (e) {
      return null;
    }
  }

  /**
   * Compensate for head rotation/tilt using nose-forehead axis.
   * When head turns left, iris appears to shift right in image space.
   * We subtract the head rotation component to isolate true gaze.
   */
  _compensateHeadPose(gaze, lm) {
    try {
      const nose = lm[IRIS.NOSE_TIP];
      const forehead = lm[IRIS.FOREHEAD];
      const chin = lm[IRIS.CHIN];

      // Head yaw: nose tip horizontal offset from face center
      const faceCenter = (lm[IRIS.LEFT_OUTER].x + lm[IRIS.RIGHT_OUTER].x) / 2;
      const headYaw = (nose.x - faceCenter) * 2; // normalized offset

      // Head pitch: nose-chin angle
      const faceHeight = Math.abs(forehead.y - chin.y);
      const headPitch = faceHeight > 0.05
        ? ((nose.y - forehead.y) / faceHeight - 0.5) * 2
        : 0;

      // Subtract head pose contribution (empirical coefficients)
      const compensatedX = gaze.x - headYaw * 0.3;
      const compensatedY = gaze.y - headPitch * 0.2;

      return {
        x: Math.max(0, Math.min(1, compensatedX)),
        y: Math.max(0, Math.min(1, compensatedY)),
      };
    } catch (e) {
      return gaze;
    }
  }

  // ── Calibration API ──

  /**
   * Start calibration sequence. Returns the 5 points to show.
   */
  startCalibration() {
    this.calibration.reset();
    return [
      { x: 0.5, y: 0.5, label: '中心' },
      { x: 0.1, y: 0.1, label: '左上' },
      { x: 0.9, y: 0.1, label: '右上' },
      { x: 0.1, y: 0.9, label: '左下' },
      { x: 0.9, y: 0.9, label: '右下' },
    ];
  }

  /**
   * Record a calibration point. Call when user is looking at the target.
   * @param {number} screenX - target x (0-1)
   * @param {number} screenY - target y (0-1)
   * @param {Array} landmarks - current face landmarks
   */
  recordCalibrationPoint(screenX, screenY, landmarks) {
    const rawGaze = this._computeIrisRatio(landmarks);
    if (!rawGaze) return false;

    this.calibration.addPoint(screenX, screenY, rawGaze.x, rawGaze.y);
    return true;
  }

  /**
   * Finalize calibration.
   */
  finishCalibration() {
    const ok = this.calibration.compute();
    if (ok) {
      bus.emit('gaze:calibrated', this.calibration.toJSON());
    }
    return ok;
  }

  /**
   * Load saved calibration data.
   */
  loadCalibration(data) {
    this.calibration.fromJSON(data);
  }

  reset() {
    this._smoothX.reset();
    this._smoothY.reset();
    this._currentZone = null;
    this._zoneStartTime = 0;
    this._dwellFired = false;
  }
}
