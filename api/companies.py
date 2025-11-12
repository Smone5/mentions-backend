"""Company management API endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Depends, status
from typing import List
from uuid import UUID, uuid4

from models.company import Company, CompanyCreate, CompanyUpdate, CompanyMember
from models.user import UserProfile
from core.database import get_supabase_client
from core.auth import get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=Company, status_code=status.HTTP_201_CREATED)
async def create_company(
    company_data: CompanyCreate,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Create a new company.
    The current user becomes the owner.
    """
    supabase = get_supabase_client()
    
    # Check if user already has a company
    if current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already belongs to a company"
        )
    
    try:
        # Create company
        company_id = str(uuid4())
        company_insert = {
            "id": company_id,
            "name": company_data.name,
            "goal": company_data.goal,
            "description": company_data.description,
            "owner_id": str(current_user.id),
        }
        
        company_result = supabase.table("companies").insert(company_insert).execute()
        
        if not company_result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create company"
            )
        
        # Update user's company_id and role
        user_update = {
            "company_id": company_id,
            "role": "owner"
        }
        
        supabase.table("user_profiles").update(user_update).eq("id", str(current_user.id)).execute()
        
        logger.info(f"Company created: {company_id} by user {current_user.id}")
        
        return Company(**company_result.data[0])
        
    except Exception as e:
        logger.error(f"Failed to create company: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create company"
        )


@router.get("/{company_id}", response_model=Company)
async def get_company(
    company_id: UUID,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get company details.
    User must belong to the company to view it.
    """
    # Verify user has access to this company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("companies").select("*").eq("id", str(company_id)).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    return Company(**result.data)


@router.get("/me/company", response_model=Company)
async def get_my_company(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get the current user's company.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with any company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("companies").select("*").eq("id", str(current_user.company_id)).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    return Company(**result.data)


@router.put("/{company_id}", response_model=Company)
async def update_company(
    company_id: UUID,
    company_update: CompanyUpdate,
    current_user: UserProfile = Depends(require_role(["owner", "admin"]))
):
    """
    Update company details.
    Only owners and admins can update company information.
    """
    # Verify user has access to this company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this company"
        )
    
    supabase = get_supabase_client()
    
    # Build update dictionary, excluding None values
    update_data = company_update.model_dump(exclude_none=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    result = supabase.table("companies").update(update_data).eq("id", str(company_id)).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    logger.info(f"Company updated: {company_id} by user {current_user.id}")
    
    return Company(**result.data[0])


@router.delete("/{company_id}")
async def delete_company(
    company_id: UUID,
    current_user: UserProfile = Depends(require_role(["owner"]))
):
    """
    Delete a company.
    Only the owner can delete the company.
    This will cascade delete all related data.
    """
    # Verify user has access to this company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this company"
        )
    
    supabase = get_supabase_client()
    
    # Delete company (will cascade to related data via FK)
    result = supabase.table("companies").delete().eq("id", str(company_id)).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company not found"
        )
    
    logger.info(f"Company deleted: {company_id} by user {current_user.id}")
    
    return {
        "success": True,
        "message": "Company deleted successfully"
    }


@router.get("/{company_id}/members", response_model=List[CompanyMember])
async def get_company_members(
    company_id: UUID,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get all members of a company.
    User must belong to the company to view members.
    """
    # Verify user has access to this company
    if current_user.company_id != company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this company"
        )
    
    supabase = get_supabase_client()
    
    # Get all users in this company
    result = supabase.table("user_profiles").select(
        "id, email, full_name, role, company_id, created_at"
    ).eq("company_id", str(company_id)).execute()
    
    if not result.data:
        return []
    
    members = [
        CompanyMember(
            user_id=UUID(member["id"]),
            company_id=company_id,
            role=member.get("role", "member"),
            email=member["email"],
            full_name=member.get("full_name"),
            joined_at=member["created_at"]
        )
        for member in result.data
    ]
    
    return members

