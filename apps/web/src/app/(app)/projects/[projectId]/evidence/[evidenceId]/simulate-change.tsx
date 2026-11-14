"use client";

import { FlaskConical } from "lucide-react";
import Link from "next/link";
import { useState, useTransition } from "react";
import { Button, Spinner, Textarea } from "@/components/ui";
import { plural } from "@/lib/format";
import { simulateChange } from "../actions";

/**
 * Demo mode only: edit this item as if someone had changed it in its tool. KnowBridge then does
 * exactly what a sync does, so drift detection can be shown without waiting for a real edit.
 */
export function SimulateChange({ projectId, evidenceId, text }: { projectId: string; evidenceId: string; text: string }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(text);
  const [pending, start] = useTransition();
  const [result, setResult] = useState<{ error?: string; claims?: number }>();

  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        <FlaskConical className="size-3.5" aria-hidden="true" />
        Simulate a source change
      </Button>
    );
  }
  return (
    <form
      className="grid gap-3"
      onSubmit={(ev) => {
        ev.preventDefault();
        start(async () => setResult(await simulateChange(projectId, evidenceId, draft)));
      }}
    >
      <div>
        <label htmlFor="simulate" className="block text-[14px] font-semibold text-ink">
          Simulate a source change
        </label>
        <p className="mt-0.5 text-[13px] leading-relaxed text-ink-muted">
          Demo mode only. Edit the text as if someone changed it in its tool, for example a different number or a
          reversed decision. KnowBridge then checks it exactly as it would after a sync. The next real sync of this
          source puts the original back.
        </p>
      </div>
      <Textarea id="simulate" rows={8} value={draft} onChange={(e) => setDraft(e.target.value)} disabled={pending} />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" size="sm" disabled={pending || draft.trim() === text.trim()}>
          {pending && <Spinner className="size-3.5" />}
          Save as a source change
        </Button>
        <Button type="button" variant="quiet" size="sm" disabled={pending} onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {result?.error && <p className="text-[13px] text-danger">{result.error}</p>}
      {result && !result.error && (
        <p className="text-[13px] text-ink" role="status">
          {result.claims
            ? `${plural(result.claims, "claim")} quoting this changed text ${result.claims === 1 ? "is" : "are"} being re-checked. `
            : "No claim quotes the words you changed, so nothing needs re-checking. "}
          <Link href={`/projects/${projectId}/ledger?review=changed`} className="font-medium text-accent hover:underline">
            See it in the ledger
          </Link>
        </p>
      )}
    </form>
  );
}
