// Gallery functionality with faceted filtering and URL state management
(function() {
  console.log("Gallery functionality script starting");

  // --- Configuration ---
  const DEBOUNCE_DELAY = 300;
  const BATCH_SIZE = 50;
  const PLACEHOLDER_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

  // --- DOM Elements ---
  const galleryLayout = document.querySelector('.gallery-layout');
  const gridViewBtn = document.getElementById('grid-view');
  const focusedViewBtn = document.getElementById('focused-view');
  const listViewBtn = document.getElementById('list-view');
  const modelsGridContainer = document.querySelector('.models-grid');
  const modelsFocusedContainer = document.querySelector('.models-focused');
  const modelsListContainer = document.querySelector('.models-list');
  const searchInput = document.getElementById('gallery-search');
  const clearSearchBtn = document.getElementById('clear-search');
  const sortBySelect = document.getElementById('sort-by');
  const sortDirectionBtn = document.getElementById('sort-direction');
  const noResultsEl = document.getElementById('no-results');
  const emptyGalleryEl = document.querySelector('.empty-gallery');
  const sidebarWrapper = document.getElementById('facet-sidebar');
  const toggleSidebarBtn = document.getElementById('toggle-sidebar');
  const facetContainer = document.querySelector('.facet-container');
  const activeFiltersBar = document.querySelector('.active-filters');
  const filterPillsContainer = document.querySelector('.filter-pills');
  const clearAllFiltersBtn = document.querySelector('.clear-all-filters');
  const resultsCountEl = document.querySelector('.results-count');
  const infiniteScrollSentinel = document.getElementById('infinite-scroll-sentinel');

  // --- State ---
  let allModelsData = [];
  let currentFilteredSortedModels = [];
  let renderedModelCount = 0;

  let unmatchedData = [];

  // Filter state; every facet below adds an array of selected values.
  const filterState = {
    searchText: '',
    sortBy: 'name',
    sortDir: 'desc',
    viewMode: 'grid'
  };

  const HEALTH_LABELS = {
    update: 'Update available',
    no_preview: 'No preview',
    duplicate: 'Duplicate'
  };

  // Facets. values(model) lists a model's values for the facet; a model can have
  // several (health flags) and matches when any of them is selected. param is the
  // URL hash key. Empty facets are not shown.
  const facetConfig = {
    health: { label: 'Health', icon: '🩺', param: 'health',
              values: m => (m.health || []).map(flag => HEALTH_LABELS[flag] || flag) },
    types: { label: 'Model Type', icon: '🏷️', param: 'type', values: m => [m.type || 'Unknown'] },
    baseModels: { label: 'Base Model', icon: '🧩', param: 'base', values: m => [m.base_model || 'Unknown'] },
    creators: { label: 'Creator', icon: '👤', param: 'creator', values: m => [m.creator || 'Unknown'],
                collapsed: true },
    folders: { label: 'Folder', icon: '📁', param: 'folder', values: m => [m.folder_name || 'Unknown'] }
  };
  const facetKeys = Object.keys(facetConfig);
  facetKeys.forEach(key => { filterState[key] = []; });

  function facetValues(model, key) {
    if (!model._facets) {
      model._facets = {};
      facetKeys.forEach(k => { model._facets[k] = facetConfig[k].values(model); });
    }
    return model._facets[key];
  }

  function passesFacet(model, key) {
    const selected = filterState[key];
    return selected.length === 0 || facetValues(model, key).some(v => selected.includes(v));
  }

  // --- Helper Functions ---

  function storePreference(key, value) {
    try {
      localStorage.setItem('gallery_' + key, value);
    } catch (e) {
      console.warn('localStorage not available:', e);
    }
  }

  function getPreference(key, defaultValue) {
    try {
      const value = localStorage.getItem('gallery_' + key);
      return value !== null ? value : defaultValue;
    } catch (e) {
      console.warn('localStorage not available:', e);
      return defaultValue;
    }
  }

  function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>"']/g, function (match) {
      return {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[match];
    });
  }

  // Turn a local filesystem path (POSIX, Windows drive or UNC) into a file:// URL with
  // every path segment percent-encoded, so names containing #, %, ? or spaces still
  // link correctly. Existing URLs (http/https/file/data) are returned unchanged.
  function toFileUrl(path) {
    if (!path) return '';
    const str = String(path);
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(str) || str.startsWith('data:')) return str;
    let normalized = str.replace(/\\/g, '/');
    let prefix = 'file://';
    if (normalized.startsWith('//')) {
      // UNC path: //server/share/... -> file://server/share/...
      normalized = normalized.slice(2);
    } else if (/^[A-Za-z]:\//.test(normalized)) {
      prefix = 'file:///';
    } else if (!normalized.startsWith('/')) {
      // Relative path: encode segments, keep it relative
      prefix = '';
    }
    const encoded = normalized
      .split('/')
      .map((segment, i) => (i === 0 && /^[A-Za-z]:$/.test(segment) ? segment : encodeURIComponent(segment)))
      .join('/');
    return prefix + encoded;
  }

  // Absolute filesystem path for a (possibly gallery-relative) path, for copying.
  // Relative paths are resolved against the gallery's own file:// location.
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
    if (url.host) return '\\\\' + url.host + resolved.replace(/\//g, '\\');  // UNC
    if (/^\/[A-Za-z]:\//.test(resolved)) return resolved.slice(1).replace(/\//g, '\\');  // C:\...
    return resolved;
  }

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

  // file:// pages are not a secure context in every browser, so fall back to the
  // old textarea + execCommand route when the Clipboard API is unavailable.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => legacyCopy(text));
    }
    return Promise.resolve(legacyCopy(text));
  }

  function flashCopied(button, ok) {
    if (!button.dataset.label) button.dataset.label = button.innerHTML;
    button.textContent = ok ? 'Copied' : 'Copy failed';
    button.classList.add(ok ? 'copied' : 'copy-failed');
    clearTimeout(button._copyTimer);
    button._copyTimer = setTimeout(() => {
      button.innerHTML = button.dataset.label;
      button.classList.remove('copied', 'copy-failed');
    }, 1200);
  }

  function textToCopy(button) {
    const idx = parseInt(button.dataset.idx, 10);
    switch (button.dataset.copy) {
      case 'triggers':
        return (allModelsData[idx].trigger_words || []).join(', ');
      case 'path':
        return absolutePath(allModelsData[idx].file_path);
      case 'duplicate':
        return absolutePath((allModelsData[idx].duplicates || [])[parseInt(button.dataset.dup, 10)]);
      case 'unmatched':
        return absolutePath(unmatchedData[idx].file_path);
      default:
        return '';
    }
  }

  // Capture phase: runs before the card's own link/video handlers.
  function handleCopyClick(event) {
    const button = event.target.closest('[data-copy]');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    const text = textToCopy(button);
    if (!text) return;
    copyText(text).then(ok => flashCopied(button, ok));
  }

  // --- Collection health ---

  function renderHealthSummary() {
    const el = document.querySelector('.health-summary');
    if (!el) return;
    const countFlag = flag => allModelsData.filter(m => (m.health || []).includes(flag)).length;
    const parts = [];
    [['update', 'with updates'], ['no_preview', 'without preview'], ['duplicate', 'with duplicates']]
      .forEach(([flag, text]) => {
        const n = countFlag(flag);
        if (n) parts.push(`<button type="button" class="health-link" data-health="${flag}">${n} ${text}</button>`);
      });
    const notOnCivitai = unmatchedData.filter(u => u.reason === 'not_on_civitai').length;
    const noMetadata = unmatchedData.length - notOnCivitai;
    if (notOnCivitai) parts.push(`<button type="button" class="health-link" data-unmatched="1">${notOnCivitai} not on CivitAI</button>`);
    if (noMetadata) parts.push(`<button type="button" class="health-link" data-unmatched="1">${noMetadata} without metadata</button>`);

    if (parts.length === 0) {
      el.style.display = 'none';
      return;
    }
    el.innerHTML = `<span class="health-total">${allModelsData.length} models</span>` +
      parts.map(p => `<span class="health-sep">·</span>${p}`).join('');
    el.style.display = 'flex';

    el.querySelectorAll('[data-health]').forEach(btn => {
      btn.addEventListener('click', () => {
        filterState.health = [HEALTH_LABELS[btn.dataset.health]];
        syncUrlState();
        updateGallery();
        renderFacets();
        renderActiveFilters();
      });
    });
    el.querySelectorAll('[data-unmatched]').forEach(btn => {
      btn.addEventListener('click', () => {
        const panel = document.querySelector('.unmatched-panel');
        if (!panel) return;
        panel.open = true;
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  const UNMATCHED_GROUPS = [
    ['not_on_civitai', 'Not on CivitAI',
     'CivitAI answered "not found" for these files: deleted, private, or from another site.'],
    ['no_metadata', 'No metadata yet',
     'Not looked up yet, or the lookup failed (see the log). Running the scan again retries them.']
  ];
  const MAX_UNMATCHED_ROWS = 1000;

  function renderUnmatchedPanel() {
    const panel = document.querySelector('.unmatched-panel');
    if (!panel) return;
    if (!unmatchedData.length) {
      panel.style.display = 'none';
      return;
    }
    panel.querySelector('.unmatched-summary').textContent =
      `${unmatchedData.length} scanned file${unmatchedData.length === 1 ? '' : 's'} without a gallery card`;

    let html = '';
    UNMATCHED_GROUPS.forEach(([reason, title, help]) => {
      const rows = [];
      unmatchedData.forEach((entry, idx) => {
        if (entry.reason === reason) rows.push([entry, idx]);
      });
      if (!rows.length) return;
      const shown = rows.slice(0, MAX_UNMATCHED_ROWS).map(([entry, idx]) => `
          <div class="unmatched-row">
            <span class="unmatched-name">${escapeHTML(entry.name)}</span>
            <span class="unmatched-folder">${escapeHTML(entry.folder)}</span>
            <button type="button" class="card-action small" data-copy="unmatched" data-idx="${idx}"
                    title="${escapeHTML(absolutePath(entry.file_path))}">📋 Path</button>
          </div>`).join('');
      const more = rows.length > MAX_UNMATCHED_ROWS
        ? `<div class="unmatched-more">… and ${rows.length - MAX_UNMATCHED_ROWS} more</div>` : '';
      html += `
        <section class="unmatched-group">
          <h4>${escapeHTML(title)} (${rows.length})</h4>
          <p class="unmatched-help">${escapeHTML(help)}</p>
          ${shown}${more}
        </section>`;
    });
    panel.querySelector('.unmatched-groups').innerHTML = html;
    panel.style.display = 'block';
  }

  function formatDate(dateString) {
    if (!dateString) return '';
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) return dateString;
      return date.toISOString().split('T')[0];
    } catch (e) {
      console.warn('Error formatting date:', dateString, e);
      return dateString;
    }
  }

  // --- URL State Management ---

  function parseUrlState() {
    const hash = window.location.hash.slice(1);
    if (!hash) return;

    const params = new URLSearchParams(hash);

    // Facet selections
    facetKeys.forEach(key => {
      const value = params.get(facetConfig[key].param);
      filterState[key] = value ? value.split(',').map(decodeURIComponent).filter(Boolean) : [];
    });

    // Parse single value parameters
    const searchParam = params.get('q');
    if (searchParam !== null) {
      filterState.searchText = decodeURIComponent(searchParam);
    }

    const sortParam = params.get('sort');
    if (sortParam && ['name', 'created_at', 'updated_at', 'downloads', 'rating', 'file_modified'].includes(sortParam)) {
      filterState.sortBy = sortParam;
    }

    const dirParam = params.get('dir');
    if (dirParam && ['asc', 'desc'].includes(dirParam)) {
      filterState.sortDir = dirParam;
    }

    const viewParam = params.get('view');
    if (viewParam && ['grid', 'focused', 'list'].includes(viewParam)) {
      filterState.viewMode = viewParam;
    }

    console.log("Parsed URL state:", filterState);
  }

  function syncUrlState() {
    const params = new URLSearchParams();

    facetKeys.forEach(key => {
      if (filterState[key].length > 0) {
        params.set(facetConfig[key].param, filterState[key].map(encodeURIComponent).join(','));
      }
    });
    if (filterState.searchText) {
      params.set('q', encodeURIComponent(filterState.searchText));
    }
    if (filterState.sortBy !== 'name') {
      params.set('sort', filterState.sortBy);
    }
    if (filterState.sortDir !== 'desc') {
      params.set('dir', filterState.sortDir);
    }
    if (filterState.viewMode !== 'grid') {
      params.set('view', filterState.viewMode);
    }

    const hashString = params.toString();
    const newUrl = hashString ? `#${hashString}` : window.location.pathname + window.location.search;

    // Use replaceState to avoid polluting history for every filter change
    window.history.replaceState(null, '', newUrl);
  }

  // --- Facet Count Computation ---

  function computeFacetCounts() {
    const counts = {};
    facetKeys.forEach(key => { counts[key] = new Map(); });

    // Every known value is listed (count 0 if the other filters exclude it)
    allModelsData.forEach(model => {
      facetKeys.forEach(key => {
        facetValues(model, key).forEach(v => {
          if (!counts[key].has(v)) counts[key].set(v, 0);
        });
      });
    });

    // A facet's counts honor the search and every OTHER facet's selection: "what
    // would be available if I select this value".
    allModelsData.forEach(model => {
      if (filterState.searchText && !modelMatchesSearch(model, filterState.searchText)) return;
      const passes = {};
      facetKeys.forEach(key => { passes[key] = passesFacet(model, key); });
      facetKeys.forEach(key => {
        if (!facetKeys.every(other => other === key || passes[other])) return;
        facetValues(model, key).forEach(v => {
          counts[key].set(v, counts[key].get(v) + 1);
        });
      });
    });

    return counts;
  }

  // Lowercased search text, built once per model (search and facet counts run this
  // for every model on every keystroke).
  function searchTextOf(model) {
    if (model._search === undefined) {
      model._search = [
        model.name, model.type, model.base_model, model.folder_name, model.creator,
        ...(model.tags || []), ...(model.trigger_words || []), model.description
      ]
        .filter(Boolean)
        .join('\n')
        .toLowerCase();
    }
    return model._search;
  }

  function modelMatchesSearch(model, searchText) {
    if (!searchText) return true;
    return searchTextOf(model).includes(searchText.toLowerCase());
  }

  // --- Facet Rendering ---

  function renderFacets() {
    if (!facetContainer) return;

    const counts = computeFacetCounts();

    let html = '';

    // Render each facet section
    Object.entries(facetConfig).forEach(([facetKey, config]) => {
      const facetCounts = counts[facetKey];
      const selectedValues = filterState[facetKey];

      // Sort by count (desc), then alphabetically
      const sortedEntries = Array.from(facetCounts.entries())
        .sort((a, b) => {
          if (b[1] !== a[1]) return b[1] - a[1];
          return a[0].localeCompare(b[0]);
        });

      if (sortedEntries.length === 0) return;

      const isExpanded = selectedValues.length > 0 || !config.collapsed;

      html += `
        <div class="facet-section" data-facet="${facetKey}">
          <div class="facet-header" data-expanded="${isExpanded}">
            <span class="facet-icon">${config.icon}</span>
            <span class="facet-label">${config.label}</span>
            <span class="facet-toggle">${isExpanded ? '−' : '+'}</span>
          </div>
          <div class="facet-items" style="display: ${isExpanded ? 'block' : 'none'}">
            ${sortedEntries.map(([value, count]) => {
              const isSelected = selectedValues.includes(value);
              const isDisabled = count === 0 && !isSelected;
              return `
                <label class="facet-item ${isSelected ? 'selected' : ''} ${isDisabled ? 'disabled' : ''}">
                  <input type="checkbox"
                         data-facet="${facetKey}"
                         data-value="${escapeHTML(value)}"
                         ${isSelected ? 'checked' : ''}
                         ${isDisabled ? 'disabled' : ''}>
                  <span class="facet-checkbox"></span>
                  <span class="facet-value">${escapeHTML(value)}</span>
                  <span class="facet-count">${count}</span>
                </label>
              `;
            }).join('')}
          </div>
        </div>
      `;
    });

    facetContainer.innerHTML = html;
    attachFacetEventListeners();
  }

  function attachFacetEventListeners() {
    // Facet header toggle
    facetContainer.querySelectorAll('.facet-header').forEach(header => {
      header.addEventListener('click', function() {
        const section = this.closest('.facet-section');
        const items = section.querySelector('.facet-items');
        const toggle = this.querySelector('.facet-toggle');
        const isExpanded = this.dataset.expanded === 'true';

        this.dataset.expanded = !isExpanded;
        items.style.display = isExpanded ? 'none' : 'block';
        toggle.textContent = isExpanded ? '+' : '−';
      });
    });

    // Checkbox change handlers
    facetContainer.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
      checkbox.addEventListener('change', function() {
        const facetKey = this.dataset.facet;
        const value = this.dataset.value;

        toggleFacetValue(facetKey, value, this.checked);
      });
    });
  }

  function toggleFacetValue(facetKey, value, isSelected) {
    const values = filterState[facetKey];

    if (isSelected) {
      if (!values.includes(value)) {
        values.push(value);
      }
    } else {
      const index = values.indexOf(value);
      if (index > -1) {
        values.splice(index, 1);
      }
    }

    syncUrlState();
    storePreference(facetKey, JSON.stringify(values));
    updateGallery();
    renderFacets();
    renderActiveFilters();
  }

  // --- Active Filters Rendering ---

  function renderActiveFilters() {
    if (!filterPillsContainer || !activeFiltersBar) return;

    const hasFilters = facetKeys.some(key => filterState[key].length > 0);

    let pillsHtml = '';

    // Generate pills for each facet
    Object.entries(facetConfig).forEach(([facetKey, config]) => {
      filterState[facetKey].forEach(value => {
        pillsHtml += `
          <span class="filter-pill" data-facet="${facetKey}" data-value="${escapeHTML(value)}">
            <span class="pill-category">${config.label}:</span>
            <span class="pill-value">${escapeHTML(value)}</span>
            <button class="pill-remove" title="Remove filter">×</button>
          </span>
        `;
      });
    });

    filterPillsContainer.innerHTML = pillsHtml;

    // Show/hide clear all button
    if (clearAllFiltersBtn) {
      clearAllFiltersBtn.style.display = hasFilters ? 'inline-flex' : 'none';
    }

    // Update results count
    if (resultsCountEl) {
      const total = allModelsData.length;
      const shown = currentFilteredSortedModels.length;
      if (hasFilters || filterState.searchText) {
        resultsCountEl.textContent = `Showing ${shown} of ${total} models`;
      } else {
        resultsCountEl.textContent = `${total} models`;
      }
    }

    // Attach pill remove listeners
    filterPillsContainer.querySelectorAll('.pill-remove').forEach(btn => {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        const pill = this.closest('.filter-pill');

        const facetKey = pill.dataset.facet;
        const value = pill.dataset.value;
        toggleFacetValue(facetKey, value, false);
      });
    });
  }

  // --- Rendering Functions ---

  function renderBatch(modelsToRender) {
    console.log(`Rendering batch of ${modelsToRender.length} models`);

    if (modelsToRender.length === 0) {
      console.warn("renderBatch called with empty array");
      return;
    }

    const gridFragment = document.createDocumentFragment();
    const focusedFragment = document.createDocumentFragment();
    const listFragment = document.createDocumentFragment();

    modelsToRender.forEach(model => {
      const cardHTML = renderModelCard(model);
      const focusedHTML = renderModelFocusedItem(model);
      const itemHTML = renderModelListItem(model);

      const cardTemplate = document.createElement('template');
      cardTemplate.innerHTML = cardHTML.trim();
      gridFragment.appendChild(cardTemplate.content.firstChild);

      const focusedTemplate = document.createElement('template');
      focusedTemplate.innerHTML = focusedHTML.trim();
      focusedFragment.appendChild(focusedTemplate.content.firstChild);

      const itemTemplate = document.createElement('template');
      itemTemplate.innerHTML = itemHTML.trim();
      listFragment.appendChild(itemTemplate.content.firstChild);
    });

    if (filterState.searchText) {
      highlightTextInContainer(gridFragment, filterState.searchText);
      highlightTextInContainer(focusedFragment, filterState.searchText);
      highlightTextInContainer(listFragment, filterState.searchText);
    }

    modelsGridContainer.appendChild(gridFragment);
    modelsFocusedContainer.appendChild(focusedFragment);
    modelsListContainer.appendChild(listFragment);

    observeImages(modelsGridContainer);
    observeImages(modelsFocusedContainer);
    observeImages(modelsListContainer);

    console.log(`Appended batch of ${modelsToRender.length} models.`);
  }

  // Badges for health flags (inside the card link; purely informational)
  function healthBadgesHtml(model) {
    const health = model.health || [];
    let html = '';
    if (health.includes('update')) {
      const title = model.update_version ? `Newer version on CivitAI: ${model.update_version}` : 'Newer version on CivitAI';
      html += `<span class="health-badge update" title="${escapeHTML(title)}">Update</span>`;
    }
    if (health.includes('duplicate')) {
      const n = (model.duplicates || []).length;
      html += `<span class="health-badge duplicate" title="Same version stored ${n} times">${n}× copies</span>`;
    }
    return html ? `<div class="health-badges">${html}</div>` : '';
  }

  // Copy buttons. They sit outside the card's <a>, and the click handler stops the
  // event, so copying never opens the detail page.
  function cardActionsHtml(model) {
    const idx = model._idx;
    const words = model.trigger_words || [];
    let html = '';
    if (words.length) {
      html += `<button type="button" class="card-action" data-copy="triggers" data-idx="${idx}"
                 title="Copy trigger words: ${escapeHTML(words.join(', '))}">📋 Triggers</button>`;
    }
    if (model.file_path) {
      html += `<button type="button" class="card-action" data-copy="path" data-idx="${idx}"
                 title="Copy model file path">📋 Path</button>`;
    }
    const duplicates = model.duplicates || [];
    if (duplicates.length > 1) {
      const rows = duplicates.map((p, i) => `
          <div class="duplicate-row">
            <span class="duplicate-path" title="${escapeHTML(absolutePath(p))}">${escapeHTML(absolutePath(p))}</span>
            <button type="button" class="card-action small" data-copy="duplicate" data-idx="${idx}" data-dup="${i}">📋</button>
          </div>`).join('');
      html += `<details class="duplicate-list"><summary>${duplicates.length} copies</summary>${rows}</details>`;
    }
    return html ? `<div class="card-actions">${html}</div>` : '';
  }

  function renderModelCard(model) {
    const rating = model.stats?.rating ? parseFloat(model.stats.rating).toFixed(1) : '0';
    const ratingCount = model.stats?.rating_count || 0;
    const downloads = model.stats?.downloads || 0;

    // Build version list (local + remote) for badge/dropdown.
    const versions = model.versions || [];
    const localCount = versions.filter(v => v.is_local).length;
    const totalCount = versions.length;

    let mergedVersionsHtml = '';
    if (totalCount > 1) {
      const versionsList = versions
        .map(v => {
          const cls = 'merged-version-link ' + (v.is_local ? 'local' : 'remote') +
                      (v.is_current ? ' current' : '');
          const target = v.is_local ? '' : ' target="_blank" rel="noopener"';
          return `<a href="${escapeHTML(toFileUrl(v.link || ''))}" class="${cls}"${target}>${escapeHTML(v.name || '')}</a>`;
        })
        .join('');
      mergedVersionsHtml = `
        <div class="merged-versions-badge" title="${localCount} local / ${totalCount} total versions">
          <span class="merged-count">${localCount}/${totalCount} versions</span>
          <div class="merged-versions-dropdown">
            ${versionsList}
          </div>
        </div>`;
    }

    return `
      <div class="model-card ${totalCount > 1 ? 'has-merged-versions' : ''}"
          data-model-id="${escapeHTML(model.model_id)}"
          data-version-id="${escapeHTML(model.version_id)}"
          data-name="${escapeHTML(model.name?.toLowerCase())}"
          data-type="${escapeHTML(model.type?.toLowerCase())}"
          data-base-model="${escapeHTML(model.base_model?.toLowerCase())}"
          data-folder-name="${escapeHTML(model.folder_name?.toLowerCase())}"
          data-created-at="${escapeHTML(model.created_at || '')}"
          data-updated-at="${escapeHTML(model.updated_at || '')}"
          data-downloads="${downloads}"
          data-rating="${rating}"
          data-file-modified="${escapeHTML(model.file_modified || '')}">
          <a href="${escapeHTML(toFileUrl(model.html_path))}" class="model-link">
              ${model.preview_image_path
                  ? `<div class="model-preview">
                      ${model.is_video
                          ? `<video src="${escapeHTML(toFileUrl(model.preview_image_path))}" preload="metadata" class="preview-video" muted loop playsinline></video><div class="video-indicator">VIDEO</div><div class="video-play-overlay"><svg class="play-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><svg class="pause-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg></div>`
                          : `<img src="${PLACEHOLDER_IMAGE}" data-src="${escapeHTML(toFileUrl(model.preview_image_path))}" alt="${escapeHTML(model.name)}" class="lazy-load-image">`
                      }
                    </div>`
                  : `<div class="model-preview no-image"><div class="no-image-text">No Preview</div></div>`
              }
              ${healthBadgesHtml(model)}
              <div class="model-info">
                  <h3 class="model-name">${escapeHTML(model.name)}</h3>
                  <div class="model-meta">
                      <span class="model-type">${escapeHTML(model.type)}</span>
                      <span class="model-base">${escapeHTML(model.base_model)}</span>
                  </div>
                  <div class="model-stats">
                      ${downloads > 0 ? `
                      <span class="stat-item downloads" title="Downloads">
                          <span class="stat-icon">⬇️</span>
                          <span class="stat-value">${downloads.toLocaleString()}</span>
                      </span>` : ''}
                      ${parseFloat(rating) > 0 ? `
                      <span class="stat-item rating" title="Rating">
                          <span class="stat-icon">⭐</span>
                          <span class="stat-value">${rating}</span>
                          ${ratingCount > 0 ? `<span class="stat-count">(${ratingCount.toLocaleString()})</span>` : ''}
                      </span>` : ''}
                  </div>
                  ${model.version ? `<div class="model-version">v${escapeHTML(model.version)}</div>` : ''}
              </div>
          </a>
          ${mergedVersionsHtml}
          ${cardActionsHtml(model)}
      </div>`;
  }

  function renderModelFocusedItem(model) {
    return `
      <div class="model-focused-item"
          data-model-id="${escapeHTML(model.model_id)}"
          data-name="${escapeHTML(model.name?.toLowerCase())}">
          <a href="${escapeHTML(toFileUrl(model.html_path))}" class="model-link">
              ${model.preview_image_path
                  ? `<div class="focused-preview">
                      ${model.is_video
                          ? `<video src="${escapeHTML(toFileUrl(model.preview_image_path))}" preload="metadata" class="preview-video" muted loop playsinline></video><div class="video-indicator">VIDEO</div><div class="video-play-overlay"><svg class="play-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><svg class="pause-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg></div>`
                          : `<img src="${PLACEHOLDER_IMAGE}" data-src="${escapeHTML(toFileUrl(model.preview_image_path))}" alt="${escapeHTML(model.name)}" class="lazy-load-image">`
                      }
                    </div>`
                  : `<div class="focused-preview no-image"></div>`
              }
              ${healthBadgesHtml(model)}
              <div class="focused-overlay">
                  <h3 class="focused-name">${escapeHTML(model.name)}</h3>
              </div>
          </a>
          ${cardActionsHtml(model)}
      </div>`;
  }

  function renderModelListItem(model) {
    const rating = model.stats?.rating ? parseFloat(model.stats.rating).toFixed(1) : '0';
    const ratingCount = model.stats?.rating_count || 0;
    const downloads = model.stats?.downloads || 0;

    return `
      <div class="model-list-item"
          data-model-id="${escapeHTML(model.model_id)}"
          data-version-id="${escapeHTML(model.version_id)}"
          data-name="${escapeHTML(model.name?.toLowerCase())}"
          data-type="${escapeHTML(model.type?.toLowerCase())}"
          data-base-model="${escapeHTML(model.base_model?.toLowerCase())}"
          data-folder-name="${escapeHTML(model.folder_name?.toLowerCase())}"
          data-created-at="${escapeHTML(model.created_at || '')}"
          data-updated-at="${escapeHTML(model.updated_at || '')}"
          data-downloads="${downloads}"
          data-rating="${rating}"
          data-file-modified="${escapeHTML(model.file_modified || '')}">
          <a href="${escapeHTML(toFileUrl(model.html_path))}" class="model-link">
              <div class="model-list-preview">
                  ${model.preview_image_path
                      ? `${model.is_video
                          ? `<video src="${escapeHTML(toFileUrl(model.preview_image_path))}" preload="metadata" class="preview-video" muted loop playsinline></video><div class="video-indicator mini">VIDEO</div><div class="video-play-overlay mini"><svg class="play-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><svg class="pause-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg></div>`
                          : `<img src="${PLACEHOLDER_IMAGE}" data-src="${escapeHTML(toFileUrl(model.preview_image_path))}" alt="${escapeHTML(model.name)}" class="lazy-load-image">`
                        }`
                      : `<div class="no-image-text">No Preview</div>`
                  }
              </div>
              <div class="model-list-info">
                  <h3 class="model-name">${escapeHTML(model.name)}</h3>
                  <div class="model-meta">
                      <span class="model-type">${escapeHTML(model.type)}</span>
                      <span class="model-base">${escapeHTML(model.base_model)}</span>
                      ${model.version ? `<span class="model-version">v${escapeHTML(model.version)}</span>` : ''}
                  </div>
              </div>
              <div class="model-list-stats">
                  ${downloads > 0 ? `
                  <span class="stat-item downloads" title="Downloads">
                      <span class="stat-icon">⬇️</span>
                      <span class="stat-value">${downloads.toLocaleString()}</span>
                  </span>` : ''}
                  ${parseFloat(rating) > 0 ? `
                  <span class="stat-item rating" title="Rating">
                      <span class="stat-icon">⭐</span>
                      <span class="stat-value">${rating}</span>
                      ${ratingCount > 0 ? `<span class="stat-count">(${ratingCount.toLocaleString()})</span>` : ''}
                  </span>` : ''}
                  ${model.created_at ? `
                  <span class="stat-item date" title="Created">
                      <span class="stat-icon">📅</span>
                      <span class="stat-value date-value">${formatDate(model.created_at)}</span>
                  </span>` : ''}
              </div>
          </a>
          ${healthBadgesHtml(model)}
          ${cardActionsHtml(model)}
      </div>`;
  }

  function renderNextBatch() {
    console.log(`Attempting to render next batch. Rendered: ${renderedModelCount}, Total: ${currentFilteredSortedModels.length}`);
    if (renderedModelCount >= currentFilteredSortedModels.length) {
      console.log("All models rendered.");
      return;
    }

    const nextBatch = currentFilteredSortedModels.slice(renderedModelCount, renderedModelCount + BATCH_SIZE);
    if (nextBatch.length > 0) {
      renderBatch(nextBatch);
      renderedModelCount += nextBatch.length;
    } else {
      console.log("No more models in the next batch slice.");
    }

    if (renderedModelCount >= currentFilteredSortedModels.length) {
      console.log("All models have been rendered after this batch.");
      if (scrollObserver && infiniteScrollSentinel) {
        scrollObserver.unobserve(infiniteScrollSentinel);
        console.log("Infinite scroll observer disconnected.");
      }
    }
  }

  // --- Data Processing Functions ---

  function filterAndSortModels() {
    let filteredModels = [...allModelsData];

    // 1. Facets (AND across facets, OR within one)
    filteredModels = filteredModels.filter(model => facetKeys.every(key => passesFacet(model, key)));

    // 4. Apply Search Filter
    if (filterState.searchText) {
      filteredModels = filteredModels.filter(model =>
        modelMatchesSearch(model, filterState.searchText)
      );
    }

    // 5. Apply Sorting
    const multiplier = filterState.sortDir === 'asc' ? 1 : -1;
    filteredModels.sort((a, b) => {
      let valueA, valueB;

      switch (filterState.sortBy) {
        case 'name':
          valueA = a.name || '';
          valueB = b.name || '';
          return multiplier * valueA.localeCompare(valueB);
        case 'rating':
          valueA = parseFloat(a.stats?.rating) || 0;
          valueB = parseFloat(b.stats?.rating) || 0;
          break;
        case 'downloads':
          valueA = parseInt(a.stats?.downloads) || 0;
          valueB = parseInt(b.stats?.downloads) || 0;
          break;
        case 'created_at':
        case 'updated_at':
        case 'file_modified':
          valueA = a[filterState.sortBy] ? new Date(a[filterState.sortBy]).getTime() : 0;
          valueB = b[filterState.sortBy] ? new Date(b[filterState.sortBy]).getTime() : 0;
          break;
        default:
          return 0;
      }

      if (valueA === valueB) {
        return (a.name || '').localeCompare(b.name || '');
      }
      return multiplier * (valueA - valueB);
    });

    return filteredModels;
  }

  function updateGallery() {
    currentFilteredSortedModels = filterAndSortModels();
    console.log(`Updating gallery. Found ${currentFilteredSortedModels.length} models after filtering/sorting.`);

    modelsGridContainer.innerHTML = '';
    modelsFocusedContainer.innerHTML = '';
    modelsListContainer.innerHTML = '';
    renderedModelCount = 0;

    if (currentFilteredSortedModels.length === 0) {
      noResultsEl.style.display = 'block';
      if (scrollObserver && infiniteScrollSentinel) {
        scrollObserver.unobserve(infiniteScrollSentinel);
        console.log("Infinite scroll observer disconnected (no results).");
      }
      renderActiveFilters();
      return;
    } else {
      noResultsEl.style.display = 'none';
    }

    renderNextBatch();

    if (scrollObserver && infiniteScrollSentinel && renderedModelCount < currentFilteredSortedModels.length) {
      scrollObserver.observe(infiniteScrollSentinel);
      console.log("Infinite scroll observer (re)activated.");
    }

    renderActiveFilters();
  }

  // --- Highlighting ---

  function highlightText(element, searchText) {
    if (!searchText.trim()) return;

    const allTextNodes = [];
    const walker = document.createTreeWalker(
      element,
      NodeFilter.SHOW_TEXT,
      { acceptNode: node => (node.nodeValue.trim() && !node.parentNode.closest('.highlight')) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT },
      false
    );

    let node;
    while (node = walker.nextNode()) {
      allTextNodes.push(node);
    }

    const escapedSearchText = searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escapedSearchText})`, 'gi');

    allTextNodes.forEach(textNode => {
      const parent = textNode.parentNode;
      if (parent.nodeName === 'SCRIPT' || parent.nodeName === 'STYLE' || parent.nodeName === 'A') return;

      const matches = textNode.nodeValue.match(regex);
      if (!matches) return;

      const fragment = document.createDocumentFragment();
      const parts = textNode.nodeValue.split(regex);

      parts.forEach((part, i) => {
        if (i % 2 === 0) {
          if (part) fragment.appendChild(document.createTextNode(part));
        } else {
          const highlightSpan = document.createElement('span');
          highlightSpan.className = 'highlight';
          highlightSpan.textContent = part;
          fragment.appendChild(highlightSpan);
        }
      });
      parent.replaceChild(fragment, textNode);
    });
  }

  function removeHighlights(container) {
    const highlights = container.querySelectorAll('.highlight');
    highlights.forEach(highlight => {
      const parent = highlight.parentNode;
      if (parent) {
        parent.replaceChild(document.createTextNode(highlight.textContent), highlight);
        parent.normalize();
      }
    });
  }

  function highlightTextInContainer(container, searchText) {
    container.querySelectorAll('.model-card .model-info, .model-list-item .model-list-info').forEach(infoElement => {
      highlightText(infoElement, searchText);
    });
  }

  // --- Event Handlers ---

  function handleViewToggle(mode) {
    console.log(`Setting view mode to: ${mode}`);
    filterState.viewMode = mode;

    // Remove active from all containers and buttons
    modelsGridContainer.classList.remove('view-active');
    modelsFocusedContainer.classList.remove('view-active');
    modelsListContainer.classList.remove('view-active');
    gridViewBtn.classList.remove('active');
    focusedViewBtn.classList.remove('active');
    listViewBtn.classList.remove('active');

    // Set active for selected mode
    if (mode === 'grid') {
      modelsGridContainer.classList.add('view-active');
      gridViewBtn.classList.add('active');
    } else if (mode === 'focused') {
      modelsFocusedContainer.classList.add('view-active');
      focusedViewBtn.classList.add('active');
    } else {
      modelsListContainer.classList.add('view-active');
      listViewBtn.classList.add('active');
    }

    storePreference('view', mode);
    syncUrlState();
  }

  function handleSortChange() {
    filterState.sortBy = sortBySelect.value;
    storePreference('sortBy', filterState.sortBy);
    console.log("Sort by changed:", filterState.sortBy);
    syncUrlState();
    updateGallery();
  }

  function handleSortDirectionToggle() {
    filterState.sortDir = filterState.sortDir === 'desc' ? 'asc' : 'desc';
    sortDirectionBtn.setAttribute('data-direction', filterState.sortDir);
    sortDirectionBtn.querySelector('svg').style.transform = filterState.sortDir === 'asc' ? 'rotate(180deg)' : '';
    storePreference('sortDir', filterState.sortDir);
    console.log("Sort direction changed:", filterState.sortDir);
    syncUrlState();
    updateGallery();
  }

  let searchDebounceTimeout;
  function handleSearchInput() {
    clearTimeout(searchDebounceTimeout);
    searchDebounceTimeout = setTimeout(() => {
      filterState.searchText = searchInput.value.trim();
      console.log("Searching for:", filterState.searchText);
      syncUrlState();
      updateGallery();
      renderFacets(); // Update counts based on search
    }, DEBOUNCE_DELAY);
  }

  function handleClearSearch() {
    searchInput.value = '';
    filterState.searchText = '';
    searchInput.focus();
    syncUrlState();
    updateGallery();
    renderFacets();
  }

  function handleClearAllFilters() {
    facetKeys.forEach(key => {
      filterState[key] = [];
      storePreference(key, '[]');
    });
    syncUrlState();
    updateGallery();
    renderFacets();
    renderActiveFilters();
  }

  function toggleSidebar() {
    if (!sidebarWrapper) return;
    const isExpanded = sidebarWrapper.classList.toggle('expanded');
    storePreference('sidebarExpanded', isExpanded);

    // Update button title
    if (toggleSidebarBtn) {
      toggleSidebarBtn.title = isExpanded ? 'Collapse filters' : 'Expand filters';
    }
  }

  // --- Intersection Observers ---

  let imageObserver = null;
  let scrollObserver = null;

  function initializeImageObserver() {
    const observerOptions = {
      root: null,
      rootMargin: '0px',
      threshold: 0.1
    };

    imageObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const img = entry.target;
          const src = img.getAttribute('data-src');
          if (src) {
            img.src = src;
            img.classList.remove('lazy-load-image');
            console.log(`Lazy loading image: ${src.substring(0, 50)}...`);
          }
          observer.unobserve(img);
        }
      });
    }, observerOptions);
    console.log("Image lazy load observer initialized.");
  }

  function observeImages(container) {
    if (!imageObserver) return;
    const images = container.querySelectorAll('img.lazy-load-image');
    images.forEach(img => imageObserver.observe(img));
    console.log(`Observing ${images.length} new images for lazy loading.`);
  }

  function initializeInfiniteScrollObserver() {
    if (!infiniteScrollSentinel) {
      console.warn("Infinite scroll sentinel not found.");
      return;
    }

    const observerOptions = {
      root: null,
      rootMargin: '200px',
      threshold: 0
    };

    scrollObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && renderedModelCount < currentFilteredSortedModels.length) {
          console.log("Infinite scroll sentinel intersected, loading next batch.");
          renderNextBatch();
        }
      });
    }, observerOptions);
    console.log("Infinite scroll observer initialized.");
  }

  // --- Initialization ---

  async function initializeGallery() {
    console.log("Initializing gallery...");

    if (!galleryLayout || !modelsGridContainer || !modelsListContainer) {
      console.error("Essential gallery containers not found. Aborting initialization.");
      if (emptyGalleryEl) emptyGalleryEl.textContent = "Error: Gallery failed to initialize (missing elements).";
      return;
    }

    // 1. Parse URL state first (takes precedence)
    parseUrlState();

    // 2. Load preferences for values not in URL
    if (filterState.viewMode === 'grid') {
      filterState.viewMode = getPreference('view', 'grid');
    }
    if (filterState.sortBy === 'name') {
      filterState.sortBy = getPreference('sortBy', 'name');
    }
    if (filterState.sortDir === 'desc') {
      filterState.sortDir = getPreference('sortDir', 'desc');
    }

    const savedSidebarExpanded = getPreference('sidebarExpanded', 'true') === 'true';

    // 3. Set Initial UI State
    handleViewToggle(filterState.viewMode);
    if (sortBySelect) sortBySelect.value = filterState.sortBy;
    if (sortDirectionBtn) {
      sortDirectionBtn.setAttribute('data-direction', filterState.sortDir);
      const svg = sortDirectionBtn.querySelector('svg');
      if (svg) svg.style.transform = filterState.sortDir === 'asc' ? 'rotate(180deg)' : '';
    }
    if (searchInput && filterState.searchText) {
      searchInput.value = filterState.searchText;
    }
    // Set initial sidebar state
    if (sidebarWrapper) {
      if (savedSidebarExpanded) {
        sidebarWrapper.classList.add('expanded');
      } else {
        sidebarWrapper.classList.remove('expanded');
      }
      // Update button title
      if (toggleSidebarBtn) {
        toggleSidebarBtn.title = savedSidebarExpanded ? 'Collapse filters' : 'Expand filters';
      }
    }

    // 4. Get Data from External Script
    if (typeof window.allModelsData !== 'undefined' && Array.isArray(window.allModelsData)) {
      allModelsData = window.allModelsData;
      allModelsData.forEach((model, i) => { model._idx = i; });
      unmatchedData = Array.isArray(window.galleryUnmatched) ? window.galleryUnmatched : [];
      console.log(`Successfully loaded ${allModelsData.length} models from external data script.`);
    } else {
      console.error("External models data (window.allModelsData) not found or not an array.");
      if (emptyGalleryEl) {
        emptyGalleryEl.textContent = "Error: Model data script is missing or invalid.";
        emptyGalleryEl.style.display = 'block';
      }
      modelsGridContainer.innerHTML = '';
      modelsListContainer.innerHTML = '';
      return;
    }

    // 5. Initial Render
    document.addEventListener('click', handleCopyClick, true);
    renderHealthSummary();
    renderUnmatchedPanel();
    if (allModelsData.length > 0) {
      if (emptyGalleryEl) emptyGalleryEl.style.display = 'none';
      renderFacets();
      initializeImageObserver();
      initializeInfiniteScrollObserver();
      updateGallery();
    } else {
      console.log("No models found in data.");
      if (emptyGalleryEl) emptyGalleryEl.style.display = 'block';
      renderFacets();
    }

    // 6. Attach Event Listeners
    gridViewBtn?.addEventListener('click', () => handleViewToggle('grid'));
    focusedViewBtn?.addEventListener('click', () => handleViewToggle('focused'));
    listViewBtn?.addEventListener('click', () => handleViewToggle('list'));
    sortBySelect?.addEventListener('change', handleSortChange);
    sortDirectionBtn?.addEventListener('click', handleSortDirectionToggle);
    searchInput?.addEventListener('input', handleSearchInput);
    clearSearchBtn?.addEventListener('click', handleClearSearch);
    toggleSidebarBtn?.addEventListener('click', toggleSidebar);
    clearAllFiltersBtn?.addEventListener('click', handleClearAllFilters);

    // 7. Handle browser back/forward
    window.addEventListener('popstate', function() {
      parseUrlState();
      handleViewToggle(filterState.viewMode);
      if (sortBySelect) sortBySelect.value = filterState.sortBy;
      if (sortDirectionBtn) {
        sortDirectionBtn.setAttribute('data-direction', filterState.sortDir);
        const svg = sortDirectionBtn.querySelector('svg');
        if (svg) svg.style.transform = filterState.sortDir === 'asc' ? 'rotate(180deg)' : '';
      }
      if (searchInput) searchInput.value = filterState.searchText;
      updateGallery();
      renderFacets();
      renderActiveFilters();
    });

    // 8. Video play/pause functionality (hover for desktop, tap for mobile)
    const isTouchDevice = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);

    function setupVideoHandlers(container) {
      if (!container) return;

      const cardSelector = '.model-card, .model-list-item, .model-focused-item';

      if (isTouchDevice) {
        // Touch devices: tap play button to toggle play/pause
        container.addEventListener('click', function(e) {
          // Only handle clicks on the play button overlay
          const playButton = e.target.closest('.video-play-overlay');
          if (!playButton) return;

          const card = e.target.closest(cardSelector);
          if (!card) return;

          const video = card.querySelector('video');
          if (!video) return;

          e.preventDefault();
          e.stopPropagation();

          if (video.paused) {
            // Pause all other videos first
            container.querySelectorAll(cardSelector + '.playing').forEach(other => {
              if (other !== card) {
                other.classList.remove('playing');
                const otherVideo = other.querySelector('video');
                if (otherVideo) {
                  otherVideo.pause();
                  otherVideo.currentTime = 0;
                }
              }
            });
            video.currentTime = 0;
            video.play().catch(() => {});
            card.classList.add('playing');
          } else {
            video.pause();
            card.classList.remove('playing');
          }
        }, true);
      } else {
        // Desktop: hover to play
        container.addEventListener('mouseenter', function(e) {
          const card = e.target.closest(cardSelector);
          if (!card) return;
          const video = card.querySelector('video');
          if (video) {
            video.currentTime = 0;
            video.play().catch(() => {});
            card.classList.add('playing');
          }
        }, true);

        container.addEventListener('mouseleave', function(e) {
          const card = e.target.closest(cardSelector);
          if (!card) return;
          const video = card.querySelector('video');
          if (video) {
            video.pause();
            video.currentTime = 0;
            card.classList.remove('playing');
          }
        }, true);
      }
    }

    // Setup video handlers for all view containers
    setupVideoHandlers(modelsGridContainer);
    setupVideoHandlers(modelsFocusedContainer);
    setupVideoHandlers(modelsListContainer);

    console.log("Gallery initialization complete.");
  }

  // --- Start Initialization ---
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeGallery);
  } else {
    initializeGallery();
  }

})();
