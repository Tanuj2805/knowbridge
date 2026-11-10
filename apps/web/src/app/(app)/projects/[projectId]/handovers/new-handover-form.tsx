"use client";

import { useActionState } from "react";
import { SubmitButton } from "@/components/submit-button";
import { ErrorNote, Input, Label, RequiredNote, Select } from "@/components/ui";
import type { Member, Role } from "@/lib/types";
import { createHandover } from "./actions";

function PersonSelect({ name, label, hint, members, prefer }: {
  name: string;
  label: string;
  hint: string;
  members: Member[];
  prefer: Role;
}) {
  const first = members.find((m) => m.roles.includes(prefer));
  return (
    <div>
      <Label htmlFor={name} hint={hint} required>
        {label}
      </Label>
      <Select id={name} name={name} required defaultValue={first?.user.id ?? ""}>
        <option value="" disabled>
          Choose someone
        </option>
        {members.map((m) => (
          <option key={m.user.id} value={m.user.id}>
            {m.user.name}
          </option>
        ))}
      </Select>
    </div>
  );
}

export function NewHandoverForm({ projectId, members }: { projectId: string; members: Member[] }) {
  const [state, action] = useActionState(createHandover.bind(null, projectId), undefined);
  return (
    <form action={action} className="grid gap-4">
      <RequiredNote />
      <div className="grid gap-4 sm:grid-cols-3">
        <PersonSelect name="leaver_id" label="Leaving" hint="Answers the Gap Interview" members={members} prefer="leaver" />
        <PersonSelect name="successor_id" label="Taking over" hint="Receives the handover" members={members} prefer="successor" />
        <PersonSelect name="approver_id" label="Approves" hint="Reviews before anything is shared" members={members} prefer="approver" />
      </div>
      <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
        <div>
          <Label htmlFor="leaver_last_day" hint="Optional">
            Last day
          </Label>
          <Input id="leaver_last_day" name="leaver_last_day" type="date" />
        </div>
        <div>
          <Label htmlFor="title" hint="Optional; we'll name it after the two people">
            Name
          </Label>
          <Input id="title" name="title" placeholder="e.g. Backend handover" />
        </div>
      </div>
      {state?.error && <ErrorNote>{state.error}</ErrorNote>}
      <div>
        <SubmitButton pendingText="Starting…">Start the handover</SubmitButton>
      </div>
    </form>
  );
}
