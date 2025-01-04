// Initialize Socket.IO with error handling
const socket = io('http://localhost:5000', {
    transports: ['websocket', 'polling'],
    reconnectionAttempts: 5,
    reconnectionDelay: 1000,
    timeout: 60000
});

socket.on('connect', () => {
    console.log('Connected to server');
    addMessage('Connected to server', 'info');
});

socket.on('connect_error', (error) => {
    console.error('Connection error:', error);
    addMessage('Connection error: ' + error.message, 'error');
});

socket.on('disconnect', (reason) => {
    console.log('Disconnected:', reason);
    addMessage('Disconnected from server: ' + reason, 'warning');
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
    const messageDiv = document.createElement('div');
    messageDiv.textContent = data.data;
    messageDiv.classList.add(data.type || 'info');
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    // Update console output for found items
    if (data.data.includes('Artist:') || data.data.includes('Album:') || 
        data.data.includes('Found') || data.data.includes('Review')) {
        const consoleDiv = document.createElement('div');
        
        // Special handling for review prompt
        if (data.data.includes('Review')) {
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
                saveReviewedItems(currentItems);
            });
            
            consoleDiv.querySelector('.review-entries').addEventListener('click', () => {
                showReviewDialog(currentItems);
            });
            
            consoleDiv.querySelector('.remove-all').addEventListener('click', () => {
                if (confirm('Are you sure you want to remove all entries?')) {
                    currentItems = [];
                    addMessage('All entries removed', 'warning');
                }
            });
        } else {
            // Regular item display
            consoleDiv.textContent = data.data;
            if (data.data.includes('Artist:') || data.data.includes('Album:')) {
                consoleDiv.className = 'found-item';
            }
        }
        
        consoleOutput.appendChild(consoleDiv);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
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

// Load available JSON files
function loadJsonFiles() {
    fetch('/api/files')
        .then(response => response.json())
        .then(data => {
            jsonFileSelect.innerHTML = '<option value="">Select a file</option>';
            data.files.forEach(file => {
                const option = document.createElement('option');
                option.value = file;
                option.textContent = file;
                jsonFileSelect.appendChild(option);
            });
        })
        .catch(error => {
            console.error('Error loading JSON files:', error);
            addMessage('Error loading JSON files: ' + error.message, 'error');
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

// Show review dialog
function showReviewDialog(items) {
    const reviewDiv = document.createElement('div');
    reviewDiv.className = 'review-dialog';
    reviewDiv.innerHTML = `
        <div class="review-content">
            <h4>Review Found Items</h4>
            <div class="review-controls mb-3">
                <div class="btn-group">
                    <button class="btn btn-outline-primary btn-sm select-all">Select All</button>
                    <button class="btn btn-outline-primary btn-sm deselect-all">Deselect All</button>
                    <button class="btn btn-outline-danger btn-sm remove-selected">Remove Selected</button>
                </div>
            </div>
            <div class="items-list">
                ${items.map((item, index) => `
                    <div class="item" data-index="${index}">
                        <div class="d-flex align-items-center">
                            <input type="checkbox" class="form-check-input me-2" checked>
                            <div class="item-details flex-grow-1">
                                <div class="fw-bold">${item.artist || 'Unknown Artist'}</div>
                                <div class="text-muted small">${item.album || 'Unknown Album'}</div>
                                ${item.spotify_url ? `<div class="text-muted small">URL: ${item.spotify_url}</div>` : ''}
                            </div>
                            <button class="btn btn-outline-danger btn-sm remove-item" title="Remove this item">×</button>
                        </div>
                    </div>
                `).join('')}
            </div>
            <div class="review-summary mt-3 mb-3">
                <div class="alert alert-info">
                    <strong>Total Items:</strong> <span class="total-count">${items.length}</span>
                    <br>
                    <strong>Selected:</strong> <span class="selected-count">${items.length}</span>
                </div>
            </div>
            <div class="review-actions">
                <button class="btn btn-primary save-items">Save Selected Items</button>
                <button class="btn btn-secondary cancel-review">Cancel</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(reviewDiv);
    
    // Update counts
    function updateCounts() {
        const total = reviewDiv.querySelectorAll('.item').length;
        const selected = reviewDiv.querySelectorAll('.item input[type="checkbox"]:checked').length;
        reviewDiv.querySelector('.total-count').textContent = total;
        reviewDiv.querySelector('.selected-count').textContent = selected;
    }
    
    // Select/Deselect all
    reviewDiv.querySelector('.select-all').addEventListener('click', () => {
        reviewDiv.querySelectorAll('.item input[type="checkbox"]').forEach(checkbox => {
            checkbox.checked = true;
        });
        updateCounts();
    });
    
    reviewDiv.querySelector('.deselect-all').addEventListener('click', () => {
        reviewDiv.querySelectorAll('.item input[type="checkbox"]').forEach(checkbox => {
            checkbox.checked = false;
        });
        updateCounts();
    });
    
    // Remove selected items
    reviewDiv.querySelector('.remove-selected').addEventListener('click', () => {
        const itemsToRemove = Array.from(reviewDiv.querySelectorAll('.item input[type="checkbox"]:checked'))
            .map(checkbox => checkbox.closest('.item'));
        itemsToRemove.forEach(item => item.remove());
        updateCounts();
    });
    
    // Individual item removal
    reviewDiv.querySelectorAll('.remove-item').forEach(button => {
        button.addEventListener('click', () => {
            button.closest('.item').remove();
            updateCounts();
        });
    });
    
    // Checkbox change handler
    reviewDiv.querySelectorAll('.item input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', updateCounts);
    });
    
    // Handle save action
    reviewDiv.querySelector('.save-items').addEventListener('click', () => {
        const selectedItems = [];
        reviewDiv.querySelectorAll('.item').forEach((itemDiv, index) => {
            if (itemDiv.querySelector('input[type="checkbox"]').checked) {
                selectedItems.push(items[itemDiv.dataset.index]);
            }
        });
        
        if (selectedItems.length === 0) {
            addMessage('No items selected to save', 'warning');
            return;
        }
        
        currentItems = selectedItems;
        saveJsonButton.classList.remove('d-none');
        addMessage(`${selectedItems.length} items selected for saving`, 'info');
        reviewDiv.remove();
    });
    
    // Handle cancel
    reviewDiv.querySelector('.cancel-review').addEventListener('click', () => {
        if (confirm('Are you sure you want to cancel? All changes will be lost.')) {
            reviewDiv.remove();
        }
    });
    
    // Initial count update
    updateCounts();
}

// Save reviewed items
function saveReviewedItems(items, customPath = null) {
    const data = {
        items: items,
        file: customPath || currentFile
    };
    
    fetch('/api/review', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            throw new Error(data.error);
        }
        addMessage('Items saved successfully', 'success');
        loadJsonFiles();  // Refresh the JSON files list
        saveJsonButton.classList.add('d-none');
    })
    .catch(error => {
        addMessage('Error saving items: ' + error.message, 'error');
    });
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
scanForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    console.log('Form submitted'); // Debug log
    
    const urlInput = document.getElementById('url');
    const url = urlInput.value.trim();
    const scanType = document.querySelector('input[name="scanType"]:checked').value;
    
    if (!url) {
        addMessage('Please enter a URL to scan', 'error');
        return;
    }
    
    console.log(`Scanning ${scanType} for URL: ${url}`); // Debug log
    
    // Clear previous results but keep the URL
    consoleOutput.innerHTML = '';
    saveJsonButton.classList.add('d-none');
    
    // Disable only the scan button during scan
    scanButton.disabled = true;
    addMessage(`Starting ${scanType} scan of ${url}...`);
    
    try {
        console.log('Sending fetch request...'); // Debug log
        const response = await fetch('/api/scan', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url,
                type: scanType
            })
        });
        console.log('Received response:', response.status); // Debug log

        if (!response.ok) {
            const errorData = await response.json();
            console.error('Response not OK:', errorData); // Debug log
            throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        console.log('Scan response data:', data); // Debug log

        if (data.error) {
            throw new Error(data.error);
        }

        addMessage('Scan completed successfully', 'success');
        
        if (!data.items || data.items.length === 0) {
            addMessage('No items found in the scan', 'warning');
            return;
        }
        
        // Store current items and file
        currentItems = data.items;
        currentFile = data.file;
        
        // Show review dialog
        showReviewDialog(data.items);
        
    } catch (error) {
        console.error('Scan error:', error); // Debug log
        let errorMessage = error.message;
        
        // Try to parse the error response for more details
        try {
            const errorData = await error.response?.json();
            if (errorData?.traceback) {
                console.error('Error traceback:', errorData.traceback);
                errorMessage = errorData.error || errorMessage;
            }
        } catch (e) {
            console.error('Error parsing error response:', e);
        }
        
        addMessage(`Error during scan: ${errorMessage}`, 'error');
    } finally {
        scanButton.disabled = false;
    }
});

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