/**
 * 多用户面板 — 声纹识别 + 用户切换 + 注册向导
 *
 * 功能：
 *   - header 用户头像按钮 + 下拉切换面板
 *   - 用户注册向导（录 3 句话采集声纹）
 *   - 声纹自动识别后实时更新 header
 *   - 用户偏好设置
 */

const BASE = '';

// ── 状态 ─────────────────────────────────────────────────────

let _users = [];
let _currentUser = null;
let _panelOpen = false;
let _pollTimer = null;

// ── 初始化 ───────────────────────────────────────────────────

export function initUserPanel() {
  _injectHeaderButton();
  _injectPanel();
  _injectStyles();
  _fetchUsers();
  // 每 5 秒轮询当前用户（声纹自动识别可能改变）
  _pollTimer = setInterval(_fetchCurrentUser, 5000);
}

// ── 数据获取 ─────────────────────────────────────────────────

async function _fetchUsers() {
  try {
    const r = await fetch(`${BASE}/api/users`);
    const data = await r.json();
    _users = data.users || [];
    _currentUser = data.current_user;
    _updateHeaderAvatar();
    _renderPanel();
  } catch (e) {
    console.debug('[UserPanel] fetch error:', e);
  }
}

async function _fetchCurrentUser() {
  try {
    const r = await fetch(`${BASE}/api/users/current`);
    const data = await r.json();
    if (data.user && data.user.user_id !== _currentUser) {
      _currentUser = data.user.user_id;
      _updateHeaderAvatar();
    }
  } catch (e) { /* silent */ }
}

async function _switchUser(userId) {
  try {
    await fetch(`${BASE}/api/users/switch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    _currentUser = userId;
    _updateHeaderAvatar();
    _renderPanel();
  } catch (e) {
    console.error('[UserPanel] switch error:', e);
  }
}

async function _deleteUser(userId) {
  if (!confirm(`确定删除该用户？`)) return;
  try {
    await fetch(`${BASE}/api/users/${userId}`, { method: 'DELETE' });
    await _fetchUsers();
  } catch (e) {
    console.error('[UserPanel] delete error:', e);
  }
}

// ── Header 按钮 ──────────────────────────────────────────────

function _injectHeaderButton() {
  const headerRight = document.querySelector('.header-right');
  if (!headerRight) return;

  const btn = document.createElement('button');
  btn.id = 'user-avatar-btn';
  btn.className = 'user-avatar-btn';
  btn.title = '用户切换';
  btn.textContent = '👤';
  btn.onclick = () => {
    _panelOpen = !_panelOpen;
    const panel = document.getElementById('user-panel');
    if (panel) panel.style.display = _panelOpen ? 'block' : 'none';
  };
  headerRight.prepend(btn);
}

function _updateHeaderAvatar() {
  const btn = document.getElementById('user-avatar-btn');
  if (!btn) return;
  const user = _users.find(u => u.user_id === _currentUser);
  btn.textContent = user ? user.avatar : '👤';
  btn.title = user ? user.name : '用户';
}

// ── 下拉面板 ─────────────────────────────────────────────────

function _injectPanel() {
  const panel = document.createElement('div');
  panel.id = 'user-panel';
  panel.className = 'user-panel';
  panel.style.display = 'none';
  document.body.appendChild(panel);

  // 点击外部关闭
  document.addEventListener('click', (e) => {
    if (_panelOpen && !panel.contains(e.target) &&
        e.target.id !== 'user-avatar-btn') {
      _panelOpen = false;
      panel.style.display = 'none';
    }
  });
}

function _renderPanel() {
  const panel = document.getElementById('user-panel');
  if (!panel) return;

  const userCards = _users.map(u => `
    <div class="user-card ${u.user_id === _currentUser ? 'active' : ''}"
         onclick="window.__userPanel.switch('${u.user_id}')">
      <span class="user-avatar-lg">${u.avatar}</span>
      <div class="user-info">
        <span class="user-name">${u.name}</span>
        <span class="user-badge">${u.has_voiceprint ? '🎤' : ''}${u.user_id === _currentUser ? ' 当前' : ''}</span>
      </div>
      ${u.user_id !== 'default' ? `<button class="user-delete" onclick="event.stopPropagation();window.__userPanel.delete('${u.user_id}')">✕</button>` : ''}
    </div>
  `).join('');

  panel.innerHTML = `
    <div class="user-panel-header">用户切换</div>
    <div class="user-list">${userCards}</div>
    <button class="user-add-btn" onclick="window.__userPanel.showRegister()">
      ➕ 添加新用户
    </button>
  `;
}

// ── 注册向导 ─────────────────────────────────────────────────

function _showRegisterWizard() {
  const overlay = document.createElement('div');
  overlay.id = 'user-register-overlay';
  overlay.className = 'user-register-overlay';
  overlay.innerHTML = `
    <div class="user-register-modal">
      <h3>注册新用户</h3>
      <div id="reg-step-1" class="reg-step">
        <label>昵称</label>
        <input type="text" id="reg-name" placeholder="输入昵称" maxlength="20">
        <label>头像</label>
        <div class="avatar-picker" id="avatar-picker"></div>
        <button class="reg-next-btn" onclick="window.__userPanel.regStep2()">下一步 →</button>
      </div>
      <div id="reg-step-2" class="reg-step" style="display:none">
        <p>请说 3 句话以采集声纹（每句约 3 秒）</p>
        <div class="voice-prompts">
          <div class="vp" id="vp-0">① "今天天气怎么样"</div>
          <div class="vp" id="vp-1">② "帮我打开微信"</div>
          <div class="vp" id="vp-2">③ "我想听一首歌"</div>
        </div>
        <div class="rec-progress">
          <div class="rec-bar" id="rec-bar" style="width:0%"></div>
        </div>
        <button class="reg-rec-btn" id="reg-rec-btn" onclick="window.__userPanel.startRecording()">
          🎤 开始录音
        </button>
        <p class="rec-status" id="rec-status"></p>
      </div>
      <div id="reg-step-3" class="reg-step" style="display:none">
        <p class="reg-done">✅ 声纹采集完成！</p>
        <button class="reg-finish-btn" onclick="window.__userPanel.finishRegister()">完成注册</button>
      </div>
      <button class="reg-close" onclick="window.__userPanel.closeRegister()">✕</button>
    </div>
  `;
  document.body.appendChild(overlay);

  // 头像选择器
  const emojis = ['😊','😎','🤓','👨','👩','👧','👦','🧑','👴','👵','🐱','🐶','🦊','🐻','🐼','🌟','🎤','🎮'];
  const picker = document.getElementById('avatar-picker');
  picker.innerHTML = emojis.map(e =>
    `<span class="avatar-option" onclick="window.__userPanel.pickAvatar('${e}')">${e}</span>`
  ).join('');
  window.__regAvatar = '😊';
  window.__regAudios = [];
  window.__regStep = 0;
}

// 全局暴露供 onclick 使用
window.__userPanel = {
  switch: _switchUser,
  delete: _deleteUser,
  showRegister: _showRegisterWizard,
  closeRegister: () => {
    const el = document.getElementById('user-register-overlay');
    if (el) el.remove();
  },
  pickAvatar: (emoji) => {
    window.__regAvatar = emoji;
    document.querySelectorAll('.avatar-option').forEach(el => el.classList.remove('selected'));
    event.target.classList.add('selected');
  },
  regStep2: () => {
    const name = document.getElementById('reg-name')?.value?.trim();
    if (!name) { alert('请输入昵称'); return; }
    window.__regName = name;
    document.getElementById('reg-step-1').style.display = 'none';
    document.getElementById('reg-step-2').style.display = 'block';
  },
  startRecording: async () => {
    const btn = document.getElementById('reg-rec-btn');
    const status = document.getElementById('rec-status');
    const step = window.__regStep;
    if (step >= 3) return;

    btn.disabled = true;
    btn.textContent = '🔴 录音中...';
    status.textContent = `正在录制第 ${step + 1} 段`;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new AudioContext({ sampleRate: 16000 });
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      const chunks = [];

      processor.onaudioprocess = (e) => {
        chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      };
      source.connect(processor);
      processor.connect(ctx.destination);

      // 录 3 秒
      await new Promise(r => setTimeout(r, 3000));

      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach(t => t.stop());
      ctx.close();

      // 合并音频
      const total = chunks.reduce((s, c) => s + c.length, 0);
      const audio = new Float32Array(total);
      let offset = 0;
      for (const c of chunks) { audio.set(c, offset); offset += c.length; }

      // 转 base64
      const bytes = new Uint8Array(audio.buffer);
      let binary = '';
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
      const b64 = btoa(binary);
      window.__regAudios.push(b64);

      // 标记完成
      const vp = document.getElementById(`vp-${step}`);
      if (vp) vp.classList.add('done');
      const bar = document.getElementById('rec-bar');
      if (bar) bar.style.width = `${((step + 1) / 3) * 100}%`;

      window.__regStep = step + 1;

      if (window.__regStep >= 3) {
        btn.textContent = '✅ 录音完成';
        status.textContent = '3 段声纹采集完毕';
        document.getElementById('reg-step-2').style.display = 'none';
        document.getElementById('reg-step-3').style.display = 'block';
      } else {
        btn.disabled = false;
        btn.textContent = '🎤 录制下一段';
        status.textContent = `已完成 ${window.__regStep}/3`;
      }
    } catch (e) {
      btn.disabled = false;
      btn.textContent = '🎤 重试';
      status.textContent = `录音失败: ${e.message}`;
    }
  },
  finishRegister: async () => {
    const btn = document.querySelector('.reg-finish-btn');
    btn.textContent = '注册中...';
    btn.disabled = true;

    try {
      const r = await fetch(`${BASE}/api/users/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: window.__regName,
          avatar: window.__regAvatar,
          audio_segments: window.__regAudios,
        }),
      });
      const data = await r.json();
      if (data.ok) {
        window.__userPanel.closeRegister();
        await _fetchUsers();
        _switchUser(data.user.user_id);
      } else {
        alert('注册失败: ' + (data.error || '未知错误'));
        btn.textContent = '重试';
        btn.disabled = false;
      }
    } catch (e) {
      alert('注册失败: ' + e.message);
      btn.textContent = '重试';
      btn.disabled = false;
    }
  },
};

// ── 样式注入 ─────────────────────────────────────────────────

function _injectStyles() {
  if (document.getElementById('user-panel-styles')) return;
  const style = document.createElement('style');
  style.id = 'user-panel-styles';
  style.textContent = `
    .user-avatar-btn {
      width: 36px; height: 36px; border-radius: 50%;
      border: 2px solid var(--accent, #6c63ff); background: var(--bg2, #1a1a2e);
      font-size: 20px; cursor: pointer; display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s;
    }
    .user-avatar-btn:hover { transform: scale(1.1); }

    .user-panel {
      position: fixed; top: 50px; right: 16px; width: 280px;
      background: var(--bg2, #1a1a2e); border: 1px solid var(--border, #333);
      border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
      z-index: 9999; padding: 12px; max-height: 400px; overflow-y: auto;
    }
    .user-panel-header { font-weight: 600; margin-bottom: 8px; color: var(--text, #eee); }
    .user-card {
      display: flex; align-items: center; gap: 10px; padding: 8px 10px;
      border-radius: 8px; cursor: pointer; transition: background 0.2s;
    }
    .user-card:hover { background: var(--bg3, #252542); }
    .user-card.active { background: var(--accent, #6c63ff)22; border: 1px solid var(--accent, #6c63ff); }
    .user-avatar-lg { font-size: 28px; }
    .user-info { flex: 1; }
    .user-name { display: block; font-weight: 500; color: var(--text, #eee); }
    .user-badge { font-size: 11px; color: var(--text-dim, #888); }
    .user-delete { background: none; border: none; color: #f55; cursor: pointer; font-size: 14px; padding: 4px; }
    .user-add-btn {
      width: 100%; padding: 10px; margin-top: 8px; border: 1px dashed var(--border, #444);
      border-radius: 8px; background: none; color: var(--text, #eee); cursor: pointer; font-size: 14px;
    }
    .user-add-btn:hover { background: var(--bg3, #252542); }

    .user-register-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 10000;
      display: flex; align-items: center; justify-content: center;
    }
    .user-register-modal {
      background: var(--bg2, #1a1a2e); border-radius: 16px; padding: 24px;
      width: 90%; max-width: 400px; position: relative; color: var(--text, #eee);
    }
    .user-register-modal h3 { margin: 0 0 16px; }
    .user-register-modal label { display: block; margin: 8px 0 4px; font-size: 13px; color: var(--text-dim, #aaa); }
    .user-register-modal input {
      width: 100%; padding: 8px 12px; border-radius: 8px; border: 1px solid var(--border, #444);
      background: var(--bg, #0b0d14); color: var(--text, #eee); font-size: 14px;
    }
    .reg-close { position: absolute; top: 12px; right: 12px; background: none; border: none; color: #888; font-size: 18px; cursor: pointer; }
    .avatar-picker { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
    .avatar-option { font-size: 24px; cursor: pointer; padding: 4px; border-radius: 6px; border: 2px solid transparent; }
    .avatar-option:hover, .avatar-option.selected { border-color: var(--accent, #6c63ff); background: var(--accent, #6c63ff)22; }
    .reg-next-btn, .reg-rec-btn, .reg-finish-btn {
      width: 100%; padding: 10px; margin-top: 12px; border: none; border-radius: 8px;
      background: var(--accent, #6c63ff); color: #fff; font-size: 14px; cursor: pointer;
    }
    .reg-next-btn:hover, .reg-rec-btn:hover, .reg-finish-btn:hover { opacity: 0.9; }
    .voice-prompts { margin: 12px 0; }
    .vp { padding: 8px; margin: 4px 0; border-radius: 6px; background: var(--bg, #0b0d14); font-size: 13px; }
    .vp.done { background: #22c55e22; border-left: 3px solid #22c55e; }
    .rec-progress { height: 4px; background: var(--bg, #0b0d14); border-radius: 2px; margin: 8px 0; overflow: hidden; }
    .rec-bar { height: 100%; background: var(--accent, #6c63ff); transition: width 0.3s; }
    .rec-status { font-size: 12px; color: var(--text-dim, #888); text-align: center; margin-top: 8px; }
    .reg-done { text-align: center; font-size: 18px; margin: 24px 0; }
  `;
  document.head.appendChild(style);
}
