import webview
from flask import Flask, render_template, jsonify, request, Response
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
from spotscrape import SpotifySearchManager, PlaylistManager, WebContentExtractor, ContentProcessor
from functools import wraps

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

# Global progress queue for SSE
progress_queue = Queue()

# Modify the user_message function to send to GUI
def gui_message(msg: str, log_only: bool = False):
    debug_logger.info(f"GUI Message: {msg}")
    message_queue.put(msg)

# Override the user_message in spotscrape
spotscrape.user_message = gui_message

def send_progress(progress, message):
    """Helper function to send progress updates"""
    progress_queue.put({
        'progress': progress,
        'message': message,
        'timestamp': datetime.now().isoformat()
    })

def async_route(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapped

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
@async_route
async def scan_url():
    try:
        data = request.json
        url = data.get('url')
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        # Initialize managers with progress callbacks
        spotify_manager = SpotifySearchManager()
        spotify_manager.set_progress_callback(send_progress)
        web_extractor = WebContentExtractor()
        
        send_progress(10, "Starting URL scan...")
        content = await web_extractor.extract_content(url)
        
        send_progress(30, "Processing content...")
        album_ids = await spotify_manager.scan_spotify_links(content)
        
        if not album_ids:
            return jsonify({'error': 'No Spotify albums found on the page'}), 404
        
        send_progress(50, "Retrieving album information...")
        albums = []
        total_albums = len(album_ids)
        
        for i, album_id in enumerate(album_ids, 1):
            album_info = await spotify_manager.get_album_info(album_id)
            if album_info:
                albums.append({
                    'id': album_id,
                    'name': album_info.get('name', 'Unknown Album'),
                    'artist': album_info.get('artists', [{'name': 'Unknown Artist'}])[0]['name'],
                    'popularity': album_info.get('popularity', 0),
                    'images': album_info.get('images', []),
                    'tracks': [
                        {
                            'id': track['id'],
                            'name': track['name'],
                            'popularity': track.get('popularity', 0)
                        }
                        for track in album_info.get('tracks', {}).get('items', [])
                    ]
                })
            progress = 50 + (i / total_albums * 40)
            send_progress(progress, f"Retrieved album {i} of {total_albums}")
        
        send_progress(100, "Scan complete!")
        return jsonify({'albums': albums})

    except Exception as e:
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
                        # Format albums for frontend display
                        formatted_albums = []
                        for album in albums_data:
                            # Log the album data for debugging
                            debug_logger.debug(f"Processing album data: {json.dumps(album, indent=2)}")
                            
                            album_data = {
                                'id': album.get('Album ID', ''),
                                'artist': album.get('Artist', ''),
                                'name': album.get('Album', ''),
                                'popularity': album.get('Album Popularity', 0),
                                'images': album.get('Album Images', [])
                            }
                            # Log the formatted album data
                            debug_logger.debug(f"Formatted album data: {json.dumps(album_data, indent=2)}")
                            
                            formatted_albums.append(album_data)
                            
                        scan_results['gpt'] = {
                            'status': 'complete',
                            'albums': formatted_albums,
                            'error': None
                        }
                        debug_logger.debug(f"Loaded {len(formatted_albums)} albums from file")
                        gui_message(f"Found {len(formatted_albums)} albums")
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
@async_route
async def create_playlist():
    try:
        data = request.json
        albums = data.get('albums', [])
        playlist_name = data.get('playlistName', '')
        playlist_description = data.get('playlistDescription', '')
        include_all_tracks = data.get('includeAllTracks', True)
        include_popular_tracks = data.get('includePopularTracks', False)

        if not albums:
            return jsonify({'error': 'No albums selected'}), 400

        # Initialize managers with progress callbacks
        playlist_manager = PlaylistManager()
        playlist_manager.set_progress_callback(send_progress)
        spotify_manager = SpotifySearchManager()
        spotify_manager.set_progress_callback(send_progress)
        
        send_progress(10, "Initializing playlist creation...")
        playlist_id = await playlist_manager.create_playlist(
            name=playlist_name,
            description=playlist_description
        )
        
        if not playlist_id:
            return jsonify({'error': 'Failed to create playlist'}), 500
        
        send_progress(30, "Gathering tracks...")
        tracks_to_add = []
        total_albums = len(albums)
        
        for i, album_id in enumerate(albums, 1):
            album_info = await spotify_manager.get_album_info(album_id)
            if not album_info:
                continue
                
            album_tracks = album_info.get('tracks', {}).get('items', [])
            if include_popular_tracks:
                # Sort tracks by popularity and take the most popular one
                album_tracks.sort(key=lambda x: x.get('popularity', 0), reverse=True)
                album_tracks = album_tracks[:1]
            elif not include_all_tracks:
                # Take the first track as a default
                album_tracks = album_tracks[:1]
                
            tracks_to_add.extend([track['id'] for track in album_tracks])
            progress = 30 + (i / total_albums * 40)
            send_progress(progress, f"Processed album {i} of {total_albums}")
        
        if not tracks_to_add:
            return jsonify({'error': 'No tracks found to add'}), 400
        
        send_progress(70, "Adding tracks to playlist...")
        await playlist_manager.add_tracks_to_playlist(playlist_id, tracks_to_add)
        
        send_progress(100, "Playlist created successfully!")
        return jsonify({
            'status': 'success',
            'message': 'Playlist created successfully!',
            'playlist_id': playlist_id
        })

    except Exception as e:
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

@app.route('/api/playlist-progress')
def playlist_progress():
    def generate():
        while True:
            try:
                progress_data = progress_queue.get(timeout=30)  # 30 second timeout
                yield f"data: {json.dumps(progress_data)}\n\n"
            except Queue.Empty:
                # Send a keepalive message
                yield f"data: {json.dumps({'keepalive': True})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/scan-webpage', methods=['POST'])
async def scan_webpage_route():
    """Handle webpage scanning with GPT"""
    try:
        logger.debug("Received scan-webpage request")
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            logger.error("No URL provided in request")
            return jsonify({'error': 'No URL provided'}), 400

        logger.debug(f"Starting GPT scan for URL: {url}")
        gui_message("Starting GPT scan...")
        
        # Create JSON directory if it doesn't exist
        json_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "JSON"))
        os.makedirs(json_dir, exist_ok=True)
        
        # Default file path
        destination_file = os.path.normpath(os.path.join(json_dir, "spotscrape_gpt.json"))
        
        try:
            # Reset scan results
            scan_results['gpt'] = {'status': 'processing', 'albums': [], 'error': None}
            
            # Start the scan in a background task
            def run_scan():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    gui_message("Processing webpage content...")
                    results = loop.run_until_complete(scan_webpage(url, destination_file))
                    
                    # Update scan results
                    if results:
                        formatted_albums = []
                        for album in results:
                            formatted_albums.append({
                                'id': album.get('Album ID', ''),
                                'artist': album.get('Artist', ''),
                                'name': album.get('Album', ''),
                                'popularity': album.get('Album Popularity', 0),
                                'images': album.get('Album Images', [])
                            })
                        scan_results['gpt'] = {
                            'status': 'complete',
                            'albums': formatted_albums,
                            'error': None
                        }
                        gui_message(f"Found {len(formatted_albums)} albums")
                    else:
                        scan_results['gpt'] = {
                            'status': 'error',
                            'albums': [],
                            'error': 'No results found'
                        }
                        gui_message("No albums found in the content")
                    loop.close()
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"Error during GPT scan: {error_msg}", exc_info=True)
                    scan_results['gpt'] = {
                        'status': 'error',
                        'albums': [],
                        'error': error_msg
                    }
                    gui_message(f"Error during scan: {error_msg}")

            # Start scan in a thread
            thread = threading.Thread(target=run_scan)
            thread.start()
            
            return jsonify({
                'status': 'processing',
                'message': 'Scan started'
            })
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error during GPT scan: {error_msg}", exc_info=True)
            gui_message(f"Error starting scan: {error_msg}")
            return jsonify({
                'status': 'error',
                'message': f'Error during scan: {error_msg}'
            }), 500
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in scan-webpage route: {error_msg}", exc_info=True)
        gui_message(f"Internal server error: {error_msg}")
        return jsonify({
            'status': 'error',
            'message': 'Internal server error'
        }), 500

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
                                     width=1200, height=920,
                                     min_size=(1000, 750))
        
        # Add close handler
        def on_closed():
            debug_logger.info("Window closed, shutting down")
            try:
                # Stop the Flask server
                func = request.environ.get('werkzeug.server.shutdown')
                if func is not None:
                    func()

                # Clean up any pending tasks
                loop = asyncio.get_event_loop()
                if not loop.is_closed():
                    # Cancel all tasks
                    for task in asyncio.all_tasks(loop):
                        task.cancel()
                    
                    # Run loop one last time to complete cancellation
                    loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True))
                    
                    # Close the loop
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()

                # Clean exit without forcing
                sys.exit(0)
            except Exception as e:
                debug_logger.error(f"Error during shutdown: {e}")
                # Force exit if clean shutdown fails
                os._exit(0)
            
        window.events.closed += on_closed
        
        debug_logger.debug("WebView window created")
        webview.start()
        debug_logger.debug("WebView started")
        
    except Exception as e:
        debug_logger.error(f"Fatal error in main: {str(e)}", exc_info=True)
        sys.exit(1) 
        sys.exit(1) 