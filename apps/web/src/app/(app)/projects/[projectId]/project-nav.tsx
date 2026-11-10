"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/components/ui";

export type Tab = { href: string; label: string; count?: number };

/** The project's sections, as tabs under its name. */
export function ProjectNav({ base, tabs }: { base: string; tabs: Tab[] }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Project sections" className="-mb-px flex gap-1 overflow-x-auto [scrollbar-width:none]">
      {tabs.map((t) => {
        const href = `${base}${t.href}`;
        const active = t.href === "" ? pathname === base : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={t.href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cx(
              "group relative flex shrink-0 items-center gap-1.5 px-3 pb-3 pt-2 text-[14px] transition-colors duration-150 first:pl-0",
              active ? "font-medium text-ink" : "text-ink-muted hover:text-ink",
            )}
          >
            {t.label}
            {t.count !== undefined && t.count > 0 && (
              <span
                className={cx("tabular-nums text-[11px] ", active ? "text-accent" : "text-ink-faint")}
              >
                {t.count.toLocaleString("en-IN")}
              </span>
            )}
            <span
              aria-hidden="true"
              className={cx(
                "absolute bottom-0 left-3 right-3 h-[2px] origin-left bg-accent transition-transform duration-200 ease-out group-first:left-0",
                active ? "scale-x-100" : "scale-x-0 group-hover:scale-x-100 group-hover:bg-rule-strong",
              )}
            />
          </Link>
        );
      })}
    </nav>
  );
}
