"""Company models for multi-tenant support."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID


class Company(BaseModel):
    """Company model representing a tenant."""
    id: UUID
    name: str
    goal: Optional[str] = None
    description: Optional[str] = None
    owner_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CompanyCreate(BaseModel):
    """Model for creating a new company."""
    name: str = Field(..., min_length=1, max_length=255)
    goal: Optional[str] = Field(None, max_length=1000, description="Company's goal or mission")
    description: Optional[str] = Field(None, max_length=2000, description="Company description")

    class Config:
        from_attributes = True


class CompanyUpdate(BaseModel):
    """Model for updating a company."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    goal: Optional[str] = Field(None, max_length=1000)
    description: Optional[str] = Field(None, max_length=2000)

    class Config:
        from_attributes = True


class CompanyMember(BaseModel):
    """Model for company member information."""
    user_id: UUID
    company_id: UUID
    role: str  # owner, admin, member
    email: str
    full_name: Optional[str] = None
    joined_at: datetime

    class Config:
        from_attributes = True

