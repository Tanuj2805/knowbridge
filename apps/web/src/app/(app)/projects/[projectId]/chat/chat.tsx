"use client";

import { ArrowUp, Check, Copy, FileText, MessageSquareText, RotateCcw, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { Fragment, type ReactNode, useEffect, useRef, useState, useTransition } from "react";
import { cx } from "@/components/ui";
import {
  EVIDENCE_KIND_LABEL,
  GRADE_LABEL,
  type AskResult,
  type ChatTurn,
  type GuardNotes,
  type RagChunk,
} from "@/lib/types";
import { askProject } from "./actions";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  result?: AskResult;
  error?: string;
  /** the server's signature on an answer, sent back with the history */
  token?: string | null;
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What the guardrails did, in plain words. Nothing shows when they had nothing to do. */
function guardLines(g: GuardNotes | undefined, invented: string[]): string[] {
  if (!g) return [];
  const lines: string[] = [];
  if (g.cleaned_sources)
    lines.push(`${plural(g.cleaned_sources, "source", "sources")} contained text aimed at an AI. It was removed before answering.`);
  if (g.unsupported_figures?.length)
    lines.push(`Check ${g.unsupported_figures.join(", ")}: not found in the sources.`);
  if (g.ungrounded) lines.push("No source backs this answer. Treat it with care.");
  if (invented.length) lines.push("A citation to a source the model was never given was removed.");
  if (g.removed_links) lines.push(`${plural(g.removed_links, "link", "links")} not in the sources removed.`);
  if (g.redacted) lines.push("A secret or personal detail was masked.");
  if (g.forged_turns || g.dropped_turns) lines.push("An earlier message couldn't be verified, so it was left out.");
  return lines;
}

const SUGGESTIONS = [
  "What should I work on first?",
  "What are the biggest risks right now?",
  "Who owns what in this project?",
  "Why were the main decisions made?",
  "What is blocked or waiting on someone?",
];

const storageKey = (projectId: string) => `kb-chat:${projectId}`;
const newId = () => Math.random().toString(36).slice(2);

// --- answer text: paragraphs, "- " lists, **bold**, and [C1]/[E2] citations as numbered chips ---

function Inline({ text, cite }: { text: string; cite: (ref: string) => ReactNode }) {
  const parts = text.split(/(\[[CE]\d{1,3}\]|\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) => {
        const ref = part.match(/^\[([CE]\d{1,3})\]$/);
        if (ref) return <Fragment key={i}>{cite(ref[1])}</Fragment>;
        if (part.length > 2 && part.startsWith("`") && part.endsWith("`"))
          return (
            <code key={i} className="rounded bg-paper-sunk px-1 py-px font-mono text-[0.88em] text-ink">
              {part.slice(1, -1)}
            </code>
          );
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
          return <strong key={i} className="font-semibold text-ink">{part.slice(2, -2)}</strong>;
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

function AnswerText({ text, cite }: { text: string; cite: (ref: string) => ReactNode }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) {
      blocks.push({ list: false, lines: [] });
      continue;
    }
    const item = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)$/);
    const last = blocks[blocks.length - 1];
    if (item) {
      if (last?.list) last.lines.push(item[1]);
      else blocks.push({ list: true, lines: [item[1]] });
    } else if (last && !last.list && last.lines.length) last.lines.push(line);
    else blocks.push({ list: false, lines: [line] });
  }
  return (
    <div className="flex flex-col gap-3 text-[15px] leading-[1.7] text-ink">
      {blocks
        .filter((b) => b.lines.length)
        .map((b, i) =>
          b.list ? (
            <ul key={i} className="flex flex-col gap-1.5 pl-5 [list-style:disc] marker:text-ink-faint">
              {b.lines.map((l, j) => (
                <li key={j}>
                  <Inline text={l} cite={cite} />
                </li>
              ))}
            </ul>
          ) : (
            <p key={i}>
              <Inline text={b.lines.join(" ")} cite={cite} />
            </p>
          ),
        )}
    </div>
  );
}

// --- the sources an answer cites ---

function sourceMeta(c: RagChunk): string {
  const meta = baseMeta(c);
  return c.cleaned ? `${meta} · text aimed at an AI removed` : meta;
}

function baseMeta(c: RagChunk): string {
  if (c.kind === "claim") {
    const grade = c.grade ? GRADE_LABEL[c.grade][0] : "";
    return ["Claim", c.type_label, grade, c.approved ? "approved" : ""].filter(Boolean).join(" · ");
  }
  const kind = (c.item_kind && EVIDENCE_KIND_LABEL[c.item_kind]) || "";
  return [kind || "Source", c.source, c.author, c.date].filter(Boolean).join(" · ");
}

function SourceItem({ c, n, projectId, staff, active }: { c: RagChunk; n: number; projectId: string; staff: boolean; active: boolean }) {
  const quote = c.kind === "claim" ? c.quotes?.[0] : undefined;
  const href = !staff
    ? undefined
    : c.kind === "claim"
      ? `/projects/${projectId}/ledger?q=${encodeURIComponent(c.title.slice(0, 80))}`
      : `/projects/${projectId}/evidence/${c.id}`;
  const body = (
    <>
      <span
        className={cx(
          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-medium tabular-nums transition-colors",
          active ? "bg-accent text-on-accent" : "bg-accent-soft text-accent",
        )}
      >
        {n}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-[12px] text-ink-faint">
          {c.kind === "claim" ? <Sparkles className="size-3" aria-hidden="true" /> : <FileText className="size-3" aria-hidden="true" />}
          <span className="truncate">{sourceMeta(c)}</span>
        </span>
        <span className="mt-0.5 line-clamp-2 block text-[14px] leading-snug text-ink">{c.title}</span>
        {quote ? (
          <span className="mt-1 line-clamp-2 block text-[13px] italic leading-snug text-ink-muted">
            &ldquo;{quote.quote}&rdquo; <span className="not-italic text-ink-faint">({[quote.source, quote.author].filter(Boolean).join(", ")})</span>
          </span>
        ) : c.kind === "evidence" && c.text && c.text !== c.title ? (
          <span className="mt-1 line-clamp-2 block text-[13px] leading-snug text-ink-muted">{c.text}</span>
        ) : null}
      </span>
    </>
  );
  const cls = cx(
    "flex gap-3 rounded-md px-2 py-2 -mx-2 transition-colors duration-150",
    active ? "bg-accent-soft/60" : href && "hover:bg-paper-sunk",
  );
  return (
    <li id={`src-${n}`}>
      {href ? (
        <Link href={href} className={cls}>
          {body}
        </Link>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </li>
  );
}

function CopyAnswer({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() =>
        navigator.clipboard?.writeText(text.replace(/\s?\[[CE]\d{1,3}\]/g, "")).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        })
      }
      className="inline-flex items-center gap-1 transition-colors hover:text-ink"
    >
      {copied ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function AssistantMessage({ m, projectId, staff }: { m: Message; projectId: string; staff: boolean }) {
  const [active, setActive] = useState<number | null>(null);
  const r = m.result;
  const cited = r?.citations ?? [];
  const order = new Map(cited.map((c, i) => [c.ref, i + 1]));
  const cite = (ref: string) => {
    const n = order.get(ref);
    if (!n) return null;
    return (
      <button
        type="button"
        onMouseEnter={() => setActive(n)}
        onMouseLeave={() => setActive(null)}
        onFocus={() => setActive(n)}
        onBlur={() => setActive(null)}
        onClick={() => document.getElementById(`src-${n}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" })}
        aria-label={`Source ${n}`}
        className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full bg-accent-soft px-1 align-middle text-[11px] font-medium tabular-nums text-accent transition-colors hover:bg-accent hover:text-on-accent"
      >
        {n}
      </button>
    );
  };

  const blocked = Boolean(r?.blocked);
  const notes = guardLines(r?.guard, r?.invented ?? []);

  return (
    <div className="flex animate-rise gap-3.5">
      <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        {blocked ? <ShieldCheck className="size-3.5" aria-hidden="true" /> : <Sparkles className="size-3.5" aria-hidden="true" />}
      </span>
      <div className="min-w-0 flex-1">
        {blocked && (
          <p className="mb-1 text-[12px] font-medium uppercase tracking-[0.08em] text-accent">Stopped by guardrails</p>
        )}
        {m.error ? (
          <p className="text-[15px] leading-relaxed text-ink-muted">{m.error}</p>
        ) : r?.error ? (
          <p className="text-[15px] leading-relaxed text-ink-muted">{r.error}</p>
        ) : (
          <AnswerText text={m.content} cite={cite} />
        )}

        {cited.length > 0 && (
          <div className="mt-4 border-t border-rule pt-3">
            <p className="mb-1 text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">
              {cited.length === 1 ? "Source" : `${cited.length} sources`}
            </p>
            <ol className="flex flex-col">
              {cited.map((c, i) => (
                <SourceItem key={c.ref} c={c} n={i + 1} projectId={projectId} staff={staff} active={active === i + 1} />
              ))}
            </ol>
          </div>
        )}
        {r?.error && r.sources.length > 0 && (
          <div className="mt-4 border-t border-rule pt-3">
            <p className="mb-1 text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">What it found</p>
            <ol className="flex flex-col">
              {r.sources.slice(0, 6).map((c, i) => (
                <SourceItem key={c.ref || c.id} c={c} n={i + 1} projectId={projectId} staff={staff} active={false} />
              ))}
            </ol>
          </div>
        )}

        {notes.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1 border-l-2 border-accent/40 pl-3 text-[13px] leading-snug text-ink-muted">
            {notes.map((n) => (
              <li key={n} className="flex items-start gap-1.5">
                <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden="true" />
                <span>{n}</span>
              </li>
            ))}
          </ul>
        )}

        {r && !r.error && !blocked && (
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-faint">
            {r.sources.length > 0 && <span>Searched {r.sources.length} items</span>}
            {r.withheld > 0 && <span>{r.withheld} sensitive left out</span>}
            <CopyAnswer text={m.content} />
          </div>
        )}
      </div>
    </div>
  );
}

function Thinking() {
  return (
    <div className="flex animate-fade gap-3.5" role="status" aria-live="polite">
      <span className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Sparkles className="size-3.5 motion-safe:animate-pulse" aria-hidden="true" />
      </span>
      <p className="mt-1.5 text-[14px] text-ink-muted">
        Searching the project&apos;s sources
        <span className="inline-flex w-5">
          <span className="motion-safe:animate-pulse">…</span>
        </span>
      </p>
    </div>
  );
}

export function Chat({ projectId, projectName, staff, ready }: { projectId: string; projectName: string; staff: boolean; ready: boolean }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pending, start] = useTransition();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // the conversation survives a reload (this browser only)
  useEffect(() => {
    try {
      const saved = localStorage.getItem(storageKey(projectId));
      // eslint-disable-next-line react-hooks/set-state-in-effect -- read once after mount, to match the server render
      if (saved) setMessages(JSON.parse(saved));
    } catch {
      /* storage unavailable */
    }
  }, [projectId]);
  useEffect(() => {
    try {
      if (messages.length) localStorage.setItem(storageKey(projectId), JSON.stringify(messages.slice(-30)));
      else localStorage.removeItem(storageKey(projectId));
    } catch {
      /* storage unavailable */
    }
  }, [messages, projectId]);
  useEffect(() => {
    if (messages.length) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);

  function send(text: string) {
    const question = text.trim();
    if (!question || pending) return;
    // refused turns stay out of the history; answers go back with the server's signature (answers
    // saved before signing existed have none and stay out too: the server would drop them anyway)
    const history: ChatTurn[] = messages
      .filter((m) => !m.error && m.content && !m.result?.blocked && (m.role === "user" || m.token))
      .map((m) => ({ role: m.role, content: m.content, ...(m.role === "assistant" ? { token: m.token } : {}) }));
    setMessages((ms) => [...ms, { id: newId(), role: "user", content: question }]);
    setInput("");
    start(async () => {
      const res = await askProject(projectId, question, history);
      setMessages((ms) => [
        ...ms,
        res.ok
          ? { id: newId(), role: "assistant", content: res.result.answer, result: res.result, token: res.result.token }
          : { id: newId(), role: "assistant", content: "", error: res.error },
      ]);
      inputRef.current?.focus();
    });
  }

  const empty = messages.length === 0;

  return (
    <section className="flex min-h-[calc(100dvh-16rem)] min-w-0 flex-col" aria-label="Chat with the project">
      <div className="flex items-center justify-between gap-4 pb-2">
        <h1 className="font-display text-[1.35rem] tracking-[-0.02em] text-ink">Chat</h1>
        {!empty && (
          <button
            type="button"
            onClick={() => setMessages([])}
            disabled={pending}
            className="inline-flex items-center gap-1.5 text-[13px] text-ink-muted transition-colors hover:text-ink disabled:opacity-50"
          >
            <RotateCcw className="size-3.5" aria-hidden="true" />
            New chat
          </button>
        )}
      </div>

      <div className="flex flex-1 flex-col">
        {empty ? (
          <div className="flex flex-1 flex-col justify-center py-10">
            <span className="flex size-10 items-center justify-center rounded-full bg-accent-soft text-accent">
              <MessageSquareText className="size-5" aria-hidden="true" />
            </span>
            <p className="mt-4 font-display text-[1.6rem] leading-tight tracking-[-0.03em] text-ink sm:text-[1.9rem]">
              Ask anything about {projectName}
            </p>
            <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-ink-muted">
              Answers come only from what this project&apos;s sources brought in: messages, docs, issues, pull
              requests, commits and cards. Every point links to where it came from.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  disabled={!ready || pending}
                  onClick={() => send(s)}
                  className="rounded-full border border-rule-strong px-3.5 py-1.5 text-[13px] text-ink-muted transition-[color,border-color,transform] duration-150 hover:border-accent hover:text-ink motion-safe:active:scale-[0.97] disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-8 py-6">
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex animate-rise justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-paper-sunk px-4 py-2.5 text-[15px] leading-relaxed text-ink">
                    {m.content}
                  </p>
                </div>
              ) : (
                <AssistantMessage key={m.id} m={m} projectId={projectId} staff={staff} />
              ),
            )}
            {pending && <Thinking />}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <form
        className="sticky bottom-0 -mx-1 mt-4 bg-gradient-to-t from-paper from-70% to-transparent px-1 pb-3 pt-6"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <div
          data-focus-frame
          className="flex items-end gap-2 rounded-2xl border border-rule-strong bg-paper-raised p-2 pl-4 shadow-[var(--shadow-lift)] transition-[border-color,box-shadow] focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20"
        >
          <label htmlFor="chat-input" className="sr-only">
            Your question
          </label>
          <textarea
            id="chat-input"
            ref={inputRef}
            rows={1}
            value={input}
            maxLength={1000}
            disabled={!ready}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder={ready ? "Ask about owners, decisions, risks, what to do next…" : "No AI model is set up for this server."}
            className="max-h-40 min-h-[2.25rem] min-w-0 flex-1 resize-none border-0 bg-transparent py-1.5 text-[15px] leading-relaxed text-ink shadow-none outline-none ring-0 [field-sizing:content] placeholder:text-ink-faint focus:outline-none focus-visible:outline-none"
          />
          <button
            type="submit"
            disabled={!input.trim() || pending || !ready}
            aria-label="Send"
            className="flex size-9 shrink-0 items-center justify-center rounded-full bg-btn text-on-btn transition-[background-color,transform,opacity] duration-150 hover:bg-btn-hover motion-safe:active:scale-[0.94] disabled:opacity-35"
          >
            <ArrowUp className="size-4" aria-hidden="true" />
          </button>
        </div>
        <p className="mt-1.5 px-1 text-center text-[12px] text-ink-faint">
          Answers use only this project&apos;s record. Check the sources before acting on them.
        </p>
      </form>
    </section>
  );
}
