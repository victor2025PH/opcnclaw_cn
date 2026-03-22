/**
 * 用户画像面板 — 设置 tab "我的画像"
 *
 * 加载/保存用户画像，产品列表增删，交互计数展示
 */

import { t } from '/js/state.js';

const _BASE = () => window.__baseUrl || '';

let _profile = null;

// ── DOM refs ──
const $ = id => document.getElementById(id);

function _getFields() {
  return {
    company:     $('up-company'),
    industry:    $('up-industry'),
    teamSize:    $('up-team-size'),
    targetUsers: $('up-target-users'),
    budgetRange: $('up-budget-range'),
    brandTone:   $('up-brand-tone'),
    writingStyle:$('up-writing-style'),
    forbidden:   $('up-forbidden-words'),
    commonTerms: $('up-common-terms'),
    competitors: $('up-competitors'),
    productNew:  $('up-product-new'),
    productsList:$('up-products-list'),
    count:       $('up-interaction-count'),
    status:      $('up-status'),
  };
}

// ── 加载画像 ──
async function loadProfile() {
  try {
    const r = await fetch(`${_BASE()}/api/user/profile`);
    if (!r.ok) return;
    _profile = await r.json();
    fillForm(_profile);
  } catch (e) {
    console.warn('[UserProfile] load failed:', e);
  }
}

function fillForm(p) {
  const f = _getFields();
  if (!f.company) return;

  f.company.value     = p.company || '';
  f.industry.value    = p.industry || '';
  f.teamSize.value    = p.team_size || '';
  f.targetUsers.value = p.target_users || '';
  f.budgetRange.value = p.budget_range || '';
  f.brandTone.value   = p.brand_tone || '';
  f.writingStyle.value= p.writing_style || '';
  f.forbidden.value   = (p.forbidden_words || []).join(', ');
  f.commonTerms.value = (p.common_terms || []).join(', ');
  f.competitors.value = (p.competitor_names || []).join(', ');
  if (f.moatLine) {
    f.moatLine.textContent = t('profile.moatInteractionLine', { count: String(p.interaction_count ?? 0) });
  }

  renderProducts(p.products || []);
}

// ── 产品列表渲染 ──
function renderProducts(products) {
  const el = $('up-products-list');
  if (!el) return;
  if (!products.length) {
    el.innerHTML = `<div style="font-size:12px;color:var(--text-muted);padding:4px 0" data-i18n="profile.productsEmpty">${t('profile.productsEmpty')}</div>`;
    return;
  }
  const delTitle = t('profile.delProductTitle');
  el.innerHTML = products.map((p, i) => `
    <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--bg-surface);border-radius:8px">
      <span style="flex:1;font-size:13px;color:var(--text-primary)">${escHtml(p.name)}</span>
      <button class="up-product-del" data-idx="${i}" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:14px;padding:2px 6px" title="${escHtml(delTitle)}">✕</button>
    </div>
  `).join('');

  el.querySelectorAll('.up-product-del').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx);
      if (_profile && _profile.products) {
        _profile.products.splice(idx, 1);
        renderProducts(_profile.products);
      }
    });
  });
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── 保存画像 ──
async function saveProfile() {
  const f = _getFields();
  if (!f.company) return;

  const splitComma = v => v.split(/[,，]/).map(s => s.trim()).filter(Boolean);

  const data = {
    company:         f.company.value.trim(),
    industry:        f.industry.value.trim(),
    team_size:       f.teamSize.value.trim(),
    target_users:    f.targetUsers.value.trim(),
    budget_range:    f.budgetRange.value.trim(),
    brand_tone:      f.brandTone.value.trim(),
    writing_style:   f.writingStyle.value.trim(),
    forbidden_words: splitComma(f.forbidden.value),
    common_terms:    splitComma(f.commonTerms.value),
    competitor_names:splitComma(f.competitors.value),
    products:        _profile?.products || [],
  };

  try {
    const r = await fetch(`${_BASE()}/api/user/profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    const res = await r.json();
    if (res.ok) {
      _profile = res.profile;
      showStatus(t('profile.statusSaved'), 'var(--success)');
    } else {
      showStatus(t('profile.statusSaveErr', { msg: res.error || t('profile.statusSaveUnknown') }), 'var(--error)');
    }
  } catch (e) {
    showStatus(t('profile.statusSaveErr', { msg: e.message || '' }), 'var(--error)');
  }
}

function showStatus(msg, color) {
  const el = $('up-status');
  if (!el) return;
  el.textContent = msg;
  el.style.color = color;
  setTimeout(() => { el.textContent = ''; }, 3000);
}

// ── 初始化 ──
export function initUserProfile() {
  const saveBtn = $('up-save');
  const resetBtn = $('up-reset');
  const addBtn = $('up-product-add');
  const newInput = $('up-product-new');

  if (saveBtn) saveBtn.addEventListener('click', saveProfile);

  if (resetBtn) resetBtn.addEventListener('click', async () => {
    if (!confirm(t('profile.resetConfirm'))) return;
    try {
      await fetch(`${_BASE()}/api/user/profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company: '', industry: '', team_size: '', target_users: '',
          budget_range: '', brand_tone: '', writing_style: '',
          forbidden_words: [], common_terms: [], competitor_names: [], products: [],
        }),
      });
      await loadProfile();
      showStatus(t('profile.statusResetOk'), 'var(--warning)');
    } catch (e) {
      showStatus(t('profile.resetFail'), 'var(--error)');
    }
  });

  if (addBtn && newInput) {
    const addProduct = () => {
      const name = newInput.value.trim();
      if (!name) return;
      if (!_profile) _profile = { products: [] };
      if (!_profile.products) _profile.products = [];
      if (_profile.products.some(p => p.name === name)) {
        showStatus(t('profile.productDuplicate'), 'var(--warning)');
        return;
      }
      _profile.products.push({ name, description: '' });
      renderProducts(_profile.products);
      newInput.value = '';
    };
    addBtn.addEventListener('click', addProduct);
    newInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); addProduct(); }
    });
  }

  // 监听 tab 切换 —— 切到画像 tab 时自动加载最新数据
  const tabs = document.getElementById('settings-tabs');
  if (tabs) {
    tabs.addEventListener('click', (e) => {
      const btn = e.target.closest('.stab');
      if (btn && btn.dataset.tab === 'tab-profile') {
        loadProfile();
        loadMoatScore();
      }
      if (btn && btn.dataset.tab === 'tab-store') {
        loadStore();
      }
      if (btn && btn.dataset.tab === 'tab-wechat-bot') {
        loadWechatBotTab();
      }
    });
  }

  // 首次打开设置时如果已在画像 tab 也加载
  const modal = document.getElementById('settings-modal');
  if (modal) {
    const observer = new MutationObserver(() => {
      if (!modal.classList.contains('hidden')) {
        const pane = document.getElementById('tab-profile');
        if (pane && pane.classList.contains('active')) {
          loadProfile();
          loadMoatScore();
        }
      }
    });
    observer.observe(modal, { attributes: true, attributeFilter: ['class'] });
  }

  // 备份按钮
  const exportBtn = $('moat-export-btn');
  const exportZipBtn = $('moat-export-zip-btn');
  const importInput = $('moat-import-input');
  const backupStatus = $('moat-backup-status');

  if (exportBtn) exportBtn.addEventListener('click', async () => {
    try {
      backupStatus.textContent = t('profile.backupExporting');
      backupStatus.style.color = 'var(--text-muted)';
      const r = await fetch(`${_BASE()}/api/moat/export`);
      const data = await r.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `moat_backup_${new Date().toISOString().slice(0,10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      backupStatus.textContent = t('profile.backupOk');
      backupStatus.style.color = 'var(--success)';
    } catch (e) {
      backupStatus.textContent = t('profile.backupFail', { msg: e.message || '' });
      backupStatus.style.color = 'var(--error)';
    }
  });

  if (exportZipBtn) exportZipBtn.addEventListener('click', () => {
    backupStatus.textContent = t('profile.backupZipping');
    window.location.href = `${_BASE()}/api/moat/export-zip`;
    setTimeout(() => { backupStatus.textContent = t('profile.backupDownloadStarted'); backupStatus.style.color = 'var(--success)'; }, 1000);
  });

  if (importInput) importInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      backupStatus.textContent = t('profile.backupImporting');
      const text = await file.text();
      const data = JSON.parse(text);
      const r = await fetch(`${_BASE()}/api/moat/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await r.json();
      if (result.ok) {
        const parts = [];
        if (result.imported?.length) parts.push(t('profile.backupImportLine', { items: result.imported.join(', ') }));
        if (result.skipped?.length) parts.push(t('profile.backupSkippedLine', { items: result.skipped.join(', ') }));
        backupStatus.textContent = parts.join(' | ') || t('profile.backupImportDone');
        backupStatus.style.color = 'var(--success)';
        loadProfile();
        loadMoatScore();
      } else {
        backupStatus.textContent = t('profile.backupImportErr', { msg: result.error || t('profile.statusSaveUnknown') });
        backupStatus.style.color = 'var(--error)';
      }
    } catch (e) {
      backupStatus.textContent = t('profile.backupParseErr', { msg: e.message || '' });
      backupStatus.style.color = 'var(--error)';
    }
    importInput.value = '';
  });

  function refreshProfileI18n() {
    if (_profile) fillForm(_profile);
    loadMoatScore();
    loadStore(_storeCategory);
    renderAchievementBadges();
  }
  window.addEventListener('oc-lang-change', refreshProfileI18n);
  window.addEventListener('oc-i18n-updated', refreshProfileI18n);

  // 欢迎页护城河状态条 + 画像仪表盘（一次请求）
  setTimeout(loadMoatScore, 2000);
}


// ── 护城河分数 ──

async function loadMoatScore() {
  const dashLevel = document.getElementById('moat-dash-level');
  const dashDesc = document.getElementById('moat-dash-desc');
  if (dashLevel) dashLevel.textContent = t('profile.moatLoading');
  if (dashDesc) dashDesc.textContent = '';
  try {
    const r = await fetch(`${_BASE()}/api/moat-score`);
    if (!r.ok) return;
    const d = await r.json();
    renderMoatDashboard(d);
    applyWelcomeMoat(d);
  } catch (e) {
    console.warn('[Moat] load failed:', e);
  }
}

function renderMoatDashboard(d) {
  // 圆环分数
  const ring = document.getElementById('moat-ring');
  const ringScore = document.getElementById('moat-ring-score');
  const dashLevel = document.getElementById('moat-dash-level');
  const dashDesc = document.getElementById('moat-dash-desc');
  const barsEl = document.getElementById('moat-bars');

  if (ring) {
    const pct = d.percentage || 0;
    const circumference = 2 * Math.PI * 16;  // r=16
    const dashLen = (pct / 100) * circumference;
    ring.setAttribute('stroke-dasharray', `${dashLen} ${circumference}`);
  }
  if (ringScore) ringScore.textContent = d.total || 0;
  if (dashLevel) dashLevel.textContent = `${d.level_icon || ''} ${d.level || ''}`;
  if (dashDesc) dashDesc.textContent = d.level_desc || '';

  // 各维度条形图
  if (barsEl && d.details) {
    const colors = {
      profile: '#6c63ff', memory: '#8b5cf6', projects: '#06b6d4',
      evolution: '#f59e0b', feedback: '#22c55e', interaction: '#ec4899',
    };
    barsEl.innerHTML = Object.entries(d.details).map(([key, v]) => {
      const pct = v.max > 0 ? Math.round(v.score / v.max * 100) : 0;
      const color = colors[key] || '#6c63ff';
      return `
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:11px;color:var(--text-secondary);min-width:64px">${v.label}</span>
          <div style="flex:1;height:4px;background:rgba(255,255,255,0.06);border-radius:2px;overflow:hidden">
            <div style="height:100%;width:${pct}%;background:${color};border-radius:2px;transition:width 0.8s ease"></div>
          </div>
          <span style="font-size:10px;color:var(--text-muted);min-width:32px;text-align:right">${v.score}/${v.max}</span>
        </div>
        <div style="font-size:9px;color:var(--text-muted);margin-left:72px;margin-top:-4px">${v.tip || ''}</div>`;
    }).join('');
  }

  // 增长任务
  const tasksEl = document.getElementById('moat-tasks');
  if (tasksEl && d.growth_tasks && d.growth_tasks.length) {
    tasksEl.innerHTML = `<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:4px" data-i18n="profile.moatImproveTitle">${t('profile.moatImproveTitle')}</div>` +
      d.growth_tasks.filter(t => !t.done).slice(0, 4).map(t => `
        <div class="moat-task-item" data-action="${t.action || ''}" style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:var(--bg-primary);border:1px solid var(--border);border-radius:8px;cursor:pointer;transition:all 0.15s">
          <span style="font-size:16px">${t.icon}</span>
          <div style="flex:1;min-width:0">
            <div style="font-size:12px;color:var(--text-primary);font-weight:500">${t.title}</div>
            <div style="font-size:10px;color:var(--text-muted)">${t.desc}</div>
          </div>
          <span style="font-size:10px;color:var(--accent);white-space:nowrap;font-weight:600">${t.reward}</span>
        </div>`).join('');

    // 点击任务跳转
    tasksEl.querySelectorAll('.moat-task-item').forEach(el => {
      el.addEventListener('click', () => {
        const action = el.dataset.action;
        if (action === 'open_profile') {
          // 已在画像页，滚到顶部
          el.closest('.stab-pane')?.scrollTo({top: 0, behavior: 'smooth'});
        } else if (action === 'chat') {
          // 关闭设置，回到聊天
          document.getElementById('settings-modal')?.classList.add('hidden');
        }
      });
      el.addEventListener('mouseenter', () => { el.style.borderColor = 'var(--accent)'; });
      el.addEventListener('mouseleave', () => { el.style.borderColor = 'var(--border)'; });
    });
  }
}

/** 欢迎页护城河条（与画像仪表盘共用 /api/moat-score 响应） */
function applyWelcomeMoat(d) {
  const bar = document.getElementById('moat-bar');
  const fill = document.getElementById('moat-fill');
  const icon = document.getElementById('moat-icon');
  const level = document.getElementById('moat-level');
  const scoreText = document.getElementById('moat-score-text');
  const desc = document.getElementById('moat-desc');

  if (!bar) return;
  bar.style.display = 'block';
  if (fill) fill.style.width = (d.percentage || 0) + '%';
  if (icon) icon.textContent = d.level_icon || '🌱';
  if (level) level.textContent = d.level || t('profile.moatLevelDefault');
  if (scoreText) scoreText.textContent = t('profile.moatScoreFmt', { n: String(d.total || 0) });
  if (desc) desc.textContent = d.level_desc || '';

  checkAchievements(d);
  renderAchievementBadges();
}

async function loadWelcomeMoat() {
  await loadMoatScore();
}

function renderAchievementBadges() {
  const el = document.getElementById('moat-achievements');
  if (!el) return;
  const achieved = JSON.parse(localStorage.getItem('oc_achievements') || '{}');
  const all = [
    { id: 'first_10', icon: '🌱' },
    { id: 'first_20', icon: '🥉' },
    { id: 'first_40', icon: '🥈' },
    { id: 'first_60', icon: '🥇' },
    { id: 'first_80', icon: '🏆' },
  ];
  const tipOn = t('profile.achievement.badgeUnlocked');
  const tipOff = t('profile.achievement.badgeLocked');
  el.innerHTML = all.map(a => {
    const done = !!achieved[a.id];
    const tip = done ? tipOn : tipOff;
    return `<span style="font-size:16px;opacity:${done ? 1 : 0.2};filter:${done ? 'none' : 'grayscale(1)'};transition:all 0.3s" title="${tip.replace(/"/g, '&quot;')}">${a.icon}</span>`;
  }).join('');
}

function checkAchievements(d) {
  const key = 'oc_achievements';
  const achieved = JSON.parse(localStorage.getItem(key) || '{}');
  const total = d.total || 0;

  const milestones = [
    { id: 'first_10', threshold: 10, icon: '🌱' },
    { id: 'first_20', threshold: 20, icon: '🥉' },
    { id: 'first_40', threshold: 40, icon: '🥈' },
    { id: 'first_60', threshold: 60, icon: '🥇' },
    { id: 'first_80', threshold: 80, icon: '🏆' },
  ];

  for (const m of milestones) {
    if (total >= m.threshold && !achieved[m.id]) {
      achieved[m.id] = Date.now();
      localStorage.setItem(key, JSON.stringify(achieved));
      showAchievementToast(m);
      break;  // 一次只弹一个
    }
  }
}

function showAchievementToast(m) {
  const title = t(`profile.achievement.${m.id}.title`);
  const desc = t(`profile.achievement.${m.id}.desc`);
  const headline = t('profile.achievement.toastTitle', { title });
  const toast = document.createElement('div');
  toast.style.cssText = `
    position:fixed;top:20px;left:50%;transform:translateX(-50%) translateY(-100px);
    z-index:10000;background:linear-gradient(135deg,#1a1a2e,#2d2d4e);
    border:1px solid var(--accent,#6c63ff);border-radius:16px;padding:16px 24px;
    display:flex;align-items:center;gap:12px;box-shadow:0 8px 32px rgba(108,99,255,0.3);
    transition:transform 0.5s cubic-bezier(0.34,1.56,0.64,1);
    max-width:360px;
  `;
  const iconSpan = document.createElement('span');
  iconSpan.style.fontSize = '32px';
  iconSpan.textContent = m.icon;
  const wrap = document.createElement('div');
  const line1 = document.createElement('div');
  line1.style.cssText = 'font-size:14px;font-weight:700;color:#fff';
  line1.textContent = headline;
  const line2 = document.createElement('div');
  line2.style.cssText = 'font-size:12px;color:var(--text-secondary,#aaa);margin-top:2px';
  line2.textContent = desc;
  wrap.appendChild(line1);
  wrap.appendChild(line2);
  toast.appendChild(iconSpan);
  toast.appendChild(wrap);
  document.body.appendChild(toast);

  // 动画弹入
  requestAnimationFrame(() => {
    toast.style.transform = 'translateX(-50%) translateY(0)';
  });

  // 5 秒后消失
  setTimeout(() => {
    toast.style.transform = 'translateX(-50%) translateY(-100px)';
    setTimeout(() => toast.remove(), 500);
  }, 5000);
}


// ── 角色商店 ──

let _storeCategory = '';

async function loadStore(category = '') {
  _storeCategory = category;
  try {
    const url = category
      ? `${_BASE()}/api/agents/store?category=${encodeURIComponent(category)}`
      : `${_BASE()}/api/agents/store`;
    const r = await fetch(url);
    if (!r.ok) return;
    const d = await r.json();
    renderStoreCategories(d.categories || []);
    renderStoreRoles(d.roles || []);
  } catch (e) { console.warn('[Store] load failed:', e); }

  // 加载已安装的自定义角色
  try {
    const r2 = await fetch(`${_BASE()}/api/agents/roles/custom`);
    const d2 = await r2.json();
    renderInstalledRoles(d2.roles || []);
  } catch (e) { /* silent */ }
}

function renderStoreCategories(categories) {
  const el = $('store-categories');
  if (!el) return;
  el.innerHTML = `<button class="store-cat-btn ${!_storeCategory ? 'active' : ''}" onclick="window._loadStoreCategory('')" style="padding:4px 12px;border-radius:12px;border:1px solid var(--border);background:${!_storeCategory ? 'var(--accent)' : 'var(--bg-surface)'};color:${!_storeCategory ? '#fff' : 'var(--text-secondary)'};font-size:11px;cursor:pointer">${t('store.catAll')}</button>` +
    categories.map(c => {
      const active = _storeCategory === c;
      return `<button class="store-cat-btn ${active ? 'active' : ''}" onclick="window._loadStoreCategory('${c}')" style="padding:4px 12px;border-radius:12px;border:1px solid var(--border);background:${active ? 'var(--accent)' : 'var(--bg-surface)'};color:${active ? '#fff' : 'var(--text-secondary)'};font-size:11px;cursor:pointer">${c}</button>`;
    }).join('');
}

function renderStoreRoles(roles) {
  const el = $('store-role-list');
  if (!el) return;
  if (!roles.length) {
    el.innerHTML = `<div style="text-align:center;color:var(--text-muted);font-size:12px;padding:20px" data-i18n="store.emptyCategory">${t('store.emptyCategory')}</div>`;
    return;
  }
  const installLabel = t('store.install');
  el.innerHTML = roles.map(r => `
    <div style="display:flex;align-items:flex-start;gap:10px;padding:10px 12px;background:var(--bg-primary);border:1px solid var(--border);border-radius:10px">
      <span style="font-size:24px;flex-shrink:0">${r.avatar}</span>
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:6px">
          <span style="font-size:13px;font-weight:600;color:var(--text-primary)">${r.name}</span>
          <span style="font-size:9px;padding:1px 6px;background:var(--bg-surface);border-radius:4px;color:var(--text-muted)">${r.category || ''}</span>
        </div>
        <div style="font-size:11px;color:var(--text-secondary);margin-top:2px;line-height:1.4">${r.description}</div>
      </div>
      <button onclick="window._installRole('${r.id}',this)" style="padding:4px 12px;border-radius:6px;border:1px solid var(--accent);background:transparent;color:var(--accent);font-size:11px;cursor:pointer;white-space:nowrap;flex-shrink:0;transition:all 0.15s">${installLabel}</button>
    </div>`).join('');
}

function renderInstalledRoles(roles) {
  const el = $('store-installed-list');
  if (!el) return;
  if (!roles.length) {
    el.innerHTML = `<div style="text-align:center;color:var(--text-muted);font-size:12px;padding:10px" data-i18n="store.emptyCustom">${t('store.emptyCustom')}</div>`;
    return;
  }
  const delTitle = t('profile.delProductTitle');
  el.innerHTML = roles.map(r => `
    <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--bg-surface);border-radius:8px">
      <span style="font-size:18px">${r.avatar || '🤖'}</span>
      <div style="flex:1;min-width:0">
        <div style="font-size:12px;color:var(--text-primary);font-weight:500">${r.name}</div>
        <div style="font-size:10px;color:var(--text-muted)">${(r.description || '').substring(0, 40)}</div>
      </div>
      <button onclick="window._uninstallRole('${r.id}',this)" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:12px" title="${escHtml(delTitle)}">✕</button>
    </div>`).join('');
}

window._loadStoreCategory = function(cat) { loadStore(cat); };

window._installRole = async function(roleId, btn) {
  btn.textContent = t('store.installing');
  btn.disabled = true;
  try {
    const r = await fetch(`${_BASE()}/api/agents/store/install/${roleId}`, { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      btn.textContent = t('store.installedOk');
      btn.style.background = 'var(--success)';
      btn.style.color = '#fff';
      btn.style.borderColor = 'var(--success)';
      loadStore(_storeCategory);  // 刷新已安装列表
    } else {
      btn.textContent = (d.error && (d.error.includes('已存在') || d.error.includes('exists'))) ? t('store.alreadyInstalled') : t('store.failed');
      btn.style.color = 'var(--error)';
    }
  } catch (e) {
    btn.textContent = t('store.failed');
  }
};

window._uninstallRole = async function(roleId, btn) {
  if (!confirm(t('store.uninstallConfirm'))) return;
  try {
    await fetch(`${_BASE()}/api/agents/roles/${roleId}`, { method: 'DELETE' });
    loadStore(_storeCategory);
  } catch (e) { alert(t('profile.uninstallFailAlert')); }
};


// ── 微信 Bot 设置 tab ──

async function loadWechatBotTab() {
  // 加载通道状态
  try {
    const r = await fetch(`${_BASE()}/api/wechat/channels`);
    const d = await r.json();
    const channels = d.channels || [];

    // iLink 状态
    const ilink = channels.find(c => c.id === 'ilink');
    const dot = document.getElementById('ilink-dot');
    const label = document.getElementById('ilink-label');
    const connectBtn = document.getElementById('ilink-connect-btn');
    const disconnectBtn = document.getElementById('ilink-disconnect-btn');

    if (ilink && ilink.connected) {
      if (dot) dot.style.background = '#22c55e';
      if (label) label.textContent = '已连接' + (ilink.running ? '（运行中）' : '');
      if (connectBtn) connectBtn.style.display = 'none';
      if (disconnectBtn) disconnectBtn.style.display = 'inline-block';
    } else {
      if (dot) dot.style.background = '#666';
      if (label) label.textContent = '未连接';
      if (connectBtn) connectBtn.style.display = 'inline-block';
      if (disconnectBtn) disconnectBtn.style.display = 'none';
    }

    // UIA 状态
    const uia = channels.find(c => c.id === 'uia');
    const uiaEl = document.getElementById('uia-status');
    if (uiaEl) {
      if (uia && uia.connected) {
        uiaEl.innerHTML = `<span style="color:var(--success)">✅ 已连接</span> — ${uia.running ? '自动回复中' : '待机'}`;
      } else {
        uiaEl.innerHTML = '<span style="color:var(--text-muted)">未启用（需要 Windows 桌面微信）</span>';
      }
    }

    // 通道列表
    const listEl = document.getElementById('wechat-channels-list');
    if (listEl) {
      listEl.innerHTML = channels.map(c => {
        const statusIcon = c.connected ? (c.running ? '🟢' : '🟡') : '⚪';
        return `<div style="padding:4px 0">${statusIcon} ${c.name} — ${c.connected ? (c.running ? '运行中' : '已连接') : '未连接'}</div>`;
      }).join('');
    }
  } catch(e) {
    console.warn('[WeChatBot] load failed:', e);
  }

  // 绑定按钮事件
  const connectBtn = document.getElementById('ilink-connect-btn');
  if (connectBtn && !connectBtn._bound) {
    connectBtn._bound = true;
    connectBtn.addEventListener('click', async () => {
      connectBtn.textContent = '获取二维码...';
      connectBtn.disabled = true;
      try {
        const r = await fetch(`${_BASE()}/api/ilink/login`, {method:'POST'});
        const d = await r.json();
        if (!d.ok) { connectBtn.textContent = '绑定失败: ' + (d.error||''); connectBtn.disabled = false; return; }

        const qrDiv = document.getElementById('ilink-settings-qr');
        const qrImg = document.getElementById('ilink-settings-qr-img');
        if (qrImg && d.qrcode_img) {
          qrImg.src = d.qrcode_img.startsWith('data:') ? d.qrcode_img : 'data:image/png;base64,' + d.qrcode_img;
        }
        if (qrDiv) qrDiv.style.display = 'block';
        connectBtn.textContent = '等待扫码...';

        // 轮询
        for (let i = 0; i < 60; i++) {
          await new Promise(r => setTimeout(r, 2000));
          const sr = await fetch(`${_BASE()}/api/ilink/qrcode-status?qrcode_id=${encodeURIComponent(d.qrcode_id)}`);
          const sd = await sr.json();
          if (sd.connected) {
            connectBtn.textContent = '✅ 绑定成功！';
            if (qrDiv) qrDiv.style.display = 'none';
            setTimeout(() => loadWechatBotTab(), 1000);
            return;
          }
        }
        connectBtn.textContent = '二维码过期，请重试';
        connectBtn.disabled = false;
        if (qrDiv) qrDiv.style.display = 'none';
      } catch(e) {
        connectBtn.textContent = '连接失败';
        connectBtn.disabled = false;
      }
    });
  }

  const disconnectBtn = document.getElementById('ilink-disconnect-btn');
  if (disconnectBtn && !disconnectBtn._bound) {
    disconnectBtn._bound = true;
    disconnectBtn.addEventListener('click', async () => {
      if (!confirm('确定断开微信 ClawBot？')) return;
      await fetch(`${_BASE()}/api/ilink/disconnect`, {method:'POST'});
      loadWechatBotTab();
    });
  }
}
