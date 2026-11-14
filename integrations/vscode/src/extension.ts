/**
 * KnowBridge for VS Code.
 *
 *  - The "This file" panel shows, for the file you have open, who changed it and the decisions, risks
 *    and other claims about it, each with its grade and a link to its evidence. Ask the project a
 *    question from the same panel.
 *  - The status bar says how much KnowBridge knows about the open file.
 *  - Copilot's agent mode gets KnowBridge's tools: the extension registers the KnowBridge MCP server.
 *
 * Settings: the website address (knowbridge.url) and a personal access token, kept in VS Code's secret
 * storage. The token is read-only and opens one project; KnowBridge checks every request.
 */
import { execFile } from "node:child_process";
import * as path from "node:path";
import * as vscode from "vscode";
import { type CodeContext, KnowBridge, KnowBridgeError, type WhoAmI, gradeLabel, typeLabel } from "../../shared/knowbridge";
import { html } from "./panel";

const SECRET = "knowbridge.token";
const CACHE_MS = 2 * 60_000;

type Repo = { root: string; remote: string; linked: boolean | null };

let kb: KnowBridge | undefined;
let who: WhoAmI | undefined;
const repos = new Map<string, Repo>(); // by workspace folder
const cache = new Map<string, { at: number; ctx: CodeContext }>();

function git(cwd: string, ...args: string[]): Promise<string> {
  return new Promise((resolve) =>
    execFile("git", args, { cwd, timeout: 5000, windowsHide: true }, (err, out) => resolve(err ? "" : out.trim())),
  );
}

async function repoFor(file: vscode.Uri): Promise<Repo | undefined> {
  const folder = vscode.workspace.getWorkspaceFolder(file);
  if (!folder) return undefined;
  const key = folder.uri.fsPath;
  let repo = repos.get(key);
  if (!repo) {
    const root = (await git(key, "rev-parse", "--show-toplevel")) || key;
    const remote = await git(key, "config", "--get", "remote.origin.url");
    repo = { root: path.normalize(root), remote, linked: null };
    if (remote && kb && who) {
      try {
        const found = await kb.resolve(remote);
        repo.linked = found.projects.some((p) => p.id === who!.project.id);
      } catch {
        repo.linked = null;
      }
    }
    repos.set(key, repo);
  }
  return repo;
}

async function connect(context: vscode.ExtensionContext, interactive: boolean): Promise<boolean> {
  const config = vscode.workspace.getConfiguration("knowbridge");
  // KNOWBRIDGE_URL / KNOWBRIDGE_TOKEN in the environment work too (for automated tests and dev containers).
  let url = config.get<string>("url", "") || process.env.KNOWBRIDGE_URL || "";
  let token = (await context.secrets.get(SECRET)) || process.env.KNOWBRIDGE_TOKEN || "";
  if (interactive) {
    const u = await vscode.window.showInputBox({
      title: "KnowBridge: your website address",
      prompt: "The address you open KnowBridge at, e.g. https://knowbridge.example.com",
      value: url || "https://",
      ignoreFocusOut: true,
      validateInput: (v) => (/^https?:\/\/\S+$/.test(v.trim()) ? undefined : "Start with https:// (or http:// for a local KnowBridge)"),
    });
    if (!u) return false;
    const t = await vscode.window.showInputBox({
      title: "KnowBridge: access token",
      prompt: "Make one in KnowBridge: open the project, then Editor → Make a token. It starts with kb_.",
      password: true,
      ignoreFocusOut: true,
      validateInput: (v) => (v.trim().startsWith("kb_") ? undefined : "An access token starts with kb_"),
    });
    if (!t) return false;
    url = u.trim().replace(/\/+$/, "");
    token = t.trim();
  }
  if (!url || !token) return false;

  const client = new KnowBridge({ url, token });
  try {
    who = await client.whoami(true);
  } catch (e) {
    kb = undefined;
    who = undefined;
    if (interactive || (e instanceof KnowBridgeError && e.status === 401)) {
      vscode.window.showErrorMessage(`KnowBridge: ${(e as Error).message}`);
    }
    return false;
  }
  kb = client;
  if (interactive) {
    await config.update("url", url, vscode.ConfigurationTarget.Global);
    await context.secrets.store(SECRET, token);
    vscode.window.showInformationMessage(
      `KnowBridge: connected to ${who.project.name} as ${who.user.name}` +
        (who.approved_only ? " (approved claims only)." : "."),
    );
  }
  repos.clear();
  cache.clear();
  return true;
}

class FilePanel implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private current = "";
  private timer?: NodeJS.Timeout;

  constructor(
    private context: vscode.ExtensionContext,
    private status: vscode.StatusBarItem,
  ) {}

  resolveWebviewView(view: vscode.WebviewView) {
    this.view = view;
    view.webview.options = { enableScripts: true, localResourceRoots: [] };
    view.webview.html = html(view.webview.cspSource);
    view.webview.onDidReceiveMessage(async (m) => {
      if (m.type === "open" && typeof m.url === "string" && /^https?:\/\//.test(m.url)) {
        vscode.env.openExternal(vscode.Uri.parse(m.url));
      } else if (m.type === "connect") {
        vscode.commands.executeCommand("knowbridge.connect");
      } else if (m.type === "ask" && typeof m.question === "string") {
        await this.ask(m.question);
      } else if (m.type === "ready") {
        this.update(true);
      }
    });
    view.onDidChangeVisibility(() => view.visible && this.update());
  }

  private post(message: unknown) {
    this.view?.webview.postMessage(message);
  }

  async ask(question: string) {
    if (!kb) return this.post({ type: "needsConnect" });
    this.post({ type: "asking", question, path: this.current });
    try {
      // the open file goes with the question: "who owns this file?" means that file
      const a = await kb.ask(question.slice(0, 1000), this.current || undefined);
      this.post({ type: "answer", question, answer: a });
    } catch (e) {
      this.post({ type: "answer", question, error: (e as Error).message });
    }
  }

  schedule() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.update(), 350);
  }

  async update(force = false) {
    const editor = vscode.window.activeTextEditor;
    if (!kb || !who) {
      this.status.text = "$(plug) KnowBridge";
      this.status.tooltip = "Connect KnowBridge";
      this.status.command = "knowbridge.connect";
      this.status.show();
      return this.post({ type: "needsConnect" });
    }
    this.status.command = "workbench.view.extension.knowbridge";
    if (!editor || editor.document.uri.scheme !== "file") {
      this.status.hide();
      return this.post({ type: "idle", project: who.project.name });
    }
    const repo = await repoFor(editor.document.uri);
    if (!repo) {
      this.status.hide();
      return this.post({ type: "idle", project: who.project.name, note: "Open a file inside a workspace folder." });
    }
    const rel = path.relative(repo.root, editor.document.uri.fsPath).split(path.sep).join("/");
    if (rel.startsWith("..")) return this.post({ type: "idle", project: who.project.name });
    if (!force && rel === this.current && cache.has(rel)) return;
    this.current = rel;

    const hit = cache.get(rel);
    let ctx: CodeContext;
    if (!force && hit && Date.now() - hit.at < CACHE_MS) {
      ctx = hit.ctx;
    } else {
      this.post({ type: "loading", path: rel });
      try {
        ctx = await kb.codeContext(rel);
        cache.set(rel, { at: Date.now(), ctx });
      } catch (e) {
        this.status.text = "$(warning) KnowBridge";
        this.status.tooltip = (e as Error).message;
        this.status.show();
        return this.post({ type: "error", path: rel, message: (e as Error).message });
      }
    }
    if (rel !== this.current) return; // the user moved on while we were asking
    const risks = (ctx.counts.risk ?? 0) + (ctx.counts.blocker ?? 0);
    const owner = ctx.owners[0];
    this.status.text = ctx.found
      ? `$(book) ${ctx.claims.length}${risks ? ` · $(warning) ${risks}` : ""}${owner ? ` · ${owner.name.split(" ")[0]}` : ""}`
      : "$(book) KnowBridge";
    this.status.tooltip = ctx.found
      ? `KnowBridge: ${ctx.claims.length} claim(s) about ${rel}${owner ? `, mostly changed by ${owner.name}` : ""}`
      : `KnowBridge has nothing recorded about ${rel}`;
    this.status.show();
    this.post({
      type: "context",
      ctx,
      project: who.project.name,
      linked: repo.linked,
      labels: { grade: Object.fromEntries(["verified", "supported", "attested", "inferred", "conflicting", "missing"].map((g) => [g, gradeLabel(g)])), type: Object.fromEntries(Object.keys({ owner: 1, decision: 1, risk: 1, blocker: 1, dependency: 1, recurring_problem: 1, open_question: 1, next_action: 1, contact: 1 }).map((t) => [t, typeLabel(t)])) },
    });
  }
}

export async function activate(context: vscode.ExtensionContext) {
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 90);
  context.subscriptions.push(status);
  const panel = new FilePanel(context, status);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider("knowbridge.file", panel));

  // Copilot agent mode (and any MCP client in VS Code) gets KnowBridge's tools. The token is added only
  // when the server is started, never kept in the server's definition.
  const mcpChanged = new vscode.EventEmitter<void>();
  const mcpScript = vscode.Uri.joinPath(context.extensionUri, "dist", "knowbridge-mcp.mjs").fsPath;
  if (vscode.lm && typeof vscode.lm.registerMcpServerDefinitionProvider === "function") {
    context.subscriptions.push(
      vscode.lm.registerMcpServerDefinitionProvider("knowbridge.mcp", {
        onDidChangeMcpServerDefinitions: mcpChanged.event,
        provideMcpServerDefinitions: async () => {
          const url = vscode.workspace.getConfiguration("knowbridge").get<string>("url", "");
          if (!url || !(await context.secrets.get(SECRET))) return [];
          // VS Code's own runtime runs the server as plain Node, so nothing else needs installing.
          return [
            new vscode.McpStdioServerDefinition("KnowBridge", process.execPath, [mcpScript], {
              ELECTRON_RUN_AS_NODE: "1",
              KNOWBRIDGE_URL: url,
            }, "1.0.0"),
          ];
        },
        resolveMcpServerDefinition: async (def) => {
          const token = await context.secrets.get(SECRET);
          if (!token) {
            vscode.window.showWarningMessage("KnowBridge: connect first (KnowBridge: Connect).");
            return undefined;
          }
          if (def instanceof vscode.McpStdioServerDefinition) def.env = { ...def.env, KNOWBRIDGE_TOKEN: token };
          return def;
        },
      }),
    );
  }

  context.subscriptions.push(
    vscode.commands.registerCommand("knowbridge.connect", async () => {
      if (await connect(context, true)) {
        mcpChanged.fire();
        panel.update(true);
      }
    }),
    vscode.commands.registerCommand("knowbridge.disconnect", async () => {
      await context.secrets.delete(SECRET);
      kb = undefined;
      who = undefined;
      cache.clear();
      mcpChanged.fire();
      panel.update(true);
      vscode.window.showInformationMessage("KnowBridge: disconnected. The token is removed from this computer.");
    }),
    vscode.commands.registerCommand("knowbridge.refresh", () => {
      cache.clear();
      panel.update(true);
    }),
    vscode.commands.registerCommand("knowbridge.openProject", () => {
      if (who) vscode.env.openExternal(vscode.Uri.parse(`${who.web_url}/projects/${who.project.id}`));
    }),
    vscode.commands.registerCommand("knowbridge.ask", async () => {
      const q = await vscode.window.showInputBox({
        title: "Ask KnowBridge",
        prompt: "Answered from the project's own record, with sources",
        placeHolder: "Why does payments use polling instead of webhooks?",
      });
      if (!q?.trim()) return;
      await vscode.commands.executeCommand("knowbridge.file.focus");
      await panel.ask(q.trim());
    }),
    vscode.window.onDidChangeActiveTextEditor(() => panel.schedule()),
    vscode.workspace.onDidSaveTextDocument(() => panel.schedule()),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("knowbridge.url")) connect(context, false).then(() => panel.update(true));
    }),
  );

  await connect(context, false);
  panel.update(true);
}

export function deactivate() {}
