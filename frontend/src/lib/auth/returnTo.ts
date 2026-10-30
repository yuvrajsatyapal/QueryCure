export const DEFAULT_RETURN_TO = "/app";
export const SIGN_IN_PATH = "/sign-in";

// The API's login route accepts at most 300 characters of `return_to` and re-validates it.
const MAX_LENGTH = 300;
const ORIGIN = "https://querycure.invalid";

/** A same-site path to return to after sign-in, or the dashboard. Defense in depth: the API
 * applies its own same-site check before redirecting. Control characters and whitespace are
 * refused because browsers strip them, turning "/\t/host" into the off-site "//host". */
export function safeReturnTo(value: string | null | undefined): string {
  if (!value || value.length > MAX_LENGTH) return DEFAULT_RETURN_TO;
  if (!value.startsWith("/") || value.startsWith("//") || /[\\\s\u0000-\u001f\u007f]/.test(value)) return DEFAULT_RETURN_TO;
  let url: URL;
  try {
    url = new URL(value, ORIGIN);
  } catch {
    return DEFAULT_RETURN_TO;
  }
  if (url.origin !== ORIGIN) return DEFAULT_RETURN_TO;
  if (url.pathname === SIGN_IN_PATH || url.pathname.startsWith(`${SIGN_IN_PATH}/`)) return DEFAULT_RETURN_TO;
  return value;
}

/** The sign-in page, returning to `current` afterwards (the dashboard needs no parameter), with the
 * reason a previous attempt failed when there is one. */
export function signInHref(current: string, authError?: string | null): string {
  const next = safeReturnTo(current);
  const params = [next === DEFAULT_RETURN_TO ? null : `next=${encodeURIComponent(next)}`, authError ? `auth_error=${encodeURIComponent(authError)}` : null];
  const query = params.filter(Boolean).join("&");
  return query ? `${SIGN_IN_PATH}?${query}` : SIGN_IN_PATH;
}

// The API sends a failed sign-in to `/app?auth_error=` without the destination, so the sign-in page
// keeps it for this tab. Every attempt overwrites it, so it always belongs to the latest one.
export const PENDING_RETURN_KEY = "qc.signIn.returnTo";

export function rememberReturnTo(path: string): void {
  try {
    sessionStorage.setItem(PENDING_RETURN_KEY, safeReturnTo(path));
  } catch {
    // Storage blocked (private window, site data off): a failed sign-in then returns to the dashboard.
  }
}

export function rememberedReturnTo(): string {
  try {
    return safeReturnTo(sessionStorage.getItem(PENDING_RETURN_KEY));
  } catch {
    return DEFAULT_RETURN_TO;
  }
}
