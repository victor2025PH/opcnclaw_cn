/**
 * Web Push 订阅管理
 *
 * 功能：请求通知权限、订阅推送、发送测试通知
 */

const BASE = '';

export function initPushManager() {
  _injectButton();
  _injectStyles();
}

async function _requestPermission() {
  if (!('Notification' in window)) {
    alert('此浏览器不支持推送通知');
    return;
  }

  const perm = await Notification.requestPermission();
  if (perm !== 'granted') {
    _showGuide();
    return;
  }

  await _subscribe();
}

async function _subscribe() {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: _urlBase64ToUint8Array(
        // 需要替换为实际 VAPID public key
        'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkCs7U2QJzTBB8XtPb88Zv9R5LXwFLMb4Xz1tFcYA'
      ),
    });

    const r = await fetch(`${BASE}/api/push/subscribe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subscription: sub.toJSON(),
        types: ['wechat', 'system', 'workflow'],
      }),
    });
    const data = await r.json();
    if (data.ok) {
      _updateButton('subscribed');
      _showToast('推送通知已开启');
    }
  } catch (e) {
    console.error('[Push] subscribe error:', e);
    _showToast('订阅失败: ' + e.message);
  }
}

async function _testPush() {
  try {
    await fetch(`${BASE}/api/push/test`, { method: 'POST' });
    _showToast('测试推送已发送');
  } catch (e) {
    _showToast('发送失败');
  }
}

function _injectButton() {
  // QR 页面的快捷操作区
  const quickOps = document.querySelector('.quick-ops, .qop-grid');
  if (quickOps) {
    const btn = document.createElement('button');
    btn.id = 'push-btn';
    btn.className = 'push-btn';
    btn.innerHTML = '🔔 开启通知';
    btn.onclick = _requestPermission;
    quickOps.appendChild(btn);
  }

  // header 区域也添加小按钮
  const headerRight = document.querySelector('.header-right');
  if (headerRight) {
    const btn = document.createElement('button');
    btn.id = 'push-icon-btn';
    btn.className = 'push-icon-btn';
    btn.title = '推送通知';
    btn.textContent = '🔔';
    btn.onclick = _requestPermission;
    headerRight.appendChild(btn);
  }

  // 检查现有订阅状态
  if ('Notification' in window && Notification.permission === 'granted') {
    _updateButton('subscribed');
  }
}

function _updateButton(state) {
  const btn = document.getElementById('push-btn');
  const iconBtn = document.getElementById('push-icon-btn');
  if (state === 'subscribed') {
    if (btn) { btn.innerHTML = '🔔 通知已开启'; btn.onclick = _testPush; }
    if (iconBtn) { iconBtn.style.color = 'var(--accent, #6c63ff)'; }
  }
}

function _showGuide() {
  alert('通知权限被拒绝。\n\n请在浏览器设置中允许此网站发送通知：\n设置 → 隐私和安全 → 网站设置 → 通知');
}

function _showToast(msg) {
  const toast = document.createElement('div');
  toast.className = 'push-toast';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 2500);
}

function _urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
}

function _injectStyles() {
  if (document.getElementById('push-styles')) return;
  const style = document.createElement('style');
  style.id = 'push-styles';
  style.textContent = `
    .push-btn {
      padding: 8px 16px; border-radius: 8px; border: 1px solid var(--border, #444);
      background: var(--bg2, #1a1a2e); color: var(--text, #eee); cursor: pointer; font-size: 13px;
    }
    .push-btn:hover { background: var(--accent, #6c63ff)22; }
    .push-icon-btn {
      width: 32px; height: 32px; border-radius: 50%; border: none;
      background: none; font-size: 18px; cursor: pointer;
    }
    .push-toast {
      position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%) translateY(20px);
      background: var(--bg2, #1a1a2e); color: var(--text, #eee); padding: 10px 20px;
      border-radius: 8px; border: 1px solid var(--border, #333); font-size: 13px;
      opacity: 0; transition: all 0.3s; z-index: 10001;
    }
    .push-toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  `;
  document.head.appendChild(style);
}
