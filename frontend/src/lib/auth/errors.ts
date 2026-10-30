export const NOT_APPROVED = "This account is not approved for this trial. Sign in with an approved account, or ask the owner for access.";

// The codes the API's OAuth callback puts in `?auth_error=` (api/routers/auth.py, auth/oauth.py).
const AUTH_ERRORS: Record<string, string> = {
  access_denied: "Sign-in was cancelled.",
  state_missing: "The sign-in attempt expired. Please try again.",
  state_mismatch: "The sign-in response did not match this browser's request, so it was refused.",
  token_exchange_failed: "The sign-in provider did not confirm the sign-in. Please try again.",
  provider_unreachable: "The sign-in provider could not be reached. Please try again later.",
  profile_unavailable: "Your profile could not be read from the sign-in provider.",
  not_allowed: NOT_APPROVED,
};

export function authErrorMessage(code: string): string {
  return AUTH_ERRORS[code] ?? "Sign-in failed. Please try again.";
}
