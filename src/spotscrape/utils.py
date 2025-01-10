"""
Utility functions for logging and messaging
"""
import logging
import os
import sys
from typing import Tuple
from datetime import datetime

def get_app_root():
    """Get the application root directory for both executable and development."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))

def setup_logging() -> Tuple[logging.Logger, logging.Logger]:
    """Set up logging for the application."""
    # Create logfiles directory if it doesn't exist
    log_dir = os.path.join(get_app_root(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Set up main logger
    logger = logging.getLogger('spot-main')
    logger.setLevel(logging.INFO)
    
    # Set up Spotify logger
    spotify_logger = logging.getLogger('spot-spotify')
    spotify_logger.setLevel(logging.INFO)
    
    # Create handlers with date in filename
    main_handler = logging.FileHandler(
        os.path.join(log_dir, f"spot-main-{datetime.now().strftime('%Y%m%d')}.log"),
        encoding='utf-8'
    )
    spotify_handler = logging.FileHandler(
        os.path.join(log_dir, f"spot-spotify-{datetime.now().strftime('%Y%m%d')}.log"),
        encoding='utf-8'
    )
    
    # Create console handler for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    
    # Set formatters
    main_handler.setFormatter(formatter)
    spotify_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(main_handler)
    logger.addHandler(console_handler)
    spotify_logger.addHandler(spotify_handler)
    spotify_logger.addHandler(console_handler)
    
    # Log startup message
    logger.info(f"Logging initialized. Log directory: {log_dir}")
    spotify_logger.info(f"Spotify logging initialized. Log directory: {log_dir}")
    
    return logger, spotify_logger

def user_message(msg: str, log_only: bool = False) -> None:
    """Log a message and optionally display it to the user."""
    logger = logging.getLogger('spot-main')
    logger.info(msg)
    if not log_only:
        print(msg) 