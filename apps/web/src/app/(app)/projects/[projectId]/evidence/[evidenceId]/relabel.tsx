"use client";

import { useState, useTransition } from "react";
import { Select } from "@/components/ui";
import type { Sensitivity } from "@/lib/types";
import { relabelEvidence } from "../actions";

export function Relabel({ projectId, evidenceId, value }: { projectId: string; evidenceId: string; value: Sensitivity }) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return (
    <div>
      <label htmlFor="relabel" className="text-[13px] text-ink-muted block mb-1">
        Change label
      </label>
      <Select
        id="relabel"
        defaultValue={value}
        disabled={pending}
        onChange={(e) => {
          const next = e.target.value as Sensitivity;
          if (next === "confidential" && !confirm("Mark as confidential? Only people with a confidential clearance will see it, and claims citing it will be withheld from everyone else.")) {
            e.target.value = value;
            return;
          }
          start(async () => setError(await relabelEvidence(projectId, evidenceId, next)));
        }}
        className="max-w-48"
      >
        <option value="team">Team</option>
        <option value="restricted">Restricted</option>
        <option value="confidential">Confidential</option>
      </Select>
      {error && <p className="text-[12px] text-danger mt-1">{error}</p>}
    </div>
  );
}
