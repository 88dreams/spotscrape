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
from openai import OpenAI
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
from pathlib import Path

# Suppress specific warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.HTTPWarning)
warnings.filterwarnings("ignore", message=".*Content-Length and Transfer-Encoding.*", 
                       category=UserWarning, module='urllib3')

# Global cache configurations
CACHE_TTL = 3600  # 1 hour cache lifetime
request_cache = TTLCache(maxsize=100, ttl=CACHE_TTL)
spotify_cache = TTLCache(maxsize=1000, ttl=CACHE_TTL)

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if i == retries - 1:  # Last attempt
                        raise
                    wait_time = (backoff_in_seconds * 2 ** i) + random.uniform(0, 1)
                    logger.warning(f"Attempt {i + 1} failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
            return await func(*args, **kwargs)  # Final attempt
        return wrapper
    return decorator

# Initialize logger at module level with a NullHandler to prevent "No handlers" warnings
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

def setup_logging():
    """Set up logging with improved configuration"""
    log_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 
        "logfiles"
    ))
    os.makedirs(log_dir, exist_ok=True)
    
    log_number = get_next_log_number()
    log_file = os.path.normpath(os.path.join(log_dir, f"spotscraper{log_number}.log"))
    
    # Create formatter
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    
    try:
        # Set up file handler
        file_handler = RotatingFileHandler(
            log_file,
            mode='a',  # Open in append mode to prevent conflicts
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        
        # Configure module logger only
        logger.handlers.clear()  # Clear existing handlers
        logger.addHandler(file_handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # Prevent duplicate logging
        
        print(f"Logging to file: {log_file}")
        return log_file
        
    except Exception as e:
        print(f"Error setting up logging: {str(e)}")
        raise

def user_message(msg: str, log_only: bool = False):
    """Print a message to console and log it"""
    if not log_only:
        print(msg)
    logger.info(msg)  # Log the message without USER: prefix

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
    def get_openai(cls):
        """Get or create OpenAI client"""
        if cls._openai_instance is None:
            cls._openai_instance = OpenAI(
                api_key=os.getenv('OPENAI_API_KEY')
            )
        return cls._openai_instance

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
        self.batch_size = 100
        self._spotify = None

    async def _get_spotify(self):
        if not self._spotify:
            self._spotify = await ClientManager.get_spotify()
        return self._spotify

    @RateLimiter(max_calls=100, time_period=60)
    async def create_playlist(self, name: str, description: str = "") -> str:
        """Create a new playlist with rate limiting and caching"""
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
                return playlist['id']
        except Exception as e:
            logger.error(f"Error creating playlist '{name}': {e}")
            raise

    @retry_with_backoff(retries=3)
    async def add_tracks(self, playlist_id: str, track_uris: List[str]) -> None:
        """Add tracks to playlist with retries and improved error handling"""
        if not track_uris:
            return

        try:
            spotify = await self._get_spotify()
            
            for i in range(0, len(track_uris), self.batch_size):
                batch = track_uris[i:i + self.batch_size]
                try:
                    async with self._lock:
                        spotify.playlist_add_items(playlist_id, batch)
                    await asyncio.sleep(0.1)  # Prevent rate limiting
                    logger.debug(f"Added batch of {len(batch)} tracks to playlist {playlist_id}")
                except Exception as e:
                    logger.error(f"Error adding batch to playlist: {e}")
                    # Continue with next batch instead of failing completely
                    continue
                    
        except Exception as e:
            logger.error(f"Error adding tracks to playlist {playlist_id}: {e}")
            raise

class SpotifySearchManager:
    """Handles Spotify search operations with caching"""
    def __init__(self):
        self._lock = AsyncLock()
        self._cache = TTLCache(maxsize=1000, ttl=CACHE_TTL)
        self._spotify = None

    async def _get_spotify(self):
        if not self._spotify:
            self._spotify = await ClientManager.get_spotify()
        return self._spotify

    @RateLimiter(max_calls=100, time_period=60)
    async def search_album(self, artist: str, album: str) -> Optional[str]:
        """Search for album with caching and rate limiting"""
        cache_key = f"{artist}:{album}"
        
        if cache_key in self._cache:
            return self._cache[cache_key]

        spotify = await self._get_spotify()
        
        # Clean search terms
        artist = artist.replace('$', 's').replace('/', ' ').strip()
        album = album.replace('/', ' ').strip()
        
        async with self._lock:
            try:
                # Try exact search first
                query = f'album:"{album}" artist:"{artist}"'
                results = spotify.search(q=query, type='album', limit=1)
                
                if results and results['albums']['items']:
                    album_id = results['albums']['items'][0]['id']
                    self._cache[cache_key] = album_id
                    return album_id
                
                # Try fuzzy search
                query = f'"{artist}" "{album}"'
                results = spotify.search(q=query, type='album', limit=1)
                
                if results and results['albums']['items']:
                    album_id = results['albums']['items'][0]['id']
                    self._cache[cache_key] = album_id
                    return album_id
                
                self._cache[cache_key] = None
                return None
                
            except Exception as e:
                logger.error(f"Error searching for album '{album}' by '{artist}': {e}")
                return None

    @retry_with_backoff(retries=3)
    async def search_track(self, query: str) -> Optional[str]:
        """Search for track with retries and improved error handling"""
        cache_key = f"track:{query}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            spotify = await self._get_spotify()
            results = spotify.search(q=query, type='track', limit=1)
            
            if not results or 'tracks' not in results or 'items' not in results['tracks']:
                logger.warning(f"Invalid response format for query: {query}")
                return None
            
            if results['tracks']['items']:
                track_uri = results['tracks']['items'][0]['uri']
                self._cache[cache_key] = track_uri
                return track_uri
            
            logger.debug(f"No results found for query: {query}")
            return None
            
        except Exception as e:
            logger.error(f"Error searching for track '{query}': {e}")
            raise

class WebContentExtractor:
    """Handles web content extraction with improved efficiency"""
    def __init__(self):
        self._lock = AsyncLock()
        self._playwright = None
        self._browser = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def setup(self):
        """Initialize Playwright resources"""
        if not self._playwright:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-blink-features=AutomationControlled'
                ]
            )

    async def cleanup(self):
        """Clean up Playwright resources"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def extract_content(self, url: str) -> str:
        """Extract content from webpage with improved error handling"""
        if not self._browser:
            await self.setup()

        async with self._lock:
            try:
                context = await self._browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    java_script_enabled=True
                )
                
                # Add stealth mode scripts
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
                
                page = await context.new_page()
                try:
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
                    await context.close()
                    
            except Exception as e:
                logger.error(f"Error extracting content from {url}: {e}")
                raise

def get_next_log_number() -> int:
    """Get the next available log file number (0-9) with improved efficiency"""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logfiles")
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

async def process_with_gpt(content: str, chunk_size: int = 4000) -> List[Dict]:
    """Process content with GPT with improved content filtering and prompting"""
    try:
        # Clean and chunk the content
        cleaned_content = clean_html_content(content)
        chunks = textwrap.wrap(cleaned_content, chunk_size, break_long_words=False, break_on_hyphens=False)
        
        system_prompt = """You are a precise music information extractor. Extract song and album references from the text.

        Rules:
        1. Extract BOTH songs and albums with their artists
        2. Maintain exact original spelling and capitalization
        3. Include both individual songs and full albums
        4. Ignore any non-music content, advertisements, or navigation elements
        5. Format each song as: {"type": "song", "artist": "Artist Name", "title": "Song Title"}
        6. Format each album as: {"type": "album", "artist": "Artist Name", "title": "Album Title"}
        7. If unsure about a reference, skip it
        8. Return one item per line in the specified JSON format
        9. Do not include commentary or explanations

        Example output:
        {"type": "song", "artist": "The Beatles", "title": "Hey Jude"}
        {"type": "album", "artist": "Pink Floyd", "title": "The Dark Side of the Moon"}"""

        all_items = []
        openai_client = ClientManager.get_openai()
        
        for chunk in chunks:
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Extract song and album references from this text:\n\n{chunk}"}
                    ],
                    temperature=0.3,  # Lower temperature for more consistent output
                    max_tokens=1000
                )
                
                # Process the response
                for line in response.choices[0].message.content.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        if item['type'] in ['song', 'album']:
                            all_items.append(item)
                    except json.JSONDecodeError:
                        continue
                
            except Exception as e:
                logger.warning(f"Error processing chunk with GPT: {e}")
                continue
        
        # Remove duplicates while preserving order
        seen = set()
        unique_items = []
        for item in all_items:
            key = f"{item['type']}:{item['artist']}:{item['title']}"
            if key not in seen:
                seen.add(key)
                unique_items.append(item)
        
        return unique_items
        
    except Exception as e:
        logger.error(f"Error in GPT processing: {e}")
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
            
            # Load existing data
            existing_data = await self._file_handler.load()
            if not isinstance(existing_data, list):
                existing_data = []
            
            new_entries = []
            
            # Process each result
            for line in gpt_results.split('\n'):
                if ' - ' not in line:
                    continue
                    
                try:
                    artist, album = line.split(' - ', 1)
                    album_id = await self._search_manager.search_album(artist.strip(), album.strip())
                    
                    if album_id:
                        new_entries.append({
                            "Artist": artist.strip(),
                            "Album": album.strip(),
                            "Spotify Link": f"spotify:album:{album_id}",
                            "Extraction Date": datetime.now().isoformat()
                        })
                        
                except ValueError as e:
                    logger.warning(f"Error processing line '{line}': {e}")
                    continue
            
            # Save results if we have new entries
            if new_entries:
                await self._file_handler.save(new_entries)
                user_message(f"Added {len(new_entries)} new entries to {destination_file}")
            else:
                user_message("No new entries found to add")
                
        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            raise

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
        """Initialize Playwright resources"""
        async with self._lock:
            if not self._playwright:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch()
                self._context = await self._browser.new_context()

    async def cleanup(self):
        """Clean up Playwright resources"""
        async with self._lock:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._context = None
            self._browser = None
            self._playwright = None

    async def process_url(self, url: str) -> str:
        """Process a single URL and return its content"""
        if not self._browser:
            await self.setup()

        async with self._lock:
            try:
                page = await self._context.new_page()
                await page.goto(url)
                content = await page.content()
                await page.close()
                return content
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}")
                raise

def retry_with_backoff(retries=3, backoff_in_seconds=1):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if i == retries - 1:  # Last attempt
                        raise
                    wait_time = (backoff_in_seconds * 2 ** i) + random.uniform(0, 1)
                    logger.warning(f"Attempt {i + 1} failed: {str(e)}. Retrying in {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
            return await func(*args, **kwargs)  # Final attempt
        return wrapper
    return decorator

class ResourceManager:
    """Manages shared resources and cleanup"""
    def __init__(self):
        self._resources = set()
        self._lock = AsyncLock()

    async def register(self, resource):
        """Register a resource for cleanup"""
        async with self._lock:
            self._resources.add(resource)

    async def cleanup(self):
        """Clean up all registered resources"""
        async with self._lock:
            for resource in self._resources:
                try:
                    if hasattr(resource, 'cleanup'):
                        await resource.cleanup()
                    elif hasattr(resource, 'close'):
                        await resource.close()
                except Exception as e:
                    logger.error(f"Error cleaning up resource {resource}: {e}")
            self._resources.clear()

class SpotScraper:
    """Main class for scanning and managing Spotify links"""
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self._lock = AsyncLock()
        self._spotify = None
        self._file_handlers = {}

    async def _get_spotify(self):
        """Get or initialize Spotify client"""
        if not self._spotify:
            self._spotify = await ClientManager.get_spotify()
        return self._spotify

    def _get_default_data_path(self, scan_type: str) -> str:
        """Get the default path for saving scan data"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(script_dir, 'SpotScrape_data')
        os.makedirs(data_dir, exist_ok=True)
        
        if scan_type == 'url':
            return os.path.join(data_dir, 'musicdata_url.json')
        elif scan_type == 'gpt':
            return os.path.join(data_dir, 'musicdata_gpt.json')
        else:
            raise ValueError(f"Invalid scan type: {scan_type}")

    @retry_with_backoff(retries=3)
    async def scan_spotify_links(self, url: str) -> List[Dict]:
        """Scan a webpage for Spotify links"""
        self.logger.info(f"Scanning URL: {url}")
        
        spotify_patterns = [
            'spotify.com/track/',
            'spotify.com/album/',
            'spotify.com/artist/',
            'spotify:track:',
            'spotify:album:',
            'spotify:artist:'
        ]
        
        url_pattern = r'https?://[^\s<>"]+?(?:{})[^\s<>"]*'.format('|'.join(spotify_patterns))
        
        try:
            self.logger.debug("Creating aiohttp session")
            async with aiohttp.ClientSession() as session:
                self.logger.debug(f"Fetching URL: {url}")
                async with session.get(url, timeout=10) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to fetch URL: {response.status}")
                    
                    self.logger.debug("Reading response content")
                    content = await response.text()
                    self.logger.debug(f"Fetched content length: {len(content)}")
                    
                    # Parse HTML and find links
                    self.logger.debug("Parsing HTML content")
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Look for links in various places
                    links = set()
                    
                    # Check <a> tags
                    self.logger.debug("Searching for links in <a> tags")
                    for a in soup.find_all('a', href=True):
                        if re.search(url_pattern, a['href']):
                            links.add(a['href'])
                    
                    # Check embedded iframes
                    self.logger.debug("Searching for links in iframes")
                    for iframe in soup.find_all('iframe', src=True):
                        if re.search(url_pattern, iframe['src']):
                            links.add(iframe['src'])
                    
                    # Check for links in text content using regex
                    self.logger.debug("Searching for links in text content")
                    text_content = soup.get_text()
                    links.update(re.findall(url_pattern, text_content))
                    
                    self.logger.info(f"Found {len(links)} raw Spotify links")
                    
                    # Process found links
                    items = []
                    spotify = await self._get_spotify()
                    
                    self.logger.debug("Processing found links")
                    for link in links:
                        try:
                            if 'track' in link:
                                self.logger.debug(f"Processing track link: {link}")
                                track_id = link.split('/')[-1].split('?')[0]
                                track = spotify.track(track_id)
                                items.append({
                                    'artist': track['artists'][0]['name'],
                                    'album': track['album']['name'],
                                    'spotify_url': link,
                                    'source_url': url,
                                    'timestamp': datetime.now().isoformat()
                                })
                                self.logger.debug(f"Added track: {track['artists'][0]['name']} - {track['album']['name']}")
                            elif 'album' in link:
                                self.logger.debug(f"Processing album link: {link}")
                                album_id = link.split('/')[-1].split('?')[0]
                                album = spotify.album(album_id)
                                items.append({
                                    'artist': album['artists'][0]['name'],
                                    'album': album['name'],
                                    'spotify_url': link,
                                    'source_url': url,
                                    'timestamp': datetime.now().isoformat()
                                })
                                self.logger.debug(f"Added album: {album['artists'][0]['name']} - {album['name']}")
                        except Exception as e:
                            self.logger.warning(f"Error processing link {link}: {str(e)}")
                            continue
                    
                    self.logger.info(f"Found {len(items)} unique Spotify items")
                    return items
                    
        except Exception as e:
            self.logger.error(f"Error scanning URL {url}: {str(e)}")
            raise

    @retry_with_backoff(retries=3)
    async def scan_webpage(self, url: str, destination_file: str = None) -> List[Dict]:
        """Scan a webpage using GPT to extract music information"""
        self.logger.info(f"Scanning webpage with GPT: {url}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to fetch URL: {response.status}")
                    
                    content = await response.text()
                    
                    # Use GPT to extract music information
                    client = ClientManager.get_openai()
                    completion = client.chat.completions.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": "You are a music information extractor. Extract artist names and album titles from the given text."},
                            {"role": "user", "content": content}
                        ]
                    )
                    
                    # Process GPT response
                    items = []
                    spotify = await self._get_spotify()
                    
                    for line in completion.choices[0].message.content.split('\n'):
                        if ':' in line:
                            try:
                                artist, album = line.split(':', 1)
                                search_query = f"artist:{artist.strip()} album:{album.strip()}"
                                results = spotify.search(search_query, type='album')
                                
                                if results['albums']['items']:
                                    album_info = results['albums']['items'][0]
                                    items.append({
                                        'artist': album_info['artists'][0]['name'],
                                        'album': album_info['name'],
                                        'spotify_url': album_info['external_urls']['spotify'],
                                        'source_url': url,
                                        'timestamp': datetime.now().isoformat()
                                    })
                            except Exception as e:
                                self.logger.warning(f"Error processing GPT result: {str(e)}")
                    
                    self.logger.info(f"Found {len(items)} items from GPT analysis")
                    
                    # Save to file if destination is provided
                    if destination_file:
                        handler = FileHandler(destination_file)
                        await handler.save(items)
                        self.logger.info(f"Saved items to {destination_file}")
                    
                    return items
                    
        except Exception as e:
            self.logger.error(f"Error scanning webpage {url}: {str(e)}")
            raise

    async def create_playlist(self, json_file: str, playlist_name: str = None) -> str:
        """Create a Spotify playlist from a JSON file of tracks"""
        self.logger.info(f"Creating playlist from {json_file}")
        
        try:
            # Load items from JSON
            handler = FileHandler(json_file)
            items = await handler.load()
            
            if not items:
                raise ValueError("No items found in JSON file")
            
            # Generate playlist name if not provided
            if not playlist_name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                playlist_name = f"SpotScrape Playlist {timestamp}"
            
            # Create playlist
            spotify = await self._get_spotify()
            user_id = spotify.current_user()['id']
            playlist = spotify.user_playlist_create(
                user_id,
                playlist_name,
                public=False,
                description="Created by SpotScrape"
            )
            
            # Add tracks to playlist
            track_uris = []
            for item in items:
                try:
                    if 'spotify_url' in item:
                        if 'track' in item['spotify_url']:
                            track_uris.append(item['spotify_url'])
                        elif 'album' in item['spotify_url']:
                            album_tracks = spotify.album_tracks(item['spotify_url'])
                            track_uris.extend([track['uri'] for track in album_tracks['items']])
                except Exception as e:
                    self.logger.warning(f"Error processing item {item}: {str(e)}")
            
            if track_uris:
                # Add tracks in batches of 100 (Spotify API limit)
                for i in range(0, len(track_uris), 100):
                    batch = track_uris[i:i + 100]
                    spotify.playlist_add_items(playlist['id'], batch)
                
                self.logger.info(f"Created playlist '{playlist_name}' with {len(track_uris)} tracks")
                return playlist['id']
            else:
                raise ValueError("No valid tracks found in items")
            
        except Exception as e:
            self.logger.error(f"Error creating playlist: {str(e)}")
            raise

async def main():
    """Main application entry point with improved resource management"""
    scraper = None
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

        # Initialize SpotScraper with context management
        async with SpotScraper() as scraper:
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
                    
                    destination_file = scraper._get_default_data_path('url')
                    user_message(f"\nScanning {url} for Spotify links...")
                    await scraper.scan_spotify_links(url, destination_file)
                    user_message(f"Scan complete! Results saved to {destination_file}")

                elif choice == "2":
                    url = input("\nEnter URL to scan: ").strip()
                    if not url:
                        user_message("No URL provided")
                        continue
                    
                    destination_file = scraper._get_default_data_path('gpt')
                    user_message(f"\nScanning {url}...")
                    await scraper.scan_webpage(url, destination_file)
                    user_message(f"Scan complete! Results saved to {destination_file}")

                elif choice == "3":
                    user_message("\nSelect the JSON file to use:")
                    user_message("1. URL scan results (musicdata_url.json)")
                    user_message("2. GPT scan results (musicdata_gpt.json)")
                    
                    file_choice = input("Choose (1-2): ").strip()
                    
                    if file_choice == "1":
                        json_file = scraper._get_default_data_path('url')
                    elif file_choice == "2":
                        json_file = scraper._get_default_data_path('gpt')
                    else:
                        user_message("Invalid choice")
                        continue

                    if not os.path.exists(json_file):
                        user_message(f"File not found: {json_file}")
                        continue

                    # Load JSON file
                    with open(json_file) as f:
                        tracks = json.load(f)

                    playlist_name = input("\nEnter playlist name (or press Enter for default): ").strip()
                    await scraper.create_playlist(json_file, playlist_name)
                    user_message("Playlist created successfully!")

                elif choice == "4":
                    user_message("\nGoodbye!")
                    break

                else:
                    user_message("Invalid choice. Please enter 1-4.")

    except KeyboardInterrupt:
        user_message("\nOperation cancelled by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        user_message("An unexpected error occurred. Check the logs for details.")
    finally:
        if scraper:
            await scraper.cleanup()
        try:
            await ClientManager.cleanup()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    try:
        # Set up logging first
        log_file = setup_logging()
        user_message(f"Logging to file: {log_file}")
        
        # Load environment variables
        load_dotenv()
        
        # Run the application
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        # Ensure all resources are cleaned up
        try:
            asyncio.run(ClientManager.cleanup())
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        