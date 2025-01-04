// Initialize Socket.IO
const socket = io();

// DOM Elements
const scanForm = document.getElementById('scanForm');
const playlistForm = document.getElementById('playlistForm');
const messagesDiv = document.getElementById('messages');
const jsonFileSelect = document.getElementById('jsonFile');
const scanButton = document.getElementById('scanButton');
const createPlaylistButton = document.getElementById('createPlaylistButton');

// Socket.IO message handling
socket.on('message', function(data) {
    const messageDiv = document.createElement('div');
    messageDiv.textContent = data.data;
    
    // Add appropriate class based on message content
    if (data.data.toLowerCase().includes('error')) {
        messageDiv.classList.add('error');
    } else if (data.data.toLowerCase().includes('warning')) {
        messageDiv.classList.add('warning');
    } else if (data.data.toLowerCase().includes('success')) {
        messageDiv.classList.add('success');
    }
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
});

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
function addMessage(message, type = '') {
    const messageDiv = document.createElement('div');
    messageDiv.textContent = message;
    if (type) {
        messageDiv.classList.add(type);
    }
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Handle scan form submission
scanForm.addEventListener('submit', function(e) {
    e.preventDefault();
    
    const url = document.getElementById('url').value;
    const scanType = document.querySelector('input[name="scanType"]:checked').value;
    
    // Disable form elements during scan
    scanButton.disabled = true;
    addMessage(`Starting ${scanType} scan of ${url}...`);
    
    fetch('/api/scan', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            url: url,
            type: scanType
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            throw new Error(data.error);
        }
        addMessage('Scan completed successfully', 'success');
        loadJsonFiles();  // Refresh the JSON files list
    })
    .catch(error => {
        addMessage('Error during scan: ' + error.message, 'error');
    })
    .finally(() => {
        scanButton.disabled = false;
    });
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