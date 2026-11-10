import {
  ArrowRight,
  CalendarClock,
  FileText,
  GitBranch,
  Info,
  ListChecks,
  MessageCircleQuestion,
  MessageSquareText,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/auto-refresh";
import { EmptyState, PageHeader, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { plural, timeAgo } from "@/lib/format";
import {
  SOURCE_KIND_LABEL,
  type EvidenceStats,
  type Member,
  type ProjectSummary,
  type Source,
  type SourceKind,
} from "@/lib/types";
import { AddSource } from "./add-source";
import { SourceControls } from "./source-controls";

export const metadata: Metadata = { title: "Sources" };

const STATUS: Record<Source["status"], { label: string; tone: "neutral" | "info" | "success" | "danger" }> = {
  pending: { label: "Waiting", tone: "neutral" },
  syncing: { label: "Reading", tone: "info" },
  ready: { label: "Ready", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};

const KIND_ICON: Record<SourceKind, LucideIcon> = {
  github: GitBranch,
  document: FileText,
  taskboard: ListChecks,
  chat: MessageSquareText,
  meeting: CalendarClock,
  interview: MessageCircleQuestion,
};

const LABEL = { team: "Team", restricted: "Restricted", confidential: "Confidential" } as const;

/** One labelled fact about a source: a small label over its value. */
function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] text-ink-faint">{label}</dt>
      <dd className="mt-1 truncate text-[14px] font-medium text-ink">{children}</dd>
    </div>
  );
}

export default async function SourcesPage({ params }: PageProps<"/projects/[projectId]/sources">) {
  const { projectId } = await params;
  const [project, sources, members, stats] = await Promise.all([
    api<ProjectSummary>(`/projects/${projectId}`),
    api<Source[]>(`/projects/${projectId}/sources`),
    api<Member[]>(`/projects/${projectId}/members`),
    api<EvidenceStats>(`/projects/${projectId}/evidence/stats`),
  ]);
  const admin = project.my_roles.includes("admin");
  const names = new Map(members.map((m) => [m.user.id, m.user.name.split(" ")[0]]));
  const busy = sources.some((s) => s.status === "pending" || s.status === "syncing");
  const items = sources.reduce((n, s) => n + s.item_count, 0);
  const ready = sources.filter((s) => s.status === "ready").length;

  return (
    <div>
      <AutoRefresh active={busy} />
      <PageHeader title="Sources" actions={admin ? <AddSource projectId={projectId} members={members} /> : undefined}>
        Where KnowBridge reads the team&apos;s work from. Everything is read-only, and secrets and personal details are
        masked before anything is stored.
      </PageHeader>

      {sources.length === 0 ? (
        <EmptyState title="No sources yet" action={admin ? <AddSource projectId={projectId} members={members} /> : undefined}>
          Start with the repository and the meeting notes. Chats are where most of the &ldquo;why&rdquo; lives, so add
          them if you can.
          {!admin && <span className="mt-2 block">Only the project admin can connect sources.</span>}
        </EmptyState>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[14px] text-ink-muted">
              <span className="font-semibold text-ink">{plural(sources.length, "source")}</span> ·{" "}
              {plural(items, "item")} read · {ready} of {sources.length} ready
            </p>
            {!admin && <p className="text-[13px] text-ink-faint">Only the project admin can connect or remove sources.</p>}
          </div>

          {stats.search_external && (
            <p className="mt-3 flex max-w-3xl gap-2 text-[13px] leading-relaxed text-ink-faint">
              <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              For smart search, the masked text of Team and Restricted items is sent to Google (Gemini). Confidential
              items are never sent.
            </p>
          )}

          <ul className="stagger mt-6 grid gap-4">
            {sources.map((s) => {
              const st = STATUS[s.status];
              const Icon = KIND_ICON[s.kind] ?? FileText;
              const working = s.status === "syncing" || s.status === "pending";
              const provider = s.config.provider === "jira" ? "jira" : s.config.repo ? "github" : undefined;
              const who =
                s.readers.length === 0 ? "Everyone" : s.readers.map((r) => names.get(r) ?? "someone").join(", ");
              const where = s.config.repo
                ? `github.com/${s.config.repo}`
                : s.config.provider === "jira"
                  ? `${s.config.site?.replace("https://", "")} · ${s.config.jql}`
                  : null;
              return (
                <li
                  key={s.id}
                  className="rounded-xl border border-rule bg-paper-raised shadow-card transition-[border-color,box-shadow] duration-200 hover:border-rule-strong hover:shadow-lift"
                >
                  {/* name, kind and status, with the actions on the right */}
                  <div className="flex flex-wrap items-start gap-4 p-5">
                    <span className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                      <Icon className="size-5" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="text-[17px] font-semibold text-ink">{s.name}</span>
                        <Tag tone={st.tone}>
                          {st.label}
                          {working && "…"}
                        </Tag>
                      </div>
                      <p className="mt-0.5 text-[13px] text-ink-faint">
                        {provider === "jira" ? "Jira Cloud · live" : provider === "github" ? "GitHub · live" : SOURCE_KIND_LABEL[s.kind]}
                        {where && <span className="break-all"> · {where}</span>}
                      </p>
                    </div>
                    {admin && (
                      <SourceControls
                        projectId={projectId}
                        sourceId={s.id}
                        name={s.name}
                        busy={working}
                        provider={provider}
                        jql={s.config.jql}
                      />
                    )}
                  </div>

                  {/* the facts, each with its label */}
                  <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-rule px-5 py-4 sm:grid-cols-4">
                    <Fact label="Items">{s.item_count.toLocaleString("en-IN")}</Fact>
                    <Fact label="Last synced">{timeAgo(s.last_synced_at)}</Fact>
                    <Fact label="Who can see it">{who}</Fact>
                    <Fact label="Label">{LABEL[s.default_sensitivity]}</Fact>
                  </dl>

                  {/* what happened on the last read, and a way into its evidence */}
                  {(s.status_detail || s.config.warning || (s.status === "ready" && s.item_count > 0)) && (
                    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-rule bg-paper/60 px-5 py-3 text-[13px]">
                      <div className="min-w-0 flex-1">
                        {s.config.warning ? (
                          <p className="flex gap-2 text-[var(--grade-conflicting)]">
                            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                            {s.config.warning}
                          </p>
                        ) : (
                          s.status_detail && <p className="text-ink-muted">{s.status_detail}</p>
                        )}
                      </div>
                      {s.status === "ready" && s.item_count > 0 && (
                        <Link
                          href={`/projects/${projectId}/evidence?source=${s.id}`}
                          className="group inline-flex shrink-0 items-center gap-1 font-medium text-accent"
                        >
                          Browse evidence
                          <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                        </Link>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
