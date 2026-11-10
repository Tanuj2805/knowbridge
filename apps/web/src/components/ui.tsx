import clsx from "clsx";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

export { clsx as cx };

type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

const BUTTON: Record<ButtonVariant, string> = {
  primary: "bg-btn text-on-btn hover:bg-btn-hover border border-transparent",
  secondary: "bg-transparent text-ink border border-rule-strong hover:border-ink-faint hover:bg-paper-raised",
  quiet: "text-ink-muted hover:text-ink hover:bg-paper-sunk border border-transparent",
  danger: "bg-transparent text-danger border border-rule-strong hover:border-danger",
};

export function buttonClass(variant: ButtonVariant = "primary", size: "sm" | "md" = "md") {
  return clsx(
    "inline-flex items-center justify-center gap-2 rounded-md font-medium",
    // Press feedback (scale 0.97), short and ease-out; nothing moves for people who ask for less motion.
    "transition-[color,background-color,border-color,transform] duration-150 ease-out motion-safe:active:scale-[0.97]",
    "disabled:opacity-45 disabled:pointer-events-none whitespace-nowrap",
    size === "md" ? "h-10 px-4 text-[14px]" : "h-8 px-3 text-[13px]",
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

/** A small turning ring for buttons that are busy. */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={clsx(
        "inline-block size-4 rounded-full border-2 border-current border-r-transparent motion-safe:animate-spin",
        className,
      )}
    />
  );
}

/** A red asterisk for a field that must be filled in (read aloud as "required"). */
export function RequiredMark() {
  return (
    <>
      <span aria-hidden="true" className="ml-0.5 text-danger">
        *
      </span>
      <span className="sr-only"> (required)</span>
    </>
  );
}

/** The line at the top of a form that explains the asterisks. */
export function RequiredNote({ className }: { className?: string }) {
  return (
    <p className={clsx("text-[12px] text-ink-faint", className)}>
      Fields marked <span className="text-danger">*</span> are required.
    </p>
  );
}

export function Label({
  children,
  hint,
  htmlFor,
  required,
}: {
  children: ReactNode;
  hint?: ReactNode;
  htmlFor?: string;
  required?: boolean;
}) {
  return (
    <label htmlFor={htmlFor} className="block mb-1.5">
      <span className="text-[14px] font-medium text-ink">
        {children}
        {required && <RequiredMark />}
      </span>
      {hint && <span className="block text-[13px] text-ink-faint mt-0.5">{hint}</span>}
    </label>
  );
}

/** The message under a field that wasn't filled in right. */
export function FieldError({ children, id }: { children?: ReactNode; id?: string }) {
  if (!children) return null;
  return (
    <p id={id} role="alert" className="mt-1.5 text-[13px] font-medium text-danger">
      {children}
    </p>
  );
}

const FIELD =
  "w-full rounded-md border border-rule-strong bg-paper-raised px-3 text-[14px] text-ink placeholder:text-ink-faint " +
  "transition-[border-color,box-shadow] duration-150 focus:outline-none focus:border-accent focus:ring-3 focus:ring-accent/15";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={clsx(FIELD, "h-10", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={clsx(FIELD, "py-2 leading-relaxed", className)} {...props} />;
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={clsx(FIELD, "h-10 pr-8", className)} {...props} />;
}

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info" | "teal";

const TONE_COLOUR: Record<Exclude<Tone, "neutral">, string> = {
  accent: "var(--accent)",
  success: "var(--grade-verified)",
  warning: "var(--grade-conflicting)",
  danger: "var(--grade-missing)",
  info: "var(--grade-supported)",
  teal: "var(--grade-attested)",
};

/**
 * A label. Neutral ones are a quiet outlined word; coloured ones are a dot and a word in that colour,
 * so status reads at a glance without filling the page with pills.
 */
export function Tag({
  children,
  tone = "neutral",
  title,
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  /** Kept for older call sites; coloured tags always have their dot. */
  dot?: boolean;
  title?: string;
  className?: string;
}) {
  if (tone === "neutral") {
    return (
      <span
        title={title}
        className={clsx(
          "inline-flex items-center gap-1 whitespace-nowrap rounded border border-rule-strong px-1.5 py-px text-[12px] font-medium text-ink-muted",
          className,
        )}
      >
        {children}
      </span>
    );
  }
  return (
    <span
      title={title}
      style={{ color: TONE_COLOUR[tone] }}
      className={clsx("inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] font-medium", className)}
    >
      <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-current" />
      {children}
    </span>
  );
}

/**
 * A section of a page: a hairline on top, then its content. Content sits on the page's ground
 * rather than in a box; `framed` gives a white panel for the few things that need one (forms, menus).
 */
export function Card({
  children,
  className,
  lift,
  framed,
  as: As = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  lift?: boolean;
  framed?: boolean;
  as?: "div" | "section" | "li" | "article" | "aside";
} & Omit<ComponentProps<"div">, "children" | "className">) {
  return (
    <As
      className={clsx(
        framed ? "rounded-lg border border-rule bg-paper-raised p-5" : "border-t border-ink/80 pt-4",
        lift && "lift",
        className,
      )}
      {...(rest as object)}
    >
      {children}
    </As>
  );
}

/** A section's title row: its name and a line of explanation on the left, an action on the right. */
export function CardHeader({
  title,
  children,
  action,
  className,
}: {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex flex-wrap items-start justify-between gap-x-6 gap-y-2", className)}>
      <div className="min-w-0 max-w-2xl">
        <h2 className="font-display text-[1.2rem] leading-snug text-ink">{title}</h2>
        {children && <div className="mt-1 text-[14px] leading-relaxed text-ink-muted">{children}</div>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  );
}

/** Numbers across the top of a page, in one ruled strip (two a row on phones, four on wide screens). */
export function StatStrip({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <section
      aria-label={label ?? "At a glance"}
      className={clsx(
        "grid grid-cols-2 border-y border-rule lg:grid-flow-col lg:auto-cols-fr lg:grid-cols-none",
        "[&>*]:py-5 max-lg:[&>*:nth-child(even)]:border-l max-lg:[&>*:nth-child(even)]:border-rule max-lg:[&>*:nth-child(even)]:pl-5",
        "max-lg:[&>*:nth-child(n+3)]:border-t max-lg:[&>*:nth-child(n+3)]:border-rule",
        "lg:[&>*:not(:first-child)]:border-l lg:[&>*:not(:first-child)]:border-rule lg:[&>*:not(:first-child)]:pl-6",
      )}
    >
      {children}
    </section>
  );
}

/** One number in a StatStrip. */
export function Stat({ label, value, hint, href }: { label: string; value: ReactNode; hint?: ReactNode; href?: string }) {
  const body = (
    <>
      <p className="text-[13px] text-ink-muted">{label}</p>
      <p className="mt-1.5 font-display text-[2rem] leading-none tracking-[-0.035em] tabular-nums text-ink">{value}</p>
      {hint && <p className="mt-1.5 text-[12px] text-ink-faint">{hint}</p>}
    </>
  );
  return href ? (
    <Link href={href} className="group block pr-4 [&>p:nth-child(2)]:transition-colors hover:[&>p:nth-child(2)]:text-accent">
      {body}
    </Link>
  ) : (
    <div className="pr-4">{body}</div>
  );
}

/** A thin progress bar. `live` adds a moving sheen while work is happening. */
export function Progress({
  value,
  label,
  tone = "accent",
  live,
  size = "md",
}: {
  value: number;
  label: string;
  tone?: "accent" | "success";
  live?: boolean;
  size?: "sm" | "md";
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      className={clsx("relative w-full overflow-hidden rounded-full bg-paper-sunk", size === "sm" ? "h-1" : "h-1.5")}
    >
      <div
        className={clsx(
          "relative h-full overflow-hidden rounded-full transition-[width] duration-500 ease-out",
          tone === "success" ? "bg-[var(--grade-verified)]" : "bg-accent",
        )}
        style={{ width: `${pct}%` }}
      >
        {live && (
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-white/50 to-transparent motion-safe:animate-shimmer"
          />
        )}
      </div>
    </div>
  );
}

export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="group inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-muted hover:text-ink print:hidden"
    >
      <ArrowLeft className="size-3.5 transition-transform duration-150 group-hover:-translate-x-0.5" aria-hidden="true" />
      {children}
    </Link>
  );
}

export function PageHeader({
  eyebrow,
  title,
  children,
  actions,
  back,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <header className="mb-8">
      {back && (
        <div className="mb-4">
          <BackLink href={back.href}>{back.label}</BackLink>
        </div>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0 max-w-3xl">
          {eyebrow && <div className="mb-2 text-[13px] text-ink-muted">{eyebrow}</div>}
          <h1 className="font-display text-[2rem] leading-[1.08] tracking-[-0.035em] text-ink sm:text-[2.4rem]">
            {title}
          </h1>
          {children && <div className="mt-2.5 text-[15px] leading-relaxed text-ink-muted">{children}</div>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export function EmptyState({
  title,
  children,
  action,
  icon,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="animate-rise border-y border-rule px-2 py-14 text-center">
      {icon && <span className="mx-auto mb-3 flex justify-center text-ink-faint">{icon}</span>}
      <p className="font-display text-[1.25rem] text-ink">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-[14px] leading-relaxed text-ink-muted">{children}</div>}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="border-l-2 border-danger pl-3 text-[14px] text-danger">
      {children}
    </p>
  );
}

/** The KnowBridge mark: a span between two piers. */
export function Wordmark({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-2 text-ink", className)}>
      <svg width="28" height="20" viewBox="0 0 26 18" fill="none" aria-hidden="true">
        <path d="M1.5 15.5h23" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M3 15.5C6 6.5 20 6.5 23 15.5" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" />
        <path d="M8 15.5V10.6M13 15.5V8.6M18 15.5V10.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
      {!compact && <span className="font-display text-[18px] tracking-[-0.03em]">KnowBridge</span>}
    </span>
  );
}

const AVATAR_TONES = [
  ["#dff3e5", "#1f6b3a"],
  ["#e3ecff", "#1d4ed8"],
  ["#fbefd6", "#8a4f06"],
  ["#dcf3f0", "#0f766e"],
  ["#ececec", "#3d3d3d"],
  ["#e7f0dc", "#4d6b1f"],
];

/** Initials on a soft colour that stays the same for the same name. */
export function Avatar({ name, src, size = 28 }: { name: string; src?: string | null; size?: number }) {
  const initials = name
    .split(/\s+/)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt="" width={size} height={size} className="rounded-full ring-1 ring-rule" />;
  }
  const hash = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const [bg, fg] = AVATAR_TONES[hash % AVATAR_TONES.length];
  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size, fontSize: size * 0.38, background: bg, color: fg }}
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold"
    >
      {initials}
    </span>
  );
}
