// Mirrors services/api/app/schemas.py

export type Role = "admin" | "approver" | "leaver" | "successor" | "viewer";

export type User = {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
};

export type ProjectSummary = {
  id: string;
  name: string;
  slug: string;
  description: string;
  retention_days: number;
  created_at: string;
  my_roles: Role[];
  member_count: number;
  source_count: number;
  evidence_count: number;
  claim_count: number;
  handover_count: number;
  interviewed_count: number;
  published_count: number;
};

export type Member = {
  user: User;
  roles: Role[];
  role_template: string | null;
  clearances: string[];
};

export type Sensitivity = "team" | "restricted" | "confidential";
export type SourceKind = "github" | "document" | "taskboard" | "chat" | "meeting" | "interview";
export type SourceStatus = "pending" | "syncing" | "ready" | "failed";

export type Source = {
  id: string;
  kind: SourceKind;
  name: string;
  status: SourceStatus;
  status_detail: string;
  default_sensitivity: Sensitivity;
  readers: string[];
  scope_from: string | null;
  scope_to: string | null;
  item_count: number;
  last_synced_at: string | null;
  created_at: string;
  config: {
    repo?: string;
    files?: string[];
    provider?: "jira";
    site?: string;
    email?: string;
    jql?: string;
    account?: string;
    visibility?: "public" | "private";
    uses_own_token?: boolean;
    warning?: string;
  };
};

export type EvidenceHit = {
  id: string;
  source_id: string;
  kind: string;
  title: string;
  permalink: string;
  locator: string;
  author: string;
  occurred_at: string | null;
  sensitivity: Sensitivity;
  language: string;
  removed: boolean;
  snippet: string;
  score: number | null;
  strength?: "strong" | "possible" | null;
  related?: RelatedHit[];
};

export type RelatedHit = {
  id: string;
  kind: string;
  title: string;
  locator: string;
  author: string;
  occurred_at: string | null;
  snippet: string;
};

export type EvidencePage = { items: EvidenceHit[]; total: number | null; hidden: number };

export type EvidenceDetail = Omit<EvidenceHit, "snippet" | "score"> & {
  text: string;
  source_name: string;
  source_kind: SourceKind;
  redactions: { category: string; rule_id: string; start: number; end: number }[];
  label_reasons: string[];
  meta: Record<string, unknown>;
  context: EvidenceHit[];
  linked: EvidenceHit[];
};

export type EvidenceStats = {
  by_kind: Record<string, number>;
  by_sensitivity: Record<string, number>;
  by_language: Record<string, number>;
  embedded: number;
  search_model: string | null;
  search_external: boolean;
  kept_private: number;
  visible: number;
  hidden: number;
  masked_secrets: number;
  masked_pii: number;
};

export const SOURCE_KIND_LABEL: Record<SourceKind, string> = {
  github: "GitHub repository",
  document: "Documents",
  taskboard: "Task board",
  chat: "Chat export",
  meeting: "Meeting transcripts",
  interview: "Gap Interview",
};

export const EVIDENCE_KIND_LABEL: Record<string, string> = {
  commit: "Commit",
  pull_request: "Pull request",
  pr_comment: "PR comment",
  pr_review: "PR review",
  code_ownership: "Code ownership",
  issue: "Issue",
  issue_comment: "Issue comment",
  file: "Repo file",
  check: "CI run",
  doc_section: "Document",
  card: "Card",
  card_comment: "Card comment",
  message: "Message",
  meeting_segment: "Meeting",
  interview_answer: "Gap Interview answer",
};

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  approver: "Approver",
  leaver: "Leaving",
  successor: "Taking over",
  viewer: "Viewer",
};

// --- runs and the claim ledger ---------------------------------------------

export type ClaimType =
  | "decision"
  | "owner"
  | "dependency"
  | "risk"
  | "blocker"
  | "open_question"
  | "next_action"
  | "contact"
  | "recurring_problem";
export type Grade = "verified" | "supported" | "attested" | "inferred" | "conflicting" | "missing";
export type RunStatus = "queued" | "running" | "waiting" | "done" | "failed" | "cancelled";

export type RunStep = {
  agent: string;
  status: "running" | "done" | "paused" | "failed";
  summary: string;
  items_in: number;
  items_out: number;
  llm_calls: number;
  tokens: number;
  error: string;
  started_at: string;
  finished_at: string | null;
  progress: { done: number; total: number } | null;
};

export type Run = {
  id: string;
  status: RunStatus;
  status_detail: string;
  llm_calls: number;
  tokens_used: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  started_by_name: string;
  steps: RunStep[];
};

export type ClaimRef = {
  id: string;
  statement: string;
  valid_from: string | null;
  valid_to: string | null;
  grade: Grade;
};

export type ClaimCite = {
  evidence_id: string;
  quote: string;
  kind: string;
  title: string;
  locator: string;
  author: string;
  occurred_at: string | null;
  permalink: string;
  source_name: string;
};

export type Claim = {
  id: string;
  type: ClaimType;
  statement: string;
  rationale: string;
  alternatives: string[];
  subject: string;
  owner_name: string;
  due_date: string | null;
  valid_from: string | null;
  grade: Grade;
  grade_reason: string;
  impact: 1 | 2 | 3;
  status: "draft" | "edited" | "approved" | "rejected";
  sensitivity: Sensitivity;
  created_by_agent: string;
  from_system_data: boolean;
  checked: boolean;
  version: number;
  reviewed_by_name: string;
  reviewed_at: string | null;
  review_note: string;
  skeptic_note: string;
  replaces: ClaimRef[];
  replaced_by: ClaimRef | null;
  conflicts: ClaimRef[];
  evidence: ClaimCite[];
};

export type LedgerPage = {
  run: Run | null;
  llm_ready: boolean;
  items: Claim[];
  total: number;
  counts: Partial<Record<ClaimType, number>>;
  grades: Partial<Record<Grade, number>>;
  replaced: number;
  removed: number;
  hidden: number;
  review: { todo?: number; approved?: number };
  can_review: boolean;
};

/** What each grade means, in the reviewer's words. */
export const GRADE_LABEL: Record<Grade, [string, string]> = {
  verified: ["Verified", "Two separate sources agree, or it comes straight from system data."],
  supported: ["Supported", "Stated clearly in one place."],
  attested: ["Attested", "Confirmed by the person leaving, in the Gap Interview."],
  inferred: ["Inferred", "Its evidence implies it, or backs only part of it."],
  conflicting: ["Conflicting", "Sources disagree; someone has to decide which is right."],
  missing: ["Missing", "Asked, but nobody answered."],
};

/** Singular and plural, in the order the ledger lists them. */
export const CLAIM_TYPE_LABEL: Record<ClaimType, [string, string]> = {
  decision: ["Decision", "Decisions"],
  owner: ["Owner", "Owners"],
  dependency: ["Dependency", "Dependencies"],
  risk: ["Risk", "Risks"],
  blocker: ["Blocker", "Blockers"],
  recurring_problem: ["Recurring problem", "Recurring problems"],
  open_question: ["Open question", "Open questions"],
  next_action: ["Next action", "Next actions"],
  contact: ["Contact", "Contacts"],
};

/** The pipeline's steps, in the order they run. */
export const AGENT_LABEL: Record<string, string> = {
  sentinel: "Sentinel review",
  scout: "Scout",
  decision_miner: "Decision Miner",
  ownership_mapper: "Ownership & Dependency Mapper",
  risk_detector: "Risk & Blocker Detector",
  timeline: "Timeline Builder",
  skeptic: "Skeptic",
  interviewer: "Gap Interviewer",
};

export const AGENT_JOB: Record<string, string> = {
  sentinel: "Reads items for private context the rules missed. Can only make labels stricter.",
  scout: "Decides which specialist reads each thread, chat day, document and meeting.",
  decision_miner: "Finds what was decided, when, and why.",
  ownership_mapper: "Finds who owns what, what depends on what, and who to contact.",
  risk_detector: "Finds risks, blockers, repeat problems and unanswered questions.",
  timeline: "Merges claims that say the same thing, and links changes over time and disagreements.",
  skeptic: "Re-reads each claim's own evidence and grades it; removes claims nothing backs.",
  interviewer: "Turns what the evidence leaves unclear into questions for the person leaving.",
};

// --- handovers and the Gap Interview ---------------------------------------

export type HandoverStatus = "drafting" | "interviewing" | "in_review" | "published" | "acknowledged";
export type QuestionStatus = "open" | "answered" | "skipped" | "reassigned";

export type Handover = {
  id: string;
  title: string;
  status: HandoverStatus;
  leaver: User;
  successor: User;
  approver: User;
  leaver_last_day: string | null;
  created_at: string;
  questions_total: number;
  questions_answered: number;
  questions_open: number;
  my_open: number;
};

export type GapQuestion = {
  id: string;
  position: number;
  question: string;
  why_asked: string;
  kind: "choose" | "confirm" | "fill" | "";
  status: QuestionStatus;
  answer: string;
  answered_by_name: string;
  answered_at: string | null;
  assignee: User;
  claims: { id: string; statement: string; grade: Grade; evidence: ClaimCite[] }[];
  verdict: string;
  effects: string[];
};

export type HandoverDetail = Handover & {
  questions: GapQuestion[];
  claims_ready: boolean;
  can_manage: boolean;
  preparing: boolean;
  approved_claims: number;
  latest_version: number;
  published_version: number;
  composing: boolean;
  can_publish: boolean;
  open_flags: number;
};

export const HANDOVER_STATUS_LABEL: Record<HandoverStatus, string> = {
  drafting: "Getting ready",
  interviewing: "Gap Interview",
  in_review: "In review",
  published: "Published",
  acknowledged: "Acknowledged",
};

/** The badge colour for each handover status. */
export const HANDOVER_STATUS_TONE: Record<HandoverStatus, "neutral" | "info" | "warning" | "success" | "accent"> = {
  drafting: "neutral",
  interviewing: "info",
  in_review: "warning",
  published: "accent",
  acknowledged: "success",
};

// --- the Handover Pack -------------------------------------------------------

export type PackCite = {
  evidence_id: string;
  quote: string;
  kind: string;
  source: string;
  author: string;
  date: string | null;
  permalink: string;
};

export type PackBlock = {
  claim_id: string;
  type: ClaimType;
  statement: string;
  rationale: string;
  grade: Grade;
  grade_reason: string;
  owner: string;
  due: string | null;
  since: string | null;
  history: { statement: string; until: string | null }[];
  cites: PackCite[];
};

export type PackSection = {
  id: string;
  key: string;
  title: string;
  intro: string;
  blocks: PackBlock[];
  withheld: { count?: number; labels?: string[]; ask?: string };
  acknowledged_at: string | null;
};

export type PlanItem = {
  id: string;
  week: number;
  title: string;
  detail: string;
  owner_name: string;
  due_date: string | null;
  done: boolean;
  claim_ids: string[];
};

export type Pack = {
  version: number;
  published_version: number;
  is_published: boolean;
  title: string;
  leaver: User;
  successor: User;
  approver: User;
  leaver_last_day: string | null;
  sections: PackSection[];
  plan: PlanItem[];
  flags: { id: string; claim_id: string; statement: string; note: string; raised_by_name: string; created_at: string; resolved: boolean }[];
  can_acknowledge: boolean;
  can_publish: boolean;
};

/** "Chat with the project": what its vector index holds and which model answers. */
export type RagStatus = {
  claims_total: number;
  claims_indexed: number;
  evidence_total: number;
  evidence_indexed: number;
  embedding_model: string | null;
  model: string;
  ready: boolean;
  external: boolean;
  context_tokens: number;
  approved_only: boolean;
  can_index: boolean;
};

/** One retrieved piece the answer may cite: a claim [C1] or a source item [E1]. */
export type RagChunk = {
  ref: string;
  kind: "claim" | "evidence";
  id: string;
  title: string;
  text: string;
  score: number;
  // claims
  type_label?: string;
  grade?: Grade;
  approved?: boolean;
  quotes?: { quote: string; source: string; author: string; evidence_id: string; date: string | null }[];
  // source items
  item_kind?: string;
  source?: string;
  author?: string;
  date?: string | null;
  /** sentences addressed to an AI that the guardrails cut from this item */
  cleaned?: number;
};

/** What the guardrails did for one answer (services/api/app/guard.py). */
export type GuardNotes = {
  question_blocked?: string[];
  answer_blocked?: string;
  cleaned_sources?: number;
  cleaned_kinds?: string[];
  forged_turns?: number;
  dropped_turns?: number;
  removed_links?: number;
  redacted?: number;
  unsupported_figures?: string[];
  uncited_sentences?: number;
  ungrounded?: boolean;
  out_of_scope?: boolean;
  invented_ids?: string[];
};

export type AskResult = {
  answer: string;
  answerable: boolean;
  error: string;
  model: string;
  cached: boolean;
  /** "question" | "answer" when the guardrails stopped it */
  blocked: string;
  guard: GuardNotes;
  /** this server's signature on the answer; sent back with the history */
  token: string | null;
  citations: RagChunk[];
  sources: RagChunk[];
  invented: string[];
  withheld: number;
  dropped: number;
};

export type ChatTurn = { role: "user" | "assistant"; content: string; token?: string | null };
