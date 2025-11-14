"""Embedding generation using OpenAI."""

import logging
from typing import List
from openai import OpenAI
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Client for generating text embeddings using OpenAI."""
    
    def __init__(self):
        """Initialize OpenAI client with timeout settings."""
        # Create HTTP client with aggressive timeouts
        http_client = httpx.Client(
            timeout=httpx.Timeout(
                connect=5.0,    # 5 seconds to establish connection
                read=10.0,      # 10 seconds to read response (fail fast)
                write=5.0,      # 5 seconds to write request
                pool=5.0        # 5 seconds to get connection from pool
            )
        )
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            http_client=http_client
        )
        self.model = "text-embedding-3-small"  # Cost-effective embedding model
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ReadTimeout, Exception)),
        reraise=True
    )
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for text.
        Will retry up to 3 times with exponential backoff if it times out.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        try:
            logger.info(f"Generating embedding for {len(text)} chars...")
            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            
            embedding = response.data[0].embedding
            
            logger.info(f"✓ Generated embedding, vector dim: {len(embedding)}")
            
            return embedding
            
        except httpx.TimeoutException as e:
            logger.warning(f"⏱️  Embedding timeout after 10s - will retry: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to generate embedding: {str(e)}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ReadTimeout, Exception)),
        reraise=True
    )
    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in a batch.
        Will retry up to 3 times with exponential backoff if it times out.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        try:
            logger.info(f"Generating batch of {len(texts)} embeddings...")
            response = self.client.embeddings.create(
                model=self.model,
                input=texts
            )
            
            embeddings = [item.embedding for item in response.data]
            
            logger.info(f"✓ Generated {len(embeddings)} embeddings in batch")
            
            return embeddings
            
        except httpx.TimeoutException as e:
            logger.warning(f"⏱️  Batch embedding timeout after 10s - will retry: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to generate batch embeddings: {str(e)}")
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

