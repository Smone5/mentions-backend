"""
Keyword management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.auth import get_current_user
from core.database import get_supabase_client
from supabase import Client
from models.user import UserProfile
import logging
from typing import Optional

router = APIRouter(prefix="/keywords", tags=["keywords"])
logger = logging.getLogger(__name__)


class KeywordCreate(BaseModel):
    """Keyword creation model."""
    keyword: str
    priority: Optional[str] = "normal"  # low, normal, high


class KeywordUpdate(BaseModel):
    """Keyword update model."""
    is_active: Optional[bool] = None
    priority: Optional[str] = None


@router.get("")
async def list_keywords(
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """List keywords for company."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    response = supabase.table("keywords").select("*").eq(
        "company_id", str(user.company_id)
    ).order("created_at", desc=True).execute()
    
    return {"keywords": response.data or []}


@router.post("")
async def create_keyword(
    keyword_data: KeywordCreate,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Create a new keyword."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Validate priority
    if keyword_data.priority not in ["low", "normal", "high"]:
        raise HTTPException(status_code=400, detail="Invalid priority")
    
    normalized_keyword = keyword_data.keyword.strip().lower()

    if not normalized_keyword:
        raise HTTPException(status_code=400, detail="Keyword cannot be empty")

    # Check for duplicate
    existing = supabase.table("keywords").select("id").eq(
        "company_id", str(user.company_id)
    ).eq("keyword", normalized_keyword).execute()
    
    if existing.data:
        raise HTTPException(status_code=400, detail="Keyword already exists")
    
    # Create keyword
    response = supabase.table("keywords").insert({
        "company_id": str(user.company_id),
        "keyword": normalized_keyword,
        "priority": keyword_data.priority,
        "is_active": True,
        "created_by": str(user.id)
    }).execute()
    
    logger.info("keyword_created", keyword=normalized_keyword, company_id=str(user.company_id))
    
    return {"success": True, "id": response.data[0]["id"]}


@router.put("/{keyword_id}")
async def update_keyword(
    keyword_id: str,
    update: KeywordUpdate,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Update keyword."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Verify keyword belongs to company
    keyword_response = supabase.table("keywords").select(
        "company_id"
    ).eq("id", keyword_id).single().execute()
    
    if not keyword_response.data:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    if keyword_response.data["company_id"] != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Build update dict
    update_data = {}
    if update.is_active is not None:
        update_data["is_active"] = update.is_active
    if update.priority is not None:
        if update.priority not in ["low", "normal", "high"]:
            raise HTTPException(status_code=400, detail="Invalid priority")
        update_data["priority"] = update.priority
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    supabase.table("keywords").update(update_data).eq("id", keyword_id).execute()
    
    logger.info("keyword_updated", keyword_id=keyword_id, company_id=str(user.company_id))
    
    return {"success": True}


@router.delete("/{keyword_id}")
async def delete_keyword(
    keyword_id: str,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Delete keyword."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Verify keyword belongs to company
    keyword_response = supabase.table("keywords").select(
        "company_id"
    ).eq("id", keyword_id).single().execute()
    
    if not keyword_response.data:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    if keyword_response.data["company_id"] != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    supabase.table("keywords").delete().eq("id", keyword_id).execute()
    
    logger.info("keyword_deleted", keyword_id=keyword_id, company_id=str(user.company_id))
    
    return {"success": True}


@router.post("/{keyword_id}/discover")
async def discover_keyword(
    keyword_id: str,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Manually trigger discovery for a keyword.
    This starts the LangGraph workflow to find Reddit threads and generate drafts.
    """
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get keyword
    keyword_response = supabase.table("keywords").select(
        "id, keyword, company_id"
    ).eq("id", keyword_id).single().execute()
    
    if not keyword_response.data:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    if keyword_response.data["company_id"] != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    keyword_text = keyword_response.data["keyword"]
    
    # Get company's active Reddit account
    reddit_account_response = supabase.table("reddit_connections").select(
        "id"
    ).eq("company_id", str(user.company_id)).eq("is_active", True).order(
        "created_at", desc=True
    ).limit(1).execute()
    
    if not reddit_account_response.data:
        raise HTTPException(
            status_code=400,
            detail="No active Reddit account found. Please connect a Reddit account first."
        )
    
    reddit_account_id = reddit_account_response.data[0]["id"]
    
    # Get company goal, description, and name
    company_response = supabase.table("companies").select(
        "name, goal, description"
    ).eq("id", str(user.company_id)).single().execute()
    
    company_name = company_response.data.get("name", "") if company_response.data else ""
    company_goal = company_response.data.get("goal", "") if company_response.data else ""
    company_description = company_response.data.get("description", "") if company_response.data else ""
    
    # Get company's default prompt (if exists)
    prompt_response = supabase.table("prompts").select(
        "body, name"
    ).eq("company_id", str(user.company_id)).eq("is_default", True).execute()
    
    custom_prompt = None
    if prompt_response.data and len(prompt_response.data) > 0:
        custom_prompt = prompt_response.data[0]["body"]
        logger.info(f"Using custom prompt: {prompt_response.data[0]['name']}")
    else:
        logger.info("No custom prompt found, using default prompt")
    
    # Start discovery workflow (import here to avoid circular imports)
    from api.generate import run_generation_workflow
    import asyncio
    
    # Run 3 parallel workflows to try different subreddits
    # Each workflow will:
    # 1. Fetch subreddits 
    # 2. Pick one (with diversification)
    # 3. LLM judge decides if it's appropriate
    # 4. If approved, generate draft
    # 5. If rejected, that workflow stops (others continue)
    
    num_workflows = 3
    for i in range(num_workflows):
        thread_id = f"{user.company_id}:{keyword_text}:{keyword_id[:8]}:run{i}"
        
        # Run each workflow in background
        asyncio.create_task(
            run_generation_workflow(
                keyword_id=keyword_id,
                company_id=str(user.company_id),
                user_id=str(user.id),
                keyword=keyword_text,
                reddit_account_id=reddit_account_id,
                company_name=company_name,
                company_goal=company_goal,
                company_description=company_description,
                custom_prompt=custom_prompt
            )
        )
    
    # Update keyword discovery timestamp
    supabase.table("keywords").update({
        "last_discovered_at": "now()"
    }).eq("id", keyword_id).execute()
    
    logger.info(f"manual_discovery_triggered: keyword={keyword_text}, keyword_id={keyword_id}, user_id={str(user.id)}")
    
    return {
        "success": True,
        "message": f"Discovery started for keyword: {keyword_text}",
        "thread_id": thread_id,
        "keyword": keyword_text
    }

