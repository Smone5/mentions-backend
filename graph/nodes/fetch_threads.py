"""Node to fetch hot threads from subreddit."""

import logging
from graph.state import GenerateState
from reddit.client import get_reddit_client_for_account

logger = logging.getLogger(__name__)


async def fetch_threads_node(state: GenerateState) -> GenerateState:
    """
    Fetch hot threads from the current subreddit.
    These threads are candidates for replies.
    """
    subreddit = state["current_subreddit"]
    logger.info(f"Fetching hot threads from r/{subreddit}")
    
    try:
        reddit_client = await get_reddit_client_for_account(
            company_id=state["company_id"],
            account_id=state["reddit_account_id"]
        )
        
        threads = await reddit_client.get_hot_threads(
            subreddit_name=subreddit,
            limit=25
        )
        
        await reddit_client.close()
        
        if not threads:
            state["error"] = f"No threads found in r/{subreddit}"
            state["error_node"] = "fetch_threads"
            return state
        
        state["threads_found"] = threads
        
        logger.info(f"Found {len(threads)} threads in r/{subreddit}")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to fetch threads: {str(e)}")
        state["error"] = f"Failed to fetch threads: {str(e)}"
        state["error_node"] = "fetch_threads"
        return state

