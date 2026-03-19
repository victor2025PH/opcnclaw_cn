import { S, fn, dom, t, $, $$, getBaseUrl } from '/js/state.js';

/* ══════════════════════════════════════════════════════════════
   技能中心 + 使用统计 + 自动更新  (Skills Center + Stats + Updater)
   ══════════════════════════════════════════════════════════════ */

// ── 数据缓存 ─────────────────────────────────────────────────
let _skillsData = null;       // { categories: [...], total: N }
let _statsData  = null;       // { top: [...], recent: [...], summary: {...} }
let _activeCat  = '__all__';  // 当前选中分类
let _searchQ    = '';         // 当前搜索词

// 技能图标映射（按分类）
const CAT_ICONS = {
  '01_daily_tools':    '📅',
  '02_weather_travel': '🌤️',
  '04_finance':        '💰',
  '05_health':         '💊',
  '06_kitchen':        '🍳',
  '07_learning':       '📚',
  '08_entertainment':  '🎮',
  '09_productivity':   '💼',
  '10_life_services':  '🏠',
  '11_tech_help':      '💻',
  '17_creative':       '🎨',
};

// 技能卡片默认图标（按技能 ID 首字母）
function skillIcon(skill) {
  return CAT_ICONS[skill.category] || '🧩';
}

// ── 数据加载 ─────────────────────────────────────────────────
async function loadSkillsData(forceReload = false) {
  if (_skillsData && !forceReload) return _skillsData;
  try {
    const BASE = getBaseUrl();
    const [sk, st] = await Promise.all([
      fetch(BASE + '/api/skills').then(r => r.json()).catch(() => null),
      fetch(BASE + '/api/stats/skills').then(r => r.json()).catch(() => null),
    ]);
    _skillsData = sk || { categories: [], total: 0 };
    _statsData  = st || { top: [], recent: [], summary: {} };
    return _skillsData;
  } catch (e) {
    console.warn('技能数据加载失败', e);
    return { categories: [], total: 0 };
  }
}

// ── 打开技能中心 ─────────────────────────────────────────────
async function openSkillsCenter() {
  const el = document.getElementById('skills-center');
  el.classList.remove('hidden');
  document.getElementById('sc-search').value = '';
  _searchQ = '';
  _activeCat = '__all__';

  await loadSkillsData();
  renderSkillsCenter();
  updateStatsBar();
  renderRecentAndHot();
  renderCatChips();
  renderSkillGrid();

  document.getElementById('sc-search').focus();
}

function closeSkillsCenter() {
  document.getElementById('skills-center').classList.add('hidden');
}

// ── 统计栏 ───────────────────────────────────────────────────
function updateStatsBar() {
  const sum = _statsData?.summary || {};
  document.getElementById('sc-stat-total').textContent = _skillsData?.total || 0;
  document.getElementById('sc-stat-today').textContent = sum.today_calls ?? 0;
  document.getElementById('sc-stat-used').textContent  = sum.unique_skills_used ?? 0;
  document.getElementById('sc-total-badge').textContent = `共 ${_skillsData?.total || 0} 个`;
}

// ── 推荐区 ───────────────────────────────────────────────────
function renderRecentAndHot() {
  const recent = _statsData?.recent || [];
  const top    = (_statsData?.top || []).slice(0, 6);

  function allSkills() {
    return (_skillsData?.categories || []).flatMap(c => c.skills || []);
  }

  function makeRecommendCard(skillId) {
    const all = allSkills();
    const skill = all.find(s => s.id === skillId);
    if (!skill) return null;
    const card = document.createElement('div');
    card.className = 'sc-recommend-card';
    card.innerHTML = `
      <div class="rc-icon">${skillIcon(skill)}</div>
      <div class="rc-name">${skill.name_zh}</div>
      <div class="rc-desc">${skill.description || ''}</div>
    `;
    card.onclick = () => openSkillDetail(skill);
    return card;
  }

  // 最近使用
  const recentSection = document.getElementById('sc-recent-section');
  const recentRow = document.getElementById('sc-recent-row');
  recentRow.innerHTML = '';
  if (recent.length > 0) {
    recentSection.style.display = '';
    recent.forEach(id => {
      const card = makeRecommendCard(id);
      if (card) recentRow.appendChild(card);
    });
  } else {
    recentSection.style.display = 'none';
  }

  // 热门
  const hotSection = document.getElementById('sc-hot-section');
  const hotRow = document.getElementById('sc-hot-row');
  hotRow.innerHTML = '';
  if (top.length > 0) {
    hotSection.style.display = '';
    top.forEach(({ skill_id }) => {
      const card = makeRecommendCard(skill_id);
      if (card) hotRow.appendChild(card);
    });
  } else {
    hotSection.style.display = 'none';
  }
}

// ── 分类筛选 chips ───────────────────────────────────────────
function renderCatChips() {
  const cats = _skillsData?.categories || [];
  const wrap = document.getElementById('sc-cat-chips');
  wrap.innerHTML = '';

  // "全部" chip
  const allChip = document.createElement('button');
  allChip.className = `sc-chip ${_activeCat === '__all__' ? 'active' : ''}`;
  const totalCount = cats.reduce((s, c) => s + (c.skills?.length || 0), 0);
  allChip.innerHTML = `全部 <span class="sc-chip-badge">${totalCount}</span>`;
  allChip.onclick = () => { _activeCat = '__all__'; renderCatChips(); renderSkillGrid(); };
  wrap.appendChild(allChip);

  cats.forEach(cat => {
    const chip = document.createElement('button');
    chip.className = `sc-chip ${_activeCat === cat.id ? 'active' : ''}`;
    chip.innerHTML = `${cat.name || cat.id} <span class="sc-chip-badge">${cat.skills?.length || 0}</span>`;
    chip.onclick = () => { _activeCat = cat.id; renderCatChips(); renderSkillGrid(); };
    wrap.appendChild(chip);
  });
}

// ── 技能网格 ─────────────────────────────────────────────────
function renderSkillGrid() {
  const grid = document.getElementById('sc-grid');
  const noResult = document.getElementById('sc-no-result');
  const listTitle = document.getElementById('sc-list-title');
  grid.innerHTML = '';

  const cats = _skillsData?.categories || [];
  const q = _searchQ.toLowerCase().trim();

  let skills = [];
  if (_activeCat === '__all__') {
    skills = cats.flatMap(c => c.skills || []);
  } else {
    const cat = cats.find(c => c.id === _activeCat);
    skills = cat?.skills || [];
    listTitle.textContent = cat?.name || '技能列表';
  }

  if (q) {
    skills = skills.filter(s =>
      s.name_zh?.includes(q) ||
      s.description?.includes(q) ||
      s.trigger_words?.some(tw => tw.includes(q)) ||
      s.id?.includes(q)
    );
    listTitle.textContent = `搜索"${q}"`;
  } else if (_activeCat === '__all__') {
    listTitle.textContent = '全部技能';
  }

  // 热度数据映射
  const heatMap = {};
  (_statsData?.top || []).forEach(({ skill_id, heat_score }) => {
    heatMap[skill_id] = heat_score;
  });

  if (skills.length === 0) {
    noResult.classList.remove('hidden');
  } else {
    noResult.classList.add('hidden');
    skills.forEach(skill => {
      const card = createSkillCard(skill, heatMap[skill.id] || 0);
      grid.appendChild(card);
    });
  }
}

function createSkillCard(skill, heatScore) {
  const card = document.createElement('div');
  card.className = 'sc-card';

  // 热度点（最多5个）
  const maxHeat = 5;
  const heatLevel = Math.min(Math.round(heatScore), maxHeat);
  const dots = Array.from({ length: maxHeat }, (_, i) =>
    `<span class="heat-dot${i < heatLevel ? ' on' : ''}"></span>`
  ).join('');

  const skillType = skill.handler ? 'code' : 'prompt';
  const typeLabel = skillType === 'code' ? '精确' : 'AI增强';

  card.innerHTML = `
    <span class="sc-card-type ${skillType}">${typeLabel}</span>
    <div class="sc-card-icon">${skillIcon(skill)}</div>
    <div class="sc-card-name">${skill.name_zh}</div>
    <div class="sc-card-desc">${skill.description || ''}</div>
    ${heatLevel > 0 ? `
    <div class="sc-card-usage">
      <div class="heat-dots">${dots}</div>
      <span>热度</span>
    </div>` : ''}
  `;
  card.onclick = () => openSkillDetail(skill);
  return card;
}

// ── 技能详情 ─────────────────────────────────────────────────
function openSkillDetail(skill) {
  document.getElementById('sc-detail-icon').textContent = skillIcon(skill);
  document.getElementById('sc-detail-title').textContent = skill.name_zh;
  document.getElementById('sc-detail-cat').textContent =
    `分类：${(_skillsData?.categories || []).find(c => c.id === skill.category)?.name || skill.category}`;
  document.getElementById('sc-detail-desc').textContent =
    skill.description || '暂无描述';

  // 示例
  const exList = document.getElementById('sc-detail-examples');
  exList.innerHTML = '';
  (skill.examples || []).forEach(ex => {
    const li = document.createElement('li');
    li.textContent = ex;
    li.onclick = () => {
      closeSkillDetail();
      closeSkillsCenter();
      // 发送到输入框
      const inp = document.getElementById('msg-input');
      if (inp) {
        inp.value = ex;
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        inp.focus();
      }
    };
    exList.appendChild(li);
  });

  // 触发词
  const triggers = document.getElementById('sc-detail-triggers');
  triggers.innerHTML = (skill.trigger_words || []).slice(0, 12).map(tw =>
    `<span class="sc-tag">${tw}</span>`
  ).join('');

  document.getElementById('sc-detail-overlay').classList.remove('hidden');
}

function closeSkillDetail() {
  document.getElementById('sc-detail-overlay').classList.add('hidden');
}

// ── 首页推荐区 ───────────────────────────────────────────────
async function loadWelcomeRecommend() {
  try {
    await loadSkillsData();
    const recommendArea = document.getElementById('skill-recommend-area');
    const recommendRow  = document.getElementById('skill-recommend-row');
    if (!recommendArea || !recommendRow) return;

    // 取热门+最近各几个，去重
    const hotIds    = (_statsData?.top || []).slice(0, 4).map(s => s.skill_id);
    const recentIds = (_statsData?.recent || []).slice(0, 2);
    const ids = [...new Set([...recentIds, ...hotIds])].slice(0, 6);

    const allSkills = (_skillsData?.categories || []).flatMap(c => c.skills || []);

    // 如果没有使用记录，展示默认推荐
    const defaultIds = ['time_now', 'calc_basic', 'weather_now', 'exchange_rate', 'mortgage_equal', 'blessing_birthday'];
    const showIds = ids.length > 0 ? ids : defaultIds;

    recommendRow.innerHTML = '';
    showIds.forEach(id => {
      const skill = allSkills.find(s => s.id === id);
      if (!skill) return;
      const card = document.createElement('div');
      card.className = 'sc-recommend-card';
      card.innerHTML = `
        <div class="rc-icon">${skillIcon(skill)}</div>
        <div class="rc-name">${skill.name_zh}</div>
        <div class="rc-desc">${skill.description?.substring(0, 30) || ''}</div>
      `;
      card.onclick = () => openSkillDetail(skill);
      recommendRow.appendChild(card);
    });

    recommendArea.style.display = showIds.length > 0 ? '' : 'none';

    // 更新总数
    const openBtn = document.getElementById('open-skills-center-btn');
    if (openBtn && _skillsData?.total) {
      openBtn.textContent = `🧩 查看全部 ${_skillsData.total} 个技能 →`;
    }
  } catch (e) {
    console.warn('首页推荐加载失败', e);
  }
}

// ── 自动更新检查 ─────────────────────────────────────────────
async function checkForUpdate() {
  try {
    const BASE = getBaseUrl();
    const info = await fetch(BASE + '/api/update/check').then(r => r.json());
    if (info.has_update && !info.error) {
      const badge = document.getElementById('update-badge');
      if (badge) badge.classList.remove('hidden');
      // 5秒后弹出提示
      setTimeout(() => {
        if (confirm(`🎉 发现新版本 v${info.latest_version}！\n\n更新内容：\n${info.changelog || '优化和修复'}\n\n是否现在更新？（需要重新启动）`)) {
          applyUpdate();
        }
      }, 5000);
    }
  } catch (e) {
    // 静默失败
  }
}

async function applyUpdate() {
  const BASE = getBaseUrl();
  try {
    const result = await fetch(BASE + '/api/update/apply', { method: 'POST' }).then(r => r.json());
    if (result.ok) {
      alert(`✅ ${result.message}`);
      if (result.needs_restart) {
        if (confirm('需要重启程序。是否立即重启？')) {
          await fetch(BASE + '/api/restart', { method: 'POST' }).catch(() => {});
        }
      }
    } else {
      alert(`❌ 更新失败：${result.message}`);
    }
  } catch (e) {
    alert('更新请求失败，请手动更新');
  }
}

// ── 全局渲染入口 ─────────────────────────────────────────────
function renderSkillsCenter() {
  updateStatsBar();
  renderCatChips();
  renderSkillGrid();
}

// ── 初始化 ───────────────────────────────────────────────────
function initSkillsAndStats() {
  // 延迟2秒，等 WebSocket 连上
  setTimeout(async () => {
    await loadWelcomeRecommend();
    // 只在正式发布时检查更新（本地开发跳过）
    if (location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
      checkForUpdate();
    }
  }, 2000);
}


/* ══════════════════════════════════════════════════════════════
   SKILL CHAIN EDITOR
   ══════════════════════════════════════════════════════════════ */

const SKEY = 'oc-skill-chains';
let panel, sidebar, canvasWrap, canvas, ctx;

let _chains = [];
let _currentIdx = 0;
let _nodes = [];
let _edges = [];
let _skills = [];
let _nextId = 1;
let _draggingNode = null;
let _dragOfs = { x: 0, y: 0 };
let _connecting = null;

function save() { localStorage.setItem(SKEY, JSON.stringify(_chains)); }

function resizeCanvas() {
  const r = canvasWrap.getBoundingClientRect();
  canvas.width = r.width * devicePixelRatio;
  canvas.height = r.height * devicePixelRatio;
  canvas.style.width = r.width + 'px';
  canvas.style.height = r.height + 'px';
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  drawEdges();
}

function drawEdges() {
  const r = canvasWrap.getBoundingClientRect();
  ctx.clearRect(0, 0, r.width, r.height);
  ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent') || '#7c5cfc';
  ctx.lineWidth = 2;
  _edges.forEach(e => {
    const fromNode = _nodes.find(n => n.id === e.from);
    const toNode = _nodes.find(n => n.id === e.to);
    if (!fromNode || !toNode) return;
    const fx = fromNode.x + 40, fy = fromNode.y + 30;
    const tx = toNode.x + 40, ty = toNode.y;
    ctx.beginPath();
    ctx.moveTo(fx, fy);
    const cy1 = fy + (ty - fy) * 0.4, cy2 = fy + (ty - fy) * 0.6;
    ctx.bezierCurveTo(fx, cy1, tx, cy2, tx, ty);
    ctx.stroke();
    const angle = Math.atan2(ty - cy2, tx - tx);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - 5, ty - 8);
    ctx.lineTo(tx + 5, ty - 8);
    ctx.closePath();
    ctx.fill();
  });
}

function renderNodes() {
  canvasWrap.querySelectorAll('.sc-node').forEach(n => n.remove());
  _nodes.forEach(n => {
    const skill = _skills.find(s => s.id === n.skillId);
    const div = document.createElement('div');
    div.className = 'sc-node';
    div.dataset.nid = n.id;
    div.style.left = n.x + 'px';
    div.style.top = n.y + 'px';
    div.innerHTML = `<div class="sc-port sc-port-in" data-nid="${n.id}" data-role="in"></div>${skill?.name || n.skillId}<div class="sc-port sc-port-out" data-nid="${n.id}" data-role="out"></div><button class="sc-node-del" data-nid="${n.id}">&times;</button>`;
    canvasWrap.appendChild(div);

    div.addEventListener('pointerdown', (e) => {
      if (e.target.classList.contains('sc-port') || e.target.classList.contains('sc-node-del')) return;
      _draggingNode = n;
      _dragOfs = { x: e.clientX - n.x, y: e.clientY - n.y };
      e.preventDefault();
    });
    div.querySelector('.sc-node-del').addEventListener('click', () => {
      _nodes = _nodes.filter(nd => nd.id !== n.id);
      _edges = _edges.filter(ed => ed.from !== n.id && ed.to !== n.id);
      renderNodes();
      drawEdges();
    });
    div.querySelectorAll('.sc-port').forEach(port => {
      port.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        const nid = parseInt(port.dataset.nid);
        const role = port.dataset.role;
        if (role === 'out') {
          _connecting = nid;
        }
      });
      port.addEventListener('pointerup', (e) => {
        const nid = parseInt(port.dataset.nid);
        const role = port.dataset.role;
        if (_connecting !== null && role === 'in' && _connecting !== nid) {
          if (!_edges.find(ed => ed.from === _connecting && ed.to === nid)) {
            _edges.push({ from: _connecting, to: nid });
            drawEdges();
          }
        }
        _connecting = null;
      });
    });
  });
  drawEdges();
}

async function loadSkills() {
  try {
    const r = await fetch(getBaseUrl() + '/api/desktop-skills');
    if (r.ok) _skills = await r.json();
  } catch {}
  sidebar.innerHTML = _skills.map(s => `<div class="sc-skill-item" draggable="true" data-sid="${s.id}">${s.icon || '🔧'} ${s.name}</div>`).join('') ||
    `<div style="color:var(--text-muted);font-size:11px;padding:8px">${t('sc.dragHint')}</div>`;
  sidebar.querySelectorAll('.sc-skill-item').forEach(item => {
    item.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', item.dataset.sid);
    });
  });
}

function renderChainSelect() {
  const sel = $('sc-chain-select');
  if (!sel) return;
  sel.innerHTML = _chains.map((c, i) => `<option value="${i}"${i === _currentIdx ? ' selected' : ''}>${c.name || 'Chain ' + (i + 1)}</option>`).join('') || '<option>—</option>';
}

function loadChain(idx) {
  _currentIdx = idx;
  const chain = _chains[idx];
  if (!chain) { _nodes = []; _edges = []; _nextId = 1; } else {
    _nodes = JSON.parse(JSON.stringify(chain.nodes || []));
    _edges = JSON.parse(JSON.stringify(chain.edges || []));
    _nextId = _nodes.reduce((m, n) => Math.max(m, n.id + 1), 1);
  }
  renderNodes();
}

function open() {
  panel.classList.remove('hidden');
  loadSkills();
  renderChainSelect();
  loadChain(_currentIdx);
  setTimeout(resizeCanvas, 50);
}
function close() { panel.classList.add('hidden'); }

// ── Skill Chain Templates ──
const TEMPLATES = [
  { name: '截图+OCR+翻译', nameEn: 'Screenshot+OCR+Translate', desc: '截屏后识别文字并翻译', descEn: 'Capture screen, OCR text, then translate',
    nodes: [{id:1,skillId:'screenshot',x:60,y:40},{id:2,skillId:'ocr_region',x:60,y:130},{id:3,skillId:'translate',x:60,y:220}],
    edges: [{from:1,to:2},{from:2,to:3}] },
  { name: '屏幕录制+总结', nameEn: 'Screen Record+Summarize', desc: '录制屏幕并总结内容', descEn: 'Record screen then summarize content',
    nodes: [{id:1,skillId:'screen_record',x:60,y:40},{id:2,skillId:'summarize',x:60,y:130}],
    edges: [{from:1,to:2}] },
  { name: '文件整理', nameEn: 'File Organization', desc: '列出文件、分类并移动', descEn: 'List, categorize and move files',
    nodes: [{id:1,skillId:'list_files',x:60,y:40},{id:2,skillId:'categorize',x:60,y:130},{id:3,skillId:'move_files',x:60,y:220}],
    edges: [{from:1,to:2},{from:2,to:3}] },
  { name: '系统诊断', nameEn: 'System Diagnostics', desc: '系统信息+磁盘检查+报告', descEn: 'System info, disk check, then report',
    nodes: [{id:1,skillId:'sys_info',x:40,y:40},{id:2,skillId:'disk_check',x:150,y:40},{id:3,skillId:'report',x:95,y:140}],
    edges: [{from:1,to:3},{from:2,to:3}] },
];

function applyTemplate(tpl) {
  const name = prompt(t('sc.namePrompt'), tpl.name);
  if (!name) return;
  _chains.push({ name, nodes: JSON.parse(JSON.stringify(tpl.nodes)), edges: JSON.parse(JSON.stringify(tpl.edges)) });
  save();
  _currentIdx = _chains.length - 1;
  renderChainSelect();
  loadChain(_currentIdx);
  if (window.ocToast) window.ocToast.success(t('sc.saved'));
}

function initSkillChains() {
  panel = $('skill-chain-panel');
  sidebar = $('sc-sidebar');
  canvasWrap = $('sc-canvas-wrap');
  canvas = $('sc-canvas');
  if (!panel || !canvas) return;
  ctx = canvas.getContext('2d');

  _chains = JSON.parse(localStorage.getItem(SKEY) || '[]');

  document.addEventListener('pointermove', (e) => {
    if (!_draggingNode) return;
    _draggingNode.x = e.clientX - _dragOfs.x;
    _draggingNode.y = e.clientY - _dragOfs.y;
    const el = canvasWrap.querySelector(`[data-nid="${_draggingNode.id}"]`);
    if (el) { el.style.left = _draggingNode.x + 'px'; el.style.top = _draggingNode.y + 'px'; }
    drawEdges();
  });
  document.addEventListener('pointerup', () => { _draggingNode = null; _connecting = null; });

  canvasWrap.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
  canvasWrap.addEventListener('drop', (e) => {
    e.preventDefault();
    const sid = e.dataTransfer.getData('text/plain');
    if (!sid) return;
    const rect = canvasWrap.getBoundingClientRect();
    _nodes.push({ id: _nextId++, skillId: sid, x: e.clientX - rect.left - 40, y: e.clientY - rect.top - 15 });
    renderNodes();
  });

  $('sc-chain-select')?.addEventListener('change', function() { loadChain(parseInt(this.value) || 0); });

  $('sc-new')?.addEventListener('click', () => {
    const name = prompt(t('sc.namePrompt'), 'Chain ' + (_chains.length + 1));
    if (!name) return;
    _chains.push({ name, nodes: [], edges: [] });
    save();
    _currentIdx = _chains.length - 1;
    renderChainSelect();
    loadChain(_currentIdx);
  });

  $('sc-save')?.addEventListener('click', () => {
    if (!_chains.length) return;
    _chains[_currentIdx] = { name: _chains[_currentIdx]?.name || 'Chain', nodes: _nodes.map(n => ({ id: n.id, skillId: n.skillId, x: n.x, y: n.y })), edges: [..._edges] };
    save();
    if (window.ocToast) window.ocToast.success(t('sc.saved'));
  });

  $('sc-delete')?.addEventListener('click', () => {
    if (!_chains.length) return;
    _chains.splice(_currentIdx, 1);
    save();
    _currentIdx = Math.max(0, _currentIdx - 1);
    renderChainSelect();
    loadChain(_currentIdx);
    if (window.ocToast) window.ocToast.info(t('sc.deleted'));
  });

  $('sc-run')?.addEventListener('click', async () => {
    if (!_nodes.length) { if (window.ocToast) window.ocToast.warning(t('sc.noNodes')); return; }
    const inDegree = {};
    _nodes.forEach(n => inDegree[n.id] = 0);
    _edges.forEach(e => { if (inDegree[e.to] !== undefined) inDegree[e.to]++; });
    const queue = _nodes.filter(n => inDegree[n.id] === 0).map(n => n.id);
    const order = [];
    const adj = {};
    _edges.forEach(e => { if (!adj[e.from]) adj[e.from] = []; adj[e.from].push(e.to); });
    while (queue.length) {
      const cur = queue.shift();
      order.push(cur);
      (adj[cur] || []).forEach(next => { inDegree[next]--; if (inDegree[next] === 0) queue.push(next); });
    }
    if (window.ocToast) window.ocToast.info(t('sc.running'));
    for (const nid of order) {
      const node = _nodes.find(n => n.id === nid);
      if (!node) continue;
      try {
        await fetch(getBaseUrl() + '/api/desktop-skill/' + node.skillId, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      } catch {}
    }
    if (window.ocToast) window.ocToast.success(t('sc.done'));
  });

  $('sc-templates')?.addEventListener('click', () => {
    const isEn = (document.documentElement.lang || '').startsWith('en');
    let html = `<div style="padding:12px"><h3 style="margin:0 0 10px;font-size:14px">${t('sc.tplTitle')}</h3>`;
    TEMPLATES.forEach((tpl, i) => {
      html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:8px;margin-bottom:6px;background:var(--bg-surface);border-radius:8px;border:1px solid var(--border)">
        <div><div style="font-size:12px;font-weight:600">${isEn ? tpl.nameEn : tpl.name}</div><div style="font-size:10px;color:var(--text-muted)">${isEn ? tpl.descEn : tpl.desc} · ${tpl.nodes.length} nodes</div></div>
        <button class="mp-btn mp-btn-install sc-tpl-use" data-idx="${i}" style="font-size:10px;padding:4px 10px">${t('sc.tplUse')}</button>
      </div>`;
    });
    html += '</div>';
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center';
    const card = document.createElement('div');
    card.style.cssText = 'background:var(--bg-secondary);border-radius:12px;width:min(400px,90vw);max-height:70vh;overflow-y:auto;border:1px solid var(--border-strong)';
    card.innerHTML = html;
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    card.querySelectorAll('.sc-tpl-use').forEach(btn => {
      btn.addEventListener('click', () => { applyTemplate(TEMPLATES[parseInt(btn.dataset.idx)]); overlay.remove(); });
    });
  });

  $('sc-open')?.addEventListener('click', open);
  $('sc-back')?.addEventListener('click', close);
  window.addEventListener('resize', () => { if (!panel.classList.contains('hidden')) resizeCanvas(); });
}


/* ══════════════════════════════════════════════════════════════
   INIT
   ══════════════════════════════════════════════════════════════ */

export function init() {
  // 1. Register fn.* functions
  fn.openSkillsCenter = openSkillsCenter;
  fn.closeSkillsCenter = closeSkillsCenter;
  fn.loadWelcomeRecommend = loadWelcomeRecommend;
  fn.initSkillsAndStats = initSkillsAndStats;

  // 2. Set up event bindings (skills center)
  document.getElementById('skills-center-toggle')?.addEventListener('click', openSkillsCenter);
  document.getElementById('sc-back')?.addEventListener('click', closeSkillsCenter);
  document.getElementById('open-skills-center-btn')?.addEventListener('click', openSkillsCenter);

  document.getElementById('sc-search')?.addEventListener('input', (e) => {
    _searchQ = e.target.value;
    renderSkillGrid();
  });

  document.getElementById('sc-detail-close')?.addEventListener('click', closeSkillDetail);
  document.getElementById('sc-detail-overlay')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeSkillDetail();
  });

  // 3. Set up showChat override (wrap fn.showChat)
  const _origShowChat = fn.showChat;
  fn.showChat = function(...args) {
    if (_origShowChat) _origShowChat.apply(this, args);
    initSkillsAndStats();
  };

  // 4. Initialize if chat page is already visible
  if (!document.getElementById('chat-page')?.classList.contains('hidden')) {
    initSkillsAndStats();
  }

  // 5. Initialize skill chains
  initSkillChains();
}
