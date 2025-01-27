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

def setup_logging() -> Tuple[logging.Logger, logging.Logger]:
    """Set up logging for the application."""
    # Get log directory
    log_dir = get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    
    # Set up main logger
    logger = logging.getLogger('spot-main')
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Prevent propagation to root logger
    
    # Set up Spotify logger
    spotify_logger = logging.getLogger('spot-spotify')
    spotify_logger.setLevel(logging.INFO)
    spotify_logger.propagate = False  # Prevent propagation to root logger
    
    # Create handlers with date in filename
    main_handler = logging.FileHandler(
        os.path.join(log_dir, f"spot-main-{datetime.now().strftime('%Y%m%d')}.log"),
        encoding='utf-8'
    )
    spotify_handler = logging.FileHandler(
        os.path.join(log_dir, f"spot-spotify-{datetime.now().strftime('%Y%m%d')}.log"),
        encoding='utf-8'
    )
    
    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    
    # Set formatters
    main_handler.setFormatter(formatter)
    spotify_handler.setFormatter(formatter)
    
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    for handler in spotify_logger.handlers[:]:
        spotify_logger.removeHandler(handler)
    
    # Add handlers
    logger.addHandler(main_handler)
    spotify_logger.addHandler(spotify_handler)
    
    # Log initialization silently (only to file)
    logger.info(f"Logging initialized. Log directory: {log_dir}")
    spotify_logger.info(f"Spotify logging initialized. Log directory: {log_dir}")
    
    return logger, spotify_logger

def user_message(msg: str, log_only: bool = False) -> None:
    """Log a message and optionally display it to the user."""
    logger = logging.getLogger('spot-main')
    logger.info(msg)
    if not log_only:
        print(msg) 