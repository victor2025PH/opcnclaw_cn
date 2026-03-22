// settings.js — Orchestrator (sections extracted to settings-models.js, settings-wechat.js, settings-chat.js)
import { S, fn, dom, t, $, $$, getBaseUrl, escapeHtml, bus, expressionSystem, gazeTracker, intentFusion, EXPR_PRESETS } from '/js/state.js';
import { initWechatPanel } from '/js/settings-wechat.js';
import { initModelPanel, initMcpPanel, initModelDepGraph } from '/js/settings-models.js';
import { initMessageSearch, initBookmarks, initReactions, initTranslate, initMessageExport, initMessageEdit, initPinnedMessages, initSummary } from '/js/settings-chat.js';
import { initIntentPanel } from '/js/intent-panel.js';
import { initCoworkPanel } from '/js/cowork-panel.js';
import { initGestureBindings } from '/js/gesture-bindings.js';
import { initActionTimeline } from '/js/action-timeline.js';
import { invalidatePetGainCache, petBroadcast, petSetSkin, petGetSkin, PET_SKIN_IDS } from '/js/pet-bridge.js';

const PET_SKIN_I18N_KEYS = {
  eve: 'settings.petSkinEve',
  walle: 'settings.petSkinWalle',
  orbit: 'settings.petSkinOrbit',
};

// ══════════════════════════════════════════════════════════════
// EMOTION INDICATOR (module-scope)
// ══════════════════════════════════════════════════════════════
const _emojiMap = {
  happy: '😊', sad: '😢', angry: '😠', surprised: '😲', fearful: '😰', neutral: ''
};
const _emoLabelMap = {
  happy: '开心', sad: '低落', angry: '激动', surprised: '惊讶', fearful: '紧张', neutral: ''
};
let _emoTimer = null;

function showEmotionBadge(emotion, dominant) {
  const emo = dominant || emotion || 'neutral';
  if (emo === 'neutral') return;
  const badge = document.getElementById('emotion-badge');
  const emoji = document.getElementById('emo-emoji');
  const text = document.getElementById('emo-text');
  if (!badge) return;
  emoji.textContent = _emojiMap[emo] || '';
  text.textContent = _emoLabelMap[emo] || emo;
  badge.classList.remove('hidden');
  clearTimeout(_emoTimer);
  _emoTimer = setTimeout(() => badge.classList.add('hidden'), 8000);
}

// ══════════════════════════════════════════════════════════════
// TOAST NOTIFICATION SYSTEM (module-scope)
// ══════════════════════════════════════════════════════════════
const ocToast = (function() {
  const container = document.getElementById('oc-toast-container');
  const MAX = 5;

  function show(message, type, duration) {
    type = type || 'info';
    duration = duration || 4000;
    if (!container) return;
    while (container.children.length >= MAX) container.removeChild(container.firstChild);
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    const el = document.createElement('div');
    el.className = 'oc-toast ' + type;
    el.setAttribute('role', 'alert');
    el.innerHTML = `<span class="oc-toast-icon">${icons[type] || icons.info}</span><span class="oc-toast-body">${message}</span><button class="oc-toast-close" aria-label="Dismiss">&times;</button>`;
    el.querySelector('.oc-toast-close').addEventListener('click', () => dismiss(el));
    container.appendChild(el);
    const timer = setTimeout(() => dismiss(el), duration);
    el._timer = timer;
    return el;
  }

  function dismiss(el) {
    if (!el || !el.parentNode) return;
    clearTimeout(el._timer);
    el.classList.add('removing');
    setTimeout(() => { if (el.parentNode) el.parentNode.removeChild(el); }, 250);
  }

  function showAndLog(message, type, duration) {
    const el = show(message, type, duration);
    window.dispatchEvent(new CustomEvent('oc-notification', { detail: { message, type: type || 'info', time: Date.now() } }));
    return el;
  }

  return { show: showAndLog, success: (m, d) => showAndLog(m, 'success', d), error: (m, d) => showAndLog(m, 'error', d), warning: (m, d) => showAndLog(m, 'warning', d), info: (m, d) => showAndLog(m, 'info', d) };
})();
window.ocToast = ocToast;

// ══════════════════════════════════════════════════════════════
// PERFORMANCE PANEL (module-scope)
// ══════════════════════════════════════════════════════════════
const ocPerf = (function() {
  const $id = id => document.getElementById(id);
  const _history = [];
  const MAX_POINTS = 30;
  let _timestamps = {};
  let _totalReqs = 0;
  let _latencySum = 0;

  function openPanel() { $id('perf-panel').classList.remove('hidden'); drawChart(); }
  function closePanel() { $id('perf-panel').classList.add('hidden'); }

  $id('perf-toggle')?.addEventListener('click', openPanel);
  $id('perf-back')?.addEventListener('click', closePanel);

  function gradeCard(el, ms) {
    el.classList.remove('good', 'warn', 'bad');
    if (ms < 500) el.classList.add('good');
    else if (ms < 2000) el.classList.add('warn');
    else el.classList.add('bad');
  }

  function formatMs(ms) { return ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(1) + ' s'; }

  function mark(key) { _timestamps[key] = performance.now(); }

  function measure(startKey, endKey) {
    const s = _timestamps[startKey], e = endKey ? _timestamps[endKey] : performance.now();
    return (s && e) ? Math.round(e - s) : null;
  }

  function recordCycle(stt, ai, tts) {
    const total = (stt || 0) + (ai || 0) + (tts || 0);
    _history.push({ stt: stt || 0, ai: ai || 0, tts: tts || 0, total, time: Date.now() });
    if (_history.length > MAX_POINTS) _history.shift();
    _totalReqs++;
    _latencySum += total;

    if (stt != null) { $id('perf-stt-val').textContent = formatMs(stt); gradeCard($id('perf-stt'), stt); }
    if (ai != null) { $id('perf-ai-val').textContent = formatMs(ai); gradeCard($id('perf-ai'), ai); }
    if (tts != null) { $id('perf-tts-val').textContent = formatMs(tts); gradeCard($id('perf-tts'), tts); }
    $id('perf-total-reqs').textContent = _totalReqs;
    $id('perf-avg-latency').textContent = formatMs(Math.round(_latencySum / _totalReqs));

    if (!$id('perf-panel').classList.contains('hidden')) drawChart();
  }

  function setWsLatency(ms) {
    $id('perf-ws-val').textContent = formatMs(ms);
    gradeCard($id('perf-ws'), ms);
  }

  function drawChart() {
    const canvas = $id('perf-canvas');
    if (!canvas || _history.length === 0) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.parentElement.clientWidth;
    const h = canvas.parentElement.clientHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);

    const maxVal = Math.max(..._history.map(p => p.total), 500);
    const barW = Math.max(4, (w - 20) / MAX_POINTS - 2);
    const colors = { stt: '#4ade80', ai: '#7c6aef', tts: '#fbbf24' };

    _history.forEach((p, i) => {
      const x = 10 + i * ((w - 20) / MAX_POINTS);
      let y = h;
      for (const key of ['stt', 'ai', 'tts']) {
        const segH = (p[key] / maxVal) * (h - 10);
        y -= segH;
        ctx.fillStyle = colors[key];
        ctx.fillRect(x, y, barW, segH);
      }
    });

    ctx.fillStyle = 'rgba(255,255,255,.3)';
    ctx.font = '9px sans-serif';
    ctx.fillText('0ms', 2, h - 2);
    ctx.fillText(formatMs(maxVal), 2, 10);
  }

  return { mark, measure, recordCycle, setWsLatency, openPanel, closePanel };
})();
window.ocPerf = ocPerf;

// ══════════════════════════════════════════════════════════════
// MCP TOOL CALL HISTORY (module-scope)
// ══════════════════════════════════════════════════════════════
const mcpHistory = (function() {
  const MAX = 50;
  const KEY = 'oc-mcp-history';
  let _records = JSON.parse(localStorage.getItem(KEY) || '[]');

  function save() {
    if (_records.length > MAX) _records = _records.slice(-MAX);
    localStorage.setItem(KEY, JSON.stringify(_records));
  }

  function add(toolName, params, result, ok) {
    _records.push({
      tool: toolName,
      params: JSON.parse(JSON.stringify(params)),
      result: typeof result === 'string' ? result : JSON.stringify(result),
      ok,
      time: Date.now(),
    });
    save();
    render();
  }

  function clear() {
    _records = [];
    localStorage.removeItem(KEY);
    render();
  }

  function render() {
    const list = document.getElementById('mcp-history-list');
    const empty = document.getElementById('mcp-no-history');
    if (!list) return;
    if (_records.length === 0) {
      list.innerHTML = '';
      if (empty) empty.classList.remove('hidden');
      return;
    }
    if (empty) empty.classList.add('hidden');
    list.innerHTML = [..._records].reverse().slice(0, 20).map((r, i) => {
      const dt = new Date(r.time);
      const timeStr = dt.getHours().toString().padStart(2, '0') + ':' + dt.getMinutes().toString().padStart(2, '0');
      const preview = (r.result || '').slice(0, 80);
      return `<div class="mcp-history-item">
        <span class="mcp-h-tool">${r.tool}</span><span class="mcp-h-time">${timeStr}</span>
        <div class="mcp-h-result">${r.ok ? '' : '❌ '}${preview}${(r.result || '').length > 80 ? '…' : ''}</div>
        <div class="mcp-h-actions">
          <button class="mp-btn" style="font-size:10px;padding:2px 8px;background:var(--bg-surface);color:var(--accent)" data-replay="${_records.length - 1 - i}" data-i18n="mcp.replay">重放</button>
        </div>
      </div>`;
    }).join('');
    list.querySelectorAll('[data-replay]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.replay);
        const rec = _records[idx];
        if (rec && window._mcpReplayCallback) window._mcpReplayCallback(rec.tool, rec.params);
      });
    });
  }

  document.getElementById('mcp-clear-history')?.addEventListener('click', () => {
    if (confirm(t('mcp.clearHistoryConfirm'))) clear();
  });

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    requestAnimationFrame(render);
  } else {
    document.addEventListener('DOMContentLoaded', render, { once: true });
  }

  return { add, clear, render };
})();
// Expose mcpHistory for settings-models.js (initMcpPanel uses it)
window._mcpHistoryRef = mcpHistory;

// ══════════════════════════════════════════════════════════════
// COMMAND PALETTE (module-scope)
// ══════════════════════════════════════════════════════════════
const ocCmdPalette = (function() {
  const $id = id => document.getElementById(id);
  const RKEY = 'oc-cmd-recent';
  let _open = false;
  let _idx = 0;
  let _items = [];
  let _recent = JSON.parse(localStorage.getItem(RKEY) || '[]');

  function buildRegistry() {
    const items = [
      { id: 'panel:model',   icon: '📦', label: t('model.title') || '模型管理',     hint: 'Ctrl+M',       action: () => { const p = $id('model-panel'); p.classList.toggle('hidden'); if(!p.classList.contains('hidden')) p.focus(); } },
      { id: 'panel:mcp',     icon: '🔧', label: t('mcp.title') || 'MCP 工具',       hint: 'Ctrl+T',       action: () => { const p = $id('mcp-panel'); p.classList.toggle('hidden'); if(!p.classList.contains('hidden')) p.focus(); } },
      { id: 'panel:perf',    icon: '📊', label: t('perf.title') || '性能监控',       hint: 'Ctrl+P',       action: () => { ocPerf?.openPanel(); } },
      { id: 'panel:vcmd',    icon: '🗣️', label: t('vcmd.title') || '语音指令',       hint: '',             action: () => $id('voice-cmd-panel')?.classList.remove('hidden') },
      { id: 'panel:settings', icon: '⚙️', label: t('settings.title') || '设置',       hint: '',             action: () => $id('settings-modal')?.classList.remove('hidden') },
      { id: 'theme:dark',    icon: '🌑', label: 'Dark Theme',                        hint: 'Ctrl+Shift+D', action: () => { const s = $id('theme-select'); if(s){s.value='dark';s.dispatchEvent(new Event('change'));} } },
      { id: 'theme:light',   icon: '☀️', label: 'Light Theme',                       hint: 'Ctrl+Shift+D', action: () => { const s = $id('theme-select'); if(s){s.value='light';s.dispatchEvent(new Event('change'));} } },
      { id: 'theme:auto',    icon: '🌗', label: 'Auto Theme',                        hint: 'Ctrl+Shift+D', action: () => { const s = $id('theme-select'); if(s){s.value='auto';s.dispatchEvent(new Event('change'));} } },
      { id: 'action:voice',  icon: '🎙️', label: t('shortcuts.voice') || '语音输入',   hint: 'Space',        action: () => { fn.startVoiceRecording?.(); } },
      { id: 'action:shortcuts', icon: '⌨️', label: t('shortcuts.title') || '快捷键', hint: 'Ctrl+/',       action: () => $id('shortcuts-overlay')?.classList.add('open') },
      { id: 'action:export', icon: '📤', label: t('settings.export') || '导出设置',   hint: '',             action: () => $id('settings-export')?.click() },
      { id: 'action:import', icon: '📥', label: t('settings.import') || '导入设置',   hint: '',             action: () => $id('settings-import')?.click() },
    ];

    try {
      const vcmdList = $id('vcmd-list');
      if (vcmdList) {
        vcmdList.querySelectorAll('.vcmd-card').forEach(card => {
          const id = card.dataset.id;
          const name = card.querySelector('.vcmd-name')?.textContent || id;
          items.push({ id: 'skill:' + id, icon: '⚡', label: name, hint: '', action: () => {
            fetch(getBaseUrl() + `/api/desktop-skill/${id}`, { method: 'POST' }).then(r => r.json())
              .then(d => window.ocToast?.success(d.message || 'OK')).catch(e => window.ocToast?.error(e.message));
          }});
        });
      }
    } catch {}

    try {
      document.querySelectorAll('.mcp-tool-chip').forEach(chip => {
        const name = chip.dataset.toolName || chip.textContent.trim().replace(/★|☆/g, '').trim();
        if (name) items.push({ id: 'mcp:' + name, icon: '🔧', label: 'MCP: ' + name, hint: '', action: () => chip.click() });
      });
    } catch {}

    return items;
  }

  function fuzzyMatch(query, text) {
    const q = query.toLowerCase();
    const txt = text.toLowerCase();
    if (txt.includes(q)) return true;
    let qi = 0;
    for (let i = 0; i < txt.length && qi < q.length; i++) {
      if (txt[i] === q[qi]) qi++;
    }
    return qi === q.length;
  }

  function render(filtered) {
    _items = filtered;
    const el = $id('cmd-results');
    if (!filtered.length) {
      el.innerHTML = `<div class="cmd-empty" data-i18n="cmd.empty">${t('cmd.empty')}</div>`;
      return;
    }
    el.innerHTML = filtered.map((it, i) => `
      <div class="cmd-item${i === _idx ? ' selected' : ''}" data-i="${i}">
        <span class="cmd-icon">${it.icon}</span>
        <span class="cmd-label">${it.label}</span>
        ${it.hint ? `<span class="cmd-hint">${it.hint}</span>` : ''}
      </div>
    `).join('');
    el.querySelectorAll('.cmd-item').forEach(row => {
      row.addEventListener('click', () => execute(+row.dataset.i));
      row.addEventListener('mouseenter', () => {
        _idx = +row.dataset.i;
        el.querySelectorAll('.cmd-item').forEach((r, j) => r.classList.toggle('selected', j === _idx));
      });
    });
  }

  function execute(i) {
    const item = _items[i];
    if (!item) return;
    close();
    _recent = _recent.filter(r => r !== item.id);
    _recent.unshift(item.id);
    if (_recent.length > 8) _recent = _recent.slice(0, 8);
    localStorage.setItem(RKEY, JSON.stringify(_recent));
    item.action();
  }

  function open() {
    _open = true;
    _idx = 0;
    const registry = buildRegistry();
    const recentSet = new Set(_recent);
    const sorted = [
      ...registry.filter(it => recentSet.has(it.id)),
      ...registry.filter(it => !recentSet.has(it.id))
    ];
    render(sorted);
    $id('cmd-overlay').classList.add('open');
    const input = $id('cmd-input');
    input.value = '';
    input.placeholder = t('cmd.placeholder');
    setTimeout(() => input.focus(), 50);
  }

  function close() {
    _open = false;
    $id('cmd-overlay').classList.remove('open');
  }

  function toggle() { _open ? close() : open(); }

  $id('cmd-input')?.addEventListener('input', (e) => {
    const q = e.target.value.trim();
    const registry = buildRegistry();
    _idx = 0;
    if (!q) {
      const recentSet = new Set(_recent);
      render([...registry.filter(it => recentSet.has(it.id)), ...registry.filter(it => !recentSet.has(it.id))]);
    } else {
      render(registry.filter(it => fuzzyMatch(q, it.label + ' ' + (it.hint || ''))));
    }
  });

  $id('cmd-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); _idx = Math.min(_idx + 1, _items.length - 1); highlightIdx(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); _idx = Math.max(_idx - 1, 0); highlightIdx(); }
    else if (e.key === 'Enter') { e.preventDefault(); execute(_idx); }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
  });

  function highlightIdx() {
    $id('cmd-results').querySelectorAll('.cmd-item').forEach((r, j) => {
      r.classList.toggle('selected', j === _idx);
      if (j === _idx) r.scrollIntoView({ block: 'nearest' });
    });
  }

  $id('cmd-overlay')?.addEventListener('click', (e) => { if (e.target.id === 'cmd-overlay') close(); });

  return { open, close, toggle };
})();
window.ocCmdPalette = ocCmdPalette;


// ══════════════════════════════════════════════════════════════
// 1. MODEL MANAGEMENT PANEL — moved to settings-models.js
// ══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════
// 2. MCP TOOLS PANEL — moved to settings-models.js
// ══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════
// 3. EMOTION INDICATOR — settings toggle
// ══════════════════════════════════════════════════════════════
function initEmotionIndicator() {
  const toggle = document.getElementById('emotion-toggle');
  const knob = document.getElementById('emotion-knob');
  if (!toggle || !knob) return;

  function updateKnob() {
    knob.style.left = toggle.checked ? '25px' : '3px';
    knob.parentElement.previousElementSibling.style.background = toggle.checked ? 'var(--accent)' : 'var(--bg-surface)';
  }
  updateKnob();

  toggle.addEventListener('change', async () => {
    updateKnob();
    try {
      await fetch(getBaseUrl() + '/api/emotion/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: toggle.checked }),
      });
    } catch(e) { console.warn('emotion toggle:', e); }
  });

  async function syncEmotionState() {
    try {
      const r = await fetch(getBaseUrl() + '/api/emotion/state');
      if (r.ok) {
        const d = await r.json();
        toggle.checked = d.enabled;
        updateKnob();
      }
    } catch {}
  }

  const origSettings = document.getElementById('settings-toggle');
  if (origSettings) {
    origSettings.addEventListener('click', () => setTimeout(syncEmotionState, 300));
  }
}

// ══════════════════════════════════════════════════════════════
// 4. THEME SWITCHER (dark / light / auto)
// ══════════════════════════════════════════════════════════════
function initThemeSwitcher() {
  const sel = document.getElementById('theme-select');
  if (!sel) return;
  const mq = window.matchMedia('(prefers-color-scheme: light)');
  const quickBtn = document.getElementById('theme-quick-toggle');

  function resolveTheme(pref) {
    if (pref === 'auto') return mq.matches ? 'light' : 'dark';
    return pref;
  }

  function syncQuickThemeBtn() {
    const resolved = document.documentElement.getAttribute('data-theme') || 'dark';
    if (!quickBtn) return;
    const isLight = resolved === 'light';
    quickBtn.title = t('header.themeToggle');
    quickBtn.setAttribute('aria-label', t('header.themeToggle'));
    quickBtn.setAttribute('aria-pressed', isLight ? 'true' : 'false');
    quickBtn.innerHTML = isLight
      ? '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.79A9 9 0 0 1 11.21 3 7 7 0 1 0 21 12.79z"/></svg>'
      : '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>';
  }

  function applyTheme(resolved) {
    document.documentElement.setAttribute('data-theme', resolved);
    const mc = document.querySelector('meta[name="theme-color"]');
    if (mc) mc.content = resolved === 'light' ? '#f5f5fa' : '#0a0a14';
    syncQuickThemeBtn();
  }

  const saved = localStorage.getItem('oc-theme') || 'dark';
  sel.value = saved;
  applyTheme(resolveTheme(saved));

  sel.addEventListener('change', () => {
    localStorage.setItem('oc-theme', sel.value);
    applyTheme(resolveTheme(sel.value));
  });

  mq.addEventListener('change', () => {
    if (sel.value === 'auto') applyTheme(resolveTheme('auto'));
  });

  quickBtn?.addEventListener('click', () => {
    const resolved = document.documentElement.getAttribute('data-theme') || 'dark';
    sel.value = resolved === 'light' ? 'dark' : 'light';
    localStorage.setItem('oc-theme', sel.value);
    applyTheme(resolveTheme(sel.value));
  });
}

// ══════════════════════════════════════════════════════════════
// 5. UI MODE SWITCHER (simple / pro)
// ══════════════════════════════════════════════════════════════
function initUiModeSwitcher() {
  const sel = document.getElementById('ui-mode-select');
  if (!sel) return;

  function applyMode(mode) {
    if (mode === 'pro') {
      document.documentElement.classList.add('pro-mode');
    } else {
      document.documentElement.classList.remove('pro-mode');
    }
  }

  const saved = localStorage.getItem('oc-ui-mode') || 'simple';
  sel.value = saved;
  applyMode(saved);

  sel.addEventListener('change', () => {
    localStorage.setItem('oc-ui-mode', sel.value);
    applyMode(sel.value);
  });
}

// ══════════════════════════════════════════════════════════════
// 6. VOICE CLONE UI
// ══════════════════════════════════════════════════════════════
function initVoiceClone() {
  const listEl = document.getElementById('clone-voices-list');
  const nameInput = document.getElementById('clone-voice-name');
  const recordBtn = document.getElementById('clone-record-btn');
  const stopBtn = document.getElementById('clone-stop-btn');
  const uploadInput = document.getElementById('clone-upload-input');
  const statusEl = document.getElementById('clone-status');
  const recordingUI = document.getElementById('clone-recording-ui');
  const timerEl = document.getElementById('clone-timer');
  if (!recordBtn) return;

  let mediaRecorder = null;
  let chunks = [];
  let timerInterval = null;
  let startTime = 0;

  async function loadClones() {
    try {
      const r = await fetch(getBaseUrl() + '/api/voice-clone/list');
      const d = await r.json();
      if (!d.ok || !d.voices?.length) {
        listEl.innerHTML = `<div style="font-size:12px;color:var(--text-muted);padding:8px 0">${escapeHtml(t('clone.empty'))}</div>`;
        return;
      }
      listEl.innerHTML = d.voices.map((v) => {
        const active = d.active_path?.includes(v.name);
        const safeName = escapeHtml(v.name);
        return `
        <div class="clone-voice-card${active ? ' clone-voice-card--active' : ''}">
          <span class="clone-voice-icon" aria-hidden="true">🎭</span>
          <span class="clone-voice-meta">${safeName}</span>
          <span class="clone-voice-dur">${v.duration ? `${v.duration}s` : ''}</span>
          <button type="button" class="btn settings-btn settings-btn--primary settings-btn--compact" onclick="_cloneActivate(${JSON.stringify(v.name)})">${escapeHtml(active ? t('clone.inUse') : t('clone.use'))}</button>
          <button type="button" class="settings-icon-btn" onclick="_cloneDelete(${JSON.stringify(v.name)})" aria-label="${escapeHtml(t('clone.delete'))}">✕</button>
        </div>`;
      }).join('');
    } catch (e) {
      listEl.innerHTML = `<div style="font-size:12px;color:var(--text-muted)">${escapeHtml(t('clone.loadFail'))}</div>`;
    }
  }

  window._cloneActivate = async function(name) {
    try {
      await fetch(getBaseUrl() + '/api/voice-clone/activate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ name })
      });
      window.ocToast?.success(t('clone.switchToast'));
      loadClones();
    } catch (e) {}
  };

  window._cloneDelete = async function(name) {
    if (!confirm(t('clone.deleteConfirm', { name }))) return;
    await fetch(getBaseUrl() + '/api/voice-clone/' + encodeURIComponent(name), { method: 'DELETE' });
    loadClones();
  };

  async function uploadClone(blob, name) {
    statusEl.textContent = t('clone.uploading');
    const form = new FormData();
    form.append('audio', blob, 'recording.webm');
    form.append('name', name || t('clone.defaultVoiceName'));
    try {
      const r = await fetch(getBaseUrl() + '/api/voice-clone/create', { method: 'POST', body: form });
      const d = await r.json();
      if (d.ok) {
        statusEl.textContent = t('clone.saveOk', { name: d.name, duration: d.duration });
        loadClones();
      } else {
        statusEl.textContent = '❌ ' + (d.error || t('clone.uploadFail'));
      }
    } catch (e) {
      statusEl.textContent = t('clone.networkErr');
    }
  }

  recordBtn.addEventListener('click', async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunks = [];
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      mediaRecorder.onstop = () => {
        stream.getTracks().forEach(tr => tr.stop());
        const blob = new Blob(chunks, { type: 'audio/webm' });
        uploadClone(blob, nameInput.value.trim());
        recordingUI.style.display = 'none';
        recordBtn.style.display = '';
        clearInterval(timerInterval);
      };
      mediaRecorder.start();
      startTime = Date.now();
      recordBtn.style.display = 'none';
      recordingUI.style.display = '';
      timerInterval = setInterval(() => {
        const s = Math.floor((Date.now() - startTime) / 1000);
        timerEl.textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
      }, 200);
      statusEl.textContent = t('clone.recordingHint');
    } catch (e) {
      statusEl.textContent = t('clone.micErrorPrefix') + e.message;
    }
  });

  stopBtn?.addEventListener('click', () => {
    if (mediaRecorder?.state === 'recording') mediaRecorder.stop();
  });

  uploadInput?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    uploadClone(file, nameInput.value.trim() || file.name.replace(/\.\w+$/, ''));
    uploadInput.value = '';
  });

  const settingsToggle = document.getElementById('settings-toggle');
  settingsToggle?.addEventListener('click', () => setTimeout(loadClones, 500));
  window.addEventListener('oc-lang-change', () => loadClones());
  window.addEventListener('oc-i18n-updated', () => loadClones());
}

// ══════════════════════════════════════════════════════════════
// 7. SETTINGS TAB SWITCHER
// ══════════════════════════════════════════════════════════════
function initSettingsTabs() {
  const tabs = document.getElementById('settings-tabs');
  if (!tabs) return;

  function activateTab(tabId) {
    const btn = tabs.querySelector(`.stab[data-tab="${tabId}"]`);
    if (!btn) return false;
    tabs.querySelectorAll('.stab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.stab-pane').forEach(p => p.classList.remove('active'));
    const pane = document.getElementById(tabId);
    if (pane) pane.classList.add('active');
    return true;
  }

  const saved = localStorage.getItem('oc-settings-tab');
  if (saved) activateTab(saved);

  tabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.stab');
    if (!btn) return;
    const tabId = btn.dataset.tab;
    activateTab(tabId);
    localStorage.setItem('oc-settings-tab', tabId);
  });
}

// ══════════════════════════════════════════════════════════════
// 8. PULL-TO-REFRESH (Model / MCP panels)
// ══════════════════════════════════════════════════════════════
function initPullToRefresh() {
  function pullToRefresh(panelId, refreshFn) {
    const body = document.querySelector('#' + panelId + ' .mp-body, #' + panelId + ' .mcp-body');
    if (!body) return;
    let _startY = 0, _pulling = false;

    body.addEventListener('touchstart', (e) => {
      if (body.scrollTop <= 0) {
        _startY = e.touches[0].clientY;
        _pulling = true;
      }
    }, { passive: true });

    body.addEventListener('touchmove', (e) => {
      if (!_pulling) return;
      const dy = e.touches[0].clientY - _startY;
      if (dy > 80 && body.scrollTop <= 0) {
        _pulling = false;
        body.style.opacity = '0.5';
        refreshFn().finally(() => { body.style.opacity = '1'; });
      }
    }, { passive: true });

    body.addEventListener('touchend', () => { _pulling = false; });
  }

  window.addEventListener('load', () => {
    pullToRefresh('model-panel', async () => {
      try {
        const r = await fetch(getBaseUrl() + '/api/models');
        const d = await r.json();
        const badge = document.getElementById('mp-mode-badge');
        if (badge) {
          badge.dataset.mode = d.mode === 'full' ? 'full' : 'min';
          badge.textContent = d.mode === 'full' ? t('model.fullMode') : t('model.minMode');
        }
        document.dispatchEvent(new CustomEvent('oc:models-refresh', { detail: d.models || [] }));
      } catch {}
    });
    pullToRefresh('mcp-panel', async () => {
      try {
        await Promise.all([
          fetch(getBaseUrl() + '/api/mcp/servers'),
          fetch(getBaseUrl() + '/api/mcp/tools'),
          fetch(getBaseUrl() + '/api/mcp/skills'),
        ]);
        document.dispatchEvent(new CustomEvent('oc:mcp-refresh'));
      } catch {}
    });
  });
}

// ══════════════════════════════════════════════════════════════
// 10. KEYBOARD SHORTCUTS
// ══════════════════════════════════════════════════════════════
function initKeyboardShortcuts() {
  const shortcuts = document.getElementById('shortcuts-overlay');
  const closeBtn = document.getElementById('shortcuts-close');

  function toggleShortcuts() {
    shortcuts.classList.toggle('open');
    if (shortcuts.classList.contains('open')) shortcuts.focus();
  }

  if (closeBtn) closeBtn.addEventListener('click', () => shortcuts.classList.remove('open'));
  shortcuts?.addEventListener('click', (e) => { if (e.target === shortcuts) shortcuts.classList.remove('open'); });

  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && !e.shiftKey && e.key === 'k') {
      e.preventDefault();
      ocCmdPalette?.toggle();
      return;
    }

    if (e.ctrlKey && !e.shiftKey && e.key === 'f') {
      const chatPage = document.getElementById('chat-page');
      if (chatPage && !chatPage.classList.contains('hidden')) {
        e.preventDefault();
        fn.ocMsgSearch?.open();
        return;
      }
    }

    if (e.key === 'Escape') {
      const overlay = document.getElementById('cmd-overlay');
      if (overlay && overlay.classList.contains('open')) {
        ocCmdPalette?.close();
        return;
      }
    }

    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT' || e.target.isContentEditable) return;

    if (e.key === 'Escape') {
      if (shortcuts.classList.contains('open')) { shortcuts.classList.remove('open'); return; }
    }

    if (e.ctrlKey && !e.shiftKey && e.key === 'm') {
      e.preventDefault();
      const mp = document.getElementById('model-panel');
      if (mp.classList.contains('hidden')) { mp.classList.remove('hidden'); mp.focus(); }
      else mp.classList.add('hidden');
    }

    if (e.ctrlKey && !e.shiftKey && e.key === 't') {
      e.preventDefault();
      const mcp = document.getElementById('mcp-panel');
      if (mcp.classList.contains('hidden')) { mcp.classList.remove('hidden'); mcp.focus(); }
      else mcp.classList.add('hidden');
    }

    if (e.ctrlKey && !e.shiftKey && e.key === 'p') {
      e.preventDefault();
      const pp = document.getElementById('perf-panel');
      if (pp.classList.contains('hidden')) { ocPerf?.openPanel(); }
      else { ocPerf?.closePanel(); }
    }

    if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) {
      e.preventDefault();
      const sel = document.getElementById('theme-select');
      if (sel) {
        const order = ['dark', 'light', 'auto'];
        const cur = sel.value;
        sel.value = order[(order.indexOf(cur) + 1) % order.length];
        sel.dispatchEvent(new Event('change'));
        window.ocToast?.info('🎨 ' + sel.options[sel.selectedIndex].text);
      }
    }

    if (e.ctrlKey && e.key === '/') {
      e.preventDefault();
      toggleShortcuts();
    }

    if (e.key === ' ' && !e.ctrlKey) {
      const chatPage = document.getElementById('chat-page');
      if (chatPage && !chatPage.classList.contains('hidden')) {
        const overlay = document.getElementById('voice-overlay');
        if (overlay && overlay.classList.contains('hidden')) {
          e.preventDefault();
          fn.startVoiceRecording?.();
        }
      }
    }
  });
}

// ══════════════════════════════════════════════════════════════
// 11. FOCUS MANAGEMENT (a11y) — real Tab trap
// ══════════════════════════════════════════════════════════════
function initFocusManagement() {
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  const _traps = new Map();

  function _onKeydown(e) {
    if (e.key !== 'Tab') return;
    const panel = e.currentTarget;
    const focusable = [...panel.querySelectorAll(FOCUSABLE)].filter(el => el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first || document.activeElement === panel) {
        e.preventDefault(); last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    }
  }

  function trapFocus(panelId) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    if (!panel.hasAttribute('tabindex')) panel.setAttribute('tabindex', '-1');

    const obs = new MutationObserver(() => {
      const isVisible = !panel.classList.contains('hidden');
      if (isVisible) {
        _traps.set(panelId, document.activeElement);
        panel.addEventListener('keydown', _onKeydown);
        requestAnimationFrame(() => {
          const first = panel.querySelector(FOCUSABLE);
          (first || panel).focus();
        });
      } else {
        panel.removeEventListener('keydown', _onKeydown);
        const prev = _traps.get(panelId);
        if (prev && prev.focus) { try { prev.focus(); } catch(e) {} }
        _traps.delete(panelId);
      }
    });
    obs.observe(panel, { attributes: true, attributeFilter: ['class'] });
  }

  trapFocus('model-panel');
  trapFocus('mcp-panel');
  trapFocus('settings-modal');
  trapFocus('perf-panel');
  trapFocus('voice-cmd-panel');
}

// ══════════════════════════════════════════════════════════════
// 13. VOICE COMMANDS PANEL
// ══════════════════════════════════════════════════════════════
function initVoiceCommands() {
  const $id = id => document.getElementById(id);
  let _skills = [];

  async function openPanel() {
    $id('voice-cmd-panel').classList.remove('hidden');
    if (_skills.length === 0) await loadSkills();
  }
  function closePanel() { $id('voice-cmd-panel').classList.add('hidden'); }

  async function loadSkills() {
    try {
      const r = await fetch(getBaseUrl() + '/api/desktop-skills');
      const d = await r.json();
      _skills = d.skills || d || [];
      renderSkills(_skills);
    } catch {
      $id('vcmd-list').innerHTML = `<div class="mcp-empty" data-i18n="vcmd.noSkills">${t('vcmd.noSkills')}</div>`;
    }
  }

  function renderSkills(skills) {
    if (skills.length === 0) {
      $id('vcmd-list').innerHTML = '<div class="mcp-empty" data-i18n="vcmd.noSkills">暂无可用技能</div>';
      return;
    }
    $id('vcmd-list').innerHTML = skills.map(s => `
      <div class="vcmd-card" data-id="${s.id}">
        <span class="vcmd-icon">${s.icon || '⚡'}</span>
        <div style="flex:1">
          <div class="vcmd-name">${s.name_zh || s.name || s.id}</div>
          <div class="vcmd-desc">${s.description || ''}</div>
        </div>
        <button class="vcmd-exec" data-id="${s.id}" data-i18n="vcmd.execute">执行</button>
      </div>
    `).join('');
    $id('vcmd-list').querySelectorAll('.vcmd-exec').forEach(btn => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); execSkill(btn.dataset.id); });
    });
    $id('vcmd-list').querySelectorAll('.vcmd-card').forEach(card => {
      card.addEventListener('click', () => execSkill(card.dataset.id));
    });
  }

  async function execSkill(id) {
    const btn = $id('vcmd-list').querySelector(`.vcmd-exec[data-id="${id}"]`);
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const r = await fetch(getBaseUrl() + `/api/desktop-skill/${id}`, { method: 'POST' });
      const d = await r.json();
      window.ocToast?.success(d.message || t('vcmd.skillExecuted'));
    } catch(e) {
      window.ocToast?.error(t('vcmd.execFailed', { msg: e.message || '' }));
    }
    if (btn) { btn.disabled = false; btn.textContent = t('vcmd.execute'); }
  }

  $id('vcmd-search')?.addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    const filtered = _skills.filter(s =>
      (s.name_zh || s.name || s.id).toLowerCase().includes(q) ||
      (s.description || '').toLowerCase().includes(q)
    );
    renderSkills(filtered);
  });

  const CKEY = 'oc-custom-vcmd';
  let _customs = JSON.parse(localStorage.getItem(CKEY) || '[]');
  let _formSteps = [];
  let _editing = false;

  function saveCmds() { localStorage.setItem(CKEY, JSON.stringify(_customs)); }

  function renderCustomList() {
    const el = $id('vcmd-custom-list');
    if (!el) return;
    if (_customs.length === 0) {
      el.innerHTML = `<div style="font-size:11px;color:var(--text-muted);text-align:center;padding:12px" data-i18n="vcmd.customEmpty">${t('vcmd.customEmpty')}</div>`;
      return;
    }
    el.innerHTML = _customs.map((c, i) => `
      <div class="vcmd-custom-card">
        <div class="vcmd-c-name">${c.name}</div>
        <span class="vcmd-c-steps">${c.steps.length} steps</span>
        <button class="vcmd-exec" data-idx="${i}" style="font-size:10px;padding:3px 8px">▶</button>
        <button class="mp-btn" data-del="${i}" style="font-size:10px;padding:3px 6px;background:none;color:var(--error)">✕</button>
      </div>
    `).join('');
    el.querySelectorAll('.vcmd-exec').forEach(btn => btn.addEventListener('click', () => runCustom(+btn.dataset.idx)));
    el.querySelectorAll('[data-del]').forEach(btn => btn.addEventListener('click', () => {
      if (confirm(t('vcmd.deleteConfirm'))) { _customs.splice(+btn.dataset.del, 1); saveCmds(); renderCustomList(); }
    }));
  }

  async function runCustom(idx) {
    const cmd = _customs[idx];
    if (!cmd) return;
    for (let i = 0; i < cmd.steps.length; i++) {
      window.ocToast?.info(`${t('vcmd.runningStep')} ${i+1}/${cmd.steps.length}: ${cmd.steps[i].name}`);
      await execSkill(cmd.steps[i].id);
      if (i < cmd.steps.length - 1) await new Promise(r => setTimeout(r, 500));
    }
    window.ocToast?.success(`${cmd.name} ✓`);
  }

  function populateStepSelect() {
    const sel = $id('vcmd-step-select');
    if (!sel) return;
    sel.innerHTML = _skills.map(s => `<option value="${s.id}">${s.icon || '⚡'} ${s.name_zh || s.name || s.id}</option>`).join('');
  }

  function renderFormSteps() {
    const el = $id('vcmd-custom-steps');
    if (!el) return;
    el.innerHTML = _formSteps.map((s, i) => `
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;font-size:11px;padding:4px 8px;background:var(--bg-surface);border-radius:4px">
        <span style="color:var(--text-muted)">${i+1}.</span>
        <span style="flex:1">${s.icon || '⚡'} ${s.name}</span>
        <button onclick="this.parentElement.remove();window._vcmdRemoveStep(${i})" style="background:none;border:none;color:var(--error);cursor:pointer;font-size:11px">✕</button>
      </div>
    `).join('');
  }
  window._vcmdRemoveStep = (i) => { _formSteps.splice(i, 1); renderFormSteps(); };

  $id('vcmd-add-custom')?.addEventListener('click', () => {
    _formSteps = [];
    _editing = true;
    $id('vcmd-custom-form').classList.remove('hidden');
    $id('vcmd-custom-name').value = '';
    populateStepSelect();
    renderFormSteps();
  });

  $id('vcmd-add-step')?.addEventListener('click', () => {
    const sel = $id('vcmd-step-select');
    const sk = _skills.find(s => s.id === sel.value);
    if (sk) { _formSteps.push({ id: sk.id, name: sk.name_zh || sk.name || sk.id, icon: sk.icon }); renderFormSteps(); }
  });

  $id('vcmd-save-custom')?.addEventListener('click', () => {
    const name = $id('vcmd-custom-name').value.trim();
    if (!name || _formSteps.length === 0) { window.ocToast?.warning(t('vcmd.nameStepsRequired')); return; }
    _customs.push({ name, steps: [..._formSteps] });
    saveCmds();
    _editing = false;
    $id('vcmd-custom-form').classList.add('hidden');
    renderCustomList();
  });

  $id('vcmd-cancel-custom')?.addEventListener('click', () => {
    _editing = false;
    $id('vcmd-custom-form').classList.add('hidden');
  });

  const _origOpen = openPanel;
  async function openPanelWithCustom() {
    await _origOpen();
    populateStepSelect();
    renderCustomList();
  }

  $id('vcmd-toggle')?.addEventListener('click', openPanelWithCustom);
  $id('vcmd-back')?.addEventListener('click', closePanel);

  function refreshVcmdI18n() {
    const q = ($id('vcmd-search')?.value || '').toLowerCase();
    const filtered = q
      ? _skills.filter(s =>
        (s.name_zh || s.name || s.id).toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q))
      : _skills;
    renderSkills(filtered);
    renderCustomList();
  }
  window.addEventListener('oc-lang-change', refreshVcmdI18n);
  window.addEventListener('oc-i18n-updated', refreshVcmdI18n);
}

// ══════════════════════════════════════════════════════════════
// 15. WECHAT AUTO-REPLY — moved to settings-wechat.js
// ══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════
// 17. SETTINGS EXPORT / IMPORT
// ══════════════════════════════════════════════════════════════
function initSettingsExport() {
  const SETTINGS_KEYS = [
    'oc-theme', 'oc-lang', 'oc-fav-tools', 'oc-mcp-history', 'oc-cmd-recent',
    'oc-custom-vcmd', 'oc-perf-data', 'oc-emotion-enabled', 'oc-mic-hint',
    'oc_pet_mic_gain', 'oc_pet_playback_gain', 'oc_pet_level_mode', 'oc_pet_skin',
  ];

  function collectAll() {
    const data = { _version: 1, _exportedAt: new Date().toISOString() };
    for (const k of SETTINGS_KEYS) {
      const v = localStorage.getItem(k);
      if (v != null) data[k] = v;
    }
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k.startsWith('oc-') && !(k in data)) data[k] = localStorage.getItem(k);
      if (k.startsWith('oc_pet_') && !(k in data)) data[k] = localStorage.getItem(k);
    }
    return data;
  }

  document.getElementById('settings-export')?.addEventListener('click', () => {
    const data = collectAll();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `十三香小龙虾-settings-${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    window.ocToast?.success(t('settings.exportOk'));
  });

  document.getElementById('settings-import')?.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        if (!data._version) throw new Error('Invalid');
        for (const [k, v] of Object.entries(data)) {
          if (k.startsWith('_')) continue;
          localStorage.setItem(k, v);
        }
        window.ocToast?.success(t('settings.importOk'));
        setTimeout(() => location.reload(), 1200);
      } catch {
        window.ocToast?.error(t('settings.importFail'));
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  });
}

// ══════════════════════════════════════════════════════════════
// 18. EXPRESSION SETTINGS PANEL
// ══════════════════════════════════════════════════════════════
function initExpressionSettings() {
  const $id = id => document.getElementById(id);

  function exprItemLabel(name, def) {
    const k = `expr.item.${name}`;
    const tx = t(k);
    return tx !== k ? tx : def.label;
  }

  function presetLabel(key, p) {
    const k = `expr.preset.${key}.label`;
    const tx = t(k);
    return tx !== k ? tx : p.label;
  }

  function presetDesc(key, p) {
    const k = `expr.preset.${key}.desc`;
    const tx = t(k);
    return tx !== k ? tx : p.description;
  }

  function refreshGazeStatusText() {
    const st = $id('gaze-status');
    if (!st) return;
    if (!$id('gaze-enable')?.checked) {
      st.textContent = '';
      return;
    }
    st.textContent = gazeTracker.calibration.isCalibrated ? t('gaze.statusCalibrated') : t('gaze.statusRough');
  }

  function renderExprItem(name, def, type) {
    const isHead = type === 'head_movement';
    const displayLabel = escapeHtml(exprItemLabel(name, def));
    return `<div class="settings-row" style="flex-wrap:wrap;gap:4px;align-items:center" data-expr="${name}">
      <span class="settings-label" style="flex:1;min-width:120px">${displayLabel}</span>
      <label style="position:relative;width:40px;height:22px;flex-shrink:0">
        <input type="checkbox" class="expr-item-toggle" data-name="${name}" data-type="${type}" ${def.enabled ? 'checked' : ''} style="opacity:0;width:0;height:0">
        <span style="position:absolute;inset:0;background:var(--bg-surface);border-radius:11px;cursor:pointer;transition:.3s"></span>
        <span class="expr-knob" style="position:absolute;width:16px;height:16px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;${def.enabled ? 'transform:translateX(18px);background:var(--accent)' : ''}"></span>
      </label>
      ${!isHead ? `<span style="font-size:11px;color:var(--text-muted);min-width:50px;text-align:right" class="expr-val" data-name="${name}">—</span>` : ''}
    </div>`;
  }

  function renderPanel() {
    const all = expressionSystem.getExpressionList();

    const mouth = all.filter(e => e.type === 'expression' && e.category === 'mouth');
    const brow = all.filter(e => e.type === 'expression' && e.category === 'brow');
    const eye = all.filter(e => e.type === 'expression' && e.category === 'eye');
    const head = all.filter(e => e.type === 'head_movement');

    $id('expr-mouth-list').innerHTML = mouth.map(e => renderExprItem(e.name, e, e.type)).join('');
    $id('expr-brow-list').innerHTML = brow.map(e => renderExprItem(e.name, e, e.type)).join('');
    $id('expr-eye-list').innerHTML = eye.map(e => renderExprItem(e.name, e, e.type)).join('');
    $id('expr-head-list').innerHTML = head.map(e => renderExprItem(e.name, e, e.type)).join('');

    $id('expr-presets').innerHTML = Object.entries(EXPR_PRESETS).map(([key, p]) =>
      `<button type="button" class="btn settings-btn settings-btn--secondary settings-btn--compact expr-preset-btn" data-preset="${escapeHtml(key)}" title="${escapeHtml(presetDesc(key, p))}">${escapeHtml(presetLabel(key, p))}</button>`
    ).join('');
  }

  function bindEvents() {
    $id('expr-enable')?.addEventListener('change', (e) => {
      expressionSystem.enabled = e.target.checked;
    });

    $id('expr-sensitivity')?.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      $id('expr-sensitivity-val').textContent = val.toFixed(1);
      expressionSystem.globalSensitivity = val;
    });

    for (const container of ['expr-mouth-list', 'expr-brow-list', 'expr-eye-list', 'expr-head-list']) {
      $id(container)?.addEventListener('change', (e) => {
        const toggle = e.target.closest('.expr-item-toggle');
        if (!toggle) return;
        const name = toggle.dataset.name;
        const type = toggle.dataset.type;
        if (type === 'expression' && expressionSystem.expressions[name]) {
          expressionSystem.expressions[name].enabled = toggle.checked;
        } else if (type === 'head_movement' && expressionSystem.headMovements[name]) {
          expressionSystem.headMovements[name].enabled = toggle.checked;
        }
      });
    }

    $id('expr-presets')?.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-preset]');
      if (!btn) return;
      const presetName = btn.dataset.preset;
      expressionSystem.applyPreset(presetName);
      $id('expr-enable').checked = expressionSystem.enabled;
      $id('expr-sensitivity').value = expressionSystem.globalSensitivity;
      $id('expr-sensitivity-val').textContent = expressionSystem.globalSensitivity.toFixed(1);
      renderPanel();
      bindEvents();

      try {
        await fetch(getBaseUrl() + '/api/access/preset/' + presetName, { method: 'POST' });
      } catch (_) {}
    });

    $id('expr-save')?.addEventListener('click', async () => {
      const config = {
        expression_enabled: expressionSystem.enabled,
        sensitivity: expressionSystem.globalSensitivity,
        expressions: {},
        head_movements: {},
      };
      for (const [name, def] of Object.entries(expressionSystem.expressions)) {
        config.expressions[name] = def.enabled;
      }
      for (const [name, def] of Object.entries(expressionSystem.headMovements)) {
        config.head_movements[name] = def.enabled;
      }
      try {
        await fetch(getBaseUrl() + '/api/access/config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        window.ocToast?.success(t('expr.saveOk'));
      } catch (e) {
        console.error('Save expression config failed:', e);
      }
    });

    $id('expr-reset')?.addEventListener('click', async () => {
      try {
        const resp = await fetch(getBaseUrl() + '/api/access/config/reset', { method: 'POST' });
        if (resp.ok) {
          const config = await resp.json();
          expressionSystem.applyConfig({
            enabled: config.expression_enabled || false,
            sensitivity: config.sensitivity || 1.0,
          });
          expressionSystem._initDefaults();
          $id('expr-enable').checked = false;
          $id('expr-sensitivity').value = 1.0;
          $id('expr-sensitivity-val').textContent = '1.0';
          renderPanel();
          bindEvents();
        }
      } catch (_) {}
    });
  }

  bus.on('expression:tags', (tags) => {
    const monitor = $id('expr-live-monitor');
    if (!monitor) return;
    const tabEl = $id('tab-expression');
    if (!tabEl || !tabEl.classList.contains('active')) return;

    const lines = tags.map(tag => {
      const valEl = document.querySelector(`.expr-val[data-name="${tag.name}"]`);
      if (valEl) {
        const pct = (tag.value * 100).toFixed(0);
        valEl.textContent = `${pct}%`;
        valEl.style.color = tag.active ? 'var(--success)' : 'var(--text-muted)';
      }
      const k = `expr.item.${tag.name}`;
      const tx = t(k);
      const label = tx !== k ? tx : tag.label;
      return `${label}: ${(tag.value * 100).toFixed(0)}% ${tag.active ? '🟢' : '⚪'}`;
    });
    monitor.innerHTML = lines.length > 0
      ? lines.map(l => `<div style="padding:2px 0">${l}</div>`).join('')
      : `<div style="opacity:.5" data-i18n="expr.liveEmpty">${t('expr.liveEmpty')}</div>`;
  });

  $id('gaze-enable')?.addEventListener('change', (e) => {
    gazeTracker.enabled = e.target.checked;
    const cursor = document.getElementById('gaze-cursor');
    if (cursor) cursor.style.display = e.target.checked ? 'block' : 'none';
    const knob = $id('gaze-toggle-knob');
    if (knob) {
      knob.style.transform = e.target.checked ? 'translateX(22px)' : '';
      knob.style.background = e.target.checked ? 'var(--accent)' : '#fff';
    }
    refreshGazeStatusText();
  });

  $id('gaze-dwell')?.addEventListener('input', (e) => {
    const val = parseInt(e.target.value);
    gazeTracker.dwellThresholdMs = val;
    $id('gaze-dwell-val').textContent = (val / 1000).toFixed(1) + 's';
  });

  $id('gaze-calibrate-btn')?.addEventListener('click', () => {
    if (!S.isCameraOn) {
      $id('gaze-status').textContent = t('gaze.openCameraFirst');
      return;
    }
    startGazeCalibration();
  });

  $id('workflow-start-rec')?.addEventListener('click', () => {
    intentFusion.startRecording();
    $id('workflow-start-rec').style.display = 'none';
    $id('workflow-stop-rec').style.display = 'block';
    $id('workflow-rec-status').textContent = t('workflow.recording');
    $id('workflow-rec-status').style.color = 'var(--error)';
  });

  $id('workflow-stop-rec')?.addEventListener('click', async () => {
    const actions = intentFusion.stopRecording();
    $id('workflow-start-rec').style.display = 'block';
    $id('workflow-stop-rec').style.display = 'none';

    if (actions.length === 0) {
      $id('workflow-rec-status').textContent = t('workflow.empty');
      $id('workflow-rec-status').style.color = 'var(--text-muted)';
      return;
    }

    const name = prompt(t('workflow.namePrompt'), `${t('workflow.nameDefaultPrefix')}${new Date().toLocaleDateString()}`);
    if (!name) return;

    try {
      const resp = await fetch(getBaseUrl() + '/api/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actions, name, description: t('workflow.descSteps', { n: String(actions.length) }) }),
      });
      const data = await resp.json();
      $id('workflow-rec-status').textContent = t('workflow.savedOk', { name, steps: String(actions.length) });
      $id('workflow-rec-status').style.color = 'var(--success)';
    } catch (e) {
      $id('workflow-rec-status').textContent = t('workflow.saveFail', { msg: e.message || '' });
      $id('workflow-rec-status').style.color = 'var(--error)';
    }
  });

  setTimeout(() => {
    renderPanel();
    bindEvents();
    loadExpressionConfig().then(() => {
      $id('expr-enable').checked = expressionSystem.enabled;
      $id('expr-sensitivity').value = expressionSystem.globalSensitivity;
      $id('expr-sensitivity-val').textContent = expressionSystem.globalSensitivity.toFixed(1);
      renderPanel();
      bindEvents();
    });

    loadGazeCalibration();
    loadExpressionConfig().then(() => {
      fetch(getBaseUrl() + '/api/access/config').then(r => r.json()).then(cfg => {
        gazeTracker.enabled = cfg.gaze_enabled || false;
        if ($id('gaze-enable')) $id('gaze-enable').checked = gazeTracker.enabled;
        const knob = $id('gaze-toggle-knob');
        if (knob && gazeTracker.enabled) {
          knob.style.transform = 'translateX(22px)';
          knob.style.background = 'var(--accent)';
        }
        refreshGazeStatusText();
      }).catch(() => {});
    });
  }, 500);

  window.addEventListener('oc-lang-change', () => {
    renderPanel();
    refreshGazeStatusText();
  });
  window.addEventListener('oc-i18n-updated', () => {
    renderPanel();
    refreshGazeStatusText();
  });
}

// ══════════════════════════════════════════════════════════════
// 19. NOTIFICATION CENTER
// ══════════════════════════════════════════════════════════════
function initNotificationCenter() {
  const $id = id => document.getElementById(id);
  const SKEY = 'oc-notif-session';
  let _notifs = JSON.parse(sessionStorage.getItem(SKEY) || '[]');
  let _unread = _notifs.filter(n => !n.read).length;
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

  function save() { sessionStorage.setItem(SKEY, JSON.stringify(_notifs)); }

  function updateBadge() {
    const badge = $id('notif-badge');
    if (!badge) return;
    _unread = _notifs.filter(n => !n.read).length;
    badge.textContent = _unread;
    badge.classList.toggle('hidden', _unread === 0);
  }

  function renderList() {
    const list = $id('notif-list');
    if (!list) return;
    if (_notifs.length === 0) {
      list.innerHTML = `<div class="notif-empty" data-i18n="notif.empty">${t('notif.empty')}</div>`;
      return;
    }
    list.innerHTML = _notifs.slice().reverse().map((n, ri) => {
      const idx = _notifs.length - 1 - ri;
      const d = new Date(n.time);
      const ts = d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0') + ':' + d.getSeconds().toString().padStart(2,'0');
      return `<div class="notif-item${n.read ? '' : ' unread'}" data-idx="${idx}">
        <span class="notif-icon">${icons[n.type] || icons.info}</span>
        <div class="notif-body">
          <div class="notif-msg">${n.message}</div>
          <div class="notif-time">${ts}</div>
        </div>
      </div>`;
    }).join('');
    list.querySelectorAll('.notif-item').forEach(el => {
      el.addEventListener('click', () => { const i = +el.dataset.idx; _notifs[i].read = true; save(); updateBadge(); el.classList.remove('unread'); });
    });
  }

  window.addEventListener('oc-notification', (e) => {
    _notifs.push({ message: e.detail.message, type: e.detail.type, time: e.detail.time, read: false });
    if (_notifs.length > 100) _notifs = _notifs.slice(-100);
    save(); updateBadge();
    if ($id('notif-panel')?.classList.contains('open')) renderList();
  });

  function positionNotifPanel() {
    const bell = $id('notif-toggle');
    const p = $id('notif-panel');
    if (!bell || !p) return;
    const r = bell.getBoundingClientRect();
    p.style.top = (r.bottom + 6) + 'px';
    const rightEdge = window.innerWidth - r.right;
    p.style.right = Math.max(8, rightEdge - 40) + 'px';
    p.style.left = 'auto';
  }

  $id('notif-toggle')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const p = $id('notif-panel');
    positionNotifPanel();
    p.classList.toggle('open');
    if (p.classList.contains('open')) renderList();
  });
  document.addEventListener('click', (e) => {
    const p = $id('notif-panel');
    if (p && p.classList.contains('open') && !p.contains(e.target) && e.target !== $id('notif-toggle')) {
      p.classList.remove('open');
    }
  });
  $id('notif-close')?.addEventListener('click', () => $id('notif-panel').classList.remove('open'));
  $id('notif-read-all')?.addEventListener('click', () => { _notifs.forEach(n => n.read = true); save(); updateBadge(); renderList(); });
  $id('notif-clear-all')?.addEventListener('click', () => { _notifs = []; save(); updateBadge(); renderList(); });

  updateBadge();
}

// ══════════════════════════════════════════════════════════════
// 20. HEADER BUTTON DRAG SORT
// ══════════════════════════════════════════════════════════════
function initHeaderDragSort() {
  const OKEY = 'oc-header-order';
  const container = document.querySelector('.header-right');
  if (!container) return;
  const saved = JSON.parse(localStorage.getItem(OKEY) || 'null');

  function getButtons() { return Array.from(container.querySelectorAll('.icon-btn')); }

  function restoreOrder() {
    if (!saved || !Array.isArray(saved)) return;
    const btns = getButtons();
    const byId = {};
    btns.forEach(b => { byId[b.id] = b; });
    saved.forEach(id => {
      const b = byId[id];
      if (b) container.appendChild(b);
    });
  }
  restoreOrder();

  function saveOrder() {
    const order = getButtons().map(b => b.id).filter(Boolean);
    localStorage.setItem(OKEY, JSON.stringify(order));
  }

  let _dragEl = null;
  let _holdTimer = null;
  let _dragging = false;

  container.addEventListener('pointerdown', (e) => {
    const btn = e.target.closest('.icon-btn');
    if (!btn || !container.contains(btn)) return;
    _holdTimer = setTimeout(() => {
      _dragging = true;
      _dragEl = btn;
      btn.classList.add('dragging');
      container.classList.add('drag-active');
      btn.setPointerCapture(e.pointerId);
    }, 400);
  });

  container.addEventListener('pointermove', (e) => {
    if (!_dragging || !_dragEl) return;
    const btns = getButtons();
    const rects = btns.map(b => b.getBoundingClientRect());
    btns.forEach(b => b.classList.remove('drag-over'));
    for (let i = 0; i < btns.length; i++) {
      if (btns[i] === _dragEl) continue;
      const r = rects[i];
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
        btns[i].classList.add('drag-over');
        break;
      }
    }
  });

  container.addEventListener('pointerup', (e) => {
    if (_holdTimer) { clearTimeout(_holdTimer); _holdTimer = null; }
    if (!_dragging || !_dragEl) return;
    const btns = getButtons();
    btns.forEach(b => b.classList.remove('drag-over'));
    const rects = btns.map(b => b.getBoundingClientRect());
    for (let i = 0; i < btns.length; i++) {
      if (btns[i] === _dragEl) continue;
      const r = rects[i];
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
        const mid = r.left + r.width / 2;
        if (e.clientX < mid) container.insertBefore(_dragEl, btns[i]);
        else if (btns[i].nextSibling) container.insertBefore(_dragEl, btns[i].nextSibling);
        else container.appendChild(_dragEl);
        saveOrder();
        break;
      }
    }
    _dragEl.classList.remove('dragging');
    container.classList.remove('drag-active');
    _dragEl = null; _dragging = false;
  });

  container.addEventListener('pointercancel', () => {
    if (_holdTimer) { clearTimeout(_holdTimer); _holdTimer = null; }
    if (_dragEl) { _dragEl.classList.remove('dragging'); container.classList.remove('drag-active'); }
    getButtons().forEach(b => b.classList.remove('drag-over'));
    _dragEl = null; _dragging = false;
  });
}


// ══════════════════════════════════════════════════════════════
// PART 2: Module-scope extractions
// ══════════════════════════════════════════════════════════════

const ocAudioViz = (function() {
  const canvas = document.getElementById('audio-viz-canvas');
  if (!canvas) return {};
  const ctx = canvas.getContext('2d');
  const VKEY = 'oc-viz-mode';
  let _mode = localStorage.getItem(VKEY) || 'waveform';
  let _analyser = null;
  let _animId = null;
  let _running = false;

  const sel = document.getElementById('viz-mode-select');
  if (sel) { sel.value = _mode; sel.addEventListener('change', () => { _mode = sel.value; localStorage.setItem(VKEY, _mode); }); }

  function start(audioCtx, source) {
    if (_analyser) stop();
    _analyser = audioCtx.createAnalyser();
    _analyser.fftSize = 256;
    source.connect(_analyser);
    canvas.classList.remove('hidden');
    _running = true;
    draw();
  }

  function stop() {
    _running = false;
    if (_animId) { cancelAnimationFrame(_animId); _animId = null; }
    canvas.classList.add('hidden');
    _analyser = null;
  }

  function draw() {
    if (!_running || !_analyser) return;
    _animId = requestAnimationFrame(draw);
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    if (_mode === 'bars') {
      const bufLen = _analyser.frequencyBinCount;
      const data = new Uint8Array(bufLen);
      _analyser.getByteFrequencyData(data);
      const barW = w / bufLen * 2;
      const half = Math.floor(bufLen / 2);
      for (let i = 0; i < half; i++) {
        const v = data[i] / 255;
        const barH = v * h * 0.9;
        const hue = (i / half) * 260 + 180;
        ctx.fillStyle = `hsla(${hue},80%,60%,.8)`;
        ctx.fillRect(i * barW, h - barH, barW - 1, barH);
      }
    } else {
      const bufLen = _analyser.fftSize;
      const data = new Uint8Array(bufLen);
      _analyser.getByteTimeDomainData(data);
      ctx.lineWidth = 2;
      ctx.strokeStyle = 'rgba(99,102,241,.8)';
      ctx.beginPath();
      const sliceW = w / bufLen;
      for (let i = 0; i < bufLen; i++) {
        const v = data[i] / 128.0;
        const y = (v * h) / 2;
        i === 0 ? ctx.moveTo(0, y) : ctx.lineTo(i * sliceW, y);
      }
      ctx.lineTo(w, h / 2);
      ctx.stroke();
    }
  }

  return { start, stop };
})();
window.ocAudioViz = ocAudioViz;

(function() {
  const origStart = window.startVoiceRecording;
  if (!origStart || !window.ocAudioViz || !window.ocAudioViz.start) return;
  const overlay = document.getElementById('voice-overlay');
  if (!overlay) return;
  const obs = new MutationObserver(() => {
    if (overlay.classList.contains('hidden')) {
      window.ocAudioViz.stop();
    }
  });
  obs.observe(overlay, { attributes: true, attributeFilter: ['class'] });
})();

(function() {
  const el = $('live-subtitle');
  const textEl = $('live-subtitle-text');
  if (!el || !textEl) return;
  let _typingTimer = null;
  const dots = `<span class="live-subtitle-dots"><span></span><span></span><span></span></span>`;

  window.ocLiveSubtitle = {
    show(text) {
      el.classList.add('visible');
      if (!text) {
        textEl.innerHTML = `${t('subtitle.listening')} ${dots}`;
      } else {
        textEl.textContent = text;
      }
      const area = $('messages-area');
      if (area) area.scrollTop = area.scrollHeight;
    },
    hide() {
      el.classList.remove('visible');
      textEl.innerHTML = dots;
    },
    typeText(text) {
      el.classList.add('visible');
      clearInterval(_typingTimer);
      let i = 0;
      textEl.textContent = '';
      _typingTimer = setInterval(() => {
        if (i >= text.length) { clearInterval(_typingTimer); return; }
        textEl.textContent += text[i++];
      }, 30);
    }
  };
})();

const ocPlugins = (function() {
  const PKEY = 'oc-plugins-state';
  const _registry = [];
  let _states = JSON.parse(localStorage.getItem(PKEY) || '{}');

  function saveStates() { localStorage.setItem(PKEY, JSON.stringify(_states)); }

  function getAPI() {
    return {
      toast: typeof window.ocToast !== 'undefined' ? window.ocToast : { show(){}, success(){}, error(){}, warning(){}, info(){} },
      addQuickAction: window.addQuickAction || function(){},
      t: typeof t === 'function' ? t : (k) => k,
      getBaseUrl: typeof getBaseUrl === 'function' ? getBaseUrl : () => '',
    };
  }

  function register(plugin) {
    if (!plugin || !plugin.id || !plugin.name) { console.warn('Plugin registration requires id and name'); return; }
    if (_registry.find(p => p.id === plugin.id)) { console.warn('Plugin already registered:', plugin.id); return; }
    _registry.push(plugin);
    if (_states[plugin.id] === undefined) _states[plugin.id] = false;
    if (_states[plugin.id] && typeof plugin.init === 'function') {
      try { plugin.init(getAPI()); } catch(e) { console.error('Plugin init error:', plugin.id, e); }
    }
    renderPluginList();
  }

  const _sandboxes = {};
  const API_WHITELIST = new Set(['toast.show','toast.success','toast.error','toast.warning','toast.info','addQuickAction','t','getBaseUrl']);

  function createSandbox(plugin) {
    const iframe = document.createElement('iframe');
    iframe.sandbox = 'allow-scripts';
    iframe.style.cssText = 'display:none;width:0;height:0;border:none';
    iframe.srcdoc = `<!DOCTYPE html><html><head><script>
      const _id='${plugin.id}';
      window.addEventListener('message',e=>{
        if(e.data?.type==='oc-plugin-response'&&e.data.pluginId===_id){
          const cb=window['_cb_'+e.data.callId];if(cb){cb(e.data.result);delete window['_cb_'+e.data.callId];}
        }
      });
      let _callCounter=0;
      function callHost(method,...args){
        return new Promise(resolve=>{
          const callId=++_callCounter;
          window['_cb_'+callId]=resolve;
          parent.postMessage({type:'oc-plugin-call',pluginId:_id,method,args,callId},'*');
        });
      }
      const api={toast:{show:(...a)=>callHost('toast.show',...a),success:(...a)=>callHost('toast.success',...a),error:(...a)=>callHost('toast.error',...a),warning:(...a)=>callHost('toast.warning',...a),info:(...a)=>callHost('toast.info',...a)},addQuickAction:(...a)=>callHost('addQuickAction',...a),t:(...a)=>callHost('t',...a),getBaseUrl:()=>callHost('getBaseUrl')};
      ${typeof plugin.sandboxCode === 'string' ? plugin.sandboxCode : ''}
    <\/script></head><body></body></html>`;
    document.body.appendChild(iframe);
    _sandboxes[plugin.id] = iframe;
  }

  function destroySandbox(id) {
    if (_sandboxes[id]) { _sandboxes[id].remove(); delete _sandboxes[id]; }
  }

  window.addEventListener('message', (e) => {
    if (e.data?.type !== 'oc-plugin-call') return;
    const { pluginId, method, args, callId } = e.data;
    if (!API_WHITELIST.has(method)) {
      console.warn('Plugin sandbox: blocked method', method, 'from', pluginId);
      if (typeof window.ocToast !== 'undefined') window.ocToast.warning(t('sandbox.blocked'));
      return;
    }
    const api = getAPI();
    const parts = method.split('.');
    let apiFn = api;
    for (const p of parts) apiFn = apiFn?.[p];
    let result = undefined;
    if (typeof apiFn === 'function') { try { result = apiFn(...(args || [])); } catch {} }
    const iframe = _sandboxes[pluginId];
    if (iframe?.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'oc-plugin-response', pluginId, callId, result }, '*');
    }
  });

  function setEnabled(id, enabled) {
    _states[id] = enabled;
    saveStates();
    const plugin = _registry.find(p => p.id === id);
    if (!plugin) return;
    if (enabled) {
      if (plugin.sandboxCode) { createSandbox(plugin); }
      else if (typeof plugin.init === 'function') {
        try { plugin.init(getAPI()); } catch(e) { console.error('Plugin init error:', id, e); }
      }
    } else {
      destroySandbox(id);
      if (typeof plugin.destroy === 'function') {
        try { plugin.destroy(); } catch(e) { console.error('Plugin destroy error:', id, e); }
      }
    }
  }

  function renderPluginList() {
    const list = document.getElementById('plugin-list');
    if (!list) return;
    if (_registry.length === 0) {
      list.innerHTML = `<div class="plugin-empty" data-i18n="settings.noPlugins">${t('settings.noPlugins')}</div>`;
      return;
    }
    list.innerHTML = _registry.map(p => {
      const on = _states[p.id];
      return `<div class="plugin-item">
        <span class="plugin-icon">${p.icon || '🔌'}</span>
        <span class="plugin-name">${p.name}</span>
        <div class="plugin-toggle${on ? ' active' : ''}" data-id="${p.id}"></div>
      </div>`;
    }).join('');
    list.querySelectorAll('.plugin-toggle').forEach(tog => {
      tog.addEventListener('click', () => {
        const id = tog.dataset.id;
        const newState = !_states[id];
        setEnabled(id, newState);
        tog.classList.toggle('active', newState);
      });
    });
  }

  setTimeout(() => {
    _registry.forEach(p => {
      if (!_states[p.id]) return;
      if (p.sandboxCode) { createSandbox(p); }
      else if (typeof p.init === 'function') {
        try { p.init(getAPI()); } catch(e) { console.error('Plugin init error:', p.id, e); }
      }
    });
  }, 500);

  return { register, getAPI, list: () => [..._registry], setEnabled, destroySandbox };
})();
window.ocPlugins = ocPlugins;

(function(){
  const moreBtn = document.getElementById('header-more-toggle');
  const menu = document.getElementById('header-overflow-menu');
  if(!moreBtn || !menu) return;
  moreBtn.addEventListener('click', e => {
    e.stopPropagation();
    menu.classList.toggle('open');
  });
  menu.querySelectorAll('.hom-item').forEach(item => {
    item.addEventListener('click', () => {
      menu.classList.remove('open');

      // data-action 自定义动作
      const action = item.dataset.action;
      if (action === 'open-chat') {
        // 跳转到 QR 页面（手机扫码使用）
        window.location.href = '/qr';
        return;
      }
      if (action === 'open-setup') {
        // 打开设置面板
        const st = document.getElementById('settings-toggle');
        if (st) st.click();
        return;
      }
      if (action === 'open-profile') {
        const st = document.getElementById('settings-toggle');
        if (st) st.click();
        setTimeout(() => {
          const btn = document.querySelector('.stab[data-tab="tab-profile"]');
          if (btn) btn.click();
        }, 200);
        return;
      }

      // data-target 标准动作 — 直接调用功能函数而非 .click() 隐藏按钮
      const targetId = item.dataset.target;
      if (!targetId) return;

      if (targetId === 'summary-btn') {
        // 对话摘要：直接调用 summary-btn 的 click handler
        const btn = document.getElementById('summary-btn');
        if (btn) { btn.style.display = 'inline-flex'; btn.click(); btn.style.display = ''; }
        return;
      }
      if (targetId === 'export-toggle') {
        // 导出菜单
        if (typeof window._openExportMenu === 'function') {
          window._openExportMenu(moreBtn);
        }
        return;
      }
      if (targetId === 'bookmark-toggle') {
        // 收藏面板
        const bp = document.getElementById('bookmark-panel');
        if (bp) bp.classList.toggle('open');
        return;
      }

      // 其他 data-target 按钮
      const target = document.getElementById(targetId);
      if (target) {
        // 临时显示 → 点击 → 恢复
        const origDisplay = target.style.display;
        if (getComputedStyle(target).display === 'none') {
          target.style.display = 'inline-flex';
          target.click();
          target.style.display = origDisplay;
        } else {
          target.click();
        }
      }
    });
  });
  document.addEventListener('click', e => {
    if(!menu.contains(e.target) && e.target !== moreBtn) menu.classList.remove('open');
  });
  const syncVisibility = () => {
    menu.querySelectorAll('.hom-item').forEach(item => {
      if (!item.dataset.target) return;
      const btn = document.getElementById(item.dataset.target);
      item.style.display = (btn && getComputedStyle(btn).display === 'none') ? '' : 'none';
    });
    menu.querySelectorAll('.hom-sep').forEach(sep => {
      const children = [...menu.children];
      const si = children.indexOf(sep);
      const hasAbove = children.some((c,i) => i < si && c.classList.contains('hom-item') && c.style.display !== 'none');
      const hasBelow = children.some((c,i) => i > si && c.classList.contains('hom-item') && c.style.display !== 'none');
      sep.style.display = (hasAbove && hasBelow) ? '' : 'none';
    });
  };
  moreBtn.addEventListener('click', syncVisibility);
  window.addEventListener('resize', () => { if(menu.classList.contains('open')) syncVisibility(); });
})();

// ══════════════════════════════════════════════════════════════
// PART 2: Init functions
// ══════════════════════════════════════════════════════════════

// 21. MODEL DEPENDENCY GRAPH — moved to settings-models.js

// 22. QUICK ACTIONS BAR
function initQuickActionsBar() {
  const container = document.getElementById('quick-actions');
  if (!container) return;
  const QAKEY = 'oc-quick-actions';

  const defaultActions = [
    { id: 'screenshot',  icon: '📸', label: 'qa.screenshot',  skill: 'screenshot' },
    { id: 'translate',   icon: '🌐', label: 'qa.translate',   skill: 'translate_clipboard' },
    { id: 'summarize',   icon: '📝', label: 'qa.summarize',   skill: 'summarize_clipboard' },
    { id: 'wechat',      icon: '💬', label: 'qa.wechat',      skill: 'open_wechat' },
    { id: 'desktop',     icon: '🖥️', label: 'qa.desktop',     skill: 'show_desktop' },
  ];

  function getActions() {
    const saved = JSON.parse(localStorage.getItem(QAKEY) || 'null');
    return saved || defaultActions;
  }

  function render() {
    const actions = getActions();
    container.innerHTML = actions.map(a =>
      `<div class="qa-chip" data-skill="${a.skill}" data-id="${a.id}">${a.icon} <span>${t(a.label) || a.label}</span></div>`
    ).join('');
    container.querySelectorAll('.qa-chip').forEach(chip => {
      chip.addEventListener('click', () => executeQA(chip.dataset.skill));
    });
  }

  async function executeQA(skillId) {
    try {
      const r = await fetch(getBaseUrl() + `/api/desktop-skill/${skillId}`, { method: 'POST' });
      const d = await r.json();
      if (typeof window.ocToast !== 'undefined') window.ocToast.success(d.message || skillId + ' ✓');
    } catch(e) {
      if (typeof window.ocToast !== 'undefined') window.ocToast.error(e.message);
    }
  }

  window.addQuickAction = function(action) {
    const actions = getActions();
    if (actions.find(a => a.id === action.id)) return;
    actions.push(action);
    localStorage.setItem(QAKEY, JSON.stringify(actions));
    render();
  };

  window.ocQuickActions = {
    getActions, defaultActions, QAKEY,
    save(actions) { localStorage.setItem(QAKEY, JSON.stringify(actions)); },
    render,
  };

  render();
}

// 23. ADVANCED THEME CUSTOMIZER
function initAdvancedTheme() {
  const $id = id => document.getElementById(id);
  const AKEY = 'oc-accent-color';
  const FKEY = 'oc-font-size';
  const DEFAULT_ACCENT = '#6366f1';
  const DEFAULT_FONT = 14;

  function applyAccent(color) {
    document.documentElement.style.setProperty('--accent', color);
    document.documentElement.style.setProperty('--accent-soft', color + '22');
  }

  function applyFont(size) {
    document.documentElement.style.setProperty('font-size', size + 'px');
  }

  const savedAccent = localStorage.getItem(AKEY);
  const savedFont = localStorage.getItem(FKEY);
  if (savedAccent) applyAccent(savedAccent);
  if (savedFont) applyFont(+savedFont);

  const picker = $id('accent-picker');
  const slider = $id('font-slider');
  const sizeVal = $id('font-size-val');

  if (picker) {
    picker.value = savedAccent || DEFAULT_ACCENT;
    picker.addEventListener('input', (e) => {
      applyAccent(e.target.value);
      localStorage.setItem(AKEY, e.target.value);
      updatePresets(e.target.value);
    });
  }

  if (slider) {
    slider.value = savedFont || DEFAULT_FONT;
    if (sizeVal) sizeVal.textContent = (savedFont || DEFAULT_FONT) + 'px';
    slider.addEventListener('input', (e) => {
      const v = +e.target.value;
      applyFont(v);
      localStorage.setItem(FKEY, v);
      if (sizeVal) sizeVal.textContent = v + 'px';
    });
  }

  function updatePresets(active) {
    document.querySelectorAll('.accent-preset').forEach(p => {
      p.classList.toggle('active', p.dataset.color === active);
    });
  }

  document.querySelectorAll('.accent-preset').forEach(p => {
    p.addEventListener('click', () => {
      const c = p.dataset.color;
      applyAccent(c);
      localStorage.setItem(AKEY, c);
      if (picker) picker.value = c;
      updatePresets(c);
    });
  });
  updatePresets(savedAccent || DEFAULT_ACCENT);

  $id('theme-reset')?.addEventListener('click', () => {
    localStorage.removeItem(AKEY);
    localStorage.removeItem(FKEY);
    applyAccent(DEFAULT_ACCENT);
    applyFont(DEFAULT_FONT);
    if (picker) picker.value = DEFAULT_ACCENT;
    if (slider) slider.value = DEFAULT_FONT;
    if (sizeVal) sizeVal.textContent = DEFAULT_FONT + 'px';
    updatePresets(DEFAULT_ACCENT);
    if (typeof window.ocToast !== 'undefined') window.ocToast.info(t('settings.themeResetOk'));
  });
}

// 24. WAKE WORD CUSTOMIZER
function initWakeWordCustomizer() {
  const $id = id => document.getElementById(id);
  const WKEY = 'oc-wakeword-text';
  const SKEY = 'oc-wakeword-sensitivity';
  const sensLabels = { 1: t('settings.sensitivityLow') || '低', 2: t('settings.sensitivityMed') || '中', 3: t('settings.sensitivityHigh') || '高' };

  const saved = localStorage.getItem(WKEY);
  const savedSens = localStorage.getItem(SKEY);
  const input = $id('wakeword-text');
  const slider = $id('wakeword-sensitivity');
  const valEl = $id('sensitivity-val');

  if (input && saved) input.value = saved;
  if (slider && savedSens) slider.value = savedSens;
  if (valEl) valEl.textContent = sensLabels[+(savedSens || 2)];

  function applyWakeWords() {
    const text = input?.value?.trim();
    if (!text) return;
    const words = text.split(/[,，、\s]+/).filter(Boolean).map(w => w.toLowerCase());
    if (typeof _wakeWordsCache !== 'undefined' && words.length) {
      const defaults = ['你好', '小龙', '龙虾', '唤醒', '开始', '在吗', 'hey claw', 'hello'];
      window._wakeWordsCache = [...new Set([...words, ...defaults])];
    }
  }

  input?.addEventListener('change', () => {
    localStorage.setItem(WKEY, input.value);
    applyWakeWords();
  });

  slider?.addEventListener('input', () => {
    const v = +slider.value;
    localStorage.setItem(SKEY, v);
    if (valEl) valEl.textContent = sensLabels[v];
    if (typeof MONITOR_CHUNK_SECONDS !== 'undefined') {
      const map = { 1: 1.5, 2: 1.0, 3: 0.6 };
      window.MONITOR_CHUNK_SECONDS = map[v] || 1.0;
    }
  });

  if (saved) setTimeout(applyWakeWords, 1000);
  if (savedSens && typeof MONITOR_CHUNK_SECONDS !== 'undefined') {
    const map = { 1: 1.5, 2: 1.0, 3: 0.6 };
    window.MONITOR_CHUNK_SECONDS = map[+savedSens] || 1.0;
  }
}

// 25. MESSAGE SEARCH — moved to settings-chat.js

// 26. QUICK ACTIONS EDITOR
function initQaEditor() {
  const $id = id => document.getElementById(id);
  if (!window.ocQuickActions) return;
  const qa = window.ocQuickActions;
  const defaultIds = new Set(qa.defaultActions.map(a => a.id));
  let _dragEl = null;

  function render() {
    const actions = qa.getActions();
    const list = $id('qa-editor-list');
    if (!list) return;
    list.innerHTML = actions.map((a, i) => {
      const isPreset = defaultIds.has(a.id);
      return `<div class="qa-editor-item" draggable="true" data-idx="${i}">
        <span class="qa-e-icon">${a.icon}</span>
        <span class="qa-e-name">${t(a.label) || a.label || a.id}</span>
        ${isPreset ? `<span style="font-size:9px;color:var(--text-muted)">${t('settings.qaPreset')}</span>` : ''}
        <button class="qa-e-del" data-idx="${i}" ${isPreset ? 'disabled' : ''}>✕</button>
      </div>`;
    }).join('');

    list.querySelectorAll('.qa-e-del:not([disabled])').forEach(btn => {
      btn.addEventListener('click', () => {
        if (!confirm(t('settings.qaDeleteConfirm'))) return;
        const actions = qa.getActions();
        actions.splice(+btn.dataset.idx, 1);
        qa.save(actions); render(); qa.render();
      });
    });

    list.querySelectorAll('.qa-editor-item').forEach(item => {
      item.addEventListener('dragstart', (e) => {
        _dragEl = item;
        item.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
      });
      item.addEventListener('dragend', () => {
        item.classList.remove('dragging');
        _dragEl = null;
      });
      item.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      });
      item.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!_dragEl || _dragEl === item) return;
        const fromIdx = +_dragEl.dataset.idx;
        const toIdx = +item.dataset.idx;
        const actions = qa.getActions();
        const [moved] = actions.splice(fromIdx, 1);
        actions.splice(toIdx, 0, moved);
        qa.save(actions); render(); qa.render();
      });
    });
  }

  $id('qa-add-btn')?.addEventListener('click', () => {
    const icon = $id('qa-add-icon')?.value?.trim() || '📌';
    const name = $id('qa-add-name')?.value?.trim();
    const skill = $id('qa-add-skill')?.value?.trim();
    if (!name || !skill) { if (typeof window.ocToast !== 'undefined') window.ocToast.warning(t('settings.qaNameSkillRequired')); return; }
    const id = 'custom_' + Date.now();
    const actions = qa.getActions();
    actions.push({ id, icon, label: name, skill });
    qa.save(actions); render(); qa.render();
    $id('qa-add-icon').value = ''; $id('qa-add-name').value = ''; $id('qa-add-skill').value = '';
    if (typeof window.ocToast !== 'undefined') window.ocToast.success(t('settings.qaAdded'));
  });

  const observer = new MutationObserver(() => {
    const modal = $id('settings-modal');
    if (modal && !modal.classList.contains('hidden')) render();
  });
  const sm = $id('settings-modal');
  if (sm) observer.observe(sm, { attributes: true, attributeFilter: ['class'] });
  render();
}

// 27. MESSAGE BOOKMARKS — moved to settings-chat.js

// 29. TTS PREVIEW
function initTtsPreview() {
  const $id = id => document.getElementById(id);
  let _audio = null;
  let _playing = false;

  const sampleTexts = {
    zh: '你好，我是你的 AI 语音助手，很高兴为你服务。',
    en: 'Hello, I am your AI voice assistant. Nice to meet you!',
    ja: 'こんにちは、私はあなたのAI音声アシスタントです。',
  };

  $id('tts-preview-btn')?.addEventListener('click', async () => {
    const btn = $id('tts-preview-btn');
    const status = $id('tts-preview-status');
    if (_playing) {
      if (_audio) { _audio.pause(); _audio.currentTime = 0; }
      _playing = false;
      btn.textContent = t('settings.ttsPreview');
      btn.classList.remove('playing');
      status.textContent = '';
      return;
    }
    _playing = true;
    btn.textContent = t('settings.ttsPlaying');
    btn.classList.add('playing');
    status.textContent = t('settings.ttsPreviewing');
    try {
      const lang = document.documentElement.lang?.startsWith('en') ? 'en' : 'zh';
      const text = sampleTexts[lang] || sampleTexts.zh;
      const r = await fetch(getBaseUrl() + '/api/tts', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ text, format: 'mp3' }),
      });
      if (!r.ok) throw new Error('TTS failed: ' + r.status);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      _audio = new Audio(url);
      _audio.onended = () => {
        _playing = false;
        btn.textContent = t('settings.ttsPreview');
        btn.classList.remove('playing');
        status.textContent = '';
        URL.revokeObjectURL(url);
      };
      _audio.onerror = () => {
        _playing = false;
        btn.textContent = t('settings.ttsPreview');
        btn.classList.remove('playing');
        status.textContent = '';
      };
      await _audio.play();
    } catch(e) {
      _playing = false;
      btn.textContent = t('settings.ttsPreview');
      btn.classList.remove('playing');
      status.textContent = '';
      if (typeof window.ocToast !== 'undefined') window.ocToast.error('TTS preview failed: ' + e.message);
    }
  });
}

// 30–37. MESSAGE EXPORT, EDIT, SUMMARY, PINNED, REACTIONS, TRANSLATE — moved to settings-chat.js

// 33. DRAG UPLOAD
function initDragUpload() {
  const overlay = $('drag-overlay');
  const chatPage = $('chat-page');
  if (!overlay || !chatPage) return;
  let _dragCounter = 0;

  chatPage.addEventListener('dragenter', (e) => {
    e.preventDefault();
    _dragCounter++;
    overlay.classList.add('active');
  });
  chatPage.addEventListener('dragleave', (e) => {
    _dragCounter--;
    if (_dragCounter <= 0) { _dragCounter = 0; overlay.classList.remove('active'); }
  });
  chatPage.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });
  chatPage.addEventListener('drop', async (e) => {
    e.preventDefault();
    _dragCounter = 0;
    overlay.classList.remove('active');
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    for (const file of files) { await handleDropFile(file); }
  });

  async function handleDropFile(file) {
    fn.hideWelcome();
    const preview = document.createElement('div');
    preview.className = 'upload-preview';
    const isImage = file.type.startsWith('image/');
    if (isImage) {
      const thumb = document.createElement('img');
      thumb.src = URL.createObjectURL(file);
      preview.appendChild(thumb);
    } else {
      const icon = document.createElement('span');
      icon.textContent = '📎';
      icon.style.fontSize = '24px';
      preview.appendChild(icon);
    }
    const info = document.createElement('div');
    info.style.flex = '1';
    info.innerHTML = `<div style="font-weight:600">${escapeHtml(file.name)}</div><div style="color:var(--text-muted);font-size:10px">${(file.size / 1024).toFixed(1)} KB</div>
      <div class="upload-progress"><div class="upload-progress-bar" id="up-bar-${Date.now()}"></div></div>`;
    preview.appendChild(info);
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:4px';
    actions.innerHTML = `<button class="mp-btn mp-btn-install up-confirm" style="font-size:10px;padding:4px 10px">${t('upload.confirm')}</button>
      <button class="mp-btn up-cancel" style="font-size:10px;padding:4px 10px;background:var(--bg-surface);color:var(--text-muted);border:1px solid var(--border)">${t('upload.cancel')}</button>`;
    preview.appendChild(actions);
    dom.messages.appendChild(preview);
    fn.scrollToBottom();

    const confirmBtn = actions.querySelector('.up-confirm');
    const cancelBtn = actions.querySelector('.up-cancel');
    cancelBtn.addEventListener('click', () => preview.remove());

    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true;
      confirmBtn.textContent = t('upload.uploading');
      const bar = preview.querySelector('[class*="upload-progress-bar"]');
      try {
        const fd = new FormData();
        fd.append('file', file);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', getBaseUrl() + '/api/upload');
        xhr.upload.addEventListener('progress', (pe) => {
          if (pe.lengthComputable && bar) bar.style.width = Math.round(pe.loaded / pe.total * 100) + '%';
        });
        await new Promise((resolve, reject) => {
          xhr.onload = () => { if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.responseText); else reject(new Error(xhr.statusText)); };
          xhr.onerror = () => reject(new Error('Network error'));
          xhr.send(fd);
        });
        preview.remove();
        if (typeof window.ocToast !== 'undefined') window.ocToast.success(t('upload.done'));
        const userMsg = { role: 'user', content: `📎 ${file.name} (${(file.size / 1024).toFixed(1)} KB)` };
        if (isImage) userMsg.imageData = [URL.createObjectURL(file)];
        S.messages.push(userMsg);
        fn.appendMessage(userMsg);
      } catch (err) {
        confirmBtn.textContent = t('upload.error');
        if (typeof window.ocToast !== 'undefined') window.ocToast.error(t('upload.error'));
      }
    });
  }
}

// 38. KEYMAP PANEL
function initKeymapPanel() {
  const panel = $('keymap-panel');
  const body = $('keymap-body');
  const search = $('keymap-search');
  if (!panel || !body) return;

  const SHORTCUTS = [
    { group: 'keymap.general', items: [
      { keys: ['Ctrl','F'], desc: '消息搜索 / Message Search' },
      { keys: ['Escape'], desc: '关闭面板 / Close Panel' },
      { keys: ['?'], desc: '快捷键帮助 / Shortcut Help' },
      { keys: ['Ctrl','/'], desc: '快捷键帮助 / Shortcut Help' },
    ]},
    { group: 'keymap.voice', items: [
      { keys: ['Space'], desc: '开始/停止录音 / Toggle Recording' },
    ]},
    { group: 'keymap.panels', items: [
      { keys: ['Ctrl','M'], desc: '模型面板 / Model Panel' },
      { keys: ['Ctrl','T'], desc: 'MCP 工具 / MCP Tools' },
      { keys: ['Ctrl','P'], desc: '性能面板 / Performance' },
      { keys: ['Ctrl','Shift','D'], desc: '切换主题 / Toggle Theme' },
    ]},
    { group: 'keymap.command', items: [
      { keys: ['Ctrl','K'], desc: '命令面板 / Command Palette' },
    ]},
  ];

  function render(filter) {
    const lf = (filter || '').toLowerCase();
    body.innerHTML = SHORTCUTS.map(g => {
      const rows = g.items.map(it => {
        const kbds = it.keys.map(k => `<kbd>${k}</kbd>`).join(' + ');
        const vis = !lf || it.desc.toLowerCase().includes(lf) || it.keys.some(k => k.toLowerCase().includes(lf));
        return `<div class="keymap-row${vis ? '' : ' hidden'}"><span>${it.desc}</span><span class="keymap-keys">${kbds}</span></div>`;
      }).join('');
      return `<div class="keymap-group"><div class="keymap-group-title">${t(g.group)}</div>${rows}</div>`;
    }).join('');
  }

  function openKeymap() { render(''); panel.classList.add('open'); search.value = ''; search.focus(); }
  function closeKeymap() { panel.classList.remove('open'); }

  $('keymap-close')?.addEventListener('click', closeKeymap);
  panel.addEventListener('click', (e) => { if (e.target === panel) closeKeymap(); });
  search?.addEventListener('input', () => render(search.value));

  document.addEventListener('keydown', (e) => {
    if ((e.key === '?' && !e.ctrlKey && !e.metaKey) || (e.key === '/' && (e.ctrlKey || e.metaKey))) {
      const tag = document.activeElement?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      e.preventDefault();
      if (panel.classList.contains('open')) closeKeymap();
      else openKeymap();
    }
    if (e.key === 'Escape' && panel.classList.contains('open')) { e.stopPropagation(); closeKeymap(); }
  });

  const settingsGroups = document.querySelectorAll('.settings-group');
  if (settingsGroups.length) {
    const last = settingsGroups[settingsGroups.length - 1];
    const grp = document.createElement('div');
    grp.className = 'settings-group';
    grp.innerHTML = `<h3 data-i18n="keymap.title">${t('keymap.title')}</h3><button class="mp-btn" id="keymap-open-btn" style="font-size:11px;padding:6px 14px;background:var(--bg-surface);color:var(--text-primary);border:1px solid var(--border);border-radius:6px;cursor:pointer">⌨️ ${t('keymap.title')} <kbd>?</kbd></button>`;
    last.after(grp);
    $('keymap-open-btn')?.addEventListener('click', openKeymap);
  }
}

// 40. ONBOARDING GUIDE
function initOnboarding() {
  if (localStorage.getItem('oc-onboarding-done')) return;

  const steps = [
    { target: '#msg-input', title: '💬 开始对话', desc: '在这里输入文字，或点击麦克风图标用语音对话', pos: 'top' },
    { target: '#settings-toggle', title: '⚙️ 个性设置', desc: '点击齿轮进入设置，可切换主题、声音、AI 平台等', pos: 'bottom-left' },
    { target: '#header-more-toggle', title: '🔧 更多功能', desc: '点击这里查看摄像头、技能中心、模型管理等高级功能', pos: 'bottom-left' },
  ];

  let current = 0;

  const overlay = document.createElement('div');
  overlay.id = 'onboarding-overlay';
  overlay.innerHTML = `
    <style>
      #onboarding-overlay{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.55);transition:opacity .3s}
      .ob-tooltip{position:fixed;z-index:10000;background:#fff;color:#1a1a2e;border-radius:14px;padding:20px 24px;
        max-width:320px;box-shadow:0 12px 40px rgba(0,0,0,.3);animation:ob-in .3s ease}
      @keyframes ob-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
      .ob-tooltip h4{margin:0 0 6px;font-size:16px;font-weight:700}
      .ob-tooltip p{margin:0 0 16px;font-size:14px;color:#5a5a72;line-height:1.5}
      .ob-actions{display:flex;justify-content:space-between;align-items:center}
      .ob-dots{display:flex;gap:6px}
      .ob-dot{width:8px;height:8px;border-radius:50%;background:#ddd}
      .ob-dot.active{background:#6c5ce7}
      .ob-next{padding:8px 20px;background:#6c5ce7;color:#fff;border:none;border-radius:8px;
        font-size:14px;font-weight:600;cursor:pointer}
      .ob-next:hover{background:#5b4bd6}
      .ob-skip{background:none;border:none;color:#9a9ab0;cursor:pointer;font-size:13px}
      .ob-skip:hover{color:#6c5ce7}
      .ob-highlight{position:fixed;z-index:9999;border-radius:8px;
        box-shadow:0 0 0 4000px rgba(0,0,0,.5),0 0 0 3px #6c5ce7;transition:all .3s}
    </style>
    <div class="ob-highlight" id="ob-highlight"></div>
    <div class="ob-tooltip" id="ob-tooltip">
      <h4 id="ob-title"></h4>
      <p id="ob-desc"></p>
      <div class="ob-actions">
        <button class="ob-skip" id="ob-skip">跳过引导</button>
        <div class="ob-dots" id="ob-dots"></div>
        <button class="ob-next" id="ob-next">下一步</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const hl = document.getElementById('ob-highlight');
  const tip = document.getElementById('ob-tooltip');
  const titleEl = document.getElementById('ob-title');
  const descEl = document.getElementById('ob-desc');
  const dotsEl = document.getElementById('ob-dots');
  const nextBtn = document.getElementById('ob-next');
  const skipBtn = document.getElementById('ob-skip');

  function showStep(i) {
    const step = steps[i];
    const el = document.querySelector(step.target);
    if (!el) { finish(); return; }

    const rect = el.getBoundingClientRect();
    hl.style.left = (rect.left - 4) + 'px';
    hl.style.top = (rect.top - 4) + 'px';
    hl.style.width = (rect.width + 8) + 'px';
    hl.style.height = (rect.height + 8) + 'px';

    titleEl.textContent = step.title;
    descEl.textContent = step.desc;

    dotsEl.innerHTML = steps.map((_, j) =>
      `<div class="ob-dot${j === i ? ' active' : ''}"></div>`
    ).join('');

    nextBtn.textContent = i === steps.length - 1 ? '开始使用' : '下一步';

    if (step.pos === 'top') {
      tip.style.bottom = (window.innerHeight - rect.top + 16) + 'px';
      tip.style.top = 'auto';
      tip.style.left = Math.max(16, rect.left - 60) + 'px';
      tip.style.right = 'auto';
    } else {
      tip.style.top = (rect.bottom + 16) + 'px';
      tip.style.bottom = 'auto';
      tip.style.right = '16px';
      tip.style.left = 'auto';
    }
  }

  function finish() {
    localStorage.setItem('oc-onboarding-done', '1');
    overlay.style.opacity = '0';
    setTimeout(() => overlay.remove(), 300);
  }

  nextBtn.addEventListener('click', () => {
    current++;
    if (current >= steps.length) finish();
    else showStep(current);
  });

  skipBtn.addEventListener('click', finish);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) finish();
  });

  setTimeout(() => showStep(0), 1500);
}

function initPetGainSliders() {
  const GM = 'oc_pet_mic_gain';
  const GP = 'oc_pet_playback_gain';
  const GL = 'oc_pet_level_mode';
  const m = document.getElementById('pet-mic-gain');
  const p = document.getElementById('pet-playback-gain');
  const lm = document.getElementById('pet-level-mode');
  const mv = document.getElementById('pet-mic-gain-val');
  const pv = document.getElementById('pet-playback-gain-val');
  if (!m || !p || !mv || !pv) return;
  function syncVals() {
    mv.textContent = Number(m.value).toFixed(2);
    pv.textContent = Number(p.value).toFixed(2);
  }
  function load() {
    const a = localStorage.getItem(GM);
    const b = localStorage.getItem(GP);
    m.value = a != null && a !== '' ? a : '1';
    p.value = b != null && b !== '' ? b : '1';
    if (lm) {
      const mode = localStorage.getItem(GL) || 'sum';
      lm.value = mode === 'max' ? 'max' : 'sum';
    }
    syncVals();
  }
  function save() {
    localStorage.setItem(GM, m.value);
    localStorage.setItem(GP, p.value);
    syncVals();
    invalidatePetGainCache();
  }
  function saveLevelMode() {
    if (!lm) return;
    const v = lm.value === 'max' ? 'max' : 'sum';
    localStorage.setItem(GL, v);
    try {
      petBroadcast({ petLevelMode: v, ts: Date.now() });
    } catch (_) {}
  }
  load();
  m.addEventListener('input', save);
  p.addEventListener('input', save);
  lm?.addEventListener('change', saveLevelMode);
  document.getElementById('settings-toggle')?.addEventListener('click', () => {
    setTimeout(load, 0);
  });
}

function initPetSkinSelect() {
  const sel = document.getElementById('pet-skin-select');
  const chipWrap = document.getElementById('pet-skin-preview-chips');
  if (!sel) return;

  const CHIP_EMOJI = { eve: '🦞', walle: '🦾', orbit: '🛰️' };

  function rebuildOptions() {
    sel.innerHTML = PET_SKIN_IDS.map((id) => {
      const key = PET_SKIN_I18N_KEYS[id] || 'settings.petSkin';
      return `<option value="${id}">${escapeHtml(t(key))}</option>`;
    }).join('');
  }

  function renderChips() {
    if (!chipWrap) return;
    chipWrap.innerHTML = PET_SKIN_IDS.map((id) => {
      const key = PET_SKIN_I18N_KEYS[id] || 'settings.petSkin';
      const label = escapeHtml(t(key));
      const emoji = CHIP_EMOJI[id] || '🦞';
      return `<button type="button" class="pet-skin-chip" data-skin="${id}" title="${label}" aria-label="${label}"><span class="pet-skin-chip-emoji" aria-hidden="true">${emoji}</span><span class="pet-skin-chip-text">${label}</span></button>`;
    }).join('');
  }

  function highlightChips() {
    if (!chipWrap) return;
    const v = petGetSkin();
    chipWrap.querySelectorAll('.pet-skin-chip').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.skin === v);
    });
  }

  function applyToUi() {
    const v = petGetSkin();
    if (sel.value !== v) sel.value = v;
    highlightChips();
  }

  function refreshFromI18n() {
    rebuildOptions();
    renderChips();
    applyToUi();
  }

  rebuildOptions();
  renderChips();
  applyToUi();
  window.addEventListener('oc-lang-change', refreshFromI18n);
  window.addEventListener('oc-i18n-updated', refreshFromI18n);
  sel.addEventListener('change', () => {
    petSetSkin(sel.value);
    applyToUi();
  });
  chipWrap?.addEventListener('click', (e) => {
    const btn = e.target.closest('.pet-skin-chip');
    if (!btn?.dataset?.skin) return;
    petSetSkin(btn.dataset.skin);
    applyToUi();
  });
  window.addEventListener('storage', (e) => {
    if (e.key === 'oc_pet_skin' || e.key === 'petSkin') applyToUi();
  });
  document.getElementById('settings-toggle')?.addEventListener('click', () => {
    setTimeout(applyToUi, 0);
  });
  try {
    petBroadcast({ skin: petGetSkin(), ts: Date.now() });
  } catch (_) {}
}

// ══════════════════════════════════════════════════════════════
// COMBINED INIT
// ══════════════════════════════════════════════════════════════
export function init() {
  // Part 1
  initModelPanel();
  initMcpPanel();
  initEmotionIndicator();
  initThemeSwitcher();
  initUiModeSwitcher();
  initVoiceClone();
  initSettingsTabs();
  initPullToRefresh();
  initKeyboardShortcuts();
  initFocusManagement();
  initVoiceCommands();
  initWechatPanel();
  initSettingsExport();
  initExpressionSettings();
  initNotificationCenter();
  initHeaderDragSort();
  // Part 2
  initModelDepGraph();
  initQuickActionsBar();
  initAdvancedTheme();
  initWakeWordCustomizer();
  initMessageSearch();
  initQaEditor();
  initBookmarks();
  initTtsPreview();
  initMessageExport();
  initMessageEdit();
  initDragUpload();
  initSummary();
  initPinnedMessages();
  initReactions();
  initTranslate();
  initKeymapPanel();
  initOnboarding();
  initIntentPanel();
  initCoworkPanel();
  initGestureBindings();
  initActionTimeline();
  initPetGainSliders();
  initPetSkinSelect();

  fn.showEmotionBadge = showEmotionBadge;
}
