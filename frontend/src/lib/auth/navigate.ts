/** A full page load of the home page: it drops every in-memory query, so nothing of the signed-out
 * account survives. A separate module so tests can replace it (jsdom cannot navigate). A hard load is
 * the point here, so the router's client-side push is deliberately not used. */
export function goHome(): void {
  const home = new URL("/", window.location.origin);
  window.location.assign(home);
}
