/* global Zotero, Services */
/* eslint-disable no-unused-vars */

var MarginaliaExtractor;

function log(msg) {
  Zotero.debug('[MarginaliaExtractor] ' + msg);
}

async function startup({ id, version, rootURI }) {
  log('Starting up v' + version);

  Services.scriptloader.loadSubScript(rootURI + 'content/marginaliaExtractor.js');

  await Zotero.initializationPromise;

  MarginaliaExtractor.init({ id, version, rootURI });

  for (const win of Zotero.getMainWindows()) {
    MarginaliaExtractor.addToWindow(win);
  }
}

function onMainWindowLoad({ window }) {
  MarginaliaExtractor?.addToWindow(window);
}

function onMainWindowUnload({ window }) {
  MarginaliaExtractor?.removeFromWindow(window);
}

function shutdown() {
  log('Shutting down');
  MarginaliaExtractor?.shutdown();
  MarginaliaExtractor = undefined;
}

function install() {
  log('Installed');
}

function uninstall() {
  log('Uninstalled');
}
