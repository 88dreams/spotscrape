document.addEventListener('DOMContentLoaded', function() {
    // Debug logging optimization
    const debugLogQueue = [];
    let debugLogTimeout = null;
    const DEBUG_LOG_BATCH_DELAY = 1000; // 1 second batching
    const DEBUG_LOG_MAX_BATCH = 50; // Maximum logs per batch

    async function flushDebugLogs() {
        if (debugLogQueue.length === 0) return;
        
        const logsToSend = debugLogQueue.splice(0, DEBUG_LOG_MAX_BATCH);
        try {
            await fetch('/api/debug-log', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ logs: logsToSend })
            });
        } catch (e) {
            console.error('Debug logging failed:', e);
            // On failure, add important logs back to queue
            const importantLogs = logsToSend.filter(log => log.level === 'ERROR' || log.level === 'WARN');
            debugLogQueue.unshift(...importantLogs);
        }
        
        if (debugLogQueue.length > 0) {
            // Schedule next batch if there are remaining logs
            debugLogTimeout = setTimeout(flushDebugLogs, DEBUG_LOG_BATCH_DELAY);
        }
    }

    async function debugLog(message, level = 'DEBUG') {
        debugLogQueue.push({ message, level, timestamp: Date.now() });
        
        // Start batch processing if not already scheduled
        if (!debugLogTimeout) {
            debugLogTimeout = setTimeout(flushDebugLogs, DEBUG_LOG_BATCH_DELAY);
        }
        
        // Immediately log errors to console
        if (level === 'ERROR') {
            console.error(message);
        }
    }

    // Cleanup function for event listeners and intervals
    const cleanupFunctions = new Set();

    function addCleanup(fn) {
        cleanupFunctions.add(fn);
    }

    // Safe event listener addition with automatic cleanup
    function addSafeEventListener(element, event, handler) {
        element.addEventListener(event, handler);
        addCleanup(() => element.removeEventListener(event, handler));
    }

    // Elements
    const urlInput = document.getElementById('urlInput');
    const searchButton = document.getElementById('searchButton');
    const albumsList = document.getElementById('albumsList');
    const allTracksSwitch = document.getElementById('allTracksSwitch');
    const popularTracksSwitch = document.getElementById('popularTracksSwitch');
    const playlistName = document.getElementById('playlistName');
    const playlistDescription = document.getElementById('playlistDescription');
    const createPlaylistButton = document.getElementById('createPlaylistButton');
    const messagesDiv = document.getElementById('messages');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');
    const searchMethodRadios = document.querySelectorAll('input[name="searchMethod"]');

    // Verify elements are found
    if (!searchButton || !urlInput) {
        console.error('Critical elements not found:', {
            searchButton: !!searchButton,
            urlInput: !!urlInput
        });
        return;
    }

    // Initialize event listeners first
    function initializeEventListeners() {
        // Search button click
        addSafeEventListener(searchButton, 'click', handleSearch);
        
        // URL input enter key
        addSafeEventListener(urlInput, 'keypress', (e) => {
            if (e.key === 'Enter') {
                handleSearch();
            }
        });

        // Track type switches
        addSafeEventListener(allTracksSwitch, 'change', handleTrackTypeChange);
        addSafeEventListener(popularTracksSwitch, 'change', handleTrackTypeChange);
        
        // Create playlist button
        addSafeEventListener(createPlaylistButton, 'click', handleCreatePlaylist);

        // Debug log initialization
        debugLog('Event listeners initialized', 'INFO');
    }

    // State management with validation and error boundaries
    const state = {
        currentUrl: '',
        selectedAlbums: new Set(),
        playlistCreationInProgress: false,
        isPolling: false,
        pollMessageTimeout: null,
        
        setUrl(url) {
            this.currentUrl = url;
            debugLog(`URL updated: ${url}`, 'INFO');
        },
        
        addSelectedAlbum(id) {
            if (!id) {
                debugLog('Attempted to add invalid album ID', 'WARN');
                return;
            }
            this.selectedAlbums.add(id);
            debugLog(`Album selected: ${id}`, 'INFO');
        },
        
        removeSelectedAlbum(id) {
            if (!id) {
                debugLog('Attempted to remove invalid album ID', 'WARN');
                return;
            }
            this.selectedAlbums.delete(id);
            debugLog(`Album deselected: ${id}`, 'INFO');
        },
        
        clearSelectedAlbums() {
            this.selectedAlbums.clear();
            debugLog('Selected albums cleared', 'INFO');
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
            debugLog(`Playlist creation status: ${inProgress}`, 'INFO');
        },

        getSelectedAlbumsCount() {
            return this.selectedAlbums.size;
        },

        getSelectedAlbumsArray() {
            return Array.from(this.selectedAlbums);
        }
    };

    // Remove redundant state variables
    const MAX_MESSAGES = 50; // This can stay as a constant

    // Update functions to use state object
    function resetUI() {
        state.clearSelectedAlbums();
        updateAlbumsList([]);
        playlistName.value = '';
        playlistDescription.value = '';
        toggleProgress(false);
        createPlaylistButton.disabled = false;
        createPlaylistButton.textContent = 'GO';
        messagesDiv.innerHTML = '';
    }

    function toggleProgress(show) {
        progressContainer.classList.toggle('hidden', !show);
        if (show) {
            startMessagePolling();
        } else {
            stopMessagePolling();
        }
    }

    function startMessagePolling(initialDelay = 1000) {
        if (state.isPolling) return;
        state.setPolling(true);
        let delay = initialDelay;
        
        async function poll() {
            if (!state.isPolling) return;
            
            try {
                const response = await fetch('/api/messages');
                const data = await response.json();
                if (data.messages && data.messages.length > 0) {
                    const fragment = document.createDocumentFragment();
                    data.messages.forEach(message => {
                        const messageElement = document.createElement('div');
                        messageElement.className = 'message success mb-2 p-2 rounded';
                        messageElement.textContent = message;
                        fragment.appendChild(messageElement);
                    });
                    messagesDiv.appendChild(fragment);
                    messagesDiv.scrollTop = messagesDiv.scrollHeight;
                    
                    delay = initialDelay;
                } else {
                    delay = Math.min(delay * 1.5, 5000);
                }
            } catch (error) {
                console.error('Error polling messages:', error);
                delay = Math.min(delay * 2, 5000);
            }

            if (state.isPolling) {
                state.pollMessageTimeout = setTimeout(poll, delay);
            }
        }

        poll();
    }

    function stopMessagePolling() {
        state.setPolling(false);
    }

    // Update handleSearch to use state
    async function handleSearch() {
        const url = urlInput.value.trim();
        if (!url) {
            addMessage('Please enter a URL', true);
            return;
        }

        if (!isValidUrl(url)) {
            addMessage('Invalid URL', true);
            searchButton.textContent = 'Reset';
            searchButton.classList.add('reset');
            searchButton.onclick = resetSearch;
            return;
        }

        state.setUrl(url);
        resetUI();
        toggleProgress(true);
        updateProgress(10, 'Starting search...');

        const searchMethod = document.querySelector('input[name="searchMethod"]:checked').value;
        const endpoint = searchMethod === 'gpt' ? '/api/scan-webpage' : '/api/scan-url';

        try {
            updateProgress(20, 'Sending request...');
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url })
            });

            if (!response.ok) {
                throw new Error('Search failed');
            }

            updateProgress(30, 'Processing response...');
            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }

            if (searchMethod === 'gpt') {
                // For GPT search, start polling for results
                if (data.status === 'processing') {
                    updateProgress(40, 'GPT processing started...');
                    pollForResults();
                }
            } else {
                // For URL search, update immediately
                if (data.albums) {
                    updateProgress(90, 'Finalizing results...');
                    updateAlbumsList(data.albums);
                    updateProgress(100, 'Search completed successfully');
                    addMessage('Search completed successfully');
                } else {
                    throw new Error('No albums found');
                }
            }

        } catch (error) {
            console.error('Search error:', error);
            addMessage('Error during search: ' + error.message, true);
            updateAlbumsList([]); // Clear albums list on error
        } finally {
            if (searchMethod !== 'gpt') {
                toggleProgress(false);
            }
        }
    }

    // Function to poll for GPT search results
    async function pollForResults() {
        let progressValue = 40;
        let delay = 1000;
        let pollTimeout;

        const poll = async () => {
            try {
                // Batch progress updates
                if (progressValue < 90) {
                    progressValue = Math.min(progressValue + 2, 90);
                    requestAnimationFrame(() => {
                        updateProgress(progressValue, 'Processing content...');
                    });
                }
                
                const response = await fetch('/api/results-gpt');
                const data = await response.json();
                
                if (data.status === 'complete') {
                    if (data.albums) {
                        requestAnimationFrame(() => {
                            updateProgress(100, 'Search completed successfully');
                            updateAlbumsList(data.albums);
                            addMessage('Search completed successfully');
                            toggleProgress(false);
                        });
                    } else {
                        throw new Error('No albums found');
                    }
                    return; // Stop polling
                } else if (data.status === 'error') {
                    throw new Error(data.error || 'Search failed');
                }
                
                // Continue polling with exponential backoff
                delay = Math.min(delay * 1.5, 5000);
                pollTimeout = setTimeout(poll, delay);
                
            } catch (error) {
                console.error('Polling error:', error);
                addMessage('Error during search: ' + error.message, true);
                updateAlbumsList([]); // Clear albums list on error
                toggleProgress(false);
            }
        };

        // Start polling
        poll();

        // Cleanup function
        return () => {
            if (pollTimeout) {
                clearTimeout(pollTimeout);
            }
        };
    }

    // Create a template element for album cards (performance optimization)
    const albumCardTemplate = document.createElement('template');
    albumCardTemplate.innerHTML = `
        <div class="album-card">
            <div class="album-card-inner">
                <input type="checkbox" class="album-checkbox" checked>
                <img class="album-thumbnail">
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

    // Function to update albums list with optimized rendering
    function updateAlbumsList(albums) {
        // Clear existing content and selection
        albumsList.innerHTML = '';
        state.clearSelectedAlbums();

        if (!albums || albums.length === 0) {
            return;
        }

        // Create document fragment for batch DOM update
        const fragment = document.createDocumentFragment();
        
        // Reuse template for each album card
        albums.forEach(album => {
            const card = albumCardTemplate.content.cloneNode(true).firstElementChild;
            const img = card.querySelector('img');
            const artistDiv = card.querySelector('.album-artist');
            const artistTooltip = card.querySelector('.album-artist + .tooltip-text');
            const titleDiv = card.querySelector('.album-title');
            const titleTooltip = card.querySelector('.album-title + .tooltip-text');
            const popularityDiv = card.querySelector('.text-sm');
            const checkbox = card.querySelector('input[type="checkbox"]');

            // Set content
            img.src = album.images && album.images.length > 0 
                ? album.images[0].url 
                : 'https://placehold.co/64x64?text=Album';
            img.alt = album.name;
            artistDiv.textContent = album.artist;
            artistTooltip.textContent = album.artist;
            titleDiv.textContent = album.name;
            titleTooltip.textContent = album.name;
            popularityDiv.textContent = `Popularity: ${album.popularity}`;

            // Add checkbox event listener
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    state.addSelectedAlbum(album.id);
                    card.classList.add('selected');
                } else {
                    state.removeSelectedAlbum(album.id);
                    card.classList.remove('selected');
                }
            });

            // Initially select the album
            state.addSelectedAlbum(album.id);
            card.classList.add('selected');

            fragment.appendChild(card);
        });

        // Batch DOM update
        albumsList.appendChild(fragment);
    }

    // Event Listeners
    searchButton.addEventListener('click', handleSearch);
    allTracksSwitch.addEventListener('change', handleTrackTypeChange);
    popularTracksSwitch.addEventListener('change', handleTrackTypeChange);
    createPlaylistButton.addEventListener('click', handleCreatePlaylist);

    // Function to handle playlist creation
    async function handleCreatePlaylist() {
        if (state.playlistCreationInProgress) {
            return;
        }

        if (state.getSelectedAlbumsCount() === 0) {
            addMessage('Please select at least one album', true);
            return;
        }

        state.setPlaylistCreationStatus(true);
        createPlaylistButton.disabled = true;
        createPlaylistButton.textContent = 'Creating...';
        toggleProgress(true);
        updateProgress(0, 'Starting playlist creation...');

        try {
            const response = await fetch('/api/create-playlist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    albums: state.getSelectedAlbumsArray(),
                    playlistName: playlistName.value || getDefaultPlaylistName(),
                    playlistDescription: playlistDescription.value,
                    includeAllTracks: allTracksSwitch.checked,
                    includePopularTracks: popularTracksSwitch.checked
                })
            });

            if (!response.ok) {
                throw new Error('Failed to create playlist');
            }

            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }

            showCompletionPopup('Playlist created successfully!');
            addMessage('Playlist created successfully!');

        } catch (error) {
            console.error('Playlist creation error:', error);
            addMessage('Error creating playlist: ' + error.message, true);
            createPlaylistButton.disabled = false;
            createPlaylistButton.textContent = 'GO';
        } finally {
            state.setPlaylistCreationStatus(false);
            toggleProgress(false);
        }
    }

    function handleTrackTypeChange(event) {
        const isAllTracks = event.target === allTracksSwitch;
        const otherSwitch = isAllTracks ? popularTracksSwitch : allTracksSwitch;
        
        if (event.target.checked) {
            otherSwitch.checked = false;
        }
    }

    function getDefaultPlaylistName() {
        let domain = 'unknown-domain';
        try {
            if (state.currentUrl) {
                const url = new URL(state.currentUrl);
                domain = url.hostname.replace('www.', '');
            }
        } catch (error) {
            console.error('Invalid URL:', state.currentUrl);
        }
        const date = new Date().toLocaleDateString();
        const time = new Date().toLocaleTimeString();
        return `${domain} - ${date} ${time}`;
    }

    // Add cleanup for all event listeners
    addSafeEventListener(searchButton, 'click', handleSearch);
    addSafeEventListener(allTracksSwitch, 'change', handleTrackTypeChange);
    addSafeEventListener(popularTracksSwitch, 'change', handleTrackTypeChange);
    addSafeEventListener(createPlaylistButton, 'click', handleCreatePlaylist);

    // Initialize the application
    initializeEventListeners();

    // Cleanup on page unload
    window.addEventListener('unload', () => {
        // Clear all timeouts and intervals
        if (state.pollMessageTimeout) {
            clearTimeout(state.pollMessageTimeout);
        }
        if (debugLogTimeout) {
            clearTimeout(debugLogTimeout);
            // Flush any remaining logs
            flushDebugLogs();
        }
        
        // Execute all cleanup functions
        cleanupFunctions.forEach(cleanup => {
            try {
                cleanup();
            } catch (e) {
                console.error('Cleanup error:', e);
            }
        });
    });

    // Function to validate URL
    function isValidUrl(string) {
        try {
            new URL(string);
            return true;
        } catch (_) {
            return false;
        }
    }

    // Function to reset search
    function resetSearch() {
        urlInput.value = '';
        searchButton.textContent = 'Search';
        searchButton.classList.remove('reset');
        searchButton.onclick = handleSearch;
        messagesDiv.innerHTML = '';
    }

    // Function to update progress
    function updateProgress(percent, message) {
        progressBar.style.width = `${percent}%`;
        progressText.textContent = message;
        document.getElementById('progressPercent').textContent = `${Math.round(percent)}%`;
    }

    // Add message function
    function addMessage(message, isError = false) {
        const fragment = document.createDocumentFragment();
        const messageElement = document.createElement('div');
        messageElement.className = `message ${isError ? 'error' : 'success'} mb-2 p-2 rounded`;
        messageElement.textContent = message;
        fragment.appendChild(messageElement);
        messagesDiv.appendChild(fragment);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;

        // Cleanup old messages if exceeding maximum
        while (messagesDiv.children.length > MAX_MESSAGES) {
            messagesDiv.removeChild(messagesDiv.firstChild);
        }
    }
}); 