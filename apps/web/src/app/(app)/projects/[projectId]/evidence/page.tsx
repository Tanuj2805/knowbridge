import type { Metadata } from "next";
import Link from "next/link";
import { KindTag, RedactedText, SensitivityTag } from "@/components/evidence-bits";
import { EmptyState, Input, Select, buttonClass } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDate, plural } from "@/lib/format";
import { EVIDENCE_KIND_LABEL, type EvidenceHit, type EvidencePage, type Source } from "@/lib/types";

export const metadata: Metadata = { title: "Evidence" };

const PAGE = 30;

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
  const link = (extra: Record<string, string | number>) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (source) p.set("source", source);
    if (kind) p.set("kind", kind);
    if (label) p.set("label", label);
    for (const [k, v] of Object.entries(extra)) p.set(k, String(v));
    return `${base}?${p}`;
  };

  return (
    <div>
      <form method="get" action={base} className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto_auto] sm:items-end">
        <div>
          <label htmlFor="q" className="sr-only">
            Search evidence
          </label>
          <Input id="q" name="q" defaultValue={q} placeholder="Search: why did we stop using webhooks?" />
        </div>
        <Select name="source" defaultValue={source} aria-label="Source">
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
        <Select name="kind" defaultValue={kind} aria-label="Kind">
          <option value="">Any kind</option>
          {Object.entries(EVIDENCE_KIND_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        <Select name="label" defaultValue={label} aria-label="Label">
          <option value="">Any label</option>
          <option value="team">Team</option>
          <option value="restricted">Restricted</option>
          <option value="confidential">Confidential</option>
        </Select>
        <button className={buttonClass("primary")}>Search</button>
      </form>

      <div className="mt-6 flex flex-wrap items-baseline justify-between gap-2 text-[13px] text-ink-muted">
        <p>
          {page.total === null
            ? `Best ${plural(page.items.length, "match", "matches")} for “${q}”`
            : `${plural(page.total, "item")}${page.total > PAGE ? `, showing ${offset + 1}–${Math.min(offset + PAGE, page.total)}` : ""}`}
        </p>
        {page.hidden > 0 && (
          <p title="These exist but you aren't allowed to see them. Nothing is hidden silently.">
            {plural(page.hidden, "item")} in this project {page.hidden === 1 ? "is" : "are"} outside your access.
          </p>
        )}
      </div>

      {page.items.length === 0 ? (
        <div className="mt-6">
          <EmptyState title={q ? "Nothing matched" : "No evidence yet"}>
            {q
              ? "Try fewer or different words. Search looks at titles and text in everything you're allowed to see."
              : "Connect a source and its items will appear here once they've been read."}
          </EmptyState>
        </div>
      ) : page.total === null ? (
        <SearchResults items={page.items} base={base} sourceName={sourceName} />
      ) : (
        <ResultList items={page.items} base={base} sourceName={sourceName} />
      )}

      {page.total !== null && page.total > PAGE && (
        <nav className="mt-6 flex justify-between" aria-label="Pages">
          {offset > 0 ? (
            <Link className={buttonClass("secondary", "sm")} href={link({ offset: Math.max(0, offset - PAGE) })}>
              ← Newer
            </Link>
          ) : (
            <span />
          )}
          {offset + PAGE < page.total && (
            <Link className={buttonClass("secondary", "sm")} href={link({ offset: offset + PAGE })}>
              Older →
            </Link>
          )}
        </nav>
      )}
    </div>
  );
}

type RowProps = { items: EvidenceHit[]; base: string; sourceName: Map<string, string> };

/** Search results: strong matches first, weaker ones folded away so nothing looks equally certain. */
function SearchResults({ items, base, sourceName }: RowProps) {
  const strong = items.filter((e) => e.strength === "strong");
  const possible = items.filter((e) => e.strength !== "strong");
  return (
    <div className="mt-3">
      {strong.length > 0 && (
        <section>
          <h2 className="text-[13px] font-medium text-ink-muted mb-1">Best matches</h2>
          <ResultList items={strong} base={base} sourceName={sourceName} />
        </section>
      )}
      {possible.length > 0 && (
        <details className="mt-5 group/more" open={strong.length === 0}>
          <summary className="cursor-pointer text-[13px] font-medium text-ink-muted hover:text-ink">
            {strong.length === 0 ? "Possible matches" : `More possible matches (${possible.length})`}
            <span className="font-normal text-ink-faint"> — related, but less certain</span>
          </summary>
          <div className="mt-1">
            <ResultList items={possible} base={base} sourceName={sourceName} />
          </div>
        </details>
      )}
    </div>
  );
}

function ResultList({ items, base, sourceName }: RowProps) {
  return (
    <ol className="divide-y divide-rule border-y border-rule">
      {items.map((e) => (
        <li key={e.id} className="py-4">
          <Link href={`${base}/${e.id}`} className="group block rounded-sm">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <KindTag>{EVIDENCE_KIND_LABEL[e.kind] ?? e.kind}</KindTag>
              <SensitivityTag value={e.sensitivity} quiet />
              {e.language === "hi-en" && <span className="text-[12px] text-ink-faint">Hinglish</span>}
              {e.removed && <span className="text-[12px] text-danger">gone from source</span>}
            </div>
            <p className="mt-1 font-medium text-[15px] group-hover:text-accent transition-colors">
              <RedactedText text={e.title || e.locator} />
            </p>
            <p className="mt-1 text-[14px] text-ink-muted leading-relaxed line-clamp-3 whitespace-pre-line">
              <RedactedText text={e.snippet} />
            </p>
            <p className="mt-1.5 font-mono text-[12px] text-ink-faint">
              {[e.author, formatDate(e.occurred_at), sourceName.get(e.source_id), e.locator].filter(Boolean).join(" · ")}
            </p>
          </Link>
          {e.related && e.related.length > 0 && (
            <details className="mt-2 ml-3 border-l-2 border-rule pl-3">
              <summary className="cursor-pointer text-[13px] text-ink-muted hover:text-ink">
                {e.related.length} more matching {e.related.length === 1 ? "item" : "items"} in this{" "}
                {e.kind === "meeting_segment"
                  ? "meeting"
                  : e.kind === "pull_request" || e.kind.startsWith("pr_")
                    ? "PR"
                    : e.kind === "issue" || e.kind === "issue_comment"
                      ? "issue"
                      : "card"}
              </summary>
              <ul className="mt-1 grid gap-2">
                {e.related.map((r) => (
                  <li key={r.id}>
                    <Link href={`${base}/${r.id}`} className="group block">
                      <p className="text-[13px] text-ink-muted group-hover:text-ink line-clamp-2">
                        <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-faint mr-2">
                          {EVIDENCE_KIND_LABEL[r.kind] ?? r.kind}
                        </span>
                        <RedactedText text={r.snippet} />
                      </p>
                      <p className="font-mono text-[11px] text-ink-faint">
                        {[r.author, formatDate(r.occurred_at)].filter(Boolean).join(" · ")}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </li>
      ))}
    </ol>
  );
}
