/**
 * Agent 团队面板 — 聊天区右侧实时显示各 Agent 工作状态 + 专长进化
 *
 * 功能：
 *   - 团队执行时自动弹出右侧面板
 *   - 每个 Agent 显示头像+名字+状态+进度
 *   - 专长标签 + 经验条（历史任务数）
 *   - 点击 Agent 可打开独立对话窗口
 *   - 完成后显示各 Agent 的工作成果
 *   - 底部：项目历史时间线
 */

const BASE = '';
let _agentPanelTeamId = null;
let _agentPollTimer = null;
let _panelVisible = false;
let _evolutionData = null;

export function initAgentPanel() {
  _injectPanel();
  _injectStyles();
  // 5 秒轮询检测是否有团队在工作
  setInterval(_checkForActiveTeam, 5000);
  // 加载进化数据（延迟）
  setTimeout(_loadEvolution, 3000);
  // 加载项目时间线（延迟）
  setTimeout(_loadProjectTimeline, 4000);
}

async function _loadEvolution() {
  try {
    const r = await fetch(`${BASE}/api/agents/evolution`);
    const d = await r.json();
    _evolutionData = d.stats || {};
  } catch (e) { /* silent */ }
}

async function _loadProjectTimeline() {
  try {
    const r = await fetch(`${BASE}/api/projects`);
    const d = await r.json();
    const projects = d.projects || [];
    _renderTimeline(projects);
  } catch (e) { /* silent */ }
}

function _renderTimeline(projects) {
  const el = document.getElementById('asp-timeline');
  if (!el) return;
  if (!projects.length) {
    el.innerHTML = '<div class="asp-empty" style="padding:12px">暂无项目记录</div>';
    return;
  }
  el.innerHTML = projects.slice(0, 8).map(p => {
    const date = p.created_at ? new Date(p.created_at * 1000).toLocaleDateString('zh-CN', {month:'short', day:'numeric'}) : '';
    const files = (p.artifacts || []).length;
    const agents = p.agent_count || 0;
    return `
      <div class="asp-project" onclick="window.open('/report/${p.project_id}','_blank')" title="点击查看报告">
        <div class="asp-proj-header">
          <span class="asp-proj-name">${(p.name || '').substring(0, 18)}</span>
          <span class="asp-proj-date">${date}</span>
        </div>
        <div class="asp-proj-meta">${agents}人 · ${files}个文件</div>
      </div>`;
  }).join('');
}

async function _checkForActiveTeam() {
  try {
    const r = await fetch(`${BASE}/api/agents/teams`);
    const d = await r.json();
    const teams = d.teams || [];
    const active = teams.find(t => t.status === 'executing' || t.status === 'planning');
    const done = teams.find(t => t.status === 'done' && t.team_id !== _agentPanelTeamId);

    if (active && active.team_id !== _agentPanelTeamId) {
      _agentPanelTeamId = active.team_id;
      _showPanel();
      _startPoll();
    } else if (done && !_panelVisible) {
      _agentPanelTeamId = done.team_id;
      _showPanel();
      _renderTeam(done);
    }
  } catch (e) { /* silent */ }
}

function _showPanel() {
  const panel = document.getElementById('agent-side-panel');
  if (panel) { panel.classList.add('open'); _panelVisible = true; }
}

function _hidePanel() {
  const panel = document.getElementById('agent-side-panel');
  if (panel) { panel.classList.remove('open'); _panelVisible = false; }
  if (_agentPollTimer) { clearInterval(_agentPollTimer); _agentPollTimer = null; }
}

function _startPoll() {
  if (_agentPollTimer) clearInterval(_agentPollTimer);
  _agentPollTimer = setInterval(async () => {
    if (!_agentPanelTeamId) return;
    try {
      const r = await fetch(`${BASE}/api/agents/team/${_agentPanelTeamId}/status`);
      const d = await r.json();
      _renderTeam(d);
      if (d.status === 'done' || d.status === 'error') {
        clearInterval(_agentPollTimer);
        _agentPollTimer = null;
        if (d.status === 'done') {
          _loadAgentResults();
          _loadProjectTimeline();  // 刷新时间线
          _loadEvolution();        // 刷新进化数据
        }
      }
    } catch (e) { /* silent */ }
  }, 3000);
}

function _renderTeam(data) {
  const list = document.getElementById('asp-agent-list');
  const header = document.getElementById('asp-header-text');
  if (!list || !header) return;

  const agents = data.agents || {};
  const tasks = data.tasks || [];
  const status = data.status || 'idle';
  const doneCount = tasks.filter(t => t.status === 'done').length;

  header.textContent = status === 'done'
    ? `✅ ${data.name || '团队'} 完成！`
    : `👔 ${data.name || '团队'} (${doneCount}/${tasks.length})`;

  const keys = Object.keys(agents);
  list.innerHTML = keys.map(aid => {
    const a = agents[aid];
    const task = tasks.find(t => t.agent_id === aid);
    const taskStatus = task ? task.status : (a.status || 'idle');
    const icon = taskStatus === 'done' ? '✅' : taskStatus === 'working' ? '🔄' : '⏳';
    const cssClass = taskStatus === 'done' ? 'done' : taskStatus === 'working' ? 'working' : '';
    const taskDesc = task ? (task.description || '').substring(0, 30) : '';
    const preview = task?.result || task?.partial_result || '';
    const previewText = preview.substring(0, 80).replace(/[#*\n]/g, ' ');

    // 协作依赖
    const deps = task?.depends_on || [];
    let depsHtml = '';
    if (deps.length) {
      const depNames = deps.map(d => {
        const depAgent = agents[d];
        return depAgent ? depAgent.name : d;
      }).join(', ');
      depsHtml = `<div class="asp-deps">← ${depNames}</div>`;
    }

    // 进化数据
    const evo = _evolutionData?.[aid];
    let evoHtml = '';
    if (evo && evo.tasks_done > 0) {
      const level = Math.min(Math.floor(evo.tasks_done / 3) + 1, 10);
      const stars = '★'.repeat(Math.min(level, 5)) + '☆'.repeat(Math.max(0, 5 - level));
      const expPct = Math.min((evo.tasks_done / 20) * 100, 100);
      evoHtml = `
        <div class="asp-evo">
          <span class="asp-evo-stars">${stars}</span>
          <span class="asp-evo-count">${evo.tasks_done}次</span>
          <div class="asp-evo-bar"><div class="asp-evo-fill" style="width:${expPct}%"></div></div>
        </div>`;
    }

    return `
      <div class="asp-agent ${cssClass}" onclick="window.__agentPanel.chat('${aid}','${(a.name||aid).replace(/'/g,'')}')" title="点击与${a.name}对话">
        <div class="asp-agent-header">
          <span class="asp-avatar">${a.avatar || '🤖'}</span>
          <span class="asp-name">${a.name || aid}</span>
          <span class="asp-status">${icon}</span>
        </div>
        ${evoHtml}
        ${depsHtml}
        ${taskDesc ? `<div class="asp-task">${taskDesc}</div>` : ''}
        ${previewText ? `<div class="asp-result">${previewText}${preview.length > 80 ? '...' : ''}</div>` : ''}
      </div>`;
  }).join('');
}

async function _loadAgentResults() {
  if (!_agentPanelTeamId) return;
  try {
    const r = await fetch(`${BASE}/api/agents/team/${_agentPanelTeamId}/status`);
    const d = await r.json();
    _renderTeam(d);
  } catch (e) { /* silent */ }
}

async function _chatWithAgent(agentId, agentName) {
  const msg = prompt(`对 ${agentName} 说：`);
  if (!msg) return;
  try {
    const r = await fetch(`${BASE}/api/agents/team/${_agentPanelTeamId}/agent/${agentId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    });
    const d = await r.json();
    if (d.ok) {
      alert(`${agentName} 回复：\n\n${d.reply?.substring(0, 500) || '(无回复)'}`);
      _loadAgentResults();
    } else {
      alert(`对话失败：${d.error}`);
    }
  } catch (e) {
    alert(`网络错误：${e.message}`);
  }
}

// 全局暴露
window.__agentPanel = {
  chat: _chatWithAgent,
  show: _showPanel,
  hide: _hidePanel,
  refresh: _loadEvolution,
};

function _injectPanel() {
  const panel = document.createElement('div');
  panel.id = 'agent-side-panel';
  panel.className = 'agent-side-panel';
  panel.innerHTML = `
    <div class="asp-header">
      <span id="asp-header-text">👥 AI 团队</span>
      <button class="asp-close" onclick="window.__agentPanel.hide()">✕</button>
    </div>
    <div class="asp-agent-list" id="asp-agent-list">
      <div class="asp-empty">暂无团队在工作</div>
    </div>
    <div class="asp-section-header" id="asp-timeline-header">📁 项目历史</div>
    <div class="asp-timeline" id="asp-timeline">
      <div class="asp-empty" style="padding:12px">加载中...</div>
    </div>
  `;
  document.body.appendChild(panel);
}

function _injectStyles() {
  if (document.getElementById('agent-panel-styles')) return;
  const style = document.createElement('style');
  style.id = 'agent-panel-styles';
  style.textContent = `
    .agent-side-panel{
      position:fixed;top:50px;right:0;bottom:0;width:280px;
      background:var(--bg-secondary,#1a1a2e);border-left:1px solid var(--border,#333);
      transform:translateX(100%);transition:transform 0.25s ease;z-index:50;
      display:flex;flex-direction:column;overflow:hidden;
    }
    .agent-side-panel.open{transform:translateX(0)}
    .asp-header{
      display:flex;align-items:center;justify-content:space-between;
      padding:10px 12px;border-bottom:1px solid var(--border,#333);
      font-size:13px;font-weight:600;color:var(--text-primary,#eee);flex-shrink:0;
    }
    .asp-close{background:none;border:none;color:var(--text-secondary,#888);cursor:pointer;font-size:14px}
    .asp-agent-list{flex:1;overflow-y:auto;padding:8px;min-height:0}
    .asp-empty{text-align:center;color:var(--text-secondary,#666);padding:30px;font-size:12px}
    .asp-agent{
      padding:8px;margin-bottom:6px;border-radius:8px;cursor:pointer;
      background:var(--bg-primary,#0b0d14);border:1px solid var(--border,#333);
      transition:all 0.15s;
    }
    .asp-agent:hover{border-color:var(--accent,#6c63ff);background:rgba(108,99,255,0.08)}
    .asp-agent.done{border-left:3px solid #22c55e}
    .asp-agent.working{border-left:3px solid #f59e0b}
    .asp-agent-header{display:flex;align-items:center;gap:6px}
    .asp-avatar{font-size:18px}
    .asp-name{flex:1;font-size:12px;font-weight:500;color:var(--text-primary,#eee)}
    .asp-status{font-size:12px}
    .asp-task{font-size:10px;color:var(--text-secondary,#888);margin-top:4px;line-height:1.3}
    .asp-result{font-size:10px;color:var(--text-secondary,#aaa);margin-top:3px;line-height:1.3;
      background:rgba(255,255,255,0.04);padding:4px 6px;border-radius:4px}
    .asp-deps{font-size:9px;color:var(--accent,#6c63ff);margin-top:2px;opacity:0.7}
    /* 进化显示 */
    .asp-evo{display:flex;align-items:center;gap:4px;margin-top:3px}
    .asp-evo-stars{font-size:8px;color:#f59e0b;letter-spacing:-1px}
    .asp-evo-count{font-size:9px;color:var(--text-muted,#666)}
    .asp-evo-bar{flex:1;height:3px;background:rgba(255,255,255,0.06);border-radius:2px;min-width:30px}
    .asp-evo-fill{height:100%;background:linear-gradient(90deg,#6c63ff,#8b5cf6);border-radius:2px;transition:width 0.3s}
    /* 项目时间线 */
    .asp-section-header{
      padding:8px 12px 4px;font-size:11px;font-weight:600;color:var(--text-muted,#666);
      border-top:1px solid var(--border,#333);flex-shrink:0;
    }
    .asp-timeline{overflow-y:auto;padding:4px 8px 8px;max-height:200px}
    .asp-project{
      padding:6px 8px;margin-bottom:4px;border-radius:6px;cursor:pointer;
      background:var(--bg-primary,#0b0d14);border:1px solid var(--border,#222);
      transition:all 0.15s;
    }
    .asp-project:hover{border-color:var(--accent,#6c63ff)}
    .asp-proj-header{display:flex;justify-content:space-between;align-items:center}
    .asp-proj-name{font-size:11px;color:var(--text-primary,#eee);font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px}
    .asp-proj-date{font-size:9px;color:var(--text-muted,#666)}
    .asp-proj-meta{font-size:9px;color:var(--text-secondary,#888);margin-top:2px}
  `;
  document.head.appendChild(style);
}
