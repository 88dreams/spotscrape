"""
Web content extraction functionality
"""
import aiohttp
import logging
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from aiohttp import ClientError, ClientTimeout
from playwright.async_api import async_playwright, TimeoutError

class WebContentExtractor:
    def __init__(self):
        self.logger = logging.getLogger('spot-debug')
        self.browser = None
        self.playwright = None
    
    async def get_browser(self):
        """Initialize and return a browser instance."""
        if not self.browser:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
        return self.browser
    
    async def cleanup(self):
        """Clean up browser resources."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

    def user_message(self, message: str):
        """Log user messages."""
        self.logger.info(message)
    
    async def extract_content(self, url: str) -> str:
        """Extract content from a webpage."""
        try:
            browser = await self.get_browser()
            page = await browser.new_page()
            
            try:
                # Navigate to page and wait for content
                await page.goto(url)
                await page.wait_for_selector('body')
                
                # Get page content
                content = await page.content()
                
                if not content:
                    return ""
                
                # Parse content
                soup = BeautifulSoup(content, 'lxml')
                
                # Get all text and links
                text = soup.get_text()
                links = [a.get('href', '') for a in soup.find_all('a')]
                
                # Combine text and links
                full_content = text + "\n" + "\n".join(links)
                
                return full_content
                
            finally:
                await page.close()
                
        except Exception as e:
            self.logger.error(f"Error extracting content: {e}")
            return ""
            
        finally:
            await self.cleanup() 