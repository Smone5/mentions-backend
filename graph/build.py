"""LangGraph workflow builder."""

import logging
from datetime import datetime
from langgraph.graph import StateGraph, END

from graph.state import GenerateState
from graph.checkpointer import get_checkpointer
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


def build_generate_graph():
    """
    Build the draft generation LangGraph workflow.
    
    Flow:
    1. Fetch Subreddits
    2. Judge Subreddit (GATE) -> END if rejected
    3. Fetch Rules
    4. Fetch Threads
    5. Rank Threads
    6. RAG Retrieve
    7. Draft Compose
    8. Vary Draft
    9. Judge Draft (GATE) -> END if rejected
    10. Emit Ready (save to database)
    
    Returns:
        Compiled LangGraph workflow
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
    
    # judge_draft -> emit_ready or END (GATE)
    workflow.add_conditional_edges(
        "judge_draft",
        should_continue,
        {
            "continue": "emit_ready",
            "end": END
        }
    )
    
    # emit_ready -> END
    workflow.add_edge("emit_ready", END)
    
    # Compile with checkpointer for state persistence
    checkpointer = get_checkpointer()
    compiled = workflow.compile(checkpointer=checkpointer)
    
    logger.info("Generation graph built successfully")
    
    return compiled


# Global graph instance
_graph = None


def get_generate_graph():
    """Get or create the global generation graph instance."""
    global _graph
    
    if _graph is None:
        _graph = build_generate_graph()
        logger.info("Generation graph initialized")
    
    return _graph

