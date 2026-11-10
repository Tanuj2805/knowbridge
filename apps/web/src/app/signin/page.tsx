import { ArrowLeft, ArrowRight, Check, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, demoMode, devLogin, oauthProviders, signIn } from "@/auth";
import { GridBackground } from "@/components/grid-background";
import { ThemeToggle } from "@/components/theme-toggle";
import { Avatar, Wordmark, buttonClass, cx } from "@/components/ui";
import { PERSONAS } from "@/lib/personas";

export const metadata: Metadata = { title: "Sign in" };

const AFTER = "/dashboard";

export default async function SignInPage() {
  const session = await auth();
  if (session?.user) redirect(AFTER);

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
          <h1 className="font-display text-[2.2rem] leading-tight tracking-[-0.035em] text-ink">Sign in</h1>
          <p className="mt-1.5 text-[15px] text-ink-muted">Open your KnowBridge workspace.</p>

          {oauthProviders.length > 0 && (
            <div className="mt-7 grid gap-2">
              {oauthProviders.map((p) => (
                <form
                  key={p.id}
                  action={async () => {
                    "use server";
                    await signIn(p.id, { redirectTo: AFTER });
                  }}
                >
                  <button className={cx(buttonClass("secondary"), "h-11 w-full")}>Continue with {p.name}</button>
                </form>
              ))}
            </div>
          )}

          {demoMode && (
            <div className="mt-8">
              <div className="flex items-center gap-3">
                <span className="h-px flex-1 bg-rule" />
                <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-faint">Try the demo as</p>
                <span className="h-px flex-1 bg-rule" />
              </div>
              <p className="mt-3 text-center text-[13px] text-ink-muted">
                Project Nimbus, a made-up college fest app. Pick who you want to be.
              </p>
              <ul className="stagger mt-4 border-t border-rule">
                {PERSONAS.map((p) => (
                  <li key={p.id}>
                    <form
                      action={async () => {
                        "use server";
                        await signIn("demo", { persona: p.id, redirectTo: AFTER });
                      }}
                    >
                      <button className="group flex w-full items-center gap-3 border-b border-rule py-3.5 text-left transition-colors">
                        <Avatar name={p.name} size={38} />
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="text-[15px] font-medium text-ink transition-colors group-hover:text-accent">{p.name}</span>
                            <span className="text-[12px] text-ink-faint">
                              {p.role}
                            </span>
                          </span>
                          <span className="mt-0.5 block text-[13px] leading-snug text-ink-muted">{p.blurb}</span>
                        </span>
                        <ArrowRight
                          className="size-4 shrink-0 text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent"
                          aria-hidden="true"
                        />
                      </button>
                    </form>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {devLogin && (
            <div className="mt-10 border-t border-ink/80 pt-4">
              <p className="text-[14px] font-semibold text-ink">Sign in as a teammate</p>
              <p className="mt-0.5 text-[13px] text-ink-muted">
                For trying KnowBridge on this computer: use the email of someone you added to a project. Only works
                when DEV_LOGIN=true, and never on a live site.
              </p>
              <form
                className="mt-3 flex gap-2"
                action={async (form: FormData) => {
                  "use server";
                  await signIn("dev", { email: String(form.get("email") ?? ""), redirectTo: AFTER });
                }}
              >
                <label htmlFor="dev-email" className="sr-only">
                  Email
                </label>
                <input
                  id="dev-email"
                  name="email"
                  type="email"
                  required
                  placeholder="teammate@company.com"
                  className="h-9 min-w-0 flex-1 rounded-lg border border-rule-strong bg-paper-raised px-3 text-[14px] shadow-card focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/15"
                />
                <button className={buttonClass("secondary")}>Sign in</button>
              </form>
            </div>
          )}

          {!demoMode && oauthProviders.length === 0 && (
            <p className="mt-6 text-sm text-ink-muted">
              No sign-in method is set up. Add GitHub or Google OAuth keys, or set DEMO_MODE=true.
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
