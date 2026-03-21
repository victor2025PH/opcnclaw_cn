// intent-panel.js — Backend intent fusion visualization (P0)
import { getBaseUrl, bus, t } from '/js/state.js';

const API = () => getBaseUrl() + '/api/intent';
const POLL_MS = 2000;
const TIMELINE_MS = 500;

const CH = [
  { id: 'gaze', icon: '\u{1F440}', labelKey: 'intent.ch_gaze' },
  { id: 'expression', icon: '\u{1F60A}', labelKey: 'intent.ch_expr' },
  { id: 'voice', icon: '\u{1F3A4}', labelKey: 'intent.ch_voice' },
  { id: 'touch', icon: '\u{1F446}', labelKey: 'intent.ch_touch' },
  { id: 'desktop', icon: '\u{1F5A5}\uFE0F', labelKey: 'intent.ch_desktop' },
];

let _panel = null;
let _badge = null;
let _poll = null;
let _open = false;
let _lastState = null;

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
}

function pickChannelSignals(signals, ch) {
  return (signals || []).filter(s => (s.channel || '') === ch);
}

function renderChannels(signals) {
  return CH.map(ch => {
    const list = pickChannelSignals(signals, ch.id);
    const last = list.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))[0];
    const line = last
      ? `${esc(last.name)} · ${Math.round((last.confidence || 0) * 100)}%`
      : '—';
    return `
      <div class="ip-ch-item" data-ch="${ch.id}">
        <span class="ip-ch-ico">${ch.icon}</span>
        <div class="ip-ch-body">
          <div class="ip-ch-label">${t(ch.labelKey)}</div>
          <div class="ip-ch-val">${line}</div>
        </div>
      </div>`;
  }).join('');
}

function renderFusion(cur) {
  if (!cur) {
    return `<div class="ip-fusion-empty">${t('intent.fusion_none')}</div>`;
  }
  const pct = Math.round((cur.confidence || 0) * 100);
  const boost = cur.boosted ? ` · ${t('intent.boosted')} ×${cur.boost_factor || 1}` : '';
  return `
    <div class="ip-fusion-main">
      <div class="ip-fusion-intent">${esc(cur.intent)}</div>
      <div class="ip-fusion-meta">${pct}%${boost} · ${(cur.channels || []).join(',') || '—'}</div>
      <div class="ip-fusion-bar"><div class="ip-fusion-fill" style="width:${pct}%"></div></div>
    </div>`;
}

function drawTimeline(signals) {
  const svg = _panel?.querySelector('.ip-timeline-svg');
  if (!svg) return;
  const w = 280;
  const h = 72;
  const rowH = h / CH.length;
  const now = Date.now() / 1000;
  const dots = [];
  for (const s of signals || []) {
    const ts = typeof s.timestamp === 'number' ? s.timestamp : parseFloat(s.timestamp);
    if (!ts) continue;
    const ageMs = (now - ts) * 1000;
    if (ageMs < 0 || ageMs > TIMELINE_MS) continue;
    const x = (1 - ageMs / TIMELINE_MS) * (w - 8) + 4;
    const idx = CH.findIndex(c => c.id === (s.channel || ''));
    const y = (idx >= 0 ? idx : CH.length - 1) * rowH + rowH / 2;
    dots.push(`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="var(--accent)" opacity="0.85"/>`);
  }
  const grid = CH.map((_, i) => {
    const y = (i + 1) * rowH;
    return `<line x1="4" y1="${y}" x2="${w - 4}" y2="${y}" stroke="var(--border)" stroke-width="0.5" opacity="0.35"/>`;
  }).join('');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.innerHTML = `
    <text x="4" y="10" font-size="9" fill="var(--text-muted)">0.5s</text>
    <text x="${w - 36}" y="10" font-size="9" fill="var(--text-muted)">now</text>
    ${grid}
    ${dots.join('')}`;
}

function renderPanel() {
  if (!_panel || !_lastState) return;
  const st = _lastState;
  const sigs = st.active_signals || [];
  _panel.querySelector('.ip-channels').innerHTML = renderChannels(sigs);
  _panel.querySelector('.ip-fusion-slot').innerHTML = renderFusion(st.current_intent);
  const stats = st.stats || {};
  _panel.querySelector('.ip-stats').textContent =
    `${t('intent.stats')} · ${stats.signals_received ?? 0} / ${stats.fusions_performed ?? 0} / ${stats.emergency_stops ?? 0}`;
  drawTimeline(sigs);
  const run = st.running;
  _panel.querySelector('.ip-engine-status').textContent = run ? t('intent.engine_on') : t('intent.engine_off');
  _panel.querySelector('.ip-engine-status').classList.toggle('ok', !!run);
}

function renderBadge() {
  if (!_badge) return;
  const cur = _lastState?.current_intent;
  if (cur?.intent) {
    _badge.textContent = '\u{1F9E0}';
    _badge.title = `${cur.intent} · ${Math.round((cur.confidence || 0) * 100)}%`;
    _badge.style.setProperty('--ip-glow', 'var(--accent)');
  } else {
    _badge.textContent = '\u{1F9E0}';
    _badge.title = t('intent.badge_title');
    _badge.style.setProperty('--ip-glow', 'var(--text-muted)');
  }
}

async function poll() {
  try {
    const r = await fetch(API() + '/state');
    if (!r.ok) throw new Error(String(r.status));
    _lastState = await r.json();
    renderBadge();
    if (_open) renderPanel();
    bus.emit('intent:fusion', _lastState);
  } catch {
    _lastState = { running: false, active_signals: [], current_intent: null, stats: {} };
    renderBadge();
    if (_open) renderPanel();
  }
}

async function postEmergency() {
  try {
    const r = await fetch(API() + '/emergency', { method: 'POST' });
    const d = await r.json().catch(() => ({}));
    if (r.ok) await poll();
    return d;
  } catch {
    return null;
  }
}

async function postTestSignal(channel, name) {
  try {
    await fetch(API() + '/signal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel, name, confidence: 0.92 }),
    });
    await poll();
  } catch { /* */ }
}

function toggle() {
  _open = !_open;
  _panel.classList.toggle('open', _open);
  _badge.classList.toggle('active', _open);
  if (_open) {
    poll();
    renderPanel();
  }
}

function buildPanel() {
  _panel = document.createElement('div');
  _panel.className = 'ip-panel';
  _panel.innerHTML = `
    <div class="ip-header">
      <span class="ip-header-title">\u{1F9E0} ${t('intent.title')}</span>
      <span class="ip-engine-status"></span>
      <button class="ip-close" type="button" aria-label="close">\u2715</button>
    </div>
    <div class="ip-fusion-slot"></div>
    <div class="ip-channels"></div>
    <div class="ip-timeline-wrap">
      <div class="ip-timeline-label">${t('intent.timeline')} (${TIMELINE_MS}ms)</div>
      <svg class="ip-timeline-svg" width="100%" height="72" xmlns="http://www.w3.org/2000/svg"></svg>
    </div>
    <div class="ip-stats ip-muted"></div>
    <div class="ip-actions">
      <button type="button" class="ip-btn ip-btn-danger" id="ip-emergency">\u{1F6D1} ${t('intent.emergency')}</button>
    </div>
    <details class="ip-dev">
      <summary>${t('intent.dev_tests')}</summary>
      <div class="ip-dev-btns">
        <button type="button" data-ch="expression" data-name="nod">${t('intent.test_nod')}</button>
        <button type="button" data-ch="voice" data-name="confirm">${t('intent.test_voice')}</button>
        <button type="button" data-ch="touch" data-name="tap">${t('intent.test_touch')}</button>
      </div>
    </details>
  `;
  _panel.querySelector('.ip-close').addEventListener('click', toggle);
  _panel.querySelector('#ip-emergency').addEventListener('click', () => postEmergency());
  _panel.querySelector('.ip-dev-btns').addEventListener('click', e => {
    const b = e.target.closest('button[data-ch]');
    if (!b) return;
    postTestSignal(b.dataset.ch, b.dataset.name);
  });
  document.addEventListener('click', e => {
    if (_open && !_panel.contains(e.target) && e.target !== _badge && !_badge.contains(e.target)) {
      toggle();
    }
  });
  return _panel;
}

export function initIntentPanel() {
  const headerRight = document.querySelector('.header-right');
  if (!headerRight) return;

  _badge = document.createElement('button');
  _badge.className = 'icon-btn ip-badge';
  _badge.id = 'intent-toggle';
  _badge.type = 'button';
  _badge.title = t('intent.badge_title');
  _badge.textContent = '\u{1F9E0}';
  _badge.addEventListener('click', e => {
    e.stopPropagation();
    toggle();
  });

  const settingsBtn = document.getElementById('settings-toggle');
  headerRight.insertBefore(_badge, settingsBtn);

  headerRight.appendChild(buildPanel());

  const overflowMenu = document.getElementById('header-overflow-menu');
  if (overflowMenu) {
    const firstSep = overflowMenu.querySelector('.hom-sep');
    const homItem = document.createElement('button');
    homItem.className = 'hom-item';
    homItem.dataset.target = 'intent-toggle';
    homItem.innerHTML = '<span class="hom-icon">\u{1F9E0}</span>' + t('intent.title');
    if (firstSep) overflowMenu.insertBefore(homItem, firstSep);
    else overflowMenu.appendChild(homItem);
  }

  poll();
  _poll = setInterval(poll, POLL_MS);
}
