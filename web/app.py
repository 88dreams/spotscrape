from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO
import sys
import os
import asyncio
from functools import partial

# Add the parent directory to the Python path so we can import from spotscrape.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from spotscrape import scan_spotify_links, scan_webpage, create_playlist, get_default_data_path

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

def emit_message(message):
    """Emit a message to the client"""
    socketio.emit('message', {'data': message})

class WebLogger:
    """Logger that sends messages to the web client"""
    def info(self, message):
        emit_message(message)
    
    def warning(self, message):
        emit_message(f"Warning: {message}")
    
    def error(self, message):
        emit_message(f"Error: {message}")

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/api/scan', methods=['POST'])
def scan():
    """Handle scan requests"""
    try:
        data = request.get_json()
        url = data.get('url')
        scan_type = data.get('type', 'url')  # 'url' or 'gpt'
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
            
        # Get the appropriate destination file
        destination_file = get_default_data_path(scan_type)
        
        # Create an event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            if scan_type == 'url':
                loop.run_until_complete(scan_spotify_links(url, destination_file))
            else:
                loop.run_until_complete(scan_webpage(url, destination_file))
                
            return jsonify({
                'success': True,
                'message': f'Scan completed successfully',
                'file': destination_file
            })
            
        finally:
            loop.close()
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlist', methods=['POST'])
def create_playlist_endpoint():
    """Handle playlist creation requests"""
    try:
        data = request.get_json()
        json_file = data.get('file')
        playlist_name = data.get('name')
        
        if not json_file:
            return jsonify({'error': 'JSON file path is required'}), 400
            
        # Create an event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(create_playlist(json_file, playlist_name))
            return jsonify({
                'success': True,
                'message': 'Playlist created successfully'
            })
        finally:
            loop.close()
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/files')
def list_files():
    """List available JSON files"""
    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SpotScrape_data")
        if not os.path.exists(data_dir):
            return jsonify({'files': []})
            
        files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
        return jsonify({'files': files})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    socketio.run(app, debug=True) 