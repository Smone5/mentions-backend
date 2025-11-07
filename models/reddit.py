"""Reddit integration models."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl
from uuid import UUID


class RedditApp(BaseModel):
    """Reddit app configuration for a company."""
    id: UUID
    company_id: UUID
    client_id: str
    # client_secret_ciphertext is NOT included in response for security
    redirect_uri: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RedditAppCreate(BaseModel):
    """Model for configuring a Reddit app."""
    client_id: str = Field(..., min_length=1, description="Reddit app client ID")
    client_secret: str = Field(..., min_length=1, description="Reddit app client secret")
    redirect_uri: str = Field(..., description="OAuth redirect URI")

    class Config:
        from_attributes = True


class RedditAccount(BaseModel):
    """Reddit account connection for a user."""
    id: UUID
    company_id: UUID
    user_id: UUID
    reddit_username: str
    karma_total: int
    karma_comment: int
    account_created_at: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RedditOAuthStart(BaseModel):
    """Response for starting Reddit OAuth flow."""
    auth_url: str
    state: str  # State parameter for CSRF protection


class RedditOAuthCallback(BaseModel):
    """Reddit OAuth callback data."""
    code: str
    state: str

