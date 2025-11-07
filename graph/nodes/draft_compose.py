"""Node to compose a draft reply."""

import logging
from graph.state import GenerateState
from llm.client import get_llm_client

logger = logging.getLogger(__name__)


async def draft_compose_node(state: GenerateState) -> GenerateState:
    """
    Compose a draft reply to the selected thread.
    Uses company context, RAG context, and thread details.
    """
    logger.info(f"Composing draft for thread: {state['thread_title']}")
    
    try:
        llm_client = get_llm_client()
        
        # Build company context
        company_context = f"Goal: {state['company_goal']}"
        if state.get("company_description"):
            company_context += f"\nDescription: {state['company_description']}"
        
        # Compose draft
        draft = await llm_client.compose_draft(
            thread_title=state["thread_title"],
            thread_body=state["thread_body"],
            top_comments=state["top_comments"],
            subreddit_rules=state["subreddit_rules"],
            company_context=company_context,
            rag_context=state.get("rag_context"),
            keyword=state["keyword"]
        )
        
        state["draft_body"] = draft
        
        logger.info(f"Draft composed: {len(draft)} characters")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to compose draft: {str(e)}")
        state["error"] = f"Failed to compose draft: {str(e)}"
        state["error_node"] = "draft_compose"
        return state

