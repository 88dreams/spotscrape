"""
Spotify API interaction manager classes
"""
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import re
import logging
import asyncio
from typing import List, Dict, Optional, Any, Callable

class SpotifySearchManager:
    _spotify_instance = None
    _spotify_lock = asyncio.Lock()

    def __init__(self):
        self._progress_callback = None
        # Configure logger
        self.logger = logging.getLogger('spot-debug')
        self.logger.propagate = False
        # Disable spotipy logging
        spotipy_logger = logging.getLogger('spotipy')
        spotipy_logger.setLevel(logging.ERROR)
        spotipy_logger.propagate = False
        spotipy_logger.disabled = True
    
    def set_progress_callback(self, callback: Callable[[int, str], None]) -> None:
        self._progress_callback = callback
    
    async def get_spotify(self):
        """Get or create Spotify client instance."""
        async with self._spotify_lock:
            if not self._spotify_instance:
                self.logger.info("Initializing Spotify client")
                self._spotify_instance = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    scope="playlist-modify-public playlist-modify-private"
                ))
            return self._spotify_instance
    
    async def scan_spotify_links(self, content: str) -> List[str]:
        """Extract Spotify album IDs from content."""
        if not content:
            self.logger.warning("Empty content provided for scanning")
            return []

        # Clean the content first
        content = content.replace('\\/', '/').replace('&amp;', '&')
        
        # Comprehensive set of patterns to match various Spotify album URL formats
        patterns = [
            # Standard web URLs
            r'(?:https?://)?(?:www\.)?(?:open|play)\.spotify\.com/album/([a-zA-Z0-9]{22})(?:\?.*)?',
            # Spotify URIs
            r'spotify:album:([a-zA-Z0-9]{22})',
            # Basic URLs
            r'spotify\.com/album/([a-zA-Z0-9]{22})',
            # Relative URLs
            r'/album/([a-zA-Z0-9]{22})',
            # Embedded player URLs
            r'embed/album/([a-zA-Z0-9]{22})',
            # API URLs
            r'api\.spotify\.com/v1/albums/([a-zA-Z0-9]{22})'
        ]
        
        album_ids = set()
        for pattern in patterns:
            try:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    album_id = match.group(1)
                    if album_id and len(album_id) == 22:  # Validate ID length
                        album_ids.add(album_id)
                        self.logger.debug(f"Found album ID: {album_id} using pattern: {pattern}")
            except Exception as e:
                self.logger.error(f"Error matching pattern '{pattern}': {e}")
                continue
        
        # Log results
        if album_ids:
            self.logger.info(f"Found {len(album_ids)} unique album IDs: {', '.join(album_ids)}")
        else:
            self.logger.info("No album IDs found in content")
            # Log a sample of the content for debugging
            content_sample = content[:500] + '...' if len(content) > 500 else content
            self.logger.debug(f"Content sample: {content_sample}")
            
        return list(album_ids)
    
    async def get_album_info(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album information from Spotify API."""
        try:
            sp = await self.get_spotify()
            album_info = sp.album(album_id)
            if album_info:
                self.logger.info(f"Successfully retrieved info for album: {album_info.get('name', 'Unknown')}")
            return album_info
        except Exception as e:
            self.logger.error(f"Error getting album info for ID {album_id}: {e}")
            return None
    
    async def cleanup(self):
        """Clean up Spotify resources"""
        if self._spotify_instance:
            try:
                self._spotify_instance.close()
                self._spotify_instance = None
            except Exception as e:
                self.logger.error(f"Error closing Spotify instance: {e}")

class PlaylistManager:
    def __init__(self):
        self.logger = logging.getLogger('spot-debug')
        self._spotify_instance = None
        self._lock = asyncio.Lock()
    
    async def create_playlist(self, name: str, description: str = "") -> Optional[str]:
        """Create a Spotify playlist with the given name and description.
        
        Args:
            name (str): The name of the playlist
            description (str, optional): The description of the playlist
            
        Returns:
            Optional[str]: The playlist ID if successful, None otherwise
        """
        try:
            sp = spotipy.Spotify(auth_manager=SpotifyOAuth())
            user_id = sp.current_user()['id']
            
            playlist = sp.user_playlist_create(
                user=user_id,
                name=name,
                public=True,
                description=description
            )
            
            if not playlist or not isinstance(playlist, dict):
                raise ValueError("Failed to create playlist")
                
            playlist_id = playlist.get('id')
            if not playlist_id:
                raise ValueError("Failed to get playlist ID")
                
            return playlist_id
            
        except Exception as e:
            self.logger.error(f"Error creating playlist: {e}")
            return None
            
    async def add_tracks_to_playlist(self, playlist_id: str, track_ids: List[str]) -> bool:
        """Add tracks to a playlist.
        
        Args:
            playlist_id (str): The ID of the playlist
            track_ids (List[str]): List of track IDs to add
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not track_ids:
                return True
                
            sp = spotipy.Spotify(auth_manager=SpotifyOAuth())
            
            # Convert track IDs to URIs if needed
            track_uris = [
                f"spotify:track:{track_id}" if not track_id.startswith('spotify:') else track_id
                for track_id in track_ids
            ]
            
            # Add tracks in batches of 100 (Spotify's limit)
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i + 100]
                sp.playlist_add_items(playlist_id, batch)
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding tracks to playlist: {e}")
            return False 
    
    async def cleanup(self):
        """Clean up Spotify resources"""
        if self._spotify_instance:
            try:
                self._spotify_instance.close()
                self._spotify_instance = None
            except Exception as e:
                self.logger.error(f"Error closing Spotify instance: {e}") 