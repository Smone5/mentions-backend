"""Rate limiting service for Reddit posting (Hard Rule #6)."""

import logging
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID
from core.database import get_supabase_client
from core.config import settings

logger = logging.getLogger(__name__)

# Rate limit constants (Hard Rule #6)
MAX_POSTS_PER_ACCOUNT_PER_DAY = 10
MAX_POSTS_PER_SUBREDDIT_PER_ACCOUNT_PER_WEEK = 3
MIN_MINUTES_BETWEEN_POSTS = 15
MAX_POSTS_PER_COMPANY_PER_DAY = 50


async def check_post_eligibility(
    company_id: UUID,
    reddit_account_id: UUID,
    subreddit: str
) -> tuple[bool, str]:
    """
    Check if account is eligible to post based on rate limits.
    
    Enforces Hard Rule #6: Rate limiting must be enforced.
    
    Args:
        company_id: Company UUID
        reddit_account_id: Reddit account UUID
        subreddit: Target subreddit
        
    Returns:
        (is_eligible, reason)
    """
    # Allow bypassing rate limits for testing/development
    if settings.SKIP_RATE_LIMITS:
        logger.warning(
            f"⚠️  RATE LIMITS BYPASSED (SKIP_RATE_LIMITS=true)\n"
            f"   Account: {reddit_account_id}\n"
            f"   Subreddit: r/{subreddit}\n"
            f"   This should only be used for testing!"
        )
        return True, "Rate limits bypassed"
    
    supabase = get_supabase_client()
    
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    
    try:
        # Check 1: Account daily limit
        account_posts_today = supabase.table("posts").select("id", count="exact").eq(
            "reddit_account_id", str(reddit_account_id)
        ).gte("posted_at", today_start.isoformat()).execute()
        
        posts_today = account_posts_today.count or 0
        
        if posts_today >= MAX_POSTS_PER_ACCOUNT_PER_DAY:
            return False, f"Account daily limit reached ({MAX_POSTS_PER_ACCOUNT_PER_DAY} posts/day)"
        
        # Check 2: Subreddit weekly limit per account
        subreddit_posts_week = supabase.table("posts").select("id", count="exact").eq(
            "reddit_account_id", str(reddit_account_id)
        ).eq("subreddit", subreddit).gte("posted_at", week_start.isoformat()).execute()
        
        posts_this_week = subreddit_posts_week.count or 0
        
        if posts_this_week >= MAX_POSTS_PER_SUBREDDIT_PER_ACCOUNT_PER_WEEK:
            return False, f"Subreddit weekly limit reached ({MAX_POSTS_PER_SUBREDDIT_PER_ACCOUNT_PER_WEEK} posts/week in r/{subreddit})"
        
        # Check 3: Time since last post
        last_post = supabase.table("posts").select("posted_at").eq(
            "reddit_account_id", str(reddit_account_id)
        ).order("posted_at", desc=True).limit(1).execute()
        
        if last_post.data:
            last_post_time = datetime.fromisoformat(last_post.data[0]["posted_at"].replace("Z", "+00:00"))
            minutes_since = (now - last_post_time).total_seconds() / 60
            
            if minutes_since < MIN_MINUTES_BETWEEN_POSTS:
                wait_minutes = math.ceil(MIN_MINUTES_BETWEEN_POSTS - minutes_since)
                return False, f"Must wait {wait_minutes} more minutes between posts"
        
        # Check 4: Company daily limit
        company_posts_today = supabase.table("posts").select("id", count="exact").eq(
            "company_id", str(company_id)
        ).gte("posted_at", today_start.isoformat()).execute()
        
        company_posts_count = company_posts_today.count or 0
        
        if company_posts_count >= MAX_POSTS_PER_COMPANY_PER_DAY:
            return False, f"Company daily limit reached ({MAX_POSTS_PER_COMPANY_PER_DAY} posts/day)"
        
        # All checks passed
        logger.info(
            f"Post eligibility check passed for account {reddit_account_id} "
            f"to r/{subreddit}"
        )
        
        return True, "Eligible"
        
    except Exception as e:
        logger.error(f"Failed to check post eligibility: {str(e)}")
        # On error, be conservative and reject
        return False, f"Eligibility check failed: {str(e)}"

