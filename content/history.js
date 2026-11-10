"use strict";

/* global window, document */

function el(tag) {
  return document.createElementNS("http://www.w3.org/1999/xhtml", tag);
}

// window.arguments[0] = { runs, attachmentID, result: null }
// result: { restore: runId } or { delete: runId }

function mhInit() {
  const args = window.arguments && window.arguments[0];
  if (!args) { window.close(); return; }
  const list = document.getElementById("mh-list");
  list.innerHTML = "";

  const runs = args.runs || [];
  if (!runs.length) {
    const empty = el("div");
    empty.id = "mh-empty";
    empty.textContent = "No runs recorded for this PDF yet.";
    list.appendChild(empty);
  }

  runs.forEach((run) => {
    const row = el("div");
    row.className = "mh-row";

    const info = el("div");
    const date = el("div");
    date.className = "mh-date";
    date.textContent = new Date(run.timestamp).toLocaleString();
    const meta = el("div");
    meta.className = "mh-meta";
    meta.textContent = `${run.count || 0} annotation(s) · run ${run.runId}`;
    info.appendChild(date);
    info.appendChild(meta);
    row.appendChild(info);

    const spacer = el("div");
    spacer.className = "mh-spacer";
    row.appendChild(spacer);

    const restore = el("button");
    restore.className = "mh-btn mh-restore";
    restore.textContent = "Restore";
    restore.addEventListener("click", () => {
      args.result = { restore: run.runId };
      window.close();
    });
    row.appendChild(restore);

    const del = el("button");
    del.className = "mh-btn mh-delete";
    del.textContent = "Delete";
    del.addEventListener("click", () => {
      args.result = { delete: run.runId };
      window.close();
    });
    row.appendChild(del);

    list.appendChild(row);
  });

  document.getElementById("mh-close")?.addEventListener("click", () => window.close());
}

window.addEventListener("load", mhInit);
