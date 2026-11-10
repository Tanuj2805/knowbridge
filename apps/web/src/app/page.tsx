import { ArrowRight, Check } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { auth } from "@/auth";
import { DEMO_LENGTH, DemoVideoSection, WatchVideoButton } from "@/components/demo-video";
import { GridBackground } from "@/components/grid-background";
import { ThemeToggle } from "@/components/theme-toggle";
import { TypedTitle } from "@/components/typed-title";
import { Wordmark, buttonClass, cx } from "@/components/ui";
import { GRADE_LABEL, type Grade } from "@/lib/types";

export const metadata: Metadata = {
  title: { absolute: "KnowBridge · Handover documents your successor can check" },
};

const STEPS = [
  ["Connect", "GitHub, Jira, meeting notes, task boards and chat exports. Read-only; secrets are masked before anything is stored."],
  ["Rebuild", "Agents pull out decisions, owners, dependencies and risks, each as a claim with the exact words it came from."],
  ["Ask", "Where sources disagree or nobody answered, the person leaving gets about ten short questions."],
  ["Hand over", "An approver checks the claims. The successor gets a pack and a 30-day plan, every line linked to its source."],
];

const AGENTS = [
  ["Sentinel", "Masks secrets and personal details, and labels sensitive items, before anything is stored."],
  ["Scout", "Decides which specialist reads each thread, chat day, document and meeting."],
  ["Decision Miner", "Finds what was decided, when, by whom, and why."],
  ["Ownership Mapper", "Works out who owns what, what depends on what, and who to ask."],
  ["Risk Detector", "Spots risks, blockers, repeat problems and questions nobody answered."],
  ["Timeline Builder", "Merges duplicates, and links what changed over time and what disagrees."],
  ["Skeptic", "Re-reads every claim's own evidence and grades it; removes what nothing backs."],
  ["Gap Interviewer", "Turns what's unclear into short questions for the person leaving."],
  ["Composer", "Writes the handover pack and a 30-day plan from approved claims only."],
];

const GRADES: Grade[] = ["verified", "supported", "attested", "inferred", "conflicting", "missing"];

const TRUST = [
  ["Secrets never stored", "Tokens, keys and personal details are masked on the way in. The original values are never kept."],
  ["Confidential stays local", "Items marked confidential are never sent to a model, and only people cleared for them see them."],
  ["A person signs off", "Nothing reaches the successor until an approver has reviewed every claim in the pack."],
  ["Everything on record", "Every view, approval, edit and export goes into an audit log that can't be changed from the app."],
];

/** A short list of what the agents found, as it looks in the claim ledger. */
const SAMPLE_CLAIMS: { grade: Grade; type: string; text: string; quote: string; where: string }[] = [
  {
    grade: "verified",
    type: "Decision",
    text: "Payment test mode was dropped on 14 Oct because webhooks kept failing on the campus network.",
    quote: "webhooks keep timing out on the hostel wifi, switching to polling",
    where: "PR 38 review · Dev Patel",
  },
  {
    grade: "conflicting",
    type: "Dependency",
    text: "Early-bird tickets end on 15 Dec (Trello) or 31 Dec (meeting notes).",
    quote: "early bird closes 31st, not the 15th",
    where: "Weekly sync, 27 Sep · Kabir Singh",
  },
  {
    grade: "attested",
    type: "Owner",
    text: "Aarav holds the only GoDaddy login for nimbusfest.in, which renews on 2 December.",
    quote: "It's on my personal account. I'll move it before I leave.",
    where: "Gap Interview · Aarav Mehta",
  },
];

export default async function Home() {
  const session = await auth();
  const signedIn = !!session?.user;
  const primary = signedIn ? { href: "/dashboard", label: "Open your dashboard" } : { href: "/signin", label: "Open the demo" };

  return (
    <div className="flex flex-1 flex-col">
      <header className="fixed inset-x-0 top-0 z-30 border-b border-rule/60 bg-paper/75 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-[80rem] items-center gap-6 px-4 sm:px-6">
          <Link href="/" className="rounded-md">
            <Wordmark />
          </Link>
          <nav aria-label="Sections" className="hidden items-center md:flex">
            {[
              ["#video", "Watch video"],
              ["#product", "Product"],
              ["#how", "How it works"],
              ["#agents", "Agents"],
              ["#trust", "Trust"],
            ].map(([href, label]) => (
              <a key={href} href={href} className="group relative px-3 py-2 text-[14px] text-ink-muted transition-colors hover:text-ink">
                {label}
                <span
                  aria-hidden="true"
                  className="absolute inset-x-3 bottom-1 h-px origin-left scale-x-0 bg-ink transition-transform duration-200 ease-out group-hover:scale-x-100"
                />
              </a>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <ThemeToggle />
            {signedIn ? (
              <Link href="/dashboard" className={buttonClass("primary")}>
                Dashboard
              </Link>
            ) : (
              <>
                <Link href="/signin" className={cx(buttonClass("quiet"), "hidden sm:inline-flex")}>
                  Sign in
                </Link>
                <Link href="/signin" className={buttonClass("primary")}>
                  Open the demo
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">
        {/* --- hero: the name, large, over the moving grid ------------------------- */}
        <section className="relative flex min-h-[100svh] items-center overflow-hidden pt-16">
          <GridBackground />
          <div className="relative mx-auto w-full max-w-[80rem] px-4 py-20 text-center sm:px-6">
            <p className="inline-flex animate-rise items-center gap-2.5 rounded-full border border-accent/20 bg-paper-raised/80 px-4 py-2 text-[14px] font-semibold text-accent shadow-card backdrop-blur">
              <span aria-hidden="true" className="relative flex size-2">
                <span className="absolute inset-0 rounded-full bg-accent motion-safe:animate-ping-soft" />
                <span className="relative size-2 rounded-full bg-accent" />
              </span>
              <span>
                Evidence-linked handovers<span className="hidden sm:inline">, built by nine agents</span>
              </span>
            </p>
            <TypedTitle className="mx-auto mt-8 max-w-5xl text-[clamp(2.7rem,7.2vw,5.6rem)] font-extrabold leading-[1.04] tracking-[-0.045em] [word-spacing:0.08em] text-ink" />
            <p className="mx-auto mt-8 max-w-3xl animate-rise text-[clamp(1.05rem,1.7vw,1.4rem)] leading-relaxed text-ink-faint [word-spacing:0.04em] [animation-delay:120ms]">
              When someone leaves, their successor gets a handover with{" "}
              <strong className="font-semibold text-ink-muted">every line linked to its source</strong>,{" "}
              <strong className="font-semibold text-ink-muted">gaps asked, not guessed</strong>, and{" "}
              <strong className="font-semibold text-ink-muted">nothing shared until a person approves</strong>.
            </p>
            <div className="mt-10 flex animate-rise flex-col justify-center gap-3 [animation-delay:180ms] sm:flex-row">
              <Link href={primary.href} className={cx(buttonClass("primary"), "group h-12 px-6 text-[15px]")}>
                {primary.label}
                <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </Link>
              <WatchVideoButton className="h-12 bg-paper/70 px-5 text-[15px] backdrop-blur" />
            </div>
            <ul className="mt-10 flex animate-rise flex-wrap justify-center gap-x-7 gap-y-2 text-[13px] text-ink-muted [animation-delay:240ms]">
              {["Nine agents, one job each", "Every claim cited", "Nothing shared until a person approves"].map((t) => (
                <li key={t} className="flex items-center gap-1.5">
                  <Check className="size-4 text-accent" aria-hidden="true" />
                  {t}
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* --- the walkthrough video ------------------------------------------------ */}
        <section id="video" className="scroll-mt-16 border-t border-rule bg-paper-raised">
          <div className="mx-auto max-w-[80rem] px-4 py-24 sm:px-6">
            <div className="mb-10 max-w-2xl">
              <h2 className="font-display text-[clamp(2rem,3.6vw,3rem)] leading-[1.05] tracking-[-0.04em] text-ink">
                See it work, start to finish.
              </h2>
              <p className="mt-4 text-[16px] leading-relaxed text-ink-muted">
                A {DEMO_LENGTH} walkthrough in plain English: create a project, connect GitHub, Jira and chats, let the
                agents build the claims, run the Gap Interview, publish the handover, and ask the chat.
              </p>
            </div>
            <DemoVideoSection />
          </div>
        </section>

        {/* --- the product, as it really looks ------------------------------------ */}
        <section id="product" className="scroll-mt-16 border-t border-rule">
          <div className="mx-auto max-w-[80rem] px-4 py-24 sm:px-6">
            <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr] lg:gap-16">
              <div>
                <h2 className="font-display text-[clamp(2rem,3.6vw,3rem)] leading-[1.05] tracking-[-0.04em] text-ink">
                  A ledger of what the team knows, with the receipts.
                </h2>
                <p className="mt-5 max-w-md text-[16px] leading-relaxed text-ink-muted">
                  Each claim carries the quote it rests on and a grade from the Skeptic. Where two sources disagree,
                  you see both, side by side, until someone settles it.
                </p>
              </div>
              <AppFrame />
            </div>
          </div>
        </section>

        {/* --- how it works -------------------------------------------------------- */}
        <section id="how" className="scroll-mt-16 border-t border-rule bg-paper-raised">
          <div className="mx-auto max-w-[80rem] px-4 py-24 sm:px-6">
            <h2 className="max-w-2xl font-display text-[clamp(2rem,3.6vw,3rem)] leading-[1.05] tracking-[-0.04em] text-ink">
              From scattered notes to a checked handover in four steps.
            </h2>
            <ol className="mt-14 grid gap-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-8">
              {STEPS.map(([title, body], i) => (
                <li key={title} className="border-t border-ink pt-5">
                  <p className="tabular-nums text-[13px] text-accent">0{i + 1}</p>
                  <h3 className="mt-3 font-display text-[1.5rem] tracking-[-0.03em] text-ink">{title}</h3>
                  <p className="mt-2 text-[15px] leading-relaxed text-ink-muted">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* --- agents and grades --------------------------------------------------- */}
        <section id="agents" className="scroll-mt-16 border-t border-rule">
          <div className="mx-auto grid max-w-[80rem] gap-16 px-4 py-24 sm:px-6 lg:grid-cols-[1.3fr_1fr]">
            <div>
              <h2 className="font-display text-[clamp(2rem,3.6vw,3rem)] leading-[1.05] tracking-[-0.04em] text-ink">
                Nine agents, each doing one job.
              </h2>
              <dl className="mt-10 border-t border-ink">
                {AGENTS.map(([name, job], i) => (
                  <div key={name} className="grid gap-1 border-b border-rule py-4 sm:grid-cols-[2.5rem_11rem_1fr] sm:gap-4">
                    <span className="tabular-nums text-[12px] text-ink-faint">{String(i + 1).padStart(2, "0")}</span>
                    <dt className="text-[15px] font-medium text-ink">{name}</dt>
                    <dd className="text-[14px] leading-relaxed text-ink-muted">{job}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div id="grades" className="scroll-mt-16">
              <h2 className="font-display text-[clamp(2rem,3.6vw,3rem)] leading-[1.05] tracking-[-0.04em] text-ink">
                Six grades of trust.
              </h2>
              <p className="mt-4 text-[15px] leading-relaxed text-ink-muted">
                The Skeptic grades every claim, so a successor knows what two sources agree on and what only one
                person said.
              </p>
              <ul className="mt-8 border-t border-ink">
                {GRADES.map((g) => (
                  <li key={g} className="border-b border-rule py-4">
                    <p className="flex items-center gap-2 text-[15px] font-medium" style={{ color: `var(--grade-${g})` }}>
                      <span aria-hidden="true" className="size-2 rounded-full bg-current" />
                      {GRADE_LABEL[g][0]}
                    </p>
                    <p className="mt-1 pl-4 text-[14px] leading-relaxed text-ink-muted">{GRADE_LABEL[g][1]}</p>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* --- trust --------------------------------------------------------------- */}
        <section id="trust" className="scroll-mt-16 border-t border-rule bg-paper-raised">
          <div className="mx-auto max-w-[80rem] px-4 py-24 sm:px-6">
            <h2 className="max-w-2xl font-display text-[clamp(2rem,3.6vw,3rem)] leading-[1.05] tracking-[-0.04em] text-ink">
              Built for material you can&apos;t afford to leak.
            </h2>
            <ul className="mt-14 grid gap-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-8">
              {TRUST.map(([title, body]) => (
                <li key={title} className="border-t border-ink pt-5">
                  <h3 className="text-[16px] font-medium text-ink">{title}</h3>
                  <p className="mt-2 text-[15px] leading-relaxed text-ink-muted">{body}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* --- close ------------------------------------------------------------- */}
        <section className="relative overflow-hidden border-t border-rule">
          <GridBackground density={0.7} />
          <div className="relative mx-auto max-w-[80rem] px-4 py-28 text-center sm:px-6">
            <h2 className="font-display text-[clamp(2.4rem,6vw,4.8rem)] leading-[1] tracking-[-0.05em] text-ink">
              Someone leaving soon?
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-[16px] leading-relaxed text-ink-muted">
              Walk through a whole handover in the Project Nimbus demo, from sources to the successor&apos;s 30-day plan.
            </p>
            <Link href={primary.href} className={cx(buttonClass("primary"), "group mt-9 h-12 px-6 text-[15px]")}>
              {primary.label}
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-[80rem] flex-col gap-3 px-4 py-8 text-[13px] text-ink-faint sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <Wordmark />
          <p>Handover documents your successor can check, line by line.</p>
        </div>
      </footer>
    </div>
  );
}

/** The claim ledger in one browser frame: live HTML, not a picture. */
function AppFrame() {
  return (
    <div className="overflow-hidden rounded-xl border border-rule bg-paper shadow-lift">
      <div className="flex items-center gap-4 border-b border-rule bg-paper-raised px-4 py-2.5">
        <Wordmark compact />
        <div className="flex gap-4 text-[12px] text-ink-muted">
          <span>Overview</span>
          <span>Evidence</span>
          <span className="relative font-medium text-ink">
            Claim ledger
            <span className="absolute -bottom-[11px] left-0 right-0 h-[2px] bg-accent" />
          </span>
          <span className="hidden sm:inline">Handovers</span>
        </div>
        <span className="ml-auto hidden tabular-nums text-[11px] text-ink-faint sm:inline">113 claims</span>
      </div>
      <div className="grid gap-px bg-rule sm:grid-cols-[11rem_1fr]">
        <div className="hidden bg-paper p-4 text-[12px] sm:block">
          <p className="text-ink-faint">Claim types</p>
          <ul className="mt-2 grid gap-1.5">
            {[
              ["Decisions", 38],
              ["Owners", 34],
              ["Risks", 13],
              ["Dependencies", 9],
              ["Blockers", 8],
            ].map(([k, v], i) => (
              <li key={k} className={cx("flex justify-between", i === 0 ? "font-medium text-ink" : "text-ink-muted")}>
                {k}
                <span className="tabular-nums text-ink-faint">{v}</span>
              </li>
            ))}
          </ul>
          <p className="mt-5 text-ink-faint">Approved</p>
          <div className="mt-2 h-1 rounded-full bg-paper-sunk">
            <div className="h-full w-2/3 rounded-full bg-accent" />
          </div>
        </div>
        <ul className="divide-y divide-rule bg-paper">
          {SAMPLE_CLAIMS.map((c) => (
            <li key={c.text} className="px-4 py-3.5">
              <p className="flex items-center gap-3 text-[11px]">
                <span className="uppercase tracking-wider text-ink-faint">{c.type}</span>
                <span className="flex items-center gap-1.5 font-medium" style={{ color: `var(--grade-${c.grade})` }}>
                  <span className="size-1.5 rounded-full bg-current" />
                  {GRADE_LABEL[c.grade][0]}
                </span>
              </p>
              <p className="mt-1.5 text-[14px] font-medium leading-snug text-ink">{c.text}</p>
              <p className="mt-2 border-l-2 border-accent/50 pl-2.5 text-[12px] text-ink-muted">“{c.quote}”</p>
              <p className="mt-1 pl-3 text-[11px] text-ink-faint">{c.where}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
