"""Node to judge if subreddit is appropriate (HARD GATE)."""

import logging
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def judge_subreddit_node(state: GenerateState) -> GenerateState:
    """
    Judge if the current subreddit is appropriate for the company's goal.
    
    This is a HARD GATE (Hard Rule #3) - rejection stops the pipeline.
    """
    subreddit = state["current_subreddit"]
    logger.info(f"Judging subreddit: r/{subreddit}")
    
    try:
        llm_client = get_llm_client()
        
        # Judge the subreddit
        result = await llm_client.judge_subreddit(
            subreddit=subreddit,
            keyword=state["keyword"],
            company_goal=state["company_goal"],
            subreddit_description=state.get("subreddit_description")
        )
        
        if result["verdict"] == "reject":
            # HARD STOP - subreddit rejected
            logger.warning(
                f"Subreddit r/{subreddit} rejected: {result['reason']} "
                f"(confidence: {result['confidence']})"
            )
            
            state["subreddit_approved"] = False
            state["subreddit_judge_reason"] = result["reason"]
            state["error"] = f"Subreddit rejected: {result['reason']}"
            state["error_node"] = "judge_subreddit"
            
            return state
        
        # Subreddit approved
        logger.info(
            f"Subreddit r/{subreddit} approved: {result['reason']} "
            f"(confidence: {result['confidence']})"
        )
        
        state["subreddit_approved"] = True
        state["subreddit_judge_reason"] = result["reason"]
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to judge subreddit: {str(e)}")
        state["error"] = f"Failed to judge subreddit: {str(e)}"
        state["error_node"] = "judge_subreddit"
        state["subreddit_approved"] = False
        return state

