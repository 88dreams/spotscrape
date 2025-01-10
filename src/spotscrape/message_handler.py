"""
Message handling functionality for SpotScrape
"""
import logging
from datetime import datetime
from queue import Queue
import re

# Initialize logger
logger = logging.getLogger(__name__)

# Global queues for messages and progress updates
message_queue = Queue()
progress_queue = Queue()

def add_emoji_to_message(msg: str) -> str:
    """Add appropriate emoji based on message content."""
    # Error messages
    if any(term in msg.lower() for term in ['error', 'failed', 'not found', 'invalid']):
        return f"⚠️ {msg}"
    
    # Success messages
    if any(term in msg.lower() for term in ['success', 'completed', 'found', 'created', 'saved']):
        return f"✨ {msg}"
    
    # Processing messages
    if any(term in msg.lower() for term in ['processing', 'scanning', 'extracting', 'analyzing']):
        return f"🔄 {msg}"
    
    # Album related messages
    if any(term in msg.lower() for term in ['album', 'track', 'playlist']):
        return f"💿 {msg}"
    
    # URL/Web related messages
    if any(term in msg.lower() for term in ['url', 'http', 'web', 'link']):
        return f"🌐 {msg}"
    
    # GPT related messages
    if 'gpt' in msg.lower():
        return f"🤖 {msg}"
    
    # Default emoji for other messages
    return f"ℹ️ {msg}"

def gui_message(msg: str, log_only: bool = False):
    """Send message to GUI and log it.
    
    Args:
        msg (str): The message to send
        log_only (bool): If True, only log the message without sending to GUI
    """
    logger.info(f"GUI Message: {msg}")
    if not log_only:
        message_queue.put(add_emoji_to_message(msg))

def send_progress(progress: int, message: str):
    """Send progress update to frontend"""
    # Add emoji to progress message based on progress value
    if progress == 0:
        emoji = "🚀"  # Starting
    elif progress == 100:
        emoji = "✅"  # Complete
    elif "error" in message.lower():
        emoji = "⚠️"  # Error
    else:
        emoji = "🔄"  # In progress
    
    progress_queue.put({
        'progress': progress,
        'message': f"{emoji} {message}",
        'timestamp': datetime.now().isoformat()
    }) 