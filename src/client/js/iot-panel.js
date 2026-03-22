/**
 * IoT 智能家居控制面板
 *
 * 功能：设备列表、开关控制、房间分组、HomeAssistant 配置
 */

const BASE = '';
let _devices = [];
let _configured = false;

export function initIoTPanel() {
  _injectTab();
  _injectStyles();
}

async function _fetchDevices() {
  try {
    const r = await fetch(`${BASE}/api/iot/devices`);
    const data = await r.json();
    _devices = data.devices || [];
    _configured = data.configured;
    _renderPanel();
  } catch (e) {
    console.debug('[IoT] fetch error:', e);
  }
}

async function _controlDevice(entityId, action, value) {
  try {
    const r = await fetch(`${BASE}/api/iot/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entity_id: entityId, action, value }),
    });
    const data = await r.json();
    if (data.ok) {
      setTimeout(_fetchDevices, 500); // 刷新状态
    }
    return data;
  } catch (e) {
    return { error: e.message };
  }
}

async function _saveConfig() {
  const url = document.getElementById('iot-ha-url')?.value?.trim();
  const token = document.getElementById('iot-ha-token')?.value?.trim();
  if (!url || !token) { alert('请填写完整'); return; }

  try {
    await fetch(`${BASE}/api/iot/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, token }),
    });
    _configured = true;
    _fetchDevices();
  } catch (e) {
    alert('配置失败: ' + e.message);
  }
}

function _injectTab() {
  // 在 settings 面板中查找 tab 容器
  const tabContainer = document.querySelector('.settings-tabs, .tab-bar');
  if (tabContainer) {
    const tab = document.createElement('button');
    tab.className = 'stab';
    tab.textContent = '🏠 智能家居';
    tab.dataset.tab = 'iot-panel-tab';
    tab.onclick = () => { _showPanel(); _fetchDevices(); };
    tabContainer.appendChild(tab);
  }

  // 创建面板容器
  const panel = document.createElement('div');
  panel.id = 'iot-panel';
  panel.className = 'iot-panel';
  panel.style.display = 'none';
  document.body.appendChild(panel);
}

function _showPanel() {
  const panel = document.getElementById('iot-panel');
  if (!panel) return;
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  if (panel.style.display === 'block') _renderPanel();
}

function _renderPanel() {
  const panel = document.getElementById('iot-panel');
  if (!panel) return;

  if (!_configured) {
    panel.innerHTML = `
      <div class="iot-header">🏠 智能家居设置</div>
      <div class="iot-config">
        <p>请配置 HomeAssistant 连接：</p>
        <label>URL</label>
        <input type="text" id="iot-ha-url" placeholder="http://homeassistant.local:8123">
        <label>Long-Lived Token</label>
        <input type="password" id="iot-ha-token" placeholder="eyJ0eXAi...">
        <button class="iot-save-btn" onclick="window.__iot.saveConfig()">保存并连接</button>
      </div>
    `;
    return;
  }

  // 按房间分组
  const rooms = {};
  for (const d of _devices) {
    const room = d.room || '未分组';
    if (!rooms[room]) rooms[room] = [];
    rooms[room].push(d);
  }

  const ICONS = { light: '💡', switch: '🔌', climate: '❄️', sensor: '📊', cover: '🪟', fan: '🌀' };

  let html = `<div class="iot-header">🏠 智能家居 <span class="iot-count">${_devices.length} 设备</span></div>`;

  for (const [room, devs] of Object.entries(rooms)) {
    html += `<div class="iot-room"><div class="iot-room-name">${room}</div>`;
    for (const d of devs) {
      const icon = ICONS[d.type] || '📦';
      const isOn = d.state === 'on';
      html += `
        <div class="iot-device ${isOn ? 'on' : ''}">
          <span class="iot-icon">${icon}</span>
          <div class="iot-dev-info">
            <span class="iot-dev-name">${d.name}</span>
            <span class="iot-dev-state">${d.state}</span>
          </div>
          <button class="iot-toggle ${isOn ? 'active' : ''}"
                  onclick="window.__iot.toggle('${d.id}','${isOn ? 'off' : 'on'}')">
            ${isOn ? 'ON' : 'OFF'}
          </button>
        </div>`;
    }
    html += '</div>';
  }

  if (_devices.length === 0) {
    html += '<p class="iot-empty">未发现设备，请确认 HomeAssistant 已连接</p>';
  }

  html += '<button class="iot-refresh" onclick="window.__iot.refresh()">🔄 刷新设备</button>';
  panel.innerHTML = html;
}

window.__iot = {
  toggle: (id, action) => _controlDevice(id, action),
  refresh: () => _fetchDevices(),
  saveConfig: _saveConfig,
  show: () => { _showPanel(); _fetchDevices(); },
};

function _injectStyles() {
  if (document.getElementById('iot-panel-styles')) return;
  const style = document.createElement('style');
  style.id = 'iot-panel-styles';
  style.textContent = `
    .iot-panel {
      position: fixed; bottom: 60px; right: 16px; width: 320px; max-height: 500px;
      background: var(--bg2, #1a1a2e); border: 1px solid var(--border, #333);
      border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
      z-index: 9999; padding: 16px; overflow-y: auto;
    }
    .iot-header { font-weight: 600; font-size: 16px; margin-bottom: 12px; color: var(--text, #eee); }
    .iot-count { font-size: 12px; color: var(--text-dim, #888); font-weight: 400; }
    .iot-room { margin-bottom: 12px; }
    .iot-room-name { font-size: 12px; color: var(--text-dim, #888); margin-bottom: 6px; text-transform: uppercase; }
    .iot-device {
      display: flex; align-items: center; gap: 10px; padding: 8px 10px;
      border-radius: 8px; background: var(--bg, #0b0d14); margin-bottom: 4px;
    }
    .iot-device.on { background: var(--accent, #6c63ff)11; border: 1px solid var(--accent, #6c63ff)33; }
    .iot-icon { font-size: 22px; }
    .iot-dev-info { flex: 1; }
    .iot-dev-name { display: block; font-size: 13px; color: var(--text, #eee); }
    .iot-dev-state { font-size: 11px; color: var(--text-dim, #888); }
    .iot-toggle {
      padding: 4px 12px; border-radius: 12px; border: 1px solid var(--border, #444);
      background: var(--bg2, #1a1a2e); color: var(--text-dim, #888); font-size: 11px; cursor: pointer;
    }
    .iot-toggle.active { background: var(--accent, #6c63ff); color: #fff; border-color: var(--accent, #6c63ff); }
    .iot-config { margin-top: 12px; }
    .iot-config label { display: block; margin: 8px 0 4px; font-size: 12px; color: var(--text-dim, #aaa); }
    .iot-config input {
      width: 100%; padding: 8px; border-radius: 6px; border: 1px solid var(--border, #444);
      background: var(--bg, #0b0d14); color: var(--text, #eee); font-size: 13px; margin-bottom: 4px;
    }
    .iot-save-btn, .iot-refresh {
      width: 100%; padding: 8px; margin-top: 8px; border: none; border-radius: 8px;
      background: var(--accent, #6c63ff); color: #fff; cursor: pointer; font-size: 13px;
    }
    .iot-empty { text-align: center; color: var(--text-dim, #666); padding: 20px; font-size: 13px; }
  `;
  document.head.appendChild(style);
}
