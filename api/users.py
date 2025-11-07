"""
User API endpoints.
"""
from fastapi import APIRouter, HTTPException, Depends, status
from typing import Optional
from uuid import UUID

from models.user import UserProfile, UserProfileUpdate, SMSConsentUpdate
from core.database import get_supabase_client

router = APIRouter(prefix="/users", tags=["users"])


async def get_current_user() -> UUID:
    """
    Get the current authenticated user ID.
    In production, this would verify the JWT token from Supabase.
    """
    # TODO: Implement actual JWT verification
    # For now, this is a placeholder
    pass


@router.get("/me", response_model=UserProfile)
async def get_current_user_profile(
    user_id: UUID = Depends(get_current_user)
):
    """
    Get the current user's profile.
    """
    supabase = get_supabase_client()
    
    result = supabase.table("user_profiles").select("*").eq("id", str(user_id)).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )
    
    return UserProfile(**result.data)


@router.put("/me", response_model=UserProfile)
async def update_user_profile(
    profile_update: UserProfileUpdate,
    user_id: UUID = Depends(get_current_user)
):
    """
    Update the current user's profile.
    """
    supabase = get_supabase_client()
    
    # Build update dictionary, excluding None values
    update_data = profile_update.model_dump(exclude_none=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    # Add updated_at timestamp
    update_data["updated_at"] = "now()"
    
    result = supabase.table("user_profiles").update(update_data).eq("id", str(user_id)).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found"
        )
    
    return UserProfile(**result.data[0])


@router.post("/me/sms-consent")
async def update_sms_consent(
    consent_update: SMSConsentUpdate,
    user_id: UUID = Depends(get_current_user)
):
    """
    Update SMS consent preferences.
    This calls a database function to properly track opt-in/opt-out for compliance.
    """
    supabase = get_supabase_client()
    
    if consent_update.sms_consent:
        # Opt in
        result = supabase.rpc("opt_in_to_sms", {"user_id": str(user_id)}).execute()
    else:
        # Opt out
        result = supabase.rpc("opt_out_of_sms", {"user_id": str(user_id)}).execute()
    
    return {
        "success": True,
        "sms_consent": consent_update.sms_consent,
        "message": f"SMS notifications {'enabled' if consent_update.sms_consent else 'disabled'}"
    }


@router.delete("/me")
async def delete_user_account(
    user_id: UUID = Depends(get_current_user)
):
    """
    Delete the current user's account.
    This will cascade delete all related data.
    """
    supabase = get_supabase_client()
    
    # Delete from Supabase Auth (will cascade to user_profiles via FK)
    result = supabase.auth.admin.delete_user(str(user_id))
    
    return {
        "success": True,
        "message": "Account deleted successfully"
    }

