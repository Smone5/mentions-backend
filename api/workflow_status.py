"""Real-time workflow status streaming API."""

import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

from core.auth import get_current_user
from core.database import get_supabase_client
from models.user import UserProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow", tags=["workflow"])


# In-memory storage for workflow status updates
# In production, use Redis or similar
_workflow_updates = {}


def update_workflow_status(keyword_id: str, status: str, details: str = ""):
    """
    Update the workflow status for a keyword.
    Called from the workflow nodes to broadcast progress.
    """
    _workflow_updates[keyword_id] = {
        "status": status,
        "details": details,
        "timestamp": datetime.utcnow().isoformat()
    }
    logger.info(f"Workflow status updated for {keyword_id}: {status} - {details}")


async def generate_status_stream(keyword_id: str, company_id: str) -> AsyncGenerator[str, None]:
    """
    Generate Server-Sent Events for workflow status updates.
    """
    try:
        # Send initial connection message
        yield f"data: {json.dumps({'status': 'connected', 'keyword_id': keyword_id})}\n\n"
        
        last_status = None
        timeout_count = 0
        max_timeout = 300  # 5 minutes total timeout
        
        while timeout_count < max_timeout:
            # Check for updates
            if keyword_id in _workflow_updates:
                current_status = _workflow_updates[keyword_id]
                
                # Only send if status changed
                if current_status != last_status:
                    yield f"data: {json.dumps(current_status)}\n\n"
                    last_status = current_status
                    
                    # If workflow completed or failed, end stream
                    if current_status["status"] in ["completed", "failed"]:
                        # Clean up
                        del _workflow_updates[keyword_id]
                        break
            
            # Wait before checking again
            await asyncio.sleep(1)
            timeout_count += 1
        
        # Send timeout message if we reached max
        if timeout_count >= max_timeout:
            yield f"data: {json.dumps({'status': 'timeout', 'details': 'Workflow status stream timed out'})}\n\n"
    
    except asyncio.CancelledError:
        logger.info(f"Status stream cancelled for keyword {keyword_id}")
        raise
    except Exception as e:
        logger.error(f"Error in status stream: {str(e)}", exc_info=True)
        yield f"data: {json.dumps({'status': 'error', 'details': str(e)})}\n\n"


@router.get("/status/{keyword_id}")
async def stream_workflow_status(
    keyword_id: str,
    token: str = None,  # EventSource can't send headers, so we accept token as query param
):
    """
    Stream real-time workflow status updates for a keyword.
    
    Returns Server-Sent Events (SSE) with status updates:
    - connected: Initial connection established
    - running: Workflow is executing (with step details)
    - completed: Workflow finished successfully
    - failed: Workflow encountered an error
    - timeout: Stream timed out
    
    Note: Since EventSource doesn't support custom headers, pass the auth token
    as a query parameter: /workflow/status/{keyword_id}?token=YOUR_TOKEN
    """
    # Manually authenticate using token from query param
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token required")
    
    try:
        # Verify token with Supabase
        supabase = get_supabase_client()
        user_result = supabase.auth.get_user(token)
        
        if not user_result or not user_result.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = user_result.user.id
        
        # Get user profile
        profile_result = supabase.table("user_profiles").select("*").eq(
            "id", user_id
        ).single().execute()
        
        if not profile_result.data:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        company_id = profile_result.data.get("company_id")
        
        if not company_id:
            raise HTTPException(status_code=400, detail="User must belong to a company")
        
        # Verify keyword belongs to user's company
        keyword_result = supabase.table("keywords").select("id").eq(
            "id", keyword_id
        ).eq("company_id", str(company_id)).single().execute()
        
        if not keyword_result.data:
            raise HTTPException(status_code=404, detail="Keyword not found")
        
        logger.info(f"Starting workflow status stream for keyword {keyword_id}")
        
        return StreamingResponse(
            generate_status_stream(keyword_id, str(company_id)),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed")


@router.get("/status/{keyword_id}/current")
async def get_current_status(
    keyword_id: str,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Get the current workflow status for a keyword (non-streaming).
    """
    if not current_user.company_id:
        raise HTTPException(status_code=400, detail="User must belong to a company")
    
    # Verify keyword belongs to user's company
    supabase = get_supabase_client()
    result = supabase.table("keywords").select("id").eq(
        "id", keyword_id
    ).eq("company_id", str(current_user.company_id)).single().execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Keyword not found")
    
    # Return current status if available
    if keyword_id in _workflow_updates:
        return _workflow_updates[keyword_id]
    else:
        return {"status": "idle", "details": "No workflow running", "timestamp": None}

