import os
import sys
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS
import threading
import logging
import asyncio
from datetime import datetime
import webview
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
from jinja2 import FileSystemLoader, Environment
import atexit
import time
from spotscrape.message_handler import gui_message, send_progress, message_queue, progress_queue

"""
File Structure:
/SpotScrape_data/
    spotscrape_gpt.json  - Results from GPT scanning
    spotscrape_url.json  - Results from URL scanning
/logs/
    spot-debug-*.log     - Debug logging
    spot-spotify-*.log   - Spotify operations
    spot-main-*.log      - Main application flow
"""

# Configure debug logging
def setup_debug_logging():
    """Set up debug logging with enhanced configuration"""
    debug_logger = logging.getLogger('spot-debug')
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.propagate = False  # Prevent propagation to root logger
    
    # Get the executable's directory or current directory
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Create or overwrite the debug log file
    log_path = os.path.join(log_dir, f"spot-debug-{datetime.now().strftime('%Y%m%d')}.log")
    
    file_handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # Use simpler timestamp format without milliseconds
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'  # Simplified timestamp format
    )
    file_handler.setFormatter(formatter)
    
    # Remove any existing handlers
    for handler in debug_logger.handlers[:]:
        debug_logger.removeHandler(handler)
    
    debug_logger.addHandler(file_handler)
    debug_logger.info(f"Log file created at: {log_path}")
    return debug_logger

# Initialize debug logger
debug_logger = setup_debug_logging()

# Completely disable all Flask and Werkzeug logging
logging.getLogger('werkzeug').disabled = True
cli = sys.modules['flask.cli']
cli.show_server_banner = lambda *x: None

# Create the Flask app with logging disabled
app = Flask(__name__)
app.logger.disabled = True
app.config['PROPAGATE_EXCEPTIONS'] = False

# Disable all loggers
for logger_name in logging.root.manager.loggerDict:
    logging.getLogger(logger_name).disabled = True
    logging.getLogger(logger_name).propagate = False

# Re-enable only our debug logger
debug_logger.disabled = False

# Configure root logger to prevent console output
logging.getLogger().setLevel(logging.ERROR)
logging.getLogger().handlers = []

# Initialize Flask
if getattr(sys, 'frozen', False):
    # Running as compiled executable
    base_dir = os.path.dirname(sys.executable)
    template_dir = os.path.join(base_dir, '_internal', 'frontend', 'templates')
    static_dir = os.path.join(base_dir, '_internal', 'frontend', 'static')
else:
    # Running as script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(base_dir, 'frontend', 'templates')
    static_dir = os.path.join(base_dir, 'frontend', 'static')

# Add detailed debug logging for template and static directories
debug_logger.info(f"Base directory: {base_dir}")
debug_logger.info(f"Template directory: {template_dir}")
debug_logger.info(f"Static directory: {static_dir}")

# Verify directories exist and list contents
if not os.path.exists(template_dir):
    debug_logger.error(f"Template directory does not exist: {template_dir}")
    debug_logger.info("Available directories in base_dir:")
    try:
        debug_logger.info(str(os.listdir(base_dir)))
        if os.path.exists(os.path.join(base_dir, '_internal')):
            debug_logger.info(f"Contents of _internal dir: {os.listdir(os.path.join(base_dir, '_internal'))}")
            if os.path.exists(os.path.join(base_dir, '_internal', 'frontend')):
                debug_logger.info(f"Contents of frontend dir: {os.listdir(os.path.join(base_dir, '_internal', 'frontend'))}")
    except Exception as e:
        debug_logger.error(f"Error listing directories: {e}")

if not os.path.exists(static_dir):
    debug_logger.error(f"Static directory does not exist: {static_dir}")

# Create the Flask app with basic configuration
app = Flask(__name__)
app.static_folder = static_dir
app.template_folder = template_dir
app.jinja_loader = FileSystemLoader(template_dir)
CORS(app)

# Add debug route to verify template loading
@app.route('/debug')
def debug():
    try:
        template_list = app.jinja_loader.list_templates()
        return jsonify({
            'template_dir': template_dir,
            'templates': template_list,
            'exists': os.path.exists(template_dir),
            'files': os.listdir(template_dir) if os.path.exists(template_dir) else []
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'template_dir': template_dir,
            'exists': os.path.exists(template_dir)
        })

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

# Override the user_message in spotscrape
spotscrape.user_message = gui_message

def async_route(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapped

@app.route('/')
def index():
    """Serve the index page with enhanced error handling"""
    debug_logger.debug("Attempting to serve index page")
    try:
        debug_logger.debug(f"Current template folder: {app.template_folder}")
        debug_logger.debug(f"Available templates: {app.jinja_loader.list_templates()}")
        return render_template('index.html')
    except Exception as e:
        error_msg = f"Error serving index page: {str(e)}"
        debug_logger.error(error_msg, exc_info=True)
        return f"""
        <html>
            <body>
                <h1>Error Loading Application</h1>
                <p>There was an error loading the application templates.</p>
                <p>Error: {error_msg}</p>
                <p>Template Directory: {template_dir}</p>
                <p>Static Directory: {static_dir}</p>
            </body>
        </html>
        """, 500

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
    """Handle URL scanning requests."""
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            debug_logger.error("No URL provided in request")
            return jsonify({'status': 'error', 'error': 'No URL provided'}), 400
            
        debug_logger.info(f"Starting URL scan for: {url}")
        gui_message(f"Starting URL scan for: {url}")
        send_progress(0, "Initializing scan...")
        
        # Initialize components
        web_extractor = WebContentExtractor()
        spotify_manager = SpotifySearchManager()
        
        try:
            # Extract content from URL
            debug_logger.info("Extracting content from URL...")
            gui_message("Extracting content from URL...")
            send_progress(10, "Extracting content from URL...")
            content = await web_extractor.extract_content(url)
            
            if not content:
                error_msg = f"Failed to extract content from URL: {url}"
                debug_logger.error(error_msg)
                gui_message(error_msg, True)
                send_progress(0, error_msg)
                return jsonify({'status': 'error', 'error': error_msg}), 400
                
            debug_logger.info(f"Successfully extracted content. Length: {len(content)}")
            gui_message(f"Successfully extracted {len(content)} characters of content")
            send_progress(20, "Content extracted successfully")
            
            # Scan for Spotify links
            debug_logger.info("Scanning for Spotify links...")
            gui_message("Scanning for Spotify links...")
            send_progress(30, "Scanning for Spotify links...")
            album_ids = await spotify_manager.scan_spotify_links(content)
            
            if not album_ids:
                debug_logger.info("No Spotify album links found in content")
                gui_message("No Spotify album links found in content")
                send_progress(100, "No Spotify album links found")
                return jsonify({
                    'status': 'complete',
                    'albums': [],
                    'message': 'No Spotify album links found in the content'
                })
            
            debug_logger.info(f"Found {len(album_ids)} album IDs: {album_ids}")
            gui_message(f"Found {len(album_ids)} Spotify album links")
            send_progress(50, f"Found {len(album_ids)} Spotify album links")
            
            # Get album info for each ID
            albums = []
            total = len(album_ids)
            
            for i, album_id in enumerate(album_ids, 1):
                progress = 50 + ((i / total) * 45)  # Progress from 50% to 95%
                debug_logger.info(f"Getting info for album {i}/{total}, ID: {album_id}")
                gui_message(f"Processing album {i}/{total}...")
                send_progress(int(progress), f"Processing album {i}/{total}...")
                
                try:
                    album_info = await spotify_manager.get_album_info(album_id)
                    
                    if album_info:
                        # Get tracks and sort by popularity
                        tracks = album_info.get('tracks', {}).get('items', [])
                        most_popular_track = None
                        
                        # Only attempt to get track info if tracks exist
                        if tracks and hasattr(spotify_manager, 'get_tracks_info'):
                            try:
                                tracks_with_info = await spotify_manager.get_tracks_info([track['id'] for track in tracks])
                                if tracks_with_info:
                                    most_popular_track = max(tracks_with_info, key=lambda x: x.get('popularity', 0))
                            except Exception as track_error:
                                debug_logger.error(f"Error getting track info: {track_error}")
                                # Continue without track info if it fails
                                pass

                        formatted_album = {
                            'id': album_info.get('id'),
                            'artist': album_info.get('artists', [{}])[0].get('name'),
                            'name': album_info.get('name'),
                            'popularity': album_info.get('popularity', 0),
                            'images': album_info.get('images', []),
                            'spotify_url': f"https://open.spotify.com/album/{album_id}",
                            'most_popular_track_id': most_popular_track.get('id') if most_popular_track else None,
                            'source_url': url,
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        albums.append(formatted_album)
                        debug_logger.info(f"Added album: {formatted_album['artist']} - {formatted_album['name']}")
                        gui_message(f"✓ Found: {formatted_album['artist']} - {formatted_album['name']}")
                        send_progress(int(progress), f"✓ Found: {formatted_album['artist']} - {formatted_album['name']}")
                    else:
                        debug_logger.warning(f"Could not get info for album ID: {album_id}")
                        gui_message(f"✗ Could not get info for album", True)
                        send_progress(int(progress), f"✗ Could not get album info")
                except Exception as album_error:
                    debug_logger.error(f"Error processing album {album_id}: {str(album_error)}")
                    gui_message(f"✗ Error processing album: {str(album_error)}", True)
                    continue
            
            debug_logger.info(f"Successfully retrieved info for {len(albums)} albums")
            send_progress(95, "Saving results...")
            
            # Save results to file
            data_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SpotScrape_data"))
            os.makedirs(data_dir, exist_ok=True)
            url_file = os.path.normpath(os.path.join(data_dir, "spotscrape_url.json"))
            
            try:
                with open(url_file, 'w', encoding='utf-8') as f:
                    json.dump(albums, f, indent=2, ensure_ascii=False)
                debug_logger.info(f"Saved {len(albums)} URL scan results to {url_file}")
                gui_message(f"Saved {len(albums)} albums to file")
                send_progress(100, f"Completed! Found {len(albums)} albums")
            except Exception as e:
                debug_logger.error(f"Error saving URL scan results: {e}")
                gui_message("Error saving results to file", True)
                send_progress(95, "Error saving results")

            # Return success response
            response_data = {
                'status': 'complete',
                'albums': albums,
                'message': f'Found {len(albums)} albums'
            }
            debug_logger.info("Sending response with albums")
            return jsonify(response_data)
            
        finally:
            # Ensure we clean up the web extractor
            await web_extractor.cleanup()
            
    except Exception as e:
        error_msg = f"Error during URL scan: {str(e)}"
        debug_logger.error(error_msg, exc_info=True)
        gui_message(error_msg, True)
        send_progress(0, f"Error: {str(e)}")
        return jsonify({'status': 'error', 'error': error_msg}), 500

# Add after other logger setups
def setup_gpt_logging():
    """Set up GPT logging with enhanced configuration"""
    gpt_logger = logging.getLogger('spot-gpt')
    gpt_logger.setLevel(logging.DEBUG)
    gpt_logger.propagate = False  # Prevent propagation to root logger
    
    # Get the executable's directory or current directory
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Create or overwrite the GPT log file
    log_path = os.path.join(log_dir, f"spot-gpt-{datetime.now().strftime('%Y%m%d')}.log")
    
    file_handler = logging.FileHandler(log_path, mode='w', encoding='utf-8', errors='ignore')
    file_handler.setLevel(logging.DEBUG)
    
    # Use simpler timestamp format without milliseconds
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # Remove any existing handlers
    for handler in gpt_logger.handlers[:]:
        gpt_logger.removeHandler(handler)
    
    gpt_logger.addHandler(file_handler)
    gpt_logger.info(f"GPT Log file created at: {log_path}")
    return gpt_logger

# Initialize GPT logger
gpt_logger = setup_gpt_logging()

# Update the scan_gpt route to use the GPT logger
@app.route('/api/scan-gpt', methods=['POST'])
def scan_gpt():
    gpt_logger.debug("Received scan-gpt request")
    try:
        data = request.json
        url = data.get('url')
        gpt_logger.debug(f"Processing URL: {url}")
        
        if not url:
            gpt_logger.error("No URL provided")
            return jsonify({'error': 'URL is required'}), 400
            
        # Create SpotScrape_data directory if it doesn't exist
        data_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SpotScrape_data"))
        os.makedirs(data_dir, exist_ok=True)
        
        # Default file path for GPT scan results
        destination_file = os.path.normpath(os.path.join(data_dir, "spotscrape_gpt.json"))
        gpt_logger.debug(f"Using destination file: {destination_file}")
        
        # Reset results
        scan_results['gpt'] = {'status': 'processing', 'albums': [], 'error': None}
        
        # Run scan in a separate thread
        def run_scan():
            try:
                gpt_logger.debug("Starting scan in new thread")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Process the content
                results = loop.run_until_complete(scan_webpage(url, destination_file))
                
                if results:
                    try:
                        # Format albums for frontend display
                        formatted_albums = []
                        for album in results:
                            try:
                                # Ensure proper encoding of text fields
                                artist_name = album.get('artist', '').encode('utf-8', errors='ignore').decode('utf-8')
                                album_name = album.get('name', '').encode('utf-8', errors='ignore').decode('utf-8')
                                
                                album_data = {
                                    'id': album.get('id', ''),
                                    'artist': artist_name,
                                    'name': album_name,
                                    'popularity': album.get('popularity', 0),
                                    'images': album.get('images', []),
                                    'spotify_url': album.get('spotify_url', ''),
                                    'source_url': url,
                                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                }
                                formatted_albums.append(album_data)
                                gpt_logger.debug(f"Formatted album: {artist_name} - {album_name}")
                            except Exception as e:
                                gpt_logger.error(f"Error formatting album: {str(e)}")
                                continue
                        
                        # Save formatted results to GPT-specific file
                        try:
                            with open(destination_file, 'w', encoding='utf-8', errors='ignore') as f:
                                json.dump(formatted_albums, f, indent=2, ensure_ascii=False)
                            gpt_logger.info(f"Saved {len(formatted_albums)} GPT scan results to {destination_file}")
                        except Exception as e:
                            gpt_logger.error(f"Error saving GPT scan results: {e}")
                        
                        scan_results['gpt'] = {
                            'status': 'complete',
                            'albums': formatted_albums,
                            'error': None
                        }
                        gpt_logger.debug(f"Loaded {len(formatted_albums)} albums from file")
                        gui_message(f"Found {len(formatted_albums)} albums")
                    except Exception as e:
                        gpt_logger.error(f"Error processing GPT results: {e}")
                        scan_results['gpt'] = {
                            'status': 'error',
                            'albums': [],
                            'error': f"Error processing results: {str(e)}"
                        }
                else:
                    scan_results['gpt'] = {
                        'status': 'complete',
                        'albums': [],
                        'error': None
                    }
                    gpt_logger.warning("No results found")
                
                loop.close()
                gpt_logger.debug("Scan completed successfully")
            except Exception as e:
                gpt_logger.error(f"Error in scan thread: {str(e)}", exc_info=True)
                scan_results['gpt'] = {
                    'status': 'error',
                    'albums': [],
                    'error': str(e)
                }
        
        thread = threading.Thread(target=run_scan)
        thread.start()
        gpt_logger.debug("Scan thread started")
        
        return jsonify({'status': 'processing'})
        
    except Exception as e:
        gpt_logger.error(f"Error in scan-gpt endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/create-playlist', methods=['POST'])
@async_route
async def create_playlist():
    """Handle playlist creation with better error handling and progress updates"""
    spotify_manager = None
    try:
        data = request.json
        album_ids = data.get('albums', [])  # This is now a list of album IDs
        playlist_name = data.get('playlistName', '')
        playlist_description = data.get('playlistDescription', '')
        include_all_tracks = data.get('includeAllTracks', True)
        include_popular_tracks = data.get('includePopularTracks', False)

        if not album_ids:
            logger.error("No albums provided for playlist creation")
            return jsonify({'error': 'No albums selected'}), 400

        if not playlist_name:
            playlist_name = "SpotScrape Playlist"
            
        if not playlist_description:
            playlist_description = "Created with SpotScrape"

        # Initialize managers
        playlist_manager = PlaylistManager()
        spotify_manager = SpotifySearchManager()
        
        gui_message("Creating new playlist...")
        
        # Create the playlist
        playlist_id = await playlist_manager.create_playlist(
            name=playlist_name,
            description=playlist_description
        )
        
        if not playlist_id:
            logger.error("Failed to create playlist")
            return jsonify({'error': 'Failed to create playlist - authorization may be required'}), 500
        
        gui_message(f"Created playlist: {playlist_name}")
        gui_message("Gathering tracks from albums...")
        
        # Process albums and collect tracks
        tracks_to_add = []
        total_albums = len(album_ids)
        
        for i, album_id in enumerate(album_ids, 1):
            if not album_id:
                logger.warning(f"Invalid album ID: {album_id}")
                continue
                
            try:
                album_info = await spotify_manager.get_album_info(album_id)
                if not album_info:
                    logger.warning(f"Could not fetch info for album ID: {album_id}")
                    continue
                
                artist_name = album_info.get('artists', [{}])[0].get('name', 'Unknown')
                album_name = album_info.get('name', 'Unknown')
                gui_message(f"Processing album {i} of {total_albums}: {artist_name} - {album_name}")
                    
                album_tracks = album_info.get('tracks', {}).get('items', [])
                if not album_tracks:
                    logger.warning(f"No tracks found for album ID: {album_id}")
                    continue
                
                if include_popular_tracks:
                    # Sort tracks by popularity and take the most popular one
                    album_tracks.sort(key=lambda x: x.get('popularity', 0), reverse=True)
                    album_tracks = album_tracks[:1]
                elif not include_all_tracks:
                    # Take only the first track
                    album_tracks = album_tracks[:1]
                    
                track_ids = [track['id'] for track in album_tracks if track.get('id')]
                tracks_to_add.extend(track_ids)
                
            except Exception as e:
                logger.error(f"Error processing album {album_id}: {str(e)}")
                continue
        
        if not tracks_to_add:
            logger.error("No tracks found to add to playlist")
            return jsonify({'error': 'No tracks found to add to playlist'}), 400
        
        gui_message(f"Adding {len(tracks_to_add)} tracks to playlist...")
        
        # Add tracks to playlist
        success = await playlist_manager.add_tracks_to_playlist(playlist_id, tracks_to_add)
        if not success:
            logger.error("Failed to add tracks to playlist")
            return jsonify({'error': 'Failed to add tracks to playlist'}), 500
            
        gui_message("Successfully created playlist!")
        
        return jsonify({
            'status': 'success',
            'message': 'Playlist created successfully!',
            'playlist_id': playlist_id
        })
        
    except Exception as e:
        error_msg = f"Error creating playlist: {str(e)}"
        logger.error(error_msg)
        return jsonify({'error': error_msg}), 500
    finally:
        # Clean up Spotify resources
        if spotify_manager and spotify_manager._spotify_instance:
            try:
                spotify_manager._spotify_instance.close()
                spotify_manager._spotify_instance = None
            except Exception as e:
                logger.error(f"Error cleaning up Spotify resources: {e}")
        # Clear any remaining progress messages
        while not progress_queue.empty():
            try:
                progress_queue.get_nowait()
            except:
                pass

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
    """SSE endpoint for real-time messages"""
    def generate():
        while True:
            try:
                # Get message from queue with timeout
                message = message_queue.get(timeout=1)
                yield f"data: {json.dumps({'message': message})}\n\n"
            except Empty:
                # Send heartbeat to keep connection alive
                yield ": heartbeat\n\n"
            except Exception as e:
                logger.error(f"Error in message stream: {e}")
                break

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/progress')
def get_progress():
    """SSE endpoint for real-time progress updates"""
    def generate():
        while True:
            try:
                # Get progress update from queue with timeout
                progress = progress_queue.get(timeout=1)
                yield f"data: {json.dumps(progress)}\n\n"
            except Empty:
                # Send heartbeat to keep connection alive
                yield ": heartbeat\n\n"
            except Exception as e:
                logger.error(f"Error in progress stream: {e}")
                break

    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/scan-webpage', methods=['POST'])
async def scan_webpage_route():
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({
                'status': 'error',
                'message': 'No URL provided'
            }), 400
            
        # Reset scan results
        scan_results['gpt'] = {
            'status': 'processing',
            'albums': [],
            'error': None
        }
        
        # Create SpotScrape_data directory if it doesn't exist
        data_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SpotScrape_data"))
        os.makedirs(data_dir, exist_ok=True)
        
        # Default file path for GPT scan results
        destination_file = os.path.normpath(os.path.join(data_dir, "spotscrape_gpt.json"))
        debug_logger.debug(f"Using destination file: {destination_file}")
        
        gui_message("Starting GPT scan...")
        gui_message("Initializing content extraction...")
        gui_message("Initializing GPT scan...")
        gui_message("Extracting webpage content...")
        
        # Start the scan in a background task
        def run_scan():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                # Run the scan
                results = loop.run_until_complete(scan_webpage(url, destination_file))
                
                # Check if file exists and has content
                if os.path.exists(destination_file) and os.path.getsize(destination_file) > 0:
                    # Load and format results
                    with open(destination_file, 'r', encoding='utf-8') as f:
                        albums_data = json.load(f)
                        formatted_albums = []
                        not_found_albums = []
                        
                        gui_message(f"\nProcessing {len(albums_data)} albums found in the content...")
                        
                        for i, album in enumerate(albums_data, 1):
                            try:
                                # Log the album data for debugging
                                debug_logger.debug(f"Processing album data: {json.dumps(album, indent=2)}")
                                
                                if album.get('id'):  # Album was found on Spotify
                                    # Ensure proper encoding of text fields
                                    artist_name = album.get('artist', '').encode('utf-8', errors='ignore').decode('utf-8')
                                    album_name = album.get('name', '').encode('utf-8', errors='ignore').decode('utf-8')
                                    
                                    album_data = {
                                        'id': album.get('id', ''),
                                        'artist': artist_name,
                                        'name': album_name,
                                        'popularity': album.get('popularity', 0),
                                        'images': album.get('images', []),
                                        'spotify_url': f"https://open.spotify.com/album/{album.get('id', '')}",
                                        'source_url': url,
                                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                    }
                                    formatted_albums.append(album_data)
                                    gui_message(f"Processed album {i} of {len(albums_data)}: {artist_name} - {album_name}")
                                else:  # Album was not found on Spotify
                                    artist_name = album.get('artist', '').encode('utf-8', errors='ignore').decode('utf-8')
                                    album_name = album.get('name', '').encode('utf-8', errors='ignore').decode('utf-8')
                                    not_found_albums.append(f"{artist_name} - {album_name}")
                            except Exception as e:
                                debug_logger.error(f"Error processing album entry: {str(e)}")
                                continue
                        
                        scan_results['gpt'] = {
                            'status': 'complete',
                            'albums': formatted_albums,
                            'error': None
                        }
                        
                        gui_message(f"\nSuccessfully processed {len(formatted_albums)} albums")
                        
                        if not_found_albums:
                            gui_message("\nThe following albums could not be found on Spotify:")
                            for album in not_found_albums:
                                gui_message(f"• {album}")
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
        logger.error(f"Error in scan-webpage route: {error_msg}", exc_info=True)
        gui_message(f"Internal server error: {error_msg}")
        return jsonify({
            'status': 'error',
            'message': 'Internal server error'
        }), 500

def force_quit():
    """Force quit the application and all its processes"""
    debug_logger.info("Force quitting application...")
    try:
        # Get the current process ID
        pid = os.getpid()
        debug_logger.info(f"Current process ID: {pid}")
        
        # Force kill the process
        if sys.platform == 'win32':
            # Redirect output to null to suppress taskkill messages
            os.system(f'taskkill /F /PID {pid} /T >nul 2>&1')
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception as e:
        debug_logger.error(f"Error during force quit: {e}")
        os._exit(1)

def cleanup_resources():
    """Clean up function to be called on exit"""
    debug_logger.info("Cleaning up resources...")
    try:
        # Set a timeout for cleanup
        cleanup_start = time.time()
        cleanup_timeout = 5  # 5 seconds timeout
        
        # Clear message queues
        while not message_queue.empty():
            message_queue.get_nowait()
        while not progress_queue.empty():
            progress_queue.get_nowait()
            
        # Clean up any remaining Spotify instances
        if hasattr(SpotifySearchManager, '_spotify_instance') and SpotifySearchManager._spotify_instance:
            try:
                SpotifySearchManager._spotify_instance.close()
                SpotifySearchManager._spotify_instance = None
            except:
                pass
                
        # Kill any remaining threads except main thread
        for thread in threading.enumerate():
            if thread != threading.main_thread():
                try:
                    thread._stop()
                except:
                    pass
                    
        # If cleanup takes too long, force quit
        if time.time() - cleanup_start > cleanup_timeout:
            debug_logger.warning("Cleanup timeout exceeded, forcing quit...")
            force_quit()
            
    except Exception as e:
        debug_logger.error(f"Error during cleanup: {e}")
        force_quit()

def shutdown_server():
    """Shutdown the Flask server"""
    debug_logger.info("Shutting down Flask server...")
    try:
        # Make a request to the shutdown endpoint
        import requests
        requests.get('http://localhost:5000/shutdown', timeout=0.5)
    except Exception as e:
        debug_logger.error(f"Error shutting down Flask server: {e}")

@app.route('/shutdown')
def shutdown():
    """Endpoint to shut down the Flask server"""
    try:
        func = request.environ.get('werkzeug.server.shutdown')
        if func is not None:
            func()
            return 'Server shutting down...'
    except Exception as e:
        debug_logger.error(f"Error in shutdown endpoint: {e}")
        return 'Error shutting down server'

def start_server():
    """Start the Flask server"""
    debug_logger.debug("Starting Flask server")
    # Disable Flask development server output
    import click
    click.echo = lambda *args, **kwargs: None
    # Run Flask with minimal output
    app.run(port=5000, threaded=True, debug=False, use_reloader=False)

def main():
    """Entry point for the application"""
    try:
        # Suppress all console output
        class NullIO:
            def write(self, *args, **kwargs):
                pass
            def flush(self, *args, **kwargs):
                pass
        
        sys.stdout = NullIO()
        sys.stderr = NullIO()
        
        # Disable all warnings
        import warnings
        warnings.filterwarnings('ignore')
        
        # Register cleanup function
        atexit.register(cleanup_resources)
        
        # Disable debug mode for webview
        webview.WEBVIEW_DEBUG = False
        os.environ['WEBVIEW_LOGS'] = '0'  # Disable webview logging
        
        # Handle Ctrl+C gracefully
        def signal_handler(signum, frame):
            debug_logger.info(f"Received shutdown signal: {signum}")
            cleanup_resources()
            if window:
                window.destroy()
            shutdown_server()
            time.sleep(0.5)  # Give a moment for resources to clean up
            force_quit()
            
        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # Termination request
        if sys.platform == 'win32':
            signal.signal(signal.SIGBREAK, signal_handler)  # Ctrl+Break on Windows
        
        # Start Flask server in a separate thread
        t = threading.Thread(target=start_server, daemon=True)
        t.start()
        debug_logger.debug("Flask server thread started")
        
        # Create and start webview window with close handler
        window = webview.create_window('SpotScrape', 'http://localhost:5000',
                                     width=1200, height=850,
                                     min_size=(1000, 750))
        
        # Add close handler
        def on_closed():
            debug_logger.info("Window closed, shutting down")
            try:
                cleanup_resources()
                shutdown_server()
                
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

                time.sleep(0.5)  # Give a moment for resources to clean up
                force_quit()
            except Exception as e:
                debug_logger.error(f"Error during shutdown: {e}")
                force_quit()
            
        window.events.closed += on_closed
        
        debug_logger.debug("WebView window created")
        webview.start()
        debug_logger.debug("WebView started")
        
    except Exception as e:
        debug_logger.error(f"Fatal error in main: {str(e)}", exc_info=True)
        cleanup_resources()
        force_quit()

if __name__ == '__main__':
    main() 