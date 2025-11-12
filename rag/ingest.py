"""
Document ingestion and chunking for RAG.
"""
from langchain.text_splitter import RecursiveCharacterTextSplitter
from rag.embed import get_embedding
from core.database import get_supabase_client
from supabase import Client
import logging
import uuid

logger = logging.getLogger(__name__)


async def ingest_document(
    company_id: str,
    filename: str,
    content: str,
    file_type: str,
    supabase: Client | None = None
) -> str:
    """
    Ingest document and create embeddings.
    
    Args:
        company_id: Company ID
        filename: Original filename
        content: Document content (text)
        file_type: MIME type or file extension
        supabase: Optional Supabase client
        
    Returns:
        Document ID
    """
    if supabase is None:
        supabase = get_supabase_client()
    
    # Save document record
    doc_id = str(uuid.uuid4())
    
    supabase.table("rag_documents").insert({
        "id": doc_id,
        "company_id": company_id,
        "filename": filename,
        "file_type": file_type,
        "content": content,
    }).execute()
    
    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        length_function=len
    )
    chunks = splitter.split_text(content)
    
    # Generate embeddings and store
    for i, chunk_text in enumerate(chunks):
        # Get embedding from OpenAI
        embedding = await get_embedding(chunk_text)
        
        # Store in database (pgvector)
        chunk_id = str(uuid.uuid4())
        supabase.table("rag_chunks").insert({
            "id": chunk_id,
            "document_id": doc_id,
            "company_id": company_id,
            "chunk_index": i,
            "chunk_text": chunk_text,
            "embedding": str(embedding),  # pgvector will handle conversion
        }).execute()
    
    logger.info("document_ingested", doc_id=doc_id, chunks=len(chunks), filename=filename)
    return doc_id

