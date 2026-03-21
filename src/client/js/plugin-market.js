/**
 * 插件市场 — 已安装插件列表 + 启用/禁用管理
 *
 * API: GET /api/plugins, POST /api/plugins/{id}/enable, POST /api/plugins/{id}/disable
 */

const BASE = '';
let _plugins = [];

export function initPluginMarket() {
  _injectPanel();
  _injectStyles();
}

async function _fetchPlugins() {
  try {
    const r = await fetch(`${BASE}/api/plugins`);
    const data = await r.json();
    _plugins = data.plugins || [];
    _renderPlugins();
  } catch (e) {
    console.debug('[Plugins] fetch error:', e);
  }
}

async function _togglePlugin(id, enable) {
  try {
    const action = enable ? 'enable' : 'disable';
    await fetch(`${BASE}/api/plugins/${id}/${action}`, { method: 'POST' });
    await _fetchPlugins();
  } catch (e) {
    alert('操作失败: ' + e.message);
  }
}

function _injectPanel() {
  const container = document.getElementById('plugin-market-container');
  if (container) {
    container.innerHTML = _buildHTML();
    return;
  }
  // 浮动面板
  const panel = document.createElement('div');
  panel.id = 'plugin-panel';
  panel.className = 'plugin-panel';
  panel.style.display = 'none';
  panel.innerHTML = _buildHTML();
  document.body.appendChild(panel);
}

function _buildHTML() {
  return `
    <div class="plugin-header">
      <span>🧩 插件市场</span>
      <button class="plugin-refresh" onclick="window.__plugins.refresh()">🔄</button>
    </div>
    <div class="plugin-search">
      <input type="text" id="plugin-search" placeholder="搜索插件..." oninput="window.__plugins.filter(this.value)">
    </div>
    <div id="plugin-list" class="plugin-list"></div>
  `;
}

function _renderPlugins(filter = '') {
  const list = document.getElementById('plugin-list');
  if (!list) return;

  const filtered = filter
    ? _plugins.filter(p => (p.name + p.description).toLowerCase().includes(filter.toLowerCase()))
    : _plugins;

  if (filtered.length === 0) {
    list.innerHTML = '<div class="plugin-empty">暂无插件</div>';
    return;
  }

  list.innerHTML = filtered.map(p => `
    <div class="plugin-card ${p.enabled ? 'enabled' : 'disabled'}">
      <div class="plugin-icon">${p.icon || '🧩'}</div>
      <div class="plugin-info">
        <div class="plugin-name">${p.name}</div>
        <div class="plugin-desc">${p.description || ''}</div>
        <div class="plugin-meta">
          v${p.version || '1.0'} · ${p.author || 'unknown'}
        </div>
      </div>
      <label class="plugin-toggle">
        <input type="checkbox" ${p.enabled ? 'checked' : ''}
               onchange="window.__plugins.toggle('${p.id}', this.checked)">
        <span class="plugin-slider"></span>
      </label>
    </div>
  `).join('');
}

window.__plugins = {
  refresh: _fetchPlugins,
  toggle: _togglePlugin,
  filter: (q) => _renderPlugins(q),
  show: () => {
    const el = document.getElementById('plugin-panel');
    if (el) {
      el.style.display = el.style.display === 'none' ? 'block' : 'none';
      if (el.style.display === 'block') _fetchPlugins();
    }
  },
};

function _injectStyles() {
  if (document.getElementById('plugin-styles')) return;
  const style = document.createElement('style');
  style.id = 'plugin-styles';
  style.textContent = `
    .plugin-panel {
      position: fixed; top: 60px; right: 16px; width: 360px; max-height: 600px;
      background: var(--bg2, #1a1a2e); border: 1px solid var(--border, #333);
      border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.3);
      z-index: 9999; overflow: hidden;
    }
    .plugin-header {
      padding: 12px 16px; display: flex; justify-content: space-between; align-items: center;
      font-weight: 600; font-size: 16px; color: var(--text, #eee);
      border-bottom: 1px solid var(--border, #333);
    }
    .plugin-refresh { background: none; border: none; font-size: 16px; cursor: pointer; }
    .plugin-search { padding: 8px 16px; }
    .plugin-search input {
      width: 100%; padding: 8px 12px; border-radius: 8px; border: 1px solid var(--border, #444);
      background: var(--bg, #0b0d14); color: var(--text, #eee); font-size: 13px;
    }
    .plugin-list { padding: 8px 16px 16px; overflow-y: auto; max-height: 450px; }
    .plugin-card {
      display: flex; align-items: center; gap: 12px; padding: 10px; margin-bottom: 8px;
      border-radius: 8px; background: var(--bg, #0b0d14); border: 1px solid var(--border, #333);
    }
    .plugin-card.enabled { border-color: var(--accent, #6c63ff)44; }
    .plugin-icon { font-size: 28px; }
    .plugin-info { flex: 1; }
    .plugin-name { font-weight: 500; font-size: 13px; color: var(--text, #eee); }
    .plugin-desc { font-size: 11px; color: var(--text-dim, #888); margin-top: 2px; }
    .plugin-meta { font-size: 10px; color: var(--text-dim, #666); margin-top: 4px; }
    .plugin-empty { text-align: center; color: var(--text-dim, #666); padding: 40px; }
    .plugin-toggle { position: relative; width: 40px; height: 22px; }
    .plugin-toggle input { opacity: 0; width: 0; height: 0; }
    .plugin-slider {
      position: absolute; inset: 0; background: var(--border, #444);
      border-radius: 11px; cursor: pointer; transition: background 0.2s;
    }
    .plugin-slider::before {
      content: ''; position: absolute; width: 18px; height: 18px;
      left: 2px; top: 2px; background: white; border-radius: 50%; transition: transform 0.2s;
    }
    .plugin-toggle input:checked + .plugin-slider { background: var(--accent, #6c63ff); }
    .plugin-toggle input:checked + .plugin-slider::before { transform: translateX(18px); }
  `;
  document.head.appendChild(style);
}
