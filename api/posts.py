"""Post management and posting API endpoints."""

import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status, BackgroundTasks
from uuid import UUID

from models.user import UserProfile
from core.database import get_supabase_client
from core.auth import get_current_user
from services.post import post_to_reddit
from tasks.verify_post import verify_post_visibility

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post("/{draft_id}/post")
async def post_draft(
    draft_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Post an approved draft to Reddit.
    
    This endpoint enforces ALL hard rules:
    - Rule 1: Human approval required
    - Rule 2: No links in reply
    - Rule 6: Rate limiting enforced
    - Rule 8: Post verification scheduled
    - Rule 10: No posting in dev/staging (mocked)
    
    The post will be created immediately, and verification will run in the background.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    try:
        # Post to Reddit (all hard rules enforced in service)
        result = await post_to_reddit(
            draft_id=draft_id,
            approved_by=current_user.id
        )
        
        # Schedule verification if not a mock post
        if not result.get("mock") and result.get("post_id"):
            background_tasks.add_task(
                verify_post_visibility,
                post_id=UUID(result["post_id"])
            )
        
        logger.info(f"Post created successfully: {result.get('post_id')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to post draft {draft_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("")
async def list_posts(
    limit: int = 50,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    List all posts for the company.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("posts").select("*").eq(
        "company_id", str(current_user.company_id)
    ).order("posted_at", desc=True).limit(limit).execute()
    
    return result.data


@router.get("/{post_id}")
async def get_post(
    post_id: UUID,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get a specific post by ID.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("posts").select("*").eq("id", str(post_id)).eq(
        "company_id", str(current_user.company_id)
    ).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    
    return result.data


@router.post("/{post_id}/verify")
async def verify_post(
    post_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Manually trigger verification for a post.
    
    Useful for re-checking posts that may have been initially filtered.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    # Verify post belongs to company
    result = supabase.table("posts").select("id").eq("id", str(post_id)).eq(
        "company_id", str(current_user.company_id)
    ).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )
    
    # Schedule verification
    background_tasks.add_task(verify_post_visibility, post_id=post_id)
    
    logger.info(f"Manual verification scheduled for post {post_id}")
    
    return {
        "success": True,
        "message": "Verification scheduled"
    }

