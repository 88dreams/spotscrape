document.addEventListener('DOMContentLoaded', function() {
    // Constants for configuration
    const CONFIG = {
        DEBUG_LOG: {
            BATCH_DELAY: 1000,
            MAX_BATCH: 50
        },
        MESSAGES: {
            MAX_COUNT: 50
        },
        POLLING: {
            MIN_DELAY: 1000,
            MAX_DELAY: 5000,
            BACKOFF_RATE: 1.5
        },
        ENDPOINTS: {
            DEBUG_LOG: '/api/debug-log',
            MESSAGES: '/api/messages',
            PROGRESS: '/api/progress',
            SCAN_URL: '/api/scan-url',
            SCAN_GPT: '/api/scan-webpage',
            CREATE_PLAYLIST: '/api/create-playlist',
            GPT_RESULTS: '/api/results-gpt'
        },
        UI: {
            DEBOUNCE_DELAY: 150,
            ALBUM_BATCH_SIZE: 20,
            SCROLL_THROTTLE: 100,
            VIRTUAL_SCROLL: {
                BUFFER_SIZE: 10,
                ITEM_HEIGHT: 120
            },
            IMAGES: {
                LAZY_LOAD_THRESHOLD: 0.2,
                RETRY_ATTEMPTS: 2,
                RETRY_DELAY: 1500,
                PLACEHOLDER: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80"%3E%3Crect width="80" height="80" fill="%23eee"/%3E%3C/svg%3E'
            },
            FILTER: {
                MIN_POPULARITY: 0,
                MAX_POPULARITY: 100,
                DEBOUNCE_DELAY: 200
            },
            SORT: {
                OPTIONS: ['name', 'artist', 'popularity'],
                DIRECTIONS: ['asc', 'desc']
            },
            HISTORY: {
                MAX_ITEMS: 50
            }
        },
        CACHE: {
            MAX_AGE: 1000 * 60 * 60,
            MAX_ITEMS: 200,
            COMPRESSION: true
        },
        QUEUE: {
            RETRY_ATTEMPTS: 3,
            RETRY_DELAY: 1000,
            CONCURRENT_REQUESTS: 6,
            TIMEOUT: 30000
        }
    };

    // Enhanced request queue and caching system
    const requestQueue = {
        queue: [],
        processing: new Set(),
        retryDelays: [1000, 2000, 4000], // Progressive retry delays
        
        async add(request) {
            const requestId = Math.random().toString(36).substring(7);
            const queueItem = {
                id: requestId,
                request,
                retryCount: 0,
                status: 'pending',
                priority: request.priority || 0
            };
            
            // Insert based on priority
            const insertIndex = this.queue.findIndex(item => item.priority <= queueItem.priority);
            if (insertIndex === -1) {
                this.queue.push(queueItem);
            } else {
                this.queue.splice(insertIndex, 0, queueItem);
            }
            
            debugLogger.log(`Request queued: ${requestId}`, 'INFO');
            
            // Start processing if capacity available
            if (this.processing.size < CONFIG.QUEUE.CONCURRENT_REQUESTS) {
                this.processQueue();
            }
            
            return new Promise((resolve, reject) => {
                queueItem.resolve = resolve;
                queueItem.reject = reject;
            });
        },
        
        async processQueue() {
            if (this.queue.length === 0 || 
                this.processing.size >= CONFIG.QUEUE.CONCURRENT_REQUESTS) {
                return;
            }
            
            const item = this.queue.shift();
            if (!item) return;
            
            this.processing.add(item.id);
            
            try {
                const controller = new AbortController();
                const timeout = setTimeout(() => controller.abort(), CONFIG.QUEUE.TIMEOUT);
                
                const response = await fetch(item.request.url, {
                    ...item.request.options,
                    signal: controller.signal,
                    headers: {
                        ...item.request.options?.headers,
                        'X-Request-ID': item.id
                    }
                });
                
                clearTimeout(timeout);
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                let data;
                const contentType = response.headers.get('content-type');
                if (contentType?.includes('application/json')) {
                    data = await response.json();
                } else {
                    data = await response.text();
                }
                
                this.processing.delete(item.id);
                item.resolve(data);
                
            } catch (error) {
                if (item.retryCount < CONFIG.QUEUE.RETRY_ATTEMPTS) {
                    // Progressive retry delay
                    const retryDelay = this.retryDelays[item.retryCount] || 
                                     this.retryDelays[this.retryDelays.length - 1];
                    
                    item.retryCount++;
                    this.queue.unshift(item);
                    this.processing.delete(item.id);
                    debugLogger.log(`Retrying request ${item.id}, attempt ${item.retryCount}`, 'WARN');
                    await new Promise(resolve => setTimeout(resolve, retryDelay));
                } else {
                    this.processing.delete(item.id);
                    item.reject(error);
                    debugLogger.log(`Request ${item.id} failed after ${CONFIG.QUEUE.RETRY_ATTEMPTS} attempts`, 'ERROR');
                }
            }
            
            // Process next item
            this.processQueue();
        },
        
        clear() {
            this.queue = [];
            this.processing.clear();
            debugLogger.log('Request queue cleared', 'INFO');
        }
    };

    // Enhanced response cache with compression
    const responseCache = {
        cache: new Map(),
        
        generateKey(endpoint, params) {
            return `${endpoint}:${JSON.stringify(params)}`;
        },
        
        async compress(data) {
            if (!CONFIG.CACHE.COMPRESSION || typeof data !== 'string') {
                return data;
            }
            
            try {
                const blob = new Blob([data]);
                return await new Response(blob.stream().pipeThrough(new CompressionStream('gzip'))).blob();
            } catch (error) {
                console.warn('Compression failed, storing uncompressed data:', error);
                return data;
            }
        },
        
        async decompress(data) {
            if (!CONFIG.CACHE.COMPRESSION || !(data instanceof Blob)) {
                return data;
            }
            
            try {
                return await new Response(data.stream().pipeThrough(new DecompressionStream('gzip'))).text();
            } catch (error) {
                console.warn('Decompression failed:', error);
                return data;
            }
        },
        
        async set(endpoint, params, response) {
            const key = this.generateKey(endpoint, params);
            const compressedData = await this.compress(response);
            
            const entry = {
                data: compressedData,
                timestamp: Date.now(),
                accessCount: 0
            };
            
            // Remove oldest or least accessed entries if cache is full
            if (this.cache.size >= CONFIG.CACHE.MAX_ITEMS) {
                const entries = Array.from(this.cache.entries());
                entries.sort((a, b) => {
                    // Prioritize keeping frequently accessed items
                    const accessDiff = b[1].accessCount - a[1].accessCount;
                    if (accessDiff !== 0) return accessDiff;
                    // If access counts are equal, remove older items
                    return b[1].timestamp - a[1].timestamp;
                });
                
                const entriesToRemove = entries.slice(Math.floor(CONFIG.CACHE.MAX_ITEMS * 0.2));
                entriesToRemove.forEach(([key]) => this.cache.delete(key));
            }
            
            this.cache.set(key, entry);
            debugLogger.log(`Cache set for ${key}`, 'INFO');
        },
        
        async get(endpoint, params) {
            const key = this.generateKey(endpoint, params);
            const entry = this.cache.get(key);
            
            if (!entry) {
                return null;
            }
            
            // Check if cache entry is expired
            if (Date.now() - entry.timestamp > CONFIG.CACHE.MAX_AGE) {
                this.cache.delete(key);
                debugLogger.log(`Cache expired for ${key}`, 'INFO');
                return null;
            }
            
            entry.accessCount++;
            debugLogger.log(`Cache hit for ${key}`, 'INFO');
            return await this.decompress(entry.data);
        },
        
        clear() {
            this.cache.clear();
            debugLogger.log('Cache cleared', 'INFO');
        }
    };

    // Enhanced fetch utility with queuing and caching
    const enhancedFetch = {
        async get(endpoint, params = {}, useCache = true) {
            if (useCache) {
                const cachedResponse = responseCache.get(endpoint, params);
                if (cachedResponse) {
                    return cachedResponse;
                }
            }

            const request = {
                url: endpoint,
                options: {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' }
                }
            };

            const data = await requestQueue.add(request);
            
            if (useCache) {
                responseCache.set(endpoint, params, data);
            }

            return data;
        },

        async post(endpoint, params = {}) {
            const request = {
                url: endpoint,
                options: {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(params)
                }
            };

            return await requestQueue.add(request);
        }
    };

    // Utility functions for performance optimization
    const utils = {
        debounce(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        },

        throttle(func, limit) {
            let inThrottle;
            return function executedFunction(...args) {
                if (!inThrottle) {
                    func(...args);
                    inThrottle = true;
                    setTimeout(() => inThrottle = false, limit);
                }
            };
        },

        // Image loading optimization
        loadImage(url) {
            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => resolve(url);
                img.onerror = () => reject(new Error('Image load failed'));
                img.src = url;
            });
        },

        // Batch DOM operations
        batchDOMOperations(operations, batchSize = 5) {
            let index = 0;
            const total = operations.length;

            return new Promise((resolve) => {
                function processNextBatch() {
                    const end = Math.min(index + batchSize, total);
                    
                    requestAnimationFrame(() => {
                        for (let i = index; i < end; i++) {
                            operations[i]();
                        }
                        
                        index = end;
                        if (index < total) {
                            processNextBatch();
                        } else {
                            resolve();
                        }
                    });
                }
                
                processNextBatch();
            });
        }
    };

    // Debug logging optimization with improved batching
    const debugLogger = {
        queue: [],
        timeout: null,

        async flush() {
            if (this.queue.length === 0) return;
            
            const logsToSend = this.queue.splice(0, CONFIG.DEBUG_LOG.MAX_BATCH);
            try {
                await fetch(CONFIG.ENDPOINTS.DEBUG_LOG, {
                method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ logs: logsToSend })
            });
        } catch (e) {
            console.error('Debug logging failed:', e);
                const importantLogs = logsToSend.filter(log => 
                    log.level === 'ERROR' || log.level === 'WARN'
                );
                this.queue.unshift(...importantLogs);
            }
            
            if (this.queue.length > 0) {
                this.scheduleFlush();
            }
        },

        scheduleFlush() {
            if (!this.timeout) {
                this.timeout = setTimeout(() => {
                    this.timeout = null;
                    this.flush();
                }, CONFIG.DEBUG_LOG.BATCH_DELAY);
            }
        },

        log(message, level = 'DEBUG') {
            this.queue.push({ message, level, timestamp: Date.now() });
            this.scheduleFlush();
            
        if (level === 'ERROR') {
            console.error(message);
        }
    }
    };

    // Cleanup registry with WeakMap for better memory management
    const cleanupRegistry = new WeakMap();

    function registerCleanup(target, cleanup) {
        const cleanups = cleanupRegistry.get(target) || [];
        cleanups.push(cleanup);
        cleanupRegistry.set(target, cleanups);
    }

    function cleanup(target) {
        const cleanups = cleanupRegistry.get(target);
        if (cleanups) {
            cleanups.forEach(fn => fn());
            cleanupRegistry.delete(target);
        }
    }

    // Elements cache with validation
    const elements = {
        urlInput: document.getElementById('urlInput'),
        urlSearchButton: document.getElementById('urlSearchButton'),
        gptSearchButton: document.getElementById('gptSearchButton'),
        albumsList: document.getElementById('albumsList'),
        allTracksSwitch: document.getElementById('allTracksSwitch'),
        popularTracksSwitch: document.getElementById('popularTracksSwitch'),
        playlistName: document.getElementById('playlistName'),
        playlistDescription: document.getElementById('playlistDescription'),
        createPlaylistButton: document.getElementById('createPlaylistButton'),
        messagesDiv: document.getElementById('messages'),
        progressContainer: document.getElementById('progressContainer'),
        progressBar: document.getElementById('progressBar'),
        progressText: document.getElementById('progressText'),
        progressPercent: document.getElementById('progressPercent'),
        toggleSelectAll: document.getElementById('toggleSelectAll')
    };

    // Validate critical elements
    if (!elements.urlSearchButton || !elements.gptSearchButton || !elements.urlInput) {
        console.error('Critical elements missing:', {
            urlSearchButton: !!elements.urlSearchButton,
            gptSearchButton: !!elements.gptSearchButton,
            urlInput: !!elements.urlInput
        });
        return;
    }

    // State management with immutable updates
    const state = {
        currentUrl: '',
        selectedAlbums: new Set(),
        playlistCreationInProgress: false,
        isPolling: false,
        pollMessageTimeout: null,
        filter: {
            type: 'album', // 'album' or 'artist'
            text: '',
            popularityValue: 50,
            popularityOperator: 'gt', // 'gt' or 'lt'
            activeFilters: new Set()
        },
        sort: {
            field: 'popularity',
            direction: 'desc'
        },
        searchHistory: [],
        originalAlbums: [], // Store original album list
        
        setUrl(url) {
            this.currentUrl = url;
            debugLogger.log(`URL updated: ${url}`, 'INFO');
        },
        
        addSelectedAlbum(id) {
            if (!id) {
                debugLogger.log('Attempted to add invalid album ID', 'WARN');
                return;
            }
            this.selectedAlbums.add(id);
            debugLogger.log(`Album selected: ${id}`, 'INFO');
        },
        
        removeSelectedAlbum(id) {
            if (!id) {
                debugLogger.log('Attempted to remove invalid album ID', 'WARN');
                return;
            }
            this.selectedAlbums.delete(id);
            debugLogger.log(`Album deselected: ${id}`, 'INFO');
        },
        
        clearSelectedAlbums() {
            this.selectedAlbums.clear();
            debugLogger.log('Selected albums cleared', 'INFO');
        },

        setPolling(isPolling) {
            this.isPolling = isPolling;
            if (!isPolling && this.pollMessageTimeout) {
                clearTimeout(this.pollMessageTimeout);
                this.pollMessageTimeout = null;
            }
        },

        setPlaylistCreationStatus(inProgress) {
            this.playlistCreationInProgress = inProgress;
            debugLogger.log(`Playlist creation status: ${inProgress}`, 'INFO');
        },

        getSelectedAlbumsCount() {
            return this.selectedAlbums.size;
        },

        getSelectedAlbumsArray() {
            return Array.from(this.selectedAlbums);
        },

        setFilter(filterType, value) {
            this.filter[filterType] = value;
            this.filter.activeFilters.add(filterType);
            if (!value && filterType !== 'minPopularity' && filterType !== 'maxPopularity') {
                this.filter.activeFilters.delete(filterType);
            }
            debugLogger.log(`Filter updated: ${filterType} = ${value}`, 'INFO');
        },

        clearFilters() {
            this.filter = {
                type: 'album', // 'album' or 'artist'
                text: '',
                popularityValue: 50,
                popularityOperator: 'gt', // 'gt' or 'lt'
                activeFilters: new Set()
            };
            debugLogger.log('Filters cleared', 'INFO');
        },

        setSort(field, direction) {
            this.sort.field = field;
            this.sort.direction = direction;
            debugLogger.log(`Sort updated: ${field} ${direction}`, 'INFO');
        },

        addToSearchHistory(url, searchMethod, timestamp = Date.now()) {
            const historyItem = { url, searchMethod, timestamp };
            this.searchHistory.unshift(historyItem);
            
            if (this.searchHistory.length > CONFIG.UI.HISTORY.MAX_ITEMS) {
                this.searchHistory.pop();
            }

            try {
                localStorage.setItem('searchHistory', JSON.stringify(this.searchHistory));
            } catch (e) {
                console.error('Failed to save search history:', e);
            }
        },

        loadSearchHistory() {
            try {
                const saved = localStorage.getItem('searchHistory');
                if (saved) {
                    this.searchHistory = JSON.parse(saved);
                }
            } catch (e) {
                console.error('Failed to load search history:', e);
                this.searchHistory = [];
            }
        },

        clearSearchHistory() {
            this.searchHistory = [];
            try {
                localStorage.removeItem('searchHistory');
            } catch (e) {
                console.error('Failed to clear search history:', e);
            }
        }
    };

    // Template optimization with DocumentFragment
    const templates = {
        albumCard: (() => {
            const template = document.createElement('template');
            template.innerHTML = `
        <div class="album-card">
            <div class="album-card-inner">
                <input type="checkbox" class="album-checkbox" aria-label="Select album">
                <img class="album-thumbnail" src="" alt="" loading="lazy">
                <div class="album-info">
                    <div class="tooltip-container">
                        <div class="album-title text-truncate"></div>
                        <span class="tooltip-text"></span>
                    </div>
                    <div class="tooltip-container">
                        <div class="album-artist text-truncate"></div>
                        <span class="tooltip-text"></span>
                    </div>
                    <div class="album-popularity text-sm"></div>
                </div>
            </div>
            <button class="spotify-play-button" aria-label="Open in Spotify"></button>
        </div>
    `;
            return template;
        })(),
        
        message: (() => {
            const template = document.createElement('template');
            template.innerHTML = `
                <div class="message mb-2 p-2 rounded"></div>
            `;
            return template;
        })(),

        filterControls: (() => {
            const template = document.createElement('template');
            template.innerHTML = `
                <div class="filter-controls mb-4">
                    <div class="filter-row">
                        <div class="filter-type-select">
                            <select class="filter-type" aria-label="Filter type">
                                <option value="album">Album</option>
                                <option value="artist">Artist</option>
                                <option value="popularity">Popularity</option>
                            </select>
                        </div>
                        <input type="text" class="filter-text" placeholder="Filter by album..." aria-label="Filter text">
                        <div class="filter-popularity-container">
                            <input type="text" inputmode="numeric" pattern="[0-9]*" 
                                   class="filter-popularity" 
                                   placeholder="enter number, then select greater or less than" 
                                   aria-label="Popularity value">
                            <button class="popularity-toggle" aria-label="Toggle popularity comparison">
                                <span class="toggle-text">&gt;</span>
                            </button>
                        </div>
                        <div class="sort-controls">
                            <select class="sort-field" aria-label="Sort by">
                                <option value="" disabled selected>Sort By</option>
                                <option value="popularity">Popularity</option>
                                <option value="name">Name</option>
                                <option value="artist">Artist</option>
                            </select>
                            <button class="sort-direction" aria-label="Sort direction">
                                <span class="sort-icon">▾</span>
                            </button>
                        </div>
                        <button class="clear-filters" aria-label="Clear filters">Clear</button>
                    </div>
                </div>
            `;
            return template;
        })(),

        searchHistory: (() => {
            const template = document.createElement('template');
            template.innerHTML = `
                <div class="search-history">
                    <div class="history-header">
                        <h3>Recent Searches</h3>
                        <button class="clear-history" aria-label="Clear history">Clear</button>
                    </div>
                    <ul class="history-list"></ul>
                </div>
            `;
            return template;
        })(),

        historyItem: (() => {
            const template = document.createElement('template');
            template.innerHTML = `
                <li class="history-item">
                    <div class="history-link-wrapper">
                        <span class="search-method-badge"></span>
                        <a href="#" class="history-link"></a>
                        <span class="history-time"></span>
                    </div>
                </li>
            `;
            return template;
        })()
    };

    // UI updates with requestAnimationFrame
    const ui = {
        resetUI() {
            state.clearSelectedAlbums();
            this.updateAlbumsList([]);
            elements.playlistName.value = '';
            elements.playlistDescription.value = '';
            this.toggleProgress(false);
            elements.createPlaylistButton.disabled = false;
            elements.createPlaylistButton.textContent = 'GO';
            elements.messagesDiv.innerHTML = '';
            if (elements.toggleSelectAll) {
                elements.toggleSelectAll.classList.remove('visible');
            }
            this.updateSelectAllButton(true);
        },

        updateSelectAllButton(allSelected = false) {
            if (!elements.toggleSelectAll) return;
            
            const button = elements.toggleSelectAll;
            const textSpan = button.querySelector('.select-all-text');
            
            if (allSelected) {
                button.classList.remove('none-selected');
                textSpan.textContent = 'DESELECT ALL';
            } else {
                button.classList.add('none-selected');
                textSpan.textContent = 'SELECT ALL';
            }
        },

        toggleAllAlbums(select = true) {
            const checkboxes = elements.albumsList.querySelectorAll('.album-checkbox');
            checkboxes.forEach(checkbox => {
                const cardElement = checkbox.closest('.album-card');
                const albumId = cardElement.dataset.albumId;
                
                checkbox.checked = select;
                if (select) {
                    state.addSelectedAlbum(albumId);
                    cardElement.classList.add('selected');
                } else {
                    state.removeSelectedAlbum(albumId);
                    cardElement.classList.remove('selected');
                }
            });
            
            this.updateSelectAllButton(select);
        },

        updateAlbumsList(albums) {
            if (!albums?.length) {
                const albumsList = document.getElementById('albumsList');
                if (albumsList) {
                    albumsList.innerHTML = '';
                }
                if (elements.toggleSelectAll) {
                    elements.toggleSelectAll.style.display = 'none';
                }
                const filterContainer = document.querySelector('.filter-container');
                if (filterContainer) {
                    filterContainer.style.display = 'none';
                }
                return;
            }

            const albumsList = document.getElementById('albumsList');
            if (!albumsList) {
                console.error('Albums list container not found');
                return;
            }

            // Set container height for virtual scrolling
            albumsList.style.height = `${albums.length * CONFIG.UI.VIRTUAL_SCROLL.ITEM_HEIGHT}px`;
            albumsList.style.position = 'relative';
            
            const fragment = document.createDocumentFragment();
            albumsList.innerHTML = '';

            // Show controls
            if (elements.toggleSelectAll) {
                elements.toggleSelectAll.style.display = 'flex';
                elements.toggleSelectAll.classList.add('visible');
            }
            const filterContainer = document.querySelector('.filter-container');
            if (filterContainer) {
                filterContainer.style.display = 'block';
            }

            // Create operations array for batched processing
            const operations = albums.map((album, index) => async () => {
                try {
                    const card = templates.albumCard.content.cloneNode(true);
                    const cardElement = card.firstElementChild;
                    cardElement.dataset.albumId = album.id;
                    
                    // Position for virtual scrolling
                    cardElement.style.position = 'absolute';
                    cardElement.style.top = `${index * CONFIG.UI.VIRTUAL_SCROLL.ITEM_HEIGHT}px`;
                    cardElement.style.width = '100%';
                    cardElement.style.height = `${CONFIG.UI.VIRTUAL_SCROLL.ITEM_HEIGHT}px`;
                    
                    // Query all required elements
                    const elements = {
                        img: cardElement.querySelector('.album-thumbnail'),
                        artistDiv: cardElement.querySelector('.album-artist'),
                        artistTooltip: cardElement.querySelector('.album-artist + .tooltip-text'),
                        titleDiv: cardElement.querySelector('.album-title'),
                        titleTooltip: cardElement.querySelector('.album-title + .tooltip-text'),
                        popularityDiv: cardElement.querySelector('.album-popularity.text-sm'),
                        checkbox: cardElement.querySelector('.album-checkbox'),
                        playButton: cardElement.querySelector('.spotify-play-button')
                    };

                    // Verify all elements exist
                    Object.entries(elements).forEach(([name, element]) => {
                        if (!element) {
                            throw new Error(`Required element '${name}' not found in album card template`);
                        }
                    });

                    // Enhanced image loading with intersection observer
                    const imageUrl = album.images?.[0]?.url || CONFIG.UI.IMAGES.PLACEHOLDER;
                    imageLoader.observe(elements.img, imageUrl);

                    // Rest of the card setup remains unchanged
                    elements.artistDiv.textContent = album.artist;
                    elements.artistTooltip.textContent = album.artist;
                    elements.titleDiv.textContent = album.name;
                    elements.titleTooltip.textContent = album.name;
                    
                    const popularityScore = album.popularity || 0;
                    const popularityEmoji = popularityScore >= 75 ? '🔥' : 
                                          popularityScore >= 50 ? '⭐' : 
                                          popularityScore >= 25 ? '👍' : '🎵';
                    elements.popularityDiv.textContent = `${popularityEmoji} Popularity: ${popularityScore}`;

                    elements.checkbox.checked = true;
                    cardElement.classList.add('selected');
                    state.addSelectedAlbum(album.id);

                    const handleInteraction = (e) => {
                        const isCheckbox = e.target === elements.checkbox;
                        
                        if (isCheckbox) {
                            if (elements.checkbox.checked) {
                                state.addSelectedAlbum(album.id);
                                cardElement.classList.add('selected');
                            } else {
                                state.removeSelectedAlbum(album.id);
                                cardElement.classList.remove('selected');
                            }
                            const allChecked = !albumsList.querySelector('.album-checkbox:not(:checked)');
                            this.updateSelectAllButton(allChecked);
                        } else if (e.target === elements.playButton || (!isCheckbox && !e.target.closest('label'))) {
                            e.stopPropagation();
                            if (album.spotify_url) {
                                window.open(album.spotify_url, '_blank');
                            } else {
                                this.addMessage('Spotify URL not available for this album', true);
                            }
                        }
                    };

                    cardElement.addEventListener('click', handleInteraction);
                    fragment.appendChild(card);
                } catch (error) {
                    console.error('Error creating album card:', error);
                    this.addMessage(`Error creating album card for "${album.name}": ${error.message}`, true);
                }
            });

            // Process operations in batches
            utils.batchDOMOperations(operations, CONFIG.UI.ALBUM_BATCH_SIZE).then(() => {
                albumsList.appendChild(fragment);
                this.updateSelectAllButton(true);
                
                // Initialize virtual scrolling
                virtualScroll.initialize(albumsList);
                virtualScroll.updateVisibleItems();
            });
        },

        toggleProgress(show) {
            elements.progressContainer.classList.toggle('hidden', !show);
            if (show) {
                this.startMessagePolling();
            } else {
                this.stopMessagePolling();
            }
        },

        updateProgress(percent, message) {
            requestAnimationFrame(() => {
                elements.progressBar.style.width = `${percent}%`;
                elements.progressText.textContent = message;
                elements.progressPercent.textContent = `${Math.round(percent)}%`;
            });
        },

        addMessage(message, isError = false) {
            requestAnimationFrame(() => {
                const messageElement = templates.message.content.cloneNode(true).firstElementChild;
                messageElement.textContent = message;
                messageElement.classList.add(isError ? 'error' : 'success');
                
                elements.messagesDiv.appendChild(messageElement);
                elements.messagesDiv.scrollTop = elements.messagesDiv.scrollHeight;

                while (elements.messagesDiv.children.length > CONFIG.MESSAGES.MAX_COUNT) {
                    elements.messagesDiv.removeChild(elements.messagesDiv.firstChild);
                }
            });
        },

        startMessagePolling() {
            if (this.messageSource) return;
            
            this.messageSource = new EventSource(CONFIG.ENDPOINTS.MESSAGES);
            this.messageSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.message) {
                    this.addMessage(data.message);
                }
            };
            
            this.progressSource = new EventSource(CONFIG.ENDPOINTS.PROGRESS);
            this.progressSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.progress !== undefined && data.message) {
                    this.updateProgress(data.progress, data.message);
                }
            };
        },

        stopMessagePolling() {
            if (this.messageSource) {
                this.messageSource.close();
                this.messageSource = null;
            }
            if (this.progressSource) {
                this.progressSource.close();
                this.progressSource = null;
            }
        },

        async pollForResults() {
            let progressValue = 40;
            let delay = CONFIG.POLLING.MIN_DELAY;
            let pollTimeout;

            const poll = async () => {
                try {
                    if (progressValue < 90) {
                        progressValue = Math.min(progressValue + 2, 90);
                        ui.updateProgress(progressValue, 'Processing content...');
                    }
                    
                    const data = await enhancedFetch.get(CONFIG.ENDPOINTS.GPT_RESULTS, {}, false);
                    
                    if (data.status === 'complete') {
                        if (data.albums) {
                            ui.updateProgress(100, 'Search completed successfully');
                            ui.updateAlbumsList(data.albums);
                            ui.addMessage('Search completed successfully');
                            ui.toggleProgress(false);
                        } else {
                            throw new Error('No albums found');
                        }
                        return;
                    } else if (data.status === 'error') {
                        throw new Error(data.error || 'Search failed');
                    }
                    
                    delay = Math.min(delay * CONFIG.POLLING.BACKOFF_RATE, CONFIG.POLLING.MAX_DELAY);
                    pollTimeout = setTimeout(poll, delay);
                    
                } catch (error) {
                    console.error('Polling error:', error);
                    ui.addMessage('Error during search: ' + error.message, true);
                    ui.updateAlbumsList([]);
                    ui.toggleProgress(false);
                }
            };

            poll();
            return () => pollTimeout && clearTimeout(pollTimeout);
        },

        handleTrackTypeChange(event) {
            const isAllTracks = event.target === elements.allTracksSwitch;
            const otherSwitch = isAllTracks ? elements.popularTracksSwitch : elements.allTracksSwitch;
        
            if (event.target.checked) {
                otherSwitch.checked = false;
            }
        },

        resetSearch() {
            elements.urlInput.value = '';
            elements.searchButton.textContent = 'Search';
            elements.searchButton.classList.remove('reset');
            elements.searchButton.onclick = this.handleSearch;
            elements.messagesDiv.innerHTML = '';
        },

        isValidUrl(string) {
            try {
                new URL(string);
                return true;
            } catch (_) {
                return false;
            }
        },

        getDefaultPlaylistName() {
            let domain = 'unknown-domain';
            try {
                if (state.currentUrl) {
                    const url = new URL(state.currentUrl);
                    domain = url.hostname.replace('www.', '');
                }
            } catch (error) {
                console.error('Invalid URL:', state.currentUrl);
            }
            return `${domain} - ${new Date().toLocaleString()}`;
        },

        showCompletionPopup(message) {
            alert(message);
        },

        initializeFilterControls() {
            const container = document.querySelector('.filter-container');
            if (!container) return;

            const filterControls = templates.filterControls.content.cloneNode(true);
            container.appendChild(filterControls);

            // Initialize filter elements
            const elements = {
                filterType: container.querySelector('.filter-type'),
                filterText: container.querySelector('.filter-text'),
                popularityContainer: container.querySelector('.filter-popularity-container'),
                popularityValue: container.querySelector('.filter-popularity'),
                popularityToggle: container.querySelector('.popularity-toggle'),
                sortField: container.querySelector('.sort-field'),
                sortDirection: container.querySelector('.sort-direction'),
                clearFilters: container.querySelector('.clear-filters')
            };

            // Filter type change handler
            elements.filterType.addEventListener('change', (e) => {
                state.filter.type = e.target.value;
                
                // Show/hide appropriate input based on filter type
                if (e.target.value === 'popularity') {
                    elements.filterText.style.display = 'none';
                    elements.popularityContainer.classList.add('visible');
                    elements.popularityValue.value = '';
                    elements.popularityValue.placeholder = 'enter number, then select greater or less than';
                } else {
                    elements.filterText.style.display = 'block';
                    elements.popularityContainer.classList.remove('visible');
                    elements.filterText.placeholder = `Filter by ${e.target.value}...`;
                }
                
                if (elements.filterText.value || elements.popularityValue.value) {
                    ui.applyFiltersAndSort();
                }
            });

            // Text filter input handler
            elements.filterText.addEventListener('input', utils.debounce((e) => {
                state.setFilter('text', e.target.value);
                ui.applyFiltersAndSort();
            }, CONFIG.UI.FILTER.DEBOUNCE_DELAY));

            // Popularity filter handlers
            elements.popularityValue.addEventListener('input', (e) => {
                const value = e.target.value;
                
                // Allow empty input for resetting
                if (value === '') {
                    state.filter.popularityValue = null;
                    state.filter.activeFilters.delete('popularity');
                    e.target.placeholder = 'enter number, then select greater or less than';
                    ui.applyFiltersAndSort();
                    return;
                }

                // Validate input is a number between 0 and 100
                const numValue = parseInt(value);
                if (isNaN(numValue) || numValue < 0 || numValue > 100) {
                    e.target.value = '';
                    e.target.placeholder = 'enter number, then select greater or less than';
                    state.filter.popularityValue = null;
                    state.filter.activeFilters.delete('popularity');
                } else {
                    state.filter.popularityValue = numValue;
                    state.filter.activeFilters.add('popularity');
                }
                
                ui.applyFiltersAndSort();
            });

            elements.popularityToggle.addEventListener('click', () => {
                const isGreaterThan = state.filter.popularityOperator === 'gt';
                state.filter.popularityOperator = isGreaterThan ? 'lt' : 'gt';
                elements.popularityToggle.querySelector('.toggle-text').textContent = isGreaterThan ? '<' : '>';
                if (elements.popularityValue.value) {
                    ui.applyFiltersAndSort();
                }
            });

            // Sort controls
            elements.sortField.addEventListener('change', (e) => {
                state.setSort(e.target.value, state.sort.direction);
                ui.applyFiltersAndSort();
            });

            elements.sortDirection.addEventListener('click', () => {
                const newDirection = state.sort.direction === 'asc' ? 'desc' : 'asc';
                state.setSort(state.sort.field, newDirection);
                elements.sortDirection.setAttribute('data-direction', newDirection);
                ui.applyFiltersAndSort();
            });

            // Clear filters
            elements.clearFilters.addEventListener('click', () => {
                state.clearFilters();
                elements.filterType.value = 'album';
                elements.filterText.value = '';
                elements.filterText.style.display = 'block';
                elements.popularityContainer.classList.remove('visible');
                elements.filterText.placeholder = 'Filter by album...';
                elements.popularityValue.value = '';
                elements.popularityValue.placeholder = 'enter number, then select greater or less than';
                state.filter.popularityOperator = 'gt';
                elements.popularityToggle.querySelector('.toggle-text').textContent = '>';
                ui.applyFiltersAndSort();
            });
        },

        initializeSearchHistory() {
            const container = document.querySelector('.history-container');
            if (!container) return;

            const historyElement = templates.searchHistory.content.cloneNode(true);
            container.appendChild(historyElement);

            const clearButton = container.querySelector('.clear-history');
            clearButton.addEventListener('click', () => {
                state.clearSearchHistory();
                this.updateSearchHistory();
            });

            state.loadSearchHistory();
            this.updateSearchHistory();
        },

        updateSearchHistory() {
            const historyList = document.querySelector('.history-list');
            if (!historyList) {
                console.error('History list element not found');
                return;
            }

            historyList.innerHTML = '';
            const fragment = document.createDocumentFragment();

            state.searchHistory.forEach(item => {
                const historyItem = templates.historyItem.content.cloneNode(true);
                const linkWrapper = historyItem.querySelector('.history-link-wrapper');
                const badge = historyItem.querySelector('.search-method-badge');
                const link = historyItem.querySelector('.history-link');
                const time = historyItem.querySelector('.history-time');

                // Set search method badge
                badge.textContent = item.searchMethod?.toUpperCase() || 'URL';
                badge.classList.add(item.searchMethod || 'url');

                link.textContent = item.url;
                link.href = '#';
                linkWrapper.addEventListener('click', (e) => {
                    e.preventDefault();
                    elements.urlInput.value = item.url;
                    
                    // Set the corresponding search method radio
                    const radio = document.querySelector(`input[name="searchMethod"][value="${item.searchMethod || 'url'}"]`);
                    if (radio) radio.checked = true;
                    
                    handlers.handleSearch.bind(handlers)();
                    
                    // Close dropdown after selection
                    const dropdown = document.getElementById('historyDropdown');
                    const dropdownButton = document.getElementById('historyDropdownButton');
                    if (dropdown && dropdownButton) {
                        dropdown.classList.add('hidden');
                        dropdownButton.classList.remove('active');
                    }
                });

                time.textContent = new Date(item.timestamp).toLocaleString();
                fragment.appendChild(historyItem);
            });

            historyList.appendChild(fragment);
        },

        applyFiltersAndSort() {
            if (!state.originalAlbums.length) return;

            let filteredAlbums = albumFilters.applyFilters(state.originalAlbums);
            filteredAlbums = albumFilters.sortAlbums(filteredAlbums);

            // Create a Set of filtered album IDs for quick lookup
            const filteredAlbumIds = new Set(filteredAlbums.map(album => album.id));

            // Deselect any albums that are not in the filtered results
            const albumsList = document.getElementById('albumsList');
            if (albumsList) {
                const checkboxes = albumsList.querySelectorAll('.album-checkbox');
                checkboxes.forEach(checkbox => {
                    const cardElement = checkbox.closest('.album-card');
                    const albumId = cardElement.dataset.albumId;
                    
                    if (!filteredAlbumIds.has(albumId)) {
                        checkbox.checked = false;
                        cardElement.classList.remove('selected');
                        state.removeSelectedAlbum(albumId);
                    }
                });
            }

            this.updateAlbumsList(filteredAlbums);
            
            // Update the select all button state based on remaining selected albums
            const allChecked = filteredAlbums.length > 0 && 
                             filteredAlbums.every(album => state.selectedAlbums.has(album.id));
            this.updateSelectAllButton(allChecked);
        }
    };

    // Event handlers with debouncing and throttling
    const handlers = {
        async handleSearch(searchMethod) {
            try {
                const url = elements.urlInput.value.trim();
                if (!this.isValidUrl(url)) {
                    ui.addMessage('Please enter a valid URL', true);
                    return;
                }

                state.setUrl(url);
                state.addToSearchHistory(url, searchMethod);
                ui.updateSearchHistory();
                ui.resetUI();
                ui.toggleProgress(true);
                
                debugLogger.log(`Starting ${searchMethod} search for URL: ${url}`, 'INFO');
                
                const data = await enhancedFetch.post(searchMethod === 'gpt' ? CONFIG.ENDPOINTS.SCAN_GPT : CONFIG.ENDPOINTS.SCAN_URL, { url });
                
                if (searchMethod === 'gpt') {
                    // For GPT method, start polling for results
                    this.pollForResults();
                } else {
                    // For URL method, handle results immediately
                    debugLogger.log(`Processing URL scan results. Status: ${data.status}`, 'INFO');
                    
                    if (data.status === 'complete' && data.albums) {
                        state.originalAlbums = data.albums; // Store original albums
                        ui.applyFiltersAndSort(); // Apply any active filters and sorting
                    } else if (data.status === 'error') {
                        debugLogger.log(`Error in response: ${data.error}`, 'ERROR');
                        throw new Error(data.error || 'Failed to process URL');
                    } else {
                        debugLogger.log('No albums found in content', 'INFO');
                        ui.addMessage('No albums found in the content');
                    }
                    ui.toggleProgress(false);
                }
            } catch (error) {
                debugLogger.log(`Error in handleSearch: ${error.message}`, 'ERROR');
                ui.addMessage(error.message, true);
                ui.toggleProgress(false);
            }
        },

        async pollForResults() {
            let progressValue = 40;
            let delay = CONFIG.POLLING.MIN_DELAY;
            let pollTimeout;

            const poll = async () => {
                try {
                    if (progressValue < 90) {
                        progressValue = Math.min(progressValue + 2, 90);
                        ui.updateProgress(progressValue, 'Processing content...');
                    }
                    
                    const data = await enhancedFetch.get(CONFIG.ENDPOINTS.GPT_RESULTS, {}, false);
                    
                    if (data.status === 'complete') {
                        if (data.albums) {
                            ui.updateProgress(100, 'Search completed successfully');
                            ui.updateAlbumsList(data.albums);
                            ui.addMessage('Search completed successfully');
                            ui.toggleProgress(false);
                        } else {
                            throw new Error('No albums found');
                        }
                        return;
                    } else if (data.status === 'error') {
                        throw new Error(data.error || 'Search failed');
                    }
                    
                    delay = Math.min(delay * CONFIG.POLLING.BACKOFF_RATE, CONFIG.POLLING.MAX_DELAY);
                    pollTimeout = setTimeout(poll, delay);
                    
                } catch (error) {
                    console.error('Polling error:', error);
                    ui.addMessage('Error during search: ' + error.message, true);
                    ui.updateAlbumsList([]);
                    ui.toggleProgress(false);
                }
            };

            poll();
            return () => pollTimeout && clearTimeout(pollTimeout);
        },

        handleTrackTypeChange(event) {
            const isAllTracks = event.target === elements.allTracksSwitch;
            const otherSwitch = isAllTracks ? elements.popularTracksSwitch : elements.allTracksSwitch;
        
            if (event.target.checked) {
                otherSwitch.checked = false;
            }
        },

        resetSearch() {
            elements.urlInput.value = '';
            elements.searchButton.textContent = 'Search';
            elements.searchButton.classList.remove('reset');
            elements.searchButton.onclick = this.handleSearch;
            elements.messagesDiv.innerHTML = '';
        },

        isValidUrl(string) {
            try {
                new URL(string);
                return true;
            } catch (_) {
                return false;
            }
        },

        getDefaultPlaylistName() {
            let domain = 'unknown-domain';
            try {
                if (state.currentUrl) {
                    const url = new URL(state.currentUrl);
                    domain = url.hostname.replace('www.', '');
                }
            } catch (error) {
                console.error('Invalid URL:', state.currentUrl);
            }
            return `${domain} - ${new Date().toLocaleString()}`;
        },

        showCompletionPopup(message) {
            alert(message);
        },

        async handleCreatePlaylist() {
            if (state.playlistCreationInProgress) {
                return;
            }

            if (state.getSelectedAlbumsCount() === 0) {
                ui.addMessage('Please select at least one album', true);
                return;
            }

            try {
                state.setPlaylistCreationStatus(true);
                elements.createPlaylistButton.disabled = true;
                elements.createPlaylistButton.textContent = 'Creating...';
                ui.toggleProgress(true);
                ui.updateProgress(0, 'Starting playlist creation...');

                const data = await enhancedFetch.post(CONFIG.ENDPOINTS.CREATE_PLAYLIST, {
                    albums: state.getSelectedAlbumsArray(),
                    playlistName: elements.playlistName.value || this.getDefaultPlaylistName(),
                    playlistDescription: elements.playlistDescription.value,
                    includeAllTracks: elements.allTracksSwitch.checked,
                    includePopularTracks: elements.popularTracksSwitch.checked
                });

                if (data.error) {
                    throw new Error(data.error);
                }

                this.showCompletionPopup('Playlist created successfully!');
                ui.addMessage('Playlist created successfully!');

            } catch (error) {
                console.error('Playlist creation error:', error);
                ui.addMessage('Error creating playlist: ' + error.message, true);
            } finally {
                state.setPlaylistCreationStatus(false);
                elements.createPlaylistButton.disabled = false;
                elements.createPlaylistButton.textContent = 'GO';
                ui.toggleProgress(false);
            }
        }
    };

    // Event delegation for better performance
    function initializeEventListeners() {
        // Debounced URL validation
        const debouncedUrlValidation = utils.debounce((url) => {
            const isValid = handlers.isValidUrl(url);
            elements.urlSearchButton.disabled = !isValid;
            elements.gptSearchButton.disabled = !isValid;
            if (!isValid && url.length > 0) {
                ui.addMessage('Please enter a valid URL', true);
            }
        }, CONFIG.UI.DEBOUNCE_DELAY);

        // URL input handling
        elements.urlInput.addEventListener('input', (e) => {
            const url = e.target.value.trim();
            debouncedUrlValidation(url);
        });

        // URL Search button handler
        elements.urlSearchButton.addEventListener('click', utils.debounce(() => {
            handlers.handleSearch.bind(handlers)('url');
        }, CONFIG.UI.DEBOUNCE_DELAY));

        // GPT Search button handler
        elements.gptSearchButton.addEventListener('click', utils.debounce(() => {
            handlers.handleSearch.bind(handlers)('gpt');
        }, CONFIG.UI.DEBOUNCE_DELAY));

        // Enter key handler with debounce
        elements.urlInput.addEventListener('keypress', utils.debounce((e) => {
            if (e.key === 'Enter' && !elements.urlSearchButton.disabled) {
                handlers.handleSearch.bind(handlers)('url');
            }
        }, CONFIG.UI.DEBOUNCE_DELAY));

        // Optimized track type switch handlers
        elements.allTracksSwitch.addEventListener('change', utils.debounce(handlers.handleTrackTypeChange, CONFIG.UI.DEBOUNCE_DELAY));
        elements.popularTracksSwitch.addEventListener('change', utils.debounce(handlers.handleTrackTypeChange, CONFIG.UI.DEBOUNCE_DELAY));

        // Optimized playlist creation
        elements.createPlaylistButton.addEventListener('click', () => {
            handlers.handleCreatePlaylist();
        });

        // Optimized select all toggle handler
        if (elements.toggleSelectAll) {
            elements.toggleSelectAll.addEventListener('click', utils.debounce(() => {
                const isSelectingAll = elements.toggleSelectAll.querySelector('.select-all-text').textContent === 'SELECT ALL';
                ui.toggleAllAlbums(isSelectingAll);
            }, CONFIG.UI.DEBOUNCE_DELAY));
        }

        // Optimized scroll handling for album list
        if (elements.albumsList) {
            elements.albumsList.addEventListener('scroll', utils.throttle(() => {
                // Future implementation: Infinite scroll or virtual list
                // This is prepared for future enhancement
            }, CONFIG.UI.SCROLL_THROTTLE));
        }

        // Register cleanups
        registerCleanup(window, () => {
            if (state.pollMessageTimeout) {
                clearTimeout(state.pollMessageTimeout);
            }
            if (debugLogger.timeout) {
                clearTimeout(debugLogger.timeout);
                debugLogger.flush();
            }
        });

        ui.initializeFilterControls();
        ui.initializeSearchHistory();
        initializeHistoryDropdown();
    }

    // Enhanced image loading utilities
    const imageLoader = {
        observer: null,
        loadingImages: new Map(),
        imageCache: new Map(),
        
        initialize() {
            this.observer = new IntersectionObserver(
                (entries) => {
                    entries.forEach(entry => {
                        if (entry.isIntersecting) {
                            const imgElement = entry.target;
                            const url = imgElement.dataset.src;
                            if (url) {
                                this.loadImage(imgElement, url);
                            }
                            this.observer.unobserve(imgElement);
                        }
                    });
                },
                {
                    threshold: CONFIG.UI.IMAGES.LAZY_LOAD_THRESHOLD
                }
            );
        },
        
        async loadImage(imgElement, url, retryCount = 0) {
            // Check cache first
            if (this.imageCache.has(url)) {
                imgElement.src = this.imageCache.get(url);
                return;
            }
            
            // Prevent duplicate loading
            if (this.loadingImages.has(url)) {
                return this.loadingImages.get(url).then(blob => {
                    imgElement.src = URL.createObjectURL(blob);
                });
            }
            
            try {
                const loadPromise = fetch(url)
                    .then(response => response.blob())
                    .then(blob => {
                        const objectUrl = URL.createObjectURL(blob);
                        this.imageCache.set(url, objectUrl);
                        imgElement.src = objectUrl;
                        this.loadingImages.delete(url);
                        return blob;
                    });
                    
                this.loadingImages.set(url, loadPromise);
                await loadPromise;
                
            } catch (error) {
                console.error(`Error loading image: ${url}`, error);
                if (retryCount < CONFIG.UI.IMAGES.RETRY_ATTEMPTS) {
                    setTimeout(() => {
                        this.loadImage(imgElement, url, retryCount + 1);
                    }, CONFIG.UI.IMAGES.RETRY_DELAY);
                } else {
                    imgElement.src = CONFIG.UI.IMAGES.PLACEHOLDER;
                }
            }
        },
        
        observe(imgElement, url) {
            imgElement.src = CONFIG.UI.IMAGES.PLACEHOLDER;
            imgElement.dataset.src = url;
            this.observer.observe(imgElement);
        },
        
        cleanup() {
            if (this.observer) {
                this.observer.disconnect();
            }
            // Clean up object URLs
            this.imageCache.forEach(objectUrl => {
                URL.revokeObjectURL(objectUrl);
            });
            this.imageCache.clear();
            this.loadingImages.clear();
        }
    };

    // Initialize image loader
    imageLoader.initialize();

    // Add cleanup on page unload
    window.addEventListener('unload', () => {
        imageLoader.cleanup();
        virtualScroll.cleanup();
    });

    // Update the utils.loadImage function to use the new image loader
    utils.loadImage = (url) => {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => resolve(url);
            img.onerror = () => reject(new Error('Image load failed'));
            img.src = url;
        });
    };

    // Update the album card creation to use the new image loader
    const updateAlbumCard = (cardElement, album) => {
        // ... existing card setup code ...
        const imgElement = cardElement.querySelector('.album-thumbnail');
        if (imgElement) {
            const imageUrl = album.images?.[0]?.url || CONFIG.UI.IMAGES.PLACEHOLDER;
            imageLoader.observe(imgElement, imageUrl);
        }
        // ... rest of existing card setup code ...
    };

    // Add filter and sort utilities
    const albumFilters = {
        applyFilters(albums) {
            if (!state.filter.activeFilters.size) return albums;

            return albums.filter(album => {
                // Text search in album name or artist based on filter type
                if (state.filter.text) {
                    const searchText = state.filter.text.toLowerCase();
                    if (state.filter.type === 'album') {
                        if (!album.name.toLowerCase().includes(searchText)) {
                            return false;
                        }
                    } else if (state.filter.type === 'artist') {
                        if (!album.artist.toLowerCase().includes(searchText)) {
                            return false;
                        }
                    }
                }

                // Popularity filter
                const popularity = album.popularity || 0;
                if (state.filter.popularityOperator === 'gt') {
                    if (popularity < state.filter.popularityValue) {
                        return false;
                    }
                } else {
                    if (popularity > state.filter.popularityValue) {
                        return false;
                    }
                }

                return true;
            });
        },

        sortAlbums(albums) {
            const { field, direction } = state.sort;
            const multiplier = direction === 'asc' ? 1 : -1;

            return [...albums].sort((a, b) => {
                let valueA, valueB;

                switch (field) {
                    case 'name':
                        valueA = a.name.toLowerCase();
                        valueB = b.name.toLowerCase();
                        break;
                    case 'artist':
                        valueA = a.artist.toLowerCase();
                        valueB = b.artist.toLowerCase();
                        break;
                    case 'popularity':
                        valueA = a.popularity || 0;
                        valueB = b.popularity || 0;
                        break;
                    default:
                        return 0;
                }

                if (valueA < valueB) return -1 * multiplier;
                if (valueA > valueB) return 1 * multiplier;
                return 0;
            });
        }
    };

    // Add dropdown toggle functionality
    function initializeHistoryDropdown() {
        const dropdownButton = document.getElementById('historyDropdownButton');
        const dropdown = document.getElementById('historyDropdown');
        
        if (!dropdownButton || !dropdown) {
            console.error('History dropdown elements not found');
            return;
        }

        // Toggle dropdown
        dropdownButton.addEventListener('click', (e) => {
            e.stopPropagation();
            const isHidden = dropdown.classList.contains('hidden');
            dropdown.classList.toggle('hidden');
            dropdownButton.classList.toggle('active', !isHidden);
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !dropdownButton.contains(e.target)) {
                dropdown.classList.add('hidden');
                dropdownButton.classList.remove('active');
            }
        });

        // Close dropdown when pressing Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                dropdown.classList.add('hidden');
                dropdownButton.classList.remove('active');
            }
        });

        // Handle clear history button
        const clearButton = dropdown.querySelector('.clear-history');
        if (clearButton) {
            clearButton.addEventListener('click', (e) => {
                e.stopPropagation();
                state.clearSearchHistory();
                ui.updateSearchHistory();
            });
        }
    }

    // Virtual scroll manager
    const virtualScroll = {
        visibleItems: new Set(),
        observer: null,
        containerHeight: 0,
        
        initialize(container) {
            this.container = container;
            this.setupIntersectionObserver();
            this.setupResizeObserver();
            
            // Throttled scroll handler
            container.addEventListener('scroll', utils.throttle(() => {
                this.updateVisibleItems();
            }, CONFIG.UI.SCROLL_THROTTLE));
        },
        
        setupIntersectionObserver() {
            this.observer = new IntersectionObserver(
                (entries) => {
                    entries.forEach(entry => {
                        const albumId = entry.target.dataset.albumId;
                        if (entry.isIntersecting) {
                            this.visibleItems.add(albumId);
                        } else {
                            this.visibleItems.delete(albumId);
                        }
                    });
                },
                {
                    root: this.container,
                    rootMargin: `${CONFIG.UI.VIRTUAL_SCROLL.BUFFER_SIZE * CONFIG.UI.VIRTUAL_SCROLL.ITEM_HEIGHT}px 0px`
                }
            );
        },
        
        setupResizeObserver() {
            const resizeObserver = new ResizeObserver(utils.throttle(() => {
                this.containerHeight = this.container.clientHeight;
                this.updateVisibleItems();
            }, 100));
            resizeObserver.observe(this.container);
        },
        
        updateVisibleItems() {
            const scrollTop = this.container.scrollTop;
            const viewportHeight = this.containerHeight;
            const bufferSize = CONFIG.UI.VIRTUAL_SCROLL.BUFFER_SIZE;
            const itemHeight = CONFIG.UI.VIRTUAL_SCROLL.ITEM_HEIGHT;
            
            const startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - bufferSize);
            const endIndex = Math.ceil((scrollTop + viewportHeight) / itemHeight) + bufferSize;
            
            Array.from(this.container.children).forEach((child, index) => {
                if (index >= startIndex && index <= endIndex) {
                    child.style.display = '';
                    this.observer.observe(child);
                } else {
                    child.style.display = 'none';
                    this.observer.unobserve(child);
                }
            });
        },
        
        cleanup() {
            if (this.observer) {
                this.observer.disconnect();
            }
            this.visibleItems.clear();
        }
    };

    // Initialize application
    initializeEventListeners();
    debugLogger.log('Application initialized', 'INFO');
}); 