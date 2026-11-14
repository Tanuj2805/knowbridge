/** The "This file" panel's page: plain HTML and script, no VS Code imports (so it can be previewed in a browser). */

function nonce(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  return Array.from({ length: 32 }, () => chars[Math.floor(Math.random() * chars.length)]).join("");
}

export function html(cspSource: string): string {
  const n = nonce();
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'nonce-${n}'; script-src 'nonce-${n}';">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style nonce="${n}">
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); color: var(--vscode-foreground); padding: 4px 10px 16px; line-height: 1.45; }
  h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--vscode-descriptionForeground); margin: 16px 0 6px; font-weight: 600; }
  .path { font-family: var(--vscode-editor-font-family); font-size: 12px; color: var(--vscode-descriptionForeground); word-break: break-all; }
  .muted { color: var(--vscode-descriptionForeground); }
  .note { font-size: 12px; color: var(--vscode-descriptionForeground); margin-top: 6px; }
  .warn { color: var(--vscode-editorWarning-foreground); }
  .owner { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12px; }
  .bar { flex: 1; height: 5px; border-radius: 3px; background: var(--vscode-editorWidget-border, #8884); overflow: hidden; }
  .bar > span { display: block; height: 100%; background: var(--vscode-progressBar-background); }
  .claim { border-top: 1px solid var(--vscode-editorWidget-border, #8883); padding: 8px 0; }
  .meta { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; color: var(--vscode-descriptionForeground); }
  .grade { display: inline-flex; align-items: center; gap: 4px; font-weight: 600; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; display: inline-block; }
  .g-verified { color: #3fb950; } .g-supported { color: #39c5cf; } .g-attested { color: #d29922; }
  .g-inferred { color: #8b949e; } .g-conflicting { color: #f0883e; } .g-missing { color: #f85149; }
  .statement { margin: 3px 0; }
  a { color: var(--vscode-textLink-foreground); text-decoration: none; cursor: pointer; }
  a:hover { text-decoration: underline; }
  .sources { margin: 2px 0 0; padding: 0; list-style: none; font-size: 11.5px; }
  .sources li { margin: 1px 0; }
  form { display: flex; gap: 6px; margin-top: 6px; }
  input { flex: 1; min-width: 0; background: var(--vscode-input-background); color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, transparent); padding: 4px 6px; border-radius: 2px; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: 0; padding: 4px 10px; border-radius: 2px; cursor: pointer; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  .answer { white-space: pre-wrap; margin-top: 8px; }
</style></head>
<body>
<div id="file"></div>
<h2>Ask the project</h2>
<form id="ask"><input id="q" placeholder="Why is it built this way?" maxlength="1000"><button type="submit">Ask</button></form>
<div id="answer"></div>
<script nonce="${n}">
const vscode = acquireVsCodeApi();
const $ = (id) => document.getElementById(id);
function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) { if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v); }
  for (const k of kids) if (k) e.append(k);
  return e;
}
function link(text, url) {
  const a = el("a", { text });
  a.addEventListener("click", (ev) => { ev.preventDefault(); vscode.postMessage({ type: "open", url }); });
  return a;
}
const day = (iso) => (iso ? String(iso).slice(0, 10) : "");
let labels = { grade: {}, type: {} };

function renderContext(m) {
  labels = m.labels;
  const c = m.ctx, root = $("file");
  root.replaceChildren();
  root.append(el("div", { class: "path", text: c.path || "(repository root)" }));
  if (m.linked === false) root.append(el("div", { class: "note warn", text: "This repository isn't one of " + m.project + "'s sources, so little may match." }));
  if (!c.found) {
    root.append(el("p", { class: "muted", text: "Nothing is recorded about this file in " + m.project + " yet." }));
    if (c.withheld) root.append(el("p", { class: "note", text: c.withheld + " claim(s) about it are withheld from you." }));
    return;
  }
  if (c.owners.length) {
    root.append(el("h2", { text: "Who changed it · " + c.commits + " commit" + (c.commits === 1 ? "" : "s") }));
    for (const o of c.owners) {
      const bar = el("div", { class: "bar" }, el("span", { style: "width:" + Math.round(o.share * 100) + "%" }));
      root.append(el("div", { class: "owner" }, el("span", { text: o.name }), bar, el("span", { class: "muted", text: Math.round(o.share * 100) + "%" })));
    }
    if (c.created_by) root.append(el("div", { class: "note", text: "Created by " + c.created_by + (c.created_at ? " on " + day(c.created_at) : "") + " (earliest commit KnowBridge has)" }));
  } else {
    root.append(el("p", { class: "note", text: c.repo_commits
      ? "No commits in the connected GitHub repository touched this file."
      : "No GitHub repository with commits is connected to " + m.project + ", so who wrote this file isn't known. Add the repository under Sources in KnowBridge." }));
  }
  if (c.claims.length) {
    root.append(el("h2", { text: "What the project knows · " + c.claims.length }));
    for (const x of c.claims) {
      const meta = el("div", { class: "meta" },
        el("span", { text: labels.type[x.type] || x.type }),
        el("span", { class: "grade g-" + x.grade }, el("span", { class: "dot" }), document.createTextNode(labels.grade[x.grade] || x.grade)),
        (x.status === "approved" || x.status === "edited") ? el("span", { text: "approved" }) : null,
        el("span", { text: x.why }));
      const sources = el("ul", { class: "sources" });
      for (const s of x.sources.slice(0, 3)) {
        const label = s.source_name + ": " + (s.title || s.kind) + (s.occurred_at ? " · " + day(s.occurred_at) : "");
        sources.append(el("li", {}, s.permalink ? link(label, s.permalink) : el("span", { class: "muted", text: label })));
      }
      const block = el("div", { class: "claim" }, meta, el("div", { class: "statement", text: x.statement }), sources);
      if (x.url) block.append(link("Open in KnowBridge", x.url));
      root.append(block);
    }
  }
  if (c.withheld) root.append(el("p", { class: "note", text: c.withheld + " more claim(s) about this file are withheld from you." }));
  if (c.approved_only) root.append(el("p", { class: "note", text: "Showing approved claims only." }));
}

window.addEventListener("message", (ev) => {
  const m = ev.data, root = $("file");
  if (m.type === "needsConnect") {
    root.replaceChildren(el("p", { text: "Connect KnowBridge to see what your project knows about the file you have open." }));
    const b = el("button", { text: "Connect" }); b.addEventListener("click", () => vscode.postMessage({ type: "connect" }));
    root.append(b);
  } else if (m.type === "idle") {
    root.replaceChildren(el("p", { class: "muted", text: m.note || "Open a file to see what " + m.project + " knows about it." }));
  } else if (m.type === "loading") {
    root.replaceChildren(el("div", { class: "path", text: m.path }), el("p", { class: "muted", text: "Looking it up…" }));
  } else if (m.type === "error") {
    root.replaceChildren(el("div", { class: "path", text: m.path }), el("p", { class: "warn", text: m.message }));
  } else if (m.type === "context") {
    renderContext(m);
  } else if (m.type === "asking") {
    $("answer").replaceChildren(el("p", { class: "muted", text: "Asking about “" + m.question + "”" + (m.path ? " (about " + m.path.split("/").pop() + ")" : "") + "…" }));
  } else if (m.type === "answer") {
    const box = $("answer");
    if (m.error) return box.replaceChildren(el("p", { class: "warn", text: m.error }));
    const a = m.answer;
    box.replaceChildren(el("div", { class: "answer", text: a.answer || a.error || "No answer." }));
    const cited = (a.citations && a.citations.length ? a.citations : (a.sources || []).slice(0, 4));
    if (cited.length) {
      box.append(el("h2", { text: "Sources" }));
      const list = el("ul", { class: "sources" });
      for (const s of cited) {
        const t = "[" + s.ref + "] " + (s.kind === "claim" ? (s.type_label || "Claim") + " · " + (labels.grade[s.grade] || s.grade || "") + ": " : (s.source || "Source") + ": ") + s.title;
        list.append(el("li", { text: t }));
      }
      box.append(list);
    }
  }
});
$("ask").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = $("q").value.trim();
  if (q) vscode.postMessage({ type: "ask", question: q });
});
vscode.postMessage({ type: "ready" });
</script></body></html>`;
}
