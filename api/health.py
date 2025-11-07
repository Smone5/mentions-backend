"""Health check endpoint."""

from fastapi import APIRouter
from core.config import settings

router = APIRouter()


@router.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "env": settings.ENV,
        "allow_posts": settings.ALLOW_POSTS,
    }

