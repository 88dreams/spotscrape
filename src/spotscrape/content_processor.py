"""
Content processing and analysis functionality
"""
import logging
import openai
from typing import List, Dict, Any, Optional
import json
import os
import asyncio

class ContentProcessor:
    def __init__(self):
        self.logger = logging.getLogger('spot-debug')
        self.chunk_size = 4000  # Maximum size for each chunk
        self.client = None
        
    def _init_client(self):
        """Initialize the OpenAI client if not already initialized."""
        if not self.client:
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError("OpenAI API key not found")
            self.client = openai.OpenAI(api_key=api_key)
        
    def split_content(self, content: str) -> List[str]:
        """Split content into manageable chunks for GPT processing.
        
        Args:
            content (str): The content to split into chunks
            
        Returns:
            List[str]: List of content chunks
        """
        try:
            if not content:
                self.logger.warning("Empty content provided for splitting")
                return []
            
            # Clean the content first (remove extra whitespace)
            cleaned_content = ' '.join(content.split())
            
            # Split content into chunks
            chunks = []
            current_chunk = []
            current_length = 0
            
            for paragraph in cleaned_content.split('\n'):
                # Skip empty paragraphs
                if not paragraph.strip():
                    continue
                    
                # If adding this paragraph would exceed chunk size, save current chunk
                if current_length + len(paragraph) > self.chunk_size:
                    if current_chunk:
                        chunks.append(' '.join(current_chunk))
                        current_chunk = []
                        current_length = 0
                
                current_chunk.append(paragraph)
                current_length += len(paragraph) + 1  # +1 for space
            
            # Add the last chunk if it exists
            if current_chunk:
                chunks.append(' '.join(current_chunk))
            
            self.logger.debug(f"Split content into {len(chunks)} chunks")
            return chunks
            
        except Exception as e:
            self.logger.error(f"Error splitting content: {str(e)}")
            return []

    async def process_chunk(self, chunk: str) -> List[Dict[str, str]]:
        """Process a single chunk of content with GPT.
        
        Args:
            chunk (str): The content chunk to process
            
        Returns:
            List[Dict[str, str]]: List of artist-album pairs
        """
        try:
            # Initialize OpenAI client
            self._init_client()
            
            # Create the prompt
            prompt = f"""
            Analyze the following text and identify any music albums mentioned.
            For each album, extract ONLY the artist name and album name.
            
            Rules:
            1. Extract ONLY complete artist-album pairs
            2. Maintain exact original spelling and capitalization
            3. Include full albums only (no singles or EPs unless explicitly labeled as albums)
            4. Ignore any non-music content
            5. Do not include track listings or song names
            
            Text to analyze:
            {chunk}
            
            Respond in JSON format with an array of objects, each containing:
            - artist: The artist name
            - album: The album name
            """
            
            # Call OpenAI API with new format
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a music expert helping to identify albums mentioned in text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            # Parse the response
            if response.choices and response.choices[0].message:
                try:
                    result = json.loads(response.choices[0].message.content)
                    if isinstance(result, list):
                        return result
                    self.logger.warning("GPT response was not a list")
                    return []
                except json.JSONDecodeError:
                    self.logger.error("Failed to parse OpenAI response as JSON")
                    return []
            
            return []
            
        except Exception as e:
            self.logger.error(f"Error processing chunk: {str(e)}")
            return [] 