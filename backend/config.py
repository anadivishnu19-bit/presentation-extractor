"""
Central configuration for Presentation Extractor.

All paths are resolved relative to the project root (one level above this
backend/ folder) so the app works the same whether it's launched from the
project root or from inside backend/.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

STORAGE_DIR = PROJECT_ROOT / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
PAGES_DIR = STORAGE_DIR / "pages"
DB_DIR = STORAGE_DIR / "db"
MANIFEST_PATH = DB_DIR / "documents.json"

for d in (STORAGE_DIR, UPLOADS_DIR, PAGES_DIR, DB_DIR):
    d.mkdir(parents=True, exist_ok=True)

# --- DeepSeek ---
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip()

# If DeepSeek can't be reached (network policy, bad key, rate limit, etc.)
# the app must never crash the extraction pipeline -- it falls back to a
# heuristic (non-AI) structuring of the raw parsed data and marks the page
# as "ai_enhanced": false so the frontend can show that clearly.
DEEPSEEK_TIMEOUT_SECS = float(os.environ.get("DEEPSEEK_TIMEOUT_SECS", "60"))
DEEPSEEK_MAX_RETRIES = int(os.environ.get("DEEPSEEK_MAX_RETRIES", "2"))

# How many pages to structure concurrently (I/O-bound DeepSeek calls, so this
# is a big speedup on multi-page decks). Raise cautiously -- DeepSeek's API
# has its own rate limits.
MAX_CONCURRENT_PAGES = int(os.environ.get("MAX_CONCURRENT_PAGES", "4"))

# --- Extraction heuristics (tunable) ---
MIN_CHART_AREA_FRACTION = 0.03   # ignore raster images/vector clusters smaller than 3% of page area
MAX_CHART_AREA_FRACTION = 0.92   # ignore near-full-page rects (likely page borders/backgrounds)
CHART_MERGE_PADDING = 8          # points; merge vector-drawing rects within this distance
# Nearby-text search margins are intentionally asymmetric: legends commonly sit
# well to the side of a chart with a real gap, while unrelated body text
# (bullets, headings) tends to sit close above/below -- so we reach further
# sideways than we do vertically, to pick up real legends without pulling in
# unrelated paragraphs.
NEARBY_TEXT_MARGIN_X = 80        # points
NEARBY_TEXT_MARGIN_Y = 20        # points
TABLE_OVERLAP_EXCLUSION = 0.6    # fraction of a vector-drawing cluster that must overlap a detected table to be discarded as "not actually a chart"

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
