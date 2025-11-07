"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Environment
    ENV: str = "dev"
    
    # Supabase
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    DB_CONN: str
    
    # OpenAI
    OPENAI_API_KEY: str
    
    # Google Cloud
    GOOGLE_PROJECT_ID: str
    GOOGLE_LOCATION: str = "us-central1"
    KMS_KEYRING: str = "reddit-secrets"
    KMS_KEY: str = "reddit-token-key"
    
    # Safety
    ALLOW_POSTS: bool = False
    
    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True
    
    # CORS
    @property
    def allowed_origins(self) -> List[str]:
        """Get allowed CORS origins based on environment."""
        if self.ENV == "dev":
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        elif self.ENV == "prod":
            # Add your production frontend URL here
            return ["https://yourdomain.com"]
        else:
            return ["*"]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

