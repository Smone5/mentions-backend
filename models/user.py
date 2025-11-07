"""
User models for the Mentions application.
"""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID


class UserProfile(BaseModel):
    """User profile model extending Supabase auth.users"""
    id: UUID
    email: EmailStr
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    birthdate: Optional[date] = None
    sms_consent: bool = False
    sms_opt_out_at: Optional[datetime] = None
    company_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    """User profile update model"""
    full_name: Optional[str] = None
    phone_number: Optional[str] = Field(None, description="Phone number in E.164 format recommended")
    birthdate: Optional[date] = None
    
    class Config:
        from_attributes = True


class SMSConsentUpdate(BaseModel):
    """SMS consent update model"""
    sms_consent: bool = Field(..., description="Whether user consents to SMS notifications")
    
    class Config:
        from_attributes = True


class UserSignupData(BaseModel):
    """Data collected during user signup"""
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=1)
    company_name: Optional[str] = None
    phone_number: Optional[str] = None
    birthdate: Optional[date] = None
    sms_consent: bool = False
    
    class Config:
        from_attributes = True

