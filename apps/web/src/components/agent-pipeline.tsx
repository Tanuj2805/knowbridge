"use client";

import { useEffect, useState, type ReactNode } from "react";
import { formatDateTime, plural, timeAgo } from "@/lib/format";
import { AGENT_JOB, AGENT_LABEL, type Run, type RunStep } from "@/lib/types";
import { Progress, cx } from "./ui";

/** The order a "build claims" run goes through. Later steps (interview, pack) appear once they've run. */
const ORDER = ["sentinel", "scout", "decision_miner", "ownership_mapper", "risk_detector", "timeline", "skeptic"];
const LATER = ["interviewer", "composer"];

type State = "waiting" | "current" | "running" | "done" | "paused" | "failed";

export function duration(seconds: number): string {
  if (seconds < 1) return "<1 s";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m} min ${s} s` : `${m} min`;
}

/** The current time, ticking while `active`. Null on the server and the first browser render, so
 *  both render the same text (anything that depends on "now" appears right after). */
function useNow(active: boolean): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    if (!active) return () => clearTimeout(first);
    const id = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [active]);
  return now;
}

/** A status mark: a quiet ring while waiting, a turning ring while working, a tick when done. */
export function StatusMark({ state, size = 20 }: { state: State; size?: number }) {
  const box = { width: size, height: size };
  if (state === "running") {
    return (
      <span
        role="img"
        aria-label="working"
        style={box}
        className="relative inline-flex shrink-0 rounded-full motion-safe:animate-halo"
      >
        <span className="absolute inset-0 rounded-full border-2 border-accent/20 border-t-accent motion-safe:animate-spin" />
      </span>
    );
  }
  if (state === "done") {
    return (
      <span role="img" aria-label="done" style={box} className="inline-flex shrink-0 items-center justify-center rounded-full bg-accent text-on-accent">
        <svg viewBox="0 0 16 16" width={size * 0.6} height={size * 0.6} aria-hidden="true">
          <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    );
  }
  if (state === "failed") {
    return (
      <span role="img" aria-label="failed" style={box} className="inline-flex shrink-0 items-center justify-center rounded-full bg-danger text-white text-[11px] font-bold">
        !
      </span>
    );
  }
  if (state === "paused") {
    return (
      <span role="img" aria-label="paused" style={box} className="inline-flex shrink-0 items-center justify-center gap-[2px] rounded-full border-2 border-[var(--grade-conflicting)]">
        <span className="h-2 w-[2px] bg-[var(--grade-conflicting)]" />
        <span className="h-2 w-[2px] bg-[var(--grade-conflicting)]" />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span role="img" aria-label="up next" style={box} className="inline-flex shrink-0 items-center justify-center rounded-full border-2 border-accent">
        <span className="size-1.5 rounded-full bg-accent" />
      </span>
    );
  }
  return <span role="img" aria-label="waiting" style={box} className="inline-block shrink-0 rounded-full border-2 border-dashed border-rule-strong" />;
}

function stepState(step: RunStep | undefined, runActive: boolean): State {
  if (!step) return "waiting";
  if (step.status === "running" && !runActive) return "paused";
  return step.status as State;
}

/** Seconds a step took (or has taken so far); null while "now" isn't known yet. */
function seconds(step: RunStep, now: number | null): number | null {
  const end = step.finished_at ? new Date(step.finished_at).getTime() : now;
  return end === null ? null : Math.max(0, (end - new Date(step.started_at).getTime()) / 1000);
}

/**
 * The live view of a run: what's happening now, how far each agent has got, and what each one found.
 * Open while the run works; a one-line summary (with details on request) once it's finished.
 */
export function AgentPipeline({ run, action }: { run: Run; action?: ReactNode }) {
  const active = run.status === "queued" || run.status === "running";
  const now = useNow(active);
  const [open, setOpen] = useState(false);
  const byAgent = new Map(run.steps.map((s) => [s.agent, s]));
  const agents = [...ORDER, ...LATER.filter((a) => byAgent.has(a))];
  const paused = run.status === "queued" && run.status_detail.startsWith("Paused");
  const current = agents.find((a) => byAgent.get(a)?.status === "running");
  const finished = ORDER.filter((a) => byAgent.get(a)?.status === "done").length;
  const live = current ? byAgent.get(current)?.progress : null;
  const fraction = (finished + (live && live.total ? live.done / live.total : 0)) / ORDER.length;
  const started = run.started_at ?? run.created_at;
  const end = run.finished_at ? new Date(run.finished_at).getTime() : now;
  const total = end === null ? null : Math.max(0, (end - new Date(started).getTime()) / 1000);
  const expanded = active || open || run.status === "failed";

  const headline = paused
    ? "Paused: the model asked us to slow down"
    : run.status === "queued"
      ? "Starting…"
      : run.status === "running" && current
        ? `${AGENT_LABEL[current] ?? current} is working`
        : run.status === "running"
          ? "Working"
          : run.status === "failed"
            ? "The run stopped early"
            : now
              ? `Claims built ${timeAgo(run.finished_at, now)}`
              : "Claims built";

  return (
    <section
      aria-label="Agents"
      aria-live="polite"
      className={cx(
        "rounded-lg border bg-paper-raised shadow-card",
        run.status === "failed" ? "border-danger/40" : active ? "border-accent/40" : "border-rule",
      )}
    >
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3 px-5 py-4">
        <StatusMark state={paused ? "paused" : active ? "running" : run.status === "failed" ? "failed" : "done"} size={22} />
        <div className="min-w-[13rem] flex-1">
          <p className="font-medium leading-snug">{headline}</p>
          <p className="mt-0.5 text-[13px] text-ink-muted">
            {active && current
              ? AGENT_JOB[current]
              : run.status_detail ||
                [
                  run.started_by_name && `Started by ${run.started_by_name}`,
                  formatDateTime(started),
                  run.llm_calls > 0 && plural(run.llm_calls, "model call"),
                  run.tokens_used > 0 && `${Math.round(run.tokens_used / 1000)}k tokens`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
          </p>
          {active && (
            <div className="mt-3 flex items-center gap-3">
              <Progress value={fraction} label="Run progress" live />
              <span className="shrink-0 text-[12px] font-medium text-ink-faint tabular-nums">
                {finished} of {ORDER.length}
                {total !== null && ` · ${duration(total)}`}
              </span>
            </div>
          )}
        </div>
        <div className="ml-auto flex items-center gap-3">
          {!active && total !== null && (
            <span className="text-[12px] font-medium text-ink-faint tabular-nums" title="How long the run took">
              {duration(total)}
            </span>
          )}
          {action}
        </div>
      </div>

      {expanded ? (
        <ol className="border-t border-rule px-5 py-3">
          {agents.map((agent) => {
            const step = byAgent.get(agent);
            const state = stepState(step, active);
            const p = step?.progress;
            return (
              <li key={agent} className="grid grid-cols-[1.5rem_1fr_auto] items-start gap-x-3 py-2">
                <span className="pt-0.5">
                  <StatusMark state={state} size={18} />
                </span>
                <div className="min-w-0">
                  <p className={cx("text-[14px]", state === "waiting" ? "text-ink-faint" : "text-ink")}>
                    <span className="font-medium">{AGENT_LABEL[agent] ?? agent}</span>
                    <span className="sr-only"> ({state})</span>
                  </p>
                  <p className={cx("text-[13px] leading-snug", state === "waiting" ? "text-ink-faint" : "text-ink-muted")}>
                    {state === "running" ? AGENT_JOB[agent] : step?.summary || AGENT_JOB[agent]}
                  </p>
                  {state === "running" && p && p.total > 0 && (
                    <div className="mt-1.5 flex max-w-sm items-center gap-2">
                      <Progress value={p.done / p.total} label={`${AGENT_LABEL[agent]} progress`} size="sm" live />
                      <span className="shrink-0 text-[11px] font-medium text-ink-faint tabular-nums">
                        {p.done} of {plural(p.total, "call")}
                      </span>
                    </div>
                  )}
                  {step?.error && <p className="mt-1 text-[13px] text-danger">{step.error}</p>}
                </div>
                <span className="pt-0.5 text-[12px] font-medium text-ink-faint tabular-nums">
                  {step && state !== "waiting" && seconds(step, now) !== null ? duration(seconds(step, now)!) : ""}
                </span>
              </li>
            );
          })}
          {!active && (
            <li className="pt-1">
              <button type="button" onClick={() => setOpen(false)} className="text-[13px] text-ink-muted hover:text-ink">
                Hide details
              </button>
            </li>
          )}
        </ol>
      ) : (
        <div className="border-t border-rule px-5 py-2.5">
          <button type="button" onClick={() => setOpen(true)} className="text-[13px] text-ink-muted hover:text-ink">
            Show what each agent did
          </button>
        </div>
      )}
    </section>
  );
}

/** A small "working" line for jobs outside the pipeline (writing questions, writing the pack). */
export function Working({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-2.5 text-ink-muted" aria-live="polite">
      <StatusMark state="running" size={16} />
      <span>{children}</span>
    </p>
  );
}
