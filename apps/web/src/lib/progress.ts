import type { ProjectSummary } from "./types";

export const STEP_COUNT = 5;

/** The five steps from an empty project to a published handover: how many are done, and what to do next. */
export function nextStep(p: ProjectSummary): { label: string; href: string; done: number } {
  const base = `/projects/${p.id}`;
  const staff = p.my_roles.some((r) => r === "admin" || r === "approver");
  const steps = [
    { ok: p.member_count > 1, label: "Add the people involved", href: `${base}/members` },
    { ok: p.source_count > 0, label: "Connect the team's sources", href: `${base}/sources` },
    { ok: p.claim_count > 0, label: "Build the claim ledger", href: `${base}/ledger` },
    { ok: p.interviewed_count > 0, label: "Run the Gap Interview", href: `${base}/handovers` },
    { ok: p.published_count > 0, label: "Review and publish the pack", href: `${base}/handovers` },
  ];
  const done = steps.filter((s) => s.ok).length;
  const next = steps.find((s) => !s.ok);
  if (!next) return { label: "Handed over", href: `${base}/handovers`, done };
  // People who aren't admins or approvers can't do the build steps themselves.
  if (!staff && done < 3) return { label: "Waiting for the project admin", href: base, done };
  return { label: next.label, href: staff ? next.href : `${base}/handovers`, done };
}
