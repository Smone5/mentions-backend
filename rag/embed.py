"""
OpenAI embeddings for RAG.
"""
from openai import OpenAI
from core.config import settings
import logging

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    """Get OpenAI client for embeddings."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def get_embedding(text: str) -> list[float]:
    """
    Get embedding vector from OpenAI.
    
    Args:
        text: Text to embed
        
    Returns:
        Embedding vector (1536 dimensions for text-embedding-3-small)
    """
    client = get_openai_client()
    
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        
        embedding = response.data[0].embedding
        logger.info("embedding_generated", text_length=len(text))
        return embedding
        
    except Exception as e:
        logger.error("embedding_failed", error=str(e))
        raise Exception(f"Embedding generation failed: {e}")

