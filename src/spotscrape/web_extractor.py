"""
Web content extraction functionality
"""
import aiohttp
import logging
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from aiohttp import ClientError, ClientTimeout

class WebContentExtractor:
    def __init__(self):
        self.logger = logging.getLogger('spot-debug')
        self.timeout = ClientTimeout(total=30)  # 30 second timeout
    
    async def extract_content(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract text content and links from a webpage.
        Returns a tuple of (content, error_message)
        """
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        
                        # Extract all links first
                        links = []
                        for a in soup.find_all('a', href=True):
                            links.append(a['href'])
                        
                        # Remove script and style elements
                        for script in soup(["script", "style"]):
                            script.decompose()
                            
                        # Get text content
                        text = soup.get_text()
                        
                        # Clean up whitespace
                        lines = (line.strip() for line in text.splitlines())
                        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                        text = ' '.join(chunk for chunk in chunks if chunk)
                        
                        # Combine text and links
                        full_content = text + "\n" + "\n".join(links)
                        self.logger.debug(f"Extracted {len(links)} links from page")
                        return full_content, None
                    else:
                        error_msg = f"HTTP {response.status}: {response.reason}"
                        self.logger.error(f"Failed to fetch URL: {error_msg}")
                        return None, error_msg
        except aiohttp.ClientConnectorError as e:
            error_msg = f"Connection error: Could not connect to {url}"
            self.logger.error(error_msg)
            return None, error_msg
        except aiohttp.InvalidURL:
            error_msg = f"Invalid URL: {url}"
            self.logger.error(error_msg)
            return None, error_msg
        except aiohttp.ClientTimeout:
            error_msg = "Request timed out"
            self.logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Error extracting content: {str(e)}"
            self.logger.error(error_msg)
            return None, error_msg 