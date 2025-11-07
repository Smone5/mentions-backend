"""RAG document management API endpoints."""

import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from uuid import UUID

from models.rag import Document, DocumentCreate, DocumentChunk, RetrieveRequest
from models.user import UserProfile
from core.auth import get_current_user
from rag.store import get_rag_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/documents", response_model=Document, status_code=status.HTTP_201_CREATED)
async def upload_document(
    doc_data: DocumentCreate,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Upload and ingest a document into the RAG system.
    
    The document will be:
    1. Chunked into overlapping segments
    2. Embedded using OpenAI
    3. Stored in pgvector for semantic search
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    try:
        rag_store = get_rag_store()
        
        doc_id = await rag_store.ingest_document(
            company_id=current_user.company_id,
            title=doc_data.title,
            content=doc_data.content,
            source_url=doc_data.source_url,
            chunk_size=doc_data.chunk_size,
            chunk_overlap=doc_data.chunk_overlap,
        )
        
        # Fetch the created document
        documents = await rag_store.list_documents(current_user.company_id)
        document = next((d for d in documents if d["id"] == doc_id), None)
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Document created but not found"
            )
        
        logger.info(f"Document {doc_id} uploaded by user {current_user.id}")
        
        return Document(**document)
        
    except Exception as e:
        logger.error(f"Failed to upload document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload document: {str(e)}"
        )


@router.get("/documents", response_model=List[Document])
async def list_documents(
    current_user: UserProfile = Depends(get_current_user)
):
    """
    List all documents for the user's company.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not associated with a company"
        )
    
    try:
        rag_store = get_rag_store()
        
        documents = await rag_store.list_documents(current_user.company_id)
        
        return [Document(**doc) for doc in documents]
        
    except Exception as e:
        logger.error(f"Failed to list documents: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list documents"
        )


@router.post("/retrieve", response_model=List[DocumentChunk])
async def retrieve_documents(
    retrieve_req: RetrieveRequest,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Retrieve relevant document chunks for a query.
    
    Uses semantic search with pgvector to find the most relevant chunks.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    try:
        rag_store = get_rag_store()
        
        chunks = await rag_store.retrieve(
            company_id=current_user.company_id,
            query=retrieve_req.query,
            top_k=retrieve_req.top_k,
        )
        
        return [DocumentChunk(**chunk) for chunk in chunks]
        
    except Exception as e:
        logger.error(f"Failed to retrieve documents: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve documents"
        )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: UUID,
    current_user: UserProfile = Depends(get_current_user)
):
    """
    Delete a document and all its chunks.
    
    Only users in the same company can delete documents.
    """
    if not current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must belong to a company"
        )
    
    try:
        rag_store = get_rag_store()
        
        deleted = await rag_store.delete_document(
            company_id=current_user.company_id,
            document_id=str(document_id),
        )
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        logger.info(f"Document {document_id} deleted by user {current_user.id}")
        
        return {
            "success": True,
            "message": "Document deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document"
        )

