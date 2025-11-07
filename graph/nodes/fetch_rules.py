"""Node to fetch subreddit rules."""

import logging
from graph.state import GenerateState
from reddit.client import get_reddit_client_for_account

logger = logging.getLogger(__name__)


async def fetch_rules_node(state: GenerateState) -> GenerateState:
    """
    Fetch rules for the current subreddit.
    Rules are important for draft composition and judging.
    """
    subreddit = state["current_subreddit"]
    logger.info(f"Fetching rules for r/{subreddit}")
    
    try:
        reddit_client = await get_reddit_client_for_account(
            company_id=state["company_id"],
            account_id=state["reddit_account_id"]
        )
        
        rules = await reddit_client.get_subreddit_rules(subreddit)
        
        await reddit_client.close()
        
        state["subreddit_rules"] = rules
        
        logger.info(f"Fetched rules for r/{subreddit}: {len(rules)} chars")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to fetch rules: {str(e)}")
        # Don't fail the pipeline if rules can't be fetched
        state["subreddit_rules"] = "Could not fetch subreddit rules."
        return state

