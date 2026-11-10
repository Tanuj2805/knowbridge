import type { Metadata } from "next";
import Link from "next/link";
import { Card, EmptyState, PageHeader, buttonClass, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { describe, iconFor, type AuditEvent } from "@/lib/audit";
import { formatDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Audit log" };

const AREAS: { key: string; label: string; prefixes: string[] }[] = [
  { key: "", label: "Everything", prefixes: [] },
  { key: "review", label: "Claims and review", prefixes: ["claim.", "run."] },
  { key: "handover", label: "Handovers and packs", prefixes: ["handover.", "interview.", "pack."] },
  { key: "access", label: "Evidence and access", prefixes: ["evidence.", "source.", "member.", "search."] },
];

export default async function AuditPage({ params, searchParams }: PageProps<"/projects/[projectId]/audit">) {
  const { projectId } = await params;
  const sp = await searchParams;
  const area = AREAS.find((a) => a.key === sp.area) ?? AREAS[0];
  const before = typeof sp.before === "string" ? sp.before : "";
  const query = new URLSearchParams({ limit: "200" });
  if (before) query.set("before", before);
  const all = await api<AuditEvent[]>(`/projects/${projectId}/audit?${query}`);
  const events = area.prefixes.length ? all.filter((e) => area.prefixes.some((p) => e.action.startsWith(p))) : all;
  const base = `/projects/${projectId}/audit`;

  return (
    <div>
      <PageHeader title="Audit log">
        Every view of a pack, every approval and edit, every export and every label change, newest first. Nothing here
        can be edited or deleted from the app.
      </PageHeader>

      <nav aria-label="Areas" className="mb-6 inline-flex flex-wrap gap-1 rounded-md bg-paper-sunk p-1 text-[13px]">
        {AREAS.map((a) => (
          <Link
            key={a.key}
            href={a.key ? `${base}?area=${a.key}` : base}
            aria-current={a === area ? "page" : undefined}
            className={cx(
              "rounded-md px-3 py-1.5 font-medium transition-all duration-150",
              a === area ? "bg-paper-raised text-ink shadow-card" : "text-ink-muted hover:text-ink",
            )}
          >
            {a.label}
          </Link>
        ))}
      </nav>

      {events.length === 0 ? (
        <EmptyState title="Nothing here yet">
          Actions in this project will be recorded here as they happen.
        </EmptyState>
      ) : (
        <Card>
          <ol className="divide-y divide-rule">
            {events.map((e) => {
              const Icon = iconFor(e);
              return (
                <li key={e.id} className="flex items-center gap-4 py-3">
                  <Icon className="size-4 shrink-0 text-ink-faint" aria-hidden="true" />
                  <p className="min-w-0 flex-1 text-[14px] text-ink-muted">
                    <span className="font-medium text-ink">{e.actor ?? "KnowBridge"}</span>{" "}
                    {describe(e)}
                  </p>
                  <time dateTime={e.at} className="shrink-0 tabular-nums text-[12px]  text-ink-faint">
                    {formatDateTime(e.at)}
                  </time>
                </li>
              );
            })}
          </ol>
        </Card>
      )}

      {all.length === 200 && (
        <div className="mt-4">
          <Link
            href={`${base}?${new URLSearchParams({ ...(area.key ? { area: area.key } : {}), before: all[all.length - 1].at })}`}
            className={buttonClass("secondary", "sm")}
          >
            Older →
          </Link>
        </div>
      )}
    </div>
  );
}
