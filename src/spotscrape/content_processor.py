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
    """Processes content for GPT analysis"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    @staticmethod
    def split_content(content: str, max_chunk_size: int = 4000) -> List[str]:
        """Split content into chunks for GPT processing."""
        # Split content into paragraphs
        paragraphs = content.split('\n\n')
        chunks = []
        current_chunk = []
        current_size = 0
        
        for paragraph in paragraphs:
            paragraph_size = len(paragraph)
            
            if current_size + paragraph_size > max_chunk_size and current_chunk:
                # Join current chunk and add to chunks
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = []
                current_size = 0
            
            current_chunk.append(paragraph)
            current_size += paragraph_size
        
        # Add remaining chunk if any
        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))
        
        return chunks
        
    async def process_content(self, content: str) -> List[Dict]:
        """Process content with GPT."""
        try:
            # Split content into manageable chunks
            chunks = self.split_content(content)
            
            # Process each chunk
            results = []
            for chunk in chunks:
                # Process chunk with GPT
                chunk_result = await process_with_gpt(chunk)
                if chunk_result:
                    results.extend(chunk_result)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error processing content: {str(e)}", exc_info=True)
            raise 