/* global Zotero, Components, Services */
/* eslint-disable no-unused-vars */

/**
 * Marginalia Extractor — plugin controller (v0.2).
 *
 * v0.2 flow:
 *   1. User picks a PDF attachment and a scanned PDF.
 *   2. The helper runs with page mapping, progress and cancellation.
 *   3. The plugin opens a preview review window; nothing is written yet.
 *   4. On Apply, annotations are created (and any previous run for this
 *      attachment is replaced), tagged for provenance.
 */

var MarginaliaExtractor = {

  PREF_PREFIX: 'extensions.marginalia-extractor@zotero-marginalia-extractor',
  PROTOCOL_VERSION: 2,
  MIN_HELPER_VERSION: '0.6.0',
  RUN_TAG: 'marginalia-extractor',
  RUN_TAG_PREFIX: 'marginalia-run-',
  SCAN_TAG_PREFIX: 'marginalia-scan-',

  MENU_IDS: [
    'marginalia-extractor-sep',
    'marginalia-extractor-run',
    'marginalia-extractor-mapping',
    'marginalia-extractor-history',
    'marginalia-extractor-export',
    'marginalia-extractor-remove',
    'marginalia-extractor-tools-sep',
    'marginalia-extractor-tools',
    'marginalia-extractor-batch',
    'marginalia-extractor-cancel',
    'marginalia-extractor-diagnose',
    'marginalia-extractor-log',
  ],

  DEFAULT_COLORS: [
    { name: 'yellow',   zotero: 'yellow', hue_min: 20,  hue_max: 38,  sat_min: 70, val_min: 60,  sat_max: 255, val_max: 255, enabled: true, kind: 'any' },
    { name: 'red',      zotero: 'red',    hue_min: 0,   hue_max: 8,   sat_min: 70, val_min: 60,  sat_max: 255, val_max: 255, enabled: true, kind: 'any' },
    { name: 'pink',     zotero: 'red',    hue_min: 165, hue_max: 179, sat_min: 60, val_min: 60,  sat_max: 255, val_max: 255, enabled: true, kind: 'any' },
    { name: 'green',    zotero: 'green',  hue_min: 40,  hue_max: 85,  sat_min: 60, val_min: 60,  sat_max: 255, val_max: 255, enabled: true, kind: 'any' },
    { name: 'blue',     zotero: 'blue',   hue_min: 90,  hue_max: 130, sat_min: 60, val_min: 60,  sat_max: 255, val_max: 255, enabled: true, kind: 'any' },
    { name: 'purple',   zotero: 'purple', hue_min: 130, hue_max: 165, sat_min: 50, val_min: 60,  sat_max: 255, val_max: 255, enabled: true, kind: 'any' },
    { name: 'blue-pen', zotero: 'blue',   hue_min: 100, hue_max: 130, sat_min: 80, val_min: 0,   sat_max: 255, val_max: 180, enabled: true, kind: 'pen' },
    { name: 'red-pen',  zotero: 'red',    hue_min: 0,   hue_max: 8,   sat_min: 80, val_min: 0,   sat_max: 255, val_max: 180, enabled: true, kind: 'pen' },
  ],

  id: null,
  version: null,
  rootURI: null,

  _windows: new Set(),
  _run: null,
  _lastRunPaths: null,
  _lastLogPath: null,

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  init({ id, version, rootURI }) {
    this.id = id;
    this.version = version;
    this.rootURI = rootURI;
    // The preferences pane needs the plugin root to open the calibrator dialog.
    this.setPref('rootURI', rootURI);
    try { this._registerPrefsPane(); } catch (e) { Zotero.debug('[Marginalia] prefs pane: ' + e); }
  },

  shutdown() {
    this._stopRun();
    for (const win of this._windows) this._unregisterMenus(win);
    this._windows.clear();
  },

  addToWindow(win) {
    if (!win || this._windows.has(win)) return;
    this._windows.add(win);
    this._registerMenus(win);
  },

  removeFromWindow(win) {
    this._unregisterMenus(win);
    this._windows.delete(win);
  },

  // ── Preferences ──────────────────────────────────────────────────────────

  _registerPrefsPane() {
    if (!Zotero.PreferencePanes) return;
    Zotero.PreferencePanes.register({
      pluginID: this.id,
      src: this.rootURI + 'content/preferences.xhtml',
      scripts: [this.rootURI + 'content/prefs.js'],
      label: 'Marginalia Extractor',
      image: this.rootURI + 'icons/marginalia.svg',
    });
  },

  getPref(key, defaultValue) {
    try {
      const fullKey = this.PREF_PREFIX + '.' + key;
      const ps = Services.prefs;
      const t = ps.getPrefType(fullKey);
      if (t === 0) return defaultValue;
      if (t === 128) return ps.getBoolPref(fullKey);
      if (t === 64) return ps.getIntPref(fullKey);
      return ps.getStringPref(fullKey);
    } catch (_) {
      return defaultValue;
    }
  },

  setPref(key, value) {
    try {
      const fullKey = this.PREF_PREFIX + '.' + key;
      const ps = Services.prefs;
      if (typeof value === 'boolean') ps.setBoolPref(fullKey, value);
      else if (typeof value === 'number') ps.setIntPref(fullKey, value);
      else ps.setStringPref(fullKey, String(value));
    } catch (e) {
      Zotero.debug('[Marginalia] setPref failed: ' + e);
    }
  },

  getColors() {
    try {
      const raw = this.getPref('colors', '');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length) return parsed;
      }
    } catch (_) {}
    return JSON.parse(JSON.stringify(this.DEFAULT_COLORS));
  },

  getConfig(runtime) {
    return Object.assign({
      dpi: this.getPref('dpi', 200),
      mark_mode: this.getPref('markMode', 'both'),
      ocr_backend: this.getPref('ocrBackend', 'tesseract'),
      ocr_lang: this.getPref('ocrLang', 'eng'),
      ocr_line_split: this.getPref('ocrLineSplit', true),
      ollama_url: this.getPref('ollamaUrl', 'http://127.0.0.1:11434'),
      ollama_model: this.getPref('ollamaModel', 'qwen2.5vl'),
      llm_url: this.getPref('llmUrl', this.getPref('ollamaUrl', '')),
      llm_model: this.getPref('llmModel', this.getPref('ollamaModel', '')),
      llm_api_key: this.getPref('llmApiKey', ''),
      llm_api_key_env: this.getPref('llmApiKeyEnv', 'MARGINALIA_LLM_API_KEY'),
      llm_prompt: this.getPref('llmPrompt', ''),
      llm_timeout: this.getPref('llmTimeout', 180),
      llm_max_tokens: this.getPref('llmMaxTokens', 1024),
      llm_temperature: parseFloat(this.getPref('llmTemperature', '0')) || 0,
      note_fallback_color: this.getPref('noteFallbackColor', 'yellow'),
      page_offset: this.getPref('pageOffset', 0),
      match_pages: this.getPref('matchPages', true),
      split_spreads: this.getPref('splitSpreads', false),
      perspective_correct: this.getPref('perspectiveCorrect', true),
      perspective_min_area: parseFloat(this.getPref('perspectiveMinArea', '0.30')) || 0.30,
      merge_cross_page: this.getPref('mergeCrossPage', true),
      white_balance: this.getPref('whiteBalance', true),
      color_space: this.getPref('colorSpace', 'hsv'),
      remove_shadows: this.getPref('removeShadows', true),
      deskew: this.getPref('deskew', true),
      detect_dark_underlines: this.getPref('detectDarkUnderlines', true),
      dark_underline_color: this.getPref('darkUnderlineColor', 'grey'),
      ocr_pdf_pages: this.getPref('ocrPdfPages', true),
      ocr_detect_orientation: this.getPref('ocrDetectOrientation', true),
      min_highlight_area: this.getPref('minHighlightArea', 120),
      min_note_area: this.getPref('minNoteArea', 60),
      margin_fraction: parseFloat(this.getPref('marginFraction', '0.18')) || 0.18,
      max_candidates: this.getPref('maxCandidates', 4),
      comment_prefix: this.getPref('commentPrefix', ''),
      comment_suffix: this.getPref('commentSuffix', ''),
      append_scan_source: this.getPref('appendScanSource', false),
      low_confidence: parseFloat(this.getPref('lowConfidence', '0.35')) || 0.35,
      render_review_images: true,
      colors: this.getColors(),
    }, runtime || {});
  },

  getPythonPath() { return this.getPref('pythonPath', 'python3'); },
  getHelperDir() { return this.getPref('helperDir', ''); },

  _helperScriptPath() {
    const dir = this.getHelperDir();
    if (!dir) return '';
    const sep = dir.endsWith('/') ? '' : '/';
    return dir + sep + 'marginalia_helper.py';
  },

  _helperBinaryPath() {
    const dir = this.getHelperDir();
    if (!dir) return '';
    const sep = dir.endsWith('/') ? '' : '/';
    const name = Services.appinfo.OS === 'WINNT' ? 'marginalia-helper.exe' : 'marginalia-helper';
    return dir + sep + name;
  },

  _fileExists(path) {
    try {
      const nsIFile = Components.interfaces.nsIFile;
      const file = Components.classes['@mozilla.org/file/local;1'].createInstance(nsIFile);
      file.initWithPath(path);
      return file.exists();
    } catch (_) {
      return false;
    }
  },

  _helperAvailable() {
    return !!(this._helperScriptPath() || this._helperBinaryPath());
  },

  _helperInvocation(helperArgs) {
    const binary = this._helperBinaryPath();
    const useBinary = this.getPref('autoBinary', true) && binary && this._fileExists(binary);
    if (useBinary) {
      return { command: binary, argv: helperArgs.slice() };
    }
    const script = this._helperScriptPath();
    if (!script) return null;
    const python = this.getPythonPath();
    const isAbsolute = python.startsWith('/') || /^[A-Za-z]:[\\/]/.test(python);
    if (isAbsolute) {
      return { command: python, argv: [script, ...helperArgs] };
    }
    if (Services.appinfo.OS === 'WINNT') {
      return {
        command: 'C:\\Windows\\System32\\cmd.exe',
        argv: ['/c', python, script, ...helperArgs],
      };
    }
    return { command: '/usr/bin/env', argv: [python, script, ...helperArgs] };
  },

  // ── Menus ─────────────────────────────────────────────────────────────────

  _registerMenus(win) {
    const doc = win.document;
    const itemMenu = doc.getElementById('zotero-itemmenu');
    if (itemMenu && !doc.getElementById('marginalia-extractor-run')) {
      const sep = doc.createXULElement('menuseparator');
      sep.id = 'marginalia-extractor-sep';
      itemMenu.appendChild(sep);

      const run = doc.createXULElement('menuitem');
      run.id = 'marginalia-extractor-run';
      run.setAttribute('label', 'Extract Marginalia…');
      run.addEventListener('command', () => this.handleExtract(win));
      itemMenu.appendChild(run);

      const mapping = doc.createXULElement('menuitem');
      mapping.id = 'marginalia-extractor-mapping';
      mapping.setAttribute('label', 'Preview Page Mapping…');
      mapping.addEventListener('command', () => this.handlePreviewMapping(win));
      itemMenu.appendChild(mapping);

      const history = doc.createXULElement('menuitem');
      history.id = 'marginalia-extractor-history';
      history.setAttribute('label', 'Marginalia Run History…');
      history.addEventListener('command', () => this.handleHistory(win));
      itemMenu.appendChild(history);

      const exportItem = doc.createXULElement('menuitem');
      exportItem.id = 'marginalia-extractor-export';
      exportItem.setAttribute('label', 'Export Annotations to Markdown…');
      exportItem.addEventListener('command', () => this.handleExport(win));
      itemMenu.appendChild(exportItem);

      const remove = doc.createXULElement('menuitem');
      remove.id = 'marginalia-extractor-remove';
      remove.setAttribute('label', 'Remove Marginalia Extraction');
      remove.addEventListener('command', () => this.handleRemove(win));
      itemMenu.appendChild(remove);

      const onPopupShowing = () => {
        const attachment = this._resolveAttachment(win);
        const visible = !!attachment;
        sep.hidden = !visible;
        run.hidden = !visible;
        mapping.hidden = !visible;
        history.hidden = !visible;
        exportItem.hidden = !visible;
        remove.hidden = !visible;
      };
      if (itemMenu._marginaliaPopupHandler) {
        itemMenu.removeEventListener('popupshowing', itemMenu._marginaliaPopupHandler);
      }
      itemMenu._marginaliaPopupHandler = onPopupShowing;
      itemMenu.addEventListener('popupshowing', onPopupShowing);
    }

    const toolsMenu = doc.getElementById('menu_ToolsPopup');
    if (toolsMenu && !doc.getElementById('marginalia-extractor-tools')) {
      const tsep = doc.createXULElement('menuseparator');
      tsep.id = 'marginalia-extractor-tools-sep';
      toolsMenu.appendChild(tsep);

      const run = doc.createXULElement('menuitem');
      run.id = 'marginalia-extractor-tools';
      run.setAttribute('label', 'Extract Marginalia…');
      run.addEventListener('command', () => this.handleExtract(win));
      toolsMenu.appendChild(run);

      const cancel = doc.createXULElement('menuitem');
      cancel.id = 'marginalia-extractor-cancel';
      cancel.setAttribute('label', 'Cancel Marginalia Extraction');
      cancel.addEventListener('command', () => this.handleCancel(win));
      toolsMenu.appendChild(cancel);

      const diagnose = doc.createXULElement('menuitem');
      diagnose.id = 'marginalia-extractor-diagnose';
      diagnose.setAttribute('label', 'Marginalia Extractor: Check Setup');
      diagnose.addEventListener('command', () => this.handleDiagnose(win));
      toolsMenu.appendChild(diagnose);

      const batch = doc.createXULElement('menuitem');
      batch.id = 'marginalia-extractor-batch';
      batch.setAttribute('label', 'Batch Extract Selected PDFs…');
      batch.addEventListener('command', () => this.handleBatch(win));
      toolsMenu.appendChild(batch);

      const logItem = doc.createXULElement('menuitem');
      logItem.id = 'marginalia-extractor-log';
      logItem.setAttribute('label', 'Open Last Marginalia Log');
      logItem.addEventListener('command', () => this.handleOpenLog(win));
      toolsMenu.appendChild(logItem);
    }
  },

  _unregisterMenus(win) {
    const doc = win?.document;
    if (!doc) return;
    for (const id of this.MENU_IDS) {
      const el = doc.getElementById(id);
      if (el && el.parentNode) el.parentNode.removeChild(el);
    }
    const itemMenu = doc.getElementById('zotero-itemmenu');
    if (itemMenu && itemMenu._marginaliaPopupHandler) {
      itemMenu.removeEventListener('popupshowing', itemMenu._marginaliaPopupHandler);
      itemMenu._marginaliaPopupHandler = null;
    }
  },

  // ── Selection ─────────────────────────────────────────────────────────────

  _resolveAttachment(win) {
    let items;
    try { items = win.ZoteroPane.getSelectedItems(); } catch (_) { return null; }
    if (!items || !items.length) return null;
    const first = items[0];
    if (this._isPdfAttachment(first)) return first;
    try {
      for (const id of (first.getAttachments ? first.getAttachments() : [])) {
        const child = Zotero.Items.get(id);
        if (this._isPdfAttachment(child)) return child;
      }
    } catch (_) {}
    return null;
  },

  _isPdfAttachment(item) {
    try {
      return item && item.isAttachment && item.isAttachment()
        && item.attachmentContentType === 'application/pdf';
    } catch (_) {
      return false;
    }
  },

  // ── Run ───────────────────────────────────────────────────────────────────

  async handleExtract(win, options = {}) {
    if (this._run) {
      this._alert(win, 'Marginalia Extractor', 'An extraction is already running. Use Tools → Cancel Marginalia Extraction.');
      return;
    }
    const attachment = options.attachment || this._resolveAttachment(win);
    if (!attachment) {
      this._alert(win, 'Marginalia Extractor', 'Select a PDF attachment first.');
      return;
    }
    if (!this._helperAvailable()) {
      this._alert(win, 'Marginalia Extractor',
        'The Python helper is not configured.\n\nOpen Settings → Marginalia Extractor and choose the "helper" folder from the zotero-marginalia-extractor checkout (or its dist/ binary folder).');
      return;
    }

    const pdfPath = await this._attachmentPath(attachment);
    if (!pdfPath) {
      this._alert(win, 'Marginalia Extractor', 'Could not locate the PDF file on disk.');
      return;
    }
    let scanPath = options.scanPath;
    if (!scanPath) {
      scanPath = await this._pickFile(win, 'Choose the scanned PDF of the same pages');
    }
    if (!scanPath) return;

    const runId = Date.now().toString(36);
    const tempDir = this._ensureTempDir();
    const reviewDir = tempDir + '/review';
    this._ensureDir(reviewDir);
    const paths = {
      config: tempDir + '/config.json',
      output: tempDir + '/result.json',
      progress: tempDir + '/progress.json',
      cancel: tempDir + '/cancel.flag',
      log: tempDir + '/run.log',
    };
    try { await Zotero.File.putContentsAsync(paths.progress, '{}'); } catch (_) {}

    const progress = this._showProgress(win);
    this._run = {
      win,
      attachmentID: attachment.id,
      runId,
      paths,
      progress,
      cancelled: false,
      timer: null,
      pollBusy: false,
    };

    try {
      const config = this.getConfig({
        review_dir: reviewDir,
        progress_path: paths.progress,
        cancel_path: paths.cancel,
        log_path: paths.log,
        map_overrides: options.mapOverrides || {},
      });
      await Zotero.File.putContentsAsync(paths.config, JSON.stringify(config, null, 2));

      this._startProgressPolling();
      const args = [
        '--pdf', pdfPath,
        '--scan', scanPath,
        '--output', paths.output,
        '--config', paths.config,
        '--progress', paths.progress,
        '--cancel', paths.cancel,
        '--review-dir', reviewDir,
        '--log', paths.log,
      ];
      await this._runHelper(args);

      this._stopProgressPolling();
      const raw = await Zotero.File.getContentsAsync(paths.output);
      const result = JSON.parse(raw);
      progress.close();

      if (result.protocol_version !== this.PROTOCOL_VERSION) {
        this._clearRun();
        this._alert(win, 'Marginalia Extractor',
          `Helper protocol mismatch (got ${result.protocol_version}, expected ${this.PROTOCOL_VERSION}).\n\nUpdate the helper and the plugin together.`);
        return;
      }
      this._lastLogPath = paths.log;
      if (this._versionLess(result.helper_version || '0', this.MIN_HELPER_VERSION)) {
        this._alert(win, 'Marginalia Extractor',
          `Helper v${result.helper_version || '?'} is older than the expected v${this.MIN_HELPER_VERSION}.\n\n` +
          'Rebuild or update the helper to use the newest features.');
      }
      if (result.status === 'cancelled') {
        this._clearRun();
        this._alert(win, 'Marginalia Extractor', 'Extraction cancelled.');
        return;
      }

      const session = this._buildSession(attachment, result, runId);
      if (!session.annotations.length) {
        this._clearRun();
        const warn = (result.warnings || []).join('\n');
        this._alert(win, 'Marginalia Extractor',
          'No annotations were detected.' + (warn ? '\n\n' + warn : '') +
          '\n\nTry increasing DPI or checking colour mappings.');
        return;
      }
      this.openReview(win, session);
      this._lastRunPaths = { paths, reviewDir };
      this._clearRun();
    } catch (err) {
      this._stopProgressPolling();
      progress.close();
      this._clearRun();
      this._alert(win, 'Marginalia Extractor', 'Extraction failed:\n\n' + this._describeError(err));
    }
  },

  handleCancel(win) {
    if (!this._run) {
      this._alert(win, 'Marginalia Extractor', 'No extraction is running.');
      return;
    }
    this._run.cancelled = true;
    try {
      Zotero.File.putContentsAsync(this._run.paths.cancel, 'cancel').catch(() => {});
    } catch (_) {}
    this._run.progress.setHeadline('Marginalia: cancelling…');
  },

  _startProgressPolling() {
    const run = this._run;
    if (!run) return;
    run.timer = setInterval(async () => {
      if (!this._run || this._run !== run || run.pollBusy) return;
      run.pollBusy = true;
      try {
        const raw = await Zotero.File.getContentsAsync(run.paths.progress);
        const status = JSON.parse(raw);
        if (status && status.status === 'running') {
          run.progress.setHeadline(`Marginalia: page ${status.done}/${status.total}`);
          run.progress.setDescription(status.message || '');
        } else if (status && status.status === 'starting') {
          run.progress.setHeadline('Marginalia: starting…');
        } else if (status && status.status === 'error') {
          run.progress.setHeadline('Marginalia: error');
          run.progress.setDescription(status.message || '');
        }
      } catch (_) {}
      run.pollBusy = false;
    }, 700);
  },

  _stopProgressPolling() {
    if (this._run?.timer) clearInterval(this._run.timer);
    if (this._run) this._run.timer = null;
  },

  _clearRun() {
    if (this._run?.timer) clearInterval(this._run.timer);
    this._run = null;
  },

  _stopRun() {
    this._stopProgressPolling();
    this._run = null;
  },

  _runHelper(helperArgs) {
    const invocation = this._helperInvocation(helperArgs);
    if (!invocation) {
      return Promise.reject(new Error('The Python helper is not configured.'));
    }
    const internal = Zotero.Utilities.Internal;
    const exec = internal && internal.exec;
    if (typeof exec !== 'function') {
      return Promise.reject(new Error('Zotero.Utilities.Internal.exec is unavailable in this Zotero build.'));
    }
    return new Promise((resolve, reject) => {
      let done = false;
      const finish = (fn, value) => { if (!done) { done = true; fn(value); } };
      try {
        const maybe = exec(invocation.command, invocation.argv);
        if (maybe && typeof maybe.then === 'function') {
          maybe.then((stdout) => finish(resolve, stdout), (err) => finish(reject, err));
        } else {
          finish(resolve, maybe);
        }
      } catch (e) {
        finish(reject, e);
      }
    });
  },

  async handleDiagnose(win) {
    if (!this._helperAvailable()) {
      this._alert(win, 'Marginalia Extractor', 'Set the helper folder in Settings first.');
      return;
    }
    try {
      const tempDir = this._ensureTempDir();
      const configPath = tempDir + '/check-config.json';
      await Zotero.File.putContentsAsync(configPath, JSON.stringify(this.getConfig({}), null, 2));
      const stdout = await this._runHelper(['--check', '--config', configPath]);
      let report;
      try { report = JSON.parse(stdout); } catch (_) { report = stdout; }
      const text = typeof report === 'string' ? report : JSON.stringify(report, null, 2);
      this._alert(win, 'Marginalia Extractor — Setup Check', text.slice(0, 3500));
    } catch (err) {
      this._alert(win, 'Marginalia Extractor — Setup Check', this._describeError(err));
    }
  },

  async handleRemove(win) {
    const attachment = this._resolveAttachment(win);
    if (!attachment) {
      this._alert(win, 'Marginalia Extractor', 'Select a PDF attachment first.');
      return;
    }
    const removed = await this._removeAllForAttachment(attachment);
    this._alert(win, 'Marginalia Extractor', `Removed ${removed} extracted annotation(s).`);
  },

  // ── Mapping preview ───────────────────────────────────────────────────────

  async handlePreviewMapping(win) {
    if (this._run) {
      this._alert(win, 'Marginalia Extractor', 'An extraction is already running.');
      return;
    }
    const attachment = this._resolveAttachment(win);
    if (!attachment) {
      this._alert(win, 'Marginalia Extractor', 'Select a PDF attachment first.');
      return;
    }
    if (!this._helperAvailable()) {
      this._alert(win, 'Marginalia Extractor', 'The helper is not configured.');
      return;
    }
    const pdfPath = await this._attachmentPath(attachment);
    if (!pdfPath) {
      this._alert(win, 'Marginalia Extractor', 'Could not locate the PDF on disk.');
      return;
    }
    const scanPath = await this._pickFile(win, 'Choose the scanned PDF for mapping preview');
    if (!scanPath) return;

    const tempDir = this._ensureTempDir();
    const configPath = tempDir + '/map-config.json';
    const outputPath = tempDir + '/map.json';
    const progress = this._showProgress(win);
    progress.setHeadline('Marginalia: previewing page mapping…');
    try {
      await Zotero.File.putContentsAsync(configPath, JSON.stringify(this.getConfig({}), null, 2));
      await this._runHelper([
        '--pdf', pdfPath,
        '--scan', scanPath,
        '--output', outputPath,
        '--config', configPath,
        '--map-only',
      ]);
      const result = JSON.parse(await Zotero.File.getContentsAsync(outputPath));
      progress.close();
      const args = {
        mapping: result.page_mapping || [],
        pdfPages: result.pdf_pages || [],
        warnings: result.warnings || [],
        result: null,
      };
      win.openDialog(
        this.rootURI + 'content/mapping.xhtml',
        'marginalia-extractor-mapping',
        'chrome,dialog,modal,centerscreen,resizable,width=780,height=640',
        args
      );
      if (args.result && args.result.accept) {
        await this.handleExtract(win, {
          attachment,
          scanPath,
          mapOverrides: args.result.overrides || {},
        });
      }
    } catch (err) {
      progress.close();
      this._alert(win, 'Marginalia Extractor', 'Mapping preview failed:\n\n' + this._describeError(err));
    }
  },

  // ── Run history ───────────────────────────────────────────────────────────

  _runsDir() {
    try {
      const dir = Services.dirsvc.get('ProfD', Components.interfaces.nsIFile);
      dir.append('marginalia-extractor');
      if (!dir.exists()) dir.create(Components.interfaces.nsIFile.DIRECTORY_TYPE, 0o700);
      dir.append('runs');
      if (!dir.exists()) dir.create(Components.interfaces.nsIFile.DIRECTORY_TYPE, 0o700);
      return dir.path;
    } catch (_) {
      return this._ensureTempDir() + '/runs';
    }
  },

  _runFilePath(attachmentID) {
    return this._runsDir() + '/' + attachmentID + '.json';
  },

  async _saveRun(attachment, runId, rows) {
    try {
      const path = this._runFilePath(attachment.id);
      let runs = [];
      try { runs = JSON.parse(await Zotero.File.getContentsAsync(path)); } catch (_) {}
      if (!Array.isArray(runs)) runs = [];
      runs.unshift({
        runId,
        timestamp: new Date().toISOString(),
        count: rows.filter((row) => !row.deleted).length,
        rows,
      });
      runs = runs.slice(0, 20);
      await Zotero.File.putContentsAsync(path, JSON.stringify(runs, null, 2));
    } catch (_) {}
  },

  async _loadRuns(attachment) {
    try {
      const raw = await Zotero.File.getContentsAsync(this._runFilePath(attachment.id));
      const runs = JSON.parse(raw);
      return Array.isArray(runs) ? runs : [];
    } catch (_) {
      return [];
    }
  },

  async _deleteRun(attachment, runId) {
    try {
      const runs = (await this._loadRuns(attachment)).filter((run) => run.runId !== runId);
      await Zotero.File.putContentsAsync(
        this._runFilePath(attachment.id), JSON.stringify(runs, null, 2)
      );
    } catch (_) {}
  },

  async handleHistory(win) {
    const attachment = this._resolveAttachment(win);
    if (!attachment) {
      this._alert(win, 'Marginalia Extractor', 'Select a PDF attachment first.');
      return;
    }
    const runs = await this._loadRuns(attachment);
    const args = { runs, attachmentID: attachment.id, result: null };
    try {
      win.openDialog(
        this.rootURI + 'content/history.xhtml',
        'marginalia-extractor-history',
        'chrome,dialog,modal,centerscreen,resizable,width=780,height=640',
        args
      );
    } catch (e) {
      this._alert(win, 'Marginalia Extractor', 'Could not open history: ' + e);
      return;
    }
    if (!args.result) return;
    if (args.result.delete) {
      await this._deleteRun(attachment, args.result.delete);
    }
    if (args.result.restore) {
      const run = runs.find((item) => item.runId === args.result.restore);
      if (run && run.rows) {
        await this.applyExtraction(win, attachment, run.rows);
      }
    }
  },

  // ── Export ────────────────────────────────────────────────────────────────

  _annotationsFor(attachment) {
    let ids = [];
    try { ids = attachment.getAnnotations() || []; } catch (_) {}
    const items = ids.map((id) => Zotero.Items.get(id)).filter(Boolean);
    items.sort((a, b) => String(a.annotationSortIndex || '').localeCompare(String(b.annotationSortIndex || '')));
    return items;
  },

  _markdown(attachment, annotations) {
    let title = 'Annotations';
    try {
      const parent = attachment.parentItem;
      title = (parent && parent.getField('title')) || attachment.getField('title') || title;
    } catch (_) {}
    const filename = attachment.attachmentFilename || '';
    const lines = [`# ${title}`, '', `Source: ${filename}`, ''];
    for (const item of annotations) {
      const page = item.annotationPageLabel || '';
      const type = item.annotationType || 'highlight';
      const color = item.annotationColor || '';
      const text = (item.annotationText || '').replace(/\s+/g, ' ').trim();
      const comment = (item.annotationComment || '').replace(/\s+/g, ' ').trim();
      lines.push(`- **p. ${page}** · ${type}${color ? ` · ${color}` : ''}`);
      if (text) lines.push(`  > ${text}`);
      if (comment) lines.push(`  ${comment}`);
      lines.push('');
    }
    return lines.join('\n');
  },

  async handleExport(win) {
    const attachment = this._resolveAttachment(win);
    if (!attachment) {
      this._alert(win, 'Marginalia Extractor', 'Select a PDF attachment first.');
      return;
    }
    const annotations = this._annotationsFor(attachment);
    if (!annotations.length) {
      this._alert(win, 'Marginalia Extractor', 'No annotations to export.');
      return;
    }
    const markdown = this._markdown(attachment, annotations);
    const path = await this._pickSaveFile(win, 'Export annotations to Markdown', 'marginalia.md');
    if (!path) return;
    try {
      await Zotero.File.putContentsAsync(path, markdown);
      this._alert(win, 'Marginalia Extractor',
        `Exported ${annotations.length} annotation(s) to:\n\n${path}`);
    } catch (e) {
      this._alert(win, 'Marginalia Extractor', 'Export failed:\n\n' + e);
    }
  },

  // ── Batch ─────────────────────────────────────────────────────────────────

  _batchAttachments(win) {
    let items = [];
    try { items = win.ZoteroPane.getSelectedItems() || []; } catch (_) {}
    const seen = new Set();
    const result = [];
    const add = (attachment) => {
      if (attachment && this._isPdfAttachment(attachment) && !seen.has(attachment.id)) {
        seen.add(attachment.id);
        result.push(attachment);
      }
    };
    for (const item of items) {
      add(item);
      if (!this._isPdfAttachment(item)) {
        try {
          for (const id of item.getAttachments ? item.getAttachments() : []) {
            add(Zotero.Items.get(id));
          }
        } catch (_) {}
      }
    }
    return result;
  },

  async _runToSession(win, attachment, scanPath, mapOverrides = {}) {
    const pdfPath = await this._attachmentPath(attachment);
    if (!pdfPath) return null;
    const tempDir = this._ensureTempDir();
    const reviewDir = tempDir + '/review';
    this._ensureDir(reviewDir);
    const paths = {
      config: tempDir + '/batch-config.json',
      output: tempDir + '/batch-result.json',
      progress: tempDir + '/batch-progress.json',
      cancel: tempDir + '/batch-cancel.flag',
      log: tempDir + '/batch.log',
    };
    const config = this.getConfig({
      review_dir: reviewDir,
      progress_path: paths.progress,
      cancel_path: paths.cancel,
      log_path: paths.log,
      map_overrides: mapOverrides,
    });
    await Zotero.File.putContentsAsync(paths.config, JSON.stringify(config, null, 2));
    await this._runHelper([
      '--pdf', pdfPath,
      '--scan', scanPath,
      '--output', paths.output,
      '--config', paths.config,
      '--progress', paths.progress,
      '--cancel', paths.cancel,
      '--review-dir', reviewDir,
      '--log', paths.log,
    ]);
    const result = JSON.parse(await Zotero.File.getContentsAsync(paths.output));
    if (result.protocol_version !== this.PROTOCOL_VERSION || result.status === 'cancelled') {
      return null;
    }
    this._lastRunPaths = { paths, reviewDir };
    return this._buildSession(attachment, result, Date.now().toString(36));
  },

  async handleBatch(win) {
    if (this._run) {
      this._alert(win, 'Marginalia Extractor', 'An extraction is already running.');
      return;
    }
    const attachments = this._batchAttachments(win);
    if (!attachments.length) {
      this._alert(win, 'Marginalia Extractor', 'Select one or more PDF attachments first.');
      return;
    }
    const pairs = [];
    for (let i = 0; i < attachments.length; i++) {
      const name = attachments[i].attachmentFilename || 'PDF';
      const scan = await this._pickFile(win, `Scan for ${name} (${i + 1}/${attachments.length})`);
      if (scan) pairs.push({ attachment: attachments[i], scan });
    }
    if (!pairs.length) return;
    const ok = Services.prompt.confirm(
      win,
      'Batch Marginalia Extraction',
      `Run ${pairs.length} extraction(s)?\n\nAnnotations will be applied without opening the review window.`
    );
    if (!ok) return;

    const progress = this._showProgress(win);
    let created = 0;
    let removed = 0;
    let failed = 0;
    for (let i = 0; i < pairs.length; i++) {
      progress.setHeadline(`Marginalia batch: ${i + 1}/${pairs.length}`);
      try {
        const session = await this._runToSession(win, pairs[i].attachment, pairs[i].scan);
        if (!session) { failed++; continue; }
        const result = await this.applyExtraction(win, pairs[i].attachment, session.annotations, { silent: true });
        created += result.created || 0;
        removed += result.removed || 0;
      } catch (e) {
        failed++;
        Zotero.debug('[Marginalia] batch item failed: ' + e);
      }
    }
    progress.close();
    this._alert(win, 'Marginalia Extractor',
      `Batch complete.\n\nCreated: ${created}\nReplaced: ${removed}\nFailed: ${failed}`);
  },

  handleOpenLog(win) {
    if (!this._lastLogPath || !this._fileExists(this._lastLogPath)) {
      this._alert(win, 'Marginalia Extractor', 'No log yet. Run an extraction first.');
      return;
    }
    try {
      const nsIFile = Components.interfaces.nsIFile;
      const file = Components.classes['@mozilla.org/file/local;1'].createInstance(nsIFile);
      file.initWithPath(this._lastLogPath);
      file.launch();
    } catch (_) {
      this._alert(win, 'Marginalia Extractor', 'Log file:\n\n' + this._lastLogPath);
    }
  },

  // ── Annotation creation ───────────────────────────────────────────────────

  async applyExtraction(win, attachment, rows, options = {}) {
    if (!attachment) {
      if (!options.silent) this._alert(win, 'Marginalia Extractor', 'The PDF attachment no longer exists.');
      return { created: 0, removed: 0 };
    }
    const replace = this.getPref('replacePrevious', true);
    // Stage first: remember the old run, but do not delete it until the new
    // annotations have been created successfully.
    const previous = replace ? await this._taggedAnnotationIDs(attachment) : [];

    const runId = Date.now().toString(36);
    let created = 0;
    for (const row of rows) {
      if (row.deleted) continue;
      try {
        const item = new Zotero.Item('annotation');
        item.libraryID = attachment.libraryID;
        item.parentID = attachment.id;
        item.annotationType = row.type || 'highlight';
        item.annotationColor = row.color || '#ffd400';
        item.annotationText = row.text || '';
        item.annotationComment = row.comment || '';
        item.annotationIsExternal = false;
        item.annotationPageLabel = row.pageLabel || '';
        item.annotationSortIndex = row.sortIndex || '';
        item.annotationPosition = JSON.stringify(this._positionForRow(row));
        item.addTag(this.RUN_TAG, 0);
        item.addTag(this.RUN_TAG_PREFIX + runId, 0);
        if (row.scanLabel) item.addTag(this.SCAN_TAG_PREFIX + row.scanLabel, 0);
        await item.saveTx();
        created++;
      } catch (e) {
        Zotero.debug('[Marginalia] create failed: ' + e);
      }
    }
    let removed = 0;
    if (replace && previous.length) {
      removed = await this._eraseItems(previous);
    }
    await this._writeSidecar(attachment, runId, rows);
    await this._saveRun(attachment, runId, rows);
    this._cleanupRunFiles();
    if (!options.silent) {
      this._alert(win, 'Marginalia Extractor',
        `Applied.\n\nCreated: ${created}\nReplaced previous: ${removed}`);
    }
    return { created, removed };
  },

  _cleanupRunFiles() {
    const info = this._lastRunPaths;
    if (!info) return;
    this._lastRunPaths = null;
    try {
      const nsIFile = Components.interfaces.nsIFile;
      const local = Components.classes['@mozilla.org/file/local;1'];
      for (const [key, path] of Object.entries(info.paths || {})) {
        if (key === 'log') continue;
        try {
          const file = local.createInstance(nsIFile);
          file.initWithPath(path);
          if (file.exists()) file.remove(false);
        } catch (_) {}
      }
      try {
        const dir = local.createInstance(nsIFile);
        dir.initWithPath(info.reviewDir);
        if (dir.exists()) dir.remove(true);
      } catch (_) {}
    } catch (_) {}
  },

  async _taggedAnnotationIDs(attachment) {
    let ids = [];
    try { ids = attachment.getAnnotations() || []; } catch (_) {}
    const tagged = [];
    for (const id of ids) {
      const item = Zotero.Items.get(id);
      if (!item) continue;
      let tags = [];
      try { tags = item.getTags() || []; } catch (_) {}
      if (tags.some((t) => t.tag === this.RUN_TAG)) tagged.push(id);
    }
    return tagged;
  },

  async _eraseItems(ids) {
    let removed = 0;
    for (const id of ids) {
      const item = Zotero.Items.get(id);
      if (!item) continue;
      try { await item.eraseTx(); removed++; } catch (_) {}
    }
    return removed;
  },

  async _removeAllForAttachment(attachment) {
    const ids = await this._taggedAnnotationIDs(attachment);
    return this._eraseItems(ids);
  },

  async _writeSidecar(attachment, runId, rows) {
    try {
      const dir = this._ensureTempDir() + '/runs';
      this._ensureDir(dir);
      const payload = {
        attachmentID: attachment.id,
        runId,
        appliedAt: new Date().toISOString(),
        count: rows.filter((r) => !r.deleted).length,
      };
      await Zotero.File.putContentsAsync(dir + '/' + attachment.id + '.json', JSON.stringify(payload, null, 2));
    } catch (_) {}
  },

  // ── Review session ────────────────────────────────────────────────────────

  _positionForRow(row) {
    const position = {
      pageIndex: row.pageIndex,
      rects: row.rects || [],
    };
    if (row.nextPageRects && row.nextPageRects.length) {
      position.nextPageRects = row.nextPageRects;
    }
    return position;
  },

  _buildSession(attachment, result, runId) {
    const pagesByUnit = new Map();
    const annotations = [];

    // Include pages with detections, plus any page referenced as the second
    // half of a cross-page annotation (its images were saved before merging).
    const needed = new Set();
    for (const page of result.pages || []) {
      if (page.error) continue;
      if ((page.annotations || []).length) needed.add(page.pdf_index);
      for (const ann of page.annotations || []) {
        if (ann.next_page_index !== null && ann.next_page_index !== undefined) {
          needed.add(ann.next_page_index);
        }
      }
    }

    for (const page of result.pages || []) {
      if (page.error) continue;
      if (!needed.has(page.pdf_index)) continue;
      const unit = page.scan_label || String(page.scan_index + 1);
      const images = page.images || {};
      pagesByUnit.set(unit, {
        unit,
        pageIndex: page.pdf_index,
        pageLabel: page.page_label,
        widthPts: page.width_pts,
        heightPts: page.height_pts,
        dpi: page.dpi || 200,
        model: page.model || { sentences: [] },
        images: {
          scan: images.scan ? this._toFileURL(images.scan) : null,
          pdf: images.pdf ? this._toFileURL(images.pdf) : null,
        },
        alignment: page.alignment,
      });
      let counter = 0;
      for (const ann of page.annotations || []) {
        annotations.push({
          rowId: `${unit}-${counter++}`,
          unit,
          scanLabel: unit,
          pageIndex: page.pdf_index,
          pageLabel: page.page_label,
          type: ann.type,
          color: ann.color,
          rects: ann.rects || [],
          text: ann.text || '',
          comment: ann.comment || '',
          source: ann.source || '',
          method: ann.association_method || '',
          confidence: ann.confidence || 0,
          sortIndex: ann.sort_index || '',
          candidates: ann.candidates || [],
          nextPageRects: ann.next_page_rects || [],
          nextPageIndex: ann.next_page_index || null,
          deleted: false,
        });
      }
    }
    return {
      attachmentID: attachment.id,
      runId,
      sourcePdf: result.source_pdf || '',
      scanPdf: result.scan_pdf || '',
      pageCount: pagesByUnit.size,
      warnings: result.warnings || [],
      mapping: result.page_mapping || [],
      pages: Array.from(pagesByUnit.values()),
      annotations,
    };
  },

  openReview(win, session) {
    session.defaults = {
      color: this.getPref('defaultNewColor', '#ffd400'),
      type: this.getPref('defaultNewType', 'highlight'),
      lowConfidence: parseFloat(this.getPref('lowConfidence', '0.35')) || 0.35,
    };
    const params = {
      session,
      onApply: (rows) => this.applyExtraction(win, Zotero.Items.get(session.attachmentID), rows),
    };
    try {
      win.openDialog(
        this.rootURI + 'content/review.xhtml',
        'marginalia-extractor-review',
        'chrome,centerscreen,resizable,width=1180,height=780',
        params
      );
    } catch (e) {
      Zotero.debug('[Marginalia] review failed: ' + e);
      this._alert(win, 'Marginalia Extractor', 'Could not open the review window: ' + e);
    }
  },

  // ── Utilities ─────────────────────────────────────────────────────────────

  _versionLess(value, minimum) {
    const parse = (v) => String(v || '0').split('.').map((n) => parseInt(n, 10) || 0);
    const a = parse(value);
    const b = parse(minimum);
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const x = a[i] || 0;
      const y = b[i] || 0;
      if (x !== y) return x < y;
    }
    return false;
  },

  async _attachmentPath(attachment) {
    try { return await attachment.getFilePathAsync(); } catch (_) {}
    try {
      const f = attachment.getFile();
      return f ? f.path : null;
    } catch (_) {}
    return null;
  },

  _toFileURL(path) {
    if (!path) return null;
    let p = String(path).replace(/\\/g, '/');
    if (!p.startsWith('/')) p = '/' + p;
    return 'file://' + encodeURI(p).replace(/#/g, '%23');
  },

  _ensureTempDir() {
    const dir = Zotero.getTempDirectory();
    dir.append('marginalia-extractor');
    if (!dir.exists()) dir.create(Components.interfaces.nsIFile.DIRECTORY_TYPE, 0o700);
    return dir.path;
  },

  _ensureDir(path) {
    try {
      const nsIFile = Components.interfaces.nsIFile;
      const dir = Components.classes['@mozilla.org/file/local;1'].createInstance(nsIFile);
      dir.initWithPath(path);
      if (!dir.exists()) dir.create(nsIFile.DIRECTORY_TYPE, 0o700);
    } catch (_) {}
  },

  _pickFile(win, title) {
    return new Promise((resolve) => {
      try {
        const nsIFilePicker = Components.interfaces.nsIFilePicker;
        const picker = Components.classes['@mozilla.org/filepicker;1'].createInstance(nsIFilePicker);
        picker.init(win, title, nsIFilePicker.modeOpen);
        try { picker.appendFilters(nsIFilePicker.filterPDF); } catch (_) {}
        let settled = false;
        const done = (rv) => {
          if (settled) return;
          settled = true;
          resolve(rv === nsIFilePicker.returnOK && picker.file ? picker.file.path : null);
        };
        const maybe = picker.open(done);
        if (maybe && typeof maybe.then === 'function') {
          maybe.then(() => done(nsIFilePicker.returnOK)).catch(() => done(nsIFilePicker.returnCancel));
        }
      } catch (_) {
        resolve(null);
      }
    });
  },

  _pickSaveFile(win, title, defaultName) {
    return new Promise((resolve) => {
      try {
        const nsIFilePicker = Components.interfaces.nsIFilePicker;
        const picker = Components.classes['@mozilla.org/filepicker;1'].createInstance(nsIFilePicker);
        picker.init(win, title, nsIFilePicker.modeSave);
        try { picker.defaultString = defaultName; } catch (_) {}
        let settled = false;
        const done = (rv) => {
          if (settled) return;
          settled = true;
          const ok = rv === nsIFilePicker.returnOK || rv === nsIFilePicker.returnReplace;
          resolve(ok && picker.file ? picker.file.path : null);
        };
        const maybe = picker.open(done);
        if (maybe && typeof maybe.then === 'function') {
          maybe.then(() => done(nsIFilePicker.returnOK)).catch(() => done(nsIFilePicker.returnCancel));
        }
      } catch (_) {
        resolve(null);
      }
    });
  },

  _alert(win, title, text) {
    try { Services.prompt.alert(win, title, text); }
    catch (_) { Zotero.debug('[Marginalia] ' + title + ': ' + text); }
  },

  _describeError(err) {
    if (!err) return 'Unknown error';
    if (typeof err === 'string') return err;
    const parts = [];
    if (err.message) parts.push(err.message);
    if (err.stderr) parts.push(err.stderr);
    if (err.stdout) parts.push(err.stdout);
    return parts.join('\n') || String(err);
  },

  _showProgress(win) {
    let pw = null;
    try {
      pw = new Zotero.ProgressWindow({ closeOnClick: false });
      pw.changeHeadline('Marginalia Extractor');
      pw.show();
    } catch (_) {}
    return {
      setHeadline: (text) => { try { pw?.changeHeadline(text); } catch (_) {} },
      setDescription: (_text) => {},
      close: () => { try { pw?.startCloseTimer(600); } catch (_) {} },
    };
  },
};
