// Initialize Socket.IO with reconnection settings
const socket = io({
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    timeout: 60000
});

socket.on('connect', () => {
    console.log('Connected to server');
    addMessage('Connected to server', 'info');
});

socket.on('disconnect', (reason) => {
    console.log('Disconnected:', reason);
    addMessage(`Disconnected: ${reason}`, 'error');
    
    // Attempt to reconnect if not already trying
    if (reason === 'io server disconnect') {
        socket.connect();
    }
});

socket.on('connect_error', (error) => {
    console.log('Connection error:', error);
    addMessage(`Connection error: ${error.message}`, 'error');
});

socket.on('reconnect', (attemptNumber) => {
    console.log('Reconnected after', attemptNumber, 'attempts');
    addMessage(`Reconnected after ${attemptNumber} attempts`, 'info');
});

socket.on('reconnect_attempt', (attemptNumber) => {
    console.log('Attempting to reconnect:', attemptNumber);
    addMessage(`Attempting to reconnect (${attemptNumber})`, 'info');
});

// DOM Elements
const scanForm = document.getElementById('scanForm');
const playlistForm = document.getElementById('playlistForm');
const messagesDiv = document.getElementById('messages');
const consoleOutput = document.getElementById('consoleOutput');
const jsonFileSelect = document.getElementById('jsonFile');
const scanButton = document.getElementById('scanButton');
const saveJsonButton = document.getElementById('saveJsonButton');
const createPlaylistButton = document.getElementById('createPlaylistButton');
const clearMessagesButton = document.getElementById('clearMessages');
const customSaveOptions = document.querySelector('.custom-save-options');
const jsonFilePicker = document.getElementById('jsonFilePicker');
const customJsonPath = document.getElementById('customJsonPath');
const browseButton = document.getElementById('browseButton');

// Current scan results
let currentItems = [];
let currentFile = '';

// Socket.IO message handling
socket.on('message', function(data) {
    console.log('Received socket message:', data);
    
    // Create message div
    const messageDiv = document.createElement('div');
    messageDiv.textContent = data.data;
    messageDiv.classList.add(data.type || 'info');
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    // Update console output for found items
    if (data.data.includes('Artist:') || data.data.includes('Album:') || 
        data.data.includes('Found') || data.data.includes('Review found items')) {
        
        console.log('Processing found item or review message:', data.data);
        const consoleDiv = document.createElement('div');
        
        // Special handling for review prompt
        if (data.data.includes('Review found items')) {
            console.log('Creating review section');
            consoleDiv.className = 'review-section';
            consoleDiv.innerHTML = `
                <div class="review-header">${data.data}</div>
                <div class="review-actions mt-2">
                    <button class="btn btn-success btn-sm me-2 save-all">Save All Entries</button>
                    <button class="btn btn-warning btn-sm me-2 review-entries">Review Entries</button>
                    <button class="btn btn-danger btn-sm remove-all">Remove All</button>
                </div>
            `;
            
            // Add event listeners
            consoleDiv.querySelector('.save-all').addEventListener('click', () => {
                console.log('Save all clicked');
                saveReviewedItems(currentItems);
            });
            
            consoleDiv.querySelector('.review-entries').addEventListener('click', () => {
                console.log('Review entries clicked');
                showReviewDialog(currentItems);
            });
            
            consoleDiv.querySelector('.remove-all').addEventListener('click', () => {
                console.log('Remove all clicked');
                if (confirm('Are you sure you want to remove all entries?')) {
                    currentItems = [];
                    addMessage('All entries removed', 'warning');
                }
            });
        } else {
            // Regular item display
            console.log('Creating found item entry');
            consoleDiv.textContent = data.data;
            consoleDiv.className = 'found-item';
            
            // If this is an artist/album entry, add it to the current items
            if (data.data.includes('Artist:') || data.data.includes('Album:')) {
                const lines = data.data.split('\n');
                const item = {};
                lines.forEach(line => {
                    if (line.includes('Artist:')) {
                        item.artist = line.split('Artist:')[1].trim();
                    } else if (line.includes('Album:')) {
                        item.album = line.split('Album:')[1].trim();
                    } else if (line.includes('Spotify URL:')) {
                        item.spotify_url = line.split('Spotify URL:')[1].trim();
                    }
                });
                if (Object.keys(item).length > 0) {
                    currentItems.push(item);
                }
            }
        }
        
        consoleOutput.appendChild(consoleDiv);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    }
    
    // If this is a completion message, show the review options
    if (data.data.includes('Scan completed successfully')) {
        console.log('Scan completed, showing review options');
        if (currentItems.length > 0) {
            const reviewSection = document.createElement('div');
            reviewSection.className = 'review-section mt-3';
            reviewSection.innerHTML = `
                <div class="alert alert-success">
                    <h5>Scan completed! Found ${currentItems.length} items.</h5>
                    <div class="mt-2">
                        <button class="btn btn-primary btn-sm me-2 review-items">Review Items</button>
                        <button class="btn btn-success btn-sm me-2 save-all">Save All</button>
                        <button class="btn btn-danger btn-sm clear-items">Clear All</button>
                    </div>
                </div>
            `;
            
            reviewSection.querySelector('.review-items').addEventListener('click', () => {
                showReviewDialog(currentItems);
            });
            
            reviewSection.querySelector('.save-all').addEventListener('click', () => {
                saveReviewedItems(currentItems);
            });
            
            reviewSection.querySelector('.clear-items').addEventListener('click', () => {
                if (confirm('Are you sure you want to clear all items?')) {
                    currentItems = [];
                    consoleOutput.innerHTML = '';
                    addMessage('All items cleared', 'warning');
                }
            });
            
            consoleOutput.appendChild(reviewSection);
        }
    }
});

// Handle save type radio change
document.querySelectorAll('input[name="saveType"]').forEach(radio => {
    radio.addEventListener('change', function() {
        customSaveOptions.classList.toggle('d-none', this.value === 'default');
    });
});

// Handle browse button click
browseButton.addEventListener('click', function() {
    jsonFilePicker.click();
});

// Handle file picker change
jsonFilePicker.addEventListener('change', function() {
    if (this.files.length > 0) {
        customJsonPath.value = this.files[0].path;
    }
});

// Clear messages button
if (clearMessagesButton) {
    clearMessagesButton.addEventListener('click', function() {
        messagesDiv.innerHTML = '';
        consoleOutput.innerHTML = '';
    });
}

// Function to get available JSON files
async function getJsonFiles() {
    try {
        const response = await fetch('/get_json_files');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        return data.files;
    } catch (error) {
        console.error('Error getting JSON files:', error);
        return [];
    }
}

// Load available JSON files
async function loadJsonFiles() {
    const files = await getJsonFiles();
    const fileList = document.getElementById('jsonFile');
    if (!fileList) {
        console.error('Could not find jsonFile select element');
        return;
    }
    
    // Clear existing options except the placeholder
    while (fileList.options.length > 1) {
        fileList.remove(1);
    }
    
    files.forEach(file => {
        const option = document.createElement('option');
        option.value = file;
        option.textContent = file;
        fileList.appendChild(option);
    });
}

// Add message to the messages div
function addMessage(message, type = 'info') {
    const messageDiv = document.createElement('div');
    messageDiv.textContent = message;
    messageDiv.classList.add(type);
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Function to handle form submission
async function handleScan(event) {
    event.preventDefault();
    console.log('Form submitted');
    
    const url = document.getElementById('url').value.trim();
    const scanType = document.querySelector('input[name="scanType"]:checked').value;
    
    if (!url) {
        addMessage('Please enter a URL', 'error');
        return;
    }
    
    // Disable the scan button during scan
    scanButton.disabled = true;
    
    console.log(`Scanning ${scanType} for URL: ${url}`);
    addMessage(`Starting ${scanType} scan for URL: ${url}`, 'info');
    
    console.log('Sending fetch request...');
    try {
        const response = await fetch('/scan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url,
                type: scanType
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        if (data.success) {
            addMessage('Scan completed successfully!', 'success');
            if (data.items && data.items.length > 0) {
                showReviewDialog(data.items);
            } else {
                addMessage('No items found', 'warning');
            }
        } else {
            addMessage(`Error: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        addMessage(`Error: ${error.message}`, 'error');
    } finally {
        // Re-enable the scan button
        scanButton.disabled = false;
    }
}

// Function to show review dialog
function showReviewDialog(items) {
    const reviewSection = document.getElementById('review-section');
    const itemsList = document.getElementById('items-list');
    itemsList.innerHTML = '';
    
    items.forEach((item, index) => {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'review-item';
        itemDiv.innerHTML = `
            <input type="checkbox" id="item-${index}" checked>
            <label for="item-${index}">
                Artist: ${item.artist}<br>
                Album: ${item.album}<br>
                Spotify URL: ${item.spotify_url}
            </label>
        `;
        itemsList.appendChild(itemDiv);
    });
    
    reviewSection.style.display = 'block';
    
    // Add event listeners for review buttons
    document.getElementById('save-all').onclick = () => saveItems(items);
    document.getElementById('remove-all').onclick = () => {
        itemsList.innerHTML = '';
        reviewSection.style.display = 'none';
    };
}

// Function to save reviewed items
async function saveItems(items) {
    const checkedItems = Array.from(document.querySelectorAll('.review-item input:checked'))
        .map(checkbox => items[parseInt(checkbox.id.split('-')[1])]);
    
    if (checkedItems.length === 0) {
        addMessage('No items selected to save', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/save_items', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                items: checkedItems
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        if (data.success) {
            addMessage('Items saved successfully!', 'success');
            document.getElementById('review-section').style.display = 'none';
            loadJsonFiles();  // Refresh the file list
        } else {
            addMessage(`Error saving items: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        addMessage(`Error saving items: ${error.message}`, 'error');
    }
}

// Handle save JSON button
saveJsonButton.addEventListener('click', function() {
    const saveType = document.querySelector('input[name="saveType"]:checked').value;
    if (saveType === 'custom' && !customJsonPath.value) {
        addMessage('Please select a save location', 'error');
        return;
    }
    
    saveReviewedItems(currentItems, saveType === 'custom' ? customJsonPath.value : null);
});

// Handle scan form submission
scanForm.addEventListener('submit', handleScan);

// Handle playlist form submission
playlistForm.addEventListener('submit', function(e) {
    e.preventDefault();
    
    const jsonFile = jsonFileSelect.value;
    const playlistName = document.getElementById('playlistName').value;
    
    if (!jsonFile) {
        addMessage('Please select a JSON file', 'error');
        return;
    }
    
    // Disable form elements during playlist creation
    createPlaylistButton.disabled = true;
    addMessage('Creating playlist...');
    
    fetch('/api/playlist', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            file: jsonFile,
            name: playlistName
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            throw new Error(data.error);
        }
        addMessage('Playlist created successfully', 'success');
        if (data.playlist_id) {
            const playlistUrl = `https://open.spotify.com/playlist/${data.playlist_id}`;
            addMessage(`Open playlist: ${playlistUrl}`, 'success');
        }
    })
    .catch(error => {
        addMessage('Error creating playlist: ' + error.message, 'error');
    })
    .finally(() => {
        createPlaylistButton.disabled = false;
    });
});

// Load JSON files when the page loads
document.addEventListener('DOMContentLoaded', loadJsonFiles); 