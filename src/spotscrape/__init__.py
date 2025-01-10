"""
SpotScrape - A tool for scraping music information and creating Spotify playlists
"""

__version__ = "1.0.0"
__author__ = "88dreams"

from .spotify_manager import SpotifySearchManager, PlaylistManager
from .web_extractor import WebContentExtractor
from .content_processor import ContentProcessor
from .utils import setup_logging, user_message
from .core import scan_spotify_links, scan_webpage, create_playlist

__all__ = [
    'SpotifySearchManager',
    'PlaylistManager',
    'WebContentExtractor',
    'ContentProcessor',
    'setup_logging',
    'user_message',
    'scan_spotify_links',
    'scan_webpage',
    'create_playlist'
] 