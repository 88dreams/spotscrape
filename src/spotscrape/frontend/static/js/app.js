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
            SCAN_URL: '/api/scan-url',
            SCAN_GPT: '/api/scan-webpage',
            CREATE_PLAYLIST: '/api/create-playlist',
            GPT_RESULTS: '/api/results-gpt'
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
        searchButton: document.getElementById('searchButton'),
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
        searchMethodRadios: document.querySelectorAll('input[name="searchMethod"]')
    };

    // Validate critical elements
    if (!elements.searchButton || !elements.urlInput) {
        console.error('Critical elements missing:', {
            searchButton: !!elements.searchButton,
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
        }
    };

    // Template optimization with DocumentFragment
    const templates = {
        albumCard: (() => {
            const template = document.createElement('template');
            template.innerHTML = `
        <div class="album-card">
            <div class="album-card-inner">
                <input type="checkbox" class="album-checkbox" checked>
                        <img class="album-thumbnail" loading="lazy">
                <div class="album-info">
                    <div class="tooltip-container">
                        <div class="album-artist font-semibold text-truncate"></div>
                        <span class="tooltip-text"></span>
                    </div>
                    <div class="tooltip-container">
                        <div class="album-title text-gray-600 text-truncate"></div>
                        <span class="tooltip-text"></span>
                    </div>
                    <div class="text-sm text-gray-500 text-truncate"></div>
                </div>
            </div>
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

        updateAlbumsList(albums) {
            if (!albums?.length) {
                elements.albumsList.innerHTML = '';
                state.clearSelectedAlbums();
            return;
        }

        const fragment = document.createDocumentFragment();
        
        albums.forEach(album => {
                const card = templates.albumCard.content.cloneNode(true);
                const cardElement = card.firstElementChild;
                const img = cardElement.querySelector('img');
                const artistDiv = cardElement.querySelector('.album-artist');
                const artistTooltip = cardElement.querySelector('.album-artist + .tooltip-text');
                const titleDiv = cardElement.querySelector('.album-title');
                const titleTooltip = cardElement.querySelector('.album-title + .tooltip-text');
                const popularityDiv = cardElement.querySelector('.text-sm');
                const checkbox = cardElement.querySelector('input[type="checkbox"]');

                img.src = album.images?.[0]?.url || 'https://placehold.co/64x64?text=Album';
            img.alt = album.name;
            artistDiv.textContent = album.artist;
            artistTooltip.textContent = album.artist;
            titleDiv.textContent = album.name;
            titleTooltip.textContent = album.name;
            popularityDiv.textContent = `Popularity: ${album.popularity}`;

            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    state.addSelectedAlbum(album.id);
                        cardElement.classList.add('selected');
                } else {
                    state.removeSelectedAlbum(album.id);
                        cardElement.classList.remove('selected');
                }
            });

            state.addSelectedAlbum(album.id);
                cardElement.classList.add('selected');
            fragment.appendChild(card);
        });

            requestAnimationFrame(() => {
                elements.albumsList.innerHTML = '';
                elements.albumsList.appendChild(fragment);
            });
        },

        startMessagePolling(initialDelay = CONFIG.POLLING.MIN_DELAY) {
            if (state.isPolling) return;
            state.setPolling(true);
            let delay = initialDelay;
            
            const poll = async () => {
                if (!state.isPolling) return;
                
                try {
                    const response = await fetch(CONFIG.ENDPOINTS.MESSAGES);
                    const data = await response.json();
                    
                    if (data.messages?.length > 0) {
                        const fragment = document.createDocumentFragment();
                        data.messages.forEach(message => {
                            const messageElement = templates.message.content.cloneNode(true).firstElementChild;
                            messageElement.textContent = message;
                            messageElement.classList.add('success');
                            fragment.appendChild(messageElement);
                        });
                        
                        requestAnimationFrame(() => {
                            elements.messagesDiv.appendChild(fragment);
                            elements.messagesDiv.scrollTop = elements.messagesDiv.scrollHeight;
                        });
                        
                        delay = initialDelay;
                    } else {
                        delay = Math.min(delay * CONFIG.POLLING.BACKOFF_RATE, CONFIG.POLLING.MAX_DELAY);
                    }
                } catch (error) {
                    console.error('Error polling messages:', error);
                    delay = Math.min(delay * CONFIG.POLLING.BACKOFF_RATE, CONFIG.POLLING.MAX_DELAY);
                }

                if (state.isPolling) {
                    state.pollMessageTimeout = setTimeout(poll, delay);
                }
            };

            poll();
        },

        stopMessagePolling() {
            state.setPolling(false);
        }
    };

    // Event handlers with debouncing and throttling
    const handlers = {
        async handleSearch() {
            try {
                const url = elements.urlInput.value.trim();
                if (!this.isValidUrl(url)) {
                    ui.addMessage('Please enter a valid URL', true);
                    return;
                }

                state.setUrl(url);
                ui.resetUI();
                ui.toggleProgress(true);
                
                const searchMethod = Array.from(elements.searchMethodRadios).find(radio => radio.checked)?.value;
                const endpoint = searchMethod === 'gpt' ? CONFIG.ENDPOINTS.SCAN_GPT : CONFIG.ENDPOINTS.SCAN_URL;
                
                debugLogger.log(`Starting ${searchMethod} search for URL: ${url}`, 'INFO');
                
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });

                debugLogger.log(`Got response with status: ${response.status}`, 'INFO');
                
                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || 'Failed to process URL');
                }

                const data = await response.json();
                debugLogger.log(`Received response data: ${JSON.stringify(data)}`, 'INFO');
                
                if (searchMethod === 'gpt') {
                    // For GPT method, start polling for results
                    this.pollForResults();
                } else {
                    // For URL method, handle results immediately
                    debugLogger.log(`Processing URL scan results. Status: ${data.status}`, 'INFO');
                    
                    if (data.status === 'complete' && data.albums) {
                        debugLogger.log(`Found ${data.albums.length} albums`, 'INFO');
                        ui.updateAlbumsList(data.albums);
                        if (data.message) {
                            ui.addMessage(data.message);
                        }
                        ui.addMessage(`Found ${data.albums.length} albums`);
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
                    
                    const response = await fetch(CONFIG.ENDPOINTS.GPT_RESULTS);
                    const data = await response.json();
                    
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

        async handleCreatePlaylist() {
            if (state.playlistCreationInProgress) return;

        if (state.getSelectedAlbumsCount() === 0) {
                ui.addMessage('Please select at least one album', true);
            return;
        }

        state.setPlaylistCreationStatus(true);
            elements.createPlaylistButton.disabled = true;
            elements.createPlaylistButton.textContent = 'Creating...';
            ui.toggleProgress(true);
            ui.updateProgress(0, 'Starting playlist creation...');

            try {
                const response = await fetch(CONFIG.ENDPOINTS.CREATE_PLAYLIST, {
                method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    albums: state.getSelectedAlbumsArray(),
                        playlistName: elements.playlistName.value || this.getDefaultPlaylistName(),
                        playlistDescription: elements.playlistDescription.value,
                        includeAllTracks: elements.allTracksSwitch.checked,
                        includePopularTracks: elements.popularTracksSwitch.checked
                })
            });

                if (!response.ok) throw new Error('Failed to create playlist');

            const data = await response.json();
                if (data.error) throw new Error(data.error);

                this.showCompletionPopup('Playlist created successfully!');
                ui.addMessage('Playlist created successfully!');
                elements.createPlaylistButton.disabled = false;
                elements.createPlaylistButton.textContent = 'GO';

        } catch (error) {
            console.error('Playlist creation error:', error);
                ui.addMessage('Error creating playlist: ' + error.message, true);
                elements.createPlaylistButton.disabled = false;
                elements.createPlaylistButton.textContent = 'GO';
        } finally {
            state.setPlaylistCreationStatus(false);
                ui.toggleProgress(false);
            }
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
        }
    };

    // Event delegation for better performance
    function initializeEventListeners() {
        elements.searchButton.addEventListener('click', () => handlers.handleSearch());
        elements.urlInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handlers.handleSearch();
        });
        elements.allTracksSwitch.addEventListener('change', handlers.handleTrackTypeChange);
        elements.popularTracksSwitch.addEventListener('change', handlers.handleTrackTypeChange);
        elements.createPlaylistButton.addEventListener('click', () => handlers.handleCreatePlaylist());

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
    }

    // Initialize application
    initializeEventListeners();
    debugLogger.log('Application initialized', 'INFO');
}); 