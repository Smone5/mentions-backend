"""
Database connection and client management.
Uses Supabase client for PostgreSQL access.
"""
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
        logger.info(f"supabase_client_created: url={settings.SUPABASE_URL}", extra={"url": settings.SUPABASE_URL})
    
    return _supabase_client


def get_db_connection():
    """Get database connection (for direct SQL queries if needed)."""
    # For now, use Supabase client
    # Can add asyncpg connection pool later if needed
    return get_supabase_client()


def get_db_connection_string() -> str:
    """Get the database connection string."""
    return settings.DB_CONN

