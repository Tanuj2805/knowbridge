import type { Metadata } from "next";
import Link from "next/link";
import { AuthShell } from "@/components/auth/auth-shell";
import { ForgotForm } from "@/components/auth/forms";

export const metadata: Metadata = { title: "Reset your password" };

export default function ForgotPasswordPage() {
  return (
    <AuthShell title="Reset your password" lead="Enter your email and we'll send you a 6-digit code to set a new one.">
      <ForgotForm />
      <p className="mt-6 text-center text-[14px] text-ink-muted">
        Remembered it?{" "}
        <Link href="/signin" className="font-medium text-accent underline-offset-2 hover:underline">
          Back to sign in
        </Link>
      </p>
    </AuthShell>
  );
}
