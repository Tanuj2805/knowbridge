import { plural } from "@/lib/format";
import type { HandoverDetail } from "@/lib/types";
import { StatusMark } from "./agent-pipeline";
import { cx } from "./ui";

type Stage = { label: string; note: string; state: "done" | "running" | "current" | "waiting" };

/** Where a handover stands, from set-up to the successor having read it. */
export function stagesOf(h: HandoverDetail): Stage[] {
  const interviewDone = h.questions_total > 0 && h.questions_open === 0;
  const interviewing = h.preparing || h.questions_open > 0;
  const written = h.latest_version > 0;
  const published = h.published_version > 0;
  const read = h.status === "acknowledged";
  const step = (done: boolean, running: boolean, current: boolean): Stage["state"] =>
    done ? "done" : running ? "running" : current ? "current" : "waiting";
  return [
    { label: "Set up", note: `${h.leaver.name.split(" ")[0]} → ${h.successor.name.split(" ")[0]}`, state: "done" },
    {
      label: "Gap Interview",
      note: h.preparing
        ? "Writing questions…"
        : h.questions_total
          ? `${h.questions_answered} of ${h.questions_total} answered`
          : "Not started",
      state: step(interviewDone, h.preparing, interviewing || (!written && h.questions_total === 0)),
    },
    {
      label: "Review claims",
      // Claims rebuilt after a pack was written start unapproved again; the pack keeps what it was written from.
      note: h.approved_claims
        ? `${h.approved_claims} approved`
        : written
          ? "Rebuilt since the pack: review again"
          : "Nothing approved yet",
      state: step(written, false, !written && (interviewDone || h.approved_claims > 0)),
    },
    {
      label: "Write the pack",
      note: h.composing ? "The Composer is writing…" : written ? `Version ${h.latest_version}` : "Not written yet",
      state: step(written && !h.composing, h.composing, false),
    },
    {
      label: "Publish",
      note: published ? `Version ${h.published_version} is live` : written ? "Ready to publish" : "",
      state: step(published && h.published_version === h.latest_version, false, written && !h.composing),
    },
    {
      label: `${h.successor.name.split(" ")[0]} reads it`,
      note: read ? "Every section read" : published ? "Waiting for them" : "",
      state: step(read, false, published),
    },
  ];
}

export function HandoverStages({ handover }: { handover: HandoverDetail }) {
  const stages = stagesOf(handover);
  const doneCount = stages.filter((s) => s.state === "done").length;
  return (
    <nav aria-label="Handover progress">
      <p className="sr-only">
        {doneCount} of {plural(stages.length, "stage")} done.
      </p>
      <ol className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6 lg:gap-0">
        {stages.map((s, i) => (
          <li key={s.label} className="relative flex gap-3 lg:flex-col lg:gap-2 lg:pr-4">
            {i < stages.length - 1 && (
              <span
                aria-hidden="true"
                className={cx(
                  "absolute left-7 right-1 top-[10px] hidden h-px origin-left lg:block",
                  s.state === "done" ? "animate-grow bg-accent" : "bg-rule-strong",
                )}
              />
            )}
            <span className="relative z-[1] self-start bg-paper lg:pr-1">
              <StatusMark state={s.state} size={20} />
            </span>
            <div className="min-w-0">
              <p className={cx("text-[14px] font-medium", s.state === "waiting" ? "text-ink-faint" : "text-ink")}>{s.label}</p>
              {s.note && (
                <p className={cx("text-[12px] leading-snug", s.state === "current" ? "text-accent" : "text-ink-muted")}>
                  {s.note}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
    </nav>
  );
}
