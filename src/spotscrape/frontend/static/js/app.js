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
                const albumsList = document.getElementById('albumsList');
                if (albumsList) {
                    albumsList.innerHTML = '';
                }
                return;
            }

            const albumsList = document.getElementById('albumsList');
            if (!albumsList) {
                console.error('Albums list container not found');
                return;
            }

            const fragment = document.createDocumentFragment();
            albumsList.innerHTML = '';

            albums.forEach(album => {
                try {
                    const card = templates.albumCard.content.cloneNode(true);
                    const cardElement = card.firstElementChild;
                    
                    // Query all required elements
                    const elements = {
                        img: cardElement.querySelector('.album-thumbnail'),
                        artistDiv: cardElement.querySelector('.album-artist'),
                        artistTooltip: cardElement.querySelector('.album-artist + .tooltip-text'),
                        titleDiv: cardElement.querySelector('.album-title'),
                        titleTooltip: cardElement.querySelector('.album-title + .tooltip-text'),
                        popularityDiv: cardElement.querySelector('.album-popularity.text-sm'),
                        checkbox: cardElement.querySelector('.album-checkbox')
                    };

                    // Verify all elements exist
                    Object.entries(elements).forEach(([name, element]) => {
                        if (!element) {
                            throw new Error(`Required element '${name}' not found in album card template`);
                        }
                    });

                    // Set image with fallback
                    elements.img.src = album.images?.[0]?.url || 'https://placehold.co/80x80?text=Album';
                    elements.img.alt = `${album.name} album cover`;

                    // Set text content
                    elements.artistDiv.textContent = album.artist;
                    elements.artistTooltip.textContent = album.artist;
                    elements.titleDiv.textContent = album.name;
                    elements.titleTooltip.textContent = album.name;
                    
                    // Format popularity with emoji indicator
                    const popularityScore = album.popularity || 0;
                    const popularityEmoji = popularityScore >= 75 ? '🔥' : 
                                          popularityScore >= 50 ? '⭐' : 
                                          popularityScore >= 25 ? '👍' : '🎵';
                    elements.popularityDiv.textContent = `${popularityEmoji} Popularity: ${popularityScore}`;

                    // Handle selection
                    elements.checkbox.addEventListener('change', () => {
                        if (elements.checkbox.checked) {
                            state.addSelectedAlbum(album.id);
                            cardElement.classList.add('selected');
                        } else {
                            state.removeSelectedAlbum(album.id);
                            cardElement.classList.remove('selected');
                        }
                    });

                    fragment.appendChild(card);
                } catch (error) {
                    console.error('Error creating album card:', error);
                    this.addMessage(`Error creating album card for "${album.name}": ${error.message}`, true);
                }
            });

            albumsList.appendChild(fragment);
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
            let delay = CONFIG.POLLING.MIN_DELAY;
            let pollTimeout;

            const poll = async () => {
                try {
                    const response = await fetch(CONFIG.ENDPOINTS.GPT_RESULTS);
                    const data = await response.json();
                    
                    if (data.status === 'complete') {
                        if (data.albums) {
                            this.updateAlbumsList(data.albums);
                            this.toggleProgress(false);
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
                    this.addMessage('Error during search: ' + error.message, true);
                    this.updateAlbumsList([]);
                    this.toggleProgress(false);
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