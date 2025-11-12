"""LangGraph workflow builder."""

import logging
from langgraph.graph import StateGraph, END

from graph.state import GenerateState
from graph.nodes import (
    fetch_subreddits_node,
    judge_subreddit_node,
    fetch_rules_node,
    fetch_threads_node,
    rank_threads_node,
    rag_retrieve_node,
    draft_compose_node,
    vary_draft_node,
    judge_draft_node,
    emit_ready_node,
)

logger = logging.getLogger(__name__)


def should_continue(state: GenerateState) -> str:
    """
    Routing function to determine if pipeline should continue or end.
    
    If there's an error, route to END.
    Otherwise, continue to next node.
    """
    if state.get("error"):
        return "end"
    return "continue"


def should_retry_draft(state: GenerateState) -> str:
    """
    Routing function after judge_draft to determine if we should retry.
    
    If there's an error, END (max attempts exceeded).
    If draft is rejected and draft retries remain, RETRY_DRAFT (back to draft_compose).
    If draft is rejected, draft retries exhausted, but thread attempts remain, RETRY_THREAD (back to rank_threads for next thread).
    If draft is approved, CONTINUE (to emit_ready).
    """
    if state.get("error"):
        # Max attempts exceeded or other error - END
        return "end"
    
    if not state.get("draft_approved", False):
        # Draft rejected - determine if we retry draft or try new thread
        retry_count = state.get("draft_retry_count", 0)
        
        # If draft_retry_count was just incremented, we're retrying the draft
        if retry_count > 0 and state.get("draft_feedback"):
            return "retry_draft"
        else:
            # draft_retry_count was reset, so we're trying a new thread
            return "retry_thread"
    
    # Draft approved - CONTINUE
    return "continue"


def build_generate_graph():
    """
    Build the draft generation LangGraph workflow with intelligent retry logic.
    
    Flow:
    1. Fetch Subreddits
    2. Judge Subreddit (GATE) -> END if rejected
    3. Fetch Rules
    4. Fetch Threads
    5. Rank Threads (prioritizes recent, skips already-attempted threads on retry)
    6. RAG Retrieve
    7. Draft Compose (incorporates feedback from previous rejection on retry)
    8. Vary Draft
    9. Judge Draft (GATE with retry) -> Three strategies:
       a. If draft rejected and retries remain (< 3): Loop to Draft Compose with feedback
       b. If draft retries exhausted and threads remain (< 3): Loop to Rank Threads for next thread
       c. If all attempts exhausted: END with error
    10. Emit Ready (save to database)
    
    This creates up to 9 total attempts: 3 threads × 3 draft attempts per thread.
    
    Returns:
        Uncompiled StateGraph workflow (to be compiled with checkpointer)
    """
    logger.info("Building generation graph")
    
    # Create graph
    workflow = StateGraph(GenerateState)
    
    # Add nodes
    workflow.add_node("fetch_subreddits", fetch_subreddits_node)
    workflow.add_node("judge_subreddit", judge_subreddit_node)
    workflow.add_node("fetch_rules", fetch_rules_node)
    workflow.add_node("fetch_threads", fetch_threads_node)
    workflow.add_node("rank_threads", rank_threads_node)
    workflow.add_node("rag_retrieve", rag_retrieve_node)
    workflow.add_node("draft_compose", draft_compose_node)
    workflow.add_node("vary_draft", vary_draft_node)
    workflow.add_node("judge_draft", judge_draft_node)
    workflow.add_node("emit_ready", emit_ready_node)
    
    # Set entry point
    workflow.set_entry_point("fetch_subreddits")
    
    # Add edges with conditional routing
    
    # fetch_subreddits -> judge_subreddit or END
    workflow.add_conditional_edges(
        "fetch_subreddits",
        should_continue,
        {
            "continue": "judge_subreddit",
            "end": END
        }
    )
    
    # judge_subreddit -> fetch_rules or END (GATE)
    workflow.add_conditional_edges(
        "judge_subreddit",
        should_continue,
        {
            "continue": "fetch_rules",
            "end": END
        }
    )
    
    # fetch_rules -> fetch_threads
    workflow.add_edge("fetch_rules", "fetch_threads")
    
    # fetch_threads -> rank_threads or END
    workflow.add_conditional_edges(
        "fetch_threads",
        should_continue,
        {
            "continue": "rank_threads",
            "end": END
        }
    )
    
    # rank_threads -> rag_retrieve or END
    workflow.add_conditional_edges(
        "rank_threads",
        should_continue,
        {
            "continue": "rag_retrieve",
            "end": END
        }
    )
    
    # rag_retrieve -> draft_compose (RAG errors don't stop pipeline)
    workflow.add_edge("rag_retrieve", "draft_compose")
    
    # draft_compose -> vary_draft or END
    workflow.add_conditional_edges(
        "draft_compose",
        should_continue,
        {
            "continue": "vary_draft",
            "end": END
        }
    )
    
    # vary_draft -> judge_draft (variation errors don't stop pipeline)
    workflow.add_edge("vary_draft", "judge_draft")
    
    # judge_draft -> emit_ready, draft_compose (retry draft), rank_threads (try new thread), or END (GATE with retry)
    workflow.add_conditional_edges(
        "judge_draft",
        should_retry_draft,
        {
            "continue": "emit_ready",
            "retry_draft": "draft_compose",  # Loop back to re-compose with feedback
            "retry_thread": "rank_threads",  # Try next thread
            "end": END
        }
    )
    
    # emit_ready -> END
    workflow.add_edge("emit_ready", END)
    
    logger.info("Generation graph built successfully")
    
    # Return the uncompiled workflow so it can be compiled with checkpointer later
    return workflow


# Global graph instance
_graph = None


def get_generate_graph():
    """Get or create the global generation graph instance."""
    global _graph
    
    if _graph is None:
        _graph = build_generate_graph()
        logger.info("Generation graph initialized")
    
    return _graph

