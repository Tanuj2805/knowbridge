import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { auth, demoMode } from "@/auth";
import { AuthShell } from "@/components/auth/auth-shell";
import { SignUpForm } from "@/components/auth/forms";
import { accountOptions } from "@/lib/accounts";

export const metadata: Metadata = { title: "Create an account" };

export default async function SignUpPage() {
  const session = await auth();
  if (session?.user) redirect("/dashboard");
  const options = await accountOptions();

  return (
    <AuthShell title="Create your account" lead="Start a project and turn your team's work into a handover anyone can trust.">
      {options.password ? (
        <SignUpForm />
      ) : (
        <p className="mt-6 text-[14px] text-ink-muted">
          Creating accounts isn&apos;t available right now: the server can&apos;t be reached. Try again in a minute.
        </p>
      )}
      <p className="mt-6 text-center text-[14px] text-ink-muted">
        Already have an account?{" "}
        <Link href="/signin" className="font-medium text-accent underline-offset-2 hover:underline">
          Sign in
        </Link>
        {demoMode && (
          <>
            {" "}
            ·{" "}
            <Link href="/signin#demo" className="font-medium text-accent underline-offset-2 hover:underline">
              Try the demo
            </Link>
          </>
        )}
      </p>
    </AuthShell>
  );
}
