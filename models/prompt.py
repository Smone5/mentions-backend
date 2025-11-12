"""Prompt models for customizable LLM prompts."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID


class Prompt(BaseModel):
    """Prompt template model."""
    id: UUID
    company_id: UUID
    name: str
    description: Optional[str] = None
    template: str
    prompt_type: str  # "compose", "judge_subreddit", "judge_draft", "rank", etc.
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PromptCreate(BaseModel):
    """Model for creating a prompt."""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    template: str = Field(..., min_length=1)
    prompt_type: str = Field(..., description="Type of prompt (compose, judge_subreddit, etc.)")

    class Config:
        from_attributes = True


class PromptUpdate(BaseModel):
    """Model for updating a prompt."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    template: Optional[str] = Field(None, min_length=1)
    is_active: Optional[bool] = None

    class Config:
        from_attributes = True


class PromptRenderRequest(BaseModel):
    """Request model for rendering a prompt template."""
    prompt_id: UUID
    variables: dict = Field(default_factory=dict)

    class Config:
        from_attributes = True

