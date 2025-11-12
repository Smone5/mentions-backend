"""Post verification task (Hard Rule #8)."""

import logging
import asyncio
from datetime import datetime
from uuid import UUID
from core.database import get_supabase_client
from reddit.client import get_reddit_client_for_account

logger = logging.getLogger(__name__)


async def verify_post_visibility(post_id: UUID):
    """
    Verify that a posted comment is visible on Reddit.
    
    Enforces Hard Rule #8: Verify post visibility.
    
    This checks if the post was:
    - Shadow-banned
    - Spam filtered
    - Removed by moderators
    
    Args:
        post_id: UUID of the post to verify
    """
    supabase = get_supabase_client()
    
    logger.info(f"Starting verification for post {post_id}")
    
    try:
        # Get post record
        post_result = supabase.table("posts").select("*").eq(
            "id", str(post_id)
        ).single().execute()
        
        if not post_result.data:
            logger.error(f"Post {post_id} not found")
            return
        
        post = post_result.data
        
        # Wait for Reddit to process the post
        await asyncio.sleep(30)
        
        # Get Reddit client
        reddit_client = await get_reddit_client_for_account(
            company_id=UUID(post["company_id"]),
            account_id=UUID(post["reddit_account_id"])
        )
        
        # Check if comment is visible
        is_visible = await reddit_client.check_comment_visible(
            post["comment_reddit_id"]
        )
        
        await reddit_client.close()
        
        # Update post record
        update_data = {
            "verified": True,
            "verified_at": datetime.utcnow().isoformat(),
        }
        
        if not is_visible:
            logger.warning(f"Post {post_id} appears to be removed or shadow-banned")
            update_data["error_message"] = "Post appears to be removed or shadow-banned"
            
            # TODO: Notify user that post may be removed
        else:
            logger.info(f"Post {post_id} verified as visible")
        
        supabase.table("posts").update(update_data).eq("id", str(post_id)).execute()
        
    except Exception as e:
        logger.error(f"Failed to verify post {post_id}: {str(e)}")
        
        # Mark as verified with error
        supabase.table("posts").update({
            "verified": True,
            "verified_at": datetime.utcnow().isoformat(),
            "error_message": f"Verification failed: {str(e)}"
        }).eq("id", str(post_id)).execute()

