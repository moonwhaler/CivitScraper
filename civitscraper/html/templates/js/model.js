// Model page: preview stage, viewer with prompt + settings, copy actions.
// Inlined into every model page after common.js.
(function () {
  'use strict';

  const CS = window.CS;
  const $ = (sel, root = document) => root.querySelector(sel);

  let images = [];
  try {
    images = JSON.parse(($('#images-data') || {}).textContent || '[]');
  } catch (e) {
    images = [];
  }

  // A1111/Forge infotext: prompt, "Negative prompt: ...", then "Key: value, ...".
  function infotext(image) {
    if (!image) return '';
    const lines = [];
    if (image.prompt) lines.push(image.prompt);
    if (image.negative_prompt) lines.push('Negative prompt: ' + image.negative_prompt);
    const params = (image.params || [])
      .map(([key, value]) => `${key}: ${/[,:\n"]/.test(value) ? JSON.stringify(value) : value}`)
      .join(', ');
    if (params) lines.push(params);
    return lines.join('\n');
  }

  // --- Back to the gallery ------------------------------------------------
  // Pages opened from the gallery carry #from=gallery; going back then restores
  // the gallery's filters and scroll position. Opened any other way, the link
  // simply loads the gallery.
  const backLink = $('[data-action="back"]');
  if (backLink && /(^|[#&])from=gallery\b/.test(window.location.hash) && history.length > 1) {
    backLink.addEventListener('click', event => {
      event.preventDefault();
      history.back();
    });
  }

  // --- Paths: show and copy the absolute path of wherever the page is now ---
  document.querySelectorAll('[data-abs-from]').forEach(el => {
    const resolved = CS.absolutePath(el.dataset.absFrom);
    if (resolved) el.textContent = resolved;
  });

  // --- NSFW blur (shares the gallery's setting) ----------------------------
  const BLUR_KEY = 'civitscraper_gallery_blur';
  const blurBtn = $('[data-action="toggle-blur"]');
  function setBlur(on) {
    document.body.classList.toggle('nsfw-blur', on);
    if (blurBtn) blurBtn.setAttribute('aria-pressed', String(on));
  }
  if (blurBtn) setBlur(CS.storageGet(BLUR_KEY, '0') === '1');

  // --- Stage: thumbnails switch the main preview ----------------------------
  const stage = $('.m-main .mount-window');
  let stageIndex = 0;

  function showOnStage(index) {
    const image = images[index];
    if (!image || !stage) return;
    stageIndex = index;
    const old = stage.querySelector('.m-main-media');
    let media;
    if (image.is_video) {
      media = document.createElement('video');
      Object.assign(media, { muted: true, loop: true, playsInline: true, autoplay: !CS.reducedMotion() });
    } else {
      media = document.createElement('img');
      media.alt = 'Preview';
      media.decoding = 'async';
    }
    media.className = 'm-main-media';
    media.src = CS.toFileUrl(image.path);
    old.replaceWith(media);
    if (image.width && image.height) stage.style.aspectRatio = `${image.width} / ${image.height}`;
    $('.m-main').classList.toggle('is-nsfw', !!image.nsfw);
    $('.m-main-open').dataset.index = index;
    document.querySelectorAll('.m-thumb[data-index]').forEach(t => {
      const on = Number(t.dataset.index) === index;
      t.classList.toggle('active', on);
      t.setAttribute('aria-pressed', String(on));
    });
  }

  // --- Viewer ----------------------------------------------------------------
  const viewer = $('#viewer');
  let current = 0;
  let returnFocus = null;

  function renderStrip() {
    const strip = $('.viewer-strip', viewer);
    strip.innerHTML = images.map((img, i) => `
      <button type="button" class="viewer-thumb" role="listitem" data-action="viewer-go" data-index="${i}" aria-label="Preview ${i + 1}">
        ${img.is_video
          ? '<span class="viewer-thumb-video"><svg class="icon sm" aria-hidden="true"><use href="#i-play"/></svg></span>'
          : `<img src="${CS.escapeHTML(CS.toFileUrl(img.path))}" alt="" loading="lazy">`}
      </button>`).join('');
  }

  function showInViewer(index) {
    current = (index + images.length) % images.length;
    const image = images[current];
    const img = $('.viewer-media img', viewer);
    const video = $('.viewer-media video', viewer);
    video.pause();
    if (image.is_video) {
      img.hidden = true;
      img.removeAttribute('src');
      video.hidden = false;
      video.src = CS.toFileUrl(image.path);
      if (!CS.reducedMotion()) video.play().catch(() => {});
    } else {
      video.hidden = true;
      video.removeAttribute('src');
      img.hidden = false;
      img.src = CS.toFileUrl(image.path);
      img.alt = image.prompt ? CS.shorten(image.prompt, 120) : `Preview ${current + 1}`;
    }
    $('.viewer-media', viewer).classList.toggle('is-nsfw', !!image.nsfw);
    $('.viewer-count', viewer).textContent = `${current + 1} / ${images.length}`;
    $('.viewer-title', viewer).textContent = `Preview ${current + 1}`;

    const hasPrompt = !!image.prompt;
    const hasNeg = !!image.negative_prompt;
    const params = image.params || [];
    $('[data-block="prompt"]', viewer).hidden = !hasPrompt;
    $('[data-block="negative"]', viewer).hidden = !hasNeg;
    $('[data-block="params"]', viewer).hidden = !params.length;
    $('.viewer-empty', viewer).hidden = hasPrompt || hasNeg || params.length > 0;
    $('[data-action="copy-infotext"]', viewer).disabled = !(hasPrompt || params.length);
    $('[data-action="copy-prompt"]', viewer).disabled = !hasPrompt;
    $('.viewer-prompt:not(.negative)', viewer).textContent = image.prompt || '';
    $('.viewer-prompt.negative', viewer).textContent = image.negative_prompt || '';
    const dl = $('.viewer-params', viewer);
    dl.replaceChildren();
    params.forEach(([key, value]) => {
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      dd.textContent = value;
      dl.append(dt, dd);
    });

    viewer.querySelectorAll('.viewer-thumb').forEach(t => {
      const on = Number(t.dataset.index) === current;
      t.classList.toggle('active', on);
      if (on) t.scrollIntoView({ block: 'nearest', inline: 'center' });
    });
    history.replaceState(null, '', '#image=' + (current + 1) + keepFrom());
  }

  function keepFrom() {
    return /(^|[#&])from=gallery\b/.test(window.location.hash) ? '&from=gallery' : '';
  }

  function openViewer(index) {
    if (!viewer || !images.length) return;
    returnFocus = document.activeElement;
    if (!viewer.dataset.ready) {
      renderStrip();
      viewer.dataset.ready = '1';
    }
    viewer.hidden = false;
    document.body.classList.add('overlay-open');
    showInViewer(index);
    $('[data-action="viewer-close"]', viewer).focus({ preventScroll: true });
  }

  function closeViewer() {
    if (!viewer || viewer.hidden) return;
    $('.viewer-media video', viewer).pause();
    viewer.hidden = true;
    document.body.classList.remove('overlay-open');
    history.replaceState(null, '', keepFrom() ? '#from=gallery' : window.location.pathname + window.location.search);
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
  }

  function togglePanel() {
    const on = viewer.classList.toggle('panel-hidden');
    $('[data-action="viewer-panel"]', viewer).setAttribute('aria-pressed', String(!on));
  }

  function trapFocus(event) {
    const focusables = Array.from(viewer.querySelectorAll('button:not([disabled]), video[controls]:not([hidden])'))
      .filter(el => el.offsetParent !== null);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
    else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
  }

  // --- Events ------------------------------------------------------------------
  document.addEventListener('click', event => {
    const copy = event.target.closest('[data-copy-text], [data-copy-rel], [data-copy-index]');
    if (copy) {
      event.preventDefault();
      event.stopPropagation();
      let text = '';
      let what = copy.dataset.copyWhat || 'text';
      if (copy.dataset.copyText !== undefined) {
        text = copy.dataset.copyText;
      } else if (copy.dataset.copyRel !== undefined) {
        text = CS.absolutePath(copy.dataset.copyRel);
        if (copy.dataset.copyPart === 'folder') text = CS.parentDir(text);
      } else {
        text = infotext(images[Number(copy.dataset.copyIndex)]);
        what = 'prompt and settings';
      }
      CS.copyWithFeedback(text, copy, what);
      return;
    }

    const el = event.target.closest('[data-action]');
    if (!el) return;
    switch (el.dataset.action) {
      case 'show': return showOnStage(Number(el.dataset.index));
      case 'open-viewer': return openViewer(Number(el.dataset.index));
      case 'viewer-close': return closeViewer();
      case 'viewer-prev': return showInViewer(current - 1);
      case 'viewer-next': return showInViewer(current + 1);
      case 'viewer-go': return showInViewer(Number(el.dataset.index));
      case 'viewer-panel': return togglePanel();
      case 'copy-infotext': return CS.copyWithFeedback(infotext(images[current]), el, 'prompt and settings');
      case 'copy-prompt': return CS.copyWithFeedback(images[current].prompt, el, 'prompt');
      case 'copy-negative': return CS.copyWithFeedback(images[current].negative_prompt, el, 'negative prompt');
      case 'toggle-blur': {
        const on = !document.body.classList.contains('nsfw-blur');
        setBlur(on);
        return CS.storageSet(BLUR_KEY, on ? '1' : '0');
      }
    }
  });

  // Clicking the dark area around the image closes the viewer.
  if (viewer) {
    viewer.addEventListener('click', event => {
      if (event.target === viewer || event.target.classList.contains('viewer-stage') ||
          event.target.classList.contains('viewer-media')) {
        closeViewer();
      }
    });
  }

  document.addEventListener('keydown', event => {
    if (!viewer || viewer.hidden) return;
    if (event.target.matches && event.target.matches('input, textarea')) return;
    switch (event.key) {
      case 'Escape': event.preventDefault(); return closeViewer();
      case 'ArrowLeft': event.preventDefault(); return showInViewer(current - 1);
      case 'ArrowRight': event.preventDefault(); return showInViewer(current + 1);
      case 'i': case 'I': return togglePanel();
      case 'c': case 'C':
        if (event.ctrlKey || event.metaKey) return;
        return CS.copyWithFeedback(infotext(images[current]), $('[data-action="copy-infotext"]', viewer), 'prompt and settings');
      case 'Tab': return trapFocus(event);
    }
  });

  // Deep link: #image=3 opens the viewer on the third preview.
  const deep = /(?:^|[#&])image=(\d+)/.exec(window.location.hash);
  if (deep && images.length) openViewer(Math.min(images.length, Math.max(1, Number(deep[1]))) - 1);

  // Lazy video previews in the grid, hover/tap to play.
  const shots = $('.m-shots');
  if (shots) {
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(entries => entries.forEach(e => {
        if (!e.isIntersecting) return;
        e.target.preload = 'metadata';
        e.target.src = e.target.dataset.src;
        io.unobserve(e.target);
      }), { rootMargin: '300px 0px' });
      shots.querySelectorAll('video[data-src]').forEach(v => io.observe(v));
    }
    CS.wireVideoPreviews(shots, '.m-shot');
  }
  if (stage) CS.wireVideoPreviews(document.querySelector('.m-stage'), '.m-main');

  window.CSModel = { infotext };
})();
