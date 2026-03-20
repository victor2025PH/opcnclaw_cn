// action-timeline.js — Vertical action timeline with thumbnails (B4)
import { S, fn, getBaseUrl, bus } from '/js/state.js';

const COWORK_API = () => getBaseUrl() + '/api/cowork';

const ACTION_ICONS = {
  click: '\u{1F5B1}\uFE0F', type: '\u2328\uFE0F', hotkey: '\u26A1', scroll: '\u2195\uFE0F',
  screenshot: '\u{1F4F7}', drag: '\u{1F4CC}', key: '\u2328\uFE0F', default: '\u{1F4AC}',
};

function normalizeTs(raw) {
  if (!raw) return Date.now();
  const n = typeof raw === 'number' ? raw : Date.parse(raw);
  return n > 1e12 ? n : n * 1000;
}

let _container = null;
let _entries = [];
let _loading = false;
let _thumbCache = {};

function fmtTime(ms) {
  const d = new Date(ms);
  return d.getHours().toString().padStart(2, '0') + ':' +
         d.getMinutes().toString().padStart(2, '0') + ':' +
         d.getSeconds().toString().padStart(2, '0');
}

function fmtAgo(ms) {
  const s = Math.floor((Date.now() - ms) / 1000);
  if (s < 0) return '刚刚';
  if (s < 60) return s + '\u79D2\u524D';
  if (s < 3600) return Math.floor(s / 60) + '\u5206\u949F\u524D';
  return Math.floor(s / 3600) + '\u5C0F\u65F6\u524D';
}

async function loadJournal() {
  _loading = true;
  render();
  try {
    const resp = await fetch(COWORK_API() + '/journal');
    if (!resp.ok) throw new Error(resp.status);
    const data = await resp.json();
    _entries = Array.isArray(data) ? data : (data.entries || data.journal || []);
  } catch {
    _entries = [];
  }
  _loading = false;
  render();
}

async function loadThumbnails(id) {
  if (_thumbCache[id]) return _thumbCache[id];
  try {
    const resp = await fetch(COWORK_API() + `/journal/${id}/thumbnails`);
    if (!resp.ok) return null;
    const data = await resp.json();
    _thumbCache[id] = data;
    return data;
  } catch {
    return null;
  }
}

async function undoTo(id) {
  try {
    const resp = await fetch(COWORK_API() + '/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action_id: id }),
    });
    if (resp.ok) {
      _thumbCache = {};
      await loadJournal();
    }
  } catch { /* silent */ }
}

async function toggleThumbs(id) {
  const el = _container.querySelector(`.at-thumbs[data-id="${id}"]`);
  if (!el) return;
  if (el.style.display !== 'none') {
    el.style.display = 'none';
    return;
  }
  el.innerHTML = '<div class="at-loading">加载截图...</div>';
  el.style.display = '';
  const data = await loadThumbnails(id);
  if (!data) {
    el.innerHTML = '<div class="at-empty-thumb">无截图数据</div>';
    return;
  }
  el.innerHTML = `
    <div class="at-thumb-pair">
      <div class="at-thumb-item">
        <div class="at-thumb-label">操作前</div>
        ${data.before ? `<img src="${data.before}" alt="before">` : '<div class="at-empty-thumb">-</div>'}
      </div>
      <div class="at-thumb-item">
        <div class="at-thumb-label">操作后</div>
        ${data.after ? `<img src="${data.after}" alt="after">` : '<div class="at-empty-thumb">-</div>'}
      </div>
    </div>`;
}

function render() {
  if (!_container) return;

  if (_loading) {
    _container.innerHTML = '<div class="at-loading">\u23F3 加载操作日志...</div>';
    return;
  }

  if (_entries.length === 0) {
    _container.innerHTML = '<div class="at-empty">\u{1F4ED} 暂无操作记录<br><span style="font-size:11px;color:var(--text-muted)">AI 执行桌面操作后将显示在这里</span></div>';
    return;
  }

  const visible = _entries.filter(e => !e.undone);
  _container.innerHTML = `
    <div class="at-header">
      <span>\u{1F4CB} 操作时间线 (${visible.length})</span>
      <button class="at-refresh" onclick="this.closest('.at-container')._refresh()">\u{1F504} 刷新</button>
    </div>
    <div class="at-timeline">
      ${visible.map((e, i) => {
        const icon = ACTION_ICONS[e.action || e.action_type] || ACTION_ICONS.default;
        const ts = normalizeTs(e.ts || e.timestamp);
        const desc = e.desc || e.description || e.action || '';
        const hasThumbs = e.has_before || e.has_after || e.has_thumbnails;
        return `
          <div class="at-node ${i === 0 ? 'at-latest' : ''}${e.undone ? ' at-undone' : ''}">
            <div class="at-dot-col">
              <div class="at-dot">${icon}</div>
              ${i < visible.length - 1 ? '<div class="at-line"></div>' : ''}
            </div>
            <div class="at-content">
              <div class="at-desc">${desc}</div>
              <div class="at-meta">
                <span class="at-time">${fmtTime(ts)}</span>
                <span class="at-ago">${fmtAgo(ts)}</span>
                ${hasThumbs ? `<button class="at-btn at-thumb-toggle" data-id="${e.id}">\u{1F4F7} 截图</button>` : ''}
                ${e.reversible && !e.undone ? `<button class="at-btn at-undo-to" data-id="${e.id}">\u21A9\uFE0F 撤销到这里</button>` : ''}
              </div>
              <div class="at-thumbs" data-id="${e.id}" style="display:none"></div>
            </div>
          </div>`;
      }).join('')}
    </div>`;

  _container._refresh = loadJournal;

  _container.querySelectorAll('.at-thumb-toggle').forEach(btn => {
    btn.addEventListener('click', () => toggleThumbs(btn.dataset.id));
  });
  _container.querySelectorAll('.at-undo-to').forEach(btn => {
    btn.addEventListener('click', () => {
      if (confirm('确定要撤销到这一步吗？之后的操作将被回滚。')) {
        undoTo(btn.dataset.id);
      }
    });
  });
}

export function initActionTimeline() {
  const tabExpr = document.getElementById('tab-expression');
  if (!tabExpr) return;

  const section = document.createElement('div');
  section.className = 'settings-group';
  section.innerHTML = '<h3>\u{1F4CB} AI 操作时间线</h3><p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">查看 AI 桌面操作记录，支持截图对比和撤销。</p>';

  _container = document.createElement('div');
  _container.className = 'at-container';
  section.appendChild(_container);

  const saveButtons = tabExpr.querySelector('div[style*="display:flex"][style*="gap:8px"][style*="margin-top:8px"]');
  if (saveButtons) {
    tabExpr.insertBefore(section, saveButtons);
  } else {
    tabExpr.appendChild(section);
  }

  loadJournal();

  bus.on('cowork:journal_update', loadJournal);
}
