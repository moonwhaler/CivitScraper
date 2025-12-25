// Gallery functionality with faceted filtering and URL state management
(function() {
  console.log("Gallery functionality script starting");

  // --- Configuration ---
  const DEBOUNCE_DELAY = 300;
  const BATCH_SIZE = 50;
  const PLACEHOLDER_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

  // --- DOM Elements ---
  const galleryContainer = document.querySelector('.gallery-container');
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
  const facetSidebar = document.getElementById('facet-sidebar');
  const toggleSidebarBtn = document.getElementById('toggle-sidebar');
  const closeSidebarBtn = document.getElementById('close-sidebar');
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

  // Multi-filter state
  const filterState = {
    types: [],
    baseModels: [],
    folders: [],
    searchText: '',
    sortBy: 'name',
    sortDir: 'desc',
    viewMode: 'grid',
    multipleVersionsOnly: false
  };

  // Facet metadata for rendering
  const facetConfig = {
    types: { label: 'Model Type', icon: '🏷️', key: 'type' },
    baseModels: { label: 'Base Model', icon: '🧩', key: 'base' },
    folders: { label: 'Folder', icon: '📁', key: 'folder' }
  };

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

    // Parse array parameters
    const typeParam = params.get('type');
    if (typeParam) {
      filterState.types = typeParam.split(',').map(decodeURIComponent).filter(Boolean);
    }

    const baseParam = params.get('base');
    if (baseParam) {
      filterState.baseModels = baseParam.split(',').map(decodeURIComponent).filter(Boolean);
    }

    const folderParam = params.get('folder');
    if (folderParam) {
      filterState.folders = folderParam.split(',').map(decodeURIComponent).filter(Boolean);
    }

    // Parse single value parameters
    const searchParam = params.get('q');
    if (searchParam !== null) {
      filterState.searchText = decodeURIComponent(searchParam);
    }

    const sortParam = params.get('sort');
    if (sortParam && ['name', 'created_at', 'updated_at', 'downloads', 'rating'].includes(sortParam)) {
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

    const multiVersionsParam = params.get('multiVersions');
    if (multiVersionsParam === 'true') {
      filterState.multipleVersionsOnly = true;
    }

    console.log("Parsed URL state:", filterState);
  }

  function syncUrlState() {
    const params = new URLSearchParams();

    if (filterState.types.length > 0) {
      params.set('type', filterState.types.map(encodeURIComponent).join(','));
    }
    if (filterState.baseModels.length > 0) {
      params.set('base', filterState.baseModels.map(encodeURIComponent).join(','));
    }
    if (filterState.folders.length > 0) {
      params.set('folder', filterState.folders.map(encodeURIComponent).join(','));
    }
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
    if (filterState.multipleVersionsOnly) {
      params.set('multiVersions', 'true');
    }

    const hashString = params.toString();
    const newUrl = hashString ? `#${hashString}` : window.location.pathname + window.location.search;

    // Use replaceState to avoid polluting history for every filter change
    window.history.replaceState(null, '', newUrl);
  }

  // --- Facet Count Computation ---

  function computeFacetCounts() {
    const counts = {
      types: new Map(),
      baseModels: new Map(),
      folders: new Map()
    };

    // Initialize all known values with 0 counts
    allModelsData.forEach(model => {
      const type = model.type || 'Unknown';
      const baseModel = model.base_model || 'Unknown';
      const folder = model.folder_name || 'Unknown';

      if (!counts.types.has(type)) counts.types.set(type, 0);
      if (!counts.baseModels.has(baseModel)) counts.baseModels.set(baseModel, 0);
      if (!counts.folders.has(folder)) counts.folders.set(folder, 0);
    });

    // For each facet, compute counts based on OTHER facets' filters
    // This shows "what would be available if I select this value"
    allModelsData.forEach(model => {
      const type = model.type || 'Unknown';
      const baseModel = model.base_model || 'Unknown';
      const folder = model.folder_name || 'Unknown';

      // Check if model passes base model and folder filters (for type counts)
      const passesBaseModelFilter = filterState.baseModels.length === 0 ||
        filterState.baseModels.includes(baseModel);
      const passesFolderFilter = filterState.folders.length === 0 ||
        filterState.folders.includes(folder);
      const passesTypeFilter = filterState.types.length === 0 ||
        filterState.types.includes(type);

      // Check search filter
      const passesSearch = !filterState.searchText || modelMatchesSearch(model, filterState.searchText);

      // Count for types: must pass baseModel, folder, and search filters
      if (passesBaseModelFilter && passesFolderFilter && passesSearch) {
        counts.types.set(type, (counts.types.get(type) || 0) + 1);
      }

      // Count for baseModels: must pass type, folder, and search filters
      if (passesTypeFilter && passesFolderFilter && passesSearch) {
        counts.baseModels.set(baseModel, (counts.baseModels.get(baseModel) || 0) + 1);
      }

      // Count for folders: must pass type, baseModel, and search filters
      if (passesTypeFilter && passesBaseModelFilter && passesSearch) {
        counts.folders.set(folder, (counts.folders.get(folder) || 0) + 1);
      }
    });

    return counts;
  }

  function modelMatchesSearch(model, searchText) {
    if (!searchText) return true;
    const searchLower = searchText.toLowerCase();
    return (
      (model.name || '').toLowerCase().includes(searchLower) ||
      (model.type || '').toLowerCase().includes(searchLower) ||
      (model.base_model || '').toLowerCase().includes(searchLower) ||
      (model.folder_name || '').toLowerCase().includes(searchLower) ||
      (model.description || '').toLowerCase().includes(searchLower)
    );
  }

  // --- Facet Rendering ---

  function renderFacets() {
    if (!facetContainer) return;

    const counts = computeFacetCounts();

    // Count models with multiple local versions
    const multiVersionCount = allModelsData.filter(model =>
      (model.local_version_count || 1) > 1
    ).length;

    let html = '';

    // Add Multiple Local Versions toggle at the top
    if (multiVersionCount > 0) {
      html += `
        <div class="facet-section toggle-section">
          <label class="facet-toggle-item ${filterState.multipleVersionsOnly ? 'active' : ''}">
            <input type="checkbox"
                   id="multiple-versions-toggle"
                   ${filterState.multipleVersionsOnly ? 'checked' : ''}>
            <span class="facet-toggle-switch"></span>
            <span class="facet-toggle-label">
              <span class="facet-icon">📦</span>
              Multiple Local Versions
            </span>
            <span class="facet-count">${multiVersionCount}</span>
          </label>
        </div>
      `;
    }

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

      const isExpanded = sortedEntries.some(([value]) => selectedValues.includes(value)) ||
                         selectedValues.length === 0;

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
    // Multiple versions toggle handler
    const multiVersionsToggle = document.getElementById('multiple-versions-toggle');
    if (multiVersionsToggle) {
      multiVersionsToggle.addEventListener('change', function() {
        filterState.multipleVersionsOnly = this.checked;
        storePreference('multipleVersionsOnly', this.checked ? 'true' : 'false');
        syncUrlState();
        updateGallery();
        renderFacets();
      });
    }

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
      // Skip the multiple versions toggle (handled separately)
      if (checkbox.id === 'multiple-versions-toggle') return;

      checkbox.addEventListener('change', function() {
        const facetKey = this.dataset.facet;
        const value = this.dataset.value;

        toggleFacetValue(facetKey, value, this.checked);
      });
    });
  }

  function updateMultipleVersionsToggle() {
    const toggle = document.getElementById('multiple-versions-toggle');
    if (toggle) {
      toggle.checked = filterState.multipleVersionsOnly;
      const label = toggle.closest('.facet-toggle-item');
      if (label) {
        label.classList.toggle('active', filterState.multipleVersionsOnly);
      }
    }
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

    const hasFilters = filterState.types.length > 0 ||
                       filterState.baseModels.length > 0 ||
                       filterState.folders.length > 0 ||
                       filterState.multipleVersionsOnly;

    let pillsHtml = '';

    // Generate pill for multiple versions filter
    if (filterState.multipleVersionsOnly) {
      pillsHtml += `
        <span class="filter-pill" data-filter="multipleVersions">
          <span class="pill-category">Filter:</span>
          <span class="pill-value">Multiple Local Versions</span>
          <button class="pill-remove" title="Remove filter">×</button>
        </span>
      `;
    }

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

        // Handle special filters
        if (pill.dataset.filter === 'multipleVersions') {
          filterState.multipleVersionsOnly = false;
          updateMultipleVersionsToggle();
          syncUrlState();
          updateGallery();
          renderFacets();
          return;
        }

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

  function renderModelCard(model) {
    const rating = model.stats?.rating ? parseFloat(model.stats.rating).toFixed(1) : '0';
    const ratingCount = model.stats?.rating_count || 0;
    const downloads = model.stats?.downloads || 0;

    return `
      <div class="model-card"
          data-model-id="${escapeHTML(model.model_id)}"
          data-version-id="${escapeHTML(model.version_id)}"
          data-name="${escapeHTML(model.name?.toLowerCase())}"
          data-type="${escapeHTML(model.type?.toLowerCase())}"
          data-base-model="${escapeHTML(model.base_model?.toLowerCase())}"
          data-folder-name="${escapeHTML(model.folder_name?.toLowerCase())}"
          data-description="${escapeHTML(model.description?.toLowerCase())}"
          data-created-at="${escapeHTML(model.created_at || '')}"
          data-updated-at="${escapeHTML(model.updated_at || '')}"
          data-downloads="${downloads}"
          data-rating="${rating}">
          <a href="${model.html_path}" class="model-link">
              ${model.preview_image_path
                  ? `<div class="model-preview">
                      ${model.is_video
                          ? `<video src="${model.preview_image_path}" preload="metadata" class="preview-video" muted loop playsinline></video><div class="video-indicator">VIDEO</div><div class="video-play-overlay"><svg class="play-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><svg class="pause-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg></div>`
                          : `<img src="${PLACEHOLDER_IMAGE}" data-src="${model.preview_image_path}" alt="${escapeHTML(model.name)}" class="lazy-load-image">`
                      }
                    </div>`
                  : `<div class="model-preview no-image"><div class="no-image-text">No Preview</div></div>`
              }
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
      </div>`;
  }

  function renderModelFocusedItem(model) {
    return `
      <div class="model-focused-item"
          data-model-id="${escapeHTML(model.model_id)}"
          data-name="${escapeHTML(model.name?.toLowerCase())}">
          <a href="${model.html_path}" class="model-link">
              ${model.preview_image_path
                  ? `<div class="focused-preview">
                      ${model.is_video
                          ? `<video src="${model.preview_image_path}" preload="metadata" class="preview-video" muted loop playsinline></video><div class="video-indicator">VIDEO</div><div class="video-play-overlay"><svg class="play-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><svg class="pause-icon" xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg></div>`
                          : `<img src="${PLACEHOLDER_IMAGE}" data-src="${model.preview_image_path}" alt="${escapeHTML(model.name)}" class="lazy-load-image">`
                      }
                    </div>`
                  : `<div class="focused-preview no-image"></div>`
              }
              <div class="focused-overlay">
                  <h3 class="focused-name">${escapeHTML(model.name)}</h3>
              </div>
          </a>
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
          data-description="${escapeHTML(model.description?.toLowerCase())}"
          data-created-at="${escapeHTML(model.created_at || '')}"
          data-updated-at="${escapeHTML(model.updated_at || '')}"
          data-downloads="${downloads}"
          data-rating="${rating}">
          <a href="${model.html_path}" class="model-link">
              <div class="model-list-preview">
                  ${model.preview_image_path
                      ? `${model.is_video
                          ? `<video src="${model.preview_image_path}" preload="metadata" class="preview-video" muted loop playsinline></video><div class="video-indicator mini">VIDEO</div><div class="video-play-overlay mini"><svg class="play-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg><svg class="pause-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg></div>`
                          : `<img src="${PLACEHOLDER_IMAGE}" data-src="${model.preview_image_path}" alt="${escapeHTML(model.name)}" class="lazy-load-image">`
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

    // 1. Apply Type Filter (AND with other facets)
    if (filterState.types.length > 0) {
      filteredModels = filteredModels.filter(model => {
        const modelType = model.type || 'Unknown';
        return filterState.types.includes(modelType);
      });
    }

    // 2. Apply Base Model Filter (AND with other facets)
    if (filterState.baseModels.length > 0) {
      filteredModels = filteredModels.filter(model => {
        const modelBase = model.base_model || 'Unknown';
        return filterState.baseModels.includes(modelBase);
      });
    }

    // 3. Apply Folder Filter (AND with other facets)
    if (filterState.folders.length > 0) {
      filteredModels = filteredModels.filter(model => {
        const modelFolder = model.folder_name || 'Unknown';
        return filterState.folders.includes(modelFolder);
      });
    }

    // 4. Apply Search Filter
    if (filterState.searchText) {
      filteredModels = filteredModels.filter(model =>
        modelMatchesSearch(model, filterState.searchText)
      );
    }

    // 5. Apply Multiple Local Versions Filter
    if (filterState.multipleVersionsOnly) {
      filteredModels = filteredModels.filter(model =>
        (model.local_version_count || 1) > 1
      );
    }

    // 6. Apply Sorting
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
    filterState.types = [];
    filterState.baseModels = [];
    filterState.folders = [];
    filterState.multipleVersionsOnly = false;
    syncUrlState();
    storePreference('types', '[]');
    storePreference('baseModels', '[]');
    storePreference('folders', '[]');
    storePreference('multipleVersionsOnly', 'false');
    updateMultipleVersionsToggle();
    updateGallery();
    renderFacets();
    renderActiveFilters();
  }

  function toggleSidebar() {
    const isVisible = facetSidebar.classList.toggle('visible');
    storePreference('sidebarVisible', isVisible);
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

    if (!galleryContainer || !modelsGridContainer || !modelsListContainer) {
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

    const savedSidebarVisible = getPreference('sidebarVisible', 'true') === 'true';

    // 3. Set Initial UI State
    handleViewToggle(filterState.viewMode);
    sortBySelect.value = filterState.sortBy;
    sortDirectionBtn.setAttribute('data-direction', filterState.sortDir);
    sortDirectionBtn.querySelector('svg').style.transform = filterState.sortDir === 'asc' ? 'rotate(180deg)' : '';
    if (searchInput && filterState.searchText) {
      searchInput.value = filterState.searchText;
    }
    if (savedSidebarVisible && facetSidebar) {
      facetSidebar.classList.add('visible');
    }

    // 4. Get Data from External Script
    if (typeof window.allModelsData !== 'undefined' && Array.isArray(window.allModelsData)) {
      allModelsData = window.allModelsData;
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
    closeSidebarBtn?.addEventListener('click', toggleSidebar);
    clearAllFiltersBtn?.addEventListener('click', handleClearAllFilters);

    // 7. Handle browser back/forward
    window.addEventListener('popstate', function() {
      parseUrlState();
      handleViewToggle(filterState.viewMode);
      sortBySelect.value = filterState.sortBy;
      sortDirectionBtn.setAttribute('data-direction', filterState.sortDir);
      sortDirectionBtn.querySelector('svg').style.transform = filterState.sortDir === 'asc' ? 'rotate(180deg)' : '';
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
