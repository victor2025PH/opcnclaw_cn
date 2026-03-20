/**
 * Lightweight event bus for inter-module communication.
 * All multimodal modules (gesture, expression, gaze, desktop)
 * publish signals here; the fusion engine subscribes.
 */
export class EventBus {
  constructor() {
    this._listeners = new Map();
  }

  on(event, fn) {
    if (!this._listeners.has(event)) this._listeners.set(event, []);
    this._listeners.get(event).push(fn);
    return () => this.off(event, fn);
  }

  off(event, fn) {
    const arr = this._listeners.get(event);
    if (!arr) return;
    const idx = arr.indexOf(fn);
    if (idx >= 0) arr.splice(idx, 1);
  }

  emit(event, data) {
    const arr = this._listeners.get(event);
    if (!arr) return;
    for (const fn of arr) {
      try { fn(data); } catch (e) { console.error(`[EventBus] ${event}:`, e); }
    }
  }

  once(event, fn) {
    const wrapper = (data) => { this.off(event, wrapper); fn(data); };
    return this.on(event, wrapper);
  }
}

export const bus = new EventBus();
