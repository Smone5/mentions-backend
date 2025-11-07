"""RAG document models."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID


class Document(BaseModel):
    """RAG document model."""
    id: UUID
    company_id: UUID
    title: str
    source_url: Optional[str] = None
    chunk_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentCreate(BaseModel):
    """Model for creating a document."""
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1)
    source_url: Optional[str] = Field(None, max_length=1000)
    chunk_size: int = Field(1000, ge=200, le=2000)
    chunk_overlap: int = Field(200, ge=0, le=500)

    class Config:
        from_attributes = True


class DocumentChunk(BaseModel):
    """RAG document chunk model."""
    id: str
    content: str
    chunk_index: int
    title: str
    source_url: Optional[str] = None
    similarity: float

    class Config:
        from_attributes = True


class RetrieveRequest(BaseModel):
    """Request model for retrieving documents."""
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(5, ge=1, le=20)

    class Config:
        from_attributes = True

