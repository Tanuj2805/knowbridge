import { ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { Card, CardHeader, PageHeader, Progress, Stat, StatStrip, buttonClass, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import type { EvidenceStats, ProjectSummary } from "@/lib/types";
import { SmartSearchStatus } from "./build-search";

const STEPS = 5;

type StepProps = {
  n: number;
  title: string;
  done: boolean;
  current: boolean;
  children: React.ReactNode;
  action?: React.ReactNode;
};

function Step({ n, title, done, current, children, action }: StepProps) {
  return (
    <li className={cx("grid grid-cols-[2.5rem_1fr] gap-4 border-b border-rule py-5 last:border-b-0", current && "")}>
      <span
        className={cx(
          "relative inline-flex size-8 items-center justify-center rounded-full tabular-nums text-[13px]",
          done ? "bg-accent text-on-accent" : current ? "text-accent ring-[1.5px] ring-accent" : "text-ink-faint ring-1 ring-rule-strong",
        )}
        aria-label={done ? "Done" : current ? `Step ${n}, up next` : `Step ${n}`}
      >
        {current && (
          <span aria-hidden="true" className="absolute inset-0 rounded-full ring-[1.5px] ring-accent motion-safe:animate-ping-soft" />
        )}
        {done ? <Check className="size-4" strokeWidth={2.5} /> : n}
      </span>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="max-w-xl">
          <p className={cx("text-[16px] font-medium", done || current ? "text-ink" : "text-ink-muted")}>{title}</p>
          <div className="mt-1 text-[14px] leading-relaxed text-ink-muted">{children}</div>
        </div>
        {action}
      </div>
    </li>
  );
}

function StepLink({ href, children, primary }: { href: string; children: React.ReactNode; primary?: boolean }) {
  return (
    <Link href={href} className={cx(buttonClass(primary ? "primary" : "secondary", "sm"), "group")}>
      {children}
      <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
    </Link>
  );
}

export default async function ProjectOverview({ params }: PageProps<"/projects/[projectId]">) {
  const { projectId } = await params;
  const p = await api<ProjectSummary>(`/projects/${projectId}`);
  const base = `/projects/${projectId}`;
  const admin = p.my_roles.includes("admin");
  const staff = admin || p.my_roles.includes("approver");
  const stats = staff && p.evidence_count > 0 ? await api<EvidenceStats>(`/projects/${projectId}/evidence/stats`) : null;

  const done = [p.member_count > 1, p.source_count > 0, p.claim_count > 0, p.interviewed_count > 0, p.published_count > 0];
  const next = done.indexOf(false);
  const count = done.filter(Boolean).length;

  return (
    <div>
      <PageHeader
        title="Overview"
        actions={
          <Link href={`${base}/${staff ? "ledger" : "handovers"}`} className={buttonClass("primary")}>
            {staff ? "Open the claim ledger" : "Open handovers"}
          </Link>
        }
      >
        {p.description || "No description yet."}
      </PageHeader>

      <StatStrip>
        <Stat label="People" value={p.member_count} href={`${base}/members`} />
        <Stat label="Sources" value={p.source_count} href={staff ? `${base}/sources` : undefined} />
        <Stat
          label="Evidence items"
          value={p.evidence_count.toLocaleString("en-IN")}
          href={staff ? `${base}/evidence` : undefined}
        />
        <Stat
          label="Claims"
          value={p.claim_count.toLocaleString("en-IN")}
          hint={p.claim_count ? "from the latest run" : "not built yet"}
          href={staff ? `${base}/ledger` : undefined}
        />
      </StatStrip>

      <div className="mt-12 grid gap-12 lg:grid-cols-[1fr_20rem] lg:gap-16">
        <Card>
          <CardHeader
            title="Getting to a handover"
            action={<span className="tabular-nums text-[13px]  text-ink-muted">{count}/{STEPS}</span>}
          >
            Five steps from scattered notes to a pack your successor can check.
          </CardHeader>
          <div className="mt-4">
            <Progress value={count / STEPS} label="Steps done" />
          </div>
          <ol className="mt-2">
            <Step
              n={1}
              title="Add the people involved"
              done={done[0]}
              current={next === 0}
              action={next === 0 && <StepLink href={`${base}/members`} primary>Add people</StepLink>}
            >
              Who is leaving, who is taking over, and who signs off.
            </Step>
            <Step
              n={2}
              title="Connect what the team already wrote"
              done={done[1]}
              current={next === 1}
              action={staff && next === 1 && <StepLink href={`${base}/sources`} primary>Connect sources</StepLink>}
            >
              The repository, meeting notes, task board and chat exports. Read-only, and secrets are masked on the way
              in.
            </Step>
            <Step
              n={3}
              title="Rebuild the project's state"
              done={done[2]}
              current={next === 2}
              action={
                staff && (
                  <StepLink href={`${base}/ledger`} primary={next === 2}>
                    {p.claim_count > 0 ? `See ${plural(p.claim_count, "claim")}` : "Build claims"}
                  </StepLink>
                )
              }
            >
              Agents pull out decisions, owners, risks and open questions, and a separate checker grades each one
              against its source.
            </Step>
            <Step
              n={4}
              title="Ask the leaver only what's missing"
              done={done[3]}
              current={next === 3}
              action={
                <StepLink href={`${base}/handovers`} primary={next === 3}>
                  {p.handover_count > 0 ? "Open handovers" : "Start a handover"}
                </StepLink>
              }
            >
              About ten questions, not a twenty-page document.
            </Step>
            <Step n={5} title="Review, approve, hand over" done={done[4]} current={next === 4}>
              Nothing reaches the successor until the approver signs off.
              {p.published_count > 0 && ` ${plural(p.published_count, "pack")} published so far.`}
            </Step>
          </ol>
        </Card>

        <div className="grid content-start gap-12">
          {stats && (
            <Card as="aside">
              <CardHeader title="Privacy">What Sentinel did with this project&apos;s material.</CardHeader>
              <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4">
                {(
                  [
                    ["Secrets masked", stats.masked_secrets],
                    ["Personal details masked", stats.masked_pii],
                    ["Restricted items", stats.by_sensitivity.restricted ?? 0],
                    ["Confidential items", stats.by_sensitivity.confidential ?? 0],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <dd className="font-display text-[1.5rem] leading-none tabular-nums text-ink">{v}</dd>
                    <dt className="mt-1 text-[12px] text-ink-faint">{k}</dt>
                  </div>
                ))}
              </dl>
              <div className="mt-5 grid gap-2 border-t border-rule pt-4 text-[13px] leading-relaxed text-ink-muted">
                {stats.hidden > 0 && <p>{plural(stats.hidden, "item")} outside your access.</p>}
                <SmartSearchStatus
                  projectId={projectId}
                  ready={stats.embedded}
                  total={stats.visible}
                  model={stats.search_model}
                  admin={admin}
                  external={stats.search_external}
                  keptPrivate={stats.kept_private}
                />
                {stats.by_language["hi-en"] ? <p>{plural(stats.by_language["hi-en"], "Hinglish message")}.</p> : null}
              </div>
            </Card>
          )}
          {admin && (
            <Card as="aside">
              <CardHeader title="Team">
                {plural(p.member_count, "person", "people")} on this project. Add the leaver, the successor and an
                approver.
              </CardHeader>
              <Link href={`${base}/members`} className={cx(buttonClass("secondary", "sm"), "mt-4")}>
                Manage people
              </Link>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
