import { ArrowRight, Check, ChevronRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { auth } from "@/auth";
import { Pagination } from "@/components/pagination";
import { Avatar, Card, CardHeader, EmptyState, Progress, Stat, StatStrip, Tag, buttonClass, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, plural } from "@/lib/format";
import { nextStep } from "@/lib/progress";
import { HANDOVER_STATUS_LABEL, HANDOVER_STATUS_TONE, type Handover, type ProjectSummary } from "@/lib/types";

export const metadata: Metadata = { title: "Dashboard" };

const HANDOVERS_PER_PAGE = 5;
const PROJECTS_PER_PAGE = 5;

type Row = Handover & { project: ProjectSummary };

const FILTERS = [
  { key: "all", label: "All" },
  { key: "active", label: "In progress" },
  { key: "done", label: "Done" },
] as const;
type Filter = (typeof FILTERS)[number]["key"];

const isDone = (h: Handover) => h.status === "published" || h.status === "acknowledged";

function greeting(name: string) {
  const hour = Number(
    new Intl.DateTimeFormat("en-IN", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }).format(new Date()),
  );
  const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `${part}, ${name.split(" ")[0]}`;
}

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const filter: Filter = FILTERS.some((f) => f.key === one("show")) ? (one("show") as Filter) : "all";
  const asPage = (k: string) => Math.max(1, Math.floor(Number(one(k))) || 1);

  const session = await auth();
  const projects = await api<ProjectSummary[]>("/projects");
  const handovers: Row[] = (
    await Promise.all(
      projects.map((p) =>
        api<Handover[]>(`/projects/${p.id}/handovers`)
          .then((hs) => hs.map((h) => ({ ...h, project: p })))
          .catch(() => [] as Row[]),
      ),
    )
  )
    .flat()
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  const questions = handovers.reduce((n, h) => n + h.my_open, 0);
  const inProgress = handovers.filter((h) => !isDone(h));
  const claims = projects.reduce((n, p) => n + p.claim_count, 0);

  // --- handovers: filter and page ------------------------------------------------------------
  const filtered = handovers.filter((h) => (filter === "all" ? true : filter === "done" ? isDone(h) : !isDone(h)));
  const hCount = Math.max(1, Math.ceil(filtered.length / HANDOVERS_PER_PAGE));
  const hPage = Math.min(asPage("hpage"), hCount);
  const hRows = filtered.slice((hPage - 1) * HANDOVERS_PER_PAGE, hPage * HANDOVERS_PER_PAGE);

  const pCount = Math.max(1, Math.ceil(projects.length / PROJECTS_PER_PAGE));
  const pPage = Math.min(asPage("ppage"), pCount);
  const pRows = projects.slice((pPage - 1) * PROJECTS_PER_PAGE, pPage * PROJECTS_PER_PAGE);

  /** A link to this page with some settings changed (the others kept). */
  const link = (changes: Record<string, string | number | null>) => {
    const p = new URLSearchParams();
    const current = { show: filter === "all" ? "" : filter, hpage: hPage > 1 ? hPage : "", ppage: pPage > 1 ? pPage : "" };
    for (const [k, v] of Object.entries({ ...current, ...changes })) if (v) p.set(k, String(v));
    return `/dashboard${p.size ? `?${p}` : ""}`;
  };

  const today = new Intl.DateTimeFormat("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "Asia/Kolkata",
  }).format(new Date());

  return (
    <main className="mx-auto w-full max-w-[80rem] flex-1 px-4 py-10 sm:px-6">
      <div className="animate-rise">
        <header className="mb-8">
          <p className="text-[13px] text-ink-faint">{today}</p>
          <h1 className="mt-1.5 font-display text-[2.2rem] leading-[1.1] tracking-[-0.035em] text-ink sm:text-[2.6rem]">
            {greeting(session?.user?.name ?? "there")}
          </h1>
        </header>

        {/* --- the numbers ---------------------------------------------------------- */}
        <div>
          <StatStrip>
            <Stat label="Projects" value={projects.length} href="/projects" />
            <Stat label="Handovers in progress" value={inProgress.length} />
            <Stat label="Questions for you" value={questions} />
            <Stat label="Claims built" value={claims.toLocaleString("en-IN")} />
          </StatStrip>
        </div>

        {projects.length === 0 ? (
          <div className="mt-10">
            <EmptyState
              title="No projects yet"
              action={
                <Link href="/projects?new=1" className={buttonClass("primary")}>
                  New project
                </Link>
              }
            >
              Once you start a project, its handovers and progress show up here.
            </EmptyState>
          </div>
        ) : (
          <div className="mt-12 grid gap-12 lg:grid-cols-[1fr_22rem] lg:gap-14">
            {/* --- handovers -------------------------------------------------------- */}
            <Card id="handovers" className="scroll-mt-24">
              <CardHeader
                title="Handovers"
                action={
                  <nav aria-label="Show" className="inline-flex rounded-md bg-paper-sunk p-0.5 text-[13px]">
                    {FILTERS.map((f) => {
                      const n =
                        f.key === "all" ? handovers.length : f.key === "done" ? handovers.length - inProgress.length : inProgress.length;
                      return (
                        <Link
                          key={f.key}
                          href={link({ show: f.key === "all" ? null : f.key, hpage: null })}
                          scroll={false}
                          aria-current={filter === f.key ? "page" : undefined}
                          className={cx(
                            "rounded px-3 py-1.5 font-medium transition-colors",
                            filter === f.key ? "bg-paper-raised text-ink shadow-card" : "text-ink-muted hover:text-ink",
                          )}
                        >
                          {f.label} <span className="tabular-nums text-ink-faint">{n}</span>
                        </Link>
                      );
                    })}
                  </nav>
                }
              >
                Who is handing over to whom, and how far each one has got.
              </CardHeader>

              {hRows.length === 0 ? (
                <p className="mt-6 border-y border-rule py-10 text-center text-[14px] text-ink-muted">
                  {handovers.length === 0
                    ? "No handovers yet. Start one from a project's Handovers tab."
                    : filter === "done"
                      ? "No finished handovers yet."
                      : "Nothing in progress."}
                </p>
              ) : (
                <>
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[40rem] text-left text-[14px]">
                      <thead>
                        <tr className="border-b border-rule text-[12px] text-ink-faint">
                          <th className="py-2.5 pr-3 font-medium">Handover</th>
                          <th className="px-3 py-2.5 font-medium">Status</th>
                          <th className="px-3 py-2.5 font-medium">Gap Interview</th>
                          <th className="px-3 py-2.5 font-medium">Last day</th>
                          <th className="py-2.5 pl-3">
                            <span className="sr-only">Open</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody className="stagger divide-y divide-rule">
                        {hRows.map((h) => {
                          const href = `/projects/${h.project.id}/handovers/${h.id}`;
                          return (
                            <tr key={h.id} className="group transition-colors hover:bg-paper-raised">
                              <td className="py-3.5 pr-3">
                                <Link href={href} className="flex items-center gap-3">
                                  <span className="flex shrink-0 items-center">
                                    <Avatar name={h.leaver.name} size={28} />
                                    <span className="-ml-1.5 rounded-full ring-2 ring-paper">
                                      <Avatar name={h.successor.name} size={28} />
                                    </span>
                                  </span>
                                  <span className="min-w-0">
                                    <span className="block truncate font-medium text-ink group-hover:text-accent">{h.title}</span>
                                    <span className="block truncate text-[12px] text-ink-faint">{h.project.name}</span>
                                  </span>
                                </Link>
                              </td>
                              <td className="px-3 py-3.5">
                                <Tag tone={HANDOVER_STATUS_TONE[h.status]}>{HANDOVER_STATUS_LABEL[h.status]}</Tag>
                                {h.my_open > 0 && (
                                  <p className="mt-0.5 text-[12px] font-medium text-accent">
                                    {plural(h.my_open, "question")} for you
                                  </p>
                                )}
                              </td>
                              <td className="px-3 py-3.5">
                                {h.questions_total > 0 ? (
                                  <div className="flex items-center gap-2.5">
                                    <div className="w-20">
                                      <Progress
                                        size="sm"
                                        value={h.questions_answered / h.questions_total}
                                        label="Questions answered"
                                        tone={h.questions_open === 0 ? "success" : "accent"}
                                      />
                                    </div>
                                    <span className="text-[12px] tabular-nums text-ink-muted">
                                      {h.questions_answered} of {h.questions_total}
                                    </span>
                                  </div>
                                ) : (
                                  <span className="text-[13px] text-ink-faint">Not started</span>
                                )}
                              </td>
                              <td className="px-3 py-3.5 text-[13px] text-ink-muted">
                                {h.leaver_last_day ? formatDate(h.leaver_last_day) : "—"}
                              </td>
                              <td className="py-3.5 pl-3 text-right">
                                <Link
                                  href={href}
                                  aria-label={`Open ${h.title}`}
                                  className="inline-flex size-8 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-paper-sunk hover:text-accent"
                                >
                                  <ChevronRight className="size-4" aria-hidden="true" />
                                </Link>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <Pagination
                    page={hPage}
                    pageSize={HANDOVERS_PER_PAGE}
                    total={filtered.length}
                    href={(p) => link({ hpage: p > 1 ? p : null })}
                    noun="handover"
                  />
                </>
              )}
            </Card>

            {/* --- projects --------------------------------------------------------- */}
            <Card as="aside" id="projects" className="self-start scroll-mt-24">
              <CardHeader
                title="Projects"
                action={
                  <Link href="/projects" className="text-[13px] font-medium text-accent hover:underline underline-offset-4">
                    View all
                  </Link>
                }
              >
                What each project needs next.
              </CardHeader>
              <ul className="stagger mt-3 divide-y divide-rule">
                {pRows.map((p) => {
                  const step = nextStep(p);
                  const finished = step.done === 5;
                  return (
                    <li key={p.id} className="py-4">
                      <Link href={`/projects/${p.id}`} className="group block">
                        <div className="flex items-baseline justify-between gap-3">
                          <p className="truncate text-[15px] font-semibold text-ink group-hover:text-accent">{p.name}</p>
                          <span className="shrink-0 text-[12px] tabular-nums text-ink-faint">{step.done} of 5</span>
                        </div>
                        <div className="mt-2">
                          <Progress size="sm" value={step.done / 5} label="Steps done" tone={finished ? "success" : "accent"} />
                        </div>
                      </Link>
                      <Link
                        href={step.href}
                        className={cx(
                          "group/next mt-2 inline-flex items-center gap-1 text-[13px] font-medium",
                          finished ? "text-[var(--grade-verified)]" : "text-ink-muted hover:text-accent",
                        )}
                      >
                        {finished ? (
                          <Check className="size-3.5" aria-hidden="true" />
                        ) : (
                          <span className="text-ink-faint">Next:</span>
                        )}
                        {step.label}
                        {!finished && (
                          <ArrowRight className="size-3.5 transition-transform group-hover/next:translate-x-0.5" aria-hidden="true" />
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ul>
              <Pagination
                page={pPage}
                pageSize={PROJECTS_PER_PAGE}
                total={projects.length}
                href={(p) => link({ ppage: p > 1 ? p : null })}
                noun="project"
              />
            </Card>
          </div>
        )}
      </div>
    </main>
  );
}
