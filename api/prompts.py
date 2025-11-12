"""Prompt management API endpoints."""

import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from uuid import UUID, uuid4
from jinja2 import Template, TemplateError

from models.prompt import Prompt, PromptCreate, PromptUpdate, PromptRenderRequest
from pydantic import BaseModel, Field
from typing import Optional
from models.user import UserProfile
from core.database import get_supabase_client
from core.auth import get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])


# Database-aligned models (since DB schema differs from models/prompt.py)
class PromptCreateDB(BaseModel):
    """Model for creating a prompt matching DB schema."""
    name: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    model: Optional[str] = Field(default='gpt-4')
    temperature: Optional[float] = Field(default=0.6, ge=0, le=2)
    is_default: Optional[bool] = Field(default=False)


class PromptUpdateDB(BaseModel):
    """Model for updating a prompt matching DB schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    body: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0, le=2)
    is_default: Optional[bool] = None


@router.post("")
async def create_prompt(
    prompt_data: PromptCreateDB,
    current_user: UserProfile = Depends(require_role(["owner", "admin"]))
):
    """
    Create a new prompt template.
    Only owners and admins can create prompts.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    try:
        # If this is marked as default, unset other defaults
        if prompt_data.is_default:
            supabase.table("prompts").update({"is_default": False}).eq(
                "company_id", str(current_user.company_id)
            ).execute()
        
        prompt_id = str(uuid4())
        prompt_insert = {
            "id": prompt_id,
            "company_id": str(current_user.company_id),
            "name": prompt_data.name,
            "body": prompt_data.body,
            "model": prompt_data.model,
            "temperature": prompt_data.temperature,
            "is_default": prompt_data.is_default,
            "created_by": str(current_user.id),
        }
        
        result = supabase.table("prompts").insert(prompt_insert).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create prompt"
            )
        
        logger.info(f"Prompt created: {prompt_id} by user {current_user.id}")
        
        return result.data[0]
        
    except Exception as e:
        logger.error(f"Failed to create prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create prompt: {str(e)}"
        )


@router.get("")
async def list_prompts(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    List all prompts for the user's company.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("prompts").select("*").eq(
        "company_id", str(current_user.company_id)
    ).order("created_at", desc=True).execute()
    
    return {"prompts": result.data or []}


@router.get("/{prompt_id}", response_model=Prompt)
async def get_prompt(
    prompt_id: UUID,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get a specific prompt by ID.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("prompts").select("*").eq("id", str(prompt_id)).eq(
        "company_id", str(current_user.company_id)
    ).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt not found"
        )
    
    return Prompt(**result.data)


@router.put("/{prompt_id}")
async def update_prompt(
    prompt_id: UUID,
    prompt_update: PromptUpdateDB,
    current_user: UserProfile = Depends(require_role(["owner", "admin"]))
):
    """
    Update a prompt template.
    Only owners and admins can update prompts.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    # Build update dictionary
    update_data = prompt_update.model_dump(exclude_none=True)
    
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )
    
    # If setting as default, unset other defaults first
    if update_data.get('is_default'):
        supabase.table("prompts").update({"is_default": False}).eq(
            "company_id", str(current_user.company_id)
        ).execute()
    
    result = supabase.table("prompts").update(update_data).eq("id", str(prompt_id)).eq(
        "company_id", str(current_user.company_id)
    ).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt not found"
        )
    
    logger.info(f"Prompt updated: {prompt_id} by user {current_user.id}")
    
    return result.data[0]


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: UUID,
    current_user: UserProfile = Depends(require_role(["owner", "admin"]))
):
    """
    Delete a prompt template.
    Only owners and admins can delete prompts.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    result = supabase.table("prompts").delete().eq("id", str(prompt_id)).eq(
        "company_id", str(current_user.company_id)
    ).execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt not found"
        )
    
    logger.info(f"Prompt deleted: {prompt_id} by user {current_user.id}")
    
    return {
        "success": True,
        "message": "Prompt deleted successfully"
    }


@router.post("/render")
async def render_prompt(
    render_req: PromptRenderRequest,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Render a prompt template with variables.
    
    Useful for testing prompt templates before saving.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    supabase = get_supabase_client()
    
    # Get prompt
    result = supabase.table("prompts").select("template").eq("id", str(render_req.prompt_id)).eq(
        "company_id", str(current_user.company_id)
    ).single().execute()
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt not found"
        )
    
    template_str = result.data["template"]
    
    # Render template
    try:
        template = Template(template_str)
        rendered = template.render(**render_req.variables)
        
        return {
            "success": True,
            "rendered": rendered
        }
        
    except TemplateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template rendering error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to render prompt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to render prompt"
        )


def render_template(template_str: str, variables: dict) -> str:
    """
    Utility function to render a Jinja2 template with variables.
    
    Args:
        template_str: Jinja2 template string
        variables: Dictionary of variables to render
        
    Returns:
        Rendered string
        
    Raises:
        Exception: If template rendering fails
    """
    try:
        template = Template(template_str)
        return template.render(**variables)
    except Exception as e:
        logger.error(f"Template rendering failed: {str(e)}")
        raise Exception(f"Template rendering failed: {str(e)}")

