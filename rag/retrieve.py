"""
Semantic search and retrieval for RAG.
"""
from rag.embed import get_embedding
from core.database import get_supabase_client
from supabase import Client
import logging

logger = logging.getLogger(__name__)


async def semantic_search(
    company_id: str,
    query: str,
    limit: int = 5,
    supabase: Client | None = None
) -> list[dict]:
    """
    Search for relevant chunks using vector similarity.
    
    Args:
        company_id: Company ID
        query: Search query text
        limit: Maximum number of results
        
    Returns:
        List of relevant chunks with similarity scores
    """
    if supabase is None:
        supabase = get_supabase_client()
    
    # Get query embedding
    query_embedding = await get_embedding(query)
    
    # Vector similarity search using pgvector
    # Note: Supabase client may need raw SQL for pgvector operations
    # For now, we'll use a simplified approach
    
    # Fetch all chunks for company (in production, use proper vector search)
    response = supabase.table("rag_chunks").select(
        "id, chunk_text, chunk_index, document_id, rag_documents!inner(filename)"
    ).eq("company_id", company_id).limit(limit * 3).execute()
    
    # TODO: Implement proper cosine similarity search with pgvector
    # This requires raw SQL: SELECT ... ORDER BY embedding <=> $1::vector LIMIT $2
    
    # For now, return first N chunks (will be improved with proper vector search)
    chunks = response.data[:limit] if response.data else []
    
    logger.info("semantic_search", query_length=len(query), results=len(chunks))
    
    return [
        {
            "id": c["id"],
            "chunk_text": c["chunk_text"],
            "filename": c.get("rag_documents", {}).get("filename", "unknown"),
            "similarity": 0.8  # Placeholder
        }
        for c in chunks
    ]

