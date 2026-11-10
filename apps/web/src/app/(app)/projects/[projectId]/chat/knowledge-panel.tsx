"use client";

import { Check, Copy, Download, RefreshCw } from "lucide-react";
import { useState, useTransition } from "react";
import { Button, Progress, Spinner, buttonClass, cx } from "@/components/ui";
import type { RagStatus } from "@/lib/types";
import { rebuildIndex } from "./actions";

function Coverage({ label, done, total }: { label: string; done: number; total: number }) {
  const all = total > 0 && done >= total;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
        <span className="text-ink-muted">{label}</span>
        <span className="tabular-nums text-ink">
          {done}
          <span className="text-ink-faint"> / {total}</span>
        </span>
      </div>
      <Progress value={total ? done / total : 0} label={`${label}: ${done} of ${total} indexed`} size="sm"
        tone={all ? "success" : "accent"} />
    </div>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="inline-flex items-center gap-1 text-[12px] text-ink-faint transition-colors hover:text-ink"
      aria-label={label}
    >
      {copied ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** What the assistant can draw on (the project's vector index) and how to give it to another model. */
export function KnowledgePanel({ projectId, status }: { projectId: string; status: RagStatus }) {
  const [pending, start] = useTransition();
  const [note, setNote] = useState<string>();
  const missing = status.evidence_total - status.evidence_indexed + (status.claims_total - status.claims_indexed);
  const snippet = `POST /projects/${projectId}/rag/retrieve
{ "query": "who owns deployments?", "k": 8,
  "budget_tokens": 4000 }
→ { "context": "...", "chunks": [...] }`;

  return (
    <aside className="flex flex-col gap-8 text-[14px] lg:sticky lg:top-6 lg:self-start" aria-label="What the assistant knows">
      <section>
        <h2 className="text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">What it knows</h2>
        <p className="mt-2 leading-relaxed text-ink-muted">
          Everything your sources brought in, stored as vectors so it can be found by meaning, not just exact words.
        </p>
        <div className="mt-4 flex flex-col gap-3.5">
          <Coverage label="Source items" done={status.evidence_indexed} total={status.evidence_total} />
          <Coverage label="Claims" done={status.claims_indexed} total={status.claims_total} />
        </div>
        {status.approved_only && (
          <p className="mt-3 text-[13px] leading-relaxed text-ink-faint">You see approved claims and the sources you can open.</p>
        )}
        {status.can_index && (
          <div className="mt-4 flex items-center gap-3">
            <Button
              variant="secondary"
              size="sm"
              disabled={pending}
              onClick={() =>
                start(async () => {
                  const err = await rebuildIndex(projectId);
                  setNote(err ?? "Indexing started. New items are added in the background.");
                })
              }
            >
              {pending ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" aria-hidden="true" />}
              {missing > 0 ? `Index ${missing} new` : "Re-index"}
            </Button>
          </div>
        )}
        {note && <p className="mt-2 text-[13px] text-ink-muted" role="status">{note}</p>}
      </section>

      <section className="border-t border-rule pt-6">
        <h2 className="text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">Answering</h2>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[13px]">
          <dt className="text-ink-faint">Model</dt>
          <dd className="truncate text-ink" title={status.model}>{status.model || "not set up"}</dd>
          <dt className="text-ink-faint">Search</dt>
          <dd className="truncate text-ink" title={status.embedding_model ?? ""}>
            {status.embedding_model ? status.embedding_model.split("@")[0].replace(/^\w+:/, "") : "keywords only"}
          </dd>
          <dt className="text-ink-faint">Context</dt>
          <dd className="text-ink tabular-nums">{status.context_tokens.toLocaleString()} tokens</dd>
        </dl>
      </section>

      <section className="border-t border-rule pt-6">
        <h2 className="text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">Use with another model</h2>
        <p className="mt-2 leading-relaxed text-ink-muted">
          Give any LLM (Qwen, Llama, GPT) this project as its knowledge. Sensitive items stay out.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <a href={`/projects/${projectId}/chat/context?tokens=8000`} className={buttonClass("secondary", "sm")}>
            <Download className="size-3.5" aria-hidden="true" />
            Context file
          </a>
          <a href={`/projects/${projectId}/chat/context?tokens=32000`} className={cx(buttonClass("quiet", "sm"))}>
            Full (32k)
          </a>
        </div>
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[12px] text-ink-faint">Or retrieve per question (API)</span>
            <CopyButton text={snippet} label="Copy the API example" />
          </div>
          <pre className="whitespace-pre-wrap break-all rounded-md bg-paper-sunk px-3 py-2.5 font-mono text-[11.5px] leading-relaxed text-ink-muted">
            {snippet}
          </pre>
        </div>
      </section>
    </aside>
  );
}
