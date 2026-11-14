"use client";

import { Check, Copy, KeyRound } from "lucide-react";
import { useActionState, useState, useTransition } from "react";
import { SubmitButton } from "@/components/submit-button";
import { Button, Input, Label, Spinner } from "@/components/ui";
import { createToken, revokeToken, type TokenState } from "./actions";

export function CopyText({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      size="sm"
      variant="secondary"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1800);
        } catch {
          /* clipboard blocked: the text is on screen to copy by hand */
        }
      }}
    >
      {copied ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      {copied ? "Copied" : label}
    </Button>
  );
}

export function NewTokenForm({ projectId }: { projectId: string }) {
  const [state, action] = useActionState<TokenState, FormData>(createToken.bind(null, projectId), undefined);
  return (
    <div>
      <form action={action} className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1">
          <Label htmlFor="token-name">Name</Label>
          <Input id="token-name" name="name" placeholder="VS Code on my laptop" maxLength={100} required />
        </div>
        <SubmitButton pendingText="Making…">
          <KeyRound className="size-4" aria-hidden="true" />
          Make a token
        </SubmitButton>
      </form>
      {state?.error && <p className="mt-2 text-[13px] text-danger">{state.error}</p>}
      {state?.token && (
        <div className="mt-5 rounded-lg border border-accent bg-accent-soft/40 p-4" role="status">
          <p className="text-[14px] font-medium text-ink">Copy your token now: it won&apos;t be shown again.</p>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
            <code className="min-w-0 flex-1 break-all rounded bg-paper-raised px-3 py-2 font-mono text-[13px] text-ink">
              {state.token.token}
            </code>
            <CopyText text={state.token.token} />
          </div>
          <p className="mt-2 text-[12px] text-ink-muted">
            Read-only, for this project only, valid until{" "}
            {state.token.expires_at ? new Date(state.token.expires_at).toLocaleDateString("en-IN") : "you revoke it"}.
          </p>
        </div>
      )}
    </div>
  );
}

export function RevokeButton({ projectId, tokenId }: { projectId: string; tokenId: string }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <span className="inline-flex flex-col items-end">
      <Button
        size="sm"
        variant="danger"
        disabled={pending}
        onClick={() => start(async () => setError(await revokeToken(projectId, tokenId)))}
      >
        {pending && <Spinner />}
        Revoke
      </Button>
      {error && <span className="text-[12px] text-danger">{error}</span>}
    </span>
  );
}
