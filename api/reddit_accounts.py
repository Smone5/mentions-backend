"""
Reddit account management and OAuth endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from core.auth import get_current_user
from core.database import get_supabase_client
from core.kms import encrypt, decrypt
from supabase import Client
from models.user import UserProfile
import logging
import secrets
from urllib.parse import urlencode
import httpx

router = APIRouter()
logger = logging.getLogger(__name__)


class RedditAppConfig(BaseModel):
    """Reddit app configuration model."""
    client_id: str
    client_secret: str
    redirect_uri: str


@router.post("/app/configure")
async def configure_reddit_app(
    config: RedditAppConfig,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Configure Reddit app credentials for company."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Verify user is owner/admin - Note: role needs to be fetched from DB
    profile_response = supabase.table("user_profiles").select("role").eq("id", str(user.id)).single().execute()
    if not profile_response.data or profile_response.data.get("role") not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    # Encrypt client_secret
    encrypted_secret = encrypt(config.client_secret)
    
    # Upsert to database
    response = supabase.table("reddit_apps").upsert({
        "company_id": str(user.company_id),
        "client_id": config.client_id,
        "client_secret_ciphertext": encrypted_secret,
        "redirect_uri": config.redirect_uri,
    }, on_conflict="company_id").execute()
    
    logger.info("reddit_app_configured", company_id=str(user.company_id), user_id=str(user.id))
    
    return {"success": True, "message": "Reddit app configured"}


@router.get("/app/config")
async def get_reddit_app_config(
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Get Reddit app configuration (without secret)."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    response = supabase.table("reddit_apps").select(
        "id, client_id, redirect_uri, created_at"
    ).eq("company_id", str(user.company_id)).execute()
    
    if not response.data:
        return {"configured": False}
    
    return {
        "configured": True,
        **response.data[0]
    }


@router.get("/connect/start")
async def start_reddit_oauth(
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Start Reddit OAuth flow."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get company's Reddit app config
    app_response = supabase.table("reddit_apps").select(
        "id, client_id, redirect_uri"
    ).eq("company_id", str(user.company_id)).single().execute()
    
    if not app_response.data:
        raise HTTPException(status_code=400, detail="Reddit app not configured")
    
    app_config = app_response.data
    
    # Generate state parameter
    state = secrets.token_urlsafe(32)
    
    # Build authorization URL
    params = {
        "client_id": app_config["client_id"],
        "response_type": "code",
        "state": state,
        "redirect_uri": app_config["redirect_uri"],
        "duration": "permanent",
        "scope": "identity read submit vote"
    }
    
    auth_url = f"https://www.reddit.com/api/v1/authorize?{urlencode(params)}"
    
    return {"auth_url": auth_url, "state": state}


@router.get("/connect/callback")
async def reddit_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Handle Reddit OAuth callback."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # TODO: Verify state parameter
    
    # Get app config
    app_response = supabase.table("reddit_apps").select(
        "id, client_id, client_secret_ciphertext, redirect_uri"
    ).eq("company_id", str(user.company_id)).single().execute()
    
    if not app_response.data:
        raise HTTPException(status_code=400, detail="Reddit app not configured")
    
    app_config = app_response.data
    client_secret = decrypt(app_config["client_secret_ciphertext"])
    
    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(app_config["client_id"], client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": app_config["redirect_uri"]
            },
            headers={"User-Agent": "mentions/1.0"}
        )
        
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get tokens")
        
        tokens = token_response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
        
        # Fetch Reddit profile
        profile_response = await client.get(
            "https://oauth.reddit.com/api/v1/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "mentions/1.0"
            }
        )
        
        if profile_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get profile")
        
        profile = profile_response.json()
        
        # Encrypt refresh token
        encrypted_refresh = encrypt(refresh_token)
        
        # Save to database
        supabase.table("reddit_connections").upsert({
            "company_id": str(user.company_id),
            "user_id": str(user.id),
            "company_reddit_app_id": app_config["id"],
            "reddit_username": profile["name"],
            "refresh_token_ciphertext": encrypted_refresh,
            "karma_total": profile.get("total_karma", 0),
            "karma_comment": profile.get("comment_karma", 0),
            "account_created_at": profile.get("created_utc"),
            "is_active": True
        }, on_conflict="user_id,company_id").execute()
    
    logger.info("reddit_account_connected", company_id=str(user.company_id), username=profile["name"])
    
    return {"success": True, "reddit_username": profile["name"]}


@router.get("")
async def list_reddit_accounts(
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """List Reddit accounts for company."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    response = supabase.table("reddit_connections").select(
        "id, reddit_username, karma_total, karma_comment, account_created_at, created_at, is_active"
    ).eq("company_id", str(user.company_id)).execute()
    
    return {"accounts": response.data or []}


@router.delete("/{account_id}")
async def disconnect_reddit_account(
    account_id: str,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Disconnect Reddit account."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Verify account belongs to company
    account_response = supabase.table("reddit_connections").select(
        "company_id"
    ).eq("id", account_id).single().execute()
    
    if not account_response.data:
        raise HTTPException(status_code=404, detail="Account not found")
    
    if account_response.data["company_id"] != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Mark as inactive
    supabase.table("reddit_connections").update({
        "is_active": False
    }).eq("id", account_id).execute()
    
    logger.info("reddit_account_disconnected", account_id=account_id, user_id=str(user.id))
    
    return {"success": True}

