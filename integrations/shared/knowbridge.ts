/**
 * A small client for KnowBridge's editor API, shared by the MCP server and the VS Code extension.
 *
 * It talks to the website's public door (`<site>/api/v1/...`) with a personal access token. The token is
 * read-only and opens one project; KnowBridge applies the same permission checks as on the website.
 */

export type Settings = { url: string; token: string };

export class KnowBridgeError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export type WhoAmI = {
  user: { name: string; email: string };
  project: { id: string; name: string };
  roles: string[];
  approved_only: boolean;
  web_url: string;
};

export type CodeSource = { kind: string; title: string; permalink: string; source_name: string; occurred_at: string | null };
export type CodeClaim = {
  id: string;
  type: string;
  grade: string;
  status: string;
  statement: string;
  subject: string;
  owner_name: string;
  why: string;
  sources: CodeSource[];
  url: string | null;
};
export type CodeContext = {
  path: string;
  folder: boolean;
  found: boolean;
  owners: { name: string; commits: number; share: number; last_change: string | null }[];
  commits: number;
  last_change: string | null;
  claims: CodeClaim[];
  counts: Record<string, number>;
  withheld: number;
  approved_only: boolean;
  project_url: string;
  repo_commits: number;
  created_by: string;
  created_at: string | null;
};
export type ClaimDetail = {
  id: string;
  type: string;
  grade: string;
  grade_reason: string;
  status: string;
  statement: string;
  rationale: string;
  subject: string;
  owner_name: string;
  quotes: { quote: string; title: string; kind: string; author: string; permalink: string; source_name: string; occurred_at: string | null }[];
  url: string | null;
};
export type Chunk = {
  ref: string;
  kind: "claim" | "evidence";
  id: string;
  title: string;
  text: string;
  type_label?: string;
  grade?: string;
  approved?: boolean;
  source?: string;
  author?: string;
  date?: string | null;
  quotes?: { quote: string; source: string; author: string; date: string | null }[];
};
export type Answer = {
  answer: string;
  answerable: boolean;
  error: string | null;
  blocked: string;
  citations: Chunk[];
  sources: Chunk[];
  withheld: number;
};
export type Retrieved = { chunks: Chunk[]; context: string; withheld: number };

const TIMEOUT_MS = 90_000; // asking can take a while: retrieval, then the model

export function baseUrl(url: string): string {
  const u = url.trim().replace(/\/+$/, "");
  return u.endsWith("/api/v1") ? u : `${u}/api/v1`;
}

export class KnowBridge {
  private who?: WhoAmI;

  constructor(private settings: Settings) {}

  private async call<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
    if (!this.settings.url || !this.settings.token) {
      throw new KnowBridgeError(0, "KnowBridge isn't set up: add the site address and an access token.");
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    let res: Response;
    try {
      res = await fetch(`${baseUrl(this.settings.url)}${path}`, {
        method: init.method ?? "GET",
        headers: {
          Authorization: `Bearer ${this.settings.token}`,
          Accept: "application/json",
          ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
        signal: ctrl.signal,
      });
    } catch (e) {
      const why = (e as Error).name === "AbortError" ? "it took too long to answer" : (e as Error).message;
      throw new KnowBridgeError(0, `Couldn't reach KnowBridge at ${this.settings.url} (${why}).`);
    } finally {
      clearTimeout(timer);
    }
    const text = await res.text();
    let body: unknown = text;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      /* not JSON */
    }
    if (!res.ok) {
      const detail = (body as { detail?: unknown })?.detail;
      throw new KnowBridgeError(
        res.status,
        typeof detail === "string" ? detail : `KnowBridge answered ${res.status}.`,
      );
    }
    return body as T;
  }

  /** Whose token this is and which project it opens (cached). */
  async whoami(fresh = false): Promise<WhoAmI> {
    if (!this.who || fresh) this.who = await this.call<WhoAmI>("/token");
    return this.who;
  }

  async projectId(): Promise<string> {
    return (await this.whoami()).project.id;
  }

  resolve(repo: string) {
    return this.call<{ repo: string; projects: { id: string; name: string }[] }>(
      `/projects/resolve?repo=${encodeURIComponent(repo)}`,
    );
  }

  async codeContext(path: string): Promise<CodeContext> {
    return this.call<CodeContext>(
      `/projects/${await this.projectId()}/code-context?path=${encodeURIComponent(path)}`,
    );
  }

  async claim(id: string): Promise<ClaimDetail> {
    return this.call<ClaimDetail>(`/projects/${await this.projectId()}/claims/${encodeURIComponent(id)}`);
  }

  /** `path`: the file open in the editor; "this file" in the question then means it. */
  async ask(question: string, path?: string): Promise<Answer> {
    return this.call<Answer>(`/projects/${await this.projectId()}/rag/ask`, {
      method: "POST",
      body: { question, ...(path ? { path } : {}) },
    });
  }

  async search(query: string, k = 10): Promise<Retrieved> {
    return this.call<Retrieved>(`/projects/${await this.projectId()}/rag/retrieve`, {
      method: "POST",
      body: { query, k, budget_tokens: 4000 },
    });
  }
}

// --- plain-text renderings (what an AI assistant reads) -------------------------------------------

const GRADE: Record<string, string> = {
  verified: "Verified",
  supported: "Supported",
  attested: "Attested",
  inferred: "Inferred",
  conflicting: "Conflicting",
  missing: "Missing",
};
const TYPE: Record<string, string> = {
  owner: "Owner",
  decision: "Decision",
  risk: "Risk",
  blocker: "Blocker",
  dependency: "Dependency",
  recurring_problem: "Recurring problem",
  open_question: "Open question",
  next_action: "Next action",
  contact: "Contact",
};
export const gradeLabel = (g: string) => GRADE[g] ?? g;
export const typeLabel = (t: string) => TYPE[t] ?? t;
const day = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : "");

export function contextText(ctx: CodeContext): string {
  const lines: string[] = [];
  lines.push(`KnowBridge on ${ctx.path || "(repository root)"}${ctx.folder ? " (folder)" : ""}`);
  if (!ctx.found) {
    lines.push("Nothing is recorded about this path yet.");
    if (ctx.withheld) lines.push(`${ctx.withheld} claim(s) about it are withheld: you aren't cleared to see them.`);
    return lines.join("\n");
  }
  if (ctx.owners.length) {
    lines.push(
      `Who changed it (${ctx.commits} commit${ctx.commits === 1 ? "" : "s"}, last ${day(ctx.last_change)}): ` +
        ctx.owners.map((o) => `${o.name} ${Math.round(o.share * 100)}%`).join(", "),
    );
    if (ctx.created_by) lines.push(`Created by: ${ctx.created_by} (${day(ctx.created_at)}, the earliest commit KnowBridge has)`);
  } else {
    lines.push(
      ctx.repo_commits
        ? "No commits in the connected GitHub repository touched this path."
        : "No GitHub repository with commits is connected to this project, so who wrote this file isn't known.",
    );
  }
  for (const c of ctx.claims) {
    lines.push("");
    lines.push(`[${typeLabel(c.type)} · ${gradeLabel(c.grade)}${c.status === "approved" || c.status === "edited" ? " · approved" : ""}] ${c.statement}`);
    lines.push(`  claim id: ${c.id} · ${c.why}${c.owner_name ? ` · owner: ${c.owner_name}` : ""}`);
    for (const s of c.sources.slice(0, 3)) {
      lines.push(`  source: ${s.source_name}: ${s.title}${s.occurred_at ? ` (${day(s.occurred_at)})` : ""}${s.permalink ? ` ${s.permalink}` : ""}`);
    }
  }
  if (ctx.withheld) lines.push(`\n${ctx.withheld} more claim(s) about this path are withheld from you.`);
  if (ctx.approved_only) lines.push("Only claims an approver has approved are shown.");
  return lines.join("\n");
}

export function claimText(c: ClaimDetail): string {
  const lines = [
    `[${typeLabel(c.type)} · ${gradeLabel(c.grade)}] ${c.statement}`,
    `Why this grade: ${c.grade_reason || "—"}`,
  ];
  if (c.rationale) lines.push(`Reason: ${c.rationale}`);
  if (c.owner_name) lines.push(`Owner: ${c.owner_name}`);
  lines.push("Evidence:");
  for (const q of c.quotes) {
    lines.push(`  "${q.quote}" (${q.source_name}, ${q.author}${q.occurred_at ? `, ${day(q.occurred_at)}` : ""})${q.permalink ? ` ${q.permalink}` : ""}`);
  }
  if (c.url) lines.push(`Open in KnowBridge: ${c.url}`);
  return lines.join("\n");
}

function chunkLine(ch: Chunk): string {
  if (ch.kind === "claim") {
    const quotes = (ch.quotes ?? []).slice(0, 2).map((q) => `"${q.quote}" (${q.source}${q.date ? `, ${q.date}` : ""})`);
    return `[${ch.ref}] ${ch.type_label ?? "Claim"} · ${gradeLabel(ch.grade ?? "")}${ch.approved ? " · approved" : ""}: ${ch.title}\n  claim id: ${ch.id}${quotes.length ? `\n  evidence: ${quotes.join("; ")}` : ""}`;
  }
  return `[${ch.ref}] ${ch.source ?? "Source"}${ch.author ? `, ${ch.author}` : ""}${ch.date ? `, ${ch.date}` : ""}: ${ch.title}\n  ${ch.text.replace(/\s+/g, " ").slice(0, 400)}`;
}

export function searchText(r: Retrieved, query: string): string {
  if (!r.chunks.length) return `Nothing in the project matches "${query}".`;
  const lines = [`What the project records about "${query}" (claims are graded; evidence is quoted as written):`];
  for (const ch of r.chunks) lines.push("", chunkLine(ch));
  if (r.withheld) lines.push("", `${r.withheld} more item(s) matched but are too sensitive to send to an AI assistant.`);
  return lines.join("\n");
}

export function answerText(a: Answer): string {
  if (a.blocked) return `KnowBridge didn't answer: ${a.answer || "the question looked like an attempt to change its rules."}`;
  const lines = [a.answer || a.error || "No answer."];
  const cited = a.citations.length ? a.citations : a.sources.slice(0, 5);
  if (cited.length) {
    lines.push("", "Sources:");
    for (const ch of cited) lines.push(chunkLine(ch));
  }
  if (!a.answerable) lines.push("", "The project's record doesn't fully answer this; ask the people named above.");
  return lines.join("\n");
}
