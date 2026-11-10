"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowLeft,
  CalendarClock,
  ChevronDown,
  FileText,
  GitBranch,
  ListChecks,
  MessageSquareText,
  Plus,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import { startTransition, useActionState, useState, type FormEvent } from "react";
import {
  Button,
  ErrorNote,
  FieldError,
  Input,
  Label,
  RequiredMark,
  RequiredNote,
  Select,
  Spinner,
  buttonClass,
  cx,
} from "@/components/ui";
import type { Member, SourceKind } from "@/lib/types";
import { connectSource, type FormState } from "./actions";

type Kind = Exclude<SourceKind, "interview">;

const KINDS: { kind: Kind; label: string; icon: LucideIcon; blurb: string; accept: string; help: string; example: string }[] = [
  {
    kind: "github",
    label: "GitHub",
    icon: GitBranch,
    blurb: "Commits, pull requests, issues and CI runs",
    accept: ".json,.yaml,.yml",
    help: "Commits, pull requests and their reviews, issues, README and docs/, and CI runs. Read-only.",
    example: "e.g. fest-app repository",
  },
  {
    kind: "document",
    label: "Documents",
    icon: FileText,
    blurb: "Meeting notes, specs and minutes",
    accept: ".md,.markdown,.txt,.pdf,.docx",
    help: "Markdown, text, PDF or Word files.",
    example: "e.g. Specs and notes",
  },
  {
    kind: "taskboard",
    label: "Task board",
    icon: ListChecks,
    blurb: "Jira, Trello, Asana, Linear or GitHub Projects",
    accept: ".json,.csv",
    help: "Connect Jira Cloud directly, or upload a Trello export (JSON) or a CSV from Jira, GitHub Projects, Asana or Linear.",
    example: "e.g. Trello board",
  },
  {
    kind: "chat",
    label: "Chat",
    icon: MessageSquareText,
    blurb: "WhatsApp, Slack or Discord exports",
    accept: ".txt,.json,.zip",
    help: "WhatsApp “Export chat” (.txt), Slack export (.zip or channel .json), or Discord (DiscordChatExporter .json).",
    example: "e.g. WhatsApp tech group",
  },
  {
    kind: "meeting",
    label: "Meeting",
    icon: CalendarClock,
    blurb: "Transcripts from Meet, Zoom, Teams or Otter",
    accept: ".vtt,.srt,.txt,.docx,.md",
    help: "Google Meet (.txt or .docx), Zoom or Teams (.vtt), Otter or Fireflies exports, or notes written as “Name: what they said”. Each file is one meeting.",
    example: "e.g. Weekly syncs",
  },
];

/** A titled group of fields inside the form. */
function Group({
  title,
  hint,
  required,
  children,
}: {
  title: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="border-t border-rule pt-5">
      <legend className="sr-only">
        {title}
        {required && " (required)"}
      </legend>
      <p aria-hidden="true" className="text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-faint">
        {title}
        {required && <span className="ml-0.5 text-danger">*</span>}
      </p>
      {hint && <p className="mt-1 text-[13px] text-ink-muted">{hint}</p>}
      <div className="mt-3 grid gap-4">{children}</div>
    </fieldset>
  );
}

/** One of two or more choices, shown as a selectable panel (a radio button underneath). */
function Choice({
  name,
  value,
  checked,
  onChange,
  title,
  hint,
}: {
  name: string;
  value: string;
  checked: boolean;
  onChange: () => void;
  title: string;
  hint: string;
}) {
  return (
    <label
      className={cx(
        "flex cursor-pointer items-start gap-3 rounded-lg border px-3.5 py-3 transition-colors",
        checked ? "border-accent bg-accent-soft/50" : "border-rule hover:border-rule-strong",
      )}
    >
      <input type="radio" name={name} value={value} checked={checked} onChange={onChange} className="mt-0.5 accent-[var(--accent)]" />
      <span>
        <span className="block text-[14px] font-medium text-ink">{title}</span>
        <span className="block text-[13px] text-ink-muted">{hint}</span>
      </span>
    </label>
  );
}

function SourceForm({
  projectId,
  members,
  kind,
  onBack,
  onDone,
}: {
  projectId: string;
  members: Member[];
  kind: Kind;
  onBack: () => void;
  onDone: () => void;
}) {
  const meta = KINDS.find((k) => k.kind === kind)!;
  const [audience, setAudience] = useState<"all" | "some">("all");
  const [boardMode, setBoardMode] = useState<"upload" | "jira">("upload");
  const [files, setFiles] = useState<string[]>([]);
  const [errors, setErrors] = useState<{ files?: string; repo?: string; readers?: string }>({});
  const jira = kind === "taskboard" && boardMode === "jira";
  const [state, send, sending] = useActionState(async (prev: FormState, form: FormData) => {
    const result = await connectSource(projectId, prev, form);
    if (result?.ok) onDone();
    return result;
  }, undefined);

  // Sent by hand rather than through the form's action, so nothing typed is cleared when a check
  // fails or the server says no (a form action resets the form once it runs).
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const chosen = form.getAll("files").filter((f) => f instanceof File && f.size > 0).length;
    const found: typeof errors = {};
    if (kind === "github" && !String(form.get("repo") ?? "").trim() && chosen === 0) {
      found.repo = "Enter a repository, or choose a snapshot file below.";
    } else if (kind !== "github" && !jira && chosen === 0) {
      found.files = "Choose at least one file.";
    }
    if (form.get("audience") === "some" && form.getAll("readers").length === 0) {
      found.readers = "Pick at least one person.";
    }
    setErrors(found);
    if (Object.keys(found).length === 0) startTransition(() => send(form));
  };

  return (
    <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
      <input type="hidden" name="kind" value={kind} />
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        <button
          type="button"
          onClick={onBack}
          className="group mb-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-muted hover:text-ink"
        >
          <ArrowLeft className="size-3.5 transition-transform group-hover:-translate-x-0.5" aria-hidden="true" />
          Choose another kind
        </button>
        <div className="mb-5 flex items-start gap-3">
          <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <meta.icon className="size-5" aria-hidden="true" />
          </span>
          <div>
            <p className="text-[16px] font-semibold text-ink">{meta.label}</p>
            <p className="text-[13px] leading-relaxed text-ink-muted">{meta.help}</p>
          </div>
        </div>

        <RequiredNote className="mb-4" />
        <div className="grid gap-6">
          <Group title="About it">
            <div>
              <Label htmlFor="src-name" required>
                Name
              </Label>
              <Input id="src-name" name="name" required autoFocus placeholder={meta.example} />
            </div>

            {kind === "taskboard" && (
              <div role="radiogroup" aria-label="How to add the board" className="grid gap-2 sm:grid-cols-2">
                <Choice
                  name="board_mode"
                  value="upload"
                  checked={boardMode === "upload"}
                  onChange={() => setBoardMode("upload")}
                  title="Upload an export"
                  hint="A Trello JSON or a CSV file"
                />
                <Choice
                  name="board_mode"
                  value="jira"
                  checked={boardMode === "jira"}
                  onChange={() => setBoardMode("jira")}
                  title="Connect Jira Cloud"
                  hint="Live, read-only"
                />
              </div>
            )}

            {kind === "github" && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="repo" hint="owner/name, or upload a snapshot below">
                    Repository
                    <RequiredMark />
                  </Label>
                  <Input
                    id="repo"
                    name="repo"
                    placeholder="your-org/fest-app"
                    autoComplete="off"
                    aria-invalid={!!errors.repo}
                    aria-describedby={errors.repo ? "repo-error" : undefined}
                    className={errors.repo ? "border-danger" : undefined}
                    onChange={() => errors.repo && setErrors((e) => ({ ...e, repo: undefined }))}
                  />
                  <FieldError id="repo-error">{errors.repo}</FieldError>
                </div>
                <div>
                  <Label htmlFor="github_token" hint="Optional. Only for private repositories">
                    Read-only token
                  </Label>
                  <Input id="github_token" name="github_token" type="password" autoComplete="new-password" />
                </div>
                <details className="group/help text-[13px] text-ink-muted sm:col-span-2">
                  <summary className="inline-flex cursor-pointer items-center gap-1 font-medium text-accent">
                    How to make a read-only token
                    <ChevronDown className="size-3.5 transition-transform group-open/help:rotate-180" aria-hidden="true" />
                  </summary>
                  <ol className="mt-2 ml-4 grid list-decimal gap-1">
                    <li>
                      GitHub → Settings → Developer settings →{" "}
                      <a
                        href="https://github.com/settings/personal-access-tokens/new"
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-accent underline-offset-4 hover:underline"
                      >
                        Fine-grained tokens
                      </a>
                      .
                    </li>
                    <li>Repository access: only this repository.</li>
                    <li>Permissions, all Read-only: Contents, Issues, Pull requests, Metadata, and Actions.</li>
                  </ol>
                  <p className="mt-2">It&apos;s checked before saving, encrypted, and never shown again.</p>
                </details>
              </div>
            )}

            {jira && (
              <div className="grid gap-4">
                <div>
                  <Label htmlFor="jira_site" required>
                    Jira site
                  </Label>
                  <Input id="jira_site" name="jira_site" required placeholder="https://yourteam.atlassian.net" autoComplete="off" />
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <Label htmlFor="jira_email" required>
                      Atlassian email
                    </Label>
                    <Input id="jira_email" name="jira_email" type="email" required autoComplete="off" />
                  </div>
                  <div>
                    <Label htmlFor="jira_token" required>
                      API token
                    </Label>
                    <Input id="jira_token" name="jira_token" type="password" required autoComplete="new-password" />
                  </div>
                </div>
                <div>
                  <Label htmlFor="jql" required hint="A project key like ROV, or any JQL filter">
                    Which issues
                  </Label>
                  <Input id="jql" name="jql" required placeholder="ROV" autoComplete="off" />
                </div>
                <p className="text-[13px] text-ink-muted">
                  Make a token at{" "}
                  <a
                    href="https://id.atlassian.com/manage-profile/security/api-tokens"
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-accent underline-offset-4 hover:underline"
                  >
                    id.atlassian.com → Security → API tokens
                  </a>
                  . It&apos;s encrypted before it&apos;s saved; KnowBridge only reads.
                </p>
              </div>
            )}

            {kind === "meeting" && (
              <div>
                <Label htmlFor="meeting_date" hint="Optional. Used when a transcript doesn't say when the meeting was">
                  Meeting date
                </Label>
                <Input id="meeting_date" name="meeting_date" type="date" className="max-w-48" />
              </div>
            )}
          </Group>

          {!jira && (
            <Group
              title="Files"
              required={kind !== "github"}
              hint={kind === "github" ? "A repository snapshot, if you'd rather not link the repository." : undefined}
            >
              <label
                htmlFor="files"
                className={cx(
                  "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed bg-paper px-4 py-7 text-center transition-colors hover:border-accent hover:bg-accent-soft/30",
                  errors.files ? "border-danger" : "border-rule-strong",
                )}
              >
                <Upload className="size-5 text-ink-faint" aria-hidden="true" />
                <span className="text-[14px] font-medium text-ink">
                  {files.length ? `${files.length} file${files.length > 1 ? "s" : ""} chosen` : "Choose files"}
                </span>
                <span className="text-[12px] text-ink-faint">
                  {files.length
                    ? files.slice(0, 3).join(", ") + (files.length > 3 ? "…" : "")
                    : meta.accept.replaceAll(",", " ")}
                </span>
                <input
                  id="files"
                  name="files"
                  type="file"
                  multiple
                  accept={meta.accept}
                  className="sr-only"
                  aria-describedby={errors.files ? "files-error" : undefined}
                  onChange={(e) => {
                    setFiles([...(e.currentTarget.files ?? [])].map((f) => f.name));
                    setErrors((er) => ({ ...er, files: undefined, repo: undefined }));
                  }}
                />
              </label>
              <FieldError id="files-error">{errors.files}</FieldError>
            </Group>
          )}

          <Group
            title="Who can see it"
            required
            hint="Match who could see it in the original tool. A claim is never shown to someone who can't see all of its evidence."
          >
            <div role="radiogroup" aria-label="Who can see it" className="grid gap-2 sm:grid-cols-2">
              <Choice
                name="audience"
                value="all"
                checked={audience === "all"}
                onChange={() => setAudience("all")}
                title="Everyone on the project"
                hint="The usual choice"
              />
              <Choice
                name="audience"
                value="some"
                checked={audience === "some"}
                onChange={() => setAudience("some")}
                title="Only some people"
                hint="e.g. private meetings"
              />
            </div>
            {audience === "some" && (
              <div className="grid gap-1.5 rounded-lg border border-rule p-3 sm:grid-cols-2">
                {members.map((m) => (
                  <label key={m.user.id} className="flex items-center gap-2 text-[14px] text-ink">
                    <input
                      type="checkbox"
                      name="readers"
                      value={m.user.id}
                      className="accent-[var(--accent)]"
                      onChange={() => errors.readers && setErrors((e) => ({ ...e, readers: undefined }))}
                    />
                    {m.user.name}
                  </label>
                ))}
              </div>
            )}
            <FieldError>{errors.readers}</FieldError>
          </Group>

          <details className="group/more border-t border-rule pt-5">
            <summary className="flex cursor-pointer items-center justify-between text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-faint hover:text-ink">
              More options
              <ChevronDown className="size-4 transition-transform group-open/more:rotate-180" aria-hidden="true" />
            </summary>
            <div className="mt-3 grid gap-4 sm:grid-cols-3">
              <div className="sm:col-span-3">
                <Label htmlFor="default_sensitivity" hint="Optional. Sentinel can raise it per item, never lower it">
                  Starting label
                </Label>
                <Select id="default_sensitivity" name="default_sensitivity" defaultValue="team" className="max-w-56">
                  <option value="team">Team</option>
                  <option value="restricted">Restricted</option>
                  <option value="confidential">Confidential</option>
                </Select>
              </div>
              <div>
                <Label htmlFor="scope_from" hint="Optional">
                  From
                </Label>
                <Input id="scope_from" name="scope_from" type="date" />
              </div>
              <div>
                <Label htmlFor="scope_to" hint="Optional">
                  To
                </Label>
                <Input id="scope_to" name="scope_to" type="date" />
              </div>
            </div>
          </details>

          {state?.error && <ErrorNote>{state.error}</ErrorNote>}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-rule bg-paper-raised px-6 py-4">
        <Dialog.Close className={buttonClass("quiet")}>Cancel</Dialog.Close>
        <Button type="submit" disabled={sending} aria-busy={sending}>
          {sending && <Spinner />}
          {sending ? (jira ? "Checking the connection…" : "Uploading…") : "Connect source"}
        </Button>
      </div>
    </form>
  );
}

/**
 * "Connect a source": a button that opens a window in two steps. First pick what kind of source it
 * is, then fill in only what that kind needs. The window closes once the source is connected.
 */
export function AddSource({ projectId, members }: { projectId: string; members: Member[] }) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<Kind | null>(null);

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setKind(null);
      }}
    >
      <Dialog.Trigger className={buttonClass("primary")}>
        <Plus className="size-4" aria-hidden="true" />
        Connect a source
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1b33]/40 backdrop-blur-[2px] data-[state=open]:animate-fade" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[calc(100vw-2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-rule bg-paper-raised shadow-lift focus:outline-none data-[state=open]:animate-[kb-dialog_0.22s_cubic-bezier(0.23,1,0.32,1)]">
          <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-6">
            <div>
              <Dialog.Title className="font-display text-[1.35rem] tracking-[-0.02em] text-ink">Connect a source</Dialog.Title>
              <Dialog.Description className="mt-1 text-[14px] text-ink-muted">
                {kind
                  ? "Fill in what this source needs. Everything is read-only, and secrets are masked on the way in."
                  : "What does the team want to bring in? You can add more sources later."}
              </Dialog.Description>
            </div>
            <Dialog.Close
              className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-paper-sunk hover:text-ink"
              aria-label="Close"
            >
              <X className="size-4" aria-hidden="true" />
            </Dialog.Close>
          </div>

          {kind ? (
            <SourceForm
              key={kind}
              projectId={projectId}
              members={members}
              kind={kind}
              onBack={() => setKind(null)}
              onDone={() => {
                setOpen(false);
                setKind(null);
              }}
            />
          ) : (
            <ul className="stagger grid gap-3 overflow-y-auto px-6 pb-6 sm:grid-cols-2">
              {KINDS.map((k) => (
                <li key={k.kind}>
                  <button
                    type="button"
                    onClick={() => setKind(k.kind)}
                    className="lift group flex h-full w-full items-start gap-3.5 rounded-xl border border-rule bg-paper p-4 text-left"
                  >
                    <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent transition-colors group-hover:bg-accent group-hover:text-on-accent">
                      <k.icon className="size-5" aria-hidden="true" />
                    </span>
                    <span>
                      <span className="block text-[15px] font-semibold text-ink">{k.label}</span>
                      <span className="mt-0.5 block text-[13px] leading-snug text-ink-muted">{k.blurb}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
