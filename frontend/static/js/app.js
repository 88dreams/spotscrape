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
            // Fallback to console if debug endpoint fails
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

    // State
    let currentUrl = '';
    let selectedAlbums = new Set();
    let isPollingMessages = false;

    // Start message polling
    startMessagePolling();

    // Functions
    async function startMessagePolling() {
        if (isPollingMessages) return;
        isPollingMessages = true;
        
        async function pollMessages() {
            try {
                const response = await fetch('/api/messages');
                const data = await response.json();
                
                if (data.messages && data.messages.length > 0) {
                    data.messages.forEach(message => {
                        const p = document.createElement('p');
                        p.textContent = message;
                        p.className = 'message';
                        messagesDiv.appendChild(p);
                        messagesDiv.scrollTop = messagesDiv.scrollHeight;
                    });
                }
            } catch (error) {
                console.error('Error polling messages:', error);
            }
            
            if (isPollingMessages) {
                setTimeout(pollMessages, 1000);
            }
        }
        
        pollMessages();
    }

    // Event Listeners
    searchButton.addEventListener('click', handleSearch);
    allTracksSwitch.addEventListener('change', handleTrackTypeChange);
    popularTracksSwitch.addEventListener('change', handleTrackTypeChange);
    createPlaylistButton.addEventListener('click', handleCreatePlaylist);

    // Functions
    async function handleSearch() {
        const url = urlInput.value.trim();
        if (!url) return;

        currentUrl = url;
        const searchMethod = document.querySelector('input[name="searchMethod"]:checked').value;
        
        // Clear previous messages
        messagesDiv.innerHTML = '';
        
        try {
            searchButton.disabled = true;
            searchButton.textContent = 'Searching...';
            
            // Update endpoint for URL scanning
            const endpoint = searchMethod === 'url' ? 'scan-url' : 'scan-gpt';
            
            await debugLog(`Making request to /api/${endpoint} with URL: ${url}`);
            const response = await fetch(`/api/${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url })
            });

            await debugLog(`Response status: ${response.status}`);
            let data;
            try {
                const text = await response.text();
                await debugLog(`Raw response: ${text}`);
                data = JSON.parse(text);
            } catch (parseError) {
                await debugLog(`Error parsing response: ${parseError}`, 'ERROR');
                throw new Error('Invalid response from server');
            }
            await debugLog(`Response data: ${JSON.stringify(data)}`);

            if (!response.ok) {
                throw new Error(data.error || 'Search failed');
            }

            if (data.error) {
                throw new Error(data.error);
            }

            // Clear previous results
            albumsList.innerHTML = '';
            selectedAlbums.clear();

            // Check if we have results
            if (data.status === 'processing') {
                // Start polling for results
                pollForResults(searchMethod);
            }

        } catch (error) {
            await debugLog(`Search error: ${error.message}`, 'ERROR');
            const p = document.createElement('p');
            p.textContent = 'Error: ' + error.message;
            p.className = 'message error';
            messagesDiv.appendChild(p);
        } finally {
            searchButton.disabled = false;
            searchButton.textContent = 'Go';
        }
    }

    async function pollForResults(searchMethod) {
        try {
            await debugLog(`Polling results for ${searchMethod}`);
            const response = await fetch(`/api/results-${searchMethod}`);
            let data;
            try {
                const text = await response.text();
                await debugLog(`Raw poll response: ${text}`);
                data = JSON.parse(text);
            } catch (parseError) {
                await debugLog(`Error parsing poll response: ${parseError}`, 'ERROR');
                throw new Error('Invalid response from server');
            }
            await debugLog(`Poll data: ${JSON.stringify(data)}`);
            
            if (data.status === 'complete' && data.albums) {
                // Clear previous results first
                albumsList.innerHTML = '';
                selectedAlbums.clear();
                
                // Add each album to the list
                data.albums.forEach(album => {
                    addAlbumToList(album);
                });
            } else if (data.status === 'processing') {
                // Poll again in 1 second
                setTimeout(() => pollForResults(searchMethod), 1000);
            } else if (data.error) {
                throw new Error(data.error);
            } else if (data.status === 'error') {
                throw new Error(data.error || 'Unknown error occurred');
            }
        } catch (error) {
            await debugLog(`Polling error: ${error.message}`, 'ERROR');
            const p = document.createElement('p');
            p.textContent = 'Error: ' + error.message;
            p.className = 'message error';
            messagesDiv.appendChild(p);
        }
    }

    function addAlbumToList(album) {
        const div = document.createElement('div');
        div.style.display = 'flex';
        div.style.alignItems = 'center';
        div.style.padding = '4px 0';
        
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.style.marginRight = '10px';
        checkbox.id = `album-${album.id}`;
        checkbox.checked = true;
        selectedAlbums.add(album.id);
        
        const artistCol = document.createElement('div');
        artistCol.style.width = '250px';
        artistCol.style.paddingRight = '20px';
        artistCol.style.fontWeight = 'bold';
        artistCol.textContent = album.artist;
        
        const albumCol = document.createElement('div');
        albumCol.style.flex = '1';
        albumCol.textContent = album.name;
        
        div.appendChild(checkbox);
        div.appendChild(artistCol);
        div.appendChild(albumCol);
        
        checkbox.addEventListener('change', () => {
            if (checkbox.checked) {
                selectedAlbums.add(album.id);
            } else {
                selectedAlbums.delete(album.id);
            }
        });

        albumsList.appendChild(div);
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

    async function handleCreatePlaylist() {
        if (selectedAlbums.size === 0) {
            alert('Please select at least one album');
            return;
        }

        const name = playlistName.value || getDefaultPlaylistName();
        const description = playlistDescription.value || 
            `Created from ${currentUrl || 'unknown source'} on ${new Date().toLocaleString()}`;

        try {
            createPlaylistButton.disabled = true;
            createPlaylistButton.textContent = 'Creating...';

            const response = await fetch('/api/create-playlist', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    albums: Array.from(selectedAlbums),
                    playlistName: name,
                    playlistDescription: description,
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

            alert('Playlist created successfully!');

        } catch (error) {
            console.error('Playlist creation error:', error);
            alert('Error creating playlist: ' + error.message);
        } finally {
            createPlaylistButton.disabled = false;
            createPlaylistButton.textContent = 'GO';
        }
    }
}); 