"""Database connection and client setup."""

from supabase import create_client, Client
from core.config import settings
import logging

logger = logging.getLogger(__name__)

# Global Supabase client instance
_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    """Get or create Supabase client instance."""
    global _supabase_client
    
    if _supabase_client is None:
        _supabase_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_SERVICE_ROLE_KEY
        )
        logger.info("Supabase client initialized")
    
    return _supabase_client


def get_db_connection_string() -> str:
    """Get database connection string."""
    return settings.DB_CONN

