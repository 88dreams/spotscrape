import os
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from dotenv import load_dotenv

logger = logging.getLogger('spot-config')

class ConfigManager:
    """Manages application configuration and API keys"""
    
    _instance = None
    _config: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize configuration with proper precedence"""
        self._config = {}
        self._load_environment()
        
        # Development mode check
        self.dev_mode = os.getenv('SPOTSCRAPE_DEV', '0').lower() in ('1', 'true', 'yes')
        if self.dev_mode:
            logger.info("Running in development mode")
            self._load_dev_config()
        else:
            logger.info("Running in production mode")
            self._load_prod_config()
    
    def _load_environment(self):
        """Load environment variables with enhanced logging"""
        try:
            # First try user's home directory
            env_file = Path.home() / '.spotscrape' / '.env'
            logger.info(f"Checking for .env file in home directory: {env_file}")
            if env_file.exists():
                logger.info(f"Loading .env from home directory: {env_file}")
                load_dotenv(env_file)
                return

            # Then try current directory
            current_env = Path('.env')
            logger.info(f"Checking for .env file in current directory: {current_env.absolute()}")
            if current_env.exists():
                logger.info(f"Loading .env from current directory: {current_env.absolute()}")
                load_dotenv(current_env)
                return

            # Finally try parent directories
            logger.info("No .env file found in home or current directory, checking parent directories")
            load_dotenv()

            # Verify required variables are loaded
            required_vars = ['SPOTIPY_CLIENT_ID', 'SPOTIPY_CLIENT_SECRET', 'OPENAI_API_KEY']
            missing_vars = [var for var in required_vars if not os.getenv(var)]
            if missing_vars:
                logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
                raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        except Exception as e:
            logger.error(f"Error loading environment variables: {str(e)}")
            raise
    
    def _load_dev_config(self):
        """Load development configuration"""
        # In dev mode, we prioritize environment variables
        self._config.update({
            'spotify': {
                'client_id': os.getenv('SPOTIPY_CLIENT_ID'),
                'client_secret': os.getenv('SPOTIPY_CLIENT_SECRET'),
                'redirect_uri': os.getenv('SPOTIPY_REDIRECT_URI', 'http://localhost:8888/callback')
            },
            'openai': {
                'api_key': os.getenv('OPENAI_API_KEY')
            }
        })
    
    def _load_prod_config(self):
        """Load production configuration"""
        config_dir = self._get_config_dir()
        config_file = config_dir / 'config.json'
        
        if not config_file.exists():
            # Create default config in user's home directory
            self._create_default_config(config_dir)
        
        try:
            with open(config_file, 'r') as f:
                self._config = json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self._config = {}
    
    def _get_config_dir(self) -> Path:
        """Get the configuration directory"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            base_dir = Path(sys._MEIPASS)
        else:
            # Running as script
            base_dir = Path.home() / '.spotscrape'
        
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir
    
    def _create_default_config(self, config_dir: Path):
        """Create default configuration file"""
        config = {
            'spotify': {
                'client_id': '',
                'client_secret': '',
                'redirect_uri': 'http://localhost:8888/callback'
            },
            'openai': {
                'api_key': ''
            }
        }
        
        config_file = config_dir / 'config.json'
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
    
    def get_spotify_config(self) -> Dict[str, str]:
        """Get Spotify configuration"""
        return self._config.get('spotify', {})
    
    def get_openai_config(self) -> Dict[str, str]:
        """Get OpenAI configuration"""
        return self._config.get('openai', {})
    
    def is_configured(self) -> bool:
        """Check if all required configurations are set"""
        spotify_config = self.get_spotify_config()
        openai_config = self.get_openai_config()
        
        return all([
            spotify_config.get('client_id'),
            spotify_config.get('client_secret'),
            openai_config.get('api_key')
        ])
    
    def save_config(self, config: Dict[str, Any]):
        """Save configuration to file"""
        if self.dev_mode:
            logger.warning("Cannot save config in development mode")
            return
        
        config_dir = self._get_config_dir()
        config_file = config_dir / 'config.json'
        
        try:
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            self._config = config
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise 