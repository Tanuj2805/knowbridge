import {
  ArrowRightLeft,
  Eye,
  FileText,
  FolderKanban,
  History,
  ListChecks,
  MessageSquareText,
  Plug,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

export type AuditEvent = {
  id: string;
  at: string;
  actor: string | null;
  action: string;
  object_type: string;
  object_id: string;
  meta: Record<string, unknown>;
};

/** What happened, in words. Anything not listed shows its raw action name. */
const SAYS: Record<string, (m: Record<string, unknown>) => string> = {
  "project.create": () => "created the project",
  "project.demo_load": () => "loaded the Project Nimbus demo",
  "member.upsert": () => "added or changed a member",
  "member.remove": () => "removed a member",
  "source.connect": () => "connected a source",
  "source.update": () => "changed a source's settings",
  "source.sync": () => "synced a source",
  "source.add_files": () => "added files to a source",
  "source.remove": () => "removed a source",
  "search.reindex": () => "rebuilt smart search",
  "evidence.view": () => "opened an evidence item",
  "evidence.relabel": (m) => `relabelled an item${m.new ? ` to ${m.new}` : ""}`,
  "evidence.relabel.ai": (m) => `Sentinel raised an item to ${m.new ?? "a stricter label"}${m.reason ? `: ${m.reason}` : ""}`,
  "run.start": () => "started building claims",
  "claim.approve": () => "approved a claim",
  "claim.edit": (m) => `edited and approved a claim${m.version ? ` (now version ${m.version})` : ""}`,
  "claim.reject": () => "rejected a claim",
  "claim.reopen": () => "reopened a claim for review",
  "claim.flag": () => "flagged a claim in the pack as possibly wrong",
  "handover.create": () => "started a handover",
  "interview.start": () => "prepared the Gap Interview",
  "interview.answer": () => "answered a Gap Interview question",
  "interview.skip": () => "said “I don't know” to a question",
  "interview.reassign": () => "passed a question to someone else",
  "interview.applied": (m) => `the Gap Interviewer applied an answer (${m.verdict ?? "read"})`,
  "pack.compose": () => "asked the Composer for a new version of the pack",
  "pack.composed": (m) => `the Composer wrote version ${m.version ?? ""} of the pack`,
  "pack.publish": (m) => `published version ${m.version ?? ""} of the pack`,
  "pack.view": (m) => `read the pack${m.version ? ` (version ${m.version})` : ""}`,
  "pack.acknowledge": (m) => `confirmed reading “${m.section ?? "a section"}”`,
  "pack.export": (m) => `exported the pack${m.format ? ` as ${m.format === "ics" ? "a calendar" : m.format}` : ""}`,
  "rag.ask": (m) => `asked the project chat${m.question ? `: “${String(m.question).slice(0, 80)}”` : ""}`,
  "rag.export": (m) =>
    m.format === "retrieve" ? "retrieved project context for another model" : "downloaded the project context file",
  "rag.guard": (m) => {
    const did: string[] = [];
    if (m.question_blocked) did.push("refused a question that tried to change the assistant's rules");
    if (m.answer_blocked) did.push("withheld an answer that leaked its instructions");
    if (m.cleaned_sources) did.push(`cut text aimed at an AI from ${m.cleaned_sources} source(s)`);
    if (m.forged_turns) did.push("dropped a chat turn the assistant never wrote");
    if (m.removed_links) did.push("removed unknown links from an answer");
    if (m.redacted) did.push("masked a secret in an answer");
    return `Guardrails ${did.join("; ") || "stepped in"}`;
  },
};

export function describe(e: AuditEvent): string {
  return (SAYS[e.action] ?? (() => e.action))(e.meta ?? {});
}

/** An icon for each kind of action, by the first part of its name. */
const ICON: Record<string, LucideIcon> = {
  project: FolderKanban,
  member: Users,
  source: Plug,
  search: Search,
  evidence: FileText,
  run: Sparkles,
  claim: ListChecks,
  handover: ArrowRightLeft,
  interview: MessageSquareText,
  pack: Send,
  view: Eye,
  rag: MessageSquareText,
};

export function iconFor(e: AuditEvent): LucideIcon {
  if (e.action === "rag.guard") return ShieldCheck;
  return ICON[e.action.split(".")[0]] ?? History;
}
