"""
Raw PDF extraction layer.

The core design principle here (this is the fix for "Claude's extraction
wasn't accurate"): we never ask an AI to *read numbers off a picture of a
chart*. Instead we pull out everything the PDF itself actually contains --
real text spans with real coordinates and font sizes, real ruled-table
cells, and the literal text tokens that sit on top of a chart region (axis
labels, data labels, legend entries -- these are almost always live text
objects in a PPT/Excel-exported PDF, not part of the rasterized picture).
That grounded, literal material is what gets handed to the LLM to tidy up
into presentable JSON. The LLM is explicitly told to use only what's given
to it and never invent a number it doesn't see.

Two libraries, two jobs:
  * PyMuPDF (fitz)  -- text spans w/ font metrics, images, vector drawings,
                        cropping page regions to PNG.
  * pdfplumber       -- ruled-line table detection (it's simply better at
                        this than fitz's built-in table finder).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
import pdfplumber

from . import config

Rect = Tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class TextSpan:
    text: str
    bbox: Rect
    size: float
    bold: bool


@dataclass
class RawTable:
    rows: List[List[str]] = field(default_factory=list)
    bbox: Optional[Rect] = None

    @property
    def columns(self) -> List[str]:
        return self.rows[0] if self.rows else []

    @property
    def body(self) -> List[List[str]]:
        return self.rows[1:] if len(self.rows) > 1 else []


@dataclass
class ChartRegion:
    bbox: Rect
    image_bytes: bytes
    nearby_text: List[str]
    source: str  # "raster" | "vector"


@dataclass
class PageBundle:
    page_number: int  # 1-indexed
    heading_candidate: str
    body_text: str
    all_spans: List[TextSpan]
    tables: List[RawTable]
    charts: List[ChartRegion]
    likely_scanned: bool = False
    full_page_image_bytes: Optional[bytes] = None


def _rects_close(a: Rect, b: Rect, pad: float) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (
        ax0 - pad > bx1 or bx0 - pad > ax1 or ay0 - pad > by1 or by0 - pad > ay1
    )


def _union(a: Rect, b: Rect) -> Rect:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _merge_rects(rects: List[Rect], pad: float) -> List[Rect]:
    """Greedy union-merge of overlapping/near rects into clusters."""
    merged: List[Rect] = []
    for r in rects:
        placed = False
        for i, m in enumerate(merged):
            if _rects_close(r, m, pad):
                merged[i] = _union(m, r)
                placed = True
                break
        if not placed:
            merged.append(r)
    # repeat until stable (clusters can chain-merge)
    if len(merged) != len(rects):
        return _merge_rects(merged, pad) if merged != rects else merged
    return merged


def _extract_spans(page: fitz.Page) -> List[TextSpan]:
    spans: List[TextSpan] = []
    raw = page.get_text("dict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for sp in line.get("spans", []):
                text = sp.get("text", "").strip()
                if not text:
                    continue
                flags = sp.get("flags", 0)
                bold = bool(flags & 2 ** 4) or "Bold" in sp.get("font", "")
                spans.append(
                    TextSpan(text=text, bbox=tuple(sp["bbox"]), size=sp["size"], bold=bold)
                )
    return spans


def _detect_heading(spans: List[TextSpan], page_height: float) -> str:
    if not spans:
        return ""
    body_sizes = [s.size for s in spans if len(s.text) > 15]
    median_body = statistics.median(body_sizes) if body_sizes else statistics.median(
        [s.size for s in spans]
    )
    # candidates: notably larger than body text, short-ish, in the top half of the page
    candidates = [
        s
        for s in spans
        if s.size >= median_body * 1.25
        and len(s.text) <= 140
        and s.bbox[1] <= page_height * 0.55
    ]
    if not candidates:
        # fall back to the largest span anywhere on the page
        candidates = sorted(spans, key=lambda s: -s.size)[:1]
    candidates.sort(key=lambda s: (-s.size, s.bbox[1]))
    top_size = candidates[0].size
    # collect same-size spans on roughly the same line/area to rebuild a
    # multi-span heading (titles are often split into multiple text runs)
    heading_spans = [s for s in candidates if abs(s.size - top_size) < 0.5]
    heading_spans.sort(key=lambda s: (s.bbox[1], s.bbox[0]))
    text = " ".join(s.text for s in heading_spans[:6]).strip()
    return text


def _extract_tables(pdf_path: Path, page_index: int) -> List[RawTable]:
    tables: List[RawTable] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_index >= len(pdf.pages):
                return tables
            page = pdf.pages[page_index]
            for t in page.find_tables():
                raw = t.extract()
                rows = [[(c or "").strip() for c in row] for row in raw]
                rows = [r for r in rows if any(cell for cell in r)]
                if len(rows) >= 2 and len(rows[0]) >= 2:
                    tables.append(RawTable(rows=rows, bbox=tuple(t.bbox)))
    except Exception:
        # pdfplumber can choke on malformed PDFs; tables are a bonus, not
        # worth failing the whole page over.
        pass
    return tables


def _overlap_fraction(a: Rect, b: Rect) -> float:
    """Fraction of rect a's area that is covered by the intersection with b."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    a_area = (ax1 - ax0) * (ay1 - ay0)
    return inter / a_area if a_area else 0.0


def _spans_in_or_near(spans: List[TextSpan], bbox: Rect, margin_x: float, margin_y: float) -> List[str]:
    """
    Spans whose bbox INTERSECTS the chart bbox expanded by the given margins.
    Deliberately an intersection test, not "span center falls inside": a
    center-point test unfairly excludes long text (e.g. a wide legend label
    like "Affordable Housing — 18%") whose start sits just past the margin
    but whose midpoint, dragged rightward by its own width, lands outside it
    -- while a short label at the same starting position passes. Intersection
    doesn't have that length bias.
    """
    x0, y0, x1, y1 = bbox
    x0, y0, x1, y1 = x0 - margin_x, y0 - margin_y, x1 + margin_x, y1 + margin_y
    out = []
    for s in spans:
        sx0, sy0, sx1, sy1 = s.bbox
        if sx0 <= x1 and sx1 >= x0 and sy0 <= y1 and sy1 >= y0:
            out.append(s.text)
    return out


def _extract_charts(
    page: fitz.Page, spans: List[TextSpan], table_bboxes: Optional[List[Rect]] = None
) -> List[ChartRegion]:
    table_bboxes = table_bboxes or []
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    regions: List[ChartRegion] = []

    # 1) raster images (screenshots / pasted pictures of charts)
    raster_rects: List[Rect] = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            bbox_list = page.get_image_rects(xref)
        except Exception:
            bbox_list = []
        for r in bbox_list:
            area_frac = (r.width * r.height) / page_area if page_area else 0
            if config.MIN_CHART_AREA_FRACTION <= area_frac <= config.MAX_CHART_AREA_FRACTION:
                raster_rects.append((r.x0, r.y0, r.x1, r.y1))

    # 2) vector drawings (native charts drawn with lines/rects, e.g. from
    #    PowerPoint/Excel exports that keep charts as vector graphics)
    vector_rects: List[Rect] = []
    try:
        for d in page.get_drawings():
            r = d.get("rect")
            if r is None:
                continue
            vector_rects.append((r.x0, r.y0, r.x1, r.y1))
    except Exception:
        pass
    vector_clusters = _merge_rects(vector_rects, config.CHART_MERGE_PADDING)
    vector_clusters = [
        r
        for r in vector_clusters
        if config.MIN_CHART_AREA_FRACTION
        <= ((r[2] - r[0]) * (r[3] - r[1])) / page_area
        <= config.MAX_CHART_AREA_FRACTION
    ]
    # drop vector clusters that are actually just a ruled table's gridlines
    # (pdfplumber already extracted that content as a proper table)
    vector_clusters = [
        r
        for r in vector_clusters
        if not any(_overlap_fraction(r, tb) >= config.TABLE_OVERLAP_EXCLUSION for tb in table_bboxes)
    ]

    def _crop(bbox: Rect) -> bytes:
        clip = fitz.Rect(*bbox)
        pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(3, 3))  # ~216 DPI
        return pix.tobytes("png")

    for r in raster_rects:
        regions.append(
            ChartRegion(
                bbox=r,
                image_bytes=_crop(r),
                nearby_text=_spans_in_or_near(spans, r, config.NEARBY_TEXT_MARGIN_X, config.NEARBY_TEXT_MARGIN_Y),
                source="raster",
            )
        )
    for r in vector_clusters:
        # skip if it heavily overlaps a raster region already captured
        if any(_rects_close(r, rr.bbox, 2) for rr in regions):
            continue
        regions.append(
            ChartRegion(
                bbox=r,
                image_bytes=_crop(r),
                nearby_text=_spans_in_or_near(spans, r, config.NEARBY_TEXT_MARGIN_X, config.NEARBY_TEXT_MARGIN_Y),
                source="vector",
            )
        )
    return regions


def _is_likely_scanned(page: fitz.Page, body_text: str) -> bool:
    """
    A page with almost no extractable text but a large embedded image is
    almost always a scanned/rasterized page (or a slide exported as a flat
    picture) rather than a genuinely blank page. We can't run OCR here
    (no system dependency we can assume is installed on a one-click Windows
    setup), so the honest move is to flag it clearly and show the page
    image, rather than silently returning an empty card that looks like a
    bug.
    """
    if len(body_text) >= 25:
        return False
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return False
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            for r in page.get_image_rects(xref):
                if (r.width * r.height) / page_area >= 0.55:
                    return True
        except Exception:
            continue
    return False


def parse_pdf(pdf_path: Path) -> List[PageBundle]:
    doc = fitz.open(pdf_path)
    bundles: List[PageBundle] = []
    for i in range(len(doc)):
        page = doc[i]
        spans = _extract_spans(page)
        heading = _detect_heading(spans, page.rect.height)
        body_text = page.get_text("text").strip()
        tables = _extract_tables(pdf_path, i)
        table_bboxes = [t.bbox for t in tables if t.bbox]
        charts = _extract_charts(page, spans, table_bboxes)

        scanned = _is_likely_scanned(page, body_text)
        full_page_bytes = None
        if scanned:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            full_page_bytes = pix.tobytes("png")

        bundles.append(
            PageBundle(
                page_number=i + 1,
                heading_candidate=heading,
                body_text=body_text,
                all_spans=spans,
                tables=tables,
                charts=charts,
                likely_scanned=scanned,
                full_page_image_bytes=full_page_bytes,
            )
        )
    doc.close()
    return bundles
