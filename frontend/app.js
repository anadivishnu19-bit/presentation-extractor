const API = "";

const state = {
  docs: [],           // [{id, filename, status, num_pages, pages_done, uploaded_at, error}]
  activeId: null,
  activeDoc: null,     // full document once loaded
  pollTimers: {},      // docId -> interval id
};

const el = {
  docList: document.getElementById("doc-list"),
  fileInput: document.getElementById("file-input"),
  content: document.getElementById("content"),
  topbarTitle: document.getElementById("active-doc-title"),
  searchInput: document.getElementById("search-input"),
  searchResults: document.getElementById("search-results"),
  deepseekStatus: document.getElementById("deepseek-status"),
  printBtn: document.getElementById("print-btn"),
  outlineList: document.getElementById("outline-list"),
};

let outlineObserver = null;

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
      " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function el_(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

/* ---------------- API ---------------- */

async function apiListDocuments() {
  const r = await fetch(`${API}/api/documents`);
  return r.json();
}

async function apiGetDocument(id) {
  const r = await fetch(`${API}/api/documents/${id}`);
  if (!r.ok) throw new Error("Failed to load document");
  return r.json();
}

async function apiUpload(file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API}/api/documents`, { method: "POST", body: fd });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Upload failed");
  }
  return r.json();
}

async function apiDelete(id) {
  await fetch(`${API}/api/documents/${id}`, { method: "DELETE" });
}

async function apiSearch(id, q) {
  const r = await fetch(`${API}/api/documents/${id}/search?q=${encodeURIComponent(q)}`);
  if (!r.ok) return [];
  return r.json();
}

async function apiDeepseekCheck() {
  const r = await fetch(`${API}/api/system/deepseek-check`);
  return r.json();
}

/* ---------------- Sidebar / document list ---------------- */

function statusBadge(doc) {
  if (doc.status === "processing") {
    const n = doc.num_pages || 0;
    const done = doc.pages_done || 0;
    return `<span class="status-badge status-processing">Processing ${n ? `${done}/${n}` : "…"}</span>`;
  }
  if (doc.status === "error") return `<span class="status-badge status-error">Error</span>`;
  return `<span class="status-badge status-ready">Ready · ${doc.num_pages} pages</span>`;
}

function renderDocList() {
  el.docList.innerHTML = "";
  if (state.docs.length === 0) {
    el.docList.appendChild(el_("div", "empty-hint", "No PDFs uploaded yet."));
    return;
  }
  for (const doc of state.docs) {
    const item = el_("div", "doc-item" + (doc.id === state.activeId ? " active" : ""));
    item.dataset.id = doc.id;

    const icon = el_("div", "doc-icon", "📄");
    const info = el_("div", "doc-info");
    const name = el_("div", "doc-name", doc.filename);
    name.title = doc.filename;
    const meta = el_("div", "doc-meta");
    meta.innerHTML = statusBadge(doc);
    info.appendChild(name);
    info.appendChild(meta);

    const removeBtn = el_("button", "doc-remove");
    removeBtn.title = "Remove";
    removeBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
    removeBtn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      if (!confirm(`Remove "${doc.filename}" from Presentation Extractor?`)) return;
      await apiDelete(doc.id);
      stopPolling(doc.id);
      state.docs = state.docs.filter((d) => d.id !== doc.id);
      if (state.activeId === doc.id) {
        state.activeId = null;
        state.activeDoc = null;
        renderEmptyContent();
      }
      renderDocList();
    });

    item.appendChild(icon);
    item.appendChild(info);
    item.appendChild(removeBtn);
    item.addEventListener("click", () => selectDocument(doc.id));
    el.docList.appendChild(item);
  }
}

/* ---------------- Selecting / loading a document ---------------- */

async function selectDocument(id) {
  state.activeId = id;
  renderDocList();
  el.searchInput.disabled = false;
  clearSearchResults();
  await refreshActiveDocument();
}

async function refreshActiveDocument() {
  if (!state.activeId) return;
  try {
    const doc = await apiGetDocument(state.activeId);
    state.activeDoc = doc;
    // keep the sidebar meta (status/progress) in sync too
    const idx = state.docs.findIndex((d) => d.id === doc.id);
    if (idx >= 0) state.docs[idx] = { ...state.docs[idx], ...doc };
    renderDocList();
    renderContent();
  } catch (e) {
    console.error(e);
  }
}

function renderEmptyContent() {
  el.topbarTitle.textContent = "Upload a PDF to get started";
  el.searchInput.disabled = true;
  el.searchInput.value = "";
  el.printBtn.disabled = true;
  clearSearchResults();
  el.content.innerHTML = `
    <div class="placeholder">
      <div class="placeholder-icon">📄</div>
      <h2>No document selected</h2>
      <p>Upload one or more presentation PDFs on the left. Each page is read carefully, then
         extracted into a consistent format — heading, key metrics, key points, tables, and
         charts/graphs (shown as real data tables wherever the source PDF contains the figures).</p>
    </div>`;
  renderOutline(null);
}

function renderContent() {
  const doc = state.activeDoc;
  if (!doc) return;
  el.topbarTitle.textContent = doc.filename;
  el.printBtn.disabled = doc.status !== "ready";
  el.content.innerHTML = "";

  if (doc.status === "error") {
    const banner = el_("div", "error-banner", doc.error || "This document could not be processed.");
    el.content.appendChild(banner);
    renderOutline(doc);
    return;
  }

  if (doc.status === "processing") {
    const total = doc.num_pages || 0;
    const done = doc.pages_done || 0;
    const pct = total ? Math.round((done / total) * 100) : 5;
    const banner = el_("div", "progress-banner");
    const label = el_("span", null, total ? `Reading page ${done} of ${total}…` : "Opening PDF…");
    const track = el_("div", "progress-bar-track");
    const fill = el_("div", "progress-bar-fill");
    fill.style.width = pct + "%";
    track.appendChild(fill);
    banner.appendChild(label);
    banner.appendChild(track);
    el.content.appendChild(banner);
  }

  // Document-level executive summary: a 15-second overview above the
  // page-by-page cards, once the whole document has finished processing.
  if (doc.status === "ready" && (doc.executive_summary || (doc.top_metrics || []).length)) {
    el.content.appendChild(renderExecSummary(doc));
  }

  const pages = doc.pages || [];
  if (pages.length === 0 && doc.status === "processing") {
    el.content.appendChild(el_("div", "placeholder", "Extraction starting…"));
  }

  for (const page of pages) {
    el.content.appendChild(renderPageCard(page));
  }

  renderOutline(doc);
}

function renderExecSummary(doc) {
  const box = el_("div", "exec-summary");
  box.appendChild(el_("div", "exec-summary-label", "Executive Summary"));
  if (doc.executive_summary) {
    box.appendChild(el_("div", "exec-summary-text", doc.executive_summary));
  }
  if ((doc.top_metrics || []).length) {
    box.appendChild(renderMetrics(doc.top_metrics));
  }
  return box;
}

// Every page card follows the SAME section order, regardless of what the
// page actually contains: Heading -> Summary -> Key Metrics -> Key Points ->
// Tables -> Charts. A section simply doesn't render when it's empty -- the
// order and styling never change, so a whole deck reads consistently
// instead of each page looking like a different kind of document.
function renderPageCard(page) {
  const card = el_("div", "page-card");
  card.id = `page-${page.page_number}`;

  const head = el_("div", "page-card-head");
  head.appendChild(el_("div", "page-num-badge", `PAGE ${page.page_number}`));
  head.appendChild(el_("div", "page-heading", page.heading || "(No heading detected)"));
  const flag = el_("div", "ai-flag " + (page.ai_enhanced ? "ai-flag-on" : "ai-flag-off"),
    page.ai_enhanced ? "AI-structured" : "Raw extraction");
  head.appendChild(flag);
  card.appendChild(head);

  if (page.likely_scanned) {
    const banner = el_("div", "scanned-banner");
    banner.textContent = "⚠ This page looks like a scanned image with little embeddable text — showing the page image for manual review; structured extraction may be limited here.";
    card.appendChild(banner);
    if (page.scanned_page_image_url) {
      const img = document.createElement("img");
      img.className = "chart-img";
      img.style.marginBottom = "14px";
      img.src = page.scanned_page_image_url;
      img.alt = `Page ${page.page_number} (scanned)`;
      card.appendChild(img);
    }
  }

  if (page.summary) {
    card.appendChild(el_("div", "page-summary", page.summary));
  }

  if (page.key_metrics && page.key_metrics.length) {
    card.appendChild(el_("div", "section-label", "Key Metrics"));
    card.appendChild(renderMetrics(page.key_metrics));
  }

  if (page.key_points && page.key_points.length) {
    card.appendChild(el_("div", "section-label", "Key Points"));
    const ul = el_("ul", "key-points");
    for (const kp of page.key_points) ul.appendChild(el_("li", null, kp));
    card.appendChild(ul);
  }

  if (page.tables && page.tables.length) {
    card.appendChild(el_("div", "section-label", "Tables"));
    for (const t of page.tables) card.appendChild(renderTable(t));
  }

  if (page.charts && page.charts.length) {
    card.appendChild(el_("div", "section-label", `Charts & Graphs (${page.charts.length})`));
    for (const c of page.charts) card.appendChild(renderChart(c));
  }

  const hasAnyContent = page.summary || (page.key_metrics || []).length || (page.key_points || []).length ||
    (page.tables || []).length || (page.charts || []).length || page.likely_scanned;
  if (!hasAnyContent) {
    card.appendChild(el_("div", "page-summary", "No extractable content detected on this page."));
  }

  return card;
}

// change like "+18% YoY" -> up, "-4% QoQ" -> down, anything else -> flat
function metricChangeClass(change) {
  if (!change) return "flat";
  if (/^[+]|up|increase|grew|growth/i.test(change)) return "up";
  if (/^[-]|down|decrease|declin|fell/i.test(change)) return "down";
  return "flat";
}

function renderMetrics(metrics) {
  const grid = el_("div", "metrics-grid");
  for (const m of metrics) {
    const card = el_("div", "metric-card");
    card.appendChild(el_("div", "metric-label", m.label));
    card.appendChild(el_("div", "metric-value", m.value));
    if (m.change) {
      card.appendChild(el_("div", `metric-change ${metricChangeClass(m.change)}`, m.change));
    }
    grid.appendChild(card);
  }
  return grid;
}

function renderTable(t) {
  const wrap = el_("table", "data-table");
  if (t.title) wrap.appendChild(el_("caption", null, t.title));
  if (t.columns && t.columns.length) {
    const thead = document.createElement("thead");
    const tr = document.createElement("tr");
    for (const c of t.columns) tr.appendChild(el_("th", null, c));
    thead.appendChild(tr);
    wrap.appendChild(thead);
  }
  const tbody = document.createElement("tbody");
  for (const row of t.rows || []) {
    const tr = document.createElement("tr");
    for (const cell of row) tr.appendChild(el_("td", null, cell));
    tbody.appendChild(tr);
  }
  wrap.appendChild(tbody);
  const block = el_("div");
  block.appendChild(wrap);
  return block;
}

function renderChart(c) {
  const block = el_("div", "chart-block");
  const hasTable = c.data_table && c.data_table.rows && c.data_table.rows.length;
  const grid = el_("div", "chart-grid" + (hasTable ? " has-table" : ""));

  const left = el_("div");
  if (c.chart_type && c.chart_type !== "unknown") {
    left.appendChild(el_("span", "chart-type-tag", c.chart_type));
  }
  if (c.image_url) {
    const img = document.createElement("img");
    img.className = "chart-img";
    img.src = c.image_url;
    img.alt = c.caption || "Extracted chart";
    left.appendChild(img);
  }
  if (c.caption) left.appendChild(el_("div", "chart-caption", c.caption));
  if (c.note) left.appendChild(el_("div", "chart-note", c.note));
  grid.appendChild(left);

  if (hasTable) {
    grid.appendChild(renderTable(c.data_table));
  }

  block.appendChild(grid);
  return block;
}

/* ---------------- Outline / TOC ---------------- */

function renderOutline(doc) {
  if (outlineObserver) {
    outlineObserver.disconnect();
    outlineObserver = null;
  }
  el.outlineList.innerHTML = "";

  const pages = doc && doc.pages ? doc.pages : [];
  if (!doc || pages.length === 0) {
    el.outlineList.appendChild(el_("div", "empty-hint", "Open a document to see its page-by-page outline here."));
    return;
  }

  const itemsByPage = {};
  for (const page of pages) {
    const item = el_("div", "outline-item");
    item.dataset.page = page.page_number;
    item.appendChild(el_("div", "outline-num", String(page.page_number)));
    item.appendChild(el_("div", "outline-heading", page.heading || "(No heading detected)"));
    item.addEventListener("click", () => {
      const target = document.getElementById(`page-${page.page_number}`);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    el.outlineList.appendChild(item);
    itemsByPage[page.page_number] = item;
  }

  // highlight whichever page card is currently in view as the user scrolls
  outlineObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const pageNum = entry.target.id.replace("page-", "");
        const item = itemsByPage[pageNum];
        if (!item) continue;
        item.classList.toggle("active", entry.isIntersecting);
      }
    },
    { root: el.content, rootMargin: "-10% 0px -75% 0px" }
  );
  for (const page of pages) {
    const target = document.getElementById(`page-${page.page_number}`);
    if (target) outlineObserver.observe(target);
  }
}

/* ---------------- Print / export ---------------- */

el.printBtn.addEventListener("click", () => {
  if (!el.printBtn.disabled) window.print();
});

/* ---------------- Search ---------------- */

function clearSearchResults() {
  el.searchResults.hidden = true;
  el.searchResults.innerHTML = "";
}

let searchDebounce = null;
el.searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  const q = el.searchInput.value.trim();
  if (!q || !state.activeId) {
    clearSearchResults();
    return;
  }
  searchDebounce = setTimeout(async () => {
    const results = await apiSearch(state.activeId, q);
    renderSearchResults(results, q);
  }, 200);
});

function renderSearchResults(results, q) {
  el.searchResults.innerHTML = "";
  if (results.length === 0) {
    el.searchResults.hidden = false;
    el.searchResults.appendChild(el_("div", "search-results-title", `No matches for "${q}"`));
    return;
  }
  el.searchResults.hidden = false;
  el.searchResults.appendChild(el_("div", "search-results-title", `${results.length} match${results.length === 1 ? "" : "es"} for "${q}"`));
  for (const r of results) {
    const item = el_("div", "search-result-item");
    item.appendChild(el_("div", "sr-page", `Page ${r.page_number}`));
    item.appendChild(el_("div", "sr-type", r.match_type.replace("_", " ")));
    item.appendChild(el_("div", "sr-snippet", r.snippet));
    item.addEventListener("click", () => {
      const target = document.getElementById(`page-${r.page_number}`);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    el.searchResults.appendChild(item);
  }
}

/* ---------------- Upload ---------------- */

el.fileInput.addEventListener("change", async (ev) => {
  const files = Array.from(ev.target.files || []);
  ev.target.value = "";
  for (const file of files) {
    try {
      const created = await apiUpload(file);
      state.docs.unshift({
        id: created.id,
        filename: created.filename,
        status: "processing",
        num_pages: 0,
        pages_done: 0,
        uploaded_at: new Date().toISOString(),
      });
      renderDocList();
      if (!state.activeId) selectDocument(created.id);
      startPolling(created.id);
    } catch (e) {
      alert(`Could not upload ${file.name}: ${e.message}`);
    }
  }
});

function startPolling(id) {
  stopPolling(id);
  state.pollTimers[id] = setInterval(async () => {
    try {
      const doc = await apiGetDocument(id);
      const idx = state.docs.findIndex((d) => d.id === id);
      if (idx >= 0) state.docs[idx] = { ...state.docs[idx], ...doc };
      if (state.activeId === id) {
        state.activeDoc = doc;
        renderContent();
      }
      renderDocList();
      if (doc.status === "ready" || doc.status === "error") {
        stopPolling(id);
      }
    } catch (e) {
      console.error(e);
    }
  }, 1500);
}

function stopPolling(id) {
  if (state.pollTimers[id]) {
    clearInterval(state.pollTimers[id]);
    delete state.pollTimers[id];
  }
}

/* ---------------- DeepSeek status ---------------- */

async function checkDeepseek() {
  try {
    const res = await apiDeepseekCheck();
    if (res.ok) {
      el.deepseekStatus.innerHTML = `<span class="dot dot-ok"></span> DeepSeek connected (${res.model})`;
    } else {
      el.deepseekStatus.innerHTML = `<span class="dot dot-bad"></span> DeepSeek unavailable — showing raw extraction`;
      el.deepseekStatus.title = res.reason || "";
    }
  } catch {
    el.deepseekStatus.innerHTML = `<span class="dot dot-bad"></span> Could not reach backend`;
  }
}

/* ---------------- Init ---------------- */

(async function init() {
  checkDeepseek();
  try {
    const docs = await apiListDocuments();
    state.docs = docs;
    renderDocList();
    for (const d of docs) {
      if (d.status === "processing") startPolling(d.id);
    }
  } catch (e) {
    console.error("Failed to load documents", e);
  }
})();
