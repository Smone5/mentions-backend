"""Embedding generation using OpenAI."""

import logging
from typing import List
from openai import OpenAI

from core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Client for generating text embeddings using OpenAI."""
    
    def __init__(self):
        """Initialize OpenAI client."""
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "text-embedding-3-small"  # Cost-effective embedding model
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for text.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            
            embedding = response.data[0].embedding
            
            logger.info(f"Generated embedding for {len(text)} chars, vector dim: {len(embedding)}")
            
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            raise
    
    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in a batch.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts
            )
            
            embeddings = [item.embedding for item in response.data]
            
            logger.info(f"Generated {len(embeddings)} embeddings in batch")
            
            return embeddings
            
        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {str(e)}")
            raise


# Global embedding client instance
_embedding_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """Get or create global embedding client instance."""
    global _embedding_client
    
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
        logger.info("Embedding client initialized")
    
    return _embedding_client

