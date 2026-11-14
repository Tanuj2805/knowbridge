import { ArrowLeft, Check, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { GridBackground } from "@/components/grid-background";
import { ThemeToggle } from "@/components/theme-toggle";
import { Wordmark } from "@/components/ui";

/** The sign-in, sign-up and password pages: the brand on the left, the form on the right. */
export function AuthShell({ title, lead, children }: { title: string; lead?: ReactNode; children: ReactNode }) {
  return (
    <main className="grid flex-1 lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-rule lg:flex lg:flex-col lg:justify-between lg:px-14 lg:py-10">
        <GridBackground density={0.8} />
        <Link href="/" className="relative w-fit rounded-md">
          <Wordmark />
        </Link>

        <div className="relative animate-rise">
          <p className="font-display text-[clamp(3.5rem,7vw,6.5rem)] leading-[0.92] tracking-[-0.055em] text-ink">
            Know<span className="text-accent">Bridge</span>
          </p>
          <p className="mt-6 max-w-md text-[17px] leading-relaxed text-ink-muted">
            Handover documents where every line links to the commit, ticket or message it came from.
          </p>
          <ul className="mt-8 grid gap-2.5 text-[15px] text-ink-muted">
            {["Nine agents build a checked record", "Secrets masked before anything is stored", "Nothing shared until a person approves"].map(
              (t) => (
                <li key={t} className="flex items-center gap-2.5">
                  <Check className="size-4 text-accent" aria-hidden="true" />
                  {t}
                </li>
              ),
            )}
          </ul>
        </div>

        <p className="relative flex items-center gap-2 text-[13px] text-ink-faint">
          <ShieldCheck className="size-4" aria-hidden="true" />
          Built for student clubs and small teams.
        </p>
      </section>

      <section className="flex flex-col px-5 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Link href="/" className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-muted hover:text-ink">
            <ArrowLeft className="size-3.5" aria-hidden="true" />
            Home
          </Link>
          <ThemeToggle />
        </div>

        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10 animate-rise">
          <div className="mb-8 lg:hidden">
            <Wordmark />
          </div>
          <h1 className="font-display text-[2.2rem] leading-tight tracking-[-0.035em] text-ink">{title}</h1>
          {lead && <p className="mt-1.5 text-[15px] text-ink-muted">{lead}</p>}
          {children}
        </div>
      </section>
    </main>
  );
}
