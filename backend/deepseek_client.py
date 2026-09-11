"""
Turns a raw PageBundle (from pdf_parser.py) into clean, presentable JSON
using the DeepSeek API.

Grounding rule (this is what fixes "the data isn't accurate"): the prompt
hands DeepSeek the literal text extracted from the PDF page -- including,
for every detected chart, only the text tokens that were physically
positioned on/near that chart in the PDF -- and explicitly forbids it from
inventing figures it wasn't given. DeepSeek's job is tidying and structuring
what's there, never guessing what a bar "probably" says from pixels.

If the API is unreachable (network policy, bad key, rate limits, timeouts)
extraction must not break: `structure_page` falls back to a deterministic,
non-AI structuring of the same raw data and marks `ai_enhanced=False` so the
frontend can show that plainly instead of silently degrading quality.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import List, Optional

from openai import OpenAI, APIError, APIConnectionError, APITimeoutError

from . import config
from .models import ChartData, DocumentFull, KeyMetric, PageData, TableData
from .pdf_parser import PageBundle

logger = logging.getLogger("presentation_extractor.deepseek")

_client: Optional[OpenAI] = None


def _get_client() -> Optional[OpenAI]:
    global _client
    if not config.DEEPSEEK_API_KEY:
        return None
    if _client is None:
        _client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=config.DEEPSEEK_TIMEOUT_SECS,
            max_retries=0,  # we do our own retry loop below; the SDK's default (2) would nest on top and multiply delay
        )
    return _client


SYSTEM_PROMPT = """You are a meticulous financial-document analyst assistant. \
You will be given the RAW, literal content that was mechanically extracted from one page \
of a company presentation/report PDF: the page's text, any ruled tables already detected, \
and for each chart/graph found on the page, the literal text tokens (axis labels, data \
labels, legend entries, units) that were physically positioned on or beside that chart in \
the PDF file.

Your job is ONLY to organize and lightly clean this material into the requested JSON. \
You must NOT invent, estimate, guess, or hallucinate any number, name, or fact that is not \
present in the raw material you were given. If a chart's nearby-text tokens are too sparse \
to reconstruct a data table, leave data_table null and just write a short factual caption \
about what the chart appears to show (axis/legend labels only) -- do not make up trend \
commentary you cannot support from the given text. Preserve numbers, units (%, Rs cr, bps, \
INR, etc.) and time periods exactly as written in the source text.

You must also pull out `key_metrics`: the handful of standout figures on this page (a KPI, \
a growth rate, a ratio -- the numbers an analyst would scan for first), each as a short \
label plus its value exactly as written (e.g. label "Total Assets", value "Rs 4,820 Cr"). \
Only include a `change` field if the source text explicitly states a comparison (e.g. "+18% \
YoY") -- never compute or infer a change yourself. Leave key_metrics empty if the page has \
no standout figures (e.g. a purely qualitative/text page); do not force metrics that aren't \
really there. Output strict JSON only, matching the schema you're given -- no markdown, no \
commentary outside the JSON."""


def _build_user_prompt(bundle: PageBundle) -> str:
    tables_raw = []
    for t in bundle.tables:
        tables_raw.append({"columns": t.columns, "rows": t.body})

    charts_raw = []
    for i, c in enumerate(bundle.charts):
        charts_raw.append(
            {
                "chart_index": i,
                "source": c.source,
                "nearby_text_tokens": c.nearby_text,
            }
        )

    payload = {
        "page_number": bundle.page_number,
        "heading_candidate_from_layout": bundle.heading_candidate,
        "raw_page_text": bundle.body_text[:6000],
        "detected_tables": tables_raw,
        "detected_charts": charts_raw,
    }

    schema_hint = {
        "heading": "string - the page's main heading/title, cleaned up",
        "summary": "string - 1-2 sentence factual summary of what this page communicates",
        "key_metrics": [
            {
                "label": "short metric name, e.g. 'Total Assets'",
                "value": "the figure with its unit exactly as written, e.g. 'Rs 4,820 Cr'",
                "change": "e.g. '+18% YoY' ONLY if explicitly stated in the source text, else null",
            }
        ],
        "key_points": ["array of short factual bullet strings pulled from raw_page_text"],
        "tables": [
            {"title": "string or null", "columns": ["..."], "rows": [["..."]]}
        ],
        "charts": [
            {
                "chart_index": "int, matches detected_charts[i].chart_index",
                "caption": "string - what the chart shows, grounded only in its nearby_text_tokens",
                "chart_type": "one of: bar, line, pie, table, unknown",
                "data_table": {
                    "columns": ["..."],
                    "rows": [["..."]],
                    "_or_null_if_tokens_insufficient": True,
                },
            }
        ],
    }

    return (
        "RAW PAGE DATA:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nRETURN JSON MATCHING THIS SHAPE:\n"
        + json.dumps(schema_hint, ensure_ascii=False, indent=2)
    )


def _call_deepseek(bundle: PageBundle) -> Optional[dict]:
    client = _get_client()
    if client is None:
        return None

    user_prompt = _build_user_prompt(bundle)
    last_err = None
    for attempt in range(config.DEEPSEEK_MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            content = resp.choices[0].message.content
            return json.loads(content)
        except (APIConnectionError, APITimeoutError) as e:
            last_err = e
            logger.warning("DeepSeek connection issue (attempt %d): %s", attempt + 1, e)
            time.sleep(min(2 ** attempt, 5))
        except APIError as e:
            last_err = e
            logger.warning("DeepSeek API error (attempt %d): %s", attempt + 1, e)
            time.sleep(min(2 ** attempt, 5))
        except json.JSONDecodeError as e:
            last_err = e
            logger.warning("DeepSeek returned non-JSON content: %s", e)
            break
    logger.error("DeepSeek call failed after retries: %s", last_err)
    return None


_METRIC_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])[+-]?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\s?%"),
    # \b + a required digit right after Rs/INR/₹ matters: without them this
    # matched "rs," inside ordinary words like "quarters," (IGNORECASE makes
    # "Rs" match lowercase "rs", and a bare comma satisfied a too-loose
    # [\d,]+) and returned nonsense metrics like value="rs,".
    re.compile(r"\b(?:Rs\.?|INR|₹)\s?\d[\d,]*(?:\.\d+)?\s?(?:Cr|Crore|Lakh|Lakhs|Mn|Bn|Million|Billion)?\b", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s?bps\b", re.IGNORECASE),
]


def _extract_heuristic_metrics(lines: List[str], exclude_text: set) -> List[dict]:
    """
    Best-effort, no-AI stand-in for key_metrics: scan lines for numbers that
    look like a %, a currency figure (Rs/INR/₹ ... Cr/Lakh/Mn/Bn), or bps,
    and use the rest of that line as the label. Used only when DeepSeek is
    unavailable -- deliberately conservative (one metric per line, first
    match only) since there's no model here to disambiguate.
    """
    metrics: List[dict] = []
    seen_values = set()
    for line in lines:
        if line in exclude_text:
            continue
        match = None
        for pat in _METRIC_PATTERNS:
            m = pat.search(line)
            if m:
                match = m.group(0).strip()
                break
        if not match or match in seen_values:
            continue
        seen_values.add(match)
        label = re.sub(r"\s+", " ", line.replace(match, " ")).strip(" :–-•\t.,")
        if len(label) > 60:
            label = label[:57] + "..."
        metrics.append({"label": label or "Figure", "value": match, "change": None})
        if len(metrics) >= 6:
            break
    return metrics


def _heuristic_structure(bundle: PageBundle) -> dict:
    """Deterministic, no-AI structuring used when DeepSeek is unavailable."""
    # exclude any line that's actually table-cell text (already captured under
    # "tables") so it doesn't get duplicated as a bogus "key point" bullet
    table_cell_text = set()
    for t in bundle.tables:
        for cell in t.columns:
            table_cell_text.add(cell.strip())
        for row in t.body:
            for cell in row:
                table_cell_text.add(cell.strip())
    chart_label_text = set()
    for c in bundle.charts:
        for tok in c.nearby_text:
            chart_label_text.add(tok.strip())

    lines = [l.strip() for l in bundle.body_text.splitlines() if l.strip()]
    filtered_lines = [
        l
        for l in lines
        if l != bundle.heading_candidate and l not in table_cell_text and l not in chart_label_text
    ]
    key_points = filtered_lines[:8]
    key_metrics = _extract_heuristic_metrics(filtered_lines, table_cell_text | chart_label_text)
    tables = [{"title": None, "columns": t.columns, "rows": t.body} for t in bundle.tables]
    charts = []
    for i, c in enumerate(bundle.charts):
        charts.append(
            {
                "chart_index": i,
                "caption": "Chart detected on page (AI cleanup unavailable — showing raw labels)."
                if c.nearby_text
                else "Chart/graphic detected on page.",
                "chart_type": "unknown",
                "data_table": None,
            }
        )
    return {
        "heading": bundle.heading_candidate,
        "summary": "",
        "key_metrics": key_metrics,
        "key_points": key_points,
        "tables": tables,
        "charts": charts,
    }


def structure_page(bundle: PageBundle, image_url_for_chart, scanned_page_image_url: Optional[str] = None) -> PageData:
    """
    image_url_for_chart: callable(chart_index:int) -> str, gives the served
    URL for that chart's cropped image (persisting images is the caller's
    responsibility since it needs the doc_id/page_number to build a path).
    scanned_page_image_url: set by the caller when bundle.likely_scanned, the
    served URL of the full rendered page image.
    """
    result = _call_deepseek(bundle)
    ai_enhanced = result is not None
    if result is None:
        result = _heuristic_structure(bundle)

    charts_out = []
    result_charts = {c.get("chart_index"): c for c in result.get("charts", []) if isinstance(c, dict)}
    for i, raw_chart in enumerate(bundle.charts):
        rc = result_charts.get(i, {})
        dt = rc.get("data_table")
        data_table = None
        note = None
        if dt and dt.get("rows"):
            data_table = TableData(columns=dt.get("columns", []), rows=dt.get("rows", []))
        else:
            note = "No embedded data labels were found near this chart — showing the image only."
        charts_out.append(
            ChartData(
                caption=rc.get("caption", ""),
                chart_type=rc.get("chart_type", "unknown")
                if rc.get("chart_type") in ("bar", "line", "pie", "table", "unknown")
                else "unknown",
                image_url=image_url_for_chart(i),
                data_table=data_table,
                note=note,
            )
        )

    tables_out = [
        TableData(title=t.get("title"), columns=t.get("columns", []), rows=t.get("rows", []))
        for t in result.get("tables", [])
        if isinstance(t, dict)
    ]

    metrics_out = [
        KeyMetric(label=str(m.get("label", "")), value=str(m.get("value", "")), change=m.get("change") or None)
        for m in result.get("key_metrics", [])
        if isinstance(m, dict) and m.get("label") and m.get("value")
    ]

    return PageData(
        page_number=bundle.page_number,
        heading=result.get("heading") or bundle.heading_candidate,
        summary=result.get("summary", ""),
        key_metrics=metrics_out,
        key_points=[str(p) for p in result.get("key_points", [])],
        tables=tables_out,
        charts=charts_out,
        ai_enhanced=ai_enhanced,
        raw_text_preview=bundle.body_text[:500],
        likely_scanned=bundle.likely_scanned,
        scanned_page_image_url=scanned_page_image_url,
    )


DOC_SUMMARY_SYSTEM_PROMPT = """You are a meticulous financial-document analyst assistant. \
You will be given the already-extracted heading, summary, and key metrics for every page of \
a company presentation/report (extracted page-by-page from the real PDF text). Your job is \
to write a short whole-document executive summary (3-5 sentences) that an analyst could read \
in 15 seconds to know what the deck covers, and to pick the 4-8 most important metrics across \
the whole document (favor ones that appear to be headline figures -- totals, growth rates, \
key ratios -- over minor ones). You must NOT invent any fact, number, or figure that isn't \
already present in the page data you're given -- you are only summarizing and prioritizing \
what's there. Output strict JSON only: {"executive_summary": "...", "top_metrics": [{"label":\
"...", "value": "...", "change": "..." or null}]}. No markdown, no commentary outside the JSON."""


def synthesize_document_summary(pages: List[PageData]) -> dict:
    """
    One extra call (after all pages are done) that rolls page-level headings/
    summaries/metrics up into a document-level executive summary + the most
    important metrics overall -- so an analyst gets a 15-second overview
    instead of having to read every page card. Falls back to a plain,
    non-AI outline when DeepSeek is unavailable.
    """
    client = _get_client()
    page_digest = [
        {
            "page_number": p.page_number,
            "heading": p.heading,
            "summary": p.summary,
            "key_metrics": [m.model_dump() for m in p.key_metrics],
        }
        for p in pages
    ]

    if client is not None:
        try:
            resp = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": DOC_SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(page_digest, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            result = json.loads(resp.choices[0].message.content)
            return {
                "executive_summary": result.get("executive_summary", ""),
                "top_metrics": [
                    m for m in result.get("top_metrics", []) if isinstance(m, dict) and m.get("label") and m.get("value")
                ][:8],
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("Document summary synthesis failed, falling back to outline: %s", e)

    # heuristic fallback: no invented prose, just a factual outline
    headings = [p.heading for p in pages if p.heading]
    outline = "; ".join(headings[:10])
    all_metrics = [m.model_dump() for p in pages for m in p.key_metrics][:8]
    return {
        "executive_summary": f"{len(pages)}-page document covering: {outline}." if outline else "",
        "top_metrics": all_metrics,
    }


def connectivity_self_test() -> dict:
    """Used by /api/system/deepseek-check and the standalone test script."""
    client = _get_client()
    if client is None:
        return {"ok": False, "reason": "No DEEPSEEK_API_KEY configured in .env"}
    try:
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=5,
            timeout=15,
        )
        text = (resp.choices[0].message.content or "").strip()
        return {"ok": True, "model": config.DEEPSEEK_MODEL, "reply": text}
    except Exception as e:  # noqa: BLE001 - surface any failure reason to the user
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
