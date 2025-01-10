"""
Message handling functionality for SpotScrape
"""
import logging
from datetime import datetime
from queue import Queue

# Initialize logger
logger = logging.getLogger(__name__)

# Global queues for messages and progress updates
message_queue = Queue()
progress_queue = Queue()

def gui_message(msg: str, log_only: bool = False):
    """Send message to GUI and log it.
    
    Args:
        msg (str): The message to send
        log_only (bool): If True, only log the message without sending to GUI
    """
    logger.info(f"GUI Message: {msg}")
    if not log_only:
        message_queue.put(msg)

def send_progress(progress: int, message: str):
    """Send progress update to frontend"""
    progress_queue.put({
        'progress': progress,
        'message': message,
        'timestamp': datetime.now().isoformat()
    }) 