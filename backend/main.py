from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, store
from .deepseek_client import connectivity_self_test
from .extraction_pipeline import new_document_id, process_document
from .search import search_document

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Presentation Extractor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(config.STORAGE_DIR)), name="static")


@app.get("/api/system/deepseek-check")
def deepseek_check():
    return connectivity_self_test()


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    doc_id = new_document_id()
    dest = config.UPLOADS_DIR / f"{doc_id}.pdf"
    contents = await file.read()
    if not contents:
        raise HTTPException(400, "Uploaded file is empty.")
    dest.write_bytes(contents)

    thread = threading.Thread(
        target=process_document,
        args=(doc_id, dest, file.filename),
        daemon=True,
    )
    thread.start()

    return {"id": doc_id, "filename": file.filename, "status": "processing"}


@app.get("/api/documents")
def list_documents():
    docs = store.list_documents()
    docs.sort(key=lambda d: d.uploaded_at, reverse=True)
    return docs


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    doc = store.get_full(doc_id)
    if doc is None:
        meta = store.get_meta(doc_id)
        if meta is None:
            raise HTTPException(404, "Document not found.")
        return meta
    return doc


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    ok = store.delete_document(doc_id)
    if not ok:
        raise HTTPException(404, "Document not found.")
    return {"deleted": doc_id}


@app.get("/api/documents/{doc_id}/search")
def search(doc_id: str, q: str = ""):
    doc = store.get_full(doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found or still processing.")
    return search_document(doc, q)


# Serve the frontend as static files, with index.html at the root.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
