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
        
        # First, get or create the thread record
        thread_id_db = None
        thread_reddit_id = state["thread_id"]
        
        # Check if we've already created an artifact for this thread
        # This prevents duplicate drafts when running multiple parallel workflows
        existing_artifact = supabase.table("artifacts").select("id").eq(
            "company_id", state["company_id"]
        ).eq("thread_reddit_id", thread_reddit_id).execute()
        
        if existing_artifact.data:
            logger.info(f"Artifact already exists for thread {thread_reddit_id}, skipping")
            state["skipped_duplicate"] = True
            return state
        
        # Check if thread exists
        thread_result = supabase.table("threads").select("id").eq(
            "company_id", state["company_id"]
        ).eq("reddit_id", thread_reddit_id).execute()
        
        if thread_result.data:
            thread_id_db = thread_result.data[0]["id"]
        else:
            # Create thread record
            thread_id_db = str(uuid4())
            thread_data = {
                "id": thread_id_db,
                "company_id": state["company_id"],
                "subreddit": state["current_subreddit"],
                "reddit_id": thread_reddit_id,
                "title": state["thread_title"],
                "body": state.get("thread_body"),
                "url": f"https://reddit.com/comments/{thread_reddit_id}",
                "created_utc": datetime.utcnow().isoformat(),
                "rank_score": state.get("thread_rank_score"),
            }
            supabase.table("threads").insert(thread_data).execute()
        
        # Create artifact record
        artifact_id = str(uuid4())
        
        # Prepare judge data
        judge_subreddit_data = None
        if state.get("subreddit_suitable") is not None:
            judge_subreddit_data = {
                "verdict": "approve" if state.get("subreddit_suitable") else "reject",
                "reason": state.get("subreddit_judge_reason"),
                "confidence": state.get("subreddit_confidence"),
            }
        
        judge_draft_data = None
        if state.get("draft_meets_quality") is not None:
            judge_draft_data = {
                "verdict": "approve" if state.get("draft_meets_quality") else "reject",
                "reason": state.get("draft_judge_reason"),
                "confidence": state.get("draft_confidence"),
                "risk_level": state.get("draft_risk_level"),
            }
        
        artifact_data = {
            "id": artifact_id,
            "company_id": state["company_id"],
            "reddit_account_id": state["reddit_account_id"],
            "thread_id": thread_id_db,
            "subreddit": state["current_subreddit"],
            "keyword": state["keyword"],
            "company_goal": state.get("company_goal"),
            "thread_reddit_id": thread_reddit_id,
            "thread_title": state["thread_title"],
            "thread_body": state.get("thread_body"),
            "thread_url": f"https://reddit.com/comments/{thread_reddit_id}",
            "rules_summary": state.get("subreddit_rules"),
            "draft_primary": state["draft_body"],
            "draft_variants": state.get("draft_variations", []),
            "rag_context": state.get("rag_contexts"),
            "judge_subreddit": judge_subreddit_data,
            "judge_draft": judge_draft_data,
            "status": "new",
        }
        
        artifact_result = supabase.table("artifacts").insert(artifact_data).execute()
        
        if not artifact_result.data:
            raise Exception("Failed to create artifact")
        
        state["artifact_id"] = artifact_id
        
        # Create draft record (for compatibility with drafts table)
        draft_id = str(uuid4())
        
        draft_data = {
            "id": draft_id,
            "artifact_id": artifact_id,
            "kind": "generated",
            "body": state["draft_body"],
            "risk": state.get("draft_risk_level", "medium"),
            "status": "pending",
        }
        
        draft_result = supabase.table("drafts").insert(draft_data).execute()
        
        if not draft_result.data:
            raise Exception("Failed to create draft")
        
        state["draft_id"] = draft_id
        
        # Save variations as separate drafts
        for i, variation in enumerate(state.get("draft_variations", [])):
            variation_id = str(uuid4())
            variation_data = {
                "id": variation_id,
                "artifact_id": artifact_id,
                "kind": "generated",
                "body": variation,
                "risk": state.get("draft_risk_level", "medium"),
                "source_draft_id": draft_id,  # Link to original draft
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

