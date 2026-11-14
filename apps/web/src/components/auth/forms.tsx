"use client";

import { ArrowLeft, Eye, EyeOff, MailCheck } from "lucide-react";
import Link from "next/link";
import { useActionState, useEffect, useRef, useState, useTransition } from "react";
import { SubmitButton } from "@/components/submit-button";
import { FieldError, Input, Label, cx } from "@/components/ui";
import {
  type FormState,
  requestReset,
  resendCode,
  resendResetCode,
  resetPassword,
  signInWithPassword,
  signUp,
  verifyCode,
} from "@/lib/account-actions";

const DIGITS = 6;
const RESEND_AFTER = 60; // seconds; the server allows one new code a minute

function PasswordInput({
  id = "password",
  autoComplete,
  invalid,
}: {
  id?: string;
  autoComplete: "current-password" | "new-password";
  invalid?: boolean;
}) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input
        id={id}
        name="password"
        type={shown ? "text" : "password"}
        autoComplete={autoComplete}
        required
        minLength={autoComplete === "new-password" ? 8 : undefined}
        maxLength={200}
        aria-invalid={invalid || undefined}
        aria-describedby={invalid ? `${id}-error` : undefined}
        className="h-11 pr-11"
      />
      <button
        type="button"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide password" : "Show password"}
        className="absolute right-1.5 top-1/2 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-ink-faint hover:bg-paper-sunk hover:text-ink"
      >
        {shown ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
      </button>
    </div>
  );
}

/**
 * Six boxes for the emailed code. Typing moves to the next box, Backspace goes back, pasting the
 * whole code fills every box, and phones offer the code from the email (one-time-code). When the
 * last digit is typed the form submits itself (`autoSubmit`).
 */
export function CodeInput({ invalid, autoSubmit = true }: { invalid?: boolean; autoSubmit?: boolean }) {
  const [digits, setDigits] = useState<string[]>(Array(DIGITS).fill(""));
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const hidden = useRef<HTMLInputElement>(null);

  useEffect(() => boxes.current[0]?.focus(), []);

  const fill = (start: number, text: string) => {
    const incoming = text.replace(/\D/g, "").slice(0, DIGITS - start).split("");
    if (!incoming.length) return;
    const next = [...digits];
    incoming.forEach((d, i) => (next[start + i] = d));
    setDigits(next);
    const last = Math.min(start + incoming.length, DIGITS - 1);
    boxes.current[last]?.focus();
    if (autoSubmit && next.every(Boolean)) {
      // let React write the hidden field first
      requestAnimationFrame(() => hidden.current?.form?.requestSubmit());
    }
  };

  return (
    <div>
      <input ref={hidden} type="hidden" name="code" value={digits.join("")} />
      <div className="flex justify-between gap-2" role="group" aria-label="6-digit code">
        {digits.map((d, i) => (
          <input
            key={i}
            ref={(el) => {
              boxes.current[i] = el;
            }}
            value={d}
            inputMode="numeric"
            autoComplete={i === 0 ? "one-time-code" : "off"}
            aria-label={`Digit ${i + 1}`}
            aria-invalid={invalid || undefined}
            maxLength={DIGITS}
            onChange={(e) => {
              const v = e.target.value.replace(/\D/g, "");
              if (!v) {
                const next = [...digits];
                next[i] = "";
                setDigits(next);
                return;
              }
              // typing over a filled box replaces its digit; a longer value is autofill or paste
              fill(i, v.length === 2 && d ? v.replace(d, "").slice(-1) || v.slice(-1) : v);
            }}
            onKeyDown={(e) => {
              if (e.key === "Backspace" && !digits[i] && i > 0) {
                const next = [...digits];
                next[i - 1] = "";
                setDigits(next);
                boxes.current[i - 1]?.focus();
                e.preventDefault();
              } else if (e.key === "ArrowLeft" && i > 0) boxes.current[i - 1]?.focus();
              else if (e.key === "ArrowRight" && i < DIGITS - 1) boxes.current[i + 1]?.focus();
            }}
            onPaste={(e) => {
              e.preventDefault();
              fill(i, e.clipboardData.getData("text"));
            }}
            onFocus={(e) => e.target.select()}
            className={cx(
              "h-14 w-full min-w-0 rounded-lg border bg-paper-raised text-center font-mono text-[24px] font-semibold text-ink",
              "transition-[border-color,box-shadow] duration-150 focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/15",
              invalid ? "border-danger" : "border-rule-strong",
            )}
          />
        ))}
      </div>
    </div>
  );
}

/** "Send a new code", available again a minute after the last one. */
function ResendButton({ email, send }: { email: string; send: (email: string) => Promise<{ ok: boolean }> }) {
  const [wait, setWait] = useState(RESEND_AFTER);
  const [pending, start] = useTransition();
  const [sent, setSent] = useState(false);
  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);
  if (wait > 0) {
    return (
      <span className="text-ink-faint">
        {sent ? "New code sent. " : ""}You can ask for a new code in {wait}s
      </span>
    );
  }
  return (
    <button
      type="button"
      disabled={pending}
      onClick={() =>
        start(async () => {
          await send(email);
          setSent(true);
          setWait(RESEND_AFTER);
        })
      }
      className="font-medium text-accent underline-offset-2 hover:underline disabled:opacity-60"
    >
      {pending ? "Sending…" : "Send a new code"}
    </button>
  );
}

/** "We sent a code to …" above the boxes. */
function SentTo({ email, notice }: { email: string; notice?: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
        <MailCheck className="size-5" aria-hidden="true" />
      </span>
      <p className="text-[14px] leading-relaxed text-ink-muted">
        {notice ? `${notice} ` : ""}Enter the 6-digit code we sent to <span className="font-semibold text-ink">{email}</span>.
        It works for 10 minutes. Not there? Check spam.
      </p>
    </div>
  );
}

/** Step 2 of signing up (or of signing in to an unconfirmed account): the code signs them in. */
function VerifyStep({ email, next, notice, onBack }: { email: string; next?: string; notice?: string; onBack: () => void }) {
  const [state, action] = useActionState<FormState, FormData>(verifyCode, { email });
  return (
    <form action={action} className="mt-7 grid gap-5" noValidate>
      <input type="hidden" name="email" value={email} />
      <input type="hidden" name="next" value={next ?? ""} />
      <SentTo email={email} notice={notice} />
      <CodeInput key={state.error ?? "first"} invalid={!!state.error} />
      {state.error && (
        <p role="alert" className="-mt-2 text-[14px] text-danger">
          {state.error}
        </p>
      )}
      <SubmitButton className="h-11 w-full text-[15px]" pendingText="Checking…">
        Confirm and continue
      </SubmitButton>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-ink-muted hover:text-ink">
          <ArrowLeft className="size-3.5" aria-hidden="true" />
          Use a different email
        </button>
        <ResendButton email={email} send={resendCode} />
      </div>
    </form>
  );
}

export function SignInForm({ email: initialEmail = "", next = "" }: { email?: string; next?: string }) {
  const [state, action] = useActionState<FormState, FormData>(signInWithPassword, { email: initialEmail });
  const [dismissed, setDismissed] = useState<FormState>();
  if (state.step === "code" && state.email && state !== dismissed) {
    return <VerifyStep email={state.email} next={next} notice={state.notice} onBack={() => setDismissed(state)} />;
  }
  return (
    <form action={action} className="mt-7 grid gap-4" noValidate>
      <input type="hidden" name="next" value={next} />
      <div>
        <Label htmlFor="email">Email</Label>
        <Input id="email" name="email" type="email" autoComplete="email" required defaultValue={state.email} className="h-11" />
      </div>
      <div>
        <div className="mb-1.5 flex items-baseline justify-between">
          <label htmlFor="password" className="text-[14px] font-medium text-ink">
            Password
          </label>
          <Link href="/forgot-password" className="text-[13px] font-medium text-accent underline-offset-2 hover:underline">
            Forgot password?
          </Link>
        </div>
        <PasswordInput autoComplete="current-password" invalid={!!state.error} />
      </div>
      {state.error && (
        <p id="password-error" role="alert" className="text-[14px] leading-relaxed text-danger">
          {state.error}
        </p>
      )}
      <SubmitButton className="h-11 w-full text-[15px]" pendingText="Signing in…">
        Sign in
      </SubmitButton>
    </form>
  );
}

export function SignUpForm() {
  const [state, action] = useActionState<FormState, FormData>(signUp, {});
  const [dismissed, setDismissed] = useState<FormState>();
  if (state.step === "code" && state.email && state !== dismissed) {
    return <VerifyStep email={state.email} onBack={() => setDismissed(state)} />;
  }
  const err = (f: string) => (state.field === f ? state.error : undefined);
  return (
    <form action={action} className="mt-7 grid gap-4" noValidate>
      <div>
        <Label htmlFor="name">Your name</Label>
        <Input
          id="name"
          name="name"
          autoComplete="name"
          required
          maxLength={200}
          defaultValue={state.name}
          className="h-11"
          aria-invalid={!!err("name") || undefined}
        />
        <FieldError id="name-error">{err("name")}</FieldError>
      </div>
      <div>
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          defaultValue={state.email}
          className="h-11"
          aria-invalid={!!err("email") || undefined}
        />
        <FieldError id="email-error">{err("email")}</FieldError>
      </div>
      <div>
        <Label htmlFor="password" hint="At least 8 characters. A short phrase is easiest to remember.">
          Password
        </Label>
        <PasswordInput autoComplete="new-password" invalid={!!err("password")} />
        <FieldError id="password-error">{err("password")}</FieldError>
      </div>
      {state.error && !state.field && (
        <p role="alert" className="text-[14px] text-danger">
          {state.error}
        </p>
      )}
      <SubmitButton className="h-11 w-full text-[15px]" pendingText="Creating your account…">
        Create account
      </SubmitButton>
      <p className="text-[12px] leading-relaxed text-ink-faint">
        We&apos;ll email you a 6-digit code to confirm it&apos;s you. Your password is stored only as a one-way hash.
      </p>
    </form>
  );
}

/** Forgot password: the email, then the code and a new password together. */
export function ForgotForm() {
  const [asked, ask] = useActionState<FormState, FormData>(requestReset, {});
  const [state, reset] = useActionState<FormState, FormData>(resetPassword, {});
  const [dismissed, setDismissed] = useState<FormState>();
  const email = asked.step === "code" && asked !== dismissed ? asked.email : undefined;

  if (!email) {
    return (
      <form action={ask} className="mt-7 grid gap-4" noValidate>
        <div>
          <Label htmlFor="email">Email</Label>
          <Input id="email" name="email" type="email" autoComplete="email" required defaultValue={asked.email} className="h-11" />
          <FieldError id="email-error">{asked.error}</FieldError>
        </div>
        <SubmitButton className="h-11 w-full text-[15px]" pendingText="Sending…">
          Send me a code
        </SubmitButton>
      </form>
    );
  }
  const codeError = state.field === "code" || (!state.field && state.error) ? state.error : undefined;
  return (
    <form action={reset} className="mt-7 grid gap-5" noValidate>
      <input type="hidden" name="email" value={email} />
      <SentTo email={email} notice="If there's an account with this email, we've sent it a code." />
      <CodeInput key={codeError ?? "first"} invalid={!!codeError} autoSubmit={false} />
      {codeError && (
        <p role="alert" className="-mt-2 text-[14px] text-danger">
          {codeError}
        </p>
      )}
      <div>
        <Label htmlFor="password" hint="At least 8 characters.">
          New password
        </Label>
        <PasswordInput autoComplete="new-password" invalid={state.field === "password"} />
        <FieldError id="password-error">{state.field === "password" ? state.error : undefined}</FieldError>
      </div>
      <SubmitButton className="h-11 w-full text-[15px]" pendingText="Saving…">
        Save new password and sign in
      </SubmitButton>
      <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <button type="button" onClick={() => setDismissed(asked)} className="inline-flex items-center gap-1 text-ink-muted hover:text-ink">
          <ArrowLeft className="size-3.5" aria-hidden="true" />
          Use a different email
        </button>
        <ResendButton email={email} send={resendResetCode} />
      </div>
    </form>
  );
}
