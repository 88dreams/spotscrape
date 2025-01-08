import webview
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import threading
import os
import sys
import logging
import asyncio
from datetime import datetime
from spotscrape import (
    scan_spotify_links,
    scan_webpage,
    create_playlist,
    setup_logging,
    user_message
)
import json
from queue import Queue
import signal
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Configure debug logging
def setup_debug_logging():
    debug_logger = logging.getLogger('spot-debug')
    debug_logger.setLevel(logging.DEBUG)
    
    # Create logfiles directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logfiles")
    os.makedirs(log_dir, exist_ok=True)
    
    # Create or overwrite the debug log file
    log_path = os.path.join(log_dir, "spot-debug.log")
    if os.path.exists(log_path):
        os.remove(log_path)
        
    file_handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(formatter)
    debug_logger.addHandler(file_handler)
    
    return debug_logger

# Initialize debug logger
debug_logger = setup_debug_logging()

# Initialize Flask
app = Flask(__name__,
            static_folder='frontend/static',
            template_folder='frontend/templates')
CORS(app)

# Setup logging
logger, spotify_logger = setup_logging()

# Make logger global in spotscrape module
import spotscrape
spotscrape.logger = logger
spotscrape.spotify_logger = spotify_logger

# Store window reference
window = None

# Add after other global variables
scan_results = {
    'gpt': {'status': 'idle', 'albums': [], 'error': None},
    'url': {'status': 'idle', 'albums': [], 'error': None}
}

# Add after other global variables
message_queue = Queue()

# Modify the user_message function to send to GUI
def gui_message(msg: str, log_only: bool = False):
    debug_logger.info(f"GUI Message: {msg}")
    message_queue.put(msg)

# Override the user_message in spotscrape
spotscrape.user_message = gui_message

@app.route('/')
def index():
    debug_logger.debug("Serving index page")
    return render_template('index.html')

@app.route('/api/results-gpt')
def get_gpt_results():
    debug_logger.debug(f"Fetching GPT results: {scan_results['gpt']}")
    return jsonify(scan_results['gpt'])

@app.route('/api/results-url')
def get_url_results():
    debug_logger.debug(f"Fetching URL results: {scan_results['url']}")
    return jsonify(scan_results['url'])

@app.route('/api/scan-url', methods=['POST'])
def scan_url():
    """Renamed from scan-spotify to match frontend"""
    debug_logger.debug("Received scan-url request")
    try:
        data = request.json
        url = data.get('url')
        debug_logger.debug(f"Processing URL: {url}")
        
        if not url:
            debug_logger.error("No URL provided")
            return jsonify({'error': 'URL is required'}), 400
            
        # Create JSON directory if it doesn't exist
        json_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "JSON"))
        os.makedirs(json_dir, exist_ok=True)
        
        # Default file path
        destination_file = os.path.normpath(os.path.join(json_dir, "spotscrape_url.json"))
        debug_logger.debug(f"Using destination file: {destination_file}")
        
        # Reset results
        scan_results['url'] = {'status': 'processing', 'albums': [], 'error': None}
        
        # Run scan in a separate thread
        def run_scan():
            try:
                debug_logger.debug("Starting scan in new thread")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(scan_spotify_links(url, destination_file))
                
                # Load results from file
                if os.path.exists(destination_file):
                    with open(destination_file, 'r') as f:
                        albums_data = json.load(f)
                        # Format albums for frontend display
                        formatted_albums = []
                        for album in albums_data:
                            formatted_albums.append({
                                'id': album.get('Album ID', ''),
                                'artist': album.get('Artist', ''),
                                'name': album.get('Album', ''),
                                'popularity': album.get('Album Popularity', 0)
                            })
                        scan_results['url'] = {
                            'status': 'complete',
                            'albums': formatted_albums,
                            'error': None
                        }
                        debug_logger.debug(f"Loaded {len(formatted_albums)} albums from file")
                        # Just send a simple status message
                        gui_message(f"Found {len(formatted_albums)} albums")
                else:
                    scan_results['url'] = {
                        'status': 'error',
                        'albums': [],
                        'error': 'No results found'
                    }
                
                loop.close()
                debug_logger.debug("Scan completed successfully")
            except Exception as e:
                debug_logger.error(f"Error in scan thread: {str(e)}", exc_info=True)
                scan_results['url'] = {
                    'status': 'error',
                    'albums': [],
                    'error': str(e)
                }
        
        thread = threading.Thread(target=run_scan)
        thread.start()
        debug_logger.debug("Scan thread started")
        
        return jsonify({'status': 'processing'})
        
    except Exception as e:
        debug_logger.error(f"Error in scan-url endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan-gpt', methods=['POST'])
def scan_gpt():
    debug_logger.debug("Received scan-gpt request")
    try:
        data = request.json
        url = data.get('url')
        debug_logger.debug(f"Processing URL: {url}")
        
        if not url:
            debug_logger.error("No URL provided")
            return jsonify({'error': 'URL is required'}), 400
            
        # Create JSON directory if it doesn't exist
        json_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "JSON"))
        os.makedirs(json_dir, exist_ok=True)
        
        # Default file path
        destination_file = os.path.normpath(os.path.join(json_dir, "spotscrape_gpt.json"))
        debug_logger.debug(f"Using destination file: {destination_file}")
        
        # Reset results
        scan_results['gpt'] = {'status': 'processing', 'albums': [], 'error': None}
        
        # Run scan in a separate thread
        def run_scan():
            try:
                debug_logger.debug("Starting scan in new thread")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(scan_webpage(url, destination_file))
                
                # Load results from file
                if os.path.exists(destination_file):
                    with open(destination_file, 'r') as f:
                        albums_data = json.load(f)
                        scan_results['gpt'] = {
                            'status': 'complete',
                            'albums': albums_data,
                            'error': None
                        }
                        debug_logger.debug(f"Loaded {len(albums_data)} albums from file")
                else:
                    scan_results['gpt'] = {
                        'status': 'error',
                        'albums': [],
                        'error': 'No results found'
                    }
                
                loop.close()
                debug_logger.debug("Scan completed successfully")
            except Exception as e:
                debug_logger.error(f"Error in scan thread: {str(e)}", exc_info=True)
                scan_results['gpt'] = {
                    'status': 'error',
                    'albums': [],
                    'error': str(e)
                }
        
        thread = threading.Thread(target=run_scan)
        thread.start()
        debug_logger.debug("Scan thread started")
        
        return jsonify({'status': 'processing'})
        
    except Exception as e:
        debug_logger.error(f"Error in scan-gpt endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/create-playlist', methods=['POST'])
def create_new_playlist():
    debug_logger.debug("Received create-playlist request")
    try:
        data = request.json
        debug_logger.debug(f"Playlist creation data: {data}")
        
        album_ids = data.get('albums', [])
        playlist_name = data.get('playlistName', '')
        playlist_description = data.get('playlistDescription', '')
        include_all_tracks = data.get('includeAllTracks', True)
        include_popular_tracks = data.get('includePopularTracks', False)
        
        if not album_ids:
            debug_logger.error("No albums provided")
            return jsonify({'error': 'Album IDs are required'}), 400
            
        # Run playlist creation in a separate thread
        def run_creation():
            try:
                debug_logger.debug("Starting playlist creation in new thread")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Get Spotify client
                spotify = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
                    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
                    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
                    scope="playlist-modify-public playlist-modify-private"
                ))
                
                # Create playlist
                user_id = spotify.current_user()['id']
                playlist = spotify.user_playlist_create(
                    user=user_id,
                    name=playlist_name,
                    public=True,
                    description=playlist_description or f"Created by SpotScrape on {datetime.now().strftime('%Y-%m-%d')}"
                )
                
                # Add tracks
                track_uris = []
                for album_id in album_ids:
                    try:
                        album_tracks = spotify.album_tracks(album_id)
                        if include_popular_tracks:
                            # Find most popular track
                            most_popular = None
                            highest_popularity = -1
                            for track in album_tracks['items']:
                                track_info = spotify.track(track['id'])
                                popularity = track_info.get('popularity', 0)
                                if popularity > highest_popularity:
                                    highest_popularity = popularity
                                    most_popular = track
                            if most_popular:
                                track_uris.append(most_popular['uri'])
                        else:
                            # Add all tracks
                            track_uris.extend([track['uri'] for track in album_tracks['items']])
                    except Exception as e:
                        debug_logger.error(f"Error processing album {album_id}: {e}")
                        continue
                
                # Add tracks in batches of 100
                if track_uris:
                    for i in range(0, len(track_uris), 100):
                        batch = track_uris[i:i+100]
                        spotify.playlist_add_items(playlist['id'], batch)
                
                gui_message(f"Created playlist '{playlist_name}' with {len(track_uris)} tracks")
                debug_logger.debug("Playlist creation completed successfully")
                
            except Exception as e:
                debug_logger.error(f"Error in playlist creation thread: {str(e)}", exc_info=True)
                gui_message(f"Error creating playlist: {str(e)}")
                return jsonify({'error': str(e)}), 500
        
        thread = threading.Thread(target=run_creation)
        thread.start()
        debug_logger.debug("Playlist creation thread started")
        
        return jsonify({'message': 'Playlist creation started', 'status': 'processing'})
        
    except Exception as e:
        debug_logger.error(f"Error in create-playlist endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug-log', methods=['POST'])
def debug_log():
    try:
        data = request.json
        message = data.get('message')
        level = data.get('level', 'DEBUG')
        if level == 'ERROR':
            debug_logger.error(f"Frontend: {message}")
        else:
            debug_logger.debug(f"Frontend: {message}")
        return jsonify({'status': 'ok'})
    except Exception as e:
        debug_logger.error(f"Error logging debug message: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages')
def get_messages():
    """Endpoint to get queued messages"""
    messages = []
    while not message_queue.empty():
        messages.append(message_queue.get())
    return jsonify({'messages': messages})

def start_server():
    debug_logger.debug("Starting Flask server")
    app.run(port=5000, threaded=True)

if __name__ == '__main__':
    debug_logger.debug("Application starting")
    try:
        # Handle Ctrl+C gracefully
        def signal_handler(signum, frame):
            debug_logger.info("Received shutdown signal")
            if window:
                window.destroy()
            sys.exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)
        
        # Start Flask server in a separate thread
        t = threading.Thread(target=start_server)
        t.daemon = True
        t.start()
        debug_logger.debug("Flask server thread started")
        
        # Create and start webview window with close handler
        window = webview.create_window('SpotScrape', 'http://localhost:5000',
                                     width=1400, height=900)
        
        # Add close handler
        def on_closed():
            debug_logger.info("Window closed, shutting down")
            os._exit(0)
            
        window.events.closed += on_closed
        
        debug_logger.debug("WebView window created")
        webview.start()
        debug_logger.debug("WebView started")
        
    except Exception as e:
        debug_logger.error(f"Fatal error in main: {str(e)}", exc_info=True)
        sys.exit(1) 