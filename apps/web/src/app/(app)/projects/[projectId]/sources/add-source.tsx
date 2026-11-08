"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { ErrorNote, Input, Label, Select, cx } from "@/components/ui";
import type { Member, SourceKind } from "@/lib/types";
import { connectSource } from "./actions";

const KINDS: { kind: SourceKind; label: string; accept: string; help: string }[] = [
  {
    kind: "github",
    label: "GitHub",
    accept: ".json,.yaml,.yml",
    help: "Commits, pull requests and their reviews, issues, README and docs/, and CI runs. Read-only.",
  },
  {
    kind: "document",
    label: "Documents",
    accept: ".md,.markdown,.txt,.pdf,.docx",
    help: "Meeting notes, specs, minutes. Markdown, text, PDF or Word.",
  },
  {
    kind: "taskboard",
    label: "Task board",
    accept: ".json,.csv",
    help: "Connect Jira Cloud directly, or upload a Trello export (JSON) or a CSV from Jira, GitHub Projects, Asana or Linear.",
  },
  {
    kind: "chat",
    label: "Chat",
    accept: ".txt,.json,.zip",
    help: "WhatsApp “Export chat” (.txt), Slack export (.zip or channel .json), or Discord (DiscordChatExporter .json).",
  },
  {
    kind: "meeting",
    label: "Meeting",
    accept: ".vtt,.srt,.txt,.docx,.md",
    help: "Meeting transcripts: Google Meet (download the transcript doc as .txt or .docx), Zoom or Teams (.vtt), Otter or Fireflies exports, or notes written as “Name: what they said”. Each file is one meeting.",
  },
];

export function AddSource({ projectId, members }: { projectId: string; members: Member[] }) {
  const [kind, setKind] = useState<SourceKind>("github");
  const [audience, setAudience] = useState<"all" | "some">("all");
  const [boardMode, setBoardMode] = useState<"upload" | "jira">("upload");
  const jira = kind === "taskboard" && boardMode === "jira";
  const [state, action] = useActionState(connectSource.bind(null, projectId), undefined);
  const form = useRef<HTMLFormElement>(null);
  const meta = KINDS.find((k) => k.kind === kind)!;

  useEffect(() => {
    if (state?.ok) form.current?.reset();
  }, [state]);

  return (
    <form ref={form} action={action} className="grid gap-5">
      <div role="tablist" aria-label="Kind of source" className="flex flex-wrap gap-1 border-b border-rule">
        {KINDS.map((k) => (
          <button
            key={k.kind}
            type="button"
            role="tab"
            aria-selected={kind === k.kind}
            onClick={() => setKind(k.kind)}
            className={cx(
              "px-3 py-2 text-sm -mb-px border-b-2 transition-colors",
              kind === k.kind ? "border-accent text-ink font-medium" : "border-transparent text-ink-muted hover:text-ink",
            )}
          >
            {k.label}
          </button>
        ))}
      </div>
      <input type="hidden" name="kind" value={kind} />
      <p className="text-[14px] text-ink-muted -mt-2">{meta.help}</p>

      <div>
        <Label htmlFor="src-name">Name</Label>
        <Input
          id="src-name"
          name="name"
          required
          placeholder={
            {
              github: "e.g. fest-app repository",
              document: "e.g. Specs and notes",
              taskboard: "e.g. Trello board",
              chat: "e.g. WhatsApp tech group",
              meeting: "e.g. Weekly syncs",
              interview: "",
            }[kind]
          }
        />
      </div>

      {kind === "meeting" && (
        <div>
          <Label
            htmlFor="meeting_date"
            hint="Used when a transcript doesn't say when the meeting was. Google Meet and dated file names (2026-10-14-sync.vtt) are read automatically."
          >
            Meeting date
          </Label>
          <Input id="meeting_date" name="meeting_date" type="date" className="max-w-48" />
          <p className="text-[13px] text-ink-faint mt-2">
            Tip: meetings are often private. Under &ldquo;Who can see&rdquo;, choose only the people who attended.
          </p>
        </div>
      )}

      {kind === "github" && (
        <div>
          <Label htmlFor="repo">Repository</Label>
          <Input id="repo" name="repo" placeholder="owner/name" autoComplete="off" />
          <div className="mt-4">
            <Label htmlFor="github_token" hint="Needed for private repositories. Optional for public ones.">
              Read-only token
            </Label>
            <Input id="github_token" name="github_token" type="password" autoComplete="new-password" />
          </div>
          <details className="mt-2 text-[13px] text-ink-muted">
            <summary className="cursor-pointer text-accent">How to make a read-only token</summary>
            <ol className="mt-2 ml-4 list-decimal grid gap-1">
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
              <li>
                Permissions, all <b>Read-only</b>: Contents, Issues, Pull requests, Metadata, and Actions (for CI
                runs).
              </li>
            </ol>
            <p className="mt-2">
              It&apos;s checked before saving, encrypted, and never shown again. History is read with git, so even big
              repositories use few API calls.
            </p>
          </details>
          <p className="text-[13px] text-ink-faint mt-3">…or upload a repository snapshot file below instead.</p>
        </div>
      )}

      {kind === "taskboard" && (
        <div className="flex gap-4 text-[14px]" role="radiogroup" aria-label="How to add the board">
          <label className="flex items-center gap-2">
            <input type="radio" checked={boardMode === "upload"} onChange={() => setBoardMode("upload")} className="accent-[var(--accent)]" />
            Upload an export
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" checked={boardMode === "jira"} onChange={() => setBoardMode("jira")} className="accent-[var(--accent)]" />
            Connect Jira Cloud
          </label>
        </div>
      )}

      {jira && (
        <div className="grid gap-4 rounded-lg border border-rule bg-paper-sunk/50 p-4">
          <div>
            <Label htmlFor="jira_site">Jira site</Label>
            <Input id="jira_site" name="jira_site" required placeholder="https://yourteam.atlassian.net" autoComplete="off" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="jira_email">Atlassian account email</Label>
              <Input id="jira_email" name="jira_email" type="email" required autoComplete="off" />
            </div>
            <div>
              <Label htmlFor="jira_token">API token</Label>
              <Input id="jira_token" name="jira_token" type="password" required autoComplete="new-password" />
            </div>
          </div>
          <p className="text-[13px] text-ink-muted -mt-2">
            Create one at{" "}
            <a
              href="https://id.atlassian.com/manage-profile/security/api-tokens"
              target="_blank"
              rel="noreferrer noopener"
              className="text-accent underline-offset-4 hover:underline"
            >
              id.atlassian.com → Security → API tokens
            </a>
            . It&apos;s encrypted before it&apos;s saved and never shown again. KnowBridge only reads.
          </p>
          <div>
            <Label htmlFor="jql" hint="A project key like ROV, or any JQL filter.">
              Which issues
            </Label>
            <Input id="jql" name="jql" required placeholder="ROV" autoComplete="off" />
          </div>
        </div>
      )}

      {!jira && (
        <div>
          <Label htmlFor="files" hint={kind === "github" ? "Optional" : "You can pick several files."}>
            Files
          </Label>
          <input
            id="files"
            name="files"
            type="file"
            multiple
            accept={meta.accept}
            className="block w-full text-sm text-ink-muted file:mr-3 file:rounded-md file:border file:border-rule-strong file:bg-paper-raised file:px-3 file:py-1.5 file:text-sm file:text-ink hover:file:border-ink-faint"
          />
        </div>
      )}

      <fieldset>
        <legend className="text-sm font-medium mb-1.5">Who can see what comes from this source</legend>
        <p className="text-[13px] text-ink-muted mb-2">
          Match who could see it in the original tool. KnowBridge never shows a claim to someone who couldn&apos;t
          see every piece of evidence behind it.
        </p>
        <label className="flex items-center gap-2 text-[14px]">
          <input type="radio" name="audience" value="all" checked={audience === "all"} onChange={() => setAudience("all")} className="accent-[var(--accent)]" />
          Everyone on the project
        </label>
        <label className="flex items-center gap-2 text-[14px] mt-1">
          <input type="radio" name="audience" value="some" checked={audience === "some"} onChange={() => setAudience("some")} className="accent-[var(--accent)]" />
          Only some people
        </label>
        {audience === "some" && (
          <div className="mt-2 ml-6 grid gap-1">
            {members.map((m) => (
              <label key={m.user.id} className="flex items-center gap-2 text-[14px]">
                <input type="checkbox" name="readers" value={m.user.id} className="accent-[var(--accent)]" />
                {m.user.name}
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <Label htmlFor="default_sensitivity" hint="Sentinel can raise it per item, never lower it.">
            Starting label
          </Label>
          <Select id="default_sensitivity" name="default_sensitivity" defaultValue="team">
            <option value="team">Team</option>
            <option value="restricted">Restricted</option>
            <option value="confidential">Confidential</option>
          </Select>
        </div>
        <div>
          <Label htmlFor="scope_from" hint="Optional">From</Label>
          <Input id="scope_from" name="scope_from" type="date" />
        </div>
        <div>
          <Label htmlFor="scope_to" hint="Optional">To</Label>
          <Input id="scope_to" name="scope_to" type="date" />
        </div>
      </div>

      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
      {state?.ok && (
        <p role="status" className="text-sm text-accent">
          {state.ok}
        </p>
      )}
      <div>
        <SubmitButton pendingText={jira ? "Checking the connection…" : "Uploading…"}>Connect source</SubmitButton>
      </div>
    </form>
  );
}
