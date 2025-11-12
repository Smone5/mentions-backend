"""
Configuration management using Pydantic Settings.
Loads environment variables and validates them.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Environment
    ENV: str = "dev"
    
    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    DB_CONN: str  # PostgreSQL connection string
    
    # OpenAI
    OPENAI_API_KEY: str
    
    # Google Cloud
    GOOGLE_PROJECT_ID: str
    GOOGLE_LOCATION: str = "us-central1"
    KMS_KEYRING: str
    KMS_KEY: str
    
    # Safety
    ALLOW_POSTS: bool = False
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    
    # CORS
    allowed_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",  # Ignore extra environment variables
    )


settings = Settings()

