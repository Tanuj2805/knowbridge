import { CalendarDays, ChevronRight, Download, Flag, Lock } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { KindTag, RedactedText } from "@/components/evidence-bits";
import { Avatar, BackLink, EmptyState, Progress, buttonClass, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate, formatDateTime, plural } from "@/lib/format";
import { EVIDENCE_KIND_LABEL, GRADE_LABEL, type Pack, type PackBlock, type PackSection, type User } from "@/lib/types";
import { PublishButton } from "../pack-actions";
import { Acknowledge, FlagClaim, PlanCheck, PrintButton } from "./pack-controls";
import { ShowMore } from "./show-more";

export const metadata: Metadata = { title: "Handover pack" };

/** Items shown in each section before "Show all". */
const FIRST = 5;

/** Why an item was held back from this reader. */
const WHY: Record<string, string> = {
  restricted: "Restricted",
  confidential: "Confidential",
  "source access": "from sources you can't open",
};

/** What one item in each section is called, for "Show all 160 risks". */
const NOUN: Record<string, [string, string]> = {
  yours: ["thing", "things"],
  decisions: ["decision", "decisions"],
  people: ["person or owner", "people and owners"],
  systems: ["system", "systems"],
  risks: ["risk", "risks"],
  open: ["question", "questions"],
};

type Ids = { projectId: string; handoverId: string };

export default async function PackPage({ params }: PageProps<"/projects/[projectId]/handovers/[handoverId]/pack">) {
  const { projectId, handoverId } = await params;
  const back = `/projects/${projectId}/handovers/${handoverId}`;
  let pack: Pack;
  try {
    pack = await api<Pack>(`/projects/${projectId}/handovers/${handoverId}/pack`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return (
        <div className="mx-auto max-w-2xl">
          <EmptyState
            title="No pack yet"
            action={
              <Link href={back} className="text-accent hover:underline">
                Back to the handover
              </Link>
            }
          >
            {e.message}
          </EmptyState>
        </div>
      );
    }
    if (e instanceof ApiError && e.status === 422) notFound();
    throw e;
  }
  const ids = { projectId, handoverId };
  const reading = pack.can_acknowledge;
  const read = pack.sections.filter((s) => s.acknowledged_at).length;
  const exportUrl = `/projects/${projectId}/handovers/${handoverId}/export`;
  const sections = pack.sections.filter((s) => s.key !== "plan");
  const planSection = pack.sections.find((s) => s.key === "plan");

  return (
    <div>
      <div className="print:hidden">
        <BackLink href={back}>{pack.title}</BackLink>
      </div>

      {!pack.is_published && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-accent/40 bg-accent-soft/40 px-4 py-3 print:hidden">
          <p className="text-[14px] text-ink">
            <span className="font-semibold">Preview of version {pack.version}.</span> {pack.successor.name} can&apos;t
            see it until it&apos;s published
            {pack.published_version > 0 && ` (version ${pack.published_version} is live)`}.
          </p>
          {pack.can_publish && (
            <PublishButton projectId={projectId} handoverId={handoverId} version={pack.version} to={pack.successor.name} />
          )}
        </div>
      )}

      <div className="mt-6 grid gap-10 lg:grid-cols-[14rem_1fr] lg:gap-14">
        {/* --- contents: stays in view while reading ---------------------------------------- */}
        <aside className="hidden self-start print:hidden lg:sticky lg:top-24 lg:block">
          <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Contents</p>
          <ol className="mt-3 grid gap-0.5 text-[14px]">
            <li>
              <a href="#start" className="block rounded-md px-2.5 py-1.5 text-ink-muted hover:bg-paper-sunk hover:text-ink">
                Start here
              </a>
            </li>
            {pack.sections.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.key}`}
                  className="flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-ink-muted hover:bg-paper-sunk hover:text-ink"
                >
                  <span className="truncate">{s.title}</span>
                  {s.acknowledged_at ? (
                    <span className="text-[var(--grade-verified)]" aria-label="read">
                      ✓
                    </span>
                  ) : (
                    s.blocks.length > 0 && <span className="tabular-nums text-[12px] text-ink-faint">{s.blocks.length}</span>
                  )}
                </a>
              </li>
            ))}
          </ol>
          {reading && (
            <div className="mt-5 px-2.5">
              <p className="mb-1.5 text-[12px] text-ink-muted">
                {read} of {pack.sections.length} sections read
              </p>
              <Progress size="sm" value={read / Math.max(pack.sections.length, 1)} label="Sections read" />
            </div>
          )}
        </aside>

        <article className="min-w-0 max-w-3xl">
          {/* --- title ------------------------------------------------------------------------ */}
          <header>
            <p className="text-[13px] font-medium text-ink-faint">Handover pack · version {pack.version}</p>
            <h1 className="mt-1 font-display text-[2.6rem] leading-[1.05] tracking-[-0.04em] text-ink">
              For {pack.successor.name}
            </h1>
            <p className="mt-3 text-[16px] leading-relaxed text-ink-muted">
              Everything {pack.leaver.name} knows about this work, checked by {pack.approver.name}. Each statement links to
              the message, ticket or document it came from.
            </p>
            <div className="mt-5 flex flex-wrap gap-2 print:hidden">
              <a href={`${exportUrl}?format=md`} className={buttonClass("secondary", "sm")}>
                <Download className="size-3.5" aria-hidden="true" />
                Markdown
              </a>
              {pack.plan.length > 0 && (
                <a href={`${exportUrl}?format=ics`} className={buttonClass("secondary", "sm")}>
                  <CalendarDays className="size-3.5" aria-hidden="true" />
                  Add the plan to my calendar
                </a>
              )}
              <PrintButton />
            </div>
          </header>

          <StartHere pack={pack} />

          {pack.flags.length > 0 && !reading && (
            <section className="mt-8 rounded-lg border border-[var(--grade-conflicting)]/30 bg-[var(--grade-conflicting-bg)] px-5 py-4 print:hidden">
              <h2 className="flex items-center gap-2 text-[14px] font-semibold text-[var(--grade-conflicting)]">
                <Flag className="size-4" aria-hidden="true" />
                {pack.successor.name} flagged {plural(pack.flags.length, "item")} as possibly wrong
              </h2>
              <ul className="mt-2 grid gap-2 text-[14px]">
                {pack.flags.map((f) => (
                  <li key={f.id}>
                    <span className="text-ink-muted">“{f.statement}”</span> — {f.note}
                    <span className="text-[12px] text-ink-faint"> · {formatDateTime(f.created_at)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {sections.map((s, i) => (
            <Section key={s.id} n={i + 1} section={s} ids={ids} reading={reading} />
          ))}
          {planSection && <Plan section={planSection} pack={pack} ids={ids} reading={reading} n={sections.length + 1} />}
        </article>
      </div>
    </div>
  );
}

// --- start here -----------------------------------------------------------------------

function Person({ role, user, note }: { role: string; user: User; note?: string }) {
  return (
    <div className="flex items-center gap-3">
      <Avatar name={user.name} src={user.avatar_url} size={34} />
      <div className="min-w-0">
        <p className="text-[12px] text-ink-faint">{role}</p>
        <p className="truncate text-[14px] font-semibold text-ink">{user.name}</p>
        {note && <p className="text-[12px] text-ink-muted">{note}</p>}
      </div>
    </div>
  );
}

/** The gist in thirty seconds: who, how much, what matters most, and what to do first. */
function StartHere({ pack }: { pack: Pack }) {
  const count = (key: string) => pack.sections.find((s) => s.key === key)?.blocks.length ?? 0;
  const risks = pack.sections.find((s) => s.key === "risks")?.blocks.slice(0, 3) ?? [];
  const firstWeek = pack.plan.filter((i) => i.week === 1).slice(0, 4);
  return (
    <section id="start" aria-label="Start here" className="mt-8 scroll-mt-24 rounded-xl border border-rule bg-paper-raised p-6 shadow-card">
      <div className="grid gap-4 sm:grid-cols-3">
        <Person role="Handing over" user={pack.leaver} note={pack.leaver_last_day ? `Last day ${formatDate(pack.leaver_last_day)}` : undefined} />
        <Person role="Taking over" user={pack.successor} />
        <Person role="Checked by" user={pack.approver} />
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-4 border-y border-rule py-4 sm:grid-cols-4">
        {(
          [
            ["Decisions", count("decisions")],
            ["Risks and blockers", count("risks")],
            ["Open questions", count("open")],
            ["Tasks in the plan", pack.plan.length],
          ] as const
        ).map(([label, n]) => (
          <div key={label}>
            <dd className="font-display text-[1.6rem] leading-none tabular-nums text-ink">{n}</dd>
            <dt className="mt-1 text-[12px] text-ink-faint">{label}</dt>
          </div>
        ))}
      </dl>

      <div className="mt-5 grid gap-6 md:grid-cols-2">
        {risks.length > 0 && (
          <div>
            <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Watch out for</h2>
            <ul className="mt-2 grid gap-2">
              {risks.map((b) => (
                <li key={b.claim_id} className="flex gap-2 text-[14px] leading-snug text-ink">
                  <span aria-hidden="true" className="mt-1.5 size-1.5 shrink-0 rounded-full bg-[var(--grade-conflicting)]" />
                  <RedactedText text={b.statement} />
                </li>
              ))}
            </ul>
            <a href="#risks" className="mt-2 inline-block text-[13px] font-medium text-accent hover:underline print:hidden">
              All risks →
            </a>
          </div>
        )}
        {firstWeek.length > 0 && (
          <div>
            <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Your first week</h2>
            <ul className="mt-2 grid gap-2">
              {firstWeek.map((i) => (
                <li key={i.id} className="flex gap-2 text-[14px] leading-snug text-ink">
                  <span aria-hidden="true" className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" />
                  {i.title}
                </li>
              ))}
            </ul>
            <a href="#plan" className="mt-2 inline-block text-[13px] font-medium text-accent hover:underline print:hidden">
              The 30-day plan →
            </a>
          </div>
        )}
      </div>
    </section>
  );
}

// --- sections ----------------------------------------------------------------------------

function SectionHeading({ n, title, count }: { n: number; title: string; count?: number }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-t border-ink/80 pt-4">
      <h2 className="font-display text-[1.6rem] leading-snug tracking-[-0.03em] text-ink">
        <span className="mr-2 text-ink-faint tabular-nums">{String(n).padStart(2, "0")}</span>
        {title}
      </h2>
      {count !== undefined && count > 0 && <span className="shrink-0 text-[13px] text-ink-faint">{plural(count, "item")}</span>}
    </div>
  );
}

function Section({ n, section: s, ids, reading }: { n: number; section: PackSection; ids: Ids; reading: boolean }) {
  const [one, many] = NOUN[s.key] ?? ["item", "items"];
  return (
    <section id={s.key} className="mt-14 scroll-mt-24 break-inside-avoid-page">
      <SectionHeading n={n} title={s.title} count={s.blocks.length} />
      {s.intro && <p className="mt-3 text-[16px] leading-relaxed text-ink">{s.intro}</p>}

      {s.blocks.length > 0 && (
        <div className="mt-5">
          <ShowMore initial={FIRST} noun={s.blocks.length === 1 ? one : many}>
            {s.blocks.map((b) => (
              <Item key={b.claim_id} block={b} ids={ids} reading={reading} />
            ))}
          </ShowMore>
        </div>
      )}

      {s.withheld.count ? (
        <p className="mt-4 flex gap-2 rounded-lg bg-paper-sunk px-4 py-3 text-[14px] text-ink-muted">
          <Lock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>
            {plural(s.withheld.count, "item")} held back here ({(s.withheld.labels ?? []).map((l) => WHY[l] ?? l).join("; ")}).
            Ask {s.withheld.ask} if you need {s.withheld.count === 1 ? "it" : "them"}.
          </span>
        </p>
      ) : null}

      {reading && (
        <div className="mt-5">
          <Acknowledge {...ids} sectionId={s.id} done={!!s.acknowledged_at} />
        </div>
      )}
    </section>
  );
}

/** One line per item; the reasons and the sources open underneath. */
function Item({ block: b, ids, reading }: { block: PackBlock; ids: Ids; reading: boolean }) {
  const facts = [b.owner && `Owner ${b.owner}`, b.due && `due ${formatDate(b.due)}`, b.since && `since ${formatDate(b.since)}`]
    .filter(Boolean)
    .join(" · ");
  return (
    <details className="group py-3.5">
      <summary className="flex cursor-pointer items-start gap-3 rounded-md">
        <span
          aria-hidden="true"
          title={GRADE_LABEL[b.grade][0]}
          className="mt-[7px] size-2 shrink-0 rounded-full"
          style={{ background: `var(--grade-${b.grade})` }}
        />
        <span className="min-w-0 flex-1">
          <span className="block text-[15px] leading-snug text-ink group-hover:text-accent">
            <RedactedText text={b.statement} />
          </span>
          {facts && <span className="mt-1 block text-[12px] text-ink-faint">{facts}</span>}
        </span>
        <ChevronRight
          className="mt-1 size-4 shrink-0 text-ink-faint transition-transform duration-200 group-open:rotate-90 print:hidden"
          aria-hidden="true"
        />
      </summary>

      <div className="ml-5 mt-3 grid gap-3 border-l-2 border-rule pl-4">
        <p className="text-[12px] text-ink-faint">
          <span className="font-semibold" style={{ color: `var(--grade-${b.grade})` }}>
            {GRADE_LABEL[b.grade][0]}
          </span>
          {" · "}
          {b.grade_reason || GRADE_LABEL[b.grade][1]}
        </p>
        {b.rationale && (
          <p className="text-[14px] leading-relaxed text-ink">
            <span className="font-semibold">Why: </span>
            <RedactedText text={b.rationale} />
          </p>
        )}
        {b.history.length > 0 && (
          <div className="text-[13px] text-ink-muted">
            <p className="font-semibold text-ink">Before this changed</p>
            {b.history.map((h, i) => (
              <p key={i}>
                {h.statement}
                {h.until && <span className="text-ink-faint"> (until {formatDate(h.until)})</span>}
              </p>
            ))}
          </div>
        )}
        {b.cites.map((c) => (
          <figure key={c.evidence_id} className="rounded-lg bg-paper-raised px-4 py-3">
            <blockquote className="text-[14px] leading-relaxed text-ink">
              “<RedactedText text={c.quote} />”
            </blockquote>
            <figcaption className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-ink-faint">
              <KindTag>{EVIDENCE_KIND_LABEL[c.kind] ?? c.kind}</KindTag>
              <span>{[c.source, c.author, c.date && formatDate(c.date)].filter(Boolean).join(" · ")}</span>
              {c.permalink && (
                <a href={c.permalink} target="_blank" rel="noreferrer noopener" className="hover:text-ink print:hidden">
                  Original ↗
                </a>
              )}
            </figcaption>
          </figure>
        ))}
        {reading && <FlagClaim {...ids} claimId={b.claim_id} />}
      </div>
    </details>
  );
}

// --- the plan --------------------------------------------------------------------------

function Plan({ section, pack, ids, reading, n }: { section: PackSection; pack: Pack; ids: Ids; reading: boolean; n: number }) {
  const weeks = [1, 2, 3, 4].map((w) => ({ week: w, items: pack.plan.filter((i) => i.week === w) })).filter((w) => w.items.length);
  const done = pack.plan.filter((i) => i.done).length;
  return (
    <section id="plan" className="mt-14 scroll-mt-24">
      <SectionHeading n={n} title={section.title} />
      {section.intro && <p className="mt-3 text-[16px] leading-relaxed text-ink">{section.intro}</p>}
      {pack.plan.length === 0 ? (
        <p className="mt-3 text-ink-muted">No tasks were planned.</p>
      ) : (
        <>
          <div className="mt-4 flex items-center gap-3">
            <div className="w-40">
              <Progress size="sm" value={done / pack.plan.length} label="Tasks done" tone={done === pack.plan.length ? "success" : "accent"} />
            </div>
            <span className="text-[13px] text-ink-muted">
              {done} of {plural(pack.plan.length, "task")} done
            </span>
          </div>
          <div className="mt-5 grid gap-6 sm:grid-cols-2">
            {weeks.map((w) => (
              <div key={w.week} className="rounded-xl border border-rule bg-paper-raised p-4 shadow-card break-inside-avoid">
                <h3 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Week {w.week}</h3>
                <ul className="mt-3 grid gap-3">
                  {w.items.map((i) => (
                    <li key={i.id} className={cx("flex gap-3", i.done && "opacity-60")}>
                      <PlanCheck {...ids} itemId={i.id} done={i.done} editable={reading} />
                      <div className="min-w-0">
                        <p className={cx("text-[14px] font-medium leading-snug text-ink", i.done && "line-through")}>{i.title}</p>
                        {i.detail && <p className="mt-0.5 text-[13px] leading-relaxed text-ink-muted">{i.detail}</p>}
                        {(i.owner_name || i.due_date) && (
                          <p className="mt-1 text-[12px] text-ink-faint">
                            {[i.owner_name && `With ${i.owner_name}`, i.due_date && `due ${formatDate(i.due_date)}`]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </>
      )}
      {reading && (
        <div className="mt-5">
          <Acknowledge {...ids} sectionId={section.id} done={!!section.acknowledged_at} />
        </div>
      )}
    </section>
  );
}
