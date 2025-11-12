"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from core.config import settings
from core.logging import setup_logging
from api import health, users, companies, reddit, rag, prompts, generate, posts, keywords, drafts, reddit_accounts, workflow_status
from graph.checkpointer import initialize_checkpointer, cleanup_checkpointer

# Setup logging first
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup: Initialize the LangGraph checkpointer
    await initialize_checkpointer()
    yield
    # Shutdown: cleanup checkpointer
    await cleanup_checkpointer()


# Create FastAPI app
app = FastAPI(
    title="Mentions API",
    description="AI-powered Reddit reply assistant",
    version="1.0.0",
    lifespan=lifespan,
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
app.include_router(prompts.router)
app.include_router(generate.router)
app.include_router(posts.router)
app.include_router(keywords.router)
app.include_router(drafts.router, prefix="/drafts", tags=["drafts"])
app.include_router(reddit_accounts.router, prefix="/reddit-accounts", tags=["reddit-accounts"])
app.include_router(workflow_status.router)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Mentions API",
        "version": "1.0.0",
        "docs": "/docs",
    }

