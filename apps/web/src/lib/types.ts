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
};

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  approver: "Approver",
  leaver: "Leaving",
  successor: "Taking over",
  viewer: "Viewer",
};
