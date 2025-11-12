"""Draft generation API endpoints."""

import logging
from datetime import datetime
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends, status, BackgroundTasks
from typing import List

from models.generation import GenerateRequest, GenerateResponse, Artifact, Draft, DraftUpdate
from models.user import UserProfile
from core.database import get_supabase_client
from core.auth import get_current_user
from graph.build import get_generate_graph
from graph.state import GenerateState
from api.workflow_status import update_workflow_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])


async def run_generation_workflow(
    keyword_id: str,
    company_id: str,
    user_id: str,
    keyword: str,
    reddit_account_id: str,
    company_name: str,
    company_goal: str,
    company_description: str,
    custom_prompt: str = None
):
    """
    Run the generation workflow in the background.
    
    This is executed as a background task to avoid blocking the API response.
    """
    try:
        update_workflow_status(keyword_id, "starting", f"Starting discovery workflow for '{keyword}'")
        
        logger.info(f"🚀 STARTING generation workflow for keyword: '{keyword}'")
        logger.info(f"   Keyword ID: {keyword_id}")
        logger.info(f"   Company ID: {company_id}")
        logger.info(f"   User ID: {user_id}")
        
        # Create initial state
        thread_id = f"{company_id}:{keyword}:{uuid4().hex[:8]}"
        logger.info(f"   Thread ID: {thread_id}")
        
        initial_state: GenerateState = {
            "company_id": company_id,
            "user_id": user_id,
            "keyword": keyword,
            "reddit_account_id": reddit_account_id,
            "company_name": company_name,
            "company_goal": company_goal,
            "company_description": company_description,
            "custom_prompt": custom_prompt,
            "started_at": datetime.utcnow(),
            "iteration": 0,
            "draft_retry_count": 0,  # Initialize retry counter
            "thread_attempt_count": 0,  # Initialize thread attempt counter
            "attempted_thread_ids": [],  # Track attempted threads
        }
        
        # Get graph
        update_workflow_status(keyword_id, "building", "Building LangGraph workflow...")
        logger.info("📊 Building LangGraph workflow...")
        graph = get_generate_graph()
        
        # Execute workflow with streaming to track progress
        update_workflow_status(keyword_id, "running", "Executing workflow...")
        logger.info("▶️  Executing workflow (this may take a few minutes)...")
        logger.info("=" * 60)
        
        config = {"configurable": {"thread_id": thread_id}}
        
        # Get checkpointer as context manager
        from graph.checkpointer import get_checkpointer
        checkpointer_cm = get_checkpointer()
        
        # Use checkpointer as async context manager
        async with checkpointer_cm as checkpointer:
            # Compile graph with checkpointer
            graph_with_checkpoint = graph.compile(checkpointer=checkpointer)
            
            # Stream through the workflow to show progress
            step_count = 0
            async for event in graph_with_checkpoint.astream(initial_state, config=config):
                step_count += 1
                # Event is a dict with node name as key
                for node_name, node_output in event.items():
                    logger.info(f"✓ Step {step_count}: {node_name}")
                    
                    # Update status for user
                    step_details = ""
                    
                    # Log specific details based on node
                    if node_name == "fetch_subreddits" and node_output.get("subreddits"):
                        step_details = f"Found {len(node_output['subreddits'])} subreddits"
                        logger.info(f"  └─ {step_details}")
                    elif node_name == "judge_subreddit":
                        is_suitable = node_output.get("subreddit_suitable", False)
                        step_details = f"Subreddit {'suitable' if is_suitable else 'not suitable'}"
                        logger.info(f"  └─ Subreddit {'✓ suitable' if is_suitable else '✗ not suitable'}")
                    elif node_name == "fetch_threads" and node_output.get("threads"):
                        step_details = f"Found {len(node_output['threads'])} threads"
                        logger.info(f"  └─ {step_details}")
                    elif node_name == "rank_threads" and node_output.get("ranked_thread_ids"):
                        step_details = f"Ranked {len(node_output['ranked_thread_ids'])} threads"
                        logger.info(f"  └─ {step_details}")
                    elif node_name == "rag_retrieve" and node_output.get("rag_contexts"):
                        step_details = f"Retrieved {len(node_output['rag_contexts'])} context chunks"
                        logger.info(f"  └─ {step_details}")
                    elif node_name == "draft_compose" and node_output.get("draft_body"):
                        step_details = f"Composed draft"
                        logger.info(f"  └─ Composed draft ({len(node_output['draft_body'])} chars)")
                    elif node_name == "vary_draft" and node_output.get("variation_count"):
                        step_details = f"Created {node_output['variation_count']} variations"
                        logger.info(f"  └─ {step_details}")
                    elif node_name == "judge_draft":
                        is_quality = node_output.get("draft_meets_quality", False)
                        step_details = f"Draft quality {'approved' if is_quality else 'needs improvement'}"
                        logger.info(f"  └─ Draft quality {'✓ approved' if is_quality else '✗ needs improvement'}")
                    elif node_name == "emit_ready":
                        artifact_id = node_output.get("artifact_id")
                        draft_id = node_output.get("draft_id")
                        if artifact_id:
                            step_details = f"Saved artifact and draft"
                            logger.info(f"  └─ Saved artifact: {artifact_id}")
                        if draft_id:
                            logger.info(f"  └─ Saved draft: {draft_id}")
                    
                    # Send status update to frontend
                    update_workflow_status(keyword_id, "running", f"Step {step_count}: {node_name} - {step_details}")
            
            logger.info("=" * 60)
            
            # Get final state
            final_state = await graph_with_checkpoint.aget_state(config)
        
            if final_state.values.get("error"):
                error_msg = f"Failed at {final_state.values.get('error_node')}: {final_state.values['error']}"
                update_workflow_status(keyword_id, "failed", error_msg)
                logger.error(f"❌ Generation workflow FAILED at {final_state.values.get('error_node')}: {final_state.values['error']}")
            else:
                update_workflow_status(keyword_id, "completed", "Workflow completed successfully! Check drafts.")
                logger.info(f"✅ Generation workflow COMPLETED successfully!")
                if final_state.values.get("artifact_id"):
                    logger.info(f"   Artifact ID: {final_state.values['artifact_id']}")
                if final_state.values.get("draft_id"):
                    logger.info(f"   Draft ID: {final_state.values['draft_id']}")
        
    except Exception as e:
        update_workflow_status(keyword_id, "failed", f"Error: {str(e)}")
        logger.error(f"❌ Generation workflow ERROR: {str(e)}", exc_info=True)


@router.post("/run", response_model=GenerateResponse)
async def generate_drafts(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Start draft generation for a keyword.
    
    This endpoint starts the LangGraph workflow:
    1. Search for relevant subreddits
    2. Judge subreddit appropriateness (GATE)
    3. Fetch hot threads
    4. Rank threads by relevance
    5. Retrieve RAG context
    6. Compose draft reply
    7. Create variations
    8. Judge draft quality (GATE)
    9. Save to database
    
    The workflow runs in the background.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    # Verify Reddit account belongs to company
    supabase = get_supabase_client()
    
    account_result = supabase.table("reddit_connections").select("id").eq(
        "id", str(request.reddit_account_id)
    ).eq("company_id", str(current_user.company_id)).single().execute()
    
    if not account_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reddit account not found or not authorized"
        )
    
    # Get company details
    company_result = supabase.table("companies").select("name, goal, description").eq(
        "id", str(current_user.company_id)
    ).single().execute()
    
    if not company_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    # Start workflow in background
    thread_id = f"{current_user.company_id}:{request.keyword}:{uuid4().hex[:8]}"
    
    background_tasks.add_task(
        run_generation_workflow,
        keyword_id=str(request.keyword_id),
        company_id=str(current_user.company_id),
        user_id=str(current_user.id),
        keyword=request.keyword,
        reddit_account_id=str(request.reddit_account_id),
        company_name=company_result.data.get("name", ""),
        company_goal=company_result.data.get("goal", ""),
        company_description=company_result.data.get("description", "")
    )
    
    logger.info(f"Generation workflow queued for keyword: {request.keyword}")
    
    return GenerateResponse(
        success=True,
        thread_id=thread_id,
        state={"status": "queued", "message": "Generation workflow started"}
    )


@router.get("/artifacts", response_model=List[Artifact])
async def list_artifacts(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    List all artifacts (thread + drafts) for the company.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("artifacts").select("*").eq(
        "company_id", str(current_user.company_id)
    ).order("created_at", desc=True).limit(50).execute()
    
    return [Artifact(**artifact) for artifact in result.data]


@router.get("/artifacts/{artifact_id}/drafts", response_model=List[Draft])
async def get_artifact_drafts(
    artifact_id: str,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get all draft versions for an artifact.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    # Verify artifact belongs to company
    artifact_result = supabase.table("artifacts").select("id").eq(
        "id", artifact_id
    ).eq("company_id", str(current_user.company_id)).single().execute()
    
    if not artifact_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found"
        )
    
    # Get all drafts
    drafts_result = supabase.table("drafts").select("*").eq(
        "artifact_id", artifact_id
    ).order("version").execute()
    
    return [Draft(**draft) for draft in drafts_result.data]


@router.put("/drafts/{draft_id}", response_model=Draft)
async def update_draft(
    draft_id: str,
    draft_update: DraftUpdate,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Update a draft (edit body or change status).
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    # Verify draft belongs to company (via artifact)
    draft_result = supabase.table("drafts").select(
        "*, artifacts!inner(company_id)"
    ).eq("id", draft_id).single().execute()
    
    if not draft_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found"
        )
    
    if draft_result.data["artifacts"]["company_id"] != str(current_user.company_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this draft"
        )
    
    # Build update data
    update_data = draft_update.model_dump(exclude_none=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    # If approving, set approved_by and approved_at
    if update_data.get("status") == "approved":
        update_data["approved_by"] = str(current_user.id)
        update_data["approved_at"] = datetime.utcnow().isoformat()
    
    result = supabase.table("drafts").update(update_data).eq("id", draft_id).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update draft"
        )
    
    logger.info(f"Draft {draft_id} updated by user {current_user.id}")
    
    return Draft(**result.data[0])

