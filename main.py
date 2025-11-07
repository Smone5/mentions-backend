"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from core.logging import setup_logging
from api import health, users, companies, reddit, rag

# Setup logging first
setup_logging()

# Create FastAPI app
app = FastAPI(
    title="Mentions API",
    description="AI-powered Reddit reply assistant",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(users.router)
app.include_router(companies.router)
app.include_router(reddit.router)
app.include_router(rag.router)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Mentions API",
        "version": "1.0.0",
        "docs": "/docs",
    }

