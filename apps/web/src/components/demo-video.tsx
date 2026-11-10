"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Play, X } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { buttonClass, cx } from "./ui";

// The walkthrough video. Served from /public by default; set NEXT_PUBLIC_DEMO_VIDEO_URL to host it
// elsewhere (a CDN or object storage) without changing the code.
const SRC = process.env.NEXT_PUBLIC_DEMO_VIDEO_URL || "/demo/knowbridge-walkthrough.mp4";
const POSTER = "/demo/knowbridge-walkthrough-poster.jpg";
const CAPTIONS = "/demo/knowbridge-walkthrough.vtt";
export const DEMO_LENGTH = "7 min";

/** Where each part of the walkthrough starts, in seconds. */
export const CHAPTERS = [
  { t: 0, label: "The problem" },
  { t: 17, label: "How it works" },
  { t: 48, label: "Four words to know" },
  { t: 101, label: "Create a project and add people" },
  { t: 130, label: "Connect GitHub and Jira" },
  { t: 174, label: "Evidence and Sentinel" },
  { t: 200, label: "AI agents build the claims" },
  { t: 231, label: "The claim ledger" },
  { t: 258, label: "Handover and Gap Interview" },
  { t: 306, label: "Approve and publish" },
  { t: 328, label: "The handover pack" },
  { t: 346, label: "Ask the chat" },
  { t: 376, label: "Guardrails" },
];

const clock = (t: number) => `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;

/** The player window. Opens at `start` seconds; the video stops when it closes. */
function Player({ open, onOpenChange, start }: { open: boolean; onOpenChange: (o: boolean) => void; start: number }) {
  const video = useRef<HTMLVideoElement>(null);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-[#0b1b33]/70 backdrop-blur-sm data-[state=open]:animate-fade" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-5xl -translate-x-1/2 -translate-y-1/2 focus:outline-none data-[state=open]:animate-[kb-dialog_0.22s_cubic-bezier(0.23,1,0.32,1)]"
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            video.current?.focus();
          }}
        >
          <div className="mb-3 flex items-center justify-between gap-4 text-white">
            <div className="min-w-0">
              <Dialog.Title className="font-display text-[1.15rem] tracking-[-0.02em]">KnowBridge, start to finish</Dialog.Title>
              <Dialog.Description className="text-[13px] text-white/70">
                A {DEMO_LENGTH} walkthrough: set up a project, connect sources, build claims, hand over, and ask.
              </Dialog.Description>
            </div>
            <Dialog.Close
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20"
              aria-label="Close the video"
            >
              <X className="size-4" aria-hidden="true" />
            </Dialog.Close>
          </div>
          <video
            ref={video}
            className="aspect-video w-full rounded-xl bg-black shadow-2xl"
            controls
            autoPlay
            playsInline
            preload="metadata"
            poster={POSTER}
            onLoadedMetadata={(e) => {
              if (start) e.currentTarget.currentTime = start;
            }}
          >
            <source src={SRC} type="video/mp4" />
            <track kind="captions" src={CAPTIONS} srcLang="en" label="English" />
            Your browser can&apos;t play this video. <a href={SRC}>Download it</a> instead.
          </video>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function usePlayer() {
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(0);
  const play = (t = 0) => {
    setStart(t);
    setOpen(true);
  };
  return { play, player: <Player open={open} onOpenChange={setOpen} start={start} /> };
}

/** "Watch the video" as a button, for the hero. */
export function WatchVideoButton({ className, children }: { className?: string; children?: ReactNode }) {
  const { play, player } = usePlayer();
  return (
    <>
      <button type="button" onClick={() => play()} className={cx(buttonClass("secondary"), "group", className)}>
        <span className="flex size-6 items-center justify-center rounded-full bg-accent text-on-accent transition-transform duration-150 group-hover:scale-110">
          <Play className="size-3 translate-x-px fill-current" aria-hidden="true" />
        </span>
        {children ?? (
          <>
            Watch the video <span className="text-ink-faint">· {DEMO_LENGTH}</span>
          </>
        )}
      </button>
      {player}
    </>
  );
}

/** The video's poster with a play button, and its chapters: each opens the video at that part. */
export function DemoVideoSection() {
  const { play, player } = usePlayer();
  return (
    <div className="grid items-center gap-8 lg:grid-cols-[1.5fr_1fr] lg:gap-14">
      <button
        type="button"
        onClick={() => play()}
        className="group relative block overflow-hidden rounded-2xl border border-rule bg-paper-sunk shadow-lift"
        aria-label={`Play the ${DEMO_LENGTH} walkthrough video`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- a static poster; no resizing needed */}
        <img src={POSTER} alt="" className="aspect-video w-full object-cover transition-transform duration-500 group-hover:scale-[1.015]" />
        <span className="absolute inset-0 bg-[#0b1b33]/10 transition-colors group-hover:bg-[#0b1b33]/20" />
        <span className="absolute left-1/2 top-1/2 flex size-20 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-accent text-on-accent shadow-lift transition-transform duration-200 group-hover:scale-110">
          <Play className="size-8 translate-x-0.5 fill-current" aria-hidden="true" />
        </span>
        <span className="absolute bottom-4 left-4 rounded-full bg-[#0b1b33]/75 px-3 py-1 text-[13px] font-medium text-white">
          {DEMO_LENGTH} · with captions
        </span>
      </button>
      <div>
        <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-ink-faint">Jump to a part</p>
        <ol className="mt-3 grid gap-0.5 sm:grid-cols-2 lg:grid-cols-1">
          {CHAPTERS.map((c) => (
            <li key={c.t}>
              <button
                type="button"
                onClick={() => play(c.t)}
                className="group flex w-full items-baseline gap-3 rounded-md px-2 py-1.5 -mx-2 text-left text-[14px] text-ink-muted transition-colors hover:bg-paper-sunk hover:text-ink"
              >
                <span className="w-9 shrink-0 tabular-nums text-[12px] text-ink-faint group-hover:text-accent">{clock(c.t)}</span>
                {c.label}
              </button>
            </li>
          ))}
        </ol>
      </div>
      {player}
    </div>
  );
}
