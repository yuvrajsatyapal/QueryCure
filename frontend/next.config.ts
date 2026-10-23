import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { resolveApiOrigin } from "./src/lib/api/origin";

// Production security headers (SECURITY §9). The API origin is the only other origin the
// page talks to. Scripts allow 'unsafe-inline' because Next's bootstrap scripts are inline and
// nonce-based CSP is not wired yet (documented gap in SECURITY §5c); framing, plugins, base-uri
// and form targets are locked down.
//
// The API origin is validated in the build phase only: `next start` loads this file again at runtime, where the
// build-time variable may be absent, while the headers come from the build's routes manifest.
function securityHeaders(apiOrigin: string) {
  const csp = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self' ${apiOrigin}`,
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    `form-action 'self' ${apiOrigin}`,
  ].join("; ");
  return [
    { key: "Content-Security-Policy", value: csp },
    // Ignored by browsers over plain http, so local production builds are unaffected. No
    // `preload`: that is a one-way commitment for the whole registrable domain.
    { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  ];
}

export default function config(phase: string): NextConfig {
  // `next typegen` (the typecheck script) loads the config in the build phase too, only to
  // read routes; it produces no bundle, so it must not need the deployment's API origin.
  const building = phase === PHASE_PRODUCTION_BUILD && !process.argv.includes("typegen");
  const apiOrigin = resolveApiOrigin(process.env.NEXT_PUBLIC_API_BASE_URL, { production: building });
  return {
    async headers() {
      if (process.env.NODE_ENV !== "production") return [];
      return [{ source: "/:path*", headers: securityHeaders(apiOrigin) }];
    },
    cacheComponents: true,
    partialPrefetching: true,
    turbopack: {
      rules: {
        "*.css": {
          loaders: ["@tailwindcss/turbopack"],
          as: "*.css",
        },
      },
    },
  };
}
