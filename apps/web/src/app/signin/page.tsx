import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { auth, demoMode, oauthProviders, signIn } from "@/auth";
import { Avatar, Wordmark, buttonClass } from "@/components/ui";
import { PERSONAS } from "@/lib/personas";

export const metadata: Metadata = { title: "Sign in" };

export default async function SignInPage() {
  const session = await auth();
  if (session?.user) redirect("/projects");

  return (
    <main className="flex-1 grid lg:grid-cols-[1.1fr_1fr]">
      <section className="hidden lg:flex flex-col justify-between border-r border-rule bg-paper-sunk px-14 py-12">
        <Wordmark />
        <div className="max-w-lg">
          <h1 className="font-serif text-[2.75rem] leading-[1.1] tracking-[-0.015em]">
            Hand over the work, <em className="text-accent">and the reasons behind it.</em>
          </h1>
          <p className="mt-5 text-ink-muted leading-relaxed text-[17px]">
            KnowBridge reads what your team has already written, ties every line of the handover
            to where it came from, and only asks the person leaving about what the record can&apos;t
            answer.
          </p>

          <figure className="mt-10 rounded-lg border border-rule bg-paper-raised p-5 shadow-[0_1px_0_var(--rule)]">
            <p className="text-[12px] uppercase tracking-[0.08em] text-ink-faint">From a handover pack</p>
            <p className="prose-ledger mt-2">
              Payment test mode was dropped on 14 Oct because webhooks kept failing on campus Wi‑Fi.
              <sup className="font-mono text-[11px] text-accent ml-0.5">1,2</sup>
            </p>
            <figcaption className="mt-3 flex items-center gap-3 text-[13px] text-ink-muted">
              <span
                className="rounded-[4px] px-1.5 py-px font-medium"
                style={{ background: "var(--grade-verified-bg)", color: "var(--grade-verified)" }}
              >
                Verified
              </span>
              <span className="font-mono text-[12px]">#payments · PR 38 review</span>
            </figcaption>
          </figure>
        </div>
        <p className="text-[13px] text-ink-faint">Built for student clubs and small teams.</p>
      </section>

      <section className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="w-full max-w-sm mx-auto">
          <div className="lg:hidden mb-10">
            <Wordmark />
          </div>
          <h2 className="font-serif text-2xl">Sign in</h2>

          {oauthProviders.length > 0 && (
            <div className="mt-6 flex flex-col gap-2">
              {oauthProviders.map((p) => (
                <form
                  key={p.id}
                  action={async () => {
                    "use server";
                    await signIn(p.id, { redirectTo: "/projects" });
                  }}
                >
                  <button className={buttonClass("secondary") + " w-full"}>Continue with {p.name}</button>
                </form>
              ))}
            </div>
          )}

          {demoMode && (
            <div className="mt-8">
              <p className="text-sm font-medium">Try the Project Nimbus demo</p>
              <p className="text-[13px] text-ink-muted mt-0.5">
                A made-up college fest app. Pick who you want to be.
              </p>
              <ul className="mt-4 divide-y divide-rule border-y border-rule">
                {PERSONAS.map((p) => (
                  <li key={p.id}>
                    <form
                      action={async () => {
                        "use server";
                        await signIn("demo", { persona: p.id, redirectTo: "/projects" });
                      }}
                    >
                      <button className="w-full flex items-start gap-3 py-3 px-1 text-left hover:bg-paper-sunk rounded-sm transition-colors">
                        <Avatar name={p.name} size={32} />
                        <span className="flex-1 min-w-0">
                          <span className="flex items-baseline justify-between gap-2">
                            <span className="font-medium text-[15px]">{p.name}</span>
                            <span className="text-[12px] text-ink-faint">{p.role}</span>
                          </span>
                          <span className="block text-[13px] text-ink-muted leading-snug">{p.blurb}</span>
                        </span>
                      </button>
                    </form>
                  </li>
                ))}
              </ul>
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
