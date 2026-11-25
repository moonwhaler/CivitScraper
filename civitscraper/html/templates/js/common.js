// Shared helpers for the gallery and the model pages (window.CS).
// Loaded as a file by the gallery and inlined into every model page.
(function () {
  'use strict';

  const THEME_KEY = 'civitscraper_theme';

  function storageGet(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch (e) {
      return fallback;
    }
  }

  function storageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (e) {
      /* file:// pages may have no storage; the setting just won't stick */
    }
  }

  function escapeHTML(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
  }

  // --- Theme ---------------------------------------------------------------

  function systemTheme() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function currentTheme() {
    return document.documentElement.dataset.theme || systemTheme();
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll('[data-action="toggle-theme"]').forEach(btn => {
      const next = theme === 'dark' ? 'light' : 'dark';
      btn.setAttribute('aria-label', `Switch to ${next} theme`);
      btn.title = `Switch to ${next} theme`;
      const use = btn.querySelector('use');
      if (use) use.setAttribute('href', theme === 'dark' ? '#i-sun' : '#i-moon');
    });
  }

  function initTheme() {
    applyTheme(currentTheme());
    document.addEventListener('click', event => {
      if (!event.target.closest('[data-action="toggle-theme"]')) return;
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      storageSet(THEME_KEY, next);
      applyTheme(next);
    });
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (storageGet(THEME_KEY, null) === null) applyTheme(systemTheme());
      });
    }
  }

  // --- Paths ---------------------------------------------------------------

  // Local path (POSIX, Windows drive, UNC or gallery-relative) -> URL with every
  // segment percent-encoded, so #, %, ? and spaces in names still link. URLs are
  // returned unchanged.
  function toFileUrl(path) {
    if (!path) return '';
    const str = String(path);
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(str) || str.startsWith('data:')) return str;
    let normalized = str.replace(/\\/g, '/');
    let prefix = 'file://';
    if (normalized.startsWith('//')) {
      normalized = normalized.slice(2);            // UNC: //server/share -> file://server/share
    } else if (/^[A-Za-z]:\//.test(normalized)) {
      prefix = 'file:///';                         // C:/... -> file:///C:/...
    } else if (!normalized.startsWith('/')) {
      prefix = '';                                 // relative: stays relative
    }
    const encoded = normalized
      .split('/')
      .map((segment, i) => (i === 0 && /^[A-Za-z]:$/.test(segment) ? segment : encodeURIComponent(segment)))
      .join('/');
    return prefix + encoded;
  }

  // Absolute filesystem path for a (possibly page-relative) path, for copying.
  function absolutePath(path) {
    if (!path) return '';
    const str = String(path);
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(str)) return str;
    if (str.startsWith('/') || str.startsWith('\\\\') || /^[A-Za-z]:[\\/]/.test(str)) return str;
    let url;
    try {
      url = new URL(toFileUrl(str), window.location.href);
    } catch (e) {
      return str;
    }
    if (url.protocol !== 'file:') return str;
    const resolved = decodeURIComponent(url.pathname);
    if (url.host) return '\\\\' + url.host + resolved.replace(/\//g, '\\');          // UNC
    if (/^\/[A-Za-z]:\//.test(resolved)) return resolved.slice(1).replace(/\//g, '\\'); // C:\...
    return resolved;
  }

  function parentDir(path) {
    const str = String(path || '');
    const cut = Math.max(str.lastIndexOf('/'), str.lastIndexOf('\\'));
    return cut > 0 ? str.slice(0, cut) : str;
  }

  // --- Clipboard -----------------------------------------------------------

  function legacyCopy(text) {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }

  // file:// is not a secure context in every browser: fall back to the textarea
  // route when the Clipboard API is missing or refuses. Resolves to true/false.
  function copyText(text) {
    if (!text) return Promise.resolve(false);
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => legacyCopy(text));
    }
    return Promise.resolve(legacyCopy(text));
  }

  let toastTimer = null;
  function toast(message, ok = true) {
    let el = document.querySelector('.toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'toast';
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
      el.innerHTML = '<svg class="icon sm" aria-hidden="true"><use href="#i-check"/></svg><span class="toast-text"></span>';
      document.body.appendChild(el);
    }
    el.querySelector('use').setAttribute('href', ok ? '#i-check' : '#i-x');
    el.querySelector('.toast-text').textContent = message;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 1800);
  }

  // Copy and confirm: the button flashes, a toast says what was copied.
  function copyWithFeedback(text, button, what) {
    return copyText(text).then(ok => {
      if (button) {
        button.classList.add(ok ? 'copied' : 'copy-failed');
        clearTimeout(button._copyTimer);
        button._copyTimer = setTimeout(() => button.classList.remove('copied', 'copy-failed'), 1200);
      }
      toast(ok ? `Copied ${what}` : 'Copy failed: select the text and press Ctrl+C', ok);
      return ok;
    });
  }

  function shorten(text, max = 48) {
    const str = String(text || '');
    return str.length > max ? str.slice(0, max - 1) + '…' : str;
  }

  // --- Video previews ------------------------------------------------------

  const reducedMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isTouch = () => ('ontouchstart' in window) || navigator.maxTouchPoints > 0;

  // Hover/focus plays a muted preview video inside `selector` items; touch
  // devices use the item's [data-action="play"] button instead.
  function wireVideoPreviews(root, selector) {
    function play(item) {
      const video = item && item.querySelector('video');
      if (!video) return;
      if (!video.src && video.dataset.src) video.src = video.dataset.src;
      video.play().then(() => setPlaying(item, true)).catch(() => {});
    }
    function setPlaying(item, on) {
      item.classList.toggle('playing', on);
      const use = item.querySelector('[data-action="play"] use');
      if (use) use.setAttribute('href', on ? '#i-pause' : '#i-play');
    }
    function stop(item) {
      const video = item && item.querySelector('video');
      if (!video) return;
      video.pause();
      setPlaying(item, false);
    }
    if (!isTouch()) {
      root.addEventListener('mouseover', e => {
        const item = e.target.closest(selector);
        if (item && !item.contains(e.relatedTarget) && !reducedMotion()) play(item);
      });
      root.addEventListener('mouseout', e => {
        const item = e.target.closest(selector);
        if (item && !item.contains(e.relatedTarget)) stop(item);
      });
    }
    root.addEventListener('click', e => {
      const btn = e.target.closest('[data-action="play"]');
      if (!btn) return;
      const item = btn.closest(selector);
      if (!item) return;
      e.preventDefault();
      e.stopPropagation();
      if (item.classList.contains('playing')) stop(item); else play(item);
    }, true);
  }

  window.CS = {
    storageGet, storageSet, escapeHTML,
    initTheme, applyTheme,
    toFileUrl, absolutePath, parentDir,
    copyText, copyWithFeedback, toast, shorten,
    wireVideoPreviews, reducedMotion, isTouch
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
  } else {
    initTheme();
  }
})();
