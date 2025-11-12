"""Node to judge draft quality (HARD GATE with retry)."""

import logging
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)

# Maximum number of retry attempts per draft
MAX_DRAFT_RETRIES = 2
# Maximum number of threads to try
MAX_THREAD_ATTEMPTS = 3


async def judge_draft_node(state: GenerateState) -> GenerateState:
    """
    Judge if the draft is high quality and safe to post.
    
    This is a HARD GATE (Hard Rule #3) with retry logic.
    If rejected and retries remain, captures feedback for retry.
    Also enforces Hard Rule #2: No links in replies.
    """
    logger.info(f"Judging draft quality (attempt {state.get('draft_retry_count', 0) + 1})")
    
    try:
        llm_client = get_llm_client()
        
        # Judge the draft (including existing comments to check for repetition)
        result = await llm_client.judge_draft(
            draft_body=state["draft_body"],
            thread_title=state["thread_title"],
            thread_body=state["thread_body"],
            top_comments=state.get("top_comments", []),
            subreddit_rules=state.get("subreddit_rules")
        )
        
        if result["verdict"] == "reject":
            retry_count = state.get("draft_retry_count", 0)
            thread_attempt = state.get("thread_attempt_count", 0)
            
            logger.warning(
                f"Draft rejected (draft attempt {retry_count + 1}, thread attempt {thread_attempt + 1}): {result['reason']} "
                f"(confidence: {result['confidence']}, risk: {result['risk_level']})"
            )
            
            state["draft_approved"] = False
            state["draft_judge_reason"] = result["reason"]
            state["draft_risk_level"] = result["risk_level"]
            
            # Check if we can retry the same draft
            if retry_count < MAX_DRAFT_RETRIES:
                # Allow draft retry - capture feedback for next attempt
                state["draft_retry_count"] = retry_count + 1
                state["draft_feedback"] = result["reason"]
                logger.info(f"Will retry draft composition (attempt {retry_count + 2}/{MAX_DRAFT_RETRIES + 1})")
                # Don't set error - this signals draft retry
                return state
            
            # Draft retries exhausted - try a different thread
            if thread_attempt < MAX_THREAD_ATTEMPTS:
                # Try next thread
                logger.warning(f"Draft retries exhausted. Will try a different thread (thread attempt {thread_attempt + 2}/{MAX_THREAD_ATTEMPTS + 1})")
                
                # Mark current thread as attempted
                current_thread_id = state.get("thread_id")
                if current_thread_id:
                    attempted = state.get("attempted_thread_ids", [])
                    if current_thread_id not in attempted:
                        attempted.append(current_thread_id)
                        state["attempted_thread_ids"] = attempted
                
                # Reset draft retry counter for new thread
                state["draft_retry_count"] = 0
                state["draft_feedback"] = None
                state["thread_attempt_count"] = thread_attempt + 1
                
                # Signal to try next thread (no error set)
                return state
            else:
                # No more threads to try - HARD STOP
                logger.error(f"Failed after trying {MAX_THREAD_ATTEMPTS} threads with {MAX_DRAFT_RETRIES + 1} draft attempts each.")
                state["error"] = f"Failed after trying {MAX_THREAD_ATTEMPTS} threads. Last rejection: {result['reason']}"
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

