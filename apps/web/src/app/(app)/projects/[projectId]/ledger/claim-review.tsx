"use client";

import { Check, Pencil, Undo2, X } from "lucide-react";
import { useState, useTransition } from "react";
import { Button, Input, Label, Textarea } from "@/components/ui";
import type { Claim } from "@/lib/types";
import { approveAll, approveByGrade, reviewClaim, type ReviewInput } from "./actions";

/** Approve / edit / reject one claim. Every change keeps the previous wording as a version. */
export function ClaimReview({ projectId, claim, removed }: { projectId: string; claim: Claim; removed?: boolean }) {
  const [pending, start] = useTransition();
  const [mode, setMode] = useState<"idle" | "edit" | "reject">("idle");
  const [error, setError] = useState<string>();
  const send = (input: ReviewInput) =>
    start(async () => {
      const err = await reviewClaim(projectId, claim.id, input);
      setError(err);
      if (!err) setMode("idle");
    });
  const approved = claim.status === "approved" || claim.status === "edited";

  if (mode === "edit") {
    return (
      <form
        className="grid basis-full gap-3 rounded-lg border border-rule bg-paper-raised p-4"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          send({
            action: "edit",
            statement: String(f.get("statement")),
            rationale: String(f.get("rationale")),
            owner_name: String(f.get("owner_name")),
            due_date: String(f.get("due_date")) || null,
            note: String(f.get("note")),
          });
        }}
      >
        <div>
          <Label htmlFor={`s-${claim.id}`} required>
            Statement
          </Label>
          <Textarea id={`s-${claim.id}`} name="statement" rows={2} defaultValue={claim.statement} required />
        </div>
        <div>
          <Label htmlFor={`r-${claim.id}`} hint="Optional. Only if the evidence or the team says why">Why</Label>
          <Textarea id={`r-${claim.id}`} name="rationale" rows={2} defaultValue={claim.rationale} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor={`o-${claim.id}`}>Owner</Label>
            <Input id={`o-${claim.id}`} name="owner_name" defaultValue={claim.owner_name} />
          </div>
          <div>
            <Label htmlFor={`d-${claim.id}`}>Due</Label>
            <Input id={`d-${claim.id}`} name="due_date" type="date" defaultValue={claim.due_date ?? ""} />
          </div>
        </div>
        <div>
          <Label htmlFor={`n-${claim.id}`} hint="Optional; kept with this version">What you changed and why</Label>
          <Input id={`n-${claim.id}`} name="note" />
        </div>
        <div className="flex gap-2">
          <Button size="sm" disabled={pending}>{pending ? "Saving…" : "Save and approve"}</Button>
          <Button size="sm" type="button" variant="quiet" onClick={() => setMode("idle")}>
            Cancel
          </Button>
        </div>
        {error && <p className="text-[12px] text-danger">{error}</p>}
      </form>
    );
  }

  if (mode === "reject") {
    return (
      <form
        className="flex basis-full flex-wrap items-end gap-2 rounded-lg border border-rule bg-paper-raised p-4"
        onSubmit={(e) => {
          e.preventDefault();
          send({ action: "reject", note: String(new FormData(e.currentTarget).get("note")) });
        }}
      >
        <div className="min-w-0 flex-1">
          <Label htmlFor={`x-${claim.id}`} hint="Optional, but it helps whoever looks later">Why is it wrong?</Label>
          <Input id={`x-${claim.id}`} name="note" autoFocus />
        </div>
        <Button size="sm" variant="danger" disabled={pending}>{pending ? "Saving…" : "Reject"}</Button>
        <Button size="sm" type="button" variant="quiet" onClick={() => setMode("idle")}>
          Cancel
        </Button>
        {error && <p className="w-full text-[12px] text-danger">{error}</p>}
      </form>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {removed ? (
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => send({ action: "approve" })}>
          Restore and approve
        </Button>
      ) : approved ? (
        <Button size="sm" variant="quiet" disabled={pending} onClick={() => send({ action: "reopen" })}>
          <Undo2 className="size-3.5" aria-hidden="true" />
          Undo approval
        </Button>
      ) : (
        <>
          <Button size="sm" variant="quiet" disabled={pending} onClick={() => setMode("reject")}>
            <X className="size-3.5" aria-hidden="true" />
            Reject
          </Button>
          <Button size="sm" variant="secondary" disabled={pending} onClick={() => setMode("edit")}>
            <Pencil className="size-3.5" aria-hidden="true" />
            Edit
          </Button>
          <Button size="sm" disabled={pending} onClick={() => send({ action: "approve" })}>
            <Check className="size-3.5" aria-hidden="true" />
            Approve
          </Button>
        </>
      )}
      {pending && <span className="text-[12px] text-ink-faint">Saving…</span>}
      {error && <span className="text-[12px] text-danger">{error}</span>}
    </div>
  );
}

export function ApproveVerified({ projectId }: { projectId: string }) {
  const [pending, start] = useTransition();
  const [message, setMessage] = useState<string>();
  return (
    <div className="flex flex-col gap-1">
      <Button
        size="sm"
        variant="secondary"
        disabled={pending}
        onClick={() => start(async () => setMessage(await approveByGrade(projectId, ["verified"])))}
        title="Claims that two separate sources agree on, or that come straight from system data"
      >
        {pending ? "Approving…" : "Approve all Verified drafts"}
      </Button>
      {message && <span className="text-[12px] text-ink-muted">{message}</span>}
    </div>
  );
}

export function ApproveAll({ projectId, count }: { projectId: string; count: number }) {
  const [pending, start] = useTransition();
  const [message, setMessage] = useState<string>();
  return (
    <div className="flex flex-col gap-1">
      <Button
        size="sm"
        disabled={pending || count === 0}
        onClick={() => {
          if (
            confirm(
              `Approve all ${count} claims waiting for review? They'll go into the handover pack as checked. ` +
                "You can still undo any one of them afterwards.",
            )
          ) {
            start(async () => setMessage(await approveAll(projectId)));
          }
        }}
      >
        {pending ? "Approving…" : `Approve all (${count})`}
      </Button>
      {message && <span className="text-[12px] text-ink-muted">{message}</span>}
    </div>
  );
}
