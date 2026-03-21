// i18n.js — Client-side bundles + locale helpers (P3)
import { mergeI18nBundles, setLang, applyLang, currentLang, t } from '/js/state.js';

let _bundlesLoaded = false;

export async function initI18nBundles() {
  if (_bundlesLoaded) return;
  try {
    const [zh, en] = await Promise.all([
      fetch('/i18n/zh.json').then(r => (r.ok ? r.json() : {})).catch(() => ({})),
      fetch('/i18n/en.json').then(r => (r.ok ? r.json() : {})).catch(() => ({})),
    ]);
    mergeI18nBundles(zh, en);
    _bundlesLoaded = true;
  } catch (e) {
    console.warn('i18n bundles:', e);
  }
}

/** Apply language and re-merge (e.g. after user switches) */
export async function reloadI18nBundles() {
  _bundlesLoaded = false;
  await initI18nBundles();
}

export function formatDate(ms, opts) {
  const locale = currentLang === 'en' ? 'en-US' : 'zh-CN';
  return new Intl.DateTimeFormat(locale, opts || { dateStyle: 'medium', timeStyle: 'short' }).format(ms);
}

export function formatNumber(n, opts) {
  const locale = currentLang === 'en' ? 'en-US' : 'zh-CN';
  return new Intl.NumberFormat(locale, opts).format(n);
}

export function getLang() {
  return currentLang;
}

/** Apply [data-i18n] / [data-i18n-attr] on a root (QR / static pages). */
export function applyDataI18n(root = document) {
  root.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (!key) return;
    const attr = el.getAttribute('data-i18n-attr');
    const val = t(key);
    if (attr === 'placeholder') el.placeholder = val;
    else if (attr === 'title') el.title = val;
    else el.textContent = val;
  });
}

export { setLang, t, applyLang };
