"use strict";

/* global Components, Zotero, window, document */

function el(tag) {
  return document.createElementNS("http://www.w3.org/1999/xhtml", tag);
}

const ZM_PREFIX = "extensions.marginalia-extractor@zotero-marginalia-extractor.";

function _zmPrefs() {
  return Components.classes["@mozilla.org/preferences-service;1"]
    .getService(Components.interfaces.nsIPrefBranch);
}

function _zmGet(key, fallback) {
  try {
    const p = _zmPrefs();
    const full = ZM_PREFIX + key;
    const t = p.getPrefType(full);
    if (t === 0) return fallback;
    if (t === 128) return p.getBoolPref(full);
    if (t === 64) return p.getIntPref(full);
    return p.getStringPref(full);
  } catch (_) {
    return fallback;
  }
}

function _zmSet(key, value) {
  try {
    const p = _zmPrefs();
    const full = ZM_PREFIX + key;
    if (typeof value === "boolean") p.setBoolPref(full, value);
    else if (typeof value === "number") p.setIntPref(full, value);
    else p.setStringPref(full, String(value));
  } catch (e) {
    dump("[Marginalia] prefs set failed (" + key + "): " + e + "\n");
  }
}

const ZM_ZOTERO_COLORS = ["yellow", "red", "green", "blue", "purple", "magenta", "orange", "grey"];
const ZM_OUTPUTS = ["auto", "highlight", "underline", "note"];

const ZM_DEFAULT_COLORS = [
  { name: "yellow",   zotero: "yellow", output: "auto", hue_min: 20,  hue_max: 38,  sat_min: 70, val_min: 60, sat_max: 255, val_max: 255, enabled: true, kind: "any" },
  { name: "red",      zotero: "red",    output: "auto", hue_min: 0,   hue_max: 8,   sat_min: 70, val_min: 60, sat_max: 255, val_max: 255, enabled: true, kind: "any" },
  { name: "pink",     zotero: "red",    output: "auto", hue_min: 165, hue_max: 179, sat_min: 60, val_min: 60, sat_max: 255, val_max: 255, enabled: true, kind: "any" },
  { name: "green",    zotero: "green",  output: "auto", hue_min: 40,  hue_max: 85,  sat_min: 60, val_min: 60, sat_max: 255, val_max: 255, enabled: true, kind: "any" },
  { name: "blue",     zotero: "blue",   output: "auto", hue_min: 90,  hue_max: 130, sat_min: 60, val_min: 60, sat_max: 255, val_max: 255, enabled: true, kind: "any" },
  { name: "purple",   zotero: "purple", output: "auto", hue_min: 130, hue_max: 165, sat_min: 50, val_min: 60, sat_max: 255, val_max: 255, enabled: true, kind: "any" },
  { name: "blue-pen", zotero: "blue",   output: "auto", hue_min: 100, hue_max: 130, sat_min: 80, val_min: 0,  sat_max: 255, val_max: 180, enabled: true, kind: "pen" },
  { name: "red-pen",  zotero: "red",    output: "auto", hue_min: 0,   hue_max: 8,   sat_min: 80, val_min: 0,  sat_max: 255, val_max: 180, enabled: true, kind: "pen" },
];

// Settings exposed in the panel, in load/save/export order.
const ZM_CONTROLS = [
  { key: "pythonPath", id: "me-python-path", type: "text", fallback: "python3" },
  { key: "helperDir", id: "me-helper-dir", type: "text", fallback: "" },
  { key: "autoBinary", id: "me-auto-binary", type: "bool", fallback: true },
  { key: "pageOffset", id: "me-page-offset", type: "int", fallback: 0 },
  { key: "matchPages", id: "me-match-pages", type: "bool", fallback: true },
  { key: "splitSpreads", id: "me-split-spreads", type: "bool", fallback: false },
  { key: "mergeCrossPage", id: "me-merge-cross-page", type: "bool", fallback: true },
  { key: "perspectiveCorrect", id: "me-perspective", type: "bool", fallback: true },
  { key: "deskew", id: "me-deskew", type: "bool", fallback: true },
  { key: "removeShadows", id: "me-remove-shadows", type: "bool", fallback: true },
  { key: "whiteBalance", id: "me-white-balance", type: "bool", fallback: true },
  { key: "dpi", id: "me-dpi", type: "int", fallback: 200 },
  { key: "markMode", id: "me-mark-mode", type: "menu", fallback: "both" },
  { key: "noteFallbackColor", id: "me-note-color", type: "menu", fallback: "yellow" },
  { key: "colorSpace", id: "me-color-space", type: "menu", fallback: "hsv" },
  { key: "detectDarkUnderlines", id: "me-dark-underlines", type: "bool", fallback: true },
  { key: "darkUnderlineColor", id: "me-dark-underline-color", type: "menu", fallback: "grey" },
  { key: "ocrBackend", id: "me-ocr-backend", type: "menu", fallback: "tesseract" },
  { key: "llmUrl", id: "me-llm-url", type: "text", fallback: "" },
  { key: "llmModel", id: "me-llm-model", type: "text", fallback: "" },
  { key: "llmApiKey", id: "me-llm-key", type: "text", fallback: "" },
  { key: "llmApiKeyEnv", id: "me-llm-key-env", type: "text", fallback: "MARGINALIA_LLM_API_KEY" },
  { key: "llmPrompt", id: "me-llm-prompt", type: "text", fallback: "" },
  { key: "llmTimeout", id: "me-llm-timeout", type: "int", fallback: 180 },
  { key: "llmMaxTokens", id: "me-llm-max-tokens", type: "int", fallback: 1024 },
  { key: "llmTemperature", id: "me-llm-temperature", type: "float", fallback: 0 },
  { key: "ocrLang", id: "me-ocr-lang", type: "text", fallback: "eng" },
  { key: "ocrLineSplit", id: "me-ocr-line-split", type: "bool", fallback: true },
  { key: "ocrDetectOrientation", id: "me-ocr-orientation", type: "bool", fallback: true },
  { key: "ocrPdfPages", id: "me-ocr-pdf", type: "bool", fallback: true },
  { key: "maxCandidates", id: "me-max-candidates", type: "int", fallback: 4 },
  { key: "lowConfidence", id: "me-low-confidence", type: "float", fallback: 0.35 },
  { key: "defaultNewColor", id: "me-default-new-color", type: "menu", fallback: "#ffd400" },
  { key: "defaultNewType", id: "me-default-new-type", type: "menu", fallback: "highlight" },
  { key: "replacePrevious", id: "me-replace-previous", type: "bool", fallback: true },
  { key: "commentPrefix", id: "me-comment-prefix", type: "text", fallback: "" },
  { key: "commentSuffix", id: "me-comment-suffix", type: "text", fallback: "" },
  { key: "appendScanSource", id: "me-append-source", type: "bool", fallback: false },
  { key: "minHighlightArea", id: "me-min-highlight", type: "int", fallback: 120 },
  { key: "minNoteArea", id: "me-min-note", type: "int", fallback: 60 },
  { key: "marginFraction", id: "me-margin-fraction", type: "float", fallback: 0.18 },
];

const ZM_BUILTIN_PROFILES = {
  Essay: {
    dpi: 200, markMode: "both", matchPages: true, splitSpreads: false,
    perspectiveCorrect: true, deskew: true, removeShadows: true, whiteBalance: true,
    colorSpace: "hsv", pageOffset: 0, ocrLineSplit: true, ocrDetectOrientation: true,
    ocrPdfPages: true, maxCandidates: 4, replacePrevious: true,
  },
  "Book spread": {
    dpi: 200, markMode: "both", matchPages: true, splitSpreads: true,
    perspectiveCorrect: false, deskew: true, removeShadows: true, whiteBalance: true,
    colorSpace: "lab", pageOffset: 0, ocrLineSplit: true, ocrDetectOrientation: true,
    ocrPdfPages: true, maxCandidates: 4, replacePrevious: true,
  },
  "Phone photo": {
    dpi: 220, markMode: "both", matchPages: true, splitSpreads: false,
    perspectiveCorrect: true, deskew: true, removeShadows: true, whiteBalance: true,
    colorSpace: "lab", pageOffset: 0, ocrLineSplit: true, ocrDetectOrientation: true,
    ocrPdfPages: true, maxCandidates: 5, replacePrevious: true,
  },
};

const ZM_LLM_PRESETS = {
  Ollama: { backend: "ollama", url: "http://127.0.0.1:11434", model: "qwen2.5vl" },
  vLLM: { backend: "openai", url: "http://127.0.0.1:8000/v1", model: "" },
  "LM Studio": { backend: "openai", url: "http://127.0.0.1:1234/v1", model: "" },
  "llama.cpp": { backend: "openai", url: "http://127.0.0.1:8080/v1", model: "" },
  OpenRouter: { backend: "openai", url: "https://openrouter.ai/api/v1", model: "" },
  OpenAI: { backend: "openai", url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  Anthropic: { backend: "anthropic", url: "https://api.anthropic.com", model: "claude-3-5-sonnet-latest" },
};

var _zmRetries = 0;
var _zmActiveTab = "setup";

function _zmInit() {
  const anchor = document.getElementById("me-python-path");
  if (!anchor) {
    if (++_zmRetries <= 60) window.setTimeout(_zmInit, 50);
    return;
  }
  if (anchor._zmInited) return;
  anchor._zmInited = true;

  _zmMigrateLegacy();
  _zmWireControls();
  _zmWireTabs();
  _zmWireProfiles();
  _zmWireHelper();
  _zmWireColors();
  _zmLoadControls();
  _zmRefreshProfiles();
  _zmApplyVisibility();
}

// ── Controls ────────────────────────────────────────────────────────────────

function _zmWireControls() {
  for (const def of ZM_CONTROLS) {
    const el = document.getElementById(def.id);
    if (!el) continue;
    const save = () => _zmSet(def.key, _zmControlValue(def));
    el.addEventListener("change", save);
    el.addEventListener("command", save);
  }
  document.getElementById("me-llm-preset")?.addEventListener("change", () => {
    const name = document.getElementById("me-llm-preset").value;
    const preset = ZM_LLM_PRESETS[name];
    if (!preset) return;
    const backend = document.getElementById("me-ocr-backend");
    const url = document.getElementById("me-llm-url");
    const model = document.getElementById("me-llm-model");
    if (backend) backend.value = preset.backend;
    if (url) url.value = preset.url;
    if (model) model.value = preset.model;
    _zmSet("ocrBackend", preset.backend);
    _zmSet("llmUrl", preset.url);
    _zmSet("llmModel", preset.model);
    _zmRunCheck();
  });
}

function _zmMigrateLegacy() {
  if (!_zmGet("llmUrl", "")) {
    const url = _zmGet("ollamaUrl", "");
    if (url) _zmSet("llmUrl", url);
  }
  if (!_zmGet("llmModel", "")) {
    const model = _zmGet("ollamaModel", "");
    if (model) _zmSet("llmModel", model);
  }
}

function _zmControlValue(def) {
  const el = document.getElementById(def.id);
  if (!el) return def.fallback;
  if (def.type === "bool") return !!el.checked;
  if (def.type === "int") {
    const n = parseInt(el.value, 10);
    return Number.isFinite(n) ? n : def.fallback;
  }
  if (def.type === "float") {
    const n = parseFloat(el.value);
    return Number.isFinite(n) ? n : def.fallback;
  }
  return el.value;
}

function _zmSetControl(def, value) {
  const el = document.getElementById(def.id);
  if (!el) return;
  if (def.type === "bool") el.checked = !!value;
  else el.value = value;
}

function _zmLoadControls() {
  for (const def of ZM_CONTROLS) {
    _zmSetControl(def, _zmGet(def.key, def.fallback));
  }
  _zmRenderColors(_zmReadSavedColors());
}

function _zmCollectSettings() {
  const out = {};
  for (const def of ZM_CONTROLS) out[def.key] = _zmControlValue(def);
  return out;
}

function _zmApplySettings(settings) {
  if (!settings || typeof settings !== "object") return;
  for (const key of Object.keys(settings)) _zmSet(key, settings[key]);
}

// ── Tabs / search ───────────────────────────────────────────────────────────

function _zmWireTabs() {
  for (const button of document.querySelectorAll(".zm-tab")) {
    button.addEventListener("click", () => {
      _zmActiveTab = button.dataset.tab;
      for (const other of document.querySelectorAll(".zm-tab")) {
        other.classList.toggle("active", other === button);
        other.setAttribute("aria-selected", other === button ? "true" : "false");
      }
      _zmApplyVisibility();
    });
  }
  const search = document.getElementById("zm-search");
  if (search) search.addEventListener("input", _zmApplyVisibility);
}

function _zmApplyVisibility() {
  const query = (document.getElementById("zm-search")?.value || "").trim().toLowerCase();
  for (const pane of document.querySelectorAll(".zm-tabpane")) {
    const active = pane.getAttribute("data-pane") === _zmActiveTab;
    pane.hidden = !active && !query;
    for (const group of pane.getElementsByTagName("groupbox")) {
      const match = !query || (group.textContent || "").toLowerCase().includes(query);
      group.hidden = !match;
    }
  }
}

// ── Profiles ────────────────────────────────────────────────────────────────

function _zmStoredProfiles() {
  try {
    const raw = _zmGet("profiles", "");
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_) {
    return {};
  }
}

function _zmAllProfiles() {
  return Object.assign({}, ZM_BUILTIN_PROFILES, _zmStoredProfiles());
}

function _zmRefreshProfiles() {
  const select = document.getElementById("zm-profile-select");
  if (!select) return;
  select.innerHTML = "";
  const all = _zmAllProfiles();
  for (const name of Object.keys(all).sort()) {
    const option = el("option");
    option.value = name;
    option.textContent = name + (ZM_BUILTIN_PROFILES[name] ? " (built-in)" : "");
    select.appendChild(option);
  }
  const active = _zmGet("activeProfile", "Essay");
  select.value = all[active] ? active : (Object.keys(all)[0] || "");
}

function _zmWireProfiles() {
  document.getElementById("zm-profile-apply")?.addEventListener("click", () => {
    const name = document.getElementById("zm-profile-select")?.value;
    const profile = _zmAllProfiles()[name];
    if (!profile) return;
    _zmApplySettings(profile);
    _zmSet("activeProfile", name);
    _zmLoadControls();
  });
  document.getElementById("zm-profile-save")?.addEventListener("click", () => {
    const name = (window.prompt("Profile name", "My profile") || "").trim();
    if (!name) return;
    const saved = _zmStoredProfiles();
    saved[name] = _zmCollectSettings();
    _zmSet("profiles", JSON.stringify(saved));
    _zmSet("activeProfile", name);
    _zmRefreshProfiles();
  });
  document.getElementById("zm-profile-delete")?.addEventListener("click", () => {
    const name = document.getElementById("zm-profile-select")?.value;
    const saved = _zmStoredProfiles();
    if (!saved[name]) return;
    delete saved[name];
    _zmSet("profiles", JSON.stringify(saved));
    _zmRefreshProfiles();
  });
  document.getElementById("zm-export")?.addEventListener("click", _zmExport);
  document.getElementById("zm-import")?.addEventListener("click", _zmImport);
  document.getElementById("zm-reset-all")?.addEventListener("click", () => {
    if (!window.confirm("Reset all Marginalia Extractor settings to defaults?")) return;
    for (const def of ZM_CONTROLS) _zmSet(def.key, def.fallback);
    _zmSet("colors", "");
    _zmLoadControls();
  });
}

async function _zmExport() {
  if (typeof Zotero === "undefined" || !Zotero.File) return;
  try {
    const nsIFilePicker = Components.interfaces.nsIFilePicker;
    const picker = Components.classes["@mozilla.org/filepicker;1"].createInstance(nsIFilePicker);
    picker.init(window, "Export Marginalia settings", nsIFilePicker.modeSave);
    picker.defaultString = "marginalia-settings.json";
    const path = await new Promise((resolve) => {
      const done = (rv) => resolve(rv === nsIFilePicker.returnOK || rv === nsIFilePicker.returnReplace ? picker.file.path : null);
      const maybe = picker.open(done);
      if (maybe && typeof maybe.then === "function") maybe.then(() => done(nsIFilePicker.returnOK)).catch(() => done(nsIFilePicker.returnCancel));
    });
    if (!path) return;
    const payload = {
      settings: _zmCollectSettings(),
      colors: _zmReadColors(),
      profiles: _zmStoredProfiles(),
    };
    await Zotero.File.putContentsAsync(path, JSON.stringify(payload, null, 2));
    const status = document.getElementById("me-save-status");
    if (status) status.textContent = "Exported.";
  } catch (e) {
    dump("[Marginalia] export failed: " + e + "\n");
  }
}

async function _zmImport() {
  if (typeof Zotero === "undefined" || !Zotero.File) return;
  try {
    const picker = Components.classes["@mozilla.org/filepicker;1"]
      .createInstance(Components.interfaces.nsIFilePicker);
    picker.init(window, "Import Marginalia settings", Components.interfaces.nsIFilePicker.modeOpen);
    const path = await new Promise((resolve) => {
      const done = (rv) => resolve(rv === picker.returnOK ? picker.file.path : null);
      const maybe = picker.open(done);
      if (maybe && typeof maybe.then === "function") maybe.then(() => done(picker.returnOK)).catch(() => done(picker.returnCancel));
    });
    if (!path) return;
    const payload = JSON.parse(await Zotero.File.getContentsAsync(path));
    _zmApplySettings(payload.settings || {});
    if (Array.isArray(payload.colors)) _zmSet("colors", JSON.stringify(payload.colors));
    if (payload.profiles && typeof payload.profiles === "object") {
      _zmSet("profiles", JSON.stringify(payload.profiles));
    }
    _zmLoadControls();
    _zmRefreshProfiles();
  } catch (e) {
    dump("[Marginalia] import failed: " + e + "\n");
  }
}

// ── Helper / status ─────────────────────────────────────────────────────────

function _zmFileExists(path) {
  try {
    const file = Components.classes["@mozilla.org/file/local;1"]
      .createInstance(Components.interfaces.nsIFile);
    file.initWithPath(path);
    return file.exists();
  } catch (_) {
    return false;
  }
}

function _zmHelperInvocation() {
  const dir = (document.getElementById("me-helper-dir")?.value || "").trim();
  if (!dir) return null;
  const sep = dir.endsWith("/") ? "" : "/";
  for (const name of ["marginalia-helper", "marginalia-helper.exe"]) {
    const binary = dir + sep + name;
    if (_zmFileExists(binary)) return { command: binary, argv: [] };
  }
  const script = dir + sep + "marginalia_helper.py";
  if (!_zmFileExists(script)) return null;
  const python = (document.getElementById("me-python-path")?.value || "python3").trim();
  const isAbsolute = python.startsWith("/") || /^[A-Za-z]:[\\/]/.test(python);
  if (isAbsolute) return { command: python, argv: [script] };
  return { command: "/usr/bin/env", argv: [python, script] };
}

function _zmWireHelper() {
  document.getElementById("me-helper-dir")?.addEventListener("change", () => {
    _zmSet("helperDir", (document.getElementById("me-helper-dir").value || "").trim());
  });
  document.getElementById("me-browse-helper")?.addEventListener("click", () => {
    try {
      const picker = Components.classes["@mozilla.org/filepicker;1"]
        .createInstance(Components.interfaces.nsIFilePicker);
      picker.init(window, "Choose the helper folder", Components.interfaces.nsIFilePicker.modeGetFolder);
      const done = (rv) => {
        if (rv !== picker.returnOK || !picker.file) return;
        const input = document.getElementById("me-helper-dir");
        if (input) input.value = picker.file.path;
        _zmSet("helperDir", picker.file.path);
      };
      const maybe = picker.open(done);
      if (maybe && typeof maybe.then === "function") maybe.then(() => done(picker.returnOK)).catch(() => {});
    } catch (_) {}
  });
  document.getElementById("me-test-helper")?.addEventListener("click", _zmTestHelper);
  document.getElementById("me-run-check")?.addEventListener("click", _zmRunCheck);
}

function _zmTestHelper() {
  const status = document.getElementById("me-test-status");
  if (!status) return;
  const invocation = _zmHelperInvocation();
  if (invocation) {
    status.style.color = "#2a7";
    status.textContent = "✓ " + invocation.command;
  } else {
    status.style.color = "#c33";
    status.textContent = "No helper script or binary found in that folder.";
  }
}

function _zmSetChip(id, text, tone) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = "zm-chip " + (tone || "");
}

async function _zmRunCheck() {
  const detail = document.getElementById("me-check-detail");
  const invocation = _zmHelperInvocation();
  if (!invocation) {
    _zmSetChip("me-status-helper", "Helper not configured", "bad");
    return;
  }
  if (typeof Zotero === "undefined" || !Zotero.Utilities || !Zotero.Utilities.Internal || typeof Zotero.Utilities.Internal.exec !== "function" || !Zotero.File) {
    if (detail) detail.textContent = "This Zotero build cannot run the helper from the preferences window.";
    return;
  }
  _zmSetChip("me-status-helper", "Checking…", "");
  try {
    const settings = _zmCollectSettings();
    const helperConfig = {
      ocr_backend: settings.ocrBackend,
      ocr_lang: settings.ocrLang,
      llm_url: settings.llmUrl,
      llm_model: settings.llmModel,
      llm_api_key: settings.llmApiKey,
      llm_api_key_env: settings.llmApiKeyEnv,
      llm_prompt: settings.llmPrompt,
      llm_timeout: settings.llmTimeout,
      llm_max_tokens: settings.llmMaxTokens,
      llm_temperature: settings.llmTemperature,
      colors: _zmReadColors(),
    };
    const dirsvc = Components.classes["@mozilla.org/file/directory_service;1"]
      .getService(Components.interfaces.nsIProperties);
    const tmp = dirsvc.get("TmpD", Components.interfaces.nsIFile);
    tmp.append("marginalia-check-" + Date.now() + ".json");
    await Zotero.File.putContentsAsync(tmp.path, JSON.stringify(helperConfig, null, 2));
    let stdout;
    try {
      stdout = await Zotero.Utilities.Internal.exec(
        invocation.command,
        [...invocation.argv, "--check", "--config", tmp.path]
      );
    } finally {
      try { if (tmp.exists()) tmp.remove(false); } catch (_) {}
    }
    const report = JSON.parse(stdout);
    const ocr = report.ocr || {};
    _zmSetChip(
      "me-status-tesseract",
      ocr.tesseract_binary ? `Tesseract ✓ ${(ocr.tesseract_languages || []).slice(0, 2).join(", ")}` : "Tesseract missing",
      ocr.tesseract_binary ? "ok" : "bad"
    );
    const backend = ocr.backend || _zmGet("ocrBackend", "tesseract");
    if (backend === "tesseract" || backend === "none") {
      _zmSetChip("me-status-llm", "LLM not used", "");
    } else if (ocr.llm_reachable) {
      _zmSetChip("me-status-llm", `${backend} ✓ ${(ocr.llm_models || []).length} model(s)`, "ok");
    } else {
      _zmSetChip("me-status-llm", `${backend} unreachable`, "warn");
    }
    _zmSetChip(
      "me-status-helper",
      `Helper v${report.helper_version || "?"} · protocol ${report.protocol_version || "?"}`,
      "ok"
    );
    const langs = document.getElementById("me-lang-list");
    if (langs && Array.isArray(ocr.tesseract_languages)) {
      langs.innerHTML = "";
      for (const lang of ocr.tesseract_languages) {
        const option = document.createElementNS("http://www.w3.org/1999/xhtml", "option");
        option.value = lang;
        langs.appendChild(option);
      }
    }
    const modelList = Array.isArray(ocr.llm_models) && ocr.llm_models.length
      ? ocr.llm_models
      : (ocr.ollama_models || []);
    const models = document.getElementById("me-model-list");
    if (models && Array.isArray(modelList)) {
      models.innerHTML = "";
      for (const model of modelList) {
        const option = document.createElementNS("http://www.w3.org/1999/xhtml", "option");
        option.value = model;
        models.appendChild(option);
      }
    }
    if (detail) detail.textContent = (ocr.messages || []).join(" · ");
  } catch (e) {
    _zmSetChip("me-status-helper", "Check failed", "bad");
    if (detail) detail.textContent = String(e);
  }
}

// ── Colour table ────────────────────────────────────────────────────────────

function _zmReadSavedColors() {
  try {
    const raw = _zmGet("colors", "");
    return raw ? JSON.parse(raw) : JSON.parse(JSON.stringify(ZM_DEFAULT_COLORS));
  } catch (_) {
    return JSON.parse(JSON.stringify(ZM_DEFAULT_COLORS));
  }
}

function _zmMakeColorRow(color) {
  const tr = el("tr");
  const cell = () => {
    const td = el("td");
    tr.appendChild(td);
    return td;
  };

  const nameCell = cell();
  const nameInput = el("input");
  nameInput.type = "text";
  nameInput.value = color.name || "";
  nameCell.appendChild(nameInput);

  const zoteroCell = cell();
  const zoteroSel = el("select");
  for (const c of ZM_ZOTERO_COLORS) {
    const o = el("option");
    o.value = c; o.textContent = c;
    if (c === color.zotero) o.selected = true;
    zoteroSel.appendChild(o);
  }
  zoteroCell.appendChild(zoteroSel);

  const outputCell = cell();
  const outputSel = el("select");
  for (const o of ZM_OUTPUTS) {
    const option = el("option");
    option.value = o; option.textContent = o;
    if (o === (color.output || "auto")) option.selected = true;
    outputSel.appendChild(option);
  }
  outputCell.appendChild(outputSel);

  const numberCell = (value) => {
    const c = cell();
    const input = el("input");
    input.type = "number";
    input.min = "0"; input.max = "255";
    input.value = value;
    c.appendChild(input);
    return input;
  };

  const hueMin = numberCell(color.hue_min ?? 0);
  const hueMax = numberCell(color.hue_max ?? 179);
  const satMin = numberCell(color.sat_min ?? 0);
  const valMin = numberCell(color.val_min ?? 0);
  const valMax = numberCell(color.val_max ?? 255);

  const kindCell = cell();
  const kindSel = el("select");
  for (const k of ["any", "highlighter", "pen"]) {
    const o = el("option");
    o.value = k; o.textContent = k;
    if (k === (color.kind || "any")) o.selected = true;
    kindSel.appendChild(o);
  }
  kindCell.appendChild(kindSel);

  const enabledCell = cell();
  const enabledCb = el("input");
  enabledCb.type = "checkbox";
  enabledCb.checked = color.enabled !== false;
  enabledCell.appendChild(enabledCb);

  const delCell = cell();
  const delBtn = el("button");
  delBtn.textContent = "×";
  delBtn.className = "zm-btn";
  delBtn.addEventListener("click", () => tr.remove());
  delCell.appendChild(delBtn);

  tr._zmRead = () => ({
    name: nameInput.value.trim() || "colour",
    zotero: zoteroSel.value,
    output: outputSel.value,
    hue_min: parseInt(hueMin.value, 10) || 0,
    hue_max: parseInt(hueMax.value, 10) || 0,
    sat_min: parseInt(satMin.value, 10) || 0,
    val_min: parseInt(valMin.value, 10) || 0,
    sat_max: 255,
    val_max: parseInt(valMax.value, 10) || 255,
    kind: kindSel.value,
    enabled: enabledCb.checked,
  });
  return tr;
}

function _zmRenderColors(colors) {
  const tbody = document.getElementById("marginalia-colors-body");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (const color of colors) tbody.appendChild(_zmMakeColorRow(color));
}

function _zmReadColors() {
  const tbody = document.getElementById("marginalia-colors-body");
  if (!tbody) return [];
  return Array.from(tbody.querySelectorAll("tr")).map((tr) => tr._zmRead());
}

function _zmSaveColors() {
  _zmSet("colors", JSON.stringify(_zmReadColors()));
}

function _zmWireColors() {
  document.getElementById("me-add-color")?.addEventListener("click", () => {
    const tbody = document.getElementById("marginalia-colors-body");
    if (!tbody) return;
    tbody.appendChild(_zmMakeColorRow({
      name: "new", zotero: "yellow", output: "auto",
      hue_min: 0, hue_max: 179, sat_min: 60, val_min: 60, val_max: 255,
      kind: "any", enabled: true,
    }));
  });
  document.getElementById("me-reset-colors")?.addEventListener("click", () => {
    _zmRenderColors(JSON.parse(JSON.stringify(ZM_DEFAULT_COLORS)));
    _zmSaveColors();
  });
  document.getElementById("me-save")?.addEventListener("click", () => {
    _zmSaveColors();
    const status = document.getElementById("me-save-status");
    if (status) {
      status.textContent = "Saved!";
      window.setTimeout(() => { status.textContent = ""; }, 1500);
    }
  });
  document.getElementById("me-calibrate")?.addEventListener("click", _zmOpenCalibrator);
}

function _zmOpenCalibrator() {
  const root = _zmGet("rootURI", "");
  const status = document.getElementById("me-save-status");
  if (!root) {
    if (status) status.textContent = "Restart Zotero once to enable colour sampling.";
    return;
  }
  const args = { colors: _zmReadColors(), result: null };
  try {
    window.openDialog(
      root + "content/calibrate.xhtml",
      "marginalia-extractor-calibrate",
      "chrome,dialog,modal,centerscreen,resizable,width=900,height=720",
      args
    );
  } catch (e) {
    if (status) status.textContent = "Could not open calibrator: " + e;
    return;
  }
  if (args.result) {
    const tbody = document.getElementById("marginalia-colors-body");
    if (tbody) tbody.appendChild(_zmMakeColorRow(args.result));
    _zmSaveColors();
    if (status) {
      status.textContent = "Colour added.";
      window.setTimeout(() => { status.textContent = ""; }, 1500);
    }
  }
}

// Boot.
_zmInit();
