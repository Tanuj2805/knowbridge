import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, demoMode, devLogin, signIn } from "@/auth";
import { AuthShell } from "@/components/auth/auth-shell";
import { SignInForm } from "@/components/auth/forms";
import { Avatar, buttonClass } from "@/components/ui";
import { accountOptions } from "@/lib/accounts";
import { PERSONAS } from "@/lib/personas";

export const metadata: Metadata = { title: "Sign in" };

const AFTER = "/dashboard";

export default async function SignInPage({ searchParams }: PageProps<"/signin">) {
  const session = await auth();
  if (session?.user) redirect(AFTER);
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const options = await accountOptions();

  return (
    <AuthShell title="Sign in" lead="Welcome back. Open your KnowBridge workspace.">
      {options.password && (
        <>
          <SignInForm email={one("email")} next={one("next")} />
          <p className="mt-6 text-center text-[14px] text-ink-muted">
            New to KnowBridge?{" "}
            <Link href="/signup" className="font-medium text-accent underline-offset-2 hover:underline">
              Create an account
            </Link>
          </p>
        </>
      )}

      {demoMode && (
        <div id="demo" className="mt-10 scroll-mt-6">
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

      {!demoMode && !options.password && (
        <p className="mt-6 text-sm text-ink-muted">
          Sign-in isn&apos;t available right now: the server can&apos;t be reached. Try again in a minute.
        </p>
      )}
    </AuthShell>
  );
}
