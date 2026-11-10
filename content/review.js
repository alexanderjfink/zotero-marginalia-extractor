"use strict";

/* global window, document */

function el(tag) {
  return document.createElementNS("http://www.w3.org/1999/xhtml", tag);
}

// window.arguments[0] = { session, onApply }
//   session.annotations = rows (see marginaliaExtractor.js::_buildSession)
//   session.pages = [{ unit, pageIndex, pageLabel, widthPts, heightPts, dpi,
//                      model: { sentences: [{text, rects}] }, images: {scan, pdf} }]

const MR_COLORS = [
  ["#ffd400", "yellow"], ["#ff6666", "red"], ["#5fb236", "green"],
  ["#2ea8e5", "blue"], ["#a28ae5", "purple"], ["#e56eee", "magenta"],
  ["#f19837", "orange"], ["#aaaaaa", "grey"],
];

var _mr = {
  session: null,
  rows: [],
  selectedId: null,
  unit: null,
  selectedSentence: null,
  pages: new Map(),
  filters: { search: "", source: "all", flagged: false },
  undoStack: [],
  params: null,
};

function mrInit() {
  const params = window.arguments && window.arguments[0];
  if (!params || !params.session) { window.close(); return; }
  const session = params.session;
  _mr.session = session;
  _mr.params = params;
  _mr.rows = (session.annotations || []).map((row) => Object.assign({}, row));
  for (const page of session.pages || []) _mr.pages.set(page.unit, page);

  const meta = document.getElementById("mr-meta");
  if (meta) {
    meta.textContent =
      `${_mr.rows.length} annotation${_mr.rows.length === 1 ? "" : "s"} · ` +
      `${(session.pages || []).length} page${(session.pages || []).length === 1 ? "" : "s"} · ` +
      `${session.sourcePdf || "PDF"} ← ${session.scanPdf || "scan"}`;
  }
  const warnings = document.getElementById("mr-warnings");
  if (warnings && session.warnings && session.warnings.length) {
    warnings.textContent = "⚠ " + session.warnings.slice(0, 6).join(" · ");
  }

  const pageSelect = document.getElementById("mr-page-select");
  if (pageSelect) {
    pageSelect.innerHTML = "";
    for (const page of session.pages || []) {
      const option = el("option");
      option.value = page.unit;
      option.textContent = `Scan ${page.unit} → PDF ${page.pageLabel || page.pageIndex + 1}`;
      pageSelect.appendChild(option);
    }
    pageSelect.addEventListener("change", () => {
      _mr.unit = pageSelect.value;
      _mr.selectedSentence = null;
      mrRenderPreview();
    });
  }

  document.getElementById("mr-apply")?.addEventListener("click", () => mrApply(params));
  document.getElementById("mr-cancel")?.addEventListener("click", () => window.close());
  document.getElementById("mr-add")?.addEventListener("click", mrAddFromSentence);
  document.getElementById("mr-retarget")?.addEventListener("click", mrRetargetSelected);
  document.addEventListener("keydown", mrKeyDown);

  const search = document.getElementById("mr-search");
  if (search) {
    search.addEventListener("input", () => {
      _mr.filters.search = search.value.trim().toLowerCase();
      mrRenderList();
    });
  }
  const source = document.getElementById("mr-source");
  if (source) {
    source.addEventListener("change", () => {
      _mr.filters.source = source.value;
      mrRenderList();
    });
  }
  const flagged = document.getElementById("mr-flagged");
  if (flagged) {
    flagged.addEventListener("change", () => {
      _mr.filters.flagged = flagged.checked;
      mrRenderList();
    });
  }
  const bulkColor = document.getElementById("mr-bulk-color");
  if (bulkColor) {
    for (const [hex, name] of MR_COLORS) {
      const option = el("option");
      option.value = hex;
      option.textContent = name;
      bulkColor.appendChild(option);
    }
  }
  document.getElementById("mr-select-all")?.addEventListener("click", mrSelectVisible);
  document.getElementById("mr-bulk-color-apply")?.addEventListener("click", () =>
    mrBulkSet("color", document.getElementById("mr-bulk-color")?.value)
  );
  document.getElementById("mr-bulk-type-apply")?.addEventListener("click", () =>
    mrBulkSet("type", document.getElementById("mr-bulk-type")?.value)
  );
  document.getElementById("mr-bulk-delete")?.addEventListener("click", mrBulkDelete);
  document.getElementById("mr-undo")?.addEventListener("click", mrUndo);

  const first = _mr.rows[0];
  if (first) { _mr.selectedId = first.rowId; _mr.unit = first.unit; }
  mrRenderList();
  mrRenderPreview();
  if (pageSelect) pageSelect.value = _mr.unit;
}

// ── List ─────────────────────────────────────────────────────────────────────

function mrRenderList() {
  const list = document.getElementById("mr-list");
  if (!list) return;
  list.innerHTML = "";
  const rows = mrVisibleRows();
  rows.forEach((row) => list.appendChild(mrMakeCard(row)));
  const count = document.getElementById("mr-count");
  if (count) count.textContent = `${rows.length}/${_mr.rows.length}`;
  const selected = list.querySelector(".mr-card.selected");
  if (selected && selected.scrollIntoView) {
    selected.scrollIntoView({ block: "nearest" });
  }
}

function mrIsFlagged(row) {
  const threshold = (_mr.session && _mr.session.defaults && _mr.session.defaults.lowConfidence) || 0.35;
  return row.source === "margin_note" && (row.confidence || 0) < threshold;
}

function mrMatchesFilters(row) {
  if (_mr.filters.flagged && !mrIsFlagged(row)) return false;
  if (_mr.filters.source !== "all" && row.source !== _mr.filters.source) return false;
  if (_mr.filters.search) {
    const haystack = `${row.text || ""} ${row.comment || ""}`.toLowerCase();
    if (!haystack.includes(_mr.filters.search)) return false;
  }
  return true;
}

function mrVisibleRows() {
  return _mr.rows.filter(mrMatchesFilters);
}

function mrSnapshot() {
  _mr.undoStack.push(JSON.parse(JSON.stringify(_mr.rows)));
  if (_mr.undoStack.length > 20) _mr.undoStack.shift();
}

function mrUndo() {
  const previous = _mr.undoStack.pop();
  if (!previous) return;
  _mr.rows = previous;
  if (!_mr.rows.some((row) => row.rowId === _mr.selectedId)) {
    _mr.selectedId = _mr.rows.length ? _mr.rows[0].rowId : null;
  }
  mrRenderList();
  mrRenderPreview();
}

function mrSelectVisible() {
  const visible = mrVisibleRows();
  if (!visible.length) return;
  const allSelected = visible.every((row) => row.selected);
  visible.forEach((row) => { row.selected = !allSelected; });
  mrRenderList();
}

function mrBulkSet(field, value) {
  if (!value) return;
  const selected = _mr.rows.filter((row) => row.selected);
  if (!selected.length) return;
  mrSnapshot();
  selected.forEach((row) => { row[field] = value; });
  mrRenderList();
}

function mrBulkDelete() {
  const selected = _mr.rows.filter((row) => row.selected);
  if (!selected.length) return;
  mrSnapshot();
  selected.forEach((row) => { row.deleted = true; });
  mrRenderList();
}

function mrMakeCard(row) {
  const card = el("div");
  card.className = "mr-card";
  if (row.rowId === _mr.selectedId) card.classList.add("selected");
  if (row.deleted) card.classList.add("deleted");

  const head = el("div");
  head.className = "mr-card-head";

  const bulk = el("input");
  bulk.type = "checkbox";
  bulk.className = "mr-select";
  bulk.checked = !!row.selected;
  bulk.addEventListener("click", (ev) => ev.stopPropagation());
  bulk.addEventListener("change", () => {
    row.selected = bulk.checked;
    card.classList.toggle("checked", bulk.checked);
  });
  head.appendChild(bulk);

  const swatch = el("span");
  swatch.className = "mr-swatch";
  swatch.style.background = row.color || "#ffd400";
  head.appendChild(swatch);

  const colorSel = el("select");
  for (const [hex, name] of MR_COLORS) {
    const o = el("option");
    o.value = hex; o.textContent = name;
    if (hex.toLowerCase() === (row.color || "").toLowerCase()) o.selected = true;
    colorSel.appendChild(o);
  }
  colorSel.addEventListener("change", (ev) => {
    ev.stopPropagation();
    mrSnapshot();
    row.color = colorSel.value;
    swatch.style.background = row.color;
  });
  head.appendChild(colorSel);

  const typeSel = el("select");
  for (const t of ["highlight", "underline", "note"]) {
    const o = el("option");
    o.value = t; o.textContent = t;
    if (t === row.type) o.selected = true;
    typeSel.appendChild(o);
  }
  typeSel.addEventListener("change", (ev) => {
    ev.stopPropagation();
    mrSnapshot();
    row.type = typeSel.value;
  });
  head.appendChild(typeSel);

  const method = el("span");
  method.className = "mr-method";
  if (row.source === "margin_note") {
    const conf = Math.round((row.confidence || 0) * 100);
    method.textContent = `${row.method || "?"} · ${conf}%`;
    if ((row.confidence || 0) < 0.35) method.classList.add("mr-low");
  } else {
    method.textContent = "colour";
  }
  head.appendChild(method);

  const delLabel = el("label");
  delLabel.style.marginLeft = "auto";
  delLabel.style.fontSize = "0.82em";
  const del = el("input");
  del.type = "checkbox";
  del.checked = !!row.deleted;
  del.addEventListener("click", (ev) => ev.stopPropagation());
  del.addEventListener("change", () => {
    mrSnapshot();
    row.deleted = del.checked;
    card.classList.toggle("deleted", row.deleted);
  });
  delLabel.appendChild(del);
  delLabel.appendChild(document.createTextNode(" delete"));
  head.appendChild(delLabel);
  card.appendChild(head);

  const text = el("div");
  text.className = "mr-card-text";
  text.textContent = row.text || "(no matched text — positioned geometrically)";
  if (row.nextPageRects && row.nextPageRects.length) {
    text.textContent += " ↪ continues on the next page";
  }
  card.appendChild(text);

  const comment = el("input");
  comment.type = "text";
  comment.className = "mr-comment";
  comment.placeholder = "Note / comment";
  comment.value = row.comment || "";
  comment.addEventListener("click", (ev) => ev.stopPropagation());
  comment.addEventListener("input", () => { row.comment = comment.value; });
  card.appendChild(comment);

  card.addEventListener("click", () => {
    _mr.selectedId = row.rowId;
    _mr.unit = row.unit;
    _mr.selectedSentence = null;
    const select = document.getElementById("mr-page-select");
    if (select) select.value = _mr.unit;
    mrRenderList();
    mrRenderPreview();
  });

  return card;
}

// ── Preview ──────────────────────────────────────────────────────────────────

function mrSelectedRow() {
  return _mr.rows.find((row) => row.rowId === _mr.selectedId) || null;
}

function mrPage() {
  return _mr.pages.get(_mr.unit) || null;
}

function mrRenderPreview() {
  const row = mrSelectedRow();
  const page = mrPage();
  const info = document.getElementById("mr-page-info");
  if (!page) {
    if (info) info.textContent = "";
    return;
  }
  if (info) {
    const align = page.alignment ? ` · align ${Math.round((page.alignment.confidence || 0) * 100)}%` : "";
    info.textContent = `PDF page ${page.pageLabel || page.pageIndex + 1}${align}`;
  }

  const scanImg = document.getElementById("mr-scan-img");
  const pdfImg = document.getElementById("mr-pdf-img");
  mrSetImage(scanImg, page.images && page.images.scan);
  mrSetImage(pdfImg, page.images && page.images.pdf);

  mrRenderOverlays(row, page);
  mrRenderSentences(row, page);
  mrRenderNextPage(row);
}

function mrRenderNextPage(row) {
  const wrap = document.getElementById("mr-next-images");
  if (!wrap) return;
  const nextPage = row && row.nextPageIndex !== null && row.nextPageIndex !== undefined
    ? (_mr.session.pages || []).find((page) => page.pageIndex === row.nextPageIndex)
    : null;
  const rects = (row && row.nextPageRects) || [];
  if (!nextPage || !rects.length) {
    wrap.style.display = "none";
    return;
  }
  const scanUrl = nextPage.images && nextPage.images.scan;
  const pdfUrl = nextPage.images && nextPage.images.pdf;
  if (!scanUrl && !pdfUrl) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "flex";
  mrSetImage(document.getElementById("mr-next-scan-img"), scanUrl);
  mrSetImage(document.getElementById("mr-next-pdf-img"), pdfUrl);

  const scanOverlay = document.getElementById("mr-next-scan-overlay");
  const pdfOverlay = document.getElementById("mr-next-pdf-overlay");
  if (!scanOverlay || !pdfOverlay) return;
  scanOverlay.innerHTML = "";
  pdfOverlay.innerHTML = "";
  for (const box of mrRectsToBoxes(rects, nextPage.widthPts, nextPage.heightPts, false)) {
    scanOverlay.appendChild(mrBox(box));
    pdfOverlay.appendChild(mrBox(box));
  }
}

function mrSetImage(img, url) {
  if (!img) return;
  if (!url) {
    img.removeAttribute("src");
    img.style.visibility = "hidden";
    return;
  }
  img.style.visibility = "visible";
  img.onerror = () => { img.style.visibility = "hidden"; };
  if (img.getAttribute("src") !== url) img.src = url;
}

function mrRenderOverlays(row, page) {
  const scanOverlay = document.getElementById("mr-scan-overlay");
  const pdfOverlay = document.getElementById("mr-pdf-overlay");
  if (!scanOverlay || !pdfOverlay) return;
  scanOverlay.innerHTML = "";
  pdfOverlay.innerHTML = "";

  if (!row || row.unit !== page.unit) return;

  // Current target.
  for (const box of mrRectsToBoxes(row.rects, page.widthPts, page.heightPts, false)) {
    scanOverlay.appendChild(mrBox(box));
    pdfOverlay.appendChild(mrBox(box));
  }

  // Suggested candidates (clickable).
  const suggestions = row.candidates || [];
  suggestions.forEach((candidate) => {
    const boxes = mrPointRectsToBoxes(candidate.rects, page.widthPts, page.heightPts, true);
    boxes.forEach((box) => {
      box.onClick = () => mrApplyTarget(row, page, candidate);
      scanOverlay.appendChild(mrBox(box));
      pdfOverlay.appendChild(mrBox(box));
    });
  });
}

function mrBox(box) {
  const el = el("div");
  el.className = "mr-box" + (box.candidate ? " candidate" : "");
  el.style.left = box.left + "%";
  el.style.top = box.top + "%";
  el.style.width = box.width + "%";
  el.style.height = box.height + "%";
  if (box.onClick) {
    el.title = "Use this sentence as the target";
    el.addEventListener("click", (ev) => { ev.stopPropagation(); box.onClick(); });
  }
  return el;
}

function mrRectsToBoxes(rects, widthPts, heightPts, candidate) {
  if (!rects || !widthPts || !heightPts) return [];
  return rects.map(([x0, y0, x1, y1]) => ({
    left: (x0 / widthPts) * 100,
    top: ((heightPts - y1) / heightPts) * 100,
    width: ((x1 - x0) / widthPts) * 100,
    height: ((y1 - y0) / heightPts) * 100,
    candidate,
  }));
}

function mrPointRectsToBoxes(rects, widthPts, heightPts, candidate) {
  if (!rects || !widthPts || !heightPts) return [];
  return rects.map(([x0, y0, x1, y1]) => ({
    left: (x0 / widthPts) * 100,
    top: (y0 / heightPts) * 100,
    width: ((x1 - x0) / widthPts) * 100,
    height: ((y1 - y0) / heightPts) * 100,
    candidate,
  }));
}

function mrRenderSentences(row, page) {
  const container = document.getElementById("mr-sentences");
  if (!container) return;
  container.innerHTML = "";
  const sentences = (page.model && page.model.sentences) || [];
  if (!sentences.length) {
    const empty = el("div");
    empty.className = "mr-sentence";
    empty.textContent = "No sentence model for this page.";
    container.appendChild(empty);
    return;
  }
  const suggested = new Set(((row && row.candidates) || []).map((c) => c.text));
  const currentText = row && row.unit === page.unit ? row.text : null;
  const chosen = _mr.selectedSentence;

  sentences.forEach((sentence) => {
    const button = el("button");
    button.className = "mr-sentence";
    if (currentText && sentence.text === currentText) button.classList.add("current");
    if (chosen && chosen.page.unit === page.unit && chosen.sentence.text === sentence.text) {
      button.classList.add("selected-sentence");
    }
    if (suggested.has(sentence.text)) {
      const badge = el("span");
      badge.className = "mr-sug";
      badge.textContent = "★";
      button.appendChild(badge);
    }
    button.appendChild(document.createTextNode(sentence.text));
    button.addEventListener("click", () => {
      _mr.selectedSentence = { page, sentence };
      mrRenderSentences(row, page);
    });
    container.appendChild(button);
  });
}

// ── Actions ──────────────────────────────────────────────────────────────────

function mrApplyTarget(row, page, sentence) {
  mrSnapshot();
  row.unit = page.unit;
  row.pageIndex = page.pageIndex;
  row.pageLabel = page.pageLabel;
  row.rects = mrPointRectsToZotero(sentence.rects, page.heightPts);
  row.text = sentence.text;
  row.method = "manual";
  row.confidence = 1;
  row.candidates = [];
  row.nextPageRects = [];
  row.nextPageIndex = null;
  row.sortIndex = mrSortIndex(page.pageIndex, row.rects, page.heightPts);
  _mr.unit = page.unit;
  _mr.selectedSentence = null;
  const select = document.getElementById("mr-page-select");
  if (select) select.value = page.unit;
  mrRenderList();
  mrRenderPreview();
}

function mrRetargetSelected() {
  const selected = _mr.selectedSentence;
  const row = mrSelectedRow();
  const status = document.getElementById("mr-status");
  if (!selected || !row) {
    if (status) status.textContent = "Select a row and a sentence first.";
    return;
  }
  mrApplyTarget(row, selected.page, selected.sentence);
}

function mrPointRectsToZotero(rects, heightPts) {
  return (rects || []).map(([x0, y0, x1, y1]) => [x0, heightPts - y1, x1, heightPts - y0]);
}

function mrSortIndex(pageIndex, rects, heightPts) {
  const top = rects && rects.length
    ? Math.max(...rects.map((r) => heightPts - r[3]))
    : 0;
  return `${String(pageIndex).padStart(5, "0")}|000000|${String(Math.max(0, Math.round(top))).padStart(5, "0")}`;
}

function mrAddFromSentence() {
  const selected = _mr.selectedSentence;
  if (!selected) {
    const status = document.getElementById("mr-status");
    if (status) status.textContent = "Click a sentence first, then add.";
    return;
  }
  const { page, sentence } = selected;
  const defaults = (_mr.session && _mr.session.defaults) || {};
  const rects = mrPointRectsToZotero(sentence.rects, page.heightPts);
  mrSnapshot();
  const row = {
    rowId: "new-" + Date.now() + "-" + Math.random().toString(36).slice(2, 6),
    unit: page.unit,
    scanLabel: page.unit,
    pageIndex: page.pageIndex,
    pageLabel: page.pageLabel,
    type: defaults.type || "highlight",
    color: defaults.color || "#ffd400",
    rects,
    text: sentence.text,
    comment: "",
    source: "manual",
    method: "manual",
    confidence: 1,
    sortIndex: mrSortIndex(page.pageIndex, rects, page.heightPts),
    nextPageRects: [],
    nextPageIndex: null,
    candidates: [],
    deleted: false,
  };
  _mr.rows.push(row);
  _mr.selectedId = row.rowId;
  _mr.unit = page.unit;
  _mr.selectedSentence = null;
  mrRenderList();
  mrRenderPreview();
}

function mrKeyDown(event) {
  const target = event.target;
  const tag = (target && target.tagName ? target.tagName : "").toLowerCase();
  if (["input", "textarea", "select"].includes(tag) || (target && target.isContentEditable)) {
    return;
  }
  const key = event.key;
  if (key === "Escape") {
    window.close();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && key === "Enter") {
    event.preventDefault();
    if (_mr.params) mrApply(_mr.params);
    return;
  }
  if ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "z") {
    event.preventDefault();
    mrUndo();
    return;
  }
  if (key === "?") {
    event.preventDefault();
    window.alert(
      "Review shortcuts\n\n" +
      "j / ↓  next row\n" +
      "k / ↑  previous row\n" +
      "Home / End  first / last\n" +
      "d  toggle delete\n" +
      "c  cycle colour\n" +
      "t  cycle type\n" +
      "Enter  edit comment\n" +
      "Ctrl+Z  undo\n" +
      "Ctrl+Enter  apply\n" +
      "Escape  close"
    );
    return;
  }
  const row = mrSelectedRow();
  if (row && key === "d") {
    event.preventDefault();
    mrSnapshot();
    row.deleted = !row.deleted;
    mrRenderList();
    return;
  }
  if (row && key === "c") {
    event.preventDefault();
    const index = MR_COLORS.findIndex(([hex]) => hex.toLowerCase() === (row.color || "").toLowerCase());
    row.color = MR_COLORS[(index + 1) % MR_COLORS.length][0];
    mrSnapshot();
    mrRenderList();
    return;
  }
  if (row && key === "t") {
    event.preventDefault();
    const types = ["highlight", "underline", "note"];
    const index = types.indexOf(row.type);
    row.type = types[(index + 1) % types.length];
    mrSnapshot();
    mrRenderList();
    return;
  }
  if (row && key === "Enter") {
    event.preventDefault();
    const card = document.querySelector(".mr-card.selected");
    const comment = card && card.querySelector("input.mr-comment");
    if (comment) comment.focus();
    return;
  }
  if (key === "j" || key === "ArrowDown") {
    event.preventDefault();
    mrSelectRelative(1);
  } else if (key === "k" || key === "ArrowUp") {
    event.preventDefault();
    mrSelectRelative(-1);
  } else if (key === "Home") {
    event.preventDefault();
    mrSelectIndex(0);
  } else if (key === "End") {
    event.preventDefault();
    mrSelectIndex(_mr.rows.length - 1);
  }
}

function mrSelectRelative(delta) {
  const visible = mrVisibleRows();
  if (!visible.length) return;
  const index = visible.findIndex((row) => row.rowId === _mr.selectedId);
  const target = index < 0 ? 0 : Math.max(0, Math.min(visible.length - 1, index + delta));
  mrSelectRowObject(visible[target]);
}

function mrSelectIndex(index) {
  const visible = mrVisibleRows();
  if (!visible.length) return;
  const clamped = Math.max(0, Math.min(visible.length - 1, index));
  mrSelectRowObject(visible[clamped]);
}

function mrSelectRowObject(row) {
  _mr.selectedId = row.rowId;
  _mr.unit = row.unit;
  _mr.selectedSentence = null;
  const select = document.getElementById("mr-page-select");
  if (select) select.value = _mr.unit;
  mrRenderList();
  mrRenderPreview();
}

function mrApply(params) {
  const rows = _mr.rows.map((row) => ({
    rowId: row.rowId,
    unit: row.unit,
    scanLabel: row.scanLabel || row.unit,
    pageIndex: row.pageIndex,
    pageLabel: row.pageLabel,
    type: row.type,
    color: row.color,
    rects: row.rects,
    text: row.text,
    comment: row.comment,
    source: row.source,
    method: row.method,
    confidence: row.confidence,
    sortIndex: row.sortIndex,
    nextPageRects: row.nextPageRects || [],
    deleted: !!row.deleted,
  }));
  const status = document.getElementById("mr-status");
  if (status) status.textContent = "Applying…";
  try {
    params.onApply(rows);
  } catch (e) {
    if (status) status.textContent = "Error: " + e;
    return;
  }
  window.close();
}

window.addEventListener("load", mrInit);
