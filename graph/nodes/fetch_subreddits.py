"""Node to fetch relevant subreddits."""

import logging
from graph.state import GenerateState
from reddit.client import get_reddit_client_for_account

logger = logging.getLogger(__name__)


async def fetch_subreddits_node(state: GenerateState) -> GenerateState:
    """
    Fetch relevant subreddits based on keyword.
    
    This is the first node in the generation pipeline.
    """
    logger.info(f"Fetching subreddits for keyword: {state['keyword']}")
    
    try:
        # Get Reddit client for the company/account
        reddit_client = await get_reddit_client_for_account(
            company_id=state["company_id"],
            account_id=state["reddit_account_id"]
        )
        
        # Search for subreddits
        subreddits = await reddit_client.search_subreddits(
            keyword=state["keyword"],
            limit=10
        )
        
        await reddit_client.close()
        
        if not subreddits:
            state["error"] = f"No subreddits found for keyword: {state['keyword']}"
            state["error_node"] = "fetch_subreddits"
            return state
        
        state["subreddits_found"] = subreddits
        
        # Set first subreddit as current
        state["current_subreddit"] = subreddits[0]["name"]
        state["subreddit_description"] = subreddits[0]["description"]
        state["subreddit_subscribers"] = subreddits[0]["subscribers"]
        
        logger.info(f"Found {len(subreddits)} subreddits, starting with r/{subreddits[0]['name']}")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to fetch subreddits: {str(e)}")
        state["error"] = f"Failed to fetch subreddits: {str(e)}"
        state["error_node"] = "fetch_subreddits"
        return state

