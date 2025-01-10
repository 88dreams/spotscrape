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
    def __init__(self):
        self._progress_callback = None
        self.logger = logging.getLogger('spot-debug')
    
    def set_progress_callback(self, callback: Callable[[int, str], None]) -> None:
        self._progress_callback = callback
    
    async def scan_spotify_links(self, content: str) -> List[str]:
        """Extract Spotify album IDs from content."""
        album_pattern = r'https://open\.spotify\.com/album/([a-zA-Z0-9]+)'
        album_ids = list(set(re.findall(album_pattern, content)))
        return album_ids
    
    async def get_album_info(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album information from Spotify API."""
        try:
            sp = spotipy.Spotify(auth_manager=SpotifyOAuth())
            return sp.album(album_id)
        except Exception as e:
            self.logger.error(f"Error getting album info: {e}")
            return None

class PlaylistManager:
    def __init__(self):
        self.logger = logging.getLogger('spot-debug')
    
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