"use server";

import { AuthError, CredentialsSignin } from "next-auth";
import { signIn } from "@/auth";
import { accountsApi } from "@/lib/accounts";

/** What a form shows after a try. `name` and `email` refill the fields (React clears a form after an
 * action); `step: "code"` moves the form on to "enter the 6-digit code". */
export type FormState = {
  error?: string;
  code?: string;
  email?: string;
  name?: string;
  field?: string;
  step?: "code";
  notice?: string;
};

const AFTER = "/dashboard";
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const MESSAGES: Record<string, string> = {
  invalid: "That email and password don't match. Check them, or reset your password.",
  locked: "Too many wrong passwords. Wait 15 minutes, or reset your password.",
  unreachable: "We can't reach the server right now. Try again in a minute.",
  invalid_code: "That code isn't right.",
  too_many: "Too many wrong tries. Send yourself a new code.",
  expired: "That code has expired. Send yourself a new code.",
};

function codeMessage(code: string): string {
  const left = /^invalid_code_(\d+)$/.exec(code)?.[1];
  if (left) return `That code isn't right. ${left} ${left === "1" ? "try" : "tries"} left.`;
  return MESSAGES[code] ?? MESSAGES.invalid_code;
}

function text(form: FormData, key: string): string {
  return String(form.get(key) ?? "").trim();
}

/** Only paths on this site, so a link can't send someone elsewhere after signing in. */
function safeNext(next: string): string {
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : AFTER;
}

/** Runs an Auth.js sign-in; returns the failure's code, or redirects on success. */
async function trySignIn(provider: string, fields: Record<string, string>): Promise<string> {
  try {
    await signIn(provider, { ...fields, redirectTo: safeNext(fields.next ?? "") });
  } catch (e) {
    if (e instanceof CredentialsSignin) return e.code;
    if (e instanceof AuthError) return "invalid";
    throw e; // the redirect after a successful sign-in
  }
  return "";
}

export async function signInWithPassword(_: FormState, form: FormData): Promise<FormState> {
  const email = text(form, "email");
  const password = String(form.get("password") ?? "");
  if (!email || !password) return { error: "Enter your email and password.", email };
  const failed = await trySignIn("password", { email, password, next: text(form, "next") });
  if (failed === "unverified") {
    // the account was never confirmed: send a fresh code and ask for it right here
    await accountsApi("/auth/resend", { email });
    return { step: "code", email, notice: "Your email isn't confirmed yet. We've sent you a new code." };
  }
  return { error: MESSAGES[failed] ?? MESSAGES.invalid, code: failed, email };
}

export async function signUp(_: FormState, form: FormData): Promise<FormState> {
  const name = text(form, "name");
  const email = text(form, "email");
  const password = String(form.get("password") ?? "");
  if (!name) return { error: "Enter your name.", field: "name", email };
  if (!EMAIL.test(email)) return { error: "Enter a valid email address.", field: "email", email, name };
  if (password.length < 8) return { error: "Use at least 8 characters.", field: "password", email, name };
  const r = await accountsApi("/auth/register", { name, email, password });
  if (!r.ok) {
    if (r.code === "weak" || r.code === "invalid_email") {
      return { error: r.message || "Check the details.", field: r.code === "weak" ? "password" : "email", email, name };
    }
    return { error: MESSAGES.unreachable, email, name };
  }
  return { step: "code", email };
}

/** The 6-digit code from the sign-up email: confirms the address and signs in. */
export async function verifyCode(_: FormState, form: FormData): Promise<FormState> {
  const email = text(form, "email");
  const code = text(form, "code").replace(/\D/g, "");
  if (code.length !== 6) return { step: "code", email, error: "Enter all 6 digits." };
  const failed = await trySignIn("email-code", { email, code, next: text(form, "next") });
  return { step: "code", email, error: codeMessage(failed), code: failed };
}

export async function resendCode(email: string): Promise<{ ok: boolean }> {
  return { ok: (await accountsApi("/auth/resend", { email })).ok };
}

export async function requestReset(_: FormState, form: FormData): Promise<FormState> {
  const email = text(form, "email");
  if (!EMAIL.test(email)) return { error: "Enter a valid email address.", email };
  const r = await accountsApi("/auth/forgot", { email });
  return r.ok ? { step: "code", email } : { error: MESSAGES.unreachable, email };
}

export async function resendResetCode(email: string): Promise<{ ok: boolean }> {
  return { ok: (await accountsApi("/auth/forgot", { email })).ok };
}

/** The reset code and a new password: saves it, then signs in with it. */
export async function resetPassword(_: FormState, form: FormData): Promise<FormState> {
  const email = text(form, "email");
  const code = text(form, "code").replace(/\D/g, "");
  const password = String(form.get("password") ?? "");
  if (code.length !== 6) return { step: "code", email, error: "Enter all 6 digits.", field: "code" };
  if (password.length < 8) return { step: "code", email, error: "Use at least 8 characters.", field: "password" };
  const r = await accountsApi<{ email: string }>("/auth/reset", { email, code, password });
  if (!r.ok) {
    if (r.code === "weak") return { step: "code", email, error: r.message, field: "password" };
    if (r.code === "unreachable" || r.status >= 500) return { step: "code", email, error: MESSAGES.unreachable };
    return { step: "code", email, error: r.message || codeMessage(r.code), field: "code", code: r.code };
  }
  const failed = await trySignIn("password", { email, password });
  return { error: MESSAGES[failed] ?? MESSAGES.invalid, email };
}
