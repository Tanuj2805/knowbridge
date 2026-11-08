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
            className="inline-block rounded-[3px] bg-paper-sunk border border-rule-strong px-1 mx-px font-mono text-[0.78em] text-ink-muted align-baseline"
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
    team: "text-ink-muted border-rule-strong",
    restricted: "text-[var(--grade-conflicting)] border-[color:var(--grade-conflicting)]/40 bg-[var(--grade-conflicting-bg)]",
    confidential: "text-[var(--grade-missing)] border-[color:var(--grade-missing)]/40 bg-[var(--grade-missing-bg)]",
  };
  const label = { team: "Team", restricted: "Restricted", confidential: "Confidential" }[value];
  return (
    <span className={cx("inline-flex items-center rounded-[4px] border px-1.5 py-px text-[12px] font-medium", styles[value])}>
      {label}
    </span>
  );
}

export function KindTag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-block font-mono text-[11px] uppercase tracking-[0.06em] text-ink-faint">{children}</span>
  );
}
