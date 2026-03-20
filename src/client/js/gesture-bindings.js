// gesture-bindings.js — Gesture/Expression → Action binding editor (B2)
import { S, fn, getBaseUrl, bus, expressionSystem } from '/js/state.js';

const AVAILABLE_ACTIONS = [
  { id: 'confirm',     label: '确认',       icon: '\u2705' },
  { id: 'cancel',      label: '取消',       icon: '\u274C' },
  { id: 'click',       label: '点击',       icon: '\u{1F5B1}\uFE0F' },
  { id: 'right_click', label: '右键点击',   icon: '\u{1F5B1}\uFE0F' },
  { id: 'start_voice', label: '开始语音',   icon: '\u{1F3A4}' },
  { id: 'scroll_up',   label: '向上滚动',   icon: '\u2B06\uFE0F' },
  { id: 'scroll_down', label: '向下滚动',   icon: '\u2B07\uFE0F' },
  { id: 'undo',        label: '撤销',       icon: '\u21A9\uFE0F' },
  { id: 'redo',        label: '重做',       icon: '\u21AA\uFE0F' },
  { id: 'enter',       label: '回车',       icon: '\u23CE' },
  { id: 'screenshot',  label: '截图',       icon: '\u{1F4F7}' },
  { id: 'escape',      label: 'Escape',    icon: '\u{1F6AA}' },
  { id: 'tab',         label: 'Tab切换',    icon: '\u21B9' },
  { id: 'none',        label: '无动作',     icon: '\u{1F6AB}' },
];

let _container = null;
let _dirty = false;

function getActionLabel(actionId) {
  const a = AVAILABLE_ACTIONS.find(a => a.id === actionId);
  return a ? `${a.icon} ${a.label}` : actionId;
}

function buildActionSelect(currentAction, onChange) {
  const sel = document.createElement('select');
  sel.className = 'gb-action-select';
  for (const a of AVAILABLE_ACTIONS) {
    const opt = document.createElement('option');
    opt.value = a.id;
    opt.textContent = `${a.icon} ${a.label}`;
    if (a.id === currentAction) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.addEventListener('change', () => { _dirty = true; onChange(sel.value); });
  return sel;
}

function renderBindings() {
  if (!_container) return;
  const es = expressionSystem;
  if (!es) {
    _container.innerHTML = '<div class="gb-empty">表情系统未初始化</div>';
    return;
  }

  let html = '';

  // Expression bindings
  html += '<div class="gb-group"><div class="gb-group-title">\u{1F3AD} 面部表情绑定</div>';
  for (const [name, def] of Object.entries(es.expressions || {})) {
    html += `
      <div class="gb-row" data-type="expr" data-name="${name}">
        <span class="gb-gesture-name">${def.label || name}</span>
        <span class="gb-gesture-cat">${def.category || ''}</span>
        <div class="gb-action-slot" data-name="${name}" data-current="${def.action}"></div>
        <label class="gb-enable-label">
          <input type="checkbox" class="gb-enable-cb" data-name="${name}" ${def.enabled ? 'checked' : ''}>
          <span class="gb-enable-slider"></span>
        </label>
      </div>`;
  }
  html += '</div>';

  // Head movement bindings
  html += '<div class="gb-group"><div class="gb-group-title">\u{1F464} 头部动作绑定</div>';
  for (const [name, def] of Object.entries(es.headMovements || {})) {
    html += `
      <div class="gb-row" data-type="head" data-name="${name}">
        <span class="gb-gesture-name">${def.label || name}</span>
        <span class="gb-gesture-cat">head</span>
        <div class="gb-action-slot" data-name="${name}" data-current="${def.action}"></div>
        <label class="gb-enable-label">
          <input type="checkbox" class="gb-enable-cb" data-name="${name}" ${def.enabled ? 'checked' : ''}>
          <span class="gb-enable-slider"></span>
        </label>
      </div>`;
  }
  html += '</div>';

  html += `
    <div class="gb-footer">
      <button class="gb-save-btn" id="gb-save">\u{1F4BE} 保存绑定</button>
      <button class="gb-reset-btn" id="gb-reset">\u21A9\uFE0F 恢复默认</button>
    </div>`;

  _container.innerHTML = html;

  // Hydrate action selects
  _container.querySelectorAll('.gb-action-slot').forEach(slot => {
    const name = slot.dataset.name;
    const current = slot.dataset.current;
    const isExpr = slot.closest('.gb-row').dataset.type === 'expr';
    const select = buildActionSelect(current, (newAction) => {
      if (isExpr && es.expressions[name]) {
        es.expressions[name].action = newAction;
      } else if (!isExpr && es.headMovements[name]) {
        es.headMovements[name].action = newAction;
      }
    });
    slot.appendChild(select);
  });

  // Enable/disable checkboxes
  _container.querySelectorAll('.gb-enable-cb').forEach(cb => {
    cb.addEventListener('change', () => {
      _dirty = true;
      const name = cb.dataset.name;
      const row = cb.closest('.gb-row');
      const isExpr = row.dataset.type === 'expr';
      if (isExpr && es.expressions[name]) {
        es.expressions[name].enabled = cb.checked;
      } else if (!isExpr && es.headMovements[name]) {
        es.headMovements[name].enabled = cb.checked;
      }
    });
  });

  // Save button
  _container.querySelector('#gb-save')?.addEventListener('click', saveBindings);
  _container.querySelector('#gb-reset')?.addEventListener('click', resetBindings);
}

async function saveBindings() {
  const es = expressionSystem;
  if (!es) return;

  const exprConfig = {};
  for (const [name, def] of Object.entries(es.expressions)) {
    exprConfig[name] = { enabled: def.enabled, action: def.action, threshold: def.threshold };
  }
  const headConfig = {};
  for (const [name, def] of Object.entries(es.headMovements)) {
    headConfig[name] = { enabled: def.enabled, action: def.action, threshold: def.threshold };
  }

  try {
    const resp = await fetch(getBaseUrl() + '/api/access/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expression_enabled: es.enabled,
        sensitivity: es.globalSensitivity,
        expressions: exprConfig,
        head_movements: headConfig,
      }),
    });
    if (resp.ok) {
      _dirty = false;
      const saveBtn = _container.querySelector('#gb-save');
      if (saveBtn) {
        saveBtn.textContent = '\u2705 已保存';
        setTimeout(() => { saveBtn.textContent = '\u{1F4BE} 保存绑定'; }, 2000);
      }
    }
  } catch (e) {
    console.warn('Failed to save gesture bindings:', e);
  }
}

async function resetBindings() {
  try {
    await fetch(getBaseUrl() + '/api/access/config/reset', { method: 'POST' });
    const resp = await fetch(getBaseUrl() + '/api/access/config');
    if (resp.ok) {
      const cfg = await resp.json();
      expressionSystem.applyConfig({
        enabled: cfg.expression_enabled || false,
        sensitivity: cfg.sensitivity || 1.0,
        expressions: cfg.expressions || {},
        headMovements: cfg.head_movements || {},
      });
    }
  } catch { /* silent */ }
  _dirty = false;
  renderBindings();
}

export function initGestureBindings() {
  const tabExpr = document.getElementById('tab-expression');
  if (!tabExpr) return;

  // Insert the gesture bindings section before the save/reset buttons at the bottom
  _container = document.createElement('div');
  _container.className = 'gb-container';
  _container.id = 'gesture-bindings-panel';

  const divider = document.createElement('div');
  divider.className = 'settings-group';
  divider.innerHTML = `
    <h3>\u{1F3AE} 手势绑定编辑器</h3>
    <p style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">
      自定义每个表情和头部动作触发的操作。修改后点击「保存绑定」生效。
    </p>
  `;
  divider.appendChild(_container);

  const existingButtons = tabExpr.querySelector('div[style*="display:flex"][style*="gap:8px"][style*="margin-top:8px"]');
  if (existingButtons) {
    tabExpr.insertBefore(divider, existingButtons);
  } else {
    tabExpr.appendChild(divider);
  }

  // Render after expression system is loaded (slight delay)
  setTimeout(renderBindings, 500);

  bus.on('expression:preset_applied', renderBindings);
}
