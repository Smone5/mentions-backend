"""Reddit API client using asyncpraw."""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID

import asyncpraw
from asyncpraw.models import Subreddit, Submission, Comment

from core.database import get_supabase_client
from core.kms import decrypt
from core.config import settings

logger = logging.getLogger(__name__)


class RedditClient:
    """
    Reddit API client wrapper.
    
    IMPORTANT: Each company has its own Reddit app (Hard Rule #4).
    Each instance of this client is company-specific and account-specific.
    """
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        user_agent: str = "Mentions/1.0",
    ):
        """
        Initialize Reddit client for a specific company and account.
        
        Args:
            client_id: Reddit app client ID
            client_secret: Reddit app client secret (decrypted)
            refresh_token: User's refresh token (decrypted)
            user_agent: User agent string
        """
        self.reddit = asyncpraw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            user_agent=user_agent,
        )
    
    async def __aenter__(self):
        """Context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()
    
    async def close(self):
        """Close the Reddit client connection."""
        await self.reddit.close()
    
    async def get_me(self) -> Dict[str, Any]:
        """
        Get current authenticated user info.
        
        Returns:
            Dictionary with username, karma, and account details
        """
        try:
            me = await self.reddit.user.me()
            
            return {
                "username": me.name,
                "total_karma": me.link_karma + me.comment_karma,
                "link_karma": me.link_karma,
                "comment_karma": me.comment_karma,
                "created_utc": me.created_utc,
            }
        except Exception as e:
            logger.error(f"Failed to get Reddit user info: {str(e)}")
            raise
    
    async def search_subreddits(
        self,
        keyword: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant subreddits by keyword.
        
        Args:
            keyword: Search keyword
            limit: Maximum number of subreddits to return
            
        Returns:
            List of subreddit info dictionaries
        """
        try:
            results = []
            
            async for subreddit in self.reddit.subreddits.search(keyword, limit=limit):
                results.append({
                    "name": subreddit.display_name,
                    "subscribers": subreddit.subscribers,
                    "description": subreddit.public_description or subreddit.description,
                    "over_18": subreddit.over18,
                    "created_utc": subreddit.created_utc,
                })
            
            logger.info(f"Found {len(results)} subreddits for keyword: {keyword}")
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to search subreddits: {str(e)}")
            raise
    
    async def get_subreddit_rules(self, subreddit_name: str) -> str:
        """
        Get subreddit rules.
        
        Args:
            subreddit_name: Name of the subreddit
            
        Returns:
            Formatted string of subreddit rules
        """
        try:
            subreddit = await self.reddit.subreddit(subreddit_name)
            rules = await subreddit.rules()
            
            if not rules:
                return "No specific rules found."
            
            rules_text = []
            for i, rule in enumerate(rules, 1):
                rules_text.append(f"{i}. {rule.short_name}: {rule.description}")
            
            return "\n".join(rules_text)
            
        except Exception as e:
            logger.error(f"Failed to get subreddit rules for r/{subreddit_name}: {str(e)}")
            return "Could not fetch subreddit rules."
    
    async def get_hot_threads(
        self,
        subreddit_name: str,
        limit: int = 25,
        time_filter: str = "day"
    ) -> List[Dict[str, Any]]:
        """
        Get hot threads from a subreddit.
        
        Args:
            subreddit_name: Name of the subreddit
            limit: Maximum number of threads to return
            time_filter: Time filter (hour, day, week, month, year, all)
            
        Returns:
            List of thread info dictionaries
        """
        try:
            subreddit = await self.reddit.subreddit(subreddit_name)
            
            threads = []
            
            async for submission in subreddit.hot(limit=limit):
                # Skip stickied posts
                if submission.stickied:
                    continue
                
                threads.append({
                    "id": submission.id,
                    "title": submission.title,
                    "body": submission.selftext,
                    "author": str(submission.author),
                    "score": submission.score,
                    "upvote_ratio": submission.upvote_ratio,
                    "num_comments": submission.num_comments,
                    "created_utc": submission.created_utc,
                    "url": submission.url,
                    "permalink": submission.permalink,
                    "is_self": submission.is_self,
                })
            
            logger.info(f"Retrieved {len(threads)} hot threads from r/{subreddit_name}")
            
            return threads
            
        except Exception as e:
            logger.error(f"Failed to get hot threads from r/{subreddit_name}: {str(e)}")
            raise
    
    async def get_thread_details(self, thread_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific thread.
        
        Args:
            thread_id: Reddit thread ID
            
        Returns:
            Dictionary with thread details including top comments
        """
        try:
            submission = await self.reddit.submission(id=thread_id)
            
            # Get top comments (fetch more to understand full conversation)
            await submission.comments.replace_more(limit=0)  # Skip "load more" comments
            top_comments = []
            
            for comment in submission.comments[:20]:  # Top 20 comments for better context
                if isinstance(comment, Comment):
                    top_comments.append({
                        "id": comment.id,
                        "author": str(comment.author),
                        "body": comment.body,
                        "score": comment.score,
                        "created_utc": comment.created_utc,
                    })
            
            return {
                "id": submission.id,
                "title": submission.title,
                "body": submission.selftext,
                "author": str(submission.author),
                "score": submission.score,
                "upvote_ratio": submission.upvote_ratio,
                "num_comments": submission.num_comments,
                "created_utc": submission.created_utc,
                "url": submission.url,
                "permalink": submission.permalink,
                "subreddit": submission.subreddit.display_name,
                "top_comments": top_comments,
            }
            
        except Exception as e:
            logger.error(f"Failed to get thread details for {thread_id}: {str(e)}")
            raise
    
    async def post_comment(
        self,
        thread_id: str,
        body: str,
    ) -> Dict[str, Any]:
        """
        Post a comment to a Reddit thread.
        
        CRITICAL: This should ONLY be called in production with ALLOW_POSTS=true (Hard Rule #10).
        All hard rules must be enforced before calling this method.
        
        Args:
            thread_id: Reddit thread ID to comment on
            body: Comment body text (must have no links - Hard Rule #2)
            
        Returns:
            Dictionary with posted comment details
        """
        # Environment check (Hard Rule #10)
        logger.info(f"🎯 POST COMMENT CALLED - ENV={settings.ENV}, ALLOW_POSTS={settings.ALLOW_POSTS}")
        logger.info(f"   Thread: {thread_id}")
        logger.info(f"   Body length: {len(body)} chars")
        logger.info(f"   Body preview: {body[:200]}...")
        
        if settings.ENV != "prod":
            logger.warning(
                f"⚠️  [MOCK POST] Not posting to Reddit - ENV={settings.ENV} (must be 'prod')\n"
                f"   Thread ID: {thread_id}\n"
                f"   Body: {body[:100]}...\n"
                f"   To enable real posting: Set ENV=prod and ALLOW_POSTS=true"
            )
            return {
                "id": f"mock_{thread_id}",
                "body": body,
                "permalink": f"/r/test/comments/{thread_id}/test/mock",
                "created_utc": datetime.utcnow().timestamp(),
                "mock": True,
            }
        
        if not settings.ALLOW_POSTS:
            logger.error(
                f"❌ POSTING BLOCKED - ALLOW_POSTS is false\n"
                f"   Thread ID: {thread_id}\n"
                f"   Set ALLOW_POSTS=true to enable real posting"
            )
            raise Exception("ALLOW_POSTS is false - cannot post to Reddit")
        
        # If we get here, we're in prod mode with ALLOW_POSTS=true
        logger.info(f"✅ REAL POST STARTING - Posting to Reddit thread {thread_id}")
        
        try:
            # Get the submission
            submission = await self.reddit.submission(id=thread_id)
            logger.info(f"   Fetched submission: r/{submission.subreddit.display_name}")
            
            # Post the comment
            logger.info(f"   Calling submission.reply()...")
            comment = await submission.reply(body)
            
            logger.info(
                f"✅ COMMENT POSTED SUCCESSFULLY!\n"
                f"   Comment ID: {comment.id}\n"
                f"   Permalink: https://reddit.com{comment.permalink}\n"
                f"   Created: {datetime.fromtimestamp(comment.created_utc)}\n"
                f"   Subreddit: r/{submission.subreddit.display_name}"
            )
            
            return {
                "id": comment.id,
                "body": comment.body,
                "permalink": comment.permalink,
                "created_utc": comment.created_utc,
                "mock": False,
            }
            
        except Exception as e:
            logger.error(
                f"❌ FAILED TO POST COMMENT\n"
                f"   Thread: {thread_id}\n"
                f"   Error type: {type(e).__name__}\n"
                f"   Error: {str(e)}"
            )
            # Log the full exception with traceback
            import traceback
            logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise
    
    async def check_comment_visible(self, comment_id: str) -> bool:
        """
        Check if a comment is visible (not removed/spam filtered).
        
        Used for post verification (Hard Rule #8).
        
        Args:
            comment_id: Reddit comment ID
            
        Returns:
            True if visible, False if removed/spam filtered
        """
        try:
            comment = await self.reddit.comment(id=comment_id)
            
            # Check if removed
            if comment.removed:
                return False
            
            # Check if spam filtered
            if comment.spam:
                return False
            
            # Check if author is [deleted] (might indicate shadowban)
            if str(comment.author) == "[deleted]":
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to check comment visibility for {comment_id}: {str(e)}")
            return False


async def get_reddit_client_for_account(
    company_id: UUID,
    account_id: UUID
) -> RedditClient:
    """
    Get a Reddit client instance for a specific company and account.
    
    This enforces Hard Rule #4: One Reddit app per company.
    Each client is isolated to a specific company and user account.
    
    Args:
        company_id: Company UUID
        account_id: Reddit account UUID
        
    Returns:
        Configured RedditClient instance
        
    Raises:
        Exception: If Reddit app not configured or account not found
    """
    supabase = get_supabase_client()
    
    # Get company's Reddit app
    app_result = supabase.table("company_reddit_apps").select(
        "client_id, client_secret_ciphertext"
    ).eq("company_id", str(company_id)).single().execute()
    
    if not app_result.data:
        raise Exception(f"No Reddit app configured for company {company_id}")
    
    # Get account's refresh token
    account_result = supabase.table("reddit_connections").select(
        "refresh_token_ciphertext, reddit_username"
    ).eq("id", str(account_id)).eq("company_id", str(company_id)).single().execute()
    
    if not account_result.data:
        raise Exception(f"Reddit account {account_id} not found")
    
    # Decrypt credentials (Hard Rule #5)
    try:
        client_secret = decrypt(app_result.data["client_secret_ciphertext"])
        refresh_token = decrypt(account_result.data["refresh_token_ciphertext"])
    except Exception as e:
        logger.error(f"Failed to decrypt Reddit credentials: {str(e)}")
        raise Exception("Failed to decrypt Reddit credentials")
    
    # Create client instance (isolated per company/account)
    client = RedditClient(
        client_id=app_result.data["client_id"],
        client_secret=client_secret,
        refresh_token=refresh_token,
        user_agent=f"Mentions/1.0 (Company: {company_id})",
    )
    
    logger.info(
        f"Created Reddit client for company {company_id}, "
        f"account {account_result.data['reddit_username']}"
    )
    
    return client

