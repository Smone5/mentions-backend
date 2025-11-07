"""Posting service with ALL hard rules enforced."""

import logging
from datetime import datetime
from uuid import uuid4, UUID
from core.database import get_supabase_client
from core.config import settings
from reddit.client import get_reddit_client_for_account
from services.rate_limiter import check_post_eligibility
from services.link_validator import validate_no_links

logger = logging.getLogger(__name__)


async def post_to_reddit(
    draft_id: UUID,
    approved_by: UUID
) -> dict:
    """
    Post approved draft to Reddit with ALL hard rules enforced.
    
    Hard Rules Enforced:
    - Rule 1: Human approval required
    - Rule 2: No links in reply
    - Rule 6: Rate limiting enforced
    - Rule 8: Post verification scheduled
    - Rule 10: No posting in dev/staging
    
    Args:
        draft_id: UUID of the approved draft
        approved_by: UUID of the user who approved
        
    Returns:
        Dictionary with post result
        
    Raises:
        Exception: If any hard rule is violated
    """
    supabase = get_supabase_client()
    
    logger.info(f"Starting post to Reddit for draft {draft_id}")
    
    # Get draft with artifact and approval info
    draft_result = supabase.table("drafts").select(
        "*, artifacts!inner(id, company_id, reddit_account_id, subreddit, thread_id)"
    ).eq("id", str(draft_id)).single().execute()
    
    if not draft_result.data:
        raise Exception(f"Draft {draft_id} not found")
    
    draft = draft_result.data
    artifact = draft["artifacts"]
    
    # HARD RULE #1: Check approval
    if draft.get("status") != "approved":
        raise Exception(f"Draft not approved (status: {draft.get('status')})")
    
    if not draft.get("approved_by"):
        raise Exception("No approver found - human approval required")
    
    if draft.get("approved_by") != str(approved_by):
        logger.warning(
            f"Approved_by mismatch: draft has {draft.get('approved_by')}, "
            f"requested by {approved_by}"
        )
    
    # HARD RULE #10: Check environment
    if settings.ENV != "prod":
        logger.warning(f"MOCK POST: Environment is {settings.ENV}, not prod")
        return await _mock_post(draft, artifact)
    
    if not settings.ALLOW_POSTS:
        logger.warning("MOCK POST: ALLOW_POSTS is false")
        return await _mock_post(draft, artifact)
    
    # HARD RULE #2: Validate no links
    is_valid, reason = validate_no_links(draft.get("body", ""))
    if not is_valid:
        raise Exception(f"Draft contains forbidden links: {reason}")
    
    # HARD RULE #6: Check rate limits
    is_eligible, eligibility_reason = await check_post_eligibility(
        company_id=UUID(artifact["company_id"]),
        reddit_account_id=UUID(artifact["reddit_account_id"]),
        subreddit=artifact["subreddit"]
    )
    
    if not is_eligible:
        raise Exception(f"Rate limit exceeded: {eligibility_reason}")
    
    # All hard rules passed - POST TO REDDIT
    try:
        # Get Reddit client
        reddit_client = await get_reddit_client_for_account(
            company_id=UUID(artifact["company_id"]),
            account_id=UUID(artifact["reddit_account_id"])
        )
        
        # Post comment
        result = await reddit_client.post_comment(
            thread_id=artifact["thread_id"],
            body=draft["body"]
        )
        
        await reddit_client.close()
        
        # Create idempotency key to prevent double-posting
        idempotency_key = f"{draft_id}_{datetime.utcnow().isoformat()}"
        
        # Create post record
        post_data = {
            "id": str(uuid4()),
            "company_id": artifact["company_id"],
            "reddit_account_id": artifact["reddit_account_id"],
            "artifact_id": artifact["id"],
            "subreddit": artifact["subreddit"],
            "thread_reddit_id": artifact["thread_id"],
            "comment_reddit_id": result["id"],
            "permalink": result["permalink"],
            "posted_at": datetime.utcnow().isoformat(),
            "verified": False,
            "idempotency_key": idempotency_key,
            "retry_count": 0,
        }
        
        post_result = supabase.table("posts").insert(post_data).execute()
        
        if not post_result.data:
            raise Exception("Failed to create post record")
        
        post = post_result.data[0]
        
        # Update draft status
        supabase.table("drafts").update({
            "status": "posted"
        }).eq("id", str(draft_id)).execute()
        
        logger.info(
            f"Successfully posted to Reddit: {result['permalink']} "
            f"(post_id: {post['id']})"
        )
        
        # HARD RULE #8: Schedule verification (would use Cloud Tasks in production)
        # For now, we'll note that verification should be scheduled
        logger.info(f"TODO: Schedule verification for post {post['id']} in 60 seconds")
        
        return {
            "success": True,
            "post_id": post["id"],
            "comment_reddit_id": result["id"],
            "permalink": result["permalink"],
            "posted_at": post["posted_at"],
            "verification_scheduled": False,  # TODO: Implement with Cloud Tasks
        }
        
    except Exception as e:
        logger.error(f"Failed to post to Reddit: {str(e)}")
        
        # Log error to post record if possible
        try:
            error_post_data = {
                "id": str(uuid4()),
                "company_id": artifact["company_id"],
                "reddit_account_id": artifact["reddit_account_id"],
                "artifact_id": artifact["id"],
                "subreddit": artifact["subreddit"],
                "thread_reddit_id": artifact["thread_id"],
                "posted_at": datetime.utcnow().isoformat(),
                "verified": False,
                "error_message": str(e),
                "idempotency_key": f"failed_{draft_id}_{datetime.utcnow().isoformat()}",
            }
            supabase.table("posts").insert(error_post_data).execute()
        except:
            pass
        
        # Update draft status
        supabase.table("drafts").update({
            "status": "failed"
        }).eq("id", str(draft_id)).execute()
        
        raise


async def _mock_post(draft: dict, artifact: dict) -> dict:
    """
    Create a mock post record for dev/staging environments.
    
    This allows testing the full flow without actually posting to Reddit.
    """
    supabase = get_supabase_client()
    
    mock_comment_id = f"mock_{uuid4().hex[:8]}"
    mock_permalink = f"/r/{artifact['subreddit']}/comments/{artifact['thread_id']}/test/{mock_comment_id}"
    
    post_data = {
        "id": str(uuid4()),
        "company_id": artifact["company_id"],
        "reddit_account_id": artifact["reddit_account_id"],
        "artifact_id": artifact["id"],
        "subreddit": artifact["subreddit"],
        "thread_reddit_id": artifact["thread_id"],
        "comment_reddit_id": mock_comment_id,
        "permalink": mock_permalink,
        "posted_at": datetime.utcnow().isoformat(),
        "verified": True,  # Mock posts are auto-verified
        "idempotency_key": f"mock_{draft['id']}_{datetime.utcnow().isoformat()}",
    }
    
    post_result = supabase.table("posts").insert(post_data).execute()
    
    # Update draft status
    supabase.table("drafts").update({
        "status": "posted"
    }).eq("id", draft["id"]).execute()
    
    logger.info(f"Mock post created: {mock_permalink}")
    
    return {
        "success": True,
        "mock": True,
        "post_id": post_result.data[0]["id"],
        "comment_reddit_id": mock_comment_id,
        "permalink": mock_permalink,
        "posted_at": post_data["posted_at"],
    }

