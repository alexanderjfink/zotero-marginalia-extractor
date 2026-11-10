"use strict";

/* global window, document */

function el(tag) {
  return document.createElementNS("http://www.w3.org/1999/xhtml", tag);
}

// window.arguments[0] = { mapping, pdfPages, warnings, result: null }
// result: { accept: true, overrides: { [scanLabel]: pdfIndex } }

var _mm = { mapping: [], pdfPages: [] };

function mmInit() {
  const args = window.arguments && window.arguments[0];
  if (!args) { window.close(); return; }
  _mm.mapping = args.mapping || [];
  _mm.pdfPages = args.pdfPages || [];

  const warnings = document.getElementById("mm-warnings");
  if (warnings && args.warnings && args.warnings.length) {
    warnings.textContent = "⚠ " + args.warnings.slice(0, 8).join(" · ");
  }

  const body = document.getElementById("mm-body");
  body.innerHTML = "";
  if (!_mm.mapping.length) {
    const tr = el("tr");
    const td = el("td");
    td.colSpan = 3;
    td.textContent = "No scan pages were found.";
    tr.appendChild(td);
    body.appendChild(tr);
  }
  _mm.mapping.forEach((unit, index) => body.appendChild(mmRow(unit, index)));

  document.getElementById("mm-cancel")?.addEventListener("click", () => window.close());
  document.getElementById("mm-accept")?.addEventListener("click", () => mmAccept(args));
}

function mmRow(unit, index) {
  const tr = el("tr");

  const scanCell = el("td");
  scanCell.textContent = unit.label || String(unit.scan_index + 1);
  tr.appendChild(scanCell);

  const selectCell = el("td");
  const select = el("select");
  for (const page of _mm.pdfPages) {
    const option = el("option");
    option.value = String(page.index);
    option.textContent = `PDF ${page.label || page.index + 1} (page ${page.index + 1})`;
    if (page.index === unit.pdf_index) option.selected = true;
    select.appendChild(option);
  }
  if (unit.pdf_index === null || unit.pdf_index === undefined) {
    select.selectedIndex = 0;
    const option = el("option");
    option.value = "";
    option.textContent = "(unmatched — choose a page)";
    option.selected = true;
    select.insertBefore(option, select.firstChild);
  }
  select.dataset.index = String(index);
  select.dataset.label = unit.label || String(unit.scan_index + 1);
  select.dataset.original = unit.pdf_index === null || unit.pdf_index === undefined ? "" : String(unit.pdf_index);
  selectCell.appendChild(select);
  tr.appendChild(selectCell);

  const methodCell = el("td");
  methodCell.className = "mm-method";
  methodCell.textContent = unit.match_method || "";
  if (!unit.pdf_index) methodCell.classList.add("mm-warn");
  tr.appendChild(methodCell);

  return tr;
}

function mmAccept(args) {
  const overrides = {};
  for (const select of document.querySelectorAll("#mm-body select")) {
    const value = select.value;
    if (value === "") continue;
    const index = parseInt(value, 10);
    const original = select.dataset.original;
    if (Number.isFinite(index) && String(index) !== original) {
      overrides[select.dataset.label] = index;
    }
  }
  args.result = { accept: true, overrides };
  window.close();
}

window.addEventListener("load", mmInit);
