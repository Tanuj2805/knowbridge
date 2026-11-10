import { Bot, ExternalLink, Search, X } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { AgentPipeline } from "@/components/agent-pipeline";
import { AutoRefresh } from "@/components/auto-refresh";
import { KindTag, RedactedText, SensitivityTag } from "@/components/evidence-bits";
import { FilterMenu } from "@/components/filter-menu";
import { Pagination } from "@/components/pagination";
import { EmptyState, Input, PageHeader, Tag, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, plural } from "@/lib/format";
import {
  AGENT_LABEL,
  CLAIM_TYPE_LABEL,
  EVIDENCE_KIND_LABEL,
  GRADE_LABEL,
  type Claim,
  type ClaimRef,
  type ClaimType,
  type Grade,
  type LedgerPage,
} from "@/lib/types";
import { ApproveAll, ApproveVerified, ClaimReview } from "./claim-review";
import { DetailsToggle } from "./details-toggle";
import { StartRun } from "./start-run";

export const metadata: Metadata = { title: "Claim ledger" };

const ACTIVE = new Set(["queued", "running"]);
/** Claims per page: a few hundred cards at once made the page take seconds to render. */
const PAGE_SIZE = 25;
const GRADE_ORDER: Grade[] = ["verified", "attested", "supported", "inferred", "conflicting", "missing"];

type Filters = { type: string; grade: string; show: string; review: string; q: string; page: number };

export default async function LedgerView({ params, searchParams }: PageProps<"/projects/[projectId]/ledger">) {
  const { projectId } = await params;
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const f: Filters = {
    type: one("type") as ClaimType | "",
    grade: one("grade") as Grade | "",
    show: one("show") === "removed" ? "removed" : "",
    review: (["todo", "approved"] as const).find((r) => r === one("review")) ?? "",
    q: one("q"),
    page: Math.max(1, Math.floor(Number(one("page"))) || 1),
  };

  const query = new URLSearchParams();
  if (f.type) query.set("type", f.type);
  if (f.grade) query.set("grade", f.grade);
  if (f.show) query.set("show", f.show);
  if (f.review) query.set("review", f.review);
  if (f.q) query.set("q", f.q);
  query.set("limit", String(PAGE_SIZE));
  query.set("offset", String((f.page - 1) * PAGE_SIZE));
  const page = await api<LedgerPage>(`/projects/${projectId}/claims?${query}`);
  const run = page.run;
  const active = !!run && ACTIVE.has(run.status);
  const total = Object.values(page.counts).reduce((a, b) => a + (b ?? 0), 0);
  const base = `/projects/${projectId}/ledger`;
  const todo = page.review.todo ?? 0;

  /** This page with some filters changed and the rest kept; any change goes back to page 1. */
  const link = (changes: Partial<Record<keyof Filters, string | number | null>>) => {
    const next = { ...f, page: "", ...changes } as Record<string, string | number | null>;
    const p = new URLSearchParams();
    for (const k of ["type", "grade", "review", "show", "q", "page"]) {
      const v = next[k];
      if (v && !(k === "page" && Number(v) <= 1)) p.set(k, String(v));
    }
    return `${base}${p.size ? `?${p}` : ""}`;
  };
  const filtered = !!(f.type || f.grade || f.review || f.show || f.q);

  return (
    <div>
      <AutoRefresh active={active} every={2500} />
      <PageHeader
        title="Claim ledger"
        actions={
          run ? (
            <StartRun
              projectId={projectId}
              label={active ? "Building…" : "Build again"}
              disabled={active || !page.llm_ready}
              variant="secondary"
            />
          ) : undefined
        }
      >
        What the agents found, each with the exact words it came from. Nothing is final until a person approves it.
      </PageHeader>

      {!run ? (
        <EmptyState
          title="No claims yet"
          action={<StartRun projectId={projectId} label="Build claims" disabled={!page.llm_ready} />}
        >
          The agents read this project&apos;s evidence: decisions, owners, dependencies, risks and open questions come
          out as claims, each with the quote it rests on. It takes a minute or two.
          {!page.llm_ready && (
            <span className="mt-2 block text-danger">
              No AI model is set up yet. Add GEMINI_API_KEY, or LLM_BASE_URL and LLM_API_KEY, to .env.
            </span>
          )}
        </EmptyState>
      ) : (
        <>
          <AgentPipeline run={run} />
          {total > 0 && <Summary page={page} total={total} link={link} />}

          {/* --- find and filter ------------------------------------------------------------ */}
          <section aria-label="Find and filter" className="mt-8 grid gap-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
              <form method="get" action={base} className="relative flex-1">
                {f.type && <input type="hidden" name="type" value={f.type} />}
                {f.grade && <input type="hidden" name="grade" value={f.grade} />}
                {f.review && <input type="hidden" name="review" value={f.review} />}
                {f.show && <input type="hidden" name="show" value={f.show} />}
                <label htmlFor="q" className="sr-only">
                  Find a claim
                </label>
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden="true" />
                <Input id="q" name="q" defaultValue={f.q} placeholder="Find a claim: Railway, Sneha, payments…" className="pl-9 pr-9" />
                {f.q && (
                  <Link
                    href={link({ q: null })}
                    aria-label="Clear the search"
                    className="absolute right-2 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded text-ink-faint hover:bg-paper-sunk hover:text-ink"
                  >
                    <X className="size-3.5" aria-hidden="true" />
                  </Link>
                )}
              </form>
              <div className="flex flex-wrap items-center gap-2">
                {Object.keys(page.grades).length > 0 && (
                  <FilterMenu
                    label="Grade"
                    options={[
                      { label: "Any", href: link({ grade: null }), current: !f.grade },
                      ...GRADE_ORDER.filter((g) => page.grades[g]).map((g) => ({
                        label: GRADE_LABEL[g][0],
                        href: link({ grade: g }),
                        current: f.grade === g,
                        count: page.grades[g],
                        colour: `var(--grade-${g})`,
                      })),
                    ]}
                  />
                )}
                {page.can_review && (
                  <nav aria-label="Review" className="inline-flex rounded-md bg-paper-sunk p-0.5 text-[13px]">
                    {(
                      [
                        ["", "All"],
                        ["todo", "To review"],
                        ["approved", "Approved"],
                      ] as const
                    ).map(([key, label]) => (
                      <Link
                        key={key || "all"}
                        href={link({ review: key || null, show: null })}
                        scroll={false}
                        aria-current={f.review === key && !f.show ? "page" : undefined}
                        className={cx(
                          "rounded px-3 py-2 font-medium transition-colors",
                          f.review === key && !f.show ? "bg-paper-raised text-ink shadow-card" : "text-ink-muted hover:text-ink",
                        )}
                      >
                        {label}
                        {key && (
                          <span className="ml-1 tabular-nums text-ink-faint">
                            {key === "todo" ? todo : (page.review.approved ?? 0)}
                          </span>
                        )}
                      </Link>
                    ))}
                  </nav>
                )}
              </div>
            </div>

            {/* the kinds of claim, as tabs */}
            <nav aria-label="Claim types" className="flex flex-wrap gap-1.5">
              {[
                { key: "", label: "All claims", n: total },
                ...(Object.keys(CLAIM_TYPE_LABEL) as ClaimType[])
                  .filter((t) => page.counts[t])
                  .map((t) => ({ key: t, label: CLAIM_TYPE_LABEL[t][1], n: page.counts[t] ?? 0 })),
              ].map((t) => {
                const on = f.type === t.key && !f.show;
                return (
                  <Link
                    key={t.key || "all"}
                    href={link({ type: t.key || null, show: null })}
                    scroll={false}
                    aria-current={on ? "page" : undefined}
                    className={cx(
                      "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium transition-colors",
                      on ? "border-ink bg-ink text-paper" : "border-rule-strong text-ink-muted hover:border-ink-faint hover:text-ink",
                    )}
                  >
                    {t.label}
                    <span className={cx("tabular-nums", on ? "text-paper/70" : "text-ink-faint")}>{t.n}</span>
                  </Link>
                );
              })}
              {page.removed > 0 && (
                <Link
                  href={link({ show: f.show ? null : "removed", type: null, review: null })}
                  scroll={false}
                  aria-current={f.show ? "page" : undefined}
                  className={cx(
                    "inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed px-3 text-[13px] font-medium transition-colors",
                    f.show ? "border-ink text-ink" : "border-rule-strong text-ink-faint hover:text-ink",
                  )}
                >
                  Removed by the Skeptic <span className="tabular-nums">{page.removed}</span>
                </Link>
              )}
            </nav>

            {/* approve in bulk, when there's something to approve */}
            {page.can_review && todo > 0 && !f.show && (
              <div className="flex flex-col gap-3 rounded-lg border border-accent/25 bg-accent-soft/60 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-[14px] text-ink">
                  <span className="font-semibold">{plural(todo, "claim")}</span> waiting for review. Only approved claims go
                  into the handover pack.
                </p>
                <div className="flex flex-wrap items-start gap-2">
                  <ApproveVerified projectId={projectId} />
                  <ApproveAll projectId={projectId} count={todo} />
                </div>
              </div>
            )}
          </section>

          {/* --- the claims --------------------------------------------------------------------- */}
          <section aria-label="Claims" className="mt-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-[13px] text-ink-muted">
                {page.total ? plural(page.total, "claim") : "No claims"}
                {filtered && " match these filters"}
                {filtered && (
                  <Link href={base} className="ml-2 font-medium text-accent hover:underline">
                    Clear all filters
                  </Link>
                )}
              </p>
              {page.hidden > 0 && (
                <p className="text-[12px] text-ink-faint">
                  {plural(page.hidden, "claim")} {page.hidden === 1 ? "cites" : "cite"} evidence outside your access
                  and {page.hidden === 1 ? "isn't" : "aren't"} shown.
                </p>
              )}
            </div>

            {f.show === "removed" && (
              <p className="mt-3 max-w-3xl text-[13px] leading-relaxed text-ink-muted">
                The Skeptic found nothing in these claims&apos; own evidence that backs them, so they&apos;re left out of
                the ledger. They&apos;re kept here so a person can check the Skeptic was right.
              </p>
            )}

            {page.total === 0 ? (
              <div className="mt-4">
                <EmptyState title={active ? "Reading the evidence…" : f.q ? "No claim matches" : "No claims here"}>
                  {active
                    ? "Claims appear here as each agent finishes. This page updates by itself."
                    : f.q
                      ? "Try another word. This looks in statements, subjects, owners and reasons."
                      : "Nothing matches these filters."}
                </EmptyState>
              </div>
            ) : (
              <>
                <ol className="stagger mt-4 grid gap-3">
                  {page.items.map((c) => (
                    <ClaimCard
                      key={c.id}
                      claim={c}
                      projectId={projectId}
                      removed={f.show === "removed"}
                      canReview={page.can_review}
                    />
                  ))}
                </ol>
                <Pagination
                  page={f.page}
                  pageSize={PAGE_SIZE}
                  total={page.total}
                  href={(n) => link({ page: n })}
                  noun="claim"
                />
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}

// --- at a glance ------------------------------------------------------------

function Summary({
  page,
  total,
  link,
}: {
  page: LedgerPage;
  total: number;
  link: (changes: { grade?: string; review?: string }) => string;
}) {
  const graded = GRADE_ORDER.reduce((n, g) => n + (page.grades[g] ?? 0), 0);
  const approved = page.review.approved ?? 0;
  return (
    <section aria-label="At a glance" className="mt-6 grid gap-6 border-y border-rule py-5 md:grid-cols-[1fr_16rem]">
      <div>
        <p className="text-[13px] text-ink-muted">
          <span className="font-medium text-ink">{total}</span> claims · how well the evidence backs them
        </p>
        {graded === 0 && (
          <p className="mt-2 text-[13px] text-ink-faint">Grades appear when the Skeptic has checked each claim.</p>
        )}
        <div
          className={cx("mt-2 flex h-2.5 overflow-hidden rounded-full bg-paper-sunk", graded === 0 && "hidden")}
          aria-hidden="true"
        >
          {GRADE_ORDER.map((g) =>
            page.grades[g] ? (
              <span
                key={g}
                style={{ width: `${(100 * (page.grades[g] ?? 0)) / Math.max(graded, 1)}%`, background: `var(--grade-${g})` }}
              />
            ) : null,
          )}
        </div>
        <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
          {GRADE_ORDER.filter((g) => page.grades[g]).map((g) => (
            <li key={g}>
              <Link
                href={link({ grade: g })}
                className="inline-flex items-center gap-1.5 text-ink-muted hover:text-ink"
                title={GRADE_LABEL[g][1]}
              >
                <span className="size-2 rounded-full" style={{ background: `var(--grade-${g})` }} aria-hidden="true" />
                {GRADE_LABEL[g][0]} <span className="tabular-nums text-[12px] text-ink-faint">{page.grades[g]}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
      <div className="md:border-l md:border-rule md:pl-5">
        <p className="text-[13px] text-ink-muted">
          <span className="font-medium text-ink">{approved}</span> of {total} approved
        </p>
        <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-paper-sunk" aria-hidden="true">
          <span className="block h-full rounded-full bg-accent" style={{ width: `${(100 * approved) / Math.max(total, 1)}%` }} />
        </div>
        {(page.review.todo ?? 0) > 0 ? (
          <Link
            href={link({ review: "todo" })}
            className="mt-2.5 inline-block text-[13px] text-accent underline-offset-2 hover:underline"
          >
            {plural(page.review.todo ?? 0, "claim")} to review →
          </Link>
        ) : (
          <p className="mt-2.5 text-[13px] text-[var(--grade-verified)]">Everything has been reviewed.</p>
        )}
      </div>
    </section>
  );
}

// --- a claim --------------------------------------------------------------

function GradeTag({ grade, reason }: { grade: Grade; reason: string }) {
  return (
    <span
      title={reason || GRADE_LABEL[grade][1]}
      className="inline-flex items-center gap-1.5 font-medium"
      style={{ color: `var(--grade-${grade})` }}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {GRADE_LABEL[grade][0]}
    </span>
  );
}

/** Other claims this one points to (ones it disagrees with, or that it replaced), inside the details. */
function RefList({ items }: { items: ClaimRef[] }) {
  return (
    <ul className="grid gap-1.5">
      {items.map((r) => (
        <li key={r.id} className="text-[14px] leading-relaxed text-ink">
          <a href={`#claim-${r.id}`} className="underline-offset-2 hover:underline">
            <RedactedText text={r.statement} />
          </a>
          {(r.valid_from || r.valid_to) && (
            <span className="text-[12px] text-ink-faint">
              {" "}
              ({r.valid_from && formatDate(r.valid_from)}
              {r.valid_to && ` – ${formatDate(r.valid_to)}`})
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Where the claim stands with its reviewer, for the top-right corner of the card. */
function ReviewStatus({ claim: c, removed, canReview }: { claim: Claim; removed?: boolean; canReview?: boolean }) {
  if (removed) return <Tag>{c.reviewed_by_name ? `Rejected by ${c.reviewed_by_name}` : "Removed"}</Tag>;
  if (c.status === "approved" || c.status === "edited") {
    return (
      <Tag tone="success" title={c.review_note || undefined}>
        {c.status === "edited" ? "Edited and approved" : "Approved"}
        {c.reviewed_by_name && ` by ${c.reviewed_by_name}`}
      </Tag>
    );
  }
  return canReview ? <Tag tone="accent">Needs review</Tag> : null;
}

/** One labelled part of a claim's details. */
function Detail({ title, tone, children }: { title: string; tone?: "conflict"; children: React.ReactNode }) {
  return (
    <section>
      <h3
        className={cx(
          "text-[12px] font-semibold uppercase tracking-[0.08em]",
          tone === "conflict" ? "text-[var(--grade-conflicting)]" : "text-ink-faint",
        )}
      >
        {title}
      </h3>
      <div className="mt-1.5">{children}</div>
    </section>
  );
}

/**
 * A claim, kept short: what kind it is, how well it's backed, the statement, one line of facts, and the
 * reviewer's buttons. The reasons, the Skeptic's note, related claims and every source quote are one
 * click away under "Why and evidence".
 */
function ClaimCard({
  claim: c,
  projectId,
  removed,
  canReview,
}: {
  claim: Claim;
  projectId: string;
  removed?: boolean;
  canReview?: boolean;
}) {
  const facts = [
    c.owner_name && `Owner ${c.owner_name}`,
    c.due_date && `due ${formatDate(c.due_date)}`,
    c.valid_from && `since ${formatDate(c.valid_from)}`,
    plural(c.evidence.length, "source"),
  ].filter(Boolean);
  const skeptic =
    (removed || (c.checked && ["inferred", "conflicting", "missing"].includes(c.grade))) &&
    !c.from_system_data &&
    c.grade_reason;

  return (
    <li
      id={`claim-${c.id}`}
      className={cx(
        "scroll-mt-24 overflow-hidden rounded-xl border bg-paper-raised shadow-card transition-[border-color,box-shadow] duration-200 hover:shadow-lift",
        removed ? "border-dashed border-rule-strong" : "border-rule hover:border-rule-strong",
      )}
    >
      <div className="px-5 pb-4 pt-4">
        {/* how well it's backed, what kind it is, and where it stands */}
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-[12px]">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            {!removed &&
              (c.checked ? (
                <GradeTag grade={c.grade} reason={c.grade_reason} />
              ) : (
                <span title="The Skeptic hasn't checked this against its evidence yet." className="text-ink-faint">
                  Not checked yet
                </span>
              ))}
            <span className="text-ink-faint">·</span>
            <span className="font-medium text-ink-muted">{CLAIM_TYPE_LABEL[c.type][0]}</span>
            {c.impact === 3 && <Tag>High impact</Tag>}
            <SensitivityTag value={c.sensitivity} quiet />
          </div>
          <ReviewStatus claim={c} removed={removed} canReview={canReview} />
        </div>

        {/* the claim itself */}
        <p className="mt-2.5 text-[16px] font-semibold leading-snug text-ink">
          <RedactedText text={c.statement} />
        </p>
        <p className="mt-1.5 text-[13px] text-ink-muted">{facts.join(" · ")}</p>

        {/* the one thing worth seeing before opening the details */}
        {c.conflicts.length > 0 && (
          <p className="mt-2 text-[13px] font-medium text-[var(--grade-conflicting)]">
            Disagrees with {plural(c.conflicts.length, "other claim")}: open the details to compare
          </p>
        )}
        {c.grade_reason === "unanswered" && (
          <p className="mt-2 text-[13px] font-medium text-[var(--grade-missing)]">Asked, but nobody answered</p>
        )}
      </div>

      <DetailsToggle
        label="Why and evidence"
        actions={canReview ? <ClaimReview projectId={projectId} claim={c} removed={removed} /> : undefined}
      >
        <div className="grid gap-5">
          {c.subject && (
            <Detail title="About">
              <p className="text-[14px] text-ink">{c.subject}</p>
            </Detail>
          )}
          {c.rationale && (
            <Detail title="Why">
              <p className="text-[14px] leading-relaxed text-ink">
                <RedactedText text={c.rationale} />
              </p>
            </Detail>
          )}
          {c.alternatives.length > 0 && (
            <Detail title="Considered instead">
              <p className="text-[14px] text-ink">{c.alternatives.join("; ")}</p>
            </Detail>
          )}
          {skeptic && (
            <Detail title="What the Skeptic said">
              <p className="text-[14px] text-ink">{c.grade_reason}</p>
            </Detail>
          )}
          {c.conflicts.length > 0 && (
            <Detail title="Disagrees with" tone="conflict">
              <RefList items={c.conflicts} />
            </Detail>
          )}
          {c.replaces.length > 0 && (
            <Detail title="Earlier, before this changed">
              <RefList items={c.replaces} />
            </Detail>
          )}
          {c.evidence.length > 0 && (
            <Detail title={c.evidence.length === 1 ? "Evidence" : `Evidence · ${c.evidence.length} sources`}>
              <div className="grid gap-2">
                {c.evidence.map((e) => (
                  <Quote key={e.evidence_id} e={e} projectId={projectId} />
                ))}
              </div>
            </Detail>
          )}
          <p className="inline-flex items-center gap-1.5 text-[12px] text-ink-faint">
            <Bot className="size-3.5" aria-hidden="true" />
            Found by {AGENT_LABEL[c.created_by_agent] ?? c.created_by_agent}
            {c.from_system_data && " · read straight from system data, not written by a model"}
            {c.version > 1 && ` · version ${c.version}`}
            {c.review_note && ` · reviewer's note: ${c.review_note}`}
          </p>
        </div>
      </DetailsToggle>
    </li>
  );
}

function Quote({ e, projectId }: { e: Claim["evidence"][number]; projectId: string }) {
  return (
    <figure className="rounded-lg border-l-[3px] border-accent/40 bg-paper-raised px-4 py-3">
      <blockquote className="text-[14px] leading-relaxed text-ink">
        “<RedactedText text={e.quote} />”
      </blockquote>
      <figcaption className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12px] text-ink-faint">
        <KindTag>{EVIDENCE_KIND_LABEL[e.kind] ?? e.kind}</KindTag>
        <Link
          href={`/projects/${projectId}/evidence/${e.evidence_id}`}
          className="font-medium text-ink-muted underline-offset-2 hover:text-accent hover:underline"
        >
          {e.source_name}
          {e.locator && ` · ${e.locator}`}
        </Link>
        <span>{[e.author, formatDate(e.occurred_at)].filter(Boolean).join(" · ")}</span>
        {e.permalink && (
          <a href={e.permalink} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:text-ink">
            Original <ExternalLink className="size-3" aria-hidden="true" />
          </a>
        )}
      </figcaption>
    </figure>
  );
}
