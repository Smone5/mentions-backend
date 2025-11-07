"""Node to judge draft quality (HARD GATE)."""

import logging
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def judge_draft_node(state: GenerateState) -> GenerateState:
    """
    Judge if the draft is high quality and safe to post.
    
    This is a HARD GATE (Hard Rule #3) - rejection stops the pipeline.
    Also enforces Hard Rule #2: No links in replies.
    """
    logger.info(f"Judging draft quality")
    
    try:
        llm_client = get_llm_client()
        
        # Judge the draft
        result = await llm_client.judge_draft(
            draft_body=state["draft_body"],
            thread_title=state["thread_title"],
            thread_body=state["thread_body"],
            subreddit_rules=state.get("subreddit_rules")
        )
        
        if result["verdict"] == "reject":
            # HARD STOP - draft rejected
            logger.warning(
                f"Draft rejected: {result['reason']} "
                f"(confidence: {result['confidence']}, risk: {result['risk_level']})"
            )
            
            state["draft_approved"] = False
            state["draft_judge_reason"] = result["reason"]
            state["draft_risk_level"] = result["risk_level"]
            state["error"] = f"Draft rejected: {result['reason']}"
            state["error_node"] = "judge_draft"
            
            return state
        
        # Draft approved
        logger.info(
            f"Draft approved: {result['reason']} "
            f"(confidence: {result['confidence']}, risk: {result['risk_level']})"
        )
        
        state["draft_approved"] = True
        state["draft_judge_reason"] = result["reason"]
        state["draft_risk_level"] = result["risk_level"]
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to judge draft: {str(e)}")
        state["error"] = f"Failed to judge draft: {str(e)}"
        state["error_node"] = "judge_draft"
        state["draft_approved"] = False
        return state

