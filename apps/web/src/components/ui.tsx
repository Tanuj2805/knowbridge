import clsx from "clsx";
import type { ComponentProps, ReactNode } from "react";

export { clsx as cx };

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

const BUTTON: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover border border-transparent",
  secondary: "bg-paper-raised text-ink border border-rule-strong hover:border-ink-faint",
  quiet: "text-ink-muted hover:text-ink hover:bg-paper-sunk border border-transparent",
  danger: "bg-paper-raised text-danger border border-rule-strong hover:border-danger",
};

export function buttonClass(variant: ButtonVariant = "primary", size: "sm" | "md" = "md") {
  return clsx(
    "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors",
    "disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap",
    size === "md" ? "h-9 px-3.5 text-sm" : "h-7 px-2.5 text-[13px]",
    BUTTON[variant],
  );
}

export function Button({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ComponentProps<"button"> & { variant?: ButtonVariant; size?: "sm" | "md" }) {
  return <button className={clsx(buttonClass(variant, size), className)} {...props} />;
}

export function Label({ children, hint, htmlFor }: { children: ReactNode; hint?: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block mb-1.5">
      <span className="text-sm font-medium text-ink">{children}</span>
      {hint && <span className="block text-[13px] text-ink-muted mt-0.5">{hint}</span>}
    </label>
  );
}

const FIELD =
  "w-full rounded-md border border-rule-strong bg-paper-raised px-3 text-[15px] text-ink placeholder:text-ink-faint " +
  "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent-soft";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={clsx(FIELD, "h-9", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={clsx(FIELD, "py-2 leading-relaxed", className)} {...props} />;
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={clsx(FIELD, "h-9 pr-8", className)} {...props} />;
}

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "accent" }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-[4px] px-1.5 py-px text-[12px] font-medium tracking-wide",
        tone === "accent" ? "bg-accent-soft text-accent" : "bg-paper-sunk text-ink-muted",
      )}
    >
      {children}
    </span>
  );
}

export function PageHeader({
  eyebrow,
  title,
  children,
  actions,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between pb-6 border-b border-rule">
      <div className="max-w-2xl">
        {eyebrow && <p className="text-[13px] text-ink-muted mb-1">{eyebrow}</p>}
        <h1 className="font-serif text-[2rem] leading-tight tracking-[-0.01em] text-ink">{title}</h1>
        {children && <div className="mt-2 text-ink-muted leading-relaxed">{children}</div>}
      </div>
      {actions && <div className="flex gap-2 shrink-0">{actions}</div>}
    </header>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="border border-dashed border-rule-strong rounded-lg px-6 py-12 text-center">
      <p className="font-serif text-xl text-ink">{title}</p>
      {children && <div className="mt-2 text-ink-muted max-w-md mx-auto leading-relaxed">{children}</div>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="text-sm text-danger border-l-2 border-danger pl-3 py-1">
      {children}
    </p>
  );
}

/** The KnowBridge mark: two piers and a span, drawn like a pen sketch. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2 text-ink", className)}>
      <svg width="26" height="18" viewBox="0 0 26 18" fill="none" aria-hidden="true">
        <path d="M1.5 15.5h23" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <path d="M3 15.5C6 6.5 20 6.5 23 15.5" stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" />
        <path d="M8 15.5V10.6M13 15.5V8.6M18 15.5V10.6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      </svg>
      <span className="font-serif text-[1.2rem] tracking-[-0.01em] leading-none">KnowBridge</span>
    </span>
  );
}

export function Avatar({ name, src, size = 28 }: { name: string; src?: string | null; size?: number }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt="" width={size} height={size} className="rounded-full border border-rule" />;
  }
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size, fontSize: size * 0.4 }}
      className="inline-flex items-center justify-center rounded-full bg-paper-sunk border border-rule text-ink-muted font-medium"
    >
      {initials}
    </span>
  );
}
