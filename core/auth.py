"""Authentication and authorization utilities."""

import logging
from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from core.config import settings
from core.database import get_supabase_client
from models.user import UserProfile

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UserProfile:
    """
    Verify JWT token and return current user profile.
    
    This function:
    1. Extracts JWT from Authorization header
    2. Verifies JWT with Supabase
    3. Fetches user profile from database
    4. Returns UserProfile object
    
    Raises:
        HTTPException: If token is invalid or user not found
    """
    token = credentials.credentials
    
    try:
        # Verify token with Supabase
        supabase = get_supabase_client()
        
        # Get user from token
        user_response = supabase.auth.get_user(token)
        
        if not user_response or not user_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        user_id = user_response.user.id
        user_email = user_response.user.email
        
        # Fetch user profile from database
        profile_response = supabase.table("user_profiles").select("*").eq("id", user_id).single().execute()
        
        if not profile_response.data:
            # User authenticated but no profile - this shouldn't happen
            # but let's create a basic profile entry if needed
            logger.warning(f"User {user_id} authenticated but no profile found, creating one")
            
            # Create basic profile
            profile_data = {
                "id": user_id,
                "email": user_email,
                "full_name": user_email.split('@')[0],  # Default to email prefix
            }
            
            create_response = supabase.table("user_profiles").insert(profile_data).execute()
            
            if not create_response.data:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create user profile"
                )
            
            profile_response.data = create_response.data[0]
        
        # Return UserProfile object
        user_profile = UserProfile(
            id=UUID(profile_response.data["id"]),
            email=profile_response.data["email"],
            full_name=profile_response.data.get("full_name"),
            phone_number=profile_response.data.get("phone_number"),
            birthdate=profile_response.data.get("birthdate"),
            sms_consent=profile_response.data.get("sms_consent", False),
            sms_opt_out_at=profile_response.data.get("sms_opt_out_at"),
            company_id=UUID(profile_response.data["company_id"]) if profile_response.data.get("company_id") else None,
            created_at=profile_response.data["created_at"],
            updated_at=profile_response.data["updated_at"],
        )
        
        logger.info(f"User authenticated: {user_profile.email}")
        
        return user_profile
        
    except JWTError as e:
        logger.error(f"JWT verification failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_active_user(
    current_user: UserProfile = Depends(get_current_user)
) -> UserProfile:
    """
    Get current user and verify they're active.
    Can be extended to check for banned/suspended users.
    """
    # Add any additional checks here (e.g., is_active, is_banned, etc.)
    return current_user


async def verify_company_access(
    company_id: UUID,
    current_user: UserProfile = Depends(get_current_user)
) -> bool:
    """
    Verify that current user has access to the specified company.
    
    Args:
        company_id: UUID of the company to check access for
        current_user: Current authenticated user
        
    Returns:
        True if user has access, raises HTTPException otherwise
    """
    if current_user.company_id != company_id:
        logger.warning(
            f"User {current_user.id} attempted to access company {company_id} "
            f"but belongs to company {current_user.company_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this company"
        )
    
    return True


def require_role(allowed_roles: list[str]):
    """
    Dependency factory to require specific user roles.
    
    Usage:
        @router.post("/admin-only")
        async def admin_endpoint(user: UserProfile = Depends(require_role(["owner", "admin"]))):
            ...
    """
    async def role_checker(current_user: UserProfile = Depends(get_current_user)) -> UserProfile:
        # Fetch role from user_profiles table
        supabase = get_supabase_client()
        result = supabase.table("user_profiles").select("role").eq("id", str(current_user.id)).single().execute()
        
        if not result.data or result.data.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of these roles: {', '.join(allowed_roles)}"
            )
        
        return current_user
    
    return role_checker

