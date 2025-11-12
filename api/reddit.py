"""Reddit OAuth and app configuration API endpoints."""

import logging
import secrets
from typing import List, Optional
from urllib.parse import urlencode
from fastapi import APIRouter, HTTPException, Depends, status
from uuid import UUID, uuid4
from datetime import datetime, timezone

import httpx

from models.reddit import (
    RedditApp,
    RedditAppCreate,
    RedditAccount,
    RedditOAuthStart,
    RedditOAuthCallback,
)
from models.user import UserProfile
from core.database import get_supabase_client
from core.auth import get_current_user, require_role
from core.kms import encrypt, decrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reddit", tags=["reddit"])


@router.post("/app", response_model=RedditApp, status_code=status.HTTP_201_CREATED)
async def configure_reddit_app(
    app_config: RedditAppCreate,
    current_user: UserProfile = Depends(require_role(["owner", "admin"]))
):
    """
    Configure Reddit app for the company.
    Only owners and admins can configure the Reddit app.
    Client secret is encrypted with KMS before storage (Hard Rule #5).
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    try:
        # Encrypt client secret with KMS
        encrypted_secret = encrypt(app_config.client_secret)
        
        # Prepare data for upsert
        app_data = {
            "company_id": str(current_user.company_id),
            "client_id": app_config.client_id,
            "client_secret_ciphertext": encrypted_secret,
            "redirect_uri": app_config.redirect_uri,
            "created_by": str(current_user.id),
        }
        
        # Check if app already exists for this company
        existing = supabase.table("company_reddit_apps").select("id").eq(
            "company_id", str(current_user.company_id)
        ).execute()
        
        if existing.data:
            # Update existing
            app_data["updated_at"] = "now()"
            result = supabase.table("company_reddit_apps").update(app_data).eq(
                "company_id", str(current_user.company_id)
            ).execute()
        else:
            # Insert new
            app_data["id"] = str(uuid4())
            result = supabase.table("company_reddit_apps").insert(app_data).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to configure Reddit app"
            )
        
        logger.info(f"Reddit app configured for company {current_user.company_id}")
        
        # Return without the encrypted secret
        return RedditApp(**result.data[0])
        
    except Exception as e:
        logger.error(f"Failed to configure Reddit app: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to configure Reddit app"
        )


@router.get("/app", response_model=RedditApp)
async def get_reddit_app(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get Reddit app configuration for the user's company.
    Client secret is NOT returned for security.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("company_reddit_apps").select("*").eq(
        "company_id", str(current_user.company_id)
    ).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reddit app not configured for this company"
        )
    
    return RedditApp(**result.data)


@router.get("/oauth/start", response_model=RedditOAuthStart)
async def start_reddit_oauth(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Start Reddit OAuth flow.
    Returns authorization URL and state parameter for CSRF protection.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    # Get company's Reddit app config
    app_result = supabase.table("company_reddit_apps").select("client_id, redirect_uri").eq(
        "company_id", str(current_user.company_id)
    ).single().execute()
    
    if not app_result.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit app not configured for this company"
        )
    
    # Generate secure state parameter for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Store state in user session (simplified - in production use Redis or session store)
    # For now, we'll include the user_id in the state
    state_with_user = f"{current_user.id}:{state}"
    
    # Build Reddit authorization URL
    params = {
        "client_id": app_result.data["client_id"],
        "response_type": "code",
        "state": state_with_user,
        "redirect_uri": app_result.data["redirect_uri"],
        "duration": "permanent",  # Get refresh token
        "scope": "identity read submit vote history"  # Required scopes
    }
    
    auth_url = f"https://www.reddit.com/api/v1/authorize?{urlencode(params)}"
    
    logger.info(f"Started Reddit OAuth flow for user {current_user.id}")
    
    return RedditOAuthStart(auth_url=auth_url, state=state_with_user)


@router.post("/oauth/callback")
async def reddit_oauth_callback(
    callback_data: RedditOAuthCallback,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Handle Reddit OAuth callback.
    Exchanges authorization code for access/refresh tokens.
    Stores encrypted refresh token in database (Hard Rule #5).
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    # Verify state parameter for CSRF protection
    try:
        state_user_id, state_token = callback_data.state.split(":", 1)
        if state_user_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter"
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state format"
        )
    
    # Get company's Reddit app config
    app_result = supabase.table("company_reddit_apps").select(
        "id, client_id, client_secret_ciphertext, redirect_uri"
    ).eq("company_id", str(current_user.company_id)).single().execute()
    
    if not app_result.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reddit app not configured"
        )
    
    # Decrypt client secret
    try:
        client_secret = decrypt(app_result.data["client_secret_ciphertext"])
    except Exception as e:
        logger.error(f"Failed to decrypt Reddit client secret: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt credentials"
        )
    
    # Exchange authorization code for tokens
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for tokens
            token_response = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(app_result.data["client_id"], client_secret),
                data={
                    "grant_type": "authorization_code",
                    "code": callback_data.code,
                    "redirect_uri": app_result.data["redirect_uri"]
                },
                headers={"User-Agent": "Mentions/1.0"}
            )
            
            if token_response.status_code != 200:
                logger.error(f"Reddit token exchange failed: {token_response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code for tokens"
                )
            
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            refresh_token = tokens.get("refresh_token")
            
            if not access_token or not refresh_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid token response from Reddit"
                )
            
            # Fetch user profile from Reddit
            profile_response = await client.get(
                "https://oauth.reddit.com/api/v1/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": "Mentions/1.0"
                }
            )
            
            if profile_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch Reddit profile"
                )
            
            profile = profile_response.json()

            # Convert created_utc (seconds since epoch) to ISO timestamp if present
            raw_created_at: Optional[float] = profile.get("created_utc")
            created_at_iso: Optional[str] = None
            if raw_created_at is not None:
                try:
                    created_at_iso = datetime.fromtimestamp(
                        float(raw_created_at), tz=timezone.utc
                    ).isoformat()
                except (TypeError, ValueError):
                    logger.warning(
                        "Unable to convert Reddit account created_utc to timestamp",
                        extra={"created_utc": raw_created_at},
                    )
            
            # Encrypt refresh token with KMS (Hard Rule #5)
            encrypted_refresh_token = encrypt(refresh_token)
            
            # Save Reddit account to database
            account_data = {
                "company_id": str(current_user.company_id),
                "user_id": str(current_user.id),
                "company_reddit_app_id": app_result.data["id"],
                "reddit_username": profile["name"],
                "refresh_token_ciphertext": encrypted_refresh_token,
                "karma_total": profile.get("total_karma", 0),
                "karma_comment": profile.get("comment_karma", 0),
                "account_created_at": created_at_iso,
                "is_active": True,
            }
            
            # Upsert (insert or update if exists)
            existing_account = supabase.table("reddit_connections").select("id").eq(
                "user_id", str(current_user.id)
            ).eq("company_id", str(current_user.company_id)).execute()
            
            if existing_account.data:
                # Update existing connection
                result = supabase.table("reddit_connections").update(account_data).eq(
                    "id", existing_account.data[0]["id"]
                ).execute()
            else:
                # Insert new connection
                account_data["id"] = str(uuid4())
                result = supabase.table("reddit_connections").insert(account_data).execute()
            
            if not result.data:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to save Reddit account"
                )
            
            logger.info(f"Reddit account connected: {profile['name']} for user {current_user.id}")
            
            return {
                "success": True,
                "reddit_username": profile["name"],
                "karma_total": profile.get("total_karma", 0),
                "message": "Reddit account connected successfully"
            }
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during Reddit OAuth: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to communicate with Reddit"
        )
    except Exception as e:
        logger.error(f"Error during Reddit OAuth callback: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete Reddit OAuth"
        )


@router.get("/accounts", response_model=List[RedditAccount])
async def get_reddit_accounts(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get all Reddit accounts connected for the user's company.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("reddit_connections").select("*").eq(
        "company_id", str(current_user.company_id)
    ).execute()
    
    if not result.data:
        return []
    
    return [RedditAccount(**account) for account in result.data]


@router.delete("/accounts/{account_id}")
async def disconnect_reddit_account(
    account_id: UUID,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Disconnect a Reddit account.
    Users can only disconnect their own accounts unless they're an admin/owner.
    """
    supabase = get_supabase_client()
    
    # Get account to verify ownership/access
    account_result = supabase.table("reddit_connections").select("*").eq(
        "id", str(account_id)
    ).single().execute()
    
    if not account_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reddit account not found"
        )
    
    account = account_result.data
    
    # Verify user has permission
    if account["company_id"] != str(current_user.company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this account"
        )
    
    if account["user_id"] != str(current_user.id):
        # Check if user is admin/owner to disconnect others' accounts
        user_role_result = supabase.table("user_profiles").select("role").eq(
            "id", str(current_user.id)
        ).single().execute()
        
        if not user_role_result.data or user_role_result.data.get("role") not in ["owner", "admin"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only disconnect your own accounts"
            )
    
    # Delete the connection
    supabase.table("reddit_connections").delete().eq("id", str(account_id)).execute()
    
    logger.info(f"Reddit account disconnected: {account_id} by user {current_user.id}")
    
    return {
        "success": True,
        "message": "Reddit account disconnected successfully"
    }

