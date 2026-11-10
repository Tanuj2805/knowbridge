"use client";

import { useState, useTransition } from "react";
import { Button, Input } from "@/components/ui";
import { acknowledgeSection, flagClaim, markPlanItem } from "../../actions";

type Ids = { projectId: string; handoverId: string };

export function Acknowledge({ projectId, handoverId, sectionId, done }: Ids & { sectionId: string; done: boolean }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  if (done) return <p className="text-[13px] font-medium text-[var(--grade-verified)]">✓ You&apos;ve read this section</p>;
  return (
    <span className="inline-flex flex-col gap-1 print:hidden">
      <Button
        size="sm"
        disabled={pending}
        onClick={() => start(async () => setError(await acknowledgeSection(projectId, handoverId, sectionId)))}
      >
        {pending ? "Saving…" : "✓ I've read this section"}
      </Button>
      {error && <span className="text-[12px] text-danger">{error}</span>}
    </span>
  );
}

export function PlanCheck({ projectId, handoverId, itemId, done, editable }: Ids & {
  itemId: string;
  done: boolean;
  editable: boolean;
}) {
  const [pending, start] = useTransition();
  const [checked, setChecked] = useState(done);
  return (
    <input
      type="checkbox"
      aria-label="Done"
      className="mt-1 size-4 accent-[var(--accent)]"
      checked={checked}
      disabled={!editable || pending}
      onChange={(e) => {
        const next = e.target.checked;
        setChecked(next);
        start(async () => {
          if (await markPlanItem(projectId, handoverId, itemId, next)) setChecked(!next);
        });
      }}
    />
  );
}

export function FlagClaim({ projectId, handoverId, claimId }: Ids & { claimId: string }) {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  if (sent) return <p className="text-[12px] text-ink-muted">Sent to the approver. Thank you.</p>;
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[12px] text-ink-faint hover:text-ink underline-offset-2 hover:underline print:hidden"
      >
        This looks wrong
      </button>
    );
  }
  return (
    <form
      className="mt-2 flex flex-wrap gap-2 print:hidden"
      onSubmit={(e) => {
        e.preventDefault();
        const note = String(new FormData(e.currentTarget).get("note") ?? "");
        start(async () => {
          const err = await flagClaim(projectId, handoverId, claimId, note);
          setError(err);
          if (!err) setSent(true);
        });
      }}
    >
      <Input name="note" required minLength={3} placeholder="What's wrong, or what's true instead?" className="min-w-0 flex-1" />
      <Button size="sm" variant="secondary" disabled={pending}>
        {pending ? "Sending…" : "Tell the approver"}
      </Button>
      <Button size="sm" type="button" variant="quiet" onClick={() => setOpen(false)}>
        Cancel
      </Button>
      {error && <p className="w-full text-[12px] text-danger">{error}</p>}
    </form>
  );
}

export function PrintButton() {
  return (
    <Button size="sm" variant="secondary" onClick={() => window.print()}>
      Print or save as PDF
    </Button>
  );
}
