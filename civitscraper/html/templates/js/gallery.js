// Model gallery: search, facets, three views, quick look, collection health.
// Data comes from data/models_data.js (window.allModelsData, window.galleryUnmatched).
(function () {
  'use strict';

  const CS = window.CS;
  const esc = CS.escapeHTML;
  const BATCH_SIZE = 60;
  const SEARCH_DELAY = 180;
  const LOAD_AHEAD = 1200; // px below the viewport that are rendered in advance
  const RETURN_KEY = 'civitscraper_gallery_return';
  const PREF = 'civitscraper_gallery_';

  // --- DOM ---------------------------------------------------------------
  const $ = (sel, root = document) => root.querySelector(sel);
  const resultsEl = $('#results');
  const crumbsEl = $('#crumbs');
  const groupsEl = $('#groups');
  const sentinel = $('#sentinel');
  const searchInput = $('#search');
  const sortSelect = $('#sort-by');
  const sizeInput = $('#card-size');
  const facetsEl = $('.g-facets');
  const filtersEl = $('#filters');
  const countEl = $('.g-count');
  const pillsEl = $('.g-pills');
  const healthEl = $('.g-health');
  const unmatchedEl = $('.g-unmatched');
  const peekEl = $('#peek');
  const scrim = $('.scrim');

  // --- Data --------------------------------------------------------------
  const models = Array.isArray(window.allModelsData) ? window.allModelsData : null;
  const unmatched = Array.isArray(window.galleryUnmatched) ? window.galleryUnmatched : [];
  let results = [];
  let rendered = 0;

  const HEALTH_LABELS = {
    update: 'Update available', no_preview: 'No preview', duplicate: 'Duplicate',
    removed: 'Removed from CivitAI', misplaced: 'In the wrong folder', other_bases: 'Also for other bases'
  };
  const SORT_DEFAULT_DIR = { name: 'asc', file_modified: 'desc', updated_at: 'desc', created_at: 'desc', downloads: 'desc', rating: 'desc' };
  const VIEWS = ['cards', 'wall', 'table'];
  // One collator for all comparisons: localeCompare with options builds a new one per call.
  const NAME_ORDER = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });

  // Facets: values(model) lists a model's values (a model matches when any of them
  // is selected). param is the URL hash key.
  const facetConfig = {
    health: { label: 'Health', param: 'health', values: m => (m.health || []).map(f => HEALTH_LABELS[f] || f) },
    types: { label: 'Type', param: 'type', values: m => [m.type || 'Unknown'] },
    baseModels: { label: 'Base model', param: 'base', values: m => [m.base_model || 'Unknown'] },
    folders: { label: 'Folder', param: 'folder', values: m => [m.folder_name || 'Unknown'] },
    creators: { label: 'Creator', param: 'creator', values: m => [m.creator || 'Unknown'] }
  };
  const facetKeys = Object.keys(facetConfig);

  const state = { q: '', sort: 'name', dir: 'asc', view: 'cards', peek: null, grouped: false, at: [] };
  const G = window.CS.grouping;
  // The level shown when grouped (null when flat or searching)
  let level = null;
  // Every model that passes search and filters (results is narrowed to one level)
  let filteredAll = [];
  facetKeys.forEach(k => { state[k] = []; });

  // --- Pure helpers (also exercised by the node test harness) ------------

  // Search terms: whitespace-separated words, or "quoted phrases".
  function parseQuery(text) {
    const terms = [];
    const re = /"([^"]+)"|(\S+)/g;
    let m;
    while ((m = re.exec(String(text || '').toLowerCase())) !== null) {
      const term = (m[1] || m[2]).trim();
      if (term) terms.push(term);
    }
    return terms;
  }

  function searchTextOf(model) {
    if (model._search === undefined) {
      model._search = [
        model.name, model.type, model.base_model, model.folder_name, model.creator, model.version,
        ...(model.tags || []), ...(model.trigger_words || []), model.description
      ].filter(Boolean).join('\n').toLowerCase();
    }
    return model._search;
  }

  function matchesQuery(model, terms) {
    if (!terms.length) return true;
    const text = searchTextOf(model);
    return terms.every(t => text.includes(t));
  }

  function facetValues(model, key) {
    if (!model._facets) {
      model._facets = {};
      facetKeys.forEach(k => { model._facets[k] = facetConfig[k].values(model); });
    }
    return model._facets[key];
  }

  function passesFacet(model, key) {
    const selected = state[key];
    return selected.length === 0 || facetValues(model, key).some(v => selected.includes(v));
  }

  function versionLabel(name) {
    const text = String(name || '').trim();
    return /^\d+(\.\d+)*$/.test(text) ? 'v' + text : text;
  }

  function compact(n) {
    const v = Number(n) || 0;
    if (v >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
    return String(Math.round(v));
  }

  function shortDate(iso) {
    const m = /^\d{4}-\d{2}-\d{2}/.exec(String(iso || ''));
    return m ? m[0] : '';
  }

  function typeSlug(type) {
    const key = String(type || '').toLowerCase().replace(/[^a-z]/g, '');
    return ({ lora: 'lora', dora: 'lora', locon: 'locon', lycoris: 'locon', checkpoint: 'checkpoint',
      textualinversion: 'embedding', embedding: 'embedding', vae: 'vae', controlnet: 'controlnet' })[key] || 'other';
  }

  // Escape first per piece, so a term never matches inside an HTML entity.
  function highlight(text, terms) {
    const raw = String(text || '');
    if (!terms.length) return esc(raw);
    const pattern = terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
    return raw.split(new RegExp(`(${pattern})`, 'gi'))
      .map((part, i) => (i % 2 ? `<mark>${esc(part)}</mark>` : esc(part)))
      .join('');
  }

  // --- Filtering and sorting --------------------------------------------

  function compute() {
    const terms = parseQuery(state.q);
    const filtered = models.filter(m => facetKeys.every(k => passesFacet(m, k)) && matchesQuery(m, terms));
    const mul = state.dir === 'asc' ? 1 : -1;
    const byName = (a, b) => NAME_ORDER.compare(String(a.name || ''), String(b.name || ''));
    const value = m => {
      switch (state.sort) {
        case 'downloads': return Number(m.stats && m.stats.downloads) || 0;
        case 'rating': return Number(m.stats && m.stats.rating) || 0;
        default: return m[state.sort] ? Date.parse(m[state.sort]) || 0 : 0;
      }
    };
    if (state.sort === 'name') {
      filtered.sort((a, b) => mul * byName(a, b));
      return filtered;
    }
    // One key per model, not one Date.parse per comparison.
    const keys = new Map(filtered.map(m => [m, value(m)]));
    filtered.sort((a, b) => {
      const d = keys.get(a) - keys.get(b);
      return d ? mul * d : byName(a, b);
    });
    return filtered;
  }

  function facetCounts() {
    const terms = parseQuery(state.q);
    const counts = {};
    facetKeys.forEach(k => { counts[k] = new Map(); });
    models.forEach(m => {
      if (!matchesQuery(m, terms)) return;
      const passes = {};
      facetKeys.forEach(k => { passes[k] = passesFacet(m, k); });
      facetKeys.forEach(k => {
        if (!facetKeys.every(o => o === k || passes[o])) return;
        facetValues(m, k).forEach(v => counts[k].set(v, (counts[k].get(v) || 0) + 1));
      });
    });
    return counts;
  }

  // --- URL state and preferences ----------------------------------------

  // Hash values win; anything the hash leaves out falls back to the saved preference.
  function readHash() {
    state.view = VIEWS.includes(pref('view', 'cards')) ? pref('view', 'cards') : 'cards';
    state.sort = SORT_DEFAULT_DIR[pref('sort', 'name')] ? pref('sort', 'name') : 'name';
    state.dir = pref('dir', SORT_DEFAULT_DIR[state.sort]);
    const params = new URLSearchParams(window.location.hash.slice(1));
    facetKeys.forEach(k => {
      const v = params.get(facetConfig[k].param);
      state[k] = v ? v.split('|').filter(Boolean) : [];
    });
    state.q = params.get('q') || '';
    const sort = params.get('sort');
    if (sort && SORT_DEFAULT_DIR[sort]) state.sort = sort;
    const dir = params.get('dir');
    if (dir === 'asc' || dir === 'desc') state.dir = dir;
    const view = params.get('view');
    if (VIEWS.includes(view)) state.view = view;
    state.peek = params.get('peek');
    const g = params.get('g');
    state.grouped = g === '1' || (g !== '0' && pref('grouped', '0') === '1');
    const at = params.get('at');
    state.at = at ? at.split('/').filter(Boolean) : [];
    return params;
  }

  function hashFor(overrides = {}) {
    const s = Object.assign({}, state, overrides);
    const params = new URLSearchParams();
    facetKeys.forEach(k => { if (s[k].length) params.set(facetConfig[k].param, s[k].join('|')); });
    if (s.q) params.set('q', s.q);
    if (s.sort !== 'name') params.set('sort', s.sort);
    if (s.dir !== SORT_DEFAULT_DIR[s.sort]) params.set('dir', s.dir);
    if (s.view !== 'cards') params.set('view', s.view);
    if (s.grouped !== (pref('grouped', '0') === '1')) params.set('g', s.grouped ? '1' : '0');
    if (s.grouped && s.at.length) params.set('at', s.at.join('/'));
    if (s.peek) params.set('peek', s.peek);
    return params.toString();
  }

  // Filters, sort and view replace the history entry; moving through the groups
  // adds one (navigateTo), so the browser's Back button goes up a level.
  function writeHash() {
    const hash = hashFor();
    history.replaceState(null, '', hash ? '#' + hash : window.location.pathname + window.location.search);
  }

  function navigateTo(at) {
    const hash = hashFor({ at, peek: null });
    window.location.hash = hash || 'g=' + (state.grouped ? '1' : '0');
  }

  const pref = (key, fallback) => CS.storageGet(PREF + key, fallback);
  const setPref = (key, value) => CS.storageSet(PREF + key, String(value));

  // --- Rendering: shared pieces -----------------------------------------

  function detailHref(model) {
    return model.html_path ? CS.toFileUrl(model.html_path) + '#from=gallery' : '#';
  }

  function previewHtml(model, { eager = false } = {}) {
    if (!model.preview_image_path) {
      return '<div class="mount-empty"><span>No preview</span></div>';
    }
    const src = esc(CS.toFileUrl(model.preview_image_path));
    if (model.is_video) {
      return `<video data-src="${src}" muted loop playsinline preload="none" aria-hidden="true"></video>
        <button type="button" class="btn sm icon-only play-btn" data-action="play" aria-label="Play preview">
          <svg class="icon sm" aria-hidden="true"><use href="#i-play"/></svg></button>`;
    }
    return `<img src="${src}" alt="" loading="${eager ? 'eager' : 'lazy'}" decoding="async">`;
  }

  function stampHtml(model, withVersion = true) {
    const parts = [`<span class="stamp-type">${esc(model.type || 'Unknown')}</span>`];
    if (model.base_model) parts.push(`<span>${esc(model.base_model)}</span>`);
    if (withVersion && model.version) parts.push(`<span class="stamp-truncate">${esc(versionLabel(model.version))}</span>`);
    return `<div class="stamp">${parts.join('')}</div>`;
  }

  function badgesHtml(model) {
    const health = model.health || [];
    let html = '';
    if (health.includes('update')) {
      const title = model.update_version ? `Newer version on CivitAI: ${model.update_version}` : 'Newer version on CivitAI';
      html += `<span class="chip update" title="${esc(title)}"><svg class="icon sm" aria-hidden="true"><use href="#i-update"/></svg>Update</span>`;
    }
    if (health.includes('removed')) {
      const r = model.removed || {};
      const title = `CivitAI no longer lists this ${r.what === 'model' ? 'model' : 'version'}${r.date ? ` (noticed ${r.date})` : ''}; the local copy is kept`;
      html += `<span class="chip removed" title="${esc(title)}"><svg class="icon sm" aria-hidden="true"><use href="#i-archive"/></svg>Removed</span>`;
    }
    if (health.includes('misplaced')) {
      const m = model.misplaced || {};
      const title = m.to ? `${m.why || 'Looks misplaced'}. Belongs in ${m.to}` : (m.why || 'Looks misplaced');
      html += `<span class="chip misplaced" title="${esc(title)}"><svg class="icon sm" aria-hidden="true"><use href="#i-move"/></svg>Misplaced</span>`;
    }
    if (health.includes('duplicate')) {
      const n = (model.duplicates || []).length;
      html += `<span class="chip duplicate" title="The same version is stored ${n} times"><svg class="icon sm" aria-hidden="true"><use href="#i-layers"/></svg>${n}×</span>`;
    }
    return html;
  }

  // Where a search result sits in the groups (only while grouped and searching).
  function groupPathHtml(model) {
    if (!state.grouped || !state.q) return '';
    return `<p class="card-path">${esc(G.pathOf(model).join(' › '))}</p>`;
  }

  function triggerChips(model, limit) {
    const words = model.trigger_words || [];
    if (!words.length) return '';
    const shown = words.slice(0, limit);
    let html = shown.map((w, i) => `<button type="button" class="chip trigger" data-copy="trigger" data-idx="${model._idx}" data-word="${i}" title="Copy “${esc(w)}”"><span>${esc(w)}</span></button>`).join('');
    if (words.length > limit) {
      html += `<button type="button" class="chip more" data-action="peek" data-idx="${model._idx}" title="Show all trigger words">+${words.length - limit}</button>`;
    }
    return html;
  }

  function versionsChip(model) {
    const versions = model.versions || [];
    if (versions.length < 2) return '';
    const local = versions.filter(v => v.is_local).length;
    return `<button type="button" class="chip versions" data-action="peek" data-idx="${model._idx}" title="${local} of ${versions.length} versions on disk">
      <svg class="icon sm" aria-hidden="true"><use href="#i-layers"/></svg>${local}/${versions.length}</button>`;
  }

  function copyButtons(model) {
    let html = '';
    if ((model.trigger_words || []).length) {
      html += `<button type="button" class="btn ghost sm icon-only" data-copy="triggers" data-idx="${model._idx}" title="Copy trigger words" aria-label="Copy trigger words of ${esc(model.name)}">
        <svg class="icon sm" aria-hidden="true"><use href="#i-zap"/></svg></button>`;
    }
    if (model.file_path) {
      html += `<button type="button" class="btn ghost sm icon-only" data-copy="path" data-idx="${model._idx}" title="Copy file path" aria-label="Copy file path of ${esc(model.name)}">
        <svg class="icon sm" aria-hidden="true"><use href="#i-file"/></svg></button>`;
    }
    html += `<button type="button" class="btn ghost sm icon-only" data-action="peek" data-idx="${model._idx}" title="Quick look (Space)" aria-label="Quick look at ${esc(model.name)}">
      <svg class="icon sm" aria-hidden="true"><use href="#i-eye"/></svg></button>`;
    return html;
  }

  // --- Rendering: views ---------------------------------------------------

  function cardHtml(model, terms, i) {
    const nsfw = model.nsfw ? ' is-nsfw' : '';
    return `
      <article class="card mount t-${typeSlug(model.type)}${nsfw}" data-idx="${model._idx}" style="--i:${i}">
        <div class="mount-window">
          ${previewHtml(model)}
          <div class="card-badges">${badgesHtml(model)}</div>
        </div>
        <div class="card-body">
          ${stampHtml(model)}${groupPathHtml(model)}
          <h3 class="card-name"><a class="card-link" href="${esc(detailHref(model))}">${highlight(model.name, terms)}</a></h3>
          <div class="card-triggers">${triggerChips(model, 2)}</div>
          <div class="card-foot">
            ${versionsChip(model)}
            <span class="card-stats">${model.stats && model.stats.downloads ? `<span title="Downloads"><svg class="icon sm" aria-hidden="true"><use href="#i-download"/></svg>${compact(model.stats.downloads)}</span>` : ''}</span>
            <span class="card-actions">${copyButtons(model)}</span>
          </div>
        </div>
      </article>`;
  }

  function wallHtml(model, terms, i) {
    const nsfw = model.nsfw ? ' is-nsfw' : '';
    return `
      <article class="tile mount t-${typeSlug(model.type)}${nsfw}" data-idx="${model._idx}" style="--i:${i}">
        <div class="mount-window">
          ${previewHtml(model)}
          <div class="card-badges">${badgesHtml(model)}</div>
          <div class="tile-caption">
            <a class="card-link" href="${esc(detailHref(model))}">${highlight(model.name, terms)}</a>
            ${stampHtml(model, false)}
          </div>
          <span class="tile-actions">${copyButtons(model)}</span>
        </div>
      </article>`;
  }

  function rowHtml(model, terms) {
    const nsfw = model.nsfw ? ' is-nsfw' : '';
    const stats = model.stats || {};
    return `
      <tr class="row t-${typeSlug(model.type)}${nsfw}" data-idx="${model._idx}">
        <td class="row-thumb"><div class="mount-window">${previewHtml(model)}</div></td>
        <td class="row-name">
          <a class="card-link" href="${esc(detailHref(model))}">${highlight(model.name, terms)}</a>
          <div class="row-sub">${badgesHtml(model)}${versionsChip(model)}<span class="row-folder">${esc(state.grouped && state.q ? G.pathOf(model).join(' › ') : model.folder_name || '')}</span></div>
        </td>
        <td>${stampHtml(model, false)}</td>
        <td class="mono row-version">${esc(versionLabel(model.version))}</td>
        <td class="row-triggers">${triggerChips(model, 1)}</td>
        <td class="num">${stats.downloads ? compact(stats.downloads) : '–'}</td>
        <td class="num">${stats.rating ? Number(stats.rating).toFixed(1) : '–'}</td>
        <td class="mono row-date">${shortDate(model.file_modified) || '–'}</td>
        <td class="row-actions">${copyButtons(model)}</td>
      </tr>`;
  }

  const TABLE_HEAD = `
    <table class="g-table">
      <thead><tr>
        <th class="row-thumb"><span class="visually-hidden">Preview</span></th>
        <th><button type="button" data-sort="name">Name</button></th>
        <th>Type · base</th>
        <th>Version</th>
        <th>Trigger</th>
        <th class="num"><button type="button" data-sort="downloads">Downloads</button></th>
        <th class="num"><button type="button" data-sort="rating">Rating</button></th>
        <th><button type="button" data-sort="file_modified">Added</button></th>
        <th><span class="visually-hidden">Actions</span></th>
      </tr></thead>
      <tbody></tbody>
    </table>`;

  function renderBatch() {
    const terms = parseQuery(state.q);
    const batch = results.slice(rendered, rendered + BATCH_SIZE);
    if (!batch.length) return;
    let html;
    if (state.view === 'table') {
      html = batch.map(m => rowHtml(m, terms)).join('');
      $('tbody', resultsEl).insertAdjacentHTML('beforeend', html);
    } else {
      const fn = state.view === 'wall' ? wallHtml : cardHtml;
      html = batch.map((m, i) => fn(m, terms, Math.min(i, 14))).join('');
      resultsEl.insertAdjacentHTML('beforeend', html);
    }
    rendered += batch.length;
    observeVideos();
    fillViewport();
  }

  // The sentinel observer only fires when the sentinel enters the load-ahead
  // zone. If a batch leaves it still inside (small tiles, tall screen), keep
  // rendering, one batch per frame, until the zone is filled. At most one check
  // per frame, however often it is requested.
  let fillPending = false;
  function fillViewport() {
    if (fillPending) return;
    fillPending = true;
    requestAnimationFrame(() => {
      fillPending = false;
      if (rendered < results.length &&
          sentinel.getBoundingClientRect().top < window.innerHeight + LOAD_AHEAD) {
        renderBatch();
      }
    });
  }

  function renderResults() {
    results = compute();
    filteredAll = results;
    rendered = 0;
    if (state.grouped && !state.q) {
      level = G.buildLevel(results, state.at);
      results = level.direct;
    } else {
      level = null;
    }
    renderGroups();
    resultsEl.className = `g-results view-${state.view}`;
    document.body.dataset.view = state.view;
    resultsEl.innerHTML = state.view === 'table' ? TABLE_HEAD : '';
    if (state.view === 'table') {
      resultsEl.querySelectorAll('[data-sort]').forEach(btn => {
        const active = btn.dataset.sort === state.sort;
        btn.closest('th').setAttribute('aria-sort', active ? (state.dir === 'asc' ? 'ascending' : 'descending') : 'none');
      });
    }
    $('#no-results').hidden = results.length > 0 || (level && level.groups.length > 0) || models.length === 0;
    renderBatch();
    updateChrome();
  }

  // --- Groups (drill-down) ---------------------------------------------------

  function tileMediaHtml(model) {
    const src = esc(CS.toFileUrl(model.preview_image_path));
    const nsfw = model.nsfw ? ' class="is-nsfw"' : '';
    if (model.is_video) return `<video${nsfw} src="${src}" muted playsinline preload="metadata" aria-hidden="true"></video>`;
    return `<img${nsfw} src="${src}" alt="" loading="lazy" decoding="async">`;
  }

  function groupTileHtml(group, i) {
    const st = G.tileStats(group.models);
    const cells = st.previews.length
      ? st.previews.map(m => `<span class="gm-cell">${tileMediaHtml(m)}</span>`).join('')
      : '<span class="gm-cell mount-empty"><span>No preview</span></span>';
    const meta = [`${st.count.toLocaleString()} model${st.count === 1 ? '' : 's'}`];
    if (st.size) meta.push(G.humanSize(st.size));
    if (st.newest) meta.push(`newest ${shortDate(st.newest)}`);
    const flags = [['update', 'i-update', 'with updates'], ['misplaced', 'i-move', 'in the wrong folder'],
      ['duplicate', 'i-layers', 'stored twice'], ['other_bases', 'i-folder', 'also for other bases']]
      .filter(([f]) => st.health[f])
      .map(([f, icon, text]) => `<span class="chip ${f}" title="${st.health[f]} ${text}"><svg class="icon sm" aria-hidden="true"><use href="#${icon}"/></svg>${st.health[f]}</span>`)
      .join('');
    const slug = ` t-${typeSlug(level && level.at.length ? level.at[0] : group.name)}`;
    return `
      <button type="button" class="group-tile${slug}" data-group="${esc(group.name)}" style="--i:${Math.min(i, 14)}">
        <span class="group-mosaic" data-n="${Math.max(1, st.previews.length)}" aria-hidden="true">${cells}</span>
        <span class="group-body">
          <span class="group-name">${esc(group.name)}</span>
          <span class="group-meta">${meta.join('<span class="sep" aria-hidden="true">·</span>')}</span>
          ${flags ? `<span class="group-flags">${flags}</span>` : ''}
        </span>
      </button>`;
  }

  function crumbsHtml() {
    const parts = [`<a href="#${esc(hashFor({ at: [], peek: null }))}" class="crumb">All</a>`];
    level.at.forEach((step, i) => {
      const last = i === level.at.length - 1;
      // An auto-skipped step leads back to where it is: not a link.
      const skipped = !last && G.buildLevel(filteredAll, level.at.slice(0, i + 1)).at.length > i + 1;
      const label = esc(step);
      if (last) parts.push(`<span class="crumb current" aria-current="page">${label}</span>`);
      else if (skipped) parts.push(`<span class="crumb skipped" title="The only group here">${label}</span>`);
      else parts.push(`<a href="#${esc(hashFor({ at: level.at.slice(0, i + 1), peek: null }))}" class="crumb">${label}</a>`);
    });
    return parts.join('<span class="crumb-sep" aria-hidden="true">›</span>');
  }

  function renderGroups() {
    const show = Boolean(level);
    crumbsEl.hidden = !show;
    groupsEl.hidden = !show || !level.groups.length;
    if (!show) {
      groupsEl.innerHTML = '';
      return;
    }
    crumbsEl.innerHTML = `<nav aria-label="Groups">${crumbsHtml()}</nav>`;
    const groups = G.sortGroups(level.groups, state.sort, state.dir);
    groupsEl.innerHTML = groups.length
      ? `<h2 class="eyebrow group-level">${esc(level.label)}</h2><div class="group-grid">${groups.map(groupTileHtml).join('')}</div>`
      : '';
  }

  function goUp() {
    if (!level || !level.at.length) return false;
    navigateTo(G.parentPath(filteredAll, level));
    return true;
  }

  function setGrouped(on) {
    state.grouped = on;
    setPref('grouped', on ? '1' : '0');
    update();
  }

  // --- Facets ---------------------------------------------------------------

  // Built once (value lists never change); counts and checked states are updated
  // in place, so keyboard focus survives filtering.
  function buildFacets() {
    const totals = facetCounts();
    let html = '';
    facetKeys.forEach(key => {
      const entries = Array.from(totals[key].entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
      if (!entries.length || (key === 'health' && !entries.some(([, n]) => n))) return;
      const open = pref('facet_' + key, key === 'creators' || key === 'folders' ? 'closed' : 'open') === 'open' || state[key].length > 0;
      const finder = entries.length > 12
        ? `<input type="search" class="facet-find" placeholder="Find ${esc(facetConfig[key].label.toLowerCase())}…" aria-label="Find ${esc(facetConfig[key].label)}">` : '';
      html += `
        <details class="facet" data-facet="${key}" ${open ? 'open' : ''}>
          <summary><span>${esc(facetConfig[key].label)}</span><span class="facet-selected"></span><svg class="icon sm chevron" aria-hidden="true"><use href="#i-down"/></svg></summary>
          ${finder}
          <ul class="facet-list" role="list">
            ${entries.map(([value]) => `
              <li><label class="facet-item">
                <input type="checkbox" data-facet="${key}" value="${esc(value)}">
                <span class="facet-value">${key === 'types' ? `<i class="type-dot t-${typeSlug(value)}"></i>` : ''}${esc(value)}</span>
                <span class="facet-count"></span>
              </label></li>`).join('')}
          </ul>
        </details>`;
    });
    facetsEl.innerHTML = html;
  }

  function updateFacets() {
    const counts = facetCounts();
    facetsEl.querySelectorAll('input[type="checkbox"]').forEach(box => {
      const key = box.dataset.facet;
      const n = counts[key].get(box.value) || 0;
      box.checked = state[key].includes(box.value);
      box.closest('.facet-item').classList.toggle('empty', n === 0 && !box.checked);
      box.closest('.facet-item').querySelector('.facet-count').textContent = n;
    });
    facetsEl.querySelectorAll('.facet').forEach(section => {
      const n = state[section.dataset.facet].length;
      section.querySelector('.facet-selected').textContent = n ? String(n) : '';
    });
  }

  function activeFilterCount() {
    return facetKeys.reduce((n, k) => n + state[k].length, 0);
  }

  function updateChrome() {
    const total = models.length;
    const n = results.length;
    const filtered = activeFilterCount() > 0 || state.q;
    if (level) {
      const groups = level.groups.length;
      countEl.textContent = `${level.total.toLocaleString()} model${level.total === 1 ? '' : 's'}` +
        (groups ? ` in ${groups} group${groups === 1 ? '' : 's'}` : '') +
        (filtered ? ` (of ${total.toLocaleString()})` : '');
    } else {
      countEl.textContent = filtered
        ? `${n.toLocaleString()} of ${total.toLocaleString()} models`
        : `${total.toLocaleString()} models`;
    }
    const groupBtn = $('[data-action="toggle-group"]');
    if (groupBtn) groupBtn.setAttribute('aria-pressed', String(state.grouped));

    pillsEl.innerHTML = facetKeys.flatMap(k => state[k].map(v => `
      <button type="button" class="chip pill" data-remove-facet="${k}" data-value="${esc(v)}" aria-label="Remove filter ${esc(facetConfig[k].label)}: ${esc(v)}">
        <span class="pill-key">${esc(facetConfig[k].label)}</span>${esc(v)}<svg class="icon sm" aria-hidden="true"><use href="#i-x"/></svg>
      </button>`)).join('') +
      (activeFilterCount() > 1 ? '<button type="button" class="btn ghost sm" data-action="clear-filters">Clear all</button>' : '');

    const active = activeFilterCount();
    $('.g-filters-count').textContent = active ? ` (${active})` : '';
    filtersEl.querySelectorAll('[data-action="clear-filters"]').forEach(b => { b.hidden = active === 0; });
    $('.search-clear').hidden = !searchInput.value;
    document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === state.view)));
    sortSelect.value = state.sort;
    const dirBtn = $('[data-action="sort-dir"]');
    dirBtn.dataset.dir = state.dir;
    dirBtn.setAttribute('aria-label', state.dir === 'asc' ? 'Sorted ascending; switch to descending' : 'Sorted descending; switch to ascending');
    dirBtn.title = state.dir === 'asc' ? 'Ascending' : 'Descending';
    healthEl.querySelectorAll('[data-health]').forEach(b => {
      b.setAttribute('aria-pressed', String(state.health.includes(HEALTH_LABELS[b.dataset.health])));
    });
    updateFacets();
  }

  function update() {
    writeHash();
    renderResults();
  }

  // --- Collection health ------------------------------------------------------

  function renderHealth() {
    const count = flag => models.filter(m => (m.health || []).includes(flag)).length;
    const chips = [];
    [['update', 'i-update', 'with updates'], ['removed', 'i-archive', 'removed from CivitAI'],
      ['misplaced', 'i-move', 'in the wrong folder'], ['duplicate', 'i-layers', 'stored twice'], ['no_preview', 'i-image-off', 'without preview'],
      ['other_bases', 'i-folder', 'also for other bases']]
      .forEach(([flag, icon, text]) => {
        const n = count(flag);
        if (n) chips.push(`<button type="button" class="chip health ${flag}" data-health="${flag}" aria-pressed="false"><svg class="icon sm" aria-hidden="true"><use href="#${icon}"/></svg>${n} ${text}</button>`);
      });
    if (unmatched.length) {
      chips.push(`<button type="button" class="chip health" data-action="show-unmatched"><svg class="icon sm" aria-hidden="true"><use href="#i-help"/></svg>${unmatched.length} without card</button>`);
    }
    if (!chips.length) return;
    healthEl.innerHTML = `<span class="eyebrow">Collection</span>${chips.join('')}`;
    healthEl.hidden = false;
  }

  const UNMATCHED_GROUPS = [
    ['not_on_civitai', 'Not on CivitAI', 'CivitAI answered “not found” for these files: deleted, private, or from another site.'],
    ['no_metadata', 'No metadata yet', 'Not looked up yet, or the lookup failed (see the log). The next scan retries them.']
  ];

  function renderUnmatched() {
    if (!unmatched.length) return;
    $('.g-unmatched-title').textContent = `${unmatched.length} scanned file${unmatched.length === 1 ? ' has' : 's have'} no gallery card`;
    $('.g-unmatched-body').innerHTML = UNMATCHED_GROUPS.map(([reason, title, help]) => {
      const rows = unmatched.map((e, idx) => [e, idx]).filter(([e]) => e.reason === reason);
      if (!rows.length) return '';
      const shown = rows.slice(0, 1000).map(([e, idx]) => `
        <li>
          <span class="u-name mono">${esc(e.name)}</span>
          <span class="u-folder">${esc(e.folder)}</span>
          <button type="button" class="btn ghost sm icon-only" data-copy="unmatched" data-idx="${idx}" aria-label="Copy path of ${esc(e.name)}" title="${esc(CS.absolutePath(e.file_path))}">
            <svg class="icon sm" aria-hidden="true"><use href="#i-copy"/></svg></button>
        </li>`).join('');
      const more = rows.length > 1000 ? `<li class="u-more">… and ${rows.length - 1000} more</li>` : '';
      return `<section><h3>${esc(title)} <span class="facet-count">${rows.length}</span></h3><p>${esc(help)}</p><ul role="list">${shown}${more}</ul></section>`;
    }).join('');
    unmatchedEl.hidden = false;
  }

  // --- Quick look -------------------------------------------------------------

  let peekReturnFocus = null;

  function peekHtml(model) {
    const words = model.trigger_words || [];
    const stats = model.stats || {};
    const meta = [];
    if (model.creator) meta.push(`by <strong>${esc(model.creator)}</strong>`);
    if (stats.downloads) meta.push(`<span title="Downloads"><svg class="icon sm" aria-hidden="true"><use href="#i-download"/></svg>${compact(stats.downloads)}</span>`);
    if (stats.rating) meta.push(`<span title="Rating"><svg class="icon sm" aria-hidden="true"><use href="#i-star"/></svg>${Number(stats.rating).toFixed(1)}</span>`);

    const versions = (model.versions || []).map(v => {
      const label = esc(versionLabel(v.name));
      const cls = `ver${v.is_current ? ' current' : ''}${v.is_local ? ' local' : ''}`;
      const href = v.is_local ? esc(CS.toFileUrl(v.link) + '#from=gallery') : esc(v.link || '#');
      const ext = v.is_local ? '' : ' target="_blank" rel="noopener noreferrer"';
      const where = v.is_local ? 'on disk' : 'CivitAI';
      return `<li><a class="${cls}" href="${href}"${ext}><i aria-hidden="true"></i><span>${label}</span><span class="ver-where">${v.is_current ? 'this card' : where}</span>${v.is_local ? '' : '<svg class="icon sm" aria-hidden="true"><use href="#i-external"/></svg>'}</a></li>`;
    }).join('');

    const dups = (model.duplicates || []).map((p, i) => `
      <li><span class="path">${esc(CS.absolutePath(p))}</span>
        <button type="button" class="btn ghost sm icon-only" data-copy="duplicate" data-idx="${model._idx}" data-dup="${i}" aria-label="Copy this path">
          <svg class="icon sm" aria-hidden="true"><use href="#i-copy"/></svg></button></li>`).join('');

    return `
      <div class="t-${typeSlug(model.type)}">
      <div class="peek-media mount${model.nsfw ? ' is-nsfw' : ''}">
        <div class="mount-window">${model.preview_image_path && model.is_video
          ? `<video src="${esc(CS.toFileUrl(model.preview_image_path))}" muted loop playsinline ${CS.reducedMotion() ? 'controls' : 'autoplay'}></video>`
          : previewHtml(model, { eager: true })}</div>
      </div>
      ${stampHtml(model)}
      <h2 id="peek-title" class="peek-title">${esc(model.name)}</h2>
      ${meta.length ? `<p class="peek-meta">${meta.join('<span class="sep" aria-hidden="true">·</span>')}</p>` : ''}
      ${badgesHtml(model) ? `<div class="peek-badges">${badgesHtml(model)}${model.update_version ? `<span class="peek-note">Newest on CivitAI: ${esc(model.update_version)}</span>` : ''}${model.removed ? `<span class="peek-note">Gone from CivitAI${model.removed.date ? ` since ${esc(model.removed.date)}` : ''}; local copy kept</span>` : ''}${model.misplaced ? `<span class="peek-note">${esc(model.misplaced.why || 'Looks misplaced')}${model.misplaced.to ? `; belongs in ${esc(model.misplaced.to)}` : ''}. Move it with <code>civitscraper -j sort</code>.</span>` : ''}</div>` : ''}

      ${words.length ? `
      <section class="peek-section">
        <div class="peek-section-head"><h3 class="eyebrow">Trigger words</h3>
          <button type="button" class="btn sm" data-copy="triggers" data-idx="${model._idx}"><svg class="icon sm" aria-hidden="true"><use href="#i-copy"/></svg>Copy all</button></div>
        <div class="chips">${words.map((w, i) => `<button type="button" class="chip trigger" data-copy="trigger" data-idx="${model._idx}" data-word="${i}" title="Copy"><span>${esc(w)}</span></button>`).join('')}</div>
      </section>` : ''}

      ${model.file_path ? `
      <section class="peek-section">
        <div class="peek-section-head"><h3 class="eyebrow">File</h3>
          <span class="peek-btns">
            <button type="button" class="btn sm" data-copy="path" data-idx="${model._idx}"><svg class="icon sm" aria-hidden="true"><use href="#i-file"/></svg>Copy path</button>
            <button type="button" class="btn sm" data-copy="folder" data-idx="${model._idx}"><svg class="icon sm" aria-hidden="true"><use href="#i-folder"/></svg>Copy folder</button>
          </span></div>
        <p class="path">${esc(CS.absolutePath(model.file_path))}</p>
      </section>` : ''}

      ${versions ? `<section class="peek-section"><h3 class="eyebrow">Versions</h3><ul class="versions" role="list">${versions}</ul></section>` : ''}
      ${alsoForHtml(model)}
      ${dups ? `<section class="peek-section"><h3 class="eyebrow">Stored ${model.duplicates.length} times</h3><ul class="dups" role="list">${dups}</ul></section>` : ''}
      ${(model.tags || []).length ? `<section class="peek-section"><h3 class="eyebrow">Tags</h3><div class="chips">${model.tags.map(t => `<button type="button" class="chip tag" data-search="${esc(t)}">${esc(t)}</button>`).join('')}</div></section>` : ''}
      ${model.description ? `<section class="peek-section"><h3 class="eyebrow">About</h3><p class="peek-desc">${esc(model.description)}</p></section>` : ''}

      <div class="peek-foot">
        <a class="btn primary" href="${esc(detailHref(model))}">Open details<svg class="icon sm" aria-hidden="true"><use href="#i-right"/></svg></a>
      </div>
      </div>`;
  }

  // The same CivitAI model for other base models: your cards, and versions on CivitAI.
  function alsoForHtml(model) {
    const entries = model.also_for || [];
    if (!entries.length) return '';
    const items = entries.map(e => {
      const href = e.local ? esc(CS.toFileUrl(e.link) + '#from=gallery') : esc(e.link || '#');
      const ext = e.local ? '' : ' target="_blank" rel="noopener noreferrer"';
      return `<li><a class="ver${e.local ? ' local' : ''}" href="${href}"${ext}><i aria-hidden="true"></i><span>${esc(e.base)}</span><span class="ver-where">${e.local ? 'on disk' : 'CivitAI'}</span>${e.local ? '' : '<svg class="icon sm" aria-hidden="true"><use href="#i-external"/></svg>'}</a></li>`;
    }).join('');
    const hint = entries.some(e => !e.local)
      ? '<p class="peek-note">Download them with <code>civitscraper -j updates</code>.</p>' : '';
    return `<section class="peek-section"><h3 class="eyebrow">Also for</h3><ul class="versions" role="list">${items}</ul>${hint}</section>`;
  }

  function openPeek(idx, { focus = true } = {}) {
    const model = models[idx];
    if (!model) return;
    if (peekEl.hidden) peekReturnFocus = document.activeElement;
    state.peek = peekKey(model);
    peekEl.dataset.idx = idx;
    $('.peek-body', peekEl).innerHTML = peekHtml(model);
    $('.peek-body', peekEl).scrollTop = 0;
    const pos = results.indexOf(model);
    $('.peek-pos', peekEl).textContent = pos >= 0 ? `${pos + 1} / ${results.length}` : '';
    peekEl.hidden = false;
    scrim.hidden = false;
    document.body.classList.add('overlay-open');
    writeHash();
    if (focus) {
      const title = $('.peek-title', peekEl);
      title.setAttribute('tabindex', '-1');
      title.focus({ preventScroll: true });
    }
  }

  function closeOverlay() {
    if (!peekEl.hidden) {
      const v = peekEl.querySelector('video');
      if (v) v.pause();
      peekEl.hidden = true;
      state.peek = null;
      writeHash();
      if (peekReturnFocus && document.contains(peekReturnFocus)) peekReturnFocus.focus({ preventScroll: true });
    }
    document.body.classList.remove('filters-open');
    document.body.classList.remove('overlay-open');
    scrim.hidden = true;
  }

  // The URL key of a model in quick look: its version id (stable across
  // regenerations), else its position in the data.
  function peekKey(model) {
    return String(model.version_id || model._idx);
  }

  function syncPeekWithState() {
    const target = state.peek && models.find(m => peekKey(m) === state.peek);
    if (target) openPeek(target._idx, { focus: false });
    else if (!peekEl.hidden) closeOverlay();
  }

  function stepPeek(delta) {
    const current = models[Number(peekEl.dataset.idx)];
    let pos = results.indexOf(current);
    if (pos < 0) return;
    pos = (pos + delta + results.length) % results.length;
    while (rendered <= pos && rendered < results.length) renderBatch();
    openPeek(results[pos]._idx);
  }

  function trapFocus(event) {
    const container = !peekEl.hidden ? peekEl : (document.body.classList.contains('filters-open') ? filtersEl : null);
    if (!container || event.key !== 'Tab') return;
    const focusables = Array.from(container.querySelectorAll('a[href], button:not([hidden]), input, [tabindex="-1"]'))
      .filter(el => el.offsetParent !== null || el === document.activeElement);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
    else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
  }

  // --- Copy ---------------------------------------------------------------------

  function copyPayload(btn) {
    const idx = Number(btn.dataset.idx);
    const model = models[idx];
    switch (btn.dataset.copy) {
      case 'trigger': {
        const word = (model.trigger_words || [])[Number(btn.dataset.word)];
        return [word, `“${CS.shorten(word, 36)}”`];
      }
      case 'triggers': return [(model.trigger_words || []).join(', '), 'trigger words'];
      case 'path': return [CS.absolutePath(model.file_path), 'file path'];
      case 'folder': return [CS.parentDir(CS.absolutePath(model.file_path)), 'folder path'];
      case 'duplicate': return [CS.absolutePath((model.duplicates || [])[Number(btn.dataset.dup)]), 'path'];
      case 'unmatched': return [CS.absolutePath(unmatched[idx].file_path), 'path'];
      default: return ['', ''];
    }
  }

  // --- Events --------------------------------------------------------------------

  function setFacet(key, value, on) {
    const list = state[key];
    const at = list.indexOf(value);
    if (on && at < 0) list.push(value);
    if (!on && at >= 0) list.splice(at, 1);
    update();
  }

  function clearFilters() {
    facetKeys.forEach(k => { state[k] = []; });
    update();
  }

  function setView(view) {
    if (!VIEWS.includes(view) || view === state.view) return;
    state.view = view;
    setPref('view', view);
    update();
  }

  function setSort(sort, dir) {
    state.sort = sort;
    state.dir = dir || SORT_DEFAULT_DIR[sort];
    setPref('sort', state.sort);
    setPref('dir', state.dir);
    update();
  }

  let searchTimer = null;
  function onSearchInput() {
    clearTimeout(searchTimer);
    $('.search-clear').hidden = !searchInput.value;
    searchTimer = setTimeout(() => {
      state.q = searchInput.value.trim();
      update();
    }, SEARCH_DELAY);
  }

  function setSearch(text) {
    searchInput.value = text;
    state.q = text;
    update();
  }

  function onClick(event) {
    const copyBtn = event.target.closest('[data-copy]');
    if (copyBtn) {
      event.preventDefault();
      event.stopPropagation();
      const [text, what] = copyPayload(copyBtn);
      if (text) CS.copyWithFeedback(text, copyBtn, what);
      return;
    }
    const tile = event.target.closest('[data-group]');
    if (tile && level) return navigateTo(level.at.concat(tile.dataset.group));
    const el = event.target.closest('[data-action], [data-view], [data-health], [data-remove-facet], [data-sort], [data-search]');
    if (!el) return;
    if (el.dataset.view) return setView(el.dataset.view);
    if (el.dataset.health) {
      const label = HEALTH_LABELS[el.dataset.health];
      state.health = state.health.includes(label) ? [] : [label];
      return update();
    }
    if (el.dataset.removeFacet) return setFacet(el.dataset.removeFacet, el.dataset.value, false);
    if (el.dataset.sort) {
      const same = state.sort === el.dataset.sort;
      return setSort(el.dataset.sort, same ? (state.dir === 'asc' ? 'desc' : 'asc') : undefined);
    }
    if (el.dataset.search !== undefined) {
      closeOverlay();
      return setSearch(`"${el.dataset.search}"`);
    }
    switch (el.dataset.action) {
      case 'peek':
        event.preventDefault();
        return openPeek(Number(el.dataset.idx || el.closest('[data-idx]').dataset.idx));
      case 'peek-prev': return stepPeek(-1);
      case 'peek-next': return stepPeek(1);
      case 'close-overlay': return closeOverlay();
      case 'clear-search': setSearch(''); return searchInput.focus();
      case 'clear-filters': return clearFilters();
      case 'reset-all':
        facetKeys.forEach(k => { state[k] = []; });
        return setSearch('');
      case 'sort-dir': return setSort(state.sort, state.dir === 'asc' ? 'desc' : 'asc');
      case 'toggle-group': return setGrouped(!state.grouped);
      case 'toggle-blur': {
        const on = !document.body.classList.contains('nsfw-blur');
        document.body.classList.toggle('nsfw-blur', on);
        el.setAttribute('aria-pressed', String(on));
        return setPref('blur', on ? '1' : '0');
      }
      case 'show-unmatched':
        unmatchedEl.open = true;
        return unmatchedEl.scrollIntoView({ behavior: CS.reducedMotion() ? 'auto' : 'smooth', block: 'start' });
      case 'open-filters':
        document.body.classList.add('filters-open', 'overlay-open');
        scrim.hidden = false;
        return ($('summary', filtersEl) || filtersEl).focus();
      case 'close-filters': return closeOverlay();
    }
  }

  function onKeydown(event) {
    const typing = Boolean(event.target.matches && event.target.matches('input, textarea, select'));
    if (event.key === 'Escape') {
      if (!peekEl.hidden || document.body.classList.contains('filters-open')) { closeOverlay(); return; }
      if (event.target === searchInput && searchInput.value) { setSearch(''); return; }
      return;
    }
    if (event.key === 'Tab') { trapFocus(event); return; }
    if (typing) return;
    if (event.key === 'Backspace' && peekEl.hidden && !document.body.classList.contains('filters-open')) {
      if (goUp()) event.preventDefault();
      return;
    }
    if (event.key === '/' && peekEl.hidden) {
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
      return;
    }
    if (!peekEl.hidden && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
      event.preventDefault();
      stepPeek(event.key === 'ArrowRight' ? 1 : -1);
      return;
    }
    if (event.key === ' ' && peekEl.hidden) {
      const item = event.target.closest && event.target.closest('#results [data-idx]');
      if (item) {
        event.preventDefault();
        openPeek(Number(item.dataset.idx));
      }
    }
  }

  // --- Lazy videos, infinite scroll, return state ---------------------------------

  let videoObserver = null;
  function observeVideos() {
    if (!videoObserver) return;
    resultsEl.querySelectorAll('video[data-src]:not([data-observed])').forEach(v => {
      v.dataset.observed = '1';
      videoObserver.observe(v);
    });
  }

  function saveReturnState() {
    try {
      sessionStorage.setItem(RETURN_KEY, JSON.stringify({
        hash: window.location.hash, y: window.scrollY, rendered
      }));
    } catch (e) { /* no storage */ }
  }

  function restoreReturnState() {
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(RETURN_KEY) || 'null'); } catch (e) { saved = null; }
    if (!saved || saved.hash !== window.location.hash) return;
    while (rendered < Math.min(saved.rendered, results.length)) renderBatch();
    requestAnimationFrame(() => window.scrollTo(0, saved.y));
  }

  // --- Init -------------------------------------------------------------------------

  function init() {
    if (!models) {
      const box = $('#no-data');
      box.querySelector('.g-state-title').textContent = 'Gallery data is missing';
      box.querySelector('.g-state-text').innerHTML = 'The file <code>data/models_data.js</code> next to this page could not be loaded. Run the <code>regenerate-html</code> job to rebuild it.';
      box.hidden = false;
      return;
    }
    models.forEach((m, i) => { m._idx = i; });

    readHash();
    searchInput.value = state.q;

    const size = Number(pref('size', 230));
    sizeInput.value = size;
    document.documentElement.style.setProperty('--mount-min', size + 'px');
    if (pref('blur', '0') === '1') {
      document.body.classList.add('nsfw-blur');
      $('[data-action="toggle-blur"]').setAttribute('aria-pressed', 'true');
    }
    if (!models.some(m => m.nsfw)) $('[data-action="toggle-blur"]').hidden = true;

    if (!models.length) $('#no-data').hidden = false;

    renderHealth();
    renderUnmatched();
    buildFacets();
    renderResults();
    restoreReturnState();

    syncPeekWithState();

    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKeydown);
    searchInput.addEventListener('input', onSearchInput);
    sortSelect.addEventListener('change', () => setSort(sortSelect.value));
    sizeInput.addEventListener('input', () => {
      document.documentElement.style.setProperty('--mount-min', sizeInput.value + 'px');
      setPref('size', sizeInput.value);
    });
    facetsEl.addEventListener('change', e => {
      const box = e.target.closest('input[type="checkbox"]');
      if (box) setFacet(box.dataset.facet, box.value, box.checked);
    });
    facetsEl.addEventListener('input', e => {
      if (!e.target.matches('.facet-find')) return;
      const needle = e.target.value.trim().toLowerCase();
      e.target.closest('.facet').querySelectorAll('.facet-list li').forEach(li => {
        li.hidden = needle && !li.textContent.toLowerCase().includes(needle);
      });
    });
    facetsEl.addEventListener('toggle', e => {
      const section = e.target.closest('.facet');
      if (section) setPref('facet_' + section.dataset.facet, section.open ? 'open' : 'closed');
    }, true);
    window.addEventListener('pagehide', saveReturnState);
    window.addEventListener('hashchange', () => {
      readHash();
      searchInput.value = state.q;
      renderResults();
      syncPeekWithState();
    });

    if ('IntersectionObserver' in window) {
      new IntersectionObserver(entries => {
        if (entries.some(e => e.isIntersecting) && rendered < results.length) renderBatch();
      }, { rootMargin: `${LOAD_AHEAD}px 0px` }).observe(sentinel);
      // Previews that load or fail later change the layout without moving the
      // sentinel across the zone edge; scrolling and resizing re-check it.
      window.addEventListener('scroll', fillViewport, { passive: true });
      window.addEventListener('resize', fillViewport);
      videoObserver = new IntersectionObserver(entries => {
        entries.forEach(e => {
          if (!e.isIntersecting) return;
          const v = e.target;
          v.preload = 'metadata';
          v.src = v.dataset.src;
          v.removeAttribute('data-src');
          videoObserver.unobserve(v);
        });
      }, { rootMargin: '300px 0px' });
      observeVideos();
    } else {
      while (rendered < results.length) renderBatch();
    }
    CS.wireVideoPreviews(resultsEl, '[data-idx]');
  }

  // Exposed for the node test harness; harmless in the browser.
  window.CSGallery = { parseQuery, matchesQuery, versionLabel, compact, typeSlug, highlight };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
