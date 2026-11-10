import { Lock } from "lucide-react";
import { Fragment } from "react";
import type { Sensitivity } from "@/lib/types";
import { cx } from "./ui";

const MASK = /\[REDACTED:([a-z0-9-]+)\]/g;

const MASK_LABEL: Record<string, string> = {
  "github-token": "GitHub token",
  "aws-key": "AWS key",
  "google-api-key": "Google API key",
  "slack-token": "Slack token",
  "slack-webhook": "Slack webhook",
  "discord-webhook": "Discord webhook",
  "stripe-key": "Stripe key",
  "razorpay-key": "Razorpay key",
  "openai-key": "API key",
  "anthropic-key": "API key",
  "firebase-key": "Firebase key",
  "private-key": "private key",
  jwt: "token",
  password: "password",
  secret: "secret",
  email: "email",
  phone: "phone number",
  "upi-id": "UPI ID",
  "card-number": "card number",
  aadhaar: "Aadhaar number",
  pan: "PAN",
  ifsc: "IFSC",
  "bank-account": "bank account",
};

/** Shows Sentinel's placeholders as small "masked" marks instead of raw tokens. */
export function RedactedText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(MASK);
  return (
    <span className={className}>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <span
            key={i}
            title="Masked by Sentinel before storage. The original value was never kept."
            className="mx-px inline-block rounded-md border border-dashed border-rule-strong bg-paper-sunk px-1 align-baseline tabular-nums text-[0.78em] text-ink-muted"
          >
            {MASK_LABEL[part] ?? part.replace(/-/g, " ")} masked
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </span>
  );
}

export function SensitivityTag({ value, quiet }: { value: Sensitivity; quiet?: boolean }) {
  if (value === "team" && quiet) return null;
  const styles: Record<Sensitivity, string> = {
    team: "bg-paper-sunk text-ink-muted ring-rule",
    restricted: "bg-[var(--grade-conflicting-bg)] text-[var(--grade-conflicting)] ring-[var(--grade-conflicting)]/25",
    confidential: "bg-[var(--grade-missing-bg)] text-[var(--grade-missing)] ring-[var(--grade-missing)]/25",
  };
  const label = { team: "Team", restricted: "Restricted", confidential: "Confidential" }[value];
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] font-medium ring-1 ring-inset", styles[value])}>
      {value !== "team" && <Lock className="size-3" aria-hidden="true" />}
      {label}
    </span>
  );
}

/** What kind of item a piece of evidence is (a commit, a message, a meeting…), as a small badge. */
export function KindTag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-paper-sunk px-1.5 py-0.5 text-[11px] font-medium text-ink-muted">
      {children}
    </span>
  );
}
