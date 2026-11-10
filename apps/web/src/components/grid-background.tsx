"use client";

import { useEffect, useRef, useState } from "react";

const CELL = 32;

type Beam = { id: number; axis: "x" | "y"; at: number; delay: number; duration: number };

const rand = (n: number) => Math.floor(Math.random() * n);

function beam(cols: number, rows: number, id: number, first = false): Beam {
  const axis = id % 2 === 0 ? "x" : "y";
  return {
    id,
    axis,
    at: (axis === "x" ? rand(rows) : rand(cols)) * CELL,
    delay: first ? Math.random() * 6 : Math.random() * 2,
    duration: 4 + Math.random() * 4,
  };
}

/**
 * An animated grid behind the home page, where only the lines glow: a slow wave of glowing lines,
 * beams of light gliding along the lines, and a spotlight on the lines around the pointer.
 * Faded towards the edges. Plain lines for reduced motion.
 */
export function GridBackground({ density = 1 }: { density?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ cols: 0, rows: 0 });
  const [beams, setBeams] = useState<Beam[]>([]);

  // Beam positions are random, so they're made in the browser only, sized to the space the grid covers.
  useEffect(() => {
    const el = box.current;
    if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const fit = () => {
      const cols = Math.ceil(el.clientWidth / CELL);
      const rows = Math.ceil(el.clientHeight / CELL);
      setSize({ cols, rows });
      setBeams(Array.from({ length: Math.round(8 * density) }, (_, i) => beam(cols, rows, i, true)));
    };
    const id = setTimeout(fit, 0);
    const ro = new ResizeObserver(() => fit());
    ro.observe(el);
    return () => {
      clearTimeout(id);
      ro.disconnect();
    };
  }, [density]);

  // The spotlight follows the pointer (mouse only; touch has no hover).
  useEffect(() => {
    const el = box.current;
    if (!el || !matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    const move = (e: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${e.clientX - r.left}px`);
        el.style.setProperty("--my", `${e.clientY - r.top}px`);
        el.style.setProperty("--spot", e.clientY >= r.top && e.clientY <= r.bottom ? "1" : "0");
      });
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", move);
    };
  }, []);

  const moveBeam = (id: number) => setBeams((all) => all.map((b) => (b.id === id ? beam(size.cols, size.rows, id) : b)));

  return (
    <div
      ref={box}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden [mask-image:radial-gradient(ellipse_80%_75%_at_50%_45%,#000_30%,transparent_100%)]"
    >
      {/* the lines */}
      <svg className="absolute inset-0 h-full w-full">
        <defs>
          <pattern id="kb-grid" width={CELL} height={CELL} patternUnits="userSpaceOnUse" x="-1" y="-1">
            <path d={`M ${CELL} 0 L 0 0 0 ${CELL}`} fill="none" stroke="var(--rule)" strokeWidth="1" />
          </pattern>
          <pattern id="kb-grid-lit" width={CELL} height={CELL} patternUnits="userSpaceOnUse" x="-1" y="-1">
            <path d={`M ${CELL} 0 L 0 0 0 ${CELL}`} fill="none" stroke="var(--accent)" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#kb-grid)" />
      </svg>

      {/* a wave of glowing lines that sweeps slowly across the grid */}
      <svg className="kb-sweep absolute inset-0 h-full w-full">
        <rect width="100%" height="100%" fill="url(#kb-grid-lit)" />
      </svg>

      {/* the spotlight: the same lines in the accent colour, shown only near the pointer */}
      <svg
        className="kb-spot absolute inset-0 h-full w-full"
        style={{
          maskImage: "radial-gradient(180px circle at var(--mx, -999px) var(--my, -999px), #000, transparent 70%)",
          WebkitMaskImage: "radial-gradient(180px circle at var(--mx, -999px) var(--my, -999px), #000, transparent 70%)",
        }}
      >
        <rect width="100%" height="100%" fill="url(#kb-grid-lit)" />
      </svg>

      {/* beams gliding along the lines */}
      {beams.map((b) => (
        <span
          key={`${b.id}-${b.at}`}
          className={b.axis === "x" ? "kb-beam-x" : "kb-beam-y"}
          style={{
            ...(b.axis === "x" ? { top: b.at - 1 } : { left: b.at - 1 }),
            animationDelay: `${b.delay}s`,
            animationDuration: `${b.duration}s`,
          }}
          onAnimationIteration={() => moveBeam(b.id)}
        />
      ))}
    </div>
  );
}
