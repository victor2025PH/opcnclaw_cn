// settings-moments.js — 朋友圈管理面板
import { getBaseUrl } from '/js/state.js';

const BASE = '';
function showToast(msg) { if (window.ocToast) window.ocToast.info(msg); }

function panel() { return document.getElementById('moments-panel'); }

window.openMomentsPanel = function() {
  const p = panel();
  if (p) { p.classList.remove('hidden'); p.style.display = 'flex'; mpRefresh(); }
};
window.closeMomentsPanel = function() {
  const p = panel();
  if (p) { p.classList.add('hidden'); p.style.display = 'none'; }
};

async function mpRefresh() {
  try {
    const d = await fetch(`${BASE}/api/moments/stats`).then(r => r.json());
    const g = d.guard || {};
    document.getElementById('mp-stat-likes').textContent = g.likes_today || 0;
    document.getElementById('mp-stat-comments').textContent = g.comments_today || 0;
    document.getElementById('mp-stat-publishes').textContent = g.publishes_today || 0;

    // 风控状态
    const el = document.getElementById('mp-guard-stats');
    el.innerHTML = `
      <div>点赞: ${g.likes_today||0}/${g.likes_limit||50} | 评论: ${g.comments_today||0}/${g.comments_limit||20} | 发布: ${g.publishes_today||0}/${g.publishes_limit||5}</div>
      <div style="margin-top:4px">活跃时段: ${g.active_hours||'7:00-23:00'} | 状态: ${g.blocked?'⛔ 已暂停':'✅ 正常'}</div>
    `;
  } catch(e) {}
}

// ── 浏览朋友圈 ──
window.mpBrowse = async function() {
  const btn = document.getElementById('mp-browse-btn');
  const el = document.getElementById('mp-browse-result');
  const autoInteract = document.getElementById('mp-auto-interact').checked;
  btn.disabled = true; btn.textContent = '浏览中...';
  el.innerHTML = '<div style="color:#8a9bb0">正在打开朋友圈并分析...</div>';
  try {
    const d = await fetch(`${BASE}/api/moments/browse`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({max_posts: 10, auto_interact: autoInteract})
    }).then(r => r.json());
    const posts = d.posts || [];
    if (posts.length === 0) {
      el.innerHTML = '<div style="color:#8a9bb0">未读取到朋友圈内容</div>';
    } else {
      el.innerHTML = posts.map(p => `
        <div style="background:rgba(255,255,255,.04);border-radius:8px;padding:8px;margin-bottom:6px">
          <div style="display:flex;justify-content:space-between">
            <span style="font-weight:600;color:#e8f0fe">${p.author||'未知'}</span>
            <span style="font-size:10px;color:#666">${p.time_str||''}</span>
          </div>
          <div style="color:#c8d0e0;margin:4px 0">${(p.text||'').substring(0,100)}</div>
          ${p.image_desc?`<div style="font-size:10px;color:#7c6aef">[图] ${p.image_desc.substring(0,50)}</div>`:''}
          ${p.analysis?`<div style="font-size:10px;color:#4ade80;margin-top:4px">AI: ${p.analysis.reason||''} ${p.analysis.should_like?'👍':''}${p.analysis.should_comment?'💬'+p.analysis.comment_text:''}</div>`:''}
        </div>
      `).join('');
    }
    mpRefresh();
  } catch(e) {
    el.innerHTML = `<div style="color:#f87171">浏览失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '开始浏览 + AI 分析';
};

// ── AI 生成文案 ──
window.mpGenerate = async function() {
  const topic = document.getElementById('mp-pub-topic').value.trim();
  const el = document.getElementById('mp-gen-result');
  if (!topic) { showToast('请输入主题'); return; }
  el.innerHTML = '<div style="color:#8a9bb0">AI 正在生成...</div>';
  try {
    const d = await fetch(`${BASE}/api/moments/generate-text`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({topic})
    }).then(r => r.json());
    const options = d.options || [];
    if (options.length === 0) {
      el.innerHTML = '<div style="color:#8a9bb0">生成失败</div>';
    } else {
      el.innerHTML = options.map((o, i) => `
        <div style="background:rgba(124,106,239,.08);border-radius:6px;padding:6px;margin-bottom:4px;cursor:pointer;font-size:12px"
             onclick="document.getElementById('mp-pub-text').value=this.dataset.text"
             data-text="${(o.text||'').replace(/"/g,'&quot;')}">
          <span style="color:#7c6aef">${i+1}.</span> ${(o.text||'').substring(0,80)}
          <span style="font-size:10px;color:#666">[${o.style||''}]</span>
        </div>
      `).join('');
    }
  } catch(e) {
    el.innerHTML = `<div style="color:#f87171">${e.message}</div>`;
  }
};

// ── 发布 ──
window.mpPublish = async function() {
  const text = document.getElementById('mp-pub-text').value.trim();
  if (!text) { showToast('请输入文案'); return; }
  try {
    const d = await fetch(`${BASE}/api/moments/publish`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({text})
    }).then(r => r.json());
    showToast(d.ok ? '发布成功' : (d.error || '发布失败'));
    if (d.ok) document.getElementById('mp-pub-text').value = '';
    mpRefresh();
  } catch(e) { showToast('发布失败: ' + e.message); }
};

// ── 日历 ──
window.mpCalendarLoad = async function() {
  const el = document.getElementById('mp-calendar');
  el.innerHTML = '<div style="color:#8a9bb0">加载中...</div>';
  try {
    const d = await fetch(`${BASE}/api/moments/calendar`).then(r => r.json());
    const entries = d.entries || [];
    if (entries.length === 0) {
      el.innerHTML = '<div style="color:#8a9bb0">暂无计划，点击"生成"创建</div>';
    } else {
      el.innerHTML = entries.slice(0, 14).map(e => {
        const color = {planned:'#8a9bb0',approved:'#7c6aef',published:'#4ade80',skipped:'#666'}[e.status]||'#888';
        return `<div style="display:flex;gap:8px;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05)">
          <span style="width:65px;font-size:11px;color:#666">${e.date||''}</span>
          <span style="flex:1;font-size:12px;color:#c8d0e0">${(e.topic||e.text||'').substring(0,40)}</span>
          <span style="font-size:10px;color:${color}">${e.status||''}</span>
          ${e.status==='planned'?`<button onclick="mpCalendarAction('${e.date}','approve')" style="font-size:10px;padding:2px 6px;background:#7c6aef;color:#fff;border:none;border-radius:4px;cursor:pointer">✓</button>`:''}
        </div>`;
      }).join('');
    }
  } catch(e) { el.innerHTML = `<div style="color:#f87171">${e.message}</div>`; }
};

window.mpCalendarGen = async function() {
  const el = document.getElementById('mp-calendar');
  el.innerHTML = '<div style="color:#8a9bb0">AI 正在生成 30 天计划...</div>';
  try {
    const d = await fetch(`${BASE}/api/moments/calendar/generate`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({posts_per_week: 3})
    }).then(r => r.json());
    showToast(d.ok ? `已生成 ${d.count||0} 天计划` : (d.error || '生成失败'));
    mpCalendarLoad();
  } catch(e) { el.innerHTML = `<div style="color:#f87171">${e.message}</div>`; }
};

window.mpCalendarAction = async function(date, action) {
  try {
    await fetch(`${BASE}/api/moments/calendar/${date}/${action}`, {method:'POST'});
    mpCalendarLoad();
  } catch(e) { showToast('操作失败'); }
};

// ── 数据分析 ──
window.mpAnalytics = async function(type) {
  const el = document.getElementById('mp-analytics');
  el.innerHTML = '<div style="color:#8a9bb0">加载中...</div>';
  try {
    const url = type === 'strategy-report'
      ? `${BASE}/api/analytics/${type}`
      : `${BASE}/api/analytics/${type}`;
    const method = type === 'strategy-report' ? 'POST' : 'GET';
    const d = await fetch(url, {method}).then(r => r.json());
    el.innerHTML = `<pre style="white-space:pre-wrap;color:#c8d0e0">${JSON.stringify(d, null, 2).substring(0, 1000)}</pre>`;
  } catch(e) { el.innerHTML = `<div style="color:#f87171">${e.message}</div>`; }
};

// 自动刷新
setInterval(() => {
  if (!panel().classList.contains('hidden')) mpRefresh();
}, 30000);

export function init() {
  // 面板初始化完成
}
