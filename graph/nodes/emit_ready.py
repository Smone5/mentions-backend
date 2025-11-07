"""Node to save approved draft to database."""

import logging
from uuid import uuid4
from datetime import datetime
from graph.state import GenerateState
from core.database import get_supabase_client

logger = logging.getLogger(__name__)


async def emit_ready_node(state: GenerateState) -> GenerateState:
    """
    Save the approved draft to the database as a ready artifact.
    This makes the draft available in the inbox for human review.
    """
    logger.info(f"Emitting ready artifact for thread: {state['thread_id']}")
    
    try:
        supabase = get_supabase_client()
        
        # Create artifact record
        artifact_id = str(uuid4())
        
        artifact_data = {
            "id": artifact_id,
            "company_id": state["company_id"],
            "keyword_id": None,  # TODO: Link to keyword if exists
            "reddit_account_id": state["reddit_account_id"],
            "subreddit": state["current_subreddit"],
            "thread_id": state["thread_id"],
            "thread_title": state["thread_title"],
            "thread_body": state["thread_body"][:1000],  # Truncate if too long
            "thread_url": f"https://reddit.com/comments/{state['thread_id']}",
            "context_data": {
                "top_comments": state["top_comments"],
                "subreddit_rules": state["subreddit_rules"],
                "rag_context": state.get("rag_context"),
            }
        }
        
        artifact_result = supabase.table("artifacts").insert(artifact_data).execute()
        
        if not artifact_result.data:
            raise Exception("Failed to create artifact")
        
        state["artifact_id"] = artifact_id
        
        # Create draft record
        draft_id = str(uuid4())
        
        draft_data = {
            "id": draft_id,
            "artifact_id": artifact_id,
            "version": 1,
            "body": state["draft_body"],
            "risk_level": state.get("draft_risk_level", "medium"),
            "judge_reason": state.get("draft_judge_reason"),
            "status": "pending",  # Awaiting human approval
        }
        
        draft_result = supabase.table("drafts").insert(draft_data).execute()
        
        if not draft_result.data:
            raise Exception("Failed to create draft")
        
        state["draft_id"] = draft_id
        
        # Save variations if any
        for i, variation in enumerate(state.get("draft_variations", [])):
            variation_id = str(uuid4())
            variation_data = {
                "id": variation_id,
                "artifact_id": artifact_id,
                "version": i + 2,  # Version 1 is the original draft
                "body": variation,
                "risk_level": state.get("draft_risk_level", "medium"),
                "status": "pending",
            }
            supabase.table("drafts").insert(variation_data).execute()
        
        state["completed_at"] = datetime.utcnow()
        
        logger.info(
            f"Artifact {artifact_id} and draft {draft_id} created successfully"
        )
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to emit ready artifact: {str(e)}")
        state["error"] = f"Failed to save draft: {str(e)}"
        state["error_node"] = "emit_ready"
        return state

