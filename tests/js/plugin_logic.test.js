#!/usr/bin/env node
/* Headless tests for the pure logic in marginaliaExtractor.js.
 *
 * Run from the project root:
 *   node tests/js/plugin_logic.test.js
 *
 * Zotero, Components and Services are stubbed; only code paths that do not
 * touch the real Zotero API are exercised.
 */

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

// ── Minimal globals the module touches at call time ─────────────────────────
global.Zotero = {
  debug() {},
  getTempDirectory() {
    return { append() {}, path: "/tmp/marginalia-extractor", exists: () => true };
  },
};
global.Services = {
  appinfo: { OS: "Darwin" },
  prefs: {
    getPrefType() { return 0; },
  },
};
global.Components = {
  interfaces: { nsIFile: { DIRECTORY_TYPE: 1 }, nsIFilePicker: {} },
  classes: {},
};

const sourcePath = path.join(__dirname, "..", "..", "content", "marginaliaExtractor.js");
const source = fs.readFileSync(sourcePath, "utf8");
const factory = new Function(source + "\n;return MarginaliaExtractor;");
const MarginaliaExtractor = factory();

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log("PASS " + name);
  } catch (error) {
    console.error("FAIL " + name);
    console.error(error && error.stack ? error.stack : error);
    process.exitCode = 1;
  }
}

// ── _toFileURL ───────────────────────────────────────────────────────────────
test("_toFileURL encodes spaces and hashes", () => {
  const url = MarginaliaExtractor._toFileURL("/tmp/a b#c.jpg");
  assert.strictEqual(url, "file:///tmp/a%20b%23c.jpg");
});

test("_toFileURL returns null for empty input", () => {
  assert.strictEqual(MarginaliaExtractor._toFileURL(null), null);
});

// ── _positionForRow ──────────────────────────────────────────────────────────
test("_positionForRow omits nextPageRects when absent", () => {
  const position = MarginaliaExtractor._positionForRow({
    pageIndex: 2,
    rects: [[1, 2, 3, 4]],
  });
  assert.deepStrictEqual(position, { pageIndex: 2, rects: [[1, 2, 3, 4]] });
});

test("_positionForRow includes nextPageRects for cross-page annotations", () => {
  const position = MarginaliaExtractor._positionForRow({
    pageIndex: 2,
    rects: [[1, 2, 3, 4]],
    nextPageRects: [[5, 6, 7, 8]],
  });
  assert.deepStrictEqual(position.nextPageRects, [[5, 6, 7, 8]]);
});

// ── _helperBinaryPath / _helperInvocation ────────────────────────────────────
test("_helperBinaryPath appends the platform binary name", () => {
  const original = MarginaliaExtractor.getHelperDir;
  MarginaliaExtractor.getHelperDir = () => "/opt/helper";
  try {
    assert.strictEqual(MarginaliaExtractor._helperBinaryPath(), "/opt/helper/marginalia-helper");
  } finally {
    MarginaliaExtractor.getHelperDir = original;
  }
});

test("_helperInvocation prefers the binary when present", () => {
  const original = {
    getHelperDir: MarginaliaExtractor.getHelperDir,
    getPythonPath: MarginaliaExtractor.getPythonPath,
    getPref: MarginaliaExtractor.getPref,
    fileExists: MarginaliaExtractor._fileExists,
  };
  MarginaliaExtractor.getHelperDir = () => "/opt/helper";
  MarginaliaExtractor.getPythonPath = () => "/opt/py";
  MarginaliaExtractor.getPref = (key, fallback) => (key === "autoBinary" ? true : fallback);
  MarginaliaExtractor._fileExists = () => true;
  try {
    const invocation = MarginaliaExtractor._helperInvocation(["--check"]);
    assert.strictEqual(invocation.command, "/opt/helper/marginalia-helper");
    assert.deepStrictEqual(invocation.argv, ["--check"]);
  } finally {
    MarginaliaExtractor.getHelperDir = original.getHelperDir;
    MarginaliaExtractor.getPythonPath = original.getPythonPath;
    MarginaliaExtractor.getPref = original.getPref;
    MarginaliaExtractor._fileExists = original.fileExists;
  }
});

test("_helperInvocation falls back to an absolute Python", () => {
  const original = {
    getHelperDir: MarginaliaExtractor.getHelperDir,
    getPythonPath: MarginaliaExtractor.getPythonPath,
    getPref: MarginaliaExtractor.getPref,
  };
  MarginaliaExtractor.getHelperDir = () => "/opt/helper";
  MarginaliaExtractor.getPythonPath = () => "/opt/py";
  MarginaliaExtractor.getPref = (key, fallback) => (key === "autoBinary" ? false : fallback);
  try {
    const invocation = MarginaliaExtractor._helperInvocation(["--check"]);
    assert.strictEqual(invocation.command, "/opt/py");
    assert.deepStrictEqual(invocation.argv, ["/opt/helper/marginalia_helper.py", "--check"]);
  } finally {
    MarginaliaExtractor.getHelperDir = original.getHelperDir;
    MarginaliaExtractor.getPythonPath = original.getPythonPath;
    MarginaliaExtractor.getPref = original.getPref;
  }
});

test("_helperInvocation routes a bare python through /usr/bin/env", () => {
  const original = {
    getHelperDir: MarginaliaExtractor.getHelperDir,
    getPythonPath: MarginaliaExtractor.getPythonPath,
    getPref: MarginaliaExtractor.getPref,
  };
  MarginaliaExtractor.getHelperDir = () => "/opt/helper";
  MarginaliaExtractor.getPythonPath = () => "python3";
  MarginaliaExtractor.getPref = (key, fallback) => (key === "autoBinary" ? false : fallback);
  try {
    const invocation = MarginaliaExtractor._helperInvocation(["--check"]);
    assert.strictEqual(invocation.command, "/usr/bin/env");
    assert.deepStrictEqual(invocation.argv, ["python3", "/opt/helper/marginalia_helper.py", "--check"]);
  } finally {
    MarginaliaExtractor.getHelperDir = original.getHelperDir;
    MarginaliaExtractor.getPythonPath = original.getPythonPath;
    MarginaliaExtractor.getPref = original.getPref;
  }
});

// ── _buildSession ────────────────────────────────────────────────────────────
test("_buildSession includes the next page referenced by a merged annotation", () => {
  const page = (pdfIndex, scanLabel, annotations, hasImages) => ({
    scan_index: 0,
    scan_label: scanLabel,
    pdf_index: pdfIndex,
    page_label: String(pdfIndex + 1),
    width_pts: 612,
    height_pts: 792,
    dpi: 200,
    model: { sentences: [] },
    images: hasImages ? { scan: `/tmp/s${pdfIndex}.jpg`, pdf: `/tmp/p${pdfIndex}.jpg` } : {},
    alignment: { method: "ecc", confidence: 0.9 },
    annotations,
  });

  const mergedAnnotation = {
    type: "highlight",
    color: "#ffd400",
    rects: [[10, 10, 100, 20]],
    text: "page one",
    comment: "",
    source: "highlight",
    association_method: "",
    confidence: 0,
    sort_index: "00000|000000|00010",
    candidates: [],
    next_page_index: 1,
    next_page_rects: [[11, 11, 101, 21]],
  };

  const result = {
    source_pdf: "a.pdf",
    scan_pdf: "b.pdf",
    warnings: [],
    page_mapping: [],
    pages: [
      page(0, "1", [mergedAnnotation], true),
      page(1, "2", [], true),
      page(2, "3", [], false),
    ],
  };

  const session = MarginaliaExtractor._buildSession({ id: 7 }, result, "run1");
  assert.strictEqual(session.annotations.length, 1);
  assert.strictEqual(session.annotations[0].nextPageIndex, 1);
  assert.deepStrictEqual(session.annotations[0].nextPageRects, [[11, 11, 101, 21]]);
  // Page 0 (annotated) and page 1 (next page) are included; page 2 is not.
  assert.strictEqual(session.pages.length, 2);
  assert.ok(session.pages.some((p) => p.pageIndex === 1));
});

// ── _versionLess ────────────────────────────────────────────────────────────
test("_versionLess compares semantic versions", () => {
  assert.strictEqual(MarginaliaExtractor._versionLess("0.4.9", "0.5.0"), true);
  assert.strictEqual(MarginaliaExtractor._versionLess("0.5.0", "0.5.0"), false);
  assert.strictEqual(MarginaliaExtractor._versionLess("0.10.0", "0.9.9"), false);
  assert.strictEqual(MarginaliaExtractor._versionLess("1", "1.0.1"), true);
});

// ── Summary ──────────────────────────────────────────────────────────────────
console.log(`\n${passed} plugin logic test(s) passed.`);
