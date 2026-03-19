// settings-chat.js — Chat feature inits (search, bookmarks, reactions, translate, export, edit, pin, summary)
// Extracted from settings.js

import { S, fn, dom, t, $, getBaseUrl, escapeHtml } from '/js/state.js';

// ══════════════════════════════════════════════════════════════
// 25. MESSAGE SEARCH
// ══════════════════════════════════════════════════════════════
export function initMessageSearch() {
  const $id = id => document.getElementById(id);
  let _matches = [];
  let _currentIdx = -1;
  let _originalContents = new Map();

  function open() {
    $id('msg-search-bar')?.classList.add('open');
    const input = $id('msg-search-input');
    if (input) { input.value = ''; input.focus(); }
    $id('msg-search-count').textContent = '';
    clearHighlights();
  }

  function close() {
    $id('msg-search-bar')?.classList.remove('open');
    clearHighlights();
    _matches = []; _currentIdx = -1;
  }

  function clearHighlights() {
    _originalContents.forEach((html, el) => { el.innerHTML = html; });
    _originalContents.clear();
  }

  function search(query) {
    clearHighlights();
    _matches = []; _currentIdx = -1;
    if (!query.trim()) { $id('msg-search-count').textContent = ''; return; }

    const q = query.toLowerCase();
    const msgs = document.querySelectorAll('#messages-area .msg .msg-text, #messages-area .msg .msg-content');
    msgs.forEach(el => {
      const text = el.textContent;
      if (text.toLowerCase().includes(q)) {
        _originalContents.set(el, el.innerHTML);
        const regex = new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        el.innerHTML = el.innerHTML.replace(regex, '<mark class="search-hl">$1</mark>');
        el.querySelectorAll('mark.search-hl').forEach(m => _matches.push(m));
      }
    });

    const countEl = $id('msg-search-count');
    if (_matches.length === 0) {
      countEl.textContent = t('search.noResults');
    } else {
      _currentIdx = 0;
      highlightCurrent();
    }
  }

  function highlightCurrent() {
    _matches.forEach((m, i) => m.classList.toggle('active', i === _currentIdx));
    if (_matches[_currentIdx]) {
      _matches[_currentIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    const countEl = $id('msg-search-count');
    countEl.textContent = t('search.count').replace('{x}', _currentIdx + 1).replace('{y}', _matches.length);
  }

  function next() {
    if (_matches.length === 0) return;
    _currentIdx = (_currentIdx + 1) % _matches.length;
    highlightCurrent();
  }

  function prev() {
    if (_matches.length === 0) return;
    _currentIdx = (_currentIdx - 1 + _matches.length) % _matches.length;
    highlightCurrent();
  }

  $id('msg-search-input')?.addEventListener('input', (e) => search(e.target.value));
  $id('msg-search-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.shiftKey ? prev() : next(); e.preventDefault(); }
    if (e.key === 'Escape') { close(); e.preventDefault(); }
  });
  $id('msg-search-prev')?.addEventListener('click', prev);
  $id('msg-search-next')?.addEventListener('click', next);
  $id('msg-search-close')?.addEventListener('click', close);

  const ocMsgSearch = { open, close };
  window.ocMsgSearch = ocMsgSearch;
  fn.ocMsgSearch = ocMsgSearch;
}

// ══════════════════════════════════════════════════════════════
// 27. MESSAGE BOOKMARKS
// ══════════════════════════════════════════════════════════════
export function initBookmarks() {
  const $id = id => document.getElementById(id);
  const BKEY = 'oc-bookmarks';
  let _bookmarks = JSON.parse(localStorage.getItem(BKEY) || '[]');
  let _msgCounter = 0;

  function save() { localStorage.setItem(BKEY, JSON.stringify(_bookmarks)); }

  function attachBookmarkBtn(msgEl) {
    const id = 'msg-' + (++_msgCounter);
    msgEl.dataset.msgId = id;
    const btn = document.createElement('button');
    btn.className = 'msg-bookmark-btn';
    btn.textContent = '☆';
    btn.title = t('bm.title') || 'Bookmark';
    const existing = _bookmarks.find(b => b.text === getTextContent(msgEl));
    if (existing) { btn.classList.add('starred'); btn.textContent = '★'; msgEl.classList.add('bookmarked'); }
    btn.addEventListener('click', (e) => { e.stopPropagation(); toggleBookmark(msgEl, btn); });
    msgEl.appendChild(btn);
  }

  function getTextContent(msgEl) {
    const textEl = msgEl.querySelector('.msg-text');
    return textEl ? textEl.textContent.trim().slice(0, 200) : '';
  }

  function toggleBookmark(msgEl, btn) {
    const text = getTextContent(msgEl);
    const idx = _bookmarks.findIndex(b => b.text === text);
    if (idx >= 0) {
      _bookmarks.splice(idx, 1);
      btn.classList.remove('starred'); btn.textContent = '☆';
      msgEl.classList.remove('bookmarked');
      window.ocToast?.info(t('bm.removed'));
    } else {
      const role = msgEl.classList.contains('user') ? 'user' : 'ai';
      _bookmarks.push({ text, role, time: Date.now(), msgId: msgEl.dataset.msgId });
      btn.classList.add('starred'); btn.textContent = '★';
      msgEl.classList.add('bookmarked');
      window.ocToast?.success(t('bm.added'));
    }
    save();
    if ($id('bookmark-panel')?.classList.contains('open')) renderPanel();
  }

  function renderPanel() {
    const list = $id('bm-list');
    if (_bookmarks.length === 0) {
      list.innerHTML = `<div class="bm-empty" data-i18n="bm.empty">${t('bm.empty')}</div>`;
      return;
    }
    list.innerHTML = _bookmarks.slice().reverse().map((b, ri) => {
      const idx = _bookmarks.length - 1 - ri;
      const d = new Date(b.time);
      const ts = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
      const icon = b.role === 'user' ? '👤' : '🦞';
      return `<div class="bm-item" data-idx="${idx}">
        <div class="bm-text">${icon} ${b.text}</div>
        <div class="bm-meta">
          <span class="bm-time">${ts}</span>
          <button class="bm-remove" data-idx="${idx}">${t('bm.remove')}</button>
        </div>
      </div>`;
    }).join('');
    list.querySelectorAll('.bm-item').forEach(el => {
      el.addEventListener('click', (e) => {
        if (e.target.classList.contains('bm-remove')) return;
        const b = _bookmarks[+el.dataset.idx];
        if (!b) return;
        $id('bookmark-panel').classList.remove('open');
        const msgs = document.querySelectorAll('#messages-area .msg');
        for (const m of msgs) {
          if (getTextContent(m) === b.text) { m.scrollIntoView({ behavior: 'smooth', block: 'center' }); m.style.outline = '2px solid var(--accent)'; setTimeout(() => m.style.outline = '', 2000); break; }
        }
      });
    });
    list.querySelectorAll('.bm-remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = +btn.dataset.idx;
        const removed = _bookmarks[idx];
        _bookmarks.splice(idx, 1); save(); renderPanel();
        if (removed) {
          const msgs = document.querySelectorAll('#messages-area .msg');
          for (const m of msgs) {
            if (getTextContent(m) === removed.text) {
              m.classList.remove('bookmarked');
              const b = m.querySelector('.msg-bookmark-btn');
              if (b) { b.classList.remove('starred'); b.textContent = '☆'; }
              break;
            }
          }
        }
      });
    });
  }

  const area = $id('messages-area');
  if (area) {
    const observer = new MutationObserver((muts) => {
      for (const m of muts) {
        m.addedNodes.forEach(n => {
          if (n.nodeType === 1 && n.classList.contains('msg')) attachBookmarkBtn(n);
        });
      }
    });
    observer.observe(area, { childList: true });
    area.querySelectorAll('.msg').forEach(m => attachBookmarkBtn(m));
  }

  $id('bookmark-toggle')?.addEventListener('click', () => {
    const p = $id('bookmark-panel');
    p.classList.toggle('open');
    if (p.classList.contains('open')) renderPanel();
  });
  $id('bookmark-close')?.addEventListener('click', () => $id('bookmark-panel').classList.remove('open'));
}

// ══════════════════════════════════════════════════════════════
// 30. MESSAGE EXPORT
// ══════════════════════════════════════════════════════════════
export function initMessageExport() {
  const toggle = $('export-toggle');
  const menu = $('export-menu');
  if (!toggle || !menu) return;

  function positionMenu(anchor) {
    const r = anchor.getBoundingClientRect();
    menu.style.top = (r.bottom + 4) + 'px';
    const rightEdge = window.innerWidth - r.right;
    menu.style.right = Math.max(8, rightEdge) + 'px';
    menu.style.left = 'auto';
  }

  window._openExportMenu = function(anchor) {
    positionMenu(anchor || toggle);
    menu.classList.toggle('open');
  };

  toggle.addEventListener('click', (e) => {
    e.stopPropagation();
    positionMenu(toggle);
    menu.classList.toggle('open');
  });
  document.addEventListener('click', () => menu.classList.remove('open'));
  menu.addEventListener('click', e => e.stopPropagation());

  function gatherMessages(favOnly) {
    const bookmarks = JSON.parse(localStorage.getItem('oc-bookmarks') || '[]');
    const bmSet = new Set(bookmarks.map(b => b.idx));
    const area = $('messages');
    if (!area) return [];
    const msgs = [];
    area.querySelectorAll('.msg').forEach((el, idx) => {
      if (favOnly && !bmSet.has(idx)) return;
      const role = el.classList.contains('user') ? 'user' : 'assistant';
      const textEl = el.querySelector('.msg-text');
      const content = textEl ? textEl.textContent : '';
      const timeEl = el.querySelector('.msg-meta');
      const ts = timeEl ? timeEl.textContent.trim() : new Date().toLocaleString();
      msgs.push({ role, content, timestamp: ts });
    });
    return msgs;
  }

  function exportMd(msgs) {
    return msgs.map(m => `**${m.role === 'user' ? '🧑 User' : '🤖 Assistant'}** _${m.timestamp}_\n\n${m.content}\n\n---`).join('\n\n');
  }
  function exportTxt(msgs) {
    return msgs.map(m => `[${m.role} ${m.timestamp}] ${m.content}`).join('\n\n');
  }
  function exportJson(msgs) {
    return JSON.stringify(msgs, null, 2);
  }

  function download(content, ext, mime) {
    const now = new Date();
    const ds = now.getFullYear().toString() + String(now.getMonth()+1).padStart(2,'0') + String(now.getDate()).padStart(2,'0');
    const blob = new Blob([content], { type: mime });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `十三香小龙虾-chat-${ds}.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function doToast(type, msg) {
    if (window.ocToast) { window.ocToast[type](msg); return; }
  }

  menu.querySelectorAll('.export-menu-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const fmt = btn.dataset.fmt;
      const favOnly = $('export-fav-only')?.checked || false;
      const msgs = gatherMessages(favOnly);
      if (!msgs.length) {
        doToast('info', favOnly ? '没有收藏的消息可导出' : '暂无对话消息可导出');
        menu.classList.remove('open');
        return;
      }
      const map = {
        md: { fn: exportMd, ext: 'md', mime: 'text/markdown' },
        txt: { fn: exportTxt, ext: 'txt', mime: 'text/plain' },
        json: { fn: exportJson, ext: 'json', mime: 'application/json' },
      };
      const cfg = map[fmt];
      if (cfg) {
        try {
          download(cfg.fn(msgs), cfg.ext, cfg.mime);
          doToast('success', '导出成功 ✓');
        } catch(e) {
          doToast('error', '导出失败: ' + e.message);
        }
      }
      menu.classList.remove('open');
    });
  });
}

// ══════════════════════════════════════════════════════════════
// 32. MESSAGE EDIT / RESEND
// ══════════════════════════════════════════════════════════════
export function initMessageEdit() {
  function attachEditBtn(msgEl) {
    if (msgEl.querySelector('.msg-edit-btn')) return;
    if (!msgEl.classList.contains('user')) return;
    const btn = document.createElement('button');
    btn.className = 'msg-edit-btn';
    btn.textContent = '✏️';
    btn.title = t('edit.resend');
    btn.addEventListener('click', () => enterEdit(msgEl));
    msgEl.appendChild(btn);
  }

  function enterEdit(msgEl) {
    if (msgEl.classList.contains('editing')) return;
    msgEl.classList.add('editing');
    const textEl = msgEl.querySelector('.msg-text');
    if (!textEl) return;
    const original = textEl.textContent.replace(/🎙$/, '').trim();
    textEl.style.display = 'none';
    const area = document.createElement('div');
    area.className = 'msg-edit-area';
    area.innerHTML = `<textarea>${escapeHtml(original)}</textarea>
      <div class="msg-edit-actions">
        <button class="edit-cancel">${t('edit.cancel')}</button>
        <button class="edit-resend">${t('edit.resend')}</button>
      </div>`;
    textEl.after(area);
    const ta = area.querySelector('textarea');
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    area.querySelector('.edit-cancel').addEventListener('click', () => cancelEdit(msgEl, textEl, area));
    area.querySelector('.edit-resend').addEventListener('click', () => resend(msgEl, textEl, area, ta.value));
  }

  function cancelEdit(msgEl, textEl, area) {
    msgEl.classList.remove('editing');
    area.remove();
    textEl.style.display = '';
  }

  async function resend(msgEl, textEl, area, newText) {
    if (!newText.trim()) return;
    msgEl.classList.remove('editing');
    area.remove();
    textEl.style.display = '';
    textEl.innerHTML = fn.renderMarkdown(newText);

    const msgs = $('messages');
    if (!msgs) return;
    const allMsgs = Array.from(msgs.querySelectorAll('.msg'));
    const idx = allMsgs.indexOf(msgEl);
    if (idx < 0) return;

    for (let i = allMsgs.length - 1; i > idx; i--) allMsgs[i].remove();

    const sIdx = S.messages.findIndex((m, mi) => mi >= idx && m.role === 'user');
    if (sIdx >= 0) {
      S.messages[sIdx].content = newText;
      S.messages.splice(sIdx + 1);
    }

    const aiMsg = { role: 'assistant', content: '' };
    S.messages.push(aiMsg);
    const aiEl = fn.appendMessage(aiMsg, true);

    try {
      const body = { messages: fn.buildMessages(), model: 'deepseek-chat', stream: true };
      const resp = await fetch(`${getBaseUrl()}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let fullText = '', buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;
          const data = trimmed.slice(5).trim();
          if (data === '[DONE]') continue;
          try { const p = JSON.parse(data); const d = p.choices?.[0]?.delta?.content; if (d) { fullText += d; fn.updateStreamingEl(aiEl, fullText); } } catch {}
        }
      }
      aiMsg.content = fullText;
      fn.finalizeStreamingEl(aiEl, fullText);
    } catch (e) {
      aiMsg.content = t('error.prefix', { msg: e.message });
      fn.finalizeStreamingEl(aiEl, aiMsg.content);
    }
    S.isSending = false;
    fn.updateSendBtn();
  }

  const area = $('messages');
  if (area) {
    area.querySelectorAll('.msg').forEach(attachEditBtn);
    new MutationObserver(muts => {
      muts.forEach(m => m.addedNodes.forEach(n => {
        if (n.nodeType === 1 && n.classList?.contains('msg')) attachEditBtn(n);
      }));
    }).observe(area, { childList: true });
  }
}

// ══════════════════════════════════════════════════════════════
// 34. SUMMARY
// ══════════════════════════════════════════════════════════════
export function initSummary() {
  const btn = $('summary-btn');
  if (!btn) return;
  let _collapsed = true;

  btn.addEventListener('click', generateSummary);

  async function generateSummary() {
    if (!S.messages.length) {
      window.ocToast?.info(t('summary.noMsg'));
      return;
    }

    const existing = dom.messages?.parentElement?.querySelector('.summary-card');
    if (existing) existing.remove();

    const card = document.createElement('div');
    card.className = 'summary-card loading';
    card.innerHTML = `<div class="summary-card-header">📋 ${t('summary.title')}</div>
      <div class="summary-card-body">${t('summary.generating')}</div>
      <button class="summary-copy" title="Copy">📋</button>`;
    const area = $('messages-area');
    if (area) area.insertBefore(card, area.firstChild);

    const bodyEl = card.querySelector('.summary-card-body');
    try {
      const allText = S.messages.map(m => `${m.role}: ${m.content}`).join('\n');
      const r = await fetch(getBaseUrl() + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [
            { role: 'system', content: 'Summarize the following conversation concisely in the same language as the conversation. Use bullet points. 3-5 sentences max.' },
            { role: 'user', content: allText }
          ],
          stream: false
        })
      });
      if (!r.ok) throw new Error('API error');
      const data = await r.json();
      const summary = data.response || data.content || data.text || '';
      card.classList.remove('loading');
      bodyEl.textContent = summary;
      _collapsed = true;
      bodyEl.classList.add('collapsed');

      card.addEventListener('click', (e) => {
        if (e.target.classList.contains('summary-copy')) return;
        _collapsed = !_collapsed;
        bodyEl.classList.toggle('collapsed', _collapsed);
      });

      card.querySelector('.summary-copy').addEventListener('click', (e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(summary).then(() => {
          window.ocToast?.success(t('summary.copied'));
        });
      });
    } catch (e) {
      card.classList.remove('loading');
      bodyEl.textContent = t('translate.error');
    }
  }
}

// ══════════════════════════════════════════════════════════════
// 35. PINNED MESSAGES
// ══════════════════════════════════════════════════════════════
export function initPinnedMessages() {
  const PKEY = 'oc-pinned';
  const zone = $('pinned-zone');
  if (!zone) return;
  let _pinned = JSON.parse(localStorage.getItem(PKEY) || '[]');
  const MAX_VISIBLE = 3;

  function savePins() { localStorage.setItem(PKEY, JSON.stringify(_pinned)); }

  function renderZone() {
    if (!_pinned.length) { zone.classList.remove('has-pins'); zone.innerHTML = ''; return; }
    zone.classList.add('has-pins');
    const visible = _pinned.slice(0, MAX_VISIBLE);
    zone.innerHTML = visible.map((p, i) =>
      `<div class="pinned-item" data-idx="${p.idx}">
        <span style="font-size:11px;opacity:.6">📌</span>
        <span class="pinned-item-text">${escapeHtml(p.text.slice(0, 80))}</span>
        <button class="pinned-item-unpin" data-pi="${i}" title="${t('pin.unpin')}">✕</button>
      </div>`
    ).join('');
    if (_pinned.length > MAX_VISIBLE) {
      zone.innerHTML += `<div class="pinned-more" id="pinned-show-more">${t('pin.more')} (${_pinned.length - MAX_VISIBLE})</div>`;
      $('pinned-show-more')?.addEventListener('click', () => {
        zone.innerHTML = _pinned.map((p, i) =>
          `<div class="pinned-item" data-idx="${p.idx}">
            <span style="font-size:11px;opacity:.6">📌</span>
            <span class="pinned-item-text">${escapeHtml(p.text.slice(0, 80))}</span>
            <button class="pinned-item-unpin" data-pi="${i}" title="${t('pin.unpin')}">✕</button>
          </div>`
        ).join('');
        bindZoneEvents();
      });
    }
    bindZoneEvents();
  }

  function bindZoneEvents() {
    zone.querySelectorAll('.pinned-item').forEach(item => {
      item.addEventListener('click', (e) => {
        if (e.target.classList.contains('pinned-item-unpin')) return;
        const idx = parseInt(item.dataset.idx);
        const msgs = $('messages');
        if (!msgs) return;
        const all = msgs.querySelectorAll('.msg');
        if (all[idx]) { all[idx].scrollIntoView({ behavior: 'smooth', block: 'center' }); all[idx].style.animation = 'fadeSlideIn .4s'; }
      });
    });
    zone.querySelectorAll('.pinned-item-unpin').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const pi = parseInt(btn.dataset.pi);
        const removed = _pinned.splice(pi, 1)[0];
        savePins();
        renderZone();
        updatePinBtns();
      });
    });
  }

  function getMsgIndex(el) {
    const msgs = $('messages');
    if (!msgs) return -1;
    return Array.from(msgs.querySelectorAll('.msg')).indexOf(el);
  }

  function attachPinBtn(msgEl) {
    if (msgEl.querySelector('.msg-pin-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'msg-pin-btn';
    const idx = getMsgIndex(msgEl);
    const isPinned = _pinned.some(p => p.idx === idx);
    btn.textContent = '📌';
    if (isPinned) btn.classList.add('pinned');
    btn.addEventListener('click', () => togglePin(msgEl, btn));
    msgEl.appendChild(btn);
  }

  function togglePin(msgEl, btn) {
    const idx = getMsgIndex(msgEl);
    if (idx < 0) return;
    const existing = _pinned.findIndex(p => p.idx === idx);
    if (existing >= 0) {
      _pinned.splice(existing, 1);
      btn.classList.remove('pinned');
    } else {
      if (_pinned.length >= MAX_VISIBLE) {
        window.ocToast?.warning(t('pin.max'));
      }
      const textEl = msgEl.querySelector('.msg-text');
      _pinned.push({ idx, text: textEl?.textContent?.slice(0, 100) || '', role: msgEl.classList.contains('user') ? 'user' : 'ai' });
      btn.classList.add('pinned');
    }
    savePins();
    renderZone();
  }

  function updatePinBtns() {
    const msgs = $('messages');
    if (!msgs) return;
    msgs.querySelectorAll('.msg-pin-btn').forEach(btn => {
      const msgEl = btn.closest('.msg');
      const idx = getMsgIndex(msgEl);
      btn.classList.toggle('pinned', _pinned.some(p => p.idx === idx));
    });
  }

  const area = $('messages');
  if (area) {
    area.querySelectorAll('.msg').forEach(attachPinBtn);
    new MutationObserver(muts => {
      muts.forEach(m => m.addedNodes.forEach(n => {
        if (n.nodeType === 1 && n.classList?.contains('msg')) attachPinBtn(n);
      }));
    }).observe(area, { childList: true });
  }
  renderZone();
}

// ══════════════════════════════════════════════════════════════
// 36. REACTIONS
// ══════════════════════════════════════════════════════════════
export function initReactions() {
  const RKEY = 'oc-reactions';
  const EMOJIS = ['👍','👎','🔥','😂','🤔','❤️'];
  let _reactions = JSON.parse(localStorage.getItem(RKEY) || '{}');
  function saveReactions() { localStorage.setItem(RKEY, JSON.stringify(_reactions)); }

  function attachReactionBar(msgEl) {
    if (msgEl.querySelector('.msg-reactions-bar')) return;
    if (msgEl.classList.contains('user')) return;
    const bar = document.createElement('div');
    bar.className = 'msg-reactions-bar';
    const idx = getMsgIndex(msgEl);
    const current = _reactions[idx] || [];
    if (current.length) bar.classList.add('has-reactions');
    EMOJIS.forEach(em => {
      const btn = document.createElement('button');
      btn.className = 'msg-reaction' + (current.includes(em) ? ' active' : '');
      const count = current.includes(em) ? 1 : 0;
      btn.innerHTML = `${em}${count ? '<span class="r-count">1</span>' : ''}`;
      btn.addEventListener('click', () => toggleReaction(msgEl, idx, em, btn, bar));
      bar.appendChild(btn);
    });
    const textArea = msgEl.querySelector('.msg-text');
    if (textArea) textArea.after(bar);
    else msgEl.appendChild(bar);
  }

  function getMsgIndex(el) {
    const msgs = $('messages');
    if (!msgs) return 0;
    return Array.from(msgs.querySelectorAll('.msg')).indexOf(el);
  }

  function toggleReaction(msgEl, idx, emoji, btn, bar) {
    if (!_reactions[idx]) _reactions[idx] = [];
    const arr = _reactions[idx];
    const pos = arr.indexOf(emoji);
    if (pos >= 0) {
      arr.splice(pos, 1);
      btn.classList.remove('active');
      btn.innerHTML = emoji;
    } else {
      arr.push(emoji);
      btn.classList.add('active');
      btn.innerHTML = `${emoji}<span class="r-count">1</span>`;
    }
    if (arr.length) bar.classList.add('has-reactions');
    else bar.classList.remove('has-reactions');
    saveReactions();
  }

  const area = $('messages');
  if (area) {
    area.querySelectorAll('.msg').forEach(attachReactionBar);
    new MutationObserver(muts => {
      muts.forEach(m => m.addedNodes.forEach(n => {
        if (n.nodeType === 1 && n.classList?.contains('msg')) attachReactionBar(n);
      }));
    }).observe(area, { childList: true });
  }
}

// ══════════════════════════════════════════════════════════════
// 37. TRANSLATE
// ══════════════════════════════════════════════════════════════
export function initTranslate() {
  const _cache = {};

  function attachTranslateBtn(msgEl) {
    if (msgEl.querySelector('.msg-translate-btn')) return;
    const btn = document.createElement('button');
    btn.className = 'msg-translate-btn';
    btn.textContent = '🌐';
    btn.title = t('translate.btn');
    btn.addEventListener('click', () => handleTranslate(msgEl, btn));
    msgEl.appendChild(btn);
  }

  async function handleTranslate(msgEl, btn) {
    const existing = msgEl.querySelector('.msg-translation');
    if (existing) { existing.remove(); return; }

    const textEl = msgEl.querySelector('.msg-text');
    if (!textEl) return;
    const text = textEl.textContent.trim();
    if (!text) return;

    const idx = Array.from($('messages')?.querySelectorAll('.msg') || []).indexOf(msgEl);
    if (_cache[idx]) { showTranslation(msgEl, _cache[idx]); return; }

    const loading = document.createElement('div');
    loading.className = 'msg-translation loading';
    loading.textContent = t('translate.loading');
    const insertAfter = msgEl.querySelector('.msg-reactions-bar') || textEl;
    insertAfter.after(loading);

    const lang = (document.documentElement.lang || 'zh-CN').startsWith('en') ? '中文' : 'English';
    try {
      const r = await fetch(getBaseUrl() + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [
            { role: 'system', content: `You are a translator. Translate the following text to ${lang}. Output ONLY the translation, nothing else.` },
            { role: 'user', content: text }
          ],
          stream: false
        })
      });
      loading.remove();
      if (!r.ok) throw new Error('API error');
      const data = await r.json();
      const translated = data.response || data.content || data.text || '';
      _cache[idx] = translated;
      showTranslation(msgEl, translated);
    } catch (e) {
      loading.remove();
      window.ocToast?.error(t('translate.error'));
    }
  }

  function showTranslation(msgEl, text) {
    const div = document.createElement('div');
    div.className = 'msg-translation';
    div.textContent = text;
    const insertAfter = msgEl.querySelector('.msg-reactions-bar') || msgEl.querySelector('.msg-text');
    if (insertAfter) insertAfter.after(div);
    else msgEl.appendChild(div);
  }

  const area = $('messages');
  if (area) {
    area.querySelectorAll('.msg').forEach(attachTranslateBtn);
    new MutationObserver(muts => {
      muts.forEach(m => m.addedNodes.forEach(n => {
        if (n.nodeType === 1 && n.classList?.contains('msg')) attachTranslateBtn(n);
      }));
    }).observe(area, { childList: true });
  }
}
