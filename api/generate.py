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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])


async def run_generation_workflow(
    company_id: str,
    user_id: str,
    keyword: str,
    reddit_account_id: str,
    company_goal: str,
    company_description: str
):
    """
    Run the generation workflow in the background.
    
    This is executed as a background task to avoid blocking the API response.
    """
    try:
        logger.info(f"Starting generation workflow for keyword: {keyword}")
        
        # Create initial state
        thread_id = f"{company_id}:{keyword}:{uuid4().hex[:8]}"
        
        initial_state: GenerateState = {
            "company_id": company_id,
            "user_id": user_id,
            "keyword": keyword,
            "reddit_account_id": reddit_account_id,
            "company_goal": company_goal,
            "company_description": company_description,
            "started_at": datetime.utcnow(),
            "iteration": 0,
        }
        
        # Get graph
        graph = get_generate_graph()
        
        # Execute workflow
        config = {"configurable": {"thread_id": thread_id}}
        final_state = await graph.ainvoke(initial_state, config=config)
        
        if final_state.get("error"):
            logger.error(
                f"Generation workflow failed at {final_state.get('error_node')}: "
                f"{final_state['error']}"
            )
        else:
            logger.info(
                f"Generation workflow completed successfully. "
                f"Artifact: {final_state.get('artifact_id')}, "
                f"Draft: {final_state.get('draft_id')}"
            )
        
    except Exception as e:
        logger.error(f"Generation workflow error: {str(e)}")


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
    company_result = supabase.table("companies").select("goal, description").eq(
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
        company_id=str(current_user.company_id),
        user_id=str(current_user.id),
        keyword=request.keyword,
        reddit_account_id=str(request.reddit_account_id),
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

