// Immediately executing function for gallery functionality
(function() {
  console.log("Gallery functionality script starting");

  // --- Configuration ---
  const DEBOUNCE_DELAY = 300; // ms for search input
  const BATCH_SIZE = 50; // Number of models to render per batch
  const PLACEHOLDER_IMAGE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"; // 1x1 transparent pixel

  // --- DOM Elements ---
  const galleryContainer = document.querySelector('.gallery-container');
  const gridViewBtn = document.getElementById('grid-view');
  const listViewBtn = document.getElementById('list-view');
  const modelsGridContainer = document.querySelector('.models-grid');
  const modelsListContainer = document.querySelector('.models-list');
  const searchInput = document.getElementById('gallery-search');
  const clearSearchBtn = document.getElementById('clear-search');
  const sortBySelect = document.getElementById('sort-by');
  const sortDirectionBtn = document.getElementById('sort-direction');
  const noResultsEl = document.getElementById('no-results');
  const emptyGalleryEl = document.querySelector('.empty-gallery');
  const directoryTree = document.getElementById('directory-tree');
  const toggleDirectoryTreeBtn = document.getElementById('toggle-directory-tree');
  const closeDirectoryTreeBtn = document.getElementById('close-directory-tree');
  const directoryTreeContent = document.querySelector('.directory-tree-content');
  const infiniteScrollSentinel = document.getElementById('infinite-scroll-sentinel'); // Added sentinel

  // --- State ---
  let allModelsData = []; // Holds the raw data fetched from JSON
  let currentFilteredSortedModels = []; // Holds the currently filtered and sorted list
  let renderedModelCount = 0; // Tracks how many models have been rendered
  let currentSortBy = 'name';
  let currentSortDir = 'desc';
  let currentSearchText = '';
  let currentFilterType = null;
  let currentFilterValue = null;
  let currentViewMode = 'grid'; // 'grid' or 'list'

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
    // Ensure proper escaping for HTML attributes and content
    return String(str).replace(/[&<>"']/g, function (match) {
      return {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;' // Keep single quote escaped as it's often used in attributes
      }[match];
    });
  }

  function formatDate(dateString) {
      if (!dateString) return '';
      try {
          const date = new Date(dateString);
          if (isNaN(date.getTime())) return dateString; // Return original if invalid
          return date.toISOString().split('T')[0]; // YYYY-MM-DD
      } catch (e) {
          console.warn('Error formatting date:', dateString, e);
          return dateString; // Return original on error
      }
  }

  // --- Rendering Functions ---

  // Renamed from renderGallery, now renders a specific batch and appends
  function renderBatch(modelsToRender) {
    console.log(`Rendering batch of ${modelsToRender.length} models`);

    if (modelsToRender.length === 0) {
        // This case should ideally be handled by updateGallery before calling renderBatch
        console.warn("renderBatch called with empty array");
        return;
    }

    // Use DocumentFragment for performance
    const gridFragment = document.createDocumentFragment();
    const listFragment = document.createDocumentFragment();

    modelsToRender.forEach(model => {
      const cardHTML = renderModelCard(model);
      const itemHTML = renderModelListItem(model);

      // Create elements from HTML strings
      const cardTemplate = document.createElement('template');
      cardTemplate.innerHTML = cardHTML.trim();
      gridFragment.appendChild(cardTemplate.content.firstChild);

      const itemTemplate = document.createElement('template');
      itemTemplate.innerHTML = itemHTML.trim();
      listFragment.appendChild(itemTemplate.content.firstChild);
    });

    // Apply highlighting if needed to the newly added elements *within the fragments*
    if (currentSearchText) {
        highlightTextInContainer(gridFragment, currentSearchText); // Highlight within the fragment
        highlightTextInContainer(listFragment, currentSearchText); // Highlight within the fragment
    }

    // Append the fragments to the DOM
    modelsGridContainer.appendChild(gridFragment);
    modelsListContainer.appendChild(listFragment);

    // Observe newly added images for lazy loading *after* they are in the DOM
    observeImages(modelsGridContainer); // Re-check container for new images
    observeImages(modelsListContainer); // Re-check container for new images

    console.log(`Appended batch of ${modelsToRender.length} models.`);
  }

  function renderModelCard(model) {
    const rating = model.stats?.rating ? parseFloat(model.stats.rating).toFixed(1) : '0';
    const ratingCount = model.stats?.rating_count || 0;
    const downloads = model.stats?.downloads || 0;

    // Basic structure, escaping user-generated content like names, descriptions
    // Paths are assumed safe as they are generated by the script or from API
    return `
      <div class="model-card"
          data-model-id="${escapeHTML(model.model_id)}"
          data-version-id="${escapeHTML(model.version_id)}"
          data-name="${escapeHTML(model.name?.toLowerCase())}"
          data-type="${escapeHTML(model.type?.toLowerCase())}"
          data-base-model="${escapeHTML(model.base_model?.toLowerCase())}"
          data-description="${escapeHTML(model.description?.toLowerCase())}"
          data-created-at="${escapeHTML(model.created_at || '')}"
          data-updated-at="${escapeHTML(model.updated_at || '')}"
          data-downloads="${downloads}"
          data-rating="${rating}">
          <a href="${model.html_path}" class="model-link">
              ${model.preview_image_path
                  ? `<div class="model-preview">
                      ${model.is_video
                          ? `<video src="${model.preview_image_path}" preload="metadata" class="preview-video" controls muted loop playsinline></video><div class="video-indicator">VIDEO</div>`
                          // Use placeholder, data-src, and lazy-load class for images
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
                          <span class="stat-value">${downloads}</span>
                      </span>` : ''}
                      ${parseFloat(rating) > 0 ? `
                      <span class="stat-item rating" title="Rating">
                          <span class="stat-icon">⭐</span>
                          <span class="stat-value">${rating}</span>
                          ${ratingCount > 0 ? `<span class="stat-count">(${ratingCount})</span>` : ''}
                      </span>` : ''}
                  </div>
                  ${model.version ? `<div class="model-version">v${escapeHTML(model.version)}</div>` : ''}
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
          data-description="${escapeHTML(model.description?.toLowerCase())}"
          data-created-at="${escapeHTML(model.created_at || '')}"
          data-updated-at="${escapeHTML(model.updated_at || '')}"
          data-downloads="${downloads}"
          data-rating="${rating}">
          <a href="${model.html_path}" class="model-link">
              <div class="model-list-preview">
                  ${model.preview_image_path
                      ? `${model.is_video
                          ? `<video src="${model.preview_image_path}" preload="metadata" class="preview-video"></video><div class="video-indicator mini">VIDEO</div>`
                          // Use placeholder, data-src, and lazy-load class for images
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
                      <span class="stat-value">${downloads}</span>
                  </span>` : ''}
                  ${parseFloat(rating) > 0 ? `
                  <span class="stat-item rating" title="Rating">
                      <span class="stat-icon">⭐</span>
                      <span class="stat-value">${rating}</span>
                      ${ratingCount > 0 ? `<span class="stat-count">(${ratingCount})</span>` : ''}
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

  // Removed the old renderGallery function as its logic is now in renderBatch and updateGallery

  function renderNextBatch() {
    console.log(`Attempting to render next batch. Rendered: ${renderedModelCount}, Total: ${currentFilteredSortedModels.length}`);
    if (renderedModelCount >= currentFilteredSortedModels.length) {
      console.log("All models rendered.");
      // Optionally hide sentinel or disconnect observer here if needed
      return; // All models are rendered
    }

    const nextBatch = currentFilteredSortedModels.slice(renderedModelCount, renderedModelCount + BATCH_SIZE);
    if (nextBatch.length > 0) {
      renderBatch(nextBatch);
      renderedModelCount += nextBatch.length;
    } else {
      console.log("No more models in the next batch slice.");
    }

    // Re-check if all models are now rendered after this batch
    if (renderedModelCount >= currentFilteredSortedModels.length) {
        console.log("All models have been rendered after this batch.");
        // Disconnect scroll observer if all models are loaded
        if (scrollObserver && infiniteScrollSentinel) {
            scrollObserver.unobserve(infiniteScrollSentinel);
            console.log("Infinite scroll observer disconnected.");
        }
    }
  }


  // --- Data Processing Functions ---

  function filterAndSortModels() {
    let filteredModels = [...allModelsData]; // Start with all models

    // 1. Apply Directory Filter
    if (currentFilterType && currentFilterValue) {
      filteredModels = filteredModels.filter(model => {
        const modelValue = model[currentFilterType === 'base-model' ? 'base_model' : 'type'] || '';
        return modelValue.toLowerCase() === currentFilterValue;
      });
    }

    // 2. Apply Search Filter
    if (currentSearchText) {
      const searchLower = currentSearchText.toLowerCase();
      filteredModels = filteredModels.filter(model =>
        (model.name || '').toLowerCase().includes(searchLower) ||
        (model.type || '').toLowerCase().includes(searchLower) ||
        (model.base_model || '').toLowerCase().includes(searchLower) ||
        (model.description || '').toLowerCase().includes(searchLower)
      );
    }

    // 3. Apply Sorting
    const multiplier = currentSortDir === 'asc' ? 1 : -1;
    filteredModels.sort((a, b) => {
      let valueA, valueB;

      switch (currentSortBy) {
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
          valueA = a[currentSortBy] ? new Date(a[currentSortBy]).getTime() : 0;
          valueB = b[currentSortBy] ? new Date(b[currentSortBy]).getTime() : 0;
          break;
        default:
          return 0; // Should not happen
      }

      if (valueA === valueB) {
        // Secondary sort by name if primary values are equal
        return (a.name || '').localeCompare(b.name || '');
      }
      return multiplier * (valueA - valueB);
    });

    return filteredModels;
  }

  function updateGallery() {
    // 1. Filter and sort the entire dataset
    currentFilteredSortedModels = filterAndSortModels();
    console.log(`Updating gallery. Found ${currentFilteredSortedModels.length} models after filtering/sorting.`);

    // 2. Clear existing content from containers
    modelsGridContainer.innerHTML = '';
    modelsListContainer.innerHTML = '';
    renderedModelCount = 0; // Reset rendered count

    // 3. Handle empty results
    if (currentFilteredSortedModels.length === 0) {
      noResultsEl.style.display = 'block';
      // Disconnect scroll observer if no results
      if (scrollObserver && infiniteScrollSentinel) {
          scrollObserver.unobserve(infiniteScrollSentinel);
          console.log("Infinite scroll observer disconnected (no results).");
      }
      return;
    } else {
      noResultsEl.style.display = 'none';
    }

    // 4. Render the first batch
    renderNextBatch();

    // 5. Ensure the infinite scroll observer is watching the sentinel
    // (It might have been disconnected if previous state had 0 results or all items loaded)
    if (scrollObserver && infiniteScrollSentinel && renderedModelCount < currentFilteredSortedModels.length) {
        scrollObserver.observe(infiniteScrollSentinel);
        console.log("Infinite scroll observer (re)activated.");
    }
  }


  // --- Highlighting ---
  function highlightText(element, searchText) {
      if (!searchText.trim()) return;

      const allTextNodes = [];
      const walker = document.createTreeWalker(
          element,
          NodeFilter.SHOW_TEXT,
          // Filter out empty/whitespace nodes and nodes already inside a highlight
          { acceptNode: node => (node.nodeValue.trim() && !node.parentNode.closest('.highlight')) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT },
          false
      );

      let node;
      while (node = walker.nextNode()) {
          allTextNodes.push(node);
      }

      // Escape regex special characters in search text
      const escapedSearchText = searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const regex = new RegExp(`(${escapedSearchText})`, 'gi');

      allTextNodes.forEach(textNode => {
          const parent = textNode.parentNode;
          // Avoid highlighting inside script/style tags or links
          if (parent.nodeName === 'SCRIPT' || parent.nodeName === 'STYLE' || parent.nodeName === 'A') return;

          const matches = textNode.nodeValue.match(regex);
          if (!matches) return;

          const fragment = document.createDocumentFragment();
          const parts = textNode.nodeValue.split(regex);

          parts.forEach((part, i) => {
              if (i % 2 === 0) {
                  // Regular text
                  if (part) fragment.appendChild(document.createTextNode(part));
              } else {
                  // Matched text to highlight
                  const highlightSpan = document.createElement('span');
                  highlightSpan.className = 'highlight';
                  highlightSpan.textContent = part; // Use textContent for safety
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
              parent.normalize(); // Combine adjacent text nodes
          }
      });
  }

  // Combined highlightSearchResults function
  function highlightSearchResults(searchText, container = document) {
      // If container is document, remove highlights globally first
      if (container === document) {
          removeHighlights(modelsGridContainer);
          removeHighlights(modelsListContainer);
      }

      if (!searchText.trim()) return;

      // Apply highlights to the elements within the specified container (could be document or a fragment)
      highlightTextInContainer(container, searchText);
  }

  // Helper function to apply highlightText to relevant elements within a container
  function highlightTextInContainer(container, searchText) {
      // Select both potential elements within the container
      container.querySelectorAll('.model-card .model-info, .model-list-item .model-list-info').forEach(infoElement => {
          highlightText(infoElement, searchText);
      });
  }



  // --- Event Handlers ---

  function handleViewToggle(mode) {
    console.log(`Setting view mode to: ${mode}`);
    currentViewMode = mode;
    if (mode === 'grid') {
      modelsGridContainer.classList.add('view-active');
      modelsListContainer.classList.remove('view-active');
      gridViewBtn.classList.add('active');
      listViewBtn.classList.remove('active');
    } else {
      modelsListContainer.classList.add('view-active');
      modelsGridContainer.classList.remove('view-active');
      listViewBtn.classList.add('active');
      gridViewBtn.classList.remove('active');
    }
    storePreference('view', mode);
  }

  function handleSortChange() {
    currentSortBy = sortBySelect.value;
    storePreference('sortBy', currentSortBy);
    console.log("Sort by changed:", currentSortBy);
    updateGallery();
  }

  function handleSortDirectionToggle() {
    currentSortDir = currentSortDir === 'desc' ? 'asc' : 'desc';
    sortDirectionBtn.setAttribute('data-direction', currentSortDir);
    sortDirectionBtn.querySelector('svg').style.transform = currentSortDir === 'asc' ? 'rotate(180deg)' : '';
    storePreference('sortDir', currentSortDir);
    console.log("Sort direction changed:", currentSortDir);
    updateGallery();
  }

  let searchDebounceTimeout;
  function handleSearchInput() {
      clearTimeout(searchDebounceTimeout);
      searchDebounceTimeout = setTimeout(() => {
          currentSearchText = searchInput.value.trim();
          console.log("Searching for:", currentSearchText);
          // Reset directory filter when searching
          currentFilterType = null;
          currentFilterValue = null;
          setActiveDirectoryItem(null); // Visually reset tree selection
          updateGallery(); // This will re-render and apply highlights
      }, DEBOUNCE_DELAY);
  }

  function handleClearSearch() {
    searchInput.value = '';
    currentSearchText = '';
    searchInput.focus();
    // Reset directory filter as well? Maybe not, user might want to clear search within a category.
    // Let's keep the directory filter active if set.
    updateGallery();
  }

  function handleDirectoryFilter(filterType, filterValue, targetElement) {
      console.log(`Filtering by ${filterType}: ${filterValue}`);
      currentFilterType = filterType;
      currentFilterValue = filterValue;
      currentSearchText = ''; // Clear search when applying directory filter
      searchInput.value = '';
      setActiveDirectoryItem(targetElement);
      updateGallery();
  }

  function handleDirectoryReset(targetElement) {
      console.log("Resetting directory filters");
      currentFilterType = null;
      currentFilterValue = null;
      currentSearchText = ''; // Clear search as well
      searchInput.value = '';
      setActiveDirectoryItem(targetElement);
      updateGallery();
  }

  function setActiveDirectoryItem(activeElement) {
      // Remove active class from all headers and items
      directoryTree.querySelectorAll('.directory-category-header, .directory-item').forEach(el => el.classList.remove('active'));
      // Add active class to the clicked element
      if (activeElement) {
          activeElement.classList.add('active');
      }
  }

  function toggleDirectoryTree() {
      const isVisible = directoryTree.classList.toggle('visible');
      storePreference('directoryTreeVisible', isVisible);
  }

  // --- Directory Tree Generation ---
  function generateDirectoryTree() {
      if (!directoryTreeContent || allModelsData.length === 0) {
          console.warn("Directory tree content area not found or no model data.");
          return;
      }

      const modelTypes = new Map();
      const baseModels = new Map();

      allModelsData.forEach(model => {
          const type = model.type || 'Unknown';
          const baseModel = model.base_model || 'Unknown';

          modelTypes.set(type, (modelTypes.get(type) || 0) + 1);
          baseModels.set(baseModel, (baseModels.get(baseModel) || 0) + 1);
      });

      // Sort categories alphabetically
      const sortedTypes = Array.from(modelTypes.entries()).sort((a, b) => a[0].localeCompare(b[0]));
      const sortedBaseModels = Array.from(baseModels.entries()).sort((a, b) => a[0].localeCompare(b[0]));

      const treeHtml = `
          <div class="directory-category">
              <div class="directory-category-header active" data-category="all">
                  <span class="directory-icon">📂</span>
                  <span class="directory-label">All Models</span>
                  <span class="directory-count">${allModelsData.length}</span>
              </div>
          </div>

          <div class="directory-category">
              <div class="directory-category-header" data-category="type">
                  <span class="directory-icon">📂</span>
                  <span class="directory-label">By Type</span>
                  <span class="directory-toggle">+</span>
              </div>
              <div class="directory-items" style="display: none;">
                  ${sortedTypes.map(([type, count]) => `
                      <div class="directory-item" data-filter-type="type" data-filter-value="${escapeHTML(type.toLowerCase())}">
                          <span class="directory-icon">🏷️</span>
                          <span class="directory-label">${escapeHTML(type)}</span>
                          <span class="directory-count">${count}</span>
                      </div>`).join('')}
              </div>
          </div>

          <div class="directory-category">
              <div class="directory-category-header" data-category="base-model">
                  <span class="directory-icon">📂</span>
                  <span class="directory-label">By Base Model</span>
                  <span class="directory-toggle">+</span>
              </div>
              <div class="directory-items" style="display: none;">
                  ${sortedBaseModels.map(([baseModel, count]) => `
                      <div class="directory-item" data-filter-type="base-model" data-filter-value="${escapeHTML(baseModel.toLowerCase())}">
                          <span class="directory-icon">🧩</span>
                          <span class="directory-label">${escapeHTML(baseModel)}</span>
                          <span class="directory-count">${count}</span>
                      </div>`).join('')}
              </div>
          </div>
      `;

      directoryTreeContent.innerHTML = treeHtml;

      // Add event listeners after generating HTML
      directoryTreeContent.querySelectorAll('.directory-category-header').forEach(header => {
          header.addEventListener('click', function() {
              const category = this.getAttribute('data-category');
              if (category === 'all') {
                  handleDirectoryReset(this);
              } else {
                  const itemsContainer = this.nextElementSibling;
                  const isExpanded = itemsContainer.style.display !== 'none';
                  this.querySelector('.directory-toggle').textContent = isExpanded ? '+' : '-';
                  itemsContainer.style.display = isExpanded ? 'none' : 'block';
              }
          });
      });

      directoryTreeContent.querySelectorAll('.directory-item').forEach(item => {
          item.addEventListener('click', function(e) {
              e.stopPropagation();
              const filterType = this.getAttribute('data-filter-type');
              const filterValue = this.getAttribute('data-filter-value');
              handleDirectoryFilter(filterType, filterValue, this);
          });
      });
      console.log("Directory tree generated");
  }


  // --- Intersection Observers ---
  let imageObserver = null;
  let scrollObserver = null;

  function initializeImageObserver() {
    const observerOptions = {
      root: null, // Use the viewport
      rootMargin: '0px',
      threshold: 0.1 // Trigger when 10% of the image is visible
    };

    imageObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const img = entry.target;
          const src = img.getAttribute('data-src');
          if (src) {
            img.src = src;
            img.classList.remove('lazy-load-image'); // Optional: remove class after loading
            console.log(`Lazy loading image: ${src.substring(0, 50)}...`);
          }
          observer.unobserve(img); // Stop observing once loaded
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
          root: null, // Use the viewport
          rootMargin: '200px', // Load next batch when sentinel is 200px away from viewport bottom
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

    // Check for essential elements
    if (!galleryContainer || !modelsGridContainer || !modelsListContainer) {
        console.error("Essential gallery containers not found. Aborting initialization.");
        if (emptyGalleryEl) emptyGalleryEl.textContent = "Error: Gallery failed to initialize (missing elements).";
        return;
    }

    // 1. Load Preferences
    currentViewMode = getPreference('view', 'grid');
    currentSortBy = getPreference('sortBy', 'name');
    currentSortDir = getPreference('sortDir', 'desc');
    const savedDirectoryTreeVisible = getPreference('directoryTreeVisible', 'false') === 'true';

    // 2. Set Initial UI State from Preferences
    handleViewToggle(currentViewMode); // Set initial view
    sortBySelect.value = currentSortBy;
    sortDirectionBtn.setAttribute('data-direction', currentSortDir);
    sortDirectionBtn.querySelector('svg').style.transform = currentSortDir === 'asc' ? 'rotate(180deg)' : '';
    if (savedDirectoryTreeVisible) {
        directoryTree.classList.add('visible');
    }

    // 3. Get Data from External Script (Global Scope)
    if (typeof window.allModelsData !== 'undefined' && Array.isArray(window.allModelsData)) {
        // Assign the global data to the local variable within the IIFE scope
        allModelsData = window.allModelsData; // Assign global to local
        console.log(`Successfully loaded ${allModelsData.length} models from external data script.`);
        // Optional: Clean up global scope if desired
        // try { delete window.allModelsData; } catch(e) {}
    } else {
        console.error("External models data (window.allModelsData) not found or not an array.");
        if (emptyGalleryEl) {
            emptyGalleryEl.textContent = "Error: Model data script is missing or invalid.";
            emptyGalleryEl.style.display = 'block';
        }
        modelsGridContainer.innerHTML = '';
        modelsListContainer.innerHTML = '';
        return; // Stop initialization if data is missing
    }

    // 4. Initial Render & Tree Generation (only if data loaded)
    if (allModelsData.length > 0) {
        if (emptyGalleryEl) emptyGalleryEl.style.display = 'none';
        generateDirectoryTree();
        initializeImageObserver(); // Init image observer
        initializeInfiniteScrollObserver(); // Init scroll observer
        updateGallery(); // Perform initial filter, sort, and render first batch
        // Start observing the sentinel *after* the first batch is potentially rendered
        // updateGallery ensures observer is started if needed
    } else {
        console.log("No models found in data.");
        if (emptyGalleryEl) emptyGalleryEl.style.display = 'block';
        generateDirectoryTree(); // Generate tree even if empty, shows categories
    }

    // 5. Attach Event Listeners
    gridViewBtn?.addEventListener('click', () => handleViewToggle('grid'));
    listViewBtn?.addEventListener('click', () => handleViewToggle('list'));
    sortBySelect?.addEventListener('change', handleSortChange);
    sortDirectionBtn?.addEventListener('click', handleSortDirectionToggle);
    searchInput?.addEventListener('input', handleSearchInput);
    clearSearchBtn?.addEventListener('click', handleClearSearch);
    toggleDirectoryTreeBtn?.addEventListener('click', toggleDirectoryTree);
    closeDirectoryTreeBtn?.addEventListener('click', toggleDirectoryTree);

    console.log("Gallery initialization complete.");
  }

  // --- Start Initialization ---
  // Use DOMContentLoaded to ensure the DOM is ready, although script is likely at end of body
  if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initializeGallery);
  } else {
      initializeGallery();
  }

})();
