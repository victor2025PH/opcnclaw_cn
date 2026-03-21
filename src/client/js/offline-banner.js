/**
 * 离线状态指示器 — 网络模式实时显示
 *
 * 在 QR 页面和 app 页面顶部显示网络状态：
 *   🟢 在线（云端 AI）/ 🟡 本地模式（Ollama）/ 🔴 离线
 */

const BASE = '';
let _mode = 'online';
let _pollTimer = null;

export function initOfflineBanner() {
  _injectBanner();
  _injectStyles();
  _checkStatus();
  _pollTimer = setInterval(_checkStatus, 10000); // 10s 轮询
}

async function _checkStatus() {
  try {
    const r = await fetch(`${BASE}/api/system/network-status`);
    const data = await r.json();
    const newMode = data.mode || 'online';
    if (newMode !== _mode) {
      _mode = newMode;
      _updateBanner();
      if (newMode === 'online' && _mode !== 'online') {
        _showToast('已恢复云端连接');
      }
    }
    _mode = newMode;
    _updateBanner();
  } catch (e) {
    _mode = 'offline';
    _updateBanner();
  }
}

function _injectBanner() {
  const banner = document.createElement('div');
  banner.id = 'offline-banner';
  banner.className = 'offline-banner';
  banner.style.display = 'none';
  document.body.prepend(banner);
}

function _updateBanner() {
  const el = document.getElementById('offline-banner');
  if (!el) return;

  if (_mode === 'online') {
    el.style.display = 'none';
    return;
  }

  el.style.display = 'flex';
  if (_mode === 'local') {
    el.className = 'offline-banner local';
    el.innerHTML = '🟡 本地模式 — 使用本地 AI 模型，部分功能受限 <button onclick="this.parentElement.style.display=\'none\'">✕</button>';
  } else {
    el.className = 'offline-banner offline';
    el.innerHTML = '🔴 离线 — 网络不可用，等待恢复 <button onclick="this.parentElement.style.display=\'none\'">✕</button>';
  }
}

function _showToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'offline-toast';
  toast.textContent = '🟢 ' + msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 3000);
}

function _injectStyles() {
  if (document.getElementById('offline-banner-styles')) return;
  const style = document.createElement('style');
  style.id = 'offline-banner-styles';
  style.textContent = `
    .offline-banner {
      position: fixed; top: 0; left: 0; right: 0; z-index: 9998;
      padding: 8px 16px; font-size: 13px; display: flex; align-items: center;
      justify-content: center; gap: 8px;
    }
    .offline-banner.local { background: linear-gradient(90deg, #f59e0b22, #f59e0b11); color: #f59e0b; border-bottom: 1px solid #f59e0b33; }
    .offline-banner.offline { background: linear-gradient(90deg, #ef444422, #ef444411); color: #ef4444; border-bottom: 1px solid #ef444433; }
    .offline-banner button { background: none; border: none; color: inherit; cursor: pointer; font-size: 14px; margin-left: 8px; }
    .offline-toast {
      position: fixed; top: 20px; right: 20px; z-index: 10001;
      background: #22c55e; color: #fff; padding: 10px 20px; border-radius: 8px;
      font-size: 14px; opacity: 0; transform: translateX(100px); transition: all 0.3s;
    }
    .offline-toast.show { opacity: 1; transform: translateX(0); }
  `;
  document.head.appendChild(style);
}
