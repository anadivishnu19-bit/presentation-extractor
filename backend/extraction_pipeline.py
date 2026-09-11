"""
Orchestrates: save upload -> parse PDF page by page -> persist chart images
-> structure each page via DeepSeek (or heuristic fallback) -> write
progressive results to the store so the frontend can poll and show pages as
they finish, rather than waiting for the whole document.

Page structuring (the DeepSeek call) is I/O-bound, so pages are structured
CONCURRENTLY across a small thread pool -- a 20-page deck no longer takes
20x one page's latency, it takes roughly (20 / MAX_WORKERS)x. Parsing itself
(local, CPU-bound, fast) stays sequential. Because pages can finish out of
order under concurrency, results are always re-sorted by page_number before
saving so the document never appears jumbled to the frontend.
"""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from . import config, store
from .deepseek_client import structure_page, synthesize_document_summary
from .models import DocumentFull, DocumentMeta, KeyMetric, PageData
from .pdf_parser import PageBundle, parse_pdf

logger = logging.getLogger("presentation_extractor.pipeline")


def _prepare_page(doc_id: str, pages_dir: Path, bundle: PageBundle) -> tuple:
    """Local/file work for one page: persist chart + scanned-page images and
    build the URL callbacks structure_page() needs. Safe to run before the
    concurrent DeepSeek calls since it touches no shared state."""
    chart_paths = []
    for i, chart in enumerate(bundle.charts):
        fname = f"p{bundle.page_number}_chart{i}.png"
        (pages_dir / fname).write_bytes(chart.image_bytes)
        chart_paths.append(f"/static/pages/{doc_id}/{fname}")

    scanned_url = None
    if bundle.likely_scanned and bundle.full_page_image_bytes:
        fname = f"p{bundle.page_number}_full.png"
        (pages_dir / fname).write_bytes(bundle.full_page_image_bytes)
        scanned_url = f"/static/pages/{doc_id}/{fname}"

    def url_for(i: int) -> str:
        return chart_paths[i]

    return bundle, url_for, scanned_url


def _structure_one(args) -> PageData:
    bundle, url_for, scanned_url = args
    try:
        return structure_page(bundle, url_for, scanned_url)
    except Exception:  # noqa: BLE001
        logger.exception("Failed structuring page %s", bundle.page_number)
        return PageData(
            page_number=bundle.page_number,
            heading=bundle.heading_candidate,
            summary="",
            key_points=[],
            tables=[],
            charts=[],
            ai_enhanced=False,
            raw_text_preview=bundle.body_text[:500],
            likely_scanned=bundle.likely_scanned,
            scanned_page_image_url=scanned_url,
        )


def process_document(doc_id: str, pdf_path: Path, filename: str) -> None:
    meta = DocumentMeta(
        id=doc_id,
        filename=filename,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        status="processing",
        pages_done=0,
    )
    store.upsert_meta(meta)

    try:
        bundles = parse_pdf(pdf_path)
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to parse PDF %s", pdf_path)
        meta.status = "error"
        meta.error = f"Could not read this PDF: {e}"
        store.upsert_meta(meta)
        return

    meta.num_pages = len(bundles)
    store.upsert_meta(meta)

    doc = DocumentFull(**meta.model_dump(), pages=[])
    pages_dir = config.PAGES_DIR / doc_id
    pages_dir.mkdir(parents=True, exist_ok=True)

    work_items = [_prepare_page(doc_id, pages_dir, b) for b in bundles]

    pages_by_number: dict[int, PageData] = {}
    save_lock = threading.Lock()

    def on_page_done(page_data: PageData) -> None:
        with save_lock:
            pages_by_number[page_data.page_number] = page_data
            doc.pages = [pages_by_number[n] for n in sorted(pages_by_number)]
            doc.pages_done = len(doc.pages)
            store.save_full(doc)  # progressive save -> frontend can poll and render as it goes

    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_PAGES) as pool:
        futures = [pool.submit(_structure_one, item) for item in work_items]
        for future in as_completed(futures):
            on_page_done(future.result())

    # final pass: whole-document executive summary + top metrics, built from
    # the now-complete page data. Never blocks page-level results above.
    try:
        summary = synthesize_document_summary(doc.pages)
        doc.executive_summary = summary.get("executive_summary", "")
        doc.top_metrics = [
            KeyMetric(label=m.get("label", ""), value=m.get("value", ""), change=m.get("change"))
            for m in summary.get("top_metrics", [])
        ]
    except Exception:  # noqa: BLE001
        logger.exception("Document summary synthesis failed for %s", doc_id)

    doc.status = "ready"
    store.save_full(doc)


def new_document_id() -> str:
    return uuid.uuid4().hex[:12]
