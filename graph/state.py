"""LangGraph state definition for the generation workflow."""

from typing import TypedDict, Optional, List, Dict, Any
from datetime import datetime


class GenerateState(TypedDict, total=False):
    """
    State for the draft generation workflow.
    
    This state is passed through all nodes in the LangGraph pipeline.
    Each node can read from and write to this state.
    """
    
    # Input (set by caller)
    company_id: str
    user_id: str
    keyword: str
    reddit_account_id: str
    
    # Company context
    company_goal: str
    company_description: str
    
    # Subreddit discovery
    subreddits_found: List[Dict[str, Any]]
    current_subreddit: Optional[str]
    subreddit_description: Optional[str]
    subreddit_subscribers: Optional[int]
    
    # Judge results
    subreddit_approved: bool
    subreddit_judge_reason: Optional[str]
    
    # Subreddit rules
    subreddit_rules: Optional[str]
    
    # Thread discovery
    threads_found: List[Dict[str, Any]]
    current_thread: Optional[Dict[str, Any]]
    thread_id: Optional[str]
    thread_title: Optional[str]
    thread_body: Optional[str]
    top_comments: List[str]
    
    # Thread ranking
    ranked_threads: List[Dict[str, Any]]
    
    # RAG retrieval
    rag_context: Optional[str]
    
    # Draft composition
    draft_body: Optional[str]
    draft_variations: List[str]
    
    # Draft judgment
    draft_approved: bool
    draft_judge_reason: Optional[str]
    draft_risk_level: Optional[str]
    
    # Artifact creation
    artifact_id: Optional[str]
    draft_id: Optional[str]
    
    # Error handling
    error: Optional[str]
    error_node: Optional[str]
    
    # Metadata
    started_at: datetime
    completed_at: Optional[datetime]
    iteration: int

