"use client";

import type { ComponentProps } from "react";
import { useFormStatus } from "react-dom";
import { Button, Spinner } from "./ui";

export function SubmitButton({
  children,
  pendingText,
  ...props
}: ComponentProps<typeof Button> & { pendingText?: string }) {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending || props.disabled} aria-busy={pending} {...props}>
      {pending ? (
        <>
          <Spinner />
          {pendingText ?? "Working…"}
        </>
      ) : (
        children
      )}
    </Button>
  );
}
