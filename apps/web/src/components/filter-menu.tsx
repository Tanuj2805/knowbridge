"use client";

import * as Menu from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown } from "lucide-react";
import Link from "next/link";
import { cx } from "./ui";

export type FilterOption = { label: string; href: string; current: boolean; count?: number; colour?: string };

/** A compact "Grade: Any ▾" button whose menu is a list of links, one per choice (the page does the filtering). */
export function FilterMenu({ label, options }: { label: string; options: FilterOption[] }) {
  const chosen = options.find((o) => o.current);
  const filtered = chosen && options.indexOf(chosen) > 0;
  return (
    <Menu.Root>
      <Menu.Trigger
        className={cx(
          "inline-flex h-10 items-center gap-2 whitespace-nowrap rounded-md border px-3 text-[14px] transition-colors data-[state=open]:border-accent",
          filtered ? "border-accent/60 bg-accent-soft/60 text-ink" : "border-rule-strong bg-paper-raised text-ink-muted hover:border-ink-faint",
        )}
      >
        <span className="text-ink-faint">{label}:</span>
        <span className="flex items-center gap-1.5 font-medium text-ink">
          {chosen?.colour && <span aria-hidden="true" className="size-2 rounded-full" style={{ background: chosen.colour }} />}
          {chosen?.label ?? options[0]?.label}
        </span>
        <ChevronDown className="size-4 text-ink-faint" aria-hidden="true" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align="start"
          sideOffset={6}
          className="z-50 max-h-[60vh] min-w-56 origin-[var(--radix-dropdown-menu-content-transform-origin)] animate-rise overflow-y-auto rounded-lg border border-rule bg-paper-raised p-1.5 shadow-lift"
        >
          {options.map((o) => (
            <Menu.Item key={o.href} asChild>
              <Link
                href={o.href}
                scroll={false}
                className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[14px] text-ink-muted outline-none data-[highlighted]:bg-paper-sunk data-[highlighted]:text-ink"
              >
                <span className="flex size-4 items-center justify-center">
                  {o.current ? (
                    <Check className="size-4 text-accent" aria-hidden="true" />
                  ) : (
                    o.colour && <span aria-hidden="true" className="size-2 rounded-full" style={{ background: o.colour }} />
                  )}
                </span>
                <span className={cx("flex-1", o.current && "font-medium text-ink")}>{o.label}</span>
                {o.count !== undefined && <span className="tabular-nums text-[12px] text-ink-faint">{o.count}</span>}
              </Link>
            </Menu.Item>
          ))}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
