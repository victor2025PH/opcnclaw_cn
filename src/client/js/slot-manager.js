/**
 * Session Slot Manager — 前端多会话槽位管理
 *
 * 融合 tryvoice 的 multi-bot slots 与 52AI 的 AgentTeam 体系。
 * 负责：槽位 CRUD、Tab 渲染、active 切换、语音/文字分流、TTS 按槽打断。
 */

import { S, fn, dom, t, getBaseUrl, bus } from '/js/state.js';
import { petSetVisualState } from '/js/pet-bridge.js';

let _slots = [];
let _teamSseDedupe = new Map(); // slot_id -> completed_at
let _activeSlotId = 'chat-default';
let _tabContainer = null;
let _slotIndicator = null;

function _initTeamSseBridge() {
  if (typeof EventSource === 'undefined' || window._ocTeamSse) return;
  try {
    const es = new EventSource(getBaseUrl() + '/api/events/stream');
    window._ocTeamSse = es;
    es.addEventListener('team_complete_card', (e) => {
      try {
        const ev = JSON.parse(e.data);
        const payload = ev.data || {};
        bus.emit('team_complete_card', { type: 'team_complete_card', ...payload });
      } catch (err) { console.debug('[SSE] team_complete_card', err); }
    });
    es.addEventListener('team_progress', (e) => {
      try {
        const ev = JSON.parse(e.data);
        bus.emit('team_progress', ev.data || {});
      } catch (err) { console.debug('[SSE] team_progress', err); }
    });
  } catch (_) { /* EventSource 不可用 */ }
}

/** 团队结果朗读：走 /api/tts 流式，不依赖语音 WebSocket */
async function _speakTeamResultHttp(fullText, slotIdForTts) {
  if (!fullText || localStorage.getItem('oc_team_auto_speak') === '0') return;
  if (localStorage.getItem('oc_tts_muted') === '1') return;
  const text = String(fullText).replace(/\s+/g, ' ').trim();
  if (text.length < 2) return;
  const chunkSize = 480;
  const chunks = [];
  for (let i = 0; i < text.length; i += chunkSize) {
    chunks.push(text.slice(i, i + chunkSize));
  }
  const headers = { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' };
  const sid = slotIdForTts || '';
  petSetVisualState?.('speaking');
  try {
    for (const piece of chunks) {
      const resp = await fetch(`${getBaseUrl()}/api/tts`, {
        method: 'POST',
        headers,
        body: JSON.stringify(sid ? { text: piece, slot_id: sid } : { text: piece }),
      });
      if (!resp.ok) continue;
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const data = trimmed.slice(5).trim();
          if (data === '[DONE]') continue;
          try {
            const parsed = JSON.parse(data);
            if (parsed.audio && fn.queueVoiceAudio) {
              fn.queueVoiceAudio(
                parsed.audio,
                parsed.sample_rate || 24000,
                parsed.format || 'pcm',
              );
            }
          } catch (_) { /* ignore */ }
        }
      }
    }
  } catch (e) {
    console.warn('team HTTP TTS', e);
  } finally {
    petSetVisualState?.('idle');
  }
}

export function initSlotManager() {
  _injectTabUI();
  _injectStyles();
  _loadSlots();
  _initTeamSseBridge();
  bus.on('voice_transcript_ready', _onVoiceTranscript);
  bus.on('team_progress', _onTeamProgress);
  bus.on('team_complete_card', _onTeamCompleteCard);
  setInterval(_loadSlots, 15000);

  fn.handleServerSlotSwitch = handleServerSlotSwitch;
  /** 主对话轮询团队完成卡等场景：与槽位团队共用分段 /api/tts 朗读 */
  fn.speakTeamTts = (text, slotId) => {
    void _speakTeamResultHttp(String(text || '').trim(), slotId || '');
  };

  if (!localStorage.getItem('oc_slot_intro_done')) {
    setTimeout(() => {
      const btn = document.querySelector('.slot-add-btn');
      if (btn) { btn.classList.add('pulse'); }
      localStorage.setItem('oc_slot_intro_done', '1');
    }, 3000);
  }
}

async function _loadSlots() {
  try {
    const r = await fetch(`${getBaseUrl()}/api/slots`, {
      headers: { 'X-API-Token': S.token || '' },
    });
    const d = await r.json();
    if (d.ok) {
      _slots = d.slots || [];
      _activeSlotId = d.active || 'chat-default';
      _renderTabs();
      _updateIndicator();
    }
  } catch (e) { /* silent */ }
}

// ═══ 公共 API ═══

export function getActiveSlotId() {
  return _activeSlotId;
}

export function getActiveSlot() {
  return _slots.find(s => s.slot_id === _activeSlotId) || null;
}

export function getSlotById(slotId) {
  return _slots.find(s => s.slot_id === slotId) || null;
}

/** P0: 从槽位 label（如「🧘 唐僧」）解析头像与显示名 */
export function metaFromSlot(slot) {
  if (!slot) return { slot_id: '', avatar: '', display_name: '' };
  const sid = slot.slot_id || '';
  const label = (slot.label || '').trim();
  if (!label) return { slot_id: sid, avatar: '🤖', display_name: slot.bound_id || '' };
  const sp = label.indexOf(' ');
  if (sp === -1) return { slot_id: sid, avatar: label, display_name: label };
  return {
    slot_id: sid,
    avatar: label.slice(0, sp).trim(),
    display_name: label.slice(sp + 1).trim(),
  };
}

const _slotMessageCache = {};

export async function switchSlot(slotId) {
  try {
    const r = await fetch(`${getBaseUrl()}/api/slots/switch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
      body: JSON.stringify({ slot_id: slotId }),
    });
    const d = await r.json();
    if (d.ok) {
      _saveCurrentMessages();
      _activeSlotId = slotId;
      await _restoreMessages(slotId);
      _renderTabs();
      _updateIndicator();
      _updatePlaceholder();
      _syncVoiceWsSlot();
      bus.emit('slot_changed', { slot_id: slotId, slot: d.slot });
    }
  } catch (e) { console.warn('switchSlot error:', e); }
}

function _saveCurrentMessages() {
  const msgArea = document.getElementById('messages');
  if (msgArea && _activeSlotId) {
    _slotMessageCache[_activeSlotId] = {
      html: msgArea.innerHTML,
      messages: [...S.messages],
    };
  }
}

async function _restoreMessages(slotId) {
  const msgArea = document.getElementById('messages');
  if (!msgArea) return;
  const cached = _slotMessageCache[slotId];
  if (cached) {
    msgArea.innerHTML = cached.html;
    S.messages = [...cached.messages];
    msgArea.scrollTop = msgArea.scrollHeight;
    return;
  }

  msgArea.innerHTML = '';
  S.messages = [];

  const slotInfo = _slots.find(s => s.slot_id === slotId);
  if (slotInfo && slotInfo.history_count > 0 && slotInfo.slot_type !== 'chat') {
    try {
      const r = await fetch(`${getBaseUrl()}/api/slots/${slotId}/history`, {
        headers: { 'X-API-Token': S.token || '' },
      });
      const d = await r.json();
      if (d.ok && d.history?.length) {
        for (const msg of d.history) {
          S.messages.push(msg);
          fn.appendMessage?.(msg);
        }
      }
    } catch {}
  }
  msgArea.scrollTop = msgArea.scrollHeight;
}

export async function createSlot(slotType, label, boundId) {
  try {
    _saveCurrentMessages();
    const r = await fetch(`${getBaseUrl()}/api/slots`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
      body: JSON.stringify({ slot_type: slotType, label, bound_id: boundId || '', activate: true }),
    });
    const d = await r.json();
    if (d.ok) {
      await _loadSlots();
      await _restoreMessages(_activeSlotId);
      _updateIndicator();
      _updatePlaceholder();
      _syncVoiceWsSlot();
      return d.slot;
    }
  } catch (e) { console.warn('createSlot error:', e); }
  return null;
}

export async function handleServerSlotSwitch(slotId, roleId, displayName, avatar) {
  if (fn.stopSpeaking) fn.stopSpeaking({ skipPet: true });
  if (typeof S !== 'undefined' && S.audioQueue) S.audioQueue = [];
  await _loadSlots();
  const found = _slots.find(s => s.slot_id === slotId);
  if (found) {
    _activeSlotId = slotId;
    _updateIndicator();
    _updatePlaceholder();
  }
  fn.showGestureToast?.({
    icon: avatar || '🤖',
    label: `${displayName || roleId} 已就位`,
    color: '#7c6aef',
  });
}

export async function removeSlot(slotId) {
  try {
    await fetch(`${getBaseUrl()}/api/slots/${slotId}`, {
      method: 'DELETE',
      headers: { 'X-API-Token': S.token || '' },
    });
    await _loadSlots();
  } catch (e) { console.warn('removeSlot error:', e); }
}

export function interruptSlotTTS() {
  const slot = getActiveSlot();
  if (slot && fn.stopSpeaking) {
    fn.stopSpeaking();
  }
}

// ═══ 语音 WebSocket 槽位同步 ═══

function _syncVoiceWsSlot() {
  if (S.voiceWs && S.voiceWs.readyState === 1) {
    S.voiceWs.send(JSON.stringify({ type: 'set_slot', slot_id: _activeSlotId }));
  }
}

// ═══ 事件处理 ═══

const _VOICE_CMD_PATTERNS = [
  { re: /^(切换到?|打开|去)(.+?)(槽位|会话|对话)?$/,   action: 'switch' },
  { re: /^(回到|返回)(主?对话|聊天|默认)$/,            action: 'home'   },
  { re: /^(新建|创建|打开)(一个?)?(agent|智能体|助手)/i, action: 'new_agent' },
  { re: /^(新建|创建|打开)(一个?)?团队/,               action: 'new_team' },
  { re: /^(关闭|删除)(当前|这个)(槽位|会话|对话)?$/,     action: 'close' },
  { re: /^让(.+?)(帮我?|来)(.+)$/,                    action: 'delegate' },
  { re: /^(问问?|问一下|请教)(.+?)[\s,，](.+)$/,       action: 'delegate' },
];

const _ROLE_NAME_MAP = {
  '唐僧': 'tangseng', '玄奘': 'tangseng', '师父': 'tangseng', '师傅': 'tangseng',
  '悟空': 'wukong', '孙悟空': 'wukong', '大圣': 'wukong', '猴哥': 'wukong', '猴子': 'wukong',
  '八戒': 'bajie', '猪八戒': 'bajie', '天蓬': 'bajie', '老猪': 'bajie', '猪哥': 'bajie',
  '悟净': 'wujing', '沙悟净': 'wujing', '沙僧': 'wujing', '沙师弟': 'wujing',
  '小白龙': 'bailong', '白龙': 'bailong', '白龙马': 'bailong',
  '西游团队': '_team_xyj', '取经团': '_team_xyj', '西游': '_team_xyj',
};
const _ROLE_AVATARS = {
  tangseng: '🧘', wukong: '🐵', bajie: '🐷', wujing: '🏔️', bailong: '🐉',
};
const _ROLE_DISPLAY = {
  tangseng: '唐僧', wukong: '孙悟空', bajie: '猪八戒', wujing: '沙悟净', bailong: '小白龙',
};

function _tryVoiceCommand(text) {
  const t = text.trim();
  for (const pat of _VOICE_CMD_PATTERNS) {
    const m = t.match(pat.re);
    if (!m) continue;

    if (pat.action === 'home') {
      switchSlot('chat-default');
      fn.showGestureToast?.({ icon: '💬', label: '已切换到主对话', color: '#7c6aef' });
      return true;
    }
    if (pat.action === 'switch') {
      const target = m[2].trim();
      const found = _slots.find(s =>
        s.label.includes(target) || s.bound_id.includes(target)
      );
      if (found) {
        switchSlot(found.slot_id);
        fn.showGestureToast?.({ icon: '🔀', label: `已切换到 ${found.label}`, color: '#7c6aef' });
        return true;
      }
    }
    if (pat.action === 'new_agent') {
      createSlot('agent', 'Agent', '');
      fn.showGestureToast?.({ icon: '🤖', label: '新建 Agent 会话', color: '#7c6aef' });
      return true;
    }
    if (pat.action === 'new_team') {
      createSlot('team', '团队: default', 'default');
      fn.showGestureToast?.({ icon: '👥', label: '新建团队任务', color: '#7c6aef' });
      return true;
    }
    if (pat.action === 'close') {
      if (_activeSlotId !== 'chat-default') {
        removeSlot(_activeSlotId);
        fn.showGestureToast?.({ icon: '🗑️', label: '已关闭当前会话', color: '#ef4444' });
        return true;
      }
    }
    if (pat.action === 'delegate') {
      const agentName = m[1]?.trim() || m[2]?.trim();
      const taskText = m[3]?.trim() || m[2]?.trim();
      if (agentName && taskText) {
        _delegateToAgent(agentName, taskText);
        return true;
      }
    }
  }

  // 直呼名字：说角色名自动切换/创建，名字+任务直接发送
  const matched = _matchRoleName(t);
  if (matched) {
    _handleNameCall(matched.roleId, matched.remaining);
    return true;
  }

  return false;
}

function _matchRoleName(text) {
  const separators = /[,，.。!！?？\s]/;
  for (const [name, roleId] of Object.entries(_ROLE_NAME_MAP)) {
    if (text === name) return { roleId, remaining: '' };
    if (text.startsWith(name)) {
      const after = text.slice(name.length);
      if (separators.test(after[0])) {
        return { roleId, remaining: after.replace(separators, '').trim() };
      }
      if (after.length > 0) return { roleId, remaining: after.trim() };
    }
  }
  // 动态匹配已加载的角色
  if (_cachedRoles) {
    for (const r of _cachedRoles) {
      if (text === r.name || text.startsWith(r.name)) {
        const rest = text.slice(r.name.length).replace(/^[,，.。\s]+/, '').trim();
        return { roleId: r.id, remaining: rest };
      }
    }
  }
  return null;
}

async function _handleNameCall(roleId, taskText) {
  // 西游团队特殊处理
  if (roleId === '_team_xyj') {
    const existing = _slots.find(s => s.slot_type === 'team' && s.bound_id === 'xyj');
    if (existing) {
      await switchSlot(existing.slot_id);
      fn.showGestureToast?.({ icon: '🏔️', label: '已切换到西游取经团', color: '#7c6aef' });
    } else {
      await createSlot('team', '团队: xyj', 'xyj');
      fn.showGestureToast?.({ icon: '🏔️', label: '西游取经团已集结', color: '#7c6aef' });
    }
    if (taskText) {
      setTimeout(() => _dispatchTeamVoice(taskText), 500);
    }
    return;
  }

  const displayName = _ROLE_DISPLAY[roleId] || roleId;
  const avatar = _ROLE_AVATARS[roleId] || '🤖';

  // 查找已有槽位
  const existing = _slots.find(s =>
    s.bound_id === roleId ||
    s.label.includes(displayName) ||
    s.slot_id.includes(roleId)
  );

  if (existing) {
    await switchSlot(existing.slot_id);
    fn.showGestureToast?.({ icon: avatar, label: `${displayName} 在此`, color: '#7c6aef' });
  } else {
    await createSlot('agent', `${avatar} ${displayName}`, roleId);
    fn.showGestureToast?.({ icon: avatar, label: `${displayName} 已就位`, color: '#22c55e' });
  }

  if (taskText) {
    setTimeout(() => sendAgentMessage(taskText), 500);
  }
}

async function _delegateToAgent(agentName, taskText) {
  const existing = _slots.find(s =>
    s.slot_type === 'agent' && (s.label.includes(agentName) || s.bound_id.includes(agentName))
  );

  if (existing) {
    await switchSlot(existing.slot_id);
    fn.showGestureToast?.({ icon: '🤖', label: `已切换到 ${existing.label}`, color: '#7c6aef' });
    await sendAgentMessage(taskText, existing.slot_id);
    return;
  }

  let roleId = '';
  if (!_cachedRoles) {
    try {
      const r = await fetch(`${getBaseUrl()}/api/slots/available-roles`, {
        headers: { 'X-API-Token': S.token || '' },
      });
      const d = await r.json();
      _cachedRoles = d.roles || [];
    } catch { _cachedRoles = []; }
  }
  const matchedRole = _cachedRoles.find(r =>
    r.name.includes(agentName) || r.id.includes(agentName)
  );
  if (matchedRole) roleId = matchedRole.id;

  const label = matchedRole ? `${matchedRole.avatar} ${matchedRole.name}` : `🤖 ${agentName}`;
  const newSlot = await createSlot('agent', label, roleId);
  if (newSlot) {
    fn.showGestureToast?.({ icon: '🤖', label: `${label} 已就位`, color: '#7c6aef' });
    await sendAgentMessage(taskText, newSlot.slot_id);
  }
}

function _onVoiceTranscript(data) {
  if (_tryVoiceCommand(data.text)) return;

  const slot = getActiveSlot();
  if (!slot) return;
  if (slot.slot_type === 'team') {
    _dispatchTeamVoice(data.text);
  } else if (slot.slot_type === 'agent') {
    sendAgentMessage(data.text);
  }
}

async function _dispatchTeamVoice(text) {
  try {
    const r = await fetch(`${getBaseUrl()}/api/slots/team-voice`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
      body: JSON.stringify({ text, slot_id: _activeSlotId }),
    });
    const d = await r.json();
    if (d.ok && d.message) {
      fn.appendMessage?.('ai', `🎯 ${d.message}`);
      if (fn.showGestureToast) {
        fn.showGestureToast({ icon: '👥', label: d.message.substring(0, 30), color: '#7c6aef' });
      }
    }
  } catch (e) { console.warn('team voice dispatch error:', e); }
}

function _onTeamProgress(data) {
  if (!data.slot_id) return;
  const slot = _slots.find(s => s.slot_id === data.slot_id);
  if (!slot) return;

  const tab = document.querySelector(`.slot-tab[data-slot="${data.slot_id}"]`);
  if (tab) {
    const badge = tab.querySelector('.slot-badge');
    if (badge) {
      badge.textContent = data.stage === 'done' ? '✅' : '⏳';
      badge.className = `slot-badge ${data.stage === 'done' ? 'done' : 'working'}`;
    }
  }

  if (data.slot_id === _activeSlotId && data.detail) {
    _appendTeamProgressLine(data);
  }
}

function _appendTeamProgressLine(data) {
  const msgArea = document.getElementById('messages');
  if (!msgArea) return;
  let timeline = msgArea.querySelector('.team-timeline-live');
  if (!timeline) {
    timeline = document.createElement('div');
    timeline.className = 'team-timeline-live';
    timeline.innerHTML = `<div class="ttl-header">👥 ${data.team_name || '团队'} 执行中</div><div class="ttl-steps"></div>`;
    msgArea.appendChild(timeline);
  }
  const steps = timeline.querySelector('.ttl-steps');
  const step = document.createElement('div');
  const isDone = data.stage === 'done' || data.stage === 'agent_done';
  const isAgent = data.stage === 'agent_working' || data.stage === 'agent_done';
  step.className = `ttl-step ${isDone ? 'done' : ''} ${isAgent ? 'agent' : ''}`;

  const avatar = data.agent_avatar || '';
  const name = data.agent_name || '';
  const prefix = avatar ? `<span class="ttl-avatar">${avatar}</span>` : '<span class="ttl-dot"></span>';
  const nameTag = name ? `<span class="ttl-name">${name}</span>` : '';

  step.innerHTML = `${prefix}${nameTag}<span class="ttl-text">${(data.detail || '').substring(0, 60)}</span>`;
  steps.appendChild(step);
  msgArea.scrollTop = msgArea.scrollHeight;
}

function _onTeamCompleteCard(data) {
  if (!data.slot_id) return;
  const ca = data.completed_at;
  if (ca != null) {
    const prev = _teamSseDedupe.get(data.slot_id);
    if (prev === ca) return;
    _teamSseDedupe.set(data.slot_id, ca);
    if (_teamSseDedupe.size > 32) _teamSseDedupe.clear();
  }
  if (data.slot_id !== _activeSlotId) {
    const tab = document.querySelector(`.slot-tab[data-slot="${data.slot_id}"]`);
    if (tab) tab.classList.add('has-result');
    // 切到其他槽时仍朗读完成摘要（避免「团队跑完却没声音」）
    if (data.tts_text) {
      void _speakTeamResultHttp(data.tts_text, data.slot_id);
    }
    return;
  }
  _renderCompleteCard(data);
  if (data.tts_text) {
    void _speakTeamResultHttp(data.tts_text, data.slot_id);
  }
}

function _renderCompleteCard(data) {
  const msgArea = document.getElementById('messages');
  if (!msgArea) return;

  const live = msgArea.querySelector('.team-timeline-live');
  if (live) live.remove();

  const card = document.createElement('div');
  card.className = `team-complete-card ${data.error ? 'error' : ''}`;
  const agentsHtml = (data.agents || []).map(a =>
    `<div class="tcc-agent ${a.status === 'done' ? 'done' : ''}">
      <span class="tcc-avatar">${a.avatar}</span>
      <div class="tcc-detail">
        <div class="tcc-name">${a.name}</div>
        <div class="tcc-task">${a.task}</div>
        ${a.result_preview ? `<div class="tcc-preview">${a.result_preview}</div>` : ''}
      </div>
    </div>`
  ).join('');

  const mins = Math.floor((data.elapsed_seconds || 0) / 60);
  const secs = (data.elapsed_seconds || 0) % 60;
  const timeStr = mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`;

  card.innerHTML = `
    <div class="tcc-header">
      <span class="tcc-icon">${data.error ? '❌' : '✅'}</span>
      <span class="tcc-title">${data.team_name || '团队'} ${data.error ? '执行失败' : '任务完成'}</span>
      <span class="tcc-time">${timeStr} · ${data.task_count || 0}个子任务</span>
    </div>
    <div class="tcc-task-desc">📋 ${data.task || ''}</div>
    <div class="tcc-agents">${agentsHtml}</div>
    ${data.result_summary ? `<div class="tcc-summary">${data.result_summary}</div>` : ''}
    <div class="tcc-actions">
      <button class="tcc-btn" onclick="window.__slotManager.viewTeamResult('${data.team_id}')">查看详细报告</button>
      <button class="tcc-btn tcc-fwd" data-fwd-slot="${data.slot_id}">转发到...</button>
      <button class="tcc-btn tcc-chain" data-chain-slot="${data.slot_id}">🔗 串联团队</button>
    </div>
  `;
  msgArea.appendChild(card);
  msgArea.scrollTop = msgArea.scrollHeight;

  const fwdBtn = card.querySelector('.tcc-fwd');
  if (fwdBtn) {
    const summary = data.result_summary || '';
    fwdBtn.addEventListener('click', () => showForwardPicker(data.slot_id, summary));
  }

  const chainBtn = card.querySelector('.tcc-chain');
  if (chainBtn) {
    chainBtn.addEventListener('click', () => _showChainPicker(data.slot_id));
  }
}

export async function showForwardPicker(fromSlotId, text) {
  const targets = _slots.filter(s => s.slot_id !== fromSlotId);
  if (!targets.length) {
    fn.showGestureToast?.({ icon: '⚠️', label: '没有其他槽位可转发', color: '#f59e0b' });
    return;
  }

  const existing = document.getElementById('forward-picker');
  if (existing) { existing.remove(); return; }

  const picker = document.createElement('div');
  picker.id = 'forward-picker';
  picker.className = 'forward-picker';
  picker.innerHTML = `
    <div class="fp-title">转发到...</div>
    ${targets.map(s => {
      const icon = s.slot_type === 'team' ? '👥' : s.slot_type === 'agent' ? '🤖' : '💬';
      return `<div class="fp-item" data-to="${s.slot_id}">${icon} ${s.label}</div>`;
    }).join('')}
  `;

  picker.querySelectorAll('.fp-item').forEach(item => {
    item.addEventListener('click', async () => {
      picker.remove();
      const toSlotId = item.dataset.to;
      try {
        const r = await fetch(`${getBaseUrl()}/api/slots/forward`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
          body: JSON.stringify({ from_slot_id: fromSlotId, to_slot_id: toSlotId, text, auto_reply: true }),
        });
        const d = await r.json();
        if (d.ok) {
          fn.showGestureToast?.({ icon: '📤', label: d.message, color: '#22c55e' });
        }
      } catch (e) { console.warn('forward error:', e); }
    });
  });

  document.body.appendChild(picker);
  setTimeout(() => {
    document.addEventListener('click', function _close(e) {
      if (!picker.contains(e.target)) {
        picker.remove();
        document.removeEventListener('click', _close);
      }
    });
  }, 50);
}

async function _showChainPicker(sourceSlotId) {
  const existing = document.getElementById('chain-picker');
  if (existing) { existing.remove(); return; }

  const presets = [
    { id: 'xyj', label: '🏔️ 西游取经团', desc: '唐僧领队 · 悟空技术 · 八戒营销 · 悟净数据 · 白龙客服' },
    { id: 'marketing', label: '📣 营销获客团队', desc: '基于结果制定营销策略' },
    { id: 'software', label: '💻 技术研发团队', desc: '技术实现方案' },
    { id: 'service_center', label: '🎧 客服支持团队', desc: '客户沟通话术' },
    { id: 'default', label: '👥 全能团队', desc: '通用任务处理' },
  ];

  const picker = document.createElement('div');
  picker.id = 'chain-picker';
  picker.className = 'forward-picker';
  picker.innerHTML = `
    <div class="fp-title">🔗 选择下游团队</div>
    <input class="si-chain-input" placeholder="附加指令（可选）..." />
    ${presets.map(p => `<div class="fp-item" data-preset="${p.id}">
      <div>${p.label}</div>
      <div style="font-size:10px;color:var(--text-muted,#666)">${p.desc}</div>
    </div>`).join('')}
  `;

  picker.querySelectorAll('.fp-item').forEach(item => {
    item.addEventListener('click', async () => {
      const preset = item.dataset.preset;
      const extra = picker.querySelector('.si-chain-input')?.value || '';
      picker.remove();
      try {
        const r = await fetch(`${getBaseUrl()}/api/slots/pipeline`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
          body: JSON.stringify({ source_slot_id: sourceSlotId, target_preset: preset, extra_instruction: extra }),
        });
        const d = await r.json();
        if (d.ok) {
          fn.showGestureToast?.({ icon: '🔗', label: d.message || '流水线已启动', color: '#22c55e' });
          if (d.slot_id) {
            await _loadSlots();
            await switchSlot(d.slot_id);
          }
        } else {
          fn.showGestureToast?.({ icon: '⚠️', label: d.error || '串联失败', color: '#ef4444' });
        }
      } catch (e) { console.warn('chain error:', e); }
    });
  });

  document.body.appendChild(picker);
  setTimeout(() => {
    document.addEventListener('click', function _close(e) {
      if (!picker.contains(e.target)) {
        picker.remove();
        document.removeEventListener('click', _close);
      }
    });
  }, 50);
}

// ═══ Agent 流式对话 ═══

const _TOOL_ICONS = {
  web_search: '🔍', desktop_screenshot: '📸', desktop_click: '🖱️',
  desktop_type: '⌨️', open_application: '🚀', read_screen: '👁️',
};

export async function sendAgentMessage(text, slotId) {
  const sid = slotId || _activeSlotId;
  const slot = _slots.find(s => s.slot_id === sid);
  if (!slot || slot.slot_type !== 'agent') return;

  fn.appendMessage?.({ role: 'user', content: text });
  const _meta = metaFromSlot(slot);
  const aiMsg = fn.appendMessage?.({ role: 'assistant', content: '', ..._meta }, true);
  const msgArea = document.getElementById('messages');

  let _toolCard = null;
  let _renderTimer = null;

  try {
    const r = await fetch(`${getBaseUrl()}/api/slots/agent-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
      body: JSON.stringify({ text, slot_id: sid }),
    });

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let fullText = '';

    const _throttledRender = () => {
      if (_renderTimer) return;
      _renderTimer = requestAnimationFrame(() => {
        _renderTimer = null;
        if (aiMsg && fn.updateStreamingEl) {
          fn.updateStreamingEl(aiMsg, fullText);
        }
      });
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const msg = JSON.parse(line.slice(6));
          if (msg.type === 'tool_start') {
            _toolCard = _renderToolCard(msg, msgArea);
          } else if (msg.type === 'tool_end') {
            _finishToolCard(_toolCard, msg);
            _toolCard = null;
          } else if (msg.type === 'chunk') {
            fullText += msg.text;
            _throttledRender();
          }
        } catch {}
      }
    }

    if (aiMsg && fn.finalizeStreamingEl) {
      fn.finalizeStreamingEl(aiMsg, fullText);
    }
    if (msgArea) msgArea.scrollTop = msgArea.scrollHeight;
  } catch (e) {
    console.warn('Agent chat error:', e);
    if (aiMsg && fn.finalizeStreamingEl) {
      fn.finalizeStreamingEl(aiMsg, '网络错误，请重试');
    }
  }
}

function _renderToolCard(data, container) {
  if (!container) return null;
  const card = document.createElement('div');
  card.className = 'tool-call-card working';
  const icon = _TOOL_ICONS[data.name] || '🔧';
  const argsStr = data.args ? Object.entries(data.args).map(([k,v]) =>
    `<span class="tc-arg"><span class="tc-key">${k}:</span> ${String(v).substring(0, 60)}</span>`
  ).join('') : '';
  card.innerHTML = `
    <div class="tc-header">
      <span class="tc-icon">${icon}</span>
      <span class="tc-name">${data.name}</span>
      <span class="tc-status"><span class="tc-spinner"></span>执行中</span>
    </div>
    ${argsStr ? `<div class="tc-args">${argsStr}</div>` : ''}
    <div class="tc-result"></div>
  `;
  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
  return card;
}

function _finishToolCard(card, data) {
  if (!card) return;
  card.classList.remove('working');
  card.classList.add('done');
  const status = card.querySelector('.tc-status');
  if (status) status.innerHTML = '✅ 完成';
  if (data.preview) {
    const res = card.querySelector('.tc-result');
    if (res) res.textContent = data.preview;
  }
}

export async function sendTeamMessage(text) {
  fn.appendMessage?.({ role: 'user', content: text });
  await _dispatchTeamVoice(text);
}

export function viewTeamResult(teamId) {
  window.open(`/report/${teamId}`, '_blank');
}

// ═══ Tab UI ═══

function _injectTabUI() {
  _tabContainer = document.createElement('div');
  _tabContainer.id = 'slot-tabs';
  _tabContainer.className = 'slot-tabs';

  const addBtn = document.createElement('button');
  addBtn.className = 'slot-add-btn';
  addBtn.textContent = '+';
  addBtn.title = '新建会话槽位';
  addBtn.onclick = _showCreateMenu;

  _tabContainer.appendChild(addBtn);

  _slotIndicator = document.createElement('div');
  _slotIndicator.id = 'slot-indicator';
  _slotIndicator.className = 'slot-indicator';

  const chatPage = document.getElementById('chat-page');
  const chatArea = document.querySelector('.chat-main-col') ||
                   document.querySelector('.chat-container') ||
                   document.getElementById('messages')?.parentElement;

  if (chatPage) {
    chatPage.parentElement.insertBefore(_tabContainer, chatPage);
  } else if (chatArea) {
    chatArea.prepend(_tabContainer);
  }

  if (chatArea) {
    const inputArea = chatArea.querySelector('.input-area') ||
                      chatArea.querySelector('.chat-input-wrap') ||
                      chatArea.querySelector('footer');
    if (inputArea) {
      inputArea.parentElement.insertBefore(_slotIndicator, inputArea);
    }
  }

  _hookVisibility();
}

function _hookVisibility() {
  if (!_tabContainer) return;
  const bottomTabs = document.querySelectorAll('.bottom-tabs [data-tab]');
  bottomTabs.forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      _tabContainer.style.display = (tab === 'chat') ? '' : 'none';
    });
  });
}

let _dragSlotId = null;

function _renderTabs() {
  if (!_tabContainer) return;
  const addBtn = _tabContainer.querySelector('.slot-add-btn');
  _tabContainer.innerHTML = '';

  for (const slot of _slots) {
    const tab = document.createElement('div');
    tab.className = `slot-tab ${slot.slot_id === _activeSlotId ? 'active' : ''}`;
    tab.dataset.slot = slot.slot_id;
    tab.draggable = true;

    const icon = slot.slot_type === 'team' ? '👥'
               : slot.slot_type === 'agent' ? '🤖'
               : '💬';
    const stateIcon = slot.state === 'executing' ? '⏳'
                    : slot.state === 'speaking' ? '🔊'
                    : slot.state === 'thinking' ? '💭'
                    : slot.state === 'listening' ? '🎤'
                    : '';

    tab.innerHTML = `
      <span class="slot-icon">${icon}</span>
      <span class="slot-label">${slot.label || slot.slot_type}</span>
      ${stateIcon ? `<span class="slot-badge working">${stateIcon}</span>` : ''}
      ${slot.slot_id !== 'chat-default' ? `<button class="slot-close" data-close="${slot.slot_id}">×</button>` : ''}
    `;

    let _tabClickTimer = null;
    const _onTabTap = (e) => {
      const tgt = e.target || e.srcElement;
      if (tgt && tgt.classList && tgt.classList.contains('slot-close')) {
        removeSlot(tgt.dataset.close);
        return;
      }
      if (slot.slot_id === _activeSlotId) return;
      if (_tabClickTimer) clearTimeout(_tabClickTimer);
      _tabClickTimer = setTimeout(() => { _tabClickTimer = null; switchSlot(slot.slot_id); }, 100);
    };
    tab.addEventListener('click', _onTabTap);
    tab.addEventListener('touchend', (e) => { e.preventDefault(); _onTabTap(e); }, { passive: false });

    tab.addEventListener('dblclick', (e) => {
      e.preventDefault();
      if (_tabClickTimer) { clearTimeout(_tabClickTimer); _tabClickTimer = null; }
      _startRename(tab, slot);
    });

    tab.addEventListener('dragstart', (e) => {
      _dragSlotId = slot.slot_id;
      tab.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    tab.addEventListener('dragend', () => {
      tab.classList.remove('dragging');
      _dragSlotId = null;
    });
    tab.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      tab.classList.add('drag-over');
    });
    tab.addEventListener('dragleave', () => tab.classList.remove('drag-over'));
    tab.addEventListener('drop', (e) => {
      e.preventDefault();
      tab.classList.remove('drag-over');
      if (_dragSlotId && _dragSlotId !== slot.slot_id) {
        _reorderSlots(_dragSlotId, slot.slot_id);
      }
    });

    _tabContainer.appendChild(tab);
  }

  if (addBtn) _tabContainer.appendChild(addBtn);
}

function _startRename(tabEl, slot) {
  const labelEl = tabEl.querySelector('.slot-label');
  if (!labelEl) return;
  const input = document.createElement('input');
  input.className = 'slot-rename-input';
  input.value = slot.label || '';
  input.maxLength = 20;

  const finish = async () => {
    const newLabel = input.value.trim();
    if (newLabel && newLabel !== slot.label) {
      try {
        await fetch(`${getBaseUrl()}/api/slots/${slot.slot_id}/config`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
          body: JSON.stringify({ label: newLabel }),
        });
        slot.label = newLabel;
      } catch {}
    }
    labelEl.textContent = newLabel || slot.label;
    labelEl.style.display = '';
    input.remove();
  };

  input.addEventListener('blur', finish);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') { input.value = slot.label; input.blur(); }
  });

  labelEl.style.display = 'none';
  tabEl.insertBefore(input, labelEl.nextSibling);
  input.focus();
  input.select();
}

function _reorderSlots(fromId, toId) {
  const fromIdx = _slots.findIndex(s => s.slot_id === fromId);
  const toIdx = _slots.findIndex(s => s.slot_id === toId);
  if (fromIdx < 0 || toIdx < 0) return;
  const [item] = _slots.splice(fromIdx, 1);
  _slots.splice(toIdx, 0, item);
  _renderTabs();
}

const _AVAILABLE_MODELS = [
  { id: '', label: '默认模型' },
  { id: 'deepseek-chat', label: 'DeepSeek Chat' },
  { id: 'deepseek-reasoner', label: 'DeepSeek R1' },
  { id: 'glm-4-flash', label: 'GLM-4 Flash' },
  { id: 'glm-4-plus', label: 'GLM-4 Plus' },
];

function _updateIndicator() {
  if (!_slotIndicator) return;
  const slot = getActiveSlot();
  if (!slot || slot.slot_type === 'chat') {
    _slotIndicator.style.display = 'none';
    return;
  }
  _slotIndicator.style.display = 'flex';
  const icon = slot.slot_type === 'team' ? '👥' : '🤖';
  const modelLabel = _AVAILABLE_MODELS.find(m => m.id === (slot.preferred_model || ''))?.label || '默认模型';

  _slotIndicator.innerHTML = `
    <span class="si-icon">${icon}</span>
    <span class="si-text">${slot.label}</span>
    ${slot.slot_type === 'agent' ? `<select class="si-model-select" title="切换模型">${
      _AVAILABLE_MODELS.map(m => `<option value="${m.id}" ${m.id === (slot.preferred_model || '') ? 'selected' : ''}>${m.label}</option>`).join('')
    }</select>` : ''}
    <button class="si-back" onclick="document.dispatchEvent(new CustomEvent('slot-switch-default'))">↩ 回到对话</button>
  `;

  const sel = _slotIndicator.querySelector('.si-model-select');
  if (sel) {
    sel.addEventListener('change', async () => {
      const model = sel.value;
      try {
        await fetch(`${getBaseUrl()}/api/slots/${slot.slot_id}/config`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'X-API-Token': S.token || '' },
          body: JSON.stringify({ preferred_model: model || 'default' }),
        });
        slot.preferred_model = model;
        fn.showGestureToast?.({ icon: '🧠', label: `模型已切换: ${sel.options[sel.selectedIndex].text}`, color: '#7c6aef' });
      } catch {}
    });
  }
}

function _updatePlaceholder() {
  const inp = document.getElementById('msg-input');
  if (!inp) return;
  const slot = getActiveSlot();
  if (!slot || slot.slot_type === 'chat') {
    inp.placeholder = '有什么需要帮忙的？';
  } else if (slot.slot_type === 'agent') {
    const name = slot.label || 'Agent';
    inp.placeholder = `对 ${name} 说...`;
  } else if (slot.slot_type === 'team') {
    inp.placeholder = '向整个团队布置任务（多角色分工协作，不是单聊某一个）…';
  }
}

document.addEventListener('slot-switch-default', () => switchSlot('chat-default'));

let _cachedRoles = null;

async function _showCreateMenu() {
  const existing = document.getElementById('slot-create-menu');
  if (existing) { existing.remove(); return; }

  const menu = document.createElement('div');
  menu.id = 'slot-create-menu';
  menu.className = 'slot-create-menu';

  menu.innerHTML = `
    <div class="scm-section">西游角色（直呼名字可切换）</div>
    <div class="scm-item scm-featured" data-type="team-xyj">🏔️ 西游取经团（5人协作）</div>
    <div class="scm-item" data-type="agent-tangseng">🧘 唐僧 · 团队领袖</div>
    <div class="scm-item" data-type="agent-wukong">🐵 孙悟空 · 技术大牛</div>
    <div class="scm-item" data-type="agent-bajie">🐷 猪八戒 · 市场达人</div>
    <div class="scm-item" data-type="agent-wujing">🏔️ 沙悟净 · 数据管家</div>
    <div class="scm-item" data-type="agent-bailong">🐉 小白龙 · 客服公关</div>
    <div class="scm-section">专业团队</div>
    <div class="scm-item" data-type="team-marketing">📣 营销获客团队</div>
    <div class="scm-item" data-type="team-software">💻 技术研发团队</div>
    <div class="scm-item" data-type="team-service_center">🎧 客服支持团队</div>
    <div class="scm-item" data-type="team-startup">🚀 创业团队</div>
    <div class="scm-section">更多</div>
    <div class="scm-item" data-type="agent-picker">🤖 全部 52 个 Agent...</div>
    <div class="scm-item" data-type="chat">💬 新建独立对话</div>
  `;

  const _DIRECT_AGENTS = {
    'agent-tangseng': { avatar: '🧘', name: '唐僧', id: 'tangseng' },
    'agent-wukong':   { avatar: '🐵', name: '孙悟空', id: 'wukong' },
    'agent-bajie':    { avatar: '🐷', name: '猪八戒', id: 'bajie' },
    'agent-wujing':   { avatar: '🏔️', name: '沙悟净', id: 'wujing' },
    'agent-bailong':  { avatar: '🐉', name: '小白龙', id: 'bailong' },
  };

  const _handleMenuClick = async (item) => {
    const type = item.dataset.type;
    if (!type) return;
    if (type === 'agent-picker') {
      await _showAgentPicker(menu);
      return;
    }
    menu.remove();
    if (_DIRECT_AGENTS[type]) {
      const a = _DIRECT_AGENTS[type];
      await createSlot('agent', `${a.avatar} ${a.name}`, a.id);
    } else if (type.startsWith('team-')) {
      const preset = type.replace('team-', '');
      await createSlot('team', `团队: ${preset}`, preset);
    } else {
      await createSlot('chat', '新对话', '');
    }
  };
  menu.querySelectorAll('.scm-item').forEach(item => {
    item.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); _handleMenuClick(item); });
    item.addEventListener('touchend', (e) => { e.preventDefault(); e.stopPropagation(); _handleMenuClick(item); }, { passive: false });
  });

  const addBtn = _tabContainer.querySelector('.slot-add-btn');
  if (addBtn) {
    const rect = addBtn.getBoundingClientRect();
    const vw = window.innerWidth;
    menu.style.position = 'fixed';
    menu.style.top = `${rect.bottom + 4}px`;
    if (rect.left < vw / 2) {
      menu.style.left = `${Math.max(4, rect.left)}px`;
      menu.style.right = 'auto';
    } else {
      menu.style.right = `${Math.max(4, vw - rect.right)}px`;
      menu.style.left = 'auto';
    }
    menu.style.maxWidth = `${vw - 16}px`;
  }
  document.body.appendChild(menu);
  setTimeout(() => {
    document.addEventListener('click', function _close(e) {
      if (!menu.contains(e.target) && !e.target.closest('.slot-add-btn')) {
        menu.remove();
        document.removeEventListener('click', _close);
      }
    });
  }, 50);
}

const _ROLE_DEPARTMENTS = [
  { id: 'theme', name: '🏔️ 主题角色', ids: ['tangseng','wukong','bajie','wujing','bailong'] },
  { id: 'mgmt', name: '👔 管理层', ids: ['ceo','coo','cto','cfo','cmo'] },
  { id: 'dev', name: '💻 研发技术', ids: ['pm','frontend','backend','tester','devops','dba','security','architect'] },
  { id: 'mkt', name: '📣 市场营销', ids: ['marketer','seo','ads','brand','pr','community','growth'] },
  { id: 'sales', name: '💼 商务销售', ids: ['sales','presale','bd','crm'] },
  { id: 'cs', name: '🎧 客服', ids: ['cs_online','cs_after','cs_vip'] },
  { id: 'ops', name: '📦 供应链', ids: ['buyer','warehouse','logistics','dispatch','quality','scm'] },
  { id: 'fin', name: '💰 财务法务', ids: ['accountant','finance','tax','legal'] },
  { id: 'hr', name: '👥 人事行政', ids: ['hr','admin'] },
  { id: 'content', name: '✏️ 内容创意', ids: ['writer','editor','copywriter','designer','video','photographer','translator'] },
  { id: 'other', name: '🔮 专家顾问', ids: ['data_analyst','ai_trainer','mentor','consultant','researcher','assistant'] },
];

async function _showAgentPicker(parentMenu) {
  if (parentMenu) parentMenu.remove();

  const existing = document.getElementById('role-picker-modal');
  if (existing) { existing.remove(); return; }

  if (!_cachedRoles || _cachedRoles.length === 0) {
    _cachedRoles = null;
    for (let _retry = 0; _retry < 2; _retry++) {
      try {
        const r = await fetch(`${getBaseUrl()}/api/slots/available-roles`, {
          headers: { 'X-API-Token': S.token || '' },
        });
        const d = await r.json();
        if (d.ok && d.roles?.length) { _cachedRoles = d.roles; break; }
      } catch (e) {
        console.warn(`Role fetch attempt ${_retry + 1} failed:`, e);
        if (_retry === 0) await new Promise(r => setTimeout(r, 500));
      }
    }
    if (!_cachedRoles || _cachedRoles.length === 0) {
      _cachedRoles = [];
      fn.showGestureToast?.({ icon: '⚠️', label: '角色加载失败，请用菜单直选角色', color: '#f59e0b' });
      return;
    }
  }

  const modal = document.createElement('div');
  modal.id = 'role-picker-modal';
  modal.className = 'rpm-overlay';

  const roleMap = {};
  for (const r of _cachedRoles) roleMap[r.id] = r;

  function buildCards(filter) {
    let html = '';
    for (const dept of _ROLE_DEPARTMENTS) {
      const roles = dept.ids
        .map(id => roleMap[id])
        .filter(r => r && (!filter || r.name.includes(filter) || r.id.includes(filter) || r.desc.includes(filter)));
      if (!roles.length) continue;
      html += `<div class="rpm-dept">${dept.name}</div><div class="rpm-grid">`;
      for (const r of roles) {
        const voice = r.tts_voice ? `<span class="rpm-voice">🔊</span>` : '';
        html += `<div class="rpm-card" data-rid="${r.id}">
          <div class="rpm-avatar">${r.avatar}</div>
          <div class="rpm-name">${r.name}${voice}</div>
          <div class="rpm-desc">${r.desc.substring(0, 40)}</div>
        </div>`;
      }
      html += '</div>';
    }
    return html || '<div class="rpm-empty">未找到匹配角色</div>';
  }

  modal.innerHTML = `
    <div class="rpm-panel">
      <div class="rpm-header">
        <span>选择 Agent 角色</span>
        <input class="rpm-search" placeholder="搜索角色..." />
        <button class="rpm-close">✕</button>
      </div>
      <div class="rpm-body">${buildCards('')}</div>
    </div>
  `;

  modal.querySelector('.rpm-close').onclick = () => modal.remove();
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

  const searchInput = modal.querySelector('.rpm-search');
  searchInput.addEventListener('input', () => {
    modal.querySelector('.rpm-body').innerHTML = buildCards(searchInput.value.trim());
    _bindCardClicks();
  });

  function _bindCardClicks() {
    modal.querySelectorAll('.rpm-card').forEach(card => {
      card.addEventListener('click', async () => {
        const roleId = card.dataset.rid;
        const role = roleMap[roleId];
        modal.remove();
        await createSlot('agent', `${role?.avatar || '🤖'} ${role?.name || roleId}`, roleId);
      });
    });
  }
  _bindCardClicks();

  document.body.appendChild(modal);
  searchInput.focus();
}

// ═══ 样式 ═══

function _injectStyles() {
  if (document.getElementById('slot-manager-styles')) return;
  const style = document.createElement('style');
  style.id = 'slot-manager-styles';
  style.textContent = `
.slot-tabs{
  display:flex;align-items:center;gap:2px;padding:4px 12px;
  background:var(--bg-secondary,#1a1a2e);border-bottom:1px solid var(--border,#333);
  overflow-x:auto;flex-shrink:0;min-height:36px;position:relative;
  z-index:10001;
}
.slot-tab{
  display:flex;align-items:center;gap:4px;padding:4px 10px;
  border-radius:6px;cursor:pointer;font-size:12px;
  color:var(--text-secondary,#888);background:transparent;
  border:1px solid transparent;transition:all .15s;white-space:nowrap;
  position:relative;
}
.slot-tab:hover{background:rgba(108,99,255,0.08);color:var(--text-primary,#eee)}
.slot-tab.active{
  background:rgba(108,99,255,0.15);color:var(--accent,#7c6aef);
  border-color:var(--accent,#7c6aef);font-weight:600;
}
.slot-icon{font-size:13px}
.slot-label{max-width:100px;overflow:hidden;text-overflow:ellipsis}
.slot-badge{
  font-size:10px;padding:0 3px;border-radius:3px;
  background:rgba(245,158,11,0.15);color:#f59e0b;
}
.slot-badge.done{background:rgba(34,197,94,0.15);color:#22c55e}
.slot-close{
  background:none;border:none;color:var(--text-muted,#666);
  cursor:pointer;font-size:14px;line-height:1;padding:0 2px;
  opacity:0;transition:opacity .15s;
}
.slot-tab:hover .slot-close{opacity:1}
.slot-close:hover{color:var(--error,#ef4444)}
.slot-add-btn{
  width:30px;height:30px;border-radius:8px;border:1.5px solid var(--border,#444);
  background:none;color:var(--text-muted,#888);cursor:pointer;
  font-size:18px;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:all .2s;
}
.slot-add-btn:hover{
  border-color:var(--accent,#7c6aef);color:#fff;
  background:var(--accent,#7c6aef);transform:rotate(90deg);
}
.slot-add-btn.pulse{animation:slot-pulse 2s ease-in-out 3}
@keyframes slot-pulse{
  0%,100%{box-shadow:0 0 0 0 rgba(124,106,239,0)}
  50%{box-shadow:0 0 0 6px rgba(124,106,239,0.3)}
}
.slot-indicator{
  display:none;align-items:center;gap:6px;padding:4px 12px;
  background:rgba(108,99,255,0.08);border-top:1px solid rgba(108,99,255,0.2);
  font-size:11px;color:var(--accent,#7c6aef);
}
.si-icon{font-size:14px}
.si-text{flex:1}
.si-back{
  background:none;border:1px solid var(--border,#444);color:var(--text-secondary,#888);
  padding:2px 8px;border-radius:4px;cursor:pointer;font-size:10px;
}
.si-back:hover{border-color:var(--accent);color:var(--accent)}
.si-model-select{
  padding:1px 4px;font-size:10px;border-radius:4px;
  background:var(--bg-surface,#252542);border:1px solid var(--border,#444);
  color:var(--text-secondary,#aaa);cursor:pointer;outline:none;
}
.si-model-select:hover{border-color:var(--accent,#7c6aef)}
.slot-create-menu{
  position:fixed;background:var(--bg-secondary,#1e1e3a);
  border:1px solid var(--border,#333);border-radius:12px;padding:6px;
  box-shadow:0 8px 32px rgba(0,0,0,0.5);z-index:10200;min-width:200px;
  max-height:70vh;overflow-y:auto;-webkit-overflow-scrolling:touch;
  box-sizing:border-box;
}
.scm-item{
  padding:10px 12px;border-radius:6px;cursor:pointer;font-size:14px;
  color:var(--text-primary,#eee);transition:background .1s;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.scm-item:hover,.scm-item:active{background:rgba(108,99,255,0.15)}
.scm-featured{font-weight:600;color:var(--accent,#7c6aef)}
.scm-badge{
  margin-left:6px;padding:1px 5px;border-radius:3px;font-size:9px;
  background:var(--accent,#7c6aef);color:#fff;font-weight:700;
  vertical-align:middle;
}
.scm-section{
  padding:4px 12px 2px;font-size:10px;color:var(--text-muted,#555);
  text-transform:uppercase;letter-spacing:0.5px;
}
.scm-sub{padding:4px;border-top:1px solid var(--border,#333)}
.scm-search{
  width:100%;padding:5px 8px;background:var(--bg-surface,#252542);
  border:1px solid var(--border,#333);border-radius:4px;color:var(--text-primary,#eee);
  font-size:11px;margin-bottom:4px;
}
.scm-role-list{max-height:200px;overflow-y:auto}
.scm-role{
  display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:4px;
  cursor:pointer;transition:background .1s;
}
.scm-role:hover{background:rgba(108,99,255,0.12)}
.scm-role-avatar{font-size:16px}
.scm-role-info{flex:1;min-width:0}
.scm-role-name{font-size:11px;font-weight:500;color:var(--text-primary,#eee)}
.scm-role-desc{font-size:9px;color:var(--text-muted,#666);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 团队时间线 */
.team-timeline-live{
  margin:8px 0;padding:8px 12px;border-radius:8px;
  background:rgba(108,99,255,0.06);border:1px solid rgba(108,99,255,0.15);
}
.ttl-header{font-size:12px;font-weight:600;color:var(--accent,#7c6aef);margin-bottom:6px}
.ttl-steps{display:flex;flex-direction:column;gap:3px}
.ttl-step{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--text-secondary,#888);padding:2px 0}
.ttl-step.agent{padding:3px 6px;border-radius:6px;background:rgba(255,255,255,0.02)}
.ttl-avatar{font-size:16px;flex-shrink:0}
.ttl-name{font-weight:600;color:var(--text-primary,#ddd);font-size:11px;flex-shrink:0}
.ttl-dot{
  width:6px;height:6px;border-radius:50%;background:#f59e0b;flex-shrink:0;
  animation:ttl-pulse 1s infinite alternate;
}
.ttl-step.done .ttl-dot{background:#22c55e;animation:none}
@keyframes ttl-pulse{0%{opacity:.4}100%{opacity:1}}
/* 团队完成卡片 */
.team-complete-card{
  margin:8px 0;padding:12px;border-radius:10px;
  background:linear-gradient(135deg,rgba(34,197,94,0.08),rgba(108,99,255,0.08));
  border:1px solid rgba(34,197,94,0.2);
}
.team-complete-card.error{
  background:linear-gradient(135deg,rgba(239,68,68,0.08),rgba(108,99,255,0.08));
  border-color:rgba(239,68,68,0.2);
}
.tcc-header{display:flex;align-items:center;gap:6px;margin-bottom:8px}
.tcc-icon{font-size:18px}
.tcc-title{flex:1;font-size:13px;font-weight:600;color:var(--text-primary,#eee)}
.tcc-time{font-size:10px;color:var(--text-muted,#666)}
.tcc-task-desc{font-size:11px;color:var(--text-secondary,#aaa);margin-bottom:8px;line-height:1.4}
.tcc-agents{display:flex;flex-direction:column;gap:4px;margin-bottom:8px}
.tcc-agent{
  display:flex;align-items:flex-start;gap:6px;padding:4px 6px;
  border-radius:6px;background:rgba(255,255,255,0.03);
}
.tcc-agent.done{border-left:2px solid #22c55e}
.tcc-avatar{font-size:14px;flex-shrink:0;margin-top:1px}
.tcc-detail{flex:1;min-width:0}
.tcc-name{font-size:11px;font-weight:500;color:var(--text-primary,#eee)}
.tcc-task{font-size:10px;color:var(--text-muted,#777)}
.tcc-preview{font-size:10px;color:var(--text-secondary,#999);margin-top:2px;line-height:1.3}
.tcc-summary{
  font-size:11px;color:var(--text-primary,#ddd);line-height:1.5;
  padding:6px 8px;background:rgba(0,0,0,0.15);border-radius:6px;
  max-height:120px;overflow-y:auto;margin-bottom:6px;
}
.tcc-actions{display:flex;gap:6px}
.tcc-btn{
  padding:4px 12px;border-radius:4px;font-size:11px;cursor:pointer;
  background:var(--accent,#7c6aef);color:#fff;border:none;
}
.tcc-btn:hover{opacity:.85}
.slot-tab.has-result{border-color:rgba(34,197,94,0.4)}
.slot-tab.dragging{opacity:.4;border-style:dashed}
.slot-tab.drag-over{border-color:var(--accent,#7c6aef);background:rgba(108,99,255,0.12)}
.slot-rename-input{
  width:60px;padding:0 4px;font-size:11px;
  background:var(--bg-surface,#252542);border:1px solid var(--accent,#7c6aef);
  border-radius:3px;color:var(--text-primary,#eee);outline:none;
}
/* 工具调用卡片 */
.tool-call-card{
  margin:4px 0;padding:8px 10px;border-radius:8px;
  background:rgba(108,99,255,0.05);border:1px solid rgba(108,99,255,0.12);
  font-size:11px;transition:all .3s;
}
.tool-call-card.working{border-color:rgba(245,158,11,0.3);background:rgba(245,158,11,0.04)}
.tool-call-card.done{border-color:rgba(34,197,94,0.2);background:rgba(34,197,94,0.04)}
.tc-header{display:flex;align-items:center;gap:6px}
.tc-icon{font-size:14px}
.tc-name{font-weight:600;color:var(--text-primary,#eee);flex:1}
.tc-status{font-size:10px;color:var(--text-muted,#888)}
.tc-spinner{
  display:inline-block;width:10px;height:10px;
  border:2px solid rgba(245,158,11,0.3);border-top-color:#f59e0b;
  border-radius:50%;animation:tc-spin .6s linear infinite;
  margin-right:4px;vertical-align:middle;
}
@keyframes tc-spin{to{transform:rotate(360deg)}}
.tc-args{
  margin-top:4px;display:flex;flex-wrap:wrap;gap:3px;
}
.tc-arg{
  padding:1px 6px;border-radius:3px;background:rgba(255,255,255,0.04);
  color:var(--text-secondary,#999);font-size:10px;
}
.tc-key{color:var(--text-muted,#666)}
.tc-result{
  margin-top:4px;font-size:10px;color:var(--text-secondary,#888);
  line-height:1.3;max-height:60px;overflow:hidden;
}
/* 转发选择器 */
.forward-picker{
  position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
  background:var(--bg-secondary,#1e1e3a);border:1px solid var(--border,#444);
  border-radius:10px;padding:8px;box-shadow:0 8px 32px rgba(0,0,0,0.5);
  z-index:200;min-width:180px;
}
.fp-title{padding:6px 12px;font-size:12px;font-weight:600;color:var(--text-primary,#eee)}
.fp-item{
  padding:8px 12px;border-radius:6px;cursor:pointer;font-size:12px;
  color:var(--text-primary,#ddd);transition:background .1s;
}
.fp-item:hover{background:rgba(108,99,255,0.12)}
.tcc-fwd,.tcc-chain{background:transparent;border:1px solid var(--border,#555);color:var(--text-secondary,#aaa)}
.tcc-fwd:hover,.tcc-chain:hover{border-color:var(--accent);color:var(--accent)}
.si-chain-input{
  width:calc(100% - 24px);margin:4px 12px;padding:5px 8px;font-size:11px;
  background:var(--bg-surface,#252542);border:1px solid var(--border,#444);
  border-radius:4px;color:var(--text-primary,#eee);outline:none;
}
.si-chain-input:focus{border-color:var(--accent,#7c6aef)}
/* Role Picker Modal */
.rpm-overlay{
  position:fixed;inset:0;z-index:10100;background:rgba(0,0,0,0.6);
  display:flex;align-items:center;justify-content:center;
  animation:rpm-in .2s ease-out;
}
@keyframes rpm-in{from{opacity:0}to{opacity:1}}
.rpm-panel{
  width:min(680px,92vw);max-height:80vh;background:var(--bg-secondary,#131321);
  border-radius:14px;border:1px solid var(--border,#333);
  display:flex;flex-direction:column;overflow:hidden;
  box-shadow:0 12px 40px rgba(0,0,0,0.5);
}
.rpm-header{
  display:flex;align-items:center;gap:8px;padding:12px 16px;
  border-bottom:1px solid var(--border,#333);font-size:14px;font-weight:600;
  color:var(--text-primary,#eee);
}
.rpm-header span{flex:1}
.rpm-search{
  width:180px;padding:5px 10px;border-radius:6px;font-size:12px;
  background:var(--bg-surface,#1b1b30);border:1px solid var(--border,#444);
  color:var(--text-primary,#eee);outline:none;
}
.rpm-search:focus{border-color:var(--accent,#7c6aef)}
.rpm-close{
  background:none;border:none;color:var(--text-muted,#666);font-size:16px;
  cursor:pointer;padding:4px;
}
.rpm-close:hover{color:var(--text-primary,#eee)}
.rpm-body{padding:8px 16px 16px;overflow-y:auto;flex:1}
.rpm-dept{
  font-size:12px;font-weight:600;color:var(--text-muted,#888);
  margin:12px 0 6px;padding-bottom:4px;border-bottom:1px solid var(--border,#222);
}
.rpm-dept:first-child{margin-top:4px}
.rpm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px}
.rpm-card{
  padding:8px;border-radius:8px;cursor:pointer;
  background:var(--bg-surface,#1b1b30);border:1px solid transparent;
  transition:all .15s;text-align:center;
}
.rpm-card:hover{border-color:var(--accent,#7c6aef);background:rgba(124,106,239,0.08)}
.rpm-avatar{font-size:24px;margin-bottom:2px}
.rpm-name{font-size:11px;font-weight:600;color:var(--text-primary,#eee)}
.rpm-voice{font-size:9px;margin-left:2px;vertical-align:middle}
.rpm-desc{font-size:9px;color:var(--text-muted,#666);margin-top:2px;line-height:1.2;
  overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.rpm-empty{text-align:center;padding:40px;color:var(--text-muted,#555);font-size:13px}
/* Mobile */
@media(max-width:640px){
  .slot-tabs{padding:3px 6px;gap:1px;min-height:32px}
  .slot-tab{padding:3px 6px;font-size:10px;max-width:100px}
  .slot-add-btn{width:28px;height:28px;font-size:16px}
  .slot-indicator{padding:3px 8px}
  .slot-create-menu{min-width:180px;max-width:calc(100vw - 16px)}
  .scm-item{padding:12px;font-size:14px}
  .scm-section{padding:6px 12px 3px;font-size:11px}
  .rpm-grid{grid-template-columns:repeat(auto-fill,minmax(100px,1fr))}
  .rpm-panel{width:96vw;max-height:85vh}
  .rpm-search{width:120px}
}
  `;
  document.head.appendChild(style);
}

window.__slotManager = {
  switchSlot,
  createSlot,
  removeSlot,
  getActiveSlotId,
  getActiveSlot,
  getSlotById,
  metaFromSlot,
  interruptSlotTTS,
  sendAgentMessage,
  sendTeamMessage,
  viewTeamResult,
  showForwardPicker,
  refreshSlots: () => _loadSlots(),
};
