// settings-models.js — Model Management, MCP Tools, and Model Dependency Graph
// Extracted from settings.js

import { getBaseUrl, t } from '/js/state.js';

// ══════════════════════════════════════════════════════════════
// 1. MODEL MANAGEMENT PANEL
// ══════════════════════════════════════════════════════════════
export function initModelPanel() {
  const $id = id => document.getElementById(id);
  let _modelsLoaded = false;

  async function openModelPanel() {
    $id('model-panel').classList.remove('hidden');
    if (!_modelsLoaded) {
      _modelsLoaded = true;
      $id('mp-models-list').innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">加载中…</div>';
      await Promise.all([loadModels(), loadSystemInfo()]);
    }
  }

  function closeModelPanel() {
    $id('model-panel').classList.add('hidden');
  }

  async function loadSystemInfo() {
    try {
      const [gpuR, diskR] = await Promise.all([
        fetch(getBaseUrl() + '/api/system/gpu').then(r => r.json()).catch(() => ({})),
        fetch(getBaseUrl() + '/api/system/disk').then(r => r.json()).catch(() => ({})),
      ]);
      $id('mp-gpu-name').textContent = gpuR.available ? gpuR.name : '无 GPU';
      $id('mp-vram').textContent = gpuR.available ? gpuR.vram_gb + ' GB' : '—';
      $id('mp-disk').textContent = diskR.free_gb ? diskR.free_gb + ' GB' : '—';
    } catch(e) { console.warn('model sys info:', e); }
  }

  async function loadModels() {
    try {
      const r = await fetch(getBaseUrl() + '/api/models');
      const d = await r.json();
      $id('mp-mode-badge').textContent = d.mode === 'full' ? '完整模式' : '极简模式';
      $id('mp-mode-badge').style.color = d.mode === 'full' ? 'var(--success)' : 'var(--text-muted)';
      renderModels(d.models || []);
    } catch(e) {
      $id('mp-models-list').innerHTML = '<div class="mcp-empty">无法加载模型列表</div>';
    }
  }

  let _batchSelected = new Set();

  function renderModels(models) {
    const cats = {};
    models.forEach(m => {
      (cats[m.category] = cats[m.category] || []).push(m);
    });
    _batchSelected.clear();
    updateBatchBar();
    const catNames = { stt: '🎤 语音识别', runtime: '⚡ 运行时', vad: '🔊 语音检测', vision: '👁️ 视觉控制' };
    let html = '';
    for (const [cat, list] of Object.entries(cats)) {
      html += `<div class="mp-cat-title">${catNames[cat] || cat}</div>`;
      list.forEach(m => {
        const gpuTag = m.requires_gpu ? `<span style="color:var(--warning)">🖥 GPU ${m.min_vram_gb}GB+</span>` : '<span>CPU</span>';
        let btn;
        if (m.installed) {
          btn = `<button class="mp-btn mp-btn-installed">✓ 已安装</button>
                 <button class="mp-btn mp-btn-bench" data-id="${m.id}" style="margin-left:4px;font-size:10px" data-i18n="model.bench">⚡ 测试</button>
                 <button class="mp-btn mp-btn-uninstall" data-id="${m.id}" style="margin-left:4px">卸载</button>`;
        } else {
          btn = `<input type="checkbox" class="mp-check mp-batch-check" data-id="${m.id}">
                 <button class="mp-btn mp-btn-install" data-id="${m.id}">安装</button>`;
        }
        html += `<div class="mp-model-card" id="mp-card-${m.id}">
          <div class="mp-model-info">
            <div class="mp-model-name">${m.name}</div>
            <div class="mp-model-desc">${m.description}</div>
            <div class="mp-model-meta">${gpuTag} <span>${m.size_mb} MB</span></div>
          </div>
          <div style="display:flex;align-items:center;gap:4px">${btn}</div>
        </div>`;
      });
    }
    $id('mp-models-list').innerHTML = html;

    $id('mp-models-list').querySelectorAll('.mp-btn-install').forEach(btn => {
      btn.addEventListener('click', () => installModel(btn.dataset.id, btn));
    });
    $id('mp-models-list').querySelectorAll('.mp-btn-uninstall').forEach(btn => {
      btn.addEventListener('click', () => uninstallModel(btn.dataset.id));
    });
    $id('mp-models-list').querySelectorAll('.mp-btn-bench').forEach(btn => {
      btn.addEventListener('click', () => benchmarkModel(btn.dataset.id, btn));
    });
    $id('mp-models-list').querySelectorAll('.mp-batch-check').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) _batchSelected.add(cb.dataset.id);
        else _batchSelected.delete(cb.dataset.id);
        updateBatchBar();
      });
    });
  }

  const BENCH_KEY = 'oc-bench-cache';
  let _benchCache = JSON.parse(localStorage.getItem(BENCH_KEY) || '{}');

  async function benchmarkModel(id, btn) {
    if (_benchCache[id]) {
      showBenchResult(id, _benchCache[id], btn);
      return;
    }
    const orig = btn.textContent;
    btn.disabled = true; btn.textContent = t('model.benching');
    try {
      const r = await fetch(getBaseUrl() + `/api/models/benchmark`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({model_id: id}) });
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      _benchCache[id] = d;
      localStorage.setItem(BENCH_KEY, JSON.stringify(_benchCache));
      showBenchResult(id, d, btn);
      window.ocToast?.success(t('model.benchDone'));
    } catch(e) {
      window.ocToast?.error(t('model.benchFail') + ': ' + e.message);
    }
    btn.disabled = false; btn.textContent = orig;
  }

  function showBenchResult(id, data, btn) {
    const card = btn.closest('.mp-model-card');
    if (!card) return;
    let el = card.querySelector('.bench-result');
    if (!el) { el = document.createElement('div'); el.className = 'bench-result'; card.appendChild(el); }
    const speed = data.tokens_per_second ?? data.speed ?? '—';
    const ttft = data.time_to_first_token ?? data.ttft ?? '—';
    el.innerHTML = `<span class="bench-metric">${t('model.benchSpeed')}: <span class="bench-val">${typeof speed === 'number' ? speed.toFixed(1) : speed} ${t('model.benchTokens')}</span></span>`
      + `<span class="bench-metric">${t('model.benchTTFT')}: <span class="bench-val">${typeof ttft === 'number' ? ttft.toFixed(0) + 'ms' : ttft}</span></span>`;
  }

  function updateBatchBar() {
    const bar = $id('mp-batch-bar');
    if (_batchSelected.size > 0) {
      bar.classList.add('visible');
      $id('mp-batch-count').textContent = `已选 ${_batchSelected.size} 个模型`;
    } else {
      bar.classList.remove('visible');
    }
  }

  async function batchInstall() {
    const ids = [..._batchSelected];
    if (ids.length === 0) return;
    const status = $id('mp-queue-status');
    status.style.display = 'block';
    $id('mp-batch-install').disabled = true;
    for (let i = 0; i < ids.length; i++) {
      status.textContent = `队列进度: ${i + 1}/${ids.length} — 正在安装 ${ids[i]}…`;
      const card = $id('mp-card-' + ids[i]);
      const btn = card?.querySelector('.mp-btn-install');
      if (btn) await installModel(ids[i], btn);
    }
    status.textContent = `✓ 队列完成: ${ids.length} 个模型`;
    window.ocToast?.success('批量安装完成: ' + ids.length + ' 个模型');
    $id('mp-batch-install').disabled = false;
    _batchSelected.clear();
    updateBatchBar();
    setTimeout(() => { status.style.display = 'none'; }, 3000);
  }

  function clearBatchSelection() {
    _batchSelected.clear();
    $id('mp-models-list').querySelectorAll('.mp-batch-check').forEach(cb => cb.checked = false);
    updateBatchBar();
  }

  $id('mp-batch-install')?.addEventListener('click', batchInstall);
  $id('mp-batch-clear')?.addEventListener('click', clearBatchSelection);

  let _installAbort = null;

  async function installModel(id, btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = '安装中…';
    const card = $id('mp-card-' + id);

    let progBar = card.querySelector('.mp-progress');
    if (!progBar) {
      progBar = document.createElement('div');
      progBar.className = 'mp-progress';
      progBar.innerHTML = '<div class="mp-progress-fill" style="width:0%"></div>';
      card.appendChild(progBar);
    }
    const fill = progBar.querySelector('.mp-progress-fill');

    let cancelBtn = card.querySelector('.mp-btn-cancel');
    if (!cancelBtn) {
      cancelBtn = document.createElement('button');
      cancelBtn.className = 'mp-btn mp-btn-cancel';
      cancelBtn.textContent = '取消';
      cancelBtn.style.marginTop = '6px';
      card.appendChild(cancelBtn);
    }
    cancelBtn.classList.remove('hidden');

    _installAbort = new AbortController();
    cancelBtn.onclick = () => {
      if (_installAbort) _installAbort.abort();
      btnEl.textContent = '已取消';
      btnEl.disabled = false;
      cancelBtn.classList.add('hidden');
      fill.style.width = '0%';
      window.ocToast?.info('安装已取消');
      setTimeout(() => { if (progBar.parentNode) progBar.remove(); }, 1500);
    };

    try {
      const resp = await fetch(getBaseUrl() + `/api/models/${id}/install`, {
        method: 'POST', signal: _installAbort.signal,
      });
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          try {
            const ev = JSON.parse(line.slice(5).trim());
            if (ev.type === 'progress' && ev.percent >= 0) {
              fill.style.width = ev.percent + '%';
              btnEl.textContent = ev.message || '安装中…';
            }
            if (ev.type === 'done') {
              cancelBtn.classList.add('hidden');
              if (ev.success) {
                btnEl.textContent = '验证中…';
                let verifyOk = true;
                try {
                  const chk = await fetch(getBaseUrl() + `/api/models/${id}/check`);
                  const chkD = await chk.json();
                  if (!chkD.installed) {
                    verifyOk = false;
                    const warn = document.createElement('div');
                    warn.style.cssText = 'font-size:11px;color:var(--warning);margin-top:4px';
                    warn.textContent = '⚠️ 安装完成但验证失败，模块可能无法导入';
                    card.appendChild(warn);
                    window.ocToast?.warning('模型 ' + id + ' 验证失败');
                  }
                } catch {}
                if (verifyOk) window.ocToast?.success('模型 ' + id + ' 安装成功');
                _modelsLoaded = false;
                await loadModels();
              } else {
                btnEl.textContent = '安装失败';
                btnEl.disabled = false;
                window.ocToast?.error('模型 ' + id + ' 安装失败');
              }
            }
          } catch {}
        }
      }
    } catch(e) {
      if (e.name === 'AbortError') return;
      btnEl.textContent = '安装失败';
      btnEl.disabled = false;
      cancelBtn.classList.add('hidden');
    } finally {
      _installAbort = null;
    }
  }

  async function uninstallModel(id) {
    if (!confirm('确定要卸载此模型？')) return;
    try {
      await fetch(getBaseUrl() + `/api/models/${id}/uninstall`, { method: 'POST' });
      window.ocToast?.success('模型 ' + id + ' 已卸载');
      _modelsLoaded = false;
      await loadModels();
    } catch(e) { console.warn('uninstall:', e); }
  }

  $id('model-panel-toggle')?.addEventListener('click', openModelPanel);
  $id('mp-back')?.addEventListener('click', closeModelPanel);
}

// ══════════════════════════════════════════════════════════════
// 2. MCP TOOLS PANEL
// ══════════════════════════════════════════════════════════════
export function initMcpPanel() {
  const $id = id => document.getElementById(id);
  let _mcpLoaded = false;

  async function openMcpPanel() {
    $id('mcp-panel').classList.remove('hidden');
    if (!_mcpLoaded) {
      _mcpLoaded = true;
      await loadMcpData();
    }
  }

  function closeMcpPanel() {
    $id('mcp-panel').classList.add('hidden');
  }

  async function loadMcpData() {
    await Promise.all([loadServers(), loadTools(), loadSkills()]);
  }

  async function loadServers() {
    try {
      const r = await fetch(getBaseUrl() + '/api/mcp/servers');
      const d = await r.json();
      const list = $id('mcp-servers-list');
      const noSrv = $id('mcp-no-servers');
      if (!d.servers || d.servers.length === 0) {
        list.innerHTML = '';
        noSrv.classList.remove('hidden');
        return;
      }
      noSrv.classList.add('hidden');
      list.innerHTML = d.servers.map(s => `
        <div class="mcp-server-card">
          <div class="mcp-server-header">
            <span class="mcp-server-name">${s.name}</span>
            <span class="mcp-server-badge ${s.connected ? 'connected' : ''}">${s.connected ? '已连接' : '未连接'}</span>
          </div>
          <div style="font-size:11px;color:var(--text-muted)">
            ${s.transport.toUpperCase()} · ${s.tools_count} 工具
          </div>
          ${!s.connected ? `<button class="mp-btn mp-btn-install" style="margin-top:8px;font-size:11px;padding:4px 12px" onclick="mcpConnect('${s.id}')">连接</button>` : ''}
        </div>
      `).join('');
    } catch(e) {
      $id('mcp-no-servers').classList.remove('hidden');
    }
  }

  window.mcpConnect = async function(id) {
    try {
      const r = await fetch(getBaseUrl() + `/api/mcp/connect/${id}`, { method: 'POST' });
      const d = await r.json();
      if (d.ok) {
        _mcpLoaded = false;
        await loadMcpData();
      }
    } catch(e) { console.warn('mcp connect:', e); }
  };

  let _toolsData = [];
  let _activeToolName = null;
  let _favTools = JSON.parse(localStorage.getItem('oc-mcp-favs') || '[]');

  function saveFavs() { localStorage.setItem('oc-mcp-favs', JSON.stringify(_favTools)); }

  function toggleFav(name, starEl) {
    const idx = _favTools.indexOf(name);
    if (idx >= 0) { _favTools.splice(idx, 1); starEl.classList.remove('starred'); starEl.textContent = '☆'; }
    else { _favTools.push(name); starEl.classList.add('starred'); starEl.textContent = '★'; }
    saveFavs();
    reorderToolChips();
  }

  function reorderToolChips() {
    const list = $id('mcp-tools-list');
    const chips = [...list.querySelectorAll('.mcp-tool-chip')];
    chips.sort((a, b) => {
      const aFav = _favTools.includes(a.dataset.tool) ? 0 : 1;
      const bFav = _favTools.includes(b.dataset.tool) ? 0 : 1;
      return aFav - bFav;
    });
    chips.forEach(c => list.appendChild(c));
  }

  async function loadTools() {
    try {
      const r = await fetch(getBaseUrl() + '/api/mcp/tools');
      const d = await r.json();
      _toolsData = d.tools || [];
      const list = $id('mcp-tools-list');
      const noTools = $id('mcp-no-tools');
      $id('mcp-tools-count').textContent = d.count ? `${d.count} 个工具` : '';
      if (_toolsData.length === 0) {
        list.innerHTML = '';
        noTools.classList.remove('hidden');
        return;
      }
      noTools.classList.add('hidden');
      const sorted = [..._toolsData].sort((a, b) => {
        const af = _favTools.includes(a.name) ? 0 : 1;
        const bf = _favTools.includes(b.name) ? 0 : 1;
        return af - bf;
      });
      list.innerHTML = sorted.map(t => {
        const isFav = _favTools.includes(t.name);
        return `<span class="mcp-tool-chip" data-tool="${t.name}" title="${(t.description || t.name).replace(/"/g,'&quot;')}">⚙️ ${t.name}<span class="fav-star ${isFav ? 'starred' : ''}" data-fav="${t.name}">${isFav ? '★' : '☆'}</span></span>`;
      }).join('');
      list.querySelectorAll('.mcp-tool-chip').forEach(chip => {
        chip.addEventListener('click', (e) => {
          if (e.target.classList.contains('fav-star')) return;
          openToolDrawer(chip.dataset.tool);
        });
      });
      list.querySelectorAll('.fav-star').forEach(star => {
        star.addEventListener('click', (e) => {
          e.stopPropagation();
          toggleFav(star.dataset.fav, star);
        });
      });
    } catch(e) {
      $id('mcp-no-tools').classList.remove('hidden');
    }
  }

  let _activeSchema = {};

  function buildFormFromSchema(schema) {
    const form = $id('mcp-tool-form');
    const props = schema.properties || {};
    const required = new Set(schema.required || []);
    const keys = Object.keys(props);
    if (keys.length === 0) {
      form.innerHTML = '<div class="mcp-form-empty">此工具无需参数</div>';
      return;
    }
    form.innerHTML = keys.map(key => {
      const p = props[key];
      const type = p.type || 'string';
      const req = required.has(key);
      const desc = p.description || '';
      const def = p.default ?? '';
      let input;
      if (type === 'boolean') {
        input = `<label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-primary)"><input type="checkbox" class="mcp-form-input" data-key="${key}" ${def ? 'checked' : ''}> ${desc || key}</label>`;
      } else if (p.enum && p.enum.length > 0) {
        const opts = p.enum.map(v => `<option value="${v}" ${v === def ? 'selected' : ''}>${v}</option>`).join('');
        input = `<select class="mcp-form-input" data-key="${key}">${opts}</select>`;
      } else if (type === 'integer' || type === 'number') {
        const min = p.minimum != null ? `min="${p.minimum}"` : '';
        const max = p.maximum != null ? `max="${p.maximum}"` : '';
        input = `<input type="number" class="mcp-form-input" data-key="${key}" value="${def}" ${min} ${max} placeholder="${desc || key}">`;
      } else {
        input = `<input type="text" class="mcp-form-input" data-key="${key}" value="${def}" placeholder="${desc || key}">`;
      }
      return `<div class="mcp-form-field">
        <label>${key}${req ? '<span class="field-req">*</span>' : ''}<span class="field-type">${type}</span></label>
        ${input}
        ${desc && type !== 'boolean' ? `<div class="mcp-form-hint">${desc}</div>` : ''}
      </div>`;
    }).join('');
  }

  function collectFormParams() {
    const params = {};
    $id('mcp-tool-form').querySelectorAll('.mcp-form-input').forEach(el => {
      const key = el.dataset.key;
      if (el.type === 'checkbox') params[key] = el.checked;
      else if (el.type === 'number') params[key] = el.value === '' ? null : Number(el.value);
      else params[key] = el.value;
    });
    return params;
  }

  function syncFormToJson() {
    $id('mcp-tool-params').value = JSON.stringify(collectFormParams(), null, 2);
  }

  function openToolDrawer(name) {
    const tool = _toolsData.find(x => x.name === name);
    if (!tool) return;
    _activeToolName = name;
    _activeSchema = tool.input_schema || tool.parameters || {};
    $id('mcp-drawer-title').textContent = '⚙️ ' + name;
    $id('mcp-drawer-desc').textContent = tool.description || '';
    buildFormFromSchema(_activeSchema);
    const defaultParams = {};
    const props = _activeSchema.properties || {};
    for (const [k, v] of Object.entries(props)) defaultParams[k] = v.default ?? '';
    $id('mcp-tool-params').value = Object.keys(props).length ? JSON.stringify(defaultParams, null, 2) : '{}';
    $id('mcp-tool-form').querySelectorAll('.mcp-form-input').forEach(el => {
      el.addEventListener('input', syncFormToJson);
      el.addEventListener('change', syncFormToJson);
    });
    $id('mcp-tool-result').textContent = '';
    $id('mcp-tool-result').classList.remove('visible');
    $id('mcp-tool-drawer').classList.add('open');
    $id('mcp-tools-list').querySelectorAll('.mcp-tool-chip').forEach(c => c.classList.toggle('active', c.dataset.tool === name));
  }

  function closeToolDrawer() {
    $id('mcp-tool-drawer').classList.remove('open');
    _activeToolName = null;
    $id('mcp-tools-list').querySelectorAll('.mcp-tool-chip').forEach(c => c.classList.remove('active'));
  }

  // Reference to mcpHistory from the main module (it's on window via the IIFE)
  const mcpHistory = window._mcpHistoryRef;

  async function runTool() {
    if (!_activeToolName) return;
    const btn = $id('mcp-tool-run');
    const resultEl = $id('mcp-tool-result');
    btn.disabled = true; btn.textContent = '调用中…';
    let params;
    const hasFormFields = $id('mcp-tool-form').querySelector('.mcp-form-input');
    if (hasFormFields) {
      params = collectFormParams();
    } else {
      try { params = JSON.parse($id('mcp-tool-params').value || '{}'); }
      catch { resultEl.textContent = '⚠️ JSON 参数格式错误'; resultEl.classList.add('visible'); btn.disabled = false; btn.textContent = '▶ 调用'; return; }
    }
    try {
      const r = await fetch(getBaseUrl() + '/api/mcp/tool/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_name: _activeToolName, arguments: params }),
      });
      const d = await r.json();
      if (d.ok) {
        resultEl.textContent = typeof d.result === 'string' ? d.result : JSON.stringify(d.result, null, 2);
        if (mcpHistory) mcpHistory.add(_activeToolName, params, d.result, true);
      } else {
        resultEl.textContent = '❌ ' + (d.error || '调用失败');
        if (mcpHistory) mcpHistory.add(_activeToolName, params, d.error || '调用失败', false);
      }
    } catch(e) {
      resultEl.textContent = '❌ 网络错误: ' + e.message;
    }
    resultEl.classList.add('visible');
    btn.disabled = false; btn.textContent = '▶ 调用';
  }

  window._mcpReplayCallback = function(toolName, params) {
    openToolDrawer(toolName);
    $id('mcp-tool-params').value = JSON.stringify(params, null, 2);
    const form = $id('mcp-tool-form');
    if (form) {
      form.querySelectorAll('.mcp-form-input').forEach(el => {
        const key = el.dataset.key;
        if (key && params[key] !== undefined) {
          if (el.type === 'checkbox') el.checked = !!params[key];
          else el.value = params[key];
        }
      });
    }
  };

  $id('mcp-tool-run')?.addEventListener('click', runTool);
  $id('mcp-tool-close')?.addEventListener('click', closeToolDrawer);

  async function loadSkills() {
    try {
      const r = await fetch(getBaseUrl() + '/api/mcp/skills');
      const d = await r.json();
      const list = $id('mcp-skills-list');
      const noSk = $id('mcp-no-skills');
      if (!d.skills || d.skills.length === 0) {
        list.innerHTML = '';
        noSk.classList.remove('hidden');
        return;
      }
      noSk.classList.add('hidden');
      list.innerHTML = d.skills.map(s => `
        <div class="mcp-skill-card">
          <div style="flex:1">
            <div class="sk-name">${s.name_zh || s.id}</div>
            <div class="sk-desc">${(s.description || '').slice(0, 60)}</div>
          </div>
          <button class="mp-btn mp-btn-uninstall" style="font-size:11px;padding:4px 10px" onclick="mcpDeleteSkill('${s.id}')">删除</button>
        </div>
      `).join('');
    } catch(e) {
      $id('mcp-no-skills').classList.remove('hidden');
    }
  }

  window.mcpDeleteSkill = async function(id) {
    if (!confirm('删除此技能？')) return;
    try {
      await fetch(getBaseUrl() + `/api/mcp/skills/${id}`, { method: 'DELETE' });
      _mcpLoaded = false;
      await loadSkills();
    } catch(e) { console.warn('delete skill:', e); }
  };

  async function generateSkill() {
    const input = $id('mcp-skill-input');
    const desc = input.value.trim();
    if (!desc) return;
    const btn = $id('mcp-gen-skill-btn');
    btn.disabled = true;
    btn.textContent = '生成中…';
    try {
      const r = await fetch(getBaseUrl() + '/api/mcp/skills/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: desc }),
      });
      const d = await r.json();
      if (d.ok) {
        input.value = '';
        _mcpLoaded = false;
        await loadSkills();
      }
    } catch(e) { console.warn('gen skill:', e); }
    btn.disabled = false;
    btn.textContent = '✨ 生成技能';
  }

  async function addServer() {
    const name = $id('mcp-srv-name')?.value.trim();
    const transport = $id('mcp-srv-transport')?.value || 'stdio';
    const cmdOrUrl = $id('mcp-srv-cmd')?.value.trim();
    if (!name || !cmdOrUrl) return;
    const id = name.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
    const btn = $id('mcp-add-srv-btn');
    btn.disabled = true; btn.textContent = '添加中…';
    try {
      const body = { id, name, transport };
      if (transport === 'stdio') body.command = cmdOrUrl;
      else body.url = cmdOrUrl;
      const r = await fetch(getBaseUrl() + '/api/mcp/servers/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.ok) {
        $id('mcp-srv-name').value = '';
        $id('mcp-srv-cmd').value = '';
        $id('mcp-add-form').open = false;
        _mcpLoaded = false;
        await loadMcpData();
      }
    } catch(e) { console.warn('add server:', e); }
    btn.disabled = false; btn.textContent = '添加服务器';
  }

  $id('mcp-panel-toggle')?.addEventListener('click', openMcpPanel);
  $id('mcp-back')?.addEventListener('click', closeMcpPanel);
  $id('mcp-gen-skill-btn')?.addEventListener('click', generateSkill);
  $id('mcp-skill-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') generateSkill(); });
  $id('mcp-add-srv-btn')?.addEventListener('click', addServer);
}

// ══════════════════════════════════════════════════════════════
// 21. MODEL DEPENDENCY GRAPH
// ══════════════════════════════════════════════════════════════
export function initModelDepGraph() {
  const $id = id => document.getElementById(id);

  const DEPS = {
    'SenseVoice': ['onnxruntime'],
    'FunASR':     ['onnxruntime', 'torch'],
    'ChatTTS':    ['torch', 'vocos'],
    'CosyVoice':  ['torch', 'onnxruntime'],
    'GPT-SoVITS': ['torch', 'ffmpeg'],
    'Whisper':    ['torch', 'ffmpeg'],
    'XTTS-v2':    ['torch'],
    'MeloTTS':    ['torch', 'mecab'],
    'EdgeTTS':    [],
    'torch':      ['cuda-toolkit'],
    'onnxruntime':['cuda-toolkit'],
    'vocos':      ['torch'],
  };

  let _models = [];
  let _viewMode = 'list';

  $id('mp-view-list')?.addEventListener('click', () => {
    _viewMode = 'list';
    $id('mp-view-list').style.background = 'var(--accent)'; $id('mp-view-list').style.color = '#fff';
    $id('mp-view-deps').style.background = 'var(--bg-surface)'; $id('mp-view-deps').style.color = 'var(--text-secondary)';
    $id('mp-models-list').style.display = '';
    $id('mp-dep-graph').style.display = 'none';
  });

  $id('mp-view-deps')?.addEventListener('click', () => {
    _viewMode = 'deps';
    $id('mp-view-deps').style.background = 'var(--accent)'; $id('mp-view-deps').style.color = '#fff';
    $id('mp-view-list').style.background = 'var(--bg-surface)'; $id('mp-view-list').style.color = 'var(--text-secondary)';
    $id('mp-models-list').style.display = 'none';
    $id('mp-dep-graph').style.display = '';
    drawDeps();
  });

  function getInstalled() {
    const items = document.querySelectorAll('#mp-models-list .mp-card');
    const installed = new Set();
    items.forEach(card => {
      const badge = card.querySelector('.mp-status');
      if (badge && (badge.textContent.includes('✅') || badge.textContent.includes('已安装') || badge.textContent.includes('Installed'))) {
        const name = card.querySelector('.mp-name')?.textContent?.trim();
        if (name) installed.add(name);
      }
    });
    return installed;
  }

  function drawDeps() {
    const canvas = $id('mp-dep-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = 320 * dpr;
    canvas.style.height = '320px';
    ctx.scale(dpr, dpr);
    const W = rect.width, H = 320;
    ctx.clearRect(0, 0, W, H);

    const installed = getInstalled();
    const allNodes = new Set();
    Object.keys(DEPS).forEach(k => { allNodes.add(k); (DEPS[k] || []).forEach(d => allNodes.add(d)); });
    const nodeArr = Array.from(allNodes);

    const depth = {};
    const childOf = {};
    nodeArr.forEach(n => { depth[n] = -1; childOf[n] = []; });
    Object.entries(DEPS).forEach(([parent, deps]) => { deps.forEach(d => { if (childOf[d]) childOf[d].push(parent); }); });
    const roots = nodeArr.filter(n => !(DEPS[n] && DEPS[n].length > 0));
    const queue = [...roots];
    roots.forEach(r => depth[r] = 0);
    while (queue.length) {
      const cur = queue.shift();
      childOf[cur].forEach(ch => {
        if (depth[ch] < depth[cur] + 1) { depth[ch] = depth[cur] + 1; queue.push(ch); }
      });
    }
    nodeArr.forEach(n => { if (depth[n] < 0) depth[n] = 0; });
    const maxDepth = Math.max(...Object.values(depth), 0);
    const levels = [];
    for (let d = 0; d <= maxDepth; d++) levels.push(nodeArr.filter(n => depth[n] === d));

    const nodePos = {};
    const nodeW = 90, nodeH = 28, padX = 30, padY = 50;
    const totalH = (maxDepth + 1) * (nodeH + padY);
    const startY = Math.max(20, (H - totalH) / 2);

    levels.forEach((lvl, d) => {
      const totalW = lvl.length * nodeW + (lvl.length - 1) * padX;
      const startX = (W - totalW) / 2;
      lvl.forEach((n, i) => {
        nodePos[n] = { x: startX + i * (nodeW + padX), y: startY + d * (nodeH + padY) };
      });
    });

    ctx.lineWidth = 1.5;
    Object.entries(DEPS).forEach(([parent, deps]) => {
      deps.forEach(dep => {
        if (!nodePos[parent] || !nodePos[dep]) return;
        const from = nodePos[dep];
        const to = nodePos[parent];
        ctx.strokeStyle = installed.has(dep) ? '#22c55e' : '#ef4444';
        ctx.globalAlpha = 0.4;
        ctx.beginPath();
        ctx.moveTo(from.x + nodeW / 2, from.y + nodeH);
        ctx.bezierCurveTo(from.x + nodeW / 2, from.y + nodeH + padY * 0.4, to.x + nodeW / 2, to.y - padY * 0.4, to.x + nodeW / 2, to.y);
        ctx.stroke();
        const ax = to.x + nodeW / 2, ay = to.y;
        ctx.beginPath(); ctx.moveTo(ax - 4, ay - 6); ctx.lineTo(ax, ay); ctx.lineTo(ax + 4, ay - 6); ctx.stroke();
        ctx.globalAlpha = 1;
      });
    });

    nodeArr.forEach(n => {
      if (!nodePos[n]) return;
      const p = nodePos[n];
      const isInst = installed.has(n);
      ctx.fillStyle = isInst ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.1)';
      ctx.strokeStyle = isInst ? '#22c55e' : '#ef4444';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.roundRect(p.x, p.y, nodeW, nodeH, 6);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = isInst ? '#22c55e' : '#ef4444';
      ctx.font = '11px system-ui, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      const label = n.length > 12 ? n.slice(0, 11) + '…' : n;
      ctx.fillText(label, p.x + nodeW / 2, p.y + nodeH / 2);
    });
  }

  const observer = new MutationObserver(() => {
    if (_viewMode === 'deps') setTimeout(drawDeps, 200);
  });
  const ml = $id('mp-models-list');
  if (ml) observer.observe(ml, { childList: true, subtree: true });
}
