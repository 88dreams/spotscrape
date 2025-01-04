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
from datetime import datetime

# Flask and related imports
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS
import asgiref.wsgi

# Add the parent directory to sys.path
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from spotscrape import SpotScraper, setup_logging, FileHandler

# Initialize Flask app
app = Flask(__name__)
CORS(app)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25,
    logger=True,
    engineio_logger=True
)

# Set up logging
def setup_web_logging():
    """Set up logging for the web server with proper file handling"""
    log_dir = Path(__file__).parent.parent / 'logfiles'
    log_dir.mkdir(exist_ok=True)
    
    # Clean up old web debug logs
    for old_log in log_dir.glob('web_debug_*.log'):
        try:
            old_log.unlink()
        except Exception as e:
            print(f"Warning: Could not delete old log file {old_log}: {e}")
    
    # Create new log file with timestamp
    log_file = log_dir / f'web_debug_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger(__name__)

# Initialize logging
logger = setup_web_logging()

class WebLogger:
    """Logger that emits messages via Socket.IO and writes to file"""
    @staticmethod
    def info(message):
        logger.info(f"WebLogger.info: {message}")
        logger.debug(f"Emitting socket message: {message}")
        try:
            # Log to spotscraper log
            logging.getLogger('spotscrape').info(message)
            # Emit via socket.io
            socketio.emit('message', {'type': 'info', 'data': str(message)})
            logger.debug("Socket message emitted successfully")
        except Exception as e:
            logger.error(f"Error emitting socket message: {e}")

    @staticmethod
    def error(message):
        logger.error(f"WebLogger.error: {message}")
        try:
            # Log to spotscraper log
            logging.getLogger('spotscrape').error(message)
            # Emit via socket.io
            socketio.emit('message', {'type': 'error', 'data': str(message)})
        except Exception as e:
            logger.error(f"Error emitting error message: {e}")

    @staticmethod
    def warning(message):
        logger.warning(f"WebLogger.warning: {message}")
        try:
            # Log to spotscraper log
            logging.getLogger('spotscrape').warning(message)
            # Emit via socket.io
            socketio.emit('message', {'type': 'warning', 'data': str(message)})
        except Exception as e:
            logger.error(f"Error emitting warning message: {e}")

    @staticmethod
    def debug(message):
        logger.debug(f"WebLogger.debug: {message}")
        try:
            # Log to spotscraper log
            logging.getLogger('spotscrape').debug(message)
            # Emit via socket.io
            socketio.emit('message', {'type': 'debug', 'data': str(message)})
        except Exception as e:
            logger.error(f"Error emitting debug message: {e}")

def log_request_info(request):
    """Log request details"""
    logger.debug(f"Headers: {dict(request.headers)}")
    if request.is_json:
        logger.debug(f"Body: {request.get_json()}")
    else:
        logger.debug("Body: [non-JSON request]")

def log_response_info(response):
    """Log response details"""
    if response.is_json:
        logger.debug(f"Response (JSON): {response.get_json()}")
    else:
        logger.debug("Response: [non-JSON response]")
    return response

@app.before_request
def before_request():
    log_request_info(request)

@app.after_request
def after_request(response):
    return log_response_info(response)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scan', methods=['POST'])
def scan():
    """Handle scan requests"""
    logger.debug("Starting scan route")
    try:
        data = request.get_json()
        if not data or 'url' not in data or 'type' not in data:
            return jsonify({'error': 'Missing required fields'}), 400

        url = data['url']
        scan_type = data['type']
        logger.debug(f"Received scan request for {url} with type {scan_type}")

        # Initialize SpotScraper with WebLogger
        logger.debug("Initializing SpotScraper")
        scraper = SpotScraper(logger=WebLogger)

        def run_scan_sync():
            async def run_scan():
                try:
                    if scan_type == 'url':
                        logger.info(f"Starting URL scan for: {url}")
                        socketio.emit('message', {'type': 'info', 'data': f"Starting scan for {url}"})
                        
                        # Set a timeout for the scan operation
                        try:
                            logger.debug("Starting scan_spotify_links with timeout")
                            items = await asyncio.wait_for(
                                scraper.scan_spotify_links(url),
                                timeout=30  # 30 seconds timeout
                            )
                            logger.debug("scan_spotify_links completed")
                            
                            if items:
                                logger.info(f"Found {len(items)} items")
                                socketio.emit('message', {'type': 'info', 'data': f"Found {len(items)} items"})
                                
                                # Save items to file
                                destination_file = scraper._get_default_data_path('url')
                                handler = FileHandler(destination_file)
                                await handler.save(items)
                                logger.info(f"Saved items to {destination_file}")
                                socketio.emit('message', {'type': 'info', 'data': f"Saved items to {destination_file}"})
                                
                                return {
                                    'success': True,
                                    'items': items,
                                    'message': f"Found {len(items)} items"
                                }
                            else:
                                logger.info("No items found")
                                socketio.emit('message', {'type': 'info', 'data': "No items found"})
                                return {
                                    'success': True,
                                    'items': [],
                                    'message': "No items found"
                                }
                        except asyncio.TimeoutError:
                            error_msg = "Scan operation timed out after 30 seconds"
                            logger.error(error_msg)
                            socketio.emit('message', {'type': 'error', 'data': error_msg})
                            return {'error': error_msg}, 500
                        except Exception as e:
                            error_msg = f"Error during URL scan: {str(e)}"
                            logger.error(f"{error_msg}\n{traceback.format_exc()}")
                            socketio.emit('message', {'type': 'error', 'data': error_msg})
                            return {'error': str(e)}, 500
                            
                    elif scan_type == 'gpt':
                        logger.info(f"Starting GPT scan for: {url}")
                        socketio.emit('message', {'type': 'info', 'data': f"Starting GPT scan for {url}"})
                        
                        items = await scraper.scan_webpage(url)
                        if items:
                            logger.info(f"Found {len(items)} items")
                            socketio.emit('message', {'type': 'info', 'data': f"Found {len(items)} items"})
                            
                            # Save items to file
                            destination_file = scraper._get_default_data_path('gpt')
                            handler = FileHandler(destination_file)
                            await handler.save(items)
                            logger.info(f"Saved items to {destination_file}")
                            socketio.emit('message', {'type': 'info', 'data': f"Saved items to {destination_file}"})
                            
                            return {
                                'success': True,
                                'items': items,
                                'message': f"Found {len(items)} items"
                            }
                        else:
                            socketio.emit('message', {'type': 'info', 'data': "No items found"})
                            return {
                                'success': True,
                                'items': [],
                                'message': "No items found"
                            }
                    else:
                        return {'error': 'Invalid scan type'}, 400
                        
                except Exception as e:
                    error_msg = f"Error during {scan_type} scan: {str(e)}"
                    logger.error(f"{error_msg}\n{traceback.format_exc()}")
                    socketio.emit('message', {'type': 'error', 'data': error_msg})
                    return {'error': str(e)}, 500

            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(run_scan())
            finally:
                loop.close()

        # Run the scan in an eventlet greenthread with timeout
        try:
            logger.debug("Starting eventlet spawn")
            result = eventlet.with_timeout(
                35,  # 35 seconds timeout (slightly longer than the inner timeout)
                eventlet.spawn(run_scan_sync).wait
            )
            logger.debug("Eventlet spawn completed")
            
            if isinstance(result, tuple):
                return jsonify(result[0]), result[1]
            return jsonify(result)
            
        except eventlet.Timeout:
            error_msg = "Operation timed out at server level"
            logger.error(error_msg)
            socketio.emit('message', {'type': 'error', 'data': error_msg})
            return jsonify({'error': error_msg}), 504

    except Exception as e:
        error_msg = f"Error in scan route: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        socketio.emit('message', {'type': 'error', 'data': error_msg})
        return jsonify({'error': str(e)}), 500

@app.route('/get_json_files')
def get_json_files():
    """Get list of available JSON files"""
    try:
        # Create a SpotScraper instance to use its methods
        scraper = SpotScraper()
        
        # Get paths for both types of files
        url_file = os.path.basename(scraper._get_default_data_path('url'))
        gpt_file = os.path.basename(scraper._get_default_data_path('gpt'))
        
        return jsonify({'files': [gpt_file, url_file]})
    except Exception as e:
        logger.error(f"Error getting JSON files: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    logger.info("Starting Flask server with eventlet...")
    socketio.run(app, debug=True) 