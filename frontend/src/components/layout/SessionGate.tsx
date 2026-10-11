"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { ErrorNotice } from "@/components/common/ErrorNotice";
import { ApiError } from "@/lib/api/client";
import { createSession, getMe } from "@/lib/api/session";

/** Ensures a session exists (local user or anonymous demo user) before rendering the app. */
export function SessionGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: ({ signal }) => getMe(signal), retry: false });
  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (!unauthenticated) return;
    createSession()
      .then(() => queryClient.invalidateQueries({ queryKey: ["me"] }))
      .catch(() => undefined);
  }, [unauthenticated, queryClient]);

  if (me.isSuccess) return <>{children}</>;
  if (me.isError && !unauthenticated) {
    return (
      <div className="max-w-xl">
        <ErrorNotice error={me.error} />
        <p className="mt-2 text-sm text-muted">Is the API running? See the README for local setup.</p>
      </div>
    );
  }
  return <p className="text-muted">Starting session…</p>;
}
