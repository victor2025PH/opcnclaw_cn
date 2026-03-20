// cowork-panel.js — CoworkBus collaboration status panel (B3)
// Displays AI/Human collaboration state, task queue, action journal, undo/pause/resume
import { S, fn, dom, t, $, $$, getBaseUrl, bus } from '/js/state.js';

const COWORK_API = () => getBaseUrl() + '/api/cowork';
const STATUS_POLL_MS = 5000;

// Mock data used when API is unavailable
const MOCK_STATUS = {
  human_zone: 'active',
  ai_zone: 'idle',
  state: 'idle',        // idle | working | paused | conflict
  current_task: null,
  queue: [],
  uptime_s: 3621,
};

const MOCK_JOURNAL = [
  { id: 'j1', action_type: 'click', description: '点击「文件」菜单', timestamp: Date.now() - 120000, reversible: true },
  { id: 'j2', action_type: 'type', description: '输入搜索关键词 "报告"', timestamp: Date.now() - 90000, reversible: true },
  { id: 'j3', action_type: 'hotkey', description: '按下 Ctrl+S 保存文件', timestamp: Date.now() - 45000, reversible: false },
  { id: 'j4', action_type: 'scroll', description: '向下滚动 300px', timestamp: Date.now() - 20000, reversible: true },
];

const STATE_META = {
  idle:     { icon: '\u{1F7E2}', label: 'AI 空闲',  color: 'var(--success)' },
  working:  { icon: '\u{1F535}', label: 'AI 工作中', color: 'var(--accent)' },
  paused:   { icon: '\u{1F7E1}', label: '已暂停',   color: 'var(--warning)' },
  conflict: { icon: '\u{1F534}', label: '冲突',     color: 'var(--error)' },
};

const ACTION_ICONS = {
  click: '\u{1F5B1}\uFE0F', type: '\u2328\uFE0F', hotkey: '\u26A1', scroll: '\u2195\uFE0F',
  screenshot: '\u{1F4F7}', drag: '\u{1F4CC}', default: '\u{1F4AC}',
};

let _panel = null;
let _badge = null;
let _pollTimer = null;
let _open = false;
let _useMock = false;
let _status = { ...MOCK_STATUS };
let _journal = [...MOCK_JOURNAL];

function fmtAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return s + '秒前';
  if (s < 3600) return Math.floor(s / 60) + '分钟前';
  return Math.floor(s / 3600) + '小时前';
}

function renderBadge() {
  if (!_badge) return;
  const meta = STATE_META[_status.state] || STATE_META.idle;
  _badge.textContent = meta.icon;
  _badge.title = meta.label;
  _badge.style.setProperty('--cw-glow', meta.color);
  _badge.classList.toggle('cw-working', _status.state === 'working');
}

function renderPanel() {
  if (!_panel) return;
  const meta = STATE_META[_status.state] || STATE_META.idle;
  const q = _status.queue || [];
  const isPaused = _status.state === 'paused';

  _panel.querySelector('.cw-state-row').innerHTML = `
    <span class="cw-state-icon" style="color:${meta.color}">${meta.icon}</span>
    <span class="cw-state-label">${meta.label}</span>
    ${_status.current_task ? `<span class="cw-task-name">${_status.current_task.description || ''}</span>` : ''}
    <span class="cw-zone-info">
      <span title="用户区域">\u{1F9D1} ${_status.human_zone}</span>
      <span title="AI 区域">\u{1F916} ${_status.ai_zone}</span>
    </span>
  `;

  const qEl = _panel.querySelector('.cw-queue-body');
  if (q.length === 0) {
    qEl.innerHTML = '<div class="cw-empty">队列为空</div>';
  } else {
    qEl.innerHTML = q.map((task, i) => `
      <div class="cw-queue-item">
        <span class="cw-qi-idx">#${i + 1}</span>
        <span class="cw-qi-desc">${task.description || task.id}</span>
        <span class="cw-qi-status">${task.status || 'pending'}</span>
      </div>
    `).join('');
  }

  const jEl = _panel.querySelector('.cw-journal-body');
  if (_journal.length === 0) {
    jEl.innerHTML = '<div class="cw-empty">暂无操作记录</div>';
  } else {
    jEl.innerHTML = _journal.slice(0, 8).map(j => {
      const icon = ACTION_ICONS[j.action_type] || ACTION_ICONS.default;
      return `
        <div class="cw-journal-item" data-id="${j.id}">
          <span class="cw-ji-icon">${icon}</span>
          <div class="cw-ji-info">
            <span class="cw-ji-desc">${j.description}</span>
            <span class="cw-ji-time">${fmtAgo(j.timestamp)}</span>
          </div>
          ${j.reversible ? `<button class="cw-undo-btn" data-id="${j.id}" title="撤销此操作">\u21A9\uFE0F</button>` : ''}
        </div>`;
    }).join('');
  }

  const pauseBtn = _panel.querySelector('.cw-pause-btn');
  if (pauseBtn) {
    pauseBtn.textContent = isPaused ? '\u25B6\uFE0F 恢复' : '\u23F8\uFE0F 暂停';
    pauseBtn.dataset.action = isPaused ? 'resume' : 'pause';
  }

  if (_useMock) {
    const mockTag = _panel.querySelector('.cw-mock-tag');
    if (mockTag) mockTag.style.display = '';
  }
}

async function fetchStatus() {
  try {
    const resp = await fetch(COWORK_API() + '/status');
    if (!resp.ok) throw new Error(resp.status);
    _status = await resp.json();
    _useMock = false;
  } catch {
    _useMock = true;
    // Rotate mock state for demonstration
    _status = { ...MOCK_STATUS };
    const states = ['idle', 'working', 'paused'];
    _status.state = states[Math.floor(Date.now() / 10000) % states.length];
    if (_status.state === 'working') {
      _status.current_task = { id: 't1', description: '整理文件夹', status: 'running' };
      _status.queue = [
        { id: 't2', description: '发送日报邮件', status: 'pending' },
        { id: 't3', description: '备份数据库', status: 'pending' },
      ];
    }
  }
  renderBadge();
  if (_open) renderPanel();
}

async function fetchJournal() {
  try {
    const resp = await fetch(COWORK_API() + '/journal');
    if (!resp.ok) throw new Error(resp.status);
    _journal = await resp.json();
    _useMock = false;
  } catch {
    _useMock = true;
    _journal = [...MOCK_JOURNAL];
  }
  if (_open) renderPanel();
}

async function doUndo(actionId) {
  try {
    const resp = await fetch(COWORK_API() + '/undo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(actionId ? { action_id: actionId } : {}),
    });
    if (!resp.ok) throw new Error(resp.status);
    await fetchJournal();
    await fetchStatus();
  } catch {
    if (_useMock) {
      _journal = _journal.filter(j => j.id !== actionId);
      renderPanel();
    }
  }
}

async function doPauseResume(action) {
  try {
    const resp = await fetch(COWORK_API() + '/' + action, { method: 'POST' });
    if (!resp.ok) throw new Error(resp.status);
    await fetchStatus();
  } catch {
    if (_useMock) {
      _status.state = action === 'pause' ? 'paused' : 'idle';
      renderBadge();
      renderPanel();
    }
  }
}

function togglePanel() {
  _open = !_open;
  _panel.classList.toggle('open', _open);
  _badge.classList.toggle('active', _open);
  if (_open) {
    fetchStatus();
    fetchJournal();
  }
}

function buildPanel() {
  _panel = document.createElement('div');
  _panel.className = 'cw-panel';
  _panel.innerHTML = `
    <div class="cw-header">
      <span class="cw-header-title">\u{1F91D} 人机协作</span>
      <span class="cw-mock-tag" style="display:none;font-size:10px;background:var(--warning);color:#000;padding:1px 6px;border-radius:8px">Mock</span>
      <button class="cw-close-btn" title="关闭">\u2715</button>
    </div>
    <div class="cw-section">
      <div class="cw-section-title">状态</div>
      <div class="cw-state-row"></div>
    </div>
    <div class="cw-section">
      <div class="cw-section-title">任务队列</div>
      <div class="cw-queue-body"></div>
    </div>
    <div class="cw-section">
      <div class="cw-section-title">操作日志</div>
      <div class="cw-journal-body"></div>
    </div>
    <div class="cw-actions">
      <button class="cw-btn cw-undo-last-btn">\u21A9\uFE0F 撤销上一步</button>
      <button class="cw-btn cw-pause-btn" data-action="pause">\u23F8\uFE0F 暂停</button>
    </div>
  `;

  _panel.querySelector('.cw-close-btn').addEventListener('click', () => togglePanel());
  _panel.querySelector('.cw-undo-last-btn').addEventListener('click', () => doUndo(null));
  _panel.querySelector('.cw-pause-btn').addEventListener('click', (e) => {
    doPauseResume(e.currentTarget.dataset.action);
  });
  _panel.addEventListener('click', (e) => {
    const undoBtn = e.target.closest('.cw-undo-btn');
    if (undoBtn) doUndo(undoBtn.dataset.id);
  });

  document.addEventListener('click', (e) => {
    if (_open && !_panel.contains(e.target) && e.target !== _badge && !_badge.contains(e.target)) {
      togglePanel();
    }
  });

  return _panel;
}

function startPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(() => {
    fetchStatus();
    if (_open) fetchJournal();
  }, STATUS_POLL_MS);
}

export function initCoworkPanel() {
  const headerRight = document.querySelector('.header-right');
  if (!headerRight) return;

  _badge = document.createElement('button');
  _badge.className = 'icon-btn cw-badge';
  _badge.id = 'cowork-toggle';
  _badge.title = '人机协作状态';
  _badge.textContent = '\u{1F7E2}';
  _badge.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePanel();
  });

  const settingsBtn = document.getElementById('settings-toggle');
  headerRight.insertBefore(_badge, settingsBtn);

  const panel = buildPanel();
  headerRight.appendChild(panel);

  // Also add to header overflow menu
  const overflowMenu = document.getElementById('header-overflow-menu');
  if (overflowMenu) {
    const firstSep = overflowMenu.querySelector('.hom-sep');
    const homItem = document.createElement('button');
    homItem.className = 'hom-item';
    homItem.dataset.target = 'cowork-toggle';
    homItem.innerHTML = '<span class="hom-icon">\u{1F91D}</span>人机协作';
    if (firstSep) {
      overflowMenu.insertBefore(homItem, firstSep);
    } else {
      overflowMenu.appendChild(homItem);
    }
  }

  fetchStatus();
  startPolling();

  bus.on('cowork:status', (data) => {
    _status = data;
    renderBadge();
    if (_open) renderPanel();
  });
}
