import { cx } from "./ui";

/** The KnowBridge loader: the bridge mark drawing itself, over and over. */
export function Loader({ size = 56, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={(size * 18) / 26}
      viewBox="0 0 26 18"
      fill="none"
      aria-hidden="true"
      className={cx("kb-loader text-accent", className)}
    >
      <path d="M1.5 15.5h23" pathLength={1} stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M3 15.5C6 6.5 20 6.5 23 15.5" pathLength={1} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M8 15.5V10.6" pathLength={1} stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M13 15.5V8.6" pathLength={1} stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M18 15.5V10.6" pathLength={1} stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

/** A whole-area loading state: the loader with a line saying what's coming. */
export function PageLoader({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex min-h-[50vh] flex-col items-center justify-center gap-4 animate-fade">
      <span className="inline-flex size-20 items-center justify-center rounded-2xl border border-rule bg-paper-raised shadow-lift">
        <Loader size={46} />
      </span>
      <p className="text-[13px] font-medium text-ink-muted">
        {label}
        <span className="inline-block w-4 text-left motion-safe:animate-pulse">…</span>
      </p>
    </div>
  );
}
