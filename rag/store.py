"""RAG document storage and retrieval using pgvector."""

import logging
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
import asyncpg

from core.database import get_db_connection_string
from core.config import settings
from rag.embeddings import get_embedding_client
from rag.chunking import chunk_document

logger = logging.getLogger(__name__)


class RAGStore:
    """Store and retrieve documents using pgvector."""
    
    def __init__(self):
        """Initialize RAG store."""
        self.embedding_client = get_embedding_client()
        self.conn_string = get_db_connection_string()
    
    async def ingest_document(
        self,
        company_id: UUID,
        title: str,
        content: str,
        source_url: Optional[str] = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> str:
        """
        Ingest a document into the RAG system.
        
        Steps:
        1. Chunk the document
        2. Generate embeddings for each chunk
        3. Store chunks and embeddings in database
        
        Args:
            company_id: Company UUID
            title: Document title
            content: Document content
            source_url: Optional source URL
            chunk_size: Size of each chunk
            chunk_overlap: Overlap between chunks
            
        Returns:
            Document ID
        """
        try:
            # Create document chunks
            metadata = {
                "title": title,
                "source_url": source_url,
            }
            
            chunks = chunk_document(content, metadata, chunk_size, chunk_overlap)
            
            if not chunks:
                raise ValueError("No chunks generated from document")
            
            # Generate embeddings for all chunks
            chunk_texts = [chunk["content"] for chunk in chunks]
            embeddings = self.embedding_client.generate_embeddings_batch(chunk_texts)
            
            # Store in database
            conn = await asyncpg.connect(self.conn_string)
            
            try:
                # Create document record
                doc_id = str(uuid4())
                
                await conn.execute(
                    """
                    INSERT INTO company_docs (id, company_id, title, source_url, content, chunk_count)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    doc_id,
                    str(company_id),
                    title,
                    source_url,
                    content,
                    len(chunks)
                )
                
                # Insert chunks with embeddings
                for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                    chunk_id = str(uuid4())
                    
                    await conn.execute(
                        """
                        INSERT INTO company_doc_chunks (
                            id, doc_id, company_id, chunk_index, content, embedding
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::vector)
                        """,
                        chunk_id,
                        doc_id,
                        str(company_id),
                        i,
                        chunk["content"],
                        embedding
                    )
                
                logger.info(
                    f"Ingested document {doc_id} with {len(chunks)} chunks "
                    f"for company {company_id}"
                )
                
                return doc_id
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Failed to ingest document: {str(e)}")
            raise
    
    async def retrieve(
        self,
        company_id: UUID,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant document chunks for a query.
        
        Uses cosine similarity search with pgvector.
        
        Args:
            company_id: Company UUID (ensures company isolation)
            query: Search query
            top_k: Number of top results to return
            
        Returns:
            List of relevant chunk dictionaries with content and metadata
        """
        try:
            # Generate embedding for query
            query_embedding = self.embedding_client.generate_embedding(query)
            
            # Search in database
            conn = await asyncpg.connect(self.conn_string)
            
            try:
                rows = await conn.fetch(
                    """
                    SELECT 
                        c.id,
                        c.content,
                        c.chunk_index,
                        d.title,
                        d.source_url,
                        1 - (c.embedding <=> $1::vector) as similarity
                    FROM company_doc_chunks c
                    JOIN company_docs d ON c.doc_id = d.id
                    WHERE c.company_id = $2
                    ORDER BY c.embedding <=> $1::vector
                    LIMIT $3
                    """,
                    query_embedding,
                    str(company_id),
                    top_k
                )
                
                results = [
                    {
                        "id": row["id"],
                        "content": row["content"],
                        "chunk_index": row["chunk_index"],
                        "title": row["title"],
                        "source_url": row["source_url"],
                        "similarity": float(row["similarity"]),
                    }
                    for row in rows
                ]
                
                logger.info(
                    f"Retrieved {len(results)} chunks for company {company_id}, "
                    f"top similarity: {results[0]['similarity']:.3f}" if results else "no results"
                )
                
                return results
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Failed to retrieve documents: {str(e)}")
            raise
    
    async def delete_document(
        self,
        company_id: UUID,
        document_id: str,
    ) -> bool:
        """
        Delete a document and all its chunks.
        
        Args:
            company_id: Company UUID (for access control)
            document_id: Document ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        try:
            conn = await asyncpg.connect(self.conn_string)
            
            try:
                # Delete document (chunks will cascade delete)
                result = await conn.execute(
                    """
                    DELETE FROM company_docs
                    WHERE id = $1 AND company_id = $2
                    """,
                    document_id,
                    str(company_id)
                )
                
                deleted = result.split()[-1] == "1"
                
                if deleted:
                    logger.info(f"Deleted document {document_id} for company {company_id}")
                else:
                    logger.warning(f"Document {document_id} not found for company {company_id}")
                
                return deleted
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Failed to delete document: {str(e)}")
            raise
    
    async def list_documents(
        self,
        company_id: UUID,
    ) -> List[Dict[str, Any]]:
        """
        List all documents for a company.
        
        Args:
            company_id: Company UUID
            
        Returns:
            List of document metadata
        """
        try:
            conn = await asyncpg.connect(self.conn_string)
            
            try:
                rows = await conn.fetch(
                    """
                    SELECT id, title, source_url, chunk_count, created_at
                    FROM company_docs
                    WHERE company_id = $1
                    ORDER BY created_at DESC
                    """,
                    str(company_id)
                )
                
                documents = [
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "source_url": row["source_url"],
                        "chunk_count": row["chunk_count"],
                        "created_at": row["created_at"],
                    }
                    for row in rows
                ]
                
                logger.info(f"Listed {len(documents)} documents for company {company_id}")
                
                return documents
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"Failed to list documents: {str(e)}")
            raise


# Global RAG store instance
_rag_store: Optional[RAGStore] = None


def get_rag_store() -> RAGStore:
    """Get or create global RAG store instance."""
    global _rag_store
    
    if _rag_store is None:
        _rag_store = RAGStore()
        logger.info("RAG store initialized")
    
    return _rag_store

