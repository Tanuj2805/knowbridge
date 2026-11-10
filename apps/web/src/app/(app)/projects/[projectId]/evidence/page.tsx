import {
  Activity,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Code,
  FileCode,
  FileSearch,
  FileText,
  GitCommitHorizontal,
  GitPullRequest,
  Lock,
  MessageCircleQuestion,
  MessageSquare,
  MessageSquareText,
  Mic,
  Search,
  SquareKanban,
  StickyNote,
  UserCheck,
  X,
  type LucideIcon,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { RedactedText, SensitivityTag } from "@/components/evidence-bits";
import { FilterMenu } from "@/components/filter-menu";
import { Pagination } from "@/components/pagination";
import { Avatar, EmptyState, Input, PageHeader, Tag } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, plural } from "@/lib/format";
import { EVIDENCE_KIND_LABEL, type EvidenceHit, type EvidencePage, type Source } from "@/lib/types";

export const metadata: Metadata = { title: "Evidence" };

const PAGE = 30;

const KIND_ICON: Record<string, LucideIcon> = {
  commit: GitCommitHorizontal,
  pull_request: GitPullRequest,
  pr_comment: MessageSquare,
  pr_review: UserCheck,
  code_ownership: Code,
  issue: CircleDot,
  issue_comment: MessageSquare,
  file: FileCode,
  check: Activity,
  doc_section: FileText,
  card: SquareKanban,
  card_comment: StickyNote,
  message: MessageSquareText,
  meeting_segment: Mic,
  interview_answer: MessageCircleQuestion,
};

/** Kinds whose "title" is only where it was said (a channel, a meeting): the words themselves lead instead. */
const SPOKEN = new Set(["message", "meeting_segment"]);

const LABELS = [
  ["team", "Team"],
  ["restricted", "Restricted"],
  ["confidential", "Confidential"],
] as const;

const MONTH = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric", timeZone: "Asia/Kolkata" });

export default async function EvidencePageView({
  params,
  searchParams,
}: PageProps<"/projects/[projectId]/evidence">) {
  const { projectId } = await params;
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const q = one("q");
  const source = one("source");
  const kind = one("kind");
  const label = one("label");
  const offset = Math.max(0, Number(one("offset")) || 0);

  const query = new URLSearchParams();
  if (q) query.set("q", q);
  if (source) query.set("source_id", source);
  if (kind) query.set("kind", kind);
  if (label) query.set("sensitivity", label);
  query.set("offset", String(offset));
  query.set("limit", String(PAGE));

  const [page, sources] = await Promise.all([
    api<EvidencePage>(`/projects/${projectId}/evidence?${query}`),
    api<Source[]>(`/projects/${projectId}/sources`),
  ]);
  const sourceName = new Map(sources.map((s) => [s.id, s.name]));
  const base = `/projects/${projectId}/evidence`;

  /** This page with some filters changed and the rest kept; any change goes back to the first page. */
  const link = (changes: Record<string, string | number | null>) => {
    const next: Record<string, string | number | null> = { q, source, kind, label, offset: null, ...changes };
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) if (v) p.set(k, String(v));
    return `${base}${p.size ? `?${p}` : ""}`;
  };
  const chips = [
    q && { key: "q", text: `“${q}”` },
    source && { key: "source", text: sourceName.get(source) ?? "One source" },
    kind && { key: "kind", text: EVIDENCE_KIND_LABEL[kind] ?? kind },
    label && { key: "label", text: LABELS.find(([k]) => k === label)?.[1] ?? label },
  ].filter(Boolean) as { key: string; text: string }[];

  return (
    <div>
      <PageHeader title="Evidence">
        Everything read from this project&apos;s sources, after masking. Search in plain words, or narrow it down by
        source, kind and label.
      </PageHeader>

      {/* --- find and filter ---------------------------------------------------------------- */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <form method="get" action={base} className="relative flex-1">
          {source && <input type="hidden" name="source" value={source} />}
          {kind && <input type="hidden" name="kind" value={kind} />}
          {label && <input type="hidden" name="label" value={label} />}
          <label htmlFor="q" className="sr-only">
            Search evidence
          </label>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" aria-hidden="true" />
          <Input id="q" name="q" defaultValue={q} placeholder="Ask in plain words: why did we stop using webhooks?" className="pl-9" />
        </form>
        <div className="flex flex-wrap gap-2">
          <FilterMenu
            label="Source"
            options={[
              { label: "All", href: link({ source: null }), current: !source },
              ...sources.map((s) => ({
                label: s.name,
                href: link({ source: s.id }),
                current: source === s.id,
                count: s.item_count,
              })),
            ]}
          />
          <FilterMenu
            label="Kind"
            options={[
              { label: "Any", href: link({ kind: null }), current: !kind },
              ...Object.entries(EVIDENCE_KIND_LABEL).map(([k, v]) => ({
                label: v,
                href: link({ kind: k }),
                current: kind === k,
              })),
            ]}
          />
          <FilterMenu
            label="Label"
            options={[
              { label: "Any", href: link({ label: null }), current: !label },
              ...LABELS.map(([k, v]) => ({ label: v, href: link({ label: k }), current: label === k })),
            ]}
          />
        </div>
      </div>

      {/* what's being shown, and what's narrowing it */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-3">
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span className="font-medium text-ink">
            {page.total === null
              ? `Best ${plural(page.items.length, "match", "matches")}`
              : plural(page.total, "item")}
          </span>
          {chips.map((c) => (
            <Link
              key={c.key}
              href={link({ [c.key]: null })}
              scroll={false}
              className="group inline-flex items-center gap-1 rounded-full bg-accent-soft py-0.5 pl-2.5 pr-1.5 font-medium text-accent"
              aria-label={`Remove the filter ${c.text}`}
            >
              {c.text}
              <X className="size-3.5 opacity-70 group-hover:opacity-100" aria-hidden="true" />
            </Link>
          ))}
          {chips.length > 1 && (
            <Link href={base} className="text-ink-muted hover:text-ink hover:underline">
              Clear all
            </Link>
          )}
        </div>
        {page.hidden > 0 && (
          <p
            className="inline-flex items-center gap-1.5 text-[12px] text-ink-faint"
            title="These exist but you aren't allowed to see them. Nothing is hidden silently."
          >
            <Lock className="size-3.5" aria-hidden="true" />
            {plural(page.hidden, "item")} outside your access
          </p>
        )}
      </div>

      {/* --- the items ---------------------------------------------------------------------- */}
      {page.items.length === 0 ? (
        <div className="mt-6">
          <EmptyState icon={<FileSearch className="size-6" />} title={q ? "Nothing matched" : "No evidence here"}>
            {q
              ? "Try fewer or different words. Search looks at titles and text in everything you're allowed to see."
              : chips.length
                ? "Nothing matches these filters."
                : "Connect a source and its items will appear here once they've been read."}
          </EmptyState>
        </div>
      ) : page.total === null ? (
        <SearchResults items={page.items} base={base} sourceName={sourceName} />
      ) : (
        <>
          <ByMonth items={page.items} base={base} sourceName={sourceName} />
          <Pagination
            page={Math.floor(offset / PAGE) + 1}
            pageSize={PAGE}
            total={page.total}
            href={(n) => link({ offset: n > 1 ? (n - 1) * PAGE : null })}
            noun="item"
          />
        </>
      )}
    </div>
  );
}

type ListProps = { items: EvidenceHit[]; base: string; sourceName: Map<string, string> };

/** Browsing: items under a heading for each month, newest first. */
function ByMonth({ items, base, sourceName }: ListProps) {
  const groups: { month: string; items: EvidenceHit[] }[] = [];
  for (const e of items) {
    const month = e.occurred_at ? MONTH.format(new Date(e.occurred_at)) : "Undated";
    const last = groups[groups.length - 1];
    if (last?.month === month) last.items.push(e);
    else groups.push({ month, items: [e] });
  }
  return (
    <div className="mt-6 grid gap-8">
      {groups.map((g) => (
        <section key={g.month} aria-label={g.month}>
          <h2 className="mb-3 flex items-center gap-3 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-faint">
            {g.month}
            <span className="h-px flex-1 bg-rule" aria-hidden="true" />
            <span className="font-normal normal-case tracking-normal">{plural(g.items.length, "item")}</span>
          </h2>
          <ItemList items={g.items} base={base} sourceName={sourceName} />
        </section>
      ))}
    </div>
  );
}

/** Searching: strong matches first, weaker ones folded away so nothing looks equally certain. */
function SearchResults({ items, base, sourceName }: ListProps) {
  const strong = items.filter((e) => e.strength === "strong");
  const possible = items.filter((e) => e.strength !== "strong");
  return (
    <div className="mt-6 grid gap-8">
      {strong.length > 0 && (
        <section aria-label="Best matches">
          <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Best matches</h2>
          <ItemList items={strong} base={base} sourceName={sourceName} />
        </section>
      )}
      {possible.length > 0 && (
        <details className="group/more" open={strong.length === 0}>
          <summary className="mb-3 inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-semibold uppercase tracking-[0.08em] text-ink-faint hover:text-ink">
            <ChevronDown className="size-4 transition-transform group-open/more:rotate-180" aria-hidden="true" />
            {strong.length === 0 ? "Possible matches" : `${possible.length} more possible matches`}
            <span className="font-normal normal-case tracking-normal">· related, but less certain</span>
          </summary>
          <ItemList items={possible} base={base} sourceName={sourceName} />
        </details>
      )}
    </div>
  );
}

function ItemList({ items, base, sourceName }: ListProps) {
  return (
    <ol className="stagger grid gap-3">
      {items.map((e) => (
        <Item key={e.id} e={e} base={base} source={sourceName.get(e.source_id)} />
      ))}
    </ol>
  );
}

function Item({ e, base, source }: { e: EvidenceHit; base: string; source?: string }) {
  const Icon = KIND_ICON[e.kind] ?? FileText;
  const spoken = SPOKEN.has(e.kind);
  const heading = spoken ? e.snippet : e.title || e.locator;
  const body = spoken ? "" : e.snippet.trim() === (e.title || "").trim() ? "" : e.snippet;
  const where = [source, spoken ? e.title : null].filter(Boolean).join(" · ");

  return (
    <li className="rounded-xl border border-rule bg-paper-raised shadow-card transition-[border-color,box-shadow] duration-200 hover:border-rule-strong hover:shadow-lift">
      <Link href={`${base}/${e.id}`} className="group flex gap-4 p-4 sm:p-5">
        <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Icon className="size-[18px]" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          {/* what it is and where it came from */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
            <span className="font-semibold text-ink-muted">{EVIDENCE_KIND_LABEL[e.kind] ?? e.kind}</span>
            {where && <span className="truncate text-ink-faint">· {where}</span>}
            <SensitivityTag value={e.sensitivity} quiet />
            {e.language === "hi-en" && <Tag>Hinglish</Tag>}
            {e.removed && <Tag tone="danger">Gone from source</Tag>}
          </div>

          {/* the words */}
          <p
            className={
              spoken
                ? "mt-1.5 line-clamp-3 text-[15px] leading-relaxed text-ink"
                : "mt-1.5 line-clamp-2 text-[15px] font-semibold leading-snug text-ink group-hover:text-accent"
            }
          >
            <RedactedText text={heading} />
          </p>
          {body && (
            <p className="mt-1.5 line-clamp-2 whitespace-pre-line text-[14px] leading-relaxed text-ink-muted">
              <RedactedText text={body} />
            </p>
          )}

          {/* who and when */}
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-faint">
            {e.author && (
              <span className="inline-flex items-center gap-1.5 font-medium text-ink-muted">
                <Avatar name={e.author} size={20} />
                {e.author}
              </span>
            )}
            {e.occurred_at && <span>{formatDate(e.occurred_at)}</span>}
            {!spoken && e.locator && e.locator !== e.title && <span className="truncate">{e.locator}</span>}
          </div>
        </div>
        <ChevronRight
          className="mt-3 hidden size-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent sm:block"
          aria-hidden="true"
        />
      </Link>

      {e.related && e.related.length > 0 && (
        <details className="group/rel border-t border-rule px-5 py-3">
          <summary className="inline-flex cursor-pointer items-center gap-1.5 text-[13px] font-medium text-ink-muted hover:text-ink">
            <ChevronDown className="size-3.5 transition-transform group-open/rel:rotate-180" aria-hidden="true" />
            {e.related.length} more matching {e.related.length === 1 ? "item" : "items"} in this{" "}
            {e.kind === "meeting_segment"
              ? "meeting"
              : e.kind === "pull_request" || e.kind.startsWith("pr_")
                ? "PR"
                : e.kind === "issue" || e.kind === "issue_comment"
                  ? "issue"
                  : "card"}
          </summary>
          <ul className="mt-2 grid gap-1">
            {e.related.map((r) => (
              <li key={r.id}>
                <Link href={`${base}/${r.id}`} className="group/r block rounded-md px-3 py-2 transition-colors hover:bg-paper-sunk">
                  <p className="line-clamp-2 text-[13px] text-ink-muted group-hover/r:text-ink">
                    <RedactedText text={r.snippet} />
                  </p>
                  <p className="mt-0.5 text-[12px] text-ink-faint">
                    {[EVIDENCE_KIND_LABEL[r.kind] ?? r.kind, r.author, formatDate(r.occurred_at)].filter(Boolean).join(" · ")}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}
