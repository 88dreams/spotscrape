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
    
    # Delete the existing log file if it exists
    if os.path.exists(log_file):
        os.remove(log_file)

    # Create formatter
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    
    try:
        # Set up file handler
        file_handler = RotatingFileHandler(
            log_file,
            mode='w',  # Open the file in write mode to overwrite
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        
        # Configure module logger only
        logger.handlers.clear()
        logger.addHandler(file_handler)
        logger.setLevel(logging.DEBUG)
        
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
    """Main class for handling webpage scanning and playlist creation"""
    def __init__(self, logger=None):
        # Initialize logger
        self.logger = logger or logging.getLogger(__name__)
        self.playlist_manager = PlaylistManager()
        self.search_manager = SpotifySearchManager()
        self.file_handler = None
        self._browser = None
        self._playwright = None
        self._browser_lock = AsyncLock()
        self._resource_manager = ResourceManager()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()

    async def cleanup(self):
        """Clean up all resources"""
        await self._resource_manager.cleanup()
        await self._cleanup_browser()

    async def _cleanup_browser(self):
        """Clean up browser resources"""
        async with self._browser_lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

    async def _get_browser(self):
        """Get or create browser instance with resource management"""
        async with self._browser_lock:
            if not self._browser:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-gpu',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-setuid-sandbox'
                    ]
                )
                await self._resource_manager.register(self._browser)
            return self._browser

    @retry_with_backoff(retries=3)
    async def _get_page_content(self, url: str) -> str:
        """Get page content with shared browser instance and retries"""
        browser = await self._get_browser()
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        try:
            page = await context.new_page()
            response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            if not response:
                raise Exception("Failed to get response from page")
            
            if response.status >= 400:
                raise Exception(f"HTTP error {response.status}: {response.status_text}")
            
            content = await page.content()
            
            if not content.strip():
                raise Exception("Received empty page content")
            
            return content
        except Exception as e:
            logger.error(f"Error fetching page content: {str(e)}")
            raise
        finally:
            await context.close()

    def _get_default_data_path(self, scan_type: str) -> str:
        """Get the default path for saving scan results"""
        # Create SpotScrape_data directory in script directory
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'SpotScrape_data')
        os.makedirs(data_dir, exist_ok=True)
        
        # Use standardized filenames based on scan type
        if scan_type == 'url':
            filename = 'musicdata_url.json'
        elif scan_type == 'gpt':
            filename = 'musicdata_gpt.json'
        else:
            raise ValueError(f"Invalid scan type: {scan_type}")
            
        return os.path.join(data_dir, filename)

    async def review_and_filter_items(self, items: List[Dict]) -> List[Dict]:
        """Allow user to review and filter items before saving"""
        if not items:
            user_message("No items found to review.")
            return []

        user_message("\nFound the following entries:")
        for idx, item in enumerate(items, 1):
            user_message(f"{idx}. Artist: {item['artist']} | Album: {item['album']}")

        while True:
            user_message("\nOptions:")
            user_message("1. Save all entries")
            user_message("2. Remove specific entries")
            user_message("3. Remove all entries")
            
            choice = input("\nEnter your choice (1-3): ").strip()
            
            if choice == "1":
                return items
            elif choice == "2":
                while True:
                    to_remove = input("\nEnter entry numbers to remove (comma-separated) or 'done' to finish: ").strip().lower()
                    if to_remove == 'done':
                        break
                    
                    try:
                        # Convert input to list of indices
                        indices = [int(x.strip()) for x in to_remove.split(',')]
                        # Validate indices
                        if any(idx < 1 or idx > len(items) for idx in indices):
                            user_message("Invalid entry number(s). Please try again.")
                            continue
                        
                        # Remove items in reverse order to maintain correct indices
                        for idx in sorted(indices, reverse=True):
                            removed = items.pop(idx - 1)
                            user_message(f"Removed: {removed['artist']} - {removed['album']}")
                        
                        # Show remaining entries
                        user_message("\nRemaining entries:")
                        for idx, item in enumerate(items, 1):
                            user_message(f"{idx}. Artist: {item['artist']} | Album: {item['album']}")
                        
                    except ValueError:
                        user_message("Invalid input. Please enter numbers separated by commas.")
                        continue
                return items
            elif choice == "3":
                confirm = input("Are you sure you want to remove all entries? (y/n): ").strip().lower()
                if confirm == 'y':
                    return []
            else:
                user_message("Invalid choice. Please enter 1-3.")

    async def prompt_create_playlist(self, items: List[Dict]) -> None:
        """Prompt user to create a playlist from confirmed items"""
        if not items:
            return
            
        user_message("\nWould you like to create a playlist from these entries? (y/n): ")
        choice = input().strip().lower()
        
        if choice == 'y':
            playlist_name = input("\nEnter playlist name (or press Enter for default): ").strip()
            await self.create_playlist(items, playlist_name)
            user_message("Playlist created successfully!")

    async def scan_spotify_links(self, url: str, destination_file: str = None) -> List[Dict]:
        """Scan webpage for Spotify links and extract metadata"""
        try:
            if destination_file is None:
                destination_file = self._get_default_data_path('url')
            
            self.file_handler = FileHandler(destination_file)
            self.logger.info(f"Scanning {url} for Spotify links...")
            
            content = await self._get_page_content(url)
            soup = BeautifulSoup(content, 'html.parser')
            spotify_links = []
            
            # Expanded pattern to match various Spotify URL formats
            spotify_patterns = [
                'spotify.com/track/',
                'spotify.com/album/',
                'spotify.com/artist/',
                'spotify:track:',
                'spotify:album:',
                'spotify:artist:'
            ]
            
            # Search in various locations and collect raw links
            raw_links = set()
            
            # Search in href attributes
            for link in soup.find_all('a'):
                href = link.get('href', '')
                if any(pattern in href for pattern in spotify_patterns):
                    raw_links.add(href)
            
            # Search in embedded iframes
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if any(pattern in src for pattern in spotify_patterns):
                    raw_links.add(src)
            
            # Search in data attributes
            for element in soup.find_all(attrs={'data-spotify-url': True}):
                spotify_url = element['data-spotify-url']
                if any(pattern in spotify_url for pattern in spotify_patterns):
                    raw_links.add(spotify_url)
            
            # Search in text content for Spotify URLs
            text_content = soup.get_text()
            url_pattern = r'https?://[^\s<>"]+?(?:{})[^\s<>"]*'.format('|'.join(spotify_patterns))
            matches = re.finditer(url_pattern, text_content, re.IGNORECASE)
            for match in matches:
                raw_links.add(match.group())
            
            # Process each unique link to get metadata
            spotify = await ClientManager.get_spotify()
            timestamp = datetime.now().isoformat()
            
            for spotify_url in raw_links:
                try:
                    # Extract Spotify ID and type from URL
                    if 'spotify:' in spotify_url:
                        # Handle Spotify URI format
                        parts = spotify_url.split(':')
                        item_type = parts[-2]
                        item_id = parts[-1]
                    else:
                        # Handle HTTP URL format
                        parts = spotify_url.rstrip('/').split('/')
                        item_type = parts[-2]
                        item_id = parts[-1].split('?')[0]
                    
                    # Get metadata based on type
                    if item_type == 'track':
                        track = spotify.track(item_id)
                        spotify_links.append({
                            'artist': track['artists'][0]['name'],
                            'album': track['album']['name'],
                            'spotify_url': spotify_url,
                            'source_url': url,
                            'timestamp': timestamp
                        })
                    elif item_type == 'album':
                        album = spotify.album(item_id)
                        spotify_links.append({
                            'artist': album['artists'][0]['name'],
                            'album': album['name'],
                            'spotify_url': spotify_url,
                            'source_url': url,
                            'timestamp': timestamp
                        })
                    # Skip artist links as they don't have album info
                    
                except Exception as e:
                    self.logger.warning(f"Error processing Spotify URL {spotify_url}: {e}")
                    continue
            
            # Remove duplicates while preserving order
            seen = set()
            unique_links = []
            for link in spotify_links:
                key = f"{link['artist']} - {link['album']} - {link['spotify_url']}"
                if key not in seen:
                    seen.add(key)
                    unique_links.append(link)
            
            # Add review step before saving
            user_message("\nReview found items before saving:")
            filtered_items = await self.review_and_filter_items(unique_links)
            
            if filtered_items:
                await self.file_handler.save(filtered_items)
                self.logger.info(f"Saved {len(filtered_items)} items to {destination_file}")
                # Prompt to create playlist after saving
                await self.prompt_create_playlist(filtered_items)
            else:
                self.logger.info("No items were saved (all filtered out)")
            
            return filtered_items
            
        except Exception as e:
            self.logger.error(f"Error scanning URL {url}: {e}")
            raise

    async def scan_webpage(self, url: str, destination_file: str = None) -> List[Dict]:
        """Scan webpage using GPT for music content"""
        try:
            if destination_file is None:
                destination_file = self._get_default_data_path('gpt')
            
            self.file_handler = FileHandler(destination_file)
            self.logger.info(f"Scanning {url} using GPT...")
            
            content = await self._get_page_content(url)
            extracted_items = await process_with_gpt(content)
            timestamp = datetime.now().isoformat()
            
            # Get Spotify client for searching
            spotify = await ClientManager.get_spotify()
            formatted_items = []
            
            for item in extracted_items:
                try:
                    # Search based on item type
                    if item['type'] == 'song':
                        query = f"artist:{item['artist']} track:{item['title']}"
                        results = spotify.search(q=query, type='track', limit=1)
                        
                        if results and results['tracks']['items']:
                            track = results['tracks']['items'][0]
                            formatted_items.append({
                                'artist': track['artists'][0]['name'],
                                'album': track['album']['name'],
                                'spotify_url': track['external_urls']['spotify'],
                                'source_url': url,
                                'timestamp': timestamp
                            })
                    elif item['type'] == 'album':
                        query = f"artist:{item['artist']} album:{item['title']}"
                        results = spotify.search(q=query, type='album', limit=1)
                        
                        if results and results['albums']['items']:
                            album = results['albums']['items'][0]
                            formatted_items.append({
                                'artist': album['artists'][0]['name'],
                                'album': album['name'],
                                'spotify_url': album['external_urls']['spotify'],
                                'source_url': url,
                                'timestamp': timestamp
                            })
                except Exception as e:
                    self.logger.warning(f"Error processing item {item}: {e}")
                    continue
            
            # Remove duplicates while preserving order
            seen = set()
            unique_items = []
            for item in formatted_items:
                key = f"{item['artist']} - {item['album']} - {item['spotify_url']}"
                if key not in seen:
                    seen.add(key)
                    unique_items.append(item)
            
            # Add review step before saving
            user_message("\nReview found items before saving:")
            filtered_items = await self.review_and_filter_items(unique_items)
            
            if filtered_items:
                await self.file_handler.save(filtered_items)
                self.logger.info(f"Saved {len(filtered_items)} items to {destination_file}")
                # Prompt to create playlist after saving
                await self.prompt_create_playlist(filtered_items)
            else:
                self.logger.info("No items were saved (all filtered out)")
            
            return filtered_items
            
        except Exception as e:
            self.logger.error(f"Error scanning URL {url}: {e}")
            raise

    async def create_playlist(self, tracks: List[Dict], name: str = None) -> str:
        """Create a Spotify playlist from the extracted tracks"""
        try:
            if not name:
                name = f"SpotScrape Playlist {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            self.logger.info(f"Creating playlist: {name}")
            playlist_id = await self.playlist_manager.create_playlist(name)
            
            # Process tracks in batches
            batch_size = 50
            track_uris = []
            
            for track in tracks:
                try:
                    spotify_url = track.get('spotify_url')
                    if not spotify_url:
                        continue
                        
                    # Extract the ID and type from the Spotify URL
                    parts = spotify_url.rstrip('/').split('/')
                    item_type = parts[-2]  # 'album' or 'track'
                    item_id = parts[-1].split('?')[0]
                    
                    if item_type == 'track':
                        # If it's already a track, add it directly
                        track_uris.append(f"spotify:track:{item_id}")
                    elif item_type == 'album':
                        # If it's an album, get all its tracks
                        spotify = await ClientManager.get_spotify()
                        album_tracks = spotify.album_tracks(item_id)
                        track_uris.extend([
                            f"spotify:track:{t['id']}" 
                            for t in album_tracks['items']
                        ])
                except Exception as e:
                    self.logger.warning(f"Error processing track {track.get('artist')} - {track.get('album')}: {e}")
                    continue
            
            if track_uris:
                # Add tracks to playlist in batches
                for i in range(0, len(track_uris), batch_size):
                    batch = track_uris[i:i + batch_size]
                    await self.playlist_manager.add_tracks(playlist_id, batch)
                    self.logger.info(f"Added {min(i + batch_size, len(track_uris))}/{len(track_uris)} tracks to playlist")
            else:
                self.logger.warning("No valid tracks found to add to playlist")
            
            return playlist_id
        except Exception as e:
            self.logger.error(f"Error creating playlist: {e}")
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
                    await scraper.create_playlist(tracks, playlist_name)
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
        