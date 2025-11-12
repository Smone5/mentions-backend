"""Node to fetch relevant subreddits."""

import logging
import random
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
        
        # Randomly select a subreddit to diversify results across runs
        # This prevents always picking the same subreddit for the same keyword
        selected_subreddit = random.choice(subreddits)
        
        state["current_subreddit"] = selected_subreddit["name"]
        state["subreddit_description"] = selected_subreddit["description"]
        state["subreddit_subscribers"] = selected_subreddit["subscribers"]
        
        logger.info(
            f"Found {len(subreddits)} subreddits, randomly selected r/{selected_subreddit['name']} "
            f"(subscribers: {selected_subreddit['subscribers']})"
        )
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to fetch subreddits: {str(e)}")
        state["error"] = f"Failed to fetch subreddits: {str(e)}"
        state["error_node"] = "fetch_subreddits"
        return state

