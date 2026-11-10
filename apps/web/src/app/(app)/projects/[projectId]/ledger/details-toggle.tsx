"use client";

import { ChevronDown } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { cx } from "@/components/ui";

/**
 * A claim card's footer: a "Why and evidence" toggle on the left, the reviewer's buttons on the right,
 * and the details underneath once opened. Keeps the card short until someone wants the reasons.
 */
export function DetailsToggle({ label, actions, children }: { label: string; actions?: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t border-rule px-5 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={id}
          className="inline-flex items-center gap-1.5 rounded-md py-1 text-[13px] font-medium text-ink-muted transition-colors hover:text-ink"
        >
          <ChevronDown className={cx("size-4 transition-transform duration-200", open && "rotate-180")} aria-hidden="true" />
          {open ? "Hide details" : label}
        </button>
        {actions}
      </div>
      {open && (
        <div id={id} className="animate-rise border-t border-rule bg-paper/60 px-5 py-5">
          {children}
        </div>
      )}
    </>
  );
}
