"""
Core functionality for SpotScrape
"""
import logging
from logging.handlers import RotatingFileHandler
import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from threading import Lock
from functools import wraps
from typing import List, Any, Optional, Generator, Tuple, Dict
import requests
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from playwright.async_api import async_playwright
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import shutil
import urllib3
import warnings
import requests_cache
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import sys
import textwrap
import random
import aiofiles
from asyncio import Lock as AsyncLock
import aiohttp
from cachetools import TTLCache
import re
import threading
from tqdm import tqdm

# Internal imports
from spotscrape.utils import setup_logging
from spotscrape.spotify_manager import SpotifySearchManager
from spotscrape.web_extractor import WebContentExtractor
from spotscrape.content_processor import ContentProcessor
from spotscrape.message_handler import gui_message, send_progress, progress_queue

# Initialize logger
logger = logging.getLogger(__name__)

# Suppress specific warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.HTTPWarning)
warnings.filterwarnings("ignore", message=".*Content-Length and Transfer-Encoding.*", 
                       category=UserWarning, module='urllib3')

# Global cache configurations
CACHE_TTL = 3600  # 1 hour cache lifetime
request_cache = TTLCache(maxsize=100, ttl=CACHE_TTL)
spotify_cache = TTLCache(maxsize=1000, ttl=CACHE_TTL)

def get_packaged_browser_path():
    """Get the path to the packaged Playwright browser."""
    try:
        if getattr(sys, 'frozen', False):
            # Running in a PyInstaller bundle
            base_path = sys._MEIPASS
            browser_dir = os.path.join(base_path, '_internal', 'playwright', 'driver', 'package', '.local-browsers', 'chromium_headless_shell-1148')
            browser_path = os.path.join(browser_dir, 'chrome-win', 'headless_shell.exe')
            logger.debug(f"Running in PyInstaller bundle. Browser path: {browser_path}")
            return browser_path
        else:
            # Running in normal Python environment
            if sys.platform.startswith('win'):
                base_path = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'ms-playwright')
                # Look for the specific chromium version directory
                chromium_dir = None
                if os.path.exists(base_path):
                    for item in os.listdir(base_path):
                        if item.startswith('chromium_headless_shell-'):
                            chromium_dir = item
                            break
                
                if not chromium_dir:
                    # Try alternate locations
                    alt_paths = [
                        os.path.join(os.path.expanduser('~'), '.cache', 'ms-playwright'),
                        os.path.join(os.getcwd(), 'playwright-browsers'),
                        os.path.join(os.path.dirname(sys.executable), 'playwright-browsers')
                    ]
                    
                    for alt_path in alt_paths:
                        if os.path.exists(alt_path):
                            for item in os.listdir(alt_path):
                                if item.startswith('chromium_headless_shell-'):
                                    chromium_dir = item
                                    base_path = alt_path
                                    break
                            if chromium_dir:
                                break
                
                if not chromium_dir:
                    logger.error("Chromium browser directory not found in any known location")
                    raise Exception("Chromium browser directory not found. Please run 'playwright install chromium'")
                
                browser_path = os.path.join(base_path, chromium_dir, 'chrome-win', 'headless_shell.exe')
                logger.debug(f"Running in development environment. Browser path: {browser_path}")
                return browser_path
            else:
                browser_path = os.path.join(os.path.expanduser('~'), '.cache', 'ms-playwright')
                logger.debug(f"Running in development environment (non-Windows). Browser path: {browser_path}")
                return browser_path
    except Exception as e:
        logger.error(f"Error getting browser path: {str(e)}")
        raise

class ClientManager:
    """Singleton manager for API clients"""
    _spotify_instance = None
    _openai_instance = None
    _session = None
    _lock = AsyncLock()

    @classmethod
    async def get_spotify(cls) -> spotipy.Spotify:
        async with cls._lock:
            if not cls._spotify_instance:
                cls._spotify_instance = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    client_id=os.getenv("SPOTIPY_CLIENT_ID"),
                    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
                    redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
                    scope="playlist-modify-public playlist-modify-private"
                ))
            return cls._spotify_instance

    @classmethod
    async def get_openai(cls):
        """Get or create OpenAI client"""
        async with cls._lock:
            try:
                if cls._openai_instance is None:
                    logger.debug("Initializing OpenAI client")
                    api_key = os.getenv('OPENAI_API_KEY')
                    if not api_key:
                        logger.error("OPENAI_API_KEY environment variable not found")
                        raise Exception("OpenAI API key not found in environment variables")
                    
                    logger.debug("Creating AsyncOpenAI client")
                    cls._openai_instance = AsyncOpenAI(
                        api_key=api_key,
                        timeout=30.0,
                        max_retries=3
                    )
                    logger.debug("OpenAI client initialized successfully")
                return cls._openai_instance
            except Exception as e:
                logger.error(f"Error initializing OpenAI client: {str(e)}", exc_info=True)
                raise

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        async with cls._lock:
            if not cls._session or cls._session.closed:
                cls._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30),
                    connector=aiohttp.TCPConnector(limit=100)
                )
            return cls._session

    @classmethod
    async def cleanup(cls):
        """Cleanup resources"""
        if cls._session and not cls._session.closed:
            await cls._session.close()
        cls._session = None
        cls._openai_instance = None  # Reset OpenAI instance
        cls._spotify_instance = None  # Reset Spotify instance

class RateLimiter:
    """Improved rate limiter with caching"""
    def __init__(self, max_calls: int, time_period: int):
        self.max_calls = max_calls
        self.time_period = time_period
        self.calls = []
        self._lock = AsyncLock()
        self._cache = TTLCache(maxsize=1000, ttl=time_period)

    def __call__(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = str(args) + str(kwargs)
            
            # Check cache first
            if cache_key in self._cache:
                return self._cache[cache_key]

            async with self._lock:
                now = datetime.now()
                self.calls = [t for t in self.calls if (now - t).total_seconds() <= self.time_period]
                
                if len(self.calls) >= self.max_calls:
                    sleep_time = self.time_period - (now - self.calls[0]).total_seconds()
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
                    self.calls.pop(0)
                
                self.calls.append(now)
                
                result = await func(*args, **kwargs)
                self._cache[cache_key] = result
                return result
                
        return wrapper

class FileHandler:
    """Handles file operations with proper path handling"""
    def __init__(self, file_path: str):
        # Convert to proper Windows path and expand user directory
        self.file_path = os.path.abspath(os.path.expanduser(file_path))
        self.directory = os.path.dirname(self.file_path)

    async def load(self) -> List[Dict]:
        """Load JSON data from file"""
        try:
            # Ensure directory exists
            os.makedirs(self.directory, exist_ok=True)
            
            if not os.path.exists(self.file_path):
                logger.warning(f"File not found: {self.file_path}")
                return []

            async with aiofiles.open(self.file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content) if content else []

        except Exception as e:
            logger.error(f"Error loading file {self.file_path}: {e}")
            raise

    async def save(self, data: List[Dict]) -> None:
        """Save JSON data to file"""
        try:
            # Ensure directory exists
            os.makedirs(self.directory, exist_ok=True)
            
            async with aiofiles.open(self.file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2))
                logger.info(f"Data saved to {self.file_path}")

        except Exception as e:
            logger.error(f"Error saving to file {self.file_path}: {e}")
            raise

    async def backup(self) -> str:
        """Create a backup of the current file"""
        backup_name = f"{self.file_path}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.backup"
        async with self._lock:
            if os.path.exists(self.file_path):
                shutil.copy2(self.file_path, backup_name)
        return backup_name

    async def cleanup_backups(self, keep_last: int = 5) -> None:
        """Clean up old backup files"""
        try:
            backups = sorted([f for f in os.listdir() 
                            if f.startswith(f"{self.file_path}.") and f.endswith(".backup")])
            for old_backup in backups[:-keep_last]:
                try:
                    os.remove(old_backup)
                except OSError as e:
                    logger.warning(f"Could not remove old backup {old_backup}: {e}")
        except Exception as e:
            logger.error(f"Error cleaning up backups: {e}")

class PlaylistManager:
    """Manages Spotify playlist operations with improved efficiency"""
    def __init__(self):
        self._lock = AsyncLock()
        self.batch_size = 100  # Spotify's limit per request
        self._spotify = None
        self._track_cache = {}  # Cache for track information
        self.progress_callback = None

    def set_progress_callback(self, callback):
        """Set the progress callback function"""
        self.progress_callback = callback

    def _update_progress(self, progress, message):
        """Update progress if callback is set"""
        if self.progress_callback:
            self.progress_callback(progress, message)

    async def _get_spotify(self):
        if not self._spotify:
            self._spotify = await ClientManager.get_spotify()
        return self._spotify

    async def create_playlist(self, name: str, description: str = "") -> str:
        """Create a new playlist with rate limiting and caching"""
        self._update_progress(0, "Creating playlist...")
        
        try:
            spotify = await self._get_spotify()
            user_id = spotify.current_user()['id']
            
            async with self._lock:
                playlist = spotify.user_playlist_create(
                    user=user_id,
                    name=name,
                    public=True,
                    description=description
                )
                self._update_progress(100, "Playlist created successfully!")
                return playlist['id']
        except Exception as e:
            logger.error(f"Error creating playlist '{name}': {e}")
            raise

    async def add_tracks_to_playlist(self, playlist_id: str, track_ids: list):
        """Add tracks to a playlist with proper batching"""
        if not track_ids:
            return

        try:
            spotify = await self._get_spotify()
            total_tracks = len(track_ids)
            chunks = [track_ids[i:i + self.batch_size] for i in range(0, total_tracks, self.batch_size)]
            
            for i, chunk in enumerate(chunks, 1):
                try:
                    # Convert track IDs to URIs if needed
                    track_uris = [f"spotify:track:{track_id}" if not track_id.startswith('spotify:') else track_id 
                                for track_id in chunk]
                    
                    async with self._lock:
                        spotify.playlist_add_items(playlist_id, track_uris)
                    
                    progress = (i / len(chunks)) * 100
                    tracks_added = min(i * self.batch_size, total_tracks)
                    self._update_progress(progress, f"Added {tracks_added}/{total_tracks} tracks")
                    
                    # Small delay to prevent rate limiting
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error adding batch {i} to playlist: {e}")
                    raise
            
            self._update_progress(100, "All tracks added successfully!")
            
        except Exception as e:
            logger.error(f"Error adding tracks to playlist: {e}")
            raise

class SpotifySearchManager:
    """Handles Spotify search operations with caching"""
    def __init__(self):
        self._spotify = None
        self._track_cache = {}
        self._album_cache = {}
        self.progress_callback = None

    def set_progress_callback(self, callback):
        """Set the progress callback function"""
        self.progress_callback = callback

    def _update_progress(self, progress, message):
        """Update progress if callback is set"""
        if self.progress_callback:
            self.progress_callback(progress, message)

    async def _get_spotify(self):
        """Get or initialize the Spotify client"""
        if not self._spotify:
            self._spotify = await ClientManager.get_spotify()
        return self._spotify

    async def scan_spotify_links(self, content):
        """Scan content for Spotify album links and return album IDs"""
        self._update_progress(0, "Starting Spotify link scan...")
        
        patterns = [
            r'https://open\.spotify\.com/album/([a-zA-Z0-9]{22})',
            r'spotify:album:([a-zA-Z0-9]{22})'
        ]
        
        album_ids = set()
        for i, pattern in enumerate(patterns):
            matches = re.finditer(pattern, content)
            for match in matches:
                album_ids.add(match.group(1))
            progress = (i + 1) / len(patterns) * 100
            self._update_progress(progress, f"Scanning pattern {i + 1} of {len(patterns)}...")
        
        return list(album_ids)

    async def get_album_info(self, album_id):
        """Get album information from Spotify"""
        if album_id in self._album_cache:
            return self._album_cache[album_id]
        
        try:
            spotify = await self._get_spotify()
            album_info = spotify.album(album_id)
            self._album_cache[album_id] = album_info
            return album_info
        except Exception as e:
            logger.error(f"Error getting album info: {e}")
            return None

class PlaywrightCrawler:
    """Handles web crawling with improved resource management"""
    def __init__(self):
        self._lock = AsyncLock()
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def setup(self):
        """Set up Playwright resources"""
        async with self._lock:
            if self._playwright is None:
                try:
                    self._playwright = await async_playwright().start()
                    
                    # Get the base directory and browser path
                    if getattr(sys, 'frozen', False):
                        base_path = os.path.dirname(sys.executable)
                        # Look for browser in Playwright's expected directory structure
                        browser_dir = os.path.join(base_path, '_internal', 'playwright', 'driver', 'package', '.local-browsers', 'chromium_headless_shell-1148')
                        executable_path = os.path.join(browser_dir, 'chrome-win', 'headless_shell.exe')
                        
                        if not os.path.exists(executable_path):
                            # Log directory contents for debugging
                            logger.debug(f"Browser directory contents: {os.listdir(browser_dir) if os.path.exists(browser_dir) else 'directory not found'}")
                            raise FileNotFoundError(f"Browser executable not found at: {executable_path}")
                        
                        logger.debug(f"Using browser at: {executable_path}")
                    else:
                        # In development, let Playwright find the browser
                        executable_path = None
                        logger.debug("Development mode - letting Playwright find browser")
                    
                    # Launch browser with appropriate settings
                    self._browser = await self._playwright.chromium.launch(
                        executable_path=executable_path,
                        headless=True
                    )
                    
                    # Create a context with stealth settings
                    self._context = await self._browser.new_context(
                        viewport={'width': 1920, 'height': 1080},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        java_script_enabled=True
                    )
                    
                    logger.info("Playwright resources initialized successfully")
                except Exception as e:
                    logger.error(f"Error initializing Playwright: {e}")
                    if self._playwright:
                        await self._playwright.stop()
                        self._playwright = None
                    raise

    async def cleanup(self):
        """Clean up Playwright resources"""
        try:
            if self._context:
                await self._context.close()
                self._context = None
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
        except Exception as e:
            logger.error(f"Error during Playwright cleanup: {str(e)}")
            raise

    async def process_url(self, url: str) -> str:
        """Process a URL and return its content"""
        if not self._context:
            await self.setup()
        
        try:
            page = await self._context.new_page()
            try:
                # Navigate to the URL with a timeout
                await page.goto(url, timeout=30000, wait_until='networkidle')
                
                # Wait for the main content to load
                await page.wait_for_load_state('domcontentloaded')
                await asyncio.sleep(2)  # Allow dynamic content to load
                
                # Get the page content
                content = await page.content()
                return content
                
            finally:
                await page.close()
                
        except Exception as e:
            logger.error(f"Error processing URL {url}: {str(e)}")
            raise

class WebContentExtractor(PlaywrightCrawler):
    """Handles web content extraction with improved efficiency"""
    def __init__(self):
        super().__init__()

    async def extract_content(self, url: str) -> str:
        """Extract content from webpage with improved error handling"""
        if not self._context:
            await self.setup()

        async with self._lock:
            try:
                page = await self._context.new_page()
                try:
                    # Add stealth mode scripts
                    await page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                    """)
                    
                    # Configure page
                    await page.set_extra_http_headers({
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                        "Accept-Encoding": "gzip, deflate, br",
                        "DNT": "1",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1"
                    })
                    
                    # Navigate with more lenient conditions
                    response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    if not response:
                        raise Exception("Failed to get response from page")
                    
                    # Wait for main content to be available
                    await page.wait_for_selector('main, article, .article__body', timeout=30000)
                    
                    # Add a small delay to allow dynamic content to load
                    await page.wait_for_timeout(2000)
                    
                    # Get the full HTML content
                    html_content = await page.content()
                    
                    # Log a sample for debugging
                    logger.debug(f"HTML sample: {html_content[:1000]}")
                    
                    return html_content
                    
                finally:
                    await page.close()
                    
            except Exception as e:
                logger.error(f"Error extracting content from {url}: {e}")
                raise

def get_next_log_number() -> int:
    """Get the next available log file number (0-9) with improved efficiency"""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Use list comprehension for better performance
    log_files = [(os.path.getmtime(os.path.join(log_dir, f"spotscraper{i}.log")), i) 
                 for i in range(10) 
                 if os.path.exists(os.path.join(log_dir, f"spotscraper{i}.log"))]
    
    if not log_files:
        return 0
    
    if len(log_files) == 10:
        return min(log_files, key=lambda x: x[0])[1]
    
    used_numbers = {i for _, i in log_files}
    return next(i for i in range(10) if i not in used_numbers)

def get_log_dir():
    """Get the log directory path based on whether running as executable or script"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        base_dir = os.path.dirname(sys.executable)
    else:
        # Running as script
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create logs directory
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir

def setup_logging():
    """Set up logging with enhanced configuration"""
    # Get log directory using the centralized function
    log_dir = get_log_dir()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup main logger
    logger = logging.getLogger('spot-main')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    main_handler = RotatingFileHandler(
        os.path.join(log_dir, f"spot-main-{datetime.now().strftime('%Y%m%d')}.log"),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    main_handler.setFormatter(simple_formatter)
    logger.addHandler(main_handler)
    
    # Setup Spotify logger
    spotify_logger = logging.getLogger('spotify')
    spotify_logger.setLevel(logging.DEBUG)
    spotify_logger.propagate = False
    spotify_handler = RotatingFileHandler(
        os.path.join(log_dir, f"spot-spotify-{datetime.now().strftime('%Y%m%d')}.log"),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    spotify_handler.setFormatter(detailed_formatter)
    spotify_logger.addHandler(spotify_handler)
    
    # Log startup information
    logger.info("=== Starting new session ===")
    spotify_logger.info("=== Starting new session ===")
    
    return logger, spotify_logger

def user_message(msg: str, log_only: bool = False):
    """Log a user-facing message with improved formatting"""
    if not log_only:
        print(msg)
    logger.info(f"USER: {msg}")

def clean_html_content(content: str) -> str:
    """Clean HTML content to extract only relevant text for music information"""
    try:
        # Create BeautifulSoup object with lxml parser
        soup = BeautifulSoup(content, 'lxml')
        
        # Remove script, style, meta, link, and other non-content tags
        for element in soup.find_all(['script', 'style', 'meta', 'link', 'noscript', 'iframe', 'svg', 
                                    'path', 'button', 'input', 'form', 'nav', 'footer', 'header']):
            element.decompose()
            
        # Focus on main content areas
        main_content = None
        for selector in ['main', 'article', '[role="main"]', '.article__body', '.content', '#content']:
            main_content = soup.select_one(selector)
            if main_content:
                break
                
        if main_content:
            # Extract text from main content
            text = main_content.get_text(separator=' ', strip=True)
        else:
            # Fallback to body if no main content found
            text = soup.body.get_text(separator=' ', strip=True) if soup.body else soup.get_text(separator=' ', strip=True)
            
        # Clean up the text
        # Remove multiple spaces and newlines
        text = re.sub(r'\s+', ' ', text)
        # Remove non-breaking spaces and other special whitespace
        text = text.replace('\xa0', ' ').strip()
        
        return text
        
    except Exception as e:
        logger.error(f"Error cleaning HTML content: {e}")
        return content

def send_progress(progress: int, message: str):
    """Send progress update to frontend"""
    progress_queue.put({
        'progress': progress,
        'message': message,
        'timestamp': datetime.now().isoformat()
    })

async def process_with_gpt(content: str) -> str:
    """Process content with GPT to extract artist and album information"""
    gpt_logger = logging.getLogger('spot-gpt')
    try:
        gpt_logger.debug("Initializing OpenAI client")
        send_progress(10, "Initializing GPT client...")
        openai_client = await ClientManager.get_openai()
        if not openai_client:
            gpt_logger.error("Failed to initialize OpenAI client")
            gui_message("Failed to initialize GPT client", True)
            raise Exception("Failed to initialize OpenAI client")

        gpt_logger.debug("Cleaning content for GPT processing")
        send_progress(20, "Cleaning content for analysis...")
        cleaned_content = clean_html_content(content)
        if not cleaned_content:
            gpt_logger.error("Content cleaning resulted in empty text")
            gui_message("No content to analyze after cleaning", True)
            raise Exception("No content to process after cleaning")

        # Ensure content is properly encoded
        cleaned_content = cleaned_content.encode('utf-8', errors='ignore').decode('utf-8')
        gpt_logger.debug(f"Content encoded successfully. Length: {len(cleaned_content)}")

        gpt_logger.debug(f"Splitting content into chunks (content length: {len(cleaned_content)})")
        send_progress(30, "Preparing content for analysis...")
        chunks = textwrap.wrap(cleaned_content, 4000, break_long_words=False, break_on_hyphens=False)
        if not chunks:
            gpt_logger.error("No content chunks created")
            gui_message("Failed to prepare content for analysis", True)
            raise Exception("No content chunks created for processing")

        total_chunks = len(chunks)
        gui_message(f"Processing content in {total_chunks} chunks...")
        send_progress(40, f"Starting analysis of {total_chunks} content chunks...")
        all_results = []
        
        for i, chunk in enumerate(chunks, 1):
            try:
                progress = 40 + (i / total_chunks * 30)  # Progress from 40% to 70%
                gui_message(f"Analyzing chunk {i}/{total_chunks}...")
                send_progress(int(progress), f"Analyzing chunk {i} of {total_chunks}...")
                gpt_logger.debug(f"Processing chunk {i}/{total_chunks}")
                
                # Ensure chunk is properly encoded
                chunk = chunk.encode('utf-8', errors='ignore').decode('utf-8')
                
                system_prompt = """You are a precise music information extractor. Your task is to identify and extract ONLY artist and album pairs from the provided text.

                Rules:
                1. Extract ONLY complete artist-album pairs
                2. Maintain exact original spelling and capitalization
                3. Include full albums only (no singles or EPs unless explicitly labeled as albums)
                4. Ignore any non-music content, advertisements, or navigation elements
                5. Do not include track listings or song names
                6. Do not include commentary, reviews, or ratings
                7. If an artist has multiple albums mentioned, list each pair separately
                8. Do not add any additional formatting or punctuation to artist or album names

                Format each pair exactly as: Artist - Album
                One pair per line
                No additional text, commentary, or punctuation"""

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract artist-album pairs from this text:\n\n{chunk}"}
                ]

                gpt_logger.debug("Sending request to OpenAI")
                response = await openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=messages,
                    temperature=0.0,  # Set to 0 for maximum consistency
                    max_tokens=2000
                )
                gpt_logger.debug("Received response from OpenAI")

                if not response or not hasattr(response.choices[0], 'message'):
                    gpt_logger.error(f"Invalid response from OpenAI: {response}")
                    gui_message(f"Error analyzing chunk {i}/{total_chunks}", True)
                    continue

                result = response.choices[0].message.content.strip()
                # Clean any potential leading/trailing quotes or apostrophes
                result = result.strip("'\"")
                gpt_logger.debug(f"Raw GPT result: {result}")

                if result:
                    valid_pairs = []
                    for line in result.split('\n'):
                        line = line.strip().strip("'\"")  # Clean any quotes/apostrophes
                        if ' - ' in line and not any(x in line.lower() for x in ['ep', 'single', 'remix', 'feat.']):
                            artist, album = line.split(' - ', 1)
                            # Clean any potential quotes or apostrophes from artist and album names
                            artist = artist.strip().strip("'\"")
                            album = album.strip().strip("'\"")
                            valid_pairs.append(f"{artist} - {album}")
                    all_results.extend(valid_pairs)
                    gpt_logger.debug(f"Found {len(valid_pairs)} valid pairs in chunk {i}")
                    gui_message(f"Found {len(valid_pairs)} albums in chunk {i}")
                    send_progress(int(progress), f"Found {len(valid_pairs)} albums in chunk {i}")
                else:
                    gpt_logger.warning(f"No results found in chunk {i}")
                    gui_message(f"No albums found in chunk {i}")
                    send_progress(int(progress), f"No albums found in chunk {i}")

            except Exception as e:
                gpt_logger.error(f"Error processing chunk {i}: {str(e)}", exc_info=True)
                gui_message(f"Error processing chunk {i}: {str(e)}", True)
                send_progress(int(progress), f"Error in chunk {i}: {str(e)}")
                continue

        if not all_results:
            gpt_logger.warning("No artist-album pairs found in any chunks")
            gui_message("No albums found in any content chunks")
            send_progress(70, "No albums found in content")
            return ""

        # Remove duplicates while preserving order
        seen = set()
        final_results = [item for item in all_results if item and item not in seen and not seen.add(item)]
        
        gpt_logger.info(f"Found {len(final_results)} unique artist-album pairs")
        gui_message(f"\nFound {len(final_results)} unique albums")
        send_progress(80, f"Found {len(final_results)} unique albums")
        
        # Ensure final output is properly encoded
        final_output = '\n'.join(final_results).encode('utf-8', errors='ignore').decode('utf-8')
        send_progress(90, "Preparing final results...")
        return final_output

    except Exception as e:
        gpt_logger.error(f"Error in process_with_gpt: {str(e)}", exc_info=True)
        gui_message(f"Error in GPT processing: {str(e)}", True)
        send_progress(0, f"Error: {str(e)}")
        raise

class ContentProcessor:
    """Handles content processing with improved efficiency"""
    def __init__(self):
        self._extractor = WebContentExtractor()
        self._search_manager = SpotifySearchManager()
        self._playlist_manager = PlaylistManager()
        self._file_handler = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._extractor.cleanup()

    async def process_url(self, url: str, destination_file: str) -> None:
        """Process URL and save results with improved error handling"""
        try:
            # Initialize file handler
            self._file_handler = FileHandler(destination_file)
            
            # Extract content
            content = await self._extractor.extract_content(url)
            
            # Process with GPT
            gpt_results = await process_with_gpt(content)
            
            new_entries = []
            user_message("\nProcessing found albums...")
            
            # Process each result
            for line in gpt_results.split('\n'):
                if ' - ' not in line:
                    continue
                    
                try:
                    artist, album = line.split(' - ', 1)
                    album_id = await self._search_manager.search_album(artist.strip(), album.strip())
                    
                    if album_id:
                        # Get album info including popularity
                        spotify = await ClientManager.get_spotify()
                        album_info = spotify.album(album_id)
                        album_popularity = album_info.get('popularity', 0)

                        # Get track info with popularity
                        tracks = []
                        track_results = spotify.album_tracks(album_id)
                        track_ids = [track['id'] for track in track_results['items']]
                        
                        # Get track details including popularity (in batches of 50)
                        for i in range(0, len(track_ids), 50):
                            batch_ids = track_ids[i:i+50]
                            batch_tracks = spotify.tracks(batch_ids)['tracks']
                            for track in batch_tracks:
                                if track:
                                    tracks.append({
                                        'name': track['name'],
                                        'popularity': track.get('popularity', 0)
                                    })

                        new_entries.append({
                            "Artist": artist.strip(),
                            "Album": album.strip(),
                            "Album ID": album_id,
                            "Album Popularity": album_popularity,
                            "Album Images": album_info.get('images', []),
                            "Tracks": tracks,
                            "Spotify Link": f"spotify:album:{album_id}",
                            "Extraction Date": datetime.now().isoformat()
                        })
                        
                except ValueError as e:
                    logger.warning(f"Error processing line '{line}': {e}")
                    continue
            
            # Review and save results if we have new entries
            if new_entries:
                saved = await review_and_save_results(new_entries, destination_file)
                if not saved:
                    # If user chose to exit to main menu or cancel, remove the file if it exists
                    if os.path.exists(destination_file):
                        os.remove(destination_file)
            else:
                user_message("No entries found to save")
                
        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            raise

async def review_and_save_results(entries: List[Dict], destination_file: str) -> bool:
    """Review and optionally edit results before saving. Returns True if saved, False if exited."""
    while True:
        user_message("\nReview found albums:")
        for i, entry in enumerate(entries, 1):
            popularity = entry.get('Album Popularity', 0)
            user_message(f"{i}. {entry['Artist']} - {entry['Album']} (Popularity: {popularity})")
        
        user_message("\nWhat would you like to do?")
        user_message("1. Save all")
        user_message("2. Delete an entry")
        user_message("3. Cancel")
        user_message("4. Exit to main menu")
        
        choice = input("Choose (1-4): ").strip()
        
        if choice == "1":
            file_handler = FileHandler(destination_file)
            await file_handler.save(entries)
            user_message(f"Saved {len(entries)} entries to {destination_file}")
            return True
        elif choice == "2":
            entry_num = input("Enter the number of the entry to delete (or 'b' to go back): ").strip()
            if entry_num.lower() == 'b':
                continue
            try:
                idx = int(entry_num) - 1
                if 0 <= idx < len(entries):
                    deleted = entries.pop(idx)
                    user_message(f"Deleted: {deleted['Artist']} - {deleted['Album']} (Popularity: {deleted.get('Album Popularity', 0)})")
                else:
                    user_message("Invalid entry number")
            except ValueError:
                user_message("Please enter a valid number")
        elif choice == "3":
            user_message("Operation cancelled")
            return False
        elif choice == "4":
            user_message("Returning to main menu")
            return False
        else:
            user_message("Invalid choice")

async def scan_spotify_links(url: str, destination_file: str = None):
    """Scan webpage for Spotify links and add artist and album data to JSON"""
    extractor = WebContentExtractor()
    try:
        # Ensure we're using the correct data directory
        data_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SpotScrape_data"))
        os.makedirs(data_dir, exist_ok=True)
        
        # If no destination file specified, use default
        if not destination_file:
            destination_file = os.path.normpath(os.path.join(data_dir, "spotscrape_url.json"))
        
        logger.debug(f"Using destination file: {destination_file}")
        
        # Get scan timestamp
        scan_time = datetime.now().isoformat()
        logger.debug(f"Starting scan at: {scan_time}")

        # Extract content with progress indicator
        gui_message("\nExtracting webpage content...")
        send_progress(10, "Extracting webpage content...")
        content = await extractor.extract_content(url)
        logger.debug(f"Content extracted, length: {len(content)} characters")
        
        # Clean HTML content
        gui_message("Processing webpage content...")
        send_progress(20, "Processing webpage content...")
        cleaned_content = clean_html_content(content)
        logger.debug(f"Content cleaned, length: {len(cleaned_content)} characters")
        
        # Log a sample of the cleaned content for debugging
        content_sample = cleaned_content[:1000]
        logger.debug(f"Cleaned content sample: {content_sample}")
        
        # Enhanced regex pattern to capture various Spotify album link formats
        spotify_patterns = [
            r'spotify:album:([a-zA-Z0-9]{22})',  # URI format
            r'open\.spotify\.com/album/([a-zA-Z0-9]{22})',  # Web URL format
            r'spotify\.com/album/([a-zA-Z0-9]{22})',  # Alternative web URL format
            r'href="[^"]*?/album/([a-zA-Z0-9]{22})',  # href attribute format
            r'data-uri="spotify:album:([a-zA-Z0-9]{22})',  # data-uri attribute format
            r'/album/([a-zA-Z0-9]{22})',  # Simple album ID format
        ]
        
        # Collect all unique album IDs with progress indicator
        gui_message("Scanning for Spotify album links...")
        send_progress(30, "Scanning for Spotify album links...")
        album_ids = set()
        for i, pattern in enumerate(spotify_patterns):
            progress = 30 + ((i + 1) / len(spotify_patterns) * 20)  # Progress from 30% to 50%
            send_progress(int(progress), f"Scanning pattern {i + 1}/{len(spotify_patterns)}...")
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Extract the album ID from the capturing group
                album_id = match.group(1)
                if album_id and len(album_id) == 22:  # Spotify IDs are 22 characters
                    album_ids.add(album_id)
                    logger.debug(f"Found album ID: {album_id} using pattern: {pattern}")

        gui_message(f"\nFound {len(album_ids)} unique Spotify album links")
        send_progress(50, f"Found {len(album_ids)} unique Spotify album links")
        
        # Process each album with progress indicator
        entries = []
        spotify = await ClientManager.get_spotify()
        
        for i, album_id in enumerate(album_ids):
            progress = 50 + ((i + 1) / len(album_ids) * 45)  # Progress from 50% to 95%
            try:
                album_info = spotify.album(album_id)
                entry = {
                    'id': album_id,
                    'artist': album_info['artists'][0]['name'],
                    'name': album_info['name'],
                    'popularity': album_info.get('popularity', 0),
                    'images': album_info.get('images', []),
                    'spotify_url': f"spotify:album:{album_id}",
                    'source_url': url,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                entries.append(entry)
                gui_message(f"Processing album {i + 1}/{len(album_ids)}: {entry['artist']} - {entry['name']}")
                send_progress(int(progress), f"Processing album {i + 1}/{len(album_ids)}: {entry['artist']} - {entry['name']}")
            except Exception as e:
                logger.error(f"Error processing album {album_id}: {str(e)}")
                continue
        
        # Save results
        if entries:
            try:
                send_progress(95, "Saving results...")
                with open(destination_file, 'w', encoding='utf-8') as f:
                    json.dump(entries, f, indent=2, ensure_ascii=False)
                logger.info(f"Saved {len(entries)} URL scan results to {destination_file}")
                send_progress(100, f"Completed! Found {len(entries)} albums")
            except Exception as e:
                logger.error(f"Error saving URL scan results: {e}")
                send_progress(95, "Error saving results")
        else:
            send_progress(100, "Completed! No albums found")
        
        return entries
        
    except Exception as e:
        logger.error(f"Error in scan_spotify_links: {str(e)}")
        send_progress(0, f"Error: {str(e)}")
        raise
    finally:
        # Ensure Playwright resources are cleaned up
        await extractor.cleanup()

async def scan_webpage(url: str, destination_file: str) -> List[Dict[str, Any]]:
    """Scan a webpage for music content using GPT and save results to a file."""
    gpt_logger = logging.getLogger('spot-gpt')
    try:
        # Extract content
        web_extractor = WebContentExtractor()
        gui_message("Initializing web content extraction...")
        send_progress(5, "Initializing web content extraction...")
        content = await web_extractor.extract_content(url)
        
        if not content:
            gpt_logger.error("No content could be extracted from the webpage")
            gui_message("Failed to extract content from webpage", True)
            send_progress(0, "Failed to extract content from webpage")
            return []
            
        gpt_logger.info(f"Content extracted successfully ({len(content)} characters)")
        gui_message(f"Successfully extracted {len(content)} characters of content")
        send_progress(10, "Content extracted successfully")
        
        # Process with GPT
        gui_message("Starting GPT analysis of content...")
        gpt_results = await process_with_gpt(content)
        
        if not gpt_results:
            gpt_logger.warning("No results found by GPT")
            gui_message("No music content found by GPT analysis")
            send_progress(90, "No music content found")
            return []
            
        # Process each result with Spotify
        spotify_manager = SpotifySearchManager()
        results = []
        
        # Split the GPT results into individual pairs
        pairs = [pair.strip() for pair in gpt_results.split('\n') if pair.strip()]
        total_pairs = len(pairs)
        gui_message(f"\nFound {total_pairs} potential albums to process")
        send_progress(90, f"Processing {total_pairs} albums with Spotify...")
        
        for i, pair in enumerate(pairs, 1):
            progress = 90 + (i / total_pairs * 8)  # Progress from 90% to 98%
            if ' - ' not in pair:
                continue
                
            artist, album = pair.split(' - ', 1)
            artist = artist.strip()
            album = album.strip()
            
            gui_message(f"Processing album {i}/{total_pairs}: {artist} - {album}")
            send_progress(int(progress), f"Processing album {i}/{total_pairs}...")
            
            try:
                # Search for the album on Spotify
                spotify = await ClientManager.get_spotify()
                search_result = spotify.search(f"album:{album} artist:{artist}", type='album', limit=1)
                
                if search_result and search_result['albums']['items']:
                    album_info = search_result['albums']['items'][0]
                    album_id = album_info['id']
                    
                    # Get full album details
                    full_album_info = spotify.album(album_id)
                    
                    formatted_album = {
                        'id': album_id,
                        'artist': artist,
                        'name': album,
                        'popularity': full_album_info.get('popularity', 0),
                        'images': full_album_info.get('images', []),
                        'spotify_url': f"spotify:album:{album_id}",
                        'source_url': url,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    results.append(formatted_album)
                    gpt_logger.info(f"Found album: {artist} - {album}")
                    gui_message(f"✓ Found on Spotify: {artist} - {album}")
                    send_progress(int(progress), f"✓ Found: {artist} - {album}")
                else:
                    gui_message(f"✗ Not found on Spotify: {artist} - {album}")
                    send_progress(int(progress), f"✗ Not found: {artist} - {album}")
            except Exception as e:
                gpt_logger.error(f"Error processing album {artist} - {album}: {str(e)}")
                gui_message(f"✗ Error processing: {artist} - {album}")
                send_progress(int(progress), f"✗ Error: {artist} - {album}")
                continue

        if results:
            # Save results to file
            try:
                # Ensure the directory exists
                os.makedirs(os.path.dirname(destination_file), exist_ok=True)
                send_progress(98, "Saving results...")
                
                # Write the results to the specified destination file
                with open(destination_file, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)
                gpt_logger.info(f"Saved {len(results)} GPT scan results to {destination_file}")
                gui_message(f"\nSuccessfully saved {len(results)} albums to file")
                send_progress(100, f"Completed! Found {len(results)} albums")
            except Exception as e:
                gpt_logger.error(f"Error saving GPT scan results: {e}")
                gui_message("Error saving results to file", True)
                send_progress(98, "Error saving results")
        else:
            gpt_logger.warning("No albums found to save")
            gui_message("No albums were found to save")
            send_progress(100, "Completed! No albums found")
        
        # Return the results regardless of whether file save was successful
        return results
        
    except Exception as e:
        gpt_logger.error(f"Error during webpage scan: {str(e)}", exc_info=True)
        gui_message(f"Error during scan: {str(e)}", True)
        send_progress(0, f"Error: {str(e)}")
        return []
    finally:
        # Clean up resources
        await web_extractor.cleanup()

async def create_playlist(json_file: str, playlist_name: str = None):
    """Create a Spotify playlist from a JSON file with improved efficiency"""
    try:
        # Load JSON data
        user_message("\nLoading JSON data...")
        data = FileHandler.load_json(json_file)
        if not data:
            user_message("No data found in the JSON file.")
            return

        # Get user choice for playlist type
        user_message("\nWhat type of playlist would you like to create?")
        user_message("1. All tracks from albums")
        user_message("2. Most popular track from each album (Sampler)")
        choice = input("Enter your choice (1 or 2): ").strip()
        
        is_sampler = choice == "2"
        
        # Get or generate playlist name
        if not playlist_name:
            default_name = f"{'Sampler ' if is_sampler else ''}Playlist {datetime.now().strftime('%Y%m%d_%H%M%S')}"
            playlist_name = input(f"\nEnter playlist name (default: {default_name}): ").strip() or default_name

        description = f"{'Sampler playlist' if is_sampler else 'Full playlist'} created by SpotScrape on {datetime.now().strftime('%Y-%m-%d')}"
        
        # Initialize managers
        playlist_manager = PlaylistManager()
        track_uris = []
        
        user_message("\nProcessing albums...")
        spotify = await ClientManager.get_spotify()
        
        # Process albums with progress indicator
        async with ProgressIndicator(len(data), desc="Processing albums", unit="album") as pbar:
            for entry in data:
                album_id = entry.get('Album ID') or entry.get('Spotify Link', '').split(':')[-1]
                if not album_id:
                    logger.warning(f"No valid album ID found for entry: {entry}")
                    pbar.update(1)
                    continue
                
                try:
                    # Get album tracks
                    album_tracks = spotify.album_tracks(album_id)
                    track_count = len(album_tracks['items'])
                    pbar.set_description(f"Found {track_count} tracks in current album")
                    
                    if is_sampler:
                        # Get all track IDs for batch processing
                        track_ids = [track['id'] for track in album_tracks['items']]
                        tracks_info = await playlist_manager._get_tracks_info(track_ids)
                        
                        # Find most popular track
                        most_popular = None
                        highest_popularity = -1
                        
                        for track in album_tracks['items']:
                            track_info = tracks_info.get(track['id'])
                            if track_info:
                                popularity = track_info.get('popularity', 0)
                                if popularity > highest_popularity:
                                    highest_popularity = popularity
                                    most_popular = track
                        
                        if most_popular:
                            track_uris.append(most_popular['uri'])
                            pbar.set_description(f"Added: {most_popular['name']} (Popularity: {highest_popularity})")
                    else:
                        # Add all tracks
                        album_track_uris = [track['uri'] for track in album_tracks['items']]
                        track_uris.extend(album_track_uris)
                        pbar.set_description(f"Added {len(album_track_uris)} tracks from current album")
                        
                except Exception as e:
                    logger.error(f"Error processing album {album_id}: {str(e)}")
                    continue
                finally:
                    pbar.update(1)

        if not track_uris:
            user_message("No tracks found to add to playlist.")
            return

        # Create playlist and add tracks
        try:
            user_message("\nCreating playlist...")
            playlist_id = await playlist_manager.create_playlist(playlist_name, description)
            
            # Add tracks with progress indicator
            total_batches = (len(track_uris) + playlist_manager.batch_size - 1) // playlist_manager.batch_size
            async with ProgressIndicator(total_batches, desc="Adding tracks to playlist", unit="batch") as pbar:
                for i in range(0, len(track_uris), playlist_manager.batch_size):
                    batch = track_uris[i:i + playlist_manager.batch_size]
                    await playlist_manager.add_tracks(playlist_id, batch)
                    tracks_added = min(i + playlist_manager.batch_size, len(track_uris))
                    pbar.set_description(f"Added {tracks_added}/{len(track_uris)} tracks")
                    pbar.update(1)
            
            user_message(f"\nSuccessfully created playlist '{playlist_name}' with {len(track_uris)} tracks!")
            
        except Exception as e:
            logger.error(f"Error creating playlist: {str(e)}")
            user_message(f"Error: {str(e)}")
            return

    except Exception as e:
        logger.error(f"Error in create_playlist: {str(e)}")
        user_message(f"Error: {str(e)}")
        return

class ProgressIndicator:
    """Handles progress indication for long-running operations"""
    def __init__(self, total: int, desc: str = "", unit: str = ""):
        self.total = total
        self.desc = desc
        self.unit = unit
        self._progress = 0
        self._lock = threading.Lock()
        self.pbar = tqdm(total=total, desc=desc, unit=unit)

    def update(self, amount: int = 1):
        """Update progress by the specified amount"""
        with self._lock:
            self._progress += amount
            self.pbar.update(amount)

    def set_description(self, desc: str):
        """Update the description of the progress bar"""
        self.pbar.set_description(desc)

    def close(self):
        """Close the progress bar"""
        self.pbar.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.close()

async def main():
    """Main application entry point with improved error handling and user interaction"""
    try:
        # Validate environment variables
        required_env_vars = [
            "SPOTIPY_CLIENT_ID",
            "SPOTIPY_CLIENT_SECRET",
            "SPOTIPY_REDIRECT_URI",
            "OPENAI_API_KEY"
        ]
        
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            user_message(f"Missing required environment variables: {', '.join(missing_vars)}")
            return

        # Create JSON directory if it doesn't exist
        json_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "JSON"))
        os.makedirs(json_dir, exist_ok=True)

        while True:
            user_message("\nSpotScraper Menu:")
            user_message("1. Scan webpage for Spotify links")
            user_message("2. Scan webpage for music content")
            user_message("3. Create Spotify playlist from JSON")
            user_message("4. Exit")
            
            choice = input("\nEnter your choice (1-4): ").strip()
            
            if choice == "1":
                url = input("\nEnter URL to scan for Spotify links: ").strip()
                if not url:
                    user_message("No URL provided")
                    continue

                default_path = os.path.normpath(os.path.join(json_dir, "spotscrape_url.json"))
                
                user_message("\nWhere would you like to save the results?")
                user_message(f"1. Default location ({default_path})")
                user_message("2. Custom location")
                user_message("3. Exit to main menu")
                
                file_choice = input("Choose (1-3): ").strip()
                
                if file_choice == "2":
                    destination_file = input("Enter full path for JSON file (or 'b' to go back): ").strip()
                    if destination_file.lower() == 'b':
                        continue
                    destination_file = os.path.normpath(os.path.expanduser(destination_file))
                elif file_choice == "3":
                    user_message("Returning to main menu")
                    continue
                else:
                    destination_file = default_path
                
                # Ensure directory exists
                os.makedirs(os.path.dirname(destination_file), exist_ok=True)
                
                user_message(f"\nScanning {url} for Spotify links...")
                await scan_spotify_links(url, destination_file)
                user_message("Scan complete!")

            elif choice == "2":
                url = input("\nEnter URL to scan: ").strip()
                if not url:
                    user_message("No URL provided")
                    continue

                default_path = os.path.normpath(os.path.join(json_dir, "spotscrape_gpt.json"))
                
                user_message("\nWhere would you like to save the results?")
                user_message(f"1. Default location ({default_path})")
                user_message("2. Custom location")
                user_message("3. Exit to main menu")
                
                file_choice = input("Choose (1-3): ").strip()
                
                if file_choice == "2":
                    destination_file = input("Enter full path for JSON file (or 'b' to go back): ").strip()
                    if destination_file.lower() == 'b':
                        continue
                    destination_file = os.path.normpath(os.path.expanduser(destination_file))
                elif file_choice == "3":
                    user_message("Returning to main menu")
                    continue
                else:
                    destination_file = default_path
                
                # Ensure directory exists
                os.makedirs(os.path.dirname(destination_file), exist_ok=True)
                
                user_message(f"\nScanning {url}...")
                await scan_webpage(url, destination_file)
                user_message("Scan complete!")

            elif choice == "3":
                # Show both default files as options
                url_default = os.path.normpath(os.path.join(json_dir, "spotscrape_url.json"))
                gpt_default = os.path.normpath(os.path.join(json_dir, "spotscrape_gpt.json"))
                
                user_message("\nEnter the path to your JSON file:")
                user_message(f"1. URL scan results ({url_default})")
                user_message(f"2. GPT scan results ({gpt_default})")
                user_message("3. Custom location")
                user_message("4. Exit to main menu")
                
                file_choice = input("Choose (1-4): ").strip()
                
                if file_choice == "1":
                    json_file = url_default
                elif file_choice == "2":
                    json_file = gpt_default
                elif file_choice == "4":
                    user_message("Returning to main menu")
                    continue
                else:
                    json_file = input("Enter full path to JSON file (or 'b' to go back): ").strip()
                    if json_file.lower() == 'b':
                        continue
                    json_file = os.path.normpath(os.path.expanduser(json_file))

                if not os.path.exists(json_file):
                    user_message(f"File not found: {json_file}")
                    continue

                playlist_name = input("\nEnter playlist name (or press Enter for default): ").strip()
                await create_playlist(json_file, playlist_name)

            elif choice == "4":
                user_message("\nGoodbye!")
                return  # Use return instead of break to ensure proper cleanup

            else:
                user_message("Invalid choice. Please enter 1-4.")

    except KeyboardInterrupt:
        user_message("\nOperation cancelled by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        user_message("An unexpected error occurred. Check the logs for details.")
    finally:
        # Clean up ClientManager resources only
        await ClientManager.cleanup()

if __name__ == "__main__":
    try:
        # Set up logging first
        logger, spotify_logger = setup_logging()
        
        # Load environment variables
        load_dotenv()
        
        # Validate environment variables
        required_vars = [
            "SPOTIPY_CLIENT_ID",
            "SPOTIPY_CLIENT_SECRET",
            "SPOTIPY_REDIRECT_URI",
            "OPENAI_API_KEY"
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            sys.exit(1)
        
        # Run the application with proper cleanup
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main())
        finally:
            try:
                # Cancel all running tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                
                # Allow cancelled tasks to complete
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                
                # Clean up Windows-specific resources
                if sys.platform == 'win32':
                    for task in pending:
                        if hasattr(task, '_transport') and task._transport is not None:
                            try:
                                if hasattr(task._transport, '_proc'):
                                    task._transport._proc = None
                                task._transport.close()
                            except:
                                pass
                
                # Shutdown async generators and close the loop
                if hasattr(loop, '_proactor'):
                    loop._proactor.close()
                loop.close()
                
            except Exception as e:
                logger.error(f"Error during final cleanup: {e}")
            finally:
                # Ensure the loop is closed
                if not loop.is_closed():
                    loop.close()
        
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"\nFatal error: {e}")
        sys.exit(1)
        