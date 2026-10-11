import { ApiError } from "@/lib/api/client";

/** Shows the backend's envelope message and field details (never a generic HTTP string). */
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const apiError = error instanceof ApiError ? error : null;
  const message = apiError?.message ?? "Something went wrong. Please try again.";
  return (
    <div role="alert" className="rounded-md border border-rejected/40 bg-surface-2 p-3 text-sm">
      <p className="font-medium text-rejected">{message}</p>
      {apiError?.details.map((d) => (
        <p key={`${d.field}:${d.message}`} className="mt-1 font-mono text-xs text-muted">
          {d.field ? `${d.field}: ${d.message}` : d.message}
        </p>
      ))}
      {apiError?.requestId ? (
        <p className="mt-1 font-mono text-[11px] text-muted">request {apiError.requestId}</p>
      ) : null}
    </div>
  );
}
