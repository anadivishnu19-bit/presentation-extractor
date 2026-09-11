# Presentation Extractor

A local tool that reads financial presentation/report PDFs page by page and turns each
page into clean, structured content — heading, key metrics, key points, tables, and
charts/graphs (shown as real data tables wherever the source PDF has real figures) — so
an analyst can scan a whole deck without opening the PDF itself. Supports multiple PDFs
at once, with a sidebar to toggle between them, remove them, and search headings/content
within the active one.

## v2 changes (this update)

- **Universal page format** — every page now renders through the exact same template
  (Heading → Summary → Key Metrics → Key Points → Tables → Charts) instead of an ad hoc
  layout, so a whole deck reads consistently no matter what's on each page.
- **Key metrics as stat cards** — standout figures (a KPI, a growth rate, a ratio) are
  pulled out and shown as prominent cards instead of buried in paragraph text.
- **Document-level executive summary** — after a document finishes processing, one extra
  pass rolls all pages up into a 15-second overview plus the 4-8 most important metrics
  across the whole deck, shown at the top before the page-by-page detail.
- **Document outline panel** — a right-hand "table of contents" listing every page's
  heading, click to jump, and it highlights whichever page is currently in view as you
  scroll.
- **Scanned-page detection** — a page that's almost entirely a flattened image with no
  extractable text is flagged clearly ("looks like a scanned image") and shown as a
  full-page image, instead of silently coming back empty.
- **Print / Save as PDF** — a print button in the top bar gives a clean, sidebar-free
  printable view of the whole document.
- **~4x faster on multi-page decks** — page-level DeepSeek calls now run concurrently
  (4 at a time) instead of one page at a time, since they're network calls, not
  computation.
- Right-aligned, tabular-numeral formatting on table figure columns (standard financial-
  table convention) and general visual polish.

## Why this is more accurate than asking an AI to "read" the PDF

The usual failure mode (and the reason this exists) is asking an AI to look at a picture
of a chart and guess the numbers on it. That guesses wrong. Instead, this tool:

1. Parses the actual PDF structure with PyMuPDF + pdfplumber — real text objects with
   real coordinates and font sizes, real ruled-table cells, real embedded images.
2. For every chart/graph it finds, it collects only the text tokens that are literally
   positioned on or beside that chart in the PDF file — axis labels, data labels, legend
   entries. In a PDF exported from PowerPoint or Excel, those are almost always live text
   objects, not part of the picture.
3. Only *that* grounded material — never the raw image — is handed to DeepSeek, with an
   explicit instruction to organize it and never invent a number it wasn't given.
4. If DeepSeek is unreachable for any reason, the app falls back to a deterministic,
   non-AI structuring of the same raw data rather than failing — and marks that page
   **"Raw extraction"** in the UI so you always know whether AI cleanup ran.

## Running it

**First time:**

- macOS/Linux: double-click `start.sh` (or run `./start.sh` in Terminal)
- Windows: double-click `start.bat`

This creates a local Python virtual environment, installs the few required packages, and
starts the app — your browser opens automatically to `http://localhost:8000`. Every time
after that, running the same script just starts it (no reinstalling).

Requires Python 3.10+ already installed on the machine. If `python3` (or `python` on
Windows) isn't found, install it from python.org first.

**Before your first real upload**, it's worth confirming DeepSeek is reachable from this
machine:

```
.venv/bin/python scripts/test_deepseek_connection.py       # macOS/Linux
.venv\Scripts\python scripts\test_deepseek_connection.py   # Windows
```

If it can't connect (blocked by a firewall/proxy, bad key, etc.) the app still works —
it just shows raw, un-cleaned extraction instead of AI-structured content, clearly
labeled as such.

## Your DeepSeek API key

Lives in `.env` in this folder (`DEEPSEEK_API_KEY=...`). It's already filled in with the
key you provided. Keep this folder private — anyone with that file can use your DeepSeek
quota. To change it later, edit `.env` and restart the app.

## Using it

1. **Upload PDF** in the sidebar — you can upload several; each processes in the
   background and the sidebar shows live progress (`Processing 3/12`).
2. Click a document in the sidebar to view it; click the **×** on a document to remove it
   permanently (deletes its extracted data and any saved chart images).
3. Once a document is open, use the search bar at the top to search its headings, key
   metrics, key points, table contents, and chart captions — results list which page each
   match is on and clicking one jumps straight there. The **Document Outline** panel on
   the right does the same for headings, and highlights your current page as you scroll.
4. Once the whole document finishes, an **Executive Summary** card appears at the top —
   a short overview plus the most important metrics across the whole deck.
5. Each page renders as a card in the same fixed order every time: heading, a short
   summary, key metrics (as stat cards), key points, any tables, and any charts (shown as
   the cropped chart image, plus — when the PDF actually contained the underlying figures
   — a reconstructed data table next to it).
6. Use the print icon in the top bar for a clean, printable view (or "Save as PDF" from
   your browser's print dialog) of the whole document.

## What's in this folder

```
app.py                    entry point — run this (or use start.sh / start.bat)
backend/
  main.py                 FastAPI routes
  pdf_parser.py            PDF -> raw text/tables/chart-regions (the accuracy-critical part)
  deepseek_client.py        raw data -> clean JSON via DeepSeek (+ non-AI fallback)
  extraction_pipeline.py    orchestrates upload -> parse -> structure -> save, page by page
  store.py                  simple JSON-file storage (single-user tool, no DB server needed)
  search.py                 heading/content search within a document
  models.py                 the JSON schema shared by backend and frontend
  config.py                 all tunable settings (see below)
frontend/                 the browser UI (plain HTML/CSS/JS, no build step)
scripts/
  generate_sample_pdf.py    regenerate the synthetic test PDF used during development
  test_deepseek_connection.py  connectivity sanity check (see above)
samples/                  a synthetic sample presentation for testing the pipeline
storage/                  your uploaded PDFs, extracted data, and chart images (gitignored)
```

## Tuning extraction (backend/config.py)

Chart/graph detection is heuristic (there's no ground truth for "this vector drawing is a
chart" vs. "this vector drawing is a decorative box"), so a few things are exposed for
tuning if you find it missing or over-detecting charts on your specific decks:

- `MIN_CHART_AREA_FRACTION` / `MAX_CHART_AREA_FRACTION` — how big (as a fraction of the
  page) something has to be to be considered a chart rather than an icon or a full-page
  background.
- `NEARBY_TEXT_MARGIN_X` / `NEARBY_TEXT_MARGIN_Y` — how far outside a chart's boundary to
  search for its data labels/legend. Wider horizontally by default since legends often
  sit beside a chart with a real gap.
- `DEEPSEEK_MODEL` (in `.env`) — defaults to `deepseek-chat`; `deepseek-reasoner` is also
  supported if you want deeper analysis at the cost of speed.
- `MAX_CONCURRENT_PAGES` (in `.env`) — how many pages are structured via DeepSeek at once
  (default 4). Raise it for faster processing on large decks if you're not hitting rate
  limits; lower it if you are.

## Known limitations

- Chart data reconstruction depends on the source PDF having real text labels near its
  charts. A chart that's genuinely just a flattened picture with no text anywhere near it
  (e.g. a screenshot of a screenshot) will show the image with no data table — there's
  nothing in the file to reconstruct it from, and by design this tool won't guess.
- Heading detection is font-size-based (the largest, short-ish text near the top of a
  page). Decks with unusual/inconsistent title styling may occasionally need a manual
  glance — the raw page text preview is always available to double check.
- No OCR: a page that's a scanned image (no text layer at all — e.g. a photographed page)
  is flagged as "likely scanned" and shown as a full-page image for manual review, rather
  than guessed at. Adding real OCR is possible but needs a system-level dependency
  (Tesseract) that isn't safe to assume is installed on a one-click Windows setup — ask if
  you want that added and we can make it an optional install.
- This is a single-user local tool (JSON-file storage, no login). For a shared,
  always-on version the whole team hits from a browser, that's a separate hosting
  project — ask if you'd like that scoped out.
