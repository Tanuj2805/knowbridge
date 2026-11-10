"use client";

import { Moon, Sun } from "lucide-react";
import type { MouseEvent } from "react";

type Theme = "light" | "dark";

function current(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const SUN = `<svg viewBox="0 0 120 120" width="120" height="120" aria-hidden="true">
  <defs><radialGradient id="kb-sun-glow"><stop offset="0" stop-color="#fde68a"/><stop offset="1" stop-color="#fde68a" stop-opacity="0"/></radialGradient></defs>
  <circle cx="60" cy="60" r="58" fill="url(#kb-sun-glow)"/>
  <g class="kb-sun-rays" stroke="#f59e0b" stroke-width="5" stroke-linecap="round">
    <path d="M60 10v12M60 98v12M10 60h12M98 60h12M24.6 24.6l8.5 8.5M86.9 86.9l8.5 8.5M24.6 95.4l8.5-8.5M86.9 33.1l8.5-8.5"/>
  </g>
  <circle cx="60" cy="60" r="22" fill="#fbbf24" stroke="#f59e0b" stroke-width="3"/>
</svg>`;

const MOON = `<svg viewBox="0 0 120 120" width="120" height="120" aria-hidden="true">
  <defs><radialGradient id="kb-moon-glow"><stop offset="0" stop-color="#93c5fd" stop-opacity=".55"/><stop offset="1" stop-color="#93c5fd" stop-opacity="0"/></radialGradient></defs>
  <circle cx="60" cy="60" r="56" fill="url(#kb-moon-glow)"/>
  <path d="M74 34a28 28 0 1 0 12 38 22 22 0 1 1-12-38z" fill="#e0e7ff" stroke="#c7d2fe" stroke-width="2"/>
  <g fill="#f8fafc">
    <circle class="kb-star" cx="22" cy="30" r="2.2"/>
    <circle class="kb-star" cx="98" cy="22" r="1.8" style="animation-delay:.15s"/>
    <circle class="kb-star" cx="102" cy="84" r="2" style="animation-delay:.3s"/>
    <circle class="kb-star" cx="30" cy="96" r="1.6" style="animation-delay:.45s"/>
    <circle class="kb-star" cx="14" cy="64" r="1.4" style="animation-delay:.6s"/>
  </g>
</svg>`;

/** A sun or a moon that rises out of the toggle while the page changes theme, then fades away. */
function celestial(next: Theme, x: number, y: number) {
  const el = document.createElement("div");
  el.className = `kb-celestial kb-celestial-${next}`;
  el.setAttribute("aria-hidden", "true");
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
  // Its own layer in the view transition, so the circular reveal never clips it.
  el.style.setProperty("view-transition-name", "kb-celestial");
  el.innerHTML = next === "light" ? SUN : MOON;
  el.addEventListener("animationend", (e) => {
    if (e.target === el) el.remove();
  });
  document.body.appendChild(el);
}

/**
 * Switches between light and dark. The new theme spreads out from the button in a circle while a sun
 * (or a moon and stars) rises out of it. Before the first click it follows the device.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const flip = (event: MouseEvent<HTMLButtonElement>) => {
    const root = document.documentElement;
    const next: Theme = current() === "dark" ? "light" : "dark";
    const r = event.currentTarget.getBoundingClientRect();
    const x = r.left + r.width / 2;
    const y = r.top + r.height / 2;
    const apply = () => {
      root.dataset.theme = next;
      try {
        localStorage.setItem("kb-theme", next);
      } catch {}
    };

    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      apply();
      return;
    }

    if (!document.startViewTransition) {
      // Older browsers: colours cross-fade, and the sun or moon still rises.
      root.classList.add("theme-transition");
      apply();
      celestial(next, x, y);
      window.setTimeout(() => root.classList.remove("theme-transition"), 350);
      return;
    }

    const transition = document.startViewTransition(() => {
      apply();
      celestial(next, x, y);
    });
    transition.ready.then(() => {
      const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
      root.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        { duration: 750, easing: "cubic-bezier(0.77, 0, 0.175, 1)", pseudoElement: "::view-transition-new(root)" },
      );
    });
  };

  return (
    <button
      type="button"
      onClick={flip}
      title="Switch light or dark"
      className={
        "relative inline-flex size-9 items-center justify-center overflow-hidden rounded-md text-ink-muted transition-colors hover:bg-paper-sunk hover:text-ink " +
        (className ?? "")
      }
    >
      <Sun className="theme-icon theme-icon-sun size-[18px]" aria-hidden="true" />
      <Moon className="theme-icon theme-icon-moon size-[18px]" aria-hidden="true" />
      <span className="sr-only">Switch between light and dark</span>
    </button>
  );
}
