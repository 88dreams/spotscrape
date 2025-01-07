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

# Suppress specific warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
urllib3.disable_warnings(urllib3.exceptions.HTTPWarning)
warnings.filterwarnings("ignore", message=".*Content-Length and Transfer-Encoding.*", 
                       category=UserWarning, module='urllib3')

# Global cache configurations
CACHE_TTL = 3600  # 1 hour cache lifetime
request_cache = TTLCache(maxsize=100, ttl=CACHE_TTL)
spotify_cache = TTLCache(maxsize=1000, ttl=CACHE_TTL)

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
            if cls._openai_instance is None:
                cls._openai_instance = AsyncOpenAI(
                    api_key=os.getenv('OPENAI_API_KEY'),
                    timeout=30.0,
                    max_retries=3,
                    _strict_response_validation=False
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

    @RateLimiter(max_calls=100, time_period=60)
    async def add_tracks(self, playlist_id: str, track_uris: List[str]) -> None:
        """Add tracks to playlist with batching and rate limiting"""
        if not track_uris:
            return

        try:
            spotify = await self._get_spotify()
            
            for i in range(0, len(track_uris), self.batch_size):
                batch = track_uris[i:i + self.batch_size]
                async with self._lock:
                    spotify.playlist_add_items(playlist_id, batch)
                await asyncio.sleep(0.1)  # Prevent rate limiting
                logger.debug(f"Added batch of {len(batch)} tracks to playlist {playlist_id}")
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

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    simple_formatter = logging.Formatter('%(message)s')
    
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
        
        # Set up console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(simple_formatter)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        # Get module loggers
        logger = logging.getLogger(__name__)
        spotify_logger = logging.getLogger('spotify')
        
        print(f"Logging to file: {log_file}")  # Inform user before logger is set up
        # user_message(f"Logging to file: {log_file}")  # Use this after logger is set up
        
        return logger, spotify_logger
        
    except Exception as e:
        print(f"Error setting up logging: {str(e)}")
        raise

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

async def process_with_gpt(content: str) -> str:
    """Process content with GPT with improved content filtering and prompting"""
    try:
        # Clean the content first
        cleaned_content = clean_html_content(content)
        logger.debug(f"Cleaned content sample: {cleaned_content[:500]}")
        
        openai_client = await ClientManager.get_openai()
        chunks = textwrap.wrap(cleaned_content, 4000, break_long_words=False, break_on_hyphens=False)
        all_results = []
        
        system_prompt = """You are a precise music information extractor. Your task is to identify and extract ONLY artist and album pairs from the provided text.

        Rules:
        1. Extract ONLY complete artist-album pairs
        2. Maintain exact original spelling and capitalization
        3. Include full albums only (no singles or EPs unless explicitly labeled as albums)
        4. Ignore any non-music content, advertisements, or navigation elements
        5. Do not include track listings or song names
        6. Do not include commentary, reviews, or ratings
        7. If an artist has multiple albums mentioned, list each pair separately

        Format each pair exactly as: 'Artist - Album'
        One pair per line
        No additional text or commentary

        Example output:
        The Beatles - Abbey Road
        Pink Floyd - The Dark Side of the Moon"""
        
        for i, chunk in enumerate(chunks, 1):
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract artist-album pairs from this text. Ignore any non-music content:\n\n{chunk}"}
                ]
                
                response = await openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000
                )
                
                result = response.choices[0].message.content.strip()
                if result:
                    # Additional filtering of results
                    valid_pairs = []
                    for line in result.split('\n'):
                        line = line.strip()
                        if ' - ' in line and not any(x in line.lower() for x in ['ep', 'single', 'remix', 'feat.']):
                            valid_pairs.append(line)
                    all_results.extend(valid_pairs)
                
            except Exception as e:
                logger.error(f"Error processing chunk {i}: {e}")
                continue
        
        # Remove duplicates while preserving order
        seen = set()
        final_results = [item for item in all_results if item and item not in seen and not seen.add(item)]
        
        return '\n'.join(final_results)
        
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
                        user_message(f"Found: {artist.strip()} - {album.strip()}")
                        
                except ValueError as e:
                    logger.warning(f"Error processing line '{line}': {e}")
                    continue
            
            # Review and save results if we have new entries
            if new_entries:
                await review_and_save_results(new_entries, destination_file)
            else:
                user_message("No entries found to save")
                
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

async def review_and_save_results(entries: List[Dict], destination_file: str) -> List[Dict]:
    """Review and optionally modify the scan results before saving"""
    if not entries:
        user_message("No entries found to review")
        return []

    while True:
        user_message("\nFound the following Artist - Album combinations:")
        for i, entry in enumerate(entries, 1):
            user_message(f"{i}. {entry['Artist']} - {entry['Album']}")

        user_message("\nWhat would you like to do?")
        user_message("1. Save all entries")
        user_message("2. Delete specific albums")
        user_message("3. Back to Main Menu")
        
        choice = input("\nEnter your choice (1-3): ").strip()

        if choice == "1":
            # Save all entries
            file_handler = FileHandler(destination_file)
            await file_handler.save(entries)
            user_message(f"\nSaved {len(entries)} entries to {destination_file}")
            
            # Ask about creating playlist
            user_message("\nWould you like to create a Spotify playlist with these entries now?")
            user_message("1. Yes")
            user_message("2. No")
            
            playlist_choice = input("\nEnter your choice (1-2): ").strip()
            if playlist_choice == "1":
                playlist_name = input("\nEnter playlist name (or press Enter for default): ").strip()
                await create_playlist(destination_file, playlist_name)
            
            return entries

        elif choice == "2":
            # Delete specific albums
            while True:
                user_message("\nEnter the numbers of albums to delete (comma-separated, or 0 to finish):")
                for i, entry in enumerate(entries, 1):
                    user_message(f"{i}. {entry['Artist']} - {entry['Album']}")
                
                try:
                    delete_input = input("\nEnter numbers (0 to finish): ").strip()
                    if delete_input == "0":
                        break
                    
                    # Parse comma-separated numbers
                    delete_nums = [int(num.strip()) for num in delete_input.split(",")]
                    # Sort in reverse order to avoid index shifting when deleting
                    delete_nums.sort(reverse=True)
                    
                    deleted_count = 0
                    for delete_num in delete_nums:
                        if 1 <= delete_num <= len(entries):
                            deleted = entries.pop(delete_num - 1)
                            user_message(f"Deleted: {deleted['Artist']} - {deleted['Album']}")
                            deleted_count += 1
                        else:
                            user_message(f"Invalid number: {delete_num}")
                    
                    if deleted_count > 0:
                        user_message(f"\nDeleted {deleted_count} entries")
                    
                except ValueError:
                    user_message("Please enter valid numbers separated by commas")
                
                if not entries:
                    user_message("No entries left to review")
                    return []

        elif choice == "3":
            # Back to main menu without saving
            return []

        else:
            user_message("Invalid choice. Please enter 1-3.")

async def scan_spotify_links(url: str, destination_file: str) -> None:
    """Scan webpage for Spotify links and add artist and album data to JSON"""
    extractor = WebContentExtractor()
    try:
        # Initialize file handler
        file_handler = FileHandler(destination_file)

        # Extract content
        content = await extractor.extract_content(url)
        
        # Log a sample of the content for debugging
        content_sample = content[:1000]
        logger.debug(f"Content sample: {content_sample}")
        
        # Enhanced regex pattern to capture various Spotify album link formats
        spotify_patterns = [
            r'spotify:album:([a-zA-Z0-9]{22})',  # URI format
            r'open\.spotify\.com/album/([a-zA-Z0-9]{22})',  # Web URL format
            r'spotify\.com/album/([a-zA-Z0-9]{22})',  # Alternative web URL format
            r'href="[^"]*?/album/([a-zA-Z0-9]{22})',  # href attribute format
            r'data-uri="spotify:album:([a-zA-Z0-9]{22})',  # data-uri attribute format
            r'/album/([a-zA-Z0-9]{22})',  # Simple album ID format
        ]
        
        # Collect all unique album IDs
        album_ids = set()
        for pattern in spotify_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                # Extract the album ID from the capturing group
                album_id = match.group(1)
                if album_id and len(album_id) == 22:  # Spotify IDs are 22 characters
                    album_ids.add(album_id)
                    logger.debug(f"Found album ID: {album_id} using pattern: {pattern}")

        user_message(f"Found {len(album_ids)} unique Spotify album links")
        if not album_ids:
            logger.warning("No Spotify album links found in the content")
            return

        new_entries = []
        spotify = await ClientManager.get_spotify()

        # Process each album ID
        for album_id in album_ids:
            try:
                # Get album info
                album_info = spotify.album(album_id)
                artist = album_info['artists'][0]['name']
                album = album_info['name']
                album_popularity = album_info.get('popularity', 0)

                # Get track info
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

                new_entry = {
                    "Artist": artist,
                    "Album": album,
                    "Album Popularity": album_popularity,
                    "Tracks": tracks,
                    "Spotify Link": f"spotify:album:{album_id}",
                    "Extraction Date": datetime.now().isoformat()
                }

                new_entries.append(new_entry)
                user_message(f"Found: {artist} - {album} (Popularity: {album_popularity})")

            except Exception as e:
                logger.warning(f"Error processing album ID {album_id}: {e}")
                continue

        if new_entries:
            await file_handler.save(new_entries)
            user_message(f"Saved {len(new_entries)} entries to {destination_file}")
        else:
            user_message("No entries found to save")

    except Exception as e:
        logger.error(f"Error scanning Spotify links from {url}: {e}")
        raise
    finally:
        # Ensure Playwright resources are cleaned up
        await extractor.cleanup()

async def scan_webpage(url: str, destination_file: str):
    """Scan webpage and process content"""
    async with ContentProcessor() as processor:
        await processor.process_url(url, destination_file)

async def create_playlist(json_file: str, playlist_name: str = None):
    """Create a Spotify playlist from JSON file"""
    if not playlist_name:
        playlist_name = f"SpotScraper Playlist {datetime.now().strftime('%Y-%m-%d')}"

    playlist_manager = PlaylistManager()
    file_handler = FileHandler(json_file)
    
    try:
        data = await file_handler.load()
        if not data:
            user_message("No data found in JSON file")
            return

        playlist_description = input("\nEnter playlist description (or press Enter for default): ").strip()

        playlist_id = await playlist_manager.create_playlist(
            name=playlist_name,
            description=playlist_description or f"{playlist_name} - Created on {datetime.now().strftime('%Y-%m-%d')}"
        )

        track_uris = []
        spotify = await ClientManager.get_spotify()
        
        for entry in data:
            if spotify_link := entry.get('Spotify Link'):
                if 'spotify:album:' in spotify_link:
                    album_id = spotify_link.split(':')[-1]
                    album_tracks = spotify.album_tracks(album_id)
                    track_uris.extend(track['uri'] for track in album_tracks['items'])

        track_uris = list(set(track_uris))

        if track_uris:
            await playlist_manager.add_tracks(playlist_id, track_uris)
            user_message(f"Created playlist '{playlist_name}' with {len(track_uris)} tracks")
        else:
            user_message("No tracks found to add to playlist")

    except Exception as e:
        logger.error(f"Error creating playlist: {e}")
        raise

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
                
                file_choice = input("Choose (1-2): ").strip()
                
                if file_choice == "2":
                    destination_file = input("Enter full path for JSON file: ").strip()
                    destination_file = os.path.normpath(os.path.expanduser(destination_file))
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
                
                file_choice = input("Choose (1-2): ").strip()
                
                if file_choice == "2":
                    destination_file = input("Enter full path for JSON file: ").strip()
                    destination_file = os.path.normpath(os.path.expanduser(destination_file))
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
                
                file_choice = input("Choose (1-3): ").strip()
                
                if file_choice == "1":
                    json_file = url_default
                elif file_choice == "2":
                    json_file = gpt_default
                else:
                    json_file = input("Enter full path to JSON file: ").strip()
                    json_file = os.path.normpath(os.path.expanduser(json_file))

                if not os.path.exists(json_file):
                    user_message(f"File not found: {json_file}")
                    continue

                playlist_name = input("\nEnter playlist name (or press Enter for default): ").strip()
                await create_playlist(json_file, playlist_name)

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
        try:
            await ClientManager.cleanup()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

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
            
        # Run the application
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"\nFatal error: {e}")
        sys.exit(1)
    finally:
        # Ensure all resources are cleaned up
        try:
            asyncio.run(ClientManager.cleanup())
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        