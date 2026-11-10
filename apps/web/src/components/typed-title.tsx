"use client";

import { Fragment, useEffect, useState } from "react";

type Part = { text: string; kind?: "underline" | "gradient" } | { br: true };

const PARTS: Part[] = [
  { text: "Hand over the " },
  { text: "work", kind: "underline" },
  { text: " with" },
  { br: true },
  { text: "KnowBridge", kind: "gradient" },
];

const FULL = PARTS.map((p) => ("br" in p ? " " : p.text)).join("");
const TOTAL = PARTS.reduce((n, p) => n + ("br" in p ? 0 : p.text.length), 0);
/** Where each part starts and ends, counted in typed letters. */
const SPANS = PARTS.reduce<{ start: number; end: number }[]>((acc, p) => {
  const start = acc.length ? acc[acc.length - 1].end : 0;
  return [...acc, { start, end: start + ("br" in p ? 0 : p.text.length) }];
}, []);
const START_MS = 150;
const STEP_MS = 28;

/**
 * The home page title, typed out letter by letter with a caret. The whole title is laid out from the
 * start (untyped letters are just invisible), so nothing moves while it types. Screen readers get the
 * full title at once; people who ask for less motion see it whole.
 */
export function TypedTitle({ className }: { className?: string }) {
  const [typed, setTyped] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      const id = setTimeout(() => {
        setTyped(TOTAL);
        setDone(true);
      }, 0);
      return () => clearTimeout(id);
    }
    let n = 0;
    let timer = 0;
    const tick = () => {
      n += 1;
      setTyped(n);
      if (n < TOTAL) {
        // A slightly longer beat after each word, like a person typing.
        const next = FULL[n - 1] === " " ? STEP_MS * 1.6 : STEP_MS + Math.random() * 12;
        timer = window.setTimeout(tick, next);
      } else {
        setDone(true);
      }
    };
    timer = window.setTimeout(tick, START_MS);
    return () => clearTimeout(timer);
  }, []);

  const caret = <span aria-hidden="true" className={`kb-caret ${done ? "kb-caret-blink" : ""}`} />;

  return (
    <h1 className={className} aria-label={FULL}>
      <span aria-hidden="true">
        {PARTS.map((part, i) => {
          if ("br" in part) return <br key={i} />;
          const { start, end } = SPANS[i];
          const shown = Math.max(0, Math.min(part.text.length, typed - start));
          // The caret sits just after the last typed letter (at the very start before anything is typed).
          const caretHere = typed === 0 ? i === 0 : typed > start && typed <= end;
          const body = (
            <>
              {part.text.slice(0, shown)}
              {caretHere && caret}
              <span className="invisible">{part.text.slice(shown)}</span>
            </>
          );
          if (part.kind === "underline") {
            return (
              <span key={i} className="relative inline-block">
                {body}
                {shown === part.text.length && (
                  <svg
                    viewBox="0 0 300 24"
                    preserveAspectRatio="none"
                    className="kb-underline absolute -bottom-[0.12em] left-[-2%] h-[0.22em] w-[104%]"
                  >
                    <path
                      d="M4 16 C 70 6, 150 4, 296 12"
                      pathLength={1}
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="9"
                      strokeLinecap="round"
                    />
                  </svg>
                )}
              </span>
            );
          }
          if (part.kind === "gradient") {
            return (
              <span key={i} className="kb-gradient-text">
                {body}
              </span>
            );
          }
          return <Fragment key={i}>{body}</Fragment>;
        })}
      </span>
    </h1>
  );
}
