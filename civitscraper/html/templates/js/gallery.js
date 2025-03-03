// Gallery page functionality
document.addEventListener('DOMContentLoaded', function() {
    // Store DOM elements
    const searchInput = document.getElementById('gallery-search');
    const clearSearchBtn = document.getElementById('clear-search');
    const gridViewBtn = document.getElementById('grid-view');
    const listViewBtn = document.getElementById('list-view');
    const sortBySelect = document.getElementById('sort-by');
    const sortDirectionBtn = document.getElementById('sort-direction');
    const noResultsEl = document.getElementById('no-results');
    const modelsGrid = document.querySelector('.models-grid');
    const modelsList = document.querySelector('.models-list');

    // Get all model elements (cards and list items)
    const modelCards = document.querySelectorAll('.model-card');
    const modelListItems = document.querySelectorAll('.model-list-item');

    // Initialize the gallery components
    initViewToggle();
    initSearchFunctionality();
    initSortingFunctionality();
    formatDates();

    /**
     * Initialize view toggle functionality between grid and list views
     */
    function initViewToggle() {
        // Store user preferences in localStorage if available
        const storePreference = (key, value) => {
            try {
                localStorage.setItem('gallery_' + key, value);
            } catch (e) {
                console.warn('localStorage not available:', e);
            }
        };

        const getPreference = (key, defaultValue) => {
            try {
                const value = localStorage.getItem('gallery_' + key);
                return value !== null ? value : defaultValue;
            } catch (e) {
                console.warn('localStorage not available:', e);
                return defaultValue;
            }
        };

        // Load saved preferences
        const savedView = getPreference('view', 'grid');
        const savedSortBy = getPreference('sortBy', 'name');
        const savedSortDir = getPreference('sortDir', 'desc');

        // Initialize with saved preferences
        if (savedView === 'list') {
            setViewMode('list');
        }
        sortBySelect.value = savedSortBy;
        sortDirectionBtn.setAttribute('data-direction', savedSortDir);
        if (savedSortDir === 'asc') {
            sortDirectionBtn.querySelector('svg').style.transform = 'rotate(180deg)';
        }

        // Apply initial sorting
        sortModels(savedSortBy, savedSortDir);

        // View toggle functionality
        function setViewMode(mode) {
            if (mode === 'grid') {
                modelsGrid.classList.add('view-active');
                modelsList.classList.remove('view-active');
                gridViewBtn.classList.add('active');
                listViewBtn.classList.remove('active');
                storePreference('view', 'grid');
            } else {
                modelsList.classList.add('view-active');
                modelsGrid.classList.remove('view-active');
                listViewBtn.classList.add('active');
                gridViewBtn.classList.remove('active');
                storePreference('view', 'list');
            }
        }

        // Attach event listeners
        gridViewBtn.addEventListener('click', () => setViewMode('grid'));
        listViewBtn.addEventListener('click', () => setViewMode('list'));
    }

    /**
     * Initialize search functionality for models
     */
    function initSearchFunctionality() {
        let debounceTimeout;

        function debounce(fn, delay) {
            return function(...args) {
                clearTimeout(debounceTimeout);
                debounceTimeout = setTimeout(() => fn.apply(this, args), delay);
            };
        }

        function escapeRegExp(string) {
            return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        }

        function highlightText(element, searchText) {
            if (!searchText.trim()) return;

            const allTextNodes = [];
            const walker = document.createTreeWalker(
                element,
                NodeFilter.SHOW_TEXT,
                { acceptNode: node => node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT },
                false
            );

            let node;
            while (node = walker.nextNode()) {
                allTextNodes.push(node);
            }

            const regex = new RegExp(`(${escapeRegExp(searchText)})`, 'gi');
            allTextNodes.forEach(textNode => {
                const parent = textNode.parentNode;
                if (parent.nodeName === 'SCRIPT' || parent.closest('.highlight')) return;

                const matches = textNode.nodeValue.match(regex);
                if (!matches) return;

                const fragment = document.createDocumentFragment();
                const parts = textNode.nodeValue.split(regex);

                parts.forEach((part, i) => {
                    if (i % 2 === 0) {
                        // Regular text
                        fragment.appendChild(document.createTextNode(part));
                    } else {
                        // Matched text to highlight
                        const highlightSpan = document.createElement('span');
                        highlightSpan.className = 'highlight';
                        highlightSpan.appendChild(document.createTextNode(part));
                        fragment.appendChild(highlightSpan);
                    }
                });

                parent.replaceChild(fragment, textNode);
            });
        }

        function removeHighlights(element) {
            const highlights = element.querySelectorAll('.highlight');
            highlights.forEach(highlight => {
                const parent = highlight.parentNode;
                const textNode = document.createTextNode(highlight.textContent);
                parent.replaceChild(textNode, highlight);
                parent.normalize(); // Combine adjacent text nodes
            });
        }

        function searchModels(searchText) {
            searchText = searchText.trim().toLowerCase();
            let matchCount = 0;

            // Process all model cards
            modelCards.forEach(card => {
                removeHighlights(card);

                const name = card.dataset.name || '';
                const type = card.dataset.type || '';
                const baseModel = card.dataset.baseModel || '';
                const description = card.dataset.description || '';

                const isMatch = !searchText ||
                    name.includes(searchText) ||
                    type.includes(searchText) ||
                    baseModel.includes(searchText) ||
                    description.includes(searchText);

                card.style.display = isMatch ? '' : 'none';

                if (isMatch) {
                    matchCount++;
                    highlightText(card, searchText);
                }
            });

            // Process all model list items
            modelListItems.forEach(item => {
                removeHighlights(item);

                const name = item.dataset.name || '';
                const type = item.dataset.type || '';
                const baseModel = item.dataset.baseModel || '';
                const description = item.dataset.description || '';

                const isMatch = !searchText ||
                    name.includes(searchText) ||
                    type.includes(searchText) ||
                    baseModel.includes(searchText) ||
                    description.includes(searchText);

                item.style.display = isMatch ? '' : 'none';

                if (isMatch) {
                    highlightText(item, searchText);
                }
            });

            // Show/hide no results message
            noResultsEl.style.display = matchCount === 0 ? 'block' : 'none';

            return matchCount;
        }

        const debouncedSearch = debounce(searchModels, 300);

        // Attach event listeners
        searchInput.addEventListener('input', function() {
            debouncedSearch(this.value);
        });

        clearSearchBtn.addEventListener('click', function() {
            searchInput.value = '';
            searchModels('');
            searchInput.focus();
        });
    }

    /**
     * Initialize sorting functionality for models
     */
    function initSortingFunctionality() {
        // Store preferences function is defined in initViewToggle
        const storePreference = (key, value) => {
            try {
                localStorage.setItem('gallery_' + key, value);
            } catch (e) {
                console.warn('localStorage not available:', e);
            }
        };

        // Attach event listeners
        sortBySelect.addEventListener('change', function() {
            const sortBy = this.value;
            const direction = sortDirectionBtn.getAttribute('data-direction');
            sortModels(sortBy, direction);
        });

        sortDirectionBtn.addEventListener('click', function() {
            const currentDirection = this.getAttribute('data-direction');
            const newDirection = currentDirection === 'desc' ? 'asc' : 'desc';

            this.setAttribute('data-direction', newDirection);

            // Toggle the arrow direction
            if (newDirection === 'asc') {
                this.querySelector('svg').style.transform = 'rotate(180deg)';
            } else {
                this.querySelector('svg').style.transform = '';
            }

            sortModels(sortBySelect.value, newDirection);
        });
    }

    /**
     * Sort models based on criteria and direction
     */
    function sortModels(sortBy, direction) {
        // Store preferences function is defined in initViewToggle
        const storePreference = (key, value) => {
            try {
                localStorage.setItem('gallery_' + key, value);
            } catch (e) {
                console.warn('localStorage not available:', e);
            }
        };

        // Store preferences
        storePreference('sortBy', sortBy);
        storePreference('sortDir', direction);

        const multiplier = direction === 'asc' ? 1 : -1;

        // Sort function for different data types
        function compareValues(a, b) {
            let valueA, valueB;

            if (sortBy === 'name') {
                valueA = a.dataset.name || '';
                valueB = b.dataset.name || '';
                return multiplier * valueA.localeCompare(valueB);
            }
            else if (sortBy === 'rating') {
                valueA = parseFloat(a.dataset.rating) || 0;
                valueB = parseFloat(b.dataset.rating) || 0;
            }
            else if (sortBy === 'downloads') {
                valueA = parseInt(a.dataset.downloads) || 0;
                valueB = parseInt(b.dataset.downloads) || 0;
            }
            else if (sortBy === 'created_at' || sortBy === 'updated_at') {
                // Parse dates and handle empty values
                valueA = a.dataset[sortBy] ? new Date(a.dataset[sortBy]).getTime() : 0;
                valueB = b.dataset[sortBy] ? new Date(b.dataset[sortBy]).getTime() : 0;
            }

            // For numeric values
            if (valueA === valueB) {
                // Secondary sort by name if values are equal
                return multiplier * (a.dataset.name || '').localeCompare(b.dataset.name || '');
            }
            return multiplier * (valueA - valueB);
        }

        // Convert collections to arrays for sorting
        const gridItems = Array.from(modelCards);
        const listItems = Array.from(modelListItems);

        // Sort grid items
        gridItems.sort(compareValues);
        gridItems.forEach(item => modelsGrid.appendChild(item));

        // Sort list items
        listItems.sort(compareValues);
        listItems.forEach(item => modelsList.appendChild(item));
    }

    /**
     * Format dates to be more readable
     */
    function formatDates() {
        document.querySelectorAll('.date-value').forEach(dateEl => {
            const dateStr = dateEl.textContent;
            if (!dateStr) return;

            try {
                const date = new Date(dateStr);
                if (isNaN(date.getTime())) return;

                // Format: YYYY-MM-DD
                const formatted = date.toISOString().split('T')[0];
                dateEl.textContent = formatted;
            } catch (e) {
                console.warn('Error formatting date:', e);
            }
        });
    }
});
