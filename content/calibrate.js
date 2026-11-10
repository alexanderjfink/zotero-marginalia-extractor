"use strict";

/* global window, document, Components */

// window.arguments[0] = { colors: [...], result: null }
// On "Add colour rule": window.arguments[0].result = rule; window.close()

var _mc = {
  displayCanvas: null,
  fullCanvas: null,
  scale: 1,
  sample: null,
  dragging: false,
  dragStart: null,
  dragEnd: null,
};

function mcInit() {
  _mc.displayCanvas = document.getElementById("mc-canvas");
  document.getElementById("mc-open")?.addEventListener("click", mcOpenImage);
  document.getElementById("mc-cancel")?.addEventListener("click", () => window.close());
  document.getElementById("mc-add")?.addEventListener("click", mcAddRule);
  _mc.displayCanvas?.addEventListener("mousedown", mcMouseDown);
  _mc.displayCanvas?.addEventListener("mousemove", mcMouseMove);
  _mc.displayCanvas?.addEventListener("mouseup", mcMouseUp);
}

function mcOpenImage() {
  try {
    const nsIFilePicker = Components.interfaces.nsIFilePicker;
    const picker = Components.classes["@mozilla.org/filepicker;1"].createInstance(nsIFilePicker);
    picker.init(window, "Choose a page image", nsIFilePicker.modeOpen);
    try { picker.appendFilters(nsIFilePicker.filterImages); } catch (_) {}
    const done = (rv) => {
      if (rv !== nsIFilePicker.returnOK || !picker.file) return;
      mcLoadImage(picker.file.path);
    };
    const maybe = picker.open(done);
    if (maybe && typeof maybe.then === "function") {
      maybe.then(() => done(nsIFilePicker.returnOK)).catch(() => {});
    }
  } catch (_) {}
}

async function mcLoadImage(path) {
  const fileLabel = document.getElementById("mc-file");
  if (fileLabel) fileLabel.textContent = path;
  const url = await mcImageURL(path);

  const image = new window.Image();
  image.onload = () => {
    const maxW = 820;
    const maxH = 460;
    const scale = Math.min(1, maxW / image.naturalWidth, maxH / image.naturalHeight);
    _mc.scale = scale;

    const full = document.createElementNS("http://www.w3.org/1999/xhtml", "canvas");
    full.width = image.naturalWidth;
    full.height = image.naturalHeight;
    try {
      full.getContext("2d").drawImage(image, 0, 0);
      _mc.fullCanvas = full;
    } catch (e) {
      if (fileLabel) fileLabel.textContent = "Could not decode that image.";
      return;
    }

    const display = _mc.displayCanvas;
    display.width = Math.max(1, Math.round(image.naturalWidth * scale));
    display.height = Math.max(1, Math.round(image.naturalHeight * scale));
    display.getContext("2d").drawImage(image, 0, 0, display.width, display.height);
    mcSetSample(null);
  };
  image.onerror = () => {
    if (fileLabel) fileLabel.textContent = "Could not load that image.";
  };
  image.src = url;
}

async function mcImageURL(path) {
  try {
    const binary = await Zotero.File.getBinaryContentsAsync(path);
    const lower = path.toLowerCase();
    let mime = "image/png";
    if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) mime = "image/jpeg";
    else if (lower.endsWith(".webp")) mime = "image/webp";
    else if (lower.endsWith(".gif")) mime = "image/gif";
    return `data:${mime};base64,${window.btoa(binary)}`;
  } catch (_) {
    return "file://" + encodeURI(path.startsWith("/") ? path : "/" + path);
  }
}

function mcCanvasPoint(event) {
  const rect = _mc.displayCanvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(_mc.displayCanvas.width, event.clientX - rect.left));
  const y = Math.max(0, Math.min(_mc.displayCanvas.height, event.clientY - rect.top));
  return { x, y };
}

function mcMouseDown(event) {
  if (!_mc.fullCanvas) return;
  _mc.dragging = true;
  _mc.dragStart = mcCanvasPoint(event);
  _mc.dragEnd = _mc.dragStart;
  mcDrawSelection();
}

function mcMouseMove(event) {
  if (!_mc.dragging) return;
  _mc.dragEnd = mcCanvasPoint(event);
  mcDrawSelection();
}

function mcMouseUp(event) {
  if (!_mc.dragging) return;
  _mc.dragging = false;
  _mc.dragEnd = mcCanvasPoint(event);
  mcDrawSelection();
  mcSampleSelection();
}

function mcDrawSelection() {
  const selection = document.getElementById("mc-selection");
  if (!selection || !_mc.dragStart || !_mc.dragEnd) return;
  const x0 = Math.min(_mc.dragStart.x, _mc.dragEnd.x);
  const y0 = Math.min(_mc.dragStart.y, _mc.dragEnd.y);
  const w = Math.abs(_mc.dragEnd.x - _mc.dragStart.x);
  const h = Math.abs(_mc.dragEnd.y - _mc.dragStart.y);
  if (w < 1 && h < 1) {
    selection.style.display = "none";
    return;
  }
  selection.style.display = "block";
  selection.style.left = x0 + "px";
  selection.style.top = y0 + "px";
  selection.style.width = w + "px";
  selection.style.height = h + "px";
}

function mcSampleSelection() {
  if (!_mc.fullCanvas || !_mc.dragStart || !_mc.dragEnd) return;
  const x0 = Math.min(_mc.dragStart.x, _mc.dragEnd.x) / _mc.scale;
  const y0 = Math.min(_mc.dragStart.y, _mc.dragEnd.y) / _mc.scale;
  const x1 = Math.max(_mc.dragStart.x, _mc.dragEnd.x) / _mc.scale;
  const y1 = Math.max(_mc.dragStart.y, _mc.dragEnd.y) / _mc.scale;

  let left = Math.floor(x0);
  let top = Math.floor(y0);
  let width = Math.max(1, Math.ceil(x1 - x0));
  let height = Math.max(1, Math.ceil(y1 - y0));

  if (width < 3 && height < 3) {
    // A click: sample a small patch around it.
    const pad = 4;
    left = Math.max(0, left - pad);
    top = Math.max(0, top - pad);
    width = 9;
    height = 9;
  }
  const canvasW = _mc.fullCanvas.width;
  const canvasH = _mc.fullCanvas.height;
  left = Math.max(0, Math.min(canvasW - 1, left));
  top = Math.max(0, Math.min(canvasH - 1, top));
  width = Math.max(1, Math.min(canvasW - left, width));
  height = Math.max(1, Math.min(canvasH - top, height));

  const data = (() => {
    try {
      return _mc.fullCanvas.getContext("2d").getImageData(left, top, width, height).data;
    } catch (e) {
      const readout = document.getElementById("mc-readout");
      if (readout) readout.textContent = "Canvas blocked by security policy — use a PNG/JPG export.";
      return null;
    }
  })();
  if (!data) return;
  let r = 0, g = 0, b = 0, count = 0;
  for (let i = 0; i < data.length; i += 4) {
    r += data[i]; g += data[i + 1]; b += data[i + 2]; count++;
  }
  if (!count) return;
  r = Math.round(r / count); g = Math.round(g / count); b = Math.round(b / count);
  mcSetSample({ r, g, b, ...mcRgbToHsv(r, g, b) });
}

function mcSetSample(sample) {
  _mc.sample = sample;
  const swatch = document.getElementById("mc-swatch");
  const readout = document.getElementById("mc-readout");
  if (!sample) {
    if (swatch) swatch.style.background = "transparent";
    if (readout) readout.textContent = "click the image";
    return;
  }
  if (swatch) swatch.style.background = `rgb(${sample.r},${sample.g},${sample.b})`;
  if (readout) {
    readout.textContent =
      `RGB ${sample.r},${sample.g},${sample.b} · H ${sample.h} S ${sample.s} V ${sample.v}`;
  }
  mcGuessKind(sample);
}

function mcGuessKind(sample) {
  const kind = document.getElementById("mc-kind");
  if (!kind) return;
  if (sample.s < 40) kind.value = "pen";
  else if (sample.v > 170 && sample.s > 60) kind.value = "highlighter";
}

function mcRgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  let h = 0;
  if (delta > 0) {
    if (max === r) h = ((g - b) / delta) % 6;
    else if (max === g) h = (b - r) / delta + 2;
    else h = (r - g) / delta + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  const s = max === 0 ? 0 : delta / max;
  return {
    h: Math.round(h / 2),          // OpenCV 0-179
    s: Math.round(s * 255),
    v: Math.round(max * 255),
  };
}

function mcAddRule() {
  const sample = _mc.sample;
  if (!sample) {
    const readout = document.getElementById("mc-readout");
    if (readout) readout.textContent = "click the image first";
    return;
  }
  const args = window.arguments && window.arguments[0];
  const name = (document.getElementById("mc-name")?.value || "sampled").trim() || "sampled";
  const zotero = document.getElementById("mc-zotero")?.value || "yellow";
  const kind = document.getElementById("mc-kind")?.value || "any";
  const tolerance = Math.max(1, Math.min(40, parseInt(document.getElementById("mc-tolerance")?.value, 10) || 10));

  let rule;
  if (sample.s < 40) {
    // Dark/black ink: hue is meaningless; bound the value instead.
    rule = {
      name, zotero, kind: "pen",
      hue_min: 0, hue_max: 179,
      sat_min: 0, sat_max: 255,
      val_min: 0, val_max: Math.min(255, sample.v + 40),
      enabled: true,
    };
  } else {
    const hueMin = (sample.h - tolerance + 180) % 180;
    const hueMax = (sample.h + tolerance) % 180;
    const isPen = kind === "pen";
    rule = {
      name, zotero, kind,
      hue_min: hueMin,
      hue_max: hueMax,
      sat_min: Math.max(0, sample.s - (isPen ? 70 : 55)),
      sat_max: 255,
      val_min: Math.max(0, sample.v - (isPen ? 90 : 50)),
      val_max: Math.min(255, sample.v + (isPen ? 30 : 45)),
      enabled: true,
    };
  }
  if (args) args.result = rule;
  window.close();
}

window.addEventListener("load", mcInit);
