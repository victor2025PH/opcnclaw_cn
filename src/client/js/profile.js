import { S, fn, dom, t, $, $$, getBaseUrl } from '/js/state.js';

// ══════════════════════════════════════════════════════════════
// SESSIONS MANAGEMENT
// ══════════════════════════════════════════════════════════════

const $id = id => document.getElementById(id);
let _sessions = [];
let _currentId = null;

function sessOpenPanel() { $id('sessions-panel').classList.add('open'); loadSessions(); }
function sessClosePanel() { $id('sessions-panel').classList.remove('open'); }

async function loadSessions() {
  try {
    const r = await fetch(getBaseUrl() + '/api/history/sessions');
    const d = await r.json();
    _sessions = d.sessions || d || [];
    _currentId = d.current_id || (_sessions[0]?.id);
    renderSessionList();
  } catch {
    $id('sess-list').innerHTML = `<div class="notif-empty">${t('sess.empty')}</div>`;
  }
}

function renderSessionList() {
  const list = $id('sess-list');
  if (!_sessions.length) {
    list.innerHTML = `<div class="notif-empty" data-i18n="sess.empty">${t('sess.empty')}</div>`;
    return;
  }
  list.innerHTML = _sessions.map(s => {
    const d = new Date(s.updated_at || s.created_at || Date.now());
    const ts = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    const isActive = s.id === _currentId;
    return `<div class="sess-item${isActive ? ' active' : ''}" data-id="${s.id}">
      <div class="sess-title">${s.title || s.id}</div>
      ${isActive ? `<span style="font-size:9px;color:var(--accent);font-weight:600">${t('sess.current')}</span>` : ''}
      <span class="sess-time">${ts}</span>
      <button class="sess-del" data-id="${s.id}" title="Delete">✕</button>
    </div>`;
  }).join('');
  list.querySelectorAll('.sess-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('sess-del')) return;
      switchSession(el.dataset.id);
    });
  });
  list.querySelectorAll('.sess-del').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); deleteSession(btn.dataset.id); });
  });
}

async function switchSession(id) {
  try {
    await fetch(getBaseUrl() + `/api/history/sessions/${id}/switch`, { method: 'POST' });
    _currentId = id;
    renderSessionList();
    sessClosePanel();
    if (window.ocToast) window.ocToast.info('会话已切换');
    const area = $id('messages-area');
    if (area) area.innerHTML = '';
  } catch(e) {
    if (window.ocToast) window.ocToast.error(e.message);
  }
}

async function newSession() {
  try {
    const r = await fetch(getBaseUrl() + '/api/history/sessions', { method: 'POST' });
    const d = await r.json();
    if (window.ocToast) window.ocToast.success('新会话已创建');
    await loadSessions();
    if (d.id) switchSession(d.id);
  } catch(e) {
    if (window.ocToast) window.ocToast.error(e.message);
  }
}

async function deleteSession(id) {
  if (!confirm(t('sess.deleteConfirm'))) return;
  try {
    await fetch(getBaseUrl() + `/api/history/sessions/${id}`, { method: 'DELETE' });
    await loadSessions();
  } catch(e) {
    if (window.ocToast) window.ocToast.error(e.message);
  }
}

// ══════════════════════════════════════════════════════════════
// PROFILE SWITCHER & MANAGEMENT
// ══════════════════════════════════════════════════════════════

let switcher, panel, ppList, ppClose, ppFamilyPresets, ppWorkPresets, ppEdit, ppPresetsTitle;

let profiles = [];
let activeId = null;
let editingId = null;
let profileStats = {};

const AVATARS = [
  '👨','👩','👦','👧','👴','👵','🧑','👶',
  '👨‍💻','👩‍💼','👨‍🎓','👩‍🎨','👨‍🍳','👩‍⚕️','👨‍🔬','👩‍🏫',
  '💼','💻','📋','🎓','🎨','🎵','🏃','🧠',
  '🤖','🦞','😀','😎','🐱','🐶','🦊','🐼',
  '🌸','🌟','🔥','💎','🎮','📚','🏠','🚀',
];

async function loadProfiles() {
  try {
    const r = await fetch(getBaseUrl() + '/api/profiles');
    const d = await r.json();
    if (d.ok) profiles = d.profiles || [];
  } catch(e) { profiles = []; }
  try {
    const r2 = await fetch(getBaseUrl() + '/api/profiles/stats');
    const d2 = await r2.json();
    if (d2.ok) profileStats = d2.stats || {};
  } catch(e) { profileStats = {}; }
  renderSwitcher();
  renderProfileList();
  const active = profiles.find(p => p.is_active);
  if (active) _updateVoiceBadge(active);
}

function renderSwitcher() {
  let html = '';
  profiles.forEach(p => {
    const isActive = p.is_active ? ' active' : '';
    html += `<div class="profile-avatar${isActive}" data-id="${p.id}" title="${p.name}">
      ${p.avatar || '👤'}
      <span class="pa-name">${p.name}</span>
    </div>`;
  });
  html += `<button class="profile-add-btn" id="profile-manage-btn" title="管理成员">+</button>`;
  html += `<div class="profile-quick-popup" id="profile-quick-popup"></div>`;
  switcher.innerHTML = html;

  const isMobile = window.innerWidth <= 767;
  switcher.querySelectorAll('.profile-avatar').forEach(el => {
    el.addEventListener('click', (e) => {
      if (isMobile && el.classList.contains('active') && profiles.length > 1) {
        e.stopPropagation();
        _toggleQuickPopup();
      } else {
        activateProfile(el.dataset.id);
      }
    });
  });
  document.getElementById('profile-manage-btn')?.addEventListener('click', profileOpenPanel);
}

function _toggleQuickPopup() {
  const popup = document.getElementById('profile-quick-popup');
  if (!popup) return;
  if (popup.classList.contains('open')) {
    popup.classList.remove('open');
    return;
  }
  popup.innerHTML = profiles.map(p =>
    `<div class="pqp-item${p.is_active ? ' active' : ''}" data-id="${p.id}">
      <span class="pqp-av">${p.avatar || '👤'}</span>
      <span class="pqp-name">${p.name}${p.is_active ? ' ●' : ''}</span>
    </div>`
  ).join('') + `<div class="pqp-manage" id="pqp-manage">⚙ 管理成员</div>`;
  popup.querySelectorAll('.pqp-item').forEach(el => {
    el.addEventListener('click', () => {
      popup.classList.remove('open');
      if (!el.classList.contains('active')) activateProfile(el.dataset.id);
    });
  });
  document.getElementById('pqp-manage')?.addEventListener('click', () => {
    popup.classList.remove('open');
    profileOpenPanel();
  });
  popup.classList.add('open');
  const closer = (e) => {
    if (!popup.contains(e.target)) { popup.classList.remove('open'); document.removeEventListener('click', closer); }
  };
  setTimeout(() => document.addEventListener('click', closer), 10);
}

function _formatLastActive(ts) {
  if (!ts) return '暂无对话';
  const d = new Date(ts.includes('T') ? ts : ts.replace(' ', 'T'));
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前';
  if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前';
  if (diff < 604800000) return Math.floor(diff / 86400000) + ' 天前';
  return d.toLocaleDateString();
}

function renderProfileList() {
  if (!ppList) return;
  if (profiles.length === 0) {
    ppList.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text-muted)">暂无成员，从下方模板快速创建</div>';
    return;
  }
  ppList.innerHTML = profiles.map((p, i) => {
    const st = profileStats[p.id] || {};
    const msgCount = st.message_count || 0;
    const lastActive = _formatLastActive(st.last_active);
    return `
    <div class="pp-card${p.is_active ? ' active' : ''}" data-id="${p.id}" style="animation-delay:${i * 50}ms">
      <div class="pp-card-avatar">${p.avatar || '👤'}</div>
      <div class="pp-card-info">
        <div class="pp-card-name">${p.name}${p.is_active ? ' <span style="color:var(--accent);font-size:10px">● 当前</span>' : ''}</div>
        <div class="pp-card-desc">${p.environment === 'family' ? '👨‍👩‍👧‍👦 家庭' : '💼 工作'} · ${p.age_group === 'child' ? '👶 儿童' : p.age_group === 'elder' ? '👴 老人' : '🧑 成人'}</div>
        <div class="pp-card-desc" style="margin-top:2px">💬 ${msgCount} 条对话 · ${lastActive}</div>
      </div>
      <div class="pp-card-actions">
        ${i > 0 ? `<button onclick="event.stopPropagation();_profileMove('${p.id}',-1)" title="上移" style="font-size:10px;opacity:.5">▲</button>` : ''}
        ${i < profiles.length - 1 ? `<button onclick="event.stopPropagation();_profileMove('${p.id}',1)" title="下移" style="font-size:10px;opacity:.5">▼</button>` : ''}
        <button onclick="event.stopPropagation();_profileEdit('${p.id}')" title="编辑" style="font-size:12px">✏</button>
        <button onclick="event.stopPropagation();_profileExport('${p.id}')" title="导出" style="font-size:12px">📥</button>
        <button onclick="event.stopPropagation();_profileActivate('${p.id}')" title="切换">✓</button>
        <button onclick="event.stopPropagation();_profileDelete('${p.id}')" title="删除">✕</button>
      </div>
    </div>`;
  }).join('');
  ppList.querySelectorAll('.pp-card').forEach(el => {
    el.addEventListener('click', () => activateProfile(el.dataset.id));
  });
}

// ─── Edit Form Logic ───
function openEditForm(profileId) {
  const p = profiles.find(x => x.id === profileId);
  if (!p || !ppEdit) return;
  editingId = profileId;

  document.getElementById('pp-edit-title').textContent = `编辑 · ${p.name}`;
  document.getElementById('pp-edit-name').value = p.name || '';
  document.getElementById('pp-edit-env').value = p.environment || 'family';
  document.getElementById('pp-edit-age').value = p.age_group || 'adult';
  document.getElementById('pp-edit-voice').value = p.voice_id || 'zh-CN-XiaohanNeural';
  document.getElementById('pp-edit-prompt').value = p.system_prompt || '';
  document.getElementById('pp-edit-avatar-preview').textContent = p.avatar || '👤';

  const grid = document.getElementById('pp-edit-avatar-grid');
  grid.innerHTML = AVATARS.map(a =>
    `<span data-a="${a}" class="${a === (p.avatar || '👤') ? 'selected' : ''}">${a}</span>`
  ).join('');
  grid.querySelectorAll('span').forEach(el => {
    el.addEventListener('click', () => {
      grid.querySelectorAll('span').forEach(s => s.classList.remove('selected'));
      el.classList.add('selected');
      document.getElementById('pp-edit-avatar-preview').textContent = el.dataset.a;
      document.getElementById('pp-edit-avatar-custom').value = '';
    });
  });
  const customInput = document.getElementById('pp-edit-avatar-custom');
  if (customInput) {
    customInput.value = '';
    customInput.addEventListener('input', () => {
      const v = customInput.value.trim();
      if (v) {
        grid.querySelectorAll('span').forEach(s => s.classList.remove('selected'));
        document.getElementById('pp-edit-avatar-preview').textContent = v;
      }
    });
  }

  _appendCloneVoicesToSelect();

  ppEdit.classList.add('active');
  if (ppPresetsTitle) ppPresetsTitle.style.display = 'none';
  const familyGrid = ppFamilyPresets?.parentElement || ppFamilyPresets;
  const workGrid = ppWorkPresets?.parentElement || ppWorkPresets;
  if (ppFamilyPresets) ppFamilyPresets.style.display = 'none';
  if (ppWorkPresets) ppWorkPresets.style.display = 'none';
  document.querySelectorAll('#profile-panel .pp-section-title').forEach(el => {
    if (el.id !== 'pp-members-title' && el.id !== 'pp-presets-title') el.style.display = 'none';
  });
}

function closeEditForm() {
  editingId = null;
  if (ppEdit) ppEdit.classList.remove('active');
  if (ppPresetsTitle) ppPresetsTitle.style.display = '';
  if (ppFamilyPresets) ppFamilyPresets.style.display = '';
  if (ppWorkPresets) ppWorkPresets.style.display = '';
  document.querySelectorAll('#profile-panel .pp-section-title').forEach(el => el.style.display = '');
}

async function saveEdit() {
  if (!editingId) return;
  const avatar = document.getElementById('pp-edit-avatar-preview')?.textContent?.trim() || '👤';
  const payload = {
    name: document.getElementById('pp-edit-name').value.trim() || '未命名',
    avatar,
    environment: document.getElementById('pp-edit-env').value,
    age_group: document.getElementById('pp-edit-age').value,
    voice_id: document.getElementById('pp-edit-voice').value,
    system_prompt: document.getElementById('pp-edit-prompt').value,
  };
  try {
    const r = await fetch(getBaseUrl() + `/api/profiles/${editingId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (d.ok) {
      if (window.ocToast) window.ocToast.success(`「${payload.name}」已更新`);
      closeEditForm();
      await loadProfiles();
    } else {
      if (window.ocToast) window.ocToast.error('保存失败');
    }
  } catch(e) {
    if (window.ocToast) window.ocToast.error('保存失败: ' + e.message);
  }
}

async function _appendCloneVoicesToSelect() {
  const sel = document.getElementById('pp-edit-voice');
  if (!sel) return;
  sel.querySelectorAll('option[data-clone]').forEach(o => o.remove());
  try {
    const r = await fetch(getBaseUrl() + '/api/voice-clone/list');
    const d = await r.json();
    if (d.ok && d.voices?.length) {
      d.voices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = 'clone:' + v.name;
        opt.textContent = '🎙 ' + v.name + '（克隆）';
        opt.setAttribute('data-clone', '1');
        sel.appendChild(opt);
      });
      if (editingId) {
        const p = profiles.find(x => x.id === editingId);
        if (p) sel.value = p.voice_id || 'zh-CN-XiaohanNeural';
      }
    }
  } catch(e) {}
}

async function _profileMove(id, direction) {
  const idx = profiles.findIndex(p => p.id === id);
  if (idx < 0) return;
  const newIdx = idx + direction;
  if (newIdx < 0 || newIdx >= profiles.length) return;
  [profiles[idx], profiles[newIdx]] = [profiles[newIdx], profiles[idx]];
  renderProfileList();
  try {
    await fetch(getBaseUrl() + '/api/profiles/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ order: profiles.map(p => p.id) }),
    });
  } catch(e) {}
}

async function _profileExport(id) {
  try {
    const p = profiles.find(x => x.id === id);
    const name = p?.name || id;
    const r = await fetch(getBaseUrl() + `/api/profiles/${id}/export?fmt=json`);
    if (!r.ok) throw new Error('Export failed');
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}_chat.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    if (window.ocToast) window.ocToast.success(`「${name}」对话已导出`);
  } catch(e) {
    if (window.ocToast) window.ocToast.error('导出失败: ' + e.message);
  }
}

async function activateProfile(id) {
  try {
    const r = await fetch(getBaseUrl() + `/api/profiles/${id}/activate`, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      activeId = id;
      const p = d.profile;
      if (window.ocToast) window.ocToast.success(`已切换到「${p?.name}」`);
      await loadProfiles();
      await _loadProfileHistory(d.session_id || `profile:${id}`);
      _updateVoiceBadge(p);
      if (S.voiceWs?.readyState === 1) {
        try { S.voiceWs.send(JSON.stringify({ type: 'profile_sync', profile_id: id })); } catch(_) {}
      }
    }
  } catch(e) {
    if (window.ocToast) window.ocToast.error('切换失败: ' + e.message);
  }
}

function _updateVoiceBadge(profile) {
  const badge = document.getElementById('voice-profile-badge');
  if (!badge) return;
  if (profile) {
    badge.textContent = `${profile.avatar || '👤'} ${profile.name} 的语音助手`;
    badge.style.display = '';
  } else {
    badge.style.display = 'none';
  }
}

async function _loadProfileHistory(sessionId) {
  try {
    const msgEl = document.getElementById('messages');
    const welcomeEl = document.getElementById('welcome-screen');
    if (msgEl) msgEl.innerHTML = '';
    S.messages = [];

    const r = await fetch(getBaseUrl() + `/api/history?session=${encodeURIComponent(sessionId)}&limit=50`);
    const d = await r.json();
    const msgs = d.messages || [];

    if (msgs.length === 0) {
      if (welcomeEl) welcomeEl.style.display = '';
      return;
    }

    if (welcomeEl) welcomeEl.style.display = 'none';
    for (const m of msgs) {
      const msg = { role: m.role, content: m.content };
      S.messages.push(msg);
      if (fn.appendMessage) fn.appendMessage(msg);
    }
    if (fn.scrollToBottom) fn.scrollToBottom();
  } catch(e) {
    console.warn('Failed to load profile history:', e);
  }
}

async function _profileDelete(id) {
  if (!confirm('确定删除这个成员？其对话记忆将保留。')) return;
  try {
    await fetch(getBaseUrl() + `/api/profiles/${id}`, { method: 'DELETE' });
    if (editingId === id) closeEditForm();
    await loadProfiles();
  } catch(e) {}
}

async function createFromPreset(name, env) {
  try {
    const r = await fetch(getBaseUrl() + '/api/profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset: name, environment: env }),
    });
    const d = await r.json();
    if (d.ok) {
      if (window.ocToast) window.ocToast.success(`已创建「${name}」`);
      await loadProfiles();
    }
  } catch(e) {}
}

async function loadPresets() {
  try {
    const r = await fetch(getBaseUrl() + '/api/profiles/presets');
    const d = await r.json();
    if (!d.ok) return;
    const presets = d.presets || {};

    if (ppFamilyPresets && presets.family) {
      ppFamilyPresets.innerHTML = presets.family.map(p => `
        <div class="pp-preset" data-name="${p.name}" data-env="family">
          <div class="pp-preset-icon">${p.avatar}</div>
          <div class="pp-preset-name">${p.name}</div>
          <div class="pp-preset-desc">${(p.preferences?.interests || []).join('·')}</div>
        </div>
      `).join('');
      ppFamilyPresets.querySelectorAll('.pp-preset').forEach(el => {
        el.addEventListener('click', () => createFromPreset(el.dataset.name, el.dataset.env));
      });
    }

    if (ppWorkPresets && presets.work) {
      ppWorkPresets.innerHTML = presets.work.map(p => `
        <div class="pp-preset" data-name="${p.name}" data-env="work">
          <div class="pp-preset-icon">${p.avatar}</div>
          <div class="pp-preset-name">${p.name}</div>
          <div class="pp-preset-desc">${(p.preferences?.interests || []).join('·')}</div>
        </div>
      `).join('');
      ppWorkPresets.querySelectorAll('.pp-preset').forEach(el => {
        el.addEventListener('click', () => createFromPreset(el.dataset.name, el.dataset.env));
      });
    }
  } catch(e) {}
}

function profileOpenPanel() {
  closeEditForm();
  panel.classList.add('open');
  loadPresets();
}

let _ppAudio = null;
let _ppPlaying = false;

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════

export function init() {
  // ── Sessions event listeners ──
  $id('sessions-toggle')?.addEventListener('click', () => {
    const p = $id('sessions-panel');
    p.classList.contains('open') ? sessClosePanel() : sessOpenPanel();
  });
  $id('sess-close')?.addEventListener('click', sessClosePanel);
  $id('sess-new')?.addEventListener('click', newSession);

  if (window.matchMedia('(min-width:768px) and (orientation:landscape)').matches) {
    sessOpenPanel();
  }

  // ── Profile DOM refs ──
  switcher = document.getElementById('profile-switcher');
  panel = document.getElementById('profile-panel');
  ppList = document.getElementById('pp-list');
  ppClose = document.getElementById('pp-close');
  ppFamilyPresets = document.getElementById('pp-family-presets');
  ppWorkPresets = document.getElementById('pp-work-presets');
  ppEdit = document.getElementById('pp-edit');
  ppPresetsTitle = document.getElementById('pp-presets-title');
  if (!switcher || !panel) return;

  // ── Window assignments for inline onclick handlers ──
  window._profileMove = _profileMove;
  window._profileExport = _profileExport;
  window._profileEdit = openEditForm;
  window._profileActivate = activateProfile;
  window._profileDelete = _profileDelete;

  // ── Profile edit event listeners ──
  document.getElementById('pp-edit-close')?.addEventListener('click', closeEditForm);
  document.getElementById('pp-edit-cancel-btn')?.addEventListener('click', closeEditForm);
  document.getElementById('pp-edit-save-btn')?.addEventListener('click', saveEdit);

  // ── Voice preview in profile edit ──
  document.getElementById('pp-edit-voice-preview')?.addEventListener('click', async () => {
    const btn = document.getElementById('pp-edit-voice-preview');
    const voiceId = document.getElementById('pp-edit-voice')?.value;
    if (_ppPlaying) {
      if (_ppAudio) { _ppAudio.pause(); _ppAudio.currentTime = 0; }
      _ppPlaying = false;
      btn.textContent = '🔊';
      btn.classList.remove('playing');
      return;
    }
    _ppPlaying = true;
    btn.textContent = '⏹';
    btn.classList.add('playing');
    try {
      const r = await fetch(getBaseUrl() + '/api/tts/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: '你好，很高兴为你服务。这是语音试听。', voice: voiceId }),
      });
      if (!r.ok) throw new Error('TTS error');
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      _ppAudio = new Audio(url);
      _ppAudio.onended = () => { _ppPlaying = false; btn.textContent = '🔊'; btn.classList.remove('playing'); URL.revokeObjectURL(url); };
      _ppAudio.onerror = () => { _ppPlaying = false; btn.textContent = '🔊'; btn.classList.remove('playing'); };
      await _ppAudio.play();
    } catch(e) {
      _ppPlaying = false;
      btn.textContent = '🔊';
      btn.classList.remove('playing');
      if (window.ocToast) window.ocToast.error('试听失败: ' + e.message);
    }
  });

  ppClose?.addEventListener('click', () => { closeEditForm(); panel.classList.remove('open'); });

  // ── Register in fn registry ──
  fn.loadProfiles = loadProfiles;

  // ── Initial load ──
  setTimeout(loadProfiles, 2000);
}
