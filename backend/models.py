"""
Pydantic schema for the extracted-data JSON that flows from the parser ->
DeepSeek -> storage -> frontend. Kept intentionally flat and JSON-friendly
since it's persisted directly to disk (see store.py).
"""
from __future__ import annotations

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class TableData(BaseModel):
    title: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)


class KeyMetric(BaseModel):
    """One standout figure shown as a stat card (e.g. 'Total Assets' / 'Rs 4,820 Cr' / '+18% YoY')."""
    label: str
    value: str
    change: Optional[str] = None


class ChartData(BaseModel):
    caption: str = ""
    chart_type: Literal["bar", "line", "pie", "table", "unknown"] = "unknown"
    image_url: Optional[str] = None          # served path to the cropped chart image
    data_table: Optional[TableData] = None    # only populated when real labels were found
    note: Optional[str] = None                # e.g. "no embedded data labels found; showing image only"


class PageData(BaseModel):
    page_number: int
    heading: str = ""
    summary: str = ""
    key_metrics: List[KeyMetric] = Field(default_factory=list)
    key_points: List[str] = Field(default_factory=list)
    tables: List[TableData] = Field(default_factory=list)
    charts: List[ChartData] = Field(default_factory=list)
    ai_enhanced: bool = False
    raw_text_preview: str = ""
    likely_scanned: bool = False  # full-page image, almost no extractable text
    scanned_page_image_url: Optional[str] = None  # full-page render, shown when likely_scanned


class DocumentMeta(BaseModel):
    id: str
    filename: str
    uploaded_at: str
    num_pages: int = 0
    status: Literal["processing", "ready", "error"] = "processing"
    pages_done: int = 0
    error: Optional[str] = None


class DocumentFull(DocumentMeta):
    pages: List[PageData] = Field(default_factory=list)
    executive_summary: str = ""
    top_metrics: List[KeyMetric] = Field(default_factory=list)


class SearchMatch(BaseModel):
    page_number: int
    heading: str
    match_type: Literal["heading", "key_metric", "key_point", "table", "chart"]
    snippet: str
