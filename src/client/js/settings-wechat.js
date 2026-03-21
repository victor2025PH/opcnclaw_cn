// settings-wechat.js — WeChat Auto-Reply panel
// Extracted from settings.js

import { getBaseUrl } from '/js/state.js';

function showToast(msg) {
  if (window.ocToast) window.ocToast.info(msg);
}

export function initWechatPanel() {
  const panel = () => document.getElementById('wechat-panel');

  window.openWechatPanel = async function() {
    const p = panel();
    if (p) { p.style.display = ''; p.classList.remove('hidden'); p.classList.add('open'); }
    await wxpRefresh();
    wxpStartReviewStream();
  };

  window.closeWechatPanel = function() {
    const p = panel();
    if (p) { p.classList.remove('open'); p.classList.add('hidden'); p.style.display = 'none'; }
    wxpStopReviewStream();
  };
  const backBtn = document.getElementById('wxp-back');
  if (backBtn) {
    backBtn.onclick = function(e) { e.preventDefault(); e.stopPropagation(); closeWechatPanel(); };
  }

  let _lastReplyCount = -1;
  let _wxpLastToday = null;
  const _wxpSparkDeltas = [];

  function wxpDrawSparkline() {
    const line = document.getElementById('wxp-spark-line');
    if (!line || _wxpSparkDeltas.length < 2) {
      if (line) line.setAttribute('points', '4,18 236,18');
      return;
    }
    const w = 240;
    const h = 36;
    const pad = 4;
    const max = Math.max(0.01, ..._wxpSparkDeltas);
    const n = _wxpSparkDeltas.length;
    const pts = _wxpSparkDeltas.map((v, i) => {
      const x = pad + (n === 1 ? (w - pad * 2) / 2 : (i / (n - 1)) * (w - pad * 2));
      const y = h - pad - (v / max) * (h - pad * 2);
      return `${x},${y}`;
    }).join(' ');
    line.setAttribute('points', pts);
  }

  function wxpPushSparkSample(todayVal) {
    const t = Number(todayVal) || 0;
    if (_wxpLastToday !== null) {
      const delta = Math.max(0, t - _wxpLastToday);
      _wxpSparkDeltas.push(delta);
      if (_wxpSparkDeltas.length > 48) _wxpSparkDeltas.shift();
      wxpDrawSparkline();
    }
    _wxpLastToday = t;
  }

  async function wxpRefresh() {
    try {
      const r = await fetch('/api/wechat/status');
      const d = await r.json();
      wxpRenderStatus(d);

      // 系统通知：新回复时弹出
      const total = d.total_replied || 0;
      if (_lastReplyCount >= 0 && total > _lastReplyCount) {
        const logs = d.logs || [];
        const latest = logs[0];
        if (latest && Notification.permission === 'granted') {
          new Notification('十三香小龙虾 AI', {
            body: `已回复 ${latest.contact || '?'}: ${(latest.reply || '').substring(0, 50)}`,
            icon: '/assets/icon.png',
            tag: 'wechat-reply',
          });
        }
      }
      _lastReplyCount = total;

      // 首次请求通知权限
      if (_lastReplyCount === -1 && Notification.permission === 'default') {
        Notification.requestPermission();
      }
    } catch(e) {
      console.warn('wxp refresh:', e);
    }
  }

  function wxpRenderStatus(d) {
    const tog = document.getElementById('wxp-master-toggle');
    if (tog) tog.checked = !!d.enabled;
    document.getElementById('wxp-status-txt').textContent = d.enabled ? '运行中' : '已关闭';
    document.getElementById('wxp-mode-label').textContent =
      d.monitor_mode === 'uia' ? 'UIA模式' : 'OCR模式';

    document.getElementById('wxp-stat-today').textContent = d.today_replied ?? 0;
    document.getElementById('wxp-stat-pending').textContent = d.pending_count ?? 0;
    document.getElementById('wxp-stat-total').textContent = d.total_replied ?? 0;
    wxpPushSparkSample(d.today_replied ?? 0);

    wxpRenderContacts(d.contacts || {});
    wxpRenderLogs(d.logs || []);
    wxpRenderReviews(d.reviews || []);
  }

  document.getElementById('wxp-master-toggle')?.addEventListener('change', async function() {
    const en = this.checked;
    await fetch('/api/wechat/toggle', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({enabled: en})
    });
    document.getElementById('wxp-status-txt').textContent = en ? '运行中' : '已关闭';
  });

  document.getElementById('wxp-save-config')?.addEventListener('click', async () => {
    const body = {
      manual_review: document.getElementById('wxp-manual-review').checked,
      quiet_start: document.getElementById('wxp-quiet-start').value,
      quiet_end: document.getElementById('wxp-quiet-end').value,
      min_reply_delay: parseFloat(document.getElementById('wxp-delay-min').value),
      max_reply_delay: parseFloat(document.getElementById('wxp-delay-max').value),
    };
    await fetch('/api/wechat/config', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    showToast('设置已保存');
  });

  document.getElementById('wxp-add-contact-btn')?.addEventListener('click', () => {
    document.getElementById('wxp-add-form').classList.toggle('hidden');
  });
  document.getElementById('wxp-cancel-add')?.addEventListener('click', () => {
    document.getElementById('wxp-add-form').classList.add('hidden');
  });
  document.getElementById('wxp-confirm-add')?.addEventListener('click', async () => {
    const name = document.getElementById('wxp-new-name').value.trim();
    if (!name) { showToast('请输入联系人名字'); return; }
    await fetch('/api/wechat/contacts', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        name,
        is_group: document.getElementById('wxp-new-isgroup').checked,
        daily_limit: parseInt(document.getElementById('wxp-new-limit').value) || 20,
        persona: document.getElementById('wxp-new-persona').value.trim(),
      })
    });
    document.getElementById('wxp-new-name').value = '';
    document.getElementById('wxp-new-persona').value = '';
    document.getElementById('wxp-add-form').classList.add('hidden');
    await wxpRefresh();
    showToast(`已添加联系人：${name}`);
  });

  function wxpRenderContacts(contacts) {
    const el = document.getElementById('wxp-contacts-list');
    const names = Object.keys(contacts);
    if (!names.length) {
      el.innerHTML = '<div style="color:#8a9bb0;font-size:13px;text-align:center;padding:16px">暂无联系人，点击"添加"开始设置</div>';
      return;
    }
    el.innerHTML = names.map(name => {
      const c = contacts[name];
      const pct = c.daily_limit > 0 ? Math.min(100, Math.round(c.reply_count_today / c.daily_limit * 100)) : 0;
      return `
        <div class="wxp-contact-item">
          <div style="flex:1">
            <div style="font-size:14px;font-weight:600;color:#e8f0fe">
              ${c.is_group ? '👥 ' : '👤 '}${name}
            </div>
            <div style="font-size:11px;color:#8a9bb0;margin-top:2px">
              今日 ${c.reply_count_today}/${c.daily_limit} 条
              <span style="display:inline-block;width:40px;height:4px;background:#222;border-radius:2px;margin-left:6px;vertical-align:middle">
                <span style="display:block;height:100%;width:${pct}%;background:#48bb78;border-radius:2px"></span>
              </span>
            </div>
          </div>
          <label class="wxp-switch" style="transform:scale(.85)">
            <input type="checkbox" ${c.enabled ? 'checked' : ''} onchange="wxpToggleContact('${name}', this.checked)">
            <span class="wxp-slider"></span>
          </label>
          <button onclick="wxpRemoveContact('${name}')"
            style="background:none;border:none;color:#fc8181;font-size:18px;cursor:pointer;padding:4px 6px">×</button>
        </div>`;
    }).join('');
  }

  window.wxpToggleContact = async (name, enabled) => {
    await fetch(`/api/wechat/contacts/${encodeURIComponent(name)}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({enabled})
    });
  };

  window.wxpRemoveContact = async (name) => {
    if (!confirm(`确定移除「${name}」的自动回复？`)) return;
    await fetch(`/api/wechat/contacts/${encodeURIComponent(name)}`, {method:'DELETE'});
    await wxpRefresh();
  };

  function wxpRenderReviews(reviews) {
    const el = document.getElementById('wxp-reviews-list');
    if (!reviews.length) {
      el.innerHTML = '<div style="color:#8a9bb0;font-size:13px;text-align:center;padding:12px">暂无待审核</div>';
      return;
    }
    el.innerHTML = reviews.map(r => `
      <div class="wxp-review-item" id="wxp-review-${r.id}">
        <div style="font-size:12px;color:#ffd700;margin-bottom:6px">来自：${r.contact}</div>
        <div style="font-size:13px;color:#aaa;margin-bottom:4px">💬 ${r.incoming}</div>
        <div style="font-size:13px;color:#e8f0fe;margin-bottom:8px">🤖 ${r.reply}</div>
        <div style="display:flex;gap:8px">
          <button class="wxp-btn-primary" style="flex:1;padding:6px 0;font-size:12px"
            onclick="wxpApprove('${r.id}')">✓ 发送</button>
          <button class="wxp-btn-secondary" style="flex:1;padding:6px 0;font-size:12px"
            onclick="wxpReject('${r.id}')">✕ 拒绝</button>
        </div>
      </div>`).join('');
  }

  window.wxpApprove = async (id) => {
    await fetch(`/api/wechat/reviews/${id}/approve`, {method:'POST'});
    document.getElementById(`wxp-review-${id}`)?.remove();
    showToast('已批准发送');
    const cnt = document.getElementById('wxp-stat-pending');
    if (cnt) cnt.textContent = Math.max(0, parseInt(cnt.textContent) - 1);
  };

  window.wxpReject = async (id) => {
    await fetch(`/api/wechat/reviews/${id}/reject`, {method:'POST'});
    document.getElementById(`wxp-review-${id}`)?.remove();
    const cnt = document.getElementById('wxp-stat-pending');
    if (cnt) cnt.textContent = Math.max(0, parseInt(cnt.textContent) - 1);
  };

  function wxpRenderLogs(logs) {
    const el = document.getElementById('wxp-logs-list');
    if (!logs.length) { el.innerHTML = '<div style="color:#8a9bb0;text-align:center;padding:8px">暂无记录</div>'; return; }
    el.innerHTML = logs.slice(0, 10).map(l => `
      <div style="background:rgba(255,255,255,.03);border-radius:8px;padding:8px 10px;margin-bottom:6px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:13px;font-weight:600;color:#63b3ed">${l.contact||'?'}</span>
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-size:10px;color:#666">${l.time||''}</span>
            <span style="font-size:11px;color:${l.success?'#4ade80':'#f87171'}">${l.success?'✅':'❌'}</span>
          </div>
        </div>
        <div style="font-size:11px;color:#8a9bb0;margin-bottom:2px">📥 ${(l.incoming||'').substring(0,60)}</div>
        <div style="font-size:11px;color:#e8f0fe">🤖 ${(l.reply||'').substring(0,60)}</div>
      </div>`).join('');
  }

  let _wxpEventSource = null;
  function wxpStartReviewStream() {
    wxpStopReviewStream();
    try {
      _wxpEventSource = new EventSource('/api/wechat/reviews/stream');
      _wxpEventSource.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.type === 'review') {
          const cnt = document.getElementById('wxp-stat-pending');
          if (cnt) cnt.textContent = parseInt(cnt.textContent || '0') + 1;
          const el = document.getElementById('wxp-reviews-list');
          const placeholder = el.querySelector('div[style*="暂无"]');
          if (placeholder) placeholder.remove();
          el.insertAdjacentHTML('afterbegin', `
            <div class="wxp-review-item" id="wxp-review-${d.id}">
              <div style="font-size:12px;color:#ffd700;margin-bottom:6px">来自：${d.contact}</div>
              <div style="font-size:13px;color:#aaa;margin-bottom:4px">💬 ${d.incoming}</div>
              <div style="font-size:13px;color:#e8f0fe;margin-bottom:8px">🤖 ${d.reply}</div>
              <div style="display:flex;gap:8px">
                <button class="wxp-btn-primary" style="flex:1;padding:6px 0;font-size:12px"
                  onclick="wxpApprove('${d.id}')">✓ 发送</button>
                <button class="wxp-btn-secondary" style="flex:1;padding:6px 0;font-size:12px"
                  onclick="wxpReject('${d.id}')">✕ 拒绝</button>
              </div>
            </div>`);
          showToast(`📩 新待审核：${d.contact}`);
        }
      };
    } catch(e) {}
  }
  function wxpStopReviewStream() {
    if (_wxpEventSource) { _wxpEventSource.close(); _wxpEventSource = null; }
  }

  setInterval(() => {
    if (!panel().classList.contains('hidden')) wxpRefresh();
  }, 15000);

  window.wxpToggleDebug = function() {
    const body = document.getElementById('wxp-debug-body');
    const btn = document.getElementById('wxp-debug-toggle-btn');
    const hidden = body.classList.toggle('hidden');
    btn.textContent = hidden ? '展开' : '收起';
  };

  window.wxpRefreshStats = async function() {
    const el = document.getElementById('wxp-monitor-stats');
    el.textContent = '加载中...';
    try {
      const r = await fetch('/api/wechat/monitor-stats');
      const d = await r.json();
      if (!d.available) { el.textContent = '功能不可用（缺少依赖）'; return; }
      const s = d.stats || {};
      el.textContent = [
        `运行状态: ${s.is_running ? '✅ 运行中' : '⏸ 已停止'}`,
        `读取模式: ${s.mode === 'uia' ? 'UIAutomation' : 'OCR截图'}`,
        `UIA扫描次数: ${s.uia_reads ?? 0}`,
        `OCR扫描次数: ${s.ocr_reads ?? 0}`,
        `UIA失败次数: ${s.uia_failures ?? 0}`,
        `检测到消息数: ${s.messages_detected ?? 0}`,
        `最后扫描: ${s.last_scan_time ? new Date(s.last_scan_time * 1000).toLocaleTimeString() : '未扫描'}`,
        `最后扫描未读会话: ${s.last_scan_found ?? 0} 个`,
      ].join('\n');
    } catch(e) {
      el.textContent = `加载失败: ${e.message}`;
    }
  };

  window.wxpTestRead = async function() {
    const btn = document.getElementById('wxp-test-read-btn');
    const result = document.getElementById('wxp-test-result');
    btn.disabled = true;
    btn.textContent = '读取中...';
    result.style.display = 'block';
    result.textContent = '正在读取微信窗口...';
    try {
      const r = await fetch('/api/wechat/test-read', {method: 'POST'});
      const d = await r.json();
      if (!d.ok) {
        result.textContent = `错误: ${d.error || '未知错误'}`;
        return;
      }
      const res = d.result;
      const lines = [
        `微信运行: ${res.wechat_running ? '✅ 是' : '❌ 否'}`,
        `UIA可用: ${res.uia_available ? '✅ 是' : '❌ 否（需安装 uiautomation）'}`,
        `读取模式: ${res.mode}`,
      ];
      if (res.window_info?.found) {
        const wi = res.window_info;
        lines.push(`窗口标题: ${wi.title}`);
        if (wi.rect) lines.push(`窗口大小: ${wi.rect.width} × ${wi.rect.height}`);
      }
      lines.push(`\n未读会话 (${res.unread_sessions?.length ?? 0} 个):`);
      (res.unread_sessions || []).forEach(s => {
        lines.push(`  • ${s.contact} [${s.unread_count}条未读] ${s.is_group ? '(群聊)' : ''}`);
      });
      const chat = res.current_chat || {};
      lines.push(`\n当前聊天窗口: ${chat.contact || '(未识别)'}`);
      lines.push(`最新消息 (${chat.messages?.length ?? 0} 条):`);
      (chat.messages || []).forEach((m, i) => {
        lines.push(`  ${i+1}. [${m.is_mine ? '我' : m.sender || '对方'}][${m.msg_type}] ${m.content}`);
      });
      result.textContent = lines.join('\n');
    } catch(e) {
      result.textContent = `请求失败: ${e.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = '📖 读取当前窗口';
    }
  };

  let _uiaTreeData = null;
  window.wxpDumpUIA = async function() {
    const btn = document.getElementById('wxp-uia-dump-btn');
    const result = document.getElementById('wxp-uia-result');
    const depth = parseInt(document.getElementById('wxp-uia-depth').value) || 4;
    btn.disabled = true;
    btn.textContent = '导出中...';
    result.style.display = 'block';
    result.textContent = '正在读取控件树，请稍候（深度越大越慢）...';
    try {
      const r = await fetch(`/api/wechat/uia-debug?max_depth=${depth}`);
      const d = await r.json();
      if (!d.ok) {
        result.textContent = `错误: ${d.error || JSON.stringify(d)}`;
        return;
      }
      _uiaTreeData = d.tree;
      const lines = [`共 ${d.node_count} 个控件节点\n`];
      (d.tree || []).forEach(node => {
        const indent = '  '.repeat(node.depth);
        const name = node.name ? `"${node.name}"` : '';
        const aid = node.automation_id ? ` [aid:${node.automation_id}]` : '';
        const cls = node.class_name ? ` (${node.class_name})` : '';
        const kids = node.children_count > 0 ? ` ↳${node.children_count}` : '';
        lines.push(`${indent}${node.type}${cls}${aid} ${name}${kids}`);
      });
      result.textContent = lines.join('\n');
    } catch(e) {
      result.textContent = `请求失败: ${e.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = '🌳 导出控件树';
    }
  };

  window.wxpCopyUIA = function() {
    const result = document.getElementById('wxp-uia-result');
    if (!result.textContent || result.style.display === 'none') {
      showToast('请先导出控件树');
      return;
    }
    navigator.clipboard.writeText(result.textContent).then(
      () => showToast('控件树已复制到剪贴板'),
      () => showToast('复制失败，请手动选择文字')
    );
  };

  // ── 升级处理 ──
  async function wxpRefreshEscalations() {
    try {
      const r = await fetch('/api/wechat/escalations');
      const d = await r.json();
      const list = document.getElementById('wxp-escalations-list');
      const badge = document.getElementById('wxp-esc-count');
      const items = d.escalations || [];
      if (items.length === 0) {
        list.innerHTML = '<div style="color:#8a9bb0;font-size:13px;text-align:center;padding:12px">暂无需要人工处理的消息</div>';
        badge.style.display = 'none';
        return;
      }
      badge.textContent = items.length;
      badge.style.display = 'inline';
      list.innerHTML = items.map(e => `
        <div style="background:rgba(233,69,96,.08);border:1px solid rgba(233,69,96,.2);border-radius:10px;padding:10px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <span style="font-size:13px;font-weight:600;color:#e94560">${e.contact || '未知'}</span>
            <span style="font-size:11px;color:#8a9bb0">${e.reason || '需要人工介入'}</span>
          </div>
          <div style="font-size:12px;color:#c8d0e0;margin-bottom:6px;background:rgba(0,0,0,.2);padding:6px 8px;border-radius:6px">
            <div style="color:#8a9bb0;margin-bottom:4px">收到:</div>
            ${(e.messages || []).map(m => '<div>' + (m.content || m).toString().substring(0,80) + '</div>').join('')}
          </div>
          <div style="font-size:12px;color:#a0b0c8;margin-bottom:8px">
            <span style="color:#8a9bb0">AI 草稿:</span> ${(e.draft_reply || '无').substring(0,60)}
          </div>
          <div style="display:flex;gap:6px">
            <button class="wxp-btn-primary" onclick="wxpEscAction('${e.id}','send_draft')" style="padding:4px 12px;font-size:11px">✅ 发送草稿</button>
            <button class="wxp-btn-secondary" onclick="wxpEscCustom('${e.id}')" style="padding:4px 12px;font-size:11px">✏️ 自定义回复</button>
            <button class="wxp-btn-secondary" onclick="wxpEscAction('${e.id}','dismiss')" style="padding:4px 12px;font-size:11px;color:#888">忽略</button>
          </div>
        </div>
      `).join('');
    } catch(e) {}
  }

  window.wxpEscAction = async function(eid, action, customText) {
    try {
      const body = { action };
      if (customText) body.custom_reply = customText;
      const r = await fetch('/api/wechat/escalations/' + eid, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const d = await r.json();
      showToast(d.ok ? '已处理' : (d.error || '处理失败'));
      wxpRefreshEscalations();
    } catch(e) {
      showToast('请求失败');
    }
  };

  window.wxpEscCustom = function(eid) {
    const text = prompt('输入自定义回复:');
    if (text && text.trim()) {
      wxpEscAction(eid, 'send_custom', text.trim());
    }
  };

  // 在面板刷新时也刷新升级处理
  const _origRefresh = wxpRefresh;
  wxpRefresh = async function() {
    await _origRefresh();
    wxpRefreshEscalations();
  };

  // ── 激活微信窗口 ──
  window.wxpActivate = async function() {
    try {
      const r = await fetch('/api/wechat/activate', { method: 'POST' });
      const d = await r.json();
      showToast(d.message || (d.ok ? '微信已激活' : '激活失败'));
    } catch(e) {
      showToast('请求失败: ' + e.message);
    }
  };

  // ── 智能统计 ──
  window.wxpSmartStats = async function() {
    const el = document.getElementById('wxp-smart-stats');
    el.style.display = 'block';
    el.innerHTML = '<div style="color:#8a9bb0">加载中...</div>';
    try {
      // 获取智能统计 + 状态 + 监控统计
      const [sr, st, mr] = await Promise.all([
        fetch('/api/wechat/smart-stats').then(r=>r.json()).catch(()=>({})),
        fetch('/api/wechat/status').then(r=>r.json()).catch(()=>({})),
        fetch('/api/wechat/monitor-stats').then(r=>r.json()).catch(()=>({})),
      ]);
      const s = mr.stats || {};
      const v2 = st.v2 || {};
      const tracks = v2.tracks || {};
      const se = sr.smart_engine || {};

      // 构建可视化 HTML
      let html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">';

      // 回复统计
      const today = st.today_replied || 0;
      const total = st.total_replied || 0;
      html += `<div style="background:rgba(124,106,239,.1);border-radius:8px;padding:8px;text-align:center">
        <div style="font-size:20px;font-weight:700;color:#7c6aef">${today}</div>
        <div style="font-size:10px;color:#8a9bb0">今日回复</div></div>`;
      html += `<div style="background:rgba(74,222,128,.1);border-radius:8px;padding:8px;text-align:center">
        <div style="font-size:20px;font-weight:700;color:#4ade80">${total}</div>
        <div style="font-size:10px;color:#8a9bb0">总计回复</div></div>`;

      // 轨道状态
      html += '</div><div style="margin-top:8px;font-size:11px">';
      html += '<div style="color:#8a9bb0;margin-bottom:4px">轨道状态</div>';
      for (const [k,t] of Object.entries(tracks)) {
        const avail = t.available;
        const reads = t.reads || 0;
        const color = avail ? (t.healthy ? '#4ade80' : '#fbbf24') : '#555';
        const icon = avail ? (t.healthy ? '✅' : '⚠️') : '⭕';
        html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
          <span>${icon}</span>
          <span style="width:50px;color:${color}">${k}</span>
          <div style="flex:1;height:4px;background:#1a1a2e;border-radius:2px;overflow:hidden">
            <div style="width:${Math.min(100,reads/2)}%;height:100%;background:${color};border-radius:2px"></div>
          </div>
          <span style="color:#666;width:40px;text-align:right">${reads}</span>
        </div>`;
      }

      // 智能引擎
      if (se.total_batches || se.total_messages) {
        html += '<div style="color:#8a9bb0;margin:8px 0 4px">智能引擎</div>';
        html += `<div>消息: ${se.total_messages||0} | 批次: ${se.total_batches||0} | 回复: ${se.total_replies||0} | 升级: ${se.total_escalations||0}</div>`;
      }

      html += '</div>';
      el.innerHTML = html;
    } catch(e) {
      el.innerHTML = `<div style="color:#f87171">请求失败: ${e.message}</div>`;
    }
  };

  // ── 测试发送消息 ──
  window.wxpSendTest = async function() {
    const contact = document.getElementById('wxp-send-contact').value.trim();
    const text = document.getElementById('wxp-send-text').value.trim();
    const el = document.getElementById('wxp-send-result');
    if (!text) { showToast('请输入消息内容'); return; }
    el.textContent = '发送中...';
    el.style.color = '#8a9bb0';
    try {
      const r = await fetch('/api/wechat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contact, text })
      });
      const d = await r.json();
      if (d.ok) {
        el.textContent = '✅ ' + (d.message || '已发送');
        el.style.color = '#4ade80';
        document.getElementById('wxp-send-text').value = '';
      } else {
        el.textContent = '❌ ' + (d.message || d.error || '发送失败');
        el.style.color = '#f87171';
      }
    } catch(e) {
      el.textContent = '❌ 请求失败: ' + e.message;
      el.style.color = '#f87171';
    }
  };
}
