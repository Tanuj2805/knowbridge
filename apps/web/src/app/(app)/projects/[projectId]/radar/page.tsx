import { ArrowRight, Radar as RadarIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { EmptyState, PageHeader, Stat, StatStrip, Tag, buttonClass, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { CAPTURE_STATUS_LABEL, type Radar, type RadarArea, type RadarSignal } from "@/lib/types";
import { Working } from "@/components/agent-pipeline";
import { AutoRefresh } from "@/components/auto-refresh";
import { CaptureButton } from "./capture-button";
import { RegroupButton } from "./regroup-button";

export const metadata: Metadata = { title: "Risk radar" };

const RISK_LABEL = { high: "High risk", medium: "Medium risk", low: "Shared" } as const;
const RISK_TONE = { high: "danger", medium: "warning", low: "neutral" } as const;
const SIGNAL_WORDS: Record<RadarSignal, [string, string]> = {
  ownership: ["ownership claim", "ownership claims"],
  tickets: ["ticket assigned", "tickets assigned"],
  code: ["commit", "commits"],
  talk: ["message or note", "messages and notes"],
};
const pct = (x: number) => `${Math.round(x * 100)}%`;

function signalText(signals: RadarArea["signals"]) {
  return (Object.keys(SIGNAL_WORDS) as RadarSignal[])
    .filter((k) => (signals[k] ?? 0) > 0)
    .map((k) => `${signals[k]} ${signals[k] === 1 ? SIGNAL_WORDS[k][0] : SIGNAL_WORDS[k][1]}`)
    .join(" · ");
}

export default async function RadarPage({ params }: PageProps<"/projects/[projectId]/radar">) {
  const { projectId } = await params;
  const radar = await api<Radar>(`/projects/${projectId}/radar`);
  const risky = radar.areas.filter((a) => a.risk !== "low");
  const shared = radar.areas.filter((a) => a.risk === "low");
  const high = risky.filter((a) => a.risk === "high").length;

  return (
    <div>
      <AutoRefresh active={radar.grouping} every={3000} />
      <PageHeader
        title="Risk radar"
        actions={radar.claims_ready && !radar.grouping ? <RegroupButton projectId={projectId} /> : undefined}
      >
        Which parts of the project depend on one person, found before anyone leaves. AI only groups the claims into
        parts of the project; the shares are counted in code from the claim ledger: who is named as owner, who is
        assigned the tickets, who changed the code and who explains it in chat. Only what you may see is counted.
      </PageHeader>

      {radar.grouping ? (
        <div className="border-y border-rule py-14 text-[14px]">
          <Working>
            Grouping this project&apos;s claims into areas, like features, systems and outside services. Usually under
            a minute; this page updates by itself.
          </Working>
        </div>
      ) : !radar.claims_ready ? (
        <EmptyState
          title="Build claims first"
          icon={<RadarIcon className="size-6" aria-hidden="true" />}
          action={
            <Link href={`/projects/${projectId}/ledger`} className={buttonClass("primary")}>
              Open the claim ledger
            </Link>
          }
        >
          The radar reads the claim ledger, so it needs a finished &ldquo;Build claims&rdquo; run.
        </EmptyState>
      ) : radar.areas.length === 0 ? (
        <EmptyState title="Not enough to go on yet" icon={<RadarIcon className="size-6" aria-hidden="true" />}>
          No part of the project has enough ownership, ticket, code or chat evidence to judge yet.
        </EmptyState>
      ) : (
        <>
          <StatStrip label="Knowledge risk at a glance">
            <Stat label="High risk" value={high} hint="one person, no backup" />
            <Stat label="Medium risk" value={risky.length - high} hint="one person holds most of it" />
            <Stat label="Shared" value={shared.length} hint="more than one person knows it" />
            <Stat
              label="People to talk to first"
              value={radar.people.filter((p) => p.high > 0).length}
              hint="sole holders of a high-risk area"
            />
          </StatStrip>

          {radar.people.length > 0 && <People radar={radar} />}
          {risky.length > 0 && <KnowledgeMap areas={risky} />}

          <section aria-label="Ranked risks" className="mt-14">
            <div className="border-t border-ink/80 pt-4">
              <h2 className="font-display text-[1.2rem] text-ink">Ranked risks</h2>
              <p className="mt-1 max-w-2xl text-[14px] text-ink-muted">
                Most urgent first: one person and no backup, then whoever is already leaving, then the areas the
                most claims depend on. A knowledge capture asks that person a few questions now and puts the answers
                in the ledger.
              </p>
            </div>
            <ol className="stagger mt-2">
              {risky.map((a, i) => (
                <AreaRow key={a.key} area={a} rank={i + 1} projectId={projectId} />
              ))}
            </ol>
          </section>

          {shared.length > 0 && (
            <details className="group mt-10 border-t border-rule pt-4">
              <summary className="cursor-pointer list-none text-[14px] font-medium text-ink-muted hover:text-ink">
                <span className="mr-1.5 inline-block transition-transform group-open:rotate-90" aria-hidden="true">
                  ›
                </span>
                {plural(shared.length, "area")} where knowledge is already shared
              </summary>
              <ol className="mt-2">
                {shared.map((a) => (
                  <AreaRow key={a.key} area={a} projectId={projectId} />
                ))}
              </ol>
            </details>
          )}

          {radar.grouped_by === "words" && (
            <p className="mt-8 text-[13px] text-ink-faint">
              Areas were grouped by the words claims share, because the AI couldn&apos;t be reached. Use
              &ldquo;Regroup areas&rdquo; to try again.
            </p>
          )}
          {radar.withheld > 0 && (
            <p className="mt-8 text-[13px] text-ink-faint">
              {plural(radar.withheld, "claim")} you can&apos;t see {radar.withheld === 1 ? "was" : "were"} left out.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function People({ radar }: { radar: Radar }) {
  return (
    <section aria-label="People holding sole knowledge" className="mt-12">
      <div className="border-t border-ink/80 pt-4">
        <h2 className="font-display text-[1.2rem] text-ink">If they left tomorrow</h2>
        <p className="mt-1 text-[14px] text-ink-muted">Who the project leans on most, and what would leave with them.</p>
      </div>
      <ul className="mt-2 divide-y divide-rule border-b border-rule">
        {radar.people.map((p) => (
          <li key={p.user_id} className="grid gap-x-8 gap-y-1 py-4 sm:grid-cols-[14rem_1fr]">
            <div>
              <p className="text-[15px] font-medium text-ink">{p.name}</p>
              <p className="text-[13px] text-ink-muted">
                {[p.high && `${p.high} high`, p.medium && `${p.medium} medium`].filter(Boolean).join(" · ")}
                {p.leaving && <span className="ml-2 font-medium text-[var(--grade-missing)]">already leaving</span>}
              </p>
            </div>
            <p className="text-[14px] leading-relaxed text-ink-muted">{p.areas.join(", ")}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Areas down the side, people across the top; each square is that person's share of the area. */
function KnowledgeMap({ areas }: { areas: RadarArea[] }) {
  const people = new Map<string, { name: string; total: number }>();
  for (const a of areas)
    for (const h of a.holders) {
      const p = people.get(h.user_id) ?? { name: h.name, total: 0 };
      p.total += h.share;
      people.set(h.user_id, p);
    }
  const cols = [...people.entries()].sort((x, y) => y[1].total - x[1].total).slice(0, 8);

  return (
    <section aria-label="Knowledge map" className="mt-14">
      <div className="border-t border-ink/80 pt-4">
        <h2 className="font-display text-[1.2rem] text-ink">Knowledge map</h2>
        <p className="mt-1 max-w-2xl text-[14px] text-ink-muted">
          Each row is a part of the project; the darker the square, the more of what the project records about it
          comes from that person. A row with one dark square has a single point of failure.
        </p>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[36rem] border-collapse text-[13px]">
          <thead>
            <tr>
              <th scope="col" className="w-[30%] pb-2 text-left font-medium text-ink-faint">
                Area
              </th>
              {cols.map(([id, p]) => (
                <th key={id} scope="col" className="pb-2 text-center font-medium text-ink-muted">
                  {p.name.split(" ")[0]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {areas.map((a) => (
              <tr key={a.key} className="border-t border-rule">
                <th scope="row" className="py-1.5 pr-4 text-left font-medium text-ink">
                  <span className="flex items-center gap-2">
                    <span
                      aria-hidden="true"
                      className="size-1.5 shrink-0 rounded-full"
                      style={{ background: a.risk === "high" ? "var(--grade-missing)" : "var(--grade-conflicting)" }}
                    />
                    {a.name}
                  </span>
                </th>
                {cols.map(([id, p]) => {
                  const share = a.holders.find((h) => h.user_id === id)?.share ?? 0;
                  return (
                    <td key={id} className="p-1 text-center">
                      <span
                        title={share ? `${p.name}: ${pct(share)} of ${a.name}` : undefined}
                        aria-label={share >= 0.05 ? undefined : `${p.name}: none`}
                        className={cx(
                          "flex h-8 items-center justify-center rounded tabular-nums text-[12px]",
                          share >= 0.5 ? "font-semibold text-on-accent" : "text-ink-muted",
                        )}
                        style={{
                          background: share
                            ? `color-mix(in srgb, var(--accent) ${Math.round(12 + share * 88)}%, transparent)`
                            : "var(--paper-sunk)",
                        }}
                      >
                        {share >= 0.05 ? pct(share) : ""}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function AreaRow({ area: a, rank, projectId }: { area: RadarArea; rank?: number; projectId: string }) {
  const top = a.holders[0];
  return (
    <li className="grid gap-x-8 gap-y-3 border-b border-rule py-5 md:grid-cols-[1fr_15rem]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {rank && <span className="tabular-nums text-[12px] text-ink-faint">{String(rank).padStart(2, "0")}</span>}
          <Tag tone={RISK_TONE[a.risk]}>{RISK_LABEL[a.risk]}</Tag>
          {a.kind === "contact" && <Tag>Outside contact</Tag>}
          {a.leaving && <Tag tone="danger">{top.name.split(" ")[0]} is leaving</Tag>}
        </div>
        <p className="mt-2 font-display text-[1.3rem] leading-tight tracking-[-0.02em] text-ink">
          {a.name}: <span className="text-ink-muted">{a.summary}</span>
        </p>

        {/* who holds it, as one bar */}
        <div className="mt-3 flex h-2 w-full max-w-xl overflow-hidden rounded-full bg-paper-sunk" aria-hidden="true">
          {a.holders.map((h, i) => (
            <span
              key={h.user_id}
              style={{
                width: pct(h.share),
                background: i === 0 ? "var(--accent)" : `color-mix(in srgb, var(--ink-faint) ${70 - i * 15}%, transparent)`,
              }}
            />
          ))}
        </div>
        <p className="mt-1.5 text-[13px] text-ink-muted">
          {a.holders
            .slice(0, 4)
            .map((h) => `${h.name} ${pct(h.share)}`)
            .join(" · ")}
        </p>
        <p className="mt-2 text-[12px] text-ink-faint">
          From {signalText(a.signals)} · {plural(a.claim_count, "claim")}
          {a.subjects.length > 0 && <> · about {a.subjects.slice(0, 3).join(", ")}</>}
        </p>
      </div>
      {a.risk !== "low" && (
        <div className="flex items-start md:justify-end">
          {a.capture_id ? (
            <Link
              href={`/projects/${projectId}/handovers/${a.capture_id}`}
              className={cx(buttonClass("quiet", "sm"), "group")}
            >
              {a.capture_status === "drafting" || a.capture_status === "interviewing" || !a.capture_status
                ? "Capture in progress"
                : `Capture: ${CAPTURE_STATUS_LABEL[a.capture_status].toLowerCase()}`}
              <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
            </Link>
          ) : (
            <CaptureButton projectId={projectId} area={a.key} person={top.name} />
          )}
        </div>
      )}
    </li>
  );
}
