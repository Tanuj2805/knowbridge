import { ArrowRight, Check, Search, X } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { demoMode } from "@/auth";
import { Pagination } from "@/components/pagination";
import { EmptyState, Input, PageHeader, Progress, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { STEP_COUNT, nextStep } from "@/lib/progress";
import { ROLE_LABEL, type ProjectSummary } from "@/lib/types";
import { NewProjectDialog } from "./new-project-dialog";

export const metadata: Metadata = { title: "Projects" };

const PER_PAGE = 8;

const SORTS = [
  { key: "recent", label: "Newest" },
  { key: "name", label: "Name" },
  { key: "progress", label: "Least done" },
] as const;
type Sort = (typeof SORTS)[number]["key"];

export default async function ProjectsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const q = one("q").trim();
  const sort: Sort = SORTS.some((s) => s.key === one("sort")) ? (one("sort") as Sort) : "recent";
  const openNew = one("new") === "1";

  const all = await api<ProjectSummary[]>("/projects");
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const matching = all.filter((p) => words.every((w) => `${p.name} ${p.description}`.toLowerCase().includes(w)));
  const sorted = [...matching].sort((a, b) =>
    sort === "name"
      ? a.name.localeCompare(b.name)
      : sort === "progress"
        ? nextStep(a).done - nextStep(b).done || b.created_at.localeCompare(a.created_at)
        : b.created_at.localeCompare(a.created_at),
  );
  const pages = Math.max(1, Math.ceil(sorted.length / PER_PAGE));
  const page = Math.min(Math.max(1, Math.floor(Number(one("page"))) || 1), pages);
  const rows = sorted.slice((page - 1) * PER_PAGE, page * PER_PAGE);

  /** A link to this page with some settings changed (the others kept). */
  const link = (changes: Record<string, string | number | null>) => {
    const current = { q, sort: sort === "recent" ? "" : sort, page: page > 1 ? page : "" };
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...current, ...changes })) if (v) p.set(k, String(v));
    return `/projects${p.size ? `?${p}` : ""}`;
  };

  return (
    <main className="mx-auto w-full max-w-[80rem] flex-1 px-4 py-10 sm:px-6">
      <div className="animate-rise">
        <PageHeader title="Projects" actions={<NewProjectDialog demo={demoMode} defaultOpen={openNew} />}>
          Each project is one team&apos;s work: its sources, its claim ledger, and the handovers made from it.
        </PageHeader>

        {all.length === 0 ? (
          <EmptyState title="No projects yet" action={<NewProjectDialog demo={demoMode} />}>
            Start a project for a team where someone is about to leave. You&apos;ll connect its repository, notes and
            chats next.
          </EmptyState>
        ) : (
          <>
            {/* --- find and sort ------------------------------------------------------- */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <form method="get" action="/projects" className="relative w-full sm:max-w-sm">
                {sort !== "recent" && <input type="hidden" name="sort" value={sort} />}
                <label htmlFor="q" className="sr-only">
                  Find a project
                </label>
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint"
                  aria-hidden="true"
                />
                <Input id="q" name="q" defaultValue={q} placeholder="Find a project" className="pl-9 pr-9" />
                {q && (
                  <Link
                    href={link({ q: null, page: null })}
                    aria-label="Clear the search"
                    className="absolute right-2 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded text-ink-faint hover:bg-paper-sunk hover:text-ink"
                  >
                    <X className="size-3.5" aria-hidden="true" />
                  </Link>
                )}
              </form>
              <nav aria-label="Sort" className="inline-flex self-start rounded-md bg-paper-sunk p-0.5 text-[13px] sm:self-auto">
                {SORTS.map((s) => (
                  <Link
                    key={s.key}
                    href={link({ sort: s.key === "recent" ? null : s.key, page: null })}
                    scroll={false}
                    aria-current={sort === s.key ? "page" : undefined}
                    className={cx(
                      "rounded px-3 py-1.5 font-medium transition-colors",
                      sort === s.key ? "bg-paper-raised text-ink shadow-card" : "text-ink-muted hover:text-ink",
                    )}
                  >
                    {s.label}
                  </Link>
                ))}
              </nav>
            </div>

            {/* --- the list ------------------------------------------------------------ */}
            {rows.length === 0 ? (
              <p className="mt-6 rounded-xl border border-dashed border-rule-strong py-14 text-center text-[14px] text-ink-muted">
                No project matches &ldquo;{q}&rdquo;.{" "}
                <Link href={link({ q: null, page: null })} className="font-medium text-accent hover:underline">
                  Show all projects
                </Link>
              </p>
            ) : (
              <ul className="stagger mt-6 grid gap-4">
                {rows.map((p) => {
                  const step = nextStep(p);
                  const finished = step.done === STEP_COUNT;
                  return (
                    <li
                      key={p.id}
                      className="grid gap-6 rounded-xl border border-rule bg-paper-raised p-6 shadow-card transition-[border-color,box-shadow] duration-200 hover:border-rule-strong hover:shadow-lift md:grid-cols-[1fr_17rem] lg:grid-cols-[1fr_17rem_auto] lg:items-center lg:gap-0"
                    >
                      {/* name and what it is */}
                      <div className="min-w-0 lg:pr-8">
                        <Link
                          href={`/projects/${p.id}`}
                          className="font-display text-[1.35rem] leading-tight tracking-[-0.025em] text-ink transition-colors hover:text-accent"
                        >
                          {p.name}
                        </Link>
                        <p className="mt-1 text-[12px] text-ink-faint">
                          {p.my_roles.map((r) => ROLE_LABEL[r]).join(" · ")} · started {formatDate(p.created_at)}
                        </p>
                        <p className="mt-3 line-clamp-2 max-w-2xl text-[14px] leading-relaxed text-ink-muted">
                          {p.description || "No description yet."}
                        </p>
                      </div>

                      {/* how far along, and what's next */}
                      <div className="border-t border-rule pt-5 md:border-l md:border-t-0 md:pl-6 md:pt-0 lg:px-8">
                        <div className="flex items-baseline justify-between text-[12px]">
                          <span className="text-ink-faint">Towards a handover</span>
                          <span className="tabular-nums text-ink-muted">
                            {step.done} of {STEP_COUNT}
                          </span>
                        </div>
                        <div className="mt-2">
                          <Progress size="sm" value={step.done / STEP_COUNT} label="Steps done" tone={finished ? "success" : "accent"} />
                        </div>
                        <Link
                          href={step.href}
                          className={cx(
                            "group/next mt-3 inline-flex items-center gap-1 text-[13px] font-medium",
                            finished ? "text-[var(--grade-verified)]" : "text-ink-muted hover:text-accent",
                          )}
                        >
                          {finished ? <Check className="size-3.5" aria-hidden="true" /> : <span className="text-ink-faint">Next:</span>}
                          {step.label}
                          {!finished && (
                            <ArrowRight className="size-3.5 transition-transform group-hover/next:translate-x-0.5" aria-hidden="true" />
                          )}
                        </Link>
                      </div>

                      {/* the numbers, and a way in */}
                      <div className="flex items-center justify-between gap-6 border-t border-rule pt-5 md:col-span-2 lg:col-span-1 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
                        <dl className="grid grid-cols-4 gap-6 lg:gap-7 lg:text-right">
                          {(
                            [
                              [p.member_count, "people"],
                              [p.source_count, "sources"],
                              [p.claim_count, "claims"],
                              [p.handover_count, "handovers"],
                            ] as const
                          ).map(([n, label]) => (
                            <div key={label}>
                              <dd className="font-display text-[1.15rem] leading-none tabular-nums text-ink">
                                {n.toLocaleString("en-IN")}
                              </dd>
                              <dt className="mt-1.5 text-[11px] text-ink-faint">{label}</dt>
                            </div>
                          ))}
                        </dl>
                        <Link
                          href={`/projects/${p.id}`}
                          aria-label={`Open ${p.name}`}
                          className="group inline-flex size-9 shrink-0 items-center justify-center rounded-md border border-rule text-ink-faint transition-colors hover:border-accent hover:text-accent"
                        >
                          <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                        </Link>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}

            <Pagination
              page={page}
              pageSize={PER_PAGE}
              total={sorted.length}
              href={(n) => link({ page: n > 1 ? n : null })}
              noun="project"
            />
          </>
        )}
      </div>
    </main>
  );
}
