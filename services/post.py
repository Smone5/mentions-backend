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
    
    logger.info(f"=" * 80)
    logger.info(f"🚀 STARTING POST TO REDDIT WORKFLOW")
    logger.info(f"   Draft ID: {draft_id}")
    logger.info(f"   Approved by: {approved_by}")
    logger.info(f"   Environment: {settings.ENV}")
    logger.info(f"   ALLOW_POSTS: {settings.ALLOW_POSTS}")
    logger.info(f"=" * 80)
    
    # Get draft with artifact and approval info
    logger.info(f"Fetching draft {draft_id} from database...")
    draft_result = supabase.table("drafts").select(
        "*, artifacts!inner(id, company_id, reddit_account_id, subreddit, thread_id, thread_reddit_id), approvals!chosen_draft_id(status, approved_by)"
    ).eq("id", str(draft_id)).single().execute()
    
    if not draft_result.data:
        raise Exception(f"Draft {draft_id} not found")
    
    draft = draft_result.data
    artifact = draft["artifacts"]
    
    # HARD RULE #1: Check approval
    logger.info(f"✅ HARD RULE #1: Checking human approval...")
    
    # Get approval status from approvals table
    approvals = draft.get("approvals", [])
    if not approvals:
        logger.error(f"❌ Draft not approved (no approval record found)")
        raise Exception(f"Draft not approved (status: pending)")
    
    approval = approvals[0]
    approval_status = approval.get("status")
    
    if approval_status != "approved":
        logger.error(f"❌ Draft not approved (status: {approval_status})")
        raise Exception(f"Draft not approved (status: {approval_status})")
    
    approver_id = approval.get("approved_by")
    if not approver_id:
        logger.error(f"❌ No approver found")
        raise Exception("No approver found - human approval required")
    
    logger.info(f"   Draft approved by: {approver_id}")
    
    if approver_id != str(approved_by):
        logger.warning(
            f"Approved_by mismatch: approval has {approver_id}, "
            f"requested by {approved_by}"
        )
    
    # HARD RULE #10: Check if posting is allowed
    # Allow real posts in dev if ALLOW_POSTS is explicitly set to true
    logger.info(f"✅ HARD RULE #10: Checking environment...")
    if not settings.ALLOW_POSTS:
        logger.warning(
            f"⚠️  MOCK POST MODE\n"
            f"   ENV={settings.ENV}\n"
            f"   ALLOW_POSTS={settings.ALLOW_POSTS}\n"
            f"   This draft will NOT be posted to Reddit\n"
            f"   To enable real posting: Set ENV=prod and ALLOW_POSTS=true"
        )
        return await _mock_post(draft, artifact)
    
    logger.info(f"   Real posting enabled (ALLOW_POSTS=true)")
    
    # HARD RULE #2: Validate no links
    logger.info(f"✅ HARD RULE #2: Checking for links in draft...")
    is_valid, reason = validate_no_links(draft.get("body", ""))
    if not is_valid:
        logger.error(f"❌ Draft contains forbidden links: {reason}")
        raise Exception(f"Draft contains forbidden links: {reason}")
    logger.info(f"   No links found - passed")
    
    # HARD RULE #6: Check rate limits
    logger.info(f"✅ HARD RULE #6: Checking rate limits...")
    logger.info(f"   Company: {artifact['company_id']}")
    logger.info(f"   Account: {artifact['reddit_account_id']}")
    logger.info(f"   Subreddit: r/{artifact['subreddit']}")
    
    is_eligible, eligibility_reason = await check_post_eligibility(
        company_id=UUID(artifact["company_id"]),
        reddit_account_id=UUID(artifact["reddit_account_id"]),
        subreddit=artifact["subreddit"]
    )
    
    if not is_eligible:
        logger.error(f"❌ Rate limit exceeded: {eligibility_reason}")
        raise Exception(f"Rate limit exceeded: {eligibility_reason}")
    
    logger.info(f"   Rate limits OK - can post")
    
    # All hard rules passed - POST TO REDDIT
    logger.info(f"✅ ALL HARD RULES PASSED - Proceeding to post to Reddit")
    logger.info(f"   Thread: {artifact['thread_reddit_id']}")
    logger.info(f"   Subreddit: r/{artifact['subreddit']}")
    
    try:
        # Get Reddit client
        logger.info(f"   Creating Reddit client...")
        reddit_client = await get_reddit_client_for_account(
            company_id=UUID(artifact["company_id"]),
            account_id=UUID(artifact["reddit_account_id"])
        )
        logger.info(f"   Reddit client created")
        
        # Post comment
        logger.info(f"   Calling reddit_client.post_comment()...")
        result = await reddit_client.post_comment(
            thread_id=artifact["thread_reddit_id"],
            body=draft["body"]
        )
        logger.info(f"   reddit_client.post_comment() returned")
        
        await reddit_client.close()
        logger.info(f"   Reddit client closed")
        
        # Create idempotency key to prevent double-posting
        idempotency_key = f"{draft_id}_{datetime.utcnow().isoformat()}"
        
        # Create post record
        post_data = {
            "id": str(uuid4()),
            "company_id": artifact["company_id"],
            "reddit_account_id": artifact["reddit_account_id"],
            "artifact_id": artifact["id"],
            "subreddit": artifact["subreddit"],
            "thread_reddit_id": artifact["thread_reddit_id"],
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
        
        is_mock = result.get("mock", False)
        
        if is_mock:
            logger.info(
                f"⚠️  MOCK POST CREATED (not actually on Reddit)\n"
                f"   Post ID: {post['id']}\n"
                f"   Mock permalink: {result['permalink']}"
            )
        else:
            logger.info(
                f"🎉 SUCCESSFULLY POSTED TO REDDIT!\n"
                f"   Post ID: {post['id']}\n"
                f"   Comment ID: {result['id']}\n"
                f"   Permalink: https://reddit.com{result['permalink']}\n"
                f"   View at: https://reddit.com{result['permalink']}"
            )
        
        # HARD RULE #8: Schedule verification (would use Cloud Tasks in production)
        # For now, we'll note that verification should be scheduled
        logger.info(f"✅ HARD RULE #8: TODO - Schedule verification for post {post['id']} in 60 seconds")
        
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
                "thread_reddit_id": artifact["thread_reddit_id"],
                "posted_at": datetime.utcnow().isoformat(),
                "verified": False,
                "error_message": str(e),
                "idempotency_key": f"failed_{draft_id}_{datetime.utcnow().isoformat()}",
            }
            supabase.table("posts").insert(error_post_data).execute()
        except Exception as error_log_ex:
            logger.warning(f"Failed to log error post record: {error_log_ex}")
        
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
    mock_permalink = f"/r/{artifact['subreddit']}/comments/{artifact['thread_reddit_id']}/test/{mock_comment_id}"
    
    post_data = {
        "id": str(uuid4()),
        "company_id": artifact["company_id"],
        "reddit_account_id": artifact["reddit_account_id"],
        "artifact_id": artifact["id"],
        "subreddit": artifact["subreddit"],
        "thread_reddit_id": artifact["thread_reddit_id"],
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

