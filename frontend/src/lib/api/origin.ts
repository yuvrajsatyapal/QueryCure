/** The API origin the web app calls and names in its CSP. Imported by `next.config.ts` (so no
 * `@/` alias here) and by the API client.
 *
 * NEXT_PUBLIC_* values are compiled into the bundle, so a production build without one used to
 * ship `http://localhost:8000`: every call blocked by its own CSP. Production builds now fail
 * instead; only development keeps the local default. */
export const DEV_API_ORIGIN = "http://localhost:8000";

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function resolveApiOrigin(
  value: string | undefined,
  { production }: { production: boolean },
): string {
  const raw = value?.trim() ?? "";
  if (!raw) {
    if (production) {
      throw new Error(
        "NEXT_PUBLIC_API_BASE_URL is required for a production build (the API's public origin, e.g. https://api.example.dev).",
      );
    }
    return DEV_API_ORIGIN;
  }
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`NEXT_PUBLIC_API_BASE_URL must be an absolute origin, got ${JSON.stringify(raw)}.`);
  }
  const bare = url.pathname === "/" && !url.search && !url.hash && !url.username && !url.password;
  if ((url.protocol !== "https:" && url.protocol !== "http:") || !bare) {
    throw new Error(`NEXT_PUBLIC_API_BASE_URL must be a bare http(s) origin, got ${JSON.stringify(raw)}.`);
  }
  if (production && url.protocol !== "https:" && !LOOPBACK.has(url.hostname)) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL must use https outside loopback in a production build.");
  }
  return url.origin;
}
