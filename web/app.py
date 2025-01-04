# Enable eventlet for async support
import eventlet
eventlet.monkey_patch()

# Standard library imports
import os
import sys
import json
from pathlib import Path
import asyncio
from functools import wraps
import logging
import traceback

# Flask and related imports
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS

# Configure logging
log_dir = Path(__file__).parent.parent / 'logfiles'
log_dir.mkdir(exist_ok=True)
log_file = log_dir / 'web_debug.log'

# Create file handler with debug level
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Create console handler with info level
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Prevent duplicate logging
logger.propagate = False

# Add parent directory to Python path to import spotscrape
sys.path.append(str(Path(__file__).parent.parent))
from spotscrape import SpotScraper, ClientManager

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Socket.IO setup with more detailed configuration
socketio = SocketIO(
    app,
    async_mode='eventlet',
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1e8,
    manage_session=False
)

@app.before_request
def log_request_info():
    """Log details of every request"""
    if request.is_json:
        logger.debug('Headers: %s', dict(request.headers))
        logger.debug('Body: %s', request.get_json())
    else:
        logger.debug('Headers: %s', dict(request.headers))
        logger.debug('Body: [non-JSON request]')

@app.after_request
def log_response_info(response):
    """Log details of every response"""
    try:
        if response.is_json:
            logger.debug('Response (JSON): %s', response.get_json())
        else:
            logger.debug('Response: [non-JSON response]')
    except Exception as e:
        logger.debug('Response logging error: %s', str(e))
    return response

def async_route(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        logger.debug(f"Starting async route: {f.__name__}")
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(f(*args, **kwargs))
            loop.close()
            return result
        except Exception as e:
            logger.error(f"Error in async route {f.__name__}: {str(e)}", exc_info=True)
            return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500
    return wrapped

# Initialize SpotScraper with socket.io for real-time updates
class WebLogger:
    def __init__(self):
        self.socket = socketio
        self.logger = logger  # Use the app logger
    
    def info(self, message):
        self.logger.info(message)
        try:
            self.socket.emit('message', {'data': str(message), 'type': 'info'})
        except Exception as e:
            self.logger.error(f"Error sending socket message: {e}")
    
    def error(self, message):
        self.logger.error(message)
        try:
            self.socket.emit('message', {'data': f"Error: {str(message)}", 'type': 'error'})
        except Exception as e:
            self.logger.error(f"Error sending socket message: {e}")
    
    def warning(self, message):
        self.logger.warning(message)
        try:
            self.socket.emit('message', {'data': f"Warning: {str(message)}", 'type': 'warning'})
        except Exception as e:
            self.logger.error(f"Error sending socket message: {e}")
    
    def debug(self, message):
        self.logger.debug(message)
        try:
            self.socket.emit('message', {'data': str(message), 'type': 'debug'})
        except Exception as e:
            self.logger.error(f"Error sending socket message: {e}")

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/files')
def get_files():
    """Get list of available JSON files"""
    data_dir = Path('SpotScrape_data')
    if not data_dir.exists():
        return jsonify({'files': []})
    
    json_files = [f.name for f in data_dir.glob('*.json')]
    return jsonify({'files': json_files})

@app.route('/api/scan', methods=['POST'])
@async_route
async def scan():
    """Handle webpage scanning"""
    try:
        logger.debug("Received scan request")
        data = request.json
        url = data.get('url')
        scan_type = data.get('type')
        
        logger.info(f"Starting {scan_type} scan for URL: {url}")
        
        if not url:
            logger.warning("No URL provided in request")
            return jsonify({'error': 'URL is required'}), 400
        
        # Initialize scraper with web logger
        logger.debug("Initializing SpotScraper")
        web_logger = WebLogger()
        scraper = SpotScraper(logger=web_logger)
        
        # Perform scan based on type
        try:
            if scan_type == 'url':
                destination_file = scraper._get_default_data_path('url')
                logger.debug(f"URL scan - destination file: {destination_file}")
                logger.debug("Starting scan_spotify_links")
                result = await scraper.scan_spotify_links(url, destination_file)
            else:  # gpt
                destination_file = scraper._get_default_data_path('gpt')
                logger.debug(f"GPT scan - destination file: {destination_file}")
                logger.debug("Starting scan_webpage")
                result = await scraper.scan_webpage(url, destination_file)
            
            logger.info(f"Scan completed. Found {len(result) if result else 0} items")
            logger.debug(f"Scan result: {result}")
            
            # Return the results for review
            response_data = {
                'success': True,
                'items': result,
                'file': os.path.basename(destination_file)
            }
            logger.debug(f"Sending response: {response_data}")
            return jsonify(response_data)
            
        except Exception as e:
            logger.error(f"Scanning error: {str(e)}", exc_info=True)
            import traceback
            error_response = {
                'error': f"Scanning error: {str(e)}",
                'traceback': traceback.format_exc()
            }
            logger.debug(f"Sending error response: {error_response}")
            return jsonify(error_response), 500
            
    except Exception as e:
        logger.error(f"Request error: {str(e)}", exc_info=True)
        import traceback
        error_response = {
            'error': str(e),
            'traceback': traceback.format_exc()
        }
        logger.debug(f"Sending error response: {error_response}")
        return jsonify(error_response), 500

@app.route('/api/review', methods=['POST'])
@async_route
async def review_items():
    """Handle review and filtering of scanned items"""
    try:
        data = request.json
        items = data.get('items', [])
        file_path = data.get('file')
        
        if not items or not file_path:
            return jsonify({'error': 'Items and file path are required'}), 400
        
        # Save reviewed items
        full_path = Path('SpotScrape_data') / file_path
        with open(full_path, 'w') as f:
            json.dump(items, f, indent=2)
        
        return jsonify({'success': True})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/playlist', methods=['POST'])
@async_route
async def create_playlist():
    """Handle playlist creation"""
    try:
        data = request.json
        json_file = data.get('file')
        playlist_name = data.get('name')
        
        if not json_file:
            return jsonify({'error': 'JSON file is required'}), 400
        
        # Initialize scraper with web logger
        scraper = SpotScraper(logger=WebLogger())
        
        # Load JSON file
        json_path = Path('SpotScrape_data') / json_file
        if not json_path.exists():
            return jsonify({'error': 'JSON file not found'}), 404
        
        with open(json_path) as f:
            tracks = json.load(f)
        
        # Create playlist
        playlist_id = await scraper.create_playlist(tracks, playlist_name)
        return jsonify({
            'success': True,
            'playlist_id': playlist_id
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Initialize eventlet WSGI server
    logger.info("Starting Flask server with eventlet...")
    socketio.run(app, debug=True, host='127.0.0.1', port=5000, use_reloader=True) 