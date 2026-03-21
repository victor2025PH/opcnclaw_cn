/**
 * 工作流可视化编辑器 — 拖拽画布 + 节点连线
 *
 * 纯 CSS+JS 实现（无 npm 依赖）：
 *   - 左侧工具栏：节点类型拖出
 *   - 中间画布：拖拽定位 + SVG 连线
 *   - 右侧属性面板：选中节点编辑参数
 *   - 预置模板一键加载
 */

const BASE = '';
let _nodes = [];
let _connections = [];
let _selectedNode = null;
let _nextId = 1;
let _dragging = null;
let _connecting = null; // {fromId, fromPort}

// ── 节点类型定义 ─────────────────────────────────────────────

const NODE_TYPES = {
  cron_trigger:  { label: '定时触发', icon: '🕐', category: 'trigger', color: '#f59e0b', ports: { out: 1 } },
  event_trigger: { label: '事件触发', icon: '📡', category: 'trigger', color: '#f59e0b', ports: { out: 1 } },
  condition:     { label: '条件判断', icon: '❓', category: 'logic',   color: '#8b5cf6', ports: { in: 1, out: 2 } },
  wechat_send:   { label: '发微信',   icon: '💬', category: 'action',  color: '#22c55e', ports: { in: 1, out: 1 } },
  tts_speak:     { label: 'TTS播报',  icon: '🔊', category: 'action',  color: '#22c55e', ports: { in: 1, out: 1 } },
  screenshot:    { label: '截屏',     icon: '📷', category: 'action',  color: '#22c55e', ports: { in: 1, out: 1 } },
  open_app:      { label: '打开应用', icon: '🚀', category: 'action',  color: '#22c55e', ports: { in: 1, out: 1 } },
  ai_generate:   { label: 'AI生成',   icon: '🤖', category: 'ai',      color: '#6c63ff', ports: { in: 1, out: 1 } },
  publish_moment:{ label: '发朋友圈', icon: '📢', category: 'action',  color: '#22c55e', ports: { in: 1, out: 1 } },
  delay:         { label: '延迟',     icon: '⏳', category: 'logic',   color: '#8b5cf6', ports: { in: 1, out: 1 } },
};

// ── 预置模板 ─────────────────────────────────────────────────

const TEMPLATES = {
  daily_report: {
    name: '每日早报',
    nodes: [
      { id: 'n1', type: 'cron_trigger', x: 50, y: 100, params: { cron: '0 8 * * *', label: '每天8:00' } },
      { id: 'n2', type: 'ai_generate', x: 250, y: 100, params: { prompt: '生成今日天气+新闻摘要，简洁50字' } },
      { id: 'n3', type: 'tts_speak', x: 450, y: 100, params: {} },
    ],
    connections: [{ from: 'n1', to: 'n2' }, { from: 'n2', to: 'n3' }],
  },
  auto_reply: {
    name: '微信自动回复',
    nodes: [
      { id: 'n1', type: 'event_trigger', x: 50, y: 100, params: { event: 'wechat_message' } },
      { id: 'n2', type: 'condition', x: 250, y: 100, params: { condition: '关键词匹配' } },
      { id: 'n3', type: 'ai_generate', x: 450, y: 60, params: { prompt: '根据消息内容生成智能回复' } },
      { id: 'n4', type: 'wechat_send', x: 650, y: 60, params: {} },
    ],
    connections: [{ from: 'n1', to: 'n2' }, { from: 'n2', to: 'n3' }, { from: 'n3', to: 'n4' }],
  },
  moment_publish: {
    name: '朋友圈定时发布',
    nodes: [
      { id: 'n1', type: 'cron_trigger', x: 50, y: 100, params: { cron: '0 12 * * *', label: '每天12:00' } },
      { id: 'n2', type: 'ai_generate', x: 250, y: 100, params: { prompt: '生成一条有趣的朋友圈文案' } },
      { id: 'n3', type: 'publish_moment', x: 450, y: 100, params: {} },
    ],
    connections: [{ from: 'n1', to: 'n2' }, { from: 'n2', to: 'n3' }],
  },
};

// ── 初始化 ───────────────────────────────────────────────────

export function initWorkflowEditor() {
  _injectEditor();
  _injectStyles();
}

function _injectEditor() {
  // 在 admin 页面查找工作流 tab 内容区
  const container = document.getElementById('workflow-editor-container') ||
                    document.getElementById('tab-workflows');
  if (!container) {
    // 创建浮动面板
    const panel = document.createElement('div');
    panel.id = 'wf-editor';
    panel.className = 'wf-editor';
    panel.style.display = 'none';
    panel.innerHTML = _buildEditorHTML();
    document.body.appendChild(panel);
    return;
  }
  container.innerHTML = _buildEditorHTML();
  _bindEvents();
}

function _buildEditorHTML() {
  const typeButtons = Object.entries(NODE_TYPES).map(([type, def]) => `
    <div class="wf-type-item" draggable="true" data-type="${type}">
      <span class="wf-type-icon">${def.icon}</span>
      <span class="wf-type-label">${def.label}</span>
    </div>
  `).join('');

  const templateButtons = Object.entries(TEMPLATES).map(([key, t]) =>
    `<button class="wf-tpl-btn" onclick="window.__wfEditor.loadTemplate('${key}')">${t.name}</button>`
  ).join('');

  return `
    <div class="wf-toolbar">
      <div class="wf-toolbar-section">
        <div class="wf-section-title">节点</div>
        ${typeButtons}
      </div>
      <div class="wf-toolbar-section">
        <div class="wf-section-title">模板</div>
        ${templateButtons}
      </div>
    </div>
    <div class="wf-canvas" id="wf-canvas">
      <svg class="wf-svg" id="wf-svg"></svg>
      <div class="wf-nodes" id="wf-nodes"></div>
    </div>
    <div class="wf-props" id="wf-props">
      <div class="wf-props-empty">选择节点查看属性</div>
    </div>
    <div class="wf-actions">
      <button onclick="window.__wfEditor.save()">💾 保存</button>
      <button onclick="window.__wfEditor.run()">▶ 运行</button>
      <button onclick="window.__wfEditor.clear()">🗑 清空</button>
    </div>
  `;
}

function _bindEvents() {
  // 拖拽节点类型到画布
  document.querySelectorAll('.wf-type-item').forEach(el => {
    el.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', el.dataset.type);
    });
  });

  const canvas = document.getElementById('wf-canvas');
  if (canvas) {
    canvas.addEventListener('dragover', e => e.preventDefault());
    canvas.addEventListener('drop', e => {
      e.preventDefault();
      const type = e.dataTransfer.getData('text/plain');
      if (type && NODE_TYPES[type]) {
        const rect = canvas.getBoundingClientRect();
        _addNode(type, e.clientX - rect.left - 60, e.clientY - rect.top - 20);
      }
    });
  }
}

// ── 节点管理 ─────────────────────────────────────────────────

function _addNode(type, x, y, params = {}, id = null) {
  const def = NODE_TYPES[type];
  if (!def) return;

  const nodeId = id || `n${_nextId++}`;
  const node = { id: nodeId, type, x, y, params: { ...params } };
  _nodes.push(node);
  _renderNodes();
  return node;
}

function _renderNodes() {
  const container = document.getElementById('wf-nodes');
  const svg = document.getElementById('wf-svg');
  if (!container || !svg) return;

  container.innerHTML = _nodes.map(n => {
    const def = NODE_TYPES[n.type];
    const selected = _selectedNode === n.id ? ' selected' : '';
    return `
      <div class="wf-node${selected}" id="wfn-${n.id}"
           style="left:${n.x}px;top:${n.y}px;border-color:${def.color}"
           onmousedown="window.__wfEditor.startDrag(event,'${n.id}')"
           onclick="window.__wfEditor.selectNode('${n.id}')">
        <span class="wf-node-icon">${def.icon}</span>
        <span class="wf-node-label">${n.params.label || def.label}</span>
        ${def.ports.in ? `<div class="wf-port in" data-node="${n.id}" data-port="in"></div>` : ''}
        ${def.ports.out ? `<div class="wf-port out" data-node="${n.id}" data-port="out"
          onmousedown="event.stopPropagation();window.__wfEditor.startConnect(event,'${n.id}')"></div>` : ''}
      </div>`;
  }).join('');

  // 渲染连线
  svg.innerHTML = _connections.map(c => {
    const from = _nodes.find(n => n.id === c.from);
    const to = _nodes.find(n => n.id === c.to);
    if (!from || !to) return '';
    const x1 = from.x + 140, y1 = from.y + 25;
    const x2 = to.x, y2 = to.y + 25;
    const cx = (x1 + x2) / 2;
    return `<path d="M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}"
              class="wf-connection" data-from="${c.from}" data-to="${c.to}"/>`;
  }).join('');
}

// ── 全局暴露 ─────────────────────────────────────────────────

window.__wfEditor = {
  startDrag: (e, nodeId) => {
    if (e.target.classList.contains('wf-port')) return;
    _dragging = { nodeId, startX: e.clientX, startY: e.clientY };
    const node = _nodes.find(n => n.id === nodeId);
    if (!node) return;
    const ox = node.x, oy = node.y;

    const onMove = (e2) => {
      node.x = ox + (e2.clientX - _dragging.startX);
      node.y = oy + (e2.clientY - _dragging.startY);
      _renderNodes();
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      _dragging = null;
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  },

  startConnect: (e, fromId) => {
    _connecting = { fromId };
    const onUp = (e2) => {
      document.removeEventListener('mouseup', onUp);
      // 查找目标节点
      const target = e2.target.closest('.wf-node');
      if (target) {
        const toId = target.id.replace('wfn-', '');
        if (toId !== fromId) {
          _connections.push({ from: fromId, to: toId });
          _renderNodes();
        }
      }
      _connecting = null;
    };
    document.addEventListener('mouseup', onUp);
  },

  selectNode: (nodeId) => {
    _selectedNode = nodeId;
    _renderNodes();
    _renderProps(nodeId);
  },

  loadTemplate: (key) => {
    const tpl = TEMPLATES[key];
    if (!tpl) return;
    _nodes = [];
    _connections = [];
    _nextId = 1;
    for (const n of tpl.nodes) {
      _addNode(n.type, n.x, n.y, n.params, n.id);
    }
    _connections = [...tpl.connections];
    _renderNodes();
  },

  save: async () => {
    try {
      const data = {
        name: prompt('工作流名称：') || '未命名',
        nodes: _nodes.map(n => ({ ...n })),
        connections: _connections,
        trigger: _nodes.find(n => n.type.includes('trigger'))?.params || {},
      };
      const r = await fetch(`${BASE}/api/workflows`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const d = await r.json();
      alert(d.ok ? '保存成功' : '保存失败: ' + (d.error || ''));
    } catch (e) { alert('保存失败: ' + e.message); }
  },

  run: async () => {
    alert('请先保存工作流，然后在工作流列表中手动执行');
  },

  clear: () => {
    if (!confirm('确定清空画布？')) return;
    _nodes = []; _connections = []; _selectedNode = null; _nextId = 1;
    _renderNodes();
    const props = document.getElementById('wf-props');
    if (props) props.innerHTML = '<div class="wf-props-empty">选择节点查看属性</div>';
  },

  show: () => {
    const el = document.getElementById('wf-editor');
    if (el) {
      el.style.display = el.style.display === 'none' ? 'flex' : 'none';
      if (el.style.display === 'flex') _bindEvents();
    }
  },
};

// ── 属性面板 ─────────────────────────────────────────────────

function _renderProps(nodeId) {
  const props = document.getElementById('wf-props');
  const node = _nodes.find(n => n.id === nodeId);
  if (!props || !node) return;

  const def = NODE_TYPES[node.type];
  let fieldsHTML = '';

  if (node.type === 'cron_trigger') {
    fieldsHTML = `
      <label>Cron 表达式</label>
      <input value="${node.params.cron || '0 8 * * *'}" onchange="window.__wfEditor._setProp('${nodeId}','cron',this.value)">
      <div class="wf-preset-crons">
        <button onclick="window.__wfEditor._setProp('${nodeId}','cron','0 8 * * *')">每天8:00</button>
        <button onclick="window.__wfEditor._setProp('${nodeId}','cron','0 12 * * *')">每天12:00</button>
        <button onclick="window.__wfEditor._setProp('${nodeId}','cron','0 18 * * 1-5')">工作日18:00</button>
        <button onclick="window.__wfEditor._setProp('${nodeId}','cron','*/30 * * * *')">每30分钟</button>
      </div>`;
  } else if (node.type === 'ai_generate') {
    fieldsHTML = `
      <label>AI Prompt</label>
      <textarea rows="4" onchange="window.__wfEditor._setProp('${nodeId}','prompt',this.value)">${node.params.prompt || ''}</textarea>`;
  } else if (node.type === 'wechat_send') {
    fieldsHTML = `
      <label>联系人</label>
      <input value="${node.params.contact || ''}" onchange="window.__wfEditor._setProp('${nodeId}','contact',this.value)">
      <label>消息模板</label>
      <textarea rows="3" onchange="window.__wfEditor._setProp('${nodeId}','template',this.value)">${node.params.template || '{content}'}</textarea>`;
  } else if (node.type === 'delay') {
    fieldsHTML = `
      <label>延迟秒数</label>
      <input type="number" value="${node.params.seconds || 5}" onchange="window.__wfEditor._setProp('${nodeId}','seconds',+this.value)">`;
  } else if (node.type === 'condition') {
    fieldsHTML = `
      <label>条件类型</label>
      <select onchange="window.__wfEditor._setProp('${nodeId}','condition',this.value)">
        <option ${node.params.condition==='关键词匹配'?'selected':''}>关键词匹配</option>
        <option ${node.params.condition==='时间段'?'selected':''}>时间段</option>
        <option ${node.params.condition==='联系人白名单'?'selected':''}>联系人白名单</option>
      </select>`;
  } else {
    fieldsHTML = `<label>标签</label>
      <input value="${node.params.label || def.label}" onchange="window.__wfEditor._setProp('${nodeId}','label',this.value)">`;
  }

  props.innerHTML = `
    <div class="wf-props-header">${def.icon} ${def.label}</div>
    <div class="wf-props-body">${fieldsHTML}</div>
    <button class="wf-delete-btn" onclick="window.__wfEditor._deleteNode('${nodeId}')">🗑 删除节点</button>
  `;
}

window.__wfEditor._setProp = (nodeId, key, value) => {
  const node = _nodes.find(n => n.id === nodeId);
  if (node) { node.params[key] = value; _renderNodes(); }
};

window.__wfEditor._deleteNode = (nodeId) => {
  _nodes = _nodes.filter(n => n.id !== nodeId);
  _connections = _connections.filter(c => c.from !== nodeId && c.to !== nodeId);
  _selectedNode = null;
  _renderNodes();
  const props = document.getElementById('wf-props');
  if (props) props.innerHTML = '<div class="wf-props-empty">选择节点查看属性</div>';
};

// ── 样式 ─────────────────────────────────────────────────────

function _injectStyles() {
  if (document.getElementById('wf-editor-styles')) return;
  const style = document.createElement('style');
  style.id = 'wf-editor-styles';
  style.textContent = `
    .wf-editor {
      position: fixed; inset: 60px 16px 16px; z-index: 9998;
      display: flex; gap: 0; background: var(--bg, #0b0d14); border: 1px solid var(--border, #333);
      border-radius: 12px; overflow: hidden;
    }
    .wf-toolbar {
      width: 160px; background: var(--bg2, #1a1a2e); padding: 12px; overflow-y: auto;
      border-right: 1px solid var(--border, #333);
    }
    .wf-section-title { font-size: 11px; color: var(--text-dim, #888); margin: 8px 0 4px; text-transform: uppercase; }
    .wf-type-item {
      display: flex; align-items: center; gap: 6px; padding: 6px 8px;
      border-radius: 6px; cursor: grab; font-size: 12px; color: var(--text, #eee); margin: 2px 0;
    }
    .wf-type-item:hover { background: var(--bg3, #252542); }
    .wf-type-icon { font-size: 16px; }
    .wf-tpl-btn {
      display: block; width: 100%; padding: 6px; margin: 4px 0; border: 1px dashed var(--border, #444);
      border-radius: 6px; background: none; color: var(--text, #eee); cursor: pointer; font-size: 11px;
    }
    .wf-tpl-btn:hover { background: var(--accent, #6c63ff)22; }
    .wf-canvas {
      flex: 1; position: relative; overflow: hidden; background:
        repeating-linear-gradient(0deg, transparent, transparent 19px, var(--border, #222) 19px, var(--border, #222) 20px),
        repeating-linear-gradient(90deg, transparent, transparent 19px, var(--border, #222) 19px, var(--border, #222) 20px);
    }
    .wf-svg { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
    .wf-connection { fill: none; stroke: var(--accent, #6c63ff); stroke-width: 2; }
    .wf-nodes { position: absolute; inset: 0; }
    .wf-node {
      position: absolute; width: 140px; padding: 8px 10px;
      background: var(--bg2, #1a1a2e); border: 2px solid var(--border, #444);
      border-radius: 8px; cursor: move; font-size: 12px; color: var(--text, #eee);
      display: flex; align-items: center; gap: 6px; user-select: none;
    }
    .wf-node.selected { box-shadow: 0 0 0 2px var(--accent, #6c63ff); }
    .wf-node-icon { font-size: 18px; }
    .wf-port {
      position: absolute; width: 10px; height: 10px; border-radius: 50%;
      background: var(--accent, #6c63ff); cursor: crosshair;
    }
    .wf-port.in { left: -5px; top: 50%; transform: translateY(-50%); }
    .wf-port.out { right: -5px; top: 50%; transform: translateY(-50%); }
    .wf-props {
      width: 220px; background: var(--bg2, #1a1a2e); padding: 12px; overflow-y: auto;
      border-left: 1px solid var(--border, #333);
    }
    .wf-props-header { font-weight: 600; margin-bottom: 10px; font-size: 14px; }
    .wf-props-empty { color: var(--text-dim, #666); font-size: 13px; text-align: center; padding: 40px 0; }
    .wf-props label { display: block; font-size: 11px; color: var(--text-dim, #aaa); margin: 8px 0 4px; }
    .wf-props input, .wf-props textarea, .wf-props select {
      width: 100%; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--border, #444);
      background: var(--bg, #0b0d14); color: var(--text, #eee); font-size: 12px;
    }
    .wf-preset-crons { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
    .wf-preset-crons button {
      padding: 2px 6px; border: 1px solid var(--border, #444); border-radius: 4px;
      background: none; color: var(--text-dim, #aaa); font-size: 10px; cursor: pointer;
    }
    .wf-delete-btn {
      width: 100%; padding: 6px; margin-top: 12px; border: 1px solid #ef4444;
      border-radius: 6px; background: none; color: #ef4444; cursor: pointer; font-size: 12px;
    }
    .wf-actions {
      position: absolute; bottom: 12px; left: 50%; transform: translateX(-50%);
      display: flex; gap: 8px; z-index: 1;
    }
    .wf-actions button {
      padding: 8px 16px; border-radius: 8px; border: none;
      background: var(--accent, #6c63ff); color: #fff; cursor: pointer; font-size: 13px;
    }
  `;
  document.head.appendChild(style);
}
