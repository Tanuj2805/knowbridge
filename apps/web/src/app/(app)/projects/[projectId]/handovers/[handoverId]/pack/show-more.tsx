"use client";

import { ChevronDown } from "lucide-react";
import { Children, useState, type ReactNode } from "react";
import { cx } from "@/components/ui";

/**
 * The first few items of a list, with a button for the rest. Everything is in the page from the start
 * (only hidden), so printing or saving as PDF always includes the whole list.
 */
export function ShowMore({ initial = 5, noun, children }: { initial?: number; noun: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const items = Children.toArray(children);
  const extra = items.length - initial;
  return (
    <>
      <ul className="divide-y divide-rule">
        {items.map((item, i) => (
          <li key={i} className={cx(i >= initial && !open && "hidden print:block", i >= initial && open && "animate-rise")}>
            {item}
          </li>
        ))}
      </ul>
      {extra > 0 && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md text-[14px] font-medium text-accent hover:underline print:hidden"
        >
          <ChevronDown className={cx("size-4 transition-transform duration-200", open && "rotate-180")} aria-hidden="true" />
          {open ? "Show fewer" : `Show all ${items.length} ${noun}`}
        </button>
      )}
    </>
  );
}
