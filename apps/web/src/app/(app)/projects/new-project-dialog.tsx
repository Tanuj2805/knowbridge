"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Plus, X } from "lucide-react";
import { useActionState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { ErrorNote, buttonClass } from "@/components/ui";
import { loadDemo } from "./actions";
import { NewProjectForm } from "./new-project-form";

function DemoOption() {
  const [state, action] = useActionState(loadDemo, undefined);
  return (
    <form action={action} className="mt-6 flex flex-col gap-3 border-t border-rule pt-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium text-ink">Or try the demo</p>
        <p className="text-[13px] text-ink-muted">A made-up college fest app with four months of history.</p>
      </div>
      <SubmitButton variant="secondary" size="sm" pendingText="Setting it up…">
        Load the demo
      </SubmitButton>
      {state?.error && (
        <div className="w-full">
          <ErrorNote>{state.error}</ErrorNote>
        </div>
      )}
    </form>
  );
}

/** The "New project" button, and the window it opens with the form. */
export function NewProjectDialog({ demo, defaultOpen }: { demo: boolean; defaultOpen?: boolean }) {
  return (
    <Dialog.Root defaultOpen={defaultOpen}>
      <Dialog.Trigger className={buttonClass("primary")}>
        <Plus className="size-4" aria-hidden="true" />
        New project
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1b33]/40 backdrop-blur-[2px] data-[state=open]:animate-fade" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl border border-rule bg-paper-raised p-6 shadow-lift focus:outline-none data-[state=open]:animate-[kb-dialog_0.22s_cubic-bezier(0.23,1,0.32,1)]">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="font-display text-[1.35rem] tracking-[-0.02em] text-ink">New project</Dialog.Title>
              <Dialog.Description className="mt-1 text-[14px] text-ink-muted">
                One project per team or product. You&apos;ll add people and connect sources next.
              </Dialog.Description>
            </div>
            <Dialog.Close
              className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-paper-sunk hover:text-ink"
              aria-label="Close"
            >
              <X className="size-4" aria-hidden="true" />
            </Dialog.Close>
          </div>
          <NewProjectForm cancel={<Dialog.Close className={buttonClass("quiet")}>Cancel</Dialog.Close>} />
          {demo && <DemoOption />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
