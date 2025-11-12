"""Node to compose a draft reply."""

import logging
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def draft_compose_node(state: GenerateState) -> GenerateState:
    """
    Compose a draft reply to the selected thread.
    Uses company context, RAG context, thread details, and image analysis.
    On retry, incorporates feedback from previous rejection.
    """
    retry_count = state.get("draft_retry_count", 0)
    is_retry = retry_count > 0
    
    if is_retry:
        logger.info(f"Re-composing draft (attempt {retry_count + 1}) with feedback: {state.get('draft_feedback')}")
    else:
        logger.info(f"Composing draft for thread: {state['thread_title']}")
    
    try:
        llm_client = get_llm_client()
        
        # Analyze image if present (only on first attempt, reuse on retries)
        image_analysis = state.get("thread_image_analysis")
        if state.get("thread_image_url") and not image_analysis:
            logger.info(f"Analyzing image: {state['thread_image_url']}")
            image_analysis = await llm_client.analyze_image(
                image_url=state["thread_image_url"],
                thread_title=state["thread_title"],
                thread_body=state["thread_body"]
            )
            state["thread_image_analysis"] = image_analysis
            logger.info(f"Image analysis: {image_analysis[:100]}...")
        
        # Build company context
        company_context = f"Company: {state['company_name']}\nGoal: {state['company_goal']}"
        if state.get("company_description"):
            company_context += f"\nDescription: {state['company_description']}"
        
        # Build feedback context for retries
        feedback_context = None
        if is_retry and state.get("draft_feedback"):
            feedback_context = f"""PREVIOUS ATTEMPT WAS REJECTED. Judge feedback:
{state['draft_feedback']}

Please address this feedback and write a better draft that will be approved."""
        
        # Compose draft
        draft = await llm_client.compose_draft(
            thread_title=state["thread_title"],
            thread_body=state["thread_body"],
            top_comments=state["top_comments"],
            subreddit_rules=state["subreddit_rules"],
            company_context=company_context,
            rag_context=state.get("rag_context"),
            keyword=state["keyword"],
            custom_prompt=state.get("custom_prompt"),
            feedback_context=feedback_context,
            image_analysis=image_analysis
        )
        
        state["draft_body"] = draft
        
        logger.info(f"Draft composed: {len(draft)} characters")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to compose draft: {str(e)}")
        state["error"] = f"Failed to compose draft: {str(e)}"
        state["error_node"] = "draft_compose"
        return state

