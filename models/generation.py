"""Models for draft generation."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID


class GenerateRequest(BaseModel):
    """Request to generate drafts for a keyword."""
    keyword: str = Field(..., min_length=1, max_length=255)
    reddit_account_id: UUID = Field(..., description="Reddit account to use for generation")

    class Config:
        from_attributes = True


class GenerateResponse(BaseModel):
    """Response from draft generation."""
    success: bool
    thread_id: str
    artifact_id: Optional[str] = None
    draft_id: Optional[str] = None
    error: Optional[str] = None
    state: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class Artifact(BaseModel):
    """Generated artifact (thread + drafts)."""
    id: UUID
    company_id: UUID
    reddit_account_id: UUID
    subreddit: str
    thread_id: str
    thread_title: str
    thread_body: str
    thread_url: str
    created_at: datetime

    class Config:
        from_attributes = True


class Draft(BaseModel):
    """Draft reply."""
    id: UUID
    artifact_id: UUID
    version: int
    body: str
    risk_level: str
    judge_reason: Optional[str] = None
    status: str  # pending, approved, rejected, posted
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DraftUpdate(BaseModel):
    """Update draft fields."""
    body: Optional[str] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True

