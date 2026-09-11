"""Simple case-insensitive search across a document's headings/content."""
from __future__ import annotations

from typing import List

from .models import DocumentFull, SearchMatch


def search_document(doc: DocumentFull, query: str) -> List[SearchMatch]:
    q = query.strip().lower()
    if not q:
        return []
    matches: List[SearchMatch] = []
    for page in doc.pages:
        if q in page.heading.lower():
            matches.append(
                SearchMatch(
                    page_number=page.page_number,
                    heading=page.heading,
                    match_type="heading",
                    snippet=page.heading,
                )
            )
            continue  # heading match is the strongest; don't also list weaker matches
        hit = False
        for m in page.key_metrics:
            hay = f"{m.label} {m.value} {m.change or ''}"
            if q in hay.lower():
                matches.append(
                    SearchMatch(
                        page_number=page.page_number,
                        heading=page.heading,
                        match_type="key_metric",
                        snippet=f"{m.label}: {m.value}" + (f" ({m.change})" if m.change else ""),
                    )
                )
                hit = True
                break
        if hit:
            continue
        for kp in page.key_points:
            if q in kp.lower():
                matches.append(
                    SearchMatch(
                        page_number=page.page_number,
                        heading=page.heading,
                        match_type="key_point",
                        snippet=kp,
                    )
                )
                hit = True
                break
        if hit:
            continue
        for t in page.tables:
            hay = " ".join(t.columns) + " " + " ".join(" ".join(r) for r in t.rows)
            if q in hay.lower():
                matches.append(
                    SearchMatch(
                        page_number=page.page_number,
                        heading=page.heading,
                        match_type="table",
                        snippet=(t.title or "Table") + f" on page {page.page_number}",
                    )
                )
                hit = True
                break
        if hit:
            continue
        for c in page.charts:
            if q in c.caption.lower():
                matches.append(
                    SearchMatch(
                        page_number=page.page_number,
                        heading=page.heading,
                        match_type="chart",
                        snippet=c.caption,
                    )
                )
                break
    return matches
