"""
Draft management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from core.auth import get_current_user
from core.database import get_supabase_client
from supabase import Client
from models.user import UserProfile
import logging
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class UpdateDraftRequest(BaseModel):
    """Draft update request."""
    body: str


@router.get("")
async def list_drafts(
    user: UserProfile = Depends(get_current_user),
    status: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    subreddit: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
    supabase: Client = Depends(get_supabase_client)
):
    """List drafts with filtering and pagination."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Build query - only show primary drafts (exclude variations)
    query = supabase.table("drafts").select(
        "*, artifacts!inner(*), approvals(status, approved_by, approved_at)"
    ).eq("artifacts.company_id", str(user.company_id)).is_("source_draft_id", "null")
    
    # Filter by approval status if provided
    if status:
        if status == "pending":
            # No approval record = pending
            query = query.is_("approvals.status", "null")
        else:
            query = query.eq("approvals.status", status)
    
    if risk:
        query = query.eq("risk", risk)
    if keyword:
        query = query.eq("artifacts.keyword", keyword)
    if subreddit:
        query = query.eq("artifacts.subreddit", subreddit)
    
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    
    response = query.execute()
    
    # Add computed status field to each draft
    drafts = response.data or []
    for draft in drafts:
        approvals = draft.get("approvals", [])
        if approvals and len(approvals) > 0:
            draft["status"] = approvals[0].get("status", "pending")
        else:
            draft["status"] = "pending"
    
    # Get total count
    count_query = supabase.table("drafts").select("id, artifacts!inner(company_id)", count="exact").eq(
        "artifacts.company_id", str(user.company_id)
    ).is_("source_draft_id", "null")
    
    count_response = count_query.execute()
    total = count_response.count if hasattr(count_response, 'count') else len(drafts)
    
    return {
        "drafts": drafts,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/{draft_id}")
async def get_draft(
    draft_id: str,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Get single draft with full context, including variations."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get draft with artifact and approval status
    response = supabase.table("drafts").select(
        "*, artifacts!inner(*), approvals(status, approved_by, approved_at)"
    ).eq("id", draft_id).eq("artifacts.company_id", str(user.company_id)).single().execute()
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft = response.data
    
    # Add computed status field
    approvals = draft.get("approvals", [])
    if approvals and len(approvals) > 0:
        draft["status"] = approvals[0].get("status", "pending")
    else:
        draft["status"] = "pending"
    
    # Fetch variations (other drafts with same artifact_id)
    if draft.get("artifact_id"):
        variations_response = supabase.table("drafts").select(
            "id, body, risk"
        ).eq("artifact_id", draft["artifact_id"]).eq("source_draft_id", draft_id).execute()
        
        draft["variations"] = variations_response.data or []
    
    return draft


@router.put("/{draft_id}")
async def update_draft(
    draft_id: str,
    request: UpdateDraftRequest,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Update draft text by creating a new edited draft.
    
    Per schema: drafts are immutable. Edits create new drafts with kind='edited'
    and source_draft_id pointing to the original.
    """
    logger.info(f"PUT /drafts/{draft_id} - User: {user.id}, Body length: {len(request.body)}")
    
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get original draft
    draft_response = supabase.table("drafts").select(
        "*, artifacts!inner(company_id), approvals(status)"
    ).eq("id", draft_id).single().execute()
    
    if not draft_response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft = draft_response.data
    artifact = draft.get("artifacts", {})
    
    if artifact.get("company_id") != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Check if draft is already approved - can't edit approved drafts
    approvals = draft.get("approvals", [])
    if approvals and any(a.get("status") in ["approved", "posted"] for a in approvals):
        raise HTTPException(status_code=400, detail="Cannot edit approved or posted draft")
    
    # CRITICAL: Validate no links (Rule 2)
    from services.link_validator import validate_no_links
    is_valid, reason = validate_no_links(request.body)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Draft contains links: {reason}")
    
    # Create new edited draft
    new_draft = supabase.table("drafts").insert({
        "artifact_id": draft["artifact_id"],
        "kind": "edited",
        "body": request.body,
        "source_draft_id": draft_id,
        "risk": draft.get("risk"),  # Preserve original risk assessment
        "created_by": str(user.id)
    }).execute()
    
    logger.info(f"draft_edited original_id={draft_id} new_id={new_draft.data[0]['id']} user_id={user.id}")
    
    return {"success": True, "new_draft_id": new_draft.data[0]["id"]}


@router.post("/{draft_id}/approve")
async def approve_draft(
    draft_id: str,
    background_tasks: BackgroundTasks,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Approve draft for posting to Reddit."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get draft
    draft_response = supabase.table("drafts").select(
        "*, artifacts!inner(*), approvals(status)"
    ).eq("id", draft_id).single().execute()
    
    if not draft_response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft = draft_response.data
    artifact = draft.get("artifacts", {})
    
    if artifact.get("company_id") != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Check if already approved
    approvals = draft.get("approvals", [])
    if approvals:
        raise HTTPException(status_code=400, detail="Draft is already approved")
    
    # Create approval record
    approval = supabase.table("approvals").insert({
        "artifact_id": draft["artifact_id"],
        "chosen_draft_id": draft_id,
        "approved_by": str(user.id),
        "status": "approved"
    }).execute()
    
    logger.info(f"draft_approved draft_id={draft_id} user_id={user.id}")
    
    return {"success": True, "status": "approved"}


@router.post("/{draft_id}/post")
async def post_draft(
    draft_id: str,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Post an approved draft to Reddit."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get draft with approval status
    draft_response = supabase.table("drafts").select(
        "*, artifacts!inner(company_id), approvals(status, id)"
    ).eq("id", draft_id).single().execute()
    
    if not draft_response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft = draft_response.data
    artifact = draft.get("artifacts", {})
    
    if artifact.get("company_id") != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Check if draft is approved
    approvals = draft.get("approvals", [])
    if not approvals or approvals[0].get("status") != "approved":
        raise HTTPException(
            status_code=400, 
            detail=f"Draft must be approved before posting"
        )
    
    # Post to Reddit (importing here to avoid circular dependency)
    from services.post import post_to_reddit
    from uuid import UUID
    
    try:
        result = await post_to_reddit(
            draft_id=UUID(draft_id),
            approved_by=user.id
        )
        
        # Update approval status to posted
        if approvals:
            supabase.table("approvals").update({
                "status": "posted"
            }).eq("id", approvals[0]["id"]).execute()
        
        logger.info(f"draft_posted draft_id={draft_id} user_id={user.id} post_id={result.get('post_id')}")
        
        return {"success": True, "status": "posted", "result": result}
        
    except Exception as e:
        logger.error(f"Failed to post to Reddit: {str(e)}")
        
        # Update approval status to failed
        if approvals:
            supabase.table("approvals").update({
                "status": "failed"
            }).eq("id", approvals[0]["id"]).execute()
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to post to Reddit: {str(e)}"
        )


@router.post("/{draft_id}/reject")
async def reject_draft(
    draft_id: str,
    reason: Optional[str] = None,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """
    Reject draft by deleting any approval records.
    
    Note: Rejections are implicit - no approval = rejected.
    """
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get draft
    draft_response = supabase.table("drafts").select(
        "*, artifacts!inner(company_id), approvals(id)"
    ).eq("id", draft_id).single().execute()
    
    if not draft_response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft = draft_response.data
    artifact = draft.get("artifacts", {})
    
    if artifact.get("company_id") != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Delete any approval records for this draft
    approvals = draft.get("approvals", [])
    if approvals:
        supabase.table("approvals").delete().eq("chosen_draft_id", draft_id).execute()
    
    logger.info(f"draft_rejected draft_id={draft_id} user_id={user.id} reason={reason}")
    
    return {"success": True}


@router.delete("/{draft_id}")
async def delete_draft(
    draft_id: str,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Delete a draft and its variations."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    # Get draft to verify ownership
    draft_response = supabase.table("drafts").select(
        "*, artifacts!inner(company_id)"
    ).eq("id", draft_id).single().execute()
    
    if not draft_response.data:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    draft = draft_response.data
    artifact = draft.get("artifacts", {})
    
    if artifact.get("company_id") != str(user.company_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Delete variations first (drafts that reference this draft as source)
    supabase.table("drafts").delete().eq("source_draft_id", draft_id).execute()
    
    # Delete approval records
    supabase.table("approvals").delete().eq("chosen_draft_id", draft_id).execute()
    
    # Delete the draft itself
    supabase.table("drafts").delete().eq("id", draft_id).execute()
    
    logger.info(f"draft_deleted draft_id={draft_id} user_id={user.id}")
    
    return {"success": True}


class BulkDeleteRequest(BaseModel):
    draft_ids: list[str]


@router.post("/bulk-delete")
async def bulk_delete_drafts(
    request: BulkDeleteRequest,
    user: UserProfile = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_client)
):
    """Delete multiple drafts at once."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User not associated with a company")
    
    draft_ids = request.draft_ids
    if not draft_ids:
        raise HTTPException(status_code=400, detail="No draft IDs provided")
    
    # Verify all drafts belong to user's company
    drafts_response = supabase.table("drafts").select(
        "id, artifacts!inner(company_id)"
    ).in_("id", draft_ids).execute()
    
    if not drafts_response.data:
        raise HTTPException(status_code=404, detail="No drafts found")
    
    # Check ownership
    for draft in drafts_response.data:
        if draft["artifacts"]["company_id"] != str(user.company_id):
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied for draft {draft['id']}"
            )
    
    # Recursively find all variations (including nested ones)
    all_draft_ids = set(draft_ids)
    to_check = list(draft_ids)
    
    while to_check:
        # Find all drafts that reference the current batch
        variations_response = supabase.table("drafts").select(
            "id"
        ).in_("source_draft_id", to_check).execute()
        
        # Get the IDs of variations
        variation_ids = [v["id"] for v in (variations_response.data or [])]
        
        # Filter to only new IDs we haven't seen yet
        new_ids = [vid for vid in variation_ids if vid not in all_draft_ids]
        
        if not new_ids:
            break
            
        # Add to our set and check their children next
        all_draft_ids.update(new_ids)
        to_check = new_ids
    
    # Convert back to list for the delete operations
    all_draft_ids_list = list(all_draft_ids)
    
    # Delete all approval records
    supabase.table("approvals").delete().in_("chosen_draft_id", all_draft_ids_list).execute()
    
    # Delete all drafts (including variations) in one operation
    # This works because we've collected all descendants
    supabase.table("drafts").delete().in_("id", all_draft_ids_list).execute()
    
    logger.info(f"drafts_bulk_deleted count={len(draft_ids)} total_with_variations={len(all_draft_ids_list)} user_id={user.id}")
    
    return {"success": True, "deleted_count": len(draft_ids), "total_deleted": len(all_draft_ids_list)}
