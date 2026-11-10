"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { KeyRound, MoreHorizontal, RefreshCw, RotateCcw, Trash2, X } from "lucide-react";
import { useActionState, useState, useTransition } from "react";
import { SubmitButton } from "@/components/submit-button";
import { Button, ErrorNote, Input, Label, Spinner, buttonClass } from "@/components/ui";
import { removeSource, syncSource, updateConnection } from "./actions";

const ITEM =
  "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[14px] text-ink-muted outline-none data-[highlighted]:bg-paper-sunk data-[highlighted]:text-ink";

/** Change a live source's token (Jira or GitHub), or which Jira issues are read. */
function SettingsWindow({
  projectId,
  sourceId,
  name,
  provider,
  jql,
  open,
  onOpenChange,
}: {
  projectId: string;
  sourceId: string;
  name: string;
  provider: "jira" | "github";
  jql?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [state, action] = useActionState(updateConnection.bind(null, projectId, sourceId), undefined);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1b33]/40 backdrop-blur-[2px] data-[state=open]:animate-fade" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl border border-rule bg-paper-raised p-6 shadow-lift focus:outline-none data-[state=open]:animate-[kb-dialog_0.22s_cubic-bezier(0.23,1,0.32,1)]">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="font-display text-[1.25rem] tracking-[-0.02em] text-ink">Connection settings</Dialog.Title>
              <Dialog.Description className="mt-1 text-[14px] text-ink-muted">{name}</Dialog.Description>
            </div>
            <Dialog.Close
              className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-ink-faint hover:bg-paper-sunk hover:text-ink"
              aria-label="Close"
            >
              <X className="size-4" aria-hidden="true" />
            </Dialog.Close>
          </div>
          <form action={action} className="grid gap-4">
            {provider === "jira" && (
              <div>
                <Label htmlFor={`jql-${sourceId}`} hint="A project key like ROV, or any JQL filter">
                  Which issues
                </Label>
                <Input id={`jql-${sourceId}`} name="jql" defaultValue={jql} autoComplete="off" />
              </div>
            )}
            <div>
              <Label htmlFor={`tok-${sourceId}`} hint="Leave empty to keep the current one">
                New {provider === "jira" ? "API" : "read-only"} token
              </Label>
              <Input id={`tok-${sourceId}`} name="token" type="password" autoComplete="new-password" />
            </div>
            {state?.error && <ErrorNote>{state.error}</ErrorNote>}
            {state?.ok && (
              <p role="status" className="text-[14px] text-[var(--grade-verified)]">
                {state.ok}
              </p>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <Dialog.Close className={buttonClass("quiet")}>Close</Dialog.Close>
              <SubmitButton pendingText="Checking…">Save</SubmitButton>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A source's actions: sync it now, and a menu with the rarer ones (full re-sync, settings, remove). */
export function SourceControls({
  projectId,
  sourceId,
  name,
  busy,
  provider,
  jql,
}: {
  projectId: string;
  sourceId: string;
  name: string;
  busy: boolean;
  /** Set for live sources (GitHub with a repo, or Jira); file uploads have none. */
  provider?: "jira" | "github";
  jql?: string;
}) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  const [settings, setSettings] = useState(false);
  const live = Boolean(provider);

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-1">
        <Button
          variant="secondary"
          size="sm"
          disabled={busy || pending}
          onClick={() => start(async () => setError(await syncSource(projectId, sourceId)))}
        >
          {pending || busy ? <Spinner className="size-3.5" /> : <RefreshCw className="size-3.5" aria-hidden="true" />}
          {busy ? "Reading…" : live ? "Check for changes" : "Sync now"}
        </Button>
        <Menu.Root>
          <Menu.Trigger
            className="inline-flex size-8 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-paper-sunk hover:text-ink data-[state=open]:bg-paper-sunk"
            aria-label={`More actions for ${name}`}
          >
            <MoreHorizontal className="size-4" aria-hidden="true" />
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content
              align="end"
              sideOffset={6}
              className="z-50 w-56 origin-[var(--radix-dropdown-menu-content-transform-origin)] animate-rise rounded-lg border border-rule bg-paper-raised p-1.5 shadow-lift"
            >
              {live && (
                <Menu.Item
                  className={ITEM}
                  disabled={busy || pending}
                  onSelect={() => start(async () => setError(await syncSource(projectId, sourceId, true)))}
                >
                  <RotateCcw className="size-4" aria-hidden="true" />
                  Full re-sync
                </Menu.Item>
              )}
              {live && (
                <Menu.Item className={ITEM} onSelect={() => setSettings(true)}>
                  <KeyRound className="size-4" aria-hidden="true" />
                  Connection settings…
                </Menu.Item>
              )}
              {live && <Menu.Separator className="my-1.5 h-px bg-rule" />}
              <Menu.Item
                className={`${ITEM} data-[highlighted]:bg-[var(--grade-missing-bg)] data-[highlighted]:text-[var(--grade-missing)]`}
                onSelect={() => {
                  if (confirm(`Remove “${name}”? Its evidence is deleted, and any claim that cited it loses that citation.`)) {
                    start(() => removeSource(projectId, sourceId));
                  }
                }}
              >
                <Trash2 className="size-4" aria-hidden="true" />
                Remove source
              </Menu.Item>
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
      </div>
      {error && <p className="max-w-xs text-right text-[12px] text-danger">{error}</p>}
      {provider && (
        <SettingsWindow
          projectId={projectId}
          sourceId={sourceId}
          name={name}
          provider={provider}
          jql={jql}
          open={settings}
          onOpenChange={setSettings}
        />
      )}
    </div>
  );
}
