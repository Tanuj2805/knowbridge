import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/auto-refresh";
import { SensitivityTag } from "@/components/evidence-bits";
import { EmptyState, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { plural, timeAgo } from "@/lib/format";
import { SOURCE_KIND_LABEL, type EvidenceStats, type Member, type ProjectSummary, type Source } from "@/lib/types";
import { AddSource } from "./add-source";
import { ConnectionSettings } from "./connection-settings";
import { SourceActions } from "./source-actions";

export const metadata: Metadata = { title: "Sources" };

const STATUS: Record<Source["status"], { label: string; cls: string }> = {
  pending: { label: "Waiting", cls: "text-ink-muted" },
  syncing: { label: "Reading", cls: "text-accent" },
  ready: { label: "Ready", cls: "text-[var(--grade-verified)]" },
  failed: { label: "Failed", cls: "text-danger" },
};

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

  return (
    <div className="grid gap-12 lg:grid-cols-[1fr_26rem]">
      <AutoRefresh active={busy} />
      <section>
        <h2 className="font-serif text-xl">Connected sources</h2>
        <p className="text-ink-muted text-[15px] mt-1 max-w-xl">
          Everything here is read-only. Secrets and personal details are masked on the way in, before anything is
          stored or seen by a model.
        </p>
        {stats.search_external && (
          <p className="text-[13px] text-ink-muted mt-2 max-w-xl border-l-2 border-rule-strong pl-3">
            For smart search, the masked text of Team and Restricted items is sent to Google (Gemini) to be indexed.
            Confidential items are never sent; they stay searchable by keyword for people cleared to see them.
          </p>
        )}

        {sources.length === 0 ? (
          <div className="mt-6">
            <EmptyState title="No sources yet">
              Start with the repository and the meeting notes. Chats are where most of the &ldquo;why&rdquo; lives,
              so add them if you can.
            </EmptyState>
          </div>
        ) : (
          <ul className="mt-5 divide-y divide-rule border-y border-rule">
            {sources.map((s) => {
              const st = STATUS[s.status];
              const who =
                s.readers.length === 0
                  ? "Everyone on the project"
                  : s.readers.map((r) => names.get(r) ?? "someone").join(", ");
              return (
                <li key={s.id} className="py-4 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-start">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="font-medium text-[15px]">{s.name}</span>
                      <span className="text-[13px] text-ink-faint">{s.config.provider === "jira"
                          ? "Jira Cloud (live)"
                          : s.config.repo
                            ? "GitHub (live)"
                            : SOURCE_KIND_LABEL[s.kind]}
                      </span>
                      <SensitivityTag value={s.default_sensitivity} quiet />
                    </div>
                    <p className="text-[13px] mt-1">
                      <span className={cx("font-medium", st.cls)}>
                        {st.label}
                        {(s.status === "syncing" || s.status === "pending") && "…"}
                      </span>
                      {s.status_detail && <span className="text-ink-muted"> · {s.status_detail}</span>}
                    </p>
                    <p className="text-[13px] text-ink-faint mt-1">
                      {plural(s.item_count, "item")} · synced {timeAgo(s.last_synced_at)} · visible to {who}
                    </p>
                    {s.config.repo && (
                      <p className="text-[13px] text-ink-faint mt-1 font-mono break-all">
                        github.com/{s.config.repo} · {s.config.visibility ?? "public"} ·{" "}
                        {s.config.uses_own_token ? `own token${s.config.account ? ` (${s.config.account})` : ""}` : "server token"}
                      </p>
                    )}
                    {s.config.warning && (
                      <p className="text-[13px] mt-1 text-[var(--grade-conflicting)]">⚠ {s.config.warning}</p>
                    )}
                    {s.config.provider === "jira" && (
                      <p className="text-[13px] text-ink-faint mt-1 font-mono break-all">
                        {s.config.site?.replace("https://", "")} · {s.config.jql} · as {s.config.account}
                      </p>
                    )}
                    {s.status === "ready" && s.item_count > 0 && (
                      <Link
                        href={`/projects/${projectId}/evidence?source=${s.id}`}
                        className="inline-block mt-1.5 text-[13px] text-accent underline-offset-4 hover:underline"
                      >
                        Browse its evidence
                      </Link>
                    )}
                  </div>
                  {admin && (
                    <div className="flex flex-col items-end gap-1">
                      <SourceActions
                        projectId={projectId}
                        sourceId={s.id}
                        name={s.name}
                        busy={s.status === "syncing" || s.status === "pending"}
                        live={Boolean(s.config.provider === "jira" || s.config.repo)}
                      />
                      {(s.config.provider === "jira" || s.config.repo) && (
                        <ConnectionSettings
                          projectId={projectId}
                          sourceId={s.id}
                          provider={s.config.provider === "jira" ? "jira" : "github"}
                          jql={s.config.jql}
                        />
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {admin ? (
        <aside>
          <h2 className="font-serif text-xl mb-4">Connect a source</h2>
          <AddSource projectId={projectId} members={members} />
        </aside>
      ) : (
        <aside className="text-[14px] text-ink-muted">Only the project admin can connect or remove sources.</aside>
      )}
    </div>
  );
}
