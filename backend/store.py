"""
Lightweight JSON-file storage layer.

This is a single-user local tool, not a multi-tenant service, so a full
database is overkill: a manifest file lists all documents, and each
document's fully-extracted content lives in its own JSON file. A per-process
lock guards concurrent writes (uploads are processed one page at a time in a
background thread, and the manifest is written after every page so the
frontend can poll live progress).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .models import DocumentFull, DocumentMeta

_lock = threading.RLock()


def _read_manifest() -> Dict[str, dict]:
    if not config.MANIFEST_PATH.exists():
        return {}
    with open(config.MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_manifest(data: Dict[str, dict]) -> None:
    tmp = config.MANIFEST_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(config.MANIFEST_PATH)


def _doc_path(doc_id: str) -> Path:
    return config.DB_DIR / f"{doc_id}.json"


def list_documents() -> List[DocumentMeta]:
    with _lock:
        manifest = _read_manifest()
    return [DocumentMeta(**v) for v in manifest.values()]


def upsert_meta(meta: DocumentMeta) -> None:
    with _lock:
        manifest = _read_manifest()
        manifest[meta.id] = meta.model_dump()
        _write_manifest(manifest)


def get_meta(doc_id: str) -> Optional[DocumentMeta]:
    with _lock:
        manifest = _read_manifest()
    if doc_id not in manifest:
        return None
    return DocumentMeta(**manifest[doc_id])


def save_full(doc: DocumentFull) -> None:
    with _lock:
        tmp = _doc_path(doc.id).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(doc.model_dump_json(indent=2))
        tmp.replace(_doc_path(doc.id))
        upsert_meta(DocumentMeta(**doc.model_dump(exclude={"pages"})))


def get_full(doc_id: str) -> Optional[DocumentFull]:
    path = _doc_path(doc_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return DocumentFull(**json.load(f))


def delete_document(doc_id: str) -> bool:
    with _lock:
        manifest = _read_manifest()
        if doc_id not in manifest:
            return False
        del manifest[doc_id]
        _write_manifest(manifest)
    path = _doc_path(doc_id)
    if path.exists():
        path.unlink()
    upload_path = config.UPLOADS_DIR / f"{doc_id}.pdf"
    if upload_path.exists():
        upload_path.unlink()
    pages_dir = config.PAGES_DIR / doc_id
    if pages_dir.exists():
        import shutil

        shutil.rmtree(pages_dir, ignore_errors=True)
    return True
