import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { cx } from "./ui";

/** Page numbers to show: all of them when there are few, else the ends and the pages around this one. */
function pages(page: number, count: number): (number | "…")[] {
  if (count <= 7) return Array.from({ length: count }, (_, i) => i + 1);
  const around = [page - 1, page, page + 1].filter((p) => p > 1 && p < count);
  const out: (number | "…")[] = [1];
  if (around[0] > 2) out.push("…");
  out.push(...around);
  if (around[around.length - 1] < count - 1) out.push("…");
  out.push(count);
  return out;
}

/**
 * "Showing 6–10 of 23 handovers", with Previous / Next and page numbers. Links keep the reader where
 * they are on the page (no jump to the top), so paging through one list doesn't lose your place.
 */
export function Pagination({
  page,
  pageSize,
  total,
  href,
  noun = "item",
  nouns,
}: {
  page: number;
  pageSize: number;
  total: number;
  href: (page: number) => string;
  noun?: string;
  nouns?: string;
}) {
  const count = Math.max(1, Math.ceil(total / pageSize));
  if (total === 0) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(total, page * pageSize);
  const step = "inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-md px-2 text-[13px] font-medium";

  return (
    <nav aria-label="Pages" className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <p className="text-[13px] text-ink-faint tabular-nums">
        {total <= pageSize
          ? `${total} ${total === 1 ? noun : (nouns ?? `${noun}s`)}`
          : `Showing ${first}–${last} of ${total} ${nouns ?? `${noun}s`}`}
      </p>
      {count > 1 && (
        <div className="flex items-center gap-1">
          {page > 1 ? (
            <Link href={href(page - 1)} scroll={false} className={cx(step, "text-ink-muted hover:bg-paper-sunk hover:text-ink")}>
              <ChevronLeft className="size-4" aria-hidden="true" />
              <span className="hidden sm:inline">Previous</span>
            </Link>
          ) : (
            <span className={cx(step, "text-ink-faint/50")} aria-disabled="true">
              <ChevronLeft className="size-4" aria-hidden="true" />
              <span className="hidden sm:inline">Previous</span>
            </span>
          )}
          {pages(page, count).map((p, i) =>
            p === "…" ? (
              <span key={`gap-${i}`} className="px-1 text-[13px] text-ink-faint">
                …
              </span>
            ) : (
              <Link
                key={p}
                href={href(p)}
                scroll={false}
                aria-current={p === page ? "page" : undefined}
                className={cx(
                  step,
                  "tabular-nums",
                  p === page ? "bg-btn text-on-btn" : "text-ink-muted hover:bg-paper-sunk hover:text-ink",
                )}
              >
                {p}
              </Link>
            ),
          )}
          {page < count ? (
            <Link href={href(page + 1)} scroll={false} className={cx(step, "text-ink-muted hover:bg-paper-sunk hover:text-ink")}>
              <span className="hidden sm:inline">Next</span>
              <ChevronRight className="size-4" aria-hidden="true" />
            </Link>
          ) : (
            <span className={cx(step, "text-ink-faint/50")} aria-disabled="true">
              <span className="hidden sm:inline">Next</span>
              <ChevronRight className="size-4" aria-hidden="true" />
            </span>
          )}
        </div>
      )}
    </nav>
  );
}
