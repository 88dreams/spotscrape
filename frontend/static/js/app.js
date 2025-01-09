document.addEventListener('DOMContentLoaded', function() {
    // Debug logging function
    async function debugLog(message, level = 'DEBUG') {
        try {
            await fetch('/api/debug-log', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message, level })
            });
        } catch (e) {
            console.error('Debug logging failed:', e);
        }
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

    // State
    let currentUrl = '';
    let selectedAlbums = new Set();
    let playlistCreationInProgress = false;

    // Function to update progress
    function updateProgress(percent, message) {
        progressBar.style.width = `${percent}%`;
        progressText.textContent = message;
    }

    // Function to show/hide progress bar
    function toggleProgress(show) {
        progressContainer.classList.toggle('hidden', !show);
    }

    // Function to reset the UI
    function resetUI() {
        selectedAlbums.clear();
        updateAlbumsList([]);
        playlistName.value = '';
        playlistDescription.value = '';
        toggleProgress(false);
        createPlaylistButton.disabled = false;
        createPlaylistButton.textContent = 'GO';
        // Clear any existing messages
        while (messagesDiv.firstChild) {
            messagesDiv.removeChild(messagesDiv.firstChild);
        }
    }

    // Function to add a message to the messages div
    function addMessage(message, isError = false) {
        const messageElement = document.createElement('div');
        messageElement.className = `message ${isError ? 'error' : 'success'} mb-2 p-2 rounded`;
        messageElement.textContent = message;
        messagesDiv.appendChild(messageElement);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    // Function to show completion popup
    function showCompletionPopup(message) {
        const popup = document.createElement('div');
        popup.className = 'fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-white p-4 rounded-lg shadow-lg z-50';
        popup.innerHTML = `
            <div class="text-center">
                <h3 class="text-lg font-bold mb-2">Success!</h3>
                <p>${message}</p>
                <button class="mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">OK</button>
            </div>
        `;
        document.body.appendChild(popup);

        const okButton = popup.querySelector('button');
        okButton.onclick = () => {
            popup.remove();
            resetUI();
        };
    }

    // Function to poll for messages
    async function pollMessages() {
        try {
            const response = await fetch('/api/messages');
            const data = await response.json();
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(message => {
                    addMessage(message);
                });
            }
        } catch (error) {
            console.error('Error polling messages:', error);
        }
    }

    // Start polling for messages every second
    setInterval(pollMessages, 1000);

    // Function to handle search
    async function handleSearch() {
        const url = urlInput.value.trim();
        if (!url) {
            alert('Please enter a URL');
            return;
        }

        currentUrl = url;
        resetUI();
        toggleProgress(true);
        updateProgress(0, 'Starting search...');

        const searchMethod = document.querySelector('input[name="searchMethod"]:checked').value;
        const endpoint = searchMethod === 'gpt' ? '/api/scan-webpage' : '/api/scan-url';

        try {
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

            const data = await response.json();
            if (data.error) {
                throw new Error(data.error);
            }

            if (searchMethod === 'gpt') {
                // For GPT search, start polling for results
                if (data.status === 'processing') {
                    pollForResults();
                }
            } else {
                // For URL search, update immediately
                if (data.albums) {
                    updateAlbumsList(data.albums);
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
        const pollInterval = setInterval(async () => {
            try {
                const response = await fetch('/api/results-gpt');
                const data = await response.json();
                
                if (data.status === 'complete') {
                    clearInterval(pollInterval);
                    toggleProgress(false);
                    if (data.albums) {
                        updateAlbumsList(data.albums);
                        addMessage('Search completed successfully');
                    } else {
                        throw new Error('No albums found');
                    }
                } else if (data.status === 'error') {
                    clearInterval(pollInterval);
                    toggleProgress(false);
                    throw new Error(data.error || 'Search failed');
                }
                // Continue polling if status is 'processing'
                
            } catch (error) {
                console.error('Polling error:', error);
                addMessage('Error during search: ' + error.message, true);
                clearInterval(pollInterval);
                toggleProgress(false);
                updateAlbumsList([]); // Clear albums list on error
            }
        }, 1000); // Poll every second
    }

    // Function to update albums list
    function updateAlbumsList(albums) {
        albumsList.innerHTML = '';
        selectedAlbums.clear();

        if (!albums || albums.length === 0) {
            return; // Early return if no albums
        }

        albums.forEach(album => {
            const card = document.createElement('div');
            card.className = 'album-card';
            card.innerHTML = `
                <div class="flex items-start">
                    <input type="checkbox" class="mt-1 mr-3" checked>
                    <div>
                        <div class="font-semibold">${album.artist}</div>
                        <div class="text-gray-600">${album.name}</div>
                        <div class="text-sm text-gray-500">Popularity: ${album.popularity}</div>
                    </div>
                </div>
            `;

            const checkbox = card.querySelector('input[type="checkbox"]');
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    selectedAlbums.add(album.id);
                    card.classList.add('selected');
                } else {
                    selectedAlbums.delete(album.id);
                    card.classList.remove('selected');
                }
            });

            // Initially select the album
            selectedAlbums.add(album.id);
            card.classList.add('selected');

            albumsList.appendChild(card);
        });
    }

    // Event Listeners
    searchButton.addEventListener('click', handleSearch);
    allTracksSwitch.addEventListener('change', handleTrackTypeChange);
    popularTracksSwitch.addEventListener('change', handleTrackTypeChange);
    createPlaylistButton.addEventListener('click', handleCreatePlaylist);

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
            if (currentUrl) {
                const url = new URL(currentUrl);
                domain = url.hostname.replace('www.', '');
            }
        } catch (error) {
            console.error('Invalid URL:', currentUrl);
        }
        const date = new Date().toLocaleDateString();
        const time = new Date().toLocaleTimeString();
        return `${domain} - ${date} ${time}`;
    }
}); 