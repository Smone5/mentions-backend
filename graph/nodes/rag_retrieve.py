"""Node to retrieve relevant RAG context."""

import logging
from graph.state import GenerateState
from rag.store import get_rag_store

logger = logging.getLogger(__name__)


async def rag_retrieve_node(state: GenerateState) -> GenerateState:
    """
    Retrieve relevant context from company's RAG documents.
    This context will be used to inform the draft composition.
    """
    logger.info(f"Retrieving RAG context for thread: {state['thread_title']}")
    
    try:
        rag_store = get_rag_store()
        
        # Build query from thread title and keyword
        query = f"{state['keyword']} {state['thread_title']}"
        
        # Retrieve relevant chunks
        chunks = await rag_store.retrieve(
            company_id=state["company_id"],
            query=query,
            top_k=3
        )
        
        if chunks:
            # Combine chunks into context
            context_parts = []
            for chunk in chunks:
                context_parts.append(f"From {chunk['title']}:\n{chunk['content']}")
            
            state["rag_context"] = "\n\n".join(context_parts)
            
            logger.info(f"Retrieved {len(chunks)} relevant chunks")
        else:
            state["rag_context"] = None
            logger.info("No relevant RAG context found")
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to retrieve RAG context: {str(e)}")
        # Don't fail the pipeline if RAG retrieval fails
        state["rag_context"] = None
        return state

