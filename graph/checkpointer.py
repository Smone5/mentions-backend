"""PostgreSQL checkpointer for LangGraph state persistence."""

import logging
from typing import Optional
from langgraph.checkpoint.postgres import PostgresSaver

from core.database import get_db_connection_string

logger = logging.getLogger(__name__)


_checkpointer: Optional[PostgresSaver] = None


def get_checkpointer() -> PostgresSaver:
    """
    Get or create PostgreSQL checkpointer for LangGraph.
    
    This allows LangGraph workflows to persist state and resume after interruptions.
    State is stored in the langgraph_checkpoints and langgraph_checkpoint_writes tables.
    
    Returns:
        PostgresSaver instance
    """
    global _checkpointer
    
    if _checkpointer is None:
        conn_string = get_db_connection_string()
        _checkpointer = PostgresSaver.from_conn_string(conn_string)
        logger.info("LangGraph checkpointer initialized with PostgreSQL")
    
    return _checkpointer

