"""
Company Knowledge Document Management API.
Supports uploading PDFs, Markdown, TXT, DOCX, and CSV files,
extracting their text, and indexing into the Company Knowledge RAG.
"""
import uuid
import os
from datetime import date, datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status, Query
from app import permissions as perms
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database.connection import get_db
from app.models.database import CompanyKnowledgeEmbedding
from app.rag.company_knowledge import company_knowledge_rag
from app.api.deps import get_current_org_id

router = APIRouter(prefix="/api/documents", tags=["documents"])

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}

#: Documents are read fully into memory before extraction.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _docx_text(content_bytes: bytes) -> str:
    """Paragraph text from a .docx (a zip of XML), without a Word dependency."""
    import io
    import re
    import zipfile

    with zipfile.ZipFile(io.BytesIO(content_bytes)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(perms.require("create_content"))])
async def upload_company_document(
    file: UploadFile = File(...),
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload and index a company document into Company Knowledge RAG.
    """
    # The name is only ever stored as a label (content goes straight into
    # the database), but "../../x.txt" is still not a name worth keeping.
    filename = os.path.basename((file.filename or "").replace("\\", "/")).strip()
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    file.filename = filename

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )

    content_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Documents must be under {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    text_content = ""

    if ext in (".txt", ".md", ".csv"):
        text_content = content_bytes.decode("utf-8", errors="ignore")
    elif ext == ".pdf":
        try:
            import pypdf
            import io
            reader = pypdf.PdfReader(io.BytesIO(content_bytes))
            text_content = "\n".join([page.extract_text() or "" for page in reader.pages])
        except Exception:
            raise HTTPException(status_code=400, detail="Could not read that PDF.")
    elif ext == ".docx":
        try:
            text_content = _docx_text(content_bytes)
        except Exception:
            raise HTTPException(status_code=400, detail="Could not read that .docx file.")

    if not text_content.strip():
        raise HTTPException(status_code=400, detail="Document contains no extractable text")

    doc_id = uuid.uuid4()

    chunks_count = await company_knowledge_rag.index_document(
        db=db,
        org_id=org_id,
        document_id=doc_id,
        source_name=file.filename,
        source_type=ext.replace(".", ""),
        text_content=text_content,
    )
    await db.commit()

    return {
        "status": "indexed",
        "document_id": str(doc_id),
        "filename": file.filename,
        "chunks_indexed": chunks_count,
    }


@router.get("")
async def list_documents(
    day: Optional[date] = Query(None, description="Filter to documents indexed on this day"),
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """List distinct company knowledge documents, most recently indexed first."""
    conditions = [CompanyKnowledgeEmbedding.organization_id == org_id]
    if day:
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        day_end = datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc)
        conditions.append(CompanyKnowledgeEmbedding.created_at >= day_start)
        conditions.append(CompanyKnowledgeEmbedding.created_at <= day_end)

    stmt = (
        select(
            CompanyKnowledgeEmbedding.document_id,
            CompanyKnowledgeEmbedding.source_name,
            CompanyKnowledgeEmbedding.source_type,
            func.min(CompanyKnowledgeEmbedding.created_at).label("indexed_at"),
            func.count(CompanyKnowledgeEmbedding.id).label("chunks_count"),
        )
        .where(and_(*conditions))
        .group_by(
            CompanyKnowledgeEmbedding.document_id,
            CompanyKnowledgeEmbedding.source_name,
            CompanyKnowledgeEmbedding.source_type,
        )
        .order_by(func.min(CompanyKnowledgeEmbedding.created_at).desc())
    )
    result = await db.execute(stmt)
    return [
        {
            "document_id": str(row.document_id) if row.document_id else None,
            "filename": row.source_name,
            "source_type": row.source_type,
            "indexed_at": row.indexed_at,
            "chunks_count": row.chunks_count,
        }
        for row in result.all()
    ]


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(perms.require("delete_content"))])
async def delete_document(
    document_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove a document and every chunk indexed from it."""
    result = await db.execute(
        delete(CompanyKnowledgeEmbedding).where(
            CompanyKnowledgeEmbedding.organization_id == org_id,
            CompanyKnowledgeEmbedding.document_id == document_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.commit()
