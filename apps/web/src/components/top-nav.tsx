"use client";

import * as Menu from "@radix-ui/react-dropdown-menu";
import { ChevronDown, FolderKanban, LayoutDashboard, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTransition } from "react";
import { signOutAction } from "@/lib/session-actions";
import { ThemeToggle } from "./theme-toggle";
import { Avatar, Wordmark, cx } from "./ui";

const LINKS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/projects", label: "Projects", icon: FolderKanban },
];

type Me = { name: string; email: string; image?: string | null };

/** The bar across the top of every signed-in page. */
export function TopNav({ me }: { me: Me }) {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-rule bg-paper/90 backdrop-blur-md print:hidden">
      <div className="mx-auto flex h-16 max-w-[80rem] items-center gap-2 px-4 sm:px-6">
        <Link href="/dashboard" className="mr-2 shrink-0 rounded-lg sm:mr-6">
          <span className="hidden sm:inline">
            <Wordmark />
          </span>
          <span className="sm:hidden">
            <Wordmark compact />
          </span>
        </Link>

        <nav aria-label="Main" className="flex items-center gap-1">
          {LINKS.map(({ href, label }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "group relative inline-flex h-16 items-center px-2.5 text-[14px] sm:px-3 transition-colors duration-150",
                  active ? "font-medium text-ink" : "text-ink-muted hover:text-ink",
                )}
              >
                {label}
                <span
                  aria-hidden="true"
                  className={cx(
                    "absolute inset-x-3 bottom-0 h-[2px] origin-left bg-accent transition-transform duration-200 ease-out",
                    active ? "scale-x-100" : "scale-x-0 group-hover:scale-x-100 group-hover:bg-rule-strong",
                  )}
                />
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <UserMenu me={me} />
        </div>
      </div>
    </header>
  );
}

function UserMenu({ me }: { me: Me }) {
  const [signingOut, startSignOut] = useTransition();
  return (
    <Menu.Root>
      <Menu.Trigger
        className="group inline-flex h-10 items-center gap-2 rounded-md pl-1.5 pr-2 transition-colors hover:bg-paper-sunk data-[state=open]:bg-paper-sunk"
        aria-label="Your account"
      >
        <Avatar name={me.name || me.email} src={me.image} size={30} />
        <span className="hidden max-w-[10rem] truncate text-[14px] font-medium text-ink md:inline">{me.name}</span>
        <ChevronDown
          className="size-4 text-ink-faint transition-transform duration-200 group-data-[state=open]:rotate-180"
          aria-hidden="true"
        />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content
          align="end"
          sideOffset={8}
          className="z-50 w-64 origin-[var(--radix-dropdown-menu-content-transform-origin)] animate-rise rounded-lg border border-rule bg-paper-raised p-1.5 shadow-lift"
        >
          <div className="flex items-center gap-3 px-2.5 py-2">
            <Avatar name={me.name || me.email} src={me.image} size={36} />
            <div className="min-w-0">
              <p className="truncate text-[14px] font-semibold text-ink">{me.name}</p>
              <p className="truncate text-[12px] text-ink-faint">{me.email}</p>
            </div>
          </div>
          <Menu.Separator className="my-1.5 h-px bg-rule" />
          {LINKS.map(({ href, label, icon: Icon }) => (
            <Menu.Item key={href} asChild>
              <Link
                href={href}
                className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[14px] text-ink-muted outline-none data-[highlighted]:bg-paper-sunk data-[highlighted]:text-ink"
              >
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </Link>
            </Menu.Item>
          ))}
          <Menu.Separator className="my-1.5 h-px bg-rule" />
          {/* Called from onSelect: a <form> inside the menu is removed as the menu closes, before it can submit. */}
          <Menu.Item
            onSelect={(e) => {
              e.preventDefault(); // keep the menu open until the redirect
              startSignOut(() => signOutAction());
            }}
            disabled={signingOut}
            className="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-[14px] text-ink-muted outline-none data-[highlighted]:bg-[var(--grade-missing-bg)] data-[highlighted]:text-[var(--grade-missing)]"
          >
            <LogOut className="size-4" aria-hidden="true" />
            {signingOut ? "Signing out…" : "Sign out"}
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
