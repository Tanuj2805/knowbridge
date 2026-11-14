import { RefreshCw } from "lucide-react";
import { formatDate } from "@/lib/format";
import { DRIFT_LABEL, GRADE_LABEL, type Drift, type DriftOutcome, type Grade } from "@/lib/types";
import { RedactedText } from "./evidence-bits";

type Part = { text: string; changed: boolean };

/** Word-level difference between two short passages: what was taken out of `a`, and what `b` added. */
export function wordDiff(a: string, b: string): { before: Part[]; after: Part[] } {
  const x = a.split(/(\s+)/);
  const y = b.split(/(\s+)/);
  // longest common subsequence over words (passages are a few hundred characters)
  const n = x.length;
  const m = y.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const before: Part[] = [];
  const after: Part[] = [];
  const push = (list: Part[], text: string, changed: boolean) => {
    const last = list[list.length - 1];
    // spaces join whatever is next to them, so a changed phrase is one highlight
    if (last && (last.changed === changed || /^\s+$/.test(text))) last.text += text;
    else list.push({ text, changed });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) {
      push(before, x[i], false);
      push(after, y[j], false);
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      push(before, x[i++], true);
    } else {
      push(after, y[j++], true);
    }
  }
  while (i < n) push(before, x[i++], true);
  while (j < m) push(after, y[j++], true);
  return { before, after };
}

function Passage({ parts, kind }: { parts: Part[]; kind: "before" | "after" }) {
  return (
    <p className="text-[14px] leading-relaxed text-ink">
      {parts.map((p, i) =>
        p.changed && p.text.trim() ? (
          kind === "before" ? (
            <del key={i} className="rounded-sm bg-paper-sunk px-0.5 text-ink-muted decoration-ink-faint">
              <RedactedText text={p.text} />
            </del>
          ) : (
            <ins key={i} className="rounded-sm bg-accent-soft px-0.5 font-medium text-ink no-underline">
              <RedactedText text={p.text} />
            </ins>
          )
        ) : (
          <RedactedText key={i} text={p.text} />
        ),
      )}
    </p>
  );
}

/** The passage before and after the change at the source, changed words marked. */
export function BeforeAfter({ before, after }: { before: string; after: string }) {
  const d = wordDiff(before, after);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="min-w-0 border-l-2 border-rule-strong pl-3">
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Before</p>
        <Passage parts={d.before} kind="before" />
      </div>
      <div className="min-w-0 border-l-2 border-accent pl-3">
        <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-accent">Now</p>
        {after ? (
          <Passage parts={d.after} kind="after" />
        ) : (
          <p className="text-[14px] italic text-ink-muted">Deleted at the source.</p>
        )}
      </div>
    </div>
  );
}

/** How a change affected the claim, coloured by how much it matters. */
export function DriftLabel({ outcome }: { outcome: DriftOutcome }) {
  const serious = outcome === "contradicts" || outcome === "unrelated" || outcome === "removed";
  return (
    <span
      title={DRIFT_LABEL[outcome][1]}
      className="inline-flex items-center gap-1.5 text-[12px] font-semibold"
      style={{ color: serious ? "var(--grade-conflicting)" : "var(--accent)" }}
    >
      <RefreshCw className={outcome === "pending" ? "size-3.5 animate-spin [animation-duration:2s]" : "size-3.5"} aria-hidden="true" />
      {DRIFT_LABEL[outcome][0]}
    </span>
  );
}

/** The full story of one change, for a claim's details. */
export function DriftStory({ d }: { d: Drift }) {
  const moved = d.grade_before && d.grade_after && d.grade_before !== d.grade_after;
  return (
    <div className="grid gap-3">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-ink-muted">
        <DriftLabel outcome={d.outcome} />
        <span>
          {d.change === "removed" ? "Deleted from" : d.change === "restored" ? "Back in" : "Edited in"}{" "}
          <span className="font-medium text-ink">{d.source_name || "its source"}</span>
          {d.evidence_title && !d.source_name.includes(d.evidence_title) && <> · {d.evidence_title}</>} · noticed{" "}
          {formatDate(d.detected_at)}
          {d.simulated && " · a simulated change (demo)"}
        </span>
      </p>
      <BeforeAfter before={d.before} after={d.after} />
      {(d.note || moved || d.reopened) && (
        <p className="text-[13px] leading-relaxed text-ink">
          {d.note && <>The Skeptic: {d.note} </>}
          {moved && (
            <>
              Grade {GRADE_LABEL[d.grade_before as Grade][0]} → {GRADE_LABEL[d.grade_after as Grade][0]}.{" "}
            </>
          )}
          {d.reopened && "It went back to review, so it stays out of the next pack until someone approves it again."}
        </p>
      )}
      {d.resolved_by_name && (
        <p className="text-[12px] text-ink-faint">
          Reviewed by {d.resolved_by_name}
          {d.resolved_at && ` on ${formatDate(d.resolved_at)}`}.
        </p>
      )}
    </div>
  );
}
