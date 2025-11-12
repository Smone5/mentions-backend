"""Document chunking utilities."""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> List[str]:
    """
    Split text into overlapping chunks.
    
    Args:
        text: Text to chunk
        chunk_size: Target size of each chunk in characters
        chunk_overlap: Number of characters to overlap between chunks
        
    Returns:
        List of text chunks
    """
    if not text or len(text) == 0:
        return []
    
    chunks = []
    start = 0
    
    while start < len(text):
        # Calculate end of chunk
        end = start + chunk_size
        
        # If not at the end, try to break at sentence boundary
        if end < len(text):
            # Look for sentence endings (., !, ?)
            for i in range(end, max(start, end - 100), -1):
                if text[i] in '.!?':
                    end = i + 1
                    break
        
        chunk = text[start:end].strip()
        
        if chunk:
            chunks.append(chunk)
        
        # Move start position with overlap
        start = end - chunk_overlap
        
        # Safety check to prevent infinite loop
        if start <= 0 and len(chunks) > 0:
            break
    
    logger.info(f"Split {len(text)} chars into {len(chunks)} chunks")
    
    return chunks


def chunk_document(
    content: str,
    metadata: Dict[str, Any],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> List[Dict[str, Any]]:
    """
    Chunk a document and attach metadata to each chunk.
    
    Args:
        content: Document content
        metadata: Metadata to attach to each chunk (title, url, etc.)
        chunk_size: Target size of each chunk
        chunk_overlap: Overlap between chunks
        
    Returns:
        List of chunk dictionaries with content and metadata
    """
    chunks = chunk_text(content, chunk_size, chunk_overlap)
    
    chunk_dicts = []
    for i, chunk in enumerate(chunks):
        chunk_dict = {
            "content": chunk,
            "chunk_index": i,
            "total_chunks": len(chunks),
            **metadata
        }
        chunk_dicts.append(chunk_dict)
    
    return chunk_dicts

